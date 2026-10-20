"""Cores (axes) study for party R9: selection rules S1-S3, action rules, blind test with rules on / off.
Spec: pokechamp/specs/SPEC_CORES.md.   Run in this folder:

  python3 core_test.py cores                  recompute which teams belong to each core (check against spec 2.3)
  python3 core_test.py plan [--force]         selections (on/off) and their selections for the 20 teams -> saved
  python3 core_test.py check-select           S1-S3 on all known teams (violations / relaxations)
  python3 core_test.py selftest               position tests for every action rule
  python3 core_test.py one <team_id> [--mode on|off] [--k 0] [--depth 5]     one game, printed, not saved
  python3 core_test.py run [--mode on|off|both] [--core C1,C5] [--teams id,..] [--games 5] [--depth 5]
                           [--procs N] [--max-games N] [--rules R1,T1 | -M1] [--force]
  python3 core_test.py report [--out path]    logs/CORES_R9.md from whatever is saved so far

R10 adjustment (spec SPEC_ADJUST.md; results logs/refine/adjust_R10.json):
  check-diff | adjust-plan [--force] | replay [--procs N --max-games N --no-control]
  deep [--depth 6 --games 5 --procs N --max-games N] | adjust-report [--out path] | adjust-selftest

Results: logs/refine/cores_R9.json (one write per finished game; run again to resume).
"""
import argparse, datetime, json, os, sys, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle as B  # noqa: E402
import engine as E  # noqa: E402
import refine  # noqa: E402
import policy  # noqa: E402
import prep  # noqa: E402
import safeio  # noqa: E402
import search as S  # noqa: E402
import dex  # noqa: E402

RESULT_P = os.path.join(HERE, '..', 'logs', 'refine', 'cores_R9.json')
REPORT_P = os.path.join(HERE, '..', 'logs', 'CORES_R9.md')
PARTY_N = 9
OPP_DEPTH = 3
NGAMES = 5

# members: (base name, must be the mega slot, required text in the team's name or None)
CORES = [
    {'id': 'C1', 'name': 'カバルドン+メガグソクムシャ', 'members': [('カバルドン', False), ('グソクムシャ', True)],
     'star': ['96073793', '8cfae507'], 'shared': [],
     'expect': ['96073793', '8cfae507', 'e74e0684', '8500a7c9', '56d52ca0']},
    {'id': 'C2', 'name': 'ガブリアス+メガフラエッテ（ガブエッテ）', 'members': [('ガブリアス', False), ('フラエッテ', True)],
     'star': ['2ab0e9d6', 'd19098fc'], 'shared': [],
     'expect': ['c0ae6e25', '1d079d01', 'd19098fc', '8a9518d2', 'de88d715', '2ab0e9d6']},
    {'id': 'C3', 'name': 'イエッサン+メガカメックス', 'members': [('イエッサン', False), ('カメックス', True)],
     'star': ['1e1ecbc7', 'b45a825c'], 'shared': [], 'expect': ['1e1ecbc7', 'b45a825c']},
    {'id': 'C4', 'name': 'パーモット+イダイトウ', 'members': [('パーモット', False), ('イダイトウ', False)],
     'star': ['bab22dcc', '856f9d20'], 'shared': [], 'expect': ['bab22dcc', '856f9d20', '108328e9']},
    {'id': 'C5', 'name': 'カバルドン+メガボーマンダ（カバマンダ）', 'members': [('カバルドン', False), ('ボーマンダ', True)],
     'star': ['8bee97d2', 'b8201cf9'], 'shared': ['96073793'],
     'expect': ['8bee97d2', '96073793', 'b8201cf9', '047f48a2', 'c5acded7', '466e7e1c', 'db0f3582']},
    {'id': 'C6', 'name': 'メガルカリオZ+ブリジュラス', 'members': [('ルカリオ', True), ('ブリジュラス', False)],
     'star': ['1acfca2d'], 'shared': ['8bee97d2', '6abd49d9'],
     'expect': ['8bee97d2', '6abd49d9', '1acfca2d', 'de88d715', '6e1e5745', 'yakkun_n8943']},
    {'id': 'C7', 'name': 'メガルカリオZ+カイリュー', 'members': [('ルカリオ', True), ('カイリュー', False)],
     'star': ['705822f2'], 'shared': [], 'expect': ['1036c00c', '705822f2', 'yakkun_n8938']},
    {'id': 'C8', 'name': 'メガリザードンX+ミミッキュ', 'members': [('リザードン', True, 'X'), ('ミミッキュ', False)],
     'star': ['db0baa28', 'a99ce37e'], 'shared': ['856f9d20'],
     'expect': ['db0baa28', 'hatena_oma_204318', 'a99ce37e', '856f9d20', 'yakkun_n8943']},
    {'id': 'C9', 'name': 'メガライチュウY+アシレーヌ', 'members': [('ライチュウ', True), ('アシレーヌ', False)],
     'star': ['d41ee42d', '9734da0a'], 'shared': [],
     'expect': ['1fdf7ff8', '8e9ebc27', '9734da0a', '3ed25308', '7dbcab8f', 'd41ee42d', '63d678f5']},
    {'id': 'C10', 'name': 'メガガブリアスZ 軸', 'members': [('ガブリアス', True)],
     'star': ['9441b10f', '78bbac0b'], 'shared': ['96073793', 'a99ce37e', 'd41ee42d'],
     'expect': ['96073793', 'ed829abc', 'a99ce37e', '815520d5', 'e457dcd2', '9441b10f', '3c6dac7a', '78bbac0b',
                '45330f7f', '8e9ebc27', 'af321b9f', 'd41ee42d']},
    {'id': 'C11', 'name': '鋼・受け（エアームド＋鋼／毒）', 'members': [('エアームド', False)], 'fn': 'steel',
     'star': ['d858baf8', '6abd49d9'], 'shared': [], 'expect': ['d858baf8', '6abd49d9']},
]
EVAL_IDS = ('96073793b397a61e, 8cfae5073138dec9, 2ab0e9d6c4021c97, d19098fcd8ccb498, 1e1ecbc7b6d2bad7, '
            'b45a825c55b8b4b4, bab22dcc629688e8, 856f9d20f6a9b5a9, 8bee97d26f9a0954, b8201cf9aee11893, '
            '1acfca2d8341d6c0, 705822f24b8d974e, db0baa2843d2bd4b, a99ce37e900abf25, d41ee42d123f67e3, '
            '9734da0a26ac5b50, 9441b10f81378ec0, 78bbac0b9f5c174f, d858baf8612ab064, 6abd49d970032380').split(', ')
ASHI_EVAL = ['96073793', '1e1ecbc7', 'b8201cf9', '1acfca2d', 'db0baa28', 'a99ce37e', 'd41ee42d', '9734da0a']


# ---------------------------------------------------------------- R9 loading (spec 1.1)

def _init_r9():
    """Idempotent: put R9 into battle.py without touching team.py. Must run before the pool forks."""
    return _init_party('R9')


def _team(kid):
    return next(t for t in B.KNOWN_TEAMS if t['id'] == kid)


def _full(prefix):
    return next(t['id'] for t in B.KNOWN_TEAMS if t['id'].startswith(prefix))


# ---------------------------------------------------------------- cores

def _mega_slot(m):
    it = m.get('item') or ''
    return m['name'].startswith('メガ') or it.endswith(('ナイト', 'ナイトX', 'ナイトY', 'ナイトZ'))


def _types_of(m, base_only=False):
    nm = m['name']
    if base_only:
        s = dex.SPECIES.get(B._base(nm))
        return {x.lower() for x in s['types']} if s else set()
    cands = [nm, nm.replace('X', 'Ｘ').replace('Y', 'Ｙ').replace('Z', 'Ｚ')]
    if _mega_slot(m) and not nm.startswith('メガ'):
        cands.insert(0, 'メガ' + nm)
    for c in cands:
        s = dex.SPECIES.get(c)
        if s:
            return {x.lower() for x in s['types']}
    s = dex.SPECIES.get(B._base(nm))
    return {x.lower() for x in s['types']} if s else set()


def in_core(core, t):
    team = t['team']
    for mem in core['members']:
        nm, need_mega = mem[0], mem[1]
        ok = False
        for m in team:
            if B._base(m['name']) != nm:
                continue
            if need_mega and not _mega_slot(m):
                continue
            if len(mem) > 2 and mem[2] not in m['name'] and mem[2] not in (m.get('item') or ''):
                continue
            ok = True
            break
        if not ok:
            return False
    if core.get('fn') == 'steel':
        n = sum(1 for m in team if _types_of(m, True) & {'poison', 'steel'})
        return n >= 3
    return True


def core_teams(core):
    return [t for t in B.KNOWN_TEAMS if in_core(core, t)]


def cmd_cores(a):
    _init_r9()
    allok = True
    for c in CORES:
        got = [t['id'] for t in core_teams(c)]
        exp = [_full(p) if not p.startswith(('yakkun', 'hatena')) else p for p in c['expect']]
        ok = set(got) == set(exp)
        allok &= ok
        print(f"{c['id']} {c['name']}: {len(got)} 構築 {'一致' if ok else '不一致'}")
        for t in core_teams(c):
            mark = '★' if any(t['id'].startswith(p) for p in c['star']) else ('共有' if any(t['id'].startswith(p) for p in c['shared']) else '')
            print(f"    {t['id'][:8]:<9}{mark:<3}{t['title'][:50]}")
        if not ok:
            print('    不足:', [e[:8] for e in exp if e not in got], ' 余分:', [g[:8] for g in got if g not in exp])
    print('全体:', '一致' if allok else '不一致あり')


