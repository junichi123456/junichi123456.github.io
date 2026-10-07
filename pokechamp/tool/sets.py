"""相手の型の候補（仮説）を作る。

1. 使用率データ（data/usage_sets.json, gamewith.ai のシングル全258種）から
   持ち物 × 性格・能力P配分 の組み合わせを事前確率つきで列挙する。
2. 使用率データが無い/薄いポケモンは、種族値から役割を判定して候補を作る（role_candidates）。

候補 = Cand(prior, key, base Mon, mega Mon or None, move_pool)
move_pool は {技: 採用率%}。判明した技は infer.py が先頭に差し込む。
"""
import json, math, os
from functools import lru_cache
from calc import Mon, MOVE, POKE, learnset, eff

HERE = os.path.dirname(os.path.abspath(__file__))
USAGE = json.load(open(os.path.join(HERE, 'data/usage_sets.json'), encoding='utf-8'))

STATKEY = {'hp': 'hp', 'atk': 'atk', 'def': 'def', 'spa': 'spa', 'spd': 'spd', 'spe': 'spe'}
NATURE = {
    'いじっぱり': ('atk', 'spa'), 'ようき': ('spe', 'spa'), 'ひかえめ': ('spa', 'atk'), 'おくびょう': ('spe', 'atk'),
    'わんぱく': ('def', 'spa'), 'ずぶとい': ('def', 'atk'), 'しんちょう': ('spd', 'spa'), 'おだやか': ('spd', 'atk'),
    'ゆうかん': ('atk', 'spe'), 'れいせい': ('spa', 'spe'), 'のんき': ('def', 'spe'), 'なまいき': ('spd', 'spe'),
    'むじゃき': ('spe', 'spd'), 'せっかち': ('spe', 'def'), 'やんちゃ': ('atk', 'spd'), 'うっかりや': ('spa', 'spd'),
    'さみしがり': ('atk', 'def'), 'おっとり': ('spa', 'def'), 'おとなしい': ('spd', 'def'), 'ずぶとい ': ('def', 'atk'),
    'のうてんき': ('def', 'spd'), 'がんばりや': (None, None), 'まじめ': (None, None), 'すなお': (None, None),
    'てれや': (None, None), 'きまぐれ': (None, None), 'ひかえめ ': ('spa', 'atk'), 'れいせい ': ('spa', 'spe'),
}
STATUS_MOVES_OK_WITH_SCARF = {'トリック', 'すりかえ'}


class Cand:
    __slots__ = ('prior', 'key', 'base', 'mega', 'pool', 'source')

    def __init__(self, prior, key, base, mega, pool, source):
        self.prior, self.key, self.base, self.mega, self.pool, self.source = prior, key, base, mega, pool, source

    def __repr__(self):
        m = self.mega or self.base
        return f"<{self.key} p={self.prior:.3f} {m.stat_str()} {m.item} {m.moves}>"


# ---------------------------------------------------------------- mega lookup
MEGAS = {}
for _p in POKE.values():
    if _p.get('form') and 'mega' in _p['form'] and _p.get('baseId'):
        for _n, _b in POKE.items():
            if _b['id'] == _p['baseId'] and not _b.get('form'):
                MEGAS.setdefault(_n, []).append(_p['ja'])
                break


def mega_for(species, stone):
    ms = MEGAS.get(species, [])
    if 'ナイト' not in (stone or '') or not ms:
        return None
    if len(ms) == 1:
        return ms[0]
    suf = stone[-1]
    for m in ms:
        if m.endswith({'X': 'Ｘ', 'Y': 'Ｙ', 'Z': 'Ｚ'}.get(suf, '#')):
            return m
    for m in ms:  # plain stone → the non-suffixed mega
        if m[-1] not in 'ＸＹＺ':
            return m
    return ms[0]


def _clean_nature(n):
    return n.strip()


def compat(spread, nature):
    """How plausible a nature is for a spread (0..1)."""
    up, dn = NATURE.get(nature, (None, None))
    if up is None:
        return 0.3
    sp = spread
    inv = lambda k: sp.get(k, 0) >= 16
    score = 1.0
    if up and not inv(up) and up != 'spe':
        score *= 0.35 if up in ('def', 'spd') and (inv('def') or inv('spd') or inv('hp')) else 0.15
    if up == 'spe' and not inv('spe'):
        score *= 0.2
    if dn and inv(dn):
        score *= 0.05
    if dn == 'spe' and inv('spe'):
        score *= 0.05
    return score


