"""CSV / XLSX 書き出し（Excel・Numbers・LibreOffice・Google スプレッドシート）。

値は図面と同じ関数から取る: 室・仕上 = interior.finish_schedule（I-02）、家具 = furniture.schedule_rows（I-05）、
照明 = lighting.lines/downlights/footlights/footlines/illuminance_table（E-06）、建具 = h.fittings・h.walls の開口（A-09）、
壁量 = house_legal.checks の壁量（S-01）。CSV は UTF-8 BOM 付き。
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from shapely.geometry import Point, box as sbox

from . import common as C
from .manifest import COORD_NONE

# 固定の列名（試験で確認する）
HEADERS = {
    "室": ["階", "室名", "面積m2", "天井高mm", "居室", "床", "巾木", "壁", "天井", "配色(v4.29)", "要確認", "仮置き", "根拠"],
    "建具": ["記号", "種別", "名称", "階", "室", "方位", "W_mm", "H_mm", "開き方式", "ガラス", "防火設備", "遮煙", "遮音等級", "防犯CP", "ホスト壁", "要確認", "根拠"],
    "建具表": ["記号", "名称", "W_mm", "H_mm", "個数", "階", "外部", "防火設備", "遮煙", "非常用進入口代替"],
    "仕上": ["階", "室名", "室数", "面積m2", "床", "巾木", "壁", "天井", "備考"],
    "設備": ["区分", "ID", "室", "名称", "x0_mm", "y0_mm", "x1_mm", "y1_mm", "高さmm", "質量kg"],
    "ライフライン": ["項目", "代表値", "出典", "計画"],
    "照明": ["ID", "種別", "階", "室", "x0_mm", "y0_mm", "z_mm", "x1_mm", "y1_mm", "長さmm", "光束lm", "lm/m", "色温度K", "要確認", "仮置き", "根拠"],
    "照度計算": ["階", "室", "面積m2", "目標lx", "U", "列数", "器具長さmm", "lm/m", "計画lx", "ダウン"],
    "家具": ["ID", "階・室", "名称", "寸法", "数量", "材質・色", "製品", "床との納まり", "仮置き", "要確認", "根拠"],
    "壁量": ["階", "方向", "耐力壁長さm", "壁量cm/m2", "判定"],
    "法規": ["区分", "項目", "根拠", "規定・要求", "計画", "判定"],
    "ネットワーク": ["区分", "ID", "階", "室・役割", "x_mm", "y_mm", "高さmm", "EIRP_dBm", "口数・本数", "経由・備考"],
    "凡例": ["項目", "内容"],
}
CSV_NAMES = {"室": "rooms", "建具": "openings", "建具表": "fittings_schedule", "仕上": "finishes", "設備": "equipment", "ライフライン": "lifeline",
             "照明": "lights", "照度計算": "illuminance", "家具": "furniture", "壁量": "wall_quantity", "法規": "legal_checks", "ネットワーク": "network", "凡例": "legend"}
SOURCES = {"室": "A-03/A-04, I-02", "建具": "A-09", "建具表": "A-09", "仕上": "I-02/I-02B", "設備": "A-03/A-04, E-01", "ライフライン": "A-02Z2",
           "照明": "E-04/E-05/E-06", "照度計算": "E-06", "家具": "I-05", "壁量": "S-01", "法規": "A-11〜", "ネットワーク": "E-01/E-07", "凡例": ""}


def _num(v, nd=3):
    return round(float(v), nd)


def sheet_rooms(h, F):
    import interior as IN
    fin = {(fl, n): t for fl, n, c, a, t in IN.finish_schedule(h)}
    rows = []
    for r in h.rooms:
        t = fin.get((r.floor, r.name), ("", "", "", "", ""))
        try:
            col = IN.color_of(h, r.name)["text"]
        except Exception:                       # noqa: BLE001
            col = ""
        f = F.get(room=r.name)
        rows.append([r.floor, r.name, _num(r.area, 4), r.ch or h.ch[r.floor], "○" if r.habitable else "", t[0], t[1], t[2], t[3], col,
                     "○" if f["confirm"] else "", "", f["basis"]])
    return rows


def _rooms_at(h, floor, x, y):
    out = []
    for r in h.rooms:
        if r.floor == floor and sbox(*r.rect).buffer(200).contains(Point(x, y)):
            out.append(r.name)
    return "／".join(out)


def sheet_openings(h, F):
    glz = h.spec["glazing"]
    rows = []
    for w in h.walls:
        if w.cat == "insul":
            continue
        for op in w.openings:
            if op.operation == "opening":
                continue
            um = (op.u0 + op.u1) / 2
            x, y = (um, w.c) if w.axis == "x" else (w.c, um)
            win = op.kind == "window"
            g = ""
            if win and op.exterior:
                g = glz["build_1f" if op.floor == "1F" else "build_2f"]
            elif win:
                g = "合わせ複層 FIX（室内窓）"
            elif op.glass is True:
                g = "透明扉（合わせ強化 10.8）"
            ts = re.search(r"Ts-\d+", op.name)
            cp = "CP" if (op.exterior or op.label.startswith("SD")) else ""
            f = F.get(tag=op.label)
            rows.append([op.label, "窓" if win else "扉", op.name, op.floor, _rooms_at(h, op.floor, x, y), op.side, round(op.width), round(op.height),
                         op.operation, g, "○" if op.fire else "", "○" if op.smoke_seal else "", ts.group(0) if ts else "", cp,
                         f"{w.floor}-{'X' if w.axis == 'x' else 'Y'}{round(w.c)}-{round(w.a)}～{round(w.b)}", "○" if f["confirm"] else "", f["basis"]])
    return rows


def sheet_fittings(h):
    return [[x["label"], x["name"], x["w"], x["h"], x["count"], "・".join(x["floors"]), "○" if x["exterior"] else "",
             "○" if x["fire"] else "", "○" if x["smoke"] else "", "○" if x["alt_entry"] else ""] for x in h.fittings]


def sheet_finish(h):
    import interior as IN
    return [[fl, n, c, _num(a, 3), t[0], t[1], t[2], t[3], t[4]] for fl, n, c, a, t in IN.finish_schedule(h)]


def sheet_equipment(h):
    rows = []
    for id_, room, name, r, hh in h.spec["mech_rooms"]["equipment"]:
        rows.append(["機械・蓄電", id_, room, name, *[round(v) for v in r], round(hh), ""])
    for name, r, hh, kg in getattr(h, "equipment_cg", h.equipment):
        rows.append(["ジム機器", "", "ジム", name, *[round(v) for v in r], round(hh), kg])
    return rows


def sheet_lifeline():
    import house_sheets as hs
    return [list(r) for r in hs.LIFELINE_STANDARDS[1:]]


def sheet_lights(h, F):
    import furniture as FU
    import lighting as LI
    its = FU.items(h)
    cfg = h.spec["lighting"]
    f_l = F.get(group="照明")
    f_f = F.get(group="足元灯")
    rows = []
    lns = LI.lines(h, its)
    for l in lns:
        rows.append([l["id"], "ライン照明", l["floor"], l["room"], *l["p0"][:2], l["p0"][2], *l["p1"][:2], l["L"], round(l["lm_per_m"] * l["L"] / 1000), l["lm_per_m"],
                     "2200〜5000", "", "○" if f_l["provisional"] else "", f_l["basis"]])
    for i, d in enumerate(LI.downlights(h, its, lns), 1):
        rows.append([f"{d['floor']}-{d['code']}-D{i}", "ダウンライト", d["floor"], d["room"], round(d["p"][0]), round(d["p"][1]), round(d["p"][2]), "", "", "",
                     cfg["downlight"]["max_lm"], "", "2200〜3000", "", "○", f_l["basis"]])
    for d in LI.footlights(h):
        rows.append([d["id"], "足元灯（階段）", d["floor"], d["stair"], round(d["p"][0]), round(d["p"][1]), round(d["p"][2]), "", "", "", cfg["foot"]["lm"], "",
                     cfg["foot"]["kelvin"], "", "○", f_f["basis"]])
    pcs, _mk = LI.footlines(h, its)
    for d in pcs:
        rows.append([d["id"], "足元灯ライン（廊下・ホール）", d["floor"], d["room"], *d["p0"][:2], d["p0"][2], *d["p1"][:2], d["L"], round(d["lm_per_m"] * d["L"] / 1000),
                     d["lm_per_m"], "", "", "○", f_f["basis"]])
    return rows


def sheet_illuminance(h):
    import furniture as FU
    import lighting as LI
    return [[r["floor"], r["room"], _num(r["area"], 2), r["target"], _num(r["U"], 2), r["n"], r["lengths"], r["lm_per_m"], round(r["E"]), r["dl"]]
            for r in LI.illuminance_table(h, FU.items(h)) if r["n"] > 0]


def sheet_furniture(h, F):
    import furniture as FU
    its = FU.items(h)
    rows = []
    for it, r in zip(its, FU.schedule_rows(h, its)):
        f = F.get(room=it.room, group="家具")
        rows.append([*r, "○" if it.provisional else "", "○" if it.note or f["confirm"] else "", f["basis"]])
    return rows


def sheet_walls(h):
    import house_legal
    rows, sm, wq = house_legal.checks(h)
    out = []
    for (fl, d), (L, q) in sorted(wq.items()):
        out.append([fl, d, _num(L, 3), _num(q, 2), "適合（≧12）" if q >= 12 else "不足"])
    out.append(["", "壁厚", "", h.t / 10, "適合（≧15cm）"])
    return out, rows, sm


def sheet_legal(rows):
    return [[r["cat"], r["item"], r["basis"], r["required"], r["planned"], r["result"]] for r in rows]


def sheet_network(h):
    """E-01・E-07 と同じ spec から: AP 16 台・有線 LAN 口・ラック機器・スリーブ。"""
    import wiring as WR
    w = h.spec["wifi"]
    rows = []
    rt = {r["id"]: r for r in WR.routes(h)}
    for a in w["aps"]:
        r = rt[a["id"]]
        via = "→".join("SL-" + v for v in r["via"]) or "直接"
        rows.append(["AP", a["id"], a["floor"], a["role"], *a["xy"], w["ap_h"], a["eirp"], 1,
                     f"配線 {r['length_m']:.1f}m（{via}）" + ("・★水回りの調整用（予備位置 %d, %d）" % tuple(a["alt_xy"]) if a.get("tune") else "")])
    for o in w["lan_outlets"]:
        rows.append(["LAN口", o["id"], o["floor"], o["room"], *o["xy"], o["z"], "", o["n"], o["where"]])
    rk = w["rack"]
    for e in rk["equipment"]:
        rows.append(["ラック機器", rk["id"], "1F", "機械室（東系統）", *rk["xy"], "", "", 1, e])
    sp = w["sleeve_spec"]
    rows.append(["スリーブ", "SL-C1", "1F", "機械室（東系統）床→ONU", *w["entry"]["sleeve_xy"], "", "", 2, "床下ピットからの引込（φ%d）" % sp["dia"]])
    r2 = w["riser"]
    rows.append(["スリーブ", r2["id"], "1F→2F", "縦配線（スラブ）", *r2["xy"], "", "", r2["n"], f"φ{r2['dia']}×{r2['n']}（{r2['spare']} 本予備）→2F WIC 北東角の配線ボックス"])
    for s in w["sleeves"]:
        rows.append(["スリーブ", s["id"], s["floor"], f"{s['wall']} 壁", *s["xy"], sp["z"], "", sp["n"], f"φ{sp['dia']}×{sp['n']}（1 本予備）→{s['to']}"])
    return rows


def sheet_legend(h, sm, counts):
    from datetime import date
    d = [["版", C.VERSION], ["案件", f"{C.PROJECT_NAME} {h.spec['project']['name']}"], ["所在地", h.spec["project"]["location"]],
         ["フェーズ", h.spec["project"]["phase"] + "（実施設計の精度はない）"],
         ["単位", "長さ mm、面積 m2、質量 kg、光束 lm、色温度 K、照度 lx（列名に明記）"],
         ["座標", "x・y は建物ローカル（原点 = X1・Y1 壁芯交点、+X = 東向きに X1→X4、+Y = Y1→Y4、mm、設計GL z=0）。真北は建物 +Y から "
                  f"{C.true_north_deg(h):+.2f} 度（反時計回り正）"],
         ["要確認／仮置き", "○ = 要確認／仮置き。根拠は data/export_flags.yaml（ブリーフ35・36章の Q 番号ほか）"],
         ["敷地面積m2", _num(sm["site_area"], 3)], ["建築面積m2", _num(sm["building_area"], 3)], ["延べ面積m2", _num(sm["total"], 3)],
         ["建ぺい率", _num(sm["coverage"], 4)], ["容積率", _num(sm["far"], 4)], ["最高高さm", _num(sm["height"], 3)]]
    for k, v in counts.items():
        d.append([f"行数: {k}", v])
    for k, src in SOURCES.items():
        if src:
            d.append([f"出典図面: {k}", src])
    return d


def build_tables(h):
    """{シート名: (列名, 行)}。"""
    F = C.Flags(h.root)
    walls, legal_rows, sm = sheet_walls(h)
    data = {
        "室": sheet_rooms(h, F), "建具": sheet_openings(h, F), "建具表": sheet_fittings(h), "仕上": sheet_finish(h), "設備": sheet_equipment(h),
        "ライフライン": sheet_lifeline(), "照明": sheet_lights(h, F), "照度計算": sheet_illuminance(h), "家具": sheet_furniture(h, F),
        "壁量": walls, "法規": sheet_legal(legal_rows), "ネットワーク": sheet_network(h),
    }
    data["凡例"] = sheet_legend(h, sm, {k: len(v) for k, v in data.items()})
    return {k: (HEADERS[k], v) for k, v in [(n, data[n]) for n in HEADERS]}, sm


def write(h, outdir, mf):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    outdir = Path(outdir)
    tabs, sm = build_tables(h)
    (outdir / "csv").mkdir(exist_ok=True)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, (head, rows) in tabs.items():
        for r in rows:
            assert len(r) == len(head), (name, r)
        p = outdir / "csv" / f"{CSV_NAMES[name]}.csv"
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)
        mf.add(p, "CSV(UTF-8 BOM)", COORD_NONE, note=f"{len(rows)} 行")
        ws = wb.create_sheet(name)
        ws.append(head)
        for r in rows:
            ws.append(r)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="4F5B2A")
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for i, col in enumerate(ws.columns, 1):
            width = max(len(str(c.value)) if c.value is not None else 0 for c in list(col)[:200])
            ws.column_dimensions[get_column_letter(i)].width = min(60, max(8, width * 1.6 + 2))
    p = outdir / "schedules.xlsx"
    wb.save(p)
    mf.add(p, "XLSX", COORD_NONE, note=f"{len(tabs)} シート")
