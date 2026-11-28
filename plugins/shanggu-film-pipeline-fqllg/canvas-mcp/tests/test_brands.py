"""不同画布品牌对本地参考视频的处理。运行：python -m unittest discover -s tests

2026-11-27：七色星沅新版不用认证，本地视频节点直接能接；玄上仍要先认证。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xuanshang_canvas.core.service import BRANDS, CanvasService  # noqa: E402

DEFINITIONS = {"video-asset": {"outputs": [{"type": "video"}]}, "image-asset": {"outputs": [{"type": "image"}]}}


def _service(brand: str) -> CanvasService:
    service = CanvasService.__new__(CanvasService)
    service._brand_key = brand
    service._instance = None
    return service


def _node(node_type: str) -> dict:
    return {"id": f"{node_type}-1", "type": node_type, "ui": {"label": "测试素材"}, "data": {"status": "ready"}}


class LocalVideoTests(unittest.TestCase):
    def test_qise_accepts_local_video(self):
        node = _node("video-asset")
        problem = _service("qise")._source_problem(node, "video", {node["id"]: node}, DEFINITIONS, [])
        self.assertIsNone(problem)

    def test_xuanshang_still_requires_certification(self):
        node = _node("video-asset")
        problem = _service("xuanshang")._source_problem(node, "video", {node["id"]: node}, DEFINITIONS, [])
        self.assertIn("upload_certified_video", problem)

    def test_local_image_ok_for_both(self):
        node = _node("image-asset")
        for brand in BRANDS:
            self.assertIsNone(_service(brand)._source_problem(node, "image", {node["id"]: node}, DEFINITIONS, []))

    def test_flags(self):
        self.assertFalse(BRANDS["qise"]["needs_certification"])
        self.assertTrue(BRANDS["xuanshang"]["needs_certification"])


if __name__ == "__main__":
    unittest.main()
