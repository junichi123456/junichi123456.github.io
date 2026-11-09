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
    assert abs(h.battery_room.area - 4.7) < 0.05
    assert h.gym.area >= 44.85 and abs(h.gym.area - 45.76) < 0.05, h.gym.area
    assert h.gym.daylight_area >= h.spec["battery"]["gym_target_m2"] and abs(h.gym.daylight_area - 53.40) < 0.05   # v4.25 拡張部 7.64m² 込み
    room = sbox(x0, y0, x1, y1)
    for name, r, hh, kg in h.equipment:
        assert not sbox(*r).intersects(room), name
    # 扉の開き範囲（ジム側 W900）に機器がない
    d = h.battery_door
    sw = sbox(x0 - d.width, d.u0, x0, d.u1)
    for name, r, hh, kg in h.equipment:
        assert not sbox(*r).intersects(sw), name
    cc = {n: r for n, r, *_ in h.equipment}["ケーブルクロスオーバー"]
    assert cc[0] == 12300 and cc[2] == 15400   # v4.26 W3,100（蓄電室との離隔 800）
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


def test_tank_and_reserve():
    from shapely.geometry import Point
    h = _get()["h"]
    tk = h.tank_poly()
    assert tk.intersection(h.cliff_zone).area == 0 and tk.distance(h.cliff_zone) >= 5000, tk.distance(h.cliff_zone)   # がけ2H範囲から5m 以上
    assert not tk.intersects(h.pv_reserve)
    assert abs(tk.area / 1e6 - 25) < 0.01 and h.fence_poly.buffer(-h.fence_t).contains(tk)
    px0, py0, px1, py1 = h.pergola
    assert px0 <= h.tank[0] and h.tank[2] <= px1 and py0 <= h.tank[1] and h.tank[3] <= py1      # パーゴラの下
    assert h.tank_poly().distance(Point(-11000, 16500)) < 1                                      # 流入口は槽の東辺
    # 中木 M1〜M3 は RZ の外
    for p in h.plants:
        if p["id"] in ("M1", "M2", "M3"):
            assert not h.pv_reserve.buffer(p["crown"] / 2).intersects(Point(p["xy"])), p["id"]
    # 越流経路の始点は槽の縁
    assert tk.distance(Point(*h.spec["utilities"]["storm"]["west_over"][0])) < 1


def test_reserve_foundations():
    from shapely.geometry import LineString, Point
    h = _get()["h"]
    fs = h.pv_reserve_foundations
    assert len(fs) >= 3
    spare = LineString(h.spec["lifeline"]["power"]["pv_reserve_spare"])
    for x, y in fs:
        p = Point(x, y)
        assert h.pv_reserve.contains(p) and not h.pipe_zone.contains(p) and p.distance(spare) >= 1000 and h.tank_poly().distance(p) >= 1000


def test_a02x_count():
    import house_sheets as hs
    c = _get()
    assert len(list(hs.site_integrated(c["h"], "A-02X", c["sm"]).msp)) == A02X_COUNT


def _lines(h):
    from shapely.geometry import LineString
    ll = h.spec["lifeline"]
    pw = ll["power"]
    pipes = {"water": h.pipes["water"], "sewer": h.pipes["sewer"], "storm": h.pipes["storm_w"] + h.pipes["storm_e"]}
    return dict(trunk=LineString(pw["trunk"]), comm=LineString(ll["comm"]["line"]), pv=LineString(pw["pv_pergola"]),
                spare=LineString(pw["pv_reserve_spare"])), pipes


def test_lifeline_inside_boundary():
    from shapely.geometry import Point
    h = _get()["h"]
    ll = h.spec["lifeline"]["power"]
    site = h.site.buffer(5)                         # 道路境界上の引込点は境界線上
    lines, _ = _lines(h)
    for k, g in lines.items():
        assert site.contains(g), k
    pts = [tuple(ll["entry"])] + [tuple(p) for p in ll["hh"]] + [tuple(ll["pv_reserve_hh"])] + [tuple(v) for v in ll["pcs"].values()] + [tuple(v) for v in ll["panels"].values()] \
        + [tuple(ll["switchboard"][:2]), tuple(ll["switchboard"][2:])]
    for p in pts:
        assert site.contains(Point(p)), p
        assert not h.donation_poly.buffer(-10).contains(Point(p)), p       # 寄付地に設備なし
    for g in list(lines.values()):
        assert g.intersection(h.donation_poly.buffer(-10)).is_empty
    for gs in _lines(h)[1].values():
        for g in gs:
            assert g.intersection(h.donation_poly.buffer(-10)).is_empty


