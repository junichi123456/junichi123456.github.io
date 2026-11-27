"""v4.47 機械室を 2F 東（旧 未割当（2F 東））へ移し、1F の旧機械室を未割当に。偏心率は重心を荷重の図心にして各 ≦0.10（仕様 §10.1 の検算）。"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import furniture as FU  # noqa: E402
import house_legal as HL  # noqa: E402
import kitchen_open as KO  # noqa: E402
import performance as PF  # noqa: E402
from house import House  # noqa: E402
from shapely.geometry import box as sb  # noqa: E402

# v4.46（3a608e8）の室の面積（同名の室は合算）。機械室（1F）と未割当（2F 東）は除く
OLD_AREAS = {
    ('1F', 'リビング・ダイニング'): 26.01,
    ('1F', 'キッチン'): 19.41,
    ('1F', '玄関収納'): 1.94,
    ('1F', '玄関土間'): 5.86,
    ('1F', '式台（框1）'): 1.25,
    ('1F', 'ホール'): 9.06,
    ('1F', 'ジム'): 43.34,
    ('1F', 'ジム（拡張部）'): 6.99,
    ('1F', '廊下（西）'): 1.71,
    ('1F', '未割当（1F 西）'): 6.16,
    ('1F', 'ホール・階段1'): 3.52,
    ('1F', '階段1前'): 1.1,
    ('1F', '廊下（中央）'): 4.46,
    ('1F', 'トイレ（手洗い付）'): 3.79,
    ('1F', 'PS-3'): 0.85,
    ('1F', '納戸'): 4.51,
    ('1F', 'ホール・階段2'): 4.3,
    ('1F', '廊下（北西）'): 3.38,
    ('1F', 'ランドリー・室内干し'): 12.22,
    ('1F', '廊下（北）'): 5.67,
    ('1F', '洗面・脱衣'): 8.35,
    ('1F', '浴室'): 10.32,
    ('1F', 'PS-2'): 1.11,
    ('1F', '廊下（北東）'): 4.01,
    ('1F', '居室A'): 10.08,
    ('1F', '主寝室'): 10.09,
    ('1F', '収納（北東）'): 1.57,
    ('2F', '図書室'): 26.78,
    ('2F', '未割当（2F 南）'): 26.65,
    ('2F', 'シアター'): 33.19,
    ('2F', '前室（音響ロック）'): 10.45,
    ('2F', '廊下（南西）'): 5.69,
    ('2F', '廊下（南中央）'): 3.52,
    ('2F', '階段1前'): 1.1,
    ('2F', '居室D'): 11.36,
    ('2F', '収納（西）'): 2.75,
    ('2F', '廊下（西・前）'): 1.21,
    ('2F', '廊下（西）'): 4.34,
    ('2F', '廊下（中央）'): 4.34,
    ('2F', 'トイレ（手洗い付）'): 4.51,
    ('2F', 'PS-3'): 0.85,
    ('2F', 'ホール（東）'): 3.79,
    ('2F', 'ホール・階段2'): 4.3,
    ('2F', '廊下（北西）'): 3.38,
    ('2F', '居室B'): 12.22,
    ('2F', '廊下（北）'): 5.67,
    ('2F', '未割当（2F 北）'): 17.51,
    ('2F', '未割当（2F 北・奥）'): 1.0,
    ('2F', 'PS-2'): 1.4,
    ('2F', '廊下（東）'): 3.85,
    ('2F', '居室C'): 10.08,
    ('2F', '居室E'): 10.09,
    ('2F', '収納（東）'): 1.73,
}

_H = None


def _h():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def _rooms(h):
    rm = {}
    for r in h.rooms:
        rm.setdefault((r.floor, r.name), []).append(r)
    return rm


def _area(rm, f, n):
    return sum(r.area for r in rm[(f, n)])


def test_rooms_moved():
    h = _h()
    rm = _rooms(h)
    assert ("2F", "機械室") in rm and ("1F", "機械室") not in rm and ("2F", "未割当（2F 東）") not in rm
    assert rm[("2F", "機械室")][0].rect == (10950, 8759, 16125, 10700) and abs(_area(rm, "2F", "機械室") - 10.04) < 0.03
    assert rm[("1F", "未割当（1F 北東）")][0].rect == (10950, 8700, 13875, 10700) and abs(_area(rm, "1F", "未割当（1F 北東）") - 5.85) < 0.03
    assert not [k for k in rm if k[1].startswith("機械室（") or k[1] == "機械室前"]
    b = h.battery_room
    assert tuple(b.rect) == (13975, 8700, 16125, 10700) and abs(b.area - 4.30) < 0.05
    assert not [r for r in h.rooms if "未割当" in r.name and r.habitable]


def test_other_room_areas_unchanged():
    h = _h()
    rm = _rooms(h)
    for (f, n), v in OLD_AREAS.items():
        assert abs(_area(rm, f, n) - v) < 0.01, (f, n, _area(rm, f, n), v)
    for k in [("1F", "主寝室"), ("1F", "居室A"), ("2F", "居室B"), ("2F", "居室C"), ("2F", "居室D"), ("2F", "居室E")]:
        assert 9.72 <= _area(rm, *k) <= 12.96 and all(r.habitable for r in rm[k]), k
    for (f, n), rs in rm.items():
        if n.startswith("廊下"):
            for r in rs:
                x0, y0, x1, y1 = r.rect
                assert min(x1 - x0, y1 - y0) == 1100, (f, n, r.rect)
    rows, sm, wq = HL.checks(h)
    assert abs(sm["total"] - 528.125) < 0.01


def test_y3_wall_and_window_moved():
    h = _h()
    y3 = h.rc_walls["2F"]["Y3"]
    assert not [o for o in y3.openings if o.u0 <= 13000 <= o.u1 and o.width > 1100]
    md = [o for o in y3.openings if (o.u0, o.u1) == (11400, 12400)]
    assert md and md[0].swing == -1
    assert not [o for o in h.rc_walls["1F"]["E"].openings if "主寝室" in o.name]
    assert [(o.u0, o.u1) for o in h.rc_walls["1F"]["N"].openings if "主寝室" in o.name] == [(12500, 14100)]
    w = [o for o in h.rc_walls["1F"]["N"].openings if "主寝室" in o.name][0]
    assert abs(w.glass - 1.76) < 0.01 and w.z0 - h.fl["1F"] == 800 and w.z1 - w.z0 == 1100


def test_equipment_swing_aisle_gym_clearance():
    h = _h()
    mr = h.spec["mech_rooms"]
    assert mr["floor"] == "2F"
    for e in mr["equipment"]:
        assert len(e) == 7 and e[6] > 0, e
        if e[1] == "機械室":
            assert sb(*e[3]).within(sb(10950, 8759, 16125, 10700).buffer(1)), e
            if e[5]:
                assert e[4] + e[5] <= h.H["2F"] - h.slab_t, e
    cr = h.clearance_report()
    assert not any(cr["mech_swing_hits"].values()) and cr["mech_aisle"] >= 900, cr["mech_aisle"]
    assert cr["min"][1] >= 800 and cr["usable"] >= 44.85 and cr["rack_front"] >= 1000
    its = FU.items(h)
    assert not FU.check(h, its), FU.check(h, its)[:5]
    assert KO.passages(h, its)["ok"]


def test_eccentricity_all_below_010_and_gravity_centre():
    h = _h()
    se = PF.seismic(h)
    for k, v in se["stories"].items():
        assert v["ecc"] <= 0.10, (k, v["ecc"])
        assert abs(v["g"] - 8.125) < 0.5, (k, v["g"])
        assert "ecc_center" in v and "rc" in v
    rows, sm, wq = HL.checks(h)
    assert all(q >= 12 for _, (L, q) in wq.items())
    assert not [x["item"] for x in rows if x["result"] == "不適合"]
    assert any("2F 機械室の床・吊り荷重" in x["item"] for x in rows)


def test_surplus_25m2_units():
    h = _h()
    sr = h.surplus_report()
    for f, want in (("1F", 12.01), ("2F", 45.16)):
        s = sum(r.area for r in h.rooms if r.floor == f and "未割当" in r.name)
        assert abs(s - want) < 0.05 and abs(sr[f]["area"] - s) < 1e-9
        assert sr[f]["units"] == math.floor(s / 25) and abs(sr[f]["rem"] - (s - 25 * sr[f]["units"])) < 1e-9
    assert sr["計"]["units"] == 2


def test_a04_detail_does_not_overlap_notes():
    import house_sheets as hs
    h = _h()
    sh = hs.floor_plan(h, "2F", "A-04")                      # 内部の assert: 詳細の下端が表題欄の上端から 3mm 以上離れる
    btm, notes_bottom = sh.detail_frame
    assert btm >= sh.MARGIN + sh.TB[1] + 3
    assert btm < notes_bottom - 4
