"""再現性試験（v4.33 §3）: I01・I03・Z1-11a を旧経路（--legacy）とマスター経路で同じ条件（解像度・spp・seed 0・時間制限なし）で撮り比べる。

    python3 tools/repro_blend.py [--samples 32] [--skip-render]
合格基準: palette_mismatch = 0、平均輝度の差 ≤ 3%、各チャンネル平均差 ≤ 4/255、窓領域（project_window）の平均輝度差 ≤ 5%。
画像は .cache/cg/repro/ に出す（コミットしない）。
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

OUT = ROOT / ".cache" / "cg" / "repro"


def sh(cmd, log):
    with open(OUT / log, "w", encoding="utf-8") as lf:
        return subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=ROOT).returncode


def window_mask(h, spec, W, H):
    """窓ガラス（AW）の箱を画像へ投影した領域（RZ.project_window を任意の向きに一般化）。"""
    cx, cy, cz = spec["cam"]
    tx, ty, _ = spec["target"]
    fl = math.hypot(tx - cx, ty - cy)
    fx, fy = (tx - cx) / fl, (ty - cy) / fl
    rx, ry = fy, -fx
    L = spec["lens"]
    floor = "2F" if cz > h.fl["2F"] else "1F"
    mask = np.zeros((H, W), bool)
    for b in h.boxes:
        if b.cat != "glass" or not b.tag.startswith("AW") or b.level != floor:
            continue
        pts, ok = [], True
        for x in (b.x0, b.x1):
            for y in (b.y0, b.y1):
                for z in (b.z0, b.z1):
                    px, py, pz = x - cx, y - cy, z - cz
                    dep = px * fx + py * fy
                    if dep < 200:
                        ok = False
                        break
                    pts.append((W / 2 + (px * rx + py * ry) / dep * L / 36.0 * W, H / 2 - (pz / dep * L / 36.0 - spec.get("shift_y", 0.0)) * W))
        if not ok:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, x1, y0, y1 = max(min(xs), 0), min(max(xs), W), max(min(ys), 0), min(max(ys), H)
        if x1 - x0 >= 4 and y1 - y0 >= 4:
            mask[int(y0):int(y1), int(x0):int(x1)] = True
    return mask


def stats(path, h, spec, crop_bottom=0):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    if crop_bottom:
        a = a[:-crop_bottom]
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    m = window_mask(h, spec, a.shape[1], a.shape[0])
    return dict(mean=float(lum.mean()), rgb=[float(a[..., i].mean()) for i in range(3)], win=float(lum[m].mean()) if m.sum() > 100 else None, win_area=float(m.mean()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--skip-render", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    from house import House
    import render_zones as RZ
    h = House(ROOT)
    Z = RZ.load()
    py = sys.executable
    sam = str(a.samples)
    if not a.skip_render:
        rc1 = sh([py, "src/render_cg.py", "--interior", "--legacy", "--preview", "--only", "I01,I03", "--size", "640x360", "--samples", sam, "--time-limit", "0"], "legacy_I.log")
        rc2 = sh([py, "src/render_zones.py", "--legacy", "--preview", "--only", "Z1-11a"], "legacy_Z.log")
        rc3 = sh([py, "src/shoot.py", "--camera", "I01,I03", "--preview", "--res", "640", "360", "--samples", sam, "--time-limit", "0", "--seed", "0"], "master_I.log")
        rc4 = sh([py, "src/shoot.py", "--camera", "Z1-11a", "--preview", "--seed", "0"], "master_Z.log")
        print("exit codes legacy I/Z, master I/Z:", rc1, rc2, rc3, rc4)
    spec_i = h.spec["interior_cg"]["cuts"]
    zd = RZ.cut_defs(h, Z)
    pairs = [("I01", ROOT / ".cache/cg/interior_preview/I01_ldk_south.png", ROOT / ".cache/cg/shoot/preview/I01_ldk_south.png", spec_i["I01"], 0),
             ("I03", ROOT / ".cache/cg/interior_preview/I03_kitchen.png", ROOT / ".cache/cg/shoot/preview/I03_kitchen.png", spec_i["I03"], 0),
             ("Z1-11a", ROOT / ".cache/cg/interior_zones/preview/Z1-11a.jpg", ROOT / ".cache/cg/shoot/preview/Z1-11a.jpg", zd["Z1-11a"]["spec"], Z["settings"]["band_px"])]
    res = {}
    ok_all = True
    for cid, lp, mp, spec, band in pairs:
        s1, s2 = stats(lp, h, spec, band), stats(mp, h, spec, band)
        d_mean = abs(s1["mean"] - s2["mean"]) / max(s1["mean"], 1e-6) * 100
        d_rgb = [abs(x - y) for x, y in zip(s1["rgb"], s2["rgb"])]
        d_win = abs(s1["win"] - s2["win"]) / max(s1["win"], 1e-6) * 100 if s1["win"] and s2["win"] else None
        ok = d_mean <= 3.0 and max(d_rgb) <= 4.0 and (d_win is None or d_win <= 5.0)
        ok_all &= ok
        res[cid] = dict(legacy=s1, master=s2, mean_diff_pct=round(d_mean, 2), rgb_diff=[round(v, 2) for v in d_rgb], window_diff_pct=None if d_win is None else round(d_win, 2), ok=ok)
        print(f"{cid}: 平均輝度 {s1['mean']:.1f} vs {s2['mean']:.1f}（差 {d_mean:.2f}%）／RGB 差 {[round(v, 2) for v in d_rgb]}／窓領域 {s1['win']} vs {s2['win']}（差 {d_win}）→ {'合格' if ok else '不合格'}", flush=True)
    # palette_mismatch（材質の色のリニア値が interior_palette と ±0.002 で一致しない材質の数）
    lg = ROOT / ".cache/cg/interior_preview/render_log.json"
    leg = json.loads(lg.read_text(encoding="utf-8")).get("palette_mismatch") if lg.exists() else None
    pv = json.loads((ROOT / ".cache/cg/shoot/preview/preview_log.json").read_text(encoding="utf-8"))
    mm = {k: v.get("palette_mismatch") for k, v in pv.items()}
    pm_ok = not leg and all(not v for v in mm.values())
    ok_all &= pm_ok
    res["palette_mismatch"] = dict(legacy=leg, master=mm, ok=pm_ok)
    print("palette_mismatch: 旧経路", leg, "／マスター", mm, "→", "0（合格）" if pm_ok else "不合格")
    (OUT / "repro.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("総合:", "合格" if ok_all else "不合格")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
