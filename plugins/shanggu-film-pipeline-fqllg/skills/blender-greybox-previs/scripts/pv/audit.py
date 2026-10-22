# -*- coding: utf-8 -*-
"""自动检查：主体在不在画面、有没有被挡、相机位置、运镜速度、切镜规则。"""
import math

from .spec import FPS, f2t
from . import mathutil as mu
from .scene_builder import SceneQuery

SIZE_BANDS = [(0.30, "大特写"), (0.45, "特写"), (0.65, "近景"), (0.90, "中近景"), (1.25, "中景"),
              (1.80, "中全景"), (3.50, "全景"), (8.0, "远景"), (1e9, "大远景")]


def size_name(coverage):
    for lim, name in SIZE_BANDS:
        if coverage <= lim:
            return name
    return "大远景"


def angle_name(elev):
    """elev：从主体眼睛看相机的仰角（度）。相机比眼睛高 = 俯拍，比眼睛低 = 仰拍。"""
    if elev > 35:
        return "大俯角"
    if elev > 10:
        return "俯拍"
    if elev >= -10:
        return "平视"
    if elev >= -35:
        return "仰拍"
    return "大仰角"


def group_ranges(frames):
    out = []
    for f in sorted(frames):
        if out and f <= out[-1][1] + 1:
            out[-1][1] = f
        else:
            out.append([f, f])
    return out


def rng(r):
    return f"{f2t(r[0]):.2f}～{f2t(r[1] + 1):.2f}s"


def cam_fwd(row):
    return mu.view_dir(row["yaw"], row["pitch"])


