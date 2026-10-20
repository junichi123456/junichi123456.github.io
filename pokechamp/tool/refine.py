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
    ctrl = {(lambda x: (x[0], tuple(x[1]), tuple(x[2])))(json.loads(k)): v for k, v in done.pop('_control', {}).items()}

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


# ---------------------------------------------------------------- why we lose

def losses(n):
    """What the lost games have in common: which of their mons and moves show up in losses far more than in wins,
    which of ours go down first, and per team the selection of theirs that beats our best orders and how."""
    R = load_round(n)
    ts = {t['id']: t for t in teams()}
    W, Lz = [], []
    for kid, games in R.items():
        st = team_stats(games)
        top = {r[3] for r in st['rows'][:10]}     # the orders we would actually bring
        for g in games:
            if tuple(g['order']) in top:
                (W if g['res'] == 1 else Lz).append((kid, g))

    def cnt(gs, f):
        c = {}
        for kid, g in gs:
            for k in set(f(kid, g)):
                c[k] = c.get(k, 0) + 1
        return c

    def lift(f, minn=8):
        a, b = cnt(Lz, f), cnt(W, f)
        rows = []
        for k in set(a) | set(b):
            la, wb = a.get(k, 0), b.get(k, 0)
            if la + wb >= minn:
                rows.append(((la / max(1, len(Lz))) / ((wb + 1) / max(1, len(W))), k, la, wb))
        return sorted(rows, reverse=True)

    opp_mon = lift(lambda kid, g: [B._base(x) for x in g['opp']])
    opp_move = lift(lambda kid, g: [f"{B._base(op)}:{b}" for me, a, op, b in g['log'] if not b.startswith('→') and b not in ('-', '反動')])
    my_move = lift(lambda kid, g: [f"{B._base(me)}:{a}" for me, a, op, b in g['log'] if not a.startswith('→') and a not in ('-', '反動')])
    killers = cnt(Lz, lambda kid, g: [f"{B._base(by)}→{B._base(nm)}" for tn, i, nm, by in g['faints'] if i == 0])
    first_down = cnt(Lz, lambda kid, g: [B._base(next((nm for tn, i, nm, by in g['faints'] if i == 0), '-'))])
    sweep = cnt(Lz, lambda kid, g: (lambda ks: [B._base(max(ks, key=ks.count))] if ks and ks.count(max(ks, key=ks.count)) >= 2 else [])(
        [B._base(by) for tn, i, nm, by in g['faints'] if i == 0]))
    turns_l = sum(len(g['log']) for _, g in Lz) / max(1, len(Lz))
    turns_w = sum(len(g['log']) for _, g in W) / max(1, len(W))
    left = sum(g['left'][1] for _, g in Lz) / max(1, len(Lz))
    close = sum(1 for _, g in Lz if g['left'][1] <= 0.6) / max(1, len(Lz))
    L = [f'# 勝てない要因の分析（R{n}・各構築の上位10選出の対戦 {len(W) + len(Lz)} 戦: {len(W)}勝 {len(Lz)}敗）', '',
         '「負け率比」は、その要素が負け試合に現れる割合 ÷ 勝ち試合に現れる割合（1より大きいほど負けにつながる）。', '',
         f'- 試合の長さ: 負け {turns_l:.1f} ターン / 勝ち {turns_w:.1f} ターン',
         f'- 負けたとき相手に残っていた体力（3体合計、1体=1.0）: 平均 {left:.2f}。僅差（0.6以下）の負け {close:.0%}', '',
         '## 負けにつながる相手のポケモン', '', '| 相手 | 負け率比 | 負け試合に出た数 | 勝ち試合に出た数 |', '|---|---|---|---|']
    L += [f'| {k} | {r:.2f} | {a} | {b} |' for r, k, a, b in opp_mon[:12]]
    L += ['', '## 負けにつながる相手の技', '', '| 相手:技 | 負け率比 | 負け | 勝ち |', '|---|---|---|---|']
    L += [f'| {k} | {r:.2f} | {a} | {b} |' for r, k, a, b in opp_move[:20]]
    L += ['', '## 負け試合でこちらを倒した組み合わせ（相手→こちら）', '', '| 組み合わせ | 回数 |', '|---|---|']
    L += [f'| {k} | {v} |' for k, v in sorted(killers.items(), key=lambda x: -x[1])[:15]]
    L += ['', '## 負け試合で1体で2体以上を倒した相手（全抜き・半壊の起点）', '', '| 相手 | 回数 |', '|---|---|']
    L += [f'| {k} | {v} |' for k, v in sorted(sweep.items(), key=lambda x: -x[1])[:10]]
    L += ['', '## 負け試合で最初に倒れたこちらのポケモン', '', '| こちら | 回数 |', '|---|---|']
    L += [f'| {k} | {v} |' for k, v in sorted(first_down.items(), key=lambda x: -x[1])]
    L += ['', '## 負けにつながるこちらの技（使った試合で負けが多い）', '', '| こちら:技 | 負け率比 | 負け | 勝ち |', '|---|---|---|---|']
    L += [f'| {k} | {r:.2f} | {a} | {b} |' for r, k, a, b in my_move[:12]]
    L += ['', '## 構築ごと: 最善選出を負かした相手選出と負け方', '']
    for kid, games in R.items():
        st = team_stats(games)
        w, a, f, o, wo = st['best']
        lost = [g for g in games if tuple(g['order']) in {r[3] for r in st['rows'][:5]} and g['res'] != 1]
        bysel = {}
        for g in lost:
            bysel.setdefault(tuple(g['opp']), []).append(g)
        if not bysel:
            continue
        L.append(f"### {ts[kid]['title'][:40]}（最善: {' → '.join(o)}・上位5選出の負け {len(lost)}）")
        for sel, gs in sorted(bysel.items(), key=lambda x: -len(x[1]))[:2]:
            g = gs[0]
            fa = '、'.join(f"{tn}T {'自' if i == 0 else '相'}{nm}（{by}）" for tn, i, nm, by in g['faints'])
            seq = ' / '.join(f"{a}↔{b}" for me, a, op, b in g['log'][:4])
            L.append(f"- 相手 {' → '.join(sel)}: {len(gs)}敗。例（{' → '.join(g['order'])}）: 倒れた順 {fa}。序盤 {seq}")
        L.append('')
    txt = '\n'.join(L) + '\n'
    open(os.path.join(OUT_D, f'LOSSES_R{n}.md'), 'w', encoding='utf-8').write(txt)
    print(txt)


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


