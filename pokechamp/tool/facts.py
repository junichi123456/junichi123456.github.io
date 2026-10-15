"""事実パケット: 対戦中の判断に必要な事実を Python 側で確定して、短い JSON にまとめる。

LLM（Sonnet）には数値計算をさせない。ダメージ・確定数・素早さ・型の事後確率・見落としやすい要素の警告は
すべてここで計算し、LLM は「確率的な戦術判断」だけを行う（SONNET_PROMPT.md）。

  scene(st, js)            局面の種類 S（最終局面）/ N（通常）/ B（分岐が多い）と、読みの深さ・探索時間
  warnings(st, js)         見落としチェックリスト（該当項目だけ）
  packet(st, js, res, est) 事実パケット（dict）
"""
import itertools, json

import battle as B
from calc import MOVE

SEC = {'S': 2.0, 'N': 7.0, 'B': 9.0}
DEPTH = {'S': '1-2手', 'N': '3手', 'B': '4-5手+相手行動2-3分岐'}
PIVOT = {'ボルトチェンジ', 'とんぼがえり', 'クイックターン', 'すてゼリフ', 'バトンタッチ', 'テレポート', 'しっぽきり',
         'さよならのあいさつ'}
NOTABLE_AB = {'いかく', 'ふゆう', 'ちくでん', 'ひらいしん', 'よびみず', 'すいすい', 'かたやぶり', 'マルチスケイル', 'ばけのかわ',
              'ようりょくそ', 'すなかき', 'ちょすい', 'もらいび', 'そうしょく', 'かんそうはだ', 'あついしぼう', 'テレパシー',
              'ふしぎなまもり', 'おみとおし', 'プレッシャー', 'さめはだ', 'てつのトゲ', 'ほのおのからだ', 'せいでんき'}
NOTABLE_IT = {'きあいのタスキ', 'こだわりスカーフ', 'こだわりハチマキ', 'こだわりメガネ', 'ふうせん', 'ゴツゴツメット',
              'たべのこし', 'オボンのみ', 'いのちのたま', 'とつげきチョッキ', 'じゃくてんほけん', 'ひかりのこな',
              'だっしゅつボタン', 'レッドカード'}


def _opp_active(st):
    return st.sides[1][st.act[1]]


def _me_active(st):
    return st.sides[0][st.act[0]]


# ---------------------------------------------------------------- numbers
def ko_info(rolls, hp):
    """(n, p): the fewest hits that can KO and the chance that n hits do (independent rolls). n is capped at 4."""
    if hp <= 0:
        return 0, 1.0
    for n in range(1, 5):
        if n == 1:
            ok = sum(1 for r in rolls if r >= hp)
            tot = len(rolls)
        else:
            sums = [sum(c) for c in itertools.product(rolls, repeat=n)] if n <= 3 else None
            if sums is None:
                # 4 hits: use the middle of the range
                lo, hi = sum(rolls[:1]) * 4, sum(rolls[-1:]) * 4
                if hi < hp:
                    continue
                return 4, 1.0 if lo >= hp else 0.5
            ok, tot = sum(1 for s in sums if s >= hp), len(sums)
        if ok:
            return n, ok / tot
    return 5, 0.0


def _pct(x, mx):
    return round(100 * x / max(1, mx))


# ---------------------------------------------------------------- opponent set facts
def opp_obs(d, bname):
    obs = list(d.get('obs', [])) + B.battle_obs(bname) + [{'kind': 'move', 'move': mv} for mv in d.get('moves_seen', [])]
    if d.get('item_seen'):
        obs.append({'kind': 'item', 'item': d['item_seen']})
    if d.get('ability_seen'):
        obs.append({'kind': 'ability', 'ability': d['ability_seen']})
    if d.get('mega'):
        obs.append({'kind': 'mega'})
    return obs


def opp_set_facts(js, st):
    """The opponent's set as far as the observations say: ('確定'|'有力'|'不明', [(prob, label, item, moves, cand)])."""
    a = js['opp'][js.get('active_opp', 0)]
    nm = B.norm(a['name'])
    b = B.BASE_OF.get(nm, nm)
    try:
        post = B._infer.posterior(b, opp_obs(a, b), B.MY_TYPES, B.prior_boost_for(b))
    except Exception:
        return '不明', []
    top = post[:2]
    if not top:
        return '不明', []
    p0 = top[0][0]
    lab = '確定' if p0 >= 0.8 else ('有力' if p0 >= 0.3 else '不明')
    if lab == '確定':
        top = top[:1]
    rows = []
    for p, c in top:
        if p < 0.05 and rows:
            break
        m = c.mega or c.base
        rows.append((round(p, 2), c.key, c.base.item, list(c.base.moves), c))
    return lab, rows


