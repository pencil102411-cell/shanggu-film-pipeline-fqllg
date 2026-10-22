# -*- coding: utf-8 -*-
"""渲染：灰模风格设置、动画帧、俯视图、检查视角图。全部用 Workbench（最快的平涂渲染）。"""
import math, os, time
import bpy

from .spec import color_linear, FPS
from .scene_builder import COLL_SCENE, COLL_ACTORS, COLL_HELP, COLL_CAMS, ensure_collection, scene_bounds
from . import mathutil as mu


def setup_look(sc, res, background="#9a9a9a", shadows=True):
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.fps = FPS
    sc.render.fps_base = 1.0
    sc.render.film_transparent = False
    sc.render.use_motion_blur = False
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    sc.view_settings.exposure = 0.6
    sh = sc.display.shading
    sh.light = 'STUDIO'
    sh.studio_light = 'studio.sl'
    # 光源固定在世界里，不随相机转动 → 运镜时明暗不会突变
    sh.use_world_space_lighting = True
    sh.color_type = 'OBJECT'
    sh.show_shadows = shadows
    sh.shadow_intensity = 0.35
    sh.show_cavity = False
    sh.show_specular_highlight = False
    sh.show_object_outline = False
    sh.background_type = 'WORLD'
    sc.display.render_aa = '8'
    if sc.world is None:
        sc.world = bpy.data.worlds.new("背景")
    c = color_linear(background)
    sc.world.color = c[:3]


def set_visibility(hide_actors=False, hide_roles=()):
    """返回一个恢复函数。"""
    saved = []
    ca = bpy.data.collections.get(COLL_ACTORS)
    if ca is not None:
        saved.append((ca, ca.hide_render))
        ca.hide_render = hide_actors
    cs = bpy.data.collections.get(COLL_SCENE)
    obj_saved = []
    if cs is not None and hide_roles:
        for ob in cs.objects:
            if ob.get("pv_role") in hide_roles:
                obj_saved.append((ob, ob.hide_render))
                ob.hide_render = True
    def restore():
        for c, v in saved:
            c.hide_render = v
        for o, v in obj_saved:
            o.hide_render = v
    return restore


def render_animation(sc, out_dir, f0, f1, log):
    os.makedirs(out_dir, exist_ok=True)
    sc.frame_start, sc.frame_end = f0, f1
    sc.render.filepath = os.path.join(out_dir, "")
    sc.render.use_file_extension = True
    t = time.time()
    bpy.ops.render.render(animation=True)
    log(f"渲染 {f1 - f0 + 1} 帧用时 {time.time() - t:.1f} 秒 → {out_dir}")


def render_still(sc, cam, path, frame=1):
    sc.camera = cam
    sc.frame_set(frame)
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


def temp_camera(name, ortho=False):
    cd = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, cd)
    ensure_collection(COLL_HELP, hide_render=True).objects.link(cam)
    if ortho:
        cd.type = 'ORTHO'
    cd.sensor_fit = 'HORIZONTAL'
    cd.sensor_width = mu.SENSOR_W
    cd.clip_start = 0.05
    cd.clip_end = 2000
    return cam


def remove_object(ob):
    data = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if data is not None and data.users == 0:
        if isinstance(data, bpy.types.Camera):
            bpy.data.cameras.remove(data)