def load_tag(tag):
    return load_party(int(tag[1:])) if tag[0] == 'R' and tag[1:].isdigit() else \
        json.load(open(os.path.join(PARTY_D, f'{tag}.json'), encoding='utf-8'))


def worst_selection(n):
    """Per team: the selection of theirs (with its lead) that does best against the orders we would bring
    (our best 10 orders of round n): they see our six and bring what is hardest for us."""
    out = {}
    for kid, games in load_round(n).items():
        top = {r[3] for r in team_stats(games)['rows'][:10]}
        sc = {}
        for g in games:
            d = sc.setdefault(tuple(g['opp']), [0, 0, 0, 0])
            if tuple(g['order']) in top:
                d[0] += g['res'] == 1
                d[1] += 1
            d[2] += g['res'] == 1
            d[3] += 1
        oo = min(sc, key=lambda k: (sc[k][0] / max(1, sc[k][1]), sc[k][2] / sc[k][3]))
        out[kid] = {'opp': list(oo), 'top10': round(sc[oo][0] / max(1, sc[oo][1]), 3), 'all': round(sc[oo][2] / sc[oo][3], 3)}
    return out


def blind_select(t, order_filter=None):
    """Our order from their six species only: not their own article (usage data, other articles and our logs)."""
    import sets as _sets
    _sets.EXCLUDE = {t['id']}
    B._OPP_CACHE.clear()
    opp6 = [B._base(m['name']) for m in t['team']]
    real_match = B.match_known
    B.match_known = lambda *a, **k: None
    try:
        B.set_known_context(None)
        best, top, _ = B.select(opp6, ignore_stored=True, order_filter=order_filter)
    finally:
        B.match_known = real_match
    return best, [o for _, o in top[:3]]