def speed_relation(st, rows):
    """Who moves first under each candidate set: '自分先' / '相手先' / '同速' per set, summarised."""
    me = _me_active(st)
    opp = _opp_active(st)
    mine = me.speed(st)
    out = set()
    for p, key, item, moves, c in rows or []:
        m = c.mega or c.base
        s = m.stat['spe']
        bst = opp.boosts['spe']
        s = s * (2 + bst) // 2 if bst >= 0 else s * 2 // (2 - bst)
        if (c.mega or c.base).item == 'こだわりスカーフ':
            s = s * 3 // 2
        if opp.status == 'par':
            s //= 2
        out.add('自分先' if mine > s else '相手先' if mine < s else '同速')
    if st.tr:
        out = {{'自分先': '相手先', '相手先': '自分先'}.get(x, x) for x in out}      # trick room
    if not out:
        return '不明'
    return list(out)[0] if len(out) == 1 else '型により変わる(' + '/'.join(sorted(out)) + ')'


# ---------------------------------------------------------------- scene
def scene(st, js):
    """S / N / B and why. B = many branches: the first turns, unrevealed backs, a split set, pivot moves."""
    me_alive = sum(1 for m in st.sides[0] if m.alive)
    opp_known = len(js.get('opp', []))
    opp_fainted = sum(1 for d in js.get('opp', []) if d.get('hp_pct', 100) <= 0)
    opp_left = max(1, 3 - opp_fainted)            # three are brought
    unseen = max(0, 3 - opp_known)
    why = []
    lab, rows = opp_set_facts(js, st)
    if st.turn <= 1:
        why.append('初手')
    if unseen and opp_left > 1:
        why.append(f'相手の裏{unseen}体未確定')
    if rows and rows[0][0] < 0.6 and lab != '確定':
        why.append('型が割れている')
    me, opp = _me_active(st), _opp_active(st)
    if any(x in PIVOT for x in me.moves) or any(x in PIVOT for x in opp.moves):
        why.append('pivot')
    if me_alive <= 1 and opp_left <= 1:
        return 'S', ['最終局面']
    if why:
        return 'B', why
    if me_alive <= 2 and opp_left <= 1:
        return 'S', ['残り少ない']
    return 'N', []


# ---------------------------------------------------------------- checklist (R P A I B M F S L)
def warnings(st, js, rows=None):
    me, opp = _me_active(st), _opp_active(st)
    w = []
    # R: random range
    for mv in B.legal_moves(me):
        if MOVE[mv]['cat'] == 'status':
            continue
        r = B.rolls(me, opp, mv, st)
        n, p = ko_info(list(r), opp.hp)
        if 0.05 < p < 0.95 and n <= 2:
            w.append(f'R:{mv}は{n}発で倒せるのは{round(100 * p)}%(乱数)')
    # P: priority moves of theirs that reach us
    pri = [m for m in set(opp.moves) | set(js['opp'][js.get('active_opp', 0)].get('moves_seen', []))
           if m in MOVE and MOVE[m].get('pri', 0) > 0 and MOVE[m]['cat'] != 'status']
    for m in pri:
        r = B.rolls(opp, me, m, st)
        if r[-1] >= me.hp:
            w.append(f'P:相手の先制技{m}で自分が落ちる範囲(HP{me.hp})')
    # A: abilities
    if me.disguise:
        w.append('A:自分のばけのかわ健在(最初の1撃は無効)')
    if opp.disguise:
        w.append('A:相手のばけのかわ健在(最初の1撃は無効)')
    ab = opp.cur.ability
    if ab in NOTABLE_AB:
        w.append(f'A:相手の特性{ab}')
    if me.cur.ability in NOTABLE_AB and me.cur.ability in ('ふゆう', 'ちくでん', 'ひらいしん'):
        pass
    # I: items
    for who, m in (('相手', opp), ('自分', me)):
        if m.item in NOTABLE_IT and (who == '相手' or m.item in ('こだわりスカーフ', 'こだわりハチマキ', 'こだわりメガネ')):
            w.append(f'I:{who}の持ち物{m.item}')
    if opp.item == 'きあいのタスキ' and opp.hp == opp.maxhp:
        w.append('I:タスキ持ち満タン(1回耐える)')
    # B: backs
    unseen = max(0, 3 - len(js.get('opp', [])))
    if unseen:
        w.append(f'B:相手の裏{unseen}体は未確定')
    if st.rocks[0]:
        w.append('B:自分側にステロ')
    if st.rocks[1]:
        w.append('B:相手側にステロ')
    # M: mega
    mu = st.mega_used
    w.append(f"M:メガ 自分{'使用済' if mu[0] else '未使用'}/相手{'使用済' if mu[1] else '未使用'}")
    # F: field
    if st.weather:
        w.append(f'F:天候{st.weather}(残り{st.wt})')
    if st.terrain:
        w.append(f'F:フィールド{st.terrain}(残り{st.tt})')
    if st.tr:
        w.append(f'F:トリックルーム(残り{st.tr})')
    # S: boosts / status
    for who, m in (('自分', me), ('相手', opp)):
        bs = {k: v for k, v in m.boosts.items() if v}
        if bs:
            w.append('S:' + who + 'の能力' + ','.join(f'{k}{v:+d}' for k, v in bs.items()))
        if m.status:
            w.append(f'S:{who}は{m.status}')
    # L: locks
    for who, m in (('自分', me), ('相手', opp)):
        if m.lock or m.encore or m.rampage:
            w.append(f'L:{who}は技が固定')
        if m.taunt:
            w.append(f'L:{who}はちょうはつ中')
    for who, key, i in (('自分', 'me', st.act[0]), ('相手', 'opp', js.get('active_opp', 0))):
        try:
            d = js[key][i if key == 'opp' else js.get('active_me', 0)]
        except Exception:
            d = {}
        if d.get('confusion'):
            w.append(f'L:{who}は混乱中(技が出ず自傷する場合あり)')
    if opp.rampage:
        w.append(f'L:相手はあばれる状態({opp.rampage[0]}を継続・終了後に混乱)')
    return w


