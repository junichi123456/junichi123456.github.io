"""Party design: build our six from scratch against the strong builds learned so far (data/known_teams.json).

  python design.py pool                  the candidate pool (species + the set strong players run)
  python design.py run [--depth 1]       play every ordered trio of the pool against the likely selections of every
                                         target team (resumable cache logs/design/games_d{depth}.jsonl)
  python design.py rank [--top 15]       score every legal party (6 of the pool) from the cached games
  python design.py verify i,j,k,..       re-play the best orders of a party with fresh seeds at depth 3

Why a trio cache: a game depends only on the ordered trio of ours (with its sets) and the ordered trio of theirs, so
parties that share members share games. A party's score then costs nothing once the pool's trios are played.
Score of an order vs a team = 0.5 * (win rate against their worst selection) + 0.5 * (weighted win rate);
score of a party vs a team = its best order; party score = weighted mean over target teams.
"""
import itertools, json, os, sys, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle as B  # noqa: E402
import prep  # noqa: E402
import refine as R  # noqa: E402
from calc import Mon, POKE  # noqa: E402
import sets as _sets  # noqa: E402

OUT_D = os.path.join(HERE, '..', 'logs', 'design')
ART_P = os.path.join(HERE, 'data', 'article_sets.json')
CURRENT = ['ルカリオ', 'ガブリアス', 'アシレーヌ', 'ヒートロトム', 'ミミッキュ', 'メタグロス']
EXTRA = ['カバルドン', 'リザードン', 'イダイトウ', 'ボーマンダ', 'ブリジュラス', 'セグレイブ', 'カイリュー', 'グソクムシャ']
MAX_TEAMS = 45
MAX_OPP_ORDERS = 8


def targets():
    ts = R.teams()
    out = []
    for t in ts:
        if len(t['team']) != 6:
            continue
        if any(B._base(m['name']) not in POKE for m in t['team']):
            continue
        r = t.get('rating') or {}
        rank = r.get('rank') or 10 ** 6
        pts = max(r.get('final') or 0, r.get('peak') or 0)
        out.append((rank, -pts, t))
    out.sort(key=lambda x: (x[0], x[1]))
    return [t for _, _, t in out[:MAX_TEAMS]]


def team_weight(t):
    r = t.get('rating') or {}
    rank = r.get('rank') or 10 ** 6
    pts = max(r.get('final') or 0, r.get('peak') or 0)
    return 1.0 if rank <= 300 or pts >= 2300 else 0.7


def _set_to_mon(b, e):
    mega = e.get('mega')
    ap = {k: v for k, v in (e.get('ap') or {}).items() if v}
    if mega:
        return Mon(mega, e['nature'], ap, e.get('mega_ability') or POKE[mega]['ab'][0], e['item'], e['moves'], label=b)
    return Mon(b, e['nature'], ap, e['ability'], e['item'], e['moves'], label=b)


def pool():
    """{base: Mon}: the current party's own set for its six, the most common article set for the others."""
    art = json.load(open(ART_P, encoding='utf-8'))
    cur = {B.BASE_OF.get(m.species, m.species): m for m in B.TEAM}
    out, used = {}, set()
    for b in CURRENT:
        out[b] = cur[b]
        used.add(cur[b].item)
    for b in EXTRA:
        lst = sorted(art.get(b, []), key=lambda e: -len(e['teams']))
        for e in lst:
            if e['item'] in used:        # one item per party: take the most common set with a free item
                continue
            try:
                out[b] = _set_to_mon(b, e)
                used.add(e['item'])
                break
            except Exception as ex:      # unknown move etc.
                print('skip set', b, ex)
    return out


def use_pool(p):
    B.TEAM[:] = list(p.values())
    B.MY.clear()
    B.MY.update(B.my_sets())
    B._OPP_CACHE.clear()


def orders_of(names):
    out = []
    for c in itertools.combinations(names, 3):
        for lead in c:
            out.append((lead,) + tuple(x for x in c if x != lead))
    return out


def opp_orders(t):
    """[(trip_id, weight, order)] for the target team: their likely selections."""
    R._ctx(t['id'])
    opp6 = [B._base(m['name']) for m in t['team']]
    trips = prep.opp_trips(t, opp6)
    flat = []
    for ti, (pw, oos) in enumerate(trips):
        for oo in oos:
            flat.append((ti, pw / len(oos), tuple(oo)))
    flat.sort(key=lambda x: -x[1])
    flat = flat[:MAX_OPP_ORDERS]
    tot = sum(w for _, w, _ in flat) or 1
    return [(ti, w / tot, o) for ti, w, o in flat]


# ---------------------------------------------------------------- games

def _job(args):
    o, oo, kid, seed, depth = args
    return R.game((list(o), list(oo), kid, seed, depth))[0]


