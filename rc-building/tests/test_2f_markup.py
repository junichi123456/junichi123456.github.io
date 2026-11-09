"""v4.28（8.webp）2階の組み替えと足元灯の試験。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import furniture as FU
import house_legal as HL
import lighting as LG
import performance as PF
from house import House

_H = None


def house():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def _room(h, name, fl="2F"):
    return [r for r in h.rooms if r.floor == fl and r.name == name][0]


def test_room_areas():
    h = house()
    exp = {"居室E": 19.63, "収納（居室E）": 2.17, "脱衣所": 7.02, "シャワー": 9.46, "トイレ": 6.04, "収納（トイレ）": 1.44, "廊下": None,
           "収納（居室B）": 1.23, "収納（居室C）": 1.29, "主寝室": 34.52, "WIC（主寝室）": 22.32}
    for n, a in exp.items():
        if a is not None:
            assert abs(_room(h, n).area - a) < 0.05, (n, _room(h, n).area)
    assert "ファミリークローゼット" not in [r.name for r in h.rooms if r.floor == "2F"]


def test_wc_and_dressing_constraints():
    h = house()
    wc, dr = _room(h, "トイレ"), _room(h, "脱衣所")
    assert wc.area <= 6.1 and (wc.rect[2] - wc.rect[0]) <= 1800
    assert abs((dr.rect[3] - dr.rect[1]) - 1800) < 1 and abs(dr.rect[1] - wc.rect[1]) < 1       # 奥行 1.8m・戸の面（y13,800）が揃う
    wall = [w for w in h.walls if w.floor == "2F" and w.axis == "x" and w.c == 13750][0]
    assert sorted((o.u0, o.u1) for o in wall.openings) == [(7000, 7800), (10700, 11500)]
    cor = [r for r in h.rooms if r.floor == "2F" and r.name == "廊下" and r.rect[0] == 6250 and r.rect[1] == 12250][0]
    assert cor.rect[3] - cor.rect[1] >= 1300


def test_red_lines_standard_thickness():
    h = house()
    assert not [w for w in h.walls if w.floor == "2F" and w.extra]              # 赤線は増し打ちではなく標準厚 t250
    x3 = h.rc_walls["2F"]["X3"]
    assert any((o.u0, o.u1) == (8350, 9150) for o in x3.openings)                # WIC の扉
    y3 = h.rc_walls["2F"]["Y3"]
    assert not any(o.u0 == 16500 for o in y3.openings)                           # 主寝室↔WIC の扉は撤去


def test_window_aw9_and_daylight():
    h = house()
    r = [x for x in HL.window_table(h) if x["room"] == "居室E"][0]
    assert abs(r["glass"] - 1.28) < 0.01 and r["eff"] >= r["need"]


def test_structure_2f():
    h = house()
    wq = HL.wall_quantity(h)
    assert wq[("2F", "X方向")][1] >= 12 and wq[("2F", "Y方向")][1] >= 12
    se = PF.seismic(h)
    assert max(v["ecc"] for v in se["stories"].values()) <= 0.15


def test_furniture_ok():
    h = house()
    assert FU.check(h, FU.items(h)) == []


def test_footlines():
    h = house()
    its = FU.items(h)
    fp, mk = LG.footlines(h, its)
    fc = h.spec["lighting"]["foot_line"]
    assert fp and mk
    assert {d["floor"] for d in fp} == {"1F", "2F"}
    for d in fp:
        assert d["p0"][2] == h.fl[d["floor"]] + 300 and d["lm_per_m"] in (fc["base_lm_per_m"], fc["warn_lm_per_m"])
        assert 20 <= d["lm_per_m"] <= 50
    # 脱衣所・トイレの戸口前に警告区間がある
    assert any(m["kind"] == "戸口" and m["floor"] == "2F" and abs(m["p"][1] - 13750) < 1 for m in mk)
    assert any(d["warn"] and d["floor"] == "2F" for d in fp)
    # 床面照度 1〜3 lx 程度（壁から 0.5〜0.7m）
    assert 1.0 <= LG.footline_floor_lx(fc, fc["base_lm_per_m"], 700) and LG.footline_floor_lx(fc, fc["warn_lm_per_m"], 500) <= 3.5
    # DALI: 足元灯グループが F チャネルで入る
    gr = LG.dali_groups(h, its)
    assert any(g["ch"] == "F" and g["name"].endswith("足元") for g in gr)
