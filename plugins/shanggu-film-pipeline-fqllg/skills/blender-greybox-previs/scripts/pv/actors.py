# -*- coding: utf-8 -*-
"""站位表 blocking.json → 彩色人偶 + 逐帧烘焙的走位动画。

每个人物 = 一个空物体（根，负责位置和朝向）+ 身体网格（子物体，负责姿态）
+ 头部空物体（身体的子物体，跟着身体高度上下移动，下面挂颈、脸、后脑）。
旧版纯胶囊（figure = capsule）只有身体，没有头部。
所有运动在 Python 里逐帧算好再写成关键帧，结果完全可复现。
"""
import math
import bpy, bmesh

from .spec import SpecError, color_linear, ACTOR_PALETTE, FPS, f2t
from . import mathutil as mu
from .scene_builder import ensure_collection, COLL_ACTORS

POSES = ("stand", "sit", "crouch", "kneel", "lie")
POSE_ALIASES = {"站": "stand", "站立": "stand", "坐": "sit", "坐下": "sit", "蹲": "crouch", "蹲下": "crouch",
                "跪": "kneel", "跪下": "kneel", "躺": "lie", "躺下": "lie"}
# 各姿态胶囊高度占身高比例（躺用完整身高横放）
POSE_HEIGHT = {"stand": 1.0, "sit": 0.52, "crouch": 0.62, "kneel": 0.74, "lie": 1.0}
DEFAULT_SEAT = {"sit": 0.45, "lie": 0.0}

WALK_MAX = 2.2      # 超过这个速度（米/秒）且没写 run 就提醒
TURN_DUR = 0.6
POSE_DUR = 0.8
MOVE_EASE = 0.5


def norm_pose(p):
    if p is None:
        return None
    p = POSE_ALIASES.get(p, p)
    if p not in POSES:
        raise SpecError(f"姿态「{p}」不认识，可用：站/坐/蹲/跪/躺（stand/sit/crouch/kneel/lie）")
    return p


# ================================================================ 胶囊网格

def capsule_coords(h, r, segs=24, rings=6):
    h = max(h, 2 * r + 1e-3)
    pts = [(0.0, 0.0, 0.0)]
    for i in range(1, rings + 1):  # 下半球：从底向赤道
        a = -math.pi / 2 + (math.pi / 2) * i / rings
        z = r + r * math.sin(a)
        rr = r * math.cos(a)
        for k in range(segs):
            t = 2 * math.pi * k / segs
            pts.append((rr * math.cos(t), rr * math.sin(t), z))
    for i in range(0, rings):  # 上半球：从赤道向顶
        a = (math.pi / 2) * i / rings
        z = h - r + r * math.sin(a)
        rr = r * math.cos(a)
        for k in range(segs):
            t = 2 * math.pi * k / segs
            pts.append((rr * math.cos(t), rr * math.sin(t), z))
    pts.append((0.0, 0.0, h))
    return pts


def capsule_faces(segs=24, rings=6):
    faces = []
    nr = 2 * rings  # 环数
    for k in range(segs):  # 底部扇面
        faces.append((0, 1 + (k + 1) % segs, 1 + k))
    for i in range(nr - 1):
        b0 = 1 + i * segs
        b1 = 1 + (i + 1) * segs
        for k in range(segs):
            k1 = (k + 1) % segs
            faces.append((b0 + k, b0 + k1, b1 + k1, b1 + k))
    top = 1 + nr * segs
    last = 1 + (nr - 1) * segs
    for k in range(segs):
        faces.append((last + k, last + (k + 1) % segs, top))
    return faces


def make_capsule_object(name, H, r, color, coll):
    me = bpy.data.meshes.new(name)
    me.from_pydata(capsule_coords(H, r), [], capsule_faces())
    me.update()
    for p in me.polygons:
        p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    ob.color = color
    ob.shape_key_add(name="Basis")
    for pose in ("sit", "crouch", "kneel"):
        sk = ob.shape_key_add(name=pose, from_mix=False)
        sk.value = 0.0  # 新建的形态键默认强度不是 0，必须清零，否则几种姿态会叠在一起
        for v, co in zip(sk.data, capsule_coords(H * POSE_HEIGHT[pose], r)):
            v.co = co
    return ob


# ================================================================ 人偶（头身分开）
# 胶囊转一圈都长一样，Seedance 看不出人朝哪边。人偶仍然没有四肢，但：身体左右宽、前后扁（分得清正面和侧面），
# 头略往前探，脸是浅色、后脑是深色（分得清正面和背面）。

