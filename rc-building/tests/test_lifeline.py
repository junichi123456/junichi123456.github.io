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
    assert abs(en["pv_kwp"] - 37.29) < 0.01 and abs(en["pv_gen"] - 38786) < 5       # v4.43: 38,775→38,786（建物の縮小で影損失が減る）。v4.41: 38,764→38,775
    assert abs(en["rz_kwp"] - 41.0) < 0.1 and abs(en["rz_gen"] - 41773) < 100
    assert abs(en["pv_kwp_ext"] - 78.3) < 0.1 and abs(en["pv_gen_ext"] - 80558) < 100


def test_battery_sizing():
    c = _get()
    bs, h = c["bs"], c["h"]
    r = bs["rows"]
    assert abs(bs["factor"] - 0.684) < 1e-9
    # v4.43: 建物の縮小（延べ −11.3%）で日負荷がさらに減る。A 57.8→55.0、B 85.0→84.5（C・D の防災・停電モードは不変）。v4.41: A 60.6→57.8、B 85.5→85.0
    assert abs(r["A"]["kwh"] - 55.0) < 0.3 and abs(r["B"]["kwh"] - 84.5) < 0.3 and abs(r["C"]["kwh"] - 18.5) < 0.01 and abs(r["D"]["kwh"] - 10.5) < 0.01
    assert abs(r["A"]["nominal"] - 562) < 4 and abs(r["B"]["nominal"] - 865) < 4 and abs(r["C"]["nominal"] - 198) < 2
    assert h.spec["battery"]["nominal_kwh"] >= r["C"]["nominal"]
    assert abs(bs["days_eol"] - 7.39) < 0.05 and abs(bs["days_new"] - 9.73) < 0.05 and bs["days_eol_net"] >= 7.0
    a = bs["autonomy"]
    assert a[("C", "ext")]["cloudy"] is None and 28 < a[("C", "now")]["cloudy"] < 30
    assert 8.4 < a[("B", "now")]["avg"] < 9.0 and 1.8 < a[("B", "now")]["cloudy"] < 2.1      # v4.43: 8.7（負荷の減少）。v4.41: 8.1→8.4


def test_legal_rows():
    c = _get()
    items = {r["item"]: r for r in c["rows"]}
    assert sum(r["result"] == house_legal.NG for r in c["rows"]) == 0
    for k in ("蓄電池（理論上1週間）", "建ぺい率（予約ゾーンを満たした場合・参考）", "蓄電池の届出・位置構造", "電気工作物の区分・系統連系（逆潮流なし）", "太陽光の全量自家消費（逆潮流なし）", "汚水管 勾配（φ150）"):
        assert k in items, k
    assert items["蓄電池の届出・位置構造"]["result"] == house_legal.CHK
    k = "電気工作物の区分・系統連系（逆潮流なし）"
    assert items[k]["result"] == house_legal.CHK and "RPR" in items[k]["planned"]
    assert items["太陽光の全量自家消費（逆潮流なし）"]["result"] == house_legal.OK
    assert len(c["rows"]) == 150      # v4.44: −2（2階 書庫の可燃物・警報器、書庫の積載荷重を削除）。v4.43: +1（シアター↔居室D の遮音）
    assert sum(r["result"] == house_legal.CHK for r in c["rows"]) == 38    # v4.44: 42→38（書庫 2 行・避難室・2階 水回りの読み替え）
    assert "29.99%" in items["建ぺい率（予約ゾーンを満たした場合・参考）"]["planned"], items["建ぺい率（予約ゾーンを満たした場合・参考）"]["planned"]
    assert "32.36%" in items["建ぺい率（予約ゾーンを満たした場合・参考）"]["planned"]      # v4.43: 建築面積 312.54→279.04m² で 31.37/33.74 → 29.99/32.36。v4.41: 35.21/32.83 → 31.37/33.74（RZ-a のみ／RZ 全体の表記順）


