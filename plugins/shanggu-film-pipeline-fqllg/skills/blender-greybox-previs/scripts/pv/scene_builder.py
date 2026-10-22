# -*- coding: utf-8 -*-
"""场景表 scene.json → Blender 灰模。

所有尺寸单位为米。坐标：平面图向右 = +X，向上 = +Y，高度 = Z，地面 = 0。
"""
import math, os
import bpy, bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .spec import SpecError, color_linear, SCENE_GREYS
from . import mathutil as mu

COLL_SCENE = "场景"
COLL_ACTORS = "人物"
COLL_CAMS = "相机"
COLL_HELP = "辅助"   # 只在 Blender 窗口里看，不进渲染

# 各类型默认：是否算实体（挡人、挡视线）、是否可行走、灰度类别
TYPE_DEFAULTS = {
    "wall":     dict(solid=True,  walkable=False, kind="wall"),
    "railing":  dict(solid=True,  walkable=False, kind="wall"),
    "box":      dict(solid=True,  walkable=False, kind="furniture"),
    "prism":    dict(solid=True,  walkable=False, kind="furniture"),
    "slab":     dict(solid=False, walkable=True,  kind="slab"),
    "floor":    dict(solid=False, walkable=True,  kind="floor"),
    "stairs":   dict(solid=False, walkable=True,  kind="stairs"),
    "ramp":     dict(solid=False, walkable=True,  kind="stairs"),
    "column":   dict(solid=True,  walkable=False, kind="column"),
    "cylinder": dict(solid=True,  walkable=False, kind="furniture"),
    "ceiling":  dict(solid=True,  walkable=False, kind="ceiling", role="ceiling"),
    "tree":     dict(solid=True,  walkable=False, kind="prop"),
}


# ================================================================ 基础

def ensure_collection(name, parent=None, hide_render=False):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(coll)
    coll.hide_render = hide_render
    return coll


def new_mesh_object(name, bm, coll):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def bm_box(bm, center, size, yaw_deg=0.0, z0=0.0):
    """在 bmesh 里加一个长方体。center=(x,y)，size=(长, 宽, 高)，yaw_deg 为数学逆时针角。"""
    cx, cy = center
    L, W, H = size
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    corners = []
    for dz in (z0, z0 + H):
        for dx, dy in ((-L / 2, -W / 2), (L / 2, -W / 2), (L / 2, W / 2), (-L / 2, W / 2)):
            corners.append(bm.verts.new((cx + dx * c - dy * s, cy + dx * s + dy * c, dz)))
    v = corners
    for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([v[i] for i in f])


def bm_prism(bm, polygon, z0, z1):
    """多边形底面拉伸成柱体。"""
    pts = [tuple(p) for p in polygon]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        raise SpecError("多边形至少要 3 个点")
    # 保证逆时针，法线朝外
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    if area < 0:
        pts.reverse()
    bot = [bm.verts.new((x, y, z0)) for x, y in pts]
    top = [bm.verts.new((x, y, z1)) for x, y in pts]
    bm.faces.new(list(reversed(bot)))
    bm.faces.new(top)
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((bot[i], bot[j], top[j], top[i]))


def bm_cylinder(bm, center, radius, z0, z1, segments=20):
    cx, cy = center
    poly = [(cx + radius * math.cos(2 * math.pi * k / segments), cy + radius * math.sin(2 * math.pi * k / segments))
            for k in range(segments)]
    bm_prism(bm, poly, z0, z1)


def bm_sphere(bm, center, radius, z, segs=16, rings=8):
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=radius,
                              matrix=__import__("mathutils").Matrix.Translation((center[0], center[1], z)))


def compass_rot_to_math(rot):
    """参数表里的 rot 是"俯视顺时针"角度（与人物朝向同一规则），转成数学逆时针角。"""
    return -float(rot or 0.0)


# ================================================================ 各类型

def _num(el, key, default=None, required=False):
    v = el.get(key, default)
    if v is None and required:
        raise SpecError(f"元素「{el.get('name', el.get('type'))}」缺少字段 {key}")
    return v