FIGURES = ("head", "capsule")
FIGURE_ALIASES = {"人偶": "head", "头身": "head", "胶囊": "capsule"}
SKIN = "#e9dccb"
HAIR = "#2a2522"
# 身体外形，按身高 1.75 米、半径 0.22 米：(高度, 半宽, 半厚)，+Y = 正前方
BODY_PROFILE = [
    (0.000, 0.100, 0.080), (0.020, 0.125, 0.100), (0.080, 0.145, 0.110), (0.500, 0.158, 0.114),
    (0.950, 0.176, 0.118), (1.250, 0.198, 0.124), (1.370, 0.212, 0.122), (1.430, 0.200, 0.112),
    (1.470, 0.160, 0.092), (1.495, 0.090, 0.060)]
BODY_TOP = BODY_PROFILE[-1][0]
BODY_DEPTH = max(p[2] for p in BODY_PROFILE)
HEAD_R = (0.092, 0.112, 0.125)   # 头：半宽、半厚（前后）、半高
HEAD_FWD = 0.022                 # 头中心比身体中线靠前多少
NECK = (0.052, 1.42, 1.58)       # 颈：半径、底、顶


def norm_figure(f):
    f = FIGURE_ALIASES.get(f, f)
    if f not in FIGURES:
        raise SpecError(f"人物造型「{f}」不认识，可用：head（头身分开的人偶，默认）/ capsule（旧版纯胶囊）")
    return f


def loft(profile, sv, sh, y0=0.0, segs=32, sub=4):
    """按 (高度, 半宽, 半厚) 截面放样成一个封闭网格。sv 竖向缩放，sh 横向缩放。"""
    rings = []
    for i in range(len(profile) - 1):
        a, b = profile[i], profile[i + 1]
        for k in range(sub):
            u = k / sub
            w = (1 - math.cos(math.pi * u)) / 2  # 截面之间平滑过渡
            rings.append((mu.lerp(a[0], b[0], u), mu.lerp(a[1], b[1], w), mu.lerp(a[2], b[2], w)))
    rings.append(profile[-1])
    pts = [(0.0, y0, rings[0][0] * sv)]
    for z, rx, ry in rings:
        for q in range(segs):
            t = 2 * math.pi * q / segs
            pts.append((rx * sh * math.cos(t), y0 + ry * sh * math.sin(t), z * sv))
    pts.append((0.0, y0, (rings[-1][0] + 0.008) * sv))
    faces = [(0, 1 + (q + 1) % segs, 1 + q) for q in range(segs)]
    for i in range(len(rings) - 1):
        b0, b1 = 1 + i * segs, 1 + (i + 1) * segs
        for q in range(segs):
            q1 = (q + 1) % segs
            faces.append((b0 + q, b0 + q1, b1 + q1, b1 + q))
    top, last = len(pts) - 1, 1 + (len(rings) - 1) * segs
    faces += [(last + q, last + (q + 1) % segs, top) for q in range(segs)]
    return pts, faces


def ellipsoid(rx, ry, rz, c, segs=32, rings=16):
    cx, cy, cz = c
    pts = [(cx, cy, cz - rz)]
    for i in range(1, rings):
        a = -math.pi / 2 + math.pi * i / rings
        k, z = math.cos(a), cz + rz * math.sin(a)
        for q in range(segs):
            t = 2 * math.pi * q / segs
            pts.append((cx + rx * k * math.cos(t), cy + ry * k * math.sin(t), z))
    pts.append((cx, cy, cz + rz))
    faces = [(0, 1 + (q + 1) % segs, 1 + q) for q in range(segs)]
    for i in range(rings - 2):
        b0, b1 = 1 + i * segs, 1 + (i + 1) * segs
        for q in range(segs):
            q1 = (q + 1) % segs
            faces.append((b0 + q, b0 + q1, b1 + q1, b1 + q))
    top, last = len(pts) - 1, 1 + (rings - 2) * segs
    faces += [(last + q, last + (q + 1) % segs, top) for q in range(segs)]
    return pts, faces


def mesh_object(name, pts, faces, color, coll, parent=None):
    used = sorted({i for f in faces for i in f})
    remap = {o: n for n, o in enumerate(used)}
    me = bpy.data.meshes.new(name)
    me.from_pydata([pts[i] for i in used], [], [tuple(remap[i] for i in f) for f in faces])
    me.update()
    for p in me.polygons:
        p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    ob.color = color
    ob.parent = parent
    return ob


