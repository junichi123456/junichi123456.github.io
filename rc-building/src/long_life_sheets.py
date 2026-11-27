"""v4.40 長期優良住宅の図面 6 枚: S-05 構造特記・S-06 床下ピット伏図・A-03M 維持管理（点検口）計画図・M-05 給排水衛生 系統図・M-06 省エネ（長期優良）・M-07 維持保全計画。
数値は spec の long_life・structure・utilities と House・maintenance・performance から読む。"""
from __future__ import annotations

from shapely.geometry import Point, box as sbox
from shapely.ops import unary_union

import maintenance as MT
import performance as PF
from house_sheets import frame, grid, _flow_box, _flow_line
from sheetlib import T, hdim, vdim, side_panel
from views import iter_lines, iter_polygons


def _wall_c(h, wall):
    return h.rc_walls["FDN"][wall]


def _sleeve_xy(h, sl):
    """スリーブ（[ID, 壁, 位置, 径, 高さ, 用途]）の平面位置。"""
    w = _wall_c(h, sl[1])
    return (sl[2], w.c) if w.axis == "x" else (w.c, sl[2])


# ================================================================ S-05
def structural_notes(h, number):
    st = h.spec["structure"]
    c = st["concrete"]
    sh = frame(h, number, "構造特記仕様書（劣化対策等級3・長期優良）", 1, label="—")
    sh.text("構造特記仕様書 — コンクリート・かぶり・鉄筋（告示209号 第3 1(2)③ 劣化対策等級3・W/C 50% 以下＋最小かぶり（ロ）欄）", (12, 282), 3.0, "A-TEXT", paper=True)
    sh.text("(1) コンクリート", (12, 276), 2.6, "A-TEXT", paper=True)
    rows = [["項目", "値", "根拠・区分"],
            ["設計基準強度 Fc", f"{c['Fc']} N/mm²", "告示1026号・構造計算【確定（現行）】"],
            ["耐久設計基準強度 Fd・品質基準強度 Fq", f"Fd {c['Fd']}（計画供用期間「標準」）、Fq = max(Fc, Fd) = {max(c['Fc'], c['Fd'])}", "JASS 5【標準】"],
            ["水セメント比 W/C の上限", f"{c['wc_max'] * 100:.0f}%", "告示209号 第3 1(2)③（ロ）【確定】。配合計画書で確認"],
            ["呼び強度", c["nominal"], "Fq＋構造体強度補正 S（3 または 6）【推定】。生コン工場の配合計画書で確認"],
            ["セメント", c["cement"] + "。高炉セメント B 種を使う場合は混合物の 3/10 を除いて W/C を計算", "JIS R 5210【確定】"],
            ["単位水量", f"{c['unit_water_max']} kg/m³ 以下", "評価方法基準 3-1【標準】"],
            ["単位セメント量", f"{c['unit_cement_min']} kg/m³ 以上", "JASS 5【標準】"],
            ["スランプ", f"{c['slump']} cm（打込み箇所で 21cm を使う場合は高性能 AE 減水剤で単位水量を守る）", "【標準】"],
            ["空気量", f"{c['air'][0]}% ±{c['air'][1]}%", "【標準】"],
            ["塩化物量", f"塩化物イオン {c['chloride_max']:.2f} kg/m³ 以下", "【標準】"],
            ["アルカリシリカ反応", c["asr"], "【標準】"],
            ["打込み・締固め・養生", f"打重ね時間の管理、棒形振動機、湿潤養生 {c['curing_days']} 日以上（普通ポルトランド）", "【標準】"]]
    y = sh.table(12, 273, [44, 96, 60], rows, row_h=4.6, h=1.7)
    sh.text("(3) 鉄筋・開口補強", (12, y - 5), 2.6, "A-TEXT", paper=True)
    rb = st["rebar_spec"]
    rows = [["項目", "仕様"],
            ["鉄筋", f"D10〜D16 SD295、D19〜D25 SD345（不変）。{rb['std']}。壁 {st['wall_bars']}・スラブ {st['slab_bars']}"],
            ["継手", f"{rb['lap']}、{rb['weld']}"],
            ["スペーサー", rb["spacer"]],
            ["開口補強", rb["opening"] + f"。人通口 {len(h.spec['long_life']['manways'])}（W600×H700）・スリーブ SL-P1〜P{len(h.spec['long_life']['sleeves'])}・床点検口 {len(h.spec['long_life']['floor_hatches'])} が対象（S-06・A-03M）"]]
    y = sh.table(12, y - 8, [44, 156], rows, row_h=4.6, h=1.7)
    # 右: かぶり
    cm, cd = st["cover_min"], st["cover_design"]
    sh.text("(2) 最小かぶり厚さと設計かぶり厚さ（mm）", (220, 276), 2.6, "A-TEXT", paper=True)
    rows = [["部位", "告示（ロ）欄", "本件 最小", "本件 設計（＋10）", "v4.39"],
            ["耐力壁 屋内側", "40", str(cm["wall_in"]), str(cd["wall_in"]), "40（wall）"],
            ["耐力壁 屋外側（外断熱あり）", "50（外断熱で 40 可）", str(cm["wall_out"]), str(cd["wall_out"]), "40"],
            ["床スラブ 屋内", "30", str(cm["slab"]), str(cd["slab"]), "30（slab）"],
            ["屋根スラブ 上面（屋外）", "40", str(cm["roof_top"]), str(cd["roof_top"]), "30"],
            ["土に接する壁・床・はり・基礎立上り", "50", str(cm["earth_contact"]), str(cd["earth_contact"]), "50"],
            ["基礎（立上り・捨てコンを除く）", "70", str(cm["foundation"]), str(cd["foundation"]), "70"]]
    y2 = sh.table(220, 273, [56, 38, 22, 28, 24], rows, row_h=4.6, h=1.7)
    side_panel(sh, 220, y2 - 4, [("h", "注記"),
        ("t", "外断熱面の 10 減は使わない（評価機関の解釈に依らず耐久の A を優先。外壁の屋外側は最小 50・設計 60）。"),
        ("t", "最小かぶりは（ロ）欄の値。設計かぶりは施工誤差（10）を見込んだ値で、配筋検査でかぶりを全数確認する。"),
        ("t", "壁 t250 のダブル配筋は、屋外 60＋屋内 50 で有効せいが v4.39 より約 20 減る。構造設計者が計算で確認する（LEGAL「劣化対策（RC）」）。"),
        ("t", "W/C は生コン工場の配合計画書で確認する（呼び強度 30 相当の見込み・推定）。増分費用は約 60万〜120万円【推定】。")], width=170)
    yy = y2 - 52
    sh.text("(4) 検査", (220, yy), 2.6, "A-TEXT", paper=True)
    rows = [["検査", "内容"],
            ["配筋検査", "かぶり・スペーサー・開口補強・スリーブ（SL-P1〜13）の位置を全数"],
            ["コンクリート受入れ", "スランプ・空気量・塩化物・温度、W/C は配合計画書・納入書"],
            ["打設後", "かぶり・中性化の非破壊測定は抜取り。養生日数の記録"],
            ["記録", "試験成績・写真を保存（法11条の記録。M-07・docs/maintenance_plan.md）"]]
    sh.table(220, yy - 3, [34, 156], rows, row_h=4.6, h=1.7)
    return sh


