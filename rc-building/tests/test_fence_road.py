"""v4.21 塀線の修正・道路/歩道・Dotcon+・植栽・給排水の受け入れ試験。

    python3 tests/test_fence_road.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from shapely.geometry import Point, Polygon

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import house_legal  # noqa: E402
import house_sheets as hs  # noqa: E402
from house import House  # noqa: E402

_C = {}


def _get():
    if not _C:
        h = House(ROOT)
        rows, sm, _ = house_legal.checks(h)
        _C.update(h=h, sm=sm, a02x=hs.site_integrated(h, "A-02X", sm))
    return _C["h"], _C["sm"], _C["a02x"]


def test_fence_vertices_and_band_area():
    h, _, _ = _get()
    assert [tuple(p) for p in h.fence_line_pts] == [(-31444, 29585), (22000, 27970), (28110, 20930), (23070, -31175)]
    assert abs(h.fence_poly.area / 1e6 - 2426.4) < 8
    assert abs(h.fence_band.area / 1e6 - 203.2) < 5, h.fence_band.area / 1e6
    assert abs(h.site.area / 1e6 - 2629.64) < 0.05            # 敷地は変えない
    assert h.fence_poly.is_valid and h.site.contains(h.fence_poly.buffer(-1))


def test_gate_line_east_end():
    h, _, _ = _get()
    xs = [c[0] for ln in h.fence_lines for c in ln.coords if abs(c[1] - h.y_gate) < 1]
    assert abs(max(xs) - 23417) < 30, max(xs)


def test_fence_inside_poly_and_flap():
    h, _, _ = _get()
    for ln in h.fence_lines:
        assert h.fence_poly.buffer(5).contains(ln)
    for p in h.flap:
        assert h.fence_poly.buffer(5).contains(Point(p)), p


def test_road_color_and_layers():
    h, _, sh = _get()
    from cadlib import LAYERS
    assert h.roads["color"] == "#333333"
    assert "A-ROAD-CW" in LAYERS and "A-ROAD-SW" in LAYERS
    for lay in ("A-ROAD-CW", "A-ROAD-SW"):
        es = [e for e in sh.msp if e.dxf.layer == lay and e.dxftype() == "LWPOLYLINE"]
        assert es, lay
        assert all(e.dxf.get("true_color") == 0x333333 for e in es), lay
    hat = [e for e in sh.msp if e.dxf.layer in ("A-ROAD-CW", "A-ROAD-SW") and e.dxftype() == "HATCH"]
    assert hat and all(e.dxf.get("true_color") == 0x333333 for e in hat)


def test_roads_not_overlapping_site():
    h, _, _ = _get()
    for name in ("north", "east", "south"):
        cw = Polygon(h.roads[name]["cw"])
        assert cw.intersection(h.site).area < 2e6, (name, cw.intersection(h.site).area)   # 敷地内にはほぼ入らない（2m²未満の端の誤差）


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            n += 1
            print("ok", k)
    print(f"{n} tests passed")
