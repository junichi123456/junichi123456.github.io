"""性能検討（概算）: 冷暖房負荷・耐震性（壁式RC）・年間電力需要と必要発電量。

いずれも基本計画段階の概算であり、実施設計で
省エネ計算（WEBPRO/住宅版）・構造計算（許容応力度計算）・太陽光発電量シミュレーションにより確定する。
"""
from __future__ import annotations

import math

# ------------------------------------------------------------------ 条件
CLIMATE = dict(
    name="八王子（地域区分6）",
    t_win=-4.0, t_sum=34.0,            # 設計外気温 ℃
    x_win=2.0, x_sum=19.5,             # 設計外気 絶対湿度 g/kg
    hdd=2300.0,                        # 暖房デグリーデー（基準19℃・K·日）
    cdd=320.0,                         # 冷房デグリーデー（基準24℃・K·日）
    hum_days=150, dehum_days=110,      # 加湿・除湿の期間（日）
    pv_yield=1050.0,                   # 年間発電量 kWh/kWp（傾斜10°、損失込み）
)
def abs_humidity(t, rh):
    """絶対湿度 g/kg(DA)（Tetens 式・大気圧 101.325kPa）"""
    ps = 0.61078 * 10 ** (7.5 * t / (t + 237.3))
    pv = ps * rh / 100
    return 622 * pv / (101.325 - pv)


def dew_point(t, rh):
    a, b = 17.27, 237.7
    g = a * t / (b + t) + math.log(rh / 100)
    return b * g / (a - g)


OLD_INDOOR = dict(t_win=22.0, t_sum=26.0, x_win=10.05, x_sum=9.58, label="旧目標（冬22℃/60%・夏26℃/45%）")


def indoor(h):
    """設計用の室内条件: 負荷が最大となる側の値（冬=上限温度・上限湿度、夏=下限温度・下限湿度）。"""
    d = h.spec["requirements"]["indoor"]
    return dict(t_win=d["winter_t"][1], t_sum=d["summer_t"][0],
                x_win=abs_humidity(d["winter_t"][1], d["rh"][1]), x_sum=abs_humidity(d["summer_t"][0], d["rh"][0]),
                label=f"新目標（冬{d['winter_t'][0]:.0f}〜{d['winter_t'][1]:.0f}℃・夏{d['summer_t'][0]:.0f}〜{d['summer_t'][1]:.0f}℃・湿度{d['rh'][0]}〜{d['rh'][1]}%）")
U = dict(wall=0.22, roof=0.15, floor=0.30, window=0.90, door=1.50)   # W/m²K
FLOOR_TEMP_FACTOR = 0.7       # 床下ピット（基礎断熱）に接する床の温度差係数
RECOVERY = 0.70               # 全熱交換 回収率（顕熱・潜熱）
ACH = 0.5                     # 機械換気 回/h
ACH_INF = 0.03                # すき間風（C値 0.3 程度）
SHGC = 0.30                   # 旧計画の日射熱取得率（全窓 遮熱型 Low-E トリプル・ブラインドなし）— 比較用
SOLAR = 450.0                 # 夏期ピーク 窓面日射量 W/m²（方位平均）


def envelope(h, side=None):
    """外皮（RC 外面基準）の面積と熱損失係数。side を与えると壁芯寸法を差し替えて比較できる。"""
    L = (side if side is not None else h.W) + h.t          # RC 外面の一辺 mm
    Hc = h.fl["RF"] - h.fl["1F"]                             # 外皮の高さ（1FL〜RFL）
    win = sum(op.width * op.height for op in h.openings(exterior=True)
              if op.kind == "window") / 1e6
    door = sum(op.width * op.height for op in h.openings(exterior=True)
               if op.kind == "door" and op.floor in ("1F", "2F")) / 1e6
    wall_gross = 4 * L * Hc / 1e6
    wall = wall_gross - win - door
    roof = floor = (L / 1000) ** 2
    parts = [("外壁", wall, U["wall"], 1.0), ("屋根", roof, U["roof"], 1.0), ("床（床下ピット上）", floor, U["floor"], FLOOR_TEMP_FACTOR),
             ("窓（FIX）", win, U["window"], 1.0), ("玄関ドア", door, U["door"], 1.0)]
    q = sum(a * u * f for _, a, u, f in parts)
    area = sum(a for _, a, _, _ in parts)
    return dict(parts=parts, area=area, q=q, UA=q / area, L=L, Hc=Hc, win=win)


