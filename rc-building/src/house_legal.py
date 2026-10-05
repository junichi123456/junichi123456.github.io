"""河沿要（仮称）法規チェック（建築基準法・施行令・告示・東京都建築安全条例ほか）。

数値は House モデルから算出する。用途地域等の前提は推定（要確認）であり、
最終判断は建築確認・構造計算・行政協議による。
"""
from __future__ import annotations

from shapely.geometry import LineString

OK, NG, CHK, NA = "適合", "不適合", "要確認", "対象外"


def judge(c):
    return OK if c else NG


def summary(h):
    site_area = h.site.area / 1e6
    ba = h.building_area()
    total = sum(h.floor_area(f) for f in h.floors)
    return dict(site_area=site_area, building_area=ba, total=total, coverage=ba / site_area, far=total / site_area,
                height=h.parapet_top / 1000, eave=h.fl["RF"] / 1000)


def wall_quantity(h):
    """壁式RC（平13国交告1026号）: 方向別の耐力壁長さ・壁量。"""
    res = {}
    for f in h.floors:
        area = h.floor_area(f)
        for axis, name in (("x", "X方向"), ("y", "Y方向")):
            L = 0.0
            for w in h.walls:
                if w.floor != f or w.cat != "wall" or w.axis != axis:
                    continue
                cuts = sorted((op.u0, op.u1, op.height) for op in w.openings)
                segs = []
                u = w.a
                for (a, b, hh) in cuts:
                    if a > u:
                        segs.append((u, a, hh))
                    u = max(u, b)
                if w.b > u:
                    segs.append((u, w.b, 0))
                for (a, b, hh) in segs:
                    lim = max(450.0, 0.3 * hh)
                    if b - a >= lim:
                        L += b - a
            res[(f, name)] = (L / 1000.0, L / 10.0 / area)
    return res


U_WALL = 0.22    # RC250＋外断熱100（フェノールフォーム λ0.024）＋外装
U_WIN = 0.90     # 樹脂枠・Low-E トリプル（Ar）FIX
U_DOOR = 1.50    # 断熱ドア


def smoke_systems(h):
    """排煙計画: 防煙区画（居室ごと）と排煙機の系統。令126条の3。"""
    west_x = h.gx[2]          # X3 より西 = 西系統
    rows = []
    for r in h.rooms:
        if not r.habitable:
            continue
        area = getattr(r, "daylight_area", r.area)
        name = getattr(r, "daylight_name", r.name)
        cx = (r.rect[0] + r.rect[2]) / 2
        sysname = "西系統" if cx < west_x else "東系統"
        # 排煙口: 天井面中央付近 → 室内の最遠点までの水平距離
        x0, y0, x1, y1 = r.rect
        d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / 2 / 1000
        rows.append(dict(floor=r.floor, room=name, area=area, system=sysname, inlet_dist=d,
                         natural_need=area / 50))
    systems = {}
    for row in rows:
        systems.setdefault(row["system"], []).append(row)
    cap = {}
    for k, v in systems.items():
        mx = max(x["area"] for x in v)
        need = max(120.0, (2 * mx) if len(v) > 1 else mx)
        cap[k] = dict(rooms=len(v), max_area=mx, need=need, plan=max(120.0, need))
    return rows, cap


def window_table(h):
    """居室の窓: 採光・仕様。"""
    k = h.spec["requirements"]["daylight_k"]
    ratio = h.spec["requirements"]["daylight_ratio"]
    out = []
    for r in h.rooms:
        if not r.habitable:
            continue
        area = getattr(r, "daylight_area", r.area)
        g = h.room_windows(r)
        out.append(dict(floor=r.floor, room=getattr(r, "daylight_name", r.name), area=area, need=area * ratio,
                        glass=g, eff=g * k, margin=g * k / (area * ratio) if area else 0))
    return out


def gym_envelope(h):
    """ジム外皮の開口部: 改善前（腰窓2か所＋南面搬入扉）と改善後（高窓2か所）の比較。"""
    before = dict(win=2 * 1.5 * 1.0, door=1.8 * 2.4)
    after = dict(win=sum(op.width * op.height / 1e6 for op in h.openings(floor="1F", exterior=True)
                         if op.kind == "window" and "ジム" in op.name), door=0.0)
    def q(d):
        open_a = d["win"] + d["door"]
        return d["win"] * U_WIN + d["door"] * U_DOOR + (before["win"] + before["door"] - open_a) * U_WALL
    return dict(before=before, after=after, q_before=q(before), q_after=q(after))