def make_figure(name, H, r, color, coll, hair=None):
    """头身分开的人偶。返回 (身体, 头部空物体)。头部空物体的 z 要随姿态下移（站立时为 0）。"""
    sv, sh = H / 1.75, r / 0.22
    body = mesh_object(f"{name}_体", *loft(BODY_PROFILE, sv, sh), color, coll)
    body.shape_key_add(name="Basis")
    top = BODY_TOP * sv
    for pose in ("sit", "crouch", "kneel"):
        # 姿态变矮时头整体下移，身体顶部跟着下移同样的距离
        k = max(0.1, (top - H * (1 - POSE_HEIGHT[pose])) / top)
        sk = body.shape_key_add(name=pose, from_mix=False)
        sk.value = 0.0  # 新建的形态键默认强度不是 0，必须清零
        for v in sk.data:
            v.co.z *= k
    head = bpy.data.objects.new(f"{name}_头", None)
    head.empty_display_type = 'PLAIN_AXES'
    head.empty_display_size = 0.15
    coll.objects.link(head)
    head.parent = body
    nr, n0, n1 = NECK
    mesh_object(f"{name}_颈", *loft([(n0, nr, nr), (n1, nr, nr)], sv, sv, y0=0.012 * sv, sub=1), color, coll, head)
    hx, hy, hz = (v * sv for v in HEAD_R)
    hc = (0.0, HEAD_FWD * sv, H - hz)
    pts, faces = ellipsoid(hx, hy, hz, hc)
    face, back = [], []
    for f in faces:  # 头的前半部分、发际线以下是脸，其余是后脑；共用边界顶点，没有缝
        cy = sum(pts[i][1] for i in f) / len(f)
        cz = sum(pts[i][2] for i in f) / len(f)
        (face if (cy - hc[1]) / hy > 0.12 and (cz - hc[2]) / hz < 0.42 else back).append(f)
    mesh_object(f"{name}_脸", pts, face, color_linear(SKIN), coll, head)
    mesh_object(f"{name}_后脑", pts, back, hair or color_linear(HAIR), coll, head)
    return body, head


# ================================================================ 解析与计算

