#!/usr/bin/env python3
"""取得費の見積もりと資産取り崩しモンテカルロ（仕様 spec_portfolio.md）。

金額は 2026 年の円の実質値（税込、万円）。外部依存は numpy だけ。
  python3 finance/portfolio_mc.py --grid all --csv finance/results.csv --md finance/results_tables.md
  python3 finance/portfolio_mc.py --grid T0
"""
import argparse
import csv
import sys
import time

import numpy as np

TAU = 0.20315
T_YEARS = 50
SEED = 20261125

# ---------------------------------------------------------------- 取得費
COST_ITEMS = {  # 万円。順に 低・中・高
    "建築工事費": (25000, 27500, 30000),
    "太陽光": (1000, 1400, 2000),
    "蓄電池": (2000, 3000, 4000),
    "外構": (2500, 4000, 6000),
    "設計・監理": (2000, 2750, 3600),
    "長期優良の増分・審査": (320, 600, 900),
    "調査・申請・登記費用": (300, 500, 800),
    "不動産取得税(家屋)": (345, 417, 495),
    "登録免許税(保存登記)": (11, 14, 17),
    "家具・AV・ジム・家電": (800, 1500, 3000),
    "解体・土壌調査": (0, 500, 1500),
}
CASES = {"低": 0, "中": 1, "高": 2}
CONTINGENCY = {"低": 0.0, "中": 0.05, "高": 0.10}
LAND_AREA = 2426.42
LAND_PRICE = {"低": 13, "中": 16, "高": 19}  # 万円/㎡
LAND_EVAL = {"低": 20600, "中": 25500, "高": 31500}  # 固定資産評価額 万円
CASH_ON_HAND = 3000
TOTAL_ASSET = 100000  # 10億
PROP_TAX = {"低": (320, 286), "中": (390, 369), "高": (470, 470)}  # 初年度, 10年目


def acquisition_cost(case, land=False):
    """取得費の内訳(万円)と合計。land=True なら土地未取得の加算を含む。"""
    i = CASES[case]
    items = {k: v[i] for k, v in COST_ITEMS.items()}
    work = items["建築工事費"] + items["太陽光"] + items["蓄電池"] + items["外構"]
    items["予備費"] = round(work * CONTINGENCY[case])
    if land:
        price = LAND_AREA * LAND_PRICE[case]
        items["土地代"] = round(price)
        items["仲介手数料"] = round(price * 0.03 + 6)
        items["不動産取得税(土地)"] = round(LAND_EVAL[case] * 0.5 * 0.03)
        items["登録免許税(土地)"] = round(LAND_EVAL[case] * 0.015)
    return items, sum(items.values())


def property_tax_path(case, t=T_YEARS):
    """固定資産税・都市計画税の実質値(万円/年)。1〜10年目は線形補間、以降は10年目で一定。"""
    a, b = PROP_TAX[case]
    return np.array([a + (b - a) * min(k, 9) / 9 for k in range(t)], dtype=float)


# ---------------------------------------------------------------- 乱数
def corr_matrix(rho_si=0.0, rho_sb=0.1, rho_bi=-0.5):
    return np.array([[1, rho_sb, rho_si], [rho_sb, 1, rho_bi], [rho_si, rho_bi, 1.0]])


def make_shocks(n, t, corr=None, dist="normal", seed=SEED):
    """z[N,T,3]（株・債券・インフレ）。dist='t' なら株の攪乱を t(df=5)·sqrt(3/5) に置換。
    相関は simulate 側で付ける（ここでは独立）。同じ seed なら同じ値（共通乱数）。"""
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n, t, 3))
    if dist == "t":
        chi = np.random.default_rng(seed + 1).chisquare(5, size=(n, t))
        z[:, :, 0] = z[:, :, 0] * np.sqrt(3.0 / chi)
    return z


_Z_CACHE = {}


