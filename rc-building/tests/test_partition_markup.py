"""v4.25 施主の書き込み（images/5.webp）への対応: 北東の居室（居室A）・WIC・ジム・浴室の壁・室内窓・X3 開口。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import house_legal  # noqa: E402
from house import House  # noqa: E402

_H = None


def _h():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def _room(h, name, floor="1F", idx=0):
    return [r for r in h.rooms if r.name == name and r.floor == floor][idx]


def test_room_areas():
    h = _h()
    # v4.41: 居室A は 5.96 畳（9.65m²）、WIC 4.56、玄関土間 6.09（幅 4,250→3,250）、浴室 10.24、トイレ 6.08。ジムは蓄電室を y8,625 までにして +0.51
    assert abs(h.room_A.area - 9.65) < 0.01
    assert abs(_room(h, "WIC").area - 4.56) < 0.01
    assert abs(h.gym_annex.area - 7.64) < 0.01 and abs(h.gym.daylight_area - 53.91) < 0.02       # v4.27: ジム本体 46.35→45.76（S・E の増し打ち帯）→ v4.41 46.27
    assert abs(_room(h, "浴室").area - 10.24) < 0.01 and abs(_room(h, "玄関土間").area - 6.09) < 0.01
    assert abs(_room(h, "トイレ").area - 6.08) < 0.01 and abs(_room(h, "洗面・脱衣").area - 8.29) < 0.01


def test_daylight_margin():
    rows = {r["item"]: r for r in house_legal.checks(_h())[0]}
    for k in ("採光 1F 居室A", "採光 1F ジム（拡張部含む）"):
        assert rows[k]["result"] == "適合", k
    h = _h()
    glass = h.room_windows(h.room_A) * 3.0
    assert glass / (h.room_A.area * 0.1529) >= 1.0
    assert glass / (h.room_A.area * 0.1529) >= 1.01 - 0.005


def test_x3_remnant_and_rc():
    h = _h()
    x3 = [op for w in h.walls if w.floor == "1F" and w.cat == "wall" and w.axis == "y" and w.c == h.gx[2] for op in w.openings if op.u0 < 5000 and op.kind == "door"]
    assert [(o.u0, o.u1) for o in x3] == [(815, 4850)]
    assert x3[0].u0 - 125 >= max(450, 0.3 * 2300)           # 南端に残る RC 壁（壁芯 125〜815 の 690）
    assert h.t == 250                                       # RC 壁厚（令78条の2 ≧150）


def test_hall_and_gd2():
    h = _h()
    hall = _room(h, "ホール")
    assert hall.rect[2] - hall.rect[0] == 3250 and hall.rect[2] <= 9500          # v4.41: 幅 4,250→3,250（土間の東端 9,500）
    gd2 = [op for w in h.walls for op in w.openings if "ガラス" in op.name and w.c == h.gy[1] and w.axis == "x" and w.floor == "1F"][0]
    assert (gd2.u0, gd2.u1) == (6500, 9500)             # v4.41: −1,000（W3,000 は不変）


def test_bath_wall_and_toilet_face():
    h = _h()
    # v4.41: bath_wall（t200 の東壁）は廃止。浴室は 4,600×2,225（10.24m²）で東は配管スペース（x10,850〜11,000）との境の LGS x10,900
    w = [w for w in h.walls if w.floor == "1F" and w.axis == "y" and w.c == 10900]
    assert len(w) == 1 and (w[0].a, w[0].b) == (14850, 17125)
    toilet = _room(h, "トイレ")
    assert toilet.rect == (11250, 13550, 12950, 17125)       # 北東へ移設（1,700×3,575。2F トイレの真下）
    assert _room(h, "浴室").rect == (6250, 14900, 10850, 17125)


def test_sound_and_window():
    h = _h()
    s = house_legal.gym_sound(h)
    assert s["tl"] >= 48                                     # v4.27: IW-1 は南へ再配置、Ts-45 W1,200 扉で 48dB 以上
    assert (h.gym_window.u0, h.gym_window.u1) == (1000, 2415) and h.gym_window.z1 - h.gym_window.z0 == 1300   # v4.27: 玄関入口側へ再配置


def test_no_furniture_conflict():
    import furniture
    h = _h()
    assert furniture.check(h, furniture.items(h)) == []      # 干渉・はみ出し 0（B1-U・A-C1 の移設を含む）
