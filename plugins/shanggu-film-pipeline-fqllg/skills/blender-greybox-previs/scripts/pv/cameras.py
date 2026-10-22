# -*- coding: utf-8 -*-
"""镜头表 shots.json → 每个镜头一台相机，逐帧烘焙运镜，时间轴标记负责切镜。

机位关键点（key）五种写法：
  环绕式：{"t":0, "target":"A", "size":"中景"|"dist":3, "az":200|"az_rel":30, "h":1.6|"el":10}
  世界式：{"t":0, "pos":[x,y,z], "look":"A"|[x,y,z]|{"between":["A","B"]}}
  过肩式：{"t":0, "ots":{"over":"A", "to":"B", "side":"right"}}
  身后跟：{"t":0, "follow":"A", "dist":2.8, "side":0.4}   沿人物走过的路线跟在身后
  前方引：{"t":0, "lead":"A", "dist":2.5}                沿人物将要走的路线在前面倒退着拍
通用：lens 焦距、frame 主体在画面的位置 [x,y]、roll、ease、via（世界式路径点）、keep_size（希区柯克变焦）
"""
import math
import bpy
from mathutils import Matrix, Euler

from .spec import SpecError, FPS, t2f, f2t, snap_time
from . import mathutil as mu
from .scene_builder import ensure_collection, COLL_CAMS, COLL_SCENE

LAG = 0.35        # 跟拍时相机晚多少秒跟上
LOOK_LAG = 0.2    # 镜头对准点的平滑
WARMUP = 1.0      # 平滑器预热秒数


# ================================================================ 解析

def parse_shots(shots_spec, log):
    shots = shots_spec.get("shots", [])
    if not shots:
        raise SpecError("shots.json 里没有镜头")
    fixed = []
    out = []
    for i, s in enumerate(shots):
        sid = str(s.get("id", f"镜{i + 1:02d}"))
        st, a1 = snap_time(float(s["start"]))
        en, a2 = snap_time(float(s["end"]))
        if a1 or a2:
            fixed.append(sid)
        if en - st < 1.0 / FPS:
            raise SpecError(f"{sid} 时长为 0")
        if not s.get("keys"):
            raise SpecError(f"{sid} 没有机位关键点 keys")
        out.append(dict(s, id=sid, start=st, end=en, index=i))
    out.sort(key=lambda s: s["start"])
    if abs(out[0]["start"]) > 1e-6:
        raise SpecError(f"第一个镜头要从 0 秒开始（现在是 {out[0]['start']}）")
    for a, b in zip(out, out[1:]):
        if b["start"] < a["end"] - 1e-6:
            raise SpecError(f"{a['id']} 和 {b['id']} 时间重叠（{a['end']} > {b['start']}）")
        if b["start"] > a["end"] + 1e-6:
            raise SpecError(f"{a['id']} 和 {b['id']} 之间有空档（{a['end']}～{b['start']}），镜头要首尾相接")
    if fixed:
        log(f"这些镜头的起止时间不在整帧上，已对齐到最近的帧：{', '.join(fixed)}")
    return out


# ================================================================ 平滑后的人物数据