def get_shocks(n, seed, dist):
    key = (n, seed, dist)
    if key not in _Z_CACHE:
        if len(_Z_CACHE) > 3:
            _Z_CACHE.clear()
        _Z_CACHE[key] = make_shocks(n, T_YEARS, dist=dist, seed=seed)
    return _Z_CACHE[key]


# ---------------------------------------------------------------- 税
def stock_sale(S, B, need, tau=TAU):
    """課税口座の株を売って手取り need を得る。S,B を in-place 更新。(手取り, 税)を返す。"""
    pos = S > 1e-9
    g = np.where(pos, np.maximum(0.0, 1.0 - B / np.where(pos, S, 1.0)), 0.0)
    f = 1.0 - tau * g
    sale = np.minimum(S, need / f)
    net = sale * f
    frac = np.where(pos, sale / np.where(pos, S, 1.0), 0.0)
    B -= B * frac
    S -= sale
    return net, sale * tau * g


# ---------------------------------------------------------------- シミュレーション
DEFAULTS = dict(
    w0=97000.0,           # 運用元本(万円)
    mu=0.04, sigma=0.16, cost=0.002,
    infl_mean=0.02, infl_ar=0.5, infl_sd=0.015,
    bond_mu=0.0075, bond_sd=0.06, cash_rate=0.015,
    rho_si=0.0, rho_sb=0.1, rho_bi=-0.5,
    dist="normal",
    rule="R0",
    # 支出（実質・万円/年）
    d0=360.0, case="中", prop_tax=True, kokuho=130.0, repair=164.4, insurance=35.0, utility=10.0,
    pension=0.0, pension_start=65, age0=60,   # pension は年額(世帯合計)
    spend_total=None,    # 指定すると支出全体の基準(実質)をこの値に固定(T0用)
    spend_gross=False,   # True: 売却額=支出(税は支出に含まれる)
    # ポートフォリオ
    bond_w=0.0, buffer_years=0.0, nisa=0.0, rebal_band=0.05,
    r1_add=0.002, r1_lag=True,
)


