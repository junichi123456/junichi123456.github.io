"""v4.30 内装CG 18区画×2方向（36カット）の駆動（システムの python3）。定義は data/interior_zones.yaml。
spec.yaml の interior_cg.cuts・render_log.json には触らない。Blender 段階は既存の cg_blender.py を使う。

    python3 src/render_zones.py --check                    # Blender なし: 定義・離隔・時刻の検査
    python3 src/render_zones.py --preview                  # 480×270・16spp を .cache/cg/interior_zones/preview/ へ
    python3 src/render_zones.py --floor 1F|2F              # 本番（6 カットずつ。JPEG があり def_hash が一致するカットは飛ばす）
    python3 src/render_zones.py --only Z1-23a --force      # 撮り直し
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

import furniture  # noqa: E402
import render_cg as RC  # noqa: E402
import render_interior as RI  # noqa: E402
from house import House  # noqa: E402

YAML = ROOT / "data" / "interior_zones.yaml"
OUT = ROOT / "dist" / "render" / "interior" / "zones"
CACHE = ROOT / ".cache" / "cg" / "interior_zones"
DIRS = {"N": (0.0, 1.0), "S": (0.0, -1.0), "E": (1.0, 0.0), "W": (-1.0, 0.0)}
DIR_JA = {"N": "北", "S": "南", "E": "東", "W": "西"}
BLOCK_CATS = ("wall", "partition", "glass", "door", "parapet", "mullion", "stair")


def load():
    return yaml.safe_load(YAML.read_text(encoding="utf-8"))


def cut_defs(h, Z):
    """yaml → {id: 定義 dict}（spec の interior_cg.cuts と同じ形のカット項目＋区画の情報）。"""
    st = Z["settings"]
    out = {}
    for cid, c in Z["cuts"].items():
        z = h.fl[c["floor"]] + st["eye_above_fl_mm"]
        dx, dy = DIRS[c["dir"]]
        lens = c.get("lens", st["lens_std"])
        theater = c["zone"] == "Z2-31"
        d = dict(cid=cid, zone=c["zone"], floor=c["floor"], room=c["room"], dir=c["dir"], look=c["look"], direct=bool(c.get("direct")), alt=c.get("alt"),
                 theater=theater, x=c["x"], y=c["y"],
                 slug=c["slug"], spec=dict(file=cid, title=f"{cid} {c['room']} {DIR_JA[c['dir']]}向き", cam=[c["x"], c["y"], z],
                           target=[c["x"] + dx * st["look_dist_mm"], c["y"] + dy * st["look_dist_mm"], z], lens=lens, when=st["when"],
                           exposure=c.get("exposure", st["exposure_theater"] if theater else st["exposure"]), wb=st["wb"], shift_y=st["shift_y"], pitch=st["pitch"], screens="up"))
        if c.get("open_doors"):
            d["spec"]["open_doors"] = c["open_doors"]
        if c.get("also_1f"):
            d["spec"]["also_1f"] = True
        out[cid] = d
    return out


def def_hash(d):
    s = d["spec"]
    key = json.dumps([s["cam"], s["target"], s["lens"], s["exposure"], s["when"], s.get("open_doors", {}), s.get("also_1f", False), s["shift_y"], s["wb"]], sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def hfov(lens):
    return math.degrees(2 * math.atan(18.0 / lens))


def front_distance(h, cam, dirv):
    """カメラの高さで、向きの先にある壁・間仕切・窓・扉・階段の箱までの距離（mm）。"""
    x, y, z = cam
    dx, dy = dirv
    best = 1e9
    for b in h.boxes:
        if b.cat not in BLOCK_CATS or not (b.z0 <= z <= b.z1):
            continue
        t0, t1 = -1e9, 1e9
        ok = True
        for o, dd, lo, hi in ((x, dx, b.x0, b.x1), (y, dy, b.y0, b.y1)):
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


def in_room(h, d):
    for r in h.rooms:
        if r.floor == d["floor"] and r.name == d["room"] and r.rect[0] <= d["x"] <= r.rect[2] and r.rect[1] <= d["y"] <= r.rect[3]:
            return True
    return False


def over_void(h, d):
    if d["floor"] != "2F":
        return False
    return any(hl[0] <= d["x"] <= hl[2] and hl[1] <= d["y"] <= hl[3] for hl in h.slab_holes("2F"))


def dir_diff(a, b):
    ang = lambda k: math.degrees(math.atan2(DIRS[k][1], DIRS[k][0]))
    return abs((ang(a) - ang(b) + 180) % 360 - 180)


def pre_checks(h, its, defs, Z):
    """描く前の検査: {id: dict(clearance, nearest, front_mm, in_room, over_void, errors)} と区画ごとの向きの差。"""
    ck = Z["checks"]
    cuts = [dict(id=cid, cam_mm=d["spec"]["cam"]) for cid, d in defs.items()]
    clear = RI.camera_clearance(h, its, cuts)
    res = {}
    for cid, d in defs.items():
        errs = []
        cam = d["spec"]["cam"]
        fr = front_distance(h, cam, DIRS[d["dir"]])
        r = dict(clearance=clear[cid]["mm"], nearest=clear[cid]["nearest"], front_mm=round(fr), in_room=in_room(h, d), over_void=over_void(h, d))
        if r["clearance"] < ck["clearance_min_mm"]:
            errs.append(f"離隔 {r['clearance']}mm < {ck['clearance_min_mm']}（{r['nearest']}）")
        if r["front_mm"] < ck["front_min_mm"]:
            errs.append(f"正面の壁まで {r['front_mm']}mm < {ck['front_min_mm']}")
        if not r["in_room"]:
            errs.append(f"{d['room']} の矩形の外")
        if r["over_void"]:
            errs.append("吹抜けの上")
        r["errors"] = errs
        res[cid] = r
    for zone in sorted({d["zone"] for d in defs.values()}):
        a, b = defs[zone + "a"], defs[zone + "b"]
        df = dir_diff(a["dir"], b["dir"])
        tol = ck["dir_tol_deg"]
        if not any(abs(df - t) <= tol for t in ck["dir_diff_deg"]):
            res[zone + "b"]["errors"].append(f"a/b の向きの差 {df:.0f}°")
    return res


# ---- 描いた後の検査 ----
def window_rects(h, floor):
    return [b for b in h.boxes if b.cat == "glass" and b.tag.startswith("AW") and b.level == floor]


def project_window(h, d, b, W, H):
    """窓ガラスの箱を画像へ投影した矩形 (x0,y0,x1,y1)（画素）。視野外・背後・壁に隠れるときは None。"""
    s = d["spec"]
    cx, cy, cz = s["cam"]
    fx, fy = DIRS[d["dir"]]
    rx, ry = fy, -fx
    L = s["lens"]
    pts = []
    for x in (b.x0, b.x1):
        for y in (b.y0, b.y1):
            for z in (b.z0, b.z1):
                px, py, pz = x - cx, y - cy, z - cz
                dep = px * fx + py * fy
                if dep < 200:
                    return None
                u = (px * rx + py * ry) / dep * L / 36.0
                v = pz / dep * L / 36.0 - s["shift_y"]
                pts.append((W / 2 + u * W, H / 2 - v * W))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = max(min(xs), 0), min(max(xs), W), max(min(ys), 0), min(max(ys), H)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    # 窓の中心へ向かう視線が壁・間仕切・扉で遮られないこと
    mx, my, mz = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, (b.z0 + b.z1) / 2
    vx, vy = mx - cx, my - cy
    dist = math.hypot(vx, vy)
    for o in h.boxes:
        if o is b or o.cat not in ("wall", "partition", "door") or not (o.z0 <= cz <= o.z1):
            continue
        t0, t1 = 0.0, 1.0
        ok = True
        for p0, dd, lo, hi in ((cx, vx, o.x0, o.x1), (cy, vy, o.y0, o.y1)):
            if abs(dd) < 1e-9:
                if not (lo <= p0 <= hi):
                    ok = False
                    break
            else:
                a, c = (lo - p0) / dd, (hi - p0) / dd
                t0, t1 = max(t0, min(a, c)), min(t1, max(a, c))
        if ok and t0 < t1 - 1e-6 and t1 < 0.995 and t0 < 0.995 and dist * (t1 - t0) > 5:
            return None
    return (x0, y0, x1, y1)


def image_metrics(im, h, d, Z):
    """PIL 画像（注記帯なし）→ 検査値と issues。"""
    import numpy as np
    ck = Z["checks"]
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    H, W = lum.shape
    m = dict(black=float((lum <= ck["black"]["thr"]).mean()), white=float((lum >= ck["white"]["thr"]).mean()), mean=float(lum.mean()), std=float(lum.std()))
    issues = []
    bmax = ck["black"]["max_theater"] if d["theater"] else ck["black"]["max"]
    wmax = ck["white"]["max_direct"] if d["direct"] else ck["white"]["max"]
    lo, hi = ck["mean_theater"] if d["theater"] else ck["mean"]
    if m["black"] > bmax:
        issues.append(f"黒つぶれ {m['black']*100:.1f}%（上限 {bmax*100:.0f}%）")
    if m["white"] > wmax:
        issues.append(f"白飛び {m['white']*100:.1f}%（上限 {wmax*100:.0f}%）")
    if not (lo <= m["mean"] <= hi):
        issues.append(f"平均輝度 {m['mean']:.0f}（許容 {lo}〜{hi}）")
    if m["std"] < ck["std_min"]:
        issues.append(f"標準偏差 {m['std']:.1f} < {ck['std_min']}（壁の中・単色）")
    rects = []
    for b in window_rects(h, d["floor"]):
        r = project_window(h, d, b, W, H)
        if r:
            rects.append(r)
    mask = np.zeros((H, W), bool)
    for x0, y0, x1, y1 in rects:
        mask[int(y0):int(y1), int(x0):int(x1)] = True
    wc = ck["window"]
    if mask.mean() >= wc["min_area"]:
        reg = lum[mask]
        m["window_area"] = float(mask.mean())
        m["window_ratio"] = float(reg.mean() / max(lum.mean(), 1e-6))
        m["window_std"] = float(reg.std())
        if m["window_ratio"] < wc["mean_ratio"] or m["window_std"] < wc["std_min"]:
            issues.append(f"窓の外が見えない（窓領域の平均は画像平均の {m['window_ratio']:.2f} 倍・標準偏差 {m['window_std']:.1f}）")
    else:
        m["window_area"] = float(mask.mean())
    return m, issues


def sun_ok(sun, st):
    return sun and abs(sun["el"] - st["sun"]["el"]) < 0.06 and abs(sun["az"] - st["sun"]["az_true"]) < 0.06


# ---- 注記帯と保存 ----
def band_image(png, d, entry, Z, out_jpg, quality, band):
    from PIL import Image, ImageDraw
    st = Z["settings"]
    im = Image.open(png)
    im.load()
    rgb = im.convert("RGB")
    W, H = rgb.size
    out = Image.new("RGB", (W, H + band), (241, 237, 228))
    out.paste(rgb, (0, 0))
    dr = ImageDraw.Draw(out)
    fs = max(10, int(band * 0.3))
    f = RI._font(fs)
    s = d["spec"]
    chn = entry["channels"]
    l1 = f"{d['cid']}　{d['room']}　{DIR_JA[d['dir']]}向き　{d['look']}"
    mo, da = int(s["when"][5:7]), int(s["when"][8:10])
    ex = f"露出 {s['exposure']:+.1f}" + ("（シアターは暗色仕上げのため既定 −0.5 より明るく設定）" if d["theater"] else "（プレビューで 0.5 刻みに調整）" if abs(s["exposure"] - st["exposure"]) > 1e-9 else "")
    l2 = f"{mo}月{da}日 {s['when'][11:16]}　視点 FL+{st['eye_above_fl_mm']:,}　レンズ {s['lens']}mm（水平 {hfov(s['lens']):.0f}°）　主照明 {chn['L'][0]:,}K・{chn['L'][1]:.0f}%　{ex}　家具は仮置き・色は仮定・屋外の樹木は添景"
    for _ in range(12):
        if max(dr.textlength(l1, font=f), dr.textlength(l2, font=f)) + fs * 2 <= W or fs <= 8:
            break
        fs -= 1
        f = RI._font(fs)
    dr.text((int(fs * 0.8), H + int(band * 0.08)), l1, font=f, fill=(40, 36, 30))
    dr.text((int(fs * 0.8), H + int(band * 0.08) + int(fs * 1.5)), l2, font=f, fill=(80, 74, 66))
    Path(out_jpg).parent.mkdir(parents=True, exist_ok=True)
    out.save(out_jpg, "JPEG", quality=quality, optimize=True, subsampling=0)      # EXIF なし


# ---- ログ ----
def log_path():
    return OUT / "render_log_zones.json"


def read_log():
    p = log_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else dict(cuts={})


def write_log(lg):
    OUT.mkdir(parents=True, exist_ok=True)
    log_path().write_text(json.dumps(lg, ensure_ascii=False, indent=1), encoding="utf-8")


def jpg_name(cid, c):
    """Z1-11a_ld_s.jpg（ID・室の略号・向き 1 文字）。"""
    return f"{cid}_{c['slug']}_{c['dir'].lower()}.jpg"


def jpg_path(cid):
    if not _CUTS:
        _CUTS.update(load()["cuts"])
    return OUT / jpg_name(cid, _CUTS[cid])


_CUTS = {}


def need_render(cid, d, force, lg):
    e = lg["cuts"].get(cid)
    return force or not (e and e.get("status") in ("ok", "flag") and e.get("def_hash") == def_hash(d) and jpg_path(cid).exists())


def make_args(only, preview):
    return types.SimpleNamespace(only=set(only), preview=False, size=None, samples=None, scene_only=False, no_glb=True)


def run_chunk(h, Z, defs, ids, preview, glb, tex_assets):
    """1 チャンク（≤6 カット）を Blender で描く。戻り値: (raw, cfg, clear, rc)。"""
    st = Z["settings"]
    spec = copy.deepcopy(h.spec)
    ic = spec["interior_cg"]
    pv = st["preview"]
    ic["cuts"] = {}
    for cid in ids:
        s = dict(defs[cid]["spec"])
        s["file"] = cid
        ic["cuts"][cid] = s
    res, smp, tl = (pv["resolution"], pv["samples"], pv["time_limit"]) if preview else (st["resolution"], st["samples"], st["time_limit"])
    ic["resolution"], ic["samples"], ic["time_limit"] = list(res), smp, tl
    ic["adaptive_threshold"] = st["adaptive_threshold"]
    png_dir = CACHE / ("preview" if preview else "png")
    png_dir.mkdir(parents=True, exist_ok=True)
    cfg, its = RI.interior_cfg(h, spec, make_args(ids, False), tex_assets, png_dir, glb)
    clear = RI.camera_clearance(h, its, cfg["cuts"])
    bad = {k: v for k, v in clear.items() if v["mm"] < 150}
    if bad:
        print("カメラが近すぎます（150mm 未満）:", bad)
        return None, cfg, clear, 4
    scene = CACHE / ("scene_preview.json" if preview else "scene_chunk.json")
    cfg["raw_log"] = str(png_dir / "render_log_raw.json")
    Path(cfg["raw_log"]).unlink(missing_ok=True)
    scene.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    py = os.environ.get("BPY_PYTHON") or str(ROOT / ".venv-bpy" / "bin" / "python")
    if not Path(py).exists():
        print("bpy が見つかりません。BPY_PYTHON を指定してください")
        return None, cfg, clear, 2
    with open(CACHE / "blender.log", "a", encoding="utf-8") as lf:
        rc = subprocess.call([py, str(ROOT / "src" / "cg_blender.py"), str(scene), "--only", ",".join(ids)], stdout=lf, stderr=subprocess.STDOUT)
    raw = json.loads(Path(cfg["raw_log"]).read_text(encoding="utf-8")) if Path(cfg["raw_log"]).exists() else None
    return raw, cfg, clear, rc


def finish_cut(h, Z, defs, cid, r, cfg_cut, clear, pre, raw, preview):
    """1 カットの後処理: 検査 → JPEG（注記帯）→ ログの項目。"""
    from PIL import Image
    st = Z["settings"]
    d = defs[cid]
    png = Path(r["file"])
    im = Image.open(png)
    im.load()
    m, issues = image_metrics(im, h, d, Z)
    flags = list(issues)
    if r.get("texture_fallbacks"):
        flags.append("texture_fallbacks: " + ",".join(r["texture_fallbacks"]))
    if raw is not None:
        pal = cfg_cut["_palette_mismatch"]
        if pal:
            flags.append("palette_mismatch: " + ",".join(pal))
    if not sun_ok(cfg_cut.get("sun"), st):
        flags.append("太陽の高度・方位が 27.8°/247.7° と一致しない")
    if d["spec"]["cam"][2] != h.fl[d["floor"]] + st["eye_above_fl_mm"]:
        flags.append("視点の高さが FL+1,600 ではない")
    e = dict(id=cid, zone=d["zone"], room=d["room"], dir=DIR_JA[d["dir"]], cam=d["spec"]["cam"], target=d["spec"]["target"], eye_mm=st["eye_above_fl_mm"],
             when=d["spec"]["when"], sun=cfg_cut.get("sun"), hdri_sun=r.get("hdri_sun"), lens=d["spec"]["lens"], hfov=round(hfov(d["spec"]["lens"]), 1),
             exposure=d["spec"]["exposure"], channels=r["channels"], spp=r["samples"], res=r["res"], render_seconds=r["render_seconds"],
             time_limit=r["time_limit"], time_limit_hit=r["render_seconds"] >= r["time_limit"] - 3, clearance=clear["mm"], front_mm=pre["front_mm"],
             metrics={k: round(v, 4) for k, v in m.items()}, status="flag" if flags else "ok", issues=flags, def_hash=def_hash(d))
    if d["spec"].get("open_doors"):
        e["open_doors"] = d["spec"]["open_doors"]
    out = (CACHE / "preview" / f"{cid}.jpg") if preview else jpg_path(cid)
    band_image(png, d, e, Z, out, st["jpeg_quality"], st["band_px"])
    return e


def render(args):
    t_start = time.time()
    Z = load()
    _CUTS.update(Z['cuts'])
    st = Z["settings"]
    h = House(ROOT)
    defs = cut_defs(h, Z)
    its = furniture.items(h)
    pre = pre_checks(h, its, defs, Z)
    bad = {k: v["errors"] for k, v in pre.items() if v["errors"]}
    if bad:
        print("離隔などの検査に不適合:", bad)
        return 4
    ids_all = [c for c in defs if (not args.floor or defs[c]["floor"] == args.floor) and (not args.only or c in args.only)]
    lg = read_log()
    todo = ids_all if args.preview else [c for c in ids_all if need_render(c, defs[c], args.force, lg)]
    print(f"対象 {len(ids_all)} カット、描くのは {len(todo)} カット（残りは既存を再利用）")
    if not todo:
        return 0
    CACHE.mkdir(parents=True, exist_ok=True)
    glb = CACHE / "model_interior.glb"
    from model3d import export_glb
    srcs = [ROOT / "spec.yaml"] + list((ROOT / "src").glob("*.py"))
    if args.regen_glb or not glb.exists() or glb.stat().st_mtime < max(p.stat().st_mtime for p in srcs):
        export_glb(h, glb, interior=True)
    ic = h.spec["interior_cg"]
    tex = {**h.spec["cg"]["textures"], **ic["textures"]}
    assets = RC.fetch_assets({"cg": {"textures": tex, "hdri": h.spec["cg"]["hdri"]}}, ROOT / ".cache" / "cg", use_textures=True)
    n_ok = 0
    for i in range(0, len(todo), st["chunk"]):
        ids = todo[i:i + st["chunk"]]
        t0 = time.time()
        for attempt in (1, 2):
            raw, cfg, clear, rc = run_chunk(h, Z, defs, ids, args.preview, glb, assets)
            done = {r["id"] for r in (raw or {}).get("cuts", []) if Path(r["file"]).exists()}
            if rc == 0 and done >= set(ids):
                break
            ids_missing = [c for c in ids if c not in done]
            print(f"チャンク失敗 rc={rc} 欠け={ids_missing}（試行 {attempt}）")
            if attempt == 2 or rc in (2, 4):
                break
            ids = ids_missing
        if raw is None:
            return rc or 1
        by_id = {c["id"]: c for c in cfg["cuts"]}
        pal_mm = []
        mc = raw.get("material_colors", {})
        for k, v in cfg["interior"]["palette"].items():
            if k in mc and any(abs(a - b) > 0.002 for a, b in zip(mc[k], v["rgb"])):
                pal_mm.append(k)
        for r in raw["cuts"]:
            cid = r["id"]
            if not Path(r["file"]).exists():
                continue
            cc = by_id[cid]
            cc["_palette_mismatch"] = pal_mm
            r["channels"] = cc["ch"]
            e = finish_cut(h, Z, defs, cid, r, cc, clear[cid], pre[cid], raw, args.preview)
            if args.preview:
                pv = lg.setdefault("preview", {})
                pv[cid] = dict(status=e["status"], issues=e["issues"], metrics=e["metrics"])
            else:
                lg["cuts"][cid] = e
            n_ok += 1
        failed = [c for c in ids if c not in {r["id"] for r in raw["cuts"] if Path(r["file"]).exists()}]
        for c in failed:
            if not args.preview:
                lg["cuts"][c] = dict(id=c, status="fail", issues=[f"Blender 終了コード {rc}・画像なし"], def_hash=def_hash(defs[c]))
        if not args.preview:
            lg["settings"] = dict(resolution=st["resolution"], samples=st["samples"], adaptive_threshold=st["adaptive_threshold"], time_limit=st["time_limit"], jpeg_quality=st["jpeg_quality"])
            lg["version"] = "v4.30"
            lg["palette_mismatch"] = pal_mm
            lg["order"] = list(defs)
            lg["total_seconds"] = round(lg.get("total_seconds", 0) + time.time() - t0, 1)
            write_log(lg)
        print(f"chunk {ids[0]}..{ids[-1]}: {round(time.time() - t0)} s", flush=True)
    print(f"done: {n_ok} cuts, {round(time.time() - t_start)} s")
    if args.preview:
        pvp = CACHE / "preview" / "preview_log.json"
        pvp.write_text(json.dumps(lg.get("preview", {}), ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def check(args):
    Z = load()
    _CUTS.update(Z['cuts'])
    h = House(ROOT)
    defs = cut_defs(h, Z)
    its = furniture.items(h)
    pre = pre_checks(h, its, defs, Z)
    st = Z["settings"]
    print(f"{len(defs)} カット / when={st['when']} / 視点 FL+{st['eye_above_fl_mm']}")
    for cid, p in pre.items():
        d = defs[cid]
        print(f"{cid} {d['room'][:8]:<8} {d['dir']} lens{d['spec']['lens']} 離隔 {p['clearance']:>5} 正面 {p['front_mm']:>6} {'NG ' + ';'.join(p['errors']) if p['errors'] else 'ok'}")
    return 4 if any(p["errors"] for p in pre.values()) else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--floor", choices=["1F", "2F"])
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--regen-glb", action="store_true")
    a = ap.parse_args(argv)
    a.only = set(x for x in a.only.split(",") if x)
    if a.check:
        return check(a)
    return render(a)


if __name__ == "__main__":
    sys.exit(main())
