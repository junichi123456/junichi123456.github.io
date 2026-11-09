"""v4.30 内装CG 区画シート（システムの python3）: 階ごとの 3×3 モンタージュ 2 枚と、区画ごとの 2 枚並べ 18 枚（キープランに撮影点と画角の扇）。
Blender は使わない。入力は dist/render/interior/zones/*.jpg と render_log_zones.json、data/interior_zones.yaml。

    python3 src/zone_sheets.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw  # noqa: E402

import render_zones as RZ  # noqa: E402
from house import House  # noqa: E402

INK, SUB, PAPER, RED = (40, 36, 30), (96, 90, 80), (241, 237, 228), (200, 40, 40)
OUTDIR = RZ.OUT / "sheets"
MONTAGE_DIR = ROOT / "dist" / "render" / "interior"
FIND_COL = {"設計": (180, 80, 20), "CG": (40, 90, 160)}


def font(n):
    return RZ.RI._font(n)


def load_img(cid, c, w, h):
    im = Image.open(RZ.jpg_path(cid)).convert("RGB")
    im = im.crop((0, 0, im.width, im.height - RZ.load()["settings"]["band_px"]))      # 注記帯を除く
    return im.resize((w, h), Image.LANCZOS)


def wrap(d, text, f, width):
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    return lines + ([cur] if cur else [])


def zone_findings(Z, zone):
    return [f for f in Z.get("findings", []) if zone in f.get("cuts", [])]


def zone_title(Z, zone):
    cs = [c for c in Z["cuts"].values() if c["zone"] == zone]
    rooms = []
    for c in cs:
        if c["room"] not in rooms:
            rooms.append(c["room"])
    return " ／ ".join(rooms)


def status_of(lg, cid):
    e = lg["cuts"].get(cid, {})
    return e.get("status", "none"), e.get("issues", [])


def montage(floor, Z, lg):
    """北が上: 上段 = Y 区間 3、左列 = X 区間 1。各セルに a|b を 640×360。flag は赤枠と理由。"""
    fi = floor[0]
    cw, ih, hh, rh = 1296, 360, 40, 44
    M = 16
    W = 3 * cw + 4 * M
    flag_h = 0
    rows_h = []
    for yj in (3, 2, 1):
        mx = 0
        for xi in (1, 2, 3):
            z = f"Z{fi}-{xi}{yj}"
            n = sum(len(iss) for cid in (z + "a", z + "b") for iss in [status_of(lg, cid)[1]])
            mx = max(mx, n)
        rows_h.append(hh + ih + 6 + (rh if mx else 0))
    top = 96
    H = top + sum(rows_h) + 4 * M + 40
    sh = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(sh)
    st = Z["settings"]
    d.text((M, 14), f"{floor} 内装CG 区画別（9 区画 × 2 方向）　3月21日 15:30　視点 FL+{st['eye_above_fl_mm']:,}　北が上", font=font(30), fill=INK)
    nflag = sum(1 for c in Z["cuts"] if c[1] == fi and status_of(lg, c)[0] == "flag")
    d.text((M, 56), f"各区画の左 = a、右 = b。家具は仮置き・色は仮定・屋外の樹木は添景。自動検査で引っかかったカット {nflag} 件は赤枠で示す", font=font(18), fill=SUB)
    y = top
    for r, yj in enumerate((3, 2, 1)):
        x = M
        for xi in (1, 2, 3):
            z = f"Z{fi}-{xi}{yj}"
            d.text((x, y), z, font=font(24), fill=INK)
            d.text((x + 100, y + 5), zone_title(Z, z)[:34], font=font(18), fill=SUB)
            fz = zone_findings(Z, z)
            if fz:
                d.text((x + cw - 190, y + 5), "要確認 " + "・".join(f["id"] for f in fz), font=font(16), fill=FIND_COL["設計"])
            for k, ab in enumerate("ab"):
                cid = z + ab
                ix = x + k * (ih * 16 // 9 // 1 + 8) if False else x + k * 648
                im = load_img(cid, Z["cuts"][cid], 640, ih)
                sh.paste(im, (ix, y + hh))
                s, iss = status_of(lg, cid)
                if s == "flag":
                    d.rectangle([ix - 2, y + hh - 2, ix + 641, y + hh + ih + 1], outline=RED, width=4)
                d.text((ix + 6, y + hh + 4), f"{ab}", font=font(20), fill=(255, 255, 255))
                d.text((ix + 6, y + hh + 3), f"{ab}", font=font(20), fill=(255, 255, 255))
                if iss:
                    for li, ln in enumerate(wrap(d, f"{cid}: " + "；".join(iss), font(14), 636)[:3]):
                        d.text((ix, y + hh + ih + 4 + li * 15), ln, font=font(14), fill=RED)
            x += cw + M
        y += rows_h[r] + M
    return sh


def keyplan(h, Z, lg, zone, size=450):
    fl = Z["cuts"][zone + "a"]["floor"]
    s = size / h.W
    im = Image.new("RGB", (size, size), (252, 250, 245))
    d = ImageDraw.Draw(im)
    P = lambda x, y: (x * s, size - y * s)
    for r in h.rooms:
        if r.floor == fl:
            x0, y1 = P(r.rect[0], r.rect[1])
            x1, y0 = P(r.rect[2], r.rect[3])
            d.rectangle([x0, y0, x1, y1], outline=(150, 144, 134), fill=(244, 240, 231))
    g = h.gx
    i, j = int(zone[3]), int(zone[4])
    x0, y1 = P(g[i - 1], g[j - 1])
    x1, y0 = P(g[i], g[j])
    d.rectangle([x0, y0, x1, y1], outline=(214, 120, 40), width=3)
    cols = {"a": (30, 100, 190), "b": (190, 60, 50)}
    for ab in "ab":
        c = Z["cuts"][zone + ab]
        dd = RZ.cut_defs(h, Z)[zone + ab]
        hf = math.radians(RZ.hfov(dd["spec"]["lens"]))
        fx, fy = RZ.DIRS[c["dir"]]
        ang = math.atan2(fy, fx)
        px, py = P(c["x"], c["y"])
        R = 2600 * s
        pts = [(px, py)] + [(px + R * math.cos(ang + t), py - R * math.sin(ang + t)) for t in [(-hf / 2) + hf * k / 12 for k in range(13)]]
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(ov).polygon(pts, fill=cols[ab] + (70,), outline=cols[ab] + (255,))
        im.paste(ov, (0, 0), ov)
        d = ImageDraw.Draw(im)
        d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=cols[ab])
        d.text((px + 7, py - 22), ab, font=font(18), fill=cols[ab])
    d.text((6, 4), f"{fl} キープラン（北が上）", font=font(14), fill=INK)
    return im


def zone_sheet(h, Z, lg, zone):
    iw, ih, M = 800, 450, 16
    W = 2 * iw + size_kp + 4 * M if False else 2 * iw + 450 + 4 * M
    cap_h = 150
    fz = zone_findings(Z, zone)
    H = 84 + ih + cap_h + M * 2 + (24 * len(fz) if fz else 0)
    sh = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(sh)
    fl = Z["cuts"][zone + "a"]["floor"]
    d.text((M, 12), f"{zone}　{zone_title(Z, zone)}", font=font(30), fill=INK)
    d.text((M, 52), f"{fl}　3月21日 15:30　視点 FL+{Z['settings']['eye_above_fl_mm']:,}　家具は仮置き・色は仮定・屋外の樹木は添景", font=font(16), fill=SUB)
    for k, ab in enumerate("ab"):
        cid = zone + ab
        c = Z["cuts"][cid]
        x = M + k * (iw + M)
        sh.paste(load_img(cid, c, iw, ih), (x, 84))
        s, iss = status_of(lg, cid)
        if s == "flag":
            d.rectangle([x - 2, 82, x + iw + 1, 84 + ih + 1], outline=RED, width=4)
        e = lg["cuts"].get(cid, {})
        d.text((x, 84 + ih + 6), f"{cid}　{c['room']}　{RZ.DIR_JA[c['dir']]}向き　レンズ {e.get('lens', '')}mm（水平 {e.get('hfov', 0):.0f}°）", font=font(18), fill=INK)
        d.text((x, 84 + ih + 30), "見えるもの：" + c["look"], font=font(16), fill=SUB)
        yy = 84 + ih + 52
        if c.get("alt"):
            for ln in wrap(d, "位置：" + c["alt"], font(13), iw)[:3]:
                d.text((x, yy), ln, font=font(13), fill=SUB)
                yy += 16
        if c.get("moved"):
            d.text((x, yy), f"位置：表から {c['moved']['back_mm']}mm 後ろへ", font=font(13), fill=SUB)
            yy += 16
        for ln in wrap(d, "検査：" + ("；".join(iss) if iss else "異常なし"), font(13), iw)[:3]:
            d.text((x, yy), ln, font=font(13), fill=RED if iss else SUB)
            yy += 16
    sh.paste(keyplan(h, Z, lg, zone), (2 * (iw + M) + M, 84))
    y = 84 + ih + cap_h
    for f in fz:
        d.text((M, y), f"{f['id']}（{f['kind']}{'・要施主確認' if f.get('confirm') else ''}）{f['text']}", font=font(16), fill=FIND_COL.get(f["kind"], INK))
        y += 24
    return sh


def main():
    Z = RZ.load()
    RZ._CUTS.update(Z["cuts"])
    lg = RZ.read_log()
    h = House(ROOT)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    for old in OUTDIR.glob("*.jpg"):
        old.unlink()
    n = 0
    for fl in ("1F", "2F"):
        if not all(RZ.jpg_path(c).exists() for c, v in Z["cuts"].items() if v["floor"] == fl):
            print(f"{fl}: 画像がそろっていないのでモンタージュは作らない")
            continue
        m = montage(fl, Z, lg)
        m.save(MONTAGE_DIR / f"contact_zones_{fl}.jpg", "JPEG", quality=85, optimize=True)
        n += 1
        for zone in sorted({v["zone"] for v in Z["cuts"].values() if v["floor"] == fl}):
            zone_sheet(h, Z, lg, zone).save(OUTDIR / f"{zone}.jpg", "JPEG", quality=82, optimize=True)
            n += 1
    print("sheets:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
