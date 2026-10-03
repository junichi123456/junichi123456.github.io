"""法規チェック（建築基準法・同施行令・関連法令）と仕様書適合チェック。

数値は建物モデルから算出する。計画段階の自主検討であり、
最終判断は建築確認・構造計算・所管行政庁/消防との協議による。
"""
from __future__ import annotations

import math

OK, NG, CHK, NA = "適合", "不適合", "要確認", "対象外"
REBAR_AREA = {10: 71.33, 13: 126.7, 16: 198.6, 19: 286.5, 22: 387.1, 25: 506.7}


def judge(cond):
    return OK if cond else NG


def summary(b):
    s = b.spec
    site = s["site"]
    site_area = site["width"] * site["depth"] / 1e6
    fa = b.floor_areas()
    total = sum(fa.values())
    far_area = total - b.ev_shaft_area() * len(b.floors)   # 法52条6項 昇降路の部分を不算入
    ba = b.building_area()
    road_far = site["road"]["width"] / 1000 * site["road_far_factor"]
    far_lim = min(site["far_limit"], road_far)
    return dict(site_area=site_area, building_area=ba, floor_areas=fa, total=total, far_area=far_area,
                coverage=ba / site_area, far=far_area / site_area, far_limit=far_lim, road_far=road_far,
                height=b.parapet_top / 1000, eave=b.fl["RF"] / 1000, ph_area=b.penthouse_area(),
                ph_height=(b.ph_parapet_top - b.fl["RF"]) / 1000, max_height=b.ph_parapet_top / 1000)


def road_slope(b):
    """道路斜線（法56条1項1号・2項 後退緩和）。最小余裕となる点を返す。"""
    site = b.spec["site"]
    x0, y_rb, x1, y1 = b.site_rect()
    above = [bx for bx in b.boxes if bx.z1 > 0 and bx.cat not in ("footing", "fg")]
    setback = min(bx.y0 for bx in above) - y_rb
    y_virtual = y_rb - site["road"]["width"] - setback
    worst = None
    for bx in above:
        dist = bx.y0 - y_virtual
        if dist > site["road_slope_range"]:
            continue
        allow = site["road_slope"] * dist
        margin = allow - bx.z1
        if worst is None or margin < worst[0]:
            worst = (margin, bx, allow)
    return dict(setback=setback, y_virtual=y_virtual, margin=worst[0], box=worst[1], allow=worst[2],
                slope=site["road_slope"], range=site["road_slope_range"], y_rb=y_rb)


def walking_distance(b):
    """居室の最遠点から直通階段（階段室扉）までの歩行距離（直交経路で近似）。"""
    door_y = 6750.0
    door_x = b.stair[0]
    e = b.wt / 2
    pts = [(e, e), (e, b.D - e), (b.W - e, e)]
    return max(abs(px - door_x) + abs(py - door_y) for px, py in pts) / 1000


def smoke_and_vent(b, f):
    """排煙上有効な開口（天井から 80cm 以内・引違いは 1/2）と換気上有効な開口。"""
    ch_abs = b.fl[f] + b.ch[f]
    smoke = vent = 0.0
    for op in b.openings(floor=f, exterior=True):
        if op.kind != "window" or op.wall is None:
            continue
        # 階段室の窓は事務室の排煙・換気に含めない
        if op.wall.axis == "x" and op.wall.c == b.D and op.u0 >= b.stair[0]:
            continue
        ratio = 0.5 if op.name == "引違い窓" else 1.0
        eff_h = max(0.0, min(op.z1, ch_abs) - max(op.z0, ch_abs - 800))
        smoke += op.width * ratio * eff_h / 1e6
        vent += op.width * ratio * op.height / 1e6
    return smoke, vent


def alt_entries(b):
    ops = sorted([op for op in b.openings(floor="3F", exterior=True) if op.alt_entry], key=lambda o: o.u0)
    if not ops:
        return None
    e = b.wt / 2
    centers = [(o.u0 + o.u1) / 2 for o in ops]
    gaps = [centers[0] + e] + [q - p for p, q in zip(centers, centers[1:])] + [b.W + e - centers[-1]]
    return dict(n=len(ops), w=ops[0].width / 2, h=ops[0].height, max_gap=max(gaps) / 1000)


