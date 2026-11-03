"""v4.23 ライフライン・蓄電室・ソーラー予約ゾーン・雨水貯留槽の受け入れ試験（House を1回だけ構築する）。

    python3 tests/test_lifeline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import house_legal  # noqa: E402
import performance as PF  # noqa: E402
from house import House  # noqa: E402

_C = {}


def _get():
    if not _C:
        h = House(ROOT)
        rows, sm, _ = house_legal.checks(h)
        en = PF.energy(h, PF.heat_load(h))
        _C.update(h=h, rows=rows, sm=sm, en=en, bs=PF.battery_sizing(h, en))
    return _C


def test_pv_reserve_zone():
    c = _get()
    h = c["h"]
    rz = h.pv_reserve
    assert abs(rz.area / 1e6 - 272.5) < 0.2, rz.area / 1e6
    assert abs(h.pv_reserve_a.area / 1e6 - 214.9) < 0.2 and abs(h.pv_reserve_b.area / 1e6 - 57.6) < 0.2
    # 塀内面からの距離は 1,300 以上（誤差 1mm）
    inner = h.fence_poly.buffer(-h.fence_t)
    assert inner.exterior.distance(rz) >= 1300 - 1, inner.exterior.distance(rz)
    assert rz.bounds[2] <= -9000 + 1 and rz.bounds[3] <= 11000 + 1


def test_pv_numbers():
    en = _get()["en"]
    assert abs(en["pv_kwp"] - 37.29) < 0.01 and abs(en["pv_gen"] - 38764) < 5
    assert abs(en["rz_kwp"] - 41.0) < 0.1 and abs(en["rz_gen"] - 41800) < 100
    assert abs(en["pv_kwp_ext"] - 78.3) < 0.1 and abs(en["pv_gen_ext"] - 80500) < 100


def test_battery_sizing():
    c = _get()
    bs, h = c["bs"], c["h"]
    r = bs["rows"]
    assert abs(bs["factor"] - 0.684) < 1e-9
    assert abs(r["A"]["kwh"] - 60.6) < 0.3 and abs(r["B"]["kwh"] - 85.5) < 0.3 and abs(r["C"]["kwh"] - 18.5) < 0.01 and abs(r["D"]["kwh"] - 10.5) < 0.01
    assert abs(r["A"]["nominal"] - 620) < 4 and abs(r["B"]["nominal"] - 876) < 4 and abs(r["C"]["nominal"] - 199) < 2
    assert h.spec["battery"]["nominal_kwh"] >= r["C"]["nominal"]
    assert abs(bs["days_eol"] - 7.4) < 0.05 and abs(bs["days_new"] - 9.7) < 0.05 and bs["days_eol_net"] >= 7.0
    a = bs["autonomy"]
    assert a[("C", "ext")]["cloudy"] is None and 28 < a[("C", "now")]["cloudy"] < 30
    assert 7.9 < a[("B", "now")]["avg"] < 8.3 and 1.8 < a[("B", "now")]["cloudy"] < 2.0


def test_legal_rows():
    c = _get()
    items = {r["item"]: r for r in c["rows"]}
    assert sum(r["result"] == house_legal.NG for r in c["rows"]) == 0
    for k in ("蓄電池（理論上1週間）", "建ぺい率（予約ゾーンを満たした場合・参考）", "蓄電池の届出・位置構造", "電気工作物の区分・低圧連系（拡張後）", "汚水管 勾配（φ150）"):
        assert k in items, k
    assert items["蓄電池の届出・位置構造"]["result"] == house_legal.CHK
    assert "35.21%" in items["建ぺい率（予約ゾーンを満たした場合・参考）"]["planned"], items["建ぺい率（予約ゾーンを満たした場合・参考）"]["planned"]
    assert "32.83%" in items["建ぺい率（予約ゾーンを満たした場合・参考）"]["planned"]


def test_battery_room():
    from shapely.geometry import box as sbox
    c = _get()
    h = c["h"]
    x0, y0, x1, y1 = h.battery_room.rect
    assert y1 <= h.D / 2 + 1 and abs(h.D / 2 - 9125) < 1, (y1, h.D)           # 南半分（建物中心 y=9,125 以下）
    assert sbox(*h.gym.rect).contains(sbox(*h.battery_room.rect))
    assert abs(h.battery_room.area - 4.6) < 0.1
    assert h.gym.area >= 44.85 and abs(h.gym.area - 46.3) < 0.1, h.gym.area
    room = sbox(x0, y0, x1, y1)
    for name, r, hh, kg in h.equipment:
        assert not sbox(*r).intersects(room), name
    # 扉の開き範囲（ジム側 W900）に機器がない
    d = h.battery_door
    sw = sbox(x0 - d.width, d.u0, x0, d.u1)
    for name, r, hh, kg in h.equipment:
        assert not sbox(*r).intersects(sw), name
    cc = {n: r for n, r, *_ in h.equipment}["ケーブルクロスオーバー"]
    assert cc[0] == 12500 and cc[2] == 16000
    # 機械室と同じ南半分の外（機械室は北）、換気用に東外壁に面する
    assert x1 == 18125


def test_cg_and_3d_unchanged():
    """CG・3D は変えない: 蓄電室・機器移動は h.rooms／h.walls／3D 用機器配置に入れない。glb のハッシュが v4.22 と一致。"""
    import hashlib
    import tempfile
    from model3d import export_glb
    h = _get()["h"]
    assert all(r.name != "蓄電室" for r in h.rooms) and not any(w in h.walls for w in h.battery_walls)
    with tempfile.TemporaryDirectory() as d:
        export_glb(h, Path(d) / "a.glb")
        export_glb(h, Path(d) / "b.glb", interior=True)
        ha = hashlib.sha256((Path(d) / "a.glb").read_bytes()).hexdigest()[:16]
        hb = hashlib.sha256((Path(d) / "b.glb").read_bytes()).hexdigest()[:16]
    assert (ha, hb) == GLB_V422, (ha, hb)


def test_a03_count():
    import house_sheets as hs
    h = _get()["h"]
    assert len(list(hs.floor_plan(h, "1F", "A-03").msp)) == A03_COUNT


GLB_V422 = ("9e2ddbd5bb59a2af", "66f2eabaf1603679")      # v4.22 の model.glb／model_interior.glb の SHA-256 先頭16桁
A03_COUNT = 463                                            # v4.22 の 411 + 蓄電室（間仕切り・扉・ラック・PCS・束壁・室名）と拡大詳細 52


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            n += 1
            print("ok", k)
    print(f"{n} tests passed")
