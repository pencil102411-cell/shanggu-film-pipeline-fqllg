# -*- coding: utf-8 -*-
"""灰模预演 总命令（用普通 Python 3.9+ 运行，需要 Pillow）。

  python -B previs.py setup                         检查/记录 Blender 和 FFmpeg 路径，并实测渲染
  python -B previs.py init     <项目目录>            新建项目文件夹（input / spec / output）
  python -B previs.py plan-grid <项目目录>           给平面图画米制网格，方便读坐标
  python -B previs.py scene    <项目目录> [--tag 说明]   建灰模 → 俯视图、叠图、检查视角图
  python -B previs.py blocking <项目目录> [--tag 说明]   + 人物走位 → 俯视走位图、走位检查
  python -B previs.py preview  <项目目录> [--tag 说明]   + 镜头 → 低清预览视频、检查报告
  python -B previs.py final    <项目目录> [--tag 说明] [--empty] [--per-shot]   正式分辨率交付包
  python -B previs.py open     <项目目录> [版本名]    用 Blender 窗口打开某个版本

每次 scene/blocking/preview/final 都在 output 里新建 vNN_xxx 文件夹，旧版本不覆盖。
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, math

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
USER_CFG = os.path.join(os.path.expanduser("~"), ".blender-greybox-previs", "config.json")
FPS = 24

# ================================================================ 配置与环境

def _which_glob(patterns):
    hits = []
    for p in patterns:
        hits += glob.glob(os.path.normpath(os.path.expandvars(os.path.expanduser(p))))
    return [os.path.normpath(h) for h in hits if os.path.isfile(h)]


def _ver_key(path):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", path)
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def detect_blender():
    env = os.environ.get("BLENDER_EXE")
    if env and os.path.isfile(env):
        return env
    w = shutil.which("blender")
    if w:
        return w
    cands = _which_glob([
        "~/tools/blender-*/blender.exe",
        r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
        r"D:\Program Files\Blender Foundation\Blender*\blender.exe",
        "/Applications/Blender.app/Contents/MacOS/Blender",
        "~/blender-*/blender",
        "/usr/bin/blender", "/snap/bin/blender",
    ])
    cands.sort(key=_ver_key, reverse=True)
    return cands[0] if cands else None


def detect_ffmpeg(name="ffmpeg"):
    env = os.environ.get(name.upper() + "_EXE")
    if env and os.path.isfile(env):
        return env
    w = shutil.which(name)
    if w:
        return w
    cands = _which_glob([
        rf"~\AppData\Local\Microsoft\WinGet\Packages\*FFmpeg*\*\bin\{name}.exe",
        rf"C:\ffmpeg\bin\{name}.exe", rf"~\tools\ffmpeg*\bin\{name}.exe",
        f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}",
    ])
    return cands[0] if cands else None


def load_cfg():
    path = os.environ.get("PREVIS_CONFIG") or USER_CFG
    cfg = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
    for k in ("blender", "ffmpeg", "ffprobe"):
        cfg[k] = os.path.normpath(cfg[k]) if cfg.get(k) else None
    if not cfg["blender"] or not os.path.isfile(cfg["blender"]):
        cfg["blender"] = detect_blender()
    if not cfg["ffmpeg"] or not os.path.isfile(cfg["ffmpeg"]):
        cfg["ffmpeg"] = detect_ffmpeg("ffmpeg")
    if not cfg["ffprobe"] or not os.path.isfile(cfg["ffprobe"]):
        cfg["ffprobe"] = detect_ffmpeg("ffprobe")
    return cfg


def need(cfg, key):
    if not cfg.get(key):
        die(f"找不到 {key}。运行 `python -B previs.py setup --{key} <路径>` 指定它的位置。")
    return cfg[key]


def die(msg, code=1):
    print("错误：" + msg, file=sys.stderr, flush=True)
    sys.exit(code)


def pil():
    try:
        from PIL import Image, ImageDraw, ImageFont
        return Image, ImageDraw, ImageFont
    except ImportError:
        die("缺少 Pillow（Python 画图库）。在命令行运行：python -m pip install pillow")


_FONT_CACHE = {}


def font(size):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    _, _, ImageFont = pil()
    for p in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
              "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, size)
                _FONT_CACHE[size] = f
                return f
            except OSError:
                continue
    f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


# ================================================================ 项目与版本

def next_version(project, stage, tag):
    out_root = os.path.join(project, "output")
    os.makedirs(out_root, exist_ok=True)
    nums = [int(m.group(1)) for d in os.listdir(out_root) for m in [re.match(r"v(\d+)", d)] if m]
    n = (max(nums) + 1) if nums else 1
    name = f"v{n:02d}_{stage}" + (f"_{re.sub(r'[^0-9A-Za-z一-龥_-]+', '', tag)}" if tag else "")
    path = os.path.join(out_root, name)
    if os.path.exists(path):
        die(f"版本文件夹已存在：{path}")
    os.makedirs(path)
    return path


def snapshot_spec(project, out):
    src = os.path.join(project, "spec")
    dst = os.path.join(out, "spec")
    os.makedirs(dst, exist_ok=True)
    for fn in ("scene.json", "blocking.json", "shots.json"):
        p = os.path.join(src, fn)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dst, fn))


def run_blender(cfg, project, out, stage, res=None, empty=False):
    bl = need(cfg, "blender")
    cmd = [bl, "--background", "--factory-startup", "--python-exit-code", "3",
           "--python", os.path.join(HERE, "bl_main.py"), "--",
           "--project", project, "--out", out, "--stage", stage]
    if res:
        cmd += ["--res", str(res[0]), str(res[1])]
    if empty:
        cmd += ["--empty"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    print(f"[previs] 调用 Blender（{stage}）……", flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                            encoding="utf-8", errors="replace")
    err = None
    log_lines = []
    for line in proc.stdout:
        log_lines.append(line)
        if line.startswith("[previs]"):
            print(line.rstrip(), flush=True)
        elif line.startswith("PREVIS_ERROR"):
            err = line.split(":", 1)[1].strip()
        elif "Error" in line or "Traceback" in line:
            print(line.rstrip(), flush=True)
    proc.wait()
    with open(os.path.join(out, "blender_log.txt"), "w", encoding="utf-8") as f:
        f.writelines(log_lines)
    if proc.returncode != 0 or err:
        die(f"Blender 步骤失败：{err or '见 blender_log.txt'}", 2)
    with open(os.path.join(out, "build_data.json"), "r", encoding="utf-8") as f:
        return json.load(f)


# ================================================================ 画图

def world_to_px(bounds, size):
    x0, y0, x1, y1 = bounds
    W, H = size
    return lambda x, y: ((x - x0) / (x1 - x0) * W, (y1 - y) / (y1 - y0) * H)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def draw_grid(img, bounds, step=1.0, label_every=5, color=(40, 120, 255)):
    _, ImageDraw, _ = pil()
    d = ImageDraw.Draw(img, "RGBA")
    W, H = img.size
    tp = world_to_px(bounds, (W, H))
    x0, y0, x1, y1 = bounds
    fnt = font(max(12, int(min(W, H) / 70)))
    k = math.floor(x0 / step)
    while k * step <= x1:
        x = k * step
        px, _ = tp(x, 0)
        major = abs(round(x / step) % label_every) == 0
        d.line([(px, 0), (px, H)], fill=color + ((150,) if major else (60,)), width=2 if major else 1)
        if major:
            d.text((px + 3, 3), f"x={x:g}", fill=color + (255,), font=fnt)
        k += 1
    k = math.floor(y0 / step)
    while k * step <= y1:
        y = k * step
        _, py = tp(0, y)
        major = abs(round(y / step) % label_every) == 0
        d.line([(0, py), (W, py)], fill=color + ((150,) if major else (60,)), width=2 if major else 1)
        if major:
            d.text((3, py + 2), f"y={y:g}", fill=color + (255,), font=fnt)
        k += 1
    return img


def arrow(d, p, ang_deg, length, color, width=3):
    """罗盘角：0 = 图上方，顺时针。"""
    dx, dy = math.sin(math.radians(ang_deg)), -math.cos(math.radians(ang_deg))
    q = (p[0] + dx * length, p[1] + dy * length)
    d.line([p, q], fill=color, width=width)
    left = (q[0] - dx * length * 0.35 + dy * length * 0.22, q[1] - dy * length * 0.35 - dx * length * 0.22)
    right = (q[0] - dx * length * 0.35 - dy * length * 0.22, q[1] - dy * length * 0.35 + dx * length * 0.22)
    d.polygon([q, left, right], fill=color)


POSE_CN = {"stand": "", "sit": "坐", "crouch": "蹲", "kneel": "跪", "lie": "躺"}
CAM_COLOR = (255, 196, 0)


def map_base(data, max_w=None):
    """俯视底图：提亮、降低对比，让标注更醒目。返回 (图, 世界→像素函数, 像素/米)。"""
    Image, _, _ = pil()
    tv = data["top_view"]
    img = Image.open(tv["path"]).convert("RGB")
    if max_w and img.width > max_w:
        k = max_w / img.width
        img = img.resize((int(img.width * k) // 2 * 2, int(img.height * k) // 2 * 2))
    else:
        img = img.resize((img.width // 2 * 2, img.height // 2 * 2))
    img = Image.blend(img, Image.new("RGB", img.size, (235, 235, 235)), 0.45)
    W, H = img.size
    tp = world_to_px(tv["bounds"], (W, H))
    ppm = W / (tv["bounds"][2] - tv["bounds"][0])
    return img, tp, ppm


def cam_wedge(d, p, yaw, lens, length, res, fill, outline):
    """在俯视图上画相机视野扇形。yaw 是 Blender 约定，罗盘角 = -yaw。"""
    hf = math.degrees(2 * math.atan(18.0 / lens))
    ang = -yaw
    pts = [p]
    for k in range(9):
        a = ang - hf / 2 + hf * k / 8
        pts.append((p[0] + math.sin(math.radians(a)) * length, p[1] - math.cos(math.radians(a)) * length))
    d.polygon(pts, fill=fill, outline=outline)


def draw_topdown_frame(base, data, f, tp, ppm, with_cameras, shot_rows):
    """画俯视动态预览的一帧（第 f 帧）。"""
    _, ImageDraw, _ = pil()
    img = base.copy()
    d = ImageDraw.Draw(img, "RGBA")
    W, H = img.size
    fnt = font(max(16, int(W / 45)))
    # 当前镜头的相机
    sid = None
    if with_cameras:
        for s in data.get("shots", []):
            if s["f0"] <= f <= s["f1"]:
                sid = s
                break
        if sid:
            rows = shot_rows[sid["id"]]
            r = rows[max(0, min(len(rows) - 1, f - sid["f0"]))]
            p = tp(r["pos"][0], r["pos"][1])
            cam_wedge(d, p, r["yaw"], r["lens"], max(60, ppm * 5), data["res"], CAM_COLOR + (60,), CAM_COLOR + (220,))
            path = [tp(q["pos"][0], q["pos"][1]) for q in rows]
            if len(path) > 1:
                d.line(path, fill=CAM_COLOR + (150,), width=2)
            d.ellipse([p[0] - 8, p[1] - 8, p[0] + 8, p[1] + 8], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=2)
            d.text((p[0] + 10, p[1] + 4), sid["id"], fill=(0, 0, 0, 255), font=fnt, stroke_width=3, stroke_fill=(255, 255, 255, 255))
    # 人物
    for aid, a in data.get("actors", {}).items():
        col = hex_rgb(a["color"])
        n = len(a["pos"])
        i = max(0, min(n - 1, f - 1))
        trail = [tp(x, y) for x, y in a["pos"][:i + 1]]
        future = [tp(x, y) for x, y in a["pos"][i:]]
        if len(future) > 1:
            d.line(future, fill=col + (60,), width=max(2, int(ppm * 0.04)))
        if len(trail) > 1:
            d.line(trail, fill=col + (200,), width=max(3, int(ppm * 0.07)))
        p = tp(*a["pos"][i])
        rr = max(7, a["radius"] * ppm)
        arrow(d, p, a["facing"][i], rr * 2.4, col + (255,), width=3)
        d.ellipse([p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr], fill=col + (255,), outline=(255, 255, 255, 255), width=2)
        pose = POSE_CN.get(a["pose"][i], "")
        label = a["name"] + (f"·{pose}" if pose else "")
        d.text((p[0] + rr + 4, p[1] - rr - fnt.size), label, fill=col + (255,), font=fnt,
               stroke_width=3, stroke_fill=(255, 255, 255, 255))
    # 时间码
    t = (f - 1) / FPS
    head = f"{t:6.2f} 秒   第 {f} 帧"
    if sid:
        head += f"   {sid['id']}" + (f"  {sid.get('desc', '')}" if sid.get("desc") else "")
    tw = d.textlength(head, font=fnt)
    d.rectangle([0, 0, tw + 24, fnt.size + 16], fill=(0, 0, 0, 170))
    d.text((12, 6), head, fill=(255, 255, 255, 255), font=fnt)
    draw_scale_bar(d, W, H, ppm)
    return img


def render_topdown_video(cfg, data, out_mp4, with_cameras, max_w=1280):
    """俯视动态走位预览（只给人看）。直接把每帧画面通过管道交给 FFmpeg，不落临时文件。"""
    base, tp, ppm = map_base(data, max_w)
    W, H = base.size
    ff = need(cfg, "ffmpeg")
    cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", out_mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    rows = {k: v for k, v in data.get("camera_rows", {}).items()}
    for f in range(1, data["n_frames"] + 1):
        proc.stdin.write(draw_topdown_frame(base, data, f, tp, ppm, with_cameras, rows).tobytes())
    proc.stdin.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    proc.wait()
    if proc.returncode != 0:
        die(f"俯视预览合成失败：{err[-400:]}")
    return out_mp4


def side_by_side(cfg, left_mp4, right_mp4, out_mp4, height):
    """左右拼接：左边俯视调度，右边镜头画面，统一到同样高度。"""
    ff = need(cfg, "ffmpeg")
    h = height // 2 * 2
    fc = f"[0:v]scale=-2:{h}[a];[1:v]scale=-2:{h}[b];[a][b]hstack=inputs=2,format=yuv420p[v]"
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", left_mp4, "-i", right_mp4, "-filter_complex", fc,
                        "-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS),
                        "-movflags", "+faststart", "-an", out_mp4],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        die(f"对照预览合成失败：{r.stderr.strip()[-400:]}")
    return out_mp4


def draw_blocking_map(data, out_png, with_cameras=False):
    Image, ImageDraw, _ = pil()
    img, tp, ppm = map_base(data)
    W, H = img.size
    d = ImageDraw.Draw(img, "RGBA")
    fnt = font(max(14, int(W / 70)))
    small = font(max(11, int(W / 95)))
    # 镜头：起始机位画视野扇形，移动路线画虚一点的线
    if with_cameras and data.get("camera_rows"):
        for sid, rows in data["camera_rows"].items():
            pts = [tp(r["pos"][0], r["pos"][1]) for r in rows]
            if len(pts) > 1:
                d.line(pts, fill=CAM_COLOR + (200,), width=3)
            r0 = rows[0]
            p = tp(r0["pos"][0], r0["pos"][1])
            cam_wedge(d, p, r0["yaw"], r0["lens"], max(40, ppm * 2.5), data["res"], CAM_COLOR + (45,), CAM_COLOR + (180,))
            d.ellipse([p[0] - 7, p[1] - 7, p[0] + 7, p[1] + 7], fill=(255, 255, 255, 240), outline=(0, 0, 0, 255), width=2)
            d.text((p[0] + 9, p[1] + 2), sid, fill=(0, 0, 0, 255), font=fnt, stroke_width=3, stroke_fill=(255, 255, 255, 255))
    # 人物
    for aid, a in data.get("actors", {}).items():
        col = hex_rgb(a["color"])
        pts = [tp(x, y) for x, y in a["pos"]]
        # 去重后画路径
        path = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - path[-1][0]) + abs(p[1] - path[-1][1]) > 0.5:
                path.append(p)
        if len(path) > 1:
            d.line(path, fill=col + (230,), width=max(3, int(ppm * 0.06)))
        r = max(6, a["radius"] * ppm)
        # 每个 key 的位置、时间、朝向；同一位置的多个时刻合并成一个标签
        groups = []
        for k in a["keys"]:
            f = min(len(a["pos"]) - 1, int(round(float(k.get("t", 0)) * FPS)))
            p = tp(*a["pos"][f])
            arrow(d, p, a["facing"][f], r * 2.2, col + (255,), width=3)
            for g in groups:
                if abs(g[0][0] - p[0]) + abs(g[0][1] - p[1]) < r:
                    g[1].append(float(k.get("t", 0)))
                    break
            else:
                groups.append((p, [float(k.get("t", 0))]))
        for p, ts in groups:
            d.text((p[0] + r + 3, p[1] + r * 0.2), " / ".join(f"{t:g}s" for t in ts), fill=(0, 0, 0, 255), font=small,
                   stroke_width=2, stroke_fill=(255, 255, 255, 255))
        p0, p1 = tp(*a["pos"][0]), tp(*a["pos"][-1])
        d.ellipse([p0[0] - r, p0[1] - r, p0[0] + r, p0[1] + r], outline=col + (255,), width=3)
        d.ellipse([p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r], fill=col + (255,), outline=(0, 0, 0, 255), width=1)
        d.text((p0[0] - r, p0[1] - r - fnt.size - 4), f"{a['name']}（起）", fill=col + (255,), font=fnt,
               stroke_width=3, stroke_fill=(255, 255, 255, 255))
    # 图例
    lines = ["空心圈=起点  实心圈=终点  箭头=朝向  数字=该时刻"]
    if with_cameras:
        lines.append("白点=镜头开始时的相机  黄色扇形=视野范围  黄线=相机移动路线")
    y = H - (len(lines)) * (small.size + 6) - 8
    for ln in lines:
        d.text((10, y), ln, fill=(0, 0, 0, 255), font=small, stroke_width=2, stroke_fill=(255, 255, 255, 255))
        y += small.size + 6
    draw_scale_bar(d, W, H, ppm)
    img.save(out_png)
    return out_png


def draw_scale_bar(d, W, H, ppm):
    for meters in (1, 2, 5, 10, 20, 50):
        if meters * ppm > W * 0.08:
            break
    x0, y0 = W - meters * ppm - 20, H - 30
    d.rectangle([x0, y0, x0 + meters * ppm, y0 + 8], fill=(0, 0, 0, 255))
    d.text((x0, y0 - 22), f"{meters} 米", fill=(0, 0, 0, 255), font=font(16), stroke_width=2, stroke_fill=(255, 255, 255, 255))


def plan_overlay(data, out_png):
    Image, _, _ = pil()
    plan = data["scene"].get("plan")
    if not plan:
        return None
    tv = Image.open(data["top_view"]["path"]).convert("RGB")
    pl = Image.open(plan["image"]).convert("RGB").resize(tv.size)
    mix = Image.blend(pl, tv, 0.5)
    draw_grid(mix, data["top_view"]["bounds"])
    mix.save(out_png)
    return out_png


def contact_sheet(frames_dir, data, out_png, every=12, cols=4, thumb_w=440):
    Image, ImageDraw, _ = pil()
    files = sorted(glob.glob(os.path.join(frames_dir, "*.png")))
    if not files:
        return None
    picks = list(range(0, len(files), every))
    first = Image.open(files[0])
    tw = thumb_w
    th = int(first.height * tw / first.width)
    rows = math.ceil(len(picks) / cols)
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 6, rows * (th + 26) + 6), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    shot_of = {}
    for s in data.get("shots", []):
        for f in range(s["f0"], s["f1"] + 1):
            shot_of[f] = s["id"]
    fnt = font(16)
    for i, idx in enumerate(picks):
        im = Image.open(files[idx]).resize((tw, th))
        x = 6 + (i % cols) * (tw + 6)
        y = 6 + (i // cols) * (th + 26)
        sheet.paste(im, (x, y + 20))
        frame = idx + 1
        d.text((x, y), f"{shot_of.get(frame, '')}  {(frame - 1) / FPS:.2f}s  第{frame}帧", fill=(230, 230, 230), font=fnt)
    sheet.save(out_png)
    return out_png


# ================================================================ 视频

def encode(cfg, frames_dir, out_mp4, start=1, count=None):
    ff = need(cfg, "ffmpeg")
    cmd = [ff, "-y", "-loglevel", "error", "-framerate", str(FPS), "-start_number", str(start),
           "-i", os.path.join(frames_dir, "%04d.png")]
    if count:
        cmd += ["-frames:v", str(count)]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-movflags", "+faststart", "-an", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        die(f"FFmpeg 合成失败：{r.stderr.strip()[-500:]}")
    return out_mp4


def probe(cfg, mp4):
    fp = cfg.get("ffprobe")
    if not fp:
        return None
    r = subprocess.run([fp, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate,nb_read_frames,codec_name,pix_fmt:format=duration,size",
                        "-of", "json", mp4], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return dict(error=r.stderr.strip())
    j = json.loads(r.stdout)
    s = j["streams"][0]
    has_audio = subprocess.run([fp, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", mp4],
                               capture_output=True, text=True).stdout.strip() != ""
    return dict(file=os.path.basename(mp4), width=s["width"], height=s["height"], fps=s["r_frame_rate"],
                frames=int(s.get("nb_read_frames", 0)), codec=s["codec_name"], pix_fmt=s["pix_fmt"],
                duration=float(j["format"]["duration"]), size_mb=round(int(j["format"]["size"]) / 1e6, 2),
                audio=has_audio)


def verify(info, n_frames, res):
    ok = (info and info.get("frames") == n_frames and info.get("fps") == f"{FPS}/1"
          and [info.get("width"), info.get("height")] == list(res) and not info.get("audio"))
    return ok


# ================================================================ 报告

def md_issues(issues):
    if not issues:
        return "没有发现问题。\n"
    out = []
    for level in ("警告", "提示"):
        items = [i for i in issues if i["level"] == level]
        if not items:
            continue
        out.append(f"### {level}（{len(items)} 条）\n")
        for i in items:
            who = i.get("shot") or i.get("actor") or ""
            t = f"{i['t0']:.2f}～{i['t1']:.2f}s" if abs(i["t1"] - i["t0"]) > 1e-6 else f"{i['t0']:.2f}s"
            out.append(f"- **{who}**（{t}）：{i['msg']}")
        out.append("")
    return "\n".join(out) + "\n"


def describe_move(s):
    """按相机自身的运动写运镜词（不受人物走动影响）。"""
    m = s.get("motion", {})
    parts = []
    if s.get("handheld", 0) > 0:
        parts.append("手持")
    travel = m.get("travel", 0)
    st = m.get("subject_travel", 0)
    if travel > 0.25:
        if st > 0.8 and travel > 0.4 * st:
            parts.append("跟")
        elif abs(m.get("orbit", 0)) > 20 and st < 0.5:
            parts.append("环绕")
        else:
            fwd, lat, ver = m.get("forward", 0), m.get("lateral", 0), m.get("vertical", 0)
            if abs(fwd) > 0.25 and abs(fwd) >= 0.5 * abs(lat):
                parts.append("推" if fwd > 0 else "拉")
            if abs(lat) > 0.25 and abs(lat) >= 0.5 * abs(fwd):
                parts.append("右移" if lat > 0 else "左移")
            if abs(ver) > 0.25:
                parts.append("升" if ver > 0 else "降")
    if "跟" not in parts and "环绕" not in parts:
        if abs(m.get("yaw", 0)) > 6:
            parts.append("左摇" if m["yaw"] > 0 else "右摇")
        if abs(m.get("pitch", 0)) > 5:
            parts.append("上摇" if m["pitch"] > 0 else "下摇")
    lr = m.get("lens_ratio", 1.0)
    if lr > 1.08 or lr < 1 / 1.08:
        parts.append("变焦推" if lr > 1 else "变焦拉")
    if not parts or parts == ["手持"]:
        parts.append("固定")
    return "、".join(parts)


def write_shot_table(data, path, version):
    L = [f"# 镜头参数表（{version}）\n",
         f"画幅 {data['res'][0]}×{data['res'][1]}，{FPS} 帧/秒，总长 {data['duration']:.2f} 秒，共 {len(data.get('shots', []))} 个镜头。\n",
         "景别、距离按主体眼睛位置估算；机高 = 相机离主体所站地面的高度。\n",
         "| 镜头 | 时间 | 帧 | 主体 | 景别（起→止） | 焦段 | 机高 | 角度 | 运镜 | 说明 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for s in data.get("shots", []):
        b, e = s["begin"], s["finish"]
        size = f"{b.get('size', '-')}→{e.get('size', '-')}" if b.get("size") != e.get("size") else b.get("size", "-")
        lens = f"{b['lens']:g}mm" if abs(b["lens"] - e["lens"]) < 0.5 else f"{b['lens']:g}→{e['lens']:g}mm"
        note = s.get("desc", "")
        if s.get("hidden"):
            note += f"（本镜隐藏：{'、'.join(s['hidden'])}）"
        L.append(f"| {s['id']} | {s['start']:.2f}～{s['end']:.2f}s | {s['f0']}～{s['f1']} | {'、'.join(s['subjects']) or '-'} | "
                 f"{size} | {lens} | {b['cam_h']:.2f}m | {b['angle']} | {describe_move(s)} | {note} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def write_handoff(data, path, version, video_name):
    L = [f"# Seedance 2.5 交接卡（{version}）\n",
         f"参考视频：`{video_name}`，{data['res'][0]}×{data['res'][1]}（21:9 时即 Seedance 原生宽银幕尺寸），{FPS} 帧/秒，"
         f"{data['duration']:.2f} 秒，{len(data.get('shots', []))} 个镜头，无声。\n",
         "这条灰模视频只用来锁定：**人物站位与走位、人物朝向、人物在空间中的位置、镜头构图与运镜、切镜节奏**。"
         "人物形象、建筑造型、材质、光影、动作细节都以最终提示词和参考图为准。\n",
         "## 颜色对照\n"]
    actors = list(data.get("actors", {}).values())
    noun = lambda a: "身体的人偶" if a.get("figure", "head") == "head" else "胶囊体"
    for a in actors:
        L.append(f"- {color_word(a['color'])}色（{a['color']}）{noun(a)} = **{a['name']}**（身高 {a['height']} 米）")
    has_head = any(a.get("figure", "head") == "head" for a in actors)
    if has_head:
        L.append("\n人偶头部**浅色的一面是脸，深色的一面是后脑**；身体左右宽、前后扁。看人偶就能分清人物面朝哪边。")
    L += ["", "## 镜头时间码\n", "| 镜头 | 时间 | 主体 | 景别 | 焦段 | 运镜 |", "|---|---|---|---|---|---|"]
    for s in data.get("shots", []):
        b = s["begin"]
        L.append(f"| {s['id']} | {s['start']:.2f}～{s['end']:.2f}s | {'、'.join(s['subjects']) or '-'} | "
                 f"{b.get('size', '-')} | {b['lens']:g}mm | {describe_move(s)} |")
    names = "，".join(f"{color_word(a['color'])}色{noun(a)}是{a['name']}" for a in actors)
    facing = "人偶头部浅色的一面是脸、深色的一面是后脑，人物面朝哪边以此为准；" if has_head else ""
    L += ["", "## 建议写进提示词的参考声明（按需修改）\n",
          f"> 参考(视频1)的镜头运动、节奏、景别变化、人物走位、人物朝向和人物之间的站位关系；视频中{names}；{facing}"
          "不参考视频中的人物外形、建筑造型、材质、颜色和光影，这些以提示词和参考图为准。\n",
          "参考视频每段不少于 4 秒、多条加起来不能超过 30 秒；超过 30 秒的预演已经拆成多段，分段生成后再剪辑。"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def color_word(hexc):
    r, g, b = hex_rgb(hexc)
    names = {"蓝": (47, 99, 214), "红": (217, 51, 43), "黄": (240, 196, 25), "绿": (47, 168, 79), "紫": (138, 70, 192),
             "橙": (240, 127, 29), "青": (29, 179, 191), "粉": (240, 117, 166), "白": (242, 242, 242), "黑": (26, 26, 26),
             "棕": (139, 90, 43)}
    return min(names, key=lambda k: sum((a - b_) ** 2 for a, b_ in zip(names[k], (r, g, b))))


def write_check_report(data, path, version, videos=None):
    L = [f"# 检查报告（{version}）\n"]
    if videos:
        L.append("## 视频参数核对\n")
        for v in videos:
            info, ok = v["info"], v["ok"]
            if not info:
                L.append(f"- {v['name']}：未能读取（缺 ffprobe）")
                continue
            L.append(f"- {'✅' if ok else '❌'} {info['file']}：{info['width']}×{info['height']}，{info['fps']} 帧/秒，"
                     f"{info['frames']} 帧（应为 {v['expect_frames']}），{info['duration']:.3f} 秒，{info['size_mb']} MB，"
                     f"{'有声音' if info['audio'] else '无声音'}")
        L.append("")
    L.append("## 自动检查\n")
    L.append(md_issues(data.get("issues", [])))
    if data.get("actors"):
        L.append("## 人物移动\n")
        for aid, a in data["actors"].items():
            for m in a.get("moves", []):
                L.append(f"- {a['name']}：{m['start']}～{m['end']}s 走 {m['length']} 米，平均 {m['avg_speed']} 米/秒，最快 {m['peak_speed']} 米/秒")
        L.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


# ================================================================ 命令

def cmd_setup(a):
    cfg = load_cfg()
    for k in ("blender", "ffmpeg", "ffprobe"):
        v = getattr(a, k, None)
        if v:
            if not os.path.isfile(v):
                die(f"{k} 路径不存在：{v}")
            cfg[k] = v
    os.makedirs(os.path.dirname(USER_CFG), exist_ok=True)
    with open(USER_CFG, "w", encoding="utf-8") as f:
        json.dump({k: cfg[k] for k in ("blender", "ffmpeg", "ffprobe")}, f, ensure_ascii=False, indent=2)
    print(f"配置已写入 {USER_CFG}")
    for k in ("blender", "ffmpeg", "ffprobe"):
        print(f"  {k}: {cfg[k] or '（没找到）'}")
    pil()
    print("  Pillow: 已安装")
    if cfg["blender"] and not a.no_probe:
        import tempfile
        out = os.path.join(tempfile.gettempdir(), "previs_probe")
        r = subprocess.run([cfg["blender"], "--background", "--factory-startup", "--python",
                            os.path.join(HERE, "probe_env.py"), "--", out],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        m = re.search(r"PROBE_JSON=(.*)", r.stdout)
        if not m:
            die("渲染实测失败，Blender 输出：\n" + r.stdout[-1500:])
        res = json.loads(m.group(1))
        print(f"  Blender 版本: {res['blender']}")
        for x in res["results"]:
            print(f"  渲染实测 {x['engine']}: {'能用' if x['ok'] else '不能用'}" + (f"，{x['seconds']} 秒/帧" if x.get("seconds") else ""))
        wb = [x for x in res["results"] if x["engine"] == "workbench"][0]
        if not wb["ok"]:
            die("Workbench 后台渲染不能用，本工具依赖它。请把 blender_log 发给维护者。")


TEMPLATES = os.path.join(SKILL_ROOT, "templates")


def cmd_init(a):
    p = os.path.abspath(a.project)
    for sub in ("input", "spec", "output"):
        os.makedirs(os.path.join(p, sub), exist_ok=True)
    for fn in ("scene.json", "blocking.json", "shots.json"):
        dst = os.path.join(p, "spec", fn)
        src = os.path.join(TEMPLATES, "example_" + fn)
        if not os.path.exists(dst) and os.path.exists(src) and a.example:
            shutil.copy2(src, dst)
    plan_src = os.path.join(TEMPLATES, "example_平面图.png")
    plan_dst = os.path.join(p, "input", "平面图.png")
    if a.example and os.path.exists(plan_src) and not os.path.exists(plan_dst):
        shutil.copy2(plan_src, plan_dst)
    print(f"项目文件夹已建好：{p}")
    print("  input\\  放平面图、参考图、分镜脚本")
    print("  spec\\   三张参数表 scene.json / blocking.json / shots.json")
    print("  output\\ 每次生成的版本（vNN_xxx）")


def read_scene_plan(project):
    with open(os.path.join(project, "spec", "scene.json"), "r", encoding="utf-8-sig") as f:
        sc = json.load(f)
    plan = sc.get("plan")
    if not plan:
        die("scene.json 里还没有 plan（平面图和比例）")
    return plan


def cmd_plan_grid(a):
    Image, _, _ = pil()
    project = os.path.abspath(a.project)
    plan = read_scene_plan(project)
    img_path = plan["image"] if os.path.isabs(plan["image"]) else os.path.join(project, plan["image"])
    img = Image.open(img_path).convert("RGB")
    W, H = img.size
    # 与 Blender 端同一套换算
    if "calib" in plan:
        p1, p2 = plan["calib"][:2]
        ppm = math.hypot(p2["px"][0] - p1["px"][0], p2["px"][1] - p1["px"][1]) / math.hypot(p2["m"][0] - p1["m"][0], p2["m"][1] - p1["m"][1])
        ox, oy = p1["px"][0] - p1["m"][0] * ppm, p1["px"][1] + p1["m"][1] * ppm
    else:
        ppm = float(plan["px_per_m"])
        ox, oy = plan.get("origin_px", [0, H])
    bounds = ((0 - ox) / ppm, (oy - H) / ppm, (W - ox) / ppm, (oy - 0) / ppm)
    draw_grid(img, bounds, step=a.step, label_every=a.label_every)
    out_dir = os.path.join(project, "output", "_平面图网格")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "平面图_米制网格.png")
    img.save(out)
    print(f"网格图：{out}")
    print(f"  {ppm:.2f} 像素/米；图片覆盖 X {bounds[0]:.2f}～{bounds[2]:.2f} 米，Y {bounds[1]:.2f}～{bounds[3]:.2f} 米")
    if a.crop:
        x0, y0, x1, y1 = a.crop
        box = (int((x0 * ppm) + ox), int(oy - y1 * ppm), int((x1 * ppm) + ox), int(oy - y0 * ppm))
        c = img.crop(box)
        k = max(1, int(1600 / max(c.size)))
        c = c.resize((c.width * k, c.height * k))
        cp = os.path.join(out_dir, f"局部_{x0:g}_{y0:g}_{x1:g}_{y1:g}.png")
        c.save(cp)
        print(f"局部放大：{cp}")


def stage_run(a, stage):
    cfg = load_cfg()
    project = os.path.abspath(a.project)
    if not os.path.exists(os.path.join(project, "spec", "scene.json")):
        die(f"{project}\\spec\\scene.json 不存在。先运行 init，并写好场景表。")
    out = next_version(project, stage, a.tag)
    version = os.path.basename(out)
    snapshot_spec(project, out)
    res = tuple(a.res) if getattr(a, "res", None) else None
    data = run_blender(cfg, project, out, stage, res=res, empty=getattr(a, "empty", False))
    made = []
    if stage == "scene":
        ov = plan_overlay(data, os.path.join(out, "俯视叠平面图.png"))
        if ov:
            made.append(ov)
        Image, _, _ = pil()
        g = Image.open(data["top_view"]["path"]).convert("RGB")
        draw_grid(g, data["top_view"]["bounds"])
        g.save(os.path.join(out, "俯视图_米制网格.png"))
        made += [os.path.join(out, "俯视图_米制网格.png")] + data.get("check_views", [])
    if stage in ("blocking", "preview", "final"):
        made.append(draw_blocking_map(data, os.path.join(out, "俯视走位图.png"), with_cameras=stage != "blocking"))
        print("[previs] 生成俯视走位预览视频……", flush=True)
        topdown = render_topdown_video(cfg, data, os.path.join(out, "俯视走位预览.mp4"), with_cameras=stage != "blocking")
        made.append(topdown)
    videos = []
    if stage in ("preview", "final"):
        name = "预览_低清.mp4" if stage == "preview" else "预演_完整版.mp4"
        mp4 = encode(cfg, data["frames_dir"], os.path.join(out, name))
        info = probe(cfg, mp4)
        videos.append(dict(name=name, info=info, ok=verify(info, data["n_frames"], data["res"]), expect_frames=data["n_frames"]))
        made.append(mp4)
        made.append(side_by_side(cfg, topdown, mp4, os.path.join(out, "对照预览.mp4"), max(540, data["res"][1])))
        if data.get("frames_empty_dir"):
            e = encode(cfg, data["frames_empty_dir"], os.path.join(out, "预演_空场版.mp4"))
            info = probe(cfg, e)
            videos.append(dict(name="预演_空场版.mp4", info=info, ok=verify(info, data["n_frames"], data["res"]), expect_frames=data["n_frames"]))
            made.append(e)
        # 参考视频单段最短按 4 秒算（见插件 shared/Seedance平台.md）
        if data["duration"] < 4.0 - 1e-6:
            data["issues"].append(dict(level="警告", shot="全片", t0=0.0, t1=data["duration"],
                                       msg=f"整条预演只有 {data['duration']:.2f} 秒，不足 4 秒，不能作为 Seedance 参考视频。把镜头时长加到 4 秒以上。"))
        # 超过 30 秒：按镜头拆段
        if data["duration"] > 30.0 + 1e-6:
            parts, cur = [], []
            for s in data["shots"]:
                if cur and s["end"] - cur[0]["start"] > 30.0 + 1e-6:
                    parts.append(cur)
                    cur = []
                cur.append(s)
            parts.append(cur)
            for i, p in enumerate(parts, 1):
                f0, f1 = p[0]["f0"], p[-1]["f1"]
                pm = encode(cfg, data["frames_dir"], os.path.join(out, f"{name[:-4]}_第{i}段.mp4"), f0, f1 - f0 + 1)
                made.append(pm)
                data["issues"].append(dict(level="提示", shot=f"第{i}段", t0=p[0]["start"], t1=p[-1]["end"],
                                           msg=f"总长超过 30 秒，已拆出第 {i} 段（{p[0]['id']}～{p[-1]['id']}）。"))
                # 参考视频单段最短按 4 秒算（见插件 shared/Seedance平台.md）
                seg = p[-1]["end"] - p[0]["start"]
                if seg < 4.0 - 1e-6:
                    data["issues"].append(dict(level="警告", shot=f"第{i}段", t0=p[0]["start"], t1=p[-1]["end"],
                                               msg=f"第 {i} 段只有 {seg:.2f} 秒，不足 4 秒，不能单独作为 Seedance 参考视频。调整镜头时长，让每段都不少于 4 秒。"))
        if getattr(a, "per_shot", False):
            sd = os.path.join(out, "分镜头")
            os.makedirs(sd, exist_ok=True)
            for s in data["shots"]:
                made.append(encode(cfg, data["frames_dir"], os.path.join(sd, f"{s['id']}.mp4"), s["f0"], s["f1"] - s["f0"] + 1))
                if s["end"] - s["start"] < 4.0 - 1e-6:
                    data["issues"].append(dict(level="提示", shot=s["id"], t0=s["start"], t1=s["end"],
                                               msg=f"单镜视频只有 {s['end'] - s['start']:.2f} 秒，不足 4 秒，不要单独喂给 Seedance；用完整版，或和相邻镜头一起用。"))
        # 首尾帧
        fd = os.path.join(out, "首尾帧")
        os.makedirs(fd, exist_ok=True)
        for s in data["shots"]:
            for tag, f in (("首", s["f0"]), ("尾", s["f1"])):
                src = os.path.join(data["frames_dir"], f"{f:04d}.png")
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(fd, f"{s['id']}_{tag}.png"))
        made.append(contact_sheet(data["frames_dir"], data, os.path.join(out, "联系表.png")))
        write_shot_table(data, os.path.join(out, "镜头参数表.md"), version)
        write_handoff(data, os.path.join(out, "Seedance交接卡.md"), version, name)
        if not a.keep_frames:
            shutil.rmtree(data["frames_dir"], ignore_errors=True)
            if data.get("frames_empty_dir"):
                shutil.rmtree(data["frames_empty_dir"], ignore_errors=True)
    write_check_report(data, os.path.join(out, "检查报告.md"), version, videos)
    n_warn = sum(1 for i in data.get("issues", []) if i["level"] == "警告")
    n_tip = sum(1 for i in data.get("issues", []) if i["level"] == "提示")
    print(f"\n完成：{out}")
    print(f"  自动检查：{n_warn} 条警告，{n_tip} 条提示（详见 检查报告.md）")
    for v in videos:
        print(f"  {'✅' if v['ok'] else '❌'} {v['name']} 规格核对")
    for m in made:
        if m:
            print(f"  - {os.path.relpath(m, out)}")
    print(f"RESULT_DIR={out}")


def cmd_open(a):
    cfg = load_cfg()
    project = os.path.abspath(a.project)
    out_root = os.path.join(project, "output")
    if a.version:
        cands = [d for d in os.listdir(out_root) if d.startswith(a.version)]
    else:
        cands = sorted(d for d in os.listdir(out_root) if re.match(r"v\d+", d))
    cands = [d for d in cands if os.path.exists(os.path.join(out_root, d, "工程.blend"))]
    if not cands:
        die("没找到可打开的版本")
    blend = os.path.join(out_root, cands[-1], "工程.blend")
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([need(cfg, "blender"), blend], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    print(f"已用 Blender 打开：{blend}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Blender 灰模预演")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--blender")
    s.add_argument("--ffmpeg")
    s.add_argument("--ffprobe")
    s.add_argument("--no-probe", action="store_true")
    s = sub.add_parser("init")
    s.add_argument("project")
    s.add_argument("--example", action="store_true", help="放入示例参数表")
    s = sub.add_parser("plan-grid")
    s.add_argument("project")
    s.add_argument("--step", type=float, default=1.0)
    s.add_argument("--label-every", type=int, default=5)
    s.add_argument("--crop", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"))
    for st in ("scene", "blocking", "preview", "final"):
        s = sub.add_parser(st)
        s.add_argument("project")
        s.add_argument("--tag", default="")
        s.add_argument("--res", nargs=2, type=int, metavar=("W", "H"))
        s.add_argument("--keep-frames", action="store_true")
        if st == "final":
            s.add_argument("--empty", action="store_true", help="另出一条不带人物的空场版")
            s.add_argument("--per-shot", action="store_true", help="每个镜头单独导出一条")
    s = sub.add_parser("open")
    s.add_argument("project")
    s.add_argument("version", nargs="?")
    a = p.parse_args()
    if a.cmd == "setup":
        cmd_setup(a)
    elif a.cmd == "init":
        cmd_init(a)
    elif a.cmd == "plan-grid":
        cmd_plan_grid(a)
    elif a.cmd == "open":
        cmd_open(a)
    else:
        stage_run(a, a.cmd)


if __name__ == "__main__":
    main()
