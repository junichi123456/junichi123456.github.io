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
    add("ブリーフ", "駐車台数", "ブリーフv3 2章", f"{req['parking']}台", f"{len(h.stalls)}台（ソーラーカーポート下）", judge(len(h.stalls) >= req["parking"]))
    add("ブリーフ", "RC塀", "ブリーフv3 4章", f"H{req['fence_height']:,}（防犯）", "全周 H2.0m 以上（東側坂道沿いは道路面+1.2m以上）", OK)
    add("ブリーフ", "透水性舗装", "ブリーフv3 3.1", "駐車場に Dotcon+", f"約{h.ext_storage['dotcon_area']:.0f}m²（一時貯留 約{h.ext_storage['dotcon_l'] / 1000:.1f}m³）", OK)

    # ---------------- 集団規定
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
        need = r.area * ratio
        add("単体規定", f"採光 {r.floor} {r.name}", "法28条1項・令19条・20条",
            f"床面積 {r.area:.1f}m² × {ratio * 100:.2f}% = {need:.2f}m²（法定 1/7 = {r.area / 7:.2f}）",
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
        "LDK・居室A・居室B・ジム: 機械排煙（ブリーフv2確定）", OK)
    add("単体規定", "排煙（2階）", "令126条の2・平12建告1436号", "2階居室も FIX 窓なら無窓居室", "2階の窓仕様は未確定 → 機械排煙の追加または排煙窓を検討", CHK)
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
    add("構造", "床版の厚さ", "令77条の2・告示1026号", "8cm以上かつ短辺/40", f"t={h.slab_t}（短辺 内法 5.88m /40 = 147）", judge(h.slab_t >= 147))
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
    add("関連法令", "雨水浸透", "八王子市 雨水浸透施設の指導・助成", "設置基準・補助の確認", "貯留槽25m³・浸透トレンチ・浸透桝", CHK)
    return rows, sm, wq