def pick_moves(pool, item, k=4, spread=None):
    def w(m):
        c = MOVE[m]['cat']
        x = pool[m]
        if spread:
            a, s_ = spread.get('atk', 0), spread.get('spa', 0)
            if c == 'physical' and s_ >= 16 and a < 16: x *= 0.15
            if c == 'special' and a >= 16 and s_ < 16: x *= 0.15
        return x
    mv = [m for m in sorted((m for m in pool if m in MOVE), key=lambda x: -w(x))]
    if item == 'こだわりスカーフ' or (item or '').startswith('こだわり'):
        att = [m for m in mv if MOVE[m]['cat'] != 'status' or m in STATUS_MOVES_OK_WITH_SCARF]
        return att[:k]
    return mv[:k]


@lru_cache(maxsize=None)
def usage_candidates(species, max_cands=24):
    u = USAGE.get(species)
    if not u or not u.get('spreads') or len(u.get('moves', [])) < 2:
        return None
    pool = {m['name']: m['usage'] for m in u['moves']}
    ability = u['abilities'][0]['name'] if u['abilities'] else POKE[species]['ab'][0]
    items = [(i['name'], i['usage']) for i in u['items'] if i['usage'] >= 3][:5] or [(None, 100)]
    natures = [(_clean_nature(n['name']), n['usage']) for n in u['natures'] if n['usage'] >= 3][:5]
    spreads = [(s['ap'], s['usage']) for s in u['spreads'] if s['usage'] >= 1.5][:6]
    out = []
    for (sp, sp_u), (nat, n_u) in [(a, b) for a in spreads for b in natures]:
        c = compat(sp, nat)
        if c < 0.04:
            continue
        for item, i_u in items:
            prior = sp_u * n_u * i_u * c
            spv = {k: v for k, v in sp.items() if v}
            if sum(spv.values()) > 66 or nat not in NATURE:
                continue
            moves = pick_moves(pool, item, spread=sp)
            base = Mon(species, nat, spv, ability, item, moves, label=species)
            mega = None
            ms = mega_for(species, item)
            if ms:
                mega = Mon(ms, nat, spv, POKE[ms]['ab'][0], item, moves, label=ms)
            key = f"{nat}/{base.sp_str()}/{item}"
            out.append(Cand(prior, key, base, mega, pool, 'usage'))
    out.sort(key=lambda c: -c.prior)
    out = out[:max_cands]
    tot = sum(c.prior for c in out) or 1
    for c in out:
        c.prior /= tot
    return out


# ---------------------------------------------------------------- role-based fallback
PRIORITY_MOVES = ['かげうち', 'ふいうち', 'バレットパンチ', 'アクアジェット', 'こおりのつぶて', 'マッハパンチ', 'しんそく',
                  'でんこうせっか', 'グラススライダー', 'しんくうは', 'ジェットパンチ']
SETUP_PHYS = ['つるぎのまい', 'りゅうのまい', 'ビルドアップ', 'からをやぶる']
SETUP_SPEC = ['わるだくみ', 'めいそう', 'ちょうのまい', 'からをやぶる']
RECOVERY = ['じこさいせい', 'はねやすめ', 'なまける', 'つきのひかり', 'あさのひざし', 'こうごうせい', 'ねがいごと', 'いたみわけ']
STATUS = ['おにび', 'どくどく', 'でんじは', 'あくび', 'ステルスロック']


def role_of(species):
    b = POKE[species]['bs']
    H, A, B, C, D, S = b['hp'], b['attack'], b['defense'], b['specialAttack'], b['specialDefense'], b['speed']
    off = max(A, C)
    phys = A >= C
    bulk_b, bulk_d = H + B, H + D
    if off < 95 and max(bulk_b, bulk_d) >= 190:
        return 'wall_b' if bulk_b >= bulk_d else 'wall_d', phys
    if off >= 95 or S >= 95:
        return ('fast_' if S >= 85 else 'slow_') + ('phys' if phys else 'spec'), phys
    return 'balanced', phys


