"""照明の再構成（v4.17）の受け入れ試験。

    python3 tests/test_lighting.py        （pytest があれば pytest tests/ でもよい）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from house import House  # noqa: E402

_H = None


def house():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def test_downlight_is_weak():
    sp = house().spec
    assert sp["lighting"]["downlight"]["max_lm"] <= 300
    assert sp["interior_cg"]["downlight_ratio"] <= 0.35


def test_hex_not_adopted():
    hx = house().spec["lighting"]["hex"]
    assert hx["tested"] is True and hx["adopted"] is False


def test_foot_height_spec():
    ft = house().spec["lighting"]["foot"]
    assert ft["height_from_tread"] == 300 and ft["every_steps"] == 2


def test_kitchen_open_spec():
    ko = house().spec["kitchen_open"]
    assert ko["knife_z"] >= 1550 and ko["pot_rack"] is False


def _its():
    import furniture
    return furniture.items(house())


def test_every_room_has_line_and_enough_lux():
    import lighting as L
    h = house()
    its = _its()
    lns = L.lines(h, its)
    skip = h.spec["lighting"]["no_line_rooms"]
    for row in L.illuminance_table(h, its):
        if any(k in row["room"] for k in skip):
            continue
        assert row["n"] >= 1, row["room"]
        assert row["E"] >= 0.9 * row["target"], (row["room"], row["E"], row["target"])
    assert all(l["lm_per_m"] in h.spec["lighting"]["line"]["classes_lm_per_m"] + [1500, 1000] for l in lns)


def test_downlight_positions():
    import lighting as L
    from shapely.geometry import LineString, Point, box as sbox
    h = house()
    its = _its()
    lns = L.lines(h, its)
    dl = L.downlights(h, its, lns)
    cfg = h.spec["lighting"]["downlight"]
    assert len(dl) > 40
    holes = [sbox(*s.hole) for s in h.stairs]
    for d in dl:
        x, y, z = d["p"]
        room = next(r for r in h.rooms if r.floor == d["floor"] and r.name == d["room"] and r.rect[0] <= x <= r.rect[2] and r.rect[1] <= y <= r.rect[3])
        x0, y0, x1, y1 = room.rect
        assert min(x - x0, x1 - x, y - y0, y1 - y) >= cfg["min_from_wall"] - 1e-6
        for l in lns:
            if l["code"] == d["code"] and l["floor"] == d["floor"] and l["kind"] == "line":
                assert LineString([l["p0"][:2], l["p1"][:2]]).distance(Point(x, y)) >= cfg["min_from_line"] - 1e-6
        if d["floor"] == "1F":
            assert not any(hh.contains(Point(x, y)) for hh in holes)


def test_footlights_300():
    import lighting as L
    h = house()
    ft = L.footlights(h)
    assert len(ft) == 18
    for s in h.stairs:
        mine = [f for f in ft if f["stair"] == s.name]
        assert sum(f["flight"] == "下" for f in mine) == 4 and sum(f["flight"] == "上" for f in mine) == 4 and sum(f["flight"] == "踊場" for f in mine) == 1
    for f in ft:
        assert abs(f["p"][2] - L.tread_top(h, f) - 300) <= 1, f
        x, y, z = f["p"]
        # LGS の壁面上（RC 壁の上にない）
        hit = [b for b in h.boxes if b.x0 - 1 <= x <= b.x1 + 1 and b.y0 - 1 <= y <= b.y1 + 1 and b.z0 <= z <= b.z1]
        assert hit and all(b.mat == "lgs" for b in hit), (f, hit)


def test_channels_schedule():
    import lighting as L
    sp = house().spec
    c = L.channels(sp, 22.5)
    assert c["L"][1] == 0 and c["D"][0] == 2200 and c["F"][1] > 0
    c = L.channels(sp, 10)
    assert c["L"][1] == 100 and c["D"][1] == 0 and c["F"][1] == 0
    assert sp["smart"]["lighting_schedule"][0] == [0, 2200, 10]       # 既存の全体スケジュールは変えない


def test_hex_not_in_model():
    import lighting as L
    assert not any("hex" in str(k).lower() or "六角" in str(k) for k in L.CODE)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for f in fns:
        f()
        print("ok", f.__name__)
