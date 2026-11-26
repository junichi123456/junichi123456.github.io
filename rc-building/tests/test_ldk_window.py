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
    assert set(o) == {"AW-LS", "AW-LW"}                       # v4.37: 西窓 AW-LW を追加（v4.36 の撤回を一部戻す。角は RC のまま）
    for k in ("AW-LS", "AW-LW"):
        assert o[k].z1 - fl == ch - 100 == 2700, k           # 上端 = 天井 − 100
        assert o[k].z0 - fl == 700 and o[k].height == 2000
    assert (o["AW-LS"].u0, o["AW-LS"].u1) == (1900, 4000)
    assert (o["AW-LW"].u0, o["AW-LW"].u1) == (1900, 4000)      # v4.38 施主回答 Q1 で構造優先の南窓と対称の位置へ
    assert h.room_windows(h.ldk) >= 8.4 - 1e-9
    assert 8.4 * 3.0 >= h.ldk.daylight_area * 0.1529 * 2.4


def test_structure():
    h = house()
    se = PF.seismic(h)
    for (f, d), v in se["stories"].items():
        assert v["wall_rate"] >= 12, (f, d)
        assert v["耐震等級3（Co=0.3）"]["ratio"] >= 1.0
        assert v["ecc"] <= 0.15, (f, d, v["ecc"])
    assert abs(se["stories"][("1F", "X方向")]["ecc"] - 0.089) < 0.005     # v4.36: L 字窓の撤回（角を RC 化）で 0.113→0.061。v4.37 西窓 0.062。v4.41: X3 が西へ寄り北の行が浅くなって 0.089（≦0.12）
    assert abs(se["stories"][("1F", "Y方向")]["ecc"] - 0.082) < 0.005     # 0.040→0.107。v4.37 西窓の追加で 0.107→0.071。v4.41: 0.082
    assert max(h.H.values()) <= 3500
    assert 250 >= max(150, max(h.H.values()) / 22)
    assert not [b for b in h.boxes if b.level == "1F" and b.tag in ("角柱", "方立", "角の方立")]
    lw = [o for w in h.walls if w.floor == "1F" and w.cat == "wall" and w.axis == "y" and w.c == 0 for o in w.openings if o.kind == "window"]
    assert min(o.u0 for o in lw) - h.t / 2 >= 690          # 角の西の壁 ≧ 690
    assert min(o.u0 for o in lw) - h.t / 2 == 1775         # v4.38 角の西の壁 125〜1,900


def test_condensation():
    h = house()
    c = PF.condensation(h)
    assert c["ok"] and all(r[2] >= c["dew"] + 2.0 - 0.05 for r in c["rows"]), c
    assert all(r[1] >= c["limit"] - 0.05 for r in c["rows"])          # v4.38 ZIP を上げた夜も適合（クアッド・吹出しなし）
    d = PF.cold_draft(h)
    assert d["v_x"] <= 0.15 and abs(d["v_x"] - 0.062) < 0.005, d


def test_glazing_quad():
    import sightshade as SS
    h = house()
    q = h.spec["glazing"]["quad"]
    assert set(q["labels"]) == {"AW-LS", "AW-LW"}
    env = PF.envelope(h)
    parts = {p[0]: p for p in env["parts"]}
    assert abs(parts["窓（FIX・クアッド）"][1] - 8.40) < 1e-6 and parts["窓（FIX・クアッド）"][2] == 0.65
    assert 0.2085 <= env["UA"] <= 0.2115, env["UA"]            # v4.41: 外皮が縮み窓の比率が増えて 0.2100→0.2107
    o = _ops(h)
    assert SS.op_g(h, o["AW-LS"]) == 0.40 and SS.op_g(h, o["AW-LW"]) == 0.25
    for op in h.openings(exterior=True):
        if op.kind == "window" and op.label not in q["labels"]:
            assert SS.op_g(h, op) == SS.glazing_g(h, op.side)
    assert abs(sum(SS.window_solar(h)["glass"].values()) - 18.56) < 0.01      # v4.42: 居室E の西窓 1.28m² を廃止 19.84→18.56。v4.41: 居室D の窓 W1,600→1,200 で 20.16→19.84         # 実面積（等価面積ではない）


def test_local_thickness_geometry():
    h = house()
    ext = [b for b in h.boxes if b.tag == "増し打ち"]
    assert ext and all(b.level == "1F" for b in ext)
    assert abs(h.ldk.area - 33.639375) < 1e-6


def test_cg_1400_shading():
    """内装CG 3/21 14:00: 南面は庇で全面が日陰、西面は下端だけ日なた。sightshade の真太陽時 14:00 と ±1.5° 以内。"""
    import math
    import yaml
    import render_cg as RC
    import sightshade as SS

    h = house()
    spec = yaml.safe_load((ROOT / "spec.yaml").read_text(encoding="utf-8"))
    cuts = spec["interior_cg"]["cuts"]
    for k in ("I01", "I02", "I03", "I14"):
        assert cuts[k]["when"] == "2026-03-21T14:00", k
    assert cuts["I02"]["file"] == "I02_ldk_kitchen_side"
    site = spec["smart"]["site"] if "smart" in spec and "site" in spec["smart"] else None
    lat, lon, tz = (site["lat"], site["lon"], site["tz"]) if site else (35.667, 139.36, 9)
    alt, az = RC.sun_position("2026-03-21T14:00", lat, lon, tz)
    ops = _ops(h)
    gam = h.facade_az

    def shade(a, z, side):
        n = 180 + gam if side == "S" else 270 + gam           # 面の法線方位（真北から時計回り）
        c = math.cos(math.radians(z - n))
        P = {"S": 2120, "W": 1120}[side]
        return P * math.tan(math.radians(a)) / c - 200

    Hw = 2000
    assert shade(alt, az, "S") >= Hw
    assert shade(alt, az, "W") < Hw
    # sightshade（3/22・真太陽時 14:00）との照合
    phi = math.radians(SS.LAT)
    n = 21 + int(30.4 * 2)
    d = math.radians(23.45 * math.sin(math.radians(360 * (284 + n) / 365)))
    H = math.radians(15 * 2)
    a2 = math.degrees(math.asin(math.sin(phi) * math.sin(d) + math.cos(phi) * math.cos(d) * math.cos(H)))
    z2 = (math.degrees(math.atan2(math.sin(H), math.cos(H) * math.sin(phi) - math.tan(d) * math.cos(phi))) + 180) % 360
    assert abs(alt - a2) <= 1.5, (alt, a2)
    assert abs(az - z2) <= 3.0, (az, z2)   # 14:00 JST は真太陽時 14:10 ごろ（方位は 2.5° 動く）


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