def build_wall(el, defaults):
    """每一段墙单独返回一个 bmesh，方便按镜头单独隐藏某一面墙。返回 [(段号, bmesh)]。"""
    path = _num(el, "path", required=True)
    if len(path) < 2:
        raise SpecError(f"墙「{el.get('name')}」的 path 至少要 2 个点")
    closed = bool(el.get("closed", False))
    pts = [tuple(p) for p in path]
    if closed and pts[0] != pts[-1]:
        pts.append(pts[0])
    t = float(el.get("thickness", defaults["wall_thickness"] if el["type"] == "wall" else 0.06))
    H = float(el.get("height", defaults["wall_height"] if el["type"] == "wall" else 1.05))
    z = float(el.get("z", 0.0))
    nseg = len(pts) - 1

    # 门窗洞：按 seg + at（从该段起点量起，洞中心）或 center（平面坐标，自动找最近的段）
    openings = {i: [] for i in range(nseg)}
    for op in el.get("openings", []):
        w = float(_num(op, "width", required=True))
        oh = float(op.get("height", 2.1 if op.get("kind", "door") == "door" else 1.5))
        sill = float(op.get("sill", 0.0 if op.get("kind", "door") == "door" else 0.9))
        if "center" in op:
            best = None
            for i in range(nseg):
                a, b = Vector(pts[i]), Vector(pts[i + 1])
                ab = b - a
                L = ab.length
                u = mu.clamp((Vector(op["center"]) - a).dot(ab) / (L * L), 0, 1) if L > 0 else 0
                d = (a + ab * u - Vector(op["center"])).length
                if best is None or d < best[0]:
                    best = (d, i, u * L)
            if best[0] > max(0.6, t * 2):
                raise SpecError(f"墙「{el.get('name')}」的门窗洞 center={op['center']} 离墙太远（{best[0]:.2f} 米），检查坐标")
            seg, at = best[1], best[2]
        else:
            seg, at = int(op.get("seg", 0)), float(_num(op, "at", required=True))
        if not (0 <= seg < nseg):
            raise SpecError(f"墙「{el.get('name')}」的门窗洞 seg={seg} 超出范围（共 {nseg} 段，从 0 数）")
        openings[seg].append((at - w / 2, at + w / 2, sill, sill + oh))

    out = []
    for i in range(nseg):
        a, b = Vector(pts[i]), Vector(pts[i + 1])
        d = b - a
        L = d.length
        if L < 1e-6:
            continue
        bm = bmesh.new()
        out.append((i, bm))
        u = d / L
        ang = math.degrees(math.atan2(u.y, u.x))
        has_prev = i > 0 or closed
        has_next = i < nseg - 1 or closed
        s0 = -t / 2 if has_prev else 0.0
        s1 = L + (t / 2 if has_next else 0.0)
        cuts = sorted(openings[i])
        # 实墙区间
        pieces = []
        cur = s0
        for o0, o1, zb, zt in cuts:
            o0c, o1c = max(o0, s0), min(o1, s1)
            if o0c > cur:
                pieces.append((cur, o0c, 0.0, H))
            if zb > 0:
                pieces.append((o0c, o1c, 0.0, min(zb, H)))
            if zt < H:
                pieces.append((o0c, o1c, zt, H))
            cur = max(cur, o1c)
        if cur < s1:
            pieces.append((cur, s1, 0.0, H))
        for p0, p1, h0, h1 in pieces:
            if p1 - p0 < 1e-4 or h1 - h0 < 1e-4:
                continue
            mid = a + u * ((p0 + p1) / 2)
            bm_box(bm, (mid.x, mid.y), (p1 - p0, t, h1 - h0), ang, z + h0)
    return out


def build_box(el, bm):
    z = float(el.get("z", 0.0))
    if "from" in el and "to" in el:
        (x0, y0), (x1, y1) = el["from"], el["to"]
        h = float(_num(el, "h", el.get("height"), required=True))
        bm_box(bm, ((x0 + x1) / 2, (y0 + y1) / 2), (abs(x1 - x0), abs(y1 - y0), h), 0.0, z)
    else:
        c = _num(el, "center", required=True)
        size = _num(el, "size", required=True)
        if len(size) != 3:
            raise SpecError(f"box「{el.get('name')}」的 size 要写 [宽(X), 深(Y), 高]")
        bm_box(bm, c, size, compass_rot_to_math(el.get("rot", 0)), z)


def build_prism(el, bm, default_thickness=None):
    poly = _num(el, "polygon", required=True)
    if el["type"] in ("slab", "floor", "ceiling"):
        top = float(el.get("z", 0.0))
        th = float(el.get("thickness", default_thickness or 0.2))
        bm_prism(bm, poly, top - th, top)
    else:
        z = float(el.get("z", 0.0))
        h = float(_num(el, "h", el.get("height"), required=True))
        bm_prism(bm, poly, z, z + h)