def _trace_move(turn, my_nm, foe_nm, mid, elog):
    """[turn, our mon, move (ja), target, result] from the engine's per-turn text log (spec 5.4)."""
    md = E.MOVES.get(mid)
    ja = md.ja if md else mid
    uses = f'{my_nm} uses {mid}'
    idx = [i for i, l in enumerate(elog) if l == uses]
    tgt = foe_nm
    if not idx:
        return [turn, my_nm, ja, tgt, 'none']
    for l in elog[:idx[0]]:
        if l.startswith('switch 1 '):
            tgt = l[len('switch 1 '):]
    if len(idx) > 1:
        return [turn, my_nm, ja, tgt, 'unknown']
    end = len(elog)
    for i in range(idx[0] + 1, len(elog)):
        if ' uses ' in elog[i]:
            end = i
            break
    seg = elog[idx[0] + 1:end]
    if any(l.startswith(f'{mid} missed') for l in seg):
        r = 'miss'
    elif any(l.endswith((' protected', ' guarded')) for l in seg):
        r = 'protect'
    elif any(l.endswith(' immune') for l in seg):
        r = 'immune'
    else:
        r = 'hit'
    return [turn, my_nm, ja, tgt, r]


def blind_play(args):
    """One game: true sets on both sides; each side reads ahead on its own guess of the other's sets (usage data
    and the moves seen so far). We read my_depth turns ahead, they read opp_depth."""
    party, kid, my_order, opp_order, seed, my_depth, opp_depth = args[:7]
    know = len(args) > 7 and args[7]          # True: we read on their true sets (perfect information for us)
    rules = args[8] if len(args) > 8 else None   # None: no action rules; else a tuple of policy rule ids (policy.py)
    trace = len(args) > 9 and args[9]         # True: also return 'mv', one record per move of ours (no effect on the game)
    import sets as _sets
    _sets.EXCLUDE = {kid}                      # the opponent's own article never feeds the guesses about it
    apply_party(party)
    real_match = B.match_known
    try:
        _ctx(kid)
        st = B.engine_game(my_order, opp_order)
        B.match_known = lambda *a, **k: None
        B.set_known_context(None)
        B._OPP_CACHE.clear()
        t_opp = _templates(opp_order, B.opp_sets, 1)
        B._OPP_CACHE.clear()
        t_me = _templates(my_order, B.opp_sets, 0)
        B.match_known = real_match
        B._KNOWN_CTX['team'] = None
        _ctx(kid)
        seen = [{}, {}]
        rng = prep.RandomRNG(seed)
        log, faints, mv = [], [], []
        rocks_turn, tox, fired = None, [], []
        if rules is not None:
            import policy
            ctx = policy.Ctx([m.name for m in st.sides[1].mons], rules)
            chooser = policy.make_chooser(ctx)
        else:
            ctx, chooser = None, S.chooser
        for tn in range(30):
            if st.winner is not None:
                break
            if ctx is None:
                a0 = S.lookahead_action(st if know else belief(st, 1, t_opp, seen[1]), 0, my_depth)
            else:
                bst = st if know else belief(st, 1, t_opp, seen[1])
                a0, _rid = policy.choose(st, bst, policy.ranked_root(bst, my_depth), ctx)
            a1 = S.lookahead_action(belief(st, 0, t_me, seen[0]), 1, opp_depth)
            log.append((st.active(0).name, _name(st, 0, a0), st.active(1).name, _name(st, 1, a1)))
            for i, a in ((0, a0), (1, a1)):
                if a and a[0] == 'm' and a[1] != 'recharge':
                    lst = seen[i].setdefault(st.sides[i].act, [])
                    if a[1] not in lst:
                        lst.append(a[1])
            before = [[m.alive for m in s.mons] for s in st.sides]
            fj = st.sides[1].act
            pois = a0 and a0[0] == 'm' and a0[1] == 'toxic' and st.active(0).name == 'ドヒドイデ' and \
                st.sides[1].mons[fj].status == ''
            if trace:
                my_nm, foe_nm = st.active(0).name, st.active(1).name
                elog = []
                st = E.step(st, a0, a1, rng=rng, chooser=chooser, log=elog)
                if a0 and a0[0] == 'm' and a0[1] != 'recharge':
                    mv.append(_trace_move(tn + 1, my_nm, foe_nm, a0[1], elog))
            else:
                st = E.step(st, a0, a1, rng=rng, chooser=chooser)
            if rocks_turn is None and st.sides[1].cond.get('stealthrock'):
                rocks_turn = tn + 1
            if pois and st.sides[1].mons[fj].status in ('psn', 'tox'):
                tox.append(B._base(st.sides[1].mons[fj].name))
            for i in (0, 1):
                for j, m in enumerate(st.sides[i].mons):
                    if before[i][j] and not m.alive:
                        faints.append((tn + 1, i, m.name, log[-1][2 if i == 0 else 0]))
        judged = st.winner is None
        res = st.winner if st.winner is not None else (1 if S.evaluate(st) > 0 else -1)
        left = [[(m.name, round(100 * m.hp / m.maxhp)) for m in s.mons] for s in st.sides]
        return {'res': res, 'log': log, 'faints': faints, 'left': left, 'fired': list(ctx.fired) if ctx else [],
                'rocks_turn': rocks_turn, 'tox': tox, 'turns': len(log), 'judged': judged,
                **({'mv': mv} if trace else {})}
    except Exception:
        import traceback
        return {'res': None, 'error': traceback.format_exc()[-800:]}
    finally:
        B.match_known = real_match


