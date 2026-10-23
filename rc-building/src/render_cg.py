"""外観CG（写実的な景観イメージ）を生成する。二段階の構成。

段階1（このファイル、システムの python3）: House から GLB（CG 用の要素を含む）を書き出し、カメラ・太陽・照明・材質を
    scene.json にまとめ、Poly Haven（CC0）のテクスチャと HDRI を取得する。
段階2（src/cg_blender.py、bpy の入った python）: GLB を取り込み、材質を与えて Cycles（CPU）で描画する。

    python3 src/render_cg.py                       # 全カットを本番の品質で
    python3 src/render_cg.py --preview             # 960×540・16spp・テクスチャなし（構図の確認）
    python3 src/render_cg.py --only C03 --samples 64

bpy は .venv-bpy にインストールする（README の手順）。環境変数 BPY_PYTHON でインタプリタを指定してもよい。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from house import House  # noqa: E402
from model3d import export_glb, material_table, srgb_to_lin  # noqa: E402

LAMP_LIN = (1.0, 0.288, 0.020)        # 2200K（Blackbody の近似、リニア）
PH_API = "https://api.polyhaven.com/files/"
PH_HDRI = "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/{id}_2k.hdr"


# ------------------------------------------------------------------ 太陽位置（NOAA の簡易式）
def sun_position(when: str, lat: float, lon: float, tz: float):
    """when: 'YYYY-MM-DDTHH:MM'（現地時刻）→ (高度°, 方位° 真北から時計回り)。"""
    t = dt.datetime.fromisoformat(when)
    doy = t.timetuple().tm_yday
    hour = t.hour + t.minute / 60.0
    g = 2 * math.pi / 365.0 * (doy - 1 + (hour - 12) / 24.0)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = hour * 60 + eqt + 4 * lon - 60 * tz
    ha = math.radians(tst / 4 - 180)
    phi = math.radians(lat)
    sa = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(ha)
    el = math.asin(max(-1, min(1, sa)))
    az_s = math.atan2(math.sin(ha), math.cos(ha) * math.sin(phi) - math.tan(decl) * math.cos(phi))   # 南基準・西が正
    return math.degrees(el), (math.degrees(az_s) + 180.0) % 360.0


def lamp_schedule(spec, hour):
    """spec.smart.lighting_schedule を hour 時で線形補間 → (K, 明るさ%)。"""
    rows = spec["smart"]["lighting_schedule"]
    for (h0, k0, b0), (h1, k1, b1) in zip(rows, rows[1:]):
        if h0 <= hour <= h1:
            f = (hour - h0) / (h1 - h0)
            return k0 + (k1 - k0) * f, b0 + (b1 - b0) * f
    return rows[-1][1], rows[-1][2]


# ------------------------------------------------------------------ アセット取得（Poly Haven, CC0）
def _get(url, dest, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if len(data) < 1000:
        raise IOError("too small")
    Path(dest).write_bytes(data)


def fetch_assets(spec, cache, use_textures=True):
    """テクスチャ（Diffuse 1k）と HDRI を .cache/cg/ に保存。失敗したものは None（手続き生成にフォールバック）。"""
    cache.mkdir(parents=True, exist_ok=True)
    info = {"textures": {}, "hdri": {}, "source": "Poly Haven (CC0)"}
    tex = {}
    for name, asset in spec["cg"]["textures"].items():
        dest = cache / f"{asset}_diff.jpg"
        entry = {"asset": asset, "diff": None, "status": "skipped"}
        if use_textures:
            try:
                if not dest.exists():
                    meta = json.loads(urllib.request.urlopen(urllib.request.Request(PH_API + asset, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read())
                    url = meta["Diffuse"]["1k"]["jpg"]["url"]
                    _get(url, dest)
                entry.update(diff=str(dest), status="ok")
            except Exception as e:                       # noqa: BLE001
                entry["status"] = f"procedural fallback: {asset} ({type(e).__name__})"
                print("procedural fallback:", asset, type(e).__name__, str(e)[:80])
        tex[name] = entry
    info["textures"] = tex
    hd = {}
    for kind, hid in spec["cg"]["hdri"].items():
        dest = cache / f"{hid}_2k.hdr"
        entry = {"asset": hid, "path": None, "status": "ok"}
        try:
            if not dest.exists():
                _get(PH_HDRI.format(id=hid), dest, timeout=60)
            entry["path"] = str(dest)
        except Exception as e:                           # noqa: BLE001
            entry["status"] = f"sky texture fallback: {hid} ({type(e).__name__})"
            print("sky fallback:", hid, type(e).__name__)
        hd[kind] = entry
    info["hdri"] = hd
    return info


# ------------------------------------------------------------------ scene.json
class Frame:
    """建物座標 mm ⇄ Blender（真北基準・m・設計GL 基準）。"""

    def __init__(self, h):
        self.a = h.alpha
        self.piv = (h.W / 2000.0, h.D / 2000.0)

    def to_bl(self, x, y, z):
        dx, dy = x / 1000 - self.piv[0], y / 1000 - self.piv[1]
        c, s = math.cos(self.a), math.sin(self.a)
        return [dx * c - dy * s + self.piv[0], dx * s + dy * c + self.piv[1], z / 1000]

    def vec(self, x, y, z):
        c, s = math.cos(self.a), math.sin(self.a)
        return [x * c - y * s, x * s + y * c, z]


def eye_z(h, x, y, eye_h):
    from shapely.geometry import Point
    return (h.fgl if h.site.contains(Point(x, y)) else h.ground(x, y)) + eye_h


def build_cfg(h, spec, args, assets, out_dir):
    cg = spec["cg"]
    fr = Frame(h)
    table = material_table(spec)
    mats = {}
    for k, t in table.items():
        sm = spec["materials"].get(k, {})
        mats[k] = dict(rgb=t["rgb"], roughness=t["roughness"], metallic=t["metallic"], coat=sm.get("coat", 0.0))
    colors_lin = dict(tile_joint=srgb_to_lin(spec["colors"]["tile_joint"]), dotcon_joint=srgb_to_lin("#8F8572"),
                      pv_joint=srgb_to_lin("#3A3F48"), plant_a=srgb_to_lin("#4E6B2E"), plant_b=srgb_to_lin("#6E8B3D"))
    S = 1000.0
    # カット
    cuts = []
    lat, lon, tz = cg["site"]["lat"], cg["site"]["lon"], cg["site"]["tz"]
    for cid, c in cg["cuts"].items():
        if args.only and cid not in args.only:
            continue
        x, y, z = c["cam"]
        z = eye_z(h, x, y, cg["eye_h"]) if z == "eye" else z
        tx, ty, tz_ = c["target"]
        res = c.get("res", cg["resolution"])
        kind = c.get("kind", "day")
        el, az = sun_position(c["when"], lat, lon, tz)
        samples = c.get("samples", cg["samples"])
        tl = c.get("time_limit", cg["time_limit"])
        exposure = c.get("exposure", cg.get("exposure", {}).get(kind, 0.0))
        if args.preview:
            res = [960, 540] if res[0] >= 1900 else [int(res[0] / 2), int(res[1] / 2)]
            samples, tl = args.samples or 16, 90
        elif args.samples:
            samples = args.samples
        cut = dict(id=cid, file=c["file"], title=c["title"], kind=kind, lens=c["lens"], res=res, samples=samples, time_limit=tl,
                   cam=fr.to_bl(x, y, z), target=fr.to_bl(tx, ty, tz_), exposure=exposure, when=c["when"],
                   sun=dict(el=round(el, 2), az=round(az, 2)),
                   sun_strength=c.get("sun_strength", cg.get("sun_strength", 3.0)), sky_strength=c.get("sky_strength", cg.get("sky_strength", {}).get(kind, 1.0)),
                   out=str((out_dir / (c["file"] + ".png"))))
        cut["cam_mm"] = [x, y, z]
        cuts.append(cut)
    # プランター（植物は Blender 側で作る）。建物座標 m のまま渡し、段階2 でオブジェクトの変換（真北への回転）を与える
    fm = spec["farm"]
    pg = spec["exterior"]["solar_pergola"]
    x0, y0, x1, y1 = h.pergola
    zb = max(h.ground((x0 + x1) / 2, (y0 + y1) / 2), h.fgl)
    planters = []
    for b in h.garden_beds:
        planters.append(dict(rect=[v / S for v in b], soil_z=(zb + fm["leg"] + fm["planter_h"] - 50) / S, height=0.30, kind="shade"))
    for b in h.planters:
        planters.append(dict(rect=[v / S for v in b], soil_z=(h.fgl + 20 + fm["leg"] + fm["planter_h"] - 50) / S, height=0.45, kind="sun"))
    # 夕景: 室内の灯り（窓の 0.8m 内側、窓より 0.4m 大きい発光面）
    e = h.t / 2 + h.ins
    hour = 19 + 10 / 60
    for c in cuts:
        if c["kind"] == "dusk":
            hour = int(c["when"][11:13]) + int(c["when"][14:16]) / 60.0
    kelvin, pct = lamp_schedule(spec, hour)
    wl = []
    for op in h.openings(exterior=True):
        if op.kind != "window":
            continue
        s = op.wall.side
        um, zm = (op.u0 + op.u1) / 2, (op.z0 + op.z1) / 2
        w, hh = op.width + 400, op.height + 400
        if s == "S":
            p, nrm, uax = (um, 800, zm), (0, -1, 0), (1, 0, 0)
        elif s == "N":
            p, nrm, uax = (um, h.D - 800, zm), (0, 1, 0), (1, 0, 0)
        elif s == "W":
            p, nrm, uax = (800, um, zm), (-1, 0, 0), (0, 1, 0)
        else:
            p, nrm, uax = (h.W - 800, um, zm), (1, 0, 0), (0, 1, 0)
        wl.append(dict(center=fr.to_bl(*p), u=[v * w / S for v in fr.vec(*uax)], v=[0, 0, hh / S], normal=fr.vec(*nrm), side=s))
    # 外構照明（2200K、下向き全カットオフ）。北側（水路側）には置かない
    el_lights = []
    cp = h.carport
    cph = spec["exterior"]["carport"]["h"]
    porch_top = h.fl["1F"] - 2 * 180 - 20
    for name, (x, y) in h.ext_lights:
        if y > h.D:
            continue
        if name == "ボラード":
            z, w, cone = h.fgl + 560, 45.0, 120
        elif name.startswith("足元灯"):
            z, w, cone = porch_top + 290, 24.0, 120
        elif name.startswith("カーポート"):
            z, w, cone = h.fgl + cph - 50, 90.0, 100
        else:
            z, w, cone = h.fgl + 340, 30.0, 120
        el_lights.append(dict(name=name, pos=fr.to_bl(x, y, z), watts=w, cone=cone))
    cfg = dict(
        glb=str(ROOT / "dist" / "model.glb"), alpha=h.alpha, pivot=[h.W / 2000.0, h.D / 2000.0],
        materials=mats, colors_lin=colors_lin, textures=assets["textures"], hdri={k: v["path"] for k, v in assets["hdri"].items()},
        planters=planters,
        window_lights=wl if any(c["kind"] == "dusk" for c in cuts) else [],
        ext_lights=el_lights, lamp_color=list(LAMP_LIN), lamp_strength=cg.get("lamp_strength", 40.0),
        room_light=dict(kelvin=round(kelvin), strength=cg.get("room_strength", 3.0) * pct / 55.0),
        sky_clamp=cg.get("sky_clamp", 30.0), adaptive_threshold=0.05 if args.preview else 0.03, max_bounces=4 if args.preview else 6,
        cuts=cuts, preview=bool(args.preview), raw_log=str(out_dir / "render_log_raw.json"), look=cg.get("look", "None"), view_transform=cg.get("view_transform", "AgX"))
    return cfg


def check_cameras(h, cuts):
    """カメラが周辺建物から 1.5m 以上離れていること。"""
    from shapely.geometry import Point, Polygon
    out = []
    for c in cuts:
        x, y, z = c["cam_mm"]
        p = Point(x, y)
        d = min((Polygon(b).distance(p) for b in h.neighbors if Polygon(b).is_valid and Polygon(b).area >= 4e6), default=1e9) / 1000
        out.append((c["id"], round(d, 2)))
    return out


def post_process(path):
    """PNG のメタデータを残さない（Pillow で読み込み、pnginfo なしで保存し直す）。"""
    from PIL import Image
    im = Image.open(path)
    im.load()
    im2 = Image.new("RGB", im.size)
    im2.putdata(list(im.convert("RGB").getdata()))
    im2.save(path, "PNG", optimize=True)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--scene-only", action="store_true", help="scene.json だけ書いて終わる")
    ap.add_argument("--no-glb", action="store_true")
    args = ap.parse_args(argv)
    args.only = set(args.only.split(",")) if args.only else None
    t_start = time.time()
    h = House(ROOT)
    spec = h.spec
    out_dir = (ROOT / ".cache" / "cg" / "preview") if args.preview else (ROOT / "dist" / "render")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_glb:
        export_glb(h, ROOT / "dist" / "model.glb")
    t_assets = time.time()
    assets = fetch_assets(spec, ROOT / ".cache" / "cg", use_textures=not args.preview)
    t_assets = time.time() - t_assets
    cfg = build_cfg(h, spec, args, assets, out_dir)
    scene_path = out_dir / "scene.json"
    scene_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    cams = check_cameras(h, cfg["cuts"])
    print("camera distance to neighbors (m):", cams)
    if any(d < 1.5 for _, d in cams):
        print("warning: camera closer than 1.5 m to a neighbor building")
    if args.scene_only:
        return 0
    py = os.environ.get("BPY_PYTHON") or str(ROOT / ".venv-bpy" / "bin" / "python")
    if not Path(py).exists():
        print("bpy が見つかりません。次で導入してください:\n  cd rc-building && python3 -m venv .venv-bpy && .venv-bpy/bin/pip install bpy==5.0.1\n"
              "（または環境変数 BPY_PYTHON に bpy の入った python を指定）")
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
    for r in raw["cuts"]:
        post_process(r["file"])
    total = round(time.time() - t_start, 1)
    log = dict(total_seconds=total, asset_fetch_seconds=round(t_assets, 1), blender_setup_seconds=raw.get("setup_seconds"),
               cuts=raw["cuts"], textures={k: v["status"] for k, v in assets["textures"].items()},
               hdri={k: v["status"] for k, v in assets["hdri"].items()}, source=assets["source"], camera_neighbor_distance_m=dict(cams))
    (out_dir / "render_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: {len(raw['cuts'])} cuts, total {total} s -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
