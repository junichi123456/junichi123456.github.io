"""対戦ログの蓄積と、傾向・対策の学習。

  python3 learn.py start                     新しい対戦を開始（logs/current.json を作る）
  python3 learn.py team <相手6体...>          見せ合いの相手6体を記録
  python3 learn.py pick <自分の選出順...>     自分の選出順を記録
  python3 learn.py turn '<JSON>'             1ターン分を記録（下の形式）
  python3 learn.py end win|lose|draw [メモ]   対戦を確定して logs/battles.jsonl に追記し、知識と TRENDS.md を更新
  python3 learn.py add record.json           1戦分のレコードを直接追記（ロガー由来の後入力用）
  python3 learn.py report                    knowledge.json と TRENDS.md を再生成

turn JSON:
  {"turn": 1, "me": "ガブリアス", "opp": "ボーマンダ", "my_action": "がんせきふうじ", "opp_action": "りゅうのまい",
   "first": "me"|"opp", "opp_item": "ボーマンダナイト", "opp_ability": "いかく", "opp_mega": true,
   "my_hp_pct_after": 100, "opp_hp_pct_after": 62, "ko": ["opp"|"me"], "note": ""}

battle.py はここで作った logs/knowledge.json を読み込み、相手の型・選出予測・自分の選出評価に反映する。
"""
import json, os, sys, time, math
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs'))
BATTLES = os.path.join(LOGS, 'battles.jsonl')
CURRENT = os.path.join(LOGS, 'current.json')
KNOW = os.path.join(LOGS, 'knowledge.json')
TRENDS = os.path.join(LOGS, 'TRENDS.md')

ALIAS = {'イダイトウ(オス)': 'イダイトウ', 'イダイトウ（オス）': 'イダイトウ'}


def base_name(n):
    n = ALIAS.get(n, n)
    try:
        from battle import BASE_OF, norm
        return BASE_OF.get(norm(n), norm(n))
    except Exception:
        return n