def blind(tag, games=3, worst_from=3, my_depth=4, opp_depth=3):
    """Blind test of party `tag` against every team's worst selection (from round worst_from), `games` games each."""
    party = load_tag(tag)
    apply_party(party)
    ts = teams()
    ws = worst_selection(worst_from)
    out_p = os.path.join(OUT_D, f'blind_{tag}.json')
    done = json.load(open(out_p, encoding='utf-8')) if os.path.exists(out_p) else {}
    if done.get('sig') != sig(party):
        done = {'sig': sig(party), 'teams': {}}
    t0 = time.time()
    jobs, meta = [], []
    for t in ts:
        d = done['teams'].get(t['id'])
        if d:
            d['games'] = [g for g in d['games'] if g.get('res') is not None]
        have = len(d['games']) if d else 0
        if have >= games:
            continue
        if d:
            mo = d['my_order']
        else:
            mo, top = blind_select(t)
            done['teams'][t['id']] = {'title': t['title'], 'my_order': mo, 'my_top': top,
                                      'opp_order': ws[t['id']]['opp'], 'worst_info': ws[t['id']], 'games': []}
        for k in range(have, games):
            jobs.append((party, t['id'], mo, done['teams'][t['id']]['opp_order'], zlib.crc32(f'blind{t["id"]}{k}'.encode()),
                         my_depth, opp_depth))
            meta.append(t['id'])
    print(f'blind {tag}: {len(jobs)} games (selection {round(time.time() - t0)}s)', flush=True)
    res = prep.pool_map(blind_play, jobs) if jobs else []
    for kid, r in zip(meta, res):
        done['teams'][kid]['games'].append(r)
    json.dump(done, open(out_p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    gs = [g for d in done['teams'].values() for g in d['games'] if g.get('res') is not None]
    w = sum(g['res'] == 1 for g in gs)
    print(f'blind {tag}: {w}/{len(gs)} = {w / max(1, len(gs)):.1%}  ({round(time.time() - t0)}s)', flush=True)
    for kid, d in done['teams'].items():
        print(f"  {d['title'][:26]}: {' → '.join(d['my_order'])} vs {' → '.join(d['opp_order'])}: "
              f"{''.join('○' if g.get('res') == 1 else '×' if g.get('res') is not None else '!' for g in d['games'])}",
              flush=True)
    return done


def sheet(pairs, games=6, depth=3, tag='R3'):
    """For each (team id, their selection): all 60 orders of ours x `games` games (their true sets, both sides
    `depth` turns ahead) -> wins per order and how the best order wins (first turns, faint order)."""
    party = load_tag(tag)
    apply_party(party)
    teams()
    out_p = os.path.join(OUT_D, 'sheet.json')
    done = json.load(open(out_p, encoding='utf-8')) if os.path.exists(out_p) else {}
    for kid, oo in pairs:
        key = kid + '|' + '→'.join(oo)
        if key in done:
            continue
        jobs, meta = [], []
        for o in prep.all_orders():
            for i in range(games):
                jobs.append((o, oo, kid, zlib.crc32(f'sheet{o}{oo}{i}'.encode()), depth))
                meta.append(tuple(o))
        t0 = time.time()
        res = prep.pool_map(game, jobs)
        per = {}
        for o, r in zip(meta, res):
            per.setdefault(' → '.join(o), []).append({'res': r[0], 'log': r[1][:4], 'faints': r[2]})
        done[key] = per
        json.dump(done, open(out_p, 'w', encoding='utf-8'), ensure_ascii=False)
        best = sorted(per.items(), key=lambda x: -sum(g['res'] == 1 for g in x[1]))[:3]
        print(key, round(time.time() - t0), [(o, sum(g['res'] == 1 for g in gs)) for o, gs in best], flush=True)
    return done


def depth_study(tag='R3', kids=None, depths=(2, 3, 5, 6), games=6):
    """How deep must we read to win the hardest pairings? Same blind setting (their worst selection, our order
    from the blind test, they read 3 turns ahead), our depth varied; plus depth 4 on their true sets."""
    party = load_tag(tag)
    apply_party(party)
    teams()
    bl = json.load(open(os.path.join(OUT_D, f'blind_{tag}.json'), encoding='utf-8'))['teams']
    kids = kids or sorted(bl, key=lambda k: sum(g['res'] == 1 for g in bl[k]['games']))[:4]
    out_p = os.path.join(OUT_D, f'depth_{tag}.json')
    done = json.load(open(out_p, encoding='utf-8')) if os.path.exists(out_p) else {}
    done['4'] = {k: [g['res'] for g in bl[k]['games'][:games]] for k in kids}
    for cfg in [str(d) for d in depths] + ['4k']:
        if cfg in done and all(len(done[cfg].get(k, [])) >= games for k in kids):
            continue
        d, know = int(cfg[0]), cfg.endswith('k')
        jobs, meta = [], []
        for k in kids:
            for i in range(games):
                jobs.append((party, k, bl[k]['my_order'], bl[k]['opp_order'], zlib.crc32(f'blind{k}{i}'.encode()), d, 3, know))
                meta.append(k)
        t0 = time.time()
        res = prep.pool_map(blind_play, jobs)
        done[cfg] = {}
        for k, r in zip(meta, res):
            done[cfg].setdefault(k, []).append(r.get('res'))
        json.dump(done, open(out_p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        w = sum(x == 1 for v in done[cfg].values() for x in v)
        print(f'depth {cfg}: {w}/{len(jobs)}  ({round(time.time() - t0)}s)  ' +
              '  '.join(f"{bl[k]['title'][:10]} {sum(x == 1 for x in done[cfg][k])}" for k in kids), flush=True)
    return done


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
    import glob
    for bp in sorted(glob.glob(os.path.join(OUT_D, 'blind_*.json')), key=os.path.getmtime):
        d = json.load(open(bp, encoding='utf-8'))
        if 'teams' not in d:
            continue
        tag = os.path.basename(bp)[6:-5]
        gs = [g for x in d['teams'].values() for g in x['games'] if g.get('res') is not None]
        first = [x['games'][0] for x in d['teams'].values() if x['games'] and x['games'][0].get('res') is not None]
        w = sum(g['res'] == 1 for g in gs)
        L += [f'## ブラインドテスト: パーティ {tag}（相手は最悪選出・こちら4手読み・相手3手読み）', '',
              '互いに6体の種族だけを見て選出（こちらは記事の型を使わない）。相手はこちらに最も厳しい選出を必ず持ってくる前提。'
              '対戦中も相手の型は使用率データと見えた技からの推測で読む。',
              f"- 最悪選出への勝率: **{w}/{len(gs)} = {w / max(1, len(gs)):.0%}**（各構築1戦目のみ: "
              f"{sum(g['res'] == 1 for g in first)}/{len(first)}）", '',
              '| 構築 | こちらの選出 | 相手の最悪選出 | 結果 |', '|---|---|---|---|']
        for x in d['teams'].values():
            r = ''.join('○' if g.get('res') == 1 else '×' if g.get('res') is not None else '!' for g in x['games'])
            L.append(f"| {x['title'][:28]} | {' → '.join(x['my_order'])} | {' → '.join(x['opp_order'])} | {r} |")
        L.append('')
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
    elif '--depth-study' in a:
        depth_study(a[a.index('--depth-study') + 1])
    elif '--losses' in a:
        losses(int(a[a.index('--losses') + 1]))
    elif '--analyze' in a:
        analyze(int(a[a.index('--analyze') + 1]))
    elif '--blind' in a:
        blind(a[a.index('--blind') + 1], games=int(a[a.index('--games') + 1]) if '--games' in a else 3,
              worst_from=int(a[a.index('--worst-from') + 1]) if '--worst-from' in a else 3)
    else:
        report()


if __name__ == '__main__':
    main()