class Actor:
    def __init__(self, spec, index, figure="head"):
        self.id = str(spec.get("id") or spec.get("name") or f"P{index + 1}")
        self.name = spec.get("name", self.id)
        self.H = float(spec.get("height", 1.75))
        self.r = float(spec.get("radius", 0.22))
        self.color_spec = spec.get("color", ACTOR_PALETTE[index % len(ACTOR_PALETTE)])
        self.color = color_linear(self.color_spec)
        self.figure = norm_figure(spec.get("figure", figure))
        self.hair = color_linear(spec.get("hair", HAIR))
        if self.figure == "head":
            self.head_r = HEAD_R[2] * self.H / 1.75           # 头的半高
            self.lie_lift = BODY_DEPTH * self.r / 0.22        # 躺下时身体中线离床面的高度
        else:
            self.head_r = self.lie_lift = self.r
        self.run = bool(spec.get("run", False))
        self.ghost = bool(spec.get("ghost", False))  # 允许穿过物体（不做碰撞检查）
        self.ignore = set(spec.get("ignore", []))    # 允许接触的物体，比如自己坐的椅子、躺的床
        keys = sorted(spec.get("keys", []), key=lambda k: float(k.get("t", 0)))
        if not keys or "pos" not in keys[0]:
            raise SpecError(f"人物「{self.name}」的第一个 key 必须写 pos（初始位置）")
        self.keys = keys
        # 逐帧结果
        self.pos = []      # (x, y)
        self.base_z = []   # 地面高度
        self.facing = []   # 罗盘角（连续展开）
        self.weights = []  # {pose: w}
        self.moving = []   # bool
        self.seat = []     # 当前座面/躺面高度
        self.notes = []

    # ---------- 位置 ----------
    def compute_positions(self, n_frames, query):
        segs = []  # (dep, arr, Polyline, ease, key)
        prev = self.keys[0]
        cur_pos = list(prev["pos"])
        cur_pose = norm_pose(prev.get("pose", "stand"))
        prev_t = float(prev.get("t", 0.0))
        for k in self.keys[1:]:
            t = float(k["t"])
            new_pose = norm_pose(k.get("pose")) or cur_pose
            pose_dur = float(k.get("pose_dur", k.get("dur", POSE_DUR))) if new_pose != cur_pose else 0.0
            if "pos" in k and (mu.dist2d(k["pos"], cur_pos) > 1e-4 or k.get("via")):
                pts = [cur_pos] + [list(p) for p in k.get("via", [])] + [list(k["pos"])]
                path = mu.smooth_path(pts, k.get("round", 0.6))
                arr = t - pose_dur
                if "depart" in k:
                    dep = float(k["depart"])
                elif "speed" in k:
                    dep = arr - path.length / float(k["speed"])
                else:
                    dep = prev_t
                if dep < prev_t - 1e-6:
                    raise SpecError(f"人物「{self.name}」在 {t}s 的移动来不及：需要从 {dep:.2f}s 出发，"
                                    f"但上一个 key 在 {prev_t}s。改晚 t、降低 speed 或删掉 depart。")
                if arr <= dep:
                    raise SpecError(f"人物「{self.name}」在 {t}s 的移动时长为 0，检查 t / depart / pose_dur")
                ein, eout = mu.resolve_ease(k.get("ease"), arr - dep, 0.3, MOVE_EASE)
                segs.append(dict(dep=dep, arr=arr, path=path, ein=ein, eout=eout, key=k))
                cur_pos = list(k["pos"])
            cur_pose = new_pose
            prev_t = t
        self.move_segs = segs

        z = None
        for f in range(1, n_frames + 1):
            t = f2t(f)
            p = list(self.keys[0]["pos"])
            moving = False
            for s in segs:
                if t >= s["arr"]:
                    p = s["path"].at(s["path"].length)
                elif t >= s["dep"]:
                    u = mu.ease_progress(t - s["dep"], s["arr"] - s["dep"], s["ein"], s["eout"])
                    p = s["path"].at(u * s["path"].length)
                    moving = True
                    break
                else:
                    break
            self.pos.append((p[0], p[1]))
            self.moving.append(moving)
            if z is None:
                z0 = float(self.keys[0].get("z", 0.0))
                z = query.floor_z(p[0], p[1], z0, max_up=0.6, default=z0) if query else z0
            else:
                z = query.floor_z(p[0], p[1], z, max_up=0.6, default=z) if query else z
            self.base_z.append(z)
        # 台阶处高度平滑，避免一级一级跳
        sm = mu.critically_damped([[v] for v in self.base_z], 1.0 / FPS, 0.12)
        self.base_z = [v[0] for v in sm]

    def pos_at_frame(self, f):
        return self.pos[max(0, min(len(self.pos) - 1, f - 1))]

    # ---------- 朝向 ----------
    def eval_face(self, spec, f, actors):
        if spec is None:
            return None
        if isinstance(spec, (int, float)):
            return float(spec)
        me = self.pos_at_frame(f)
        if isinstance(spec, (list, tuple)):
            tgt = spec
        else:
            other = actors.get(str(spec))
            if other is None:
                raise SpecError(f"人物「{self.name}」的 face 指向「{spec}」，但没有这个人物 id")
            tgt = other.pos_at_frame(f)
        if mu.dist2d(me, tgt) < 1e-3:
            return None
        return mu.dir_to_facing(tgt[0] - me[0], tgt[1] - me[1])

    def compute_facing(self, n_frames, actors):
        k0 = self.keys[0]
        hold_spec = k0.get("face", 0.0)
        hold_val = self.eval_face(hold_spec, 1, actors)
        if hold_val is None:
            hold_val = 0.0
        # 非移动的转身事件
        events = []
        prev_t = float(k0.get("t", 0))
        for k in self.keys[1:]:
            t = float(k["t"])
            is_move = any(s["key"] is k for s in self.move_segs)
            if "face" in k and not is_move:
                dur = float(k.get("turn_dur", k.get("dur", TURN_DUR)))
                events.append(dict(start=max(prev_t, t - dur), end=t, spec=k["face"]))
            prev_t = t
        out = []
        cur_move = None
        face_before = hold_val
        ev_start_val = {}
        for f in range(1, n_frames + 1):
            t = f2t(f)
            seg = None
            for s in self.move_segs:
                if s["dep"] <= t < s["arr"]:
                    seg = s
                    break
            if seg is not None and not seg["key"].get("face_lock"):
                if cur_move is not seg:
                    cur_move = seg
                    face_before = hold_val
                u = mu.ease_progress(t - seg["dep"], seg["arr"] - seg["dep"], seg["ein"], seg["eout"])
                tan = seg["path"].tangent(u * seg["path"].length)
                head = mu.dir_to_facing(tan[0], tan[1]) if math.hypot(tan[0], tan[1]) > 1e-6 else face_before
                w_in = mu.smoothstep((t - seg["dep"]) / 0.4)
                val = mu.lerp_angle(face_before, head, w_in)
                end_spec = seg["key"].get("face")
                if end_spec is not None:
                    w_out = mu.smoothstep((t - (seg["arr"] - 0.4)) / 0.4)
                    ev = self.eval_face(end_spec, f, actors)
                    if ev is not None and w_out > 0:
                        val = mu.lerp_angle(val, ev, w_out)
                hold_val = val
                out.append(val)
                continue
            if cur_move is not None:  # 刚走完：有 face 就转向它，没有就保持到达时的方向
                hold_spec = cur_move["key"].get("face")
                cur_move = None
            for e in events:  # 已结束的转身事件，转身目标成为之后的朝向
                if not e.get("done") and t >= e["end"]:
                    hold_spec = e["spec"]
                    e["done"] = True
            active = None
            for i, e in enumerate(events):
                if not e.get("done") and e["start"] <= t < e["end"]:
                    active = (i, e)
                    break
            if active:
                i, e = active
                if i not in ev_start_val:
                    ev_start_val[i] = hold_val
                tgt = self.eval_face(e["spec"], f, actors)
                if tgt is None:
                    tgt = hold_val
                s = mu.smoothstep((t - e["start"]) / max(1e-6, e["end"] - e["start"]))
                val = mu.lerp_angle(ev_start_val[i], tgt, s)
            else:
                ev = self.eval_face(hold_spec, f, actors) if hold_spec is not None else None
                val = ev if ev is not None else hold_val
            hold_val = val
            out.append(val)
        # 轻微平滑，转身不会一档一档地跳
        un = mu.unwrap_angles(out)
        self.facing = [v[0] for v in mu.critically_damped([[v] for v in un], 1.0 / FPS, 0.12)]

    # ---------- 姿态 ----------
    def compute_poses(self, n_frames):
        events = []
        cur = norm_pose(self.keys[0].get("pose", "stand"))
        cur_seat = float(self.keys[0].get("seat_h", DEFAULT_SEAT.get(cur, 0.0)))
        init = (cur, cur_seat)
        prev_t = float(self.keys[0].get("t", 0))
        for k in self.keys[1:]:
            t = float(k["t"])
            p = norm_pose(k.get("pose")) or cur
            seat = float(k.get("seat_h", DEFAULT_SEAT.get(p, 0.0))) if p != cur or "seat_h" in k else cur_seat
            if p != cur or abs(seat - cur_seat) > 1e-6:
                dur = float(k.get("pose_dur", k.get("dur", POSE_DUR)))
                events.append(dict(start=max(prev_t, t - dur), end=t, frm=(cur, cur_seat), to=(p, seat)))
                cur, cur_seat = p, seat
            prev_t = t
        for f in range(1, n_frames + 1):
            t = f2t(f)
            state = init
            w = {init[0]: 1.0}
            seat = init[1]
            for e in events:
                if t >= e["end"]:
                    state = e["to"]
                    w = {state[0]: 1.0}
                    seat = state[1]
                elif t >= e["start"]:
                    s = mu.smoothstep((t - e["start"]) / (e["end"] - e["start"]))
                    w = {}
                    w[e["frm"][0]] = w.get(e["frm"][0], 0) + (1 - s)
                    w[e["to"][0]] = w.get(e["to"][0], 0) + s
                    seat = mu.lerp(e["frm"][1], e["to"][1], s)
                    break
                else:
                    break
            self.weights.append(w)
            self.seat.append(seat)

    # ---------- 关键点（给相机瞄准和检查用） ----------
    def points(self, f):
        """返回 dict：base（脚底中心）、top（头顶）、eye（眼睛）、head（头中心）、body（身体中部）。"""
        i = max(0, min(len(self.pos) - 1, f - 1))
        x, y = self.pos[i]
        z = self.base_z[i]
        w = self.weights[i]
        seat = self.seat[i]
        wl = w.get("lie", 0.0)
        hu = self.upright_height(w)
        raise_z = seat if (w.get("sit", 0) + wl) > 0 else 0.0
        fx, fy = mu.facing_to_dir(self.facing[i])
        # 竖直姿态
        top_up = (x, y, z + raise_z + hu)
        head_up = (x, y, z + raise_z + hu - self.head_r)
        eye_up = (x, y, z + raise_z + hu - 0.12 * self.H / 1.75)
        body_up = (x, y, z + raise_z + hu * 0.55)
        if wl <= 1e-6:
            return dict(base=(x, y, z), top=top_up, head=head_up, eye=eye_up, body=body_up)
        # 躺：头朝 facing 方向，脸朝上
        hz = z + seat + self.lie_lift
        head_l = (x + fx * (self.H / 2 - self.head_r), y + fy * (self.H / 2 - self.head_r), hz)
        body_l = (x, y, hz)
        mix = lambda a, b: tuple(mu.lerp(a[k], b[k], wl) for k in range(3))
        return dict(base=(x, y, z), top=mix(top_up, (head_l[0], head_l[1], hz + self.head_r)),
                    head=mix(head_up, head_l), eye=mix(eye_up, head_l), body=mix(body_up, body_l))

    def upright_height(self, w):
        """当前姿态下从座面量起的身体总长（躺下时按横放前的长度算）。"""
        hu = sum(w.get(p, 0.0) * POSE_HEIGHT[p] for p in ("stand", "sit", "crouch", "kneel")) * self.H
        return hu + w.get("lie", 0.0) * self.H


