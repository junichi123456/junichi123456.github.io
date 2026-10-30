"""LDK コーナー窓・構造・結露（v4.18）の受け入れ試験。

    python3 tests/test_ldk_window.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from house import House  # noqa: E402
import performance as PF  # noqa: E402

_H = None


def house():
    global _H
    if _H is None:
        _H = House(ROOT)
    return _H


def _ops(h):
    return {op.label: op for w in h.walls for op in w.openings if op.kind == "window" and op.floor == "1F" and op.label in ("AW-LS", "AW-LW") and w.cat == "wall"}


def test_window_dimensions():
    h = house()
    o = _ops(h)
    ch, fl = h.ch["1F"], h.fl["1F"]
    for k in ("AW-LS", "AW-LW"):
        assert o[k].z1 - fl == ch - 100 == 2700, k           # 上端 = 天井 − 100
        assert o[k].z0 - fl == 700 and o[k].height == 2000
    assert (o["AW-LS"].u0, o["AW-LS"].u1) == (-125, 4000)
    assert (o["AW-LW"].u0, o["AW-LW"].u1) == (125, 4000)
    assert h.room_windows(h.ldk) >= 16.0 - 1e-9


def test_structure():
    h = house()
    se = PF.seismic(h)
    for (f, d), v in se["stories"].items():
        assert v["wall_rate"] >= 12, (f, d)
        assert v["耐震等級3（Co=0.3）"]["ratio"] >= 1.0
        assert v["ecc"] <= 0.15, (f, d, v["ecc"])
    assert abs(se["stories"][("1F", "X方向")]["ecc"] - 0.131) < 0.005
    assert max(h.H.values()) <= 3500
    assert 250 >= max(150, max(h.H.values()) / 22)
    assert PF.corner_post(h)["ratio"] < 1.0


def test_condensation():
    h = house()
    c = PF.condensation(h)
    assert c["ok"] and all(r[2] >= c["dew"] + 2.0 - 0.05 for r in c["rows"]), c


def test_local_thickness_geometry():
    h = house()
    ext = [b for b in h.boxes if b.tag == "増し打ち"]
    assert ext and all(b.level == "1F" for b in ext)
    assert abs(h.ldk.area - 33.639375) < 1e-6


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
