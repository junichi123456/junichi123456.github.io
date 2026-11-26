"""v4.40 長期優良住宅の不足 4 点（W/C・給水経路・汚水の建物出口・点検経路）・熱橋込み外皮・維持保全計画の受け入れ試験。

    python3 tests/test_long_life.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from shapely.geometry import LineString, Point, box as sbox  # noqa: E402

import furniture as FU  # noqa: E402
import house_legal  # noqa: E402
import lighting as LT  # noqa: E402
import maintenance as MT  # noqa: E402
import performance as PF  # noqa: E402
from house import House  # noqa: E402

_C = {}


def _get():
    if not _C:
        h = House(ROOT)
        rows, sm, _ = house_legal.checks(h)
        its = FU.items(h)
        _C.update(h=h, rows=rows, sm=sm, its=its)
    return _C


def test_concrete_spec():
    st = _get()["h"].spec["structure"]
    assert st["concrete"]["wc_max"] <= 0.50 and st["concrete"]["unit_water_max"] <= 185
    mn = dict(wall_in=40, wall_out=50, slab=30, roof_top=40, earth_contact=50, foundation=70)
    for k, v in mn.items():
        assert st["cover_min"][k] >= v and st["cover_design"][k] == st["cover_min"][k] + 10, k


def test_pipes_not_under_concrete():
    h = _get()["h"]
    cv = MT.cover_check(h)
    assert cv["water_under"] < 1 and cv["sewer_under"] < 1 and abs(cv["sleeve_m"] - 1722) < 10, cv
    wl, sl = h.pipes["water"][0], h.pipes["sewer"][0]
    assert wl.intersection(h.dotcon).length == 0 and sl.intersection(h.dotcon).length == 0
    assert abs(wl.length / 1000 - 29.8) < 0.1
    keys = ("目隠し壁", "ゴミ置き目隠し壁", "ゴミ収集ボックス", "外部階段", "玄関ポーチ")
    for b in h.boxes:
        if b.level == "EXT" and any(k in (b.tag or "") for k in keys):
            r = sbox(b.x0, b.y0, b.x1, b.y1)
            assert r.distance(wl) >= 300 and r.distance(sl) >= 300, (b.tag, r.distance(wl), r.distance(sl))
    assert wl.distance(sl) >= 1000
    assert h.pipe_strip.area > 0 and h.pipe_strip_fc.area > 0
    assert abs(h.ext_storage["dotcon_area_parking"] - 200.0) < 0.05 and abs(h.ext_storage["dotcon_area"] - 814.94) < 0.05
    assert h.farm[0] == 15200 and h.farm[2] == 24200


def test_sewer_exit():
    h = _get()["h"]
    sw = h.spec["utilities"]["sewer"]
    assert sw["line"][0] == [7000, -245] and sw["exit_invert"] >= 80
    pr = MT.sewer_profile(h)
    inv = [p[3] for p in pr]
    assert all(a > b for a, b in zip(inv, inv[1:])) and abs(inv[-1] + 319.4) < 1, inv
    assert abs(MT.final_invert_15(h) + 433.5) < 2
    s = h.pipes["sewer"][0]
    d = [s.project(Point(m)) for m in h.sewer_manholes]
    assert all(b - a <= 15000 + 1 for a, b in zip(d, d[1:]))
    assert Point(h.sewer_final).distance(Point(h.storm_final)) > 1000
    assert abs(MT.sewer_length_m(h) - 32.4) < 0.1


def test_pit_access():
    c = _get()
    h, its = c["h"], c["its"]
    ll = h.spec["long_life"]
    ac = MT.access(h)
    assert ac["ok"] and ac["connected"] and (ac["manways"], ac["hatches"], ac["ch"], ac["ps"], ac["co"]) == (12, 3, 3, 3, 8)
    assert not any("点検" in (o.label or "") for o in h.rc_walls["FDN"]["S"].openings)
    assert FU.check(h, its) == []
    zones = [z for _, z in FU.door_zones(h, "1F")]
    for hid, room, r, _ in ll["floor_hatches"]:
        p = sbox(*r)
        rp = FU.room_polys(h, "1F", room)
        assert any(q.buffer(1).contains(p) for q in rp), hid
        assert not any(i.floor == "1F" and i.kind != "ps" and i.z0 < h.fl["1F"] + 1900 and i.poly().intersects(p) for i in its), hid
        assert not any(sbox(*rt).intersects(p) for _, rt, _, _ in h.equipment), hid
        assert not any(z.intersects(p) for z in zones), hid
    # 同じ壁の人通口・スリーブどうし 450 以上
    items = [(f"人通口 {m[0]}", m[1], m[2], m[3]) for m in ll["manways"]] + [(s[0], s[1], s[2] - s[3] / 2, s[2] + s[3] / 2) for s in ll["sleeves"] if s[1] != "S"]
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a[1] == b[1]:
                gap = max(a[2], b[2]) - min(a[3], b[3])
                assert gap >= 450 or gap < 0 and False, (a, b, gap)


def test_hatch_clearance():
    c = _get()
    h, its = c["h"], c["its"]
    ll = h.spec["long_life"]
    lns = LT.lines(h, its)
    dls = LT.downlights(h, its, lns)
    for hid, room, r, _ in ll["ceiling_hatches"]:
        p = sbox(*r)
        for d in dls:
            if d["floor"] == "1F":
                assert p.distance(Point(d["p"][0], d["p"][1])) >= 300, (hid, d["room"])
        for l in lns:
            if l["floor"] == "1F":
                assert p.distance(LineString([l["p0"][:2], l["p1"][:2]])) >= 300, (hid, l["id"])
    pcs, _ = LT.footlines(h, its)
    for hid, room, r, _ in ll["floor_hatches"]:
        p = sbox(*r)
        for f in pcs:
            if f["floor"] == "1F":
                assert p.distance(LineString([f["p0"][:2], f["p1"][:2]])) >= 300, (hid, f["id"])


def test_envelope_tb():
    h = _get()["h"]
    tb, ea, be = PF.envelope_tb(h), PF.eta_ac(h), PF.bei_estimate(h)
    assert abs(tb["UA_tb"] - 0.2392) < 0.001 and tb["UA_tb"] <= 0.26      # v4.41: 0.2377→0.2403（外皮が縮み、熱橋の割合が増える）。等級7（0.26）は維持
    assert abs(ea["value"] - 0.531) < 0.01 and abs(be["bei"] - 0.3165) < 0.005      # v4.42: 居室E の西窓廃止で UA 0.2403→0.2392・ηAC 0.546→0.531・BEI 0.317→0.3165。v4.41: ηAC 0.53→0.55（居室D の窓縮小・居室E の窓が西へ）、BEI 0.310→0.317
    assert abs(be["E_design"] - 121530) < 200 and abs(be["E_ref"] - 384027) < 500
    assert abs(PF.energy(h, PF.heat_load(h))["total"] - 19948.46) < 1


def test_maintenance_plan():
    h = _get()["h"]
    p = MT.plan(h)
    assert p["years"] == 30 and p["max_interval"] <= 10 and p["total"] == 4920
    assert p["by_class"] == {"構造": 260, "雨水": 1906, "給排水": 284, "任意": 2320} and p["required"] == 2450
    assert abs(p["monthly_all"] - 13.67) < 0.01 and abs(p["monthly_required"] - 7.22) < 0.01


def test_legal_long_life():
    rows = _get()["rows"]
    ll = [r for r in rows if r["cat"] == "長期優良"]
    assert len(ll) == 13
    ok = {0, 1, 3, 4, 5, 6, 10}
    for i, r in enumerate(ll):
        assert r["result"] == (house_legal.OK if i in ok else house_legal.CHK), (i, r["item"], r["result"])
    assert len(rows) == 149 and sum(r["result"] == house_legal.CHK for r in rows) == 40 and not any(r["result"] == house_legal.NG for r in rows)


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