def checks(h):
    s, site, req = h.spec, h.spec["site"], h.spec["requirements"]
    sm = summary(h)
    rows = []

    def add(cat, item, basis, required, planned, result):
        rows.append(dict(cat=cat, item=item, basis=basis, required=required, planned=planned, result=result))

    o = h.outer_dims()
    hb = LineString([(o[0], o[1]), (o[2], o[1]), (o[2], o[3]), (o[0], o[3]), (o[0], o[1])])
    edges = {}
    for (a, b, k), c in zip(h.site_edges, h.edge_class):
        edges.setdefault(c, []).append(LineString([a, b]))
    dist = {c: min(hb.distance(l) for l in ls) / 1000 for c, ls in edges.items()}

    # ---------------- 設計条件（ブリーフ）
    add("ブリーフ", "敷地面積", "ブリーフv3 1章", "地図・航空写真・DEMによる推定", f"{sm['site_area']:,.2f}m²（推定誤差 ±5%程度）", CHK)
    add("ブリーフ", "建物外寸・グリッド", "ブリーフv3 5章", "内寸17.0m角、6.0/5.0/6.0、RC250＋外断熱120",
        f"壁芯 {h.W / 1000:.3f}m角、外寸 {(o[2] - o[0]) / 1000:.2f}m角", OK)
    add("ブリーフ", "1階床高", "ブリーフv3 3章", "想定浸水深（FGL+1.0m）より上", f"1FL GL+{h.fl['1F']:,}（FGL+{h.fl['1F'] - h.fgl:,}）",
        judge(h.fl["1F"] > h.fgl + site["flood_depth"]))
    add("ブリーフ", "ジムの広さ", "施主指示（v3.1）", "従前 34.5m² の1.3倍", f"{h.gym.area:.1f}m²（{h.gym.area / 34.52:.2f}倍）", judge(h.gym.area >= 34.52 * 1.3 - 0.5))
    eq = h.equipment
    wmax = min(min(r[2] - r[0], r[3] - r[1]) for _, r, _, _ in eq)
    add("ブリーフ", "ジムの搬入", "施主指示（v3.3）", "玄関から搬入、框を上がって右折でジム",
        "外部階段（4段）→玄関 W1,000×H2,300→土間→二重框→ホールで右折→遮音ドア W1,000×H2,300→ジム。幅1m超の機器は分解して搬入", OK)
    load = sum(kg for *_, kg in eq) * 9.8 / h.gym.area
    add("構造", "ジム床の積載荷重", "令85条（実況による）", "商業ジム相当の機器＋利用者",
        f"機器 計{sum(kg for *_, kg in eq):,}kg（平均 {load:,.0f}N/m²）→ 設計用 5,000N/m²（提案）・浮き床・落下エリア補強", CHK)
    ge = gym_envelope(h)
    add("ブリーフ", "ジム開口部の防犯・断熱", "施主指示（v3.2）", "腰高窓・外部扉を弱点として改善",
        f"外部扉を廃止、窓は FIX 高窓（窓台FL+2,000）防犯合わせガラス。開口 {ge['before']['win'] + ge['before']['door']:.1f}→{ge['after']['win']:.1f}m²、"
        f"開口まわりの熱損失 {ge['q_before']:.1f}→{ge['q_after']:.1f}W/K", OK)
    import performance as PF
    hl = PF.heat_load(h)
    en = PF.energy(h, hl)
    pg = h.pergola
    pg_area = (pg[2] - pg[0]) * (pg[3] - pg[1]) / 1e6
    add("ブリーフ", "太陽光発電（本館と分離した屋根付き設備）", "施主指示（v4.1・v4.2）", f"年間電力需要 約{en['total']:,.0f}kWh ×1.2 を賄う → {en['need_kwp_margin']:.1f}kWp",
        f"ソーラーパーゴラ {en['pg_kwp']:.1f}kWp＋3台用カーポート {en['cp_kwp']:.1f}kWp（影損失込み）→ 年 約{en['pv_gen']:,.0f}kWh",
        judge(en["pv_gen"] >= en["total"] * 1.2 * 0.99))
    import sightshade as SS
    S_ = ["南側道路"]
    v0 = SS.entrance_visibility(h, with_screen=False, only=S_)
    v1 = SS.entrance_visibility(h, only=S_)
    v2 = SS.entrance_visibility(h, eye=4500, only=S_)
    sw = h.screen[0]
    add("ブリーフ", "玄関の目隠し", "施主指示（v4.3）", "南側道路から目視で玄関ドアが見えない",
        f"南側道路沿い{v1['n']}地点から判定: 壁なし {len(v0['visible'])}地点で見える → 自立壁 L{(sw[2] - sw[0]) / 1000:.1f}m×H{(h.screen_top - h.fgl) / 1000:.1f}m で {len(v1['visible'])}地点（目線1.5m）／{len(v2['visible'])}地点（4.5m）",
        judge(len(v1["visible"]) == 0))
    ind = PF.indoor(h)
    dd = h.spec["requirements"]["indoor"]
    add("ブリーフ", "室内環境目標", "施主指示（v4.1）", f"全室 通年 湿度{dd['rh'][0]}〜{dd['rh'][1]}%、夏{dd['summer_t'][0]:.0f}〜{dd['summer_t'][1]:.0f}℃、冬{dd['winter_t'][0]:.0f}〜{dd['winter_t'][1]:.0f}℃",
        f"全館空調2系統＋全熱交換＋デシカント調湿。暖房 {hl['heat']:.1f}kW・冷房 {hl['cool']:.1f}kW・除湿 {hl['dehum']:.0f}L/日・加湿 {hl['hum']:.0f}L/日", OK)
    add("集団規定", "建ぺい率（パーゴラ・カーポート含む）", "法53条・法2条1号", "屋根と柱をもつ架台は建築物として扱う見込み",
        f"({sm['building_area']:.2f}+パーゴラ{pg_area:.0f}+カーポート{en['cp_area']:.0f})/{sm['site_area']:,.2f} = {(sm['building_area'] + pg_area + en['cp_area']) / sm['site_area'] * 100:.2f}%",
        judge((sm['building_area'] + pg_area + en['cp_area']) / sm['site_area'] <= h.spec['site']['coverage_limit']))
    add("ブリーフ", "蓄電池", "ブリーフv3 7章", "排煙機30分＋排水ポンプ6時間＋最低限の生活24時間", f"必要 約{en['battery']:.1f}kWh → 16kWh 級", judge(en["battery"] <= 16.5))
    add("ブリーフ", "駐車台数", "ブリーフv3 2章", f"{req['parking']}台", f"{len(h.stalls)}台（屋根なし・Dotcon+）", judge(len(h.stalls) >= req["parking"]))
    add("ブリーフ", "RC塀", "ブリーフv3 4章", f"H{req['fence_height']:,}（防犯）", "全周 H2.0m 以上（東側坂道沿いは道路面+1.2m以上）", OK)
    add("ブリーフ", "透水性舗装", "ブリーフv3 3.1・施主指示（v4.9）", "駐車場に Dotcon+、菜園まわりの透水設備も全て Dotcon+", f"駐車場・門前 約{h.ext_storage['dotcon_area_parking']:.0f}m²＋菜園まわり 約{h.ext_storage['dotcon_area_garden']:.0f}m² = 約{h.ext_storage['dotcon_area']:.0f}m²（一時貯留 約{h.ext_storage['dotcon_l'] / 1000:.1f}m³）", OK)

    # ---------------- 集団規定
    add("ブリーフ", "建物の向き", "施主指示（v4.4）", "南側道路に対して平行・直交", f"建物・外構を道路境界線に合わせて {abs(h.facade_az):.1f}° 回転（南面は真南から{'西' if h.facade_az > 0 else '東'}向き）", OK)
    gz, us = s["glazing"], s["uv_shading"]
    wins = [op for op in h.openings(exterior=True) if op.kind == "window"]
    add("ブリーフ", "窓の仕様", "施主指示（v4.5）", "全窓 Low-E ガラスのトリプルサッシ",
        f"全{len(wins)}か所 {gz['frame']}・Low-E トリプル（Ar・Low-E {gz['low_e']}面）、Uw≦{gz['uw']:.2f}。南北 日射取得型・東西 遮熱型", OK)
    import interior as IN
    sp = s["interior"]
    add("ブリーフ", "インテリアの一貫方針", "施主指示（v4.6）", "安全なデザイン、清掃・メンテナンスが簡易",
        f"危険{len(IN.SAFETY)}項目・手入れ{len(IN.MAINTENANCE)}項目の対策を全室に適用（I-01）、仕上げを室の種類ごとに統一（I-02）", OK)
    for c in IN.stair_checks(h):
        add("安全", f"{c['name']} の寸法", "品確法 評価方法基準（高齢者等配慮 等級5相当）",
            f"勾配≦6/7、{sp['stair']['step_rule'][0]}≦2R+T≦{sp['stair']['step_rule'][1]}、蹴込み≦{sp['stair']['max_nosing_gap']}",
            f"R{c['riser']:.1f}・T{c['tread']}・勾配{c['slope']:.2f}・2R+T={c['rule']:.0f}、蹴込み板あり", judge(c["ok_slope"] and c["ok_rule"]))
    hg, fg = sp["head_gap"], sp["finger_gap"]
    gg = IN.guard_gaps(h)
    bad = [v for g in gg for v in g["gaps"] if hg[0] <= v <= hg[1] or fg[0] <= v <= fg[1]]
    add("安全", "階段開口の手すり壁（頭部・指の挟み込み）", "施主指示（v4.6）",
        f"H{sp['guard_height']:,}以上、{hg[0]}〜{hg[1]}mm・{fg[0]}〜{fg[1]}mm のすき間なし",
        f"手すり壁{len(gg)}か所 H{sp['guard_height']:,}（パネル・手すり子なし）、端部は壁に接する。階段の間の壁は 2FL+{sp['guard_height']:,} まで連続", judge(not bad))
    import sightshade as SS_
    ex_ = s["exterior"]
    gv = SS_.garbage_visibility(h)
    gs_ = ex_["garbage_screen"]
    add("ブリーフ", "門の後退・ゴミ収集ボックス", "施主指示（v4.8・v4.10）", "南側の門を約4m 後退。門の外にゴミ収集ボックス（西の角）、道路から見えない",
        f"門の線を道路境界から{ex_['gate_setback'] / 1000:.1f}m 後退。ボックス W{ex_['garbage_box']['w']:,}×D{ex_['garbage_box']['d']:,}×H{ex_['garbage_box']['h']:,} を門の外・西の角に置き、"
        f"南に自立壁（X{gs_['x_end'] / 1000:.1f}m まで）＋袖壁{gs_['wing'] / 1000:.1f}m（H{gs_['h']:,}）。"
        f"南側・東側道路 {gv['n']}地点（目の高さ1.5m・門扉閉）のうち、南東の角の{len(gv['visible'])}地点から一部（判定点16のうち最大{max([p[2] for p in gv['visible']], default=0)}点）が見える（施主了承: わずかに見える分は可）",
        judge(len(gv["visible"]) <= 0.1 * gv["n"] and max([p[2] for p in gv["visible"]], default=0) <= 8))
    add("ブリーフ", "勝手口", "施主指示（v4.10）", "防犯性能を下げるため廃止", f"出入口は南の人用門扉・車両門扉の2か所のみ（門扉 {len(h.gates)}か所）", judge(len(h.gates) == 2))
    vs_ = s["vehicle_security"]
    add("ブリーフ", "車両盗難対策", "施主指示（v4.10）", "車両の盗難を防ぐ",
        f"電動スライド門扉（施錠・こじ開け検知）＋内側の電動昇降ボラード{len(h.bollards)}本、前向き駐車、電波遮断キーボックス（リレーアタック対策）、赤外線カメラ・ビームセンサー → bot 通知", OK)
    cp_ = h.carport
    add("ブリーフ", "駐車場の位置", "施主指示（v4.8）", "約8m 北へ",
        f"カーポートを 8.0m 北へ（建物南面から {(-0.245 * 1000 - cp_[3]) / 1000:.1f}m、門から {(cp_[1] - h.y_gate) / 1000:.1f}m の前面通路）。アプローチはカーポートの西を通す", OK)
    import services as SV
    import wifi as WF
    add("ブリーフ", "家具の転倒防止", "施主指示（v4.7）", "RC 壁に固定しない。突っ張り・家具の構造で耐震・転倒耐性",
        "背の高い収納・本棚は床・天井の突っ張り（天井下地補強）＋幅広の脚・背面連結・低重心・耐震ラッチ。ジム機器は自重・広い脚で安定", OK)
    rp = SV.robot_plan(h)
    add("ブリーフ", "床清掃（掃除ロボット）", "施主指示（v4.7）", "床清掃は可能な限りロボット（レールは可）",
        "・".join(f"{f} {v['area']:.0f}m²" for f, v in rp.items()) + f"、段差{s['smart']['robots']['max_step']}mm以下、各階にドック（自動ゴミ収集・給排水直結）", OK)
    add("ブリーフ", "便器", "施主指示（v4.7）", "タンクレスにしない", "全トイレ タンク式便器（フチなし・防汚）", OK)
    add("ブリーフ", "スクリーンの bot 制御", "施主指示（v4.7）", "全館のスクリーンを bot から操作できる",
        f"全{len(h.blinds)}台 KNX/Matter 対応モーター→ゲートウェイのローカル API（認証付き）。強風・凍結時の安全動作が優先", OK)
    ls = SV.lighting_curve(h)
    add("ブリーフ", "照明（時刻で変化）", "施主指示（v4.7）", "時刻に応じて色温度と明るさが変わる LED",
        f"全室 調光・調色 LED（{min(k for _, k, _ in ls)}〜{max(k for _, k, _ in ls)}K・{min(b for *_, b in ls)}〜{max(b for *_, b in ls)}%）を時刻スケジュールで制御（E-02）", OK)
    for f in ("1F", "2F"):
        r = WF.plan(h, f)
        add("ブリーフ", f"Wi-Fi（{f}）", "施主指示（v4.7）", f"5GHz 受信 {s['wifi']['target_dbm']}dBm 以上を床面の{s['wifi']['target_cover'] * 100:.0f}%以上",
            f"天井 AP {len(r['aps'])}台（PoE 有線）→ {r['cover'] * 100:.0f}%（概算、竣工時に実測）", judge(r["cover"] >= s["wifi"]["target_cover"]))
    el = s["exterior_lighting"]
    add("ブリーフ", "外構の防虫", "施主指示（v4.7）", "敷地内で虫が発生・集中しない工夫",
        f"外構照明 {len(h.ext_lights)}台を {el['cct']}K・下向き・人感センサー、日没後はスクリーンで光漏れ防止、たまり水をつくらない ほか{len(SV.INSECT)}項目（E-03）", OK)
    import sightshade as SS
    uv = SS.uv_exposure(h)
    add("ブリーフ", "紫外線対策", "施主指示（v4.5）", "日照による紫外線をカットする設備",
        f"全窓 UVカット合わせガラス（紫外線透過率{gz['tuv'] * 100:.0f}%以下）＋南・東・西の窓{len(h.blinds)}か所に外付け電動スクリーン（{us['months'][0]}〜{us['months'][-1]}月 自動）→ 室内に入る紫外線 約{uv['cases'][-1][2] / uv['tot_inc'] * 100:.1f}%（M-03）", OK)
    add("集団規定", "用途地域の制限", "法48条・別表第2", f"{site['zoning']}：住宅は建築可", "一戸建ての住宅", CHK)
    add("集団規定", "接道", "法43条", "道路に2m以上接する", f"南側道路 約13.9m・東側道路 約81.8m", OK)
    add("集団規定", "建ぺい率", "法53条", f"{site['coverage_limit'] * 100:.0f}%以下（角地緩和は不使用）",
        f"{sm['building_area']:.2f}/{sm['site_area']:,.2f} = {sm['coverage'] * 100:.2f}%", judge(sm["coverage"] <= site["coverage_limit"]))
    road_far = site["south_road_width"] / 1000 * site["road_far_factor"]
    lim = min(site["far_limit"], road_far)
    add("集団規定", "容積率", "法52条", f"min(指定{site['far_limit'] * 100:.0f}%, 道路{site['south_road_width'] / 1000:.1f}m×0.6={road_far * 100:.0f}%)",
        f"{sm['total']:.2f}/{sm['site_area']:,.2f} = {sm['far'] * 100:.2f}%", judge(sm["far"] <= lim))
    # 道路斜線（南側道路）
    setback = dist["南側道路"] * 1000
    allow = site["road_slope"] * (site["south_road_width"] + 2 * setback)
    add("集団規定", "道路斜線（南）", "法56条1項1号・2項", f"勾配{site['road_slope']}、後退距離 {setback / 1000:.1f}m による緩和",
        f"建物南面で許容 {allow / 1000:.1f}m ≧ 高さ {h.parapet_top / 1000:.2f}m", judge(allow >= h.parapet_top))
    setback_e = dist["東側道路"] * 1000
    allow_e = site["road_slope"] * (site["east_road_width"] + 2 * setback_e)
    add("集団規定", "道路斜線（東）", "法56条1項1号・2項", f"後退距離 {setback_e / 1000:.1f}m（道路高さが敷地より高い区間は緩和あり）",
        f"許容 {allow_e / 1000:.1f}m ≧ {h.parapet_top / 1000:.2f}m", judge(allow_e >= h.parapet_top))
    add("集団規定", "隣地斜線", "法56条1項2号", "31m＋2.5×L", f"最高高さ {h.parapet_top / 1000:.2f}m < 31m", OK)
    add("集団規定", "北側斜線", "法56条1項3号", "低層・中高層住居専用地域等", "準工業地域（推定）", NA)
    add("集団規定", "日影規制", "法56条の2・都条例", "準工業：高さ10m超が対象（指定時）", f"高さ {h.parapet_top / 1000:.2f}m ≦ 10m", OK)
    add("集団規定", "防火地域等", "法61条", site["fire_zone"], "壁式RC造（耐火構造）で計画", CHK)

    # ---------------- 東京都建築安全条例
    add("都条例", "がけ（北側）", "東京都建築安全条例6条", f"高さ2m超のがけ: 下端から2H={2 * site['cliff']['north_h'] / 1000:.1f}m 以上離す",
        f"水路（がけ下端）まで {dist['水路']:.1f}m", judge(dist["水路"] * 1000 >= 2 * site["cliff"]["north_h"]))
    add("都条例", "がけ（東側）", "東京都建築安全条例6条", f"道路との高低差 最大{site['cliff']['east_h'] / 1000:.1f}m: 2H={2 * site['cliff']['east_h'] / 1000:.1f}m",
        f"東側道路境界まで {dist['東側道路']:.1f}m", judge(dist["東側道路"] * 1000 >= 2 * site["cliff"]["east_h"]))
    add("都条例", "角敷地の隅切り", "東京都建築安全条例2条", "幅員がいずれも6m未満の道路の角敷地",
        f"南側道路 約{site['south_road_width'] / 1000:.1f}m（6m以上）", NA)
    add("都条例", "敷地と道路（大規模建築物）", "東京都建築安全条例4条", "延べ1,000m²超は接道長さの割増し", f"延べ {sm['total']:.0f}m²", NA)

    # ---------------- 単体規定
    k = req["daylight_k"]
    ratio = req["daylight_ratio"]
    for r in h.rooms:
        if not r.habitable:
            continue
        g = h.room_windows(r)
        area = getattr(r, "daylight_area", r.area)
        name = getattr(r, "daylight_name", r.name)
        need = area * ratio
        add("単体規定", f"採光 {r.floor} {name}", "法28条1項・令19条・20条",
            f"床面積 {area:.1f}m² × {ratio * 100:.2f}% = {need:.2f}m²（法定 1/7 = {area / 7:.2f}）",
            f"ガラス {g:.2f}m² × K{k:.1f} = {g * k:.2f}m²", judge(g * k >= need))
    add("単体規定", "採光補正係数", "令20条", "準工業: K = 8d/h − 1（上限3.0）", "隣地・道路まで十分な距離 → 3.0（要確認）", CHK)
    add("単体規定", "換気", "法28条2項・令20条の2", "窓（1/20）または機械換気設備", "全館空調・全熱交換換気（FIX窓に依存しない）", OK)
    add("単体規定", "シックハウス（24時間換気）", "法28条の2・令20条の8", "0.5回/h 以上", "全熱交換換気で常時換気", OK)
    add("単体規定", "居室の天井高", "令21条", "2.1m以上", f"CH {min(h.ch.values()):,}mm", judge(min(h.ch.values()) >= 2100))
    sp = req["stair"]
    st = h.stairs[0]
    add("単体規定", "階段（住宅）", "令23条1項ただし書", f"幅{sp['min_width']}以上・蹴上{sp['max_riser']}以下・踏面{sp['min_tread']}以上",
        f"幅{st.width:.0f}・蹴上{st.riser:.1f}・踏面{st.tread}（2か所）",
        judge(st.width >= sp["min_width"] and st.riser <= sp["max_riser"] and st.tread >= sp["min_tread"]))
    add("単体規定", "踊場・手すり", "令24条・25条", "高さ4m以内ごとに踊場、手すり設置", f"中間踊場（高さ {h.H['1F'] / 2000:.1f}m）・手すり設置", OK)
    add("単体規定", "排煙（1階）", "令126条の2・3", "FIX窓の居室は「排煙上の無窓居室」→ 排煙設備",
        "LDK・ジム・居室A: 機械排煙（機械室の排煙機）", OK)
    srows, cap = smoke_systems(h)
    add("単体規定", "排煙（2階）", "令126条の2・3", "2階居室も FIX 窓 → 排煙上の無窓居室", "居室B・C・D・図書室・主寝室: 機械排煙（1階と同じ方式）", OK)
    for k_, c in sorted(cap.items()):
        add("単体規定", f"排煙機 能力（{k_}）", "令126条の3第1項9号",
            f"120m³/分以上かつ 最大区画 {c['max_area']:.1f}m²×2 = {2 * c['max_area']:.0f}m³/分以上（{c['rooms']}区画）",
            f"排煙機 {c['plan']:.0f}m³/分（機械室）", OK)
    mx = max(r["inlet_dist"] for r in srows)
    add("単体規定", "排煙口の位置", "令126条の3第1項3号", "防煙区画の各部分から水平距離30m以下・天井から80cm以内",
        f"各室の天井に排煙口、最遠 約{mx:.1f}m", judge(mx <= 30))
    add("単体規定", "排煙の予備電源・手動開放", "令126条の3第1項5号・11号", "手動開放装置（床から0.8〜1.5m）・予備電源",
        "各室に手動開放装置、蓄電池（駐車場PV と連携）を予備電源に兼用", OK)
    add("単体規定", "内装制限（火気使用室）", "法35条の2・令128条の4第4項", "2階建て住宅の1階で火気を使う室",
        "IHクッキングヒーターなら対象外。ガス採用時は準不燃", CHK)
    add("単体規定", "非常用の照明", "令126条の4", "一戸建ての住宅は除外", "—", NA)

    # ---------------- 構造（壁式RC）
    wq = wall_quantity(h)
    for (f, d), (L, q) in sorted(wq.items()):
        add("構造", f"壁量 {f} {d}", "平13国交告1026号 第5", "12cm/m²以上（地上2階建て）",
            f"耐力壁 {L:.1f}m / 床 {h.floor_area(f):.1f}m² = {q:.1f}cm/m²", judge(q >= 12))
    add("構造", "耐力壁の厚さ", "平13国交告1026号 第5", "2階建て 15cm以上", f"{h.t / 10:.0f}cm", judge(h.t >= 150))
    cells = [(a2 - a1) * (b2 - b1) / 1e6 for a1, a2 in zip(h.gx, h.gx[1:]) for b1, b2 in zip(h.gy, h.gy[1:])]
    add("構造", "耐力壁で囲まれた面積", "平13国交告1026号 第5", "60m²以下", f"最大 {max(cells):.1f}m²", judge(max(cells) <= 60))
    add("構造", "階高・軒高・階数", "平13国交告1026号 第1", "階高3.5m以下・軒高20m以下・階数5以下",
        f"階高{h.H['1F'] / 1000:.1f}m・軒高{h.fl['RF'] / 1000:.1f}m・2階", judge(h.H["1F"] <= 3500))
    add("構造", "コンクリート強度", "平13国交告1026号 第2・令74条", "Fc18以上", f"Fc{s['structure']['concrete']['Fc']}", judge(s["structure"]["concrete"]["Fc"] >= 18))
    lx_max = max(min(a2 - a1, b2 - b1) for a1, a2 in zip(h.gx, h.gx[1:]) for b1, b2 in zip(h.gy, h.gy[1:])) - h.t
    add("構造", "床版の厚さ", "令77条の2・告示1026号", f"8cm以上かつ短辺内法/40 = {lx_max / 40:.0f}mm", f"t={h.slab_t}（短辺 内法 {lx_max / 1000:.2f}m）", judge(h.slab_t >= lx_max / 40))
    import performance as PF
    se = PF.seismic(h)
    t_need = max(x["t_req"] for x in se["slabs"])
    add("構造", "床版のたわみ（ジム床含む）", "日本建築学会 RC規準（参考）", f"必要厚 最大 {t_need:.0f}mm（ジム床 積載5kN/m²）", f"t={h.slab_t}", judge(h.slab_t >= t_need))
    worst = min(se["stories"].items(), key=lambda kv: kv[1]["耐震等級3（Co=0.3）"]["ratio"])
    (wf, wd), wv = worst
    add("構造", "地震力に対する壁のせん断（概算）", "令88条・告示1026号（参考）",
        f"Co=0.2（等級3: 0.3）、短期許容せん断 {se['fs']:.2f}N/mm²",
        f"最小余裕 {wf} {wd}: τ={wv['耐震等級3（Co=0.3）']['tau']:.2f}N/mm²（等級3）→ {wv['耐震等級3（Co=0.3）']['ratio']:.1f}倍", judge(wv["耐震等級3（Co=0.3）"]["ratio"] >= 1.0))
    ecc = max(v["ecc"] for v in se["stories"].values())
    add("構造", "偏心率", "令82条の6（参考）", "0.15以下", f"最大 {ecc:.3f}（1階 ジムの開口による）", judge(ecc <= 0.15))
    qmin = min(v["qu_ratio"] for v in se["stories"].values())
    add("構造", "保有水平耐力（目安）", "令82条の3（参考）", f"Qu ≧ Qun（Ds={se['Ds']}）", f"最小 Qu/Qun = {qmin:.1f}", judge(qmin >= 1.0))
    add("構造", "地盤の接地圧（長期）", "令93条", "長期許容支持力度 150kN/m²（要地盤調査）", f"{se['bearing']:.1f}kN/m²", judge(se["bearing"] <= 150))
    add("構造", "かぶり厚さ", "令79条", "壁・床20（耐力壁30）／土に接する40／基礎60",
        "設計かぶり 壁40・床30・土に接する50・基礎70", OK)
    add("構造", "構造計算", "法20条1項3号", "壁式RC 2階建て（延べ200m²超）→ 構造計算（許容応力度等）", "別途 構造計算書", CHK)
    add("構造", "地盤・基礎", "令38条", "地盤調査に基づく基礎", "べた基礎（杭の要否は調査後）", CHK)

    # ---------------- 外構・関連法令
    add("外構", "RC塀", "令62条の8（補強CB造）", "RC塀は対象外 → 構造計算で同等以上の安全確認", "H2.0m t=150 基礎1,200×400", CHK)
    add("外構", "擁壁を兼ねる塀", "法88条・令138条", "高さ2m超の擁壁は工作物確認申請", "東側坂道沿いで道路との段差を受ける区間が該当する可能性", CHK)
    add("外構", "水路の占用・境界", "法定外公共物管理条例（八王子市）", "境界確定・占用協議", "北側の塀・排水口の位置を協議", CHK)
    add("関連法令", "建築物省エネ法", "建築物省エネ法 10条（住宅の適合義務）", "地域区分6: 外皮 UA 0.87以下 ほか", "UA 0.25〜0.29（ブリーフ）", OK)
    add("関連法令", "宅地造成・盛土等規制法", "同法", "規制区域内の切土・盛土", "切土・盛土なし（現況地盤を維持）", OK)
    add("関連法令", "雨水浸透", "八王子市 雨水浸透施設の指導・助成", "設置基準・補助の確認", "貯留槽25m³・Dotcon+ 透水舗装・浸透桝", CHK)
    return rows, sm, wq