def test_power_clearances():
    """電力と通信・水・汚水・雨水の離隔 >= 300（交差は点で交わるだけ＝上下 0.3m を図に明記）。"""
    from shapely.geometry import Point
    h = _get()["h"]
    lines, pipes = _lines(h)
    power = [lines["trunk"], lines["pv"], lines["spare"]]
    others = [lines["comm"]] + [g for gs in pipes.values() for g in gs]
    for pw_ in power:
        for o in others:
            inter = pw_.intersection(o)
            if inter.is_empty:
                assert pw_.distance(o) >= 300, (pw_.wkt[:40], o.wkt[:40], pw_.distance(o))
            else:
                assert inter.geom_type == "Point", "並走して重なる"
    # 通信は電力から 300 離す（同溝・別管）
    from shapely.geometry import LineString
    assert lines["comm"].distance(lines["trunk"]) >= 299


def test_battery_room_distance_to_panels():
    from shapely.geometry import Point
    h = _get()["h"]
    x, y = h.spec["lifeline"]["power"]["panels"]["main"]
    assert Point(x, y).distance(__import__("shapely.geometry", fromlist=["box"]).box(*h.battery_room.rect)) < 1500   # 配線 約1m


def _sheet_problems(sh):
    import test_site_integrated as T
    bad = []
    tb = []
    for e, ly, (x0, y0, x1, y1) in T.paper_boxes(sh):
        if x0 < T.INNER[0] - 0.01 or y0 < T.INNER[1] - 0.01 or x1 > T.INNER[2] + 0.01 or y1 > T.INNER[3] + 0.01:
            bad.append((ly, "枠外"))
        elif x0 < T.TITLE[2] and x1 > T.TITLE[0] and y0 < T.TITLE[3] and y1 > T.TITLE[1]:
            bad.append((ly, "表題欄"))
        if e.dxftype() == "TEXT":
            tb.append((x0, y0, x1, y1, e.dxf.text))
    return bad, tb


def test_lifeline_sheets():
    import house_sheets as hs
    from cadlib import LAYERS
    h = _get()["h"]
    sz = hs.lifeline_sheet(h, "A-02Z")
    sz2 = hs.lifeline_tables(h, "A-02Z2")
    used = {e.dxf.layer for e in sz.msp}
    for need in ("E-POWER", "E-COMM", "E-PV", "E-SPARE", "E-BATT", "A-PVRES", "E-WATER", "E-SEWER", "A-DRAIN", "A-DONATE"):
        assert need in used, need
    assert not (used - set(LAYERS))
    for sh in (sz, sz2):
        bad, tb = _sheet_problems(sh)
        assert not bad, bad[:5]
    texts = [e.dxf.text for e in sz.msp if e.dxftype() == "TEXT"]
    assert any("ガス引込なし" in t for t in texts)
    # 番号表と番号丸の数が一致
    rows = len(sz.last_table_rows) - 1
    circ = sum(1 for e in sz.msp if e.dxftype() == "CIRCLE" and e.dxf.layer == "A-SYMB" and abs(e.dxf.radius / sz.S - 1.5) < 1e-6)
    assert rows == 15 and circ == 15, (rows, circ)
    # 基準表: 条項の断定を避ける。要確認・推定の語が各条項行に含まれる
    t2 = " ".join(e.dxf.text for e in sz2.msp if e.dxftype() == "TEXT")
    assert t2.count("要確認") >= 10 and "推定" in t2