def heat_load(h, side=None, ind=None, gamma=None, shgc=None, blinds=True):
    import sightshade as SS
    INDOOR = ind or indoor(h)
    env = envelope(h, side)
    ws = SS.window_solar(h, gamma, shgc, blinds)
    S = (env["L"] / 1000) ** 2
    floor_area = 2 * ((side if side is not None else h.W) / 1000) ** 2
    V = 2 * S * 2.9                                          # 空調対象容積 m³（天井懐を除く概算）
    vent = V * ACH
    m_air = vent * 1.2                                       # kg/h
    Hv = 0.34 * vent * (1 - RECOVERY) + 0.34 * V * ACH_INF   # W/K
    H = env["q"] + Hv
    c = CLIMATE
    dT_w = INDOOR["t_win"] - c["t_win"]
    dT_s = c["t_sum"] - INDOOR["t_sum"]
    heat = H * dT_w / 1000
    # 冷房（顕熱）: 貫流＋換気＋日射＋内部発熱（在室6人・照明・機器、ジム運動時を含む）
    internal = (6 * 75 + 2 * 250 + 2.0 * floor_area + 1500 + 800 + 1500) / 1000
    solar = ws["peak"]                                       # 夏期ピークの窓日射取得 kW（方位別に算定）
    cool_s = H * dT_s / 1000 + solar + internal
    # 潜熱（換気＋人体）
    lat_vent_s = m_air * (c["x_sum"] - INDOOR["x_sum"]) / 1000 * (1 - RECOVERY)   # kg/h
    lat_people = (6 * 55 + 2 * 300) / 680 / 1000 * 3600 / 1000 * 1000 / 1000      # kg/h 相当
    dehum = (lat_vent_s + lat_people) * 24                                         # L/日（ピーク日）
    cool_l = (lat_vent_s + lat_people) * 680 / 1000                                # kW（潜熱 680Wh/kg）
    hum = m_air * (INDOOR["x_win"] - c["x_win"]) / 1000 * (1 - RECOVERY) * 24      # L/日
    # 年間（デグリーデー法）
    # デグリーデーは設定温度に連動（基準温度 = 設定温度 − 内部発熱による昇温 約3K）
    hdd = c["hdd"] - 150 * (22.0 - INDOOR["t_win"])
    cdd = c["cdd"] + 110 * (26.0 - INDOOR["t_sum"])
    solar_heat_use = 0.9 * sum(ws["heat"].values())          # 暖房期の窓日射取得（利用率0.9）
    heat_kwh = max(0.0, H * hdd * 24 / 1000 - solar_heat_use)
    cool_kwh = H * cdd * 24 / 1000 + (solar + internal * 0.5) * 8 * 100 + cool_l * 10 * c["dehum_days"]
    hum_kwh = hum * c["hum_days"] * 0.68                      # 加湿の潜熱 kWh
    return dict(env=env, V=V, vent=vent, H=H, Hv=Hv, heat=heat, cool_s=cool_s, cool_l=cool_l, cool=cool_s + cool_l,
                solar=solar, internal=internal, dehum=dehum, hum=hum, floor_area=floor_area,
                heat_kwh=heat_kwh, cool_kwh=cool_kwh, hum_kwh=hum_kwh, hdd=hdd, cdd=cdd, indoor=INDOOR, ws=ws, solar_heat_use=solar_heat_use)