def simulate(params, z):
    p = dict(DEFAULTS)
    p.update(params)
    N, T, _ = z.shape
    rule = p["rule"]
    corr = corr_matrix(p["rho_si"], p["rho_sb"], p["rho_bi"])
    e = z @ np.linalg.cholesky(corr).T
    es, eb, ei = e[:, :, 0], e[:, :, 1], e[:, :, 2]

    infl = np.empty((N, T))
    prev = np.full(N, p["infl_mean"])
    for t in range(T):
        prev = p["infl_mean"] + p["infl_ar"] * (prev - p["infl_mean"]) + p["infl_sd"] * ei[:, t]
        infl[:, t] = prev
    rs_real = np.maximum(p["mu"] + p["sigma"] * es - p["cost"], -0.99)
    rb_real = np.maximum(p["bond_mu"] + p["bond_sd"] * eb, -0.99)
    rs_nom = (1 + rs_real) * (1 + infl) - 1
    rb_nom = (1 + rb_real) * (1 + infl) - 1

    # 支出の基準
    pt = property_tax_path(p["case"], T) if p["prop_tax"] else np.zeros(T)
    fixed = pt + p["kokuho"] + p["repair"] + p["insurance"] + p["utility"]
    pen = np.array([p["pension"] if (p["age0"] + t) >= p["pension_start"] else 0.0 for t in range(T)])
    if p["spend_total"] is not None:
        base = np.full(T, float(p["spend_total"]))
        fixed = np.zeros(T)
        d0 = float(p["spend_total"])
    else:
        d0 = p["d0"]
        base = d0 + fixed - pen
    base0 = base[0]

    w0 = p["w0"]
    bw = p["bond_w"]
    k = p["buffer_years"]
    z0 = np.zeros(N)
    if w0 <= 0:
        return dict(depl_year=np.ones(N), final=z0, min_ratio=z0, cut_frac=np.ones(N),
                    tax=z0, w0=w0, wr0=float("inf"), n=N)
    C = np.full(N, min(k * base0, w0))
    rest = w0 - C
    stock_tot = rest * (1 - bw)
    Sn = np.minimum(p["nisa"], stock_tot)
    S = stock_tot - Sn
    Bt = S.copy()
    Bd = rest * bw
    cpi = np.ones(N)
    alive = np.ones(N, bool)
    depl = np.full(N, np.inf)
    min_ratio = np.full(N, np.inf)
    cut_n = np.zeros(N)
    alive_n = np.zeros(N)
    tax_total = np.zeros(N)
    prev_stock_ret = np.zeros(N)  # >=0 扱い
    prev_port_ret = np.zeros(N)
    prev_infl = np.full(N, p["infl_mean"])
    Dm = np.ones(N)          # R4
    Dreal = np.full(N, d0)   # R2
    level = np.zeros(N)      # R3
    x_nom = None
    spend_real_prev = None
    wr0 = base0 / w0
    tau_w = 0.0 if p["spend_gross"] else TAU

    for t in range(T):
        tot = S + Sn + Bd + C
        real_tot = tot / cpi
        # --- D の決定
        if rule == "R1":
            if x_nom is None:
                x_nom = np.full(N, base0)
            else:
                x_nom = x_nom * (1 + np.maximum((prev_infl if p["r1_lag"] else infl[:, t]) + p["r1_add"], 0))
            spend_nom = x_nom
            spend_real = x_nom / cpi
        else:
            if rule == "R0":
                D = np.full(N, d0)
            elif rule == "R2":
                Dreal = np.where(prev_port_ret < 0, Dreal / (1 + prev_infl), Dreal)
                Dreal = np.maximum(Dreal, 0.6 * d0)
                if t == 0:
                    Dreal = np.full(N, d0)
                D = Dreal
            elif rule == "R3":
                ratio = real_tot / w0
                level = np.where(ratio >= 0.9, 0, np.where(ratio < 0.6, 2, np.where(ratio < 0.8, np.maximum(level, 1), level)))
                D = np.maximum(d0 - level * 0.1 * base0, 0.0)
            elif rule == "R4":
                if t > 0:
                    wr = spend_real_prev / np.maximum(real_tot, 1e-9)
                    Dm = np.where(wr > 1.2 * wr0, Dm * 0.9, np.where(wr < 0.8 * wr0, Dm * 1.1, Dm))
                    Dm = np.clip(Dm, 0.5, 1.2)
                D = d0 * Dm
            else:
                raise ValueError(rule)
            spend_real = np.maximum(D + fixed[t] - pen[t], 0.0)
            spend_nom = spend_real * cpi
        spend_real_prev = spend_real

        # --- 支出
        need = np.where(alive, spend_nom, 0.0)
        got = np.minimum(C, need); C -= got; need -= got
        sf = prev_stock_ret >= 0
        n1, tx1 = stock_sale(S, Bt, need * sf, tau_w); need -= n1
        b1 = np.minimum(Bd, need * ~sf); Bd -= b1; need -= b1
        b2 = np.minimum(Bd, need); Bd -= b2; need -= b2
        n2, tx2 = stock_sale(S, Bt, need, tau_w); need -= n2
        n3 = np.minimum(Sn, need); Sn -= n3; need -= n3
        tax_total += (tx1 + tx2) / cpi
        dead = alive & (need > 1e-6)
        ratio_spend = spend_real / base[t]
        min_ratio = np.where(alive, np.minimum(min_ratio, ratio_spend), min_ratio)
        cut_n += alive & (ratio_spend < 0.9999)
        alive_n += alive
        if dead.any():
            depl[dead] = t + 1
            for a in (S, Bt, Sn, Bd, C):
                a[dead] = 0.0
            alive = alive & ~dead

        # --- バッファ補充・リバランス
        if k > 0:
            want = np.where(alive & sf, np.maximum(k * base[t] * cpi - C, 0.0), 0.0)
            n, tx = stock_sale(S, Bt, want); C += n; tax_total += tx / cpi
        if bw > 0:
            stk = S + Sn
            tot_nc = stk + Bd
            tgt = (1 - bw)
            over = alive & (tot_nc > 0) & (stk / np.where(tot_nc > 0, tot_nc, 1) > tgt + p["rebal_band"])
            amt = np.where(over, np.minimum(stk - tgt * tot_nc, S), 0.0)
            # 売却額 amt (額面) を課税口座から売る
            pos = S > 1e-9
            g = np.where(pos, np.maximum(0.0, 1 - Bt / np.where(pos, S, 1)), 0.0)
            frac = np.where(pos, amt / np.where(pos, S, 1), 0.0)
            tx = amt * TAU * g
            Bt -= Bt * frac; S -= amt
            Bd += amt - tx; tax_total += tx / cpi

        # --- 1 年の運用
        before = S + Sn + Bd + C
        rs, rb, it = rs_nom[:, t], rb_nom[:, t], infl[:, t]
        S *= 1 + rs; Sn *= 1 + rs
        ib = np.maximum(Bd * rb, 0.0) * TAU
        Bd = Bd * (1 + rb) - ib
        ic = C * max(p["cash_rate"], 0.0) * TAU
        C = C * (1 + p["cash_rate"]) - ic
        tax_total += (ib + ic) / cpi
        after = S + Sn + Bd + C
        prev_port_ret = np.where(before > 0, after / np.where(before > 0, before, 1) - 1, 0.0)
        prev_stock_ret = rs
        prev_infl = it
        cpi = cpi * (1 + it)

    final = np.where(alive, (S + Sn + Bd + C) / cpi, 0.0)
    min_ratio = np.where(np.isfinite(min_ratio), min_ratio, 0.0)
    return dict(depl_year=depl, final=final, min_ratio=min_ratio,
                cut_frac=cut_n / np.maximum(alive_n, 1), tax=tax_total, w0=w0, wr0=wr0, n=N)


