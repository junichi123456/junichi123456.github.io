"""Blueprint 型の暮らしへの対応（v4.13）: 寝室の換気（CO2）、日なたの菜園、睡眠・水・測定。"""
from __future__ import annotations

from shapely.geometry import box

import performance as PF
import sightshade as SS


def bedroom_ventilation(h):
    """寝室（1部屋1人）の就寝中の CO2 濃度と必要換気量。"""
    ls = h.spec["lifestyle"]
    g, c0, ct = ls["co2_sleep_m3h"], ls["co2_outdoor"], ls["co2_target"]
    need = g / ((ct - c0) * 1e-6)                    # m³/h
    rows = []
    for r in h.rooms:
        if r.name not in ls["bedrooms"]:
            continue
        V = r.area * r.ch / 1000
        q0 = V * PF.ACH
        q = max(q0, need)
        rows.append(dict(name=r.name, floor=r.floor, area=r.area, V=V, q0=q0, c_base=c0 + g / q0 * 1e6,
                         q=q, ach=q / V, c_plan=c0 + g / q * 1e6))
    # 増えた換気量による冷暖房負荷（就寝中のみ、全熱交換で回収）
    dq = sum(x["q"] - x["q0"] for x in rows)
    c = PF.CLIMATE
    hours = ((ls["night"][1] - ls["night"][0]) % 24) / 24
    hl = PF.heat_load(h)
    extra_kwh = 0.34 * dq * (1 - PF.RECOVERY) * (hl["hdd"] + hl["cdd"]) * 24 * hours / 1000
    return dict(rows=rows, need=need, dq=dq, extra_kwh=extra_kwh)


def farm_sun(h):
    """プランター菜園の直達日射の影損失（本館・隣家・塀・カーポート・パーゴラの影を含む）。"""
    obs = SS.solar_obstacles(h)
    items = list(obs.items)
    cp = h.spec["exterior"]["carport"]
    items.append((box(*h.carport), h.fgl + cp["h"], h.fgl + cp["h"] + 250, "カーポート屋根"))
    items.append((box(*h.pergola), h.fgl + h.pergola_h, h.fgl + h.pergola_h + 400, "パーゴラ"))
    for r in h.screen:
        items.append((box(*r), h.fgl - 400, h.screen_top, "目隠し壁"))
    fm = h.spec["farm"]
    z = h.fgl + fm["leg"] + fm["planter_h"]
    farm = SS.shading_loss(h, h.farm, z, 0, SS.Prisms(items))
    # パーゴラの下: パーゴラ以外の影＋パネル被覆率
    no_pg = SS.Prisms([it for it in items if it[3] != "パーゴラ"])
    pg = SS.shading_loss(h, h.pergola, max(h.fgl, h.ground((h.pergola[0] + h.pergola[2]) / 2, (h.pergola[1] + h.pergola[3]) / 2)) + 300, 0, no_pg)
    cover = h.spec["exterior"]["solar_pergola"]["coverage"]
    return dict(farm=farm, under_pergola=1 - (1 - pg["direct_loss"]) * (1 - cover),
                area=sum((p[2] - p[0]) * (p[3] - p[1]) for p in h.planters) / 1e6)


CROPS = [("日なたのプランター", "ブロッコリー・カリフラワー・ケール・キャベツ（アブラナ科）、トマト、ピーマン、ズッキーニ、ブルーベリー"),
         ("パーゴラの下（半日陰）", "ほうれん草・小松菜・レタス・春菊、しそ・バジル・パセリ・ミント、しょうが・みょうが、にんにく・ねぎ"),
         ("購入に頼るもの", "豆類（レンズ豆など）・ナッツ・きのこ類の多く・オリーブオイル")]
