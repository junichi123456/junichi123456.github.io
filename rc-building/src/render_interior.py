"""内装CG 段階1（システムの python3）: 内装用 GLB の書き出し、scene.json（カット・照明・扉・パレット）、テクスチャ取得、
Blender 段階（cg_blender.py → cg_interior.py）の起動、後処理（メタデータ除去と仮置きの注記の帯）。

    python3 src/render_cg.py --interior                      # 全11カットを本番の品質で
    python3 src/render_cg.py --interior --preview            # 480×270・16spp（構図の確認）
    python3 src/render_cg.py --interior --only I01,I02
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import furniture  # noqa: E402
import lighting as LG  # noqa: E402
import render_cg as RC  # noqa: E402
from house import House  # noqa: E402
from model3d import export_glb, material_table, srgb_to_lin  # noqa: E402

FONT_CANDIDATES = ["/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf", "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"]


def scenery_cfg(h, spec):
    """窓の外の添景: 遠景の木の帯（seed 固定の乱数配置。周辺建物・道路・水路と重ねない）と、外観 CG と同じプランター。"""
    import random
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    from model3d import _site_road_polys
    sc = spec["interior_cg"].get("scenery")
    if not sc:
        return dict(trees=[], planters=[])
    t = sc["trees"]
    rnd = random.Random(t["seed"])
    road, _ = _site_road_polys(h)
    block = unary_union([Polygon(b).buffer(0) for b in list(h.neighbors) + list(h.existing)] + [Polygon(w).buffer(0) for w in h.water] + [road]).buffer(0)
    cx, cy = h.W / 2.0, h.D / 2.0
    # 地形メッシュの範囲（model3d.build_terrain: x −70〜60 m, y −70〜65 m を原点 (ox, oy) からの相対で取る）内だけに置く
    x_lo, x_hi, y_lo, y_hi = (-70 - h.ox) * 1000, (60 - h.ox) * 1000, (-70 - h.oy) * 1000, (65 - h.oy) * 1000
    az0 = math.radians(h.facade_az)                       # 建物座標の方位 = 真方位 − facade_az
    trees = []
    b0, b1 = t["bearing_deg"]
    for r_m in (t["r_min_m"] + i * 2.5 for i in range(int((t["r_max_m"] - t["r_min_m"]) / 2.5) + 1)):
        # 半径ごとのリングに、弧長の間隔 6〜9m で並べる（乱数で半径と方位を少し散らす）
        b = b0
        while b <= b1:
            rr = r_m + rnd.uniform(-1.0, 1.0)
            ang = math.radians(b) - az0
            x, y = cx + rr * 1000 * math.sin(ang), cy + rr * 1000 * math.cos(ang)
            hh = rnd.uniform(t["h_min_m"], t["h_max_m"])
            rad = hh * 0.32
            gap = rnd.uniform(t["gap_min_m"], t["gap_max_m"])
            ok = x_lo < x < x_hi and y_lo < y < y_hi and not block.intersects(Point(x, y).buffer(rad * 1000))
            if ok and all(math.hypot(x - u["p"][0] * 1000, y - u["p"][1] * 1000) > 4000 for u in trees[-40:]):
                trees.append(dict(p=[x / 1000.0, y / 1000.0, h.ground(x, y) / 1000.0], h=hh, seed=rnd.randrange(1 << 30)))
            b += math.degrees(gap / rr)
    return dict(trees=trees, trunk=srgb_to_lin(t["trunk"]), planters=RC_planters(h, spec))


def RC_planters(h, spec):
    """render_cg.py（外観）と同じプランターのリスト（建物座標 m）。"""
    S = 1000.0
    fm = spec["farm"]
    x0, y0, x1, y1 = h.pergola
    zb = max(h.ground((x0 + x1) / 2, (y0 + y1) / 2), h.fgl)
    out = []
    for b in h.garden_beds:
        out.append(dict(rect=[v / S for v in b], soil_z=(zb + fm["leg"] + fm["planter_h"] - 50) / S, height=0.30, kind="shade"))
    for b in h.planters:
        out.append(dict(rect=[v / S for v in b], soil_z=(h.fgl + 20 + fm["leg"] + fm["planter_h"] - 50) / S, height=0.45, kind="sun"))
    return out


def interior_cfg(h, spec, args, assets, out_dir, glb_path):
    ic = spec["interior_cg"]
    fr = RC.Frame(h)
    lat, lon, tz = spec["cg"]["site"]["lat"], spec["cg"]["site"]["lon"], spec["cg"]["site"]["tz"]
    its = furniture.items(h)
    table = material_table(spec)
    mats = {k: dict(rgb=t["rgb"], roughness=t["roughness"], metallic=t["metallic"], coat=spec["materials"].get(k, {}).get("coat", 0.0))
            for k, t in table.items()}
    colors_lin = dict(tile_joint=srgb_to_lin(spec["colors"]["tile_joint"]), dotcon_joint=srgb_to_lin("#8F8572"),
                      pv_joint=srgb_to_lin("#3A3F48"), plant_a=srgb_to_lin("#4E6B2E"), plant_b=srgb_to_lin("#6E8B3D"))
    pal = {}
    for k, m in spec["interior_palette"].items():
        pal[k] = dict(m)
        pal[k]["rgb"] = srgb_to_lin(m["color"])
    # カット
    cuts = []
    for cid, c in ic["cuts"].items():
        if args.only and cid not in args.only:
            continue
        el, az = RC.sun_position(c["when"], lat, lon, tz)
        hour = int(c["when"][11:13]) + int(c["when"][14:16]) / 60.0
        chs = LG.channels(spec, hour, c.get("room", ""))
        for k_, v_ in c.get("lights", {}).items():            # カットごとの上書き（上映前・夜景など）
            chs[k_] = (v_[0], float(v_[1]))
        K, pct = (chs["L"] if chs["L"][1] > 0 else chs["D"])    # 主照明（L）。消灯のときは D を注記に出す
        kind = "day" if el > 3 else "dusk"
        cam_floor = "2F" if c["cam"][2] > h.fl["2F"] else "1F"
        res = list(ic["resolution"])
        samples, tl = ic["samples"], ic["time_limit"]
        if args.preview:
            res, samples, tl = ([int(v) for v in args.size.split('x')] if args.size else [480, 270]), args.samples or 16, 90
        elif args.samples:
            samples = args.samples
        cut = dict(id=cid, file=c["file"], title=c["title"], kind=kind, lens=c["lens"], res=res, samples=samples, time_limit=tl,
                   cam=fr.to_bl(*c["cam"]), target=fr.to_bl(*c["target"]), cam_mm=c["cam"], target_mm=c["target"],
                   exposure=c["exposure"], wb=c["wb"], when=c["when"], pitch=c.get("pitch"), shift_y=c.get("shift_y", 0.0), shift_x=c.get("shift_x", 0.0),
                   sun=dict(el=round(el, 2), az=round(az, 2)) if kind == "day" else None, sun_strength=3.0,
                   sky_strength=1.0 if kind == "day" else (0.4 if hour < 19 else 0.05),
                   lamp_k=round(K), lamp_pct=round(pct, 1), lamp_w=ic["lamp_w"], ch={k_: [round(v_[0]), round(v_[1], 1)] for k_, v_ in chs.items()},
                   close_doors=c.get("close_doors", []), floors_lit=[cam_floor] + (["1F"] if c.get("also_1f") else []),
                   screens=c["screens"], open_doors=c.get("open_doors", {}), screen_video=bool(c.get("screen_video")),
                   out=str(out_dir / (c["file"] + ".png")))
        cuts.append(cut)
    scr = next(i for i in its if i.id == "TH-S")
    scn = scenery_cfg(h, spec)
    cfg = dict(
        mode="interior", glb=str(glb_path), alpha=h.alpha, pivot=[h.W / 2000.0, h.D / 2000.0], materials=mats, colors_lin=colors_lin,
        textures=assets["textures"], hdri={k: v["path"] for k, v in assets["hdri"].items()}, planters=scn["planters"], scenery=scn, window_lights=[], ext_lights=[],
        lamp_color=list(RC.LAMP_LIN), lamp_strength=0.0, room_light=dict(kelvin=3000, strength=0.0), sky_clamp=spec["cg"].get("sky_clamp", 30.0),
        adaptive_threshold=ic["adaptive_threshold"], max_bounces=8, cuts=cuts, preview=bool(args.preview), raw_log=str(out_dir / "render_log_raw.json"),
        look="None", view_transform=ic.get("view_transform", "Khronos PBR Neutral"),
        interior=dict(palette=pal, glass_tv={k_: spec["glazing"]["types"][k_]["tv"] for k_ in ("gain", "shield")}, downlights=furniture.downlights(h, its), doors=furniture.door_info(h),
                      lines=LG.lines(h, its), foots=LG.footlights(h), line_w_mm=spec["lighting"]["line"]["width"], line_h_mm=spec["lighting"]["line"]["height"],
                      downlight_ratio=ic["downlight_ratio"], k_area_w_per_lm=ic["k_area_w_per_lm"], k_spot_w_per_lm=ic["k_spot_w_per_lm"],
                      foot_lm=spec["lighting"]["foot"]["lm"],
                      inside_m=[h.W / 1000.0, h.D / 1000.0, (h.fl["RF"] - h.slab_t) / 1000.0],
                      screen_rect=[scr.rect[0] / 1000.0, scr.z0 / 1000.0, scr.rect[2] / 1000.0, (scr.z0 + scr.h) / 1000.0]))
    return cfg, its


def camera_clearance(h, its, cuts):
    """カメラから壁・床・家具の箱までの最短距離（mm）。150mm 以上であること（H6）。"""
    boxes = [(b.x0, b.y0, b.z0, b.x1, b.y1, b.z1, b.cat) for b in h.boxes if b.cat in ("wall", "partition", "parapet", "stair", "slab", "door", "glass", "footing")]
    for it in its:
        boxes.append((it.rect[0], it.rect[1], it.z0, it.rect[2], it.rect[3], it.z0 + it.h, it.id))
    for name, r, hh, kg in h.equipment:
        boxes.append((r[0], r[1], h.fl["1F"], r[2], r[3], h.fl["1F"] + hh, name))
    out = {}
    for c in cuts:
        x, y, z = c["cam_mm"]
        best = (1e9, "")
        for (x0, y0, z0, x1, y1, z1, nm) in boxes:
            dx = max(x0 - x, 0, x - x1)
            dy = max(y0 - y, 0, y - y1)
            dz = max(z0 - z, 0, z - z1)
            d = math.sqrt(dx * dx + dy * dy + dz * dz)
            if d < best[0]:
                best = (d, nm)
        out[c["id"]] = dict(mm=round(best[0]), nearest=best[1])
    return out


def _font(size):
    from PIL import ImageFont
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    raise FileNotFoundError("IPA ゴシックが見つかりません")


def annotate(path, cut, spec, band=36):
    """メタデータを残さず保存し直し、下端に仮置きの注記の帯を足す（画素として入れる）。"""
    from PIL import Image, ImageDraw
    im = Image.open(path)
    im.load()
    rgb = im.convert("RGB")
    W, H = rgb.size
    out = Image.new("RGB", (W, H + band), (241, 237, 228))
    out.paste(rgb, (0, 0))
    d = ImageDraw.Draw(out)
    fs = max(10, int(band * 0.5))
    f = _font(fs)
    mo, da, hh, mm = int(cut["when"][5:7]), int(cut["when"][8:10]), cut["when"][11:13], cut["when"][14:16]
    left = f"家具は仮置き（後日差し替え）・指定商品の寸法と色は仮定・色はいずれも仮定・屋外の樹木は添景"
    chn = cut["ch"]
    lt = f"主照明 {chn['L'][0]:,}K・{chn['L'][1]:.0f}%" if chn["L"][1] > 0 else f"主照明 消灯・補助灯 {chn['D'][0]:,}K・{chn['D'][1]:.0f}%"
    right = f"{cut['title']}　{mo}月{da}日 {hh}:{mm}　{lt}"
    ty = H + (band - fs) // 2 - 1
    d.text((int(fs * 0.8), ty), left, font=f, fill=(60, 56, 50))
    tw = d.textlength(right, font=f)
    d.text((W - tw - int(fs * 0.8), ty), right, font=f, fill=(60, 56, 50))
    out.save(path, "PNG", optimize=True)         # pnginfo なし


def main(args):
    t_start = time.time()
    h = House(ROOT)
    spec = h.spec
    ic = spec["interior_cg"]
    out_dir = (ROOT / ".cache" / "cg" / "interior_preview") if args.preview else (ROOT / "dist" / "render" / "interior")
    out_dir.mkdir(parents=True, exist_ok=True)
    glb = ROOT / "dist" / "model_interior.glb"
    t = time.time()
    if not args.no_glb or not glb.exists():
        export_glb(h, glb, interior=True)
    t_glb = time.time() - t
    # 家具の干渉検査（適合しなければ描かない）
    its = furniture.items(h)
    errs = furniture.check(h, its)
    if errs:
        print("furniture.check のエラー:", errs)
        return 3
    t = time.time()
    tex = {**spec["cg"]["textures"], **ic["textures"]}
    assets = RC.fetch_assets({"cg": {"textures": tex, "hdri": spec["cg"]["hdri"]}}, ROOT / ".cache" / "cg", use_textures=True)
    t_assets = time.time() - t
    cfg, its = interior_cfg(h, spec, args, assets, out_dir, glb)
    clear = camera_clearance(h, its, cfg["cuts"])
    print("camera clearance (mm):", {k: v["mm"] for k, v in clear.items()})
    bad = {k: v for k, v in clear.items() if v["mm"] < 150}
    if bad:
        print("カメラが壁・家具に近すぎます（150mm 未満）:", bad)
        return 4
    scene_path = out_dir / "scene.json"
    scene_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.scene_only:
        return 0
    py = os.environ.get("BPY_PYTHON") or str(ROOT / ".venv-bpy" / "bin" / "python")
    if not Path(py).exists():
        print("bpy が見つかりません。README の手順で .venv-bpy を作るか、環境変数 BPY_PYTHON を指定してください")
        return 2
    cmd = [py, str(ROOT / "src" / "cg_blender.py"), str(scene_path)]
    if args.only:
        cmd += ["--only", ",".join(sorted(args.only))]
    log_path = out_dir / "blender.log"
    with open(log_path, "w", encoding="utf-8") as lf:
        rc = subprocess.call(cmd, stdout=lf, stderr=subprocess.STDOUT)
    if rc != 0:
        print("Blender 段階が失敗しました（終了コード", rc, "）。ログ:", log_path)
        return rc
    raw = json.loads(Path(cfg["raw_log"]).read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in cfg["cuts"]}
    for r in raw["cuts"]:
        RC.post_process(r["file"])
        if not args.preview and ic.get("annotation_band", 0):
            annotate(r["file"], by_id[r["id"]], spec, ic["annotation_band"])
        r["time_limit_hit"] = r["render_seconds"] >= by_id[r["id"]]["time_limit"] - 3
    # 材質の色の照合（H8: リニア値が interior_palette と ±0.002 で一致）
    pal_mismatch = []
    mc = raw.get("material_colors", {})
    for k, v in cfg["interior"]["palette"].items():
        if k in mc and any(abs(a - b) > 0.002 for a, b in zip(mc[k], v["rgb"])):
            pal_mismatch.append(k)
    total = round(time.time() - t_start, 1)
    log = dict(total_seconds=total, glb_export_seconds=round(t_glb, 1), asset_fetch_seconds=round(t_assets, 1), blender_setup_seconds=raw.get("setup_seconds"),
               cuts=raw["cuts"], textures={k: v["status"] for k, v in assets["textures"].items()},
               hdri={k: v["status"] for k, v in assets["hdri"].items()}, source=assets["source"],
               camera_clearance_mm=clear, palette_checked=len([k for k in cfg["interior"]["palette"] if k in mc]), palette_mismatch=pal_mismatch,
               settings=dict(resolution=ic["resolution"], samples=ic["samples"], adaptive_threshold=ic["adaptive_threshold"], time_limit=ic["time_limit"],
                             view_transform=cfg["view_transform"]))
    for r in raw["cuts"]:
        r["when"] = by_id[r["id"]]["when"]
    lp = out_dir / "render_log.json"
    if args.only and not args.preview and lp.exists():
        # 一部のカットだけ描き直したときは、既存の render_log（描き直していないカットと注記）に重ねてマージする
        old = json.loads(lp.read_text(encoding="utf-8"))
        new_ids = {r["id"] for r in raw["cuts"]}
        order = list(ic["cuts"].keys())
        merged = dict(old)
        merged["previous_run_total_seconds"] = old.get("total_seconds")
        for k_ in ("total_seconds", "glb_export_seconds", "asset_fetch_seconds", "blender_setup_seconds", "source", "palette_checked", "palette_mismatch", "settings"):
            merged[k_] = log[k_]
        merged["cuts"] = sorted([c for c in old.get("cuts", []) if c.get("id") not in new_ids] + raw["cuts"], key=lambda c: order.index(c["id"]) if c.get("id") in order else 99)
        merged["camera_clearance_mm"] = {**old.get("camera_clearance_mm", {}), **clear}
        merged["textures"] = {**old.get("textures", {}), **log["textures"]}
        merged["hdri"] = {**old.get("hdri", {}), **log["hdri"]}
        merged["rerendered"] = dict(cuts=sorted(new_ids), when="2026-03-21T14:00", version="v4.19")
        log = merged
    lp.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: {len(raw['cuts'])} cuts, total {total} s -> {out_dir}")
    return 0
