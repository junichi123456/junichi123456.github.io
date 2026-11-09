"""v4.26 機械室の部屋割り・ジムへの開口・X3 の壁量・離隔 800（images/6.webp）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import house_legal  # noqa: E402
import performance as PF  # noqa: E402
from house import House  # noqa: E402
from shapely.geometry import box as sb  # noqa: E402

_H = None


def _h():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def test_x3_openings_and_remnants():
    h = _h()
    x3 = sorted((o.u0, o.u1) for w in h.walls if w.floor == "1F" and w.cat == "wall" and w.axis == "y" and w.c == h.gx[2] for o in w.openings)
    assert x3 == [(815, 4850), (13000, 13800)]
    assert 815 - 125 >= max(450, 0.3 * 2300)                 # 南端の残り壁 690
    assert 18250 - 125 - 13800 >= 690                        # 北端側（13,800〜外面）


def test_wall_quantity_and_eccentricity():
    h = _h()
    wq = house_legal.wall_quantity(h)
    assert wq[("1F", "Y方向")][1] >= 16.2 and wq[("1F", "X方向")][1] >= 15.99
    assert max(v["ecc"] for v in PF.seismic(h)["stories"].values()) <= 0.15
    assert h.t == 250


def test_three_rooms_one_door_each_into_gym():
    h = _h()
    w89 = next(w for w in h.walls if w.floor == "1F" and w.axis == "x" and w.c == 8950 and w.a == 12250)
    assert [(o.u0, o.u1) for o in w89.openings] == [(12350, 13150), (15350, 16150)]
    assert all(o.swing == 1 and o.hinge == 0 for o in w89.openings)                 # 内開き
    w15 = next(w for w in h.walls if w.floor == "1F" and w.axis == "y" and w.c == 15150)
    assert not w15.openings                                                          # 機械室どうしの扉は廃止
    d = h.battery_door
    assert d.swing == -1 and d.width == 900 and (d.u0, d.u1) == (6500, 7400)
    gym = sb(*h.gym.rect)
    assert gym.buffer(1).intersects(sb(*h.battery_room.rect)) and abs(h.battery_room.area - 4.7) < 0.05
    mw, me = (r for r in h.rooms if r.name.startswith("機械室"))
    assert abs(mw.area - 8.6) < 0.1 and abs(me.area - 8.8) < 0.1
    for r in (mw, me):                                                               # 扉のある壁（y8,950）がジムに接する
        assert abs(r.rect[1] - 9000) < 1 and gym.intersects(sb(r.rect[0], 8900, r.rect[2], 9000))


def test_clearance_800_and_swing():
    h = _h()
    r = h.clearance_report()
    assert r["min"][1] >= 800, r["min"]
    assert not r["battery_swing_hits"] and not r["lane_hits"]
    assert not any(r["mech_swing_hits"].values())                                    # 分電盤・機器が扉の軌跡に入らない
    assert r["usable"] >= 44.85, r["usable"]
    assert abs(h.gym.area - 45.17) < 0.05 and abs(h.gym.daylight_area - 52.81) < 0.05
    assert r["rack_front"] >= h.spec["mech_rooms"]["rack_front_min"]
    z = h.mech_zones()
    for n, rc, *_ in h.equipment:
        assert sb(*rc).distance(z["mech"]) >= 800 and sb(*rc).distance(z["battery"]) >= 800, n


def test_battery_not_in_gym_furniture_and_no_ap():
    import furniture as F
    h = _h()
    its = F.items(h) if hasattr(F, "items") else None
    if its is not None:
        assert not F.check(h, its)
    bat = sb(*h.battery_room.rect)
    for n, rc, *_ in h.equipment:
        assert not sb(*rc).intersects(bat), n


def test_a03_detail_does_not_overlap_notes():
    import house_sheets as hs
    h = _h()
    sh = hs.floor_plan(h, "1F", "A-03")                      # 内部の assert: 詳細の下端が表題欄の上端から 3mm 以上離れる
    btm, notes_bottom = sh.detail_frame
    assert btm >= sh.MARGIN + sh.TB[1] + 3
    assert notes_bottom - 4 - 8 + 8 > btm + 70                 # 詳細の枠（上端 = 注記欄の下端−4−5）が注記欄より下にある
    assert btm < notes_bottom - 4
