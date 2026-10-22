# -*- coding: utf-8 -*-
"""纯数学工具（不依赖 bpy，可在普通 Python 里测试）。

约定：
- 平面坐标 (x, y) 单位米；平面图上向右 = +X，向上 = +Y；高度 = Z。
- 朝向角 facing：罗盘式，0 = 朝 +Y（平面图上方），90 = 朝 +X（右），顺时针增加。
"""
import math

# ---------------------------------------------------------------- 基础

def clamp(v, a, b):
    return a if v < a else b if v > b else v


def lerp(a, b, u):
    return a + (b - a) * u


def lerp_vec(a, b, u):
    return [lerp(x, y, u) for x, y in zip(a, b)]


def smoothstep(x):
    x = clamp(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def dist2d(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def dist3d(a, b):
    return math.sqrt(sum((q - p) ** 2 for p, q in zip(a, b)))


def facing_to_dir(deg):
    r = math.radians(deg)
    return (math.sin(r), math.cos(r))


def dir_to_facing(dx, dy):
    return math.degrees(math.atan2(dx, dy)) % 360.0


def angle_diff(a, b):
    """b - a 的最短角差（度），结果在 (-180, 180]。"""
    d = (b - a) % 360.0
    return d - 360.0 if d > 180.0 else d


def lerp_angle(a, b, u):
    return a + angle_diff(a, b) * u


def unwrap_angles(seq):
    """把一串角度展开成连续值，避免 359→0 的跳变。"""
    out = []
    for v in seq:
        if not out:
            out.append(v)
        else:
            out.append(out[-1] + angle_diff(out[-1], v))
    return out


# ---------------------------------------------------------------- 缓入缓出

def ease_progress(t, T, ein, eout):
    """速度曲线：前 ein 秒平滑加速，后 eout 秒平滑减速，中间匀速。返回 0..1 的进度。

    加速段速度按 smoothstep 上升，加速度连续（不会"顿一下"）。
    """
    if T <= 1e-9:
        return 1.0
    t = clamp(t, 0.0, T)
    ein = max(0.0, ein)
    eout = max(0.0, eout)
    if ein + eout > T:
        k = T / (ein + eout)
        ein *= k
        eout *= k
    vmax = 1.0 / (T - 0.5 * (ein + eout))

    def R(x):  # ∫0^x smoothstep
        return x ** 3 - 0.5 * x ** 4

    if ein > 0 and t < ein:
        return vmax * ein * R(t / ein)
    if eout > 0 and t > T - eout:
        return 1.0 - vmax * eout * R((T - t) / eout)
    return vmax * (0.5 * ein + (t - ein))


def resolve_ease(spec, T, default_frac=0.35, default_max=1.0):
    """把 ease 写法解析成 (ein, eout) 秒数。

    spec: None/"auto"（默认）| 数字（两端同样秒数）| [in, out] | "in" | "out" | "none" | "both"
    """
    auto = min(default_max, default_frac * T)
    if spec is None or spec == "auto" or spec == "both":
        return auto, auto
    if spec == "none" or spec == 0:
        return 0.0, 0.0
    if spec == "in":
        return auto, 0.0
    if spec == "out":
        return 0.0, auto
    if isinstance(spec, (int, float)):
        return float(spec), float(spec)
    if isinstance(spec, (list, tuple)) and len(spec) == 2:
        return float(spec[0]), float(spec[1])
    raise ValueError(f"无法识别的 ease 写法: {spec!r}")


# ---------------------------------------------------------------- 路径

def chaikin(points, iterations=3, keep_ends=True):
    """切角法把折线磨圆。"""
    pts = [list(p) for p in points]
    if len(pts) < 3:
        return pts
    for _ in range(iterations):
        new = [pts[0]] if keep_ends else []
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            a = [0.75 * p[k] + 0.25 * q[k] for k in range(len(p))]
            b = [0.25 * p[k] + 0.75 * q[k] for k in range(len(p))]
            if keep_ends and i == 0:
                new.append(b)
            elif keep_ends and i == len(pts) - 2:
                new.append(a)
            else:
                new.extend([a, b])
        if keep_ends:
            new.append(pts[-1])
        pts = new
    return pts


class Polyline:
    """按弧长取点的折线。"""

    def __init__(self, points):
        self.pts = [list(p) for p in points]
        self.cum = [0.0]
        for i in range(1, len(self.pts)):
            self.cum.append(self.cum[-1] + dist3d(self.pts[i - 1], self.pts[i]))
        self.length = self.cum[-1]

    def at(self, s):
        if self.length <= 1e-9:
            return list(self.pts[0])
        s = clamp(s, 0.0, self.length)
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        seg = self.cum[hi] - self.cum[lo]
        u = 0.0 if seg <= 1e-12 else (s - self.cum[lo]) / seg
        return lerp_vec(self.pts[lo], self.pts[hi], u)

    def tangent(self, s, h=0.25):
        a = self.at(max(0.0, s - h))
        b = self.at(min(self.length, s + h))
        return [b[k] - a[k] for k in range(len(a))]


def round_corners(points, radius=0.6, samples=10):
    """固定半径倒圆角：每个拐点前后各让出 radius 米（不超过相邻段长的 45%），中间用二次曲线连接。

    和按比例削角不同，长直路不会提前好几米就开始拐弯。
    """
    pts = [list(p) for p in points]
    if len(pts) < 3 or radius <= 0:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        p0, p1, p2 = pts[i - 1], pts[i], pts[i + 1]
        l1, l2 = dist3d(p0, p1), dist3d(p1, p2)
        if l1 < 1e-6 or l2 < 1e-6:
            continue
        r = min(radius, 0.45 * l1, 0.45 * l2)
        a = [p1[k] + (p0[k] - p1[k]) * r / l1 for k in range(len(p1))]
        b = [p1[k] + (p2[k] - p1[k]) * r / l2 for k in range(len(p1))]
        for j in range(samples + 1):
            u = j / samples
            out.append([(1 - u) ** 2 * a[k] + 2 * (1 - u) * u * p1[k] + u * u * b[k] for k in range(len(p1))])
    out.append(pts[-1])
    return out


def smooth_path(points, radius=0.6):
    """radius：拐角圆角半径（米）。传 False/0 表示不磨圆。"""
    if radius is True:
        radius = 0.6
    if radius and len(points) >= 3:
        return Polyline(round_corners(points, float(radius)))
    return Polyline(points)


# ---------------------------------------------------------------- 平滑跟随（临界阻尼弹簧）

def critically_damped(samples, dt, tau, init=None):
    """对一串向量做临界阻尼平滑（不过冲）。tau 约等于"晚多少秒跟上"。

    samples: [[x,y,z], ...] 每帧目标；返回同长度的平滑结果。
    """
    if tau <= 1e-6:
        return [list(s) for s in samples]
    omega = 2.0 / tau
    x = list(init if init is not None else samples[0])
    v = [0.0] * len(x)
    out = []
    for tgt in samples:
        # 精确离散化（Game Programming Gems 4 的 SmoothDamp 形式）
        ex = omega * dt
        k = 1.0 / (1.0 + ex + 0.48 * ex * ex + 0.235 * ex * ex * ex)
        for i in range(len(x)):
            change = x[i] - tgt[i]
            temp = (v[i] + omega * change) * dt
            v[i] = (v[i] - omega * temp) * k
            x[i] = tgt[i] + (change + temp) * k
        out.append(list(x))
    return out


# ---------------------------------------------------------------- 手持噪声

class SmoothNoise:
    """几组不同频率正弦叠加的平滑噪声，按种子固定，可复现。"""

    def __init__(self, seed, bands):
        """bands: [(频率Hz, 振幅), ...]"""
        import random
        rnd = random.Random(seed)
        self.terms = []
        for f, amp in bands:
            # 每个频段拆成三条略有偏差的正弦，避免规律感
            for _ in range(3):
                ff = f * rnd.uniform(0.7, 1.3)
                self.terms.append((ff, amp / 3.0 * rnd.uniform(0.6, 1.4), rnd.uniform(0, 2 * math.pi)))

    def __call__(self, t):
        return sum(a * math.sin(2 * math.pi * f * t + p) for f, a, p in self.terms)


def handheld_offsets(intensity, seed=1):
    """返回函数 f(t) -> (dx, dy, dz, dyaw, dpitch, droll)，单位米和度。

    intensity 0..1：0.3 ≈ 很轻的稳定器感，0.6 ≈ 普通手持，1.0 ≈ 明显手持。
    低频漂移 + 小幅颤动 + 轻微横滚。
    """
    k = max(0.0, float(intensity))
    ch = [
        SmoothNoise(seed * 11 + 1, [(0.18, 0.015 * k), (1.1, 0.002 * k)]),   # x 米
        SmoothNoise(seed * 11 + 2, [(0.15, 0.012 * k), (1.3, 0.002 * k)]),   # y 米
        SmoothNoise(seed * 11 + 3, [(0.22, 0.010 * k), (1.7, 0.002 * k)]),   # z 米
        SmoothNoise(seed * 11 + 4, [(0.20, 0.70 * k), (1.6, 0.10 * k)]),     # yaw 度
        SmoothNoise(seed * 11 + 5, [(0.25, 0.55 * k), (1.9, 0.09 * k)]),     # pitch 度
        SmoothNoise(seed * 11 + 6, [(0.17, 0.40 * k), (1.4, 0.05 * k)]),     # roll 度
    ]
    return lambda t: tuple(c(t) for c in ch)


# ---------------------------------------------------------------- 镜头几何

SENSOR_W = 36.0  # 全画幅传感器宽（mm）


def fovs(lens_mm, res_x, res_y):
    """返回 (水平视角, 垂直视角)，弧度。传感器按宽度适配。"""
    hw = SENSOR_W / 2.0
    hh = hw * res_y / res_x
    return 2 * math.atan(hw / lens_mm), 2 * math.atan(hh / lens_mm)


# 景别 → 画面竖直方向覆盖的高度（米），按 1.75m 左右的人估算
SHOT_SIZES = {
    "大特写": 0.22, "ECU": 0.22,
    "特写": 0.35, "CU": 0.35,
    "近景": 0.55,
    "中近景": 0.75, "MCU": 0.75,
    "中景": 1.05, "MS": 1.05,
    "中全景": 1.45, "MFS": 1.45,
    "全景": 2.3, "FS": 2.3,
    "远景": 5.0, "WS": 5.0,
    "大远景": 12.0, "EWS": 12.0,
}

# 这些景别默认对准眼睛，更宽的景别对准身体中部
TIGHT_SIZES = {"大特写", "ECU", "特写", "CU", "近景", "中近景", "MCU", "中景", "MS"}


def dist_for_size(size, lens_mm, res_x, res_y, actor_height=1.75):
    if isinstance(size, (int, float)):
        cover = float(size)
    else:
        if size not in SHOT_SIZES:
            raise ValueError(f"未知景别: {size}（可选：{'、'.join(k for k in SHOT_SIZES if not k.isascii())}）")
        cover = SHOT_SIZES[size] * (actor_height / 1.75 if SHOT_SIZES[size] < 3 else 1.0)
    _, vf = fovs(lens_mm, res_x, res_y)
    return cover / (2 * math.tan(vf / 2))


def look_angles(cam, target):
    """从 cam 看 target 的 (yaw, pitch)，度。yaw 用 Blender 相机约定：0 = 看向 +Y，正值向左转。"""
    dx, dy, dz = target[0] - cam[0], target[1] - cam[1], target[2] - cam[2]
    yaw = math.degrees(math.atan2(-dx, dy))
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    return yaw, pitch


def aim_with_framing(cam, target, sx, sy, lens_mm, res_x, res_y):
    """让 target 落在画面 (sx, sy)（0..1，x 从左、y 从下）的相机 yaw/pitch（度）。"""
    yaw, pitch = look_angles(cam, target)
    hf, vf = fovs(lens_mm, res_x, res_y)
    a = math.degrees(math.atan((sx - 0.5) * 2 * math.tan(hf / 2)))
    b = math.degrees(math.atan((sy - 0.5) * 2 * math.tan(vf / 2)))
    return yaw + a, pitch - b


def project(cam_pos, yaw, pitch, roll, lens_mm, res_x, res_y, point):
    """把世界点投影到画面，返回 (sx, sy, depth)，sx/sy 为 0..1（可能越界），depth<=0 表示在相机背后。"""
    # 构造相机基向量
    cy, sy_ = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    fwd = (-sy_ * cp, cy * cp, sp)
    right = (cy, sy_, 0.0)
    up = (right[1] * fwd[2] - right[2] * fwd[1],
          right[2] * fwd[0] - right[0] * fwd[2],
          right[0] * fwd[1] - right[1] * fwd[0])
    if abs(roll) > 1e-9:
        cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
        right, up = (tuple(cr * right[i] + sr * up[i] for i in range(3)),
                     tuple(-sr * right[i] + cr * up[i] for i in range(3)))
    d = [point[i] - cam_pos[i] for i in range(3)]
    z = sum(d[i] * fwd[i] for i in range(3))
    if z <= 1e-6:
        return 0.5, 0.5, z
    x = sum(d[i] * right[i] for i in range(3))
    y = sum(d[i] * up[i] for i in range(3))
    hf, vf = fovs(lens_mm, res_x, res_y)
    sx = 0.5 + x / z / (2 * math.tan(hf / 2))
    sy = 0.5 + y / z / (2 * math.tan(vf / 2))
    return sx, sy, z


def view_dir(yaw, pitch):
    cy, sy_ = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    return (-sy_ * cp, cy * cp, sp)
