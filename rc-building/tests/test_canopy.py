"""連続庇・建築面積・日射（v4.18）の受け入れ試験。

    python3 tests/test_canopy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from house import House  # noqa: E402
import sightshade as SS  # noqa: E402

_H = None


def house():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def test_canopy_geometry():
    h = house()
    south, west = h.canopies
    assert south[3] - south[1] == 2000 and west[2] - west[0] == 1000     # 南の出 2,000、西の出 1,000
    assert (south[0], south[2]) == (-1245, 10900) and west[3] == 4500
    zip_top = max(b.z1 for op, b in h.blinds if "角窓" in op.name)
    assert h.canopy_z >= zip_top and h.canopy_z == h.fl["1F"] + 2900      # 下端 FL+2,900 ≧ ZIP ボックスの上端


def test_building_area_includes_canopy():
    h = house()
    a = h.building_area()
    assert 347.5 < a < 348.6, a
    assert a / (h.site.area / 1e6) < 0.60


def test_overhang_factor():
    h = house()
    ops = {op.label: op for op in h.openings(exterior=True) if op.label in ("AW-LS", "AW-LW")}
    f = SS.overhang_factor(h, ops["AW-LS"], {11, 12, 1, 2, 3})
    assert 0.40 <= f <= 0.46, f                                              # 南の暖房期の残存率
    assert SS.overhang_factor(h, ops["AW-LW"], {11, 12, 1, 2, 3}) > 0.65


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
