"""玄関ホールの透明扉 GD-1・GD-2（v4.17）の受け入れ試験。

    python3 tests/test_glass_doors.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from house import House  # noqa: E402

_H = None


def house():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def _find(label):
    h = house()
    return [(w, op) for w in h.walls for op in w.openings if op.label == label]


def test_gd_position():
    for label, wall_c, axis_u in (("GD-1", 6125, (2800, 4000)), ("GD-2", 6125, (7500, 10500))):
        r = _find(label)
        assert len(r) == 1, label
        w, op = r[0]
        assert abs(w.c - wall_c) < 1 and (op.u0, op.u1) == axis_u, label
        assert op.operation == "sliding" and op.glass is True
        assert op.z1 - op.z0 == 2200                       # RC の開口寸法は変えない
    assert _find("GD-1")[0][0].axis == "y" and _find("GD-2")[0][0].axis == "x"


def test_head_and_gap():
    h = house()
    g = h.spec["glass_doors"]
    for label in ("GD-1", "GD-2"):
        w, op = _find(label)[0]
        assert h.ch["1F"] - op.head >= 500                 # 防煙垂れ壁 500
    assert g["gap_to_wall"] > 25
    assert g["thickness"] == 10.8


def test_gym_door_unchanged():
    h = house()
    ssd = [(w, op) for w in h.walls for op in w.openings if op.kind == "door" and "遮音ドア" in op.name and op.floor == "1F"]
    assert any((op.u0, op.u1) == (3000, 4000) and w.c == 12125 or (op.u0, op.u1) == (3000, 4000) for w, op in ssd)


def test_fittings_sheet_draws():
    import sheetlib
    h = house()
    labels = [f["label"] for f in h.fittings]
    assert "GD-1" in labels and "GD-2" in labels
    sheetlib.fittings_sheet(h, "A-09")


def test_wifi_glass_loss():
    import wifi
    assert wifi.LOSS["glass_door"] < wifi.LOSS["door"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for f in fns:
        f()
        print("ok", f.__name__)