class SmoothedActors:
    """每个镜头内单独平滑人物位置/朝向（镜头开始前预热，避免把上个镜头的滞后带进来）。"""

    def __init__(self, actors, f0, f1, lag, look_lag):
        self.f0, self.f1 = f0, f1
        self.data = {}
        w0 = max(1, f0 - int(WARMUP * FPS))
        for aid, a in actors.items():
            frames = list(range(w0, f1 + 1))
            raw_pts = [a.points(f) for f in frames]
            base = [list(p["base"]) for p in raw_pts]
            face = [[a.facing[min(len(a.facing), f) - 1]] for f in frames]
            d = {}
            d["anchor"] = mu.critically_damped(base, 1 / FPS, lag, init=base[0])
            # 相对朝向的机位用更慢的朝向平滑，人物转身时相机不会猛甩
            d["face"] = mu.critically_damped(face, 1 / FPS, max(lag, 0.8), init=face[0])
            for key in ("eye", "head", "body", "top", "base"):
                ser = [list(p[key]) for p in raw_pts]
                d[key] = mu.critically_damped(ser, 1 / FPS, look_lag, init=ser[0])
            d["raw"] = raw_pts
            d["frames"] = frames
            self.data[aid] = d
        self.actors = actors
        self.lag = lag
        self._trail = {}

    # ---------- 沿人物当前这段行走路线取点：跟拍 / 引路拍 ----------
    @staticmethod
    def _trail_point(a, fr, dist, lead):
        """只看人物当前（或刚走完的）这一段路线；超出路线两端时顺着端点方向延伸。返回 (x, y, 行进方向)。"""
        t = f2t(fr)
        seg, along = None, 0.0
        for s in a.move_segs:
            if s["dep"] <= t < s["arr"]:
                u = mu.ease_progress(t - s["dep"], s["arr"] - s["dep"], s["ein"], s["eout"])
                seg, along = s, u * s["path"].length
                break
        if seg is None:
            done = [s for s in a.move_segs if s["arr"] <= t]
            if done:
                seg, along = done[-1], done[-1]["path"].length
        if seg is None:  # 还没开始走：按朝向放在身前/身后
            x, y = a.pos[fr - 1]
            fx, fy = mu.facing_to_dir(a.facing[fr - 1])
            k = dist if lead else -dist
            return x + fx * k, y + fy * k, (fx, fy)
        path = seg["path"]
        L = along + (dist if lead else -dist)

        def unit(v):
            n = math.hypot(v[0], v[1]) or 1.0
            return (v[0] / n, v[1] / n)
        if L > path.length:
            e = path.at(path.length)
            d = unit(path.tangent(path.length))
            return e[0] + d[0] * (L - path.length), e[1] + d[1] * (L - path.length), d
        if L < 0:
            s0 = path.at(0)
            d = unit(path.tangent(0))
            return s0[0] + d[0] * L, s0[1] + d[1] * L, d
        p = path.at(L)
        return p[0], p[1], unit(path.tangent(L))

    def trail(self, aid, dist, side, lead, h, f):
        key = (aid, round(dist, 3), round(side, 3), lead, None if h is None else round(h, 3))
        if key not in self._trail:
            a = self.actors[aid]
            frames = self.data[aid]["frames"]
            eye_h = a.points(frames[0])["eye"][2] - a.base_z[frames[0] - 1]
            hh = float(h) if h is not None else eye_h + 0.05
            raw = []
            for fr in frames:
                x, y, (tx, ty) = self._trail_point(a, fr, dist, lead)
                if abs(side) > 1e-6:
                    x, y = x + ty * side, y - tx * side  # 行进方向的右侧
                raw.append([x, y, a.base_z[fr - 1] + hh])
            self._trail[key] = mu.critically_damped(raw, 1 / FPS, self.lag, init=raw[0])
        d = self.data[aid]
        i = max(0, min(len(d["frames"]) - 1, f - d["frames"][0]))
        return tuple(self._trail[key][i])

    def get(self, aid, key, f):
        d = self.data[aid]
        i = f - d["frames"][0]
        i = max(0, min(len(d["frames"]) - 1, i))
        v = d[key][i]
        return v[0] if key == "face" else tuple(v)

    def height(self, aid):
        return self.actors[aid].H


# ================================================================ 单个 key 在某一帧的机位

def _actor_id(ref, actors):
    if isinstance(ref, str):
        aid = ref.split(".")[0]
        if aid not in actors:
            raise SpecError(f"镜头里引用了人物「{ref}」，但站位表里没有这个 id（现有：{', '.join(actors)}）")
        return aid
    return None


