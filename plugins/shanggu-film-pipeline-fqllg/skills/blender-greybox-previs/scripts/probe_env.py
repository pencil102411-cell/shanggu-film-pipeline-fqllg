# -*- coding: utf-8 -*-
"""环境实测：在后台模式下分别用各渲染引擎渲同一帧，检查是否出图、耗时多少。

用法：
  blender.exe --background --factory-startup --python probe_env.py -- <输出目录>
结果写到 <输出目录>/probe_result.json，并打印一行 PROBE_JSON=...
"""
import bpy, sys, os, time, json, math

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = os.path.abspath(argv[0] if argv else os.path.join(os.getcwd(), "probe_out"))
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y = 700, 300
sc.render.resolution_percentage = 100
sc.render.image_settings.file_format = 'PNG'


def mat(name, rgba):
    m = bpy.data.materials.new(name)
    m.diffuse_color = rgba
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = 1.0
    return m


bpy.ops.mesh.primitive_plane_add(size=20)
bpy.context.object.data.materials.append(mat("floor", (0.35, 0.35, 0.35, 1)))
bpy.ops.mesh.primitive_cube_add(size=2, location=(-2, 3, 1))
bpy.context.object.data.materials.append(mat("wall", (0.7, 0.7, 0.7, 1)))
bpy.ops.mesh.primitive_cylinder_add(radius=0.22, depth=1.75, location=(1, 1, 0.875))
bpy.context.object.data.materials.append(mat("actor", (0.1, 0.3, 0.9, 1)))

bpy.ops.object.camera_add(location=(0, -6, 1.6))
cam = bpy.context.object
cam.rotation_euler = (math.radians(88), 0, 0)
cam.data.lens = 35
sc.camera = cam
bpy.ops.object.light_add(type='SUN', location=(0, 0, 10))
bpy.context.object.data.energy = 3

world = bpy.data.worlds.new("w")
world.color = (0.5, 0.5, 0.5)
sc.world = world


def image_stats(path):
    img = bpy.data.images.load(path)
    px = list(img.pixels)
    bpy.data.images.remove(img)
    lum = [0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2] for i in range(0, len(px), 4)]
    n = len(lum)
    mean = sum(lum) / n
    var = sum((v - mean) ** 2 for v in lum) / n
    blues = sum(1 for i in range(0, len(px), 4) if px[i + 2] > px[i] + 0.15)
    return {"mean": round(mean, 4), "std": round(math.sqrt(var), 4), "blue_pixels": blues}


def try_render(label, setup):
    path = os.path.join(OUT, f"probe_{label}.png")
    rec = {"engine": label}
    try:
        setup()
        sc.render.filepath = path
        t = time.time()
        bpy.ops.render.render(write_still=True)
        rec["seconds"] = round(time.time() - t, 2)
        st = image_stats(path)
        rec.update(st)
        # 判定：有明暗变化，且能看到蓝色人物
        rec["ok"] = st["std"] > 0.02 and st["blue_pixels"] > 200
    except Exception as e:
        rec["ok"] = False
        rec["error"] = repr(e)
    print("PROBE", json.dumps(rec, ensure_ascii=False))
    return rec


def setup_workbench():
    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light = 'STUDIO'
    sh.color_type = 'MATERIAL'
    sh.show_shadows = True


def setup_eevee():
    sc.render.engine = 'BLENDER_EEVEE'
    sc.eevee.taa_render_samples = 8


def setup_cycles_gpu():
    sc.render.engine = 'CYCLES'
    prefs = bpy.context.preferences.addons['cycles'].preferences
    chosen = None
    for kind in ('OPTIX', 'CUDA'):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            devs = [d for d in prefs.devices if d.type == kind]
            if devs:
                for d in prefs.devices:
                    d.use = d.type == kind
                chosen = kind
                break
        except Exception:
            continue
    if not chosen:
        raise RuntimeError("no GPU device for Cycles")
    sc.cycles.device = 'GPU'
    sc.cycles.samples = 16
    sc.cycles.use_denoising = False


def setup_cycles_cpu():
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 16
    sc.cycles.use_denoising = False


results = [
    try_render("workbench", setup_workbench),
    try_render("eevee", setup_eevee),
    try_render("cycles_gpu", setup_cycles_gpu),
    try_render("cycles_cpu", setup_cycles_cpu),
]
summary = {"blender": bpy.app.version_string, "results": results}
with open(os.path.join(OUT, "probe_result.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print("PROBE_JSON=" + json.dumps(summary, ensure_ascii=False))