def cores_of(kid):
    t = _team(kid)
    return [c['id'] for c in CORES if in_core(c, t)]


def primary_core(kid):
    for c in CORES:
        if any(kid.startswith(p) for p in c['star']):
            return c
    return None


# ---------------------------------------------------------------- plan (selections and their selections)

def opp_selection(kid):
    """Their three (lead first) that contains the whole core (spec 2.4)."""
    t = _team(kid)
    opp6 = [B._base(m['name']) for m in t['team']]
    core = primary_core(kid)
    mem = [m[0] for m in core['members']]
    trips = prep.opp_trips(t, opp6)
    best = None
    for p, orders in trips:
        if all(x in orders[0] for x in mem) and (best is None or p > best[0]):
            best = (p, orders[0])
    if best:
        return list(best[1])
    w = B.opp_pick_weights(opp6, list(B.MY.values()))
    rest = sorted((x for x in opp6 if x not in mem), key=lambda x: -w[x])
    trio = mem + rest[:3 - len(mem)]
    lead = max(trio, key=lambda x: B.lead_rate(B._base(x)))
    return [lead] + [x for x in trio if x != lead]


def make_plan(kid):
    t = _team(kid)
    opp6 = [B._base(m['name']) for m in t['team']]
    opp = opp_selection(kid)                       # before blind_select (it changes sets.EXCLUDE)
    off_best, off_top = refine.blind_select(t)
    filt = policy.select_filter(opp6)
    on_best, on_top = refine.blind_select(t, order_filter=filt)
    relaxed = []
    if not filt(on_best):
        orders = [[x] + [y for y in m3 if y != x] for m3 in __import__('itertools').combinations(
            [B.BASE_OF.get(m.species, m.species) for m in B.TEAM], 3) for x in m3]
        f2, relaxed = policy.relaxed_filter(opp6, orders)
        on_best, on_top = refine.blind_select(t, order_filter=f2)
    return {'title': t['title'], 'cores': cores_of(kid), 'opp_order': opp,
            'on': {'my_order': on_best, 'my_top': on_top, 'relaxed': relaxed},
            'off': {'my_order': off_best, 'my_top': off_top}}


# ---------------------------------------------------------------- result file

def new_data(party):
    return {'sig': refine.sig(party), 'policy_version': policy.POLICY_VERSION, 'depth': [5, OPP_DEPTH],
            'plan': {}, 'games': {}}


def load_data(party, depth=5, force=False):
    p = RESULT_P
    if os.path.exists(p):
        d = json.load(open(p, encoding='utf-8'))
        bad = d.get('sig') != refine.sig(party) or d.get('policy_version') != policy.POLICY_VERSION or \
            d.get('depth') != [depth, OPP_DEPTH]
        if not bad:
            return d
        if not force:
            raise SystemExit(f'{p}: sig / policy_version / depth が違います（--force で退避して新しく始める）')
        os.replace(p, p.replace('.json', '.' + datetime.datetime.now().strftime('%Y%m%d%H%M%S') + '.json'))
    d = new_data(party)
    d['depth'] = [depth, OPP_DEPTH]
    return d


def save(d):
    os.makedirs(os.path.dirname(RESULT_P), exist_ok=True)
    safeio.write_json(RESULT_P, d)


def ensure_plan(d, kids, force=False):
    todo = [k for k in kids if force or k not in d['plan']]
    for k in todo:
        t0 = time.time()
        d['plan'][k] = make_plan(k)
        save(d)
        pl = d['plan'][k]
        print(f"plan {k[:8]} {pl['title'][:30]}: 相手{pl['opp_order']} on{pl['on']['my_order']}"
              f"{' 緩和' + str(pl['on']['relaxed']) if pl['on']['relaxed'] else ''} off{pl['off']['my_order']} "
              f"({time.time() - t0:.0f}s)", flush=True)


def cmd_plan(a):
    party = _init_r9()
    d = load_data(party, force=a.force)
    if a.force:
        d['plan'] = {}
    ensure_plan(d, EVAL_IDS, force=False)
    print(f"plan: {len(d['plan'])} 構築を {os.path.abspath(RESULT_P)} に保存")


# ---------------------------------------------------------------- check-select

def cmd_check_select(a):
    _init_r9()
    viol = relax_n = ashi_n = ashi_in = 0
    t0 = time.time()
    orders_all = [[x] + [y for y in m3 if y != x] for m3 in __import__('itertools').combinations(
        [B.BASE_OF.get(m.species, m.species) for m in B.TEAM], 3) for x in m3]
    for n, t in enumerate(list(B.KNOWN_TEAMS)):
        opp6 = [B._base(m['name']) for m in t['team']]
        f = policy.select_filter(opp6)
        relaxed = []
        if not any(f(o) for o in orders_all):
            f, relaxed = policy.relaxed_filter(opp6, orders_all)
            relax_n += 1
        best, _ = refine.blind_select(t, order_filter=f)
        okf = policy.select_filter(opp6)(best)
        ash = 'アシレーヌ' in opp6
        if ash:
            ashi_n += 1
            ashi_in += 'ドヒドイデ' in best
        if not okf:
            viol += 1
        print(f"[{n + 1}/{len(B.KNOWN_TEAMS)}] {t['id'][:8]} {best}{' アシレーヌ' if ash else ''}"
              f"{' 緩和' + str(relaxed) if relaxed else ''}{' 違反' if not okf else ''}", flush=True)
    print(f"違反 {viol} / 緩和 {relax_n} / アシレーヌ入り {ashi_n} 構築でドヒドイデ選出 {ashi_in} "
          f"({time.time() - t0:.0f}s)")
    return viol == 0 and relax_n == 0 and ashi_in == ashi_n


# ---------------------------------------------------------------- games

def rules_for(mode, rules_arg=None):
    """(mode name, selection key, rules tuple or None)."""
    if mode == 'off':
        return 'off', 'off', None
    if mode == 'on':
        if rules_arg:
            if rules_arg.startswith('-'):
                drop = set(rules_arg[1:].split(','))
                return 'on-no' + '+'.join(sorted(drop)), 'on', tuple(r for r in policy.ALL_RULES if r not in drop)
            use = tuple(rules_arg.split(','))
            return 'on-' + '+'.join(use), 'on', use
        return 'on', 'on', policy.ALL_RULES
    raise SystemExit(f'mode {mode}')


def seed_of(kid, k):
    return zlib.crc32(f'core{kid}{k}'.encode())


def _work(job):
    key, party, kid, order, oorder, seed, depth, rules = job
    t0 = time.time()
    try:
        _init_r9()
        r = refine.blind_play((party, kid, order, oorder, seed, depth, OPP_DEPTH, False, rules))
    except Exception:
        import traceback
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    r['seed'] = seed
    r['sec'] = round(time.time() - t0, 1)
    return key, r


def cmd_run(a):
    party = _init_r9()
    d = load_data(party, a.depth, a.force)
    kids = [_full(p) for p in a.teams.split(',')] if a.teams else list(EVAL_IDS)
    if a.core:
        want = set(a.core.split(','))
        kids = [k for k in kids if want & set(cores_of(k))]
    ensure_plan(d, kids)
    modes = ['on', 'off'] if a.mode == 'both' else [a.mode]
    jobs = []
    for m in modes:
        name, selkey, rules = rules_for(m, a.rules)
        for kid in kids:
            pl = d['plan'][kid]
            for k in range(a.games):
                key = f'{kid}|{name}|{k}'
                g = d['games'].get(key)
                if g and g.get('res') is not None:
                    continue
                jobs.append((key, party, kid, pl[selkey]['my_order'], pl['opp_order'], seed_of(kid, k),
                             a.depth, rules))
    done_before = sum(1 for g in d['games'].values() if g.get('res') is not None)
    total_all = done_before + len(jobs)
    if a.max_games:
        jobs = jobs[:a.max_games]
    print(f'実行 {len(jobs)} 戦（済み {done_before} / 全体 {total_all}）procs={a.procs}', flush=True)
    if not jobs:
        return
    import multiprocessing as mp
    ctx = mp.get_context('fork') if hasattr(os, 'fork') else mp.get_context('spawn')
    t0 = time.time()
    n = 0
    with ctx.Pool(min(a.procs, len(jobs))) as pool:
        for key, r in pool.imap_unordered(_work, jobs, chunksize=1):
            d['games'][key] = r
            save(d)
            n += 1
            res = {1: '勝', -1: '負', 0: '分', None: '例外'}.get(r['res'], str(r['res']))
            print(f"[{done_before + n}/{total_all}] {key[:8]}{key[16:]} {res} {r.get('turns', '-')}T "
                  f"{r['sec']}s 経過{(time.time() - t0) / 60:.1f}分", flush=True)
            if r.get('error'):
                print('   error:', r['error'].strip().splitlines()[-1], flush=True)


def cmd_one(a):
    party = _init_r9()
    kid = _full(a.team)
    pl = None
    if os.path.exists(RESULT_P):
        try:
            pl = json.load(open(RESULT_P, encoding='utf-8'))['plan'].get(kid)
        except Exception:
            pl = None
    if pl is None:
        pl = make_plan(kid)
    name, selkey, rules = rules_for(a.mode)
    order, oorder = pl[selkey]['my_order'], pl['opp_order']
    print(f"{pl['title']}\n自分 {order}  相手 {oorder}  mode={name} k={a.k} depth={a.depth}")
    t0 = time.time()
    r = refine.blind_play((party, kid, order, oorder, seed_of(kid, a.k), a.depth, OPP_DEPTH, False, rules))
    if r['res'] is None:
        print(r['error'])
        raise SystemExit(1)
    by_turn = {}
    for f in r['fired']:
        by_turn.setdefault(f[0], []).append(f)
    for i, (m0, a0, m1, a1) in enumerate(r['log'], 1):
        fs = ' '.join(f"[{x[1]}:{x[2]}→{x[3]}]" for x in by_turn.get(i, []))
        print(f"T{i:>2} {m0}:{a0}  vs  {m1}:{a1}  {fs}")
    print(f"結果 {'勝' if r['res'] == 1 else '負'} {r['turns']}T 判定={r['judged']} ステロ={r['rocks_turn']} "
          f"どくどく={r['tox']} 発動={len(r['fired'])} ({time.time() - t0:.0f}s)")


