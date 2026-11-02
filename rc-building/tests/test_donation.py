"""v4.22 塀外の帯を市へ割譲（歩行者専用道路）の受け入れ試験。

    python3 tests/test_donation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from shapely.geometry import Point, Polygon

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import house_legal  # noqa: E402
import house_sheets as hs  # noqa: E402
from cadlib import LAYERS  # noqa: E402
from house import House  # noqa: E402
from test_site_integrated import INNER, TITLE, paper_boxes  # noqa: E402

_C = {}


def _get():
    if not _C:
        h = House(ROOT)
        rows, sm, _ = house_legal.checks(h)
        _C.update(h=h, rows=rows, sm=sm, a02y=hs.donation_sheet(h, "A-02Y"))
    return _C["h"], _C["rows"], _C["sm"], _C["a02y"]


def test_areas_add_up():
    h, _, sm, _ = _get()
    assert abs(sm["site_area"] - 2426.42) < 0.05
    assert abs(h.site_gross.area / 1e6 - 2629.64) < 0.05
    assert abs(h.donation_poly.area / 1e6 - 203.2) < 5
    assert abs(h.site.area + h.donation_poly.area - h.site_gross.area) < 1e6 * 0.1     # 新＋寄付地＝旧（細片の捨てを許容）
    assert h.fence_band.equals(h.donation_poly)


def test_donation_not_overlapping_north_sidewalk():
    h, _, _, _ = _get()
    sw = h.roads["north"].get("sw")
    assert sw
    assert Polygon(sw).intersection(h.donation_poly).area < 1e4       # 0.01m² 未満


def test_coverage_far_values():
    _, rows, sm, _ = _get()
    assert abs(sm["coverage"] * 100 - 14.34) < 0.01, sm["coverage"]
    assert abs(sm["far"] * 100 - 27.45) < 0.01, sm["far"]
    ng = [r for r in rows if r["result"] == house_legal.NG]
    assert not ng, ng
    items = {r["item"]: r for r in rows}
    for k in ("寄付（割譲）手続き", "接道（東・帯の扱い）"):
        assert items[k]["result"] == house_legal.CHK, k


def test_a02y_exists_and_fits():
    h, _, _, sh = _get()
    assert sh.number == "A-02Y"
    used = {e.dxf.layer for e in sh.msp}
    assert "A-DONATE" in used and "A-DONATE-BND" in used and not (used - set(LAYERS))
    bad = []
    for e, ly, (x0, y0, x1, y1) in paper_boxes(sh):
        if x0 < INNER[0] - 0.01 or y0 < INNER[1] - 0.01 or x1 > INNER[2] + 0.01 or y1 > INNER[3] + 0.01:
            bad.append((ly, e.dxftype(), round(x0), round(y0), round(x1), round(y1), "枠外"))
        elif x0 < TITLE[2] and x1 > TITLE[0] and y0 < TITLE[3] and y1 > TITLE[1]:
            bad.append((ly, e.dxftype(), round(x0), round(y0), round(x1), round(y1), "表題欄"))
    assert not bad, bad[:8]


def test_a02y_in_cover_body():
    src = (ROOT / "src" / "build.py").read_text(encoding="utf-8")
    assert src.index("A-02X") < src.index("A-02Y")


def test_fixtures_inside_new_site():
    h, _, _, _ = _get()
    inner = h.site.buffer(5)
    for p in h.plants:
        assert inner.contains(Point(p["xy"])), p["id"]
    for _, p in h.ext_lights:
        assert inner.contains(Point(p)), p
    for z in (h.dotcon, h.dotcon_garden, h.tank and Polygon([(h.tank[0], h.tank[1]), (h.tank[2], h.tank[1]), (h.tank[2], h.tank[3]), (h.tank[0], h.tank[3])])):
        assert inner.contains(z)
    assert not h.donation_poly.buffer(-1000).intersects(Polygon([(h.tank[0], h.tank[1]), (h.tank[2], h.tank[1]), (h.tank[2], h.tank[3]), (h.tank[0], h.tank[3])]))
    for p in h.plants:
        assert not h.donation_poly.buffer(-1000).contains(Point(p["xy"]))


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            n += 1
            print("ok", k)
    print(f"{n} tests passed")