# ================================================================ S-06
def pit_plan(h, number):
    ll = h.spec["long_life"]
    sh = frame(h, number, "床下ピット伏図（人通口・配管・掃除口・釜場）", 100)
    t = T(sh, (0, 0), (38, 76))
    polys, holes = [], []
    for w in h.walls:
        if w.floor != "FDN" or w.cat != "wall":
            continue
        x0, y0, _, x1, y1, _ = w.rect(w.a, w.b, 0, 1)
        polys.append(sbox(*t(x0, y0), *t(x1, y1)))
        for op in w.openings:
            ox0, oy0, _, ox1, oy1, _ = w.rect(op.u0, op.u1, 0, 1)
            holes.append(sbox(*t(ox0, oy0), *t(ox1, oy1)))
    u = unary_union(polys).difference(unary_union(holes))
    sh.hatch_polys(list(iter_polygons(u)))
    for pts in iter_lines(u):
        sh.pline(pts, "S-COLS")
    b = [bx for bx in h.boxes if bx.tag == "基礎スラブ"][0]
    sh.rect(*t(b.x0, b.y0), *t(b.x1, b.y1), "S-FNDN")
    grid(h, sh, t)
    hdim(sh, t, h.gx, -1450)
    vdim(sh, t, h.gy, -1450)
    # 区画名
    for n, (x0, y0, x1, y1) in MT.cells(h).items():
        sh.text(n, t((x0 + x1) / 2 - 1500, (y0 + y1) / 2 + 2200), 2.4, "A-TEXT", "MIDDLE_CENTER")
    # 人通口
    for mid, wall, u0, u1, a, bb in ll["manways"]:
        w = _wall_c(h, wall)
        r = w.rect(u0, u1, 0, 1)
        sh.rect(*t(r[0], r[1]), *t(r[3], r[4]), "M-INSP", lineweight=35)
        mx, my = (r[0] + r[3]) / 2, (r[1] + r[4]) / 2
        dx, dy = (350, 0) if w.axis == "y" else (0, 350)
        sh.text(mid, t(mx + dx + (200 if w.axis == "y" else 0), my + dy), 1.3, "A-TEXT", "MIDDLE_LEFT" if w.axis == "y" else "BOTTOM_CENTER")
    # 床点検口（上階の位置）
    for hid, room, r, _ in ll["floor_hatches"]:
        sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "A-HIDDEN", lineweight=35)
        sh.line(t(r[0], r[1]), t(r[2], r[3]), "A-HIDDEN")
        sh.text(hid, t((r[0] + r[2]) / 2, r[3] + 250), 1.4, "A-TEXT", "BOTTOM_CENTER")
    # 汚水（主管・枝管）・給水
    sh.pline([t(*p) for p in ll["main"]], "E-SEWER", lineweight=50)
    for br in ll["branches"]:
        sh.pline([t(*p) for p in br], "E-SEWER", lineweight=25)
    sh.pline([t(*p) for p in ll["water_pit"]], "E-WATER", lineweight=35)
    sh.text("汚水 主管 φ150 1/100 →SL-P1（GL+100）", t(7000 + 350, 2600), 1.4, "A-TEXT", "MIDDLE_LEFT")
    sh.text("給水 φ25 →WR（1F スラブのスリーブ）→HD-1", t(14800 + 350, 3500), 1.4, "A-TEXT", "MIDDLE_LEFT")
    sx, sy = ll["water_pit"][-1]
    sh.text("WR", t(sx + 250, sy), 1.4, "A-TEXT", "MIDDLE_LEFT")
    # 掃除口
    for cid, x, y, cell, where in ll["cleanouts"]:
        sh.circle(t(x, y), 1.1 * sh.S, "E-CO", lineweight=35)
        sh.circle(t(x, y), 0.5 * sh.S, "E-CO")
        sh.text(cid, t(x + 200, y + 250), 1.3, "A-TEXT", "BOTTOM_LEFT")
    # スリーブ
    for sl in ll["sleeves"]:
        x, y = _sleeve_xy(h, sl)
        sh.circle(t(x, y), max(sl[3] / 2, 120), "M-INSP", lineweight=25)
        w = _wall_c(h, sl[1])
        off = (0, -330) if sl[1] == "S" else ((260, 120) if w.axis == "y" else (0, 300))
        sh.text(sl[0], t(x + off[0], y + off[1]), 1.2, "A-TEXT", "MIDDLE_LEFT" if sl[1] != "S" else "TOP_CENTER")
    # 釜場
    s = ll["pit"]["sump"]
    sh.rect(*t(s[0], s[1]), *t(s[2], s[3]), "M-INSP", lineweight=35)
    sh.line(t(s[0], s[1]), t(s[2], s[3]), "M-INSP")
    sh.text("釜場 SP", t(s[2] + 150, (s[1] + s[3]) / 2), 1.4, "A-TEXT", "MIDDLE_LEFT")
    for xb in (16550, 16850):                                       # 束壁（既存・破線。v4.41 x −1,000）
        sh.line(t(xb, 100), t(xb, 8800), "A-HIDDEN")
    sh.view_title("床下ピット伏図", "1:100", (12, 22))
    sh.text("網掛け=ピットの RC 壁（GL±0〜1FL）、□=人通口 W600×H700（下端 GL+200）、破線□×=1F の床点検口、◎=掃除口、○=スリーブ、破線=束壁", (12, 15), 1.8, "A-TEXT", paper=True)
    sh.text(f"ピットの有効高さ {ll['pit']['slab_bottom']}（GL±0〜1F スラブ下端）。外の防水扉は廃止（想定浸水深より下・防犯・基礎の連続性）。点検は屋内の床点検口から", (12, 10.5), 1.8, "A-TEXT", paper=True)
    # 右欄の表
    sh.text("人通口（W600×H700・下端 GL+200・開口補強）", (250, 280), 2.6, "A-TEXT", paper=True)
    rows = [["ID", "壁", "位置 u（mm）", "つなぐ区画"]] + [[m[0], m[1], f"{m[2]:,}〜{m[3]:,}", f"{m[4]}↔{m[5]}"] for m in ll["manways"]]
    y = sh.table(250, 277, [18, 14, 42, 36], rows, row_h=4.2, h=1.7)
    sh.text("配管スリーブ（打設前に入れる・S-10）", (250, y - 4), 2.6, "A-TEXT", paper=True)
    rows = [["ID", "壁・位置", "径", "高さ GL", "用途"]] + [[s_[0], f"{s_[1]} {s_[2]:,}", f"φ{s_[3]}", f"+{s_[4]}", s_[5]] for s_ in ll["sleeves"]]
    y = sh.table(250, y - 7, [16, 22, 12, 14, 66], rows, row_h=4.2, h=1.6)
    side_panel(sh, 250, y - 3, [("t", "人通口の位置: 交差部から 900 以上・上の 1F 開口の中央・配管スリーブ・電力管から 500 以上。スリーブ相互・人通口から 450 以上。開口補強は構造計算で確定（S-05）。"),
                                ("t", "9 区画は人通口 12 でつながり、床点検口 FH-1〜3（機械室／ランドリー／ホール）の下の区画から最大 2 つの人通口で全区画へ到達する。")], width=130)
    return sh


