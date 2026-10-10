"""Prepare counter-plans against the published teams in data/known_teams.json.

  python prep.py                 every one of our 60 orders (3 of 6 x lead) vs each likely selection of theirs,
                                 BOTH sides reading 3 turns ahead, real randomness, 4 games each
  python prep.py --quick         greedy ranking first, then the best 20 orders with a 1-turn look-ahead (10 games)
  python prep.py --team <id>     only that team (results are cached per team in logs/prep/<id>.json; --redo ignores
                                 the cache)

Likely selections of theirs: the ones written in the article first (fixed lead), then usage/matchup guesses with
their two most likely leads; extra lead patterns can be forced with "extra_opp" in known_teams.json.
The best order and, for every selection of theirs, the win rate of every order (best order per selection,
how the games went) go to data/known_teams.json ("counter") and logs/COUNTERS.md.
battle.py select uses the stored order when the opponent's six match a known team.
"""
import itertools, json, os, random, sys, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle as B  # noqa: E402
import engine as E  # noqa: E402
import search as S  # noqa: E402

KNOWN_P = os.path.join(HERE, 'data', 'known_teams.json')
REPORT_P = os.path.join(HERE, '..', 'logs', 'COUNTERS.md')
SEEDS = 10
DEPTH = 3          # look-ahead turns in the full mode
FULL_SEEDS = 4
CACHE_D = os.path.join(HERE, '..', 'logs', 'prep')


class RandomRNG:
    """Real randomness for play-outs (seeded)."""
    expected = False

    def __init__(self, seed):
        self.r = random.Random(seed)

    def chance(self, p, kind='', matters=False):
        return self.r.random() < p

    def roll(self, rolls, hp):
        return self.r.randrange(16)

    def sample(self, opts, kind=''):
        x = self.r.random() * sum(p for _, p in opts)
        for v, p in opts:
            x -= p
            if x <= 0:
                return v
        return opts[-1][0]


def game(args):
    """Both sides play with the same look-ahead (depth 0: 1-turn smart, else a depth-turn tree); returns
    (our result 1/0/-1, final eval, first actions, faints)."""
    order_, oorder, kid, seed = args[:4]
    depth = args[4] if len(args) > 4 else 0
    B._game_job((order_, oorder, False, kid))   # sets the known-team context in this process
    st = B.engine_game(order_, oorder)
    rng = RandomRNG(seed)
    first, faints = [], []
    for t in range(25):
        if st.winner is not None:
            break
        if depth:
            a0 = S.lookahead_action(st, 0, depth)
            a1 = S.lookahead_action(st, 1, depth)
        else:
            a0 = S.smart_action(st, 0)
            a1 = S.smart_action(st, 1)
        if t < 3:
            first.append((S.fmt(st, a0), _fmt_opp(st, a1)))
        before = [[m.alive for m in s.mons] for s in st.sides]
        st = E.step(st, a0, a1, rng=rng, chooser=S.chooser)
        for i in (0, 1):
            for j, m in enumerate(st.sides[i].mons):
                if before[i][j] and not m.alive:
                    faints.append((t + 1, i, m.name))
    res = st.winner if st.winner is not None else (1 if S.evaluate(st) > 0 else -1)
    return res, S.evaluate(st), first, faints


def _fmt_opp(st, a):
    if a is None:
        return '-'
    if a[0] == 's':
        return st.sides[1].mons[a[1]].name + 'に交代'
    if a[1] == 'recharge':
        return '（反動で動けない）'
    md = E.MOVES.get(a[1])
    return ('メガ＋' if len(a) > 2 and a[2] else '') + (md.ja if md else a[1])


def pool_map(fn, jobs):
    import multiprocessing as mp
    ctx = mp.get_context('fork') if hasattr(os, 'fork') else mp.get_context('spawn')
    with ctx.Pool(os.cpu_count() or 1) as pool:
        return pool.map(fn, jobs, chunksize=1)


def opp_trips(t, opp6):
    """Their likely selections with weights: the article's ones first (fixed lead), then matchup guesses."""
    B.set_known_context(opp6)
    by_base = {B._base(x): x for x in opp6}
    out = []
    for pk in t.get('picks', []):
        c = [by_base.get(B._base(x)) for x in pk['mons']]
        if all(c):
            out.append((0.6 * pk['weight'], [c]))
    w = B.opp_pick_weights(opp6, list(B.MY.values()))
    guess = sorted(itertools.combinations(opp6, 3), key=lambda c: -w[c[0]] * w[c[1]] * w[c[2]])
    known = [set(c[0]) for _, c in out]
    rest = [c for c in guess if set(c) not in known][:max(2, 5 - len(out))]
    for c in rest:
        lw = [B.lead_rate(B._base(x)) for x in c]
        leads = sorted(zip(lw, c), reverse=True)[:2]
        out.append((0.4 / len(rest), [[l] + [x for x in c if x != l] for _, l in leads]))
    for ex in t.get('extra_opp', []):   # forced lead patterns, e.g. a lead we must prepare for
        c = [by_base.get(B._base(x)) for x in ex['mons']]
        if all(c) and c not in [o for _, os_ in out for o in os_]:
            out.append((ex.get('weight', 0.1), [c]))
    tot = sum(p for p, _ in out)
    return [(p / tot, o) for p, o in out]


