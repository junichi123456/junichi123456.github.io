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
    assert x3 == [(815, 4850), (11050, 11850)]                # v4.44: ジム拡張部の開口と、廊下（北）→廊下（北東）の扉（v4.46）
    assert 815 - 125 >= max(450, 0.3 * 2300)                 # 南端の残り壁 690
    assert 16250 - 125 - 11850 >= 690                        # 北端側（11,850〜外面）


def test_wall_quantity_and_eccentricity():
    h = _h()
    wq = house_legal.wall_quantity(h)
    assert wq[("1F", "Y方向")][1] >= 12 and wq[("1F", "X方向")][1] >= 12      # v4.46 施主画像（1F 北東に寝室 2・東面に窓 2）。法の下限 12 を守る
    se = PF.seismic(h)["stories"]
    assert max(v["ecc"] for v in se.values()) <= 0.10          # v4.47 機械室を 2F 東へ・重心を荷重の図心に・1F 主寝室の窓を北へ・2F Y3 を RC 化（全 ≦0.10）
    assert all(abs(v["g"] - 8.125) < 0.5 for v in se.values())
    assert h.t == 250


def test_mech_room_and_battery_room_at_gym_north():
    """v4.47 機械室を 2F 東へ: 1F は未割当（1F 北東 5.85m²）と蓄電室（4.30m²）がジム北端 y8,700〜10,700（E-M 区画）に並ぶ。
    2F の機械室は旧 未割当（2F 東）10.04m²、扉 MD-1 は Y3 u11,400〜12,400（W1,000・南へ内開き）。"""
    h = _h()
    mr = h.spec["mech_rooms"]
    assert mr["wall_x_y"] == 8650 and mr["wall_mid"] == 13925 and mr["floor"] == "2F"
    wx = next(w for w in h.walls if w.floor == "1F" and w.axis == "x" and w.c == mr["wall_x_y"])
    assert [(o.u0, o.u1) for o in wx.openings] == [(12950, 13750)] and all(o.swing == 1 and o.hinge == 0 for o in wx.openings)          # ジム→未割当（1F 北東）（木製片開き戸）
    assert wx.openings[0].name == "木製片開き戸"
    wm = next(w for w in h.walls if w.floor == "1F" and w.axis == "y" and w.c == mr["wall_mid"])
    assert not wm.openings                                                          # 未割当（1F 北東）｜蓄電室 は戸なし
    d = h.battery_door
    assert d.swing == -1 and d.width == 900 and (d.u0, d.u1) == (14400, 15300) and d.wall.c == 8650
    gym = sb(*h.gym.rect)
    assert gym.buffer(150).intersects(sb(*h.battery_room.rect)) and abs(h.battery_room.area - 4.30) < 0.05
    assert h.battery_room.rect[1] >= h.gy[1] and h.battery_room.rect[3] <= h.gy[2]      # E-M 区画
    m1 = [r for r in h.rooms if r.name.startswith("機械室") and r.floor == "1F"]
    assert not m1                                                                   # 1F に機械室はない
    spare = [r for r in h.rooms if r.floor == "1F" and r.name == "未割当（1F 北東）"]
    assert len(spare) == 1 and abs(spare[0].area - 5.85) < 0.03 and spare[0].rect == (10950, 8700, 13875, 10700) and not spare[0].habitable
    m2 = [r for r in h.rooms if r.floor == "2F" and r.name == "機械室"]
    assert len(m2) == 1 and m2[0].rect == (10950, 8759, 16125, 10700) and abs(m2[0].area - 10.04) < 0.03
    assert not [r for r in h.rooms if r.name in ("機械室前", "ジム収納", "未割当（2F 東）") or r.name.startswith("機械室（")]
    md = [(i, o) for i, _, o in h.mech_doors]
    assert len(md) == 1 and md[0][0] == "MD-1" and (md[0][1].u0, md[0][1].u1) == (11400, 12400) and md[0][1].swing == -1 and md[0][1].wall.floor == "2F"
    # 天吊り（z0 ≧ 2,200）は排煙機・空調機のみ。上端は 2F スラブ下面 3,180 以下（直天井）
    for e in mr["equipment"]:
        assert len(e) == 7 and e[6] > 0, e
        z0 = e[5]
        assert e[4] + z0 <= h.H["2F"] - h.slab_t if z0 else True
        if z0 >= 2000:
            assert e[0] in ("MC-1", "MC-2", "MC-7")
        if e[1] == "機械室":
            assert sb(*e[3]).within(sb(10950, 8759, 16125, 10700).buffer(1)), e


def test_clearance_800_and_swing():
    h = _h()
    r = h.clearance_report()
    assert r["min"][1] >= 800, r["min"]
    assert not r["battery_swing_hits"] and not r["lane_hits"]
    assert not any(r["mech_swing_hits"].values()) and r["mech_aisle"] >= 900          # 分電盤・機器が扉の軌跡に入らない。v4.47 2F 機械室の通路 ≧900（実寸 966）
    assert r["usable"] >= 44.85, r["usable"]
    assert abs(h.gym.area - 43.34) < 0.05 and h.gym.daylight_area >= 51.76 * 0.95      # v4.46: ジム 5,175×8,475（−増し打ち帯）＋拡張部 6.99＝50.33（−2.8%、±5% 内）
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
    assert notes_bottom - 4 - 8 + 8 > btm + 25                 # 詳細の枠（上端 = 注記欄の下端−4−5）が注記欄より下にある（v4.46: 窓は 1 つ・1:100 で高さ 約 30mm）
    assert btm < notes_bottom - 4
