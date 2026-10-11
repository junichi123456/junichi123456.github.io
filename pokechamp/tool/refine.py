"""Fine-tuning of our six (moves, items, stats; species stay) in rounds, then a blind test.

  python refine.py --round N            round N: our party data/party/R{N}.json (R1 = team.py as it is) plays every one
                                        of its 60 orders against every likely selection of every target team, both
                                        sides reading 3 turns ahead, one game per pairing (same random seeds in every
                                        round, their selections fixed at round 1). Cached per team in logs/refine/R{N}/
  python refine.py --analyze N          per member: how often it is brought, win rate with it, moves used, faints
  python refine.py --screen N v.json   quick check of single changes (v.json) on round N's best orders, same seeds
  python refine.py --report             logs/REFINE.md: rounds side by side
  python refine.py --blind N            blind test with party R{N}: selection from the six only (no article sets for
                                        either side, each side guesses the other's sets from usage data and what it
                                        has seen), we read 4 turns ahead, they read 3; one game per team

Target teams: data/known_teams.json + data/new_teams_m6b.json.
"""
import itertools, json, os, random, sys, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle as B  # noqa: E402
import engine as E  # noqa: E402
import search as S  # noqa: E402
import prep  # noqa: E402
from calc import Mon  # noqa: E402

PARTY_D = os.path.join(HERE, 'data', 'party')
OUT_D = os.path.join(HERE, '..', 'logs', 'refine')
NEW_P = os.path.join(HERE, 'data', 'new_teams_m6b.json')
REPORT_P = os.path.join(HERE, '..', 'logs', 'REFINE.md')
DEPTH = 3


# ---------------------------------------------------------------- teams and party

def teams():
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))['teams']
    if os.path.exists(NEW_P):
        ids = {t['id'] for t in data}
        data += [t for t in json.load(open(NEW_P, encoding='utf-8'))['teams'] if t['id'] not in ids]
    have = {t['id'] for t in B.KNOWN_TEAMS}
    B.KNOWN_TEAMS.extend(t for t in data if t['id'] not in have)
    return data


def party_now():
    return [dict(species=m.species, nature=m.nature, ap=dict(m.spv), ability=m.ability, item=m.item,
                 moves=list(m.moves), label=m.label) for m in B.TEAM]


