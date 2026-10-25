"""照明の再構成（v4.17）の受け入れ試験。

    python3 tests/test_lighting.py        （pytest があれば pytest tests/ でもよい）
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


def test_downlight_is_weak():
    sp = house().spec
    assert sp["lighting"]["downlight"]["max_lm"] <= 300
    assert sp["interior_cg"]["downlight_ratio"] <= 0.35


def test_hex_not_adopted():
    hx = house().spec["lighting"]["hex"]
    assert hx["tested"] is True and hx["adopted"] is False


def test_foot_height_spec():
    ft = house().spec["lighting"]["foot"]
    assert ft["height_from_tread"] == 300 and ft["every_steps"] == 2


def test_kitchen_open_spec():
    ko = house().spec["kitchen_open"]
    assert ko["knife_z"] >= 1550 and ko["pot_rack"] is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for f in fns:
        f()
        print("ok", f.__name__)