# ================================================================ 检查

def check_actor(a, query, n_frames):
    issues = []
    # 速度
    sp = [0.0]
    for i in range(1, len(a.pos)):
        sp.append(mu.dist2d(a.pos[i - 1], a.pos[i]) * FPS)
    for s in a.move_segs:
        f0, f1 = int(s["dep"] * FPS) + 1, int(s["arr"] * FPS) + 1
        seg_sp = sp[f0:f1 + 1] or [0]
        peak = max(seg_sp)
        avg = s["path"].length / (s["arr"] - s["dep"])
        rec = dict(start=round(s["dep"], 2), end=round(s["arr"], 2), length=round(s["path"].length, 2),
                   avg_speed=round(avg, 2), peak_speed=round(peak, 2))
        a.notes.append(("move", rec))
        if peak > WALK_MAX and not (a.run or s["key"].get("run")):
            issues.append(dict(level="警告", actor=a.name, t0=rec["start"], t1=rec["end"],
                               msg=f"走得太快：最快 {peak:.1f} 米/秒（正常走 1.2–1.4，快走约 1.8）。"
                                   f"如果是跑，在这个 key 写 \"run\": true；否则延长时间。"))
        elif avg < 0.35 and s["path"].length > 1.0:
            issues.append(dict(level="提示", actor=a.name, t0=rec["start"], t1=rec["end"],
                               msg=f"走得很慢：平均 {avg:.2f} 米/秒，像在挪步。确认是否需要。"))
    if a.ghost or query is None or query.solid is None:
        return issues
    # 穿墙 / 擦碰（只在站立时查）
    bad = []
    for f in range(2, n_frames + 1):
        i = f - 1
        if a.weights[i].get("stand", 0) < 0.9:
            continue
        (x0, y0), (x1, y1) = a.pos[i - 1], a.pos[i]
        z = a.base_z[i]
        hit_obj = None
        for hz in (0.35, 1.2):
            if (x0, y0) != (x1, y1):
                h = query.first_hit((x0, y0, z + hz), (x1, y1, z + hz))
                if h and h[0] not in a.ignore:
                    hit_obj = h[0]
                    break
            ins = query.inside_solid((x1, y1, z + hz))
            if ins and ins not in a.ignore:
                hit_obj = ins
                break
            nr = query.nearest_solid((x1, y1, z + hz), a.r)
            if nr and nr[1] < a.r - 0.04 and nr[0] not in a.ignore:
                hit_obj = nr[0]
                break
        if hit_obj:
            bad.append((f, hit_obj))
    for f0, f1, obj in group_frames(bad):
        issues.append(dict(level="警告", actor=a.name, t0=round(f2t(f0), 2), t1=round(f2t(f1), 2),
                           msg=f"穿进或擦到「{obj}」。挪开路径点，或给这个人物写 \"ghost\": true 表示允许。"))
    return issues