# ---------------------------------------------------------------- selftest (spec A7)

def _foe(species, item='', ab='', nature='まじめ', ap=None, moves=(), mega=False, hp=None, boosts=None):
    m = E.make_mon(species, nature, ap or {}, ab, item, moves, 1, 0)
    if mega and m.mega_form is not None:
        m.form = m.mega_form
        m.ability = m.form.ability
        m.can_mega = False
    if hp is not None:
        m.hp = max(1, int(m.maxhp * hp))
    if boosts:
        m.boosts.update(boosts)
    return m


def _game(my, foe, bench_foes=('ミミッキュ', 'ガブリアス')):
    """State: our order `my`, their active replaced by `foe` (a Mon) + two usage-data bench mons."""
    st = B.engine_game(my, [foe_name(foe)] + list(bench_foes))
    s = st.sides[1]
    foe.side, foe.idx = 1, 0
    s.mons[0] = foe
    s.owned.add(0)
    s.mega_used = False
    return st


def foe_name(m):
    return m.name


def _top(st, first):
    """A ranked list whose top is `first` (so the rule, not the search, is what is tested)."""
    acts = E.actions(st, 0)
    assert first in acts, (first, acts)
    return [(1.0, first)] + [(0.5 - 0.01 * n, a) for n, a in enumerate(x for x in acts if x != first)]


def _run_choose(st, first, rules=None, ctx=None):
    ctx = ctx or policy.Ctx([m.name for m in st.sides[1].mons], rules)
    if first is None:
        first = policy.find(E.actions(st, 0), 'toxic') or E.actions(st, 0)[0]
    a, rid = policy.choose(st, st, _top(st, first), ctx)
    assert a in E.actions(st, 0)
    return a, rid, ctx


def cmd_selftest(a):
    _init_r9()
    ok, bad = 0, []

    def check(name, cond, info=''):
        nonlocal ok
        if cond:
            ok += 1
            print(f'  OK   {name}')
        else:
            bad.append(name)
            print(f'  FAIL {name} {info}')

    def act(st, mid):
        return policy.find(E.actions(st, 0), mid)

    ashi = lambda **k: _foe('アシレーヌ', 'オボンのみ', 'げきりゅう', 'ひかえめ', {'hp': 32, 'def': 12, 'spa': 4, 'spe': 18},
                            ['なみのり', 'ムーンフォース', 'めいそう', 'アンコール'], **k)
    gusoku = lambda **k: _foe('グソクムシャ', 'グソクムシャナイト', 'ききかいひ', 'いじっぱり', {'hp': 23, 'atk': 20, 'spd': 1, 'spe': 22},
                              ['アイアンヘッド', 'ふいうち', 'インファイト', 'つるぎのまい'], **k)
    mimi = lambda **k: _foe('ミミッキュ', 'ゴツゴツメット', 'ばけのかわ', 'いじっぱり', {'hp': 32, 'atk': 32, 'spe': 2},
                            ['じゃれつく', 'かげうち', 'つるぎのまい', 'シャドークロー'], **k)
    gab = lambda **k: _foe('ガブリアス', 'ガブリアスナイトZ', 'ふゆう', 'うっかりや', {'hp': 2, 'spa': 29, 'spd': 3, 'spe': 32},
                           ['りゅうせいぐん', 'かえんほうしゃ', 'りゅうのはどう', 'どくづき'], **k)
    print('1-2 R1')
    st = _game(['カバルドン', 'ドヒドイデ', 'グレンアルマ'], ashi())
    a1, rid, _ = _run_choose(st, act(st, 'earthquake'))
    check('カバルドン vs アシレーヌ → stealthrock (R1)', a1[1] == 'stealthrock' and rid == 'R1', (a1, rid))
    st2 = _game(['カバルドン', 'ドヒドイデ', 'グレンアルマ'], ashi())
    st2.sides[1].cond['stealthrock'] = 1
    a1, rid, _ = _run_choose(st2, act(st2, 'earthquake'))
    check('相手側ステロあり → R1 は発動しない', rid != 'R1' and a1[1] != 'stealthrock', (a1, rid))
    print('3 T1')
    st = _game(['ドヒドイデ', 'カバルドン', 'グレンアルマ'], ashi())
    a1, rid, _ = _run_choose(st, act(st, 'recover'))
    check('ドヒドイデ vs アシレーヌ → toxic (T1)', a1[1] == 'toxic' and rid == 'T1', (a1, rid))
    st.sides[1].mons[0].status = 'tox'
    a1, rid, _ = _run_choose(st, act(st, 'banefulbunker'))
    check('毒ありなら T1 は発動しない', rid != 'T1' and a1[1] != 'toxic', (a1, rid))
    print('4 can_poison')
    st = _game(['ドヒドイデ', 'カバルドン', 'グレンアルマ'], gusoku(mega=True))
    a1, rid, _ = _run_choose(st, act(st, 'banefulbunker'))
    check('メガ後のグソクムシャに toxic を選ばない', a1[1] != 'toxic' and not policy.can_poison(st, st.sides[1].mons[0]), (a1, rid))
    st = _game(['ドヒドイデ', 'カバルドン', 'グレンアルマ'], gusoku())
    f = st.sides[1].mons[0]
    a1, rid, _ = _run_choose(st, act(st, 'banefulbunker'))
    check('メガ前(can_mega)のグソクムシャにも toxic を選ばない', f.can_mega and a1[1] != 'toxic', (f.can_mega, a1, rid))
    print('5 G1 / D1')
    st = _game(['ドヒドイデ', 'カバルドン', 'グレンアルマ'], gusoku(mega=True, boosts={'atk': 2}))
    st.sides[0].mons[0].hp = int(st.sides[0].mons[0].maxhp * 0.9)
    a1, rid, _ = _run_choose(st, act(st, 'recover'))
    check('ドヒドイデ(HP90%) vs +2グソクムシャ → recover を選ばない', a1[1] != 'recover', (a1, rid))
    st = _game(['ドヒドイデ', 'カバルドン', 'グレンアルマ'], ashi())
    st.sides[0].mons[0].hp = int(st.sides[0].mons[0].maxhp * 0.9)
    st.sides[1].mons[0].status = 'tox'
    a1, rid, _ = _run_choose(st, act(st, 'recover'))
    check('D1: HP90% の回復を止める', a1[1] != 'recover', (a1, rid))
    st.sides[0].mons[0].hp = int(st.sides[0].mons[0].maxhp * 0.5)
    a1, rid, _ = _run_choose(st, act(st, 'recover'))
    check('D1: HP50% なら回復は止めない', a1[1] == 'recover', (a1, rid))
    print('6 M1')
    st = _game(['カバルドン', 'ドヒドイデ', 'グレンアルマ'], mimi())
    a1, rid, _ = _run_choose(st, act(st, 'stealthrock'))
    check('カバルドン vs ミミッキュ(皮あり) → earthquake (M1)', a1[1] == 'earthquake' and rid == 'M1', (a1, rid))
    st = _game(['エンペルト', 'ドヒドイデ', 'グレンアルマ'], mimi())
    a1, rid, _ = _run_choose(st, act(st, 'stealthrock'))
    check('エンペルト(控えあり) vs ミミッキュ(皮あり) → flipturn (M1)', a1[1] == 'flipturn' and rid == 'M1', (a1, rid))
    st = _game(['カバルドン', 'ドヒドイデ', 'グレンアルマ'], mimi())
    st.sides[1].mons[0].busted = True
    a1, rid, _ = _run_choose(st, act(st, 'earthquake'))
    check('皮が剥がれた後 → stealthrock (R1)', a1[1] == 'stealthrock' and rid == 'R1', (a1, rid))
    print('7 M2')
    st = _game(['カバルドン', 'ドヒドイデ', 'グレンアルマ'], mimi(boosts={'atk': 2}))
    st.sides[1].mons[0].busted = True
    r0 = [('stealthrock', 0), ('yawn', 1), ('slackoff', 2)]
    res = []
    for mid, _n in r0:
        a1, rid, _ = _run_choose(st, act(st, mid))
        res.append(a1[1])
    check('+2ミミッキュ(皮なし)に stealthrock・yawn・slackoff を選ばない', not set(res) & {'stealthrock', 'yawn', 'slackoff'}, res)
    print('8 Z2')
    st = _game(['マスカーニャ', 'カバルドン', 'グレンアルマ'], _foe('ガブリアス', 'きあいのタスキ', 'さめはだ', 'ようき', {'spe': 32},
                                                              ['じしん', 'げきりん', 'ステルスロック', 'つるぎのまい']))
    a1, rid, _ = _run_choose(st, act(st, 'uturn'))
    check('マスカーニャ vs ガブリアス → tripleaxel (Z2)', a1[1] == 'tripleaxel' and rid == 'Z2', (a1, rid))
    print('9 chooser')
    st = _game(['カバルドン', 'ドヒドイデ', 'グレンアルマ'], gusoku(mega=True, boosts={'atk': 2}))
    cx = policy.Ctx([], None)
    ch = policy.make_chooser(cx)
    j = ch(st, 0, [1, 2])
    check('+2グソクムシャの前 → グレンアルマ (G1r)', st.sides[0].mons[j].name == 'グレンアルマ', st.sides[0].mons[j].name)
    st.sides[0].mons[2].hp -= 10
    nf = len(cx.fired)
    j = ch(st, 0, [1, 2])
    check('グレンアルマが満タンでないなら G1r は発動しない', all(f[1] != 'G1r' for f in cx.fired[nf:]), cx.fired[nf:])
    st = _game(['カバルドン', 'マスカーニャ', 'ドヒドイデ'], gab(mega=True))
    j = ch(st, 0, [1, 2])
    check('メガガブリアスZ の前 → マスカーニャ (Z1)', st.sides[0].mons[j].name == 'マスカーニャ', st.sides[0].mons[j].name)
    st = _game(['ドヒドイデ', 'エンペルト', 'グレンアルマ'], ashi())
    j = ch(st, 0, [1, 2])
    check('R1b: ステロ要員(エンペルト)を優先', st.sides[0].mons[j].name in ('エンペルト', 'グレンアルマ') and
          (st.sides[0].mons[j].name == 'エンペルト' or S.switch_score(st, 0, 1) < S.switch_score(st, 0, 2) - 0.15),
          st.sides[0].mons[j].name)
    print('10 X1')
    st = _game(['ドヒドイデ', 'マスカーニャ', 'グレンアルマ'], gab(mega=True))
    sw = ('s', 1)
    dmg = S.best_damage(st, 1, target=st.sides[0].mons[1])
    a1, rid, ctx = _run_choose(st, sw, rules=policy.ALL_RULES)
    check(f'メガガブリアスZ の前でマスカーニャへ交代(与ダメ{dmg:.2f}) → 選ばない (X1)', dmg >= 1.0 and a1 != sw, (a1, rid, dmg))
    print('11 K')
    st = _game(['カバルドン', 'ドヒドイデ', 'グレンアルマ'], _foe('ドヒドイデ', 'たべのこし', 'さいせいりょく', 'ずぶとい', {'hp': 32, 'def': 32},
                                                          ['じこさいせい', 'どくどく', 'トーチカ', 'まとわりつく'], hp=0.05))
    eq = act(st, 'earthquake')
    ko, fs = S.est(st, 0, 'earthquake'), S.faster(st, 0)
    a1, rid, _ = _run_choose(st, eq)
    check(f'K: 先手の確1攻撃が1位なら R1 で上書きしない(est {ko:.2f}, 先手 {fs})',
          ko >= 1.0 and fs == 1.0 and a1 == eq and rid == 'K', (a1, rid))
    st = _game(['カバルドン', 'ドヒドイデ', 'グレンアルマ'], _foe('ドヒドイデ', 'たべのこし', 'さいせいりょく', 'ずぶとい', {'hp': 32, 'def': 32},
                                                          ['じこさいせい', 'どくどく', 'トーチカ', 'まとわりつく']))
    a1, rid, _ = _run_choose(st, eq if False else act(st, 'earthquake'))
    check('K の対照: 倒せない同じ局面では R1 が働く', a1[1] == 'stealthrock' and rid == 'R1', (a1, rid))
    print('S9')
    st = _game(['カバルドン', 'グレンアルマ', 'ドヒドイデ'], _foe('エアームド', 'ゴツゴツメット', 'がんじょう', 'わんぱく', {'hp': 32, 'def': 32},
                                                          ['ブレイブバード', 'ステルスロック', 'ボディプレス', 'はねやすめ']))
    st.sides[1].cond['stealthrock'] = 1
    st.sides[1].mons[0].status = 'tox'
    a1, rid, _ = _run_choose(st, act(st, 'earthquake'))
    check('S9: 打点も役割も無い → グレンアルマへ交代', a1 == ('s', 1) and rid == 'S9', (a1, rid))
    print(f'selftest: {ok} 合格 / {len(bad)} 不合格 {bad}')
    return not bad


