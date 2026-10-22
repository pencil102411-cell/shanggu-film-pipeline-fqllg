# -*- coding: utf-8 -*-
"""读取与校验三张参数表（scene / blocking / shots），以及颜色、帧换算等公共工具。不依赖 bpy。"""
import json, os, re

FPS = 24
DEFAULT_RES = (1470, 630)       # Seedance 2.5 的 21:9 原生输出尺寸
PREVIEW_RES = (700, 300)        # 同比例低清预览


class SpecError(Exception):
    pass


def load_json(path, required=True):
    if not os.path.exists(path):
        if required:
            raise SpecError(f"找不到参数表：{path}")
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise SpecError(f"{os.path.basename(path)} 不是合法 JSON：第 {e.lineno} 行第 {e.colno} 列，{e.msg}")


# ---------------------------------------------------------------- 颜色

NAMED_COLORS = {
    "红": "#d9332b", "red": "#d9332b",
    "蓝": "#2f63d6", "blue": "#2f63d6",
    "黄": "#f0c419", "yellow": "#f0c419",
    "绿": "#2fa84f", "green": "#2fa84f",
    "紫": "#8a46c0", "purple": "#8a46c0",
    "橙": "#f07f1d", "orange": "#f07f1d",
    "青": "#1db3bf", "cyan": "#1db3bf",
    "粉": "#f075a6", "pink": "#f075a6",
    "白": "#f2f2f2", "white": "#f2f2f2",
    "黑": "#1a1a1a", "black": "#1a1a1a",
    "棕": "#8b5a2b", "brown": "#8b5a2b",
}
ACTOR_PALETTE = ["蓝", "红", "黄", "绿", "紫", "橙", "青", "粉"]

# 场景灰度（sRGB 0..1）：不同类别略有深浅，帮助看清结构
SCENE_GREYS = {
    "wall": 0.80,
    "floor": 0.56,
    "ground": 0.50,
    "slab": 0.62,
    "stairs": 0.66,
    "column": 0.74,
    "furniture": 0.68,
    "ceiling": 0.86,
    "roof": 0.60,
    "prop": 0.70,
    "window": 0.90,
}


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def parse_color(c, default="#888888"):
    """返回 sRGB 的 (r,g,b)。支持中文/英文颜色名、#RRGGBB、[r,g,b]（0..1）、单个灰度数字。"""
    if c is None:
        c = default
    if isinstance(c, (int, float)):
        return (float(c),) * 3
    if isinstance(c, (list, tuple)):
        return tuple(float(v) for v in c[:3])
    s = str(c).strip()
    s = NAMED_COLORS.get(s, s)
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", s)
    if not m:
        raise SpecError(f"看不懂的颜色：{c}（可用：{'、'.join(k for k in NAMED_COLORS if not k.isascii())} 或 #RRGGBB）")
    h = m.group(1)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def color_linear(c, default="#888888"):
    r, g, b = parse_color(c, default)
    return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), 1.0)


# ---------------------------------------------------------------- 时间 ↔ 帧

def t2f(t, fps=FPS):
    """时间（秒）→ 帧号。第 0 秒 = 第 1 帧。"""
    return int(round(t * fps)) + 1


def f2t(f, fps=FPS):
    return (f - 1) / fps


def snap_time(t, fps=FPS):
    """把时间对齐到整帧，返回 (对齐后时间, 是否被调整)。"""
    snapped = round(t * fps) / fps
    return snapped, abs(snapped - t) > 1e-6


# ---------------------------------------------------------------- 配置

def load_config(skill_root):
    """读取 config.json（Blender / FFmpeg 路径）。找不到就尝试自动探测。"""
    cfg_path = os.path.join(skill_root, "config.json")
    cfg = load_json(cfg_path, required=False) or {}
    return cfg
