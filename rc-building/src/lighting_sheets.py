"""照明の図面 E-04（照明配置図 1階）・E-05（同 2階）・E-06（照明器具表・照度計算・制御）。

製品は未確定で、器具の寸法・光束・効率はすべて仮定値（spec.yaml の lighting）。
"""
from __future__ import annotations

import furniture as FU
import lighting as LG
from furniture_sheets import _plan_base
from house_sheets import frame, legend, room_labels, tp
from sheetlib import T, side_panel

SENSOR_PIR = ("廊下", "トイレ", "WIC", "クローゼット", "パントリー", "洗面", "ランドリー", "機械室", "玄関土間", "ホール", "階段", "浴室", "シャワー", "収納")
SENSOR_PRES = ("リビング", "図書室", "ジム", "居室", "主寝室", "シアター", "キッチン")


def _diamond(sh, c, r, layer="E-SENS"):
    sh.pline([(c[0], c[1] + r), (c[0] + r, c[1]), (c[0], c[1] - r), (c[0] - r, c[1])], layer, closed=True)


def _tri(sh, c, r, layer="E-FOOT"):
    sh.pline([(c[0] - r, c[1] + r), (c[0] + r, c[1] + r), (c[0], c[1] - r)], layer, closed=True)


def plan_sheet(h, floor, number):
    names = {"1F": "照明配置図（1階）", "2F": "照明配置図（2階）"}
    sh = frame(h, number, names[floor], 100)
    t = T(sh, (0, 0), (52, 73))
    its = FU.items(h)
    lns = [l for l in LG.lines(h, its) if l["floor"] == floor]
    dls = [d for d in LG.downlights(h, its) if d["floor"] == floor]
    _plan_base(h, floor, sh, t)
    room_labels(h, sh, t, floor, hgt=2.0)
    for d in dls:
        sh.circle(t(d["p"][0], d["p"][1]), 0.75 * sh.S, "E-LITE")
    for l in lns:
        a, b = t(l["p0"][0], l["p0"][1]), t(l["p1"][0], l["p1"][1])
        if l["kind"] == "shelf":
            sh.line(a, b, "E-LINE", lineweight=35)
        else:
            sh.pline([a, b], "E-LINE", lineweight=70)
        vert = abs(l["p1"][1] - l["p0"][1]) > abs(l["p1"][0] - l["p0"][0])
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        off = 1.6 * sh.S
        sh.text(l["id"].split("-", 1)[1], (mid[0] + (off if vert else 0), mid[1] + (0 if vert else off)), 1.0, "A-TEXT", "MIDDLE_CENTER", rot=90 if vert else 0)
    if floor == "1F":
        for f in LG.footlights(h):
            c = t(f["p"][0] + 120 * f["n"][0] * -1, f["p"][1])
            _tri(sh, c, 0.9 * sh.S)
        for s in h.stairs:
            xm = (s.x0 + s.x1) / 2
            sh.text(f"{s.name} 足元灯 踏面+300（2段おき・9台）", t(xm, s.y_entry - 380), 1.2, "A-TEXT", "TOP_CENTER")
    for r in h.rooms:
        if r.floor != floor:
            continue
        cx, cy = (r.rect[0] + r.rect[2]) / 2, (r.rect[1] + r.rect[3]) / 2
        if any(k in r.name for k in SENSOR_PRES):
            _diamond(sh, t(cx + 350, cy - 450), 0.9 * sh.S)
        elif any(k in r.name for k in SENSOR_PIR) and "式台" not in r.name:
            _diamond(sh, t(cx + 350, cy - 450), 0.7 * sh.S)
    sh.north_arrow(sh.P(395, 268), 7, rot=h.facade_az)
    sh.view_title(names[floor], "1:100", (24, 22))
    sh.text(f"{floor[:-1]}FL = 設計GL+{h.fl[floor]:,}（TP+{tp(h, h.fl[floor]):.2f}）／天井高 CH={h.ch[floor]:,}／製品未確定・仮定値", (24, 15), 2.4, "A-TEXT", paper=True)
    cy = side_panel(sh, 284, 282, [("h", "凡例")])
    cy = legend(sh, 285, cy - 1, [("E-LINE", "直付ライン LED（主照明・天井面に直付け）", "line"), ("E-LITE", "埋込ダウンライト（弱い補助灯 最大250lm）○", "line"),
                                   ("E-FOOT", "階段の足元灯（踏面から300）▼", "line"), ("E-SENS", "人感／在室センサー ◇", "line")])
    rows = [["器具 ID", "長さ", "lm/m", "器具数"]] + [[l["id"], f"{l['L']:,}", f"{l['lm_per_m']:,}", str(LG.device_count(l))] for l in lns]
    if len(rows) > 38:
        rows = rows[:38] + [["…", "", "", f"（全{len(lns)}列は E-06）"]]
    notes = [("h", "計画の考え方"),
             ("t", "主照明は天井面に直付けする棒状（ライン）LED（乳白カバー・連結部が目立たない側面発光）。埋込ダウンライトは夕方〜夜の弱い補助灯。コーブ（溝）・吊り器具はつくらない"),
             ("t", "ライン列は室の長手方向に平行。階段の吹抜け・天井まで届く家具の範囲は 150 離して切る。ダウンライトはライン軸から 450 以上・壁から 400 以上"),
             ("t", "六角形の連結照明は実在するが壁用・装飾用で天井の主照明に適さないため不採用（E-06）。製品は未確定で、数値は仮定値"),
             ("t", "センサー: 人感（PIR）は廊下・水回り・収納・ホール・階段、在室（ミリ波）は居室・LDK・ジム・図書室・シアター")]
    if floor == "1F":
        notes.append(("t", "階段の足元灯は壁（LGS の手すり壁の両面・踊場の間仕切）に埋込。停電時は内蔵電池で自動点灯（30分以上と仮定）"))
    yy = side_panel(sh, 284, cy - 3, notes, width=118)
    sh.table(284, yy - 3, [58, 18, 18, 18], rows, row_h=3.4, h=1.5)
    return sh