def build_stairs(el, bm):
    a = Vector(_num(el, "from", required=True))
    b = Vector(_num(el, "to", required=True))
    width = float(_num(el, "width", required=True))
    z = float(el.get("z", 0.0))
    total = float(_num(el, "height", required=True))
    n = int(el.get("steps", max(1, round(total / 0.15))))
    d = b - a
    run = d.length
    if run < 1e-3:
        raise SpecError(f"楼梯「{el.get('name')}」from 和 to 不能是同一点")
    u = d / run
    ang = math.degrees(math.atan2(u.y, u.x))
    step_run = run / n
    step_h = total / n
    for k in range(n):
        mid = a + u * (step_run * (k + 0.5))
        bm_box(bm, (mid.x, mid.y), (step_run, width, step_h * (k + 1)), ang, z)
    return dict(steps=n, step_h=step_h, step_run=step_run)


def build_ramp(el, bm):
    a = Vector(_num(el, "from", required=True))
    b = Vector(_num(el, "to", required=True))
    width = float(_num(el, "width", required=True))
    z0 = float(el.get("z", 0.0))
    z1 = float(_num(el, "z_to", required=True))
    d = b - a
    u = d.normalized()
    n = Vector((-u.y, u.x))
    hw = width / 2
    p = [a + n * hw, a - n * hw, b - n * hw, b + n * hw]
    base = min(z0, z1) - 0.05
    vb = [bm.verts.new((q.x, q.y, base)) for q in p]
    vt = [bm.verts.new((p[0].x, p[0].y, z0)), bm.verts.new((p[1].x, p[1].y, z0)),
          bm.verts.new((p[2].x, p[2].y, z1)), bm.verts.new((p[3].x, p[3].y, z1))]
    bm.faces.new(list(reversed(vb)))
    bm.faces.new(vt)
    for i in range(4):
        j = (i + 1) % 4
        bm.faces.new((vb[i], vb[j], vt[j], vt[i]))


def build_columns(el, bm):
    at = _num(el, "at", required=True)
    pts = at if isinstance(at[0], (list, tuple)) else [at]
    z = float(el.get("z", 0.0))
    h = float(_num(el, "height", el.get("h"), required=True))
    for p in pts:
        if "size" in el:
            w, dd = el["size"][:2]
            bm_box(bm, p, (w, dd, h), compass_rot_to_math(el.get("rot", 0)), z)
        else:
            bm_cylinder(bm, p, float(el.get("radius", 0.25)), z, z + h)


def build_trees(el, bm):
    at = _num(el, "at", required=True)
    pts = at if isinstance(at[0], (list, tuple)) else [at]
    z = float(el.get("z", 0.0))
    h = float(el.get("height", 6.0))
    r = float(el.get("canopy", h * 0.3))
    trunk = float(el.get("trunk", 0.15))
    for p in pts:
        bm_cylinder(bm, p, trunk, z, z + h - r, 10)
        bm_sphere(bm, p, r, z + h - r)


# ================================================================ 主流程

def _finish_object(name, bm, coll, el, td, typ):
    if bpy.data.objects.get(name) is not None:
        raise SpecError(f"物体名「{name}」重复了，场景表里每个 name 要唯一")
    ob = new_mesh_object(name, bm, coll)
    kind = el.get("kind", td["kind"])
    ob.color = color_linear(el.get("color", SCENE_GREYS.get(kind, 0.7)))
    ob["pv_type"] = typ
    ob["pv_kind"] = kind
    ob["pv_solid"] = bool(el.get("solid", td["solid"]))
    ob["pv_walkable"] = bool(el.get("walkable", td["walkable"]))
    ob["pv_role"] = el.get("role", td.get("role", ""))
    # 可被"自动剖墙"隐藏：墙、栏杆、天花默认可以，其他物体写 "cutaway": true 才行
    ob["pv_cutaway"] = bool(el.get("cutaway", typ in ("wall", "railing", "ceiling")))
    return ob