# v4.25 で更新: 間仕切り x10,600 t200（S 壁まで）・②撤去・室内窓・X3 開口 W4,835・浴室壁 t200・居室A／WIC の区画・玄関土間の縮小（意図した変更）
GLB_V422 = ("a34272db8aa00b43", "d3c8f2d7b583ec18")      # v4.28 段階1 意図した変更: 2階の部屋割り（居室E・脱衣所・トイレ・廊下・収納の分割）・扉の移設・北窓 AW-9。直前(v4.27): ("dba61049f6cebf79", "6fb2bc39bf8ad262")      # v4.27 意図した変更: 扉を x10,600 の u4,550〜5,750 へ移動（SSD-2 を塞ぎ IW-1 を撤去）・ジムの S・E 壁の増し打ち（local_thick を 3D が描く）・照明/機器の移動。直前: ("9263258e77804ac9", "1a5daf7157595946")      # v4.26: 室内 GLB はさらに、ジムの照明ラインから蓄電室の矩形を除いたため変化（外観 GLB は 9263258e…のまま）。 X3 の扉 D(9,300〜10,100) を RC で塞いだ意図した変更（旧 v4.25: 3f32bbe4…／a5956372…）。旧 v4.24: 739f6a23…／0d2f2ca3…。      # model.glb／model_interior.glb の SHA-256 先頭16桁。v4.22 は 9e2ddbd5…／66f2eabaf…。v4.24 で更新: ジム拡張部の LGS 間仕切り2本と式台の縮小（x12,000→10,500）が GLB に入るため（CG・3D の描画コードは不変）
# v4.25: 586→588（間仕切り②−1・y14,250−1・y14,650＋1・9,550 の分割＋1・室内窓＋1・x3 開口の分割など、実測）
A02X_COUNT = 588                                           # v4.24: +2（ジム拡張部の間仕切り2本）。 v4.22 の 561 + 予約ゾーン（外形・点ハッチ・ラベル2）・蓄電室の塗り・番号3件・凡例2行 ほか
# v4.25: 471→474（間仕切り②−1・y14,250−1・y14,650＋1・9,550 の分割＋1・扉＋1−1・室内窓＋2 など、実測）
# v4.27: 520→525（搬入線の折れ点 +2 と S・E 壁 t300 の増し打ち線・寸法などの実測）
A03_COUNT = 525                                            # v4.26 意図した変更: 474→520（離隔帯・搬入動線・機械室の扉3か所・スリーブ12・機器の詳細）。以前の内訳: # v4.22 の 411 + 蓄電室（間仕切り・扉・ラック・PCS・束壁・室名）と拡大詳細 52 = 463。v4.24: 463→471（+8。ジム拡張部の間仕切り2・移設した遮音ドア・拡張部の室名と面積・要確認の注記・框ラベルの移動、H-S1 撤去とマット移動を差し引いた実測値）


if __name__ == "__main__":
    n = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            v()
            n += 1
            print("ok", k)
    print(f"{n} tests passed")


def test_gym_annex_geometry_and_structure():
    """v4.25 ジム拡張部: 面積 7.64m²・重なり・通路・GD-2・X3 開口 W4,835（壁量 15.79・偏心率 ≦0.15）。"""
    from shapely.geometry import box as sb
    h = _get()["h"]
    a = h.gym_annex
    assert abs(a.area - 7.64) < 0.01 and h.gym.daylight_area >= 51.6
    g = h.genkan
    for k in ("doma", "shikidai"):
        assert not sb(*a.rect).intersection(sb(*g[k])).area > 0, k
    hall = next(r for r in h.rooms if r.name == "ホール")
    assert not sb(*a.rect).intersection(sb(*hall.rect)).area > 0
    assert hall.rect[2] - 6700 >= 1300                       # H-S2 から間仕切りまで（通路 ≧1,300）
    assert (hall.rect[2] - hall.rect[0]) == 4250 and abs(hall.area - 15.3) < 0.01
    gd2 = [op for w in h.walls for op in w.openings if "ガラス" in op.name and w.c == h.gy[1] and w.axis == "x" and w.floor == "1F"][0]
    assert (gd2.u0, gd2.u1) == (7500, 10500) and 10450 - 8975 == 1475 and hall.rect[2] <= 10500 and h.spec["gym_annex"]["wall_x"] - h.spec["gym_annex"]["wall_t"] // 2 >= 10500
    x3 = [op for w in h.walls if w.floor == "1F" and w.cat == "wall" and w.axis == "y" and w.c == h.gx[2] for op in w.openings if op.kind == "door" and op.u0 < 5000]
    assert [(o.u0, o.u1, o.height, o.operation) for o in x3] == [(815, 4850, 2300, "opening")]
    wq = house_legal.wall_quantity(h)
    assert abs(wq[("1F", "X方向")][1] - 16.00) < 0.01 and abs(wq[("1F", "Y方向")][1] - 16.27) < 0.01
    import performance as PF
    se = PF.seismic(h)["stories"]
    assert max(v["ecc"] for v in se.values()) <= 0.15 and abs(se[("1F", "Y方向")]["ecc"] - 0.040) < 0.001 and abs(se[("1F", "X方向")]["ecc"] - 0.108) < 0.001      # v4.27: 0.132/0.046 → 0.108/0.040（t300）


def test_gym_annex_lighting_name():
    """名前の対応: 拡張部は GYM（500lx）で、「ホール」を含まない（HAL にならない）。"""
    import lighting
    h = _get()["h"]
    assert "ホール" not in h.gym_annex.name
    assert lighting.room_code(h, h.gym_annex) == "GYM" and lighting.target_lx(h, h.gym_annex.name) == lighting.target_lx(h, "ジム")
    assert lighting.ceiling_z(h, h.gym_annex) == h.fl["1F"] + h.ch["1F"]            # 拡張部は CH2,800（直天井ではない）