# ================================================================ A-03M
def _floor_cut(h, sh, t, f):
    cut = h.fl[f] + 1200
    for b in h.boxes:
        if b.cat in ("wall", "partition") and b.level != "EXT" and b.level == f and b.z0 < cut < b.z1 and b.mat != "insul":
            sh.rect(*t(b.x0, b.y0), *t(b.x1, b.y1), "A-CUT" if b.cat == "wall" else "A-CUT-LGS", lineweight=35 if b.cat == "wall" else 18)


def inspection_plan(h, number):
    ll = h.spec["long_life"]
    sh = frame(h, number, "維持管理（点検口）計画図 1F・2F", 150)
    sh.text("維持管理（点検口）計画図 — 床点検口 FH・天井点検口 CH・PS・ヘッダー HD・立上り WR（床下ピットの点検経路は S-06）", (12, 282), 3.0, "A-TEXT", paper=True)
    for k, f in enumerate(("1F", "2F")):
        t = T(sh, (0, 0), (20 + k * 130, 140))
        _floor_cut(h, sh, t, f)
        for r in h.rooms:
            if r.floor == f and not r.name.endswith("の下"):
                cx, cy = r.label_at if r.label_at else ((r.rect[0] + r.rect[2]) / 2, (r.rect[1] + r.rect[3]) / 2)
                sh.text(r.name.split("（")[0][:8], t(cx, cy), 1.0, "A-ROOM", "MIDDLE_CENTER")
        if f == "1F":
            for hid, room, r, _ in ll["floor_hatches"]:
                sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "M-INSP", lineweight=50)
                sh.line(t(r[0], r[1]), t(r[2], r[3]), "M-INSP")
                sh.line(t(r[0], r[3]), t(r[2], r[1]), "M-INSP")
                sh.text(hid, t((r[0] + r[2]) / 2 + 450, (r[1] + r[3]) / 2 - 650), 1.3, "A-TEXT", "TOP_CENTER")
            for hid, room, r, _ in ll["ceiling_hatches"]:
                sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "A-HIDDEN", lineweight=35)
                sh.line(t(r[0], r[1]), t(r[2], r[3]), "A-HIDDEN")
                sh.text(hid, t(r[2] + 150, r[3] + 150), 1.3, "A-TEXT", "BOTTOM_LEFT")
            for pid, room, r, front, note in ll["ps"]:
                sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "M-INSP", lineweight=50)
                sh.hatch_polys([sbox(*t(r[0], r[1]), *t(r[2], r[3]))], pattern="ANSI31", spacing=1.2, layer="M-INSP")
                sh.text(pid, t((r[0] + r[2]) / 2, r[3] + 150), 1.3, "A-TEXT", "BOTTOM_CENTER")
            hd = [x for x in ll["headers"] if x[1] == "1F"][0]
            r = hd[2]
            sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "E-WATER", lineweight=50)
            sh.text(hd[0], t(r[0] - 150, r[3] + 150), 1.3, "A-TEXT", "BOTTOM_RIGHT")
            wx, wy = ll["water_pit"][-1]
            sh.circle(t(wx, wy), 0.9 * sh.S, "E-WATER", lineweight=35)
            sh.text("WR", t(wx + 250, wy - 150), 1.2, "A-TEXT", "MIDDLE_LEFT")
        else:
            for pid, room, r, front, note in ll["ps"]:                  # 2F は PS の上の通り（破線）
                sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "A-HIDDEN", lineweight=35)
                sh.text(pid + " ↑", t((r[0] + r[2]) / 2, r[3] + 150), 1.3, "A-TEXT", "BOTTOM_CENTER")
            hd = [x for x in ll["headers"] if x[1] == "2F"][0]
            r = hd[2]
            sh.rect(*t(r[0], r[1]), *t(r[2], r[3]), "E-WATER", lineweight=50)
            sh.text(hd[0], t(r[0] - 150, r[3] + 150), 1.3, "A-TEXT", "BOTTOM_RIGHT")
        sh.text("1階" if f == "1F" else "2階（水回りの排水はスラブを貫通するスリーブだけ。床点検口は設けない）", t(0, -1200), 2.0, "A-TEXT", "TOP_LEFT")
    sh.text("凡例: 実線□×=床点検口 FH（600角）　破線□×=天井点検口 CH（450角）　斜線□=PS　青□=ヘッダー HD　○=給水の立上り WR", (20, 120), 1.8, "A-TEXT", paper=True)
    X = 285
    sh.text("点検口の表", (X, 280), 2.6, "A-TEXT", paper=True)
    rows = [["ID", "室", "寸法", "仕様"]]
    rows += [[a, b, "600×600（有効 550）", "ステンレス枠 見付 6・内蓋に周りと同じ床材を落とし込み・段差 0（H-6）・気密パッキン・鍵付き。下の区画: " + MT.cell_of(h, (c[0] + c[2]) / 2, (c[1] + c[3]) / 2)] for a, b, c, d in ll["floor_hatches"]]
    rows += [[a, b, "450×450", "額縁なし・目地 3 の埋込型・マグネット式（H-7・H-8）" if a != "CH-3" else "UB 付属の天井点検口"] for a, b, c, d in ll["ceiling_hatches"]]
    y = sh.table(X, 277, [12, 24, 26, 63], rows, row_h=4.2, h=1.6)
    sh.text("PS（パイプスペース）・ヘッダー", (X, y - 4), 2.6, "A-TEXT", paper=True)
    rows = [["ID", "室", "扉", "通す管"]] + [[a, b, "点検扉 1 枚 FL+60〜2,700・" + {"-x": "西", "+x": "東", "-y": "南"}[d] + "向き", e] for a, b, c, d, e in ll["ps"]]
    rows += [[x[0], "機械室" if x[0] == "HD-1" else "2F 収納（トイレ）", "FL+300〜900", x[3]] for x in ll["headers"]]
    y = sh.table(X, y - 7, [12, 24, 32, 55], rows, row_h=4.2, h=1.6)
    side_panel(sh, X, y - 3, [("t", "PS は LGS＋耐水 PB・EP で、上部の天井内も点検できる高さまで扉を設ける。家具として登録し、すき間・扉の軌跡・照明からの離隔を検査済み。"),
                              ("t", "浮き床の下は継手のない区間だけ（評価書 3.1 #8）。2F の床点検口は設けず、器具・トラップから清掃する。照明・AP・LAN 口・SL-C 系から 1m 以上離す。")], width=122)
    return sh