# ---------------------------------------------------------------- report

def _wr(rows):
    n = len(rows)
    w = sum(1 for r in rows if r == 1)
    return w, n


def _pct(w, n):
    return f'{100 * w / n:.0f}% ({w}/{n})' if n else '-'


STEEL_POISON = {'エアームド', 'ブリジュラス', 'ルカリオ', 'サーフゴー', 'ゲンガー', 'キラフロル', 'ドヒドイデ', 'ハッサム', 'ナットレイ',
                'ドータクン', 'ジバコイル', 'ハガネール', 'ギルガルド', 'バンギラス'}


def classify(g):
    """Loss class: 1 グソクムシャ +2 killed >=2 (approx: it used つるぎのまい), 2 same for ミミッキュ, 3 judged,
    4 last foes steel/poison, 5 メガガブリアスZ killed one of our walls, 0 other."""
    log, fa = g.get('log', []), g.get('faints', [])
    killers = [f[3] for f in fa if f[1] == 0]
    sd = lambda nm: any(l[2] == nm and l[3] == 'つるぎのまい' for l in log)
    if sd('グソクムシャ') and sum(1 for k in killers if k == 'グソクムシャ') >= 2:
        return 1
    if sd('ミミッキュ') and sum(1 for k in killers if k == 'ミミッキュ') >= 1:
        return 2
    if g.get('judged'):
        return 3
    left_foe = [n for n, hp in g.get('left', [[], []])[1] if hp > 0]
    if left_foe:
        types_ok = all(_types_of({'name': n}) & {'poison', 'steel'} for n in left_foe)
        if types_ok:
            return 4
    walls = {'カバルドン', 'ドヒドイデ', 'エンペルト'}
    if any(f[1] == 0 and f[2] in walls and f[3] == 'ガブリアス' for f in fa):
        return 5
    return 0


CLASS_NAMES = {1: '(1) グソクムシャ+2が2体以上倒した', 2: '(2) ミミッキュ+2が1体以上倒した', 3: '(3) 30ターンで判定負け',
               4: '(4) 最後の相手が鋼・毒で打点10%未満', 5: '(5) メガガブリアスZが受けを倒した', 0: 'その他'}


