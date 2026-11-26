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
    # v4.43: 外形 16.25m 角。書庫は南西の W-S 区画 7.36m²（4.5 畳）、居室A は 2F へ、主寝室は南へ。固定の部屋は v4.42 比 −3.8% 以内
    exp = {"書庫": 7.36, "居室A": 9.59, "居室B": 9.35, "居室C": 8.77, "居室D": 8.77,
           "脱衣所": 7.07, "シャワー": 9.59, "トイレ": 6.05, "収納（北）": 4.51, "リネン庫": 4.47, "収納（居室A）": 3.82,
           "廊下": None, "主寝室": 9.70, "WIC（主寝室）": 21.47}
    for n, a in exp.items():
        if a is not None:
            assert abs(_room(h, n).area - a) < 0.05, (n, _room(h, n).area)
    assert "ファミリークローゼット" not in [r.name for r in h.rooms if r.floor == "2F"]
    assert not [r for r in h.rooms if r.name in ("収納（居室B）", "収納（居室C）", "収納（トイレ・主寝室）", "収納（主寝室）")]     # v4.43 廃止


def test_wc_and_dressing_constraints():
    h = house()
    wc, dr = _room(h, "トイレ"), _room(h, "脱衣所")
    # v4.43: トイレの幅 ≦1.8m は面積管理（5.74〜6.10m²）へ読み替え（面積 ±5% の追加指示。要確認 Q4）。脱衣所は 1,825×3,875（短辺 ≧1.8m）
    assert 5.74 <= wc.area <= 6.1 and (wc.rect[2] - wc.rect[0]) == 2350
    assert min(dr.rect[2] - dr.rect[0], dr.rect[3] - dr.rect[1]) >= 1800
    walls = [w for w in h.walls if w.floor == "2F" and w.axis == "x" and w.c == 13500]
    assert [sorted((o.u0, o.u1) for o in w.openings) for w in sorted(walls, key=lambda w: w.a)] == [[(6400, 7200), (8800, 9600)]]     # v4.43: 北の行の C 列（トイレ・収納（北））。脱衣所の戸は X3
    cor = [r for r in h.rooms if r.floor == "2F" and r.name == "廊下" and r.rect[0] == 6025 and r.rect[1] == 12250][0]
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
    # v4.43: 書庫に窓がなく（南の W-S 区画の北側）、2F W 面 u12,900〜14,500 に居室A の西窓（AW-9 を復活。W1,600×H800）がある
    assert not [x for x in HL.window_table(h) if x["room"] in ("居室E", "書庫")]
    assert [o for w in h.walls for o in w.openings if w.floor == "2F" and w.side == "W" and "FIX窓（居室A）" in o.name and (o.u0, o.u1) == (12900, 14500)]
    assert [x for x in HL.window_table(h) if x["room"] == "居室A" and x["floor"] == "2F"]


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
