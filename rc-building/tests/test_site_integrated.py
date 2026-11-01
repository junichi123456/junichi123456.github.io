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

# 変更前（v4.19）の既存図のエンティティ数。A-02X の追加で変わってはならない。
BASE_COUNTS = {"A-01": 261, "A-02": 202, "A-02D": 125}

INNER = (10.0, 10.0, 410.0, 287.0)       # 内枠（用紙mm）
TITLE = (220.0, 10.0, 410.0, 48.0)       # 表題欄
SKIP = ("G-FRAME", "G-TITLE")

_C = {}


def _get():
    if not _C:
        h = House(ROOT)
        rows, sm, _ = house_legal.checks(h)
        _C.update(h=h, sm=sm, sh=hs.site_integrated(h, "A-02X", sm))
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
    for need in ("A-CUT", "A-FENCE", "A-PAVE", "A-SITE", "A-ROOM", "E-EXLT", "A-LEGAL"):
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
    got = {"A-01": len(list(hs.site_plan(h, "A-01", sm).msp)),
           "A-02": len(list(hs.exterior_plan(h, "A-02").msp)),
           "A-02D": len(list(hs.gate_detail(h, "A-02D").msp))}
    assert got == BASE_COUNTS, got


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            n += 1
            print("ok", k)
    print(f"{n} tests passed")