def energy(h, hl):
    """年間電力需要（kWh/年）と必要な太陽光容量。"""
    items = [
        ("暖房（ヒートポンプ SCOP 3.5）", hl["heat_kwh"] / 3.5),
        ("冷房・除湿（SEER 4.0）", hl["cool_kwh"] / 4.0),
        ("加湿（ヒートポンプ式 COP 3.0）", hl["hum_kwh"] / 3.0),
        ("全熱交換換気 2系統（120W×2・常時）", 0.24 * 8760),
        ("給湯（ヒートポンプ給湯機・4人）", 1300.0),
        ("照明（LED 2W/m²・1日4時間）", 2.0 * hl["floor_area"] * 4 * 365 / 1000),
        ("家電・調理（IH）", 3000.0),
        ("ジム機器（トレッドミル2台ほか）", 1.5 * 2 * 1.0 * 365 + 300),
        ("シアター", 0.8 * 3 * 365),
        ("排水ポンプ待機・防犯設備（常時100W）", 0.10 * 8760),
    ]
    total = sum(v for _, v in items)
    c = CLIMATE
    need_kwp = total / c["pv_yield"]
    need_kwp_margin = total * 1.2 / c["pv_yield"]          # 経年劣化・天候変動の余裕 20%
    pg = h.spec["exterior"]["solar_pergola"]
    x0, y0, x1, y1 = pg["rect"]
    pergola_area = (x1 - x0) * (y1 - y0) / 1e6
    panel_area = pergola_area * pg["coverage"]
    kwp_per_m2 = pg["module_kwp_per_m2"]
    pg_kwp = panel_area * kwp_per_m2
    cp = h.spec["exterior"]["carport"]
    cp_area = cp["w"] * cp["d"] / 1e6
    cp_kwp = cp_area * cp["kwp_per_m2"]
    import sightshade as SS
    sh = SS.pv_shading(h)
    # 方位補正: パネルは建物の軸に合わせて南面方位 facade_az を向く
    f_pg = SS.annual_poa(pg["tilt"], h.facade_az) / SS.annual_poa(pg["tilt"], 0.0)
    f_cp = SS.annual_poa(3, h.facade_az) / SS.annual_poa(3, 0.0)
    pg_gen = pg_kwp * c["pv_yield"] * f_pg * (1 - sh["pergola"]["loss"])
    cp_gen = cp_kwp * c["pv_yield"] * f_cp * (1 - sh["carport"]["loss"])
    # 参考: 架台全面をパネルで覆った場合との差（被覆率による減少分）
    full_kwp = pergola_area * kwp_per_m2
    coverage_deficit = (full_kwp - pg_kwp) * c["pv_yield"]
    shade_deficit = pg_kwp * c["pv_yield"] * sh["pergola"]["loss"]
    pv_kwp = pg_kwp + cp_kwp
    need_area = need_kwp_margin / kwp_per_m2 / pg["coverage"]
    # 非常時（停電）の蓄電池
    smoke_fan = 2 * (120 / 60 * 400 / 0.5) / 1000           # kW（120m³/分・400Pa・効率0.5）×2台
    backup = dict(smoke=smoke_fan * 0.5, pump=0.75 * 6, base=0.4 * 24)
    battery = sum(backup.values())
    return dict(items=items, total=total, need_kwp=need_kwp, need_kwp_margin=need_kwp_margin, pergola_area=pergola_area,
                panel_area=panel_area, coverage=pg["coverage"], pv_kwp=pv_kwp, pv_gen=pg_gen + cp_gen, need_area=need_area,
                pg_kwp=pg_kwp, pg_gen=pg_gen, cp_area=cp_area, cp_kwp=cp_kwp, cp_gen=cp_gen, shade=sh,
                coverage_deficit=coverage_deficit, shade_deficit=shade_deficit, f_pg=f_pg, f_cp=f_cp,
                kwp_per_m2=kwp_per_m2, smoke_fan=smoke_fan, backup=backup, battery=battery)


# ------------------------------------------------------------------ 耐震
FC = 24.0
GAMMA_RC = 24.0               # kN/m³


def _wall_length(h, floor, axis):
    """有効な耐力壁の長さ（開口で分断、長さ45cm以上かつ開口高さの30%以上）と位置。"""
    segs = []
    for w in h.walls:
        if w.floor != floor or w.cat != "wall" or w.axis != axis:
            continue
        cuts = sorted((op.u0, op.u1, op.height) for op in w.openings)
        u = w.a
        prev_h = 0
        for (a, b, hh) in cuts:
            if a > u:
                segs.append((u, a, max(prev_h, hh), w.c))
            u = max(u, b)
            prev_h = hh
        if w.b > u:
            segs.append((u, w.b, prev_h, w.c))
    out = []
    for a, b, hh, c in segs:
        if b - a >= max(450.0, 0.3 * hh):
            out.append(((b - a) / 1000.0, c / 1000.0, (a + b) / 2000.0))
    return out