def cmd_report(a):
    party = _init_r9()
    if not os.path.exists(RESULT_P):
        raise SystemExit('結果がありません')
    d = json.load(open(RESULT_P, encoding='utf-8'))
    plan, games = d['plan'], d['games']
    G = {}
    for key, g in games.items():
        if g.get('res') is None:
            continue
        kid, mode, k = key.split('|')
        G.setdefault(mode, {}).setdefault(kid, {})[int(k)] = g
    L = []
    nmode = {m: sum(len(v) for v in G[m].values()) for m in G}
    secs = sum(g.get('sec', 0) for g in games.values())
    L += ['# R9 並び（軸）対策の結果', '',
          '## 1. 条件', '',
          '- パーティ R9: ' + ' / '.join(f"{p['species']}（{'・'.join(p['moves'])}）@{p['item']}" for p in party),
          f"- 読みの深さ: 自分 {d['depth'][0]} 手・相手 {d['depth'][1]} 手、最大 30 ターン（決着しなければ評価値で判定）",
          '- 種: crc32("core{構築id}{k}")（on と off で同じ）。両者とも相手の型は推測（記事の型は使わない）',
          f"- 作成: {datetime.datetime.now():%Y-%m-%d %H:%M}、対戦の合計時間 {secs / 3600:.1f} 時間（のべ、並列分を含む）",
          '- 戦数: ' + '、'.join(f'{m} {n} 戦' for m, n in nmode.items()) + f"（計画済み {len(plan)} 構築）",
          '- 注意: 1 構築 5 戦なので勝率の誤差は大きい（±20% 程度）。', '',
          '## 2. 並び一覧', '', '| ID | 並び | 該当構築 | 評価（★は主、共有は他の並びで対戦済み） |', '|---|---|---|---|']
    for c in CORES:
        hit = [t['id'][:8] for t in core_teams(c)]
        ev = [('★' if any(k.startswith(p) for p in c['star']) else '共有') + k[:8]
              for k in EVAL_IDS if k in plan and c['id'] in cores_of(k)]
        L.append(f"| {c['id']} | {c['name']} | {' '.join(hit)} | {' '.join(ev)} |")
    L += ['', '## 3. 構築ごと', '',
          '| 構築 | 並び | 相手の選出 | on の選出 | off の選出 | on 5戦 | off 5戦 | 判定決着 on/off |', '|---|---|---|---|---|---|---|---|']
    mark = lambda r: '○' if r == 1 else '×'
    for kid, pl in plan.items():
        row = []
        jud = []
        for m in ('on', 'off'):
            gs = G.get(m, {}).get(kid, {})
            row.append(''.join(mark(gs[k]['res']) if k in gs else '-' for k in range(NGAMES)))
            jud.append(sum(1 for g in gs.values() if g.get('judged')))
        rel = f" 緩和{pl['on']['relaxed']}" if pl['on'].get('relaxed') else ''
        L.append(f"| {kid[:8]} {pl['title'][:24]} | {','.join(pl['cores'])} | {'→'.join(pl['opp_order'])} | "
                 f"{'→'.join(pl['on']['my_order'])}{rel} | {'→'.join(pl['off']['my_order'])} | {row[0]} | {row[1]} | {jud[0]}/{jud[1]} |")
    L += ['', '## 4. 並びごとの勝率', '', '| 並び | on | off | 差 | 戦数 on/off |', '|---|---|---|---|---|']
    tot = {'on': [0, 0], 'off': [0, 0]}
    for c in CORES:
        cells = []
        nn = []
        vals = {}
        for m in ('on', 'off'):
            rows = [g['res'] for kid in plan if c['id'] in plan[kid]['cores'] and kid in EVAL_IDS
                    for g in G.get(m, {}).get(kid, {}).values()]
            vals[m] = _wr(rows)
            cells.append(_pct(*vals[m]))
            nn.append(len(rows))
        diff = (f"{100 * (vals['on'][0] / vals['on'][1] - vals['off'][0] / vals['off'][1]):+.0f}pt"
                if vals['on'][1] and vals['off'][1] else '-')
        L.append(f"| {c['id']} {c['name']} | {cells[0]} | {cells[1]} | {diff} | {nn[0]}/{nn[1]} |")
    for m in ('on', 'off'):
        rows = [g['res'] for kid in plan for g in G.get(m, {}).get(kid, {}).values()]
        tot[m] = _wr(rows)
    L.append(f"| 全体（重複なし） | {_pct(*tot['on'])} | {_pct(*tot['off'])} | | |")
    # rule firing
    L += ['', '## 5. 規則の発動率（on）', '', '| 規則 | 発動した試合/on の試合 | 発動回数 | 発動した試合の勝率 | 発動しなかった試合の勝率 |',
          '|---|---|---|---|---|']
    on_games = [g for kid in G.get('on', {}) for g in G['on'][kid].values()]
    for rid in policy.ALL_RULES:
        hit = [g for g in on_games if any(f[1] == rid for f in g.get('fired', []))]
        miss = [g for g in on_games if g not in hit]
        cnt = sum(1 for g in on_games for f in g.get('fired', []) if f[1] == rid)
        L.append(f"| {rid} | {len(hit)}/{len(on_games)} | {cnt} | {_pct(*_wr([g['res'] for g in hit]))} | "
                 f"{_pct(*_wr([g['res'] for g in miss]))} |")
    # rocks
    L += ['', '## 6. ステロ', '']
    for m in ('on', 'off'):
        gs = [(kid, g) for kid in G.get(m, {}) for g in G[m][kid].values()]
        if not gs:
            continue
        got = [g for _, g in gs if g.get('rocks_turn')]
        avg = sum(g['rocks_turn'] for g in got) / len(got) if got else 0
        rk = [(kid, g) for kid, g in gs if set(plan[kid][m if m in plan[kid] else 'on']['my_order']) & {'カバルドン', 'エンペルト'}]
        rk_got = [g for _, g in rk if g.get('rocks_turn')]
        L.append(f"- {m}: 撒けた試合 {_pct(len(got), len(gs))}、初めて撒いたターンの平均 {avg:.1f}、"
                 f"ステロ要員を選出した試合に限ると {_pct(len(rk_got), len(rk))}")
        if m == 'on' and gs and len(got) / len(gs) < 0.9:
            reasons = {}
            for kid, g in gs:
                if g.get('rocks_turn'):
                    continue
                if not (set(plan[kid]['on']['my_order']) & {'カバルドン', 'エンペルト'}):
                    why = 'ステロ要員を選出していない'
                elif any(f[1] in ('M1', 'M2') for f in g.get('fired', [])):
                    why = 'M1/M2 で後回し'
                else:
                    why = '初手で倒された・相手がマジックミラー・その他'
                reasons[why] = reasons.get(why, 0) + 1
            L.append('  - 撒けなかった理由: ' + '、'.join(f'{k} {v}' for k, v in reasons.items()))
    # ashi teams
    L += ['', '## 7. アシレーヌ入り構築', '']
    ak = [k for k in plan if any(k.startswith(p) for p in ASHI_EVAL)]
    for m in ('on', 'off'):
        picks = [k for k in ak if 'ドヒドイデ' in plan[k][m]['my_order']]
        gs = [g for k in ak for g in G.get(m, {}).get(k, {}).values()]
        if not ak:
            continue
        tx = [g for g in gs if g.get('tox')]
        ash = [g for g in gs if 'アシレーヌ' in g.get('tox', [])]
        L.append(f"- {m}: ドヒドイデ選出 {len(picks)}/{len(ak)} 構築、どくどくを入れた試合 {_pct(len(tx), len(gs))}、"
                 f"うちアシレーヌに入れた試合 {_pct(len(ash), len(gs))}")
    # loss classes
    L += ['', '## 8. 負け方の分類（近似: 能力変化はつるぎのまいの使用で見ている）', '', '| 分類 | on | off |', '|---|---|---|']
    cnt = {m: {} for m in ('on', 'off')}
    nloss = {}
    for m in ('on', 'off'):
        loss = [g for kid in G.get(m, {}) for g in G[m][kid].values() if g['res'] != 1]
        nloss[m] = len(loss)
        for g in loss:
            c = classify(g)
            cnt[m][c] = cnt[m].get(c, 0) + 1
    for c in (1, 2, 3, 4, 5, 0):
        L.append(f"| {CLASS_NAMES[c]} | {cnt['on'].get(c, 0)} | {cnt['off'].get(c, 0)} |")
    L.append(f"| 負け合計 | {nloss.get('on', 0)} | {nloss.get('off', 0)} |")
    # memo
    L += ['', '## 9. 対策メモの更新（仮説 §6 に対する on の結果）', '',
          '勝率は 5 戦ずつなので誤差が大きい（±20% 程度）。差が小さい並びは「支持も否定もできない」と読む。', '']
    for c in CORES:
        rows_on = [g['res'] for kid in plan if c['id'] in plan[kid]['cores'] for g in G.get('on', {}).get(kid, {}).values()]
        rows_off = [g['res'] for kid in plan if c['id'] in plan[kid]['cores'] for g in G.get('off', {}).get(kid, {}).values()]
        if not rows_on:
            L.append(f"- {c['id']} {c['name']}: on の結果なし")
            continue
        w, n = _wr(rows_on)
        wo, no = _wr(rows_off)
        verdict = '支持' if w / n >= 0.5 and (not no or w / n >= wo / no) else '支持されず'
        L.append(f"- {c['id']} {c['name']}: on {_pct(w, n)}、off {_pct(wo, no)} → 第一候補は{verdict}")
    txt = '\n'.join(L) + '\n'
    out = a.out or REPORT_P
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, 'w', encoding='utf-8').write(txt)
    print(f'{out} に書きました（on {nmode.get("on", 0)} 戦 / off {nmode.get("off", 0)} 戦）')


# ---------------------------------------------------------------- party adjustment R10 vs R9 (spec SPEC_ADJUST.md)

ADJ_P = lambda tag: os.path.join(HERE, '..', 'logs', 'refine', f'adjust_{tag}.json')   # adjust_R10.json
ADJ_REPORT = lambda tag: os.path.join(HERE, '..', 'logs', f'ADJUST_{tag}.md')          # ADJUST_R10.md
ADJ_VERSION = 1
N_WIN = N_LOSE = 10
EMP = 'エンペルト'
ICE = 'れいとうビーム'


def _init_party(tag='R9'):
    """Idempotent: put party `tag` (R9 / R10 ...) into battle.py. Species must be the same as R9's."""
    party = refine.load_tag(tag)
    if refine._BASE_SPECIES is None or refine._BASE_SPECIES != [p['species'] for p in party]:
        refine._BASE_SPECIES = [p['species'] for p in party]
    refine.apply_party(party)
    B.MY_TYPES = tuple(tuple(m.types) for m in B.TEAM)
    refine.teams()
    return party


def _diff_parties(new, base):
    """List of (path, base value, new value) for every leaf that differs."""
    out = []
    if len(new) != len(base):
        return [('len', len(base), len(new))]
    for i, (n, b) in enumerate(zip(new, base)):
        for k in sorted(set(n) | set(b)):
            if k == 'moves':
                if len(n[k]) != len(b[k]):
                    out.append((f'[{i}].moves', b[k], n[k]))
                    continue
                for j, (x, y) in enumerate(zip(n[k], b[k])):
                    if x != y:
                        out.append((f'[{i}].moves[{j}]', y, x))
            elif n.get(k) != b.get(k):
                out.append((f'[{i}].{k}', b.get(k), n.get(k)))
    return out


def cmd_check_diff(a):
    new, base = refine.load_tag(a.party), refine.load_tag(a.base)
    diffs = _diff_parties(new, base)
    for path, b, n in diffs:
        print(f'{a.base}{path}: {b} -> {a.party}{path}: {n}')
    ok = len(diffs) == 1 and diffs[0][0] == '[3].moves[1]' and new[3]['species'] == EMP
    _init_party(a.base)
    _init_party(a.party)                            # apply_party asserts
    import calc
    ok = ok and ICE in calc.learnset(EMP)
    print(f"差分 {len(diffs)} 件、{EMP} の覚える技に {ICE}: {ICE in calc.learnset(EMP)} -> {'OK' if ok else 'NG'}")
    return ok


def _adj_sigs(a):
    return {a.party: refine.sig(refine.load_tag(a.party)), a.base: refine.sig(refine.load_tag(a.base))}


def _cores_raw():
    p = RESULT_P
    return json.load(open(p, encoding='utf-8'))       # read only


def _adj_check(d, a, depth=None):
    p = ADJ_P(a.party)
    bad = d.get('version') != ADJ_VERSION or d.get('party') != a.party or d.get('base') != a.base or \
        d.get('sig') != _adj_sigs(a) or d.get('policy_version') != policy.POLICY_VERSION or \
        d.get('source', {}).get('sig') != _cores_raw()['sig'] or \
        (depth is not None and d.get('deep', {}).get('depth') != [depth, OPP_DEPTH])
    if bad:
        raise SystemExit(f'{p}: version / party / sig / policy_version / source.sig / deep.depth が違います'
                         '（adjust-plan --force で退避して新しく始める）')