def metrics(res):
    d = res["depl_year"]
    f = res["final"]
    return {
        "枯渇50年": float(np.mean(d <= 50) * 100),
        "枯渇30年": float(np.mean(d <= 30) * 100),
        "枯渇20年": float(np.mean(d <= 20) * 100),
        "終価中央値": float(np.median(f)),
        "終価10%点": float(np.percentile(f, 10)),
        "削減年割合": float(np.mean(res["cut_frac"]) * 100),
        "最低支出比中央": float(np.median(res["min_ratio"])),
        "最低支出比10%点": float(np.percentile(res["min_ratio"], 10)),
        "初年度取崩率": float(res["wr0"] * 100),
    }


def case_params(case, land=False, **kw):
    _, cost = acquisition_cost(case, land)
    p = dict(case=case, w0=TOTAL_ASSET - cost - CASH_ON_HAND, nisa=1800.0)
    p.update(kw)
    return p, cost


def run_case(label, params, n, seed, extra=None):
    z = get_shocks(n, seed, params.get("dist", "normal"))
    t0 = time.time()
    res = simulate(params, z)
    row = dict(extra or {})
    row["ケース"] = label
    row["元本"] = round(res["w0"])
    row.update(metrics(res))
    row["秒"] = round(time.time() - t0, 2)
    return row


# ---------------------------------------------------------------- グリッド
def grid_T0(n, seed):
    rows = []
    for mu in (0.05, 0.04, 0.03):
        p = dict(w0=97000.0, mu=mu, rule="R1", spend_total=1800.0, prop_tax=False, nisa=0.0,
                 spend_gross=True)
        rows.append(run_case("T0 μ%d%%" % round(mu * 100), p, n, seed,
                             dict(グリッド="T0", 取得費="-", μ=mu * 100, 規則="R1", 株比率=100, バッファ=0)))
    return rows