def resolve_point(ref, sm, f, actors, default_part="eye"):
    """把 "A" / "A.body" / [x,y,z] / {"between":[...]} 解析成世界坐标。"""
    if ref is None:
        return None
    if isinstance(ref, dict) and "between" in ref:
        pts = [resolve_point(r, sm, f, actors, default_part) for r in ref["between"]]
        return tuple(sum(p[k] for p in pts) / len(pts) for k in range(3))
    if isinstance(ref, (list, tuple)):
        if len(ref) == 2:
            return (ref[0], ref[1], 1.5)
        return tuple(ref)
    aid = _actor_id(ref, actors)
    part = ref.split(".")[1] if "." in ref else default_part
    if part not in ("eye", "head", "body", "top", "base"):
        raise SpecError(f"「{ref}」的部位写法不对，可用 .eye .head .body .top .base")
    return sm.get(aid, part, f)


def referenced_actors(ref, actors):
    out = []
    if isinstance(ref, dict) and "between" in ref:
        for r in ref["between"]:
            out += referenced_actors(r, actors)
    elif isinstance(ref, str):
        out.append(_actor_id(ref, actors))
    return out


def auto_frame_y(coverage):
    """根据画面竖直覆盖高度（米）自动定眼睛在画面里的高度，保证头顶留白合适。"""
    pts = [(0.0, 0.64), (1.05, 0.64), (1.45, 0.72), (2.3, 0.78), (5.0, 0.62), (12.0, 0.55)]
    if coverage <= pts[0][0]:
        return pts[0][1]
    for (c0, y0), (c1, y1) in zip(pts, pts[1:]):
        if coverage <= c1:
            return mu.lerp(y0, y1, (coverage - c0) / (c1 - c0))
    return pts[-1][1]