def seismic(h):
    A = (h.W / 1000) ** 2
    vol = {"1F": 0.0, "2F": 0.0, "RF": 0.0, "PAR": 0.0, "STAIR": 0.0}
    for b in h.boxes:
        v = (b.x1 - b.x0) * (b.y1 - b.y0) * (b.z1 - b.z0) / 1e9
        if b.mat != "concrete":
            continue
        if b.cat == "wall" and b.level in ("1F", "2F"):
            vol[b.level] += v
        elif b.cat == "slab" and b.level in ("2F", "RF"):
            vol[b.level + "_slab"] = vol.get(b.level + "_slab", 0) + v
        elif b.cat == "parapet":
            vol["PAR"] += v
        elif b.cat == "stair" and b.level == "1F":
            vol["STAIR"] += v
    wall_ins = 0.5     # 外断熱・外装 kN/m²（外壁面）
    perim = 4 * (h.W + h.t) / 1000
    eq_kg = sum(kg for *_, kg in getattr(h, "equipment", []))
    # R階: 屋根スラブ＋パラペット＋2階壁の1/2＋屋上防水・断熱
    W2 = (vol["RF_slab"] + vol["PAR"] + vol["2F"] / 2) * GAMMA_RC + A * 1.5 + perim * 3.2 / 2 * wall_ins
    # 2階: 2階スラブ＋1・2階壁の1/2＋階段＋仕上・間仕切・積載（地震用 600N/m²）
    W1 = ((vol["2F_slab"] + vol["1F"] / 2 + vol["2F"] / 2 + vol["STAIR"]) * GAMMA_RC
          + A * (1.2 + 0.5 + 0.6) + perim * 3.2 * wall_ins)
    Wt = W1 + W2
    hgt = (h.fl["RF"] - h.fl["1F"]) / 1000
    T = hgt * 0.02
    Rt = 1.0
    Z = 1.0
    alpha2 = W2 / Wt
    A2 = 1 + (1 / math.sqrt(alpha2) - alpha2) * 2 * T / (1 + 3 * T)
    res = dict(W1=W1, W2=W2, Wt=Wt, w_unit=Wt / (2 * A), T=T, A2=A2, alpha2=alpha2, eq_kg=eq_kg, stories={})
    fs = 1.5 * min(FC / 30, 0.49 + FC / 100)          # 短期許容せん断応力度 N/mm²
    tau_u = 2.0                                         # 壁の終局せん断強度の目安 N/mm²（Fc24・壁式）
    Ds = 0.55
    for floor, Wsum, Ai in (("1F", Wt, 1.0), ("2F", W2, A2)):
        for axis, name in (("x", "X方向"), ("y", "Y方向")):
            segs = _wall_length(h, floor, axis)
            Lw = sum(s[0] for s in segs)
            Aw = Lw * 1000 * h.t                          # mm²
            out = {}
            for co, lab in ((0.2, "建築基準法（Co=0.2）"), (0.3, "耐震等級3（Co=0.3）")):
                Q = Z * Rt * Ai * co * Wsum              # kN
                tau = Q * 1000 / Aw
                out[lab] = dict(Q=Q, tau=tau, ratio=fs / tau)
            Qu = Aw * tau_u / 1000
            Qun = Ds * Z * Rt * Ai * 1.0 * Wsum
            # 偏心率（壁の長さを剛性とみなす簡易法）
            other = "y" if axis == "x" else "x"
            segs_o = _wall_length(h, floor, other)
            pos = [s[1] for s in segs]
            Kd = [s[0] for s in segs]
            r_c = sum(k * p for k, p in zip(Kd, pos)) / sum(Kd)
            Ko = [s[0] for s in segs_o]
            r_o = sum(k * s[1] for k, s in zip(Ko, segs_o)) / sum(Ko)
            g = h.W / 2000
            e = abs(r_c - g)
            Kr = sum(k * (p - r_c) ** 2 for k, p in zip(Kd, pos)) + sum(k * (s[1] - r_o) ** 2 for k, s in zip(Ko, segs_o))
            re = math.sqrt(Kr / sum(Kd))
            out.update(Lw=Lw, wall_rate=Lw * 100 / A, Aw=Aw / 1e6, Qu=Qu, Qun=Qun, qu_ratio=Qu / Qun,
                       ecc=e / re, e=e, re=re)
            res["stories"][(floor, name)] = out
    res["fs"] = fs
    res["tau_u"] = tau_u
    res["Ds"] = Ds
    # 接地圧（べた基礎）
    base = [b for b in h.boxes if b.tag == "基礎スラブ"][0]
    base_area = (base.x1 - base.x0) * (base.y1 - base.y0) / 1e6
    W_fdn = sum((b.x1 - b.x0) * (b.y1 - b.y0) * (b.z1 - b.z0) / 1e9 for b in h.boxes
                if b.mat == "concrete" and (b.level == "FDN" or b.tag in ("基礎スラブ", "S1") and b.level == "1F")) * GAMMA_RC
    W_long = Wt + W_fdn + 2 * A * (1.3 - 0.6) + eq_kg * 9.8 / 1000          # 長期（積載 床用 1.8kN/m²相当に補正）
    res["bearing"] = W_long / base_area
    res["W_long"] = W_long
    res["base_area"] = base_area
    # スラブ（日本建築学会 RC規準の床厚算定式）
    slabs = []
    for (a1, a2) in zip(h.gx, h.gx[1:]):
        for (b1, b2) in zip(h.gy, h.gy[1:]):
            lx = min(a2 - a1, b2 - b1) - h.t
            ly = max(a2 - a1, b2 - b1) - h.t
            lam = ly / lx
            gym = a1 >= h.gx[2] and b1 < h.gy[2]
            wp = (5.0 + 1.0) if gym else (1.8 + 1.0)
            t_req = 0.02 * (lam - 0.7) / (lam - 0.6) * (1 + wp / 10 + lx / 10000) * lx
            slabs.append(dict(cell=f"{a1 / 1000:.2f}–{a2 / 1000:.2f}×{b1 / 1000:.2f}–{b2 / 1000:.2f}", lx=lx, ly=ly, wp=wp,
                              t_req=t_req, gym=gym, area=(a2 - a1) * (b2 - b1) / 1e6))
    res["slabs"] = slabs
    return res
