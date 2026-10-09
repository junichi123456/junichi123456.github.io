"""Differential test: engine.py vs Pokémon Showdown (champions mod) on random one-turn scenarios.

  python sd/difftest.py <pokemon-showdownのフォルダ> [件数] [seed]

Random teams come from the usage-based sets (sets.py). Each scenario randomizes HP, status, stat stages,
weather/terrain and hazards, picks random legal actions for both sides, and runs one turn in both engines
with the deterministic most-likely RNG (engine.TestRNG ⇔ sd/oracle.js). Any difference is printed.
"""
import json, os, random, subprocess, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import dex  # noqa: E402
import engine as E  # noqa: E402
import sets  # noqa: E402

NAT_EN = {'いじっぱり': 'Adamant', 'ようき': 'Jolly', 'ひかえめ': 'Modest', 'おくびょう': 'Timid', 'わんぱく': 'Impish',
          'ずぶとい': 'Bold', 'しんちょう': 'Careful', 'おだやか': 'Calm', 'ゆうかん': 'Brave', 'れいせい': 'Quiet',
          'のんき': 'Relaxed', 'なまいき': 'Sassy', 'むじゃき': 'Naive', 'せっかち': 'Hasty', 'やんちゃ': 'Naughty',
          'うっかりや': 'Rash', 'さみしがり': 'Lonely', 'おっとり': 'Mild', 'おとなしい': 'Gentle', 'のうてんき': 'Lax',
          'まじめ': 'Serious', 'がんばりや': 'Hardy', 'すなお': 'Docile', 'てれや': 'Bashful', 'きまぐれ': 'Quirky'}


def random_set(rng, species):
    cands = sets.usage_candidates(species)
    if not cands:
        return None
    c = rng.choices(cands, weights=[x.prior for x in cands])[0]
    b = c.base
    moves = [m for m in b.moves if dex.move_id(m)]
    if not moves:
        return None
    nat = b.nature.strip()
    ap = {k: v for k, v in b.spv.items() if v}
    return dict(species=b.species, nature=nat, ap=ap, ability=b.ability, item=b.item or '', moves=moves)


EXTRA_FORMS = {'イルカマン(マイティ)', 'ミミッキュ(ばれたすがた)', 'モルペコ(はらぺこ)', 'ポワルン(たいよう)', 'ポワルン(あまみず)',
               'ポワルン(ゆきぐも)', 'ブレードギルガルド'}
ITEM_POOL = [k for k, v in dex.ITEMS.items() if not v.get('megaStone')]


def wild_set(rng, species):
    """Random legal set: any learnable moves, any of the species' abilities, any legal item."""
    s = dex.SPECIES[species]
    learn = dex._C['learnsets'].get(species) or []
    learn = [m for m in learn if dex.move_id(m)]
    if len(learn) < 1:
        return None
    abil = [''.join(c for c in a.lower() if c.isalnum()) for a in s['abilities'].values()]
    abil = [a for a in abil if a in dex.ABILITIES]
    stones = [k for k, v in dex.MEGA_STONE.items() if species in v]
    item = rng.choice(ITEM_POOL + stones * 8)
    ap, left = {}, 66
    for k in rng.sample(['hp', 'atk', 'def', 'spa', 'spd', 'spe'], 6):
        v = min(32, left, rng.choice([0, 0, 2, 16, 32]))
        if v:
            ap[k] = v
            left -= v
    return dict(species=species, nature=rng.choice(list(NAT_EN)), ap=ap, ability=rng.choice(abil) if abil else '',
                item=item, moves=rng.sample(learn, min(4, len(learn))))


