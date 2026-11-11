"""v4.34 各階の天井視点の見下ろし（T1・T2）と各室の斜めカット（R、37 枚）の駆動（システムの python3）。定義は data/interior_rooms.yaml。
spec.yaml・interior_zones.yaml・既存 57 カメラには触らない。撮影は src/shoot.py（マスター .blend）。

    python3 src/render_rooms.py --plan                 # 視点・向きを決めて yaml の cuts: に固定する（override は保持）
    python3 src/render_rooms.py --check                # Blender なし: 離隔・角度・正面距離・高さの検査
    python3 src/render_rooms.py --preview              # 480×270・16spp で露出を確認し、範囲外のカットだけ 1 回 ±0.5 を override へ書く
    python3 src/render_rooms.py --shoot [--background] [--floor 1F|2F|T] [--only ID,..]   # 本番（6 カットずつ。JPEG があり定義が同じカットは飛ばす）
    python3 src/render_rooms.py --sheet                # コンタクトシート・docs 用画像・検査レポート
    python3 src/render_rooms.py --white-plate          # 白い拡散板の試し撮り（色温度の実測）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

YAML = ROOT / "data" / "interior_rooms.yaml"
MARK = "# ---- 以下は src/render_rooms.py --plan が書く"
OUT = ROOT / "dist" / "render" / "interior"
CACHE = ROOT / ".cache" / "cg" / "rooms"
LOG = ROOT / "dist" / "render" / "render_log.json"
SHOOT = ROOT / "src" / "shoot.py"
T_IDS = {"1F": "T1_plan_1F", "2F": "T2_plan_2F"}
CORNERS = ("SW", "SE", "NE", "NW")


def load():
    return yaml.safe_load(YAML.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 定義 → カット（master・shoot が使う）
def room_label(c):
    return c.get("room", "")


def cut_defs(h, Y=None):
    """yaml → {id: dict(cid, kind R/T, floor, room, spec, ...)}。spec は interior_cg.cuts と同じ形のカット項目。"""
    Y = Y or load()
    st = Y["settings"]
    out = {}
    for cid, c in Y.get("cuts", {}).items():
        z = h.fl[c["floor"]] + st["eye_above_fl_mm"]
        if c["kind"] == "T":
            pl = st["plan"]
            cx, cy = pl["center"]
            zc = h.fl[c["floor"]] + pl["cam_above_fl_mm"]
            spec = dict(file=cid, title=c["title"], cam=[cx, cy, zc], target=[cx, cy + 1000, zc], lens=26, when=st["when"], exposure=c.get("exposure", pl["exposure"]), wb=st["wb"],
                        shift_y=0.0, pitch=-90, screens=st["screens"], sun_k=st["sun_k"], ortho_scale=pl["ortho_scale_m"], clip_start=pl["clip_mm"] / 1000.0,
                        section="Section_" + c["floor"], hide_pergola=True)
        else:
            yaw = math.radians(c["yaw"])
            L = st["look_dist_mm"]
            spec = dict(file=cid, title=f"{cid} {c['room']}", cam=[c["x"], c["y"], z], target=[c["x"] + math.cos(yaw) * L, c["y"] + math.sin(yaw) * L, z], lens=c["lens"],
                        when=st["when"], exposure=c.get("exposure", st["exposure_theater"] if c.get("theater") else st["exposure"]), wb=st["wb"], shift_y=st["shift_y"],
                        pitch=st["pitch"], screens=st["screens"], sun_k=st["sun_k"])
            if c.get("open_doors"):
                spec["open_doors"] = c["open_doors"]
        out[cid] = dict(cid=cid, kind=c["kind"], floor=c["floor"], room=c.get("room", ""), cut=c, spec=spec)
    return out


def def_hash(d):
    s = d["spec"]
    key = json.dumps([s["cam"], s["target"], s["lens"], s["exposure"], s["when"], s.get("open_doors", {}), s["shift_y"], s["wb"], s["screens"], s["sun_k"],
                      s.get("ortho_scale"), s.get("clip_start")], sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def section_boxes(h, Y=None):
    """T の断面キャップ。FL+2,400 の水平面が貫く壁・間仕切・外断熱は濃灰、造作家具は中灰。[{floor, kind, rect, z}]（建物座標 mm）。"""
    import furniture
    Y = Y or load()
    st = Y["settings"]["plan"]
    out = []
    its = furniture.items(h)
    for fl in ("1F", "2F"):
        cz = h.fl[fl] + st["section_above_fl_mm"]
        for b in h.boxes:
            if b.cat in ("wall", "partition", "insul", "parapet", "column") and b.z0 < cz < b.z1 and b.level != "FDN":
                out.append(dict(floor=fl, kind="wall" if b.cat != "insul" else "insul", rect=[round(b.x0, 1), round(b.y0, 1), round(b.x1, 1), round(b.y1, 1)], z=cz))
        for it in its:
            if it.floor == fl and it.z0 < cz < it.z0 + it.h:
                out.append(dict(floor=fl, kind="furniture", rect=[round(v, 1) for v in it.rect], z=cz))
    return out


# ------------------------------------------------------------------ 計画（--plan）
def dirv(deg):
    return math.cos(math.radians(deg)), math.sin(math.radians(deg))


def wall_angle(yaw):
    a = yaw % 90.0
    return min(a, 90.0 - a)


def clamp_yaw(yaw, lo):
    """壁に対する角度を [lo, 90-lo] に収める（同じ象限のまま、近いほうの端へ）。"""
    if wall_angle(yaw) >= lo - 1e-9:
        return yaw
    base = math.floor(yaw / 90.0) * 90.0
    a = yaw - base
    return base + (lo if a < 45.0 else 90.0 - lo)


def rooms_of(h, tg):
    rects = []
    for i, nm in enumerate(tg["rooms"]):
        rs = [r for r in h.rooms if r.floor == tg["floor"] and r.name == nm and (i > 0 or (r.rect[0] <= tg["anchor"][0] <= r.rect[2] and r.rect[1] <= tg["anchor"][1] <= r.rect[3]))]
        if not rs and nm == "蓄電室":
            rs = [h.battery_room]
        assert rs, (tg, nm)
        rects.append(rs[0].rect)
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)], rects


def front_dist(h, its, cam, yaw):
    """向きの先の壁・間仕切・窓・扉・階段・カメラの高さにかかる家具までの距離（mm）。"""
    import render_zones as RZ
    dx, dy = dirv(yaw)
    best = RZ.front_distance(h, cam, (dx, dy))
    x, y, z = cam
    for it in its:
        if not (it.z0 <= z <= it.z0 + it.h):
            continue
        t0, t1, ok = -1e9, 1e9, True
        for o, dd, lo, hi in ((x, dx, it.rect[0], it.rect[2]), (y, dy, it.rect[1], it.rect[3])):
            if abs(dd) < 1e-9:
                if not (lo <= o <= hi):
                    ok = False
                    break
            else:
                a, c = (lo - o) / dd, (hi - o) / dd
                t0, t1 = max(t0, min(a, c)), min(t1, max(a, c))
        if ok and t0 <= t1 and t1 >= 0:
            best = min(best, max(t0, 0.0))
    return best


def exterior_windows(h):
    import blend_master as BM
    return [o for o in BM.opening_items(h) if o["kind"] == "window" and o["side"] in ("N", "S", "E", "W")]


def windows_in_view(h, wins, cam, yaw, hfov, floor, rect):
    """部屋の窓のうち、視野（水平）に中心が入るもの。"""
    out = []
    for w in wins:
        if w["floor"] != floor or not (rect[0] - 400 <= w["x"] <= rect[2] + 400 and rect[1] - 400 <= w["y"] <= rect[3] + 400):
            continue
        a = math.degrees(math.atan2(w["y"] - cam[1], w["x"] - cam[0]))
        if abs((a - yaw + 180) % 360 - 180) <= hfov / 2 - 3:
            out.append(w["label"])
    return out


def sun_info(Y):
    import render_cg as RC
    from house import House
    h = House(ROOT)
    sp = h.spec["cg"]["site"]
    el, az = RC.sun_position(Y["settings"]["when"], sp["lat"], sp["lon"], sp["tz"])
    return el, az, az + math.degrees(h.alpha)


def room_state(h, Y, floor, rect, theater):
    """室の窓: 直射（東面の窓）・ZIP スクリーンを下ろす窓（auto: 直射を受ける面、寝室の遮光生地は上げる）。"""
    el, az, az_b = sun_info(Y)
    sun_math = 90.0 - az_b
    face = {"E": 0.0, "N": 90.0, "W": 180.0, "S": 270.0}
    direct, down, up_bo = [], [], []
    for w in exterior_windows(h):
        if w["floor"] != floor or not (rect[0] - 400 <= w["x"] <= rect[2] + 400 and rect[1] - 400 <= w["y"] <= rect[3] + 400):
            continue
        c = math.cos(math.radians(face[w["side"]] - sun_math))
        if c > 0.5:
            direct.append(w["label"])
            if any(k in w["name"] for k in ("居室", "主寝室")):
                up_bo.append(w["label"])
            else:
                down.append(w["label"])
    return dict(direct=bool(direct), sun_windows=direct, screens_down=down, blackout_raised=up_bo)


def plan_room(h, its, Y, cid, tg, wins, void_rects):
    import render_interior as RI
    st, pl, ck = Y["settings"], Y["settings"]["placement"], Y["checks"]
    rect, parts = rooms_of(h, tg)
    x0, y0, x1, y1 = rect
    W, D = x1 - x0, y1 - y0
    area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in parts) / 1e6
    z = h.fl[tg["floor"]] + st["eye_above_fl_mm"]
    ix, iy = min(pl["corner_inset_mm"], W / 2), min(pl["corner_inset_mm"], D / 2)
    pts = {"SW": (x0 + ix, y0 + iy), "SE": (x1 - ix, y0 + iy), "NE": (x1 - ix, y1 - iy), "NW": (x0 + ix, y1 - iy)}
    opp = {"SW": "NE", "SE": "NW", "NE": "SW", "NW": "SE"}
    theater = "シアター" in tg["rooms"][0]
    lo, hi = pl["angle_deg"]

    def in_rect(x, y):
        return any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in parts) and not any(v[0] <= x <= v[2] and v[1] <= y <= v[3] for v in void_rects)

    def evaluate(x, y, yaw, lens):
        cam = [round(x), round(y), z]
        clr = RI.camera_clearance(h, its, [dict(id="c", cam_mm=cam)])["c"]
        fr = front_dist(h, its, cam, yaw)
        return cam, clr, fr

    ok_list, fail_note = [], []
    for ci, c in enumerate(CORNERS):
        p, q = pts[c], pts[opp[c]]
        dxx, dyy = q[0] - p[0], q[1] - p[1]
        ln = math.hypot(dxx, dyy)
        yaw0 = math.degrees(math.atan2(dyy, dxx)) if ln > 1 else {"SW": 45, "SE": 135, "NE": 225, "NW": 315}[c]
        yaw = clamp_yaw(yaw0 % 360.0, lo)
        found = None
        for k in range(0, int(pl["inset_max_mm"] / pl["inset_step_mm"]) + 1):
            s = k * pl["inset_step_mm"]
            if ln > 1 and s > ln / 2:
                break
            x, y = (p[0] + dxx / ln * s, p[1] + dyy / ln * s) if ln > 1 else p
            if not in_rect(x, y):
                continue
            cam, clr, fr = evaluate(x, y, yaw, 26)
            if clr["mm"] >= ck["clearance_min_mm"] and fr >= ck["front_min_mm"]:
                found = (cam, clr, fr, s)
                break
        if found:
            cam, clr, fr, s = found
            lens = st["lens_small"] if (area < 10 or fr < 2500) else st["lens_std"]
            hf = math.degrees(2 * math.atan(18.0 / lens))
            wv = windows_in_view(h, wins, cam, yaw, hf, tg["floor"], rect)
            ok_list.append(dict(corner=c, order=ci, x=cam[0], y=cam[1], yaw=round(yaw, 1), inset=s, front=round(fr), clear=clr, lens=lens, windows=wv))
        else:
            fail_note.append(c)
    base = dict(kind="R", floor=tg["floor"], room="・".join(dict.fromkeys(tg["rooms"])) if len(tg["rooms"]) > 1 else tg["rooms"][0], area=round(area, 1), theater=theater)
    if ok_list:
        ok_list.sort(key=lambda o: (0 if o["windows"] else 1, -o["front"], o["order"]))
        o = ok_list[0]
        base.update(corner=o["corner"], x=o["x"], y=o["y"], yaw=o["yaw"], inset=o["inset"], lens=o["lens"], front_mm=o["front"], clearance_mm=o["clear"]["mm"],
                    nearest=o["clear"]["nearest"], windows=o["windows"], alt=None)
    else:
        base.update(exception_plan(h, its, Y, tg, rect, parts, z, in_rect, area, wins, fail_note))
    base["wall_angle"] = round(wall_angle(base["yaw"]), 1)
    base.update(room_state(h, Y, tg["floor"], rect, theater))
    base["rect"] = [round(v) for v in rect]
    return base


def exception_plan(h, its, Y, tg, rect, parts, z, in_rect, area, wins, fail_note):
    """4 隅とも不合格: 戸口の敷居から室内へ 450 入った位置に立ち戸を開ける（22mm を例外として許可）。戸口で足りなければ室内で正面が最長の位置。"""
    import furniture
    import render_interior as RI
    st, pl, ck = Y["settings"], Y["settings"]["placement"], Y["checks"]
    lo = pl["angle_deg"][0]
    best = None
    di = furniture.door_info(h)
    cands = []
    for did, d in di.items():
        if d["floor"] != tg["floor"]:
            continue
        import re
        mm = re.fullmatch(r"x(\d+)y(\d+)", d["tag"])
        mid = (float(mm.group(1)), float(mm.group(2)))
        for sgn in (-1, 1):
            nx, ny = (sgn, 0) if d["axis"] == "y" else (0, sgn)
            x, y = mid[0] + nx * pl["door_stand_mm"], mid[1] + ny * pl["door_stand_mm"]
            if in_rect(x, y):
                cands.append((x, y, did, d))
    grid = []
    for gx in range(int(rect[0]) + 400, int(rect[2]) - 399, 100):
        for gy in range(int(rect[1]) + 400, int(rect[3]) - 399, 100):
            if in_rect(gx, gy):
                grid.append((gx, gy, None, None))
    for pass_name, cs in (("door", cands), ("grid", grid)):
        for (x, y, did, d) in cs:
            cam = [round(x), round(y), z]
            clr = RI.camera_clearance(h, its, [dict(id="c", cam_mm=cam)])["c"]
            if clr["mm"] < ck["clearance_min_mm"]:
                continue
            for base_a in (lo, 90 - lo):
                for q in range(4):
                    yaw = base_a + 90 * q
                    fr = front_dist(h, its, cam, yaw)
                    key = (fr >= ck["front_min_mm"], round(fr / 100))
                    if best is None or key > best[0]:
                        best = (key, cam, clr, fr, yaw, did, d, pass_name)
        if best is not None and best[0][0]:
            break
    assert best is not None, ("視点が取れない", tg)
    _, cam, clr, fr, yaw, did, d, pass_name = best
    lens = st["lens_exception"]
    hf = math.degrees(2 * math.atan(18.0 / lens))
    wv = windows_in_view(h, wins, cam, yaw, hf, tg["floor"], rect)
    od = {}
    if did:
        od = {did.split("@")[1]: 1.0}
    reason = ("4 隅（壁から 700 内側）はいずれも離隔 400mm・正面 1,500mm を満たさない（" + "・".join(fail_note) + "）ため、" +
              (f"戸口（{did}）から室内へ {pl['door_stand_mm']}mm 入った位置に立ち戸を開け、" if did else "室内で正面が最も長い位置に立ち、") +
              f"{lens}mm（水平 {hf:.0f}°）を例外として許可。正面の壁まで {round(fr)}mm")
    return dict(corner="戸口" if did else "室内", x=cam[0], y=cam[1], yaw=round(yaw % 360, 1), inset=0, lens=lens, front_mm=round(fr), clearance_mm=clr["mm"], nearest=clr["nearest"],
                windows=wv, alt=reason, **({"open_doors": od} if od else {}))


def plan_T(h, Y):
    st = Y["settings"]
    out = {}
    for fl, cid in T_IDS.items():
        out[cid] = dict(kind="T", floor=fl, room="", title=f"{cid} {fl}全体を天井面から見下ろす", exposure=st["plan"]["exposure"])
    return out


def void_rects(h, floor):
    return [tuple(v) for v in h.slab_holes("2F")] if floor == "2F" else []


def plan(args):
    import furniture
    from house import House
    h = House(ROOT)
    txt = YAML.read_text(encoding="utf-8")
    head = txt.split(MARK)[0] if MARK in txt else txt
    Y = yaml.safe_load(head)
    its = furniture.items(h)
    wins = exterior_windows(h)
    cuts = {}
    for cid, tg in Y["targets"].items():
        c = plan_room(h, its, Y, cid, tg, wins, void_rects(h, tg["floor"]))
        c["slug"] = cid.split("_", 1)[1]
        c["exposure_note"] = None
        if c["theater"]:
            c["exposure"] = Y["settings"]["exposure_theater"]
        cuts[cid] = c
    cuts.update(plan_T(h, Y))
    for cid, ov in (Y.get("override") or {}).items():
        cuts[cid].update(ov)
    # Z カットの同室（自動照合: 室名と階が一致する区画）
    import render_zones as RZ
    Zc = RZ.load()["cuts"]
    for cid, c in cuts.items():
        if c["kind"] != "R":
            continue
        zs = sorted({z["zone"] for z in Zc.values() if z["floor"] == c["floor"] and z["room"] == c["room"]})
        c["same_z"] = zs
    lines = [MARK + "（手で直さない。直すときは上の override）----", "cuts:"]
    for cid, c in cuts.items():
        c = {k: v for k, v in c.items() if v is not None}
        lines.append(f"  {cid}: " + json.dumps(c, ensure_ascii=False, separators=(", ", ": ")))
    new = head.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    YAML.write_text(new, encoding="utf-8")
    nR = sum(1 for c in cuts.values() if c["kind"] == "R")
    exc = [k for k, c in cuts.items() if c.get("alt")]
    print(f"plan: R {nR}・T {len(cuts) - nR}。例外（alt あり）{len(exc)}: {','.join(exc)}")
    return 0


# ------------------------------------------------------------------ 検査（Blender なし）
def check(args=None):
    import furniture
    import render_interior as RI
    from house import House
    h = House(ROOT)
    Y = load()
    ck = Y["checks"]
    its = furniture.items(h)
    defs = {k: d for k, d in cut_defs(h, Y).items() if d["kind"] == "R"}
    clear = RI.camera_clearance(h, its, [dict(id=k, cam_mm=d["spec"]["cam"]) for k, d in defs.items()])
    bad = 0
    for k, d in defs.items():
        c = d["cut"]
        cam = d["spec"]["cam"]
        fr = front_dist(h, its, cam, c["yaw"])
        ang = wall_angle(c["yaw"])
        errs = []
        if clear[k]["mm"] < ck["clearance_min_mm"]:
            errs.append(f"離隔 {clear[k]['mm']}")
        if fr < ck["front_min_mm"]:
            errs.append(f"正面 {round(fr)}")
        if not (ck["angle_deg"][0] - 0.01 <= ang <= ck["angle_deg"][1] + 0.01):
            errs.append(f"角度 {ang:.0f}")
        flag = " 例外" if c.get("alt") else ""
        bad += bool(errs and not c.get("alt"))
        print(f"{k:<14} {d['floor']} {d['room'][:8]:<8} ({cam[0]},{cam[1]}) yaw{c['yaw']:>6} 角{ang:>5.1f} lens{c['lens']} 離隔{clear[k]['mm']:>5} 正面{round(fr):>6}{flag} {'NG ' + ','.join(errs) if errs else 'ok'}")
    return 4 if bad else 0


# ------------------------------------------------------------------ 画像の検査・注記帯・保存
def metrics_cfg(Y):
    ck = Y["checks"]
    return dict(checks=dict(black=ck["black"], white=ck["white"], mean=ck["mean"], mean_theater=ck["mean_theater"], std_min=ck["std_min"], window=ck["window"]))


def inspect_image(h, Y, d, png):
    """R: render_zones.image_metrics を流用（向きは一時の方位として登録）。T: 平均輝度・標準偏差のみ。戻り値 (metrics, issues)。"""
    import numpy as np
    from PIL import Image
    import render_zones as RZ
    im = Image.open(png)
    im.load()
    c = d["cut"]
    if d["kind"] == "T":
        a = np.asarray(im.convert("RGB"), dtype=np.float32)
        lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
        m = dict(mean=float(lum.mean()), std=float(lum.std()), black=float((lum <= 5).mean()), white=float((lum >= 250).mean()))
        issues = []
        lo, hi = Y["checks"]["mean_plan"]
        if not lo <= m["mean"] <= hi:
            issues.append(f"平均輝度 {m['mean']:.0f}（許容 {lo}〜{hi}）")
        if m["std"] < Y["checks"]["std_min"]:
            issues.append(f"標準偏差 {m['std']:.1f}")
        return m, issues
    RZ.DIRS[d["cid"]] = dirv(c["yaw"])
    dd = dict(cid=d["cid"], dir=d["cid"], floor=d["floor"], theater=bool(c.get("theater")), direct=bool(c.get("direct")), spec=d["spec"])
    m, issues = RZ.image_metrics(im, h, dd, metrics_cfg(Y))
    if not c.get("windows"):                                  # 視野に窓が無いカットは窓の検査を対象外（image_metrics は窓の矩形で自動判定するため、ここで落とす）
        issues = [i for i in issues if not i.startswith("窓の外")]
    return m, issues


def hfov(lens):
    return math.degrees(2 * math.atan(18.0 / lens))


def screens_text(c, Y):
    dn = c.get("screens_down") or []
    up = c.get("blackout_raised") or []
    if Y["settings"]["screens"] != "auto":
        return "スクリーン " + Y["settings"]["screens"]
    s = "スクリーン: 東面の窓を下ろす" + (f"（{'・'.join(dn)}）" if dn else "（この室の窓は対象外）")
    if up:
        s += f"／寝室の遮光生地は上げる仮定（{'・'.join(up)}）"
    return s


def band_image(png, d, entry, Y, out_jpg, quality, band):
    from PIL import Image, ImageDraw
    import render_interior as RI
    st = Y["settings"]
    im = Image.open(png)
    im.load()
    rgb = im.convert("RGB")
    W, H = rgb.size
    out = Image.new("RGB", (W, H + band), (241, 237, 228))
    out.paste(rgb, (0, 0))
    dr = ImageDraw.Draw(out)
    fs = max(10, int(band * 0.3))
    f = RI._font(fs)
    c = d["cut"]
    s = d["spec"]
    mo, da = int(s["when"][5:7]), int(s["when"][8:10])
    if d["kind"] == "T":
        l1 = f"{d['cid']}　{d['floor']}を天井面（FL+2,800）から真下に見下ろす　正投影・北が上　FL+2,400 の水平断面（壁の切り口は濃灰・造作家具は中灰）"
        l2 = f"{mo}月{da}日 {s['when'][11:16]}（夏至）　カメラWB {st['wb']:,}K　主照明 {st['channels']['L'][0]:,}K・{st['channels']['L'][1]}%　露出 {s['exposure']:+.1f}　{st['version']}　家具は仮置き・色は仮定・屋外の樹木は添景"
    else:
        ex = f"露出 {s['exposure']:+.1f}" + ("（プレビューで 0.5 刻みに調整）" if c.get("exp_note") else "")
        l1 = f"{d['cid']}　{d['room']}　視点 FL+{st['eye_above_fl_mm']:,}（身長160cmの目線）　レンズ {s['lens']}mm（水平 {hfov(s['lens']):.0f}°）　壁に対し {c['wall_angle']:.0f}°"
        l2 = f"{mo}月{da}日 {s['when'][11:16]}（夏至）　昼光 {st['wb']:,}K（WB）　主照明 {st['channels']['L'][0]:,}K・{st['channels']['L'][1]}%　{screens_text(c, Y)}　{ex}　{st['version']}"
    for _ in range(14):
        if max(dr.textlength(l1, font=f), dr.textlength(l2, font=f)) + fs * 2 <= W or fs <= 8:
            break
        fs -= 1
        f = RI._font(fs)
    dr.text((int(fs * 0.8), H + int(band * 0.08)), l1, font=f, fill=(40, 36, 30))
    dr.text((int(fs * 0.8), H + int(band * 0.08) + int(fs * 1.5)), l2, font=f, fill=(80, 74, 66))
    Path(out_jpg).parent.mkdir(parents=True, exist_ok=True)
    out.save(out_jpg, "JPEG", quality=quality, optimize=True, subsampling=0)


def labels_image(h, Y, png, out_jpg):
    """T の室名つき画像（再レンダー不要）。室の矩形の中心に室名を重ねる。"""
    from PIL import Image, ImageDraw
    import render_interior as RI
    im = Image.open(png).convert("RGB")
    W, H = im.size
    pl = Y["settings"]["plan"]
    px = W / (pl["ortho_scale_m"] * 1000.0)
    cx, cy = pl["center"]
    dr = ImageDraw.Draw(im)
    f = RI._font(max(12, int(W / 100)))
    fl = "1F" if "1F" in str(png) else "2F"
    for r in h.rooms:
        if r.floor != fl:
            continue
        x = W / 2 + ((r.rect[0] + r.rect[2]) / 2 - cx) * px
        y = H / 2 - ((r.rect[1] + r.rect[3]) / 2 - cy) * px
        t = r.name
        tw = dr.textlength(t, font=f)
        dr.rectangle([x - tw / 2 - 3, y - 11, x + tw / 2 + 3, y + 11], fill=(255, 255, 255))
        dr.text((x - tw / 2, y - 9), t, font=f, fill=(20, 20, 20))
    im.save(out_jpg, "JPEG", quality=85, optimize=True)


def read_log():
    if LOG.exists():
        return json.loads(LOG.read_text(encoding="utf-8"))
    return {}


def rooms_log():
    return read_log().get("rooms", {})


def write_rooms_entry(entries, master, total_seconds):
    d = read_log()
    r = d.setdefault("rooms", {})
    r.setdefault("cuts", {}).update(entries)
    r["master"] = master
    r["version"] = "v4.34"
    r["total_seconds"] = round(r.get("total_seconds", 0) + total_seconds, 1)
    LOG.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def jpg_path(cid):
    return OUT / f"{cid}.jpg"


def need(cid, d, lg, force=False):
    e = (lg.get("cuts") or {}).get(cid)
    return force or not (e and e.get("status") in ("ok", "flag") and e.get("def_hash") == def_hash(d) and jpg_path(cid).exists())


# ------------------------------------------------------------------ 撮影（shoot.py を 6 カットずつ）
def shoot_args(Y, kind, ids, preview, out):
    st = Y["settings"]
    a = [sys.executable, str(SHOOT), "--camera", ",".join(ids), "--date", st["when"][5:10], "--time", st["when"][11:16], "--screens", st["screens"],
         "--sun-k", str(st["sun_k"]), "--out", str(out)]
    if kind == "R":
        a += ["--eye", str(st["eye_above_fl_mm"]), "--channels", ",".join(k for k, v in st["channels"].items() if (v[1] if isinstance(v, list) else v) > 0),
              "--dim", str(st["channels"]["L"][1])]
    if preview:
        a += ["--preview"]
    return a


def run_shoot(Y, kind, ids, preview):
    import blend_master as BM
    out = (BM.SHOOT_CACHE / "preview") if preview else (CACHE / "png")          # shoot.py のプレビューは --out にかかわらず .cache/cg/shoot/preview へ出す
    out.mkdir(parents=True, exist_ok=True)
    return subprocess.call(shoot_args(Y, kind, ids, preview, out)), out


def finish_png(h, Y, d, png, secs, master, preview=False):
    """1 カット: 検査 → JPEG（注記帯）→ ログの項目。"""
    m, issues = inspect_image(h, Y, d, png)
    st = Y["settings"]
    e = dict(id=d["cid"], kind=d["kind"], floor=d["floor"], room=d["room"], cam=d["spec"]["cam"], target=d["spec"]["target"], lens=d["spec"]["lens"],
             exposure=d["spec"]["exposure"], when=d["spec"]["when"], wb=st["wb"], sun_k=st["sun_k"], channels=st["channels"], render_seconds=secs,
             metrics={k: round(v, 4) for k, v in m.items()}, status="flag" if issues else "ok", issues=issues, def_hash=def_hash(d))
    if d["kind"] == "R":
        e.update(clearance=d["cut"]["clearance_mm"], front_mm=d["cut"]["front_mm"], wall_angle=d["cut"]["wall_angle"], alt=d["cut"].get("alt"))
    out = (CACHE / "preview" / f"{d['cid']}.jpg") if preview else jpg_path(d["cid"])
    band_image(png, d, e, Y, out, st["jpeg_quality"], st["band_px"])
    if d["kind"] == "T" and not preview:
        labels_image(h, Y, png if d["floor"] in str(png) else png, OUT / f"{d['cid']}_labels.jpg")
    return e


def shoot(args):
    from house import House
    t_all = time.time()
    h = House(ROOT)
    Y = load()
    defs = cut_defs(h, Y)
    sel = [k for k, d in defs.items() if (not args.floor or (args.floor == "T" and d["kind"] == "T") or (args.floor in ("1F", "2F") and d["kind"] == "R" and d["floor"] == args.floor))
           and (not args.only or k in args.only)]
    lg = rooms_log()
    todo = sel if args.preview else [k for k in sel if need(k, defs[k], lg, args.force)]
    print(f"対象 {len(sel)} カット、撮るのは {len(todo)} カット（残りは既存を再利用）", flush=True)
    chunk = Y["settings"]["chunk"]
    master = {}
    n_ok = n_fail = 0
    for kind in ("T", "R"):
        ids = [k for k in todo if defs[k]["kind"] == kind]
        for i in range(0, len(ids), chunk if kind == "R" else 2):
            part = ids[i:i + (chunk if kind == "R" else 2)]
            t0 = time.time()
            rc, outd = run_shoot(Y, kind, part, args.preview)
            entries = {}
            for cid in part:
                png = outd / f"{cid}.png"
                if not png.exists():
                    n_fail += 1
                    print(f"fail {cid} rc={rc}", flush=True)
                    continue
                secs = round(time.time() - t0, 1)
                try:
                    e = finish_png(h, Y, defs[cid], png, secs, master, args.preview)
                except Exception as ex:               # noqa: BLE001
                    import traceback
                    traceback.print_exc()
                    n_fail += 1
                    continue
                entries[cid] = e
                n_ok += 1
                print(f"done {cid} {e['status']} mean={e['metrics']['mean']:.0f} {'; '.join(e['issues'])}", flush=True)
            if not args.preview and entries:
                write_rooms_entry(entries, master_info(), time.time() - t0)
            elif args.preview:
                pv = CACHE / "preview" / "preview_log.json"
                old = json.loads(pv.read_text(encoding="utf-8")) if pv.exists() else {}
                old.update({k: dict(mean=v["metrics"]["mean"], status=v["status"], issues=v["issues"], exposure=v["exposure"]) for k, v in entries.items()})
                pv.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"chunk {part[0]}..{part[-1]}: {round(time.time() - t0)} s", flush=True)
    print(f"done: 撮影 {n_ok}・失敗 {n_fail}・{round(time.time() - t_all)} 秒", flush=True)
    return 1 if n_fail else 0


def master_info():
    import blend_master as BM
    return dict(file=BM.MASTER.name, model_hash=BM.model_hash()[:16], generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))


def adjust_exposure(args):
    """プレビューの平均輝度が範囲を外れたカットだけ、露出を 1 回 ±0.5 して override へ書く。"""
    Y = load()
    pv = json.loads((CACHE / "preview" / "preview_log.json").read_text(encoding="utf-8"))
    ck = Y["checks"]
    txt = YAML.read_text(encoding="utf-8")
    Yh = yaml.safe_load(txt.split(MARK)[0])
    ov = Yh.get("override") or {}
    n = 0
    for cid, e in pv.items():
        c = Y["cuts"][cid]
        if c["kind"] == "T":
            lo, hi = ck["mean_plan"]
        else:
            lo, hi = ck["mean_theater"] if c.get("theater") else ck["mean"]
        m = e["mean"]
        if lo <= m <= hi or cid in ov and "exposure" in ov[cid]:
            continue
        step = -0.5 if m > hi else 0.5
        cur = c.get("exposure", Y["settings"]["plan"]["exposure"] if c["kind"] == "T" else Y["settings"]["exposure"])
        ov.setdefault(cid, {}).update(exposure=cur + step, exp_note=f"プレビューの平均輝度 {m:.0f} が{'上限' if step < 0 else '下限'}（{hi if step < 0 else lo}）を{'超えた' if step < 0 else '下回った'}ため {cur:+.1f} → {cur + step:+.1f}（1回だけ）")
        n += 1
    print(f"露出を調整: {n} カット", {k: v["exposure"] for k, v in ov.items()})
    # override 行を差し替え
    lines = txt.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("override:"):
            lines[i] = "override: " + (json.dumps(ov, ensure_ascii=False) if ov else "{}")
    YAML.write_text("\n".join(lines), encoding="utf-8")
    return n


# ------------------------------------------------------------------ 色温度の試し撮り
def cct_mccamy(rgb):
    r, g, b = rgb
    X = 0.4124 * r + 0.3576 * g + 0.1805 * b
    Yv = 0.2126 * r + 0.7152 * g + 0.0722 * b
    Zv = 0.0193 * r + 0.1192 * g + 0.9505 * b
    s = X + Yv + Zv
    x, y = X / s, Yv / s
    n = (x - 0.3320) / (0.1858 - y)
    return 449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33


def white_plate(args):
    """屋外の白い拡散板（アルベド 0.8・水平）を 64×64 で撮り、線形 RGB から McCamy 式で相関色温度を出す。"""
    sys.path.insert(0, str(ROOT / "src"))
    from house import House
    import blend_master as BM
    Y = load()
    st = Y["settings"]
    ks = [int(k) for k in str(args.sun_k_list).split(",")] if args.sun_k_list else [st["sun_k"]]
    res = {}
    for k in ks:
        job = dict(master=str(BM.MASTER), when=st["when"], sun_k=k, out=str(CACHE / f"plate_{k}.exr"), result=str(CACHE / f"plate_{k}.json"), tex_dir=str(BM.tex_dir()))
        CACHE.mkdir(parents=True, exist_ok=True)
        # 設定（HDRI・太陽）は shoot.py と同じ関数で作る
        import shoot as SH
        cfg_job = SH_cfg_for_plate(Y, job)
        jp = CACHE / f"job_plate_{k}.json"
        jp.write_text(json.dumps(cfg_job, ensure_ascii=False), encoding="utf-8")
        py = BM.bpy_python()
        subprocess.run([py, str(ROOT / "src" / "shoot_blender.py"), "plate", str(jp)], stdout=open(CACHE / "plate.log", "w"), stderr=subprocess.STDOUT, timeout=900)
        r = json.loads(Path(job["result"]).read_text(encoding="utf-8"))
        r["cct_k"] = round(cct_mccamy(r["rgb"]))
        res[k] = r
        print(f"sun_k {k}: 板の線形 RGB {[round(v, 4) for v in r['rgb']]}  相関色温度 {r['cct_k']}K", flush=True)
    return res


def SH_cfg_for_plate(Y, job):
    import copy
    import types
    import render_cg as RC
    import render_interior as RI
    import blend_master as BM
    from house import House
    h = House(ROOT)
    spec = copy.deepcopy(h.spec)
    st = Y["settings"]
    spec["interior_cg"]["cuts"] = {"PLATE": dict(file="PLATE", title="plate", cam=[9125, 9125, 4600], target=[9125, 12125, 4600], lens=26, when=st["when"], exposure=0.0, wb=6500, shift_y=0,
                                                 pitch=0, screens="up", sun_k=job["sun_k"])}
    tex = {**spec["cg"]["textures"], **spec["interior_cg"]["textures"]}
    assets = RC.fetch_assets({"cg": {"textures": tex, "hdri": spec["cg"]["hdri"]}}, BM.CACHE, use_textures=True)
    ns = types.SimpleNamespace(only=None, preview=False, size=None, samples=None, scene_only=False, no_glb=True)
    cfg, _ = RI.interior_cfg(h, spec, ns, assets, CACHE, BM.MASTER)
    return dict(job, cfg=cfg)


# ------------------------------------------------------------------ シート
def sheets(args):
    from PIL import Image, ImageDraw
    import render_interior as RI
    from house import House
    h = House(ROOT)
    Y = load()
    defs = cut_defs(h, Y)
    lg = rooms_log().get("cuts", {})
    W, H, cols, rows = 480, 270, 4, 5
    mark = {"ok": "○", "flag": "△", "fail": "×"}
    f = RI._font(14)
    for fl in ("1F", "2F"):
        ids = [k for k, d in defs.items() if d["kind"] == "R" and d["floor"] == fl]
        sheet = Image.new("RGB", (cols * W, rows * (H + 22)), (241, 237, 228))
        dr = ImageDraw.Draw(sheet)
        for i, k in enumerate(ids):
            x, y = (i % cols) * W, (i // cols) * (H + 22)
            p = jpg_path(k)
            if p.exists():
                im = Image.open(p).convert("RGB")
                im = im.crop((0, 0, im.size[0], im.size[1] - Y["settings"]["band_px"])).resize((W, H))
                sheet.paste(im, (x, y + 22))
            e = lg.get(k, {})
            dr.text((x + 4, y + 3), f"{mark.get(e.get('status'), '？')} {k} {defs[k]['room']}"[:34], font=f, fill=(30, 30, 30))
        out = OUT / f"contact_rooms_{fl}.jpg"
        sheet.save(out, "JPEG", quality=85, optimize=True)
        w = 1600
        sheet.resize((w, int(sheet.size[1] * w / sheet.size[0]))).save(ROOT / "docs" / f"cg_rooms_{fl}.jpg", "JPEG", quality=85, optimize=True)
        print("sheet:", out)
    for i, (fl, cid) in enumerate(T_IDS.items(), 1):
        p = jpg_path(cid)
        if p.exists():
            im = Image.open(p).convert("RGB")
            im.resize((1200, int(im.size[1] * 1200 / im.size[0]))).save(ROOT / "docs" / f"cg_T{i}.jpg", "JPEG", quality=85, optimize=True)
    return 0


def report(args):
    """検査レポート（標準出力。ブリーフ 42 章の表に貼る）。"""
    Y = load()
    lg = rooms_log().get("cuts", {})
    n = {"ok": 0, "flag": 0}
    for k, e in lg.items():
        n[e["status"]] = n.get(e["status"], 0) + 1
        if e["issues"] or e.get("alt"):
            print(f"{k}\t{e['status']}\t{'; '.join(e['issues'])}\t{e.get('alt') or ''}")
    print("合計", len(lg), n)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--shoot", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--adjust", action="store_true", help="プレビューの結果で露出を 1 回だけ調整して override へ書く")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--white-plate", action="store_true", dest="white_plate")
    ap.add_argument("--sun-k-list", default="", dest="sun_k_list")
    ap.add_argument("--floor", choices=["1F", "2F", "T"])
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--background", action="store_true")
    a = ap.parse_args(argv)
    a.only = set(x for x in a.only.split(",") if x)
    if a.background:
        rest = [x for x in (argv if argv is not None else sys.argv[1:]) if x != "--background"]
        CACHE.mkdir(parents=True, exist_ok=True)
        lf = open(CACHE / "rooms.log", "a", encoding="utf-8")
        p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *rest], stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        print(f"バックグラウンドで開始（pid {p.pid}）。ログ: {CACHE / 'rooms.log'}")
        return 0
    if a.plan:
        return plan(a)
    if a.check:
        return check(a)
    if a.adjust:
        adjust_exposure(a)
        return 0
    if a.shoot or a.preview:
        return shoot(a)
    if a.sheet:
        return sheets(a)
    if a.report:
        return report(a)
    if a.white_plate:
        white_plate(a)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