def test_self_consumption():
    c = _get(); h, en, bs = c["h"], c["en"], c["bs"]
    sc = PF.self_consumption(h, en, bs)
    assert abs(sc["gen"] - en["pv_gen"]) < 5 and abs(sc["load"] - en["total"]) < 5
    assert abs(sc["self"] + sc["grid"] - en["total"]) < 5                 # 需要＝自家消費＋買電
    assert abs(sc["self"] - 14216) < 30 and abs(sc["curtail"] - 24063) < 50 and abs(sc["grid"] - 4774) < 30      # v4.46: 需要 18,895→18,989kWh（窓 +7.56m²）     # v4.44: 需要 18,919→18,895kWh（南窓の拡大・2F 水回りの削減）。v4.43: 18,919
    assert 0.36 < sc["sc_rate"] < 0.37 and 0.74 < sc["ss_rate"] < 0.76 and 30.6 < sc["peak_surplus"] < 31.0
    assert abs(sc["reserve"] - 142.7) < 0.1 and abs(sc["band"] - 37.3) < 0.1
    e = PF.self_consumption(h, en, bs, eol=True)
    assert abs(e["band"] - 1.3) < 0.1 and abs(e["self"] - 8971) < 30 and abs(e["grid"] - 10018) < 30
    assert len(sc["months"]) == 12 and abs(sum(m["self"] for m in sc["months"]) - sc["self"]) < 5
    assert sc["months"][11]["gen"] < sc["months"][11]["load"] and sc["months"][4]["curtail"] > 3000   # 12月は不足、5月は抑制
    ps = h.spec["pv_self"]["pcs_kw"]
    assert abs(sum(ps.values()) - h.spec["pv_reserve"]["pcs_limit_kw"]) < 1e-9 and h.spec["pv_self"]["export"] == "none"
    assert bs["days_eol_net"] >= 7.0                                      # 停電7日は不変


def test_battery_room():
    from shapely.geometry import box as sbox
    c = _get()
    h = c["h"]
    x0, y0, x1, y1 = h.battery_room.rect
    # v4.46（施主画像）: 蓄電室はジム北端の E-M 区画（Y2〜Y3）へ移設。「1 階南半分（D/2＋500）」の判定は E-M 区画に読み替え（要確認）
    assert y0 >= h.gy[1] and y1 <= h.gy[2] and abs(h.D / 2 - 8125) < 1, (y0, y1, h.D)
    assert sbox(*h.gym.rect).buffer(150).intersects(sbox(*h.battery_room.rect)) and not sbox(*h.gym.rect).intersects(sbox(x0 + 1, y0 + 1, x1, y1))
    assert abs(h.battery_room.area - 4.30) < 0.05                       # v4.46: 内法 2,150×2,000（v4.45 4.17）
    assert h.gym.area >= 43.0 and abs(h.gym.area - 43.34) < 0.05, h.gym.area     # v4.46: 5,175×8,475（−増し打ち帯）。拡張部込みで 50.33（v4.45 51.76 の −2.8%）
    assert h.gym.daylight_area >= 51.76 * 0.95 and abs(h.gym.daylight_area - 50.33) < 0.05   # v4.46 拡張部 6.99m² 込み
    room = sbox(x0, y0, x1, y1)
    for name, r, hh, kg in h.equipment:
        assert not sbox(*r).intersects(room), name
    # 扉の開き範囲（ジム側＝南へ W900）に機器がない
    d = h.battery_door
    sw = sbox(d.u0, y0 - h.pt / 2 - d.width, d.u1, y0 - h.pt / 2)
    for name, r, hh, kg in h.equipment:
        assert not sbox(*r).intersects(sw), name
    cc = {n: r for n, r, *_ in h.equipment}["ケーブルクロスオーバー"]
    assert cc[2] == 16075 and cc[1] == 2300     # v4.46: E 壁沿いに縦（E-S）。機械室・蓄電室から遠ざける
    assert x1 == 16125                                   # v4.43: 東外壁の内面（旧 17,125）


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
    b = __import__("shapely.geometry", fromlist=["box"]).box(*h.battery_room.rect)
    mr_ = next(r for r in h.rooms if r.name == "機械室" and r.floor == "1F")
    assert mr_.rect[0] <= x <= mr_.rect[2] and mr_.rect[1] <= y <= mr_.rect[3] and Point(x, y).distance(b) < 5500      # v4.46: 主分電盤は機械室（蓄電室の西隣）、配線 約 3m。v4.44: 機械室（東）が蓄電室の真北（Y3 の向こう）へ移り、配線 約5m（蓄電 PCS→主分電盤。旧 約1m）


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
    assert rows == 16 and circ == 16, (rows, circ)         # v4.40: さや管・点検桝の番号を追加（15→16）
    # 基準表: 条項の断定を避ける。要確認・推定の語が各条項行に含まれる
    t2 = " ".join(e.dxf.text for e in sz2.msp if e.dxftype() == "TEXT")
    assert t2.count("要確認") >= 10 and "推定" in t2