# ================================================================ M-05
def plumbing_sheet(h, number):
    ll = h.spec["long_life"]
    u = h.spec["utilities"]
    sh = frame(h, number, "給排水衛生 系統図・ピット内の経路・屋外の縦断", 1, label="—")
    sh.text("給排水衛生 系統図 — 給水は Dotcon+・土間の下を通さず、汚水は基礎立上り（GL+100）から出す（v4.40）", (12, 282), 3.0, "A-TEXT", paper=True)
    W, H_, G = 40, 12, 6
    xs = [12 + i * (W + G) for i in range(5)]
    sh.text("(1) 給水系統", (12, 276), 2.4, "A-TEXT", paper=True)
    water = ["量水器 MW（門前広場・門の塀の外面 x11,600）", "W-1 点検桝（止水栓）→ さや管 VU75（アプローチの横断 1.72m）→ W-2 点検桝", "管路帯（砂利・Dotcon+ の下 0m）→ 南面 SL-P7（つば付き止水）",
             "床下ピット 給水 φ25 →SL-P8 → 立上り WR（SF7→2F 機械室）", "HD-1 ヘッダー（機械室）→ 1F の各器具"]
    for i, tx in enumerate(water):
        _flow_box(sh, xs[i], 270, W, H_ + 8, tx, "E-WATER")
        if i:
            _flow_line(sh, [(xs[i - 1] + W, 260), (xs[i], 260)], "E-WATER")
    _flow_box(sh, xs[4], 246, W, H_, "PS-2（さや管）→ HD-2 → 2F の各器具", "E-WATER")
    _flow_line(sh, [(xs[4] + W / 2, 250), (xs[4] + W / 2, 246)], "E-WATER")
    sh.text("(2) 排水系統（汚水）", (12, 228), 2.4, "A-TEXT", paper=True)
    drain = ["2F 器具（トイレ 2 室）→ スラブのスリーブ", "PS-2・PS-3（掃除口 CO-2・CO-3）→ 床下ピットの枝管（1/100）", "主管 φ150 x7,000（CO-4・CO-5）→ SL-P3・SL-P2 → 出口 SL-P1（GL+100・つば付き止水）",
             "汚1（建物出口桝・逆流防止弁・掃除口）→ 汚2（2/100）→ 汚3 → 汚4 → 汚5", "汚6 最終桝（門前・管底 約GL−320）→ 公共下水（南側道路）"]
    for i, tx in enumerate(drain):
        _flow_box(sh, xs[i], 222, W, H_ + 8, tx, "E-SEWER")
        if i:
            _flow_line(sh, [(xs[i - 1] + W, 212), (xs[i], 212)], "E-SEWER")
    sh.text("釜場 SP の排水ポンプ（非常電源）の吐出は雨水系統へ（SL-P13 φ75 GL+800 →縦樋足元の雨水桝・逆止弁付き。地下水・漏水を汚水に入れない）", (12, 196), 1.7, "A-TEXT", paper=True)
    # ピット内のスリーブ表（左下）
    sh.text("(3) ピット内の経路・スリーブ", (12, 188), 2.4, "A-TEXT", paper=True)
    rows = [["ID", "壁・位置", "径・高さ", "用途"]] + [[s[0], f"{s[1]} {s[2]:,}", f"φ{s[3]}・GL+{s[4]}", s[5]] for s in ll["sleeves"]]
    y = sh.table(12, 185, [18, 26, 28, 130], rows, row_h=4.0, h=1.6)
    sh.text("掃除口（ピット内。床点検口から人通口で到達）: " + "／".join(f"{c[0]} {c[4]}（{c[3]}）" for c in ll["cleanouts"]), (12, y - 4), 1.5, "A-TEXT", paper=True)
    # 右: 縦断表・給水表
    X = 252
    sh.text("(4) 汚水の縦断（出口〜最終桝）", (X, 276), 2.4, "A-TEXT", paper=True)
    pr = MT.sewer_profile(h)
    rows = [["点", "座標 x, y", "管底 GL", "勾配", "区間", "土かぶり"]]
    for n, x, y_, inv, sl, d, cov in pr:
        rows.append([n, f"{x:,.0f}, {y_:,.0f}", f"{inv:+.0f}", "—" if not sl else f"{sl * 100:.0f}/100", "—" if not d else f"{d / 1000:.1f}m", f"{cov:.0f}"])
    y = sh.table(X, 273, [12, 34, 20, 16, 16, 20], rows, row_h=4.0, h=1.6)
    L = MT.sewer_length_m(h)
    y = side_panel(sh, X, y - 4, [("t", f"延長 約{L:.1f}m。汚2 以降を 1.5/100 とした場合の最終桝の管底 約GL{MT.final_invert_15(h):+.0f}（要確認）。出口から約5.3m は土かぶり 300 未満＝管路帯の砂利の中で樹脂の保護板（外せる）")], width=150)
    sh.text("(5) 給水の区間", (X, y - 2), 2.4, "A-TEXT", paper=True)
    rows = [["区間", "長さ", "覆い", "土被り"]] + [[a, f"{b:.1f}m", c, d] for a, b, c, d in MT.water_sections(h)]
    y = sh.table(X, y - 5, [20, 14, 70, 34], rows, row_h=4.0, h=1.6)
    y = side_panel(sh, X, y - 4, [("t", f"合計 {sum(r[1] for r in MT.water_sections(h)):.1f}m（Dotcon+ の下 0m。さや管の横断 {MT.cover_check(h)['sleeve_m'] / 1000:.2f}m）")], width=150)
    sh.text("(6) 管種・接合", (X, y - 2), 2.4, "A-TEXT", paper=True)
    rows = [["系統", "管種・接合"],
            ["給水（屋外）", f"水道用ポリエチレン管（または架橋ポリエチレン管）{u['water']['dia']}・融着"],
            ["給水・給湯（屋内）", "架橋ポリエチレン管（さや管ヘッダー方式）。HD-1・HD-2。さや管 VU75 は引抜き交換可"],
            ["汚水", f"{u['sewer']['pipe']}（VU）・接着。通気は PS から立上げ"],
            ["スリーブ", "VU φ200（SL-P1〜P3）・つば付き止水（SL-P1・P7）。打設前に入れる"]]
    y = sh.table(X, y - 5, [26, 128], rows, row_h=4.0, h=1.6)
    side_panel(sh, X, y - 3, [("t", "Dotcon+・土間の下を通さない。管路帯（砂利・幅 600〜1,200）は外せる。アプローチの横断だけさや管（評価機関でさや管が「コンクリートの下」に当たるか確認。当たる場合は横断部 1.5m 幅を外せる舗装に替える）。")], width=150)
    return sh


