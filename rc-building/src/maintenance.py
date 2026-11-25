"""v4.40 長期優良住宅の維持管理（点検経路・配管の位置・維持保全計画）。座標は spec の long_life・utilities（建物座標 mm）。

- 床下ピット 9 区画の連結・床点検口からの到達（access）
- 給水・汚水が Dotcon+・土間の下を通らないことの検査（cover_check）と汚水の縦断（sewer_profile）
- 内装 GLB の点検口の枠・目地（interior_parts）
- 維持保全計画 30 年と資金計画（plan・funding）
"""
from __future__ import annotations

from shapely.geometry import LineString, Point, box as sbox
from shapely.ops import unary_union


def cells(h):
    """床下ピットの区画（列 W/C/E × 行 S/M/N）: {名前: (x0, y0, x1, y1)}。"""
    return dict(h.pit_cells)


def cell_of(h, x, y):
    for n, (x0, y0, x1, y1) in cells(h).items():
        if x0 <= x <= x1 and y0 <= y <= y1:
            return n
    return None


def _rect_center(r):
    return (r[0] + r[2]) / 2, (r[1] + r[3]) / 2


def access(h):
    """点検経路。graph＝区画の隣接（人通口）、reach＝最寄りの床点検口から人通口を通る回数。"""
    ll = h.spec["long_life"]
    names = list(cells(h))
    graph = {n: set() for n in names}
    for mid, wall, u0, u1, a, b in ll["manways"]:
        graph[a].add(b)
        graph[b].add(a)
    sources = [cell_of(h, *_rect_center(r)) for _, _, r, _ in ll["floor_hatches"]]
    reach = {}
    frontier = [s for s in sources if s]
    for s in frontier:
        reach[s] = 0
    while frontier:
        nxt = []
        for n in frontier:
            for m in graph[n]:
                if m not in reach:
                    reach[m] = reach[n] + 1
                    nxt.append(m)
        frontier = nxt
    connected = len(reach) == len(names)
    co_ok = all(c[3] in reach and cell_of(h, c[1], c[2]) == c[3] for c in ll["cleanouts"])
    fdn_s = h.rc_walls["FDN"]["S"].openings
    no_outer = not any("点検" in (o.label or "") for o in fdn_s)
    hatch_ok = all(cell_of(h, *_rect_center(r)) is not None for _, _, r, _ in ll["floor_hatches"])
    ok = connected and co_ok and no_outer and hatch_ok
    return dict(graph=graph, connected=connected, reach=reach, max_reach=max(reach.values()) if reach else None,
                hatches=len(ll["floor_hatches"]), manways=len(ll["manways"]), ps=len(ll["ps"]), ch=len(ll["ceiling_hatches"]),
                co=len(ll["cleanouts"]), headers=len(ll["headers"]), sources=sources, no_outer_door=no_outer, ok=ok)


def cover_check(h):
    """給水（さや管の区間を除く）・汚水が Dotcon+・土間コンクリートの下を通る長さ（mm）。"""
    u = h.spec["utilities"]
    inner = h.fence_poly.buffer(-h.fence_t)
    concrete = unary_union([h.dotcon, h.approach.intersection(inner), h.dotcon_farm, h.dotcon_garden,
                            h.forecourt.difference(h.pipe_strip_fc.buffer(1))])
    ws = u["water"]["sleeve"]
    wl = list(u["water"]["line"])
    open_w = [LineString(wl[:ws["from"] + 1]), LineString(wl[ws["to"]:])]
    water_under = sum(g.intersection(concrete).length for g in open_w)
    sewer_under = h.pipes["sewer"][0].intersection(concrete).length
    sleeve_m = h.water_sleeve.intersection(h.approach).length
    return dict(water_under=water_under, sewer_under=sewer_under, sleeve_m=sleeve_m, sleeve_len=h.water_sleeve.length,
                exit_invert=u["sewer"]["exit_invert"], exit_ok=u["sewer"]["exit_invert"] >= 80)


PIPE_OD = 165          # φ150 塩ビ管の外径 mm


def sewer_profile(h):
    """[(名称, x, y, 管底 GL mm, 前区間の勾配, 前区間の長さ mm, 土かぶり mm)]（出口＋汚1〜汚6）。"""
    u = h.spec["utilities"]["sewer"]
    pts = [tuple(u["line"][0])] + [tuple(p) for p in u["manholes"]]
    names = ["出口"] + [f"汚{i + 1}" for i in range(len(u["manholes"]))]
    inv = u["exit_invert"]
    out = [(names[0], pts[0][0], pts[0][1], float(inv), 0.0, 0.0, h.fgl - (inv + PIPE_OD))]
    for i in range(1, len(pts)):
        d = LineString([pts[i - 1], pts[i]]).length
        sl = u["slopes"][i - 1]
        inv -= d * sl
        cover = h.ground(*pts[i]) - (inv + PIPE_OD) if i else None
        out.append((names[i], pts[i][0], pts[i][1], inv, sl, d, cover))
    return out


def final_invert_15(h):
    """汚2 以降を 1.5/100 とした場合の最終桝の管底（GL mm）。"""
    pr = sewer_profile(h)
    inv = pr[2][3]
    for a, b in zip(pr[2:], pr[3:]):
        inv -= b[5] * 0.015
    return inv