# v4.25 で更新: 間仕切り x10,600 t200（S 壁まで）・②撤去・室内窓・X3 開口 W4,835・浴室壁 t200・居室A／WIC の区画・玄関土間の縮小（意図した変更）
GLB_V422 = ("d6f93ec9f9818a9a", "0f7fb342bd52ff0d")      # v4.46 意図した変更: 施主の書き込みに寄せた間取り・窓・家具・機械室（直前 80ddb433cc990ce4／581a07d59ffa5b81）。# v4.45 意図した変更: 1F トイレ撤去・キッチン縮小・接続開口 4.3m・2F 多目的ホールの分割・家具・照明・配管（直前 f8b0d7d0c327d551／450b0be7a978b1e5）。# v4.44 意図した変更: 通り芯の均等化・室構成の見直し
_OLD_GLB = ("4acf124d2dff7667", "2fd58dda4c84e612")      # v4.43 意図した変更: 壁芯 16.25m 角（5.90/4.45/5.90・6.125/6.0/4.125）・1F の居室A/WIC/FC の廃止・2F の寝室 5 室・書庫・収納の組み替え・窓の増減・階段幅 950・家具・照明の移動（直前 7482a9e1d0f1a029／60d85e5b8bcd9166）。# v4.42 意図した変更: 居室E の書庫化（西窓・LGS・引戸の廃止、書架）（直前 9ea0292c4c6449b7／596e779e483bbf8c）。# v4.41 意図した変更: 壁芯 17.25m 角への縮小・北の行と中央列の組み替え・玄関ポーチ・目隠し壁・ジム機器の x −1,000（直前 ab57e0f8e2c78731／e2518d1a42292423）。# v4.40 意図した変更: FDN の外の扉の撤去・人通口 12・駐車場の舗装（西端 12,800・面取り）と菜園（東へ 700）・管路帯・インターロッキング・ボラード 2 基・PS 3・点検口の目地（直前 5f0b725a4ab51e83／6b47dad692c98805）。# v4.38 意図した変更: 西窓 u1,900〜4,000・C1/C2 の吹出し廃止・収納の扉の目地・H-S3 の台輪（直前 c51c8601220f3a43／7eceaa47eadc4f2b）。# v4.37 意図した変更: 西窓 AW-LW・収納 4 点・L-K2 D825（直前 50f8ffbfacc3da67／28087fc12d73af16）。# v4.36 意図した変更: L 字窓の撤回（角柱・方立・西窓の撤去）・キッチンの L 字化・テーブルの北移動・L-K2・窓辺の収納（直前 b370081a3c3a0d20／0129d8bd899b1f7f）。# v4.35 意図した変更: テーブルの北移動・Y2 西端の袖壁の短縮・L-K1（直前 a34272db8aa00b43／902964e0b5bc695a）。# v4.29 意図した変更: 内装 GLB のみ（外観 GLB は不変）。内装の配色（壁を明るい壁と暗い壁に面ごとに塗り分け、蹴込み板 W5、床・天井・巾木の色）。直前: 1222daf2c09d58f7（段階1・3 は 8a24d25bf22dae70。段階4 で暗い壁を開口のない区間に置く変更）。  v4.28 段階2 意図した変更: 内装 GLB は 2階の脱衣所・居室E の仕上げ（床シート・壁パネル）と家具・照明の配置変更で変化（外観 GLB は段階1のまま）。段階1: 2階の部屋割り（居室E・脱衣所・トイレ・廊下・収納の分割）・扉の移設・北窓 AW-9。直前(v4.27): ("dba61049f6cebf79", "6fb2bc39bf8ad262")      # v4.27 意図した変更: 扉を x10,600 の u4,550〜5,750 へ移動（SSD-2 を塞ぎ IW-1 を撤去）・ジムの S・E 壁の増し打ち（local_thick を 3D が描く）・照明/機器の移動。直前: ("9263258e77804ac9", "1a5daf7157595946")      # v4.26: 室内 GLB はさらに、ジムの照明ラインから蓄電室の矩形を除いたため変化（外観 GLB は 9263258e…のまま）。 X3 の扉 D(9,300〜10,100) を RC で塞いだ意図した変更（旧 v4.25: 3f32bbe4…／a5956372…）。旧 v4.24: 739f6a23…／0d2f2ca3…。      # model.glb／model_interior.glb の SHA-256 先頭16桁。v4.22 は 9e2ddbd5…／66f2eabaf…。v4.24 で更新: ジム拡張部の LGS 間仕切り2本と式台の縮小（x12,000→10,500）が GLB に入るため（CG・3D の描画コードは不変）
# v4.25: 586→588（間仕切り②−1・y14,250−1・y14,650＋1・9,550 の分割＋1・室内窓＋1・x3 開口の分割など、実測）
A02X_COUNT = 611  # v4.46: 598→611（窓・扉・蓄電室の位置などの実測）。# v4.45: 596→598（扉の増減）。# v4.43: 599→589（建物外形 16.25m 角・窓の増減の実測）。# v4.41: 601→599（縮小に伴う実測）。# v4.40: 587→601（菜園の移動・舗装の外形・管路帯・さや管・点検桝・番号 16 ほかの実測値）。# v4.37: 582→587（西窓・収納 4 点）。# v4.36: 588→582（L 字窓の撤回ほか）。#                                          # v4.24: +2（ジム拡張部の間仕切り2本）。 v4.22 の 561 + 予約ゾーン（外形・点ハッチ・ラベル2）・蓄電室の塗り・番号3件・凡例2行 ほか
# v4.25: 471→474（間仕切り②−1・y14,250−1・y14,650＋1・9,550 の分割＋1・扉＋1−1・室内窓＋2 など、実測）
# v4.27: 520→525（搬入線の折れ点 +2 と S・E 壁 t300 の増し打ち線・寸法などの実測）
A03_COUNT = 573  # v4.46: 572→573（機械室・蓄電室の再配置と 1F 北東の寝室・廊下）。# v4.45: 554→572（廊下（西）・未割当・LGS・戸の増加、トイレの撤去）。# v4.43: 538→512（1F の居室A・WIC・FC の廃止、収納・納戸の組み替えの実測）。# v4.41: 529→538（北の行の室・扉・LGS の増減の実測）。# v4.37: 520→529（西窓 AW-LW・ZIP）。# v4.36: 528→520（角柱の円と注記・方立・西窓の撤去、KB-C2・L-K2 などの増減の実測値）。# v4.35: 526→528（袖壁の短縮と回遊①の折れ点）。# v4.32 意図した変更: 525→526（拡大詳細に「通信スリーブ SL-C は E-07」の 1 行）。                                          # v4.26 意図した変更: 474→520（離隔帯・搬入動線・機械室の扉3か所・スリーブ12・機器の詳細）。以前の内訳: # v4.22 の 411 + 蓄電室（間仕切り・扉・ラック・PCS・束壁・室名）と拡大詳細 52 = 463。v4.24: 463→471（+8。ジム拡張部の間仕切り2・移設した遮音ドア・拡張部の室名と面積・要確認の注記・框ラベルの移動、H-S1 撤去とマット移動を差し引いた実測値）


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
    assert abs(a.area - 6.99) < 0.01 and h.gym.daylight_area >= 51.76 * 0.95      # v4.46: 拡張部 1,350×5,175、ジム計 50.33（−2.8%）
    g = h.genkan
    for k in ("doma", "shikidai"):
        assert not sb(*a.rect).intersection(sb(*g[k])).area > 0, k
    hall = next(r for r in h.rooms if r.name == "ホール")
    assert not sb(*a.rect).intersection(sb(*hall.rect)).area > 0
    assert hall.rect[2] - 6700 >= 1300                       # H-S2 から間仕切りまで（通路 ≧1,300）
    assert (hall.rect[2] - hall.rect[0]) == 3125 and abs(hall.area - 9.06) < 0.01       # v4.44: 幅 3,125（玄関計 16.17m²＝v4.43 比 104%）
    gd2 = [op for w in h.walls for op in w.openings if "ガラス" in op.name and w.c == h.gy[1] and w.axis == "x" and w.floor == "1F"][0]
    assert (gd2.u0, gd2.u1) == (6225, 8475) and hall.rect[2] <= 9150 and h.spec["gym_annex"]["wall_x"] - h.spec["gym_annex"]["wall_t"] // 2 >= 9150     # v4.44: W2,250・間仕切り x9,250
    x3 = [op for w in h.walls if w.floor == "1F" and w.cat == "wall" and w.axis == "y" and w.c == h.gx[2] for op in w.openings if op.kind == "door" and op.u0 < 5000]
    assert [(o.u0, o.u1, o.height, o.operation) for o in x3] == [(815, 4850, 2300, "opening")]
    wq = house_legal.wall_quantity(h)
    assert abs(wq[("1F", "X方向")][1] - 18.54) < 0.01 and abs(wq[("1F", "Y方向")][1] - 17.15) < 0.01     # v4.45: 19.19→18.23（Y2 W 列の袖壁 3,375→875）。v4.44: 17.86/18.71 → 19.19/18.33（均等な通り芯・開口の組み替え）
    import performance as PF
    se = PF.seismic(h)["stories"]
    assert max(v["ecc"] for v in se.values()) <= 0.15 and abs(se[("1F", "Y方向")]["ecc"] - 0.1345) < 0.001 and abs(se[("1F", "X方向")]["ecc"] - 0.0265) < 0.001      # v4.44: 0.056/0.000（2F X 0.107 が最大）


def test_gym_annex_lighting_name():
    """名前の対応: 拡張部は GYM（500lx）で、「ホール」を含まない（HAL にならない）。"""
    import lighting
    h = _get()["h"]
    assert "ホール" not in h.gym_annex.name
    assert lighting.room_code(h, h.gym_annex) == "GYM" and lighting.target_lx(h, h.gym_annex.name) == lighting.target_lx(h, "ジム")
    assert lighting.ceiling_z(h, h.gym_annex) == h.fl["1F"] + h.ch["1F"]            # 拡張部は CH2,800（直天井ではない）