def check_overlaps(actors, n_frames):
    issues = []
    lst = list(actors.values())
    for i in range(len(lst)):
        for j in range(i + 1, len(lst)):
            a, b = lst[i], lst[j]
            bad = []
            for f in range(1, n_frames + 1):
                k = f - 1
                if a.weights[k].get("lie", 0) > 0.1 or b.weights[k].get("lie", 0) > 0.1:
                    continue
                if abs(a.base_z[k] - b.base_z[k]) > 1.0:
                    continue
                if mu.dist2d(a.pos[k], b.pos[k]) < a.r + b.r - 0.02:
                    bad.append((f, b.name))
            for f0, f1, _ in group_frames(bad):
                issues.append(dict(level="警告", actor=f"{a.name}/{b.name}", t0=round(f2t(f0), 2), t1=round(f2t(f1), 2),
                                   msg="两人身体重叠。拉开距离或错开时间。"))
    return issues


def group_frames(items):
    """[(帧, 标签)] → 连续区间 [(起帧, 止帧, 标签)]。"""
    out = []
    for f, tag in items:
        if out and out[-1][2] == tag and f <= out[-1][1] + 1:
            out[-1] = (out[-1][0], f, tag)
        else:
            out.append((f, f, tag))
    return out


# ================================================================ 主流程

