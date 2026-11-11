"""v4.32 館内 Wi-Fi・有線 LAN・水回りの電波抑制の試験。

    cd rc-building && python3 -m pytest tests/test_wifi.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from house import House  # noqa: E402
import wifi as WF  # noqa: E402


@pytest.fixture(scope="module")
def h():
    return House(ROOT)


@pytest.fixture(scope="module")
def stats(h):
    return WF.room_stats(h)


def _sel(stats, cls):
    return [s for s in stats if s["cls"] == cls]


def test_room_counts(stats):
    """上質 12 室・水回り 9 室（spec の分類が実在の室と対応している）。"""
    assert len(_sel(stats, "premium")) == 12 and len(_sel(stats, "quiet")) == 9


def test_premium_rooms_fully_covered(h, stats):
    """上質 12 室: 床面の 100% が -55dBm 以上（計算の目標。竣工時の実測は -60 以上）。"""
    for s in _sel(stats, "premium"):
        assert s["min"] >= h.spec["wifi"]["premium"]["dbm"], (s["floor"], s["name"], s["min"])
        assert s["c55"] == 1.0


def test_quiet_rooms_suppressed(h, stats):
    """水回り 9 室: 中央値 -70〜-65・上位 10% 値 ≦ -62・最小 ≧ -75（悪くするが、切りはしない）。"""
    q = h.spec["wifi"]["quiet"]
    for s in _sel(stats, "quiet"):
        k = (s["floor"], s["name"])
        assert q["median"][0] <= s["med"] <= q["median"][1], (k, s["med"])
        assert s["p90"] <= q["p90_max"], (k, s["p90"])
        assert s["min"] >= q["min"], (k, s["min"])


def test_general_rooms(h, stats):
    """一般: -67 以上が各階 90% 以上・全点 -75 以上。"""
    sm = WF.summarize(stats, h.spec["wifi"])
    assert sm["general_cover_1F"] >= 0.90 and sm["general_cover_2F"] >= 0.90
    assert sm["general_min"] >= -75


def test_eirp_range_and_counts(h):
    aps = h.spec["wifi"]["aps"]
    lo, hi = h.spec["wifi"]["eirp_range"]
    assert (lo, hi) == (6, 20) and len(aps) == 16
    assert all(lo <= a["eirp"] <= hi and float(a["eirp"]).is_integer() for a in aps)
    assert sum(a["floor"] == "1F" for a in aps) == 7 and sum(a["floor"] == "2F" for a in aps) == 9


def test_no_ap_in_wet_areas(h):
    """水回りと、水回りブロック内の廊下には AP（予備の alt_xy も）を置かない。"""
    w = h.spec["wifi"]
    wet = [r for r in h.rooms if WF.room_class(w, f"{r.floor} {r.name}") == "quiet"]
    corr = {"1F": (9600, 12250, 12000, 15500), "2F": (6250, 12250, 12000, 13700)}
    for a in w["aps"]:
        for key in ("xy", "alt_xy"):
            if key not in a:
                continue
            x, y = a[key]
            for r in wet:
                if r.floor == a["floor"]:
                    assert not (r.rect[0] <= x <= r.rect[2] and r.rect[1] <= y <= r.rect[3]), (a["id"], r.name)
            c = corr[a["floor"]]
            assert not (c[0] <= x <= c[2] and c[1] <= y <= c[3]), (a["id"], "wet corridor")


def test_slab_and_distance_terms(h):
    """モデルの項: 上下階の AP はスラブ 30dB を加え、距離は 3 次元。"""
    import numpy as np
    M = WF.Model(h)
    p = np.array([[3250.0, 3250.0]])
    same = M.rssi(dict(floor="1F", xy=(3250, 3250), eirp=10), "1F", p)[0]
    up = M.rssi(dict(floor="2F", xy=(3250, 3250), eirp=10), "1F", p)[0]
    assert same - up > 30 and same > up
    # 同じ平面位置でも高さ差 dz=1600 の 3D 距離（自由空間）で効く
    assert abs(same - (10 - WF._pl(1.6, 5500))) < 1e-6


def _sheet_layout_ok(sh):
    """枠内（内枠）・表題欄に文字がかからない・文字どうしが重ならない。"""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_site_integrated import paper_boxes, INNER, TITLE
    bx = paper_boxes(sh)
    for e, ly, b in bx:
        assert b[0] >= INNER[0] - 0.01 and b[1] >= INNER[1] - 0.01 and b[2] <= INNER[2] + 0.01 and b[3] <= INNER[3] + 0.01, (e.dxftype(), b)
    tx = [(e.dxf.text, b) for e, ly, b in bx if e.dxftype() == "TEXT"]
    for t, b in tx:
        assert not (b[2] > TITLE[0] and b[0] < TITLE[2] and b[3] > TITLE[1] and b[1] < TITLE[3]), t
    for i in range(len(tx)):
        for j in range(i + 1, len(tx)):
            a, b = tx[i][1], tx[j][1]
            assert not (min(a[2], b[2]) - max(a[0], b[0]) > 0.3 and min(a[3], b[3]) - max(a[1], b[1]) > 0.3), (tx[i][0], tx[j][0])


def test_e01_layout(h):
    import house_sheets as hs
    _sheet_layout_ok(hs.wifi_sheet(h, "E-01"))


# ---------------------------------------------------------------- 段階3: 有線 LAN・配線・スリーブ
def test_wiring_plan_consistent(h):
    import wiring as WR
    assert WR.check(h) == []


def test_cable_lengths_and_wet_rooms(h):
    """全経路 90m 以内。天井内の幹線は水回りの室を通らない。"""
    import wiring as WR
    from shapely.geometry import LineString, box
    for r in WR.routes(h):
        assert r["length_m"] <= h.spec["wifi"]["cable"]["max_m"], r["id"]
        for f, rc in WR.wet_rects(h):
            if f == r["floor"]:
                assert not LineString(r["path"]).intersects(box(*rc).buffer(-1)), (r["id"], rc)


def test_lan_outlets(h):
    """計 21 口。居室A〜E・リビング・シアターの 7 室に 2 口以上・FL+300 以上（床コンセントなし）。水回りには置かない。"""
    import wiring as WR
    os_ = h.spec["wifi"]["lan_outlets"]
    assert WR.lan_total(h) == 21
    per = {}
    for o in os_:
        assert o["z"] >= 300
        per[(o["floor"], o["room"])] = per.get((o["floor"], o["room"]), 0) + o["n"]
    assert sorted(f"{k[0]} {k[1]}" for k, v in per.items() if v >= 2) == sorted(h.spec["wifi"]["premium"]["wired"])
    assert len(per) == 7


def test_rack_and_poe(h):
    """ラックは機械室（東系統）MC-6 内。PoE 負荷は給電の範囲内。スリーブ SL-C1〜C14。"""
    import wiring as WR
    w = h.spec["wifi"]
    mc6 = next(e for e in h.spec["mech_rooms"]["equipment"] if e[0] == "MC-6")
    x0, y0, x1, y1 = mc6[3]
    assert x0 <= w["rack"]["xy"][0] <= x1 and y0 <= w["rack"]["xy"][1] <= y1
    assert WR.poe_load_w(h) <= w["rack"]["poe_budget_w"]
    assert len(w["sleeves"]) == 12 and len(WR.sleeve_pairs(h)) == 12
    assert w["riser"]["n"] == 4 and w["riser"]["spare"] == 2


def test_e07_layout(h):
    import wiring_sheets as ws
    _sheet_layout_ok(ws.wiring_sheet(h, "E-07"))