def audit_shots(shot_infos, rows_by_shot, actors, res, hidden_by_shot, log):
    issues = []
    summaries = []
    base_query = SceneQuery()
    for si in shot_infos:
        rows = rows_by_shot[si["id"]]
        q = SceneQuery(exclude=hidden_by_shot.get(si["id"], set())) if hidden_by_shot.get(si["id"]) else base_query
        out_frames, top_cut, occluded, inside, below, too_close = {}, set(), {}, {}, set(), {}
        for r in rows:
            f = r["frame"]
            for aid in si["subjects"]:
                a = actors[aid]
                pts = a.points(f)
                # 相机贴到/穿过人物：到身体轴线的水平距离太小，且高度在身体范围内
                if (mu.dist2d(r["pos"], pts["base"]) < a.r + 0.25
                        and pts["base"][2] - 0.1 < r["pos"][2] < pts["top"][2] + 0.1):
                    too_close.setdefault(a.name, set()).add(f)
                ex, ey, ez = mu.project(r["pos"], r["yaw"], r["pitch"], r["roll"], r["lens"], res[0], res[1], pts["eye"])
                if ez <= 0 or not (0.02 <= ex <= 0.98 and 0.02 <= ey <= 0.98):
                    out_frames.setdefault(a.name, set()).add(f)
                else:
                    tx, ty, tz = mu.project(r["pos"], r["yaw"], r["pitch"], r["roll"], r["lens"], res[0], res[1], pts["top"])
                    _, vf = mu.fovs(r["lens"], res[0], res[1])
                    cov = 2 * mu.dist3d(r["pos"], pts["eye"]) * math.tan(vf / 2)
                    if ty > 1.0 and cov > 1.0:
                        top_cut.add(f)
                    if not si["occlusion_ok"]:
                        for part in ("eye", "body"):
                            h = q.first_hit(r["pos"], pts[part])
                            if h:
                                occluded.setdefault(h[0], set()).add(f)
                                break
            ins = q.inside_solid(r["pos"])
            if ins:
                inside.setdefault(ins, set()).add(f)
            fz = q.floor_z(r["pos"][0], r["pos"][1], r["pos"][2], max_up=0.0, default=-1e9)
            if r["pos"][2] < fz + 0.05:
                below.add(f)
        for name, fr in out_frames.items():
            for g in group_ranges(fr):
                issues.append(dict(level="警告", shot=si["id"], t0=f2t(g[0]), t1=f2t(g[1] + 1),
                                   msg=f"{name} 不在画面里（{rng(g)}）。调整机位/画面位置 frame，或确认是故意出画。"))
        for g in group_ranges(top_cut):
            issues.append(dict(level="提示", shot=si["id"], t0=f2t(g[0]), t1=f2t(g[1] + 1),
                               msg=f"中景以上景别头顶被裁（{rng(g)}），一般要留一点头顶空间。"))
        for name, fr in occluded.items():
            for g in group_ranges(fr):
                if g[1] - g[0] + 1 < 3:
                    continue
                issues.append(dict(level="警告", shot=si["id"], t0=f2t(g[0]), t1=f2t(g[1] + 1),
                                   msg=f"主体被「{name}」挡住（{rng(g)}）。挪机位，或在这个镜头的 hide 里隐藏它；"
                                       f"如果是故意的前景遮挡，写 \"occlusion_ok\": true。"))
        for name, fr in inside.items():
            for g in group_ranges(fr):
                issues.append(dict(level="警告", shot=si["id"], t0=f2t(g[0]), t1=f2t(g[1] + 1),
                                   msg=f"相机在「{name}」里面（{rng(g)}），画面会被它挡死。挪机位或在 hide 里隐藏它。"))
        for name, fr in too_close.items():
            for g in group_ranges(fr):
                issues.append(dict(level="警告", shot=si["id"], t0=f2t(g[0]), t1=f2t(g[1] + 1),
                                   msg=f"相机贴到或穿过了 {name} 的身体（{rng(g)}）。加大距离或换机位。"))
        for g in group_ranges(below):
            issues.append(dict(level="警告", shot=si["id"], t0=f2t(g[0]), t1=f2t(g[1] + 1),
                               msg=f"相机低于地面（{rng(g)}）。"))
        # ---- 运镜速度
        ang_v, lin_v = [0.0], [0.0]
        for r0, r1 in zip(rows, rows[1:]):
            a, b = cam_fwd(r0), cam_fwd(r1)
            dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))
            ang_v.append(math.degrees(math.acos(dot)) * FPS)
            lin_v.append(mu.dist3d(r0["pos"], r1["pos"]) * FPS)
        if len(ang_v) > 1:
            ang_v[0] = ang_v[1]
            lin_v[0] = lin_v[1]
        fast = [r["frame"] for r, v in zip(rows, ang_v) if v > si["max_pan"]]
        for g in group_ranges(fast):
            seg = [v for r, v in zip(rows, ang_v) if g[0] <= r["frame"] <= g[1]]
            issues.append(dict(level="警告", shot=si["id"], t0=f2t(g[0]), t1=f2t(g[1] + 1),
                               msg=f"转得太快：{rng(g)} 最快约 {max(seg):.0f}°/秒（上限 {si['max_pan']:.0f}°/秒）。"
                                   f"拉长这段时间或减小转动角度；跟拍人物拐弯时可以加大 dist（离远一点），"
                                   f"或给人物这段路写更大的 round（拐角半径）；确实要快摇就在镜头里写 max_pan。"))
        if si["handheld"] <= 0:
            jerk = []
            for i in range(1, len(rows)):
                acc_a = abs(ang_v[i] - ang_v[i - 1]) * FPS
                acc_l = abs(lin_v[i] - lin_v[i - 1]) * FPS
                if acc_a > 80 or acc_l > 5:
                    jerk.append(rows[i]["frame"])
            for g in group_ranges(jerk):
                issues.append(dict(level="警告", shot=si["id"], t0=f2t(g[0]), t1=f2t(g[1] + 1),
                                   msg=f"运动突然加速或急停（{rng(g)}），画面会顿一下。检查 ease 或关键点时间。"))
        # ---- 摘要
        r0, rm, r1 = rows[0], rows[len(rows) // 2], rows[-1]
        def describe(r):
            d = {}
            if si["subjects"]:
                a = actors[si["subjects"][0]]
                p = a.points(r["frame"])
                dist = mu.dist3d(r["pos"], p["eye"])
                _, vf = mu.fovs(r["lens"], res[0], res[1])
                cov = 2 * dist * math.tan(vf / 2)
                d.update(subject=a.name, dist=round(dist, 2), size=size_name(cov * 1.75 / a.H))
                d["cam_h"] = round(r["pos"][2] - a.base_z[r["frame"] - 1], 2)
                elev = math.degrees(math.atan2(r["pos"][2] - p["eye"][2], max(0.05, mu.dist2d(r["pos"], p["eye"]))))
            else:
                d["cam_h"] = round(r["pos"][2], 2)
                elev = -r["pitch"]
            d.update(lens=round(r["lens"], 1), angle=angle_name(elev), pitch=round(r["pitch"], 1),
                     pos=[round(v, 2) for v in r["pos"]])
            return d
        moving = max(ang_v) > 2.0 or max(lin_v) > 0.1
        # 相机自身的运动（用来自动写"推/拉/摇/移/跟/升降/环绕/变焦"）
        disp = [r1["pos"][i] - r0["pos"][i] for i in range(3)]
        fw = cam_fwd(rm)
        fh = math.hypot(fw[0], fw[1]) or 1.0
        fx, fy = fw[0] / fh, fw[1] / fh
        motion = dict(forward=round(disp[0] * fx + disp[1] * fy, 2),
                      lateral=round(disp[0] * fy - disp[1] * fx, 2),   # 正 = 向画面右侧
                      vertical=round(disp[2], 2),
                      travel=round(mu.dist3d(r0["pos"], r1["pos"]), 2),
                      yaw=round(r1["yaw"] - r0["yaw"], 1), pitch=round(r1["pitch"] - r0["pitch"], 1),
                      lens_ratio=round(r1["lens"] / r0["lens"], 3))
        if si["subjects"]:
            a = actors[si["subjects"][0]]
            s0, s1 = a.points(r0["frame"])["base"], a.points(r1["frame"])["base"]
            motion["subject_travel"] = round(mu.dist2d(s0, s1), 2)
            b0 = mu.dir_to_facing(r0["pos"][0] - s0[0], r0["pos"][1] - s0[1])
            b1 = mu.dir_to_facing(r1["pos"][0] - s1[0], r1["pos"][1] - s1[1])
            motion["orbit"] = round(mu.angle_diff(b0, b1), 1)
        summaries.append(dict(id=si["id"], start=si["start"], end=si["end"], dur=round(si["end"] - si["start"], 3),
                              f0=si["f0"], f1=si["f1"], subjects=[actors[a].name for a in si["subjects"]],
                              begin=describe(r0), middle=describe(rm), finish=describe(r1),
                              peak_pan=round(max(ang_v), 1), peak_speed=round(max(lin_v), 2), moving=moving,
                              motion=motion, hidden=si.get("hidden", []), auto_hidden=si.get("auto_hidden", []),
                              end_moving=(ang_v[-1] > 2.0 or lin_v[-1] > 0.1),
                              start_moving=(ang_v[0] > 2.0 or lin_v[0] > 0.1),
                              handheld=si["handheld"], desc=si.get("desc", "")))
        if si["end"] - si["start"] < 1.5:
            issues.append(dict(level="提示", shot=si["id"], t0=si["start"], t1=si["end"],
                               msg=f"镜头只有 {si['end'] - si['start']:.2f} 秒，短于 1.5 秒，确认是否需要这么快的切。"))
    issues += audit_cuts(shot_infos, rows_by_shot, actors, res, summaries)
    return issues, summaries


def audit_cuts(shot_infos, rows_by_shot, actors, res, summaries):
    issues = []
    for i in range(len(shot_infos) - 1):
        a, b = shot_infos[i], shot_infos[i + 1]
        ra, rb = rows_by_shot[a["id"]][-1], rows_by_shot[b["id"]][0]
        f = rb["frame"]
        common = [s for s in a["subjects"] if s in b["subjects"]]
        tag = f"{a['id']}→{b['id']}"
        # 越轴：两人在画面中的左右关系对调
        pair = [s for s in set(a["subjects"]) | set(b["subjects"])]
        if len(pair) >= 2:
            p, q = pair[0], pair[1]
            def order(r, fr):
                xp = mu.project(r["pos"], r["yaw"], r["pitch"], r["roll"], r["lens"], res[0], res[1], actors[p].points(fr)["eye"])
                xq = mu.project(r["pos"], r["yaw"], r["pitch"], r["roll"], r["lens"], res[0], res[1], actors[q].points(fr)["eye"])
                if xp[2] <= 0 or xq[2] <= 0:
                    return None
                return xp[0] < xq[0]
            oa, ob = order(ra, f - 1), order(rb, f)
            if oa is not None and ob is not None and oa != ob:
                issues.append(dict(level="警告", shot=tag, t0=f2t(f), t1=f2t(f),
                                   msg=f"越轴：切镜后 {actors[p].name} 和 {actors[q].name} 在画面里左右对调了。"
                                       f"两台相机要待在两人连线的同一侧；如果是故意越轴，确认有过渡。"))
        # 30 度规则
        for s in common:
            pa, pb = actors[s].points(f - 1)["eye"], actors[s].points(f)["eye"]
            va = (ra["pos"][0] - pa[0], ra["pos"][1] - pa[1])
            vb = (rb["pos"][0] - pb[0], rb["pos"][1] - pb[1])
            ang = abs(mu.angle_diff(mu.dir_to_facing(*va), mu.dir_to_facing(*vb)))
            sa = ra["lens"] / max(mu.dist3d(ra["pos"], pa), 0.1)
            sb = rb["lens"] / max(mu.dist3d(rb["pos"], pb), 0.1)
            ratio = max(sa, sb) / min(sa, sb)
            if ang < 30 and ratio < 1.5:
                issues.append(dict(level="警告", shot=tag, t0=f2t(f), t1=f2t(f),
                                   msg=f"跳切风险：切镜前后拍 {actors[s].name} 的角度只差 {ang:.0f}°、大小只差 {ratio:.1f} 倍。"
                                       f"角度至少差 30°，或景别差两级（比如中景切近景特写）。"))
        # 动接动、静接静
        sa_, sb_ = summaries[i], summaries[i + 1]
        if sa_["end_moving"] != sb_["start_moving"]:
            k = "动接静" if sa_["end_moving"] else "静接动"
            issues.append(dict(level="提示", shot=tag, t0=f2t(f), t1=f2t(f),
                               msg=f"{k}：前一镜结尾{'在动' if sa_['end_moving'] else '是静止'}，后一镜开头{'在动' if sb_['start_moving'] else '是静止'}。"
                                   f"一般动接动、静接静更顺；如果切点在人物动作中间，也可以接受。"))
    return issues
