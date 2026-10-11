"""Tune our least-used member against the teams we beat least (data/known_teams.json).

  python tune.py [--depth 2] [--seeds 3]

For every candidate (a different item / moves / nature-AP of the member, or another Pokémon in its slot):
  * the 30 orders that contain the candidate are played against every likely selection of the target teams
    (both sides reading `depth` turns ahead, real randomness, `seeds` games each); the 30 orders without it are
    played once as the shared baseline;
  * per target team the best order is taken worst-case first (the selection of theirs that beats us most),
    then by the average; the candidate's score is the mean of that over the target teams.
Results: logs/tune/<candidate>.json and logs/TUNING.md.
"""
import itertools, json, os, sys, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle as B  # noqa: E402
import prep  # noqa: E402
from calc import Mon  # noqa: E402

OUT_D = os.path.join(HERE, '..', 'logs', 'tune')
REPORT = os.path.join(HERE, '..', 'logs', 'TUNING.md')
SLOT = 'ギャラドス'                                   # the member being tuned / replaced
TARGETS = ('705822f24b8d974e', '0f829cd7dc5cfce1', '8cfae5073138dec9')   # エンペルカイリュー, 炎氷イエリザ, 重戦車

GY = dict(species='ギャラドス', ability='いかく')
CANDIDATES = [
    dict(GY, key='G0 現在の型', nature='わんぱく', ap={'hp': 32, 'atk': 2, 'def': 32}, item='ゴツゴツメット',
         moves=['たきのぼり', 'ゆきなだれ', 'でんじは', 'ちょうはつ']),
    dict(GY, key='G1 ソクノのみ', nature='わんぱく', ap={'hp': 32, 'atk': 2, 'def': 32}, item='ソクノのみ',
         moves=['たきのぼり', 'ゆきなだれ', 'でんじは', 'ちょうはつ']),
    dict(GY, key='G2 アイへ・ねっとう', nature='わんぱく', ap={'hp': 32, 'atk': 2, 'def': 32}, item='ゴツゴツメット',
         moves=['ねっとう', 'アイアンヘッド', 'でんじは', 'ちょうはつ']),
    dict(GY, key='G3 HDゴツメ', nature='しんちょう', ap={'hp': 32, 'atk': 2, 'spd': 32}, item='ゴツゴツメット',
         moves=['たきのぼり', 'アイアンヘッド', 'でんじは', 'ちょうはつ']),
    dict(GY, key='G4 竜舞ラム', nature='ようき', ap={'hp': 2, 'atk': 32, 'spe': 32}, item='ラムのみ',
         moves=['たきのぼり', 'アイアンヘッド', 'じしん', 'りゅうのまい']),
    dict(GY, key='G5 竜舞帯', nature='ようき', ap={'hp': 2, 'atk': 32, 'spe': 32}, item='たつじんのおび',
         moves=['たきのぼり', 'アイアンヘッド', 'じしん', 'りゅうのまい']),
    dict(GY, key='G6 メガギャラドス', nature='ようき', ap={'hp': 2, 'atk': 32, 'spe': 32}, item='ギャラドスナイト',
         moves=['たきのぼり', 'かみくだく', 'アイアンヘッド', 'りゅうのまい'], mega='メガギャラドス', mega_ability='かたやぶり'),
    dict(GY, key='G7 スカーフ', nature='いじっぱり', ap={'hp': 2, 'atk': 32, 'spe': 32}, item='こだわりスカーフ',
         moves=['たきのぼり', 'アイアンヘッド', 'じしん', 'ストーンエッジ']),
]
REPLACE = ['サーフゴー', 'ドドゲザン', 'メタグロス', 'ハッサム', 'ブリジュラス', 'エンペルト', 'ドヒドイデ',
           'アーマーガア', 'キラフロル', 'カバルドン']


# items must not repeat within our six (the other five hold these)
ITEM_FOR = {'ブリジュラス': 'たつじんのおび', 'ドヒドイデ': 'ゴツゴツメット', 'キラフロル': 'こだわりスカーフ',
            'カバルドン': 'ゴツゴツメット'}