# ================================================================ M-06
def energy_ll_sheet(h, number):
    ee = h.spec["long_life"]["energy"]
    sh = frame(h, number, "省エネ（長期優良）熱橋込み外皮・ηAC・BEI 概算", 1, label="—")
    tb, ea, be = PF.envelope_tb(h), PF.eta_ac(h), PF.bei_estimate(h)
    env = tb["env"]
    gr = ee["grade"]
    sh.text("省エネ（長期優良住宅）— 熱橋込み外皮・ηAC・一次エネルギーの概算。BEI は概算で、住宅版プログラム（WEBPRO は非住宅用）で確定する", (12, 282), 3.0, "A-TEXT", paper=True)
    sh.text("(1) 外皮（RC 外面基準、PF.envelope() の面積・U）", (12, 276), 2.4, "A-TEXT", paper=True)
    rows = [["部位", "面積 m²", "U W/m²K", "温度差係数", "面積×U×係数 W/K"]] + [[n, f"{a:,.1f}", f"{u:.2f}", f"{f:.1f}", f"{a * u * f:,.1f}"] for n, a, u, f in env["parts"]]
    rows.append(["計（熱橋なし）", f"{env['area']:,.1f}", "—", "—", f"{env['q']:,.2f}（UA {env['UA']:.3f}）"])
    y = sh.table(12, 273, [52, 26, 26, 26, 50], rows, row_h=4.4, h=1.7)
    sh.text("(2) 熱橋（ψ・χ は仮定値）", (12, y - 5), 2.4, "A-TEXT", paper=True)
    rows = [["熱橋", "ψ W/mK・χ W/K", "長さ・個数", "ψL W/K"]] + [[n, f"{p:.2f}", f"{l:,.1f}m", f"{v:.2f}"] for n, p, l, v in tb["items"]]
    rows.append(["庇のブラケット（断熱パッド）", f"χ {ee['chi']['value']:.2f}", f"{ee['chi']['n']} か所（南 9・西 4）", f"{tb['chi']:.2f}"])
    rows.append(["熱橋込み q・UA", "—", "—", f"q {tb['q_tb']:,.2f}　UA {tb['UA_tb']:.3f}"])
    y = sh.table(12, y - 8, [62, 34, 44, 40], rows, row_h=4.4, h=1.7)
    sh.text("(3) 外皮の判定", (12, y - 5), 2.4, "A-TEXT", paper=True)
    rows = [["項目", "本件", "等級5", "等級6", "等級7"],
            ["UA（W/m²K）", f"{tb['UA_tb']:.3f}（熱橋込み）", f"{gr['ua'][0]:.2f} 以下", f"{gr['ua'][1]:.2f} 以下", f"{gr['ua'][2]:.2f} 以下"],
            ["ηAC", f"{ea['value']:.2f}（ZIP スクリーンは算入しない＝安全側）", f"{gr['eta_ac']} 以下", "—", "—"]]
    y = sh.table(12, y - 8, [30, 80, 28, 28, 28], rows, row_h=4.4, h=1.7)
    nu = ee["nu"]
    side_panel(sh, 12, y - 4, [("t", f"ηAC = (窓の A×g×{ee['f_win']}×ν ＋ 不透明部 0.034×U×A×ν) ÷ 外皮面積 ×100。冷房期の方位係数 ν（6地域）N {nu['N']}・E {nu['E']}・S {nu['S']}・W {nu['W']}・上面 {nu['top']}（記憶・要確認）。"),
                               ("t", f"energy()・M-01 の値は熱橋を含まない。熱橋込みの暖房は +{be['d_heat_kwh'] / 3.5:,.0f}kWh/年（COP 3.5）。M-01・自家消費の値は変えない。")], width=190)
    # 右: BEI
    X = 220
    sh.text("(4) 一次エネルギー消費量の概算（MJ/年）", (X, 276), 2.4, "A-TEXT", paper=True)
    names = [("heat", "暖房"), ("cool", "冷房"), ("vent", "換気"), ("hw", "給湯"), ("light", "照明")]
    basis = {"heat": "熱橋込み H・HDD → ÷SCOP 3.5×9.76 ／ 基準: 等級4 の外皮（UA 0.87）＋第3種換気 ÷2.6",
             "cool": "÷4.0 ／ 基準: 同じ H で ÷2.4", "vent": "0.24kW 常時 ／ 基準: 第3種 0.3W/(m³/h)", "hw": "HP 1,300kWh ／ 基準: 同じ給湯熱量をガス従来型 効率 0.78",
             "light": "LED 2W/m²・4h ／ 基準: 設計 ×1.6"}
    rows = [["用途", "設計", "基準", "設計の根拠・基準の仮定"]] + [[n, f"{be['design'][k]:,.0f}", f"{be['ref'][k]:,.0f}", basis[k]] for k, n in names]
    rows.append(["計", f"{be['E_design']:,.0f}", f"{be['E_ref']:,.0f}", f"BEI 概算 {be['bei']:.2f}（等級6 {gr['bei6']} 以下・等級8 0.65 以下）"])
    y = sh.table(X, 273, [16, 20, 20, 134], rows, row_h=4.4, h=1.7)
    sh.text("加湿・家電・ジム・シアター・PV は除く（プログラムと同じ扱い）。BEI は概算で、LEGAL は要確認（住宅版で確定）", (X, y - 4), 1.6, "A-TEXT", paper=True)
    main = sum(r.area for r in h.rooms if r.floor == "1F" and r.name in ("リビング・ダイニング", "キッチン"))
    hab = sum(r.area for r in h.rooms if r.habitable) - main
    total = sum(h.floor_area(f) for f in h.floors)
    sh.text("(5) 住宅版プログラムの入力表（案）", (X, y - 12), 2.4, "A-TEXT", paper=True)
    rows = [["入力項目", "値"],
            ["地域区分", "6（八王子）"],
            ["床面積", f"合計 {total:,.1f}m²。主たる居室（LDK・キッチン）{main:.1f}m²・その他の居室 {hab:.1f}m²・非居室 {total - main - hab:.1f}m²（h.rooms の habitable で集計）"],
            ["外皮", f"部位・U（壁 {PF.U['wall']}・屋根 {PF.U['roof']}・床 {PF.U['floor']}・窓 {PF.U['window']}・ドア {PF.U['door']}）・ψ・η は (1)(2)"],
            ["暖冷房", "ダクト式セントラル空調（2 系統）"],
            ["換気", "第1種 全熱交換（比消費電力 0.12W/(m³/h)・温度交換効率 0.70）"],
            ["給湯", "電気ヒートポンプ（JIS 効率は製品で）・節湯水栓"],
            ["照明", "全 LED・調光・人感（収納 3 台）"],
            ["太陽光", "等級判定に算入しない（全量自家消費、M-01）"]]
    y = sh.table(X, y - 15, [30, 160], rows, row_h=4.4, h=1.7)
    side_panel(sh, X, y - 4, [("t", "ψ・χ・ν・基準仕様はすべて仮定・記憶（要確認）。外皮の判定（等級5・6・7）は熱橋込みで余裕がある。BEI は基準仕様の仮定に左右されるため、実施設計で住宅版プログラムの計算書で確定する。")], width=190)
    return sh