def adj_save(d, a):
    os.makedirs(os.path.dirname(ADJ_P(a.party)), exist_ok=True)
    safeio.write_json(ADJ_P(a.party), d)


def pick_pairs(cores):
    """Spec 3.1: 10 wins + 10 losses from R9 games where Empoleon was in our selection. Wins first, then losses."""
    variants = [('on-NONE', 'on', ['NONE']), ('on', 'on', list(policy.ALL_RULES)), ('off', 'off', None)]
    seen, wins, losses = set(), [], []
    for vname, selkey, rules in variants:
        cands = []
        for kid in EVAL_IDS:
            pl = cores['plan'].get(kid)
            if not pl or EMP not in pl[selkey]['my_order']:
                continue
            for k in range(NGAMES):
                g = cores['games'].get(f'{kid}|{vname}|{k}')
                if g and g.get('res') is not None:
                    cands.append((k, EVAL_IDS.index(kid), kid, g, pl))
        for k, _i, kid, g, pl in sorted(cands, key=lambda c: (c[0], c[1])):
            key = (kid, tuple(pl[selkey]['my_order']), tuple(pl['opp_order']), g['seed'])
            if key in seen:
                continue
            win = g['res'] == 1
            if (win and len(wins) >= N_WIN) or (not win and len(losses) >= N_LOSE):
                continue
            seen.add(key)
            (wins if win else losses).append({
                'src': f'{kid}|{vname}|{k}', 'kid': kid, 'variant': vname, 'rules': rules,
                'my_order': list(pl[selkey]['my_order']), 'opp_order': list(pl['opp_order']), 'seed': g['seed'],
                'orig_res': g['res'], 'orig_turns': g.get('turns'), 'orig_log': g.get('log')})
    if len(wins) < N_WIN or len(losses) < N_LOSE:
        raise SystemExit(f'再戦の組が足りません: 勝ち {len(wins)} 負け {len(losses)}')
    pairs = wins + losses
    for n, p in enumerate(pairs, 1):
        p['id'] = f'P{n:02d}'
    return [{'id': p['id'], **{k: v for k, v in p.items() if k != 'id'}} for p in pairs]


def make_deep_plan(a, cores, depth):
    """Spec 4: teams where Empoleon is in the R10 'on' selection and/or the R9 'on' selection."""
    plan = {}
    new = _init_party(a.party)
    for kid in EVAL_IDS:
        t = _team(kid)
        opp6 = [B._base(m['name']) for m in t['team']]
        t0 = time.time()
        _init_party(a.party)
        filt = policy.select_filter(opp6)
        best, top = refine.blind_select(t, order_filter=filt)
        relaxed = []
        if not filt(best):
            orders = [[x] + [y for y in m3 if y != x] for m3 in __import__('itertools').combinations(
                [B.BASE_OF.get(m.species, m.species) for m in B.TEAM], 3) for x in m3]
            f2, relaxed = policy.relaxed_filter(opp6, orders)
            best, top = refine.blind_select(t, order_filter=f2)
        cp = cores['plan'][kid]
        why = [tag for tag, o in ((a.party, best), (a.base, cp['on']['my_order'])) if EMP in o]
        print(f"deep-plan {kid[:8]} R10 {best} R9 {cp['on']['my_order']}{' 緩和' + str(relaxed) if relaxed else ''}"
              f"{' 対象' + str(why) if why else ''} ({time.time() - t0:.0f}s)", flush=True)
        if why:
            plan[kid] = {'title': t['title'], 'why': why, 'opp_order': list(cp['opp_order']),
                         a.party: {'my_order': best, 'my_top': top, 'relaxed': relaxed},
                         a.base: {'my_order': list(cp['on']['my_order'])}}
    _init_party(a.base)
    return plan


def adj_load(a, force=False, depth=6, games=5, build=False):
    """Load adjust_<party>.json (checked), or start a new one. build: compute pairs / deep plan if missing."""
    p = ADJ_P(a.party)
    d = None
    if os.path.exists(p):
        if force:
            os.replace(p, p.replace('.json', '.' + datetime.datetime.now().strftime('%Y%m%d%H%M%S') + '.json'))
        else:
            d = json.load(open(p, encoding='utf-8'))
            _adj_check(d, a, depth if build else None)
    if d is None:
        cores = _cores_raw()
        d = {'version': ADJ_VERSION, 'party': a.party, 'base': a.base, 'sig': _adj_sigs(a),
             'policy_version': policy.POLICY_VERSION, 'opp_depth': OPP_DEPTH,
             'source': {'file': 'logs/refine/cores_R9.json', 'sig': cores['sig']},
             'pairs': [], 'deep': {'depth': [depth, OPP_DEPTH], 'games': games, 'plan': {}}, 'games': {}}
    if build:
        cores = _cores_raw()
        if not d['pairs']:
            d['pairs'] = pick_pairs(cores)
            adj_save(d, a)
        if not d['deep']['plan']:
            d['deep']['plan'] = make_deep_plan(a, cores, depth)
            adj_save(d, a)
    return d


def cmd_adjust_plan(a):
    d = adj_load(a, force=a.force, depth=a.depth, games=NGAMES, build=True)
    print(f"再戦 {len(d['pairs'])} 組（勝 {sum(p['orig_res'] == 1 for p in d['pairs'])} / "
          f"負 {sum(p['orig_res'] != 1 for p in d['pairs'])}）、6 手読み対象 {len(d['deep']['plan'])} 構築 -> {os.path.abspath(ADJ_P(a.party))}")
    print('| 組 | 元の試合 | 自分の選出 | 相手の選出 | 種 | 元の結果 |')
    print('|---|---|---|---|---|---|')
    for p in d['pairs']:
        s = p['src'].split('|')
        print(f"| {p['id']} | {s[0][:8]}|{s[1]}|{s[2]} | {'→'.join(p['my_order'])} | {'→'.join(p['opp_order'])} | "
              f"{p['seed']} | {'勝' if p['orig_res'] == 1 else '負'} |")
    print('6 手読みの対象:')
    for kid, pl in d['deep']['plan'].items():
        print(f"  {kid[:8]} {pl['title'][:24]} 理由{pl['why']} R10 {pl[a.party]['my_order']} R9 {pl[a.base]['my_order']}")


def _work_adj(job):
    key, tag, party, kid, my_order, opp_order, seed, my_depth, rules = job
    t0 = time.time()
    try:
        _init_party(tag)
        r = refine.blind_play((party, kid, my_order, opp_order, seed, my_depth, OPP_DEPTH, False,
                               tuple(rules) if rules is not None else None, True))
    except Exception:
        import traceback
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    r['seed'] = seed
    r['sec'] = round(time.time() - t0, 1)
    r['party'] = tag
    r['depth'] = [my_depth, OPP_DEPTH]
    return key, r


def _run_adj(a, d, jobs, prefix, total):
    """Run jobs in a pool; one atomic save per finished game (spec 5.3)."""
    done_before = sum(1 for k, g in d['games'].items() if k.startswith(prefix) and g.get('res') is not None)
    if a.max_games:
        jobs = jobs[:a.max_games]
    print(f'実行 {len(jobs)} 戦（済み {done_before} / 全体 {total}）procs={a.procs}', flush=True)
    if not jobs:
        return
    import multiprocessing as mp
    ctx = mp.get_context('fork') if hasattr(os, 'fork') else mp.get_context('spawn')
    t0 = time.time()
    n = 0
    with ctx.Pool(min(a.procs, len(jobs))) as pool:
        for key, r in pool.imap_unordered(_work_adj, jobs, chunksize=1):
            d['games'][key] = r
            adj_save(d, a)
            n += 1
            res = {1: '勝', -1: '負', 0: '分', None: '例外'}.get(r['res'], str(r['res']))
            print(f"[{done_before + n}/{total}] {key} {res} {r.get('turns', '-')}T {r['sec']}s "
                  f"経過{(time.time() - t0) / 60:.1f}分", flush=True)
            if r.get('error'):
                print('   error:', r['error'].strip().splitlines()[-1], flush=True)


def _todo(d, key):
    g = d['games'].get(key)
    return not (g and g.get('res') is not None)


def cmd_replay(a):
    d = adj_load(a, build=True)
    parties = {a.party: refine.load_tag(a.party), a.base: refine.load_tag(a.base)}
    tags = [a.party] if a.no_control else [a.party, a.base]
    jobs = []
    for p in d['pairs']:
        for tag in tags:
            key = f"replay|{tag}|{p['id']}"
            if _todo(d, key):
                jobs.append((key, tag, parties[tag], p['kid'], p['my_order'], p['opp_order'], p['seed'], 5, p['rules']))
    _run_adj(a, d, jobs, 'replay|', len(d['pairs']) * len(tags))


def cmd_deep(a):
    d = adj_load(a, depth=a.depth, games=a.games, build=True)
    d['deep']['games'] = a.games
    parties = {a.party: refine.load_tag(a.party), a.base: refine.load_tag(a.base)}
    jobs = []
    for k in range(a.games):
        for kid, pl in d['deep']['plan'].items():
            for tag in (a.party, a.base):
                key = f'deep|{tag}|{kid}|{k}'
                if _todo(d, key):
                    jobs.append((key, tag, parties[tag], kid, pl[tag]['my_order'], pl['opp_order'], seed_of(kid, k),
                                 a.depth, ['NONE']))
    _run_adj(a, d, jobs, 'deep|', len(d['deep']['plan']) * a.games * 2)


# ---- adjust-selftest (spec 5.4)