def _load(p, default):
    try:
        return json.load(open(p, encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    json.dump(obj, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def battles():
    out = []
    if os.path.exists(BATTLES):
        for line in open(BATTLES, encoding='utf-8'):
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------- recording
def start():
    rec = {'id': time.strftime('%Y-%m-%dT%H:%M:%S'), 'result': None, 'my_order': [], 'opp_team': [],
           'opp_picks': [], 'opp_lead': None, 'opp_revealed': {}, 'turns': [], 'notes': ''}
    _save(CURRENT, rec)
    return rec


def cur():
    rec = _load(CURRENT, None)
    return rec or start()


def record_turn(t):
    rec = cur()
    rec['turns'].append(t)
    opp = t.get('opp')
    if opp:
        b = base_name(opp)
        if b not in rec['opp_picks']:
            rec['opp_picks'].append(b)
        if rec['opp_lead'] is None:
            rec['opp_lead'] = b
        rv = rec['opp_revealed'].setdefault(b, {'moves': [], 'item': None, 'ability': None, 'mega': False,
                                                 'faster_than': [], 'slower_than': []})
        mv = t.get('opp_action')
        if mv and not mv.endswith('に交代') and mv not in rv['moves']:
            rv['moves'].append(mv)
        for k_src, k in (('opp_item', 'item'), ('opp_ability', 'ability')):
            if t.get(k_src): rv[k] = t[k_src]
        if t.get('opp_mega'): rv['mega'] = True
        rv.setdefault('obs', [])
        for o in t.get('obs', []):
            rv['obs'].append(o)
        if mv and not mv.endswith('に交代'):
            rv['obs'].append({'kind': 'move', 'move': mv})
        if t.get('opp_item'): rv['obs'].append({'kind': 'item', 'item': t['opp_item']})
        if t.get('opp_mega'): rv['obs'].append({'kind': 'mega'})
        # speed observation only when both used a move of equal priority
        first = t.get('first')
        my_act, op_act = t.get('my_action', ''), t.get('opp_action', '')
        if first and t.get('me') and not my_act.endswith('に交代') and not op_act.endswith('に交代') and same_priority(my_act, op_act):
            me = base_name(t['me'])
            (rv['faster_than'] if first == 'opp' else rv['slower_than']).append(me)
    _save(CURRENT, rec)


def same_priority(a, b):
    try:
        from calc import MOVE
        return MOVE.get(a, {}).get('pri', 0) == MOVE.get(b, {}).get('pri', 0)
    except Exception:
        return True


def end(result, note=''):
    rec = cur()
    rec['result'] = result
    rec['notes'] = note
    add(rec)
    os.remove(CURRENT)


def add(rec):
    rec['opp_team'] = [base_name(x) for x in rec.get('opp_team', [])]
    rec['opp_picks'] = [base_name(x) for x in rec.get('opp_picks', [])]
    rec['my_order'] = [base_name(x) for x in rec.get('my_order', [])]
    os.makedirs(LOGS, exist_ok=True)
    with open(BATTLES, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    rebuild()


# ---------------------------------------------------------------- learning
def my_speeds():
    try:
        from team import TEAM
        from battle import BASE_OF
        return {BASE_OF.get(m.species, m.species): m.stat['spe'] for m in TEAM}, \
               {BASE_OF.get(m.species, m.species): m.speed() for m in TEAM}
    except Exception:
        return {}, {}


def max_speed(species):
    try:
        from calc import POKE
        from battle import MEGA_OF
        best = 0
        for n in [species] + MEGA_OF.get(species, []):
            if n in POKE:
                best = max(best, math.floor((POKE[n]['bs']['speed'] + 52) * 1.1))
        return best
    except Exception:
        return 999


def rebuild():
    B = [b for b in battles() if b.get('result')]
    sp = defaultdict(lambda: {'seen': 0, 'picked': 0, 'led': 0, 'w_seen': 0, 'w_picked': 0, 'moves': Counter(),
                              'items': Counter(), 'abilities': Counter(), 'mega': 0, 'scarf_evidence': 0,
                              'inferred': Counter()})
    my_orders = defaultdict(lambda: [0, 0])  # tuple(order) -> [games, wins]
    my_mon = defaultdict(lambda: [0, 0])
    vs = defaultdict(lambda: [0, 0])  # (my mon, opp species picked) -> [games, wins]
    ko_by = Counter()
    _, my_spd = my_speeds()
    for b in B:
        win = 1 if b['result'] == 'win' else 0.5 if b['result'] == 'draw' else 0
        for s in set(b['opp_team']):
            sp[s]['seen'] += 1; sp[s]['w_seen'] += win
        for s in set(b['opp_picks']):
            sp[s]['picked'] += 1; sp[s]['w_picked'] += win
        if b.get('opp_lead'):
            sp[b['opp_lead']]['led'] += 1
        for s, rv in b.get('opp_revealed', {}).items():
            for m in rv.get('moves', []): sp[s]['moves'][m] += 1
            if rv.get('item'): sp[s]['items'][rv['item']] += 1
            if rv.get('ability'): sp[s]['abilities'][rv['ability']] += 1
            if rv.get('mega'): sp[s]['mega'] += 1
            if rv.get('obs'):
                try:
                    import infer
                    post = infer.posterior(s, rv['obs'])
                    if post and post[0][0] >= 0.3:
                        sp[s]['inferred'][post[0][1].key] += 1
                except Exception:
                    pass
            for mine in rv.get('faster_than', []):
                if my_spd.get(mine, 0) >= max_speed(s):
                    sp[s]['scarf_evidence'] += 1
        o = tuple(b['my_order'])
        if o:
            my_orders[o][0] += 1; my_orders[o][1] += win
        for m in o:
            my_mon[m][0] += 1; my_mon[m][1] += win
            for s in b['opp_picks']:
                vs[f'{m}|{s}'][0] += 1; vs[f'{m}|{s}'][1] += win
        for t in b.get('turns', []):
            if 'me' in (t.get('ko') or []) and t.get('opp'):
                ko_by[base_name(t['opp'])] += 1
    know = {
        'n_battles': len(B),
        'wins': sum(1 for b in B if b['result'] == 'win'),
        'species': {k: {**{kk: vv for kk, vv in v.items() if not isinstance(vv, Counter)},
                        'moves': dict(v['moves'].most_common()), 'items': dict(v['items'].most_common()),
                        'abilities': dict(v['abilities'].most_common()),
                        'inferred': dict(v['inferred'].most_common())} for k, v in sp.items()},
        'my_orders': {' → '.join(k): v for k, v in my_orders.items()},
        'my_mon': dict(my_mon),
        'vs': dict(vs),
        'ko_by': dict(ko_by.most_common()),
    }
    _save(KNOW, know)
    write_trends(know)
    return know


def write_trends(k):
    n = k['n_battles']
    L = ['# 対戦ログから見た傾向と対策', '', f'対戦数 {n}／勝ち {k["wins"]}（勝率 {k["wins"] / n * 100:.0f}%）' if n else '対戦記録なし', '']
    if not n:
        open(TRENDS, 'w', encoding='utf-8').write('\n'.join(L)); return
    S = k['species']
    L += ['## 相手ポケモン（遭遇の多い順）', '', '| ポケモン | 遭遇 | 選出率 | 先発率 | 選出時の勝率 | 観測した技 | 観測した持ち物 |', '|---|---|---|---|---|---|---|']
    for s, v in sorted(S.items(), key=lambda x: -x[1]['seen'])[:30]:
        pr = v['picked'] / v['seen'] if v['seen'] else 0
        lr = v['led'] / v['picked'] if v['picked'] else 0
        wr = f"{v['w_picked'] / v['picked'] * 100:.0f}%" if v['picked'] else '-'
        items = '、'.join(f'{i}×{c}' for i, c in v['items'].items()) + ('、スカーフ疑い' if v['scarf_evidence'] else '')
        if v.get('inferred'):
            items += '／推定型: ' + '、'.join(f'{k}×{c}' for k, c in list(v['inferred'].items())[:2])
        L.append(f"| {s} | {v['seen']} | {pr * 100:.0f}% | {lr * 100:.0f}% | {wr} | {'、'.join(list(v['moves'])[:6])} | {items} |")
    L += ['', '## 自分の選出', '', '| 選出順 | 回数 | 勝率 |', '|---|---|---|']
    for o, (g, w) in sorted(k['my_orders'].items(), key=lambda x: -x[1][0]):
        L.append(f'| {o} | {g} | {w / g * 100:.0f}% |')
    L += ['', '## 要対策（選出されると負けやすい相手）', '']
    bad = [(s, v) for s, v in S.items() if v['picked'] >= 2 and v['w_picked'] / v['picked'] < 0.5]
    bad.sort(key=lambda x: (x[1]['w_picked'] / x[1]['picked'], -x[1]['picked']))
    if not bad:
        L.append('- 該当なし（2回以上選出され勝率5割未満の相手はいない）')
    for s, v in bad:
        best = []
        for key, (g, w) in k['vs'].items():
            m, o = key.split('|')
            if o == s and g >= 2: best.append((w / g, g, m))
        best.sort(reverse=True)
        hint = f"。勝ち越している自分側: {best[0][2]}（{best[0][0] * 100:.0f}%、{best[0][1]}戦）" if best and best[0][0] >= 0.5 else ''
        L.append(f"- **{s}**: 選出{v['picked']}回で勝率{v['w_picked'] / v['picked'] * 100:.0f}%、こちらを{k['ko_by'].get(s, 0)}体倒した{hint}")
    L += ['', '## 予想外の型（使用率データと違った点）', '']
    try:
        from sets import candidates
        found = False
        for s, v in S.items():
            if not v['moves']: continue
            exp = set()
            for c in candidates(s)[:6]: exp |= set(c.pool) if c.source == 'usage' else set(c.base.moves)
            odd = [m for m in v['moves'] if m not in exp]
            if odd:
                found = True
                L.append(f"- {s}: 想定外の技 {'、'.join(odd)}")
            if v['scarf_evidence']:
                found = True
                L.append(f"- {s}: 最速より速い行動を{v['scarf_evidence']}回観測（こだわりスカーフの可能性）")
        if not found: L.append('- なし')
    except Exception as e:
        L.append(f'- （比較できませんでした: {e}）')
    open(TRENDS, 'w', encoding='utf-8').write('\n'.join(L) + '\n')


# ---------------------------------------------------------------- used by battle.py
def knowledge():
    return _load(KNOW, {'n_battles': 0, 'species': {}, 'my_orders': {}, 'vs': {}})


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    c = a[0]
    if c == 'start': start()
    elif c == 'team':
        r = cur(); r['opp_team'] = [base_name(x) for x in a[1:]]; _save(CURRENT, r)
    elif c == 'pick':
        r = cur(); r['my_order'] = [base_name(x) for x in a[1:]]; _save(CURRENT, r)
    elif c == 'turn': record_turn(json.loads(a[1]))
    elif c == 'end': end(a[1], ' '.join(a[2:]))
    elif c == 'add': add(json.load(open(a[1], encoding='utf-8')))
    elif c == 'report': rebuild(); print(open(TRENDS, encoding='utf-8').read())
    else: print(__doc__)


if __name__ == '__main__':
    main()