class KeyEval:
    """把一个 key 在第 f 帧求成具体参数。"""

    def __init__(self, key, shot, ctx):
        self.k = key
        self.shot = shot
        self.ctx = ctx
        self.t = float(key.get("t", shot["start"]))
        self.lens = float(key.get("lens", shot.get("lens", ctx["defaults"].get("lens", 35))))
        if "ots" in key:
            self.mode = "ots"
        elif "follow" in key or "lead" in key:
            self.mode = "trail"
        elif "pos" in key:
            self.mode = "world"
        elif "target" in key:
            self.mode = "orbit"
        else:
            raise SpecError(f"{shot['id']} 在 {self.t}s 的机位要写 target（环绕式）、pos（世界式）、"
                            f"ots（过肩）、follow（身后跟拍）或 lead（前方引路拍）之一")

    def trail_actor(self):
        return self.k.get("follow") or self.k.get("lead")

    def subjects(self, actors):
        k = self.k
        out = []
        if self.mode == "orbit":
            out += referenced_actors(k["target"], actors)
        if self.mode == "ots":
            out += referenced_actors(k["ots"]["to"], actors)
        if self.mode == "trail":
            out += referenced_actors(self.trail_actor(), actors)
        if "look" in k:
            out += referenced_actors(k["look"], actors)
        return out

    def orbit_params(self, f):
        """环绕式的参数（未换算成位置）。"""
        k, ctx, sm, actors = self.k, self.ctx, self.ctx["sm"], self.ctx["actors"]
        res = ctx["res"]
        tgt = k["target"]
        aid = _actor_id(tgt, actors) if isinstance(tgt, str) else None
        H = actors[aid].H if aid else 1.75
        if "dist" in k:
            dist = float(k["dist"])
        elif "size" in k:
            dist = mu.dist_for_size(k["size"], self.lens, res[0], res[1], H)
            if isinstance(tgt, dict) and "between" in tgt:  # 双人：保证横向放得下
                pts = [resolve_point(r, sm, f, actors) for r in tgt["between"]]
                sep = max(mu.dist2d(pts[0], pts[-1]), 0.5)
                hf, _ = mu.fovs(self.lens, res[0], res[1])
                dist = max(dist, (sep + 1.2) / (2 * math.tan(hf / 2)))
        else:
            raise SpecError(f"{self.shot['id']} 在 {self.t}s 的环绕式机位要写 dist（米）或 size（景别）")
        if "az" in k:
            az = float(k["az"])
        elif "az_rel" in k:
            if not aid:
                raise SpecError(f"{self.shot['id']}：az_rel 只能用在 target 是人物时")
            az = sm.get(aid, "face", f) + float(k["az_rel"])
        else:
            raise SpecError(f"{self.shot['id']} 在 {self.t}s 的环绕式机位要写 az（绝对方位）或 az_rel（相对人物朝向）")
        return dict(dist=dist, az=az, h=k.get("h"), el=k.get("el"), aid=aid)

    def aim_ref(self):
        k = self.k
        if "look" in k:
            return k["look"]
        if self.mode == "orbit":
            return k["target"]
        if self.mode == "ots":
            return k["ots"]["to"]
        if self.mode == "trail":
            return self.trail_actor()
        return None

    def anchor(self, f):
        """环绕中心（平滑后）。"""
        k, sm, actors = self.k, self.ctx["sm"], self.ctx["actors"]
        tgt = k["target"]
        if isinstance(tgt, str):
            return sm.get(_actor_id(tgt, actors), "anchor", f)
        if isinstance(tgt, dict) and "between" in tgt:
            pts = [sm.get(_actor_id(r, actors), "anchor", f) for r in tgt["between"]]
            return tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
        p = resolve_point(tgt, sm, f, actors)
        return (p[0], p[1], 0.0)

    def eval(self, f, orbit_override=None):
        """返回 dict(pos, aim, lens, frame, roll)。"""
        k, ctx, sm, actors = self.k, self.ctx, self.ctx["sm"], self.ctx["actors"]
        res = ctx["res"]
        aim = resolve_point(self.aim_ref(), sm, f, actors) if self.aim_ref() is not None else None
        if self.mode == "trail":
            aid = _actor_id(self.trail_actor(), actors)
            dist = float(k.get("dist", 2.5))
            pos = sm.trail(aid, dist, float(k.get("side", 0.0)), "lead" in k, k.get("h"), f)
        elif self.mode == "world":
            pos = tuple(k["pos"]) if len(k["pos"]) == 3 else (k["pos"][0], k["pos"][1], 1.6)
            if aim is None:
                # yaw 用罗盘角（0 = 看向 +Y，90 = 看向 +X，顺时针），与人物朝向同一规则
                yaw = -float(k.get("yaw", 0.0))
                pitch = float(k.get("pitch", 0.0))
                d = mu.view_dir(yaw, pitch)
                aim = tuple(pos[i] + d[i] * 10 for i in range(3))
        elif self.mode == "orbit":
            p = orbit_override or self.orbit_params(f)
            anc = self.anchor(f)
            if aim is None:
                aim = (anc[0], anc[1], anc[2] + 1.5)
            if p.get("el") is not None:
                el = math.radians(float(p["el"]))
                horiz = p["dist"] * math.cos(el)
                z = aim[2] + p["dist"] * math.sin(el)
            else:
                horiz = p["dist"]
                h = p.get("h")
                z = anc[2] + (float(h) if h is not None else (aim[2] - anc[2]))
            dx, dy = mu.facing_to_dir(p["az"])
            pos = (anc[0] + dx * horiz, anc[1] + dy * horiz, z)
        else:  # ots
            o = k["ots"]
            a_id = _actor_id(o["over"], actors)
            pa = sm.get(a_id, "anchor", f)
            pe = sm.get(a_id, "eye", f)
            pb = resolve_point(o["to"], sm, f, actors)
            dx, dy = pb[0] - pa[0], pb[1] - pa[1]
            L = math.hypot(dx, dy) or 1.0
            dx, dy = dx / L, dy / L
            side = 1.0 if o.get("side", "right") == "right" else -1.0
            rx, ry = dy * side, -dx * side
            back = float(o.get("back", 1.1))      # 相机在前景人物身后多远
            off = float(o.get("offset", 0.45))    # 相机偏向肩膀一侧多远
            z = pa[2] + float(o["h"]) if "h" in o else pe[2] + 0.08
            pos = (pa[0] - dx * back + rx * off, pa[1] - dy * back + ry * off, z)
            if aim is None:
                aim = pb
        # 画面位置
        if "frame" in k:
            fr = tuple(k["frame"])
        else:
            dist = mu.dist3d(pos, aim)
            _, vf = mu.fovs(self.lens, res[0], res[1])
            cov = 2 * dist * math.tan(vf / 2)
            sx = 0.5
            if self.mode == "ots":
                sx = 0.62 if k["ots"].get("side", "right") == "right" else 0.38
            aim_ref = self.aim_ref()
            part = aim_ref.split(".")[1] if isinstance(aim_ref, str) and "." in aim_ref else "eye"
            sy = auto_frame_y(cov) if (aim_ref is not None and not isinstance(aim_ref, list) and part in ("eye", "head")) else 0.5
            fr = (sx, sy)
        return dict(pos=pos, aim=aim, lens=self.lens, frame=fr, roll=float(k.get("roll", 0.0)))


