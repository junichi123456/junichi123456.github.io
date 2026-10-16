"""Tune the 6th member (イダイトウ): each variant + the core five, the 30 orders that contain it, vs the hard four and
the eleven Mega Gusokumusha builds (depth 3). Resumable per variant (logs/design/tune6_<name>.jsonl).
  python tune6.py            -> logs/design/tune6.json"""
import json, os, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import battle as B, prep, refine as R, design as D, megapick as M
from calc import Mon
D.MAX_OPP_ORDERS = 3
D.MAX_TEAMS = 100
S = 'イダイトウ'
V = {
 'A スカーフ型': ('ようき', {'hp': 2, 'atk': 32, 'spe': 32}, 'こだわりスカーフ', ['ウェーブタックル', 'おはかまいり', 'アクアジェット', 'クイックターン']),
 'B 札・剣みがわり': ('いじっぱり', {'hp': 2, 'atk': 32, 'def': 13, 'spe': 19}, 'のろいのおふだ', ['おはかまいり', 'アクアジェット', 'こうそくいどう', 'みがわり']),
 'C 札・ターン': ('いじっぱり', {'atk': 32, 'def': 31, 'spe': 3}, 'のろいのおふだ', ['おはかまいり', 'アクアジェット', 'クイックターン', 'みがわり']),
 'D 札・波': ('いじっぱり', {'hp': 12, 'atk': 32, 'def': 22}, 'のろいのおふだ', ['ウェーブタックル', 'おはかまいり', 'アクアジェット', 'みがわり']),
 'E しずく': ('いじっぱり', {'hp': 16, 'atk': 18, 'def': 32}, 'しんぴのしずく', ['ウェーブタックル', 'おはかまいり', 'アクアジェット', 'クイックターン']),
 'G スカーフ氷': ('ようき', {'hp': 2, 'atk': 32, 'spe': 32}, 'こだわりスカーフ', ['ウェーブタックル', 'おはかまいり', 'クイックターン', 'れいとうビーム']),
}
CORE = M.CORE

def main():
    cur = {B.BASE_OF.get(m.species, m.species): m for m in B.TEAM}
    ts = [t for t in D.targets() if t['id'] in M.HARD or any(B._base(m['name']) == 'グソクムシャ' for m in t['team'])]
    out_p = os.path.join(D.OUT_D, 'tune6.json')
    out = json.load(open(out_p, encoding='utf-8')) if os.path.exists(out_p) else {}
    for name, (nat, ap, item, mv) in V.items():
        if name in out:
            continue
        pool = {b: cur[b] for b in CORE}
        pool[S] = Mon(S, nat, ap, 'てきおうりょく', item, mv, label=S)
        D.use_pool(pool)
        ords = [o for o in D.orders_of(CORE + [S]) if S in o]
        oo = {t['id']: D.opp_orders(t) for t in ts}
        jobs = [(o, o2, t['id'], zlib.crc32(repr((o, o2, 'tn')).encode()) & 0x7fffffff, 3) for t in ts for o in ords for _, _, o2 in oo[t['id']]]
        cp = os.path.join(D.OUT_D, f'tune6_{name[0]}.jsonl')
        done = {}
        if os.path.exists(cp):
            for ln in open(cp, encoding='utf-8'):
                k, v = json.loads(ln); done[json.dumps(k)] = v
        key = lambda j: json.dumps([list(j[0]), list(j[1]), j[2], j[3], j[4]])
        todo = [j for j in jobs if key(j) not in done]
        f = open(cp, 'a', encoding='utf-8')
        for i in range(0, len(todo), 1000):
            part = todo[i:i + 1000]
            for j, x in zip(part, prep.pool_map(D._job, part)):
                done[key(j)] = x; f.write(json.dumps([json.loads(key(j)), x]) + '\n')
            f.flush(); print(name, i + len(part), '/', len(todo), flush=True)
        f.close()
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
                    v = sum(w * (1 if done[key((o, o2, t['id'], zlib.crc32(repr((o, o2, 'tn')).encode()) & 0x7fffffff, 3))] == 1 else .5 if done[key((o, o2, t['id'], zlib.crc32(repr((o, o2, 'tn')).encode()) & 0x7fffffff, 3))] == 0 else 0) for w, o2 in l)
                    avg += v; worst = min(worst, v / tw)
                sc.append((0.5 * worst + 0.5 * avg, o))
            sc.sort(reverse=True)
            per[t['id']] = [round(sum(s for s, _ in sc[:3]) / 3, 3), list(sc[0][1])]
        out[name] = per
        json.dump(out, open(out_p, 'w', encoding='utf-8'), ensure_ascii=False)
        v = [x[0] for x in per.values()]
        print(f'{name} 最低 {min(v):.2f} 平均 {sum(v)/len(v):.2f}', flush=True)

if __name__ == '__main__':
    main()
    os.system('cd /home/user/junichi123456.github.io && git add -A && git commit -qm "イダイトウの型調整(tune6.py)の結果\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_017zF5X5Hhgg74J4upn1xuNA" && git pull -q --rebase origin ccr-22f85824-zkfyfy && git push -q -u origin ccr-22f85824-zkfyfy')
    print('done', flush=True)
