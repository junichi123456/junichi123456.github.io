"""v4.27 施主の書き込み（images/7.png）: ジムの S・E 壁の増し打ち（t300）、ホール側の扉 W1,200 Ts-45 と室内窓 IW-1 の再配置。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from shapely.geometry import box as sb  # noqa: E402
import house_legal  # noqa: E402
import performance as PF  # noqa: E402
from house import House  # noqa: E402

_H = []


def _h():
    if not _H:
        _H.append(House(ROOT))
    return _H[0]


def test_local_thick_rows():
    h = _h()
    lt = h.spec["structure"]["local_thick"]
    assert [(r["side"], r["t"]) for r in lt if r["floor"] == "1F"] == [("S", 350), ("W", 300), ("S", 300), ("E", 300)]   # LDK の S350・W300 に、ジムの S・E を t300（+50）
    assert (h.rc_walls["1F"]["E"].extra[0][2], h.rc_walls["1F"]["S"].extra[-1][2]) == (50, 50)


def test_areas():
    h = _h()
    assert abs(h.gym.area - 45.76) < 0.02
    assert abs(h.gym.daylight_area - 53.40) < 0.02
    assert h.clearance_report()["usable"] >= 44.85


def test_structure_ok():
    h = _h()
    se = PF.seismic(h)["stories"]
    assert max(v["ecc"] for v in se.values()) <= 0.15
    wq = house_legal.wall_quantity(h)
    assert wq[("1F", "X方向")][1] >= 12 and wq[("1F", "Y方向")][1] >= 12


def test_equipment_off_inner_faces():
    h = _h()
    gl = h.spec["gym_layout"]
    s_in = 125 + 50
    e_in = 18125 - 50
    for n, r, *_ in h.equipment:
        if n == "ストレッチマット":
            continue
        assert r[1] >= s_in and r[3] <= e_in, n
    for n, r in [("J-M1", gl["mirror"]), ("J-K1", gl["counter"])]:
        assert r[1] >= s_in and r[3] <= e_in, n


def test_door_window_and_mat():
    h = _h()
    assert (h.gym_door.u0, h.gym_door.u1, h.gym_door.hinge) == (4550, 5750, 1)
    assert (h.gym_window.u0, h.gym_window.u1) == (1000, 2415)            # IW-1 は南へ再配置（施主回答）
    assert not any(op.u0 < 4000 and op.u1 > 3000 and op.kind == "door" and w.c == 10600 for w in h.walls for op in w.openings)  # SSD-2 は塞ぐ
    sw = h.swing_zone(h.gym_door, (10600, 5750), (1, -1))
    mat = [r for n, r, *_ in h.equipment if n == "ストレッチマット"][0]
    assert not sb(*mat).intersects(sw)
    assert house_legal.gym_sound(h)["tl"] >= 48


def test_footprint_unchanged():
    import house_legal as HL
    rows, sm, _ = HL.checks(_h())
    assert abs(sm["building_area"] - 348.04) < 0.01        # 外面不変（増し打ちは室内側）