def top_view(sc, path, bounds, max_px=2400, plan_size=None, frame=1, hide_actors=True):
    """正交俯视图。bounds = (x0, y0, x1, y1) 米。返回像素尺寸与边界。"""
    x0, y0, x1, y1 = bounds
    w_m, h_m = x1 - x0, y1 - y0
    if plan_size:
        W, H = plan_size
        # 与平面图同比例；平面图太小时放大到长边至少 1600 像素，太大时缩到 max_px
        k = min(max_px / max(W, H), max(1.0, 1600 / max(W, H)))
        W, H = int(round(W * k)), int(round(H * k))
    else:
        ppm = min(80.0, max_px / max(w_m, h_m))
        W, H = int(round(w_m * ppm)), int(round(h_m * ppm))
    W += W % 2
    H += H % 2
    old_res = (sc.render.resolution_x, sc.render.resolution_y)
    old_cam = sc.camera
    sc.render.resolution_x, sc.render.resolution_y = W, H
    cam = temp_camera("俯视相机", ortho=True)
    zmax = 50.0
    cs = bpy.data.collections.get(COLL_SCENE)
    if cs:
        for ob in cs.objects:
            for c in ob.bound_box:
                zmax = max(zmax, (ob.matrix_world @ __import__("mathutils").Vector(c)).z + 5)
    cam.location = ((x0 + x1) / 2, (y0 + y1) / 2, zmax)
    cam.rotation_euler = (0, 0, 0)
    cam.data.ortho_scale = max(w_m, h_m)
    cam.data.clip_end = zmax + 50
    sh = sc.display.shading
    old = (sh.show_shadows, sh.show_cavity)
    sh.show_shadows = False
    sh.show_cavity = True
    sh.cavity_type = 'WORLD'
    restore = set_visibility(hide_actors=hide_actors, hide_roles=("ceiling", "roof"))
    # 时间轴标记会切相机，渲染静帧前临时移开
    markers = [(m, m.camera) for m in sc.timeline_markers]
    for m, _ in markers:
        m.camera = None
    try:
        render_still(sc, cam, path, frame)
    finally:
        for m, c in markers:
            m.camera = c
        restore()
        sh.show_shadows, sh.show_cavity = old
        sc.render.resolution_x, sc.render.resolution_y = old_res
        sc.camera = old_cam
        remove_object(cam)
    return dict(path=path, size=[W, H], bounds=[x0, y0, x1, y1])


def auto_check_views(objs_bounds, eye=1.6):
    x0, y0, x1, y1 = objs_bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ix, iy = (x1 - x0) * 0.12, (y1 - y0) * 0.12
    corners = [(x0 + ix, y0 + iy), (x1 - ix, y0 + iy), (x1 - ix, y1 - iy), (x0 + ix, y1 - iy)]
    names = ["左下角", "右下角", "右上角", "左上角"]
    return [dict(name=f"检查视角_{n}看中心", pos=[p[0], p[1], eye], look=[cx, cy, 1.4], lens=18) for n, p in zip(names, corners)]


def add_ref_person(pos, z=0.0):
    from .actors import make_figure
    coll = ensure_collection("参照人")
    ob, _ = make_figure("参照人_1.75米", 1.75, 0.22, color_linear("#f2f2f2"), coll)
    ob.location = (pos[0], pos[1], z)
    return ob


def check_views(sc, views, out_dir, query=None):
    """人眼高度检查视角图。views: [{name, pos:[x,y,z], look:[x,y,z], lens}]"""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    markers = [(m, m.camera) for m in sc.timeline_markers]
    for m, _ in markers:
        m.camera = None
    old_cam = sc.camera
    try:
        for i, v in enumerate(views):
            cam = temp_camera(f"检查相机{i}")
            p = v["pos"]
            if len(p) == 2:
                p = [p[0], p[1], 1.6]
            cam.location = p
            look = v.get("look", [p[0], p[1] + 5, p[2]])
            yaw, pitch = mu.look_angles(p, look)
            from .cameras import cam_matrix_euler
            cam.rotation_euler = cam_matrix_euler(yaw, pitch, 0.0)
            cam.data.lens = float(v.get("lens", 20))
            name = v.get("name", f"检查视角{i + 1}")
            path = os.path.join(out_dir, f"{name}.png")
            render_still(sc, cam, path, int(v.get("frame", 1)))
            paths.append(path)
            remove_object(cam)
    finally:
        for m, c in markers:
            m.camera = c
        sc.camera = old_cam
    return paths