def cmd_adjust_selftest(a):
    party = _init_party('R10')
    ok, bad = 0, []

    def check(name, cond, info=''):
        nonlocal ok
        if cond:
            ok += 1
            print(f'  OK   {name}')
        else:
            bad.append(name)
            print(f'  FAIL {name} {info}')

    def play(a1, mid='icebeam', foe_moves=('じしん', 'まもる', 'つるぎのまい', 'げきりん')):
        foe = _foe('ガブリアス', 'きあいのタスキ', 'さめはだ', 'ようき', {'spe': 32}, list(foe_moves))
        st = _game([EMP, 'ドヒドイデ', 'グレンアルマ'], foe)
        a0 = policy.find(E.actions(st, 0), mid)
        assert a0, E.actions(st, 0)
        if a1[0] == 'm':
            a1 = policy.find(E.actions(st, 1), a1[1])
        assert a1 in E.actions(st, 1), (a1, E.actions(st, 1))
        my_nm, foe_nm = st.active(0).name, st.active(1).name
        elog = []
        E.step(st, a0, a1, rng=prep.RandomRNG(1), log=elog)
        return refine._trace_move(1, my_nm, foe_nm, mid, elog), elog

    r, el = play(('m', 'earthquake'))
    check('エンペルト れいとうビーム vs ガブリアス(じしん) → hit', r == [1, EMP, ICE, 'ガブリアス', 'hit'], (r, el))
    r, el = play(('m', 'protect'))
    check('相手が まもる → protect', r[:4] == [1, EMP, ICE, 'ガブリアス'] and r[4] == 'protect', (r, el))
    r, el = play(('s', 1))
    check('相手が交代 → 対象は交代先', r[3] == 'ミミッキュ' and r[4] in ('hit', 'unknown'), (r, el))
    cores = _cores_raw()
    kid = _full('1e1ecbc7')
    pl = cores['plan'][kid]
    args = (party, kid, pl['on']['my_order'], pl['opp_order'], seed_of(kid, 0), 3, 3, False, ('NONE',))
    t0 = time.time()
    r0 = refine.blind_play(args + (False,))
    r1 = refine.blind_play(args + (True,))
    same = r0['res'] is not None and r0['res'] == r1['res'] and r0['log'] == r1['log'] and \
        {k: v for k, v in r1.items() if k != 'mv'} == r0 and 'mv' not in r0 and 'mv' in r1
    check(f"trace=False と True で res・log が一致（3 手読み 1 戦 x2, {time.time() - t0:.0f}s, "
          f"{r0.get('turns')}T, mv {len(r1.get('mv', []))} 件）", same, (r0.get('error'), r1.get('error')))
    print(f'adjust-selftest: {ok} 合格 / {len(bad)} 不合格 {bad}')
    return not bad


# ---- adjust-report

def _games_of(d, prefix):
    return {k: g for k, g in d['games'].items() if k.startswith(prefix) and g.get('res') is not None}


def _emp_stats(games, moves):
    """Empoleon's move counts and ice beam details over a list of game dicts."""
    use = {m: 0 for m in moves}
    res = {x: 0 for x in ('hit', 'miss', 'protect', 'immune', 'none', 'unknown')}
    targets, kills, turns, withfield, withice = {}, 0, 0, 0, 0
    for g in games:
        on_field = sum(1 for l in g.get('log', []) if l[0] == EMP)
        turns += on_field
        withfield += on_field > 0
        ice_here = False
        for t, me, mv, tg, r in g.get('mv', []):
            if me != EMP:
                continue
            use[mv] = use.get(mv, 0) + 1
            if mv == ICE:
                ice_here = True
                res[r] = res.get(r, 0) + 1
                if r == 'hit':
                    targets[tg] = targets.get(tg, 0) + 1
                    if any(f[0] == t and f[1] == 1 and f[2] == tg for f in g.get('faints', [])):
                        kills += 1
        withice += ice_here and on_field > 0
    return {'use': use, 'ice': res, 'targets': targets, 'kills': kills, 'turns': turns, 'games': len(games),
            'field': withfield, 'with_ice': withice}