def sd_set(s):
    sp = dex.SPECIES[s['species']]
    ab = dex.ab_id(s['ability'])
    it = dex.item_id(s['item'])
    return {'species': sp['name'], 'name': sp['name'], 'item': dex.ITEMS[it]['name'] if it else '',
            'ability': dex.ABILITIES[ab]['name'] if ab else '', 'moves': [dex.move_id(m) for m in s['moves']],
            'nature': NAT_EN.get(s['nature'], 'Serious'),
            'evs': {k: s['ap'].get(k, 0) for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')},
            'ivs': {k: 31 for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')}, 'level': 50, 'gender': ''}


def build(team):
    return [E.make_mon(s['species'], s['nature'], s['ap'], s['ability'], s['item'], s['moves']) for s in team]


def scenario(rng, wild=False):
    if wild:
        pool = [n for n, v in dex.SPECIES.items() if not v.get('isMega') and n not in EXTRA_FORMS and
                dex._C['learnsets'].get(n)]
    else:
        pool = [n for n in sets.USAGE if n in dex.SPECIES]
    teams = []
    for _ in range(2):
        t = []
        while len(t) < 3:
            sp = rng.choice(pool)
            if any(x['species'] == sp for x in t):
                continue
            s = wild_set(rng, sp) if wild else random_set(rng, sp)
            if s:
                t.append(s)
        teams.append(t)
    sc = {'teams': teams, 'state': [], 'field': {}}
    for i in range(2):
        mons = []
        for j in range(3):
            d = {}
            if rng.random() < 0.5:
                d['hp_frac'] = rng.choice([0.15, 0.3, 0.5, 0.7, 0.9])
            if rng.random() < 0.2:
                d['status'] = rng.choice(['brn', 'par', 'psn', 'tox', 'slp'])
                d['stime'] = rng.choice([1, 2, 3])
                d['tox'] = rng.choice([0, 1, 2])
            if rng.random() < 0.3 and j == 0:
                d['boosts'] = {rng.choice(['atk', 'def', 'spa', 'spd', 'spe']): rng.choice([-2, -1, 1, 2])}
            if rng.random() < 0.1:
                d['item'] = ''
            mons.append(d)
        cond = {}
        if rng.random() < 0.25:
            cond['stealthrock'] = True
        if rng.random() < 0.1:
            cond['spikes'] = rng.choice([1, 2])
        if rng.random() < 0.1:
            cond[rng.choice(['reflect', 'lightscreen'])] = rng.choice([2, 4])
        if rng.random() < 0.08:
            cond['tailwind'] = 3
        sc['state'].append({'mons': mons, 'cond': cond})
    if rng.random() < 0.3:
        sc['field']['weather'] = rng.choice(['sunnyday', 'raindance', 'sandstorm', 'snowscape'])
        sc['field']['wturns'] = rng.choice([2, 3, 5])
    if rng.random() < 0.2:
        sc['field']['terrain'] = rng.choice(['electricterrain', 'grassyterrain', 'mistyterrain', 'psychicterrain'])
        sc['field']['tturns'] = rng.choice([2, 4])
    if rng.random() < 0.1:
        sc['field']['pseudo'] = {'trickroom': rng.choice([2, 4])}
    return sc


def engine_state(sc):
    st = E.new_state(build(sc['teams'][0]), build(sc['teams'][1]))
    st = E.start(st, E.TestRNG())
    f = sc['field']
    if 'weather' in f:
        st.weather, st.wturns = f['weather'], f['wturns']
    if 'terrain' in f:
        st.terrain, st.tturns = f['terrain'], f['tturns']
    for k, v in f.get('pseudo', {}).items():
        st.pseudo[k] = v
    for i in range(2):
        s = st.sides[i]
        for j, d in enumerate(sc['state'][i]['mons']):
            m = s.mons[j]
            if 'hp_frac' in d:
                m.hp = max(1, int(m.maxhp * d['hp_frac']))
            if 'status' in d:
                m.status = d['status']
                m.stime = d['stime']
                m.tox = d['tox']
            if 'boosts' in d:
                for k, v in d['boosts'].items():
                    m.boosts[k] = v
            if 'item' in d:
                m.item = d['item']
        for k, v in sc['state'][i]['cond'].items():
            s.cond[k] = v
    return st


def oracle_input(sc, st, acts):
    out = {'p1': None, 'p2': None, 'field': sc['field'], 'choices': []}
    for i, key in ((0, 'p1'), (1, 'p2')):
        s = st.sides[i]
        mons = []
        for j, m in enumerate(s.mons):
            d = {'hp': m.hp, 'boosts': {k: v for k, v in m.boosts.items()}}
            if m.status:
                d['status'] = m.status
                d['stime'] = m.stime
                d['tox'] = m.tox
            d['item'] = m.item
            mons.append(d)
        out[key] = {'team': [sd_set(x) for x in sc['teams'][i]], 'mons': mons, 'cond': dict(s.cond)}
    ch = []
    for i in range(2):
        a = acts[i]
        m = st.active(i)
        if a[0] == 'm':
            k = list(m.moves).index(a[1]) + 1
            ch.append(f'move {k}' + (' mega' if a[2] else ''))
        else:
            ch.append(f'switch {a[1] + 1}')
    out['choices'] = [ch]
    return out


def compare(st, res):
    diffs = []
    for i, key in ((0, 'p1'), (1, 'p2')):
        sd = {m['species']: m for m in res[key]}
        for m in st.sides[i].mons:
            name = (m.vol['transformed'][0] if 'transformed' in m.vol else m.form).name
            o = sd.get(name) or next((v for k, v in sd.items() if k.split('-')[0] == name.split('-')[0]), None)
            if o is None:
                diffs.append(f'{key} {name}: missing in showdown {list(sd)}')
                continue
            hp = 0 if m.fainted else m.hp
            if hp != o['hp']:
                diffs.append(f"{key} {name} hp {hp} vs {o['hp']}")
            if not m.fainted and (m.status or '') != (o['status'] or ''):
                diffs.append(f"{key} {name} status {m.status!r} vs {o['status']!r}")
            b = {k: v for k, v in m.boosts.items() if v}
            if not m.fainted and b != o['boosts']:
                diffs.append(f"{key} {name} boosts {b} vs {o['boosts']}")
            if not m.fainted and (m.item or '') != (o['item'] or ''):
                diffs.append(f"{key} {name} item {m.item!r} vs {o['item']!r}")
            act = st.sides[i].act == m.idx and not m.fainted
            if act != o['active'] and not m.fainted:
                diffs.append(f"{key} {name} active {act} vs {o['active']}")
        oc = {k: v for k, v in res[key + 'cond'].items()}
        mc = {k: v for k, v in st.sides[i].cond.items() if v}
        if set(oc) != set(mc):
            diffs.append(f'{key} side conds {mc} vs {oc}')
    if (st.weather or '') != (res['weather'] or ''):
        diffs.append(f"weather {st.weather!r} vs {res['weather']!r}")
    if (st.terrain or '') != (res['terrain'] or ''):
        diffs.append(f"terrain {st.terrain!r} vs {res['terrain']!r}")
    return diffs


def sd_choice(st, i, a, order):
    m = st.active(i)
    if a[0] == 's':
        name = dex.SPECIES[st.sides[i].mons[a[1]].name]['name']
        return f'switch {order[i].index(name) + 1}'
    if a[1] in ('recharge', 'struggle') or any(k in m.vol for k in ('lockedmove', 'twoturnmove', 'mustrecharge', 'uproar')):
        return 'move 1'
    return f'move {list(m.moves).index(a[1]) + 1}' + (' mega' if len(a) > 2 and a[2] else '')


def multi(proc, rng, k, turns, wild, verbose=False):
    sc = scenario(rng, wild)
    try:
        st = engine_state(sc)
    except Exception as e:
        print('build error', e)
        return None
    inp = oracle_input(sc, st, [('m', st.active(0).moves[0], False), ('m', st.active(1).moves[0], False)])
    inp['cmd'] = 'new'
    del inp['choices']
    proc.stdin.write(json.dumps(inp, ensure_ascii=False) + '\n')
    proc.stdin.flush()
    res = json.loads(proc.stdout.readline())
    if 'error' in res:
        print(f'#{k} oracle error: {res["error"]}')
        return None
    order = res['order']
    for t in range(turns):
        acts = [rng.choice(E.actions(st, i)) if st.active(i).alive else None for i in range(2)]
        ch = [sd_choice(st, i, acts[i], order) if acts[i] else 'pass' for i in range(2)]
        proc.stdin.write(json.dumps({'cmd': 'turn', 'choices': ch}) + '\n')
        proc.stdin.flush()
        res = json.loads(proc.stdout.readline())
        if 'error' in res:
            print(f'#{k} t{t + 1} oracle error: {res["error"]} acts={acts} ch={ch} order={order}')
            return None
        log = []
        try:
            st = E.step(st, acts[0], acts[1], E.TestRNG(), log=log)
        except Exception as e:
            import traceback
            print(f'#{k} t{t + 1} ENGINE ERROR {acts}: {e}')
            traceback.print_exc()
            return False
        d = compare(st, res)
        if verbose:
            print(f'--- turn {t + 1} {acts} {ch}')
            print('   state:', [(st.active(i).name, st.active(i).hp, st.active(i).vol, {k: v for k, v in st.active(i).boosts.items() if v}) for i in range(2)])
            print('   engine:', log)
            print('   showdown:', [l for l in res['log'] if l.strip('|')])
        if d:
            print(f'#{k} turn {t + 1} actions {acts} {ch}')
            print('   teams:', [[(x['species'], x['ability'], x['item'], x['moves']) for x in tm] for tm in sc['teams']])
            for x in d:
                print('   ', x)
            print('   engine log:', log)
            print('   showdown log:', [l for l in res['log'] if l.strip('|')][:60])
            return False
        order = res['order']
        if st.done() is not None or res.get('ended'):
            break
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    sdroot = args[0]
    n = int(args[1]) if len(args) > 1 else 50
    seed = int(args[2]) if len(args) > 2 else 1
    rng = random.Random(seed)
    turns = next((int(a.split('=')[1]) for a in sys.argv if a.startswith('--turns=')), 0)
    wild = '--wild' in sys.argv
    if turns:
        proc = subprocess.Popen(['node', os.path.join(HERE, 'sd', 'oracle.js'), sdroot], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True, encoding='utf-8')
        ok = bad = 0
        only = next((int(a.split('=')[1]) for a in sys.argv if a.startswith('--only=')), None)
        for k in range(n):
            if only is not None and k != only:
                continue
            r = multi(proc, random.Random(seed * 100003 + k), k, turns, wild, verbose=only is not None)
            if r is True:
                ok += 1
            elif r is False:
                bad += 1
        print(f'{ok}/{ok + bad} scenarios identical over {turns} turns')
        return
    proc = subprocess.Popen(['node', os.path.join(HERE, 'sd', 'oracle.js'), sdroot], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, encoding='utf-8')
    bad = 0
    for k in range(n):
        sc = scenario(rng)
        try:
            st = engine_state(sc)
        except Exception as e:
            print('build error', e)
            continue
        acts = []
        for i in range(2):
            a = E.actions(st, i)
            acts.append(rng.choice(a))
        inp = oracle_input(sc, st, acts)
        proc.stdin.write(json.dumps(inp, ensure_ascii=False) + '\n')
        proc.stdin.flush()
        res = json.loads(proc.stdout.readline())
        if 'error' in res:
            print(f'#{k} oracle error: {res["error"]}')
            continue
        log = []
        try:
            st2 = E.step(st, acts[0], acts[1], E.TestRNG(), log=log)
        except Exception as e:
            import traceback
            print(f'#{k} ENGINE ERROR {acts}: {e}')
            traceback.print_exc()
            bad += 1
            continue
        d = compare(st2, res)
        if d:
            bad += 1
            print(f'#{k} actions {acts}')
            print('   teams:', [[(x['species'], x['ability'], x['item']) for x in t] for t in sc['teams']])
            for x in d:
                print('   ', x)
            print('   engine log:', log)
            print('   showdown log:', [l for l in res['log'] if not l.startswith('|request')][:40])
    print(f'{n - bad}/{n} identical')


if __name__ == '__main__':
    main()