def load_party(n):
    p = os.path.join(PARTY_D, f'R{n}.json')
    if not os.path.exists(p):
        if n != 1:
            raise SystemExit(f'{p} がありません')
        os.makedirs(PARTY_D, exist_ok=True)
        json.dump(party_now(), open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return json.load(open(p, encoding='utf-8'))


_BASE_SPECIES = None


def apply_party(party):
    """Put this party into battle.py's TEAM / MY (in this process; workers fork after this)."""
    global _BASE_SPECIES
    if _BASE_SPECIES is None:
        _BASE_SPECIES = [m.species for m in B.TEAM]
    assert [p['species'] for p in party] == _BASE_SPECIES, 'species must not change'
    items = [p['item'] for p in party]
    assert len(set(items)) == len(items), f'duplicate items: {items}'
    for p in party:
        assert sum(p['ap'].values()) <= 66 and all(0 <= v <= 32 for v in p['ap'].values()), p
        assert len(p['moves']) == 4 and len(set(p['moves'])) == 4, p
        assert all(m in B.MOVE for m in p['moves']), p['moves']
    B.TEAM[:] = [Mon(p['species'], p['nature'], p['ap'], p['ability'], p['item'], p['moves'], label=p['label'])
                 for p in party]
    B.MY.clear()
    B.MY.update(B.my_sets())
    B._OPP_CACHE.clear()


def sig(party):
    return json.dumps(party, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------- one game with a full record

def _ctx(kid):
    """Known-team context for team kid in this process (what battle._game_job does, without its play-out)."""
    if kid != ((B._KNOWN_CTX['team'] or {}).get('id')):
        B._KNOWN_CTX['team'] = next((t for t in B.KNOWN_TEAMS if t['id'] == kid), None)
        B._OPP_CACHE.clear()


def _name(st, i, a):
    if a is None:
        return '-'
    if a[0] == 's':
        return '→' + st.sides[i].mons[a[1]].name
    if a[1] == 'recharge':
        return '反動'
    md = E.MOVES.get(a[1])
    return ('M+' if len(a) > 2 and a[2] else '') + (md.ja if md else a[1])


def game(args):
    order_, oorder, kid, seed, depth = args
    _ctx(kid)
    st = B.engine_game(order_, oorder)
    rng = prep.RandomRNG(seed)
    log, faints = [], []
    for t in range(25):
        if st.winner is not None:
            break
        a0 = S.lookahead_action(st, 0, depth)
        a1 = S.lookahead_action(st, 1, depth)
        log.append((st.active(0).name, _name(st, 0, a0), st.active(1).name, _name(st, 1, a1)))
        before = [[m.alive for m in s.mons] for s in st.sides]
        st = E.step(st, a0, a1, rng=rng, chooser=S.chooser)
        for i in (0, 1):
            for j, m in enumerate(st.sides[i].mons):
                if before[i][j] and not m.alive:
                    faints.append((t + 1, i, m.name, log[-1][2 if i == 0 else 0]))
    res = st.winner if st.winner is not None else (1 if S.evaluate(st) > 0 else -1)
    left = [round(sum(m.hp / m.maxhp for m in s.mons if m.alive), 2) for s in st.sides]
    return res, log, faints, left


# ---------------------------------------------------------------- rounds

def trips_fixed(ts):
    """Their selections per team, fixed at round 1 so that every round meets the same opponents."""
    p = os.path.join(OUT_D, 'trips.json')
    d = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    ch = False
    for t in ts:
        if t['id'] not in d:
            opp6 = [B._base(m['name']) for m in t['team']]
            d[t['id']] = [[pw, oos] for pw, oos in prep.opp_trips(t, opp6)]
            ch = True
    if ch:
        os.makedirs(OUT_D, exist_ok=True)
        json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return d


def run_round(n, only=None):
    party = load_party(n)
    apply_party(party)
    ts = teams()
    tr = trips_fixed(ts)
    od = os.path.join(OUT_D, f'R{n}')
    os.makedirs(od, exist_ok=True)
    for t in ts:
        if only and t['id'] != only:
            continue
        cp = os.path.join(od, t['id'] + '.json')
        if os.path.exists(cp) and json.load(open(cp, encoding='utf-8')).get('sig') == sig(party):
            continue
        t0 = time.time()
        jobs, meta = [], []
        for o in prep.all_orders():
            for pw, oos in tr[t['id']]:
                for oo in oos:
                    jobs.append((o, oo, t['id'], zlib.crc32(repr((o, oo, 0)).encode()), DEPTH))
                    meta.append((o, oo, pw / len(oos)))
        print(f"R{n} {t['title'][:30]}: {len(jobs)} games ...", flush=True)
        res = prep.pool_map(game, jobs)
        games = [{'order': o, 'opp': oo, 'w': w, 'res': r[0], 'log': r[1], 'faints': r[2], 'left': r[3]}
                 for (o, oo, w), r in zip(meta, res)]
        json.dump({'sig': sig(party), 'seconds': round(time.time() - t0, 1), 'games': games},
                  open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
        print(f"  done {round(time.time() - t0)}s  win {sum(g['res'] == 1 for g in games) / len(games):.0%}",
              flush=True)


def load_round(n):
    od = os.path.join(OUT_D, f'R{n}')
    out = {}
    for t in teams():
        cp = os.path.join(od, t['id'] + '.json')
        if os.path.exists(cp):
            out[t['id']] = json.load(open(cp, encoding='utf-8'))['games']
    return out


def team_stats(games):
    """Best order (worst case first, as in battle.select), its worst/average, and the mean over all orders."""
    by = {}
    for g in games:
        by.setdefault(tuple(g['order']), {}).setdefault(tuple(g['opp']), []).append(g)
    rows = []
    for o, d in by.items():
        wr = {oo: sum(x['res'] == 1 for x in gs) / len(gs) for oo, gs in d.items()}
        wsum = sum(gs[0]['w'] for gs in d.values())
        avg = sum(wr[oo] * d[oo][0]['w'] for oo in d) / wsum
        flat = sum(wr.values()) / len(wr)
        rows.append((min(wr.values()), avg, flat, o, min(wr, key=wr.get)))
    rows.sort(key=lambda r: (-r[0], -r[1], -r[2]))
    allw = sum(g['res'] == 1 for g in games) / len(games)
    top5 = sum(r[2] for r in rows[:5]) / 5
    return {'best': rows[0], 'all': allw, 'top5': top5, 'rows': rows}


def analyze(n, quiet=False):
    R = load_round(n)
    ts = {t['id']: t for t in teams()}
    mon = {}
    for kid, games in R.items():
        st = team_stats(games)
        top = {r[3] for r in st['rows'][:5]}
        for g in games:
            for m in g['order']:
                d = mon.setdefault(m, {'games': 0, 'wins': 0, 'top': 0, 'lead': 0, 'moves': {}, 'faint': 0,
                                       'killed_by': {}, 'kos': 0})
                d['games'] += 1
                d['wins'] += g['res'] == 1
                if tuple(g['order']) in top:
                    d['top'] += 1
                    if m == g['order'][0]:
                        d['lead'] += 1
            if tuple(g['order']) not in top:
                continue
            for me, a, op, b in g['log']:
                me_b = B._base(me)
                if me_b in mon and not a.startswith('→'):
                    k = a.replace('M+', '')
                    mon[me_b]['moves'][k] = mon[me_b]['moves'].get(k, 0) + 1
            for tn, i, name, by in g['faints']:
                if i == 0:
                    b_ = B._base(name)
                    if b_ in mon:
                        mon[b_]['faint'] += 1
                        mon[b_]['killed_by'][B._base(by)] = mon[b_]['killed_by'].get(B._base(by), 0) + 1
                else:
                    b_ = B._base(by)
                    if b_ in mon:
                        mon[b_]['kos'] += 1
    L = [f'# R{n} 分析', '']
    L += ['| 構築 | 最善の選出 | 最悪 | 平均 | 全選出平均 | 上位5選出平均 | 苦手な相手選出 |', '|---|---|---|---|---|---|---|']
    for kid, games in R.items():
        s = team_stats(games)
        w, a, f, o, wo = s['best']
        L.append(f"| {ts[kid]['title'][:24]} | {' → '.join(o)} | {w:.0%} | {a:.0%} | {s['all']:.0%} | {s['top5']:.0%} | "
                 f"{' → '.join(wo)} |")
    L += ['', '| 個体 | 上位5選出での採用 | うち先発 | 採用時勝率(全選出) | 上位選出での技使用 | 倒れた回数 | 倒した数 | 主に倒された相手 |',
          '|---|---|---|---|---|---|---|---|']
    for m, d in sorted(mon.items(), key=lambda x: -x[1]['top']):
        mv = '、'.join(f'{k}{v}' for k, v in sorted(d['moves'].items(), key=lambda x: -x[1]))
        kb = '、'.join(f'{k}{v}' for k, v in sorted(d['killed_by'].items(), key=lambda x: -x[1])[:4])
        L.append(f"| {m} | {d['top']} | {d['lead']} | {d['wins'] / max(1, d['games']):.0%} | {mv} | {d['faint']} | "
                 f"{d['kos']} | {kb} |")
    txt = '\n'.join(L) + '\n'
    os.makedirs(OUT_D, exist_ok=True)
    open(os.path.join(OUT_D, f'R{n}_analysis.md'), 'w', encoding='utf-8').write(txt)
    if not quiet:
        print(txt)
    return mon


def summary(n):
    R = load_round(n)
    if not R:
        return None
    S_ = [team_stats(g) for g in R.values()]
    k = len(S_)
    return {'teams': k, 'worst': sum(s['best'][0] for s in S_) / k, 'avg': sum(s['best'][1] for s in S_) / k,
            'all': sum(s['all'] for s in S_) / k, 'top5': sum(s['top5'] for s in S_) / k,
            'per': {kid: team_stats(g) for kid, g in R.items()}}


# ---------------------------------------------------------------- screening of single changes

def variant(party, v):
    """party with v's changes: {'mon': base species, 'item'/'nature'/'ap'/'moves'/'ability': new value} (a
    'swap': [old, new] entry replaces one move)."""
    out = json.loads(json.dumps(party))
    for p in out:
        if B._base(p['species']) == v['mon']:
            for k in ('item', 'nature', 'ap', 'moves', 'ability'):
                if k in v:
                    p[k] = v[k]
            for old, new in v.get('swap', []):
                p['moves'] = [new if x == old else x for x in p['moves']]
    return out


def _screen_job(args):
    party, o, oo, kid, seed = args
    apply_party(party)
    return game((o, oo, kid, seed, DEPTH))[0]


SCREEN_SEED = 1     # fresh seeds: the orders were picked by their round results, so those results are biased


def _screen_set(R, mon, k_all=3, k_mon=2):
    """Per team: its best k_all orders of the round plus the best k_mon that bring `mon`, x every selection."""
    out = []
    for kid, games in R.items():
        rows = team_stats(games)['rows']
        orders = [r[3] for r in rows[:k_all]]
        orders += [r[3] for r in rows if mon in r[3] and r[3] not in orders][:k_mon]
        out += [(kid, tuple(g['order']), tuple(g['opp'])) for g in games if tuple(g['order']) in orders]
    return out


def screen(n, vfile):
    """Each variant in vfile against the unchanged party (control) on the same pairings and the same fresh seeds."""
    base = load_party(n)
    R = load_round(n)
    vs = json.load(open(vfile, encoding='utf-8'))
    teams()
    out_p = os.path.join(OUT_D, f'screen_R{n}.json')
    done = json.load(open(out_p, encoding='utf-8')) if os.path.exists(out_p) else {}
    ctrl = {tuple(json.loads(k)): v for k, v in done.pop('_control', {}).items()}

    def play(party, keys):
        apply_party(party)
        jobs = [(party, list(o), list(oo), kid, zlib.crc32(repr((list(o), list(oo), SCREEN_SEED)).encode()))
                for kid, o, oo in keys]
        return prep.pool_map(_screen_job, jobs)

    for v in vs:
        key = v['name']
        if key in done:
            continue
        t0 = time.time()
        keys = _screen_set(R, v['mon'])
        need = [x for x in keys if x not in ctrl]
        if need:
            for x, r in zip(need, play(base, need)):
                ctrl[x] = r
        res = play(variant(base, v), keys)
        per = {}
        for (kid, o, oo), r1 in zip(keys, res):
            d = per.setdefault(kid, [0, 0, 0])
            d[0] += ctrl[(kid, o, oo)] == 1
            d[1] += r1 == 1
            d[2] += 1
        done[key] = {'v': v, 'base': sum(d[0] for d in per.values()), 'new': sum(d[1] for d in per.values()),
                     'n': len(keys), 'per': per, 'seconds': round(time.time() - t0)}
        done['_control'] = {json.dumps(list(k), ensure_ascii=False): r for k, r in ctrl.items()}
        json.dump(done, open(out_p, 'w', encoding='utf-8'), ensure_ascii=False)
        done.pop('_control')
        print(f"{key}: {done[key]['base']} -> {done[key]['new']} / {len(keys)}  ({done[key]['seconds']}s)", flush=True)
    apply_party(base)
    return done


# ---------------------------------------------------------------- blind test

def _templates(names, sets_fn, side):
    out = []
    for j, n in enumerate(names):
        base, mega = sets_fn(n)
        item = (mega.item if mega is not None else base.item) or ''
        out.append(E.make_mon(base.species, base.nature, base.spv, base.ability, item, base.moves, side, j))
    return out


def belief(st, k, tmpl, seen):
    """State as the player opposite side k sees it: side k's sets replaced by guesses (tmpl) plus the moves
    seen so far; hp ratio, status, boosts, field and everything visible stay as they are."""
    b = st.clone()
    s = b.sides[k]
    for j in range(len(s.mons)):
        true = st.sides[k].mons[j]
        tp = tmpl[j]
        m = s.own(j)
        mega_now = true.mega_form is not None and true.form is true.mega_form
        m.base_form, m.mega_form = tp.base_form, tp.mega_form
        m.form = (tp.mega_form or tp.form) if mega_now else tp.form
        if 'transformed' not in true.vol:
            m.stats = None
        m.ability = m.form.ability if (mega_now or true.ability == true.set_ability) else true.ability
        m.set_ability = tp.set_ability
        m.item = '' if not true.item else (true.item if mega_now else tp.item)
        m.set_item = tp.set_item
        rev = [x for x in seen.get(j, []) if x in E.MOVES]
        m.moves = tuple((rev + [x for x in tp.moves if x not in rev])[:4]) or tp.moves
        m.pp = None
        m.nature, m.ap = tp.nature, tp.ap
        m.maxhp = tp.maxhp
        m.hp = 0 if not true.alive else max(1, round(tp.maxhp * true.hp / true.maxhp))
        m.can_mega = tp.mega_form is not None and not s.mega_used and not mega_now
    return b


def blind_game(t, seed, my_depth=4, opp_depth=3):
    opp6 = [B._base(m['name']) for m in t['team']]
    real_match = B.match_known
    # 1) our selection from their six only: no article sets
    B.match_known = lambda *a, **k: None
    B.set_known_context(None)
    best, top, _ = B.select(opp6, ignore_stored=True)
    my_order = best
    # 2) their selection: what they would bring against our six (their article's patterns first), sampled
    B.match_known = real_match
    trips = prep.opp_trips(t, opp6)
    r = random.Random(seed)
    x = r.random() * sum(p for p, _ in trips)
    for p, oos in trips:
        x -= p
        if x <= 0:
            break
    opp_order = oos[r.randrange(len(oos))]
    # 3) the real game: true sets on both sides (their article sets, our party)
    _ctx(t['id'])
    st = B.engine_game(my_order, opp_order)
    # guesses: ours about them = usage data only, theirs about us = usage data only
    B.match_known = lambda *a, **k: None
    B.set_known_context(None)
    B._OPP_CACHE.clear()
    t_opp = _templates(opp_order, B.opp_sets, 1)
    B._OPP_CACHE.clear()
    t_me = _templates(my_order, B.opp_sets, 0)
    B.match_known = real_match
    _ctx(t['id'])
    seen = [{}, {}]
    rng = prep.RandomRNG(seed)
    log, faints = [], []
    for tn in range(30):
        if st.winner is not None:
            break
        a0 = S.lookahead_action(belief(st, 1, t_opp, seen[1]), 0, my_depth)
        a1 = S.lookahead_action(belief(st, 0, t_me, seen[0]), 1, opp_depth)
        log.append((st.active(0).name, _name(st, 0, a0), st.active(1).name, _name(st, 1, a1)))
        for i, a in ((0, a0), (1, a1)):
            if a and a[0] == 'm' and a[1] != 'recharge':
                seen[i].setdefault(st.sides[i].act, [])
                if a[1] not in seen[i][st.sides[i].act]:
                    seen[i][st.sides[i].act].append(a[1])
        before = [[m.alive for m in s.mons] for s in st.sides]
        st = E.step(st, a0, a1, rng=rng, chooser=S.chooser)
        for i in (0, 1):
            for j, m in enumerate(st.sides[i].mons):
                if before[i][j] and not m.alive:
                    faints.append((tn + 1, i, m.name))
    res = st.winner if st.winner is not None else (1 if S.evaluate(st) > 0 else -1)
    left = [[(m.name, round(100 * m.hp / m.maxhp)) for m in s.mons] for s in st.sides]
    return {'id': t['id'], 'title': t['title'], 'my_order': my_order, 'opp_order': opp_order, 'res': res,
            'log': log, 'faints': faints, 'left': left, 'my_top': [o for _, o in top[:3]]}


def _blind_job(args):
    n, kid, seed = args
    apply_party(load_party(n))
    t = next(t for t in teams() if t['id'] == kid)
    try:
        return blind_game(t, seed)
    except Exception as e:  # keep the other games
        import traceback
        return {'id': kid, 'title': t['title'], 'error': traceback.format_exc()[-800:]}


def blind(n):
    apply_party(load_party(n))
    ts = teams()
    jobs = [(n, t['id'], zlib.crc32(('blind' + t['id']).encode())) for t in ts]
    out_p = os.path.join(OUT_D, f'blind_R{n}.json')
    done = json.load(open(out_p, encoding='utf-8')) if os.path.exists(out_p) else []
    have = {d['id'] for d in done if 'error' not in d}
    done = [d for d in done if d['id'] in have]
    for j in jobs:
        if j[1] in have:
            continue
        t0 = time.time()
        d = _blind_job(j)      # B.select uses all cores itself
        d['seconds'] = round(time.time() - t0, 1)
        done.append(d)
        json.dump(done, open(out_p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(d['title'][:30], d.get('res', d.get('error')), d.get('my_order'), d.get('opp_order'),
              d['seconds'], flush=True)


# ---------------------------------------------------------------- report

def _fmt_party(p):
    ap = lambda a: ' '.join(f"{'HABCDS'[['hp', 'atk', 'def', 'spa', 'spd', 'spe'].index('def' if k == 'defn' else k)]}{v}" for k, v in a.items() if v)
    return [f"| {m['label'][1:] if m['label'][0].isascii() else m['label']} | {m['nature']} {ap(m['ap'])} | {m['item']} | "
            f"{'/'.join(m['moves'])} |" for m in p]


def report():
    ts = {t['id']: t for t in teams()}
    L = ['# 微調整テスト（技・持ち物・能力。種族は固定）', '',
         '各ラウンドで、こちらの60通りの選出すべてを、各構築の想定選出（ラウンド1で固定）すべてと1戦ずつ対戦させた結果です。',
         '両者3手読み・乱数あり。乱数の種はラウンド間で共通なので、差はパーティの違いから来ています。',
         '「最悪」「平均」は各構築に対する最善の選出（最も負けやすい相手選出への勝率で順位付け）の値です。', '']
    sums = {}
    for n in (1, 2, 3, 4):
        p = os.path.join(PARTY_D, f'R{n}.json')
        if not os.path.exists(p):
            continue
        sums[n] = summary(n)
        L += [f'## R{n} のパーティ', '', '| 個体 | 性格・能力P | 持ち物 | 技 |', '|---|---|---|---|']
        L += _fmt_party(json.load(open(p, encoding='utf-8')))
        nt = os.path.join(OUT_D, f'R{n}_notes.md')
        if os.path.exists(nt):
            L += ['', open(nt, encoding='utf-8').read().strip()]
        L.append('')
    done = [n for n in sums if sums[n]]
    if done:
        L += ['## ラウンド比較（全構築の平均）', '', '| ラウンド | 構築数 | 最善選出の最悪 | 最善選出の平均 | 全選出平均 | 上位5選出平均 |',
              '|---|---|---|---|---|---|']
        for n in done:
            s = sums[n]
            L.append(f"| R{n} | {s['teams']} | {s['worst']:.0%} | {s['avg']:.0%} | {s['all']:.0%} | {s['top5']:.0%} |")
        L += ['', '## 構築ごと（最善選出の最悪 / 平均 / 全選出平均）', '',
              '| 構築 | ' + ' | '.join(f'R{n}' for n in done) + ' |', '|---|' + '---|' * len(done)]
        for kid in ts:
            cells = []
            for n in done:
                s = sums[n]['per'].get(kid)
                cells.append(f"{s['best'][0]:.0%} / {s['best'][1]:.0%} / {s['all']:.0%}<br>{' → '.join(s['best'][3])}"
                             if s else '-')
            if any(c != '-' for c in cells):
                L.append(f"| {ts[kid]['title'][:28]} | " + ' | '.join(cells) + ' |')
        L.append('')
    fn = os.path.join(OUT_D, 'final_notes.md')
    if os.path.exists(fn):
        L += [open(fn, encoding='utf-8').read().strip(), '']
    for n in (4, 3, 2, 1):
        bp = os.path.join(OUT_D, f'blind_R{n}.json')
        if not os.path.exists(bp):
            continue
        bl = json.load(open(bp, encoding='utf-8'))
        ok = [d for d in bl if 'res' in d]
        L += [f'## ブラインドテスト（パーティ R{n}・こちら4手読み・相手3手読み・各1戦）', '',
              '選出画面で互いに6体の種族だけを見て選出し、対戦中も相手の型は使用率データと見えた技からの推測で読みます。',
              f"結果: {sum(d['res'] == 1 for d in ok)}勝{sum(d['res'] != 1 for d in ok)}敗", '',
              '| 構築 | こちらの選出 | 相手の選出 | 結果 | 倒れた順 |', '|---|---|---|---|---|']
        for d in bl:
            if 'res' not in d:
                L.append(f"| {d['title'][:28]} | エラー | | | |")
                continue
            fa = '、'.join(f"{tn}T{'自' if i == 0 else '相'}{nm}" for tn, i, nm in d['faints'])
            L.append(f"| {d['title'][:28]} | {' → '.join(d['my_order'])} | {' → '.join(d['opp_order'])} | "
                     f"{'勝ち' if d['res'] == 1 else '負け'} | {fa} |")
        L.append('')
        break
    open(REPORT_P, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('→', os.path.normpath(REPORT_P))


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv[1:]
    if '--round' in a:
        run_round(int(a[a.index('--round') + 1]), a[a.index('--team') + 1] if '--team' in a else None)
        analyze(int(a[a.index('--round') + 1]), quiet=True)
        report()
    elif '--screen' in a:
        screen(int(a[a.index('--screen') + 1]), a[a.index('--screen') + 2])
    elif '--analyze' in a:
        analyze(int(a[a.index('--analyze') + 1]))
    elif '--blind' in a:
        blind(int(a[a.index('--blind') + 1]))
        report()
    else:
        report()


if __name__ == '__main__':
    main()