def schedule_sheet(h, number):
    its = FU.items(h)
    cfg = h.spec["lighting"]
    sh = frame(h, number, "照明器具表・照度計算・制御", 1, label="—")
    sh.text("照明器具表・照度計算・制御 — 主照明は直付ライン LED、埋込ダウンライトは弱い補助灯、階段は足元灯（製品未確定・仮定値）", (12, 280), 3.4, "A-TEXT", paper=True)
    lns = LG.lines(h, its)
    dls = LG.downlights(h, its, lns)
    ft = LG.footlights(h)
    ln = cfg["line"]
    tot_lm = sum(l["L"] / 1000 * l["lm_per_m"] for l in lns)
    tot_m = sum(l["L"] for l in lns) / 1000
    sh.text("(1) 器具表", (12, 271), 2.8, "A-TEXT", paper=True)
    rows = [["種類", "寸法・仕様（仮定値）", "台数・数量", "備考"],
            ["ライン（主）", f"幅{ln['width']}×高{ln['height']}、長さ 600〜2,400 を連結、乳白・直付、{ln['kelvin'][0]}〜{ln['kelvin'][1]}K、Ra{ln['ra']}以上、1〜100%、{ln['dimming']}",
             f"{len([l for l in lns])}列・約{tot_m:.0f}m・計{tot_lm / 10000:.1f}万lm", f"出力区分 {ln['classes_lm_per_m'][0]}〜{ln['classes_lm_per_m'][-1]} lm/m、効率 {cfg['efficacy_lm_per_w']} lm/W、全点灯 約{tot_lm / cfg['efficacy_lm_per_w'] / 1000:.1f}kW"],
            ["ダウンライト（弱）", f"φ75〜100 グレアレス、最大{cfg['downlight']['max_lm']}lm、{cfg['downlight']['kelvin'][0]}〜{cfg['downlight']['kelvin'][1]}K、Ra{cfg['downlight']['ra']}", f"{len(dls)}台", "夕方〜夜の補助灯（昼は消灯）"],
            ["足元灯", f"壁埋込 プレート{cfg['foot']['plate'][0]}×{cfg['foot']['plate'][1]}（出っ張り{cfg['foot']['protrude']}以下）、約{cfg['foot']['lm']}lm、{cfg['foot']['kelvin']}K、人感＋時刻、停電時自動点灯",
             f"{len(ft)}台（階段1・2 各9台）", f"踏面から{cfg['foot']['height_from_tread']}、2段おき＋踊場"]]
    y = sh.table(12, 268, [26, 100, 40, 40], rows, row_h=5.0, h=1.7)
    sh.text("(2) 照度計算（光束法 E = Φ×U×M/A、M=0.8、床面平均。JIS Z 9110 を参考にした仮定の目標値）", (12, y - 5), 2.8, "A-TEXT", paper=True)
    rows = [["階", "室", "m²", "目標lx", "U", "列数", "器具長さ(mm)", "lm/m", "計画lx", "ダウン"]]
    for r in LG.illuminance_table(h, its):
        if r["n"] == 0:
            continue
        rows.append([r["floor"], r["room"], f"{r['area']:.1f}", str(r["target"]), f"{r['U']:.2f}", str(r["n"]), r["lengths"], f"{r['lm_per_m']:,}", f"{r['E']:.0f}", str(r["dl"])])
    # 2 段に分ける
    half = (len(rows) + 1) // 2
    head = rows[0]
    sh.table(12, y - 8, [8, 40, 9, 11, 8, 8, 32, 12, 11, 9], [head] + rows[1:half], row_h=3.4, h=1.45)
    sh.table(172, y - 8, [8, 40, 9, 11, 8, 8, 32, 12, 11, 9], [head] + rows[half:], row_h=3.4, h=1.45)
    # (3) チャネル配分
    ch = cfg["channels"]
    yy = 150
    sh.text("(3) チャネルと時刻ごとの配分（L=ライン、D=ダウンライト、F=足元灯）", (12, yy), 2.8, "A-TEXT", paper=True)
    rows = [["時刻", "L（ライン・主）", "D（ダウンライト・弱）", "F（足元灯）"]]
    for hr in (0, 5.5, 7, 12, 17, 19, 21, 23):
        c = LG.channels(h.spec, hr)
        f = lambda v: "消灯" if v[1] <= 0 else f"{v[0]}K・{v[1]:.0f}%"
        rows.append([f"{int(hr):02d}:{int(hr % 1 * 60):02d}", f(c["L"]), f(c["D"]), f(c["F"])])
    rows.append(["室ごとの上書き", "ジムは使用中 5000K・100%。シアターは上映で L・D を 0、F のみ。寝室は 21 時以降 L 消灯・D 20% 以下", "", "停電時は内蔵電池で自動点灯"])
    y3 = sh.table(12, yy - 3, [24, 54, 54, 48], rows, row_h=4.2, h=1.6)
    # (4) DALI
    sh.text("(4) DALI-2 系統・グループ（各階3系統・64台・16グループ。KNX-DALI ゲートウェイ経由で bot から操作）", (200, yy), 2.8, "A-TEXT", paper=True)
    gr = LG.dali_groups(h, its)
    rows = [["系統", "グループ数", "器具数"]]
    for sysn in sorted({g["system"] for g in gr}):
        gg = [g for g in gr if g["system"] == sysn]
        rows.append([sysn, str(len(gg)), str(sum(g["devices"] for g in gg))])
    rows.append(["合計", str(len(gr)), str(sum(g["devices"] for g in gr))])
    y4 = sh.table(200, yy - 3, [30, 30, 30], rows, row_h=4.2, h=1.7)
    # (5) 六角形の判定
    hx = cfg["hex"]
    side_panel(sh, 12, y3 - 4, [("h", "六角形の連結照明の検討（試験済み・不採用）"),
        ("t", f"製品: {hx['product']}（確認日 {hx['checked']}、メーカー・国内販売店のページを確認）。実在し、連結・調色（1200〜6500K）・Matter 対応。"),
        ("t", f"判定: {hx['reason']}。代わりに棒状 LED（遠藤照明 Linear series の調光調色品を第一候補、Zumtobel SLOTLIGHT infinity II を代替。型番・DALI 対応・防塵等級は要確認）を採用"),
        ("t", "試験: LDK の天井を 3 案（既存／六角形217枚／ライン3列）で描画し比較（docs/cg_lighting_hex_vs_line.jpg）。六角形は柔らかい光の面になるが、継ぎ目の格子と段差が天井に多数残る"),
        ("h", "仮定・要確認"),
        ("t", "照明の設置容量は全点灯で約7.5W/m²。運用平均は 2W/m² 相当と仮定（performance.py の前提は据え置き）。製品の型番・光束・DALI 対応・防塵等級・PSE は未確認（要施主確認）")], width=186)
    side_panel(sh, 200, y4 - 4, [("h", "足元灯・防災"),
        ("t", "足元灯は階段の手すり壁（LGS）の両面と踊場の間仕切に埋込み、各段の踏面から300・2段おき。火災報知で避難経路の L を 100%（4000K）。一戸建て住宅は非常用の照明の対象外（令126条の4）で、足元灯は自主的な安全対策")], width=206)
    return sh