def cache_path(depth):
    os.makedirs(OUT_D, exist_ok=True)
    return os.path.join(OUT_D, f'games_d{depth}.jsonl')


def load_cache(depth):
    c = {}
    p = cache_path(depth)
    if os.path.exists(p):
        for ln in open(p, encoding='utf-8'):
            try:
                k, v = json.loads(ln)
                c[tuple(map(tuple, k[:2])) + (k[2],)] = v
            except Exception:
                pass
    return c


def run(depth=1, only=None, batch=4000):
    p = pool()
    use_pool(p)
    names = list(p)
    ords = orders_of(names)
    ts = targets()
    cache = load_cache(depth)
    jobs = []
    for t in ts:
        oos = opp_orders(t)
        for o in ords:
            for _, _, oo in oos:
                if (o, oo, t['id']) not in cache:
                    jobs.append((o, oo, t['id'], zlib.crc32(repr((o, oo, 'dz')).encode()) & 0x7fffffff, depth))
    print(f'pool {len(names)} mons, {len(ords)} orders, {len(ts)} teams; {len(jobs)} games to play (depth {depth})', flush=True)
    t0 = time.time()
    f = open(cache_path(depth), 'a', encoding='utf-8')
    for i in range(0, len(jobs), batch):
        part = jobs[i:i + batch]
        res = prep.pool_map(_job, part)
        for j, r in zip(part, res):
            f.write(json.dumps([[list(j[0]), list(j[1]), j[2]], r], ensure_ascii=False) + '\n')
        f.flush()
        done = i + len(part)
        el = time.time() - t0
        print(f'{done}/{len(jobs)}  {el:.0f}s  eta {el / done * (len(jobs) - done):.0f}s', flush=True)
    f.close()


# ---------------------------------------------------------------- scoring

def score_table(depth=1):
    """{(order, kid): score}, per-team weights."""
    p = pool()
    use_pool(p)
    ts = targets()
    cache = load_cache(depth)
    tab, tw = {}, {}
    for t in ts:
        oos = opp_orders(t)
        tw[t['id']] = team_weight(t)
        trips = {}
        for ti, w, oo in oos:
            trips.setdefault(ti, []).append((w, oo))
        for o in orders_of(list(p)):
            worst, avg, ok = 1.0, 0.0, True
            for ti, lst in trips.items():
                tw_ = sum(w for w, _ in lst)
                v = 0.0
                for w, oo in lst:
                    r = cache.get((o, oo, t['id']))
                    if r is None:
                        ok = False
                        break
                    v += w * (1.0 if r == 1 else 0.5 if r == 0 else 0.0)
                if not ok:
                    break
                avg += v
                worst = min(worst, v / tw_)
            if ok:
                tab[(o, t['id'])] = 0.5 * worst + 0.5 * avg
    return p, ts, tab, tw


def party_score(names, ts, tab, tw, detail=False):
    ords = orders_of(names)
    tot, wsum, per = 0.0, 0.0, {}
    for t in ts:
        best = max((tab.get((o, t['id']), 0.0) for o in ords), default=0.0)
        per[t['id']] = best
        tot += tw[t['id']] * best
        wsum += tw[t['id']]
    return (tot / wsum, per) if detail else tot / wsum


ITEM_FREE = True


def legal(names, p):
    items = [p[n].item for n in names]
    return len(set(items)) == 6


def rank(top=15, depth=1):
    p, ts, tab, tw = score_table(depth)
    names = list(p)
    rows = []
    for c in itertools.combinations(names, 6):
        if not legal(c, p):
            continue
        s, per = party_score(c, ts, tab, tw, True)
        low = sorted(per.values())[:5]
        rows.append((s, sum(low) / len(low), c, per))
    rows.sort(key=lambda x: -x[0])
    cur = next((r for r in rows if set(r[2]) == set(CURRENT)), None)
    print(f'{len(rows)} legal parties, {len(ts)} teams')
    if cur:
        print(f'現在: {cur[0]:.3f} (下位5構築の平均 {cur[1]:.3f}) 順位 {rows.index(cur) + 1}', ' '.join(cur[2]))
    for i, (s, low, c, per) in enumerate(rows[:top]):
        print(f'{i + 1:2d}. {s:.3f} (下位5 {low:.3f}) ' + ' '.join(c))
    return rows, p, ts, tab, tw


def main():
    a = sys.argv[1:]
    depth = int(a[a.index('--depth') + 1]) if '--depth' in a else 1
    if a[:1] == ['pool']:
        for b, m in pool().items():
            print(b, m.species, m.item, m.ability, m.nature, dict(m.spv), '/'.join(m.moves))
    elif a[:1] == ['run']:
        run(depth)
    elif a[:1] == ['rank']:
        rank(int(a[a.index('--top') + 1]) if '--top' in a else 15, depth)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
