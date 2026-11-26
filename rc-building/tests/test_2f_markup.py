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
    # v4.44: 寝室は v4.43 の面積 +1.62m²（+1 畳）。2F の書庫・シャワー・脱衣所・リネン庫・WIC（主寝室）は撤去。収納・水回りは新しい通り芯の値
    exp = {"居室A": 11.21, "居室B": 10.97, "居室C": 10.59, "居室D": 10.39, "主寝室": 11.32,
           "トイレ": 6.05, "トイレ（手洗い付）": 3.79, "収納（北）": 4.52, "収納（居室A）": 3.82, "廊下（南西）": None}
    for n, a in exp.items():
        if a is not None:
            assert abs(_room(h, n).area - a) < 0.05, (n, _room(h, n).area)
    gone = ("書庫", "脱衣所", "シャワー", "リネン庫", "WIC（主寝室）", "ファミリークローゼット")
    assert not [r for r in h.rooms if r.floor == "2F" and r.name in gone]
    assert not [r for r in h.rooms if r.floor == "1F" and r.name == "収納（洗面）"]
    assert not [r for r in h.rooms if r.name in ("収納（居室B）", "収納（居室C）", "収納（トイレ・主寝室）", "収納（主寝室）")]
    assert "archive" not in h.spec                      # v4.44 書庫の積載区画は撤去


def test_wc_and_dressing_constraints():
    h = house()
    wc = _room(h, "トイレ")
    # v4.44: 2 階は水回りをトイレ 2 か所だけにする（脱衣所・シャワー・リネン庫は撤去）。トイレは面積管理（5.74〜6.10m²）
    assert 5.74 <= wc.area <= 6.1 and (wc.rect[2] - wc.rect[0]) == 2950
    walls = [w for w in h.walls if w.floor == "2F" and w.axis == "x" and w.c == 13450]
    assert [sorted((o.u0, o.u1) for o in w.openings) for w in sorted(walls, key=lambda w: w.a)] == [[(5800, 6600), (8800, 9600)]]     # 北の行の C 列（収納（北中央）・トイレ）
    # 廊下はすべて内法 1,100（v4.44 の追加指示）
    cors = [r for r in h.rooms if r.name.startswith("廊下")]
    assert len([r for r in cors if r.floor == "2F"]) == 5 and len([r for r in cors if r.floor == "1F"]) == 2
    assert all(min(r.rect[2] - r.rect[0], r.rect[3] - r.rect[1]) == 1100 for r in cors)


def test_red_lines_standard_thickness():
    h = house()
    assert not [w for w in h.walls if w.floor == "2F" and w.extra]              # 赤線は増し打ちではなく標準厚 t250
    x3 = h.rc_walls["2F"]["X3"]
    assert any((o.u0, o.u1) == (7750, 8550) for o in x3.openings)                # 前室への遮音扉
    assert any((o.u0, o.u1) == (8850, 9650) for o in x3.openings)                # 図書室の扉
    y2, y3 = h.rc_walls["2F"]["Y2"], h.rc_walls["2F"]["Y3"]
    assert any((o.u0, o.u1) == (11300, 15800) for o in y2.openings) and any((o.u0, o.u1) == (11300, 15800) for o in y3.openings)   # シアター・図書室の大開口（壁梁）


def test_window_aw9_and_daylight():
    h = house()
    # v4.44: 書庫・WIC は撤去。2F W 面 u7,700〜9,300 に居室D の西窓（W1,600×H800）、E 面に図書室の窓
    assert not [x for x in HL.window_table(h) if x["room"] in ("居室E", "書庫")]
    assert [o for w in h.walls for o in w.openings if w.floor == "2F" and w.side == "W" and "FIX窓（居室D）" in o.name and (o.u0, o.u1) == (7700, 9300)]
    assert [x for x in HL.window_table(h) if x["room"] == "居室D" and x["floor"] == "2F" and x["margin"] >= 1.0]
    assert all(x["margin"] >= 1.0 for x in HL.window_table(h))


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
    # トイレの戸口前（北の行 y13,450）に警告区間がある（v4.44）
    assert any(m["kind"] == "戸口" and m["floor"] == "2F" and abs(m["p"][1] - 13450) < 1 for m in mk)
    assert any(d["warn"] and d["floor"] == "2F" for d in fp)
    # 床面照度 1〜3 lx 程度（壁から 0.5〜0.7m）
    assert 1.0 <= LG.footline_floor_lx(fc, fc["base_lm_per_m"], 700) and LG.footline_floor_lx(fc, fc["warn_lm_per_m"], 500) <= 3.5
    # DALI: 足元灯グループが F チャネルで入る
    gr = LG.dali_groups(h, its)
    assert any(g["ch"] == "F" and g["name"].endswith("足元") for g in gr)
