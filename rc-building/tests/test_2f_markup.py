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
    # v4.41: 寝室は 4.5〜6 畳（居室E 9.63・主寝室 9.65）。収納・水廻りは北の行の組み替え後の値（ブリーフ 49 章）
    exp = {"書庫": 18.40,  # v4.42: 居室E＋収納（居室E）を一体化
            "脱衣所": 7.06, "シャワー": 9.56, "トイレ": 6.08, "収納（トイレ・主寝室）": 4.56, "廊下": None,
           "収納（居室B）": 3.47, "収納（居室C）": 3.62, "主寝室": 9.65, "WIC（主寝室）": 22.32}
    for n, a in exp.items():
        if a is not None:
            assert abs(_room(h, n).area - a) < 0.05, (n, _room(h, n).area)
    assert "ファミリークローゼット" not in [r.name for r in h.rooms if r.floor == "2F"]


def test_wc_and_dressing_constraints():
    h = house()
    wc, dr = _room(h, "トイレ"), _room(h, "脱衣所")
    assert wc.area <= 6.1 and (wc.rect[2] - wc.rect[0]) <= 1800
    # v4.41: 脱衣所は 1,975×3,575（短辺 ≧1.8m）、戸の面は y13,500 の同一線上（C-N の脱衣所・NE のトイレ）
    assert min(dr.rect[2] - dr.rect[0], dr.rect[3] - dr.rect[1]) >= 1800 and abs(dr.rect[1] - wc.rect[1]) < 1
    walls = [w for w in h.walls if w.floor == "2F" and w.axis == "x" and w.c == 13500]
    assert [sorted((o.u0, o.u1) for o in w.openings) for w in sorted(walls, key=lambda w: w.a)] == [[(7000, 7800)], [(11500, 12300), (13300, 14100), (14600, 15400)]]
    cor = [r for r in h.rooms if r.floor == "2F" and r.name == "廊下" and r.rect[0] == 6250 and r.rect[1] == 12250][0]
    assert cor.rect[3] - cor.rect[1] >= 1200                        # v4.41: 北廊下 1.45→1.2m（壁芯 1.3m。要確認 Q4）


def test_red_lines_standard_thickness():
    h = house()
    assert not [w for w in h.walls if w.floor == "2F" and w.extra]              # 赤線は増し打ちではなく標準厚 t250
    x3 = h.rc_walls["2F"]["X3"]
    assert any((o.u0, o.u1) == (8350, 9150) for o in x3.openings)                # WIC の扉
    y3 = h.rc_walls["2F"]["Y3"]
    assert not any(o.u0 == 16500 for o in y3.openings)                           # 主寝室↔WIC の扉は撤去


def test_window_aw9_and_daylight():
    h = house()
    # v4.42: 居室E は書庫になり西窓 AW-9 は廃止。書庫に窓がなく、2F W 面に u12,900 の窓がない
    assert not [x for x in HL.window_table(h) if x["room"] in ("居室E", "書庫")]
    assert not [o for w in h.walls for o in w.openings if "FIX窓" in o.name and o.u0 == 12900]


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
    assert any(m["kind"] == "戸口" and m["floor"] == "2F" and abs(m["p"][1] - 13500) < 1 for m in mk)
    assert any(d["warn"] and d["floor"] == "2F" for d in fp)
    # 床面照度 1〜3 lx 程度（壁から 0.5〜0.7m）
    assert 1.0 <= LG.footline_floor_lx(fc, fc["base_lm_per_m"], 700) and LG.footline_floor_lx(fc, fc["warn_lm_per_m"], 500) <= 3.5
    # DALI: 足元灯グループが F チャネルで入る
    gr = LG.dali_groups(h, its)
    assert any(g["ch"] == "F" and g["name"].endswith("足元") for g in gr)