def grid_G1(n, seed):
    rows = []
    for cs in ("低", "中", "高"):
        for mu in (0.03, 0.04, 0.05):
            for r in ("R0", "R2", "R3", "R4"):
                p, c = case_params(cs, mu=mu, rule=r)
                rows.append(run_case("取得費%s μ%d%% %s" % (cs, round(mu * 100), r), p, n, seed,
                                     dict(グリッド="G1", 取得費=cs, 取得費額=c, μ=mu * 100, 規則=r, 株比率=100, バッファ=0)))
    for cs in ("低", "中"):
        for mu in (0.03, 0.04, 0.05):
            for r in ("R0", "R3"):
                p, c = case_params(cs, land=True, mu=mu, rule=r)
                rows.append(run_case("土地未取得%s μ%d%% %s" % (cs, round(mu * 100), r), p, n, seed,
                                     dict(グリッド="G1土地", 取得費=cs + "+土地", 取得費額=c, μ=mu * 100, 規則=r, 株比率=100, バッファ=0)))
    return rows


def grid_G2(n, seed, mus=(0.03, 0.04), rules=("R0", "R3")):
    rows = []
    for mu in mus:
        for k in (0, 1, 2, 3):
            for b in (0.0, 0.2, 0.4):
                for r in rules:
                    p, c = case_params("中", mu=mu, rule=r, buffer_years=k, bond_w=b)
                    rows.append(run_case("μ%d%% バッファ%d年 債券%d%% %s" % (round(mu * 100), k, round(b * 100), r), p, n, seed,
                                         dict(グリッド="G2", 取得費="中", 取得費額=c, μ=mu * 100, 規則=r,
                                              株比率=round((1 - b) * 100), バッファ=k)))
    return rows


def pick_recommended(g2rows):
    """μ4%・R3 の中で、枯渇50年(pt)＋最低支出比10%点の不足(pt)が最小の構成。"""
    cand = [r for r in g2rows if r["μ"] == 4.0 and r["規則"] == "R3"]
    return min(cand, key=lambda r: r["枯渇50年"] + (1 - r["最低支出比10%点"]) * 100 * 0.5)


def grid_G3(n, seed, rec):
    k, b = rec["バッファ"], 1 - rec["株比率"] / 100
    base = dict(rule="R3", buffer_years=k, bond_w=b)
    items = [
        ("基準(推奨構成 μ4%)", dict(mu=0.04)),
        ("スタグフレーション(株-インフレ相関-0.4)", dict(mu=0.04, rho_si=-0.4)),
        ("ファットテール(t df5)", dict(mu=0.04, dist="t")),
        ("σ18%", dict(mu=0.04, sigma=0.18)),
        ("国保A2(国保+年金30)", dict(mu=0.04, kokuho=30.0)),
        ("公的年金A3(60歳・2人、65歳から166)", dict(mu=0.04, pension=166.0)),
        ("μ3%+スタグフレーション", dict(mu=0.03, rho_si=-0.4)),
    ]
    rows = []
    for lab, kw in items:
        p, c = case_params("中", **dict(base, **kw))
        rows.append(run_case(lab, p, n, seed, dict(グリッド="G3", 取得費="中", 取得費額=c, μ=kw["mu"] * 100,
                                                    規則="R3", 株比率=rec["株比率"], バッファ=k)))
    return rows


def max_cost(mu, n, seed, rec_kb, rule, target=10.0, iters=14):
    """50年枯渇 <= target% を満たす最大の取得費(万円)を2分探索（中ケースの固定資産税）。"""
    k, b = rec_kb
    z = get_shocks(n, seed, "normal")
    lo, hi = 0.0, TOTAL_ASSET - CASH_ON_HAND  # 取得費
    def dep(cost):
        p = dict(case="中", w0=TOTAL_ASSET - CASH_ON_HAND - cost, nisa=1800.0, mu=mu, rule=rule,
                 buffer_years=k, bond_w=b)
        return float(np.mean(simulate(p, z)["depl_year"] <= 50) * 100)
    for _ in range(iters):
        mid = (lo + hi) / 2
        if dep(mid) <= target:
            lo = mid
        else:
            hi = mid
    return lo


