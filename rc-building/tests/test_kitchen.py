"""キッチン（v4.18）の受け入れ試験。

    python3 tests/test_kitchen.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from house import House  # noqa: E402
import furniture as FU  # noqa: E402
import kitchen_open as KO  # noqa: E402

_H = None


def house():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def test_shelf_tops_within_1550():
    h = house()
    assert max(v for *_, v in KO.support_tops(h)) <= h.spec["kitchen_open"]["shelf_max_z"]
    # 実際に作った形状でも、KS-W は上部パネル（1,550〜天井、物は置けない）以外の水平面が 1,550 以下
    its = {i.id: i for i in FU.items(h)}
    for iid in ("KB-S", "KB-N"):
        mb = FU.build_item(h, its[iid])
        zmax = max(V[:, 2].max() for lst in mb.parts.values() for V, F in lst) - h.fl["1F"]
        assert zmax <= 1550 + 70, (iid, zmax)    # 落下防止バーは棚の縁（天端+60）
    assert its["KB-N"].z0 + its["KB-N"].h - h.fl["1F"] <= 1550


def test_aisles_at_least_1300():
    h = house()
    ai = KO.aisles(h)
    assert len(ai) == 6 and min(v for _, v in ai) >= 1300, ai


def test_pantry_removed():
    h = house()
    assert not any(r.name == "パントリー" for r in h.rooms)
    ids = {i.id for i in FU.items(h)}
    assert "P-O1" not in ids and "KB-K" not in ids and "KS-W" in ids
    kit = next(r for r in h.rooms if r.name == "キッチン")
    assert kit.rect == (125, 6250, 6000, 12000)


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