def all_orders():
    my_names = [B.BASE_OF.get(m.species, m.species) for m in B.TEAM]
    out = []
    for c in itertools.combinations(my_names, 3):
        for lead in c:
            out.append([lead] + [x for x in c if x != lead])
    return out


def prep_team_full(t, redo=False):
    """All 60 orders x every likely selection of theirs x FULL_SEEDS games, both sides reading DEPTH turns ahead."""
    os.makedirs(CACHE_D, exist_ok=True)
    cp = os.path.join(CACHE_D, t['id'] + '.json')
    opp6 = [B._base(m['name']) for m in t['team']]
    B.set_known_context(opp6)
    trips = opp_trips(t, opp6)
    sig = repr(trips)
    if not redo and os.path.exists(cp):
        c = json.load(open(cp, encoding='utf-8'))
        if c.get('sig') == sig and 'matrix' in c.get('result', {}):
            return c['result']
    t0 = time.time()
    orders = all_orders()
    jobs, meta = [], []
    for o in orders:
        for p, oorders in trips:
            for oo in oorders:
                for sd in range(FULL_SEEDS):
                    jobs.append((o, oo, t['id'], zlib.crc32(repr((o, oo, sd)).encode()), DEPTH))
                    meta.append((tuple(o), p / len(oorders), tuple(oo)))
    print(f"  {t['title']}: {len(jobs)} games ...", flush=True)
    res = pool_map(game, jobs)
    result = summarize(meta, res, FULL_SEEDS)
    result.update({'mode': f'全{len(orders)}通り×相手選出{sum(len(o) for _, o in trips)}通り×各{FULL_SEEDS}戦・両者{DEPTH}手読み',
                   'games': len(jobs), 'seconds': round(time.time() - t0, 1)})
    json.dump({'sig': sig, 'result': result}, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
    return result


def summarize(meta, res, seeds):
    score, detail = {}, {}
    for (o, p, oo), (r, v, first, faints) in zip(meta, res):
        score[o] = score.get(o, 0.0) + p / seeds * (r + 0.01 * v)
        detail.setdefault(o, {}).setdefault(oo, []).append((r, first, faints))
    # worst case first: the selection of theirs that beats us most often decides (we do not know their pick
    # before the battle); ties by the weighted average
    def worst(o):
        return min(sum(1 for r, _, _ in g if r == 1) / len(g) for g in detail[o].values())
    ranking = sorted(score.items(), key=lambda x: (-worst(x[0]), -x[1]))
    bo = ranking[0][0]
    vs = []
    for oo, games in detail[bo].items():
        f = games[0]
        # the best order of ours against this particular selection
        per = sorted(((sum(1 for r, _, _ in detail[o][oo] if r == 1), o) for o in detail), key=lambda x: -x[0])
        vs.append({'opp': list(oo), 'wins': sum(1 for r, _, _ in games if r == 1), 'games': len(games),
                   'first_turns': f[1], 'faints': [(tn, '自分' if i == 0 else '相手', n) for tn, i, n in f[2]][:6],
                   'best_vs': [{'order': list(o), 'wins': w} for w, o in per[:3]]})
    winrate = {' → '.join(o): round(sum(sum(1 for r, _, _ in g if r == 1) for g in detail[o].values()) /
                                     max(1, sum(len(g) for g in detail[o].values())), 3) for o in detail}
    matrix = {' → '.join(o): {' → '.join(oo): sum(1 for r, _, _ in g if r == 1) for oo, g in detail[o].items()}
              for o in detail}
    return {'order': list(bo), 'score': round(ranking[0][1], 3), 'worst': round(worst(bo), 3),
            'alternatives': [{'order': list(o), 'score': round(s, 3), 'worst': round(worst(o), 3)}
                             for o, s in ranking[1:5]],
            'vs': vs, 'winrate': winrate, 'matrix': matrix}


def prep_team(t, budget):
    opp6 = [B._base(m['name']) for m in t['team']]
    t0 = time.time()
    best, top, _ = B.select(opp6, ignore_stored=True)
    cands = [o for _, o in top]
    # widen to 15 by the greedy ranking
    B.set_known_context(opp6)
    trips = opp_trips(t, opp6)
    my_names = [B.BASE_OF.get(m.species, m.species) for m in B.TEAM]
    orders = []
    for c in itertools.combinations(my_names, 3):
        for lead in c:
            orders.append([lead] + [x for x in c if x != lead])
    greedy = B.select(opp6, ignore_stored=True, return_all=True)
    ranked = [o for _, o in greedy][:20]
    for o in cands:
        if o not in ranked:
            ranked.append(o)
    jobs, meta = [], []
    for o in ranked:
        for p, oorders in trips:
            for oo in oorders:
                for sd in range(SEEDS):
                    jobs.append((o, oo, t['id'], zlib.crc32(repr((o, oo, sd)).encode())))
                    meta.append((tuple(o), p / len(oorders), tuple(oo)))
    res = pool_map(game, jobs)
    out = summarize(meta, res, SEEDS)
    out['seconds'] = round(time.time() - t0, 1)
    out['mode'] = f'上位{len(ranked)}通り×各{SEEDS}戦・両者1手読み'
    return out
    score, detail = {}, {}
    for (o, p, oo), (r, v, first, faints) in zip(meta, res):
        score[o] = score.get(o, 0.0) + p / SEEDS * (r + 0.01 * v)
        detail.setdefault(o, {}).setdefault(oo, []).append((r, first, faints))
    ranking = sorted(score.items(), key=lambda x: -x[1])
    bo = ranking[0][0]
    vs = []
    for oo, games in detail[bo].items():
        wins = sum(1 for r, _, _ in games if r == 1)
        f = games[0]
        vs.append({'opp': list(oo), 'wins': wins, 'games': len(games), 'first_turns': f[1],
                   'faints': [(tn, '自分' if i == 0 else '相手', n) for tn, i, n in f[2]][:6]})
    return {'order': list(bo), 'score': round(ranking[0][1], 3),
            'alternatives': [{'order': list(o), 'score': round(s, 3)} for o, s in ranking[1:5]],
            'vs': vs, 'seconds': round(time.time() - t0, 1)}


def report(data):
    L = ['# 公開構築への事前対策（prep.py が自動生成）', '',
         'こちらの選出（3体×先発）を相手の想定選出と対戦させた結果です。乱数（ダメージ・命中・急所・まひ・追加効果）あり。',
         '相手の型は記事に埋め込まれた型（持ち物・性格・能力P・技）を使い、相手も同じ深さで読んで動きます。', '']
    for t in data['teams']:
        c = t.get('counter')
        if not c:
            continue
        wr = c.get('winrate', {})
        L += [f"## {t['title']}", '', f"- 記事: {t['url']}", f"- 方法: {c.get('mode', '')}",
              '- 相手: ' + ' / '.join(f"{m['name']}（{m['item']}・{'/'.join(m['moves'])}）" for m in t['team']),
              f"- **おすすめ選出: {' → '.join(c['order'])}**（最悪の相手選出でも勝率 {c.get('worst', 0):.0%}、"
              f"全体 {wr.get(' → '.join(c['order']), 0):.0%}）",
              '- 次点: ' + '、'.join(f"{' → '.join(a['order'])}（最悪 {a.get('worst', 0):.0%}・全体 "
                                   f"{wr.get(' → '.join(a['order']), 0):.0%}）" for a in c['alternatives'][:3]),
              '- 選び方: 相手の選出は試合前に分からないので、想定した相手選出のうち最も負けやすいものに対する勝率で順位を付けています。', '',
              '| 相手の選出（先発→） | おすすめ選出の勝ち/試合 | この選出に最も勝った選出 | 序盤（自分 / 相手） | 倒れた順 |',
              '|---|---|---|---|---|']
        for v in c['vs']:
            ft = '<br>'.join(f"{a} / {b}" for a, b in v['first_turns'])
            fa = '、'.join(f"{tn}T{side}{n}" for tn, side, n in v['faints'])
            bv = '<br>'.join(f"{' → '.join(b['order'])}（{b['wins']}/{v['games']}）" for b in v.get('best_vs', [])[:2])
            L.append(f"| {' → '.join(v['opp'])} | {v['wins']}/{v['games']} | {bv} | {ft} | {fa} |")
        L.append('')
        if t.get('notes'):
            L += t['notes'] + ['']
    os.makedirs(os.path.dirname(REPORT_P), exist_ok=True)
    open(REPORT_P, 'w', encoding='utf-8').write('\n'.join(L) + '\n')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    args = sys.argv[1:]
    quick, redo = '--quick' in args, '--redo' in args
    only = args[args.index('--team') + 1] if '--team' in args else None
    data = json.load(open(KNOWN_P, encoding='utf-8'))
    for t in data['teams']:
        if only and t['id'] != only:
            continue
        c = prep_team(t, 0) if quick else prep_team_full(t, redo)
        t['counter'] = c
        print(f"{t['title']}: {' → '.join(c['order'])}  ({c['seconds']}s)", flush=True)
        json.dump(data, open(KNOWN_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    report(data)
    print('→', os.path.normpath(REPORT_P))


if __name__ == '__main__':
    main()
