"""対戦中の型推定（ベイズ更新）。

相手1体ごとに sets.candidates() の候補（持ち物×性格×能力P）へ観測を当てはめ、事後確率を出す。

観測 obs の形式（どれも省略可。HPは相手=表示%、自分=実数）:
  {"kind": "dealt", "by": "ルカリオ", "my_mega": true, "move": "はどうだん", "before": 100, "after": 38,
   "atk_boost": 0, "def_boost": 0, "crit": false, "opp_mega": false, "weather": null, "terrain": null}
      自分の攻撃で相手のHP%が before→after になった
  {"kind": "taken", "to": "ガブリアス", "move": "じしん", "damage": 96, "atk_boost": 0, "def_boost": 0,
   "crit": false, "burned": false, "opp_mega": false, "my_mega": false}
      相手の攻撃で自分が damage（実数）受けた（実数が分からなければ "pct" で%）
  {"kind": "order", "first": "opp", "me": "ガブリアス", "my_move": "じしん", "opp_move": "りゅうのまい",
   "my_spe_boost": 0, "opp_spe_boost": 0, "my_para": false, "opp_para": false, "opp_mega": false, "my_mega": false}
      同じ優先度の技でどちらが先に動いたか
  {"kind": "move", "move": "だいもんじ"} / {"kind": "item", "item": "こだわりスカーフ"} /
  {"kind": "ability", "ability": "いかく"} / {"kind": "mega"}
"""
import math
from calc import MOVE, POKE, calc
from sets import candidates, MEGAS, Cand
from calc import Mon
from team import TEAM

EPS = 0.01
_MY = {}
for _m in TEAM:
    base = None
    for b, ms in MEGAS.items():
        if _m.species in ms:
            base = b
    if base:
        bm = Mon(base, _m.nature, _m.spv, POKE[base]['ab'][0], _m.item, _m.moves, label=base)
        _MY[base] = (bm, _m)
        _MY[_m.species] = (bm, _m)
    else:
        _MY[_m.species] = (_m, None)
_MY_ALIAS = {'ルカリオ': 'ルカリオ', 'メガルカリオZ': 'メガルカリオＺ'}


def my_mon(name, mega=False):
    name = _MY_ALIAS.get(name, name)
    b, m = _MY[name]
    if name.startswith('メガ'):
        return m
    return m if (mega and m) else b


def _form(c, opp_mega):
    return c.mega if (opp_mega and c.mega) else c.base


def _spd(mon, boost=0, para=False):
    s = mon.stat['spe']
    s = s * (2 + boost) // 2 if boost >= 0 else s * 2 // (2 - boost)
    if mon.item == 'こだわりスカーフ':
        s = s * 3 // 2
    if para:
        s //= 2
    return s


