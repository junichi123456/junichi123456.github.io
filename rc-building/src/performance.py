"""性能検討（概算）: 冷暖房負荷・耐震性（壁式RC）・年間電力需要と必要発電量。

いずれも基本計画段階の概算であり、実施設計で
省エネ計算（住宅版のエネルギー消費性能計算プログラム。WEBPRO は非住宅用）・構造計算（許容応力度計算）・太陽光発電量シミュレーションにより確定する。
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
SHGC = 0.30                   # 旧計画の日射熱取得率（全窓 遮熱型 Low-E トリプル・スクリーンなし）— 比較用
SOLAR = 450.0                 # 夏期ピーク 窓面日射量 W/m²（方位平均）


def envelope(h, side=None):
    """外皮（RC 外面基準）の面積と熱損失係数。side を与えると壁芯寸法を差し替えて比較できる。"""
    L = (side if side is not None else h.W) + h.t          # RC 外面の一辺 mm
    Hc = h.fl["RF"] - h.fl["1F"]                             # 外皮の高さ（1FL〜RFL）
    win = sum(op.width * op.height for op in h.openings(exterior=True)
              if op.kind == "window") / 1e6
    qd = h.spec["glazing"].get("quad") or {}
    win_q = sum(op.width * op.height for op in h.openings(exterior=True)
                if op.kind == "window" and op.label in qd.get("labels", [])) / 1e6
    door = sum(op.width * op.height for op in h.openings(exterior=True)
               if op.kind == "door" and op.floor in ("1F", "2F")) / 1e6
    wall_gross = 4 * L * Hc / 1e6
    wall = wall_gross - win - door
    roof = floor = (L / 1000) ** 2
    parts = [("外壁", wall, U["wall"], 1.0), ("屋根", roof, U["roof"], 1.0), ("床（床下ピット上）", floor, U["floor"], FLOOR_TEMP_FACTOR),
             ("窓（FIX）", win - win_q, U["window"], 1.0)] + ([("窓（FIX・クアッド）", win_q, qd["uw"], 1.0)] if win_q else []) + [("玄関ドア", door, U["door"], 1.0)]
    q = sum(a * u * f for _, a, u, f in parts)
    area = sum(a for _, a, _, _ in parts)
    return dict(parts=parts, area=area, q=q, UA=q / area, L=L, Hc=Hc, win=win)


# ------------------------------------------------------------------ v4.40 長期優良住宅: 熱橋込み外皮・ηAC・BEI 概算
def _ll_energy(h):
    return h.spec["long_life"]["energy"]


def _ext_windows(h):
    return [op for op in h.openings(exterior=True) if op.kind == "window"]


def envelope_tb(h):
    """熱橋（ψ・χ、仮定値）を足した外皮。envelope() の面積・U は変えない。{env, items=[(名称, ψ, 長さ m, ψL)], chi, q_tb, UA_tb}"""
    ee = _ll_energy(h)
    env = envelope(h)
    wins = _ext_windows(h)
    length = {"perimeter": env["L"] / 1000 * 4,
              "window_perimeter": sum(2 * (op.width + op.height) for op in wins) / 1000,
              "window_top": sum(op.width for op in wins) / 1000}
    items = [(n, psi, length[k], psi * length[k]) for n, psi, k in ee["tb"]]
    chi = ee["chi"]["value"] * ee["chi"]["n"]
    q_tb = env["q"] + sum(i[3] for i in items) + chi
    return dict(env=env, items=items, chi=chi, q_tb=q_tb, UA_tb=q_tb / env["area"])


def eta_ac(h):
    """冷房期の平均日射熱取得率 ηAC（窓 g×f×ν、不透明部 0.034U×ν）。ZIP スクリーンは算入しない（安全側）。"""
    ee = _ll_energy(h)
    nu, f = ee["nu"], ee["f_win"]
    env = envelope(h)
    wins = _ext_windows(h)
    gl = h.spec["glazing"]
    qd = gl.get("quad") or {}
    win = 0.0
    for op in wins:
        t = gl["side_type"][op.side]
        g = qd["types"][t]["g"] if op.label in qd.get("labels", []) else gl["types"][t]["g"]
        win += op.width * op.height / 1e6 * g * f * nu[op.side]
    side_gross = env["L"] / 1000 * env["Hc"] / 1000
    door_a = sum(op.width * op.height for op in h.openings(exterior=True) if op.kind == "door" and op.floor in ("1F", "2F")) / 1e6
    wall_s = {k: side_gross - sum(op.width * op.height / 1e6 for op in wins if op.side == k) - (door_a if k == "S" else 0) for k in "NESW"}
    roof = env["L"] ** 2 / 1e6
    opaque = (sum(0.034 * U["wall"] * a * nu[k] for k, a in wall_s.items()) + 0.034 * U["roof"] * roof * nu["top"]
              + 0.034 * U["door"] * door_a * nu["S"])
    return dict(value=(win + opaque) / env["area"] * 100, win=win, opaque=opaque, area=env["area"])


def bei_estimate(h, hl=None, en=None):
    """一次エネルギー消費量の概算（BEI）。住宅版プログラムの代わりではない。基準の仕様は long_life.energy.ref の仮定。"""
    ee = _ll_energy(h)
    hl = hl or heat_load(h)
    en = en or energy(h, hl)
    tb = envelope_tb(h)
    env = hl["env"]
    E, ref = ee["primary_mj_per_kwh"], ee["ref"]
    H_tb = tb["q_tb"] + hl["Hv"]
    hdd, cdd = hl["hdd"], hl["cdd"]
    heat_kwh = max(0.0, H_tb * hdd * 24 / 1000 - hl["solar_heat_use"])
    cool_kwh = hl["cool_kwh"] + (H_tb - hl["H"]) * cdd * 24 / 1000
    vent, V = hl["vent"], hl["V"]
    H_ref = ref["ua"] * env["area"] + 0.34 * vent + 0.34 * V * ACH_INF
    heat_r = max(0.0, H_ref * hdd * 24 / 1000 - hl["solar_heat_use"])
    cool_r = hl["cool_kwh"] + (H_ref - hl["H"]) * cdd * 24 / 1000
    light_kwh = next(v for n, v in en["items"] if n.startswith("照明"))
    design = dict(heat=heat_kwh / 3.5 * E, cool=cool_kwh / 4.0 * E, vent=0.24 * 8760 * E, hw=1300 * E, light=light_kwh * E)
    refd = dict(heat=heat_r / ref["heat_eff"] * E, cool=cool_r / ref["cool_eff"] * E,
                vent=ref["vent_w_per_m3h"] * vent / 1000 * 8760 * E,
                hw=1300 * ref["hw_cop_design"] / ref["hw_gas_eff"] * 3.6, light=design["light"] * ref["light_factor"])
    Ed, Er = sum(design.values()), sum(refd.values())
    return dict(design=design, ref=refd, E_design=Ed, E_ref=Er, bei=Ed / Er, heat_kwh_tb=heat_kwh, cool_kwh_tb=cool_kwh,
                H_tb=H_tb, H_ref=H_ref, heat_kwh_ref=heat_r, cool_kwh_ref=cool_r, d_heat_kwh=heat_kwh - hl["heat_kwh"])


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
    # v4.23 予約ゾーン RZ（拡張後）。影の損失は spec の推定値（sightshade での再計算は未実施）
    pr = h.spec["pv_reserve"]
    rz_kwp = h.pv_reserve.area / 1e6 * pr["coverage"] * pr["module_kwp_per_m2"]
    rz_a_kwp = h.pv_reserve_a.area / 1e6 * pr["coverage"] * pr["module_kwp_per_m2"]
    rz_gen = rz_kwp * c["pv_yield"] * (1 - pr["shade_loss"])
    rz_a_gen = rz_a_kwp * c["pv_yield"] * (1 - pr["shade_loss"])
    return dict(items=items, total=total, need_kwp=need_kwp, rz_kwp=rz_kwp, rz_gen=rz_gen, rz_a_kwp=rz_a_kwp, rz_a_gen=rz_a_gen,
                pv_kwp_ext=pv_kwp + rz_kwp, pv_gen_ext=pg_gen + cp_gen + rz_gen, need_kwp_margin=need_kwp_margin, pergola_area=pergola_area,
                panel_area=panel_area, coverage=pg["coverage"], pv_kwp=pv_kwp, pv_gen=pg_gen + cp_gen, need_area=need_area,
                pg_kwp=pg_kwp, pg_gen=pg_gen, cp_area=cp_area, cp_kwp=cp_kwp, cp_gen=cp_gen, shade=sh,
                coverage_deficit=coverage_deficit, shade_deficit=shade_deficit, f_pg=f_pg, f_cp=f_cp,
                kwp_per_m2=kwp_per_m2, smoke_fan=smoke_fan, backup=backup, battery=battery)


def daily_profiles(h, en):
    """停電時の日負荷ケース A〜D（kWh/日）。A 年平均（現行＋ネットワーク）／B 冬ピーク／C 防災モード／D 最低。
    内訳の推定値は spec.yaml の battery（server_kw・winter_heat_kwh_day 等。推定・要確認）。"""
    b = h.spec["battery"]
    a = b["profile_assumptions"]
    server = a["server_kw"] * 24
    ann = en["total"] / 365
    nonheat = sum(v for n, v in en["items"] if not n.startswith(("暖房", "冷房", "加湿"))) / 365     # 暖冷房・加湿以外の日負荷
    return {
        "A": dict(name="年平均（現行＋ネットワーク）", kwh=ann + server),
        "B": dict(name="冬ピーク（1月）", kwh=nonheat + a["winter_heat_kwh_day"] + a["winter_hum_kwh_day"] + server),
        "C": dict(name="防災モード", kwh=sum(v for _, v in b["disaster_items"]), fixed=b["emergency_fixed_kwh"]),
        "D": dict(name="最低（空調なし）", kwh=sum(v for _, v in b["minimum_items"]), fixed=b["emergency_fixed_kwh"]),
    }


def battery_sizing(h, en):
    """7日分の使用可能量と公称容量 = 必要値 ÷ (DoD × 寿命末期 SOH × 効率)。面積・重量は推定の原単位。
    推奨は防災モード C の 200kWh 級。自立日数は日射ゼロの場合の日数（新品は DoD のみ、寿命末期は DoD×SOH×効率）。"""
    b = h.spec["battery"]
    f = b["dod"] * b["soh_eol"] * b["eff"]
    days = b["days_target"]
    rows = {}
    for k, p in daily_profiles(h, en).items():
        use = p["kwh"] * days + p.get("fixed", 0.0)
        nom = use / f
        rows[k] = dict(p, use=use, nominal=nom, area=nom / b["kwh_per_m2"], tons=nom / b["kwh_per_t"])
    nom = b["nominal_kwh"]
    c = rows["C"]["kwh"]
    eol = nom * f / c
    new = nom * b["dod"] / c
    eol_net = (nom * f - b["emergency_fixed_kwh"]) / c
    dec = b["december_share"]
    pv = {}
    for key, kwp, gen in (("now", en["pv_kwp"], en["pv_gen"]), ("ext", en["pv_kwp_ext"], en["pv_gen_ext"])):
        avg = gen * dec / 31
        pv[key] = dict(kwp=kwp, gen=gen, avg=avg, cloudy=avg * b["cloudy_ratio"])
    def autonomy(load, kind):
        d = pv[kind]
        usable = nom * f
        out = {}
        for nm, g in (("avg", d["avg"]), ("cloudy", d["cloudy"])):
            net = load - g
            out[nm] = None if net <= 0 else usable / net          # None＝収支プラス（無期限）
        return out
    aut = {(case, kind): autonomy(rows[case]["kwh"], kind) for case in ("C", "B") for kind in ("now", "ext")}
    return dict(factor=f, rows=rows, nominal=nom, usable_eol=nom * f, days_eol=eol, days_new=new, days_eol_net=eol_net,
                room_area=(b["rect"][2] - b["rect"][0]) * (b["rect"][3] - b["rect"][1]) / 1e6, pv=pv, autonomy=aut,
                weight_t=nom / b["kwh_per_t"])


def self_consumption(h, en, bs=None, eol=False, **over):
    """v4.39 全量自家消費（逆潮流なし）の年間収支の概算。各月21日の晴天・曇天の2日型・30分ごと。
    月合計は energy() の発電量に合わせる。蓄電池は停電7日の予約より上だけを日常に使う。
    over: band・hw_day・heat_shift・ev・margin・kwp_pg・kwp_cp。"""
    import sightshade as SS
    ps = h.spec["pv_self"]
    b = h.spec["battery"]
    if bs is None:
        bs = battery_sizing(h, en)
    STEP = 0.5
    N = int(24 / STEP)
    TT = [i * STEP for i in range(N)]
    D = SS.DAYS
    it = dict(en["items"])
    tm = ps["t_month"]
    hdd = [max(0, 19 - t) * d for t, d in zip(tm, D)]
    cdd = [max(0, t - 20) * d for t, d in zip(tm, D)]
    kwp_pg = over.get("kwp_pg", en["pg_kwp"]); kwp_cp = over.get("kwp_cp", en["cp_kwp"])
    hw_day = over.get("hw_day", ps["hot_water_day"]); shift_heat = over.get("heat_shift", ps["heat_shift"])
    ev = over.get("ev", 0.0); margin = over.get("margin", ps["grid_margin_kw"]); bat_kw = ps["pcs_kw"]["battery"]
    eff = b["eff"]
    reserve = (bs["rows"]["C"]["kwh"] * b["days_target"] + b["emergency_fixed_kwh"]) / eff
    band = over.get("band", max(0.0, b["nominal_kwh"] * b["dod"] * (b["soh_eol"] if eol else 1.0) - reserve))
    tilt_pg = h.spec["exterior"]["solar_pergola"]["tilt"]
    raw, tot = {}, {"pg": 0.0, "cp": 0.0}
    for m in range(1, 13):
        for key, tilt in (("pg", tilt_pg), ("cp", 3)):
            c, cl = SS.day_irradiance(m, tilt, h.facade_az, STEP); raw[(m, key)] = (c, cl)
            tot[key] += (SS.SUNSHINE * sum(c) + (1 - SS.SUNSHINE) * sum(cl)) * STEP * D[m - 1]
    k = {"pg": en["pg_gen"] / en["pg_kwp"] / tot["pg"], "cp": en["cp_gen"] / en["cp_kwp"] / tot["cp"]}

    def shape(fn):
        w = [fn(t + STEP / 2) for t in TT]; s = sum(w) * STEP
        return [x / s for x in w]
    flat = shape(lambda t: 1)
    night = shape(lambda t: 1 if 1 <= t < 5 else 0)
    lo, hi = ps["day_window"]
    midday = shape(lambda t: 1 if lo <= t < hi else 0)
    light = shape(lambda t: 1 if (17 <= t < 23 or 6 <= t < 8) else 0)
    appl = shape(lambda t: 0.2 / 2 if 7 <= t < 9 else 0.2 / 2 if 11 <= t < 13 else 0.45 / 4 if 17 <= t < 21 else 0.15 / 16)
    gym = shape(lambda t: 1 if (7 <= t < 8 or 18 <= t < 19) else 0)
    theater = shape(lambda t: 1 if 19 <= t < 23 else 0)
    cool = shape(lambda t: 0.4 + 0.6 * max(0, math.sin(math.pi * (t - 8) / 12)) if 8 <= t < 20 else 0.4)
    heat = shape(lambda t: 1.0 + 0.25 * math.cos(2 * math.pi * (t - 5) / 24))

    def load_day(m):
        i = m - 1
        eH = it["暖房（ヒートポンプ SCOP 3.5）"] * hdd[i] / sum(hdd) / D[i]
        eHum = it["加湿（ヒートポンプ式 COP 3.0）"] * hdd[i] / sum(hdd) / D[i]
        eC = it["冷房・除湿（SEER 4.0）"] * cdd[i] / sum(cdd) / D[i]
        comp = [
            (eH * (1 - shift_heat), heat), (eH * shift_heat, midday), (eHum, heat), (eC, cool),
            (it["全熱交換換気 2系統（120W×2・常時）"] / 365, flat), (it["排水ポンプ待機・防犯設備（常時100W）"] / 365, flat),
            (it["給湯（ヒートポンプ給湯機・4人）"] / 365, midday if hw_day else night),
            (it["照明（LED 2W/m²・1日4時間）"] / 365, light), (it["家電・調理（IH）"] / 365, appl),
            (it["ジム機器（トレッドミル2台ほか）"] / 365, gym), (it["シアター"] / 365, theater), (ev, midday)]
        return [sum(e * s[j] for e, s in comp) for j in range(N)]

    res = dict(gen=0.0, load=0.0, direct=0.0, batt=0.0, curtail=0.0, grid=0.0, peak_surplus=0.0)
    months = []
    for m in range(1, 13):
        L = load_day(m)
        mm = dict(m=m, gen=0.0, load=0.0, self=0.0, curtail=0.0, grid=0.0)
        for typ, idx, w in (("clear", 0, SS.SUNSHINE), ("cloudy", 1, 1 - SS.SUNSHINE)):
            P = [raw[(m, "pg")][idx][j] * k["pg"] * kwp_pg + raw[(m, "cp")][idx][j] * k["cp"] * kwp_cp for j in range(N)]
            soc = 0.0
            for _ in range(3):                       # 日をまたぐ SOC は日ごとの定常（3 回まわして収束）で近似
                g = dict(direct=0.0, batt=0.0, curtail=0.0, grid=0.0, ps=0.0)
                for j in range(N):
                    net = (P[j] - L[j]) * STEP
                    if net >= 0:
                        mg = min(margin, L[j]) * STEP
                        g["grid"] += mg; net += mg
                        g["direct"] += L[j] * STEP - mg
                        ch = min(net, band - soc, bat_kw * STEP); soc += ch
                        g["curtail"] += net - ch; g["ps"] = max(g["ps"], P[j] - L[j])
                    else:
                        g["direct"] += P[j] * STEP
                        need = -net; dis = min(need, soc * eff, bat_kw * STEP)
                        soc -= dis / eff; g["batt"] += dis; g["grid"] += need - dis
            n = D[m - 1] * w
            for kk in ("direct", "batt", "curtail", "grid"):
                res[kk] += g[kk] * n
            res["peak_surplus"] = max(res["peak_surplus"], g["ps"])
            res["gen"] += sum(P) * STEP * n; res["load"] += sum(L) * STEP * n
            mm["gen"] += sum(P) * STEP * n; mm["load"] += sum(L) * STEP * n
            mm["self"] += (g["direct"] + g["batt"]) * n; mm["curtail"] += g["curtail"] * n; mm["grid"] += g["grid"] * n
        months.append(mm)
    res["self"] = res["direct"] + res["batt"]
    res["sc_rate"] = res["self"] / res["gen"]; res["ss_rate"] = res["self"] / res["load"]
    res.update(band=band, reserve=reserve, months=months)
    return res


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


def _wall_stiff(h, floor, axis):
    """剛性の層 [(長さ m × 厚さ mm = K, 位置 m（直交方向の座標）)]（v4.18: 剛性 = 長さ × 厚さ。局所の増し打ちは、増し分を別の層として加える）。"""
    out = []
    for w in h.walls:
        if w.floor != floor or w.cat != "wall" or w.axis != axis:
            continue
        cuts = sorted((op.u0, op.u1, op.height) for op in w.openings)
        segs, u, prev_h = [], w.a, 0
        for (a, b, hh) in cuts:
            if a > u:
                segs.append((u, a, max(prev_h, hh)))
            u = max(u, b)
            prev_h = hh
        if w.b > u:
            segs.append((u, w.b, prev_h))
        for a, b, hh in segs:
            if b - a < max(450.0, 0.3 * hh):
                continue
            out.append(((b - a) / 1000.0 * w.t, w.c / 1000.0))
            for (e0, e1, te, sg) in w.extra:
                lo, hi = max(a, e0), min(b, e1)
                if hi > lo:
                    out.append(((hi - lo) / 1000.0 * te, (w.c + sg * (w.t / 2 + te / 2)) / 1000.0))
    return out


def gravity_center(h, floor):
    """v4.47 令82条の6 の重心: 層 floor の中間高さより上にある長期荷重の図心 (gx, gy) m。
    RC（mat == "concrete" の箱。中間高さより上の部分の体積 × 24kN/m³）、均等荷重（RF: 防水・断熱 1.5kN/m²、
    1F 層では 2F 床の仕上 1.2＋間仕切 0.5＋地震用積載 0.6kN/m² を平面中心に）、
    2F の設備（spec.mech_rooms.equipment の kg。z0 ≧ 2,200 の天吊りは RF、他は 2F 床）。
    1F の床に載る設備（ジム機器・蓄電池）は基礎へ直接流れるので含めない。"""
    zl = h.fl[floor]
    zu = h.fl["2F" if floor == "1F" else "RF"]
    zm = (zl + zu) / 2
    M = Mx = My = 0.0
    for b in h.boxes:
        if b.mat != "concrete" or b.z1 <= zm:
            continue
        w = (b.x1 - b.x0) * (b.y1 - b.y0) * (b.z1 - max(b.z0, zm)) / 1e9 * GAMMA_RC
        M += w
        Mx += w * (b.x0 + b.x1) / 2000
        My += w * (b.y0 + b.y1) / 2000
    A = (h.W / 1000) ** 2
    u = A * 1.5 + (A * (1.2 + 0.5 + 0.6) if floor == "1F" else 0.0)
    M += u
    Mx += u * h.W / 2000
    My += u * h.W / 2000
    for e in h.spec["mech_rooms"]["equipment"]:
        if e[1] != "機械室" or len(e) < 7:
            continue
        lv = "RF" if e[5] >= 2200 else "2F"
        if floor == "1F" or lv == "RF":
            kn = e[6] * 9.8 / 1000
            r = e[3]
            M += kn
            Mx += kn * (r[0] + r[2]) / 2000
            My += kn * (r[1] + r[3]) / 2000
    return Mx / M, My / M


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
            st_x = _wall_stiff(h, floor, axis)
            Aw = sum(k for k, _ in st_x) * 1000          # mm²（Σ 長さ × 厚さ）
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
            pos = [p for _, p in st_x]
            Kd = [k for k, _ in st_x]
            st_o = _wall_stiff(h, floor, other)
            r_c = sum(k * p for k, p in zip(Kd, pos)) / sum(Kd)
            Ko = [k for k, _ in st_o]
            r_o = sum(k * p for k, p in st_o) / sum(Ko)
            gx_, gy_ = gravity_center(h, floor)                        # v4.47 重心＝荷重の図心（従前は平面中心 W/2）
            g = gy_ if axis == "x" else gx_                           # X 方向の壁の位置 p は y 座標
            g_c = h.W / 2000
            e = abs(r_c - g)
            Kr = sum(k * (p - r_c) ** 2 for k, p in zip(Kd, pos)) + sum(k * (p - r_o) ** 2 for k, p in st_o)
            re = math.sqrt(Kr / sum(Kd))
            out.update(Lw=Lw, wall_rate=Lw * 100 / A, Aw=Aw / 1e6, Qu=Qu, Qun=Qun, qu_ratio=Qu / Qun,
                       ecc=e / re, e=e, re=re, g=g, rc=r_c, ecc_center=abs(r_c - g_c) / re)
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
            arch = False                    # v4.44: 書庫（積載 5kN/m²）は撤去
            wp = (5.0 + 1.0) if gym else (1.8 + 1.0)
            t_req = 0.02 * (lam - 0.7) / (lam - 0.6) * (1 + wp / 10 + lx / 10000) * lx
            slabs.append(dict(cell=f"{a1 / 1000:.2f}–{a2 / 1000:.2f}×{b1 / 1000:.2f}–{b2 / 1000:.2f}", lx=lx, ly=ly, wp=wp,
                              t_req=t_req, gym=gym, archive=arch, area=(a2 - a1) * (b2 - b1) / 1e6))
    res["slabs"] = slabs
    return res


def condensation(h):
    """LDK の窓まわりの結露判定（v4.18。v4.36 でコーナー窓を撤回）。室内側表面温度 = t_out + f_Rsi × (t_in − t_out) が、露点 + margin 以上であること。
    f_Rsi は spec.condensation.parts の仮定値（メーカーの 2 次元熱解析に置き換える）。
    v4.38 LDK 窓はクアッド・吹出しなし。rows の 2 列目は ZIP を上げた夜、3 列目は冬の夜 ZIP。
    [(部位, ZIP を上げた夜 ℃, 冬の夜 ZIP ℃, 下限 ℃, 適合)] と露点を返す。"""
    c = h.spec["condensation"]
    td = dew_point(c["t_in"], c["rh"])
    lim = td + c["margin_k"]
    rows = []
    for name, (f0, f1) in c["parts"].items():
        t0 = c["t_out"] + f0 * (c["t_in"] - c["t_out"])
        t1 = c["t_out"] + f1 * (c["t_in"] - c["t_out"])
        rows.append((name, t0, t1, lim, t1 >= lim - 0.05))      # 0.05K の丸め許容（下限ケースは 14.9℃）
    return dict(dew=td, limit=lim, rows=rows, ok=all(r[4] for r in rows))


def cold_draft(h, x=1.0):
    """v4.38 LDK 窓（クアッド）のコールドドラフト（Heiselberg の式）。dT = Ug×0.13×(t_in−t_out)（ガラス中央の表面温度との差）、
    v_near = 0.055√(dT·H)（窓際）、v_x = 0.095√(dT·H)/(x+1.32)（窓から x m、0.4≦x≦2.0）。H は窓高 m。"""
    c = h.spec["condensation"]
    q = h.spec["glazing"]["quad"]
    ops = [op for op in h.openings(exterior=True) if op.kind == "window" and op.label in q["labels"]]
    H = max(op.height for op in ops) / 1000
    dT = q["ug"] * 0.13 * (c["t_in"] - c["t_out"])
    return dict(dT=dT, H=H, v_near=0.055 * math.sqrt(dT * H), v_x=0.095 * math.sqrt(dT * H) / (x + 1.32))