def grid_BIS(n, seed, rec):
    kb = (rec["バッファ"], 1 - rec["株比率"] / 100)
    rows = []
    for mu in (0.03, 0.04, 0.05):
        for lab, kb_, rule in (("株100%・R0", (0, 0.0), "R0"), ("推奨構成・R3", kb, "R3")):
            c = max_cost(mu, n, seed, kb_, rule)
            rows.append({"グリッド": "BIS", "ケース": "μ%d%% %s" % (round(mu * 100), lab), "μ": mu * 100,
                         "構成": lab, "取得費上限": round(c), "元本": round(TOTAL_ASSET - CASH_ON_HAND - c)})
    return rows


def run_grid(name, n=100000, seed=SEED):
    if name == "T0":
        return grid_T0(n, seed)
    if name == "G1":
        return grid_G1(n, seed)
    if name == "G2":
        return grid_G2(n, seed)
    if name == "G3":
        rec = pick_recommended(grid_G2(n, seed, mus=(0.04,)))
        return grid_G3(n, seed, rec)
    if name == "BIS":
        rec = pick_recommended(grid_G2(n, seed, mus=(0.04,)))
        return grid_BIS(n, seed, rec)
    if name == "all":
        rows = grid_T0(n, seed) + grid_G1(n, seed)
        g2 = grid_G2(n, seed)
        rec = pick_recommended(g2)
        rows += g2 + grid_G3(n, seed, rec) + grid_BIS(n, seed, rec)
        return rows
    raise ValueError(name)


# ---------------------------------------------------------------- 出力
COLS_MAIN = ["ケース", "元本", "枯渇50年", "枯渇30年", "枯渇20年", "終価中央値", "終価10%点",
             "削減年割合", "最低支出比中央", "最低支出比10%点", "初年度取崩率"]


def to_markdown(rows):
    out = []
    groups = {}
    for r in rows:
        groups.setdefault(r["グリッド"], []).append(r)
    titles = {"T0": "T0 施主試算の再現", "G1": "G1 取得費×μ×規則（建物のみ、株100%・バッファ0）",
              "G1土地": "G1 土地未取得", "G2": "G2 ポートフォリオ（取得費 中）", "G3": "G3 感度（推奨構成）",
              "BIS": "取得費の上限（50年枯渇 10% 以下）"}
    for g, rs in groups.items():
        out.append("### " + titles.get(g, g) + "\n")
        if g == "BIS":
            out.append("| ケース | 取得費の上限(万円) | 運用元本(万円) |\n|---|---:|---:|")
            for r in rs:
                out.append("| %s | %s | %s |" % (r["ケース"], format(r["取得費上限"], ","), format(r["元本"], ",")))
        else:
            hdr = ["ケース", "元本(万円)", "50年枯渇%", "30年枯渇%", "20年枯渇%", "終価中央値(万円)", "終価10%点(万円)",
                   "削減年割合%", "最低支出比 中央", "最低支出比 10%点", "初年度取崩率%"]
            out.append("| " + " | ".join(hdr) + " |\n|---|" + "---:|" * (len(hdr) - 1))
            for r in rs:
                out.append("| %s | %s | %.1f | %.1f | %.1f | %s | %s | %.1f | %.2f | %.2f | %.2f |" % (
                    r["ケース"], format(r["元本"], ","), r["枯渇50年"], r["枯渇30年"], r["枯渇20年"],
                    format(round(r["終価中央値"]), ","), format(round(r["終価10%点"]), ","),
                    r["削減年割合"], r["最低支出比中央"], r["最低支出比10%点"], r["初年度取崩率"]))
        out.append("")
    return "\n".join(out)


def write_csv(rows, path):
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="T0")
    ap.add_argument("--n", type=int, default=100000)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--csv")
    ap.add_argument("--md")
    a = ap.parse_args(argv)
    t0 = time.time()
    rows = run_grid(a.grid, a.n, a.seed)
    md = to_markdown(rows)
    print(md)
    print("elapsed %.1fs, %d rows" % (time.time() - t0, len(rows)), file=sys.stderr)
    if a.csv:
        write_csv(rows, a.csv)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(md + "\n")


if __name__ == "__main__":
    main()
