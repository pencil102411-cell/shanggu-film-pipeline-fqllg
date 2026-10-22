"""第 6 节操作规则里和提示词、参数有关的部分：规则 2（引用格式）、规则 3（引用对齐）、
规则 1（重名加版本号）、规则 10（读回核对），以及 Seedance 参数校验。

这些规则在代码里强制执行，不依赖 AI 自觉遵守。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .errors import RuleViolation

KIND_LABEL = {"image": "图片", "video": "视频", "audio": "音频"}
LABEL_KIND = {"图片": "image", "视频": "video", "音频": "audio"}

# 规则 2：引用写法跟画布保持一致，统一成半角 (图片1)。画布界面保存时也会把引用改成这个样子。
# @图片1、全角（图片1）、混用的（图片1)，以及画布自己会转换的〔图片1〕【图片1】，都转成 (图片1)。
_AT_REF = re.compile(r"@\s*(图片|视频|音频)\s*(\d+)")
_PAREN_REF = re.compile(r"[（(〔【]\s*@?\s*(图片|视频|音频)\s*(\d+)\s*[）)〕】]")
_CANONICAL_REF = re.compile(r"\((图片|视频|音频)(\d+)\)")
# 正文里所有「图片/视频/音频 + 数字」，用来找出没有写成 (图片N) 的裸编号。
_LABEL_NUMBER = re.compile(r"(图片|视频|音频)\s*(\d+)")
# 省略写法：(图片7)、8 / (图片7)和8 —— 后面那个 8 画布不会当成引用。
_ELIDED_AFTER_REF = re.compile(r"\((图片|视频|音频)(\d+)\)\s*[、,，和与及/]\s*(\d+)")
# 范围写法：(图片1)—8 / (图片1)—(图片8) / 图片1—8 —— 画布不会认出中间的编号。
_RANGE = re.compile(r"(?:\((图片|视频|音频)(\d+)\)|(图片|视频|音频)\s*(\d+))\s*[—–\-~～]+\s*\(?\s*(?:图片|视频|音频)?\s*(\d+)\)?")
# 没括号的省略写法：图片7、8 / 图片7和8。
_BARE_ELIDED = re.compile(r"(?<![(（])(图片|视频|音频)\s*(\d+)\s*[、,，和与及/]\s*(\d+)")
# 数字后面跟着这些字，多半是时长、数量，不是素材编号（例如「参考视频27秒」）。
_UNIT_AFTER = re.compile(r"\s*(秒|s(?![a-z])|帧|分钟|小时|%|％|张(?!开)|个|段|条|次|岁|米|倍|fps)", re.I)


@dataclass
class PromptCheck:
    prompt: str
    converted: list[str] = field(default_factory=list)
    references: dict[str, list[int]] = field(default_factory=dict)
    reference_count: int = 0  # 全文合法引用出现的总次数
    format_problems: list[str] = field(default_factory=list)  # 画布认不出的写法（裸编号、省略、范围）
    problems: list[str] = field(default_factory=list)  # 编号越界、接入的素材没被引用
    warnings: list[str] = field(default_factory=list)


def normalize_prompt(prompt: str) -> tuple[str, list[str]]:
    """规则 2。返回（转换后的提示词，转换记录）。只转换已经带括号或 @ 的写法，裸编号不自动改。"""
    converted: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        target = f"({match.group(1)}{int(match.group(2))})"
        if match.group(0) != target:
            converted.append(f"{match.group(0)} → {target}")
        return target

    # 先处理带括号的（含「（@图片1）」这种），再处理单独的 @图片1，避免套出两层括号。
    text = _PAREN_REF.sub(_replace, prompt)
    text = _AT_REF.sub(_replace, text)
    return text, converted


def _locate(text: str, start: int, end: int) -> str:
    """给出「第几行：…前后文…」，方便定位。"""
    line = text.count("\n", 0, start) + 1
    left = text.rfind("\n", 0, start) + 1
    right = text.find("\n", end)
    right = len(text) if right == -1 else right
    before = text[max(left, start - 12):start]
    after = text[end:min(right, end + 12)]
    return f"第 {line} 行「{'…' if start - 12 > left else ''}{before}【{text[start:end]}】{after}{'…' if end + 12 < right else ''}」"


def find_format_problems(text: str) -> list[str]:
    """找出画布认不出的素材编号写法。text 应该是 normalize_prompt 之后的提示词。"""
    problems: list[str] = []
    canonical = [m.span() for m in _CANONICAL_REF.finditer(text)]
    flagged: list[tuple[int, int]] = []

    def inside_canonical(start: int, end: int) -> bool:
        return any(s <= start and end <= e for s, e in canonical)

    def overlaps_flagged(start: int, end: int) -> bool:
        return any(start < e and s < end for s, e in flagged)

    for m in _RANGE.finditer(text):
        label = m.group(1) or m.group(3)
        first = int(m.group(2) or m.group(4))
        last = int(m.group(5))
        if last <= first:
            continue  # 「图片3-1」之类不是范围，交给裸编号检查
        flagged.append(m.span())
        problems.append(
            f"{_locate(text, *m.span())}：范围写法画布不会认出中间的编号。"
            f"请把要引用的每一个都写出来，如 ({label}{first})、({label}{first + 1})……；不需要逐个引用时改用不带编号的描述"
        )

    for m in _ELIDED_AFTER_REF.finditer(text):
        if overlaps_flagged(*m.span()):
            continue
        flagged.append(m.span())
        label, number = m.group(1), int(m.group(3))
        problems.append(
            f"{_locate(text, *m.span())}：后面的「{number}」不会被当成素材引用，请写成 ({label}{int(m.group(2))})、({label}{number})"
        )

    for m in _BARE_ELIDED.finditer(text):
        if overlaps_flagged(*m.span()):
            continue
        flagged.append(m.span())
        label, first, second = m.group(1), int(m.group(2)), int(m.group(3))
        problems.append(
            f"{_locate(text, *m.span())}：没有括号，而且省略了第二个编号，画布都不会当成素材引用。"
            f"请写成 ({label}{first})、({label}{second})"
        )

    for m in _LABEL_NUMBER.finditer(text):
        if inside_canonical(*m.span()) or overlaps_flagged(*m.span()):
            continue
        label, number = m.group(1), int(m.group(2))
        if _UNIT_AFTER.match(text, m.end()):
            hint = (
                f"这里的数字看起来不是素材编号（像时长或数量），但「{label}{number}」连写容易被误读。"
                f"如果是引用素材，写成 ({label}{number})；如果不是，换个说法，例如「参考视频时长为{number}秒」"
            )
        else:
            hint = f"没有括号，画布不会把它当成素材引用。要引用素材请写成 ({label}{number})"
        problems.append(f"{_locate(text, *m.span())}：{hint}")
    return problems


def canvas_view(prompt: str) -> str:
    """按画布自己的识别规则看提示词：只统一画布认得的括号写法，@图片N 这类画布不认的保持原样。"""
    return _PAREN_REF.sub(lambda m: f"({m.group(1)}{int(m.group(2))})", prompt or "")


def check_prompt(prompt: str, counts: dict[str, int]) -> PromptCheck:
    """规则 2 + 规则 3。counts 是每种素材接入的数量，如 {"image": 3, "video": 1}。"""
    if not isinstance(prompt, str) or not prompt.strip():
        result = PromptCheck(prompt=prompt or "")
        result.problems.append("提示词不能为空")
        return result
    text, converted = normalize_prompt(prompt)
    result = PromptCheck(prompt=text, converted=converted)
    result.format_problems = find_format_problems(text)

    found: dict[str, set[int]] = {kind: set() for kind in KIND_LABEL}
    for match in _CANONICAL_REF.finditer(text):
        found[LABEL_KIND[match.group(1)]].add(int(match.group(2)))
        result.reference_count += 1
    result.references = {kind: sorted(numbers) for kind, numbers in found.items() if numbers}

    for kind, label in KIND_LABEL.items():
        count = int(counts.get(kind, 0))
        numbers = found[kind]
        too_big = sorted(n for n in numbers if n < 1 or n > count)
        if too_big:
            refs = "、".join(f"({label}{n})" for n in too_big)
            if count == 0:
                result.problems.append(f"提示词引用了 {refs}，但没有接入任何{label}")
            else:
                result.problems.append(f"提示词引用了 {refs}，但只接入了 {count} 个{label}（编号只能是 1–{count}）")
        missing = [n for n in range(1, count + 1) if n not in numbers]
        if missing:
            refs = "、".join(f"({label}{n})" for n in missing)
            result.problems.append(f"接入的{label}里，{refs} 没有在提示词里被引用到；每个接入的素材都要引用")
    return result


# ---- 规则 1：重名自动加版本号 -------------------------------------------------


def dedupe_name(name: str, existing: list[str]) -> str:
    taken = {item.strip() for item in existing if item}
    base = name.strip()
    if base not in taken:
        return base
    stem = re.sub(r"-v\d+$", "", base)
    version = 2
    while f"{stem}-v{version}" in taken:
        version += 1
    return f"{stem}-v{version}"


# ---- Seedance 参数（以画布 2026-09 版本的规则为准） ---------------------------

SEEDANCE_MODELS = ["Doubao-Seedance-2.5", "Doubao-Seedance-2.0", "Doubao-Seedance-2.0-fast", "Doubao-Seedance-2.0-mini"]
SEEDANCE_MODES = {
    "multimodal": "多模态参考",
    "first-frame": "首帧生视频",
    "first-last-frame": "首尾帧生视频",
    "video-edit": "视频编辑",
    "video-extend": "视频延长",
}
RATIOS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
SEED_MIN, SEED_MAX = -1, 2147483647
MEDIA_LIMITS = {
    "Doubao-Seedance-2.5": {"image": 30, "video": 10, "audio": 10, "total": 50},
    "default": {"image": 9, "video": 3, "audio": 3, "total": 15},
}
RESOLUTION_LABELS = {"draft": "样片（draft）", "480p": "480p", "720p": "720p", "1080p": "1080p", "4k": "4K"}


def is_seedance25(model: str) -> bool:
    return model == "Doubao-Seedance-2.5"


def allowed_resolutions(model: str) -> list[str]:
    if is_seedance25(model):
        return ["draft", "480p", "720p", "1080p"]
    if model in ("Doubao-Seedance-2.0-fast", "Doubao-Seedance-2.0-mini"):
        return ["480p", "720p"]
    return ["480p", "720p", "1080p", "4k"]


def allowed_durations(model: str, mode: str) -> list[int]:
    if is_seedance25(model) and mode == "video-edit":
        return [-1]
    top = 30 if is_seedance25(model) else 15
    return [-1, *range(4, top + 1)]


def allowed_ratios(model: str, mode: str) -> list[str]:
    if is_seedance25(model) and mode != "multimodal":
        return ["adaptive"]
    return list(RATIOS)


def mode_problem(mode: str, counts: dict[str, int], model: str) -> str | None:
    image, video, audio = counts.get("image", 0), counts.get("video", 0), counts.get("audio", 0)
    if mode == "multimodal":
        if not is_seedance25(model) and audio > 0 and image + video == 0:
            return "Seedance 2.0 不支持只接参考音频"
        return None
    if mode == "first-frame":
        return None if (image == 1 and video == 0 and audio == 0) else "首帧生视频需要且只能接入 1 张图片"
    if mode == "first-last-frame":
        return None if (image == 2 and video == 0 and audio == 0) else "首尾帧生视频需要且只能接入 2 张图片"
    if video == 0:
        return "视频编辑需要至少接入 1 个视频" if mode == "video-edit" else "视频延长需要至少接入 1 个待延长视频"
    return None


def build_video_params(defaults: dict[str, Any], overrides: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    """合并默认参数和这次指定的参数，并按 Seedance 规则校验。不合规就拒绝，不偷偷改值。"""
    params = dict(defaults)
    given = {key: value for key, value in overrides.items() if value is not None}
    params.update(given)
    problems: list[str] = []

    # 用户没指定、只是用了默认值的时长和比例，如果当前模式不允许，就换成这个模式唯一可用的值
    # （比如视频编辑只能「跟随原视频」时长、2.5 非多模态只能「自适应」比例）。用户指定的值不改，不合规就拒绝。
    model_value, mode_value = str(params.get("model")), str(params.get("seedanceMode"))
    if mode_value in SEEDANCE_MODES:
        if "duration" not in given and params.get("duration") not in allowed_durations(model_value, mode_value):
            params["duration"] = allowed_durations(model_value, mode_value)[0]
        if "ratio" not in given and params.get("ratio") not in allowed_ratios(model_value, mode_value):
            params["ratio"] = allowed_ratios(model_value, mode_value)[0]

    model = str(params.get("model"))
    if model not in SEEDANCE_MODELS:
        problems.append(f"模型「{model}」不支持，可选：{'、'.join(SEEDANCE_MODELS)}")
    mode = str(params.get("seedanceMode"))
    if mode not in SEEDANCE_MODES:
        problems.append(f"模式「{mode}」不支持，可选：{'、'.join(f'{k}（{v}）' for k, v in SEEDANCE_MODES.items())}")
    resolution = str(params.get("resolution"))
    if resolution not in allowed_resolutions(model):
        problems.append(f"{model} 不支持分辨率「{resolution}」，可选：{'、'.join(allowed_resolutions(model))}")
    try:
        duration = int(params.get("duration"))
        params["duration"] = duration
        if mode in SEEDANCE_MODES and duration not in allowed_durations(model, mode):
            values = allowed_durations(model, mode)
            hint = "只能填 -1（跟随原视频）" if values == [-1] else f"可选 -1（自动）或 {values[1]}–{values[-1]} 秒"
            problems.append(f"时长 {duration} 秒不支持，{hint}")
    except (TypeError, ValueError):
        problems.append(f"时长应该是整数秒，现在是「{params.get('duration')}」")
    ratio = str(params.get("ratio"))
    if mode in SEEDANCE_MODES and ratio not in allowed_ratios(model, mode):
        problems.append(f"比例「{ratio}」不支持，当前模式可选：{'、'.join(allowed_ratios(model, mode))}")
    try:
        seed = int(params.get("seed"))
        params["seed"] = seed
        if not SEED_MIN <= seed <= SEED_MAX:
            problems.append(f"种子应在 {SEED_MIN}–{SEED_MAX} 之间（-1 表示随机）")
    except (TypeError, ValueError):
        problems.append(f"种子应该是整数，现在是「{params.get('seed')}」")
    output_format = str(params.get("outputFormat")).lower()
    params["outputFormat"] = output_format
    if output_format not in ("mp4", "mov"):
        problems.append("输出格式只能是 mp4 或 mov")
    params["webSearch"] = bool(params.get("webSearch"))

    limits = MEDIA_LIMITS.get(model, MEDIA_LIMITS["default"])
    for kind in ("image", "video", "audio"):
        if counts.get(kind, 0) > limits[kind]:
            problems.append(f"{model} 最多接 {limits[kind]} 个{KIND_LABEL[kind]}，现在接了 {counts[kind]} 个")
    if sum(counts.get(kind, 0) for kind in ("image", "video", "audio")) > limits["total"]:
        problems.append(f"{model} 参考素材总数最多 {limits['total']} 个")
    if mode in SEEDANCE_MODES:
        issue = mode_problem(mode, counts, model)
        if issue:
            problems.append(issue)

    if problems:
        raise RuleViolation("视频节点参数不合规，没有创建：\n- " + "\n- ".join(problems))
    return params


def describe_params(params: dict[str, Any]) -> str:
    mode = SEEDANCE_MODES.get(str(params.get("seedanceMode")), str(params.get("seedanceMode")))
    duration = params.get("duration")
    duration_text = "自动" if duration == -1 else f"{duration} 秒"
    return (
        f"{params.get('model')} · {mode} · {RESOLUTION_LABELS.get(str(params.get('resolution')), params.get('resolution'))}"
        f" · {params.get('ratio')} · {duration_text} · 种子 {params.get('seed')} · {str(params.get('outputFormat')).upper()}"
        f" · 联网搜索{'开' if params.get('webSearch') else '关'}"
    )


# ---- 规则 10：读回核对 --------------------------------------------------------


def compare_fields(expected: dict[str, Any], actual: dict[str, Any], keys: list[str]) -> list[str]:
    differences = []
    for key in keys:
        if expected.get(key) != actual.get(key):
            differences.append(f"{key}：请求的是 {expected.get(key)!r}，画布里是 {actual.get(key)!r}")
    return differences