def best_attacks(species, cat, my_types, n):
    L = learnset(species)
    p = POKE[species]
    pool = [MOVE[m] for m in L if m in MOVE and MOVE[m]['cat'] == cat and (MOVE[m]['pow'] or 0) >= 50
            and (MOVE[m]['acc'] or 100) >= 85 and m not in ('はかいこうせん', 'ギガインパクト', 'だいばくはつ', 'じばく', 'ソーラービーム',
                                                        'ソーラーブレード', 'いのちがけ', 'あばれる', 'はなびらのまい', 'きあいパンチ', 'ゆめくい', 'カウンター', 'ミラーコート', 'すてみタックル' if 'normal' not in p['types'] else '')]
    out = []
    for t in p['types']:
        st = sorted([m for m in pool if m['type'] == t], key=lambda m: -(m['pow'] * (m['acc'] or 100)))
        if st:
            out.append(st[0]['ja'])
    covered = {MOVE[m]['type'] for m in out}
    rest = sorted([m for m in pool if m['type'] not in covered],
                  key=lambda m: -(m['pow'] * sum(max(eff(m['type'], t), 0.5) for t in my_types)))
    for m in rest:
        if len(out) >= n: break
        if m['type'] not in {MOVE[x]['type'] for x in out}:
            out.append(m['ja'])
    return out[:n]


def role_candidates(species, my_types=()):
    role, phys = role_of(species)
    L = learnset(species)
    cat = 'physical' if phys else 'special'
    first = lambda xs: next((x for x in xs if x in L), None)
    pri = first(PRIORITY_MOVES if phys else ['しんくうは', 'アクアジェット'])
    setup = first(SETUP_PHYS if phys else SETUP_SPEC)
    rec = first(RECOVERY)
    stat = [x for x in STATUS if x in L]
    att = best_attacks(species, cat, my_types, 4)
    defs = []
    up = 'atk' if phys else 'spa'
    if role.startswith('wall'):
        dstat = 'def' if role == 'wall_b' else 'spd'
        nat = {('def', True): 'わんぱく', ('def', False): 'ずぶとい', ('spd', True): 'しんちょう', ('spd', False): 'おだやか'}[(dstat, phys)]
        moves = (att[:1] + [rec] + stat[:2] + att[1:2])
        moves = [m for m in moves if m][:4]
        for item, p in (('たべのこし', .45), ('ゴツゴツメット', .3), ('オボンのみ', .25)):
            defs.append((nat, {'hp': 32, dstat: 32, ('spd' if dstat == 'def' else 'def'): 2}, item, moves, p))
    else:
        fast = role.startswith('fast') or role == 'balanced'
        natf = ('ようき' if phys else 'おくびょう'); nats = ('いじっぱり' if phys else 'ひかえめ')
        base_moves = att[:3] + [pri or setup or (att[3] if len(att) > 3 else None)]
        base_moves = [m for m in base_moves if m]
        setup_moves = att[:2] + [m for m in (setup, pri) if m] + att[2:]
        setup_moves = list(dict.fromkeys(setup_moves))[:4]
        sp_fast = {'hp': 2, up: 32, 'spe': 32}
        sp_bulk = {'hp': 32, up: 32, 'spd' if phys else 'def': 2}
        opts = []
        if fast:
            opts += [(natf, sp_fast, 'きあいのタスキ', setup_moves, .25), (nats, sp_fast, 'いのちのたま', base_moves, .2),
                     (natf, sp_fast, 'こだわりスカーフ', att[:4], .2), (nats, sp_fast, 'きあいのタスキ', setup_moves, .1)]
        opts += [(nats, sp_bulk, 'オボンのみ', base_moves, .15 if fast else .4), (nats, sp_bulk, 'いのちのたま', base_moves, .1 if fast else .3)]
        defs = opts
    out = []
    ms = MEGAS.get(species, [])
    ab = POKE[species]['ab'][0]
    for nat, sp, item, moves, p in defs:
        sp = {k: v for k, v in sp.items() if v}
        base = Mon(species, nat, sp, ab, item, moves, label=species)
        out.append(Cand(p * (0.5 if ms else 1), f"{nat}/{base.sp_str()}/{item}", base, None,
                        {m: 50 for m in moves}, 'role'))
        for mname in ms:  # mega variant of the same build
            stone = 'メガストーン'
            mb = Mon(species, nat, sp, ab, stone, moves, label=species)
            mm = Mon(mname, nat, sp, POKE[mname]['ab'][0], stone, moves, label=mname)
            out.append(Cand(p * 0.5 / len(ms), f"{nat}/{base.sp_str()}/{mname}", mb, mm, {m: 50 for m in moves}, 'role'))
    tot = sum(c.prior for c in out) or 1
    for c in out:
        c.prior /= tot
    return out


def candidates(species, my_types=()):
    return usage_candidates(species) or role_candidates(species, tuple(map(tuple, my_types)))


def usage_rank(species):
    u = USAGE.get(species)
    return u['rank'] if u and u.get('rank') else 300