def checks(b):
    s = b.spec
    site = s["site"]
    req = s["requirements"]
    st = s["structure"]
    sm = summary(b)
    rows = []

    def add(cat, item, basis, required, planned, result):
        rows.append(dict(cat=cat, item=item, basis=basis, required=required, planned=planned, result=result))

    # ------------------------------------------------------------ 仕様書
    add("仕様書", "用途・階数", "設計仕様書", f"{req['use']}・地上{req['stories']}階",
        f"事務所・地上{len(b.floors)}階（塔屋1）", judge(len(b.floors) == req["stories"]))
    add("仕様書", "延べ面積", "設計仕様書", f"{req['min_total_floor_area']}m²以上", f"{sm['total']:.2f}m²",
        judge(sm["total"] >= req["min_total_floor_area"]))
    add("仕様書", "天井高", "設計仕様書", " / ".join(f"{k} {v:,}" for k, v in req["ceiling_height"].items()),
        " / ".join(f"{f} {b.ch[f]:,}" for f in b.floors), judge(all(b.ch[f] >= req["ceiling_height"][f] for f in b.floors)))
    add("仕様書", "昇降機", "設計仕様書", "乗用EV 1基", "11人乗 MRL 1基（全階停止）", OK)
    add("仕様書", "便所", "設計仕様書", req["toilets"], "2・3階 WC(男)/WC(女)、1階 多機能WC", OK)
    sp = req["stair"]
    si = b.stair_info
    add("仕様書", "階段寸法", "設計仕様書", f"幅{sp['min_width']:,}以上・蹴上{sp['max_riser']}以下・踏面{sp['min_tread']}以上",
        f"幅{si['1F']['width']:,.0f}・蹴上{max(v['riser'] for v in si.values()):.1f}・踏面{si['1F']['tread']}",
        judge(si["1F"]["width"] >= sp["min_width"] and all(v["riser"] <= sp["max_riser"] and v["tread"] >= sp["min_tread"] for v in si.values())))
    add("仕様書", "屋上利用", "設計仕様書", req["roof"], "階段室（塔屋）から屋上へ出入、パラペット H=1,100", OK)

    # ------------------------------------------------------------ 集団規定
    add("集団規定", "用途地域の制限", "法48条・別表第2", f"{site['zoning']}：事務所 建築可", "事務所", OK)
    add("集団規定", "接道", "法43条", "道路に2m以上接する", f"{site['road']['kind']} 幅員{site['road']['width'] / 1000:.1f}m に {site['width'] / 1000:.1f}m 接道", OK)
    add("集団規定", "建ぺい率", "法53条", f"{site['coverage_limit'] * 100:.0f}%以下（準防火地域内の耐火建築物 +10% 緩和は不使用）",
        f"{sm['building_area']:.2f} / {sm['site_area']:.2f} = {sm['coverage'] * 100:.2f}%", judge(sm["coverage"] <= site["coverage_limit"]))
    add("集団規定", "容積率", "法52条1項・2項・6項",
        f"min(指定{site['far_limit'] * 100:.0f}%, 道路{site['road']['width'] / 1000:.1f}m×{site['road_far_factor']}={sm['road_far'] * 100:.0f}%) = {sm['far_limit'] * 100:.0f}%",
        f"{sm['far_area']:.2f} / {sm['site_area']:.2f} = {sm['far'] * 100:.2f}%（EV昇降路 不算入）", judge(sm["far"] <= sm["far_limit"]))
    rs = road_slope(b)
    add("集団規定", "道路斜線", "法56条1項1号・2項、別表第3",
        f"勾配{rs['slope']}、適用距離{rs['range'] / 1000:.0f}m、後退距離 {rs['setback'] / 1000:.2f}m による緩和",
        f"最小余裕点: 許容 {rs['allow'] / 1000:.2f}m に対し {rs['box'].z1 / 1000:.2f}m（余裕 {rs['margin'] / 1000:.2f}m）", judge(rs["margin"] >= 0))
    adj = site["adjacent_slope"]
    add("集団規定", "隣地斜線", "法56条1項2号", f"{adj['rise'] / 1000:.0f}m + {adj['slope']}×L", f"最高高さ {sm['max_height']:.2f}m < {adj['rise'] / 1000:.0f}m", judge(sm["max_height"] * 1000 < adj["rise"]))
    add("集団規定", "北側斜線", "法56条1項3号", "第一種・第二種低層／中高層住居専用地域等のみ", site["zoning"], NA)
    add("集団規定", "日影規制", "法56条の2・別表第4", site["shadow_regulation"], f"建築物の高さ {sm['height']:.2f}m（10m超）", CHK)
    add("集団規定", "高度地区", "法58条", site["height_district"], "—", CHK)
    add("集団規定", "防火地域・準防火地域", "法61条・令136条の2",
        f"{site['fire_zone']}・地上3階・延べ{sm['total']:.0f}m²（1,500m²以下）→ 準耐火建築物等以上",
        "耐火建築物（RC造）", OK)
    fire_ops = sorted({f"{op.label}" for op in b.openings(exterior=True) if op.fire})
    dW, dE = b.fire_spread_distance("W"), b.fire_spread_distance("E")
    add("集団規定", "延焼のおそれのある部分の開口部", "法2条6号・法61条・令109条",
        "隣地境界線・道路中心線から 1階3m／2階以上5m 以内の開口は防火設備",
        f"西面{dW / 1000:.1f}m・東面{dE / 1000:.1f}m → 2・3階の開口を防火設備（{'・'.join(fire_ops)}）", OK)
    add("集団規定", "敷地境界からの離れ（参考）", "民法234条", "50cm以上", f"最小 {min(dW, dE) / 1000:.2f}m", OK)

    # ------------------------------------------------------------ 単体規定（一般）
    add("単体規定", "居室の天井高", "令21条", "2.1m以上", f"最小 {min(b.ch.values()) / 1000:.2f}m", judge(min(b.ch.values()) >= 2100))
    add("単体規定", "採光", "法28条1項・令19条", "住宅・学校・病院等の居室", "事務所の居室", NA)
    for f in b.floors:
        smoke, vent = smoke_and_vent(b, f)
        hab = b.habitable_area(f)
        add("単体規定", f"換気（{f}）", "法28条2項", f"居室床面積の1/20以上 = {hab / 20:.2f}m²", f"有効開口 {vent:.2f}m²", judge(vent >= hab / 20))
    hab2 = {f: b.habitable_area(f) for f in b.floors}
    upper = {f: hab2.get(b.next_level(f), 0) for f in b.floors}
    over200 = any(v > 200 for v in upper.values())
    row = ("(3) 直上階居室 200m²超", 1200, 200, 240) if over200 else ("(4) その他", 750, 220, 210)
    max_r = max(v["riser"] for v in si.values())
    add("単体規定", "階段の寸法", "令23条",
        f"表{row[0]}: 幅{row[1]}以上・蹴上{row[2]}以下・踏面{row[3]}以上（直上階居室 最大{max(upper.values()):.1f}m²）",
        f"幅{si['1F']['width']:,.0f}・蹴上{max_r:.1f}・踏面{si['1F']['tread']}",
        judge(si["1F"]["width"] >= row[1] and max_r <= row[2] and si["1F"]["tread"] >= row[3]))
    add("単体規定", "踊場", "令24条", "高さ4m以内ごとに踊場（直階段は踏幅1.2m以上）",
        f"各階 中間踊場（最大 {max(v['landing_h'] for v in si.values()) / 1000:.2f}m ごと・奥行{min(v['landing_depth'] for v in si.values()):,.0f}）",
        judge(all(v["landing_h"] <= 4000 for v in si.values())))
    add("単体規定", "階段の手すり", "令25条", "手すりを設置、両側に側壁等", "両側 手すり H=850（RC壁＋鋼製手すり）", OK)
    add("単体規定", "便所", "法31条・令28条〜", "下水道処理区域：水洗便所", "水洗便所（公共下水道放流）", OK)

    # ------------------------------------------------------------ 防火・避難
    add("防火・避難", "面積区画", "令112条1項", "耐火建築物 1,500m²以内ごと", f"各階 {b.W * b.D / 1e6:.0f}m²", OK)
    add("防火・避難", "竪穴区画", "令112条11項", "階段・昇降路を準耐火構造の壁＋防火設備（遮煙）で区画",
        "階段室 RC壁＋SD（防火設備・遮煙）／EV 乗場戸 遮煙性能", OK)
    wd = walking_distance(b)
    add("防火・避難", "直通階段までの歩行距離", "令120条", "主要構造部 準耐火・不燃：50m以下（事務所）", f"最大 約{wd:.1f}m", judge(wd <= 50))
    lim121 = {f: (400 if i == 1 else 200) for i, f in enumerate(b.floors)}
    ok121 = all(hab2[f] <= lim121[f] for f in b.floors[1:])
    add("防火・避難", "2以上の直通階段", "令121条1項6号・2項",
        "5階以下：避難階直上階 居室 400m²超／その他の階 200m²超で必要（主要構造部準耐火 2倍）",
        " / ".join(f"{f} {hab2[f]:.1f}m²" for f in b.floors[1:]) + " → 1か所で可", judge(ok121))
    add("防火・避難", "屋外への出口", "令125条", "避難階の階段から屋外出口まで 50m以下", "1階階段室から東面出口 約1m・主出入口 約9m", OK)
    add("防火・避難", "屋上の手すり", "令126条1項", "屋上広場等の周囲 1.1m以上の手すり壁", f"パラペット H={(b.parapet_top - b.fl['RF']):,.0f}",
        judge(b.parapet_top - b.fl["RF"] >= 1100))
    for f in b.floors:
        smoke, vent = smoke_and_vent(b, f)
        area = b.W * b.D / 1e6 - 18.0 - b.ev_shaft_area()
        add("防火・避難", f"排煙設備（{f}）", "令126条の2・3",
            f"階数3以上・延べ500m²超 → 必要。防煙区画 {area:.1f}m² の1/50 = {area / 50:.2f}m²",
            f"自然排煙 有効 {smoke:.2f}m²（天井下80cm以内）", judge(smoke >= area / 50))
    add("防火・避難", "非常用の照明装置", "令126条の4", "階数3以上・延べ500m²超 → 居室・通路・階段に設置", "設置（電気設備図による）", OK)
    ae = alt_entries(b)
    add("防火・避難", "非常用進入口（代替進入口）", "令126条の6・7",
        "3階の道に面する外壁 10m以内ごとに 幅75cm×高1.2m 以上",
        f"3階南面 {ae['n']}か所 有効{ae['w']:,.0f}×{ae['h']:,.0f}・最大間隔{ae['max_gap']:.1f}m（赤▽表示）",
        judge(ae["w"] >= 750 and ae["h"] >= 1200 and ae["max_gap"] <= 10))
    add("防火・避難", "敷地内の通路", "令128条", "屋外出口から道まで 有効1.5m以上", f"東側通路 {b.fire_spread_distance('E') / 1000:.1f}m", OK)
    add("防火・避難", "内装制限", "法35条の2・令128条の4・5", "階数3以上・延べ500m²超：居室 難燃以上／通路・階段 準不燃以上",
        "居室 壁PB準不燃・天井不燃／階段 不燃", OK)
    add("防火・避難", "非常用昇降機", "法34条2項", "高さ31m超", f"{sm['height']:.2f}m", NA)
    add("防火・避難", "避雷設備", "法33条", "高さ20m超", f"{sm['height']:.2f}m", NA)

    # ------------------------------------------------------------ 構造
    c1 = st["column"]["C1"]
    g1 = st["girder"]["G1"]
    clear = b.fl["2F"] - b.gd - b.fg_top
    add("構造", "構造計算", "法20条1項3号・令81条", "RC造 階数2以上 → 許容応力度計算（ルート1）等",
        f"{st['system']}：別途 構造計算書による", CHK)
    add("構造", "コンクリート強度", "令74条", "4週圧縮強度 12N/mm²以上", f"Fc={st['concrete']['Fc']}N/mm²", judge(st["concrete"]["Fc"] >= 12))
    add("構造", "柱の小径", "令77条5号", f"支点間距離の1/15以上 = {clear / 15:.0f}mm（1階 内法{clear:,.0f}）", f"C1 {c1['b']}×{c1['d']}",
        judge(min(c1["b"], c1["d"]) >= clear / 15))
    pg = c1["main"] * REBAR_AREA[c1["main_dia"]] / (c1["b"] * c1["d"])
    add("構造", "柱の主筋", "令77条1号・6号", "4本以上・断面積比 0.8%以上", f"{c1['main']}-D{c1['main_dia']}  pg={pg * 100:.2f}%",
        judge(c1["main"] >= 4 and pg >= 0.008))
    pw = 2 * REBAR_AREA[c1["hoop_dia"]] / (c1["b"] * c1["hoop_pitch"])
    add("構造", "柱の帯筋", "令77条2〜4号", "径6mm以上・間隔15cm以下（端部10cm）・帯筋比0.2%以上",
        f"D{c1['hoop_dia']}@{c1['hoop_pitch']}  pw={pw * 100:.3f}%", judge(c1["hoop_pitch"] <= 100 and pw >= 0.002))
    lx = min(b.gx[1] - b.gx[0], b.gy[1] - b.gy[0]) - b.gb
    add("構造", "床版の厚さ", "令77条の2", f"8cm以上かつ 短辺有効スパン/40 = {lx / 40:.0f}mm", f"S1 t={b.slab_t}", judge(b.slab_t >= max(80, lx / 40)))
    wp = (st["live_load_floor"] + st["finish_load"]) / 1000
    lam = 1.0
    t_aij = 0.02 * (lam - 0.7) / (lam - 0.6) * (1 + wp / 10 + lx / 10000) * lx
    add("構造", "床版の厚さ（たわみ）", "日本建築学会 RC規準（参考）", f"周辺固定スラブ t ≥ {t_aij:.0f}mm（wp={wp:.1f}kN/m²）", f"t={b.slab_t}",
        judge(b.slab_t >= t_aij))
    add("構造", "梁の配筋", "令78条", f"複筋梁・あばら筋間隔 梁せいの3/4以下 = {g1['d'] * 0.75:.0f}mm",
        f"G1 {g1['b']}×{g1['d']} 上{g1['top']}-D{g1['main_dia']} 下{g1['bottom']}-D{g1['main_dia']} D{g1['stirrup_dia']}@{g1['stirrup_pitch']}",
        judge(g1["top"] >= 2 and g1["bottom"] >= 2 and g1["stirrup_pitch"] <= 0.75 * g1["d"]))
    add("構造", "耐力壁", "令78条の2", "厚さ12cm以上・D9以上 間隔30cm以下（複配筋 45cm以下）", f"W20 t={b.wt} D13@200 ダブル", judge(b.wt >= 120))
    cov = st["cover"]
    add("構造", "かぶり厚さ", "令79条",
        "柱・梁30／床・壁20／土に接する40／基礎60 以上",
        f"柱・梁{cov['column_beam']}／床・壁{cov['slab_wall']}／土に接する{cov['earth_contact']}／基礎{cov['foundation']}（設計かぶり）",
        judge(cov["column_beam"] >= 30 and cov["slab_wall"] >= 20 and cov["earth_contact"] >= 40 and cov["foundation"] >= 60))
    add("構造", "基礎", "令38条・平12建告1347号", "地盤の許容応力度に応じた構造", st["foundation"], CHK)

    # ------------------------------------------------------------ 関連法令
    add("関連法令", "建築物省エネ法", "建築物省エネ法 11条", "適合義務（一次エネルギー消費量基準 BEI）", "省エネ適合性判定 別途計算", CHK)
    add("関連法令", "バリアフリー法", "バリアフリー法 16条・条例", "事務所：特定建築物（努力義務）／条例の上乗せを確認",
        "EV（11人乗）・1階多機能WC・主出入口段差解消（スロープ1/12）", CHK)
    add("関連法令", "消防用設備（参考）", "消防法施行令 別表第1(15)項",
        "消火器：延べ300m²以上 要／自火報：延べ1,000m²未満・各階300m²未満 不要／屋内消火栓 不要",
        "消火器 設置、その他 所轄消防と事前協議", CHK)
    return rows, sm
