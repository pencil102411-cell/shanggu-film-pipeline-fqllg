"""从 rules/RULES.md 生成插件里的画布 skill（Claude Code 和 Codex 共用一份），保证内容完全一致。

用法（在 canvas-mcp 目录）：
    python scripts/build_adapters.py          生成 / 更新
    python scripts/build_adapters.py --check  只检查是否和 RULES.md 一致，不一致时退出码为 1
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 插件根目录：canvas-mcp 的上一级，生成的 skill 放在插件的 skills/ 下
PLUGIN_ROOT = ROOT.parent
SOURCE = ROOT / "rules" / "RULES.md"

SKILL_NAME = "xuanshang-canvas"
SKILL_DESCRIPTION = (
    "操作玄上无限画布（含玄上内部版）的流程和规则：新建项目和认证分组、查项目和节点、上传认证图片和参考视频、"
    "把认证素材放到画布上、新建 Seedance 视频节点、提交生成、样片转成片、查任务进度。"
    "用户提到玄上画布、无限画布、认证素材、Seedance 视频节点、提交生成、转成片时使用；"
    "必须配合 xuanshang-canvas 这组 MCP 工具，不要自己写脚本调画布接口。"
)

TARGETS = {
    # Claude Code 和 Codex 都从插件的 skills/ 读这一份
    PLUGIN_ROOT / "skills" / SKILL_NAME / "SKILL.md": "Claude Code 和 Codex 共用",
}


def strip_comments(text: str) -> str:
    """去掉 <!-- --> 维护注释（MCP 服务读规则时也做同样处理）。"""
    return re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)


def render(target_label: str, rules: str) -> str:
    rules = strip_comments(rules)
    body = rules.split("\n", 1)[1] if rules.startswith("# ") else rules
    return (
        "---\n"
        f"name: {SKILL_NAME}\n"
        f"description: {SKILL_DESCRIPTION}\n"
        "---\n\n"
        f"<!-- 本文件由 canvas-mcp/scripts/build_adapters.py 从 canvas-mcp/rules/RULES.md 生成（{target_label}），不要直接修改。 -->\n\n"
        "# 玄上画布插件 · 操作规则\n"
        f"{body}"
    )


def main() -> int:
    rules = SOURCE.read_text(encoding="utf-8")
    check_only = "--check" in sys.argv
    stale = []
    for path, label in TARGETS.items():
        content = render(label, rules)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        if check_only:
            stale.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"已生成：{path.relative_to(PLUGIN_ROOT)}（{label}）")
    if check_only:
        if stale:
            print("这些规则文件和 rules/RULES.md 不一致，请运行 python scripts/build_adapters.py：")
            for path in stale:
                print(f"  {path.relative_to(PLUGIN_ROOT)}")
            return 1
        print("所有规则文件都和 rules/RULES.md 一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
