"""插件一致性检查。改完任何东西、发布之前运行。

用法（在仓库根目录）：
    python -B tools/check.py

全部通过时退出码为 0；有问题时逐条列出并以退出码 1 结束。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "shanggu-film-pipeline-fqllg"
MARKETPLACE_NAME = "shanggu-film"
PLUGIN = ROOT / "plugins" / PLUGIN_NAME
CANVAS = PLUGIN / "canvas-mcp"
PROMPT_SKILL = PLUGIN / "skills" / "horizontal-cinematic-prompt-agent-v2"

# 插件里应该有的 skill，少一个或多一个都报。加新 skill 时同步改这里。
EXPECTED_SKILLS = {
    "film-pipeline",
    "blender-greybox-previs",
    "horizontal-cinematic-prompt-agent-v2",
    "video-local-edit",
    "video-rephotography",
    "xuanshang-canvas",
}

LF_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".py", ".toml", ".yaml", ".yml", ".lock"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}

problems: list[str] = []


def ok(msg: str) -> None:
    print(f"  [通过] {msg}")


def fail(msg: str) -> None:
    problems.append(msg)
    print(f"  [问题] {msg}")


def files(base: Path):
    for path in base.rglob("*"):
        if path.is_file() and not SKIP_DIRS.intersection(path.relative_to(ROOT).parts):
            yield path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_manifests() -> None:
    print("1. 安装文件和版本号")
    claude_mp = load(ROOT / ".claude-plugin" / "marketplace.json")
    codex_mp = load(ROOT / ".agents" / "plugins" / "marketplace.json")
    claude_pj = load(PLUGIN / ".claude-plugin" / "plugin.json")
    codex_pj = load(PLUGIN / ".codex-plugin" / "plugin.json")

    for label, data in (("Claude 插件市场", claude_mp), ("Codex 插件市场", codex_mp)):
        if data.get("name") != MARKETPLACE_NAME:
            fail(f"{label}的名字是 {data.get('name')!r}，应该是 {MARKETPLACE_NAME!r}")

    claude_entry = next((p for p in claude_mp.get("plugins", []) if p.get("name") == PLUGIN_NAME), None)
    codex_entry = next((p for p in codex_mp.get("plugins", []) if p.get("name") == PLUGIN_NAME), None)
    if not claude_entry or not codex_entry:
        fail("插件市场里没有找到本插件的条目")
        return
    if (codex_entry.get("source") or {}).get("source") != "local":
        fail("Codex 插件市场条目的 source.source 应该是 local")
    for label, rel in (("Claude", claude_entry.get("source")), ("Codex", (codex_entry.get("source") or {}).get("path"))):
        if not rel or not (ROOT / rel).is_dir() or (ROOT / rel).resolve() != PLUGIN.resolve():
            fail(f"{label} 插件市场指向的位置不对：{rel}")
    for label, data in (("Claude plugin.json", claude_pj), ("Codex plugin.json", codex_pj)):
        if data.get("name") != PLUGIN_NAME:
            fail(f"{label} 的名字是 {data.get('name')!r}，应该是 {PLUGIN_NAME!r}")

    versions = {
        "Claude 插件市场条目": claude_entry.get("version"),
        "Claude plugin.json": claude_pj.get("version"),
        "Codex plugin.json": codex_pj.get("version"),
    }
    if None in versions.values() or len(set(versions.values())) != 1:
        fail("版本号不一致：" + "，".join(f"{k} = {v}" for k, v in versions.items()))
    else:
        ok(f"3 处版本号一致：{claude_pj['version']}")

    # Claude Code 只认插件根目录的 .mcp.json（写在 plugin.json 里的 mcpServers 不会被识别，2026-10-21 实测）
    if "mcpServers" in claude_pj:
        fail("Claude plugin.json 里不要写 mcpServers，画布配置放在插件根目录的 .mcp.json")
    mcp_file = PLUGIN / ".mcp.json"
    server = (load(mcp_file).get("mcpServers") or {}).get("xuanshang-canvas") or {} if mcp_file.is_file() else {}
    script = next((a for a in server.get("args", []) if a.endswith("start-mcp.ps1")), "")
    if not script.startswith("${CLAUDE_PLUGIN_ROOT}/"):
        fail("插件根目录的 .mcp.json 里没有找到画布工具的启动配置")
    elif not (PLUGIN / script.removeprefix("${CLAUDE_PLUGIN_ROOT}/")).is_file():
        fail(f"画布工具的启动脚本不存在：{script}")
    else:
        ok("画布工具的启动配置指向的脚本存在")
    if codex_pj.get("skills") != "./skills/":
        fail("Codex plugin.json 的 skills 应该是 ./skills/")

    # 画布工具的版本号单独管，但 pyproject.toml 和 __init__.py 两处必须相同
    py_ver = re.search(r'^version\s*=\s*"([^"]+)"', (CANVAS / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    init_ver = re.search(r'^__version__\s*=\s*"([^"]+)"',
                         (CANVAS / "src" / "xuanshang_canvas" / "__init__.py").read_text(encoding="utf-8"), re.M)
    if not py_ver or not init_ver or py_ver.group(1) != init_ver.group(1):
        fail(f"画布工具两处版本号不一致：pyproject.toml = {py_ver and py_ver.group(1)}，"
             f"__init__.py = {init_ver and init_ver.group(1)}")
    else:
        ok(f"画布工具两处版本号一致：{py_ver.group(1)}")


def check_skills() -> None:
    print("2. skill 文件夹")
    names = []
    for folder in sorted(p for p in (PLUGIN / "skills").iterdir() if p.is_dir()):
        skill = folder / "SKILL.md"
        if not skill.is_file():
            fail(f"{folder.name} 里没有 SKILL.md")
            continue
        match = re.match(r"---\s*\n(.*?)\n---", skill.read_text(encoding="utf-8"), re.S)
        if match:
            # 开头的 name / description 要能被 YAML 正常读出来，否则 Claude Code、Codex 可能认不到这个 skill
            try:
                import yaml
                meta = yaml.safe_load(match.group(1))
                if not isinstance(meta, dict) or meta.get("name") != folder.name or not meta.get("description"):
                    fail(f"{folder.name}/SKILL.md 开头的 name/description 读出来不对")
            except ImportError:
                if re.search(r"^description:.*: ", match.group(1), re.M):
                    fail(f"{folder.name}/SKILL.md 的 description 里有「冒号+空格」，可能让 YAML 读错")
            except Exception as exc:  # yaml 解析失败
                fail(f"{folder.name}/SKILL.md 开头的 YAML 读不出来：{exc}")
        name = re.search(r"^name:\s*(\S+)\s*$", match.group(1), re.M) if match else None
        if not name or name.group(1) != folder.name:
            fail(f"{folder.name}/SKILL.md 的 name 和文件夹名不一致")
        elif not re.search(r"^description:\s*\S", match.group(1), re.M):
            fail(f"{folder.name}/SKILL.md 缺少 description")
        else:
            names.append(folder.name)
    missing, extra = EXPECTED_SKILLS - set(names), set(names) - EXPECTED_SKILLS
    if missing:
        fail("少了 skill：" + "、".join(sorted(missing)))
    if extra:
        fail("多了名单外的 skill（新加的话请同步改 tools/check.py 的 EXPECTED_SKILLS）：" + "、".join(sorted(extra)))
    if not missing and not extra:
        ok(f"{len(names)} 个 skill 和名单一致：{'、'.join(names)}")

    leftovers = [p for p in PLUGIN.rglob("*") if p.name in {".git", "install.py", "__pycache__", ".in_use"}]
    if leftovers:
        fail("插件里有不该带进来的东西：" + "、".join(str(p.relative_to(ROOT)) for p in leftovers))
    else:
        ok("没有 .git、install.py、__pycache__ 之类的残留")


LINK = re.compile(r"\]\(([^)\s]+)\)")
# 代码块和 `行内代码` 里的内容不是链接，检查前先去掉
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
# skill 里大量用 `references/xxx.md` 这种行内代码写法引用文件。只查这些开头的，
# 不查所有行内代码：`scene.json`、`检查报告.md` 这类是运行时才生成的文件名。
INLINE = re.compile(r"`([^`\n]+)`")
PATH_PREFIXES = ("references/", "modules/", "templates/", "scripts/", "agents/", "../")
SKILL_ROOT_MARK = "<技能目录>/"
SHARED_FILES = {"Seedance平台.md", "素材引用写法.md", "信息来源标注.md"}
# 素材引用统一写 (图片N)（2026-10-21 用户决定）；@图片1 这类旧写法和「至」的范围写法不能再出现。
# 画布 skill、shared/素材引用写法.md 和 shared/Seedance平台.md 在讲转换规则和其他入口的写法，不查。
OLD_REF = re.compile(
    r"[@＠]\s*(图片|视频|音频)\s*(\d|[A-Za-z](?![A-Za-z]))"          # @图片1、@图片N、＠ 图片1
    r"|[(（]\s*(图片|视频|音频)[^)）]*[)）]\s*(至|到)\s*[(（@＠]?\s*(图片|视频|音频)"  # (图片1)至(图片3)
    r"|(?<![(（])参考(视频|图片|音频)\s*\d+(?![\d.–—~\-\s]*(秒|帧|张|段|个|s\b))"  # 参考视频1的运镜（时长数字、范围不算）
)


def check_links() -> None:
    print("3. 文档里的相对链接")
    checked = 0
    for md in files(ROOT):
        if md.suffix != ".md":
            continue
        for target in LINK.findall(CODE.sub("", md.read_text(encoding="utf-8"))):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            rel = target.split("#", 1)[0]
            if not rel:
                continue
            checked += 1
            if not (md.parent / rel).exists():
                fail(f"{md.relative_to(ROOT)} 链接到不存在的文件：{target}")
    ok(f"检查了 {checked} 个相对链接")

    inline_checked = 0
    skill_dirs = sorted(p for p in (PLUGIN / "skills").iterdir() if p.is_dir())
    for skill_dir in skill_dirs:
        for md in skill_dir.rglob("*.md"):
            for code in INLINE.findall(md.read_text(encoding="utf-8")):
                token = code.split()[0] if code.split() else ""
                rel = token.split("#", 1)[0]
                if rel.startswith(SKILL_ROOT_MARK):
                    # `<技能目录>/../../shared/xxx.md`：从 skill 根目录算
                    rel = rel[len(SKILL_ROOT_MARK):]
                    candidates = [skill_dir / rel]
                elif rel.startswith("shared/"):
                    # 简写的 `shared/xxx.md`：指插件根目录下的 shared 文件夹
                    candidates = [PLUGIN / rel]
                elif rel.startswith(PATH_PREFIXES):
                    # 按 skill 根目录找；也接受相对当前文件的写法
                    candidates = [skill_dir / rel, md.parent / rel]
                else:
                    continue
                if any(c in rel for c in "<>*{}…"):
                    continue
                inline_checked += 1
                if not any(c.exists() for c in candidates):
                    fail(f"{md.relative_to(ROOT)} 提到的文件不存在：`{token}`")
    # shared 里的文件互相引用时只写文件名；提到某个 skill 的 references/ 时，至少要在一个 skill 里存在
    shared_dir = PLUGIN / "shared"
    missing_shared = SHARED_FILES - {p.name for p in shared_dir.glob("*.md")}
    if missing_shared:
        fail("shared 文件夹缺少：" + "、".join(sorted(missing_shared)))
    for md in shared_dir.glob("*.md"):
        for code in INLINE.findall(md.read_text(encoding="utf-8")):
            token = code.split()[0] if code.split() else ""
            if token in SHARED_FILES or token.endswith(".md") and "/" not in token:
                inline_checked += 1
                if not (shared_dir / token).exists():
                    fail(f"{md.relative_to(ROOT)} 提到的共用文件不存在：`{token}`")
            elif token.startswith("references/"):
                inline_checked += 1
                if not any((d / token).exists() for d in skill_dirs):
                    fail(f"{md.relative_to(ROOT)} 提到的文件在所有 skill 里都不存在：`{token}`")
    ok(f"检查了 {inline_checked} 处行内代码写法的文件路径（含 shared）")

    old_refs = []
    for md in list(PLUGIN.rglob("*.md")) + list(PLUGIN.rglob("*.py")):
        rel = md.relative_to(PLUGIN).as_posix()
        if rel.startswith(("skills/xuanshang-canvas/", "canvas-mcp/")) or rel in ("shared/素材引用写法.md", "shared/Seedance平台.md"):
            continue
        for n, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            if OLD_REF.search(line):
                old_refs.append(f"{rel}:{n}")
    if old_refs:
        fail("还有旧的引用写法（@图片1 或「(图片1)至(图片3)」），统一改成 (图片N) 并逐个写出：" + "、".join(old_refs[:10]))
    else:
        ok("素材引用都已是 (图片N) 写法，没有 @图片1 或「至」的范围写法")


def check_text() -> None:
    print("4. 换行和编码")
    bad_eol, bad_ctrl, bad_bom = [], [], []
    for path in files(ROOT):
        raw = path.read_bytes()
        if path.suffix in LF_SUFFIXES:
            if b"\r\n" in raw:
                bad_eol.append(path)
            text = raw.decode("utf-8", errors="replace")
            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
                bad_ctrl.append(path)
        elif path.suffix == ".ps1":
            if any(b > 127 for b in raw) and not raw.startswith(b"\xef\xbb\xbf"):
                bad_bom.append(path)
    for label, group in (("用了 Windows 换行（应该是 LF）", bad_eol), ("含有看不见的控制字符", bad_ctrl),
                         ("含中文但没有 BOM（Windows PowerShell 5.1 会读成乱码）", bad_bom)):
        if group:
            fail(label + "：" + "、".join(str(p.relative_to(ROOT)) for p in group))
    if not (bad_eol or bad_ctrl or bad_bom):
        ok("文本文件都是 LF 换行、没有控制字符；含中文的 PowerShell 脚本都带 BOM")


def run(label: str, cmd: list[str], cwd: Path) -> None:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if result.returncode == 0:
        ok(label)
    else:
        lines = (result.stdout + result.stderr).strip().splitlines()
        # 优先显示带"错误/失败/error"的行；剧本校验最后几行只是统计数字，看不出原因
        key = [l.strip() for l in lines if re.search(r"error|fail|错误|失败|不存在|找不到|mismatch", l, re.I)]
        fail(f"{label}没通过：" + " / ".join((key or lines)[-8:]))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print(f"检查 {ROOT}\n")
    check_manifests()
    check_skills()
    check_links()
    check_text()
    print("5. 脚本自检")
    run("画布 skill 和 RULES.md 一致", [sys.executable, "-B", "scripts/build_adapters.py", "--check"], CANVAS)
    run("画布规则测试", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], CANVAS)
    run("剧本资料完整（verify_corpus）", [sys.executable, "-B", "scripts/verify_corpus.py"], PROMPT_SKILL)
    print()
    if problems:
        print(f"有 {len(problems)} 个问题，见上面的 [问题]。")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