FALLBACK_ITEMS = ['ゴツゴツメット', 'ラムのみ', 'シュカのみ', 'たつじんのおび', 'こだわりスカーフ']


def taken_items():
    return {m.item for m in B.TEAM if B.BASE_OF.get(m.species, m.species) != SLOT}


def replacement(sp):
    """A standard set for another Pokémon in the slot: the most likely usage/role set (no observations),
    with an item that none of the other five holds."""
    base, mega, _ = B._infer.best_set(sp, [], B.MY_TYPES, None)
    item = ITEM_FOR.get(sp, base.item)
    if item in taken_items():
        item = next(x for x in FALLBACK_ITEMS if x not in taken_items())
    c = dict(key=f'R {sp}', species=sp, nature=base.nature, ap=dict(base.spv), ability=base.ability,
             item=item, moves=list(base.moves))
    if mega:
        c.update(mega=mega.species, mega_ability=mega.ability)
    return c


def apply(c):
    """Put candidate c into our team in place of SLOT (in this process)."""
    if B.MY.get('_cand') == c['key']:
        return
    B.MY.pop(SLOT, None)
    if B.MY.get('_slot_now') not in (None, *others()):
        B.MY.pop(B.MY['_slot_now'], None)
    base = Mon(c['species'], c['nature'], c['ap'], c['ability'], c['item'], c['moves'], label=c['species'])
    mega = Mon(c['mega'], c['nature'], c['ap'], c['mega_ability'], c['item'], c['moves'], label=c['species']) \
        if c.get('mega') else None
    B.MY[c['species']] = (base, mega)
    B.MY['_cand'], B.MY['_slot_now'] = c['key'], c['species']
    B._OPP_CACHE.clear()


def game(args):
    order_, oorder, kid, seed, depth, cand = args
    if cand:
        apply(cand)
    return prep.game((order_, oorder, kid, seed, depth))


def others():
    return [B.BASE_OF.get(m.species, m.species) for m in B.TEAM if B.BASE_OF.get(m.species, m.species) != SLOT]


def orders_with(sp):
    out = []
    for pair in itertools.combinations(others(), 2):
        c = (sp,) + pair
        for lead in c:
            out.append([lead] + [x for x in c if x != lead])
    return out


def orders_without():
    out = []
    for c in itertools.combinations(others(), 3):
        for lead in c:
            out.append([lead] + [x for x in c if x != lead])
    return out


def run(jobs_spec, depth, seeds, offset=0):
    jobs, meta = [], []
    for o, t, oo, cand in jobs_spec:
        for sd in range(offset, offset + seeds):
            jobs.append((o, oo, t['id'], zlib.crc32(repr((o, oo, sd, 'tune')).encode()), depth, cand))
            meta.append((t['id'], ' → '.join(o), ' → '.join(oo)))
    res = prep.pool_map(game, jobs)
    wins = {}
    for (tid, o, oo), r in zip(meta, res):
        w = wins.setdefault(tid, {}).setdefault(o, {}).setdefault(oo, [0, 0])
        w[0] += r[0] == 1
        w[1] += 1
    return wins


def team_trips(t):
    opp6 = [B._base(m['name']) for m in t['team']]
    B.set_known_context(opp6)
    return [(p, oo) for p, oos in prep.opp_trips(t, opp6) for oo in oos]


def best_of(tw):
    """Best order of one team, worst case first: (worst, avg, order)."""
    rows = []
    for o, by in tw.items():
        rates = [w / n for w, n in by.values()]
        rows.append((min(rates), sum(w for w, _ in by.values()) / sum(n for _, n in by.values()), o))
    return max(rows)


def merge(*ws):
    """Add up {team: {order: {opp: [wins, games]}}} tables."""
    out = {}
    for w in ws:
        for tid, by in (w or {}).items():
            for o, opp in by.items():
                for oo, (a, n) in opp.items():
                    x = out.setdefault(tid, {}).setdefault(o, {}).setdefault(oo, [0, 0])
                    x[0] += a
                    x[1] += n
    return out