def cmd_adjust_report(a):
    p = ADJ_P(a.party)
    if not os.path.exists(p):
        raise SystemExit(f'{p} がありません')
    d = json.load(open(p, encoding='utf-8'))
    _adj_check(d, a)
    P, Bs = a.party, a.base
    G = d['games']
    mark = lambda r: '○' if r == 1 else '×'
    jp = lambda s: '→'.join(s)
    L = []
    secs = sum(g.get('sec', 0) for g in G.values())
    rp = {p_['id']: (G.get(f"replay|{P}|{p_['id']}"), G.get(f"replay|{Bs}|{p_['id']}")) for p_ in d['pairs']}
    n_rp = sum(1 for v in rp.values() if v[0] and v[0].get('res') is not None)
    n_ct = sum(1 for v in rp.values() if v[1] and v[1].get('res') is not None)
    dg = d['deep']
    n_dp = {t: len(_games_of(d, f'deep|{t}|')) for t in (P, Bs)}
    depth = dg['depth']
    L += [f'# {Bs} の 1 匹調整（{EMP}: あくび → {ICE}）の検証', '',
          '## 1. 条件', '',
          f'- 差分: {EMP}（4 番目）の技 あくび → {ICE}（こおり・特殊、威力 90・命中 100、追加効果 10% こおり）の 1 つだけ。他の 5 体・努力値・並び順は {Bs} と同じ',
          f'- 再戦の深さ: 自分 5 手・相手 {OPP_DEPTH} 手（元の {Bs} 試合と同じ）、6 手読みの深さ: 自分 {depth[0]} 手・相手 {depth[1]} 手、最大 30 ターン（決着しなければ評価値で判定）',
          '- 種: 再戦は元の試合の保存値、6 手読みは crc32("core{構築id}{k}")（R10 と R9 で同じ）。両者とも相手の型は推測（ブラインド）',
          f'- 作成: {datetime.datetime.now():%Y-%m-%d %H:%M}、対戦の合計時間 {secs / 3600:.1f} 時間（のべ、並列分を含む）',
          f"- 6 手読み 1 戦の実測: {', '.join(f'{k} {g['sec']}s/{g.get('turns')}T' for k, g in list(_games_of(d, 'deep|').items())[:3]) or '-'}",
          f'- 戦数: 再戦 {P} {n_rp}/{len(d["pairs"])}・{Bs}対照 {n_ct}/{len(d["pairs"])}、6 手読み {P} {n_dp[P]}・{Bs} {n_dp[Bs]}'
          f'（対象 {len(dg["plan"])} 構築 x {dg["games"]} 戦）',
          '- 注意: 5 戦単位（構築別）の勝率の誤差は ±20% 程度、6 手読みの合計（25〜35 戦）でも ±10% 程度、'
          '再戦 20 組の差（負→勝 − 勝→負）は ±3 程度が偶然で起きる', '']
    # 2 replay
    L += ['## 2. 再戦 20 組の勝敗変化', '',
          f'| 組 | 構築 | 変種 | 自分の選出 | 相手の選出 | 種 | 元の結果 | {Bs}対照 | {P} の結果 | 変化 | {P} T | {P} の{ICE} 回数 |',
          '|---|---|---|---|---|---|---|---|---|---|---|---|']
    a_up = b_dn = rep = 0
    for pr in d['pairs']:
        g10, g9 = rp[pr['id']]
        o = pr['orig_res']
        if g9 and g9.get('res') is not None:
            same = g9['res'] == o and g9.get('log') == pr['orig_log']
            rep += same
            ctl = '再現' if same else f"{mark(g9['res'])} 不一致*"
            base = o if same else g9['res']
        else:
            ctl, base = '-', o
        if g10 and g10.get('res') is not None:
            new = g10['res']
            ch = '負→勝' if base != 1 and new == 1 else '勝→負' if base == 1 and new != 1 else '同じ'
            a_up += ch == '負→勝'
            b_dn += ch == '勝→負'
            nice = sum(1 for m in g10.get('mv', []) if m[1] == EMP and m[2] == ICE)
            cells = [mark(new), ch, str(g10.get('turns')), str(nice)]
        else:
            cells = ['-', '-', '-', '-']
        s = pr['src'].split('|')
        L.append(f"| {pr['id']} | {s[0][:8]} | {s[1]} | {jp(pr['my_order'])} | {jp(pr['opp_order'])} | {pr['seed']} | "
                 f"{mark(o)} | {ctl} | " + ' | '.join(cells) + ' |')
    L += ['', f'合計: 負→勝 {a_up}、勝→負 {b_dn}、純増 {a_up - b_dn:+d}、{Bs}対照の再現数 {rep}/{len(d["pairs"])}'
          f'（対照 {n_ct} 戦済み。* は元と違う組で、その組の基準は対照の結果）', '']
    # 3 deep
    L += ['## 3. 6 手読みの構築別勝率', '',
          f'| 構築 | 題名 | 理由 | 相手の選出 | {Bs}の選出 | {P}の選出 | {Bs} 5戦 | {P} 5戦 | 差 | 判定決着 {Bs}/{P} |',
          '|---|---|---|---|---|---|---|---|---|---|']
    tot = {P: [0, 0], Bs: [0, 0]}
    emp = {P: [0, 0], Bs: [0, 0]}
    for kid, pl in dg['plan'].items():
        cells, wins, jud = {}, {}, {}
        for tag in (Bs, P):
            gs = [G.get(f'deep|{tag}|{kid}|{k}') for k in range(dg['games'])]
            gs = [g if g and g.get('res') is not None else None for g in gs]
            cells[tag] = ''.join(mark(g['res']) if g else '-' for g in gs)
            ok_ = [g for g in gs if g]
            wins[tag] = sum(g['res'] == 1 for g in ok_)
            jud[tag] = sum(bool(g.get('judged')) for g in ok_)
            tot[tag][0] += wins[tag]
            tot[tag][1] += len(ok_)
            if EMP in pl[tag]['my_order']:
                emp[tag][0] += wins[tag]
                emp[tag][1] += len(ok_)
        L.append(f"| {kid[:8]} | {pl['title'][:22]} | {'・'.join(pl['why'])} | {jp(pl['opp_order'])} | "
                 f"{jp(pl[Bs]['my_order'])} | {jp(pl[P]['my_order'])}{' 緩和' if pl[P].get('relaxed') else ''} | {cells[Bs]} | {cells[P]} | "
                 f"{wins[P] - wins[Bs]:+d} | {jud[Bs]}/{jud[P]} |")
    pc = lambda w, n: f'{100 * w / n:.0f}% ({w}/{n})' if n else '-'
    dd = f"{100 * (tot[P][0] / tot[P][1] - tot[Bs][0] / tot[Bs][1]):+.0f}pt" if tot[P][1] and tot[Bs][1] else '-'
    L += ['', f'合計: {Bs} {pc(*tot[Bs])}、{P} {pc(*tot[P])}、差 {dd}（勝ち数の差 {tot[P][0] - tot[Bs][0]:+d}）',
          f'{EMP}を選出した試合に限る: {Bs} {pc(*emp[Bs])}、{P} {pc(*emp[P])}', '']
    # 4 moves
    cols = [(f'再戦 {P}', [g for k, g in _games_of(d, f'replay|{P}|').items()]),
            (f'再戦 {Bs}対照', [g for k, g in _games_of(d, f'replay|{Bs}|').items()]),
            (f'6手 {P}', [g for k, g in _games_of(d, f'deep|{P}|').items()]),
            (f'6手 {Bs}', [g for k, g in _games_of(d, f'deep|{Bs}|').items()])]
    mvnames = ['なみのり', 'あくび', ICE, 'ステルスロック', 'クイックターン']
    st = [_emp_stats(gs, mvnames) for _, gs in cols]
    L += [f'## 4. {EMP}の技の使用回数', '', '| 項目 | ' + ' | '.join(c for c, _ in cols) + ' |', '|---|---|---|---|---|']
    L.append('| 戦数（うち場に出た試合） | ' + ' | '.join(f"{s['games']}（{s['field']}）" for s in st) + ' |')
    L.append('| 場に出たターン数 | ' + ' | '.join(str(s['turns']) for s in st) + ' |')
    for m in mvnames:
        L.append(f'| {m} | ' + ' | '.join(str(s['use'].get(m, 0)) for s in st) + ' |')
    for r in ('hit', 'miss', 'protect', 'immune', 'none', 'unknown'):
        L.append(f'| {ICE} {r} | ' + ' | '.join(str(s['ice'][r]) for s in st) + ' |')
    L.append(f'| {ICE} を撃った試合 / 場に出た試合 | ' + ' | '.join(f"{s['with_ice']}/{s['field']}" for s in st) + ' |')
    L += ['', f'{ICE} を当てた相手（回数、うち倒した回数）:']
    for c, s in zip([c for c, _ in cols], st):
        tg = ' '.join(f'{k}{v}' for k, v in sorted(s['targets'].items(), key=lambda x: -x[1])) or '-'
        L.append(f"- {c}: {tg}（倒した {s['kills']}）")
    L.append('')
    # 5 verdict
    r10 = [g for _, gs in (cols[0], cols[2]) for g in gs]
    f10 = sum(1 for g in r10 if any(l[0] == EMP for l in g.get('log', [])))
    i10 = sum(1 for g in r10 if any(l[0] == EMP for l in g.get('log', [])) and
              any(m[1] == EMP and m[2] == ICE for m in g.get('mv', [])))
    net = a_up - b_dn
    dwin = tot[P][0] - tot[Bs][0]
    complete = n_rp == len(d['pairs']) and n_ct == len(d['pairs']) and n_dp[P] == n_dp[Bs] == len(dg['plan']) * dg['games']
    if n_ct and (len(d['pairs']) - n_ct) + rep < 18:
        v = f'判断不能（再現性）: {Bs}対照の再現 {rep}/{len(d["pairs"])} が 18 未満（不一致が確定）'
    elif f10 and i10 / f10 < 0.2:
        v = f'判断不能（技が使われていない）: {EMP}が場に出た {P} の試合 {f10} 戦のうち{ICE}を撃ったのは {i10} 戦（{100 * i10 / f10:.0f}%）'
    elif (net <= 0 and dwin <= 0) or dwin <= -3:
        v = f'不採用: 再戦の純増 {net:+d}、6 手読みの勝ち数差 {dwin:+d}'
    elif net >= 3 and dwin >= 0:
        v = f'採用: 再戦の純増 {net:+d}、6 手読みの勝ち数差 {dwin:+d}（有意とは言えない。悪化の兆候が無く改善の方向、という意味）'
    else:
        v = (f'判断不能（差が小さい）: 再戦の純増 {net:+d}、6 手読みの勝ち数差 {dwin:+d}。追加で回すなら、'
             '6 手読みを差が出た 1 構築で 10 戦ずつ増やす')
    L += ['## 5. 判定', '', ('' if complete else '（途中の結果からの暫定。戦数がそろっていない）\n\n') + '**' + v + '**', '',
          f'- {Bs}対照の再現 {rep}/{len(d["pairs"])}（対照 {n_ct} 戦済み）',
          f'- {ICE} を撃った試合 {i10}/{f10}（{EMP}が場に出た {P} の試合）',
          f'- 再戦の純増 {net:+d}（負→勝 {a_up}、勝→負 {b_dn}）、6 手読みの勝ち数 {Bs} {tot[Bs][0]} / {P} {tot[P][0]}', '']
    # 6 notes
    L += ['## 6. 所見', '']
    for pr in d['pairs']:
        g10, g9 = rp[pr['id']]
        if not (g10 and g10.get('res') is not None):
            continue
        base = g9['res'] if g9 and g9.get('res') is not None and (g9['res'] != pr['orig_res'] or g9.get('log') != pr['orig_log']) \
            else pr['orig_res']
        if (base == 1) == (g10['res'] == 1):
            continue
        ices = [f"T{m[0]}→{m[3]}({m[4]})" for m in g10.get('mv', []) if m[1] == EMP and m[2] == ICE]
        yawn = sum(1 for l in pr['orig_log'] if l[1] == 'あくび')
        L.append(f"- {pr['id']} {'負→勝' if g10['res'] == 1 else '勝→負'}: {ICE} {' '.join(ices) or 'なし'}、"
                 f"元の試合のあくび {yawn} 回、{P} {g10.get('turns')}T（元 {pr['orig_turns']}T）")
    if L[-1] == '':
        L.append('- 変化した組はまだありません')
    txt = '\n'.join(L) + '\n'
    out = a.out or ADJ_REPORT(a.party)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, 'w', encoding='utf-8').write(txt)
    print(f'{out} に書きました（再戦 {n_rp}/対照 {n_ct}、6 手読み {n_dp[P]}/{n_dp[Bs]}）')


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('cores').set_defaults(f=cmd_cores)
    p = sub.add_parser('plan')
    p.add_argument('--force', action='store_true')
    p.set_defaults(f=cmd_plan)
    sub.add_parser('check-select').set_defaults(f=cmd_check_select)
    sub.add_parser('selftest').set_defaults(f=cmd_selftest)
    p = sub.add_parser('one')
    p.add_argument('team')
    p.add_argument('--mode', default='on', choices=['on', 'off'])
    p.add_argument('--k', type=int, default=0)
    p.add_argument('--depth', type=int, default=5)
    p.set_defaults(f=cmd_one)
    p = sub.add_parser('run')
    p.add_argument('--mode', default='both', choices=['on', 'off', 'both'])
    p.add_argument('--core')
    p.add_argument('--teams')
    p.add_argument('--games', type=int, default=NGAMES)
    p.add_argument('--depth', type=int, default=5)
    p.add_argument('--procs', type=int, default=os.cpu_count() or 1)
    p.add_argument('--max-games', type=int, default=0, dest='max_games')
    p.add_argument('--rules')
    p.add_argument('--force', action='store_true')
    p.set_defaults(f=cmd_run)
    p = sub.add_parser('report')
    p.add_argument('--out')
    p.set_defaults(f=cmd_report)
    def common(p, procs=False):
        p.add_argument('--party', default='R10')
        p.add_argument('--base', default='R9')
        if procs:
            p.add_argument('--procs', type=int, default=os.cpu_count() or 1)
            p.add_argument('--max-games', type=int, default=0, dest='max_games')

    p = sub.add_parser('check-diff')
    common(p)
    p.set_defaults(f=cmd_check_diff)
    p = sub.add_parser('adjust-plan')
    common(p)
    p.add_argument('--force', action='store_true')
    p.add_argument('--depth', type=int, default=6)
    p.set_defaults(f=cmd_adjust_plan)
    p = sub.add_parser('replay')
    common(p, True)
    p.add_argument('--no-control', action='store_true', dest='no_control')
    p.set_defaults(f=cmd_replay)
    p = sub.add_parser('deep')
    common(p, True)
    p.add_argument('--depth', type=int, default=6)
    p.add_argument('--games', type=int, default=NGAMES)
    p.set_defaults(f=cmd_deep)
    p = sub.add_parser('adjust-report')
    common(p)
    p.add_argument('--out')
    p.set_defaults(f=cmd_adjust_report)
    sub.add_parser('adjust-selftest').set_defaults(f=cmd_adjust_selftest)
    a = ap.parse_args()
    r = a.f(a)
    if r is False:
        sys.exit(1)


if __name__ == '__main__':
    main()