# ================================================================ 镜头内插值

def eval_shot(shot, ctx):
    """逐帧求一个镜头的相机。返回 [(frame, pos, yaw, pitch, roll, lens)]。"""
    keys = [KeyEval(k, shot, ctx) for k in shot["keys"]]
    keys.sort(key=lambda e: e.t)
    for e in keys:
        if e.t < shot["start"] - 1e-6 or e.t > shot["end"] + 1e-6:
            raise SpecError(f"{shot['id']} 的机位时间 {e.t}s 不在镜头区间 {shot['start']}～{shot['end']} 内（key 的 t 用整片绝对时间）")
    f0, f1 = t2f(shot["start"]), t2f(shot["end"]) - 1
    res = ctx["res"]
    rows = []
    hh = None
    hh_amt = float(shot.get("handheld", ctx["defaults"].get("handheld", 0.0)))
    if hh_amt > 0:
        hh = mu.handheld_offsets(hh_amt, seed=shot["index"] + 1)
    prev_yaw = None
    for f in range(f0, f1 + 1):
        t = f2t(f)
        # 找所在区间
        if t <= keys[0].t or len(keys) == 1:
            st = keys[0].eval(f)
        elif t >= keys[-1].t:
            st = keys[-1].eval(f)
        else:
            j = max(i for i in range(len(keys)) if keys[i].t <= t)
            k0, k1 = keys[j], keys[j + 1]
            T = k1.t - k0.t
            ein, eout = mu.resolve_ease(k1.k.get("ease"), T)
            u = mu.ease_progress(t - k0.t, T, ein, eout)
            st = interp(k0, k1, u, f)
        yaw, pitch = mu.aim_with_framing(st["pos"], st["aim"], st["frame"][0], st["frame"][1], st["lens"], res[0], res[1])
        pos = list(st["pos"])
        roll = st["roll"]
        if hh:
            o = hh(t)
            pos = [pos[0] + o[0], pos[1] + o[1], pos[2] + o[2]]
            yaw += o[3]
            pitch += o[4]
            roll += o[5]
        if prev_yaw is not None:
            yaw = prev_yaw + mu.angle_diff(prev_yaw, yaw)
        prev_yaw = yaw
        rows.append(dict(frame=f, pos=tuple(pos), yaw=yaw, pitch=pitch, roll=roll, lens=st["lens"], aim=st["aim"]))
    return rows, keys


