"""E-07 通信・LAN 配線図（v4.32）: ラック・縦配線・幹線・SL-C スリーブ・LAN 口・引込。打設前の施工図に使う。"""
from __future__ import annotations

from shapely.geometry import box as sbox  # noqa: F401

import wiring as WR
from house_sheets import frame
from sheetlib import T, side_panel


def _skip2f(r):
    """2F の経路は配線ボックス（pts[2]）以降を描く。path 内での pts[2] の位置を返す。"""
    return r["path"].index(r["pts"][2])


def wiring_sheet(h, number):
    w = h.spec["wifi"]
    sh = frame(h, number, "通信・LAN 配線図", 200)
    sh.text("通信・LAN 配線図 — ラック（機械室・東系統 MC-6）・縦配線・天井内の幹線・RC スリーブ SL-C・有線 LAN 口・引込（RC スリーブは打設前に入れ、後から穴をあけない）", (12, 280), 3.0, "A-TEXT", paper=True)
    routes = WR.routes(h)
    pairs = WR.sleeve_pairs(h)
    for k, f in enumerate(("1F", "2F")):
        t = T(sh, (0, 0), (22 + k * 112, 150))
        cut = h.fl[f] + 1200
        for b in h.boxes:
            if b.cat in ("wall", "partition") and b.level != "EXT" and b.z0 < cut < b.z1 and b.mat != "insul":
                sh.rect(*t(b.x0, b.y0), *t(b.x1, b.y1), "A-CUT" if b.cat == "wall" else "A-CUT-LGS", lineweight=35 if b.cat == "wall" else 18)
        for r in routes:                                              # 幹線（天井内）: 各階の AP への経路
            if r["floor"] == f:
                pts = r["path"] if f == "1F" else r["path"][_skip2f(r):]   # 2F はスラブスリーブ SL-C2 の上（配線ボックス）から
                sh.pline([t(*p) for p in pts], "E-COMM", lineweight=25)
        for a in w["aps"]:
            if a["floor"] == f:
                sh.circle(t(*a["xy"]), 1.3 * sh.S, "A-CUT", lineweight=25)
                sh.text(a["id"][2:], t(a["xy"][0], a["xy"][1] - 650), 1.2, "A-TEXT", "MIDDLE_CENTER")
        for sid, (sf, wall, ps) in pairs.items():                       # RC スリーブ
            if sf == f:
                mx, my = (ps[0][0] + ps[1][0]) / 2, (ps[0][1] + ps[1][1]) / 2
                sh.circle(t(mx, my), 1.0 * sh.S, "E-SPARE", lineweight=35)
                dx, dy = (500, 0) if wall.startswith("Y") else (0, 0)
                sh.text(sid[3:], t(mx + 520, my + (350 if wall.startswith("Y") else 0)), 1.2, "A-TEXT", "LEFT")
        for o in w["lan_outlets"]:                                       # LAN 口
            if o["floor"] == f:
                x, y = o["xy"]
                sh.rect(*t(x - 150, y - 150), *t(x + 150, y + 150), "A-SYMB", lineweight=35)
        rx, ry = w["rack"]["xy"]
        if f == "1F":
            sh.rect(*t(rx - 300, ry - 500), *t(rx + 300, ry + 500), "E-COMM", lineweight=50)
            sh.text("MC-6", t(rx - 3400, ry), 1.6, "A-TEXT", "MIDDLE_CENTER")
            for nm, key in (("SL-C1", w["entry"]["sleeve_xy"]), ("SL-C2", w["riser"]["xy"])):
                sh.circle(t(*key), 1.0 * sh.S, "E-SPARE", lineweight=35)
            sh.text("C1", t(w["entry"]["sleeve_xy"][0] - 450, w["entry"]["sleeve_xy"][1] - 700), 1.2, "A-TEXT", "MIDDLE_CENTER")
            sh.text("C2", t(w["riser"]["xy"][0] + 300, w["riser"]["xy"][1] - 700), 1.2, "A-TEXT", "MIDDLE_CENTER")
            ex, ey = h.spec["lifeline"]["comm"]["line"][-1]
            sh.pline([t(ex, ey), t(ex, ey - 1200)], "E-COMM", lineweight=50)
            sh.text("光引込 ↓（南面・床下ピット→SL-C1→ONU）", t(ex - 5000, ey - 1500), 1.6, "A-TEXT", "TOP_LEFT")
        else:
            bx, by = w["riser"]["box"]["xy"]
            sh.rect(*t(bx - 300, by - 150), *t(bx + 300, by + 150), "E-COMM", lineweight=50)
            sh.text("配線ボックス（SL-C2 上）", t(bx - 4200, by - 1000), 1.4, "A-TEXT", "LEFT")
        sh.text(f"{'1階' if f == '1F' else '2階'}", t(0, -1500), 2.6, "A-TEXT", "TOP_LEFT")
    sh.text("凡例: ■ LAN 口（A=居室A 等）　○ 太=RC スリーブ SL-C（番号）　○ 細=AP　鎖線=天井内の Cat6A 幹線　太い長方形=ラック MC-6／配線ボックス　水回りに AP・LAN 口・配線は通さない", (22, 133), 1.7, "A-TEXT", paper=True)
    # 左下: 配線経路表・VLAN
    sh.text("(4) AP への配線（Cat6A 2 本・全経路 90m 以内）", (12, 126), 2.4, "A-TEXT", paper=True)
    rows = [["AP", "経由（RC スリーブ）", "長さ"]]
    for r in routes:
        rows.append([r["id"], ("機械室→" if r["floor"] == "1F" else "SL-C2→2F 配線ボックス→") + ("→".join("SL-" + v for v in r["via"]) or "直接") + "→AP", f"{r['length_m']:.1f}m"])
    yy = sh.table(12, 123, [14, 78, 14], rows, row_h=3.8, h=1.6)
    sh.text("(5) VLAN・SSID", (112, 126), 2.4, "A-TEXT", paper=True)
    rows = [["VLAN", "用途", "SSID・備考"]] + [[str(a), b, c] for a, b, c in w["ssid_vlan"]]
    sh.table(112, 123, [12, 20, 100], rows, row_h=3.8, h=1.6)
    # 右: 表
    sh.text("(1) ラック MC-6（機械室・東系統 W600×D1,000×H2,000。前の空き 1,000）", (250, 271), 2.4, "A-TEXT", paper=True)
    rows = [["機器"]] + [[e] for e in w["rack"]["equipment"]]
    yy = sh.table(250, 268, [160], rows, row_h=3.8, h=1.7)
    pl = w["rack"]["poe_loads"]
    sh.text("PoE 負荷: " + "＋".join(f"{n}{k}×{p}W" for k, n, p in pl) + f" ＝ {WR.poe_load_w(h)}W（給電 {w['rack']['poe_budget_w']}W 以上）", (251, yy - 4), 1.7, "A-TEXT", paper=True)
    yy -= 11
    sh.text("(2) RC スリーブ（各 φ100×2・1 本は予備・FL+2,950・開口端から 300 以上）", (250, yy), 2.4, "A-TEXT", paper=True)
    rows = [["符号", "階・壁", "位置 x, y", "行き先"]]
    rows.append(["SL-C1", "1F 床", "{:,}, {:,}".format(*w["entry"]["sleeve_xy"]), "床下ピット→ONU（引込）"])
    rows.append(["SL-C2", "1F→2F スラブ", "{:,}, {:,}".format(*w["riser"]["xy"]), f"φ{w['riser']['dia']}×{w['riser']['n']}（{w['riser']['spare']} 本予備）→配線ボックス"])
    for s in w["sleeves"]:
        rows.append([s["id"], f"{s['floor']} {s['wall']}", "{:,}, {:,}".format(*s["xy"]), s["to"].split("（")[0]])
    yy = sh.table(250, yy - 3, [14, 26, 24, 96], rows, row_h=3.7, h=1.6)
    sh.text(f"(3) 有線 LAN 口（Cat6A・シャッター付き・計 {WR.lan_total(h)} 口・床コンセントなし）", (250, yy - 5), 2.4, "A-TEXT", paper=True)
    rows = [["符号", "室", "高さ・口数", "位置"]]
    for o in w["lan_outlets"]:
        rows.append([o["id"], o["room"], f"FL+{o['z']:,}・{o['n']}口", o["where"]])
    yy = sh.table(250, yy - 8, [14, 32, 22, 92], rows, row_h=3.7, h=1.6)
    side_panel(sh, 250, yy - 5, [("h", "配線の考え方"),
        ("t", "光は南側道路→門の塀の通信用プルボックス→地中 φ50×2（1 本は 2 社目の回線用）→南面→床下ピット→SL-C1→ONU（経路は A-02Z）。ラックは分電盤・蓄電室の隣で給電が確実、ジムの暗証番号錠の内側。"),
        ("t", "縦配線は機械室（東）天井の SL-C2 から 2F WIC 北東角の配線ボックスへ。天井内（懐 約 380）は J フックで支持し、LGS は天井内で越え、水回りの天井内は通さない。各経路に呼び線入りの予備 PF φ28。"),
        ("t", "RC スリーブは打設前に入れ、後から穴をあけない。径・補強（D13）・壁量への算入は構造設計者が確認する（要確認）。SL-C7 は既存 SL3 と重なるため x16,600、SL-C4 は y8,200 とした。"),
        ("t", "水回りに AP・LAN 口・配線は置かない。水回りの受信強度（−67dBm 程度）は簡易モデルの試算で、RC 壁の減衰の誤差（±5dB）で動くため、竣工時に実測して E-01 の★の AP の出力を調整する。携帯電話の電波は抑えない。"),
        ("t", "非常時の負荷は約 0.6kW。UPS 1.5kVA は切替時の瞬断用（15 分以上）、長い停電は蓄電池の特定負荷から給電。発熱は温度連動の換気扇で処理（要確認）。")], width=158)
    return sh
