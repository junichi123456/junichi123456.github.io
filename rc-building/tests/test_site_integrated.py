"""A-02X 総合配置・外構統合図の受け入れ試験（House を1回だけ構築し、build 全体は回さない）。

    python3 tests/test_site_integrated.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import house_legal  # noqa: E402
import house_sheets as hs  # noqa: E402
from cadlib import LAYERS, _text_width  # noqa: E402
from house import House  # noqa: E402

# 既存図のエンティティ数（v4.19 から v4.21 の変更ごとに意図して更新）。
# v4.25: A-01 272→273・A-02 405→406・A-07 221→222・A-09 278→289（玄関土間の縮小・ベンチ移設・間仕切りの変更が反映。意図した変更）
BASE_COUNTS = {"A-01": 273, "A-02": 406, "A-02D": 125,
               # v4.23 段階3: A-02 は 417→405（貯留槽の移設で西系統の雨水管が短くなり、流れ矢印が12個減った。意図した変更）
               # v4.23 段階1: 破壊禁止の対象に加えた（v4.22 の現在数。A-02X・A-03 は増分を test_lifeline で固定）
               "A-02Y": 164, "A-04": 382, "A-05": 98, "A-06": 212, "A-07": 222, "A-08": 96, "A-09": 289, "A-10": 294, "S-01": 153, "S-02": 118}      # v4.21 段階1: 道路・歩道の図形を追加（A-01 +8、A-02 +11、段階3〜4で植栽・給排水・右欄の表を追加 A-02 403）

INNER = (10.0, 10.0, 410.0, 287.0)       # 内枠（用紙mm）
TITLE = (220.0, 10.0, 410.0, 48.0)       # 表題欄
SKIP = ("G-FRAME", "G-TITLE")

_C = {}


def _get():
    if not _C:
        h = House(ROOT)
        rows, sm, wq = house_legal.checks(h)
        _C.update(h=h, sm=sm, wq=wq, sh=hs.site_integrated(h, "A-02X", sm))
    return _C["h"], _C["sm"], _C["sh"]


def paper_boxes(sh):
    """(entity, layer, (x0, y0, x1, y1)) 用紙mm。"""
    S = sh.S
    out = []
    for e in sh.msp:
        ly, k = e.dxf.layer, e.dxftype()
        if ly in SKIP:
            continue
        pts = []
        if k == "LINE":
            pts = [e.dxf.start, e.dxf.end]
        elif k == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points()]
        elif k == "CIRCLE":
            c, r = e.dxf.center, e.dxf.radius
            pts = [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
        elif k == "HATCH":
            for path in e.paths:
                pts += [(v[0], v[1]) for v in getattr(path, "vertices", [])]
        elif k == "TEXT":
            al, p1, _ = e.get_placement()
            hp = e.dxf.height / S
            w = _text_width(e.dxf.text, hp)
            name = al.name
            ox, oy = (p1[0] - 0) / 1, p1[1]
            if "CENTER" in name:
                dx0, dx1 = -w / 2, w / 2
            elif "RIGHT" in name:
                dx0, dx1 = -w, 0
            else:
                dx0, dx1 = 0, w
            if name.startswith("TOP"):
                dy0, dy1 = -hp, 0
            elif name.startswith("MIDDLE"):
                dy0, dy1 = -hp / 2, hp / 2
            else:
                dy0, dy1 = 0, hp
            rot = math.radians(e.dxf.get("rotation", 0))
            for dx, dy in ((dx0, dy0), (dx1, dy0), (dx0, dy1), (dx1, dy1)):
                pts.append((ox + (dx * math.cos(rot) - dy * math.sin(rot)) * S,
                            oy + (dx * math.sin(rot) + dy * math.cos(rot)) * S))
        if not pts:
            continue
        xs = [(p[0] - sh.ox) / S for p in pts]
        ys = [(p[1] - sh.oy) / S for p in pts]
        out.append((e, ly, (min(xs), min(ys), max(xs), max(ys))))
    return out


def test_layers():
    _, _, sh = _get()
    used = {e.dxf.layer for e in sh.msp}
    for need in ("A-CUT", "A-FENCE", "A-PAVE", "A-SITE", "A-ROOM", "E-EXLT", "A-LEGAL", "A-ROAD-CW", "A-ROAD-SW", "E-PLNT", "E-WATER", "E-SEWER"):
        assert need in used, f"レイヤー {need} の図形がない"
    assert not (used - set(LAYERS)), f"未定義レイヤー {used - set(LAYERS)}"


def test_inside_frame_and_clear_of_title():
    _, _, sh = _get()
    bad = []
    for e, ly, (x0, y0, x1, y1) in paper_boxes(sh):
        if x0 < INNER[0] - 0.01 or y0 < INNER[1] - 0.01 or x1 > INNER[2] + 0.01 or y1 > INNER[3] + 0.01:
            bad.append((ly, e.dxftype(), round(x0), round(y0), round(x1), round(y1), "枠外"))
        elif x0 < TITLE[2] and x1 > TITLE[0] and y0 < TITLE[3] and y1 > TITLE[1]:
            bad.append((ly, e.dxftype(), round(x0), round(y0), round(x1), round(y1), "表題欄"))
    assert not bad, bad[:8]


def _plan_circles(sh, layer, r_paper):
    """図面部（用紙 x<256）にある、半径 r_paper(mm) の円の数。右欄の凡例見本は数えない。"""
    n = 0
    for e in sh.msp:
        if e.dxftype() == "CIRCLE" and e.dxf.layer == layer and abs(e.dxf.radius / sh.S - r_paper) < 1e-6:
            if (e.dxf.center[0] - sh.ox) / sh.S < 256:
                n += 1
    return n


def test_number_table_matches_bubbles():
    _, _, sh = _get()
    rows = len(sh.last_table_rows) - 1               # 見出し行を除く
    assert rows == _plan_circles(sh, "A-SYMB", 1.5) and rows >= 12, (rows, _plan_circles(sh, "A-SYMB", 1.5))


def test_exterior_light_count():
    h, _, sh = _get()
    assert _plan_circles(sh, "E-EXLT", 0.6) == len(h.ext_lights)


def test_existing_sheets_unchanged():
    h, sm, _ = _get()
    from sheetlib import fittings_sheet
    wall_rows = [["階", "方向", "耐力壁長さ", "壁量", "判定"]]
    for (f, d), (L, q) in sorted(_C["wq"].items()):
        wall_rows.append([f, d, f"{L:.1f} m", f"{q:.1f} cm/m²", "≧12 適合" if q >= 12 else "不足"])
    wall_rows.append(["", "", "壁厚", f"{h.t / 10:.0f} cm", "≧15 適合"])
    got = {"A-01": len(list(hs.site_plan(h, "A-01", sm).msp)),
           "A-02": len(list(hs.exterior_plan(h, "A-02").msp)),
           "A-02D": len(list(hs.gate_detail(h, "A-02D").msp)),
           "A-02Y": len(list(hs.donation_sheet(h, "A-02Y").msp)),
           "A-04": len(list(hs.floor_plan(h, "2F", "A-04").msp)),
           "A-05": len(list(hs.roof_plan(h, "A-05").msp)),
           "A-06": len(list(hs.elevations(h, "A-06").msp)),
           "A-07": len(list(hs.building_sections(h, "A-07").msp)),
           "A-08": len(list(hs.site_sections(h, "A-08").msp)),
           "A-09": len(list(fittings_sheet(h, "A-09").msp)),
           "A-10": len(list(hs.openings_smoke_sheet(h, "A-10").msp)),
           "S-01": len(list(hs.wall_plan(h, "S-01", wall_rows).msp)),
           "S-02": len(list(hs.details(h, "S-02").msp))}
    assert got == BASE_COUNTS, got


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            n += 1
            print("ok", k)
    print(f"{n} tests passed")