def interp(k0, k1, u, f):
    st0, st1 = k0.eval(f), k1.eval(f)
    same_orbit = (k0.mode == "orbit" and k1.mode == "orbit" and k0.k["target"] == k1.k["target"])
    if same_orbit:
        # 同一个环绕中心：插值"距离、方位角、高度"，相机走圆弧而不是直线抄近路
        p0, p1 = k0.orbit_params(f), k1.orbit_params(f)
        anc = k0.anchor(f)
        el = None
        if p0.get("el") is not None or p1.get("el") is not None:
            el = mu.lerp(float(p0.get("el") or 0.0), float(p1.get("el") or 0.0), u)
        h0v = st0["pos"][2] - anc[2]
        h1v = st1["pos"][2] - anc[2]
        p = dict(dist=mu.lerp(p0["dist"], p1["dist"], u), az=mu.lerp(p0["az"], p1["az"], u),
                 h=mu.lerp(h0v, h1v, u) if el is None else None, el=el)
        pos = k1.eval(f, p)["pos"]
    else:
        via = k1.k.get("via")
        if via:
            pts = ([list(st0["pos"])] + [list(v) if len(v) == 3 else [v[0], v[1], st0["pos"][2]] for v in via]
                   + [list(st1["pos"])])
            path = mu.smooth_path(pts, k1.k.get("round", 1.5))
            pos = tuple(path.at(u * path.length))
        else:
            pos = tuple(mu.lerp_vec(st0["pos"], st1["pos"], u))
    st = dict(pos=tuple(pos),
              aim=tuple(mu.lerp_vec(st0["aim"], st1["aim"], u)),
              frame=tuple(mu.lerp_vec(st0["frame"], st1["frame"], u)),
              roll=mu.lerp(st0["roll"], st1["roll"], u))
    # 焦距：按对数插值，变焦速度观感更均匀；keep_size = 希区柯克变焦（推拉的同时反向变焦，主体大小不变）
    if k1.k.get("keep_size"):
        d0 = mu.dist3d(st0["pos"], st0["aim"])
        d = mu.dist3d(st["pos"], st["aim"])
        st["lens"] = k0.lens * d / max(d0, 1e-3)
    else:
        st["lens"] = math.exp(mu.lerp(math.log(k0.lens), math.log(k1.lens), u))
    return st


# ================================================================ 写进 Blender

def cam_matrix_euler(yaw, pitch, roll, prev=None):
    m = (Matrix.Rotation(math.radians(yaw), 4, 'Z') @ Matrix.Rotation(math.radians(90 + pitch), 4, 'X')
         @ Matrix.Rotation(math.radians(roll), 4, 'Z'))
    return m.to_euler('XYZ', prev) if prev is not None else m.to_euler('XYZ')


def auto_cutaway(rows, subjects, actors, base_hide):
    """找出挡在相机和主体之间、或者把相机包在里面的墙/天花，返回需要额外隐藏的物体名。"""
    from .scene_builder import SceneQuery

    def can_cut(name):
        ob = bpy.data.objects.get(name)
        return ob is not None and bool(ob.get("pv_cutaway"))

    hidden = set(base_hide)
    added = set()
    for _ in range(4):  # 隐藏一层后，后面可能还有一层墙
        q = SceneQuery(exclude=hidden)
        new = set()
        for r in rows:
            ins = q.inside_solid(r["pos"])
            if ins and can_cut(ins):
                new.add(ins)
            for aid in subjects:
                p = actors[aid].points(r["frame"])
                for part in ("eye", "body"):
                    h = q.first_hit(r["pos"], p[part])
                    if h and can_cut(h[0]):
                        new.add(h[0])
        new -= hidden
        if not new:
            break
        hidden |= new
        added |= new
    return added