def build_scene(scene_spec, project_dir, log):
    defaults = {"wall_height": 3.0, "wall_thickness": 0.24}
    defaults.update(scene_spec.get("defaults", {}))
    c_scene = ensure_collection(COLL_SCENE)
    c_help = ensure_collection(COLL_HELP, hide_render=True)

    objs = []
    stats = {}
    for idx, el in enumerate(scene_spec.get("elements", [])):
        typ = el.get("type")
        if typ not in TYPE_DEFAULTS:
            raise SpecError(f"第 {idx + 1} 个元素的 type「{typ}」不认识。可用：{', '.join(TYPE_DEFAULTS)}")
        td = TYPE_DEFAULTS[typ]
        name = el.get("name") or f"{typ}_{idx + 1:02d}"
        extra = None
        if typ in ("wall", "railing"):
            segs = build_wall(el, defaults)
            names = el.get("names", [])
            for j, (si, bm) in enumerate(segs):
                if si < len(names) and names[si]:
                    nm = names[si]
                else:
                    nm = name if len(segs) == 1 else f"{name}_{si + 1}"
                objs.append(_finish_object(nm, bm, c_scene, el, td, typ))
            continue
        bm = bmesh.new()
        if typ == "box":
            build_box(el, bm)
        elif typ in ("prism", "slab", "floor", "ceiling"):
            build_prism(el, bm)
        elif typ == "stairs":
            extra = build_stairs(el, bm)
        elif typ == "ramp":
            build_ramp(el, bm)
        elif typ in ("column", "cylinder"):
            build_columns(el, bm)
        elif typ == "tree":
            build_trees(el, bm)
        objs.append(_finish_object(name, bm, c_scene, el, td, typ))
        if extra:
            stats[name] = extra

    # 地面
    g = scene_spec.get("ground", {"enabled": True})
    if g is not False and g.get("enabled", True):
        bb = scene_bounds(objs, margin=0)
        if bb is None:
            bb = (-10, -10, 10, 10)
        m = float(g.get("margin", 30.0))
        bm = bmesh.new()
        poly = [(bb[0] - m, bb[1] - m), (bb[2] + m, bb[1] - m), (bb[2] + m, bb[3] + m), (bb[0] - m, bb[3] + m)]
        gz = float(g.get("z", 0.0))
        bm_prism(bm, poly, gz - 0.1, gz)
        ob = new_mesh_object("地面", bm, c_scene)
        ob.color = color_linear(g.get("color", SCENE_GREYS["ground"]))
        ob["pv_type"] = "ground"
        ob["pv_kind"] = "ground"
        ob["pv_solid"] = False
        ob["pv_walkable"] = True
        ob["pv_role"] = "ground"
        objs.append(ob)

    # 平面图底图（只在窗口里看）
    plan = scene_spec.get("plan")
    plan_info = None
    if plan:
        plan_info = add_plan_underlay(plan, project_dir, c_help, log)

    # 1.75 米参照人（只在检查视角图里出现，见 render 模块）
    log(f"场景元素 {len(objs)} 个")
    return dict(objects=[o.name for o in objs], plan=plan_info, stair_stats=stats)


def plan_calibration(plan, img_w, img_h):
    """返回函数 px→米 以及图片四角的米坐标范围。

    两种写法：
      {"image": "...", "px_per_m": 50, "origin_px": [120, 900]}   origin_px = 世界(0,0)在图上的像素位置
      {"image": "...", "calib": [{"px": [x1,y1], "m": [X1,Y1]}, {"px": [x2,y2], "m": [X2,Y2]}]}
    图片像素 y 向下，世界 Y 向上。默认图片没有旋转。
    """
    if "calib" in plan:
        p1, p2 = plan["calib"][:2]
        dpx = math.hypot(p2["px"][0] - p1["px"][0], p2["px"][1] - p1["px"][1])
        dm = math.hypot(p2["m"][0] - p1["m"][0], p2["m"][1] - p1["m"][1])
        if dm <= 0 or dpx <= 0:
            raise SpecError("plan.calib 两个点不能重合")
        ppm = dpx / dm
        ox = p1["px"][0] - p1["m"][0] * ppm
        oy = p1["px"][1] + p1["m"][1] * ppm
    else:
        ppm = float(plan["px_per_m"])
        ox, oy = plan.get("origin_px", [0, img_h])
    def to_m(px, py):
        return ((px - ox) / ppm, (oy - py) / ppm)
    x0, y1 = to_m(0, 0)
    x1, y0 = to_m(img_w, img_h)
    return ppm, (ox, oy), (x0, y0, x1, y1)


