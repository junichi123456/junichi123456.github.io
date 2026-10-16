"""6th slot: a mega-capable Pokémon that is clearly favoured against the four builds we lose to most.
  python megapick.py [--depth 2] [--topk 3]   -> logs/design/{a[a.index('--out') + 1] if '--out' in a else 'megapick'}_d{depth}.json
Core five (ガブリアス アシレーヌ ヒートロトム ミミッキュ メタグロス) + each candidate; the 30 orders containing the
candidate are replayed against every likely selection of the four teams."""
import json, os, sys, time, zlib, itertools
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import battle as B, prep, refine as R, design as D
HARD = ('db0baa2843d2bd4b', 'fc79a2c272f85520', '8cfae5073138dec9', 'bab22dcc629688e8')
CORE = ['ガブリアス', 'アシレーヌ', 'ヒートロトム', 'ミミッキュ', 'メタグロス']

def cands(any_species=False):
    art = json.load(open(D.ART_P, encoding='utf-8'))
    out = {}
    for b, v in art.items():
        if b in CORE:
            continue
        if any_species and len({t for e in v for t in e['teams']}) < 2:
            continue
        taken = {m.item for m in B.TEAM if B.BASE_OF.get(m.species, m.species) in CORE}
        for e in sorted(v, key=lambda e: -len(e['teams'])):
            if (e.get('mega') or any_species) and e['item'] not in taken:
                try:
                    out[b] = D._set_to_mon(b, e)
                    break
                except Exception:
                    pass
    return out

def main():
    a = sys.argv[1:]
    depth = int(a[a.index('--depth') + 1]) if '--depth' in a else 2
    D.MAX_OPP_ORDERS = 5
    D.MAX_TEAMS = 100
    cur = {B.BASE_OF.get(m.species, m.species): m for m in B.TEAM}
    core = {b: cur[b] for b in CORE}
    cs = cands('--all' in a)
    if '--custom' in a:      # user-specified Meganium: おくびょう S28 C32 (H 6) まもる/ソーラービーム/ウェザーボール/+1
        from calc import Mon
        mv = a[a.index('--custom') + 1]
        cs['メガニウム'] = Mon('メガメガニウム', 'おくびょう', {'hp': 6, 'spa': 32, 'spe': 28}, 'メガソーラー', 'メガニウムナイト',
                          ['まもる', 'ソーラービーム', 'ウェザーボール', mv], label='メガニウム')
    if '--only' in a:
        keep = a[a.index('--only') + 1].split(',')
        cs = {b: m for b, m in cs.items() if b in keep}
    tag = a[a.index('--seed') + 1] if '--seed' in a else 'mp'
    pool = dict(core); pool.update(cs)
    D.use_pool(pool)
    if '--gusoku' in a:   # every target team that runs Mega Gusokumusha
        ts = [t for t in D.targets() if any(B._base(m['name']) == 'グソクムシャ' for m in t['team'])]
        HARD_IDS = {t['id'] for t in ts}
    else:
        ts = [t for t in D.targets() if t['id'] in HARD]
        for t in R.teams():
            if t['id'] in HARD and t not in ts:
                ts.append(t)
    oo = {t['id']: D.opp_orders(t) for t in ts}
    jobs, plan = [], {}
    for c in [None] + list(cs):
        names = CORE + ([c] if c else [])
        ords = [o for o in D.orders_of(names) if c is None or c in o] if c else D.orders_of(CORE)
        plan[c] = ords
        for t in ts:
            for o in ords:
                for _, _, o2 in oo[t['id']]:
                    jobs.append((o, o2, t['id'], zlib.crc32(repr((o, o2, tag)).encode()) & 0x7fffffff, depth))
    print(len(jobs), 'games, depth', depth, flush=True)
    # resumable: every finished game is appended to a cache file; a restart only plays what is missing
    cp = os.path.join(D.OUT_D, f'mpcache_d{depth}.jsonl')
    done = {}
    if os.path.exists(cp):
        for ln in open(cp, encoding='utf-8'):
            try:
                k, v = json.loads(ln)
                done[json.dumps(k)] = v
            except Exception:
                pass
    todo = [j for j in jobs if json.dumps([list(j[0]), list(j[1]), j[2], j[3], j[4]]) not in done]
    print(len(todo), 'games to play (rest cached)', flush=True)
    f = open(cp, 'a', encoding='utf-8')
    for i in range(0, len(todo), 2000):
        part = todo[i:i + 2000]
        for j, x in zip(part, prep.pool_map(D._job, part)):
            k = [list(j[0]), list(j[1]), j[2], j[3], j[4]]
            done[json.dumps(k)] = x
            f.write(json.dumps([k, x], ensure_ascii=False) + '\n')
        f.flush()
        print(f'{i + len(part)}/{len(todo)}', flush=True)
    f.close()
    r = {(j[0], j[1], j[2]): done[json.dumps([list(j[0]), list(j[1]), j[2], j[3], j[4]])] for j in jobs}
    out = {}
    for c, ords in plan.items():
        per = {}
        for t in ts:
            trips = {}
            for ti, w, o2 in oo[t['id']]:
                trips.setdefault(ti, []).append((w, o2))
            sc = []
            for o in ords:
                worst, avg = 1.0, 0.0
                for ti, l in trips.items():
                    tw = sum(w for w, _ in l)
                    v = sum(w * (1 if r[(o, o2, t['id'])] == 1 else .5 if r[(o, o2, t['id'])] == 0 else 0) for w, o2 in l)
                    avg += v; worst = min(worst, v / tw)
                sc.append((0.5 * worst + 0.5 * avg, o))
            sc.sort(reverse=True)
            per[t['id']] = (round(sum(s for s, _ in sc[:3]) / 3, 3), list(sc[0][1]))
        out[c or '(核5体のみ)'] = per
    json.dump(out, open(os.path.join(D.OUT_D, f'{a[a.index('--out') + 1] if '--out' in a else 'megapick'}_d{depth}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    nm = {t['id']: t['title'][:10] for t in ts}
    for c, per in sorted(out.items(), key=lambda x: -min(v[0] for v in x[1].values())):
        print(f"{c:10s} min {min(v[0] for v in per.values()):.2f} " + ' '.join(f"{nm[k]}{v[0]:.2f}" for k, v in per.items()))

if __name__ == '__main__':
    main()
