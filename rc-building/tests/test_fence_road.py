"""v4.21 塀線の修正・道路/歩道・Dotcon+・植栽・給排水の受け入れ試験。

    python3 tests/test_fence_road.py
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


def _zones(h):
    return {k: Polygon(z) for k, z in h.spec["exterior"]["dotcon_zones"].items()}


def test_dotcon_zones_inside_fence():
    h, _, _ = _get()
    inner = h.fence_poly.buffer(-h.fence_t)
    for k, z in _zones(h).items():
        assert z.difference(inner).area < 0.05e6, (k, z.difference(inner).area / 1e6)     # 端の誤差 0.05m² 未満
    for g in (h.dotcon_garden, h.dotcon, h.dotcon_farm, h.approach.intersection(inner)):
        assert g.difference(inner).area < 1, g.difference(inner).area
    ne = _zones(h)["north_east"]
    assert abs(ne.area / 1e6 - 122.4) < 1.0, ne.area / 1e6
    assert abs(h.ext_storage["dotcon_area"] - 828) < 3, h.ext_storage["dotcon_area"]       # 旧 838m²


def test_dotcon_zones_no_overlap():
    h, _, _ = _get()
    zs = list(_zones(h).values())
    assert zs[0].intersection(zs[1]).area < 1
    bld = Polygon([(0, 0), (h.W, 0), (h.W, h.D), (0, h.D)]).buffer(1000)            # 建物＋防草砂利帯 1.0m
    for z in zs:
        assert bld.intersection(z).area < 1
        assert z.intersection(h.dotcon_farm).area < 1 and z.distance(h.dotcon_farm) > 150
        assert z.intersection(h.dotcon).area < 1 and z.intersection(h.approach).area < 1


def test_fixtures_inside_fence():
    h, _, _ = _get()
    inner = h.fence_poly.buffer(-h.fence_t)
    for p in h.bollards + [tuple(c) for c in h.spec["security"]["cameras"]] + [p for _, p in h.ext_lights]:
        assert inner.contains(Point(p)), p
    assert len(h.bollards) == 3 and len(h.spec["security"]["cameras"]) == 8 and len(h.ext_lights) == 12


def _no_plant_zones(h):
    """植えない区域: Dotcon+・アプローチ・駐車場・菜園・貯留槽・塀外の帯・北の2H範囲・建物まわり1.0m・（段階4で）配管±1.0m。"""
    bld = Polygon([(0, 0), (h.W, 0), (h.W, h.D), (0, h.D)]).buffer(h.spec["planting"]["rules"]["gravel_band"])
    tk = h.tank
    zones = {"dotcon_garden": h.dotcon_garden, "parking": h.dotcon, "approach": h.approach, "farm": h.dotcon_farm,
             "tank": Polygon([(tk[0], tk[1]), (tk[2], tk[1]), (tk[2], tk[3]), (tk[0], tk[3])]), "band": h.fence_band,
             "cliff": h.cliff_zone, "building+gravel": bld}
    if hasattr(h, "pipe_zone"):
        zones["pipes"] = h.pipe_zone
    return zones


def test_planting_rules():
    h, _, _ = _get()
    r = h.spec["planting"]["rules"]
    assert abs(h.cliff_zone.area / 1e6 - 748) < 3, h.cliff_zone.area / 1e6
    pg = h.pergola
    bld = Polygon([(0, 0), (h.W, 0), (h.W, h.D), (0, h.D)])
    ids = [p["id"] for p in h.plants]
    assert ids == ["T1", "T2", "M1", "M2", "M3"]
    zones = _no_plant_zones(h)
    for p in h.plants:
        pt, rad = Point(p["xy"]), p["crown"] / 2
        assert h.fence_poly.contains(pt)
        assert h.fence_poly.boundary.distance(pt) >= r["tree_fence_min"], p["id"]
        assert bld.distance(pt) >= r["tree_building_min"], p["id"]
        for k, z in zones.items():
            assert not z.intersects(pt.buffer(rad)), (p["id"], k)
        if pg[0] - 4000 <= p["xy"][0] <= pg[2] + 4000 and p["xy"][1] < pg[1]:       # パーゴラの南: 冬至の影が先端パネルに届かない
            assert p["xy"][1] + rad + p["h"] * r["shadow_ratio"] <= pg[1], p["id"]
    sl = h.shrub["line"]
    for k, z in zones.items():
        assert not z.intersects(sl), ("S1", k)
    for (xy, rad) in h.groundcover:
        for k, z in zones.items():
            assert z.intersection(Point(xy).buffer(rad)).area < 1, ("G", k)


def test_utilities_layout():
    h, _, _ = _get()
    from shapely.geometry import LineString
    bld = Polygon([(0, 0), (h.W, 0), (h.W, h.D), (0, h.D)])
    for key, gs in h.pipes.items():
        for g in gs:
            assert h.site.buffer(5).contains(g), key
            if key == "sewer":
                assert g.distance(bld) > 1000, key                      # 汚水管は建物の砂利帯の外（雨水は縦樋の足元から出る）
    water_end = Point(h.pipes["water"][0].coords[-1])
    assert abs(water_end.x - 12600) < 1 and abs(water_end.y + 245) < 1
    assert h.water_meter[1] < h.y_gate                                   # 量水器は門の外（検針で門を開けない）
    sw = h.pipes["sewer"][0]
    assert 50 < sw.length / 1000 < 60, sw.length                         # 建物出口から最終桝まで 約55m
    assert tuple(sw.coords[-1]) == h.sewer_final and tuple(h.pipes["storm_e"][1].coords[-1]) == h.storm_final
    assert Point(h.sewer_final).distance(Point(h.storm_final)) > 1000    # 汚水と雨水は別の最終桝
    # 桝: 15m 以内ごと（汚水）
    d = [sw.project(Point(m)) for m in h.sewer_manholes]
    assert d == sorted(d) and all(b - a <= 15000 + 1 for a, b in zip(d, d[1:])), d
    assert all(sw.distance(Point(m)) < 1 for m in h.sewer_manholes)
    for k, z in (("pipe_zone", h.pipe_zone),):
        for p in h.plants:
            assert not z.intersects(Point(p["xy"]).buffer(p["crown"] / 2)), (k, p["id"])
        assert not z.intersects(h.shrub["line"])
    # 雨水の越流先: 貯留槽 25m³ → 西の浸透桝 2基、東は既存浸透桝 → 雨水最終桝
    assert len(h.storm_pits) == 2 and tuple(h.infil_pits[0]) == tuple(h.pipes["storm_e"][0].coords[-1])


def test_a02_inside_frame_and_labels():
    h, sm, _ = _get()
    import test_site_integrated as T
    sh = hs.exterior_plan(h, "A-02")
    bad = [(ly, e.dxftype(), [round(v) for v in b]) for e, ly, b in T.paper_boxes(sh)
           if b[0] < T.INNER[0] - 0.01 or b[1] < T.INNER[1] - 0.01 or b[2] > T.INNER[2] + 0.01 or b[3] > T.INNER[3] + 0.01
           or (b[0] < T.TITLE[2] and b[2] > T.TITLE[0] and b[1] < T.TITLE[3] and b[3] > T.TITLE[1])]
    assert not bad, bad[:6]
    texts = " ".join(e.dxf.text for e in sh.msp if e.dxftype() == "TEXT")
    assert "植栽" in texts and "勾配" in texts and "未計画" not in texts


def test_a02x_notes():
    h, _, sh = _get()
    texts = " ".join(e.dxf.text for e in sh.msp if e.dxftype() == "TEXT")
    assert "植栽は未計画" not in texts and "仮置き（要確認）" in texts


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            n += 1
            print("ok", k)
    print(f"{n} tests passed")
