"""Tests for the read-only corpus verifier."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable

from verify_corpus import DEFAULT_MANIFEST, verify_manifest


SCRIPT = Path(__file__).resolve().with_name("verify_corpus.py")


def _text_sha256(lines: list[str], start: int, end: int) -> str:
    kept = []
    for line in lines[start - 1 : end]:
        line = line.strip()
        if line and not (line.startswith("<<<PDF_PAGE:") and line.endswith(">>>")):
            kept.append(line)
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()


def _errors(result: dict) -> str:
    return "\n".join(result["errors"])


def _rooted(path: Path) -> str:
    """Return ``path`` without its drive, e.g. "\\Users\\x" or "/tmp/x"."""

    return str(path)[len(path.drive) :]


class VerifyCorpusTests(unittest.TestCase):
    def test_default_corpus_passes(self) -> None:
        result, code = verify_manifest(DEFAULT_MANIFEST)
        self.assertEqual(code, 0, _errors(result))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["stats"]["sources_checked"], 4)
        self.assertEqual(result["stats"]["sources_ok"], 4)
        self.assertEqual(result["stats"]["episodes_checked"], 24)
        self.assertEqual(result["stats"]["scenes_checked"], 451)

    def _fixture(self) -> tuple[Path, Path, dict]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # A Chinese folder name makes sure non-ASCII paths are exercised.
        root = Path(temp.name) / "语料"
        (root / "episodes").mkdir(parents=True)
        (root / "originals").mkdir()
        pdf_bytes = b"%PDF-1.4 fixture"
        (root / "originals" / "fixture.pdf").write_bytes(pdf_bytes)
        lines = ["<<<PDF_PAGE:001>>>", "  first line  ", "", " <<<PDF_PAGE:2>>> ", " second line "]
        episode_bytes = ("\n".join(lines) + "\n").encode("utf-8")
        (root / "episodes" / "episode-01.txt").write_bytes(episode_bytes)
        scene = {
            "schema_version": "1.0",
            "corpus_version": "fixture",
            "episode": 1,
            "scene_id": "E01-S001",
            "scene_order": 1,
            "scene_label": "1",
            "heading": "fixture",
            "source_file": "episode-01.txt",
            "start_line": 1,
            "end_line": len(lines),
            "text_sha256": _text_sha256(lines, 1, len(lines)),
            "previous_scene_id": None,
            "next_scene_id": None,
        }
        scene_path = root / "scene-index.jsonl"
        scene_path.write_text(json.dumps(scene, ensure_ascii=False) + "\n", encoding="utf-8")
        manifest = {
            "project": "fixture",
            "source_pdf_count": 1,
            "episode_count": 1,
            "scene_count": 1,
            "sources": [
                {
                    "file": "fixture.pdf",
                    "bytes": len(pdf_bytes),
                    "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                }
            ],
            "episodes": [
                {
                    "episode": 1,
                    "file": "episode-01.txt",
                    "bytes": len(episode_bytes),
                    "sha256": hashlib.sha256(episode_bytes).hexdigest(),
                    "lines": len(lines),
                    "scene_count": 1,
                }
            ],
            "scene_index": {
                "file": "scene-index.jsonl",
                "sha256": hashlib.sha256(scene_path.read_bytes()).hexdigest(),
            },
        }
        manifest_path = root / "corpus-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest_path, scene_path, scene

    def _outside_copy(self, source: Path) -> Path:
        """Copy ``source`` to a folder outside the fixture corpus."""

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        target = Path(temp.name) / source.name
        target.write_bytes(source.read_bytes())
        return target

    def _rewrite_manifest(self, manifest_path: Path, change: Callable[[dict], None]) -> None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        change(manifest)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def test_fixture_manifest_and_normalized_text_hash_pass(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 0, _errors(result))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["stats"]["scenes_checked"], 1)
        self.assertEqual(result["stats"]["sources_ok"], 1)

    def test_manifest_without_sources_still_checks_text(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        # Older manifests had no PDF list; a leftover source_pdf_count is ignored.
        self._rewrite_manifest(manifest_path, lambda m: m.pop("sources"))
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 0, _errors(result))
        self.assertEqual(result["stats"]["sources_checked"], 0)
        self.assertEqual(result["stats"]["scenes_ok"], 1)

    def test_bad_line_range_is_content_failure(self) -> None:
        manifest_path, scene_path, scene = self._fixture()
        scene["end_line"] = 99
        scene_path.write_text(json.dumps(scene) + "\n", encoding="utf-8")
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("行范围 1-99", _errors(result))

    def test_missing_file_is_read_failure(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        (manifest_path.parent / "episodes" / "episode-01.txt").unlink()
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("无法读取 episode", _errors(result))

    def test_wrong_episode_hash_is_content_failure(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        self._rewrite_manifest(manifest_path, lambda m: m["episodes"][0].update(sha256="0" * 64))
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("episode 'episode-01.txt'：sha256", _errors(result))

    def test_same_size_pdf_change_is_hash_failure(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        (manifest_path.parent / "originals" / "fixture.pdf").write_bytes(b"%PDF-1.4 fixturE")
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("定稿 PDF 'fixture.pdf'：sha256", _errors(result))
        self.assertNotIn("bytes", _errors(result))
        self.assertEqual(result["stats"]["sources_ok"], 0)

    def test_missing_pdf_is_read_failure(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        (manifest_path.parent / "originals" / "fixture.pdf").unlink()
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("无法读取定稿 PDF", _errors(result))

    def test_source_without_hash_is_structural_failure(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        self._rewrite_manifest(manifest_path, lambda m: m["sources"][0].pop("sha256"))
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 2)
        self.assertIn("缺少 sha256", _errors(result))

    def test_sources_must_be_a_list(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        self._rewrite_manifest(manifest_path, lambda m: m.update(sources={}))
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 2)
        self.assertIn("sources 必须是数组", _errors(result))

    def test_paths_outside_corpus_are_rejected(self) -> None:
        cases = {
            "scene_index.file": lambda scene_path, pdf_path: (
                lambda m: m["scene_index"].update(file=_rooted(self._outside_copy(scene_path)))
            ),
            "source file": lambda scene_path, pdf_path: (
                lambda m: m["sources"][0].update(file=_rooted(self._outside_copy(pdf_path)))
            ),
            "parent folder": lambda scene_path, pdf_path: (
                lambda m: m["sources"][0].update(file="../originals/fixture.pdf")
            ),
        }
        for name, make_change in cases.items():
            with self.subTest(name):
                manifest_path, scene_path, _scene = self._fixture()
                pdf_path = manifest_path.parent / "originals" / "fixture.pdf"
                self._rewrite_manifest(manifest_path, make_change(scene_path, pdf_path))
                result, code = verify_manifest(manifest_path)
                self.assertEqual(code, 2, _errors(result))
                self.assertIn("路径越界", _errors(result))

    def test_dot_file_name_is_structural_failure(self) -> None:
        for name, change in {
            "source": lambda m: m["sources"][0].update(file="."),
            "episode": lambda m: m["episodes"][0].update(file="."),
        }.items():
            with self.subTest(name):
                manifest_path, _scene_path, _scene = self._fixture()
                self._rewrite_manifest(manifest_path, change)
                result, code = verify_manifest(manifest_path)
                self.assertEqual(code, 2, _errors(result))
                self.assertIn("必须指向文件", _errors(result))

    def test_folder_prefixed_file_names_pass(self) -> None:
        manifest_path, scene_path, scene = self._fixture()
        scene["source_file"] = "episodes/episode-01.txt"
        scene_path.write_text(json.dumps(scene, ensure_ascii=False) + "\n", encoding="utf-8")

        def add_prefixes(manifest: dict) -> None:
            manifest["sources"][0]["file"] = "originals/fixture.pdf"
            manifest["episodes"][0]["file"] = "episodes/episode-01.txt"
            manifest["scene_index"]["sha256"] = hashlib.sha256(scene_path.read_bytes()).hexdigest()

        self._rewrite_manifest(manifest_path, add_prefixes)
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 0, _errors(result))
        self.assertEqual(result["stats"]["sources_ok"], 1)
        self.assertEqual(result["stats"]["scenes_ok"], 1)

    def test_link_out_of_corpus_is_rejected(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        outside = self._outside_copy(manifest_path.parent / "originals" / "fixture.pdf").parent
        link = manifest_path.parent / "originals" / "outside"
        if os.name == "nt":
            made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
            if made.returncode != 0:
                self.skipTest("cannot create a directory junction here")
        else:
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("cannot create a symlink here")
        self.addCleanup(lambda: os.rmdir(link) if os.name == "nt" else link.unlink())
        self._rewrite_manifest(manifest_path, lambda m: m["sources"][0].update(file="outside/fixture.pdf"))
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 2, _errors(result))
        self.assertIn("路径越界", _errors(result))

    def test_declared_count_mismatch_is_content_failure(self) -> None:
        for key in ("source_pdf_count", "episode_count", "scene_count"):
            with self.subTest(key):
                manifest_path, _scene_path, _scene = self._fixture()
                self._rewrite_manifest(manifest_path, lambda m: m.update({key: 2}))
                result, code = verify_manifest(manifest_path)
                self.assertEqual(code, 1, _errors(result))
                self.assertEqual(result["status"], "FAIL")
                self.assertIn(f"manifest {key} 期望 2，实际 1", _errors(result))

    def test_episode_scene_count_mismatch_is_content_failure(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        self._rewrite_manifest(manifest_path, lambda m: m["episodes"][0].update(scene_count=3))
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("scene_count 期望 3，索引实际 1", _errors(result))

    def test_read_failure_outranks_content_failure(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        (manifest_path.parent / "originals" / "fixture.pdf").unlink()
        self._rewrite_manifest(manifest_path, lambda m: m.update(scene_count=2))
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("无法读取定稿 PDF", _errors(result))
        self.assertIn("manifest scene_count 期望 2", _errors(result))

    def test_broken_index_row_skips_per_episode_counts(self) -> None:
        manifest_path, scene_path, _scene = self._fixture()
        scene_path.write_text("{not json\n", encoding="utf-8")
        self._rewrite_manifest(
            manifest_path,
            lambda m: m["scene_index"].update(sha256=hashlib.sha256(scene_path.read_bytes()).hexdigest()),
        )
        result, code = verify_manifest(manifest_path)
        self.assertEqual(code, 2)
        self.assertIn("scene-index 第 1 行无效", _errors(result))
        self.assertNotIn("索引实际", _errors(result))

    def test_piped_output_is_ascii_json(self) -> None:
        manifest_path, _scene_path, _scene = self._fixture()
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--manifest", str(manifest_path)],
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.isascii())
        result = json.loads(completed.stdout.decode("ascii"))
        self.assertEqual(result["status"], "PASS")
        self.assertIn("语料", result["manifest"])


if __name__ == "__main__":
    unittest.main()