def likelihood(c, o):
    k = o.get('kind')
    try:
        if k == 'dealt':
            att = my_mon(o['by'], o.get('my_mega', False))
            dfn = _form(c, o.get('opp_mega', False))
            before, after = o.get('before', 100), o.get('after')
            rolls = calc(att, dfn, o['move'], atk_boost=o.get('atk_boost', 0), def_boost=o.get('def_boost', 0),
                         crit=o.get('crit', False), weather=o.get('weather'), terrain=o.get('terrain'),
                         def_full_hp=before >= 100)
            hp = dfn.stat['hp']
            pct = [r / hp * 100 for r in rolls]
            if after is None:
                return 1.0
            d = before - after
            if after <= 0:
                n = sum(1 for p in pct if p >= before - 1)
            elif after <= 2 and before >= 100 and dfn.item == 'きあいのタスキ':
                n = sum(1 for p in pct if p >= 97)
                n = n or sum(1 for p in pct if abs(p - d) <= 1.5)
            else:
                n = sum(1 for p in pct if abs(p - d) <= 1.5)
            return max(n / 16, EPS)
        if k == 'taken':
            att = _form(c, o.get('opp_mega', False))
            dfn = my_mon(o['to'], o.get('my_mega', False))
            if o['move'] in MOVE and MOVE[o['move']]['cat'] == 'status':
                return 1.0
            if o['move'] not in att.moves and o['move'] in MOVE:
                att = Mon(att.species, att.nature, att.spv, att.ability, att.item, att.moves + [o['move']], label=att.label)
            rolls = calc(att, dfn, o['move'], atk_boost=o.get('atk_boost', 0), def_boost=o.get('def_boost', 0),
                         crit=o.get('crit', False), burned=o.get('burned', False), intimidated=o.get('intimidated', False),
                         weather=o.get('weather'), terrain=o.get('terrain'))
            if 'damage' in o:
                n = sum(1 for r in rolls if abs(r - o['damage']) <= 1)
            else:
                hp = dfn.stat['hp']
                n = sum(1 for r in rolls if abs(r / hp * 100 - o['pct']) <= 1.5)
            return max(n / 16, EPS)
        if k == 'order':
            mm = MOVE.get(o.get('my_move'), {}); om = MOVE.get(o.get('opp_move'), {})
            if mm.get('pri', 0) != om.get('pri', 0):
                return 1.0
            me = my_mon(o['me'], o.get('my_mega', False))
            op = _form(c, o.get('opp_mega', False))
            ms = _spd(me, o.get('my_spe_boost', 0), o.get('my_para', False))
            os_ = _spd(op, o.get('opp_spe_boost', 0), o.get('opp_para', False))
            first_opp = o['first'] == 'opp'
            if os_ == ms:
                return 0.5
            return 1.0 if (os_ > ms) == first_opp else EPS / 2
        if k == 'move':
            mv = o['move']
            if c.base.item == 'こだわりスカーフ' and MOVE.get(mv, {}).get('cat') == 'status' and mv not in ('トリック', 'すりかえ'):
                return EPS / 2
            return 1.0
        if k == 'item':
            it = o['item']
            if 'ナイト' in it or it == 'メガストーン':
                return 1.0 if c.mega else EPS / 10
            return 1.0 if c.base.item == it else EPS / 10
        if k == 'mega':
            return 1.0 if c.mega else EPS / 10
        if k == 'ability':
            ab = o['ability']
            return 1.0 if ab in (c.base.ability, c.mega.ability if c.mega else None) else 0.2
    except Exception:
        return 1.0
    return 1.0


def posterior(species, obs, my_types=(), prior_boost=None):
    cs = candidates(species, my_types)
    ws = []
    for c in cs:
        w = c.prior * (prior_boost(c) if prior_boost else 1.0)
        for o in obs:
            w *= likelihood(c, o)
        ws.append(w)
    tot = sum(ws) or 1
    res = sorted(zip([w / tot for w in ws], cs), key=lambda x: -x[0])
    return res


def revealed_moves(obs):
    out = []
    for o in obs:
        mv = o.get('move') if o.get('kind') in ('move', 'taken') else (o.get('opp_move') if o.get('kind') == 'order' else None)
        if mv and mv in MOVE and mv not in out:
            out.append(mv)
    return out


def apply_reveals(c, obs):
    """Return (base, mega) Mons of candidate c with revealed moves forced in."""
    rev = revealed_moves(obs)
    def fix(m):
        if m is None: return None
        keep = [x for x in m.moves if x not in rev]
        # drop lowest-usage unrevealed moves first
        keep.sort(key=lambda x: -c.pool.get(x, 0))
        moves = (rev + keep)[:4] if len(rev) < 4 else rev[:4]
        if moves == m.moves: return m
        return Mon(m.species, m.nature, m.spv, m.ability, m.item, moves, label=m.label)
    return fix(c.base), fix(c.mega)


def best_set(species, obs=(), my_types=(), prior_boost=None):
    post = posterior(species, list(obs), my_types, prior_boost)
    p, c = post[0]
    b, m = apply_reveals(c, obs)
    return b, m, post


def describe(species, obs, n=5):
    post = posterior(species, obs)
    return [(round(p, 3), c.key, (c.mega or c.base).stat_str()) for p, c in post[:n]]