def sewer_length_m(h):
    return h.pipes["sewer"][0].length / 1000


def water_sections(h):
    """給水の区間: [(区間, 長さ m, 覆い, 土被り)]。"""
    u = h.spec["utilities"]["water"]
    wl = u["line"]
    names = ["MW", "W-1", "W-2", "P3", "P4", "P5", "WE"]
    ws = u["sleeve"]
    rows = []
    for i in range(len(wl) - 1):
        L = LineString([wl[i], wl[i + 1]]).length / 1000
        if i == ws["from"]:
            cov = "さや管 VU75（アプローチの横断）"
        elif i == 0:
            cov = "門前広場（外せるインターロッキング）"
        else:
            cov = "砂利（管路帯）"
        dep = "0.45m" if i < len(wl) - 2 else "0.30m＋保護板（建物の手前 1.0m）"
        rows.append((f"{names[i]}→{names[i + 1]}", L, cov, dep))
    return rows


# ------------------------------------------------------------ 内装 GLB（点検口の枠・目地）
def interior_parts(h, MBfor):
    """床点検口（外周 4 本の帯・見付 6）と天井点検口（目地 3 の帯）。MBfor(グループ, 階, 材質)。"""
    ll = h.spec["long_life"]
    G = "内装仕上げ"
    fl = h.fl["1F"]
    for hid, room, r, note in ll["floor_hatches"]:
        x0, y0, x1, y1 = r
        m = MBfor(G, "1F", "stainless_paint")
        w = 6
        m.box("stainless_paint", x0, y0, fl + 2, x1, y0 + w, fl + 3)
        m.box("stainless_paint", x0, y1 - w, fl + 2, x1, y1, fl + 3)
        m.box("stainless_paint", x0, y0 + w, fl + 2, x0 + w, y1 - w, fl + 3)
        m.box("stainless_paint", x1 - w, y0 + w, fl + 2, x1, y1 - w, fl + 3)
    zc = fl + h.ch["1F"]
    for hid, room, r, note in ll["ceiling_hatches"]:
        x0, y0, x1, y1 = r
        m = MBfor(G, "1F", "joint")
        w = 3
        m.box("joint", x0, y0, zc - 1, x1, y0 + w, zc)
        m.box("joint", x0, y1 - w, zc - 1, x1, y1, zc)
        m.box("joint", x0, y0 + w, zc - 1, x0 + w, y1 - w, zc)
        m.box("joint", x1 - w, y0 + w, zc - 1, x1, y1 - w, zc)


# ------------------------------------------------------------ 維持保全計画（30 年）・資金計画
def _years(period, years):
    return [y for y in range(1, years + 1) if period and y % period == 0]


def plan(h):
    """維持保全計画。rows=[(ID, 部位, 区分, 点検周期, 点検費, 更新周期, 更新費, 内容, 点検の年, 更新の年, 30 年計)]。費用は万円。"""
    mp = h.spec["long_life"]["maintenance"]
    Y = mp["years"]
    rows, by_class, per_year = [], {}, [0] * (Y + 1)
    for rid, name, cls, pi, pc, ui, uc, note in mp["items"]:
        ins, upd = _years(pi, Y), _years(ui, Y)
        c = len(ins) * pc + len(upd) * uc
        by_class[cls] = by_class.get(cls, 0) + c
        for y in ins:
            per_year[y] += pc
        for y in upd:
            per_year[y] += uc
        rows.append((rid, name, cls, pi, pc, ui, uc, note, ins, upd, c))
    reserve = mp["reserve_per_year"] * Y
    required = sum(by_class.get(k, 0) for k in ("構造", "雨水", "給排水"))
    optional = by_class.get("任意", 0)
    total = required + optional + reserve
    peak = sorted(((per_year[y], y) for y in range(1, Y + 1)), reverse=True)[:5]
    return dict(rows=rows, by_class=by_class, required=required, optional=optional, reserve=reserve, total=total,
                per_year=per_year, peak_years=[(y, v) for v, y in peak], years=Y,
                max_interval=max(r[3] for r in rows), monthly_all=total / (Y * 12), monthly_required=(required + reserve) / (Y * 12))


def funding(h, pl=None):
    """資金計画（万円）。[(項目, 下限, 上限, 備考)]。"""
    pl = pl or plan(h)
    f = h.spec["long_life"]["funding"]
    return [("建築工事費（推定）", f["construction_man"][0], f["construction_man"][1], "評価額 中央 1.39億・上限 1.65億 ÷ 0.55 から推定"),
            ("長期優良の増分（W/C・かぶり・人通口・配管・点検口など）", f["extra_man"][0], f["extra_man"][1], "評価書 2.1・3.1 の概算"),
            ("認定の審査・図書（技術的審査・認定申請・性能評価）", f["review_man"][0], f["review_man"][1], "評価書 8 章の概算"),
            ("維持保全 30 年（積立。臨時点検の予備を含む）", pl["total"], pl["total"], f"月 約{pl['monthly_all']:.1f}万円（対象分だけなら {pl['monthly_required']:.1f}万円）"),
            ("資金の手当て", None, None, f["note"])]
