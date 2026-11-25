"""簡易試験（N=5,000）。pytest でも `python3 finance/test_portfolio_mc.py` でも動く。"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portfolio_mc as pm  # noqa: E402

N = 5000
Z = pm.make_shocks(N, pm.T_YEARS, seed=pm.SEED)


def dep(**kw):
    p, _ = pm.case_params(kw.pop("case", "中"), **kw)
    return float(np.mean(pm.simulate(p, Z)["depl_year"] <= 50) * 100)


def test_acquisition_totals():
    assert round(pm.acquisition_cost("低")[1]) == 34276
    assert round(pm.acquisition_cost("中")[1]) == 43976
    assert round(pm.acquisition_cost("高")[1]) == 56512


def test_t0_reproduction():
    for mu, target in ((0.05, 11), (0.04, 19), (0.03, 31)):
        p = dict(w0=97000.0, mu=mu, rule="R1", spend_total=1800.0, prop_tax=False, nisa=0.0, spend_gross=True)
        v = np.mean(pm.simulate(p, Z)["depl_year"] <= 50) * 100
        assert abs(v - target) <= 3.5, (mu, v)  # N=5,000 の誤差を見込む


def test_reproducible():
    a = pm.simulate(dict(w0=50000.0, rule="R3"), pm.make_shocks(N, pm.T_YEARS, seed=7))
    b = pm.simulate(dict(w0=50000.0, rule="R3"), pm.make_shocks(N, pm.T_YEARS, seed=7))
    assert np.array_equal(a["final"], b["final"]) and np.array_equal(a["depl_year"], b["depl_year"])


def test_monotonic():
    assert dep(mu=0.03) >= dep(mu=0.04) >= dep(mu=0.05)
    assert dep(case="低") <= dep(case="中") <= dep(case="高")
    assert dep(kokuho=30.0) <= dep(kokuho=130.0) <= dep(kokuho=230.0)
    lo = pm.simulate(dict(w0=60000.0, sigma=0.10), Z)["final"]
    hi = pm.simulate(dict(w0=60000.0, sigma=0.20), Z)["final"]
    # σ が上がっても(算術平均固定で)中央値は上がらない: 0.5pt 相当の許容
    assert np.median(hi) <= np.median(lo) * 1.005


def test_tax():
    # 簿価 0 なら売却額の 20.315% が税
    S = np.array([1000.0]); B = np.array([0.0])
    net, tax = pm.stock_sale(S, B, np.array([400.0]))
    sale = 1000.0 - S[0]
    assert abs(tax[0] - sale * pm.TAU) < 1e-9 and abs(net[0] - 400.0) < 1e-9
    # 含み益 0 なら税 0
    S = np.array([1000.0]); B = np.array([1000.0])
    assert pm.stock_sale(S, B, np.array([300.0]))[1][0] == 0.0
    # μ=σ=インフレ=0（債券・現金も 0）なら税 0
    p = dict(w0=60000.0, mu=0.0, cost=0.0, sigma=0.0, infl_mean=0.0, infl_sd=0.0, bond_mu=0.0, bond_sd=0.0,
             cash_rate=0.0, bond_w=0.2, buffer_years=2, rule="R0")
    assert pm.simulate(p, Z)["tax"].max() == 0.0
    # NISA からの取り崩しは非課税（課税口座が空）
    p = dict(w0=1800.0, nisa=1800.0, mu=0.04, bond_w=0.0, rule="R0", spend_total=100.0)
    r = pm.simulate(p, Z)
    assert r["tax"].max() == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
