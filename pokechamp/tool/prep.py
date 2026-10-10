"""Prepare counter-plans against the published teams in data/known_teams.json.

  python prep.py [秒数/構築の目安=300]

For each known team:
  1. every 3-of-6 order of ours (60) is played out against the team's likely selections (the ones written in the
     article first, then usage/matchup guesses) with greedy play (battle.select);
  2. the best 20 orders are replayed with a 1-turn look-ahead on BOTH sides and real randomness (damage rolls,
     accuracy, crits, paralysis, secondary effects; several seeds per game);
  3. the best order and, for every likely selection of theirs, how the games went (wins, who fainted first,
     our first moves) are written to data/known_teams.json ("counter") and logs/COUNTERS.md.
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
    """Both sides play with a 1-turn look-ahead; returns (our result 1/0/-1, final eval, first actions, faints)."""
    order_, oorder, kid, seed = args
    B._game_job((order_, oorder, False, kid))   # sets the known-team context in this process
    st = B.engine_game(order_, oorder)
    rng = RandomRNG(seed)
    first, faints = [], []
    for t in range(25):
        if st.winner is not None:
            break
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
        return pool.map(fn, jobs, chunksize=2)


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
    tot = sum(p for p, _ in out)
    return [(p / tot, o) for p, o in out]


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
         '各構築について、こちらの3体×先発の全60通りを相手の想定選出と対戦させ、上位20通りを両者1手読み・乱数ありで',
         f'各{SEEDS}戦ずつ再対戦した結果です。相手の型は記事に埋め込まれた型（持ち物・性格・能力P・技）を使っています。', '']
    for t in data['teams']:
        c = t.get('counter')
        if not c:
            continue
        L += [f"## {t['title']}", '', f"- 記事: {t['url']}",
              '- 相手: ' + ' / '.join(f"{m['name']}（{m['item']}・{'/'.join(m['moves'])}）" for m in t['team']),
              f"- **おすすめ選出: {' → '.join(c['order'])}**",
              '- 次点: ' + '、'.join(' → '.join(a['order']) for a in c['alternatives'][:3]), '',
              '| 相手の選出（先発→） | 勝ち/試合 | 序盤（自分 / 相手） | 倒れた順 |', '|---|---|---|---|']
        for v in c['vs']:
            ft = '<br>'.join(f"{a} / {b}" for a, b in v['first_turns'])
            fa = '、'.join(f"{tn}T{side}{n}" for tn, side, n in v['faints'])
            L.append(f"| {' → '.join(v['opp'])} | {v['wins']}/{v['games']} | {ft} | {fa} |")
        L.append('')
    os.makedirs(os.path.dirname(REPORT_P), exist_ok=True)
    open(REPORT_P, 'w', encoding='utf-8').write('\n'.join(L) + '\n')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 300
    data = json.load(open(KNOWN_P, encoding='utf-8'))
    for t in data['teams']:
        c = prep_team(t, budget)
        t['counter'] = c
        print(f"{t['title']}: {' → '.join(c['order'])}  ({c['seconds']}s)")
        json.dump(data, open(KNOWN_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    report(data)
    print('→', os.path.normpath(REPORT_P))


if __name__ == '__main__':
    main()