# ================================================================ M-07
def maintenance_sheet(h, number):
    pl = MT.plan(h)
    fn = MT.funding(h, pl)
    sh = frame(h, number, "維持保全計画（30年）・資金計画", 1, label="—")
    sh.text("維持保全計画（30 年）・資金計画 — 点検の周期は最大 10 年以内、費用は 2026 年単価の仮定（税込・万円）", (12, 282), 3.0, "A-TEXT", paper=True)
    fy = lambda ys: "—" if not ys else ("毎年" if len(ys) > 8 else "・".join(str(y) for y in ys))

    rows = [["ID", "部位", "区分", "点検", "点検費", "更新", "更新費", "更新の内容", "30 年計"]]
    for rid, name, cls, pi, pc, ui, uc, note, ins, upd, c in pl["rows"]:
        rows.append([rid, name, cls, f"{pi}年ごと（{fy(ins)}）", f"{pc}", f"{ui}年・{fy(upd)}" if ui else "—", f"{uc}" if uc else "—", note or "—", f"{c:,}"])
    y = sh.table(12, 276, [14, 62, 12, 50, 12, 36, 12, 66, 14], rows, row_h=4.2, h=1.5)
    rows = [["区分", "30 年計（万円）"]] + [[k, f"{pl['by_class'][k]:,}"] for k in ("構造", "雨水", "給排水", "任意")]
    rows += [["告示の対象（構造・雨水・給排水）", f"{pl['required']:,}"], ["臨時点検の予備（年 5 × 30）", f"{pl['reserve']:,}"], ["総額", f"{pl['total']:,}"],
             ["積立（月）", f"約{pl['monthly_all']:.1f}万円（対象分＋予備だけなら {pl['monthly_required']:.1f}万円）"]]
    y2 = sh.table(12, y - 4, [74, 110], rows, row_h=4.2, h=1.7)
    # 年別の棒
    X0, Y0, BW = 205, y - 4, 6.0
    mx = max(pl["per_year"][1:])
    sh.text("年別の費用（万円。点検・更新、予備を除く）", (X0, Y0 + 1), 2.2, "A-TEXT", paper=True)
    base = Y0 - 46
    for yv in range(1, pl["years"] + 1):
        v = pl["per_year"][yv]
        hh = 40.0 * v / mx
        sh.rect(*sh.P(X0 + (yv - 1) * BW, base), *sh.P(X0 + (yv - 1) * BW + BW - 1.0, base + max(hh, 0.3)), "G-TABLE")
        if yv % 5 == 0:
            sh.text(str(yv), (X0 + (yv - 1) * BW + 2, base - 4), 1.6, "A-TEXT", "MIDDLE_CENTER", paper=True)
        if v >= 400:
            sh.text(f"{v:,}", (X0 + (yv - 1) * BW + 2.5, base + hh + 1.5), 1.5, "A-TEXT", "MIDDLE_CENTER", paper=True)
    sh.line(sh.P(X0, base), sh.P(X0 + pl["years"] * BW, base), "A-GROUND")
    sh.text("（年）", (X0 + pl["years"] * BW + 1, base - 4), 1.5, "A-TEXT", paper=True)
    peaks = "・".join(f"{y_}年目 {v:,}" for y_, v in pl["peak_years"][:3])
    sh.text(f"山の年: {peaks}", (X0, base - 9), 1.8, "A-TEXT", paper=True)
    # 規定・資金計画
    yb = min(y2, base - 12) - 4
    side_panel(sh, 12, yb, [("h", "維持保全の規定（告示209号 第4・法11条）"),
        ("t", "点検の周期はすべて 10 年以内。計画期間 30 年。地震（震度5弱以上）・台風・大雨・浸水の後は臨時点検（浸水後はピットの排水・ポンプ・止水を最優先）。点検結果と劣化に応じて計画を見直し、計画変更時も見直す。点検・補修・更新の記録と竣工図・配管図・点検口図（A-03M・S-06・M-05）を保存する。")], width=180)
    sh.text("資金計画（仮定）", (205, yb), 3.0, "A-TEXT", paper=True)
    rows = [["項目", "下限", "上限", "備考"]]
    for n, a, b, note in fn:
        rows.append([n, "" if a is None else f"{a:,.0f}", "" if b is None else f"{b:,.0f}", note])
    sh.table(205, yb - 5, [58, 18, 18, 98], rows, row_h=4.2, h=1.6)
    return sh