def build_actors(blocking, n_frames, query, log):
    specs = blocking.get("actors", [])
    figure = norm_figure(blocking.get("figure", "head"))
    actors = {}
    for i, s in enumerate(specs):
        a = Actor(s, i, figure)
        if a.id in actors:
            raise SpecError(f"人物 id「{a.id}」重复")
        actors[a.id] = a
    for a in actors.values():
        a.compute_positions(n_frames, query)
    for a in actors.values():
        a.compute_facing(n_frames, actors)
        a.compute_poses(n_frames)

    coll = ensure_collection(COLL_ACTORS)
    prefs = bpy.context.preferences.edit
    prefs.keyframe_new_interpolation_type = 'LINEAR'
    for a in actors.values():
        root = bpy.data.objects.new(f"{a.id}_{a.name}", None)
        root.empty_display_type = 'PLAIN_AXES'   # 本地 +Y = 人物正前方
        root.empty_display_size = 0.6
        root.rotation_mode = 'XYZ'
        coll.objects.link(root)
        if a.figure == "head":
            body, head = make_figure(f"{a.id}_{a.name}", a.H, a.r, a.color, coll, a.hair)
        else:
            body, head = make_capsule_object(f"{a.id}_{a.name}_体", a.H, a.r, a.color, coll), None
        body.parent = root
        body["pv_actor"] = a.id
        root["pv_actor"] = a.id
        # 先转身背对头的方向、再往后躺：头朝 facing，脸朝上（Z 先转，所以用 ZYX 顺序）
        body.rotation_mode = 'ZYX'
        keys = body.data.shape_keys.key_blocks
        for f in range(1, n_frames + 1):
            i = f - 1
            x, y = a.pos[i]
            root.location = (x, y, a.base_z[i])
            root.rotation_euler = (0.0, 0.0, math.radians(-a.facing[i]))
            root.keyframe_insert("location", frame=f)
            root.keyframe_insert("rotation_euler", index=2, frame=f)
            w = a.weights[i]
            wl = w.get("lie", 0.0)
            raise_z = a.seat[i] if (w.get("sit", 0) + wl) > 0 else 0.0
            body.location = (0.0, -a.H / 2 * wl, raise_z + a.lie_lift * wl)
            body.rotation_euler = (math.radians(-90.0 * wl), 0.0, math.radians(180.0 * mu.smoothstep(wl / 0.4)))
            body.keyframe_insert("location", frame=f)
            body.keyframe_insert("rotation_euler", index=0, frame=f)
            body.keyframe_insert("rotation_euler", index=2, frame=f)
            for p in ("sit", "crouch", "kneel"):
                keys[p].value = w.get(p, 0.0)
                keys[p].keyframe_insert("value", frame=f)
            if head is not None:
                head.location = (0.0, 0.0, a.upright_height(w) - a.H)
                head.keyframe_insert("location", index=2, frame=f)
        log(f"人物「{a.name}」({a.id}) 身高 {a.H}m，{len(a.move_segs)} 段移动，造型 {a.figure}")
    issues = []
    for a in actors.values():
        issues += check_actor(a, query, n_frames)
    issues += check_overlaps(actors, n_frames)
    return actors, issues
