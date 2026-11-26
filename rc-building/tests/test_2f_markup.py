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
    # v4.46（施主画像）: 居室・主寝室は 6〜8畳（9.72〜12.96m²）。2F は居室B（北西）・C・E（北東）・D（西）、図書室は南西、トイレは中央の 1 か所
    exp = {"居室B": 12.22, "居室C": 10.08, "居室D": 11.36, "居室E": 10.09, "図書室": 26.78,
           "トイレ（手洗い付）": 4.51, "収納（西）": 2.75, "収納（東）": 1.73, "廊下（南西）": None}
    for n, a in exp.items():
        if a is not None:
            assert abs(_room(h, n).area - a) < 0.05, (n, _room(h, n).area)
    for n in ("居室B", "居室C", "居室D", "居室E"):
        assert 9.72 <= _room(h, n).area <= 12.96 and _room(h, n).habitable
    gone = ("書庫", "脱衣所", "シャワー", "リネン庫", "WIC（主寝室）", "ファミリークローゼット", "主寝室", "居室A", "トイレ", "収納（北）", "収納（北中央）", "収納（図書室）", "収納（廊下）", "収納（居室A）")
    assert not [r for r in h.rooms if r.floor == "2F" and r.name in gone]
    assert not [r for r in h.rooms if r.floor == "1F" and r.name == "収納（洗面）"]
    assert not [r for r in h.rooms if r.name in ("収納（居室B）", "収納（居室C）", "収納（トイレ・主寝室）", "収納（主寝室）")]
    assert "archive" not in h.spec                      # v4.44 書庫の積載区画は撤去


def test_wc_and_dressing_constraints():
    h = house()
    # v4.46: 2 階は水回りをトイレ（手洗い付）1 か所だけ（4.51m²、1,850×2,440）。C-N のトイレ 6.05 は撤去
    wc = _room(h, "トイレ（手洗い付）")
    assert abs(wc.area - 4.51) < 0.03 and wc.rect == (8850, 8260, 10700, 10700)
    assert not [r for r in h.rooms if r.floor == "2F" and "トイレ" in r.name and r is not wc]
    walls = [w for w in h.walls if w.floor == "2F" and w.axis == "y" and w.c == 8800]
    assert [sorted((o.u0, o.u1) for o in w.openings) for w in walls] == [[(9800, 10600)]]     # 廊下（中央）｜トイレ（室内開き）
    assert walls[0].openings[0].swing == -1 and walls[0].openings[0].hinge == 1
    # 廊下はすべて内法 1,100（v4.44 の追加指示）
    cors = [r for r in h.rooms if r.name.startswith("廊下")]
    assert len([r for r in cors if r.floor == "2F"]) == 8 and len([r for r in cors if r.floor == "1F"]) == 5      # v4.46: 2F に廊下（東）・廊下（西・前）、1F に廊下（北西）・廊下（北東）が増える
    assert all(min(r.rect[2] - r.rect[0], r.rect[3] - r.rect[1]) == 1100 for r in cors)


def test_red_lines_standard_thickness():
    h = house()
    assert not [w for w in h.walls if w.floor == "2F" and w.extra]              # 赤線は増し打ちではなく標準厚 t250
    x3 = h.rc_walls["2F"]["X3"]
    assert any((o.u0, o.u1) == (6750, 7550) for o in x3.openings)                # 前室への遮音扉（v4.46 で南寄りへ）
    assert not any((o.u0, o.u1) in ((8850, 9650), (7750, 8550)) for o in x3.openings)       # 図書室の扉は RC で閉じる・旧位置も
    assert any((o.u0, o.u1) == (10950, 12050) for o in x3.openings) and any((o.u0, o.u1) == (10950, 12050) for o in h.rc_walls["2F"]["X2"].openings)   # 廊下の開口 W1,100
    y2, y3 = h.rc_walls["2F"]["Y2"], h.rc_walls["2F"]["Y3"]
    assert any((o.u0, o.u1) == (11300, 15800) for o in y2.openings) and any((o.u0, o.u1) == (11300, 15800) for o in y3.openings)   # シアター・北東の大開口（壁梁）
    assert sorted((o.u0, o.u1) for o in y2.openings if o.kind == "door" and o.operation != "opening") == [(2900, 3700), (6000, 6800)]   # 図書室・未割当（2F 南）の戸だけ


def test_window_aw9_and_daylight():
    h = house()
    # v4.46: 2F 窓は 図書室（S・W）・居室B（N）・居室C（N）・居室E（E）・居室D（W）・未割当（S）。居室E は復活（v4.42 で書庫へ→v4.46 で居室に）
    assert not [x for x in HL.window_table(h) if x["room"] in ("書庫",)]
    assert [o for w in h.walls for o in w.openings if w.floor == "2F" and w.side == "W" and "FIX窓（居室D）" in o.name and (o.u0, o.u1) == (7700, 9300)]
    for n in ("居室B", "居室C", "居室D", "居室E", "図書室"):
        assert [x for x in HL.window_table(h) if x["room"] == n and x["floor"] == "2F" and x["margin"] >= 1.0], n
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
    # トイレの戸口前（v4.46: 廊下（中央）の x8,800・y10,200）に警告区間がある
    assert any(m["kind"] == "戸口" and m["floor"] == "2F" and abs(m["p"][0] - 8800) < 1 and abs(m["p"][1] - 10200) < 1 for m in mk)
    assert any(d["warn"] and d["floor"] == "2F" for d in fp)
    # 床面照度 1〜3 lx 程度（壁から 0.5〜0.7m）
    assert 1.0 <= LG.footline_floor_lx(fc, fc["base_lm_per_m"], 700) and LG.footline_floor_lx(fc, fc["warn_lm_per_m"], 500) <= 3.5
    # DALI: 足元灯グループが F チャネルで入る
    gr = LG.dali_groups(h, its)
    assert any(g["ch"] == "F" and g["name"].endswith("足元") for g in gr)