def score(w, teams):
    """Candidate's score from the orders that contain it: per team the best order (worst case first), averaged."""
    per = {t['id']: best_of(w[t['id']]) for t in teams if w.get(t['id'])}
    return (sum(v[0] for v in per.values()) / len(per), sum(v[1] for v in per.values()) / len(per), per)


def more(top=10, extra=3, depth=2, seeds=3):
    """Play `extra` more games per pairing for the `top` candidates and rank them on all games."""
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    teams = [t for t in data['teams'] if t['id'] in TARGETS]
    trips = {t['id']: team_trips(t) for t in teams}
    cands = CANDIDATES + [replacement(sp) for sp in REPLACE]
    first = {}
    for c in cands:
        cp = os.path.join(OUT_D, c['key'].replace(' ', '_') + '.json')
        if os.path.exists(cp):
            first[c['key']] = json.load(open(cp, encoding='utf-8'))
    ranked = sorted((c for c in cands if c['key'] in first), key=lambda c: tuple(-x for x in score(first[c['key']], teams)[:2]))
    chosen = ranked[:top]
    rows = []
    for c in chosen:
        cp = os.path.join(OUT_D, c['key'].replace(' ', '_') + '__more.json')
        if os.path.exists(cp):
            w2 = json.load(open(cp, encoding='utf-8'))
        else:
            t0 = time.time()
            w2 = run([(o, t, oo, c) for t in teams for o in orders_with(c['species']) for _, oo in trips[t['id']]],
                     depth, extra, offset=seeds)
            json.dump(w2, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
            print(c['key'], '+', extra, round(time.time() - t0), 's', flush=True)
        w = merge(first[c['key']], w2)
        wst, avg, per = score(w, teams)
        w1, a1, _ = score(first[c['key']], teams)
        rows.append({'cand': c, 'worst': wst, 'avg': avg, 'worst3': w1, 'avg3': a1,
                     'per_team': {t['title']: {'order': per[t['id']][2], 'worst': per[t['id']][0], 'avg': per[t['id']][1]}
                                  for t in teams}})
    rows.sort(key=lambda r: (-r['worst'], -r['avg']))
    json.dump(rows, open(os.path.join(OUT_D, 'summary6.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    n = seeds + extra
    L = [f'# 6枠目の調整：上位{top}候補の{n}戦評価（tune.py --more が自動生成）', '',
         f'対象: {", ".join(t["title"] for t in teams)}', f'両者{depth}手読み・乱数あり。各候補を入れた選出30通り×相手の想定選出ごとに{n}戦。',
         '構築ごとに、候補を入れた選出のうち「最も負けやすい相手選出への勝率」が最大の選出を取り、3構築で平均して順位を付けています。', '',
         f'| 順位 | 候補 | 型 | 最悪の相手選出への勝率（{n}戦） | 平均勝率（{n}戦） | 3戦時点（最悪/平均） | ' +
         ' | '.join(t['title'][:12] for t in teams) + ' |', '|' + '---|' * (6 + len(teams))]
    for i, r in enumerate(rows):
        c = r['cand']
        sp = Mon(c['species'], c['nature'], c['ap'], c['ability'], c['item'], c['moves']).sp_str()
        L.append(f"| {i + 1} | {c['key']} | {c['nature']} {sp} {c['item']} {'/'.join(c['moves'])} | {r['worst']:.0%} | "
                 f"{r['avg']:.0%} | {r['worst3']:.0%} / {r['avg3']:.0%} | " +
                 ' | '.join(f"{v['order']}（{v['worst']:.0%}/{v['avg']:.0%}）" for v in r['per_team'].values()) + ' |')
    open(os.path.join(HERE, '..', 'logs', 'TUNING6.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('→ logs/TUNING6.md')
    return rows


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv[1:]
    if '--more' in a:
        more(top=int(a[a.index('--top') + 1]) if '--top' in a else 10, extra=int(a[a.index('--more') + 1]))
        return
    depth = int(a[a.index('--depth') + 1]) if '--depth' in a else 2
    seeds = int(a[a.index('--seeds') + 1]) if '--seeds' in a else 3
    os.makedirs(OUT_D, exist_ok=True)
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    teams = [t for t in data['teams'] if t['id'] in TARGETS]
    trips = {t['id']: team_trips(t) for t in teams}
    cands = CANDIDATES + [replacement(sp) for sp in REPLACE]
    clash = [c['key'] for c in cands if c['item'] in taken_items()]
    assert not clash, f'items clash with the other five: {clash}'
    # baseline: orders without the slot (the candidate does not matter for them)
    bp = os.path.join(OUT_D, '_base.json')
    if os.path.exists(bp):
        base = json.load(open(bp, encoding='utf-8'))
    else:
        t0 = time.time()
        base = run([(o, t, oo, None) for t in teams for o in orders_without() for _, oo in trips[t['id']]], depth, seeds)
        json.dump(base, open(bp, 'w', encoding='utf-8'), ensure_ascii=False)
        print('baseline', round(time.time() - t0), 's', flush=True)
    summary = []
    for c in cands:
        cp = os.path.join(OUT_D, c['key'].replace(' ', '_') + '.json')
        if os.path.exists(cp):
            w = json.load(open(cp, encoding='utf-8'))
        else:
            t0 = time.time()
            w = run([(o, t, oo, c) for t in teams for o in orders_with(c['species']) for _, oo in trips[t['id']]],
                    depth, seeds)
            json.dump(w, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
            print(c['key'], round(time.time() - t0), 's', flush=True)
        per = {}
        for t in teams:
            merged = dict(base.get(t['id'], {}))
            merged.update(w.get(t['id'], {}))
            per[t['id']] = best_of(merged)
        score = (sum(v[0] for v in per.values()) / len(per), sum(v[1] for v in per.values()) / len(per))
        used = sum(1 for v in per.values() if c['species'] in v[2])
        summary.append({'cand': c, 'worst': round(score[0], 3), 'avg': round(score[1], 3), 'used_in_best': used,
                        'per_team': {t['title']: {'order': per[t['id']][2], 'worst': round(per[t['id']][0], 3),
                                                  'avg': round(per[t['id']][1], 3)} for t in teams}})
    summary.sort(key=lambda s: (-s['worst'], -s['avg']))
    json.dump(summary, open(os.path.join(OUT_D, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    L = ['# ギャラドス枠の調整（tune.py が自動生成）', '',
         f'対象: 勝率の低い構築（{", ".join(t["title"] for t in teams)}）。両者{depth}手読み・乱数あり・各{seeds}戦。',
         '各候補について、その候補を入れた30通りの選出と入れない30通り（共通）から、構築ごとに「最も負けやすい相手選出への勝率」が最大の選出を取り、その平均で順位を付けています。', '',
         '| 順位 | 候補 | 型 | 最悪の相手選出への勝率（平均） | 全体の勝率（平均） | 最善選出に入った構築数 |', '|---|---|---|---|---|---|']
    for i, s in enumerate(summary):
        c = s['cand']
        L.append(f"| {i + 1} | {c['key']} | {c['species']} {c['nature']} {Mon(c['species'], c['nature'], c['ap'], c['ability'], c['item'], c['moves']).sp_str()} "
                 f"{c['item']} {'/'.join(c['moves'])} | {s['worst']:.0%} | {s['avg']:.0%} | {s['used_in_best']}/{len(teams)} |")
    L += ['', '## 上位候補の構築ごとの最善選出', '']
    for s in summary[:5]:
        L.append(f"- **{s['cand']['key']}**: " + '; '.join(f"{k[:20]}… {v['order']}（最悪 {v['worst']:.0%}・全体 {v['avg']:.0%}）"
                                                       for k, v in s['per_team'].items()))
    open(REPORT, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('→', os.path.normpath(REPORT))


if __name__ == '__main__':
    main()