def add_plan_underlay(plan, project_dir, coll, log):
    path = plan.get("image")
    full = path if os.path.isabs(path) else os.path.join(project_dir, path)
    if not os.path.exists(full):
        raise SpecError(f"找不到平面图：{full}")
    img = bpy.data.images.load(full, check_existing=True)
    w, h = img.size
    ppm, origin, (x0, y0, x1, y1) = plan_calibration(plan, w, h)
    bm = bmesh.new()
    vs = [bm.verts.new((x0, y0, 0.005)), bm.verts.new((x1, y0, 0.005)),
          bm.verts.new((x1, y1, 0.005)), bm.verts.new((x0, y1, 0.005))]
    f = bm.faces.new(vs)
    uv = bm.loops.layers.uv.new()
    for loop, (u, v) in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop[uv].uv = (u, v)
    ob = new_mesh_object("平面图底图", bm, coll)
    mat = bpy.data.materials.new("平面图")
    mat.use_nodes = True
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    bsdf = nt.nodes.get("Principled BSDF")
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    ob.data.materials.append(mat)
    ob.hide_render = True
    log(f"平面图 {w}×{h} 像素，{ppm:.2f} 像素/米，覆盖 X {x0:.2f}～{x1:.2f}、Y {y0:.2f}～{y1:.2f} 米")
    return dict(image=full, size_px=[w, h], px_per_m=ppm, origin_px=list(origin), bounds=[x0, y0, x1, y1])


def scene_bounds(objs, margin=1.0, skip_roles=("ground",)):
    xs, ys = [], []
    for ob in objs:
        if ob.get("pv_role") in skip_roles:
            continue
        for v in ob.data.vertices:
            w = ob.matrix_world @ v.co
            xs.append(w.x)
            ys.append(w.y)
    if not xs:
        return None
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)


# ================================================================ 碰撞 / 地面查询

class SceneQuery:
    """把实体和可行走面各合成一棵 BVH 树，用来查地面高度、穿墙、遮挡。"""

    def __init__(self, exclude=None):
        ex = set(exclude or ())
        self.solid, self.solid_owner = self._tree(lambda o: o.get("pv_solid") and o.name not in ex)
        self.walk, _ = self._tree(lambda o: o.get("pv_walkable") and o.name not in ex)

    @staticmethod
    def _tree(pred):
        verts, polys, owner = [], [], []
        coll = bpy.data.collections.get(COLL_SCENE)
        if coll is None:
            return None, []
        for ob in coll.objects:
            if ob.type != "MESH" or not pred(ob):
                continue
            base = len(verts)
            mw = ob.matrix_world
            verts.extend([tuple(mw @ v.co) for v in ob.data.vertices])
            for p in ob.data.polygons:
                polys.append([base + i for i in p.vertices])
                owner.append(ob.name)
        if not polys:
            return None, []
        return BVHTree.FromPolygons(verts, polys), owner

    def floor_z(self, x, y, from_z, max_up=0.6, default=0.0):
        """从 from_z + max_up 往下找最近的可行走面高度。"""
        if self.walk is None:
            return default
        hit = self.walk.ray_cast(Vector((x, y, from_z + max_up)), Vector((0, 0, -1)), 50.0)
        return hit[0].z if hit[0] is not None else default

    def first_hit(self, a, b):
        """a→b 之间第一个撞到的实体，返回 (物体名, 撞点) 或 None。"""
        if self.solid is None:
            return None
        a, b = Vector(a), Vector(b)
        d = b - a
        L = d.length
        if L < 1e-6:
            return None
        hit = self.solid.ray_cast(a, d / L, L)
        if hit[0] is None:
            return None
        return self.solid_owner[hit[2]], tuple(hit[0])

    def nearest_solid(self, p, maxd=1.0):
        if self.solid is None:
            return None
        r = self.solid.find_nearest(Vector(p), maxd)
        if r[0] is None:
            return None
        return self.solid_owner[r[2]], r[3]

    def inside_solid(self, p, maxd=5.0):
        """判断点是否在实体内部：找最近的面，点在面法线的背面就算在里面。返回物体名或 None。"""
        if self.solid is None:
            return None
        o = Vector(p)
        r = self.solid.find_nearest(o, maxd)
        if r[0] is None:
            return None
        if (o - r[0]).dot(r[1]) < -1e-5:
            return self.solid_owner[r[2]]
        return None