# ---------------------------------------------------------------- packet
def packet(st, js, res=None, est=None, sc=None):
    me, opp = _me_active(st), _opp_active(st)
    sc = sc or scene(st, js)
    lab, rows = opp_set_facts(js, st)
    ko = {}
    for mv in B.legal_moves(me):
        if MOVE[mv]['cat'] == 'status':
            continue
        r = list(B.rolls(me, opp, mv, st))
        n, p = ko_info(r, opp.hp)
        ko[mv] = 'ばけのかわで無効(1回)' if opp.disguise else f"{_pct(r[0], opp.maxhp)}-{_pct(r[-1], opp.maxhp)}% {n}発{round(100 * p)}%"
    threat = {}
    for mv in [m for m in opp.moves if m in MOVE and MOVE[m]['cat'] != 'status'][:4]:
        r = list(B.rolls(opp, me, mv, st))
        n, p = ko_info(r, me.hp)
        threat[mv] = 'ばけのかわで無効(1回)' if me.disguise else f"{_pct(r[0], me.maxhp)}-{_pct(r[-1], me.maxhp)}% {n}発{round(100 * p)}%"
    bench = [{'名': m.name, 'HP': f'{m.hp}/{m.maxhp}'} for i, m in enumerate(st.sides[0]) if i != st.act[0] and m.alive]
    others = [d for i, d in enumerate(js.get('opp', [])) if i != js.get('active_opp', 0)]
    back_opp = [d['name'] + ('' if d.get('hp_pct', 100) > 0 else '(倒)') + ('' if d.get('hp_pct', 100) >= 100 or d.get('hp_pct', 100) <= 0 else f"{d.get('hp_pct')}%")
                for d in others]
    pk = {
        'turn': st.turn,
        'scene': sc[0], 'depth': DEPTH[sc[0]], 'why': sc[1],
        'me': f"{me.name} {me.hp}/{me.maxhp}" + (' ' + ','.join(f'{k}{v:+d}' for k, v in me.boosts.items() if v) if any(me.boosts.values()) else ''),
        'opp': f"{opp.name} {_pct(opp.hp, opp.maxhp)}%",
        'opp_set': {'状態': lab, '候補': [{'p': p, '型': key, '持': item, '技': mv} for p, key, item, mv, _ in rows]},
        'ko': ko, 'threat': threat, 'speed': speed_relation(st, rows),
        'bench': bench, 'opp_seen_back': back_opp,  # 見えた控え(倒=ひんし)
        'warn': warnings(st, js, rows),
    }
    if res is not None and est is not None:
        import search as S
        pk['engine_top'] = [[S.fmt(est, a), round(v, 2)] for v, a in res[:3]]
    return pk


def compact(pk):
    return json.dumps(pk, ensure_ascii=False, separators=(',', ':'))
