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
    dict(GY, key='G1 たべのこし', nature='わんぱく', ap={'hp': 32, 'atk': 2, 'def': 32}, item='たべのこし',
         moves=['たきのぼり', 'ゆきなだれ', 'でんじは', 'ちょうはつ']),
    dict(GY, key='G2 アイへ・ねっとう', nature='わんぱく', ap={'hp': 32, 'atk': 2, 'def': 32}, item='ゴツゴツメット',
         moves=['ねっとう', 'アイアンヘッド', 'でんじは', 'ちょうはつ']),
    dict(GY, key='G3 HD残飯', nature='しんちょう', ap={'hp': 32, 'atk': 2, 'spd': 32}, item='たべのこし',
         moves=['たきのぼり', 'アイアンヘッド', 'でんじは', 'ちょうはつ']),
    dict(GY, key='G4 竜舞ラム', nature='ようき', ap={'hp': 2, 'atk': 32, 'spe': 32}, item='ラムのみ',
         moves=['たきのぼり', 'アイアンヘッド', 'じしん', 'りゅうのまい']),
    dict(GY, key='G5 竜舞珠', nature='ようき', ap={'hp': 2, 'atk': 32, 'spe': 32}, item='いのちのたま',
         moves=['たきのぼり', 'アイアンヘッド', 'じしん', 'りゅうのまい']),
    dict(GY, key='G6 メガギャラドス', nature='ようき', ap={'hp': 2, 'atk': 32, 'spe': 32}, item='ギャラドスナイト',
         moves=['たきのぼり', 'かみくだく', 'アイアンヘッド', 'りゅうのまい'], mega='メガギャラドス', mega_ability='かたやぶり'),
    dict(GY, key='G7 スカーフ', nature='いじっぱり', ap={'hp': 2, 'atk': 32, 'spe': 32}, item='こだわりスカーフ',
         moves=['たきのぼり', 'アイアンヘッド', 'じしん', 'ストーンエッジ']),
]
REPLACE = ['サーフゴー', 'ドドゲザン', 'メタグロス', 'ハッサム', 'ブリジュラス', 'エンペルト', 'ドヒドイデ',
           'アーマーガア', 'キラフロル', 'カバルドン']


def replacement(sp):
    """A standard set for another Pokémon in the slot: the most likely usage/role set (no observations)."""
    base, mega, _ = B._infer.best_set(sp, [], B.MY_TYPES, None)
    m = mega or base
    c = dict(key=f'R {sp}', species=sp, nature=base.nature, ap=dict(base.spv), ability=base.ability,
             item=base.item, moves=list(base.moves))
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


def run(jobs_spec, depth, seeds):
    jobs, meta = [], []
    for o, t, oo, cand in jobs_spec:
        for sd in range(seeds):
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


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv[1:]
    depth = int(a[a.index('--depth') + 1]) if '--depth' in a else 2
    seeds = int(a[a.index('--seeds') + 1]) if '--seeds' in a else 3
    os.makedirs(OUT_D, exist_ok=True)
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    teams = [t for t in data['teams'] if t['id'] in TARGETS]
    trips = {t['id']: team_trips(t) for t in teams}
    cands = CANDIDATES + [replacement(sp) for sp in REPLACE]
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
