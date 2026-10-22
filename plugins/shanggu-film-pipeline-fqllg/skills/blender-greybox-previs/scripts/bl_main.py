# -*- coding: utf-8 -*-
"""在 Blender 里运行的总入口（由 previs.py 调用，一般不用手动跑）。

blender --background --factory-startup --python bl_main.py -- --project <项目目录> --out <版本目录> --stage scene|blocking|preview|final [--res W H] [--empty]
"""
import sys, os, json, argparse, traceback

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy
from pv import spec as S
from pv import scene_builder as SB
from pv import actors as AC
from pv import cameras as CA
from pv import audit as AU
from pv import render as RD

LOGS = []


def log(msg):
    LOGS.append(msg)
    print("[previs] " + msg, flush=True)


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--stage", required=True, choices=["scene", "blocking", "preview", "final"])
    p.add_argument("--res", nargs=2, type=int)
    p.add_argument("--empty", action="store_true")
    p.add_argument("--no-render", action="store_true")
    return p.parse_args(argv)


def hexcolor(c):
    r, g, b = S.parse_color(c)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def main():
    a = parse()
    project = os.path.abspath(a.project)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    spec_dir = os.path.join(project, "spec")
    stage = a.stage

    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.length_unit = 'METERS'
    sc.render.fps = S.FPS
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'

    scene_spec = S.load_json(os.path.join(spec_dir, "scene.json"))
    blocking = S.load_json(os.path.join(spec_dir, "blocking.json"), required=stage in ("blocking", "preview", "final"))
    shots_spec = S.load_json(os.path.join(spec_dir, "shots.json"), required=stage in ("preview", "final")) \
        if stage in ("preview", "final") else None

    if a.res:
        res = tuple(a.res)
    elif shots_spec and shots_spec.get("resolution"):
        res = tuple(shots_spec["resolution"])
    else:
        res = S.DEFAULT_RES
    if stage == "preview" and not a.res:
        res = S.PREVIEW_RES if tuple(res) == S.DEFAULT_RES else (max(2, res[0] // 2 // 2 * 2), max(2, res[1] // 2 // 2 * 2))

    data = dict(stage=stage, fps=S.FPS, res=list(res), issues=[], logs=LOGS)

    # ---------- 场景
    info = SB.build_scene(scene_spec, project, log)
    data["scene"] = info
    query = SB.SceneQuery()

    # ---------- 时长
    if shots_spec:
        shots_parsed = CA.parse_shots(shots_spec, log)
        total = shots_parsed[-1]["end"]
    elif blocking and stage != "scene":
        total = float(blocking.get("duration") or (max(float(k.get("t", 0)) for ac in blocking.get("actors", [])
                                                       for k in ac.get("keys", [{"t": 0}])) + 1.0))
    else:
        total = 1.0 / S.FPS
    n_frames = max(1, int(round(total * S.FPS)))
    sc.frame_start, sc.frame_end = 1, n_frames
    data.update(duration=round(n_frames / S.FPS, 4), n_frames=n_frames)

    # ---------- 人物
    actors = {}
    if blocking and stage != "scene":
        actors, issues = AC.build_actors(blocking, n_frames, query, log)
        data["issues"] += issues
        data["actors"] = {}
        for aid, ac in actors.items():
            dom = [max(w.items(), key=lambda kv: kv[1])[0] for w in ac.weights]
            data["actors"][aid] = dict(
                name=ac.name, color=hexcolor(ac.color_spec), height=ac.H, radius=ac.r, figure=ac.figure,
                pos=[[round(x, 3), round(y, 3)] for x, y in ac.pos], z=[round(z, 3) for z in ac.base_z],
                facing=[round(f % 360, 1) for f in ac.facing], pose=dom, moving=ac.moving,
                keys=ac.keys, moves=[n[1] for n in ac.notes if n[0] == "move"])

    # ---------- 镜头
    if shots_spec:
        shots, infos, rows, total, hidden = CA.build_cameras(shots_spec, actors, n_frames, res, log)
        issues, summaries = AU.audit_shots(infos, rows, actors, res, hidden, log)
        data["issues"] += issues
        data["shots"] = summaries
        data["camera_rows"] = {k: [dict(f=r["frame"], pos=[round(v, 3) for v in r["pos"]], yaw=round(r["yaw"], 2),
                                         pitch=round(r["pitch"], 2), roll=round(r["roll"], 2), lens=round(r["lens"], 2))
                                    for r in v] for k, v in rows.items()}
        data["total_shots_duration"] = total

    # ---------- 外观
    RD.setup_look(sc, res, scene_spec.get("background", "#9a9a9a"))

    # 俯视范围
    scene_objs = [bpy.data.objects[n] for n in info["objects"]]
    if info.get("plan"):
        bounds = info["plan"]["bounds"]
        plan_size = info["plan"]["size_px"]
    else:
        bounds = SB.scene_bounds(scene_objs, margin=1.5) or (-10, -10, 10, 10)
        plan_size = None

    if stage == "scene" and scene_spec.get("ref_person", True) is not False:
        sb = SB.scene_bounds(scene_objs, margin=0) or (-5, -5, 5, 5)
        rp = scene_spec.get("ref_person")
        pos = rp if isinstance(rp, list) else [(sb[0] + sb[2]) / 2, (sb[1] + sb[3]) / 2]
        z = query.floor_z(pos[0], pos[1], 0.0, max_up=50.0)
        RD.add_ref_person(pos, z)
        data["ref_person"] = pos

    blend_path = os.path.join(out, "工程.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, check_existing=False)
    log(f"已保存 {blend_path}")
    data["blend"] = blend_path

    if not a.no_render:
        data["top_view"] = RD.top_view(sc, os.path.join(out, "俯视图.png"), bounds, plan_size=plan_size)
        if stage == "scene":
            views = scene_spec.get("check_views") or RD.auto_check_views(SB.scene_bounds(scene_objs, margin=0) or (-5, -5, 5, 5))
            data["check_views"] = RD.check_views(sc, views, os.path.join(out, "检查视角"))
        if stage in ("preview", "final"):
            sc.render.resolution_x, sc.render.resolution_y = res
            sc.camera = bpy.data.objects[shots[0]["id"]]
            RD.render_animation(sc, os.path.join(out, "frames"), 1, n_frames, log)
            data["frames_dir"] = os.path.join(out, "frames")
            if a.empty:
                restore = RD.set_visibility(hide_actors=True)
                RD.render_animation(sc, os.path.join(out, "frames_empty"), 1, n_frames, log)
                restore()
                data["frames_empty_dir"] = os.path.join(out, "frames_empty")

    with open(os.path.join(out, "build_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("PREVIS_OK", flush=True)


try:
    main()
except S.SpecError as e:
    print("PREVIS_ERROR: " + str(e), flush=True)
    sys.exit(2)
except Exception:
    traceback.print_exc()
    print("PREVIS_ERROR: 内部错误，见上方报错", flush=True)
    sys.exit(3)