def build_cameras(shots_spec, actors, n_frames, res, log):
    shots = parse_shots(shots_spec, log)
    total = shots[-1]["end"]
    defaults = shots_spec.get("defaults", {})
    coll = ensure_collection(COLL_CAMS)
    sc = bpy.context.scene
    sc.timeline_markers.clear()
    all_rows = {}
    shot_infos = []
    hide_plan = {}  # 物体名 → 需要隐藏的帧集合
    hidden_by_shot = {}
    for shot in shots:
        f0, f1 = t2f(shot["start"]), t2f(shot["end"]) - 1
        lag = float(shot.get("lag", defaults.get("lag", LAG)))
        look_lag = float(shot.get("look_lag", defaults.get("look_lag", LOOK_LAG)))
        sm = SmoothedActors(actors, f0, f1, lag, look_lag)
        ctx = dict(sm=sm, actors=actors, res=res, defaults=defaults)
        rows, keys = eval_shot(shot, ctx)
        subj = shot.get("subjects")
        if subj is None:
            subj = []
            for k in keys:
                for a in k.subjects(actors):
                    if a and a not in subj:
                        subj.append(a)
        cd = bpy.data.cameras.new(shot["id"])
        cd.sensor_fit = 'HORIZONTAL'
        cd.sensor_width = mu.SENSOR_W
        cd.clip_start = 0.05
        cd.clip_end = 1000.0
        cam = bpy.data.objects.new(shot["id"], cd)
        cam.rotation_mode = 'XYZ'
        coll.objects.link(cam)
        prev = None
        for r in rows:
            cam.location = r["pos"]
            e = cam_matrix_euler(r["yaw"], r["pitch"], r["roll"], prev)
            cam.rotation_euler = e
            prev = e.copy()
            cd.lens = r["lens"]
            cam.keyframe_insert("location", frame=r["frame"])
            cam.keyframe_insert("rotation_euler", frame=r["frame"])
            cd.keyframe_insert("lens", frame=r["frame"])
        m = sc.timeline_markers.new(shot["id"], frame=f0)
        m.camera = cam
        hide = set(shot.get("hide", []))
        for name in hide:
            if bpy.data.objects.get(name) is None:
                raise SpecError(f"{shot['id']} 要隐藏的物体「{name}」不存在（用场景表里的 name；"
                                f"多段墙的名字是 墙名_1、墙名_2……，或用 names 给每段起名）")
        auto = []
        if shot.get("auto_hide", defaults.get("auto_hide", True)):
            auto = sorted(auto_cutaway(rows, subj, actors, hide))
            if auto:
                log(f"{shot['id']} 自动剖墙（只在本镜头隐藏）：{'、'.join(auto)}")
            hide |= set(auto)
        for name in hide:
            hide_plan.setdefault(name, set()).update(range(f0, f1 + 1))
        hidden_by_shot[shot["id"]] = hide
        all_rows[shot["id"]] = rows
        shot_infos.append(dict(id=shot["id"], start=shot["start"], end=shot["end"], f0=f0, f1=f1,
                               subjects=subj, desc=shot.get("desc", ""), size=shot.get("size", ""),
                               handheld=float(shot.get("handheld", defaults.get("handheld", 0.0))),
                               max_pan=float(shot.get("max_pan", defaults.get("max_pan", 15.0))),
                               occlusion_ok=bool(shot.get("occlusion_ok", False)),
                               hidden=sorted(hide), auto_hidden=auto,
                               keys=[dict(t=k.t, mode=k.mode, lens=k.lens) for k in keys]))
        log(f"{shot['id']}：{shot['start']:.2f}～{shot['end']:.2f}s（第 {f0}～{f1} 帧），{len(keys)} 个机位点")
    sc.camera = bpy.data.objects[shots[0]["id"]]
    # 按镜头隐藏物体（比如挡在相机前的墙）
    for name, frames in hide_plan.items():
        ob = bpy.data.objects[name]
        state = None
        for f in range(1, n_frames + 2):
            h = f in frames
            if h != state:
                ob.hide_render = h
                ob.hide_viewport = h
                ob.keyframe_insert("hide_render", frame=f)
                ob.keyframe_insert("hide_viewport", frame=f)
                state = h
    return shots, shot_infos, all_rows, total, hidden_by_shot
