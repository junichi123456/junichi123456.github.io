"""Pokémon Champions (Lv50 / 能力ポイント制) damage calculator.

Gen9 damage formula with 4096-based modifier chains and pokeRound.
Data: data/pokemon.json, data/moves.json (exported from damekei.com bundles).
"""
import json, os, math, itertools

HERE = os.path.dirname(os.path.abspath(__file__))
_P = json.load(open(os.path.join(HERE, 'data/pokemon.json')))
_M = json.load(open(os.path.join(HERE, 'data/moves.json')))
POKE = {}
_PREFIX = {'blade': 'ブレード', 'heat': 'ヒート', 'wash': 'ウォッシュ', 'frost': 'フロスト', 'fan': 'スピン', 'mow': 'カット',
           'alola': 'アローラ', 'galar': 'ガラル', 'hisui': 'ヒスイ'}
for p in _P:
    if p['form'] in _PREFIX:
        POKE.setdefault(_PREFIX[p['form']] + p['ja'], p)
    elif p['form'] == 'female':
        POKE.setdefault(p['ja'] + '♀', p)
    else:
        POKE.setdefault(p['ja'], p)
MOVE = {m['ja']: m for m in _M}
for _k in list(MOVE):
    MOVE.setdefault(_k.translate(str.maketrans('０１２３４５６７８９', '0123456789')), MOVE[_k])

TYPES = ['normal', 'fire', 'water', 'electric', 'grass', 'ice', 'fighting', 'poison', 'ground',
         'flying', 'psychic', 'bug', 'rock', 'ghost', 'dragon', 'dark', 'steel', 'fairy']
JT = dict(zip(TYPES, ['ノーマル', 'ほのお', 'みず', 'でんき', 'くさ', 'こおり', 'かくとう', 'どく', 'じめん',
                      'ひこう', 'エスパー', 'むし', 'いわ', 'ゴースト', 'ドラゴン', 'あく', 'はがね', 'フェアリー']))
_SE = {
    'normal': ({}, ['rock', 'steel'], ['ghost']),
    'fire': (['grass', 'ice', 'bug', 'steel'], ['fire', 'water', 'rock', 'dragon'], []),
    'water': (['fire', 'ground', 'rock'], ['water', 'grass', 'dragon'], []),
    'electric': (['water', 'flying'], ['electric', 'grass', 'dragon'], ['ground']),
    'grass': (['water', 'ground', 'rock'], ['fire', 'grass', 'poison', 'flying', 'bug', 'dragon', 'steel'], []),
    'ice': (['grass', 'ground', 'flying', 'dragon'], ['fire', 'water', 'ice', 'steel'], []),
    'fighting': (['normal', 'ice', 'rock', 'dark', 'steel'], ['poison', 'flying', 'psychic', 'bug', 'fairy'], ['ghost']),
    'poison': (['grass', 'fairy'], ['poison', 'ground', 'rock', 'ghost'], ['steel']),
    'ground': (['fire', 'electric', 'poison', 'rock', 'steel'], ['grass', 'bug'], ['flying']),
    'flying': (['grass', 'fighting', 'bug'], ['electric', 'rock', 'steel'], []),
    'psychic': (['fighting', 'poison'], ['psychic', 'steel'], ['dark']),
    'bug': (['grass', 'psychic', 'dark'], ['fire', 'fighting', 'poison', 'flying', 'ghost', 'steel', 'fairy'], []),
    'rock': (['fire', 'ice', 'flying', 'bug'], ['fighting', 'ground', 'steel'], []),
    'ghost': (['psychic', 'ghost'], ['dark'], ['normal']),
    'dragon': (['dragon'], ['steel'], ['fairy']),
    'dark': (['psychic', 'ghost'], ['fighting', 'dark', 'fairy'], []),
    'steel': (['ice', 'rock', 'fairy'], ['fire', 'water', 'electric', 'steel'], []),
    'fairy': (['fighting', 'dragon', 'dark'], ['fire', 'poison', 'steel'], []),
}


def eff(atk, dtypes):
    e = 1.0
    for d in dtypes:
        se, nve, imm = _SE[atk]
        if d in imm:
            return 0.0
        if d in se:
            e *= 2
        elif d in nve:
            e *= 0.5
    return e


NATURE = {  # name: (up, down)
    'いじっぱり': ('atk', 'spa'), 'ようき': ('spe', 'spa'), 'ひかえめ': ('spa', 'atk'), 'おくびょう': ('spe', 'atk'),
    'わんぱく': ('def', 'spa'), 'ずぶとい': ('def', 'atk'), 'しんちょう': ('spd', 'spa'), 'おだやか': ('spd', 'atk'),
    'ゆうかん': ('atk', 'spe'), 'れいせい': ('spa', 'spe'), 'のんき': ('def', 'spe'), 'なまいき': ('spd', 'spe'),
    'むじゃき': ('spe', 'spd'), 'せっかち': ('spe', 'def'), 'やんちゃ': ('atk', 'spd'), 'うっかりや': ('spa', 'spd'),
    'まじめ': (None, None),
}
STATS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe']
_BS = ['hp', 'attack', 'defense', 'specialAttack', 'specialDefense', 'speed']


def pokeround(x):
    f = math.floor(x)
    return f if x - f <= 0.5 else f + 1


def chain(mods):
    c = 4096
    for m in mods:
        c = (c * m + 2048) >> 12
    return c


def apply_mod(v, m):
    return pokeround(v * m / 4096)


class Mon:
    def __init__(self, species, nature='まじめ', sp=None, ability=None, item=None, moves=(), label=None):
        self.p = POKE[species]
        self.species = species
        self.label = label or species
        self.types = list(self.p['types'])
        self.nature = nature
        self.sp = dict(hp=0, atk=0, defn=0, spa=0, spd=0, spe=0)
        sp = {('def' if k == 'defn' else k): v for k, v in (sp or {}).items()}
        assert sum(sp.values()) <= 66 and all(v <= 32 for v in sp.values()), (species, sp)
        self.spv = {k: sp.get(k, 0) for k in STATS}
        self.ability = ability or self.p['ab'][0]
        self.item = item
        self.moves = list(moves)
        up, dn = NATURE[nature]
        bs = dict(zip(STATS, [self.p['bs'][k] for k in _BS]))
        self.base = bs
        self.stat = {}
        for k in STATS:
            if k == 'hp':
                self.stat[k] = bs[k] + 75 + self.spv[k]
            else:
                m = 1.1 if k == up else 0.9 if k == dn else 1.0
                self.stat[k] = math.floor((bs[k] + 20 + self.spv[k]) * m)

    def sp_str(self):
        lab = dict(hp='H', atk='A', defn='B', spa='C', spd='D', spe='S')
        lab['def'] = 'B'
        return ' '.join(f"{lab[k]}{v}" for k, v in self.spv.items() if v)

    def stat_str(self):
        return '-'.join(str(self.stat[k]) for k in STATS)

    def speed(self, boost=0, scarf=None, para=False):
        s = self.stat['spe']
        s = s * (2 + boost) // 2 if boost >= 0 else s * 2 // (2 - boost)
        if scarf if scarf is not None else self.item == 'こだわりスカーフ':
            s = pokeround(s * 6144 / 4096)
        if para:
            s //= 2
        return s


def boosted(v, b):
    return v * (2 + b) // 2 if b >= 0 else v * 2 // (2 - b)


SLICING = {'つじぎり', 'サイコカッター', 'シャドークロー', 'きりさく', 'シザークロス', 'リーフブレード', 'せいなるつるぎ',
           'アクアカッター', 'ドラゴンクロー', 'エアスラッシュ', 'ソーラーブレード', 'がんせきアックス', 'つばめがえし', 'れんぞくぎり',
           'ひけん・ちえなみ', 'きょけんとつげき', 'ネズミざん', 'トリックフラワー'}
SLICING -= {'きょけんとつげき', 'トリックフラワー'}
PUNCH = {'れいとうパンチ', 'かみなりパンチ', 'ほのおのパンチ', 'バレットパンチ', 'マッハパンチ', 'ドレインパンチ',
         'アームハンマー', 'コメットパンチ', 'シャドーパンチ', 'ばくれつパンチ', 'メガトンパンチ', 'でんこうそうげき', 'ジェットパンチ',
         'ふんどのこぶし', 'すいりゅうれんだ', 'あんこくきょうだ', 'グロウパンチ', 'スカイアッパー', 'きあいパンチ'}
TYPE_ITEM = {'もくたん': 'fire', 'しんぴのしずく': 'water', 'じしゃく': 'electric', 'きせきのタネ': 'grass',
             'とけないこおり': 'ice', 'くろおび': 'fighting', 'どくバリ': 'poison', 'やわらかいすな': 'ground',
             'するどいくちばし': 'flying', 'まがったスプーン': 'psychic', 'ぎんのこな': 'bug', 'かたいいし': 'rock',
             'のろいのおふだ': 'ghost', 'りゅうのキバ': 'dragon', 'くろいメガネ': 'dark', 'メタルコート': 'steel',
             'ようせいのハネ': 'fairy', 'シルクのスカーフ': 'normal'}
RESIST_BERRY = {'オッカのみ': 'fire', 'イトケのみ': 'water', 'ソクノのみ': 'electric', 'リンドのみ': 'grass',
                'ヤチェのみ': 'ice', 'ヨプのみ': 'fighting', 'ビアーのみ': 'poison', 'シュカのみ': 'ground',
                'バコウのみ': 'flying', 'ウタンのみ': 'psychic', 'タンガのみ': 'bug', 'ヨロギのみ': 'rock',
                'カシブのみ': 'ghost', 'ハバンのみ': 'dragon', 'ナモのみ': 'dark', 'リリバのみ': 'steel',
                'ロゼルのみ': 'fairy', 'ホズのみ': 'normal'}
MULTI = {'つららばり': (2, 5), 'スケイルショット': (2, 5), 'ロックブラスト': (2, 5), 'タネマシンガン': (2, 5),
         'ダブルウイング': (2, 2), 'ドラゴンアロー': (2, 2), 'すいりゅうれんだ': (3, 3)}
SKIN = {'スカイスキン': 'flying', 'フェアリースキン': 'fairy', 'フリーズスキン': 'ice', 'ドラゴンスキン': 'dragon'}


def calc(att, dfn, move, *, atk_boost=0, def_boost=0, crit=False, weather=None, terrain=None,
         burned=False, screen=False, intimidated=False, def_full_hp=True, hits=None,
         helping=False, target_grounded=None, att_grounded=None, glaive=False, extra_power_mod=None):
    """Return list of 16 damage rolls (sum over hits for multi-hit)."""
    mv = MOVE[move]
    cat = mv['cat']
    if cat == 'status':
        return [0] * 16
    mtype = mv['type']
    power = mv['pow'] or 0
    power_mods = []
    a_ab, d_ab = att.ability, dfn.ability
    moldbreaker = a_ab in ('かたやぶり',)
    if move == 'ウェザーボール' and weather:
        power = 100
    if move == 'だいちのはどう' and terrain and (att_grounded is not False):
        power = 100
        mtype = {'electric': 'electric', 'grassy': 'grass', 'psychic': 'psychic', 'misty': 'fairy'}[terrain]
    if move == 'ゆきなだれ':
        pass
    skin = False
    if mtype == 'normal' and a_ab in SKIN:
        mtype = SKIN[a_ab]
        skin = True
    if move == 'テラバースト':
        pass
    if move == 'ボディプレス':
        A_stat, A_boost = att.stat['def'], atk_boost
    elif cat == 'physical':
        A_stat, A_boost = att.stat['atk'], atk_boost - (1 if intimidated else 0)
    else:
        A_stat, A_boost = att.stat['spa'], atk_boost
    if move == 'イカサマ':
        A_stat = dfn.stat['atk']
    D_key = 'def' if (cat == 'physical' or move in ('サイコショック', 'サイコブレイク')) else 'spd'
    D_stat = dfn.stat[D_key]
    if crit:
        A_boost = max(A_boost, 0)
        def_boost = min(def_boost, 0)
    if d_ab == 'てんねん' and not moldbreaker:
        A_boost = 0
    if a_ab == 'てんねん':
        def_boost = 0
    A = boosted(A_stat, A_boost)
    D = boosted(D_stat, def_boost)
    # weather defense
    if weather == 'sand' and 'rock' in dfn.types and D_key == 'spd':
        D = math.floor(D * 1.5)
    if weather == 'snow' and 'ice' in dfn.types and D_key == 'def':
        D = math.floor(D * 1.5)
    # type effectiveness / immunities
    e = eff(mtype, dfn.types)
    grounded_t = target_grounded if target_grounded is not None else not (
        'flying' in dfn.types or (d_ab == 'ふゆう') or dfn.item == 'ふうせん')
    if mtype == 'ground' and not grounded_t and not moldbreaker and move != 'サウザンアロー':
        e = 0.0
    if mtype == 'ground' and 'flying' in dfn.types and moldbreaker:
        e = 0.0
    if not moldbreaker:
        if d_ab in ('ちょすい', 'よびみず') and mtype == 'water': e = 0
        if d_ab in ('ちくでん', 'ひらいしん', 'でんきエンジン') and mtype == 'electric': e = 0
        if d_ab in ('もらいび',) and mtype == 'fire': e = 0
        if d_ab in ('そうしょく',) and mtype == 'grass': e = 0
        if d_ab == 'でんきにかえる' and False: e = 0
        if d_ab == 'ばけのかわ' and def_full_hp and e > 0:
            return [0] * 16  # disguise blocks (1/8 chip handled separately)
    if e == 0:
        return [0] * 16
    # base power modifiers
    if skin:
        power_mods.append(4915)
    if a_ab == 'かたいツメ' and mv['contact']:
        power_mods.append(5325)
    if a_ab == 'きれあじ' and move in SLICING:
        power_mods.append(6144)
    if a_ab == 'てつのこぶし' and move in PUNCH:
        power_mods.append(4915)
    if a_ab == 'テクニシャン' and power <= 60:
        power_mods.append(6144)
    if a_ab == 'すなのちから' and weather == 'sand' and mtype in ('rock', 'ground', 'steel'):
        power_mods.append(5325)
    if a_ab == 'ほのおのたてがみ' and mtype == 'fire':
        power_mods.append(6144)
    if a_ab == 'メガランチャー' and move in ('はどうだん', 'あくのはどう', 'みずのはどう', 'りゅうのはどう', 'だいちのはどう'):
        power_mods.append(6144)
    if a_ab == 'がんじょうあご' and move in ('かみくだく', 'こおりのキバ', 'ほのおのキバ', 'かみなりのキバ', 'サイコファング', 'どくどくのキバ', 'エラがみ'):
        power_mods.append(6144)
    if a_ab == 'ちからずく' and False:
        power_mods.append(5325)
    if a_ab == 'フェアリーオーラ' and mtype == 'fairy':
        power_mods.append(5448)
    if att.item in TYPE_ITEM and TYPE_ITEM[att.item] == mtype:
        power_mods.append(4915)
    if att.item == 'ノーマルジュエル' and mtype == 'normal':
        power_mods.append(5325)
    if d_ab == 'たいねつ' and mtype == 'fire':
        power_mods.append(2048)
    if d_ab == 'かんそうはだ' and mtype == 'fire':
        power_mods.append(5120)
    if terrain and (att_grounded if att_grounded is not None else not (
            'flying' in att.types or a_ab == 'ふゆう' or att.item == 'ふうせん')):
        tmap = {'electric': 'electric', 'grassy': 'grass', 'psychic': 'psychic'}
        if tmap.get(terrain) == mtype:
            power_mods.append(5325)
    if terrain == 'misty' and mtype == 'dragon' and grounded_t:
        power_mods.append(2048)
    if terrain == 'grassy' and move in ('じしん', 'じならし', 'マグニチュード') and grounded_t:
        power_mods.append(2048)
    if helping:
        power_mods.append(6144)
    if extra_power_mod:
        power_mods.append(extra_power_mod)
    bp = max(1, apply_mod(power, chain(power_mods)))
    # attack modifiers
    a_mods = []
    if a_ab in ('ちからもち', 'ヨガパワー') and cat == 'physical':
        a_mods.append(8192)
    if a_ab == 'サンパワー' and weather == 'sun' and cat == 'special':
        a_mods.append(6144)
    if a_ab in ('もうか', 'げきりゅう', 'しんりょく', 'むしのしらせ'):
        pass
    if d_ab == 'あついしぼう' and mtype in ('fire', 'ice') and not moldbreaker:
        a_mods.append(2048)
    A = max(1, apply_mod(A, chain(a_mods)))
    d_mods = []
    if d_ab == 'ファーコート' and D_key == 'def' and not moldbreaker:
        d_mods.append(8192)
    D = max(1, apply_mod(D, chain(d_mods)))
    base = math.floor(math.floor(22 * bp * A / D) / 50) + 2
    # weather
    if weather == 'sun':
        if mtype == 'fire': base = apply_mod(base, 6144)
        if mtype == 'water': base = apply_mod(base, 2048)
    if weather == 'rain':
        if mtype == 'water': base = apply_mod(base, 6144)
        if mtype == 'fire': base = apply_mod(base, 2048)
    if glaive:
        base = base * 2
    if crit:
        base = apply_mod(base, 6144)
    stab_types = set(att.types)
    protean = a_ab in ('へんげんじざい', 'リベロ')
    stab = 4096
    if mtype in stab_types or protean:
        stab = 8192 if a_ab == 'てきおうりょく' else 6144
    final = []
    if screen and not crit:
        final.append(2048)
    if d_ab in ('マルチスケイル', 'ファントムガード') and def_full_hp and not moldbreaker:
        final.append(2048)
    if d_ab in ('フィルター', 'ハードロック', 'プリズムアーマー') and e > 1 and not moldbreaker:
        final.append(3072)
    if d_ab == 'はどうのぼうご' and mv['contact'] and not moldbreaker:
        final.append(2048)
    if d_ab == 'もふもふ' and mv['contact'] and not moldbreaker:
        final.append(2048)
    if d_ab == 'こおりのりんぷん' and cat == 'special':
        final.append(2048)
    if att.item == 'たつじんのおび' and e > 1:
        final.append(4915)
    if att.item == 'いのちのたま':
        final.append(5324)
    if dfn.item in RESIST_BERRY and (RESIST_BERRY[dfn.item] == mtype) and (e > 1 or mtype == 'normal'):
        final.append(2048)
    fm = chain(final)
    rolls = []
    for r in range(85, 101):
        d = math.floor(base * r / 100)
        d = apply_mod(d, stab)
        d = math.floor(d * e)
        if burned and cat == 'physical' and a_ab != 'こんじょう':
            d = apply_mod(d, 2048)
        d = apply_mod(d, fm)
        rolls.append(max(1, d))
    n = hits
    if n is None:
        if move == 'トリプルアクセル':
            # 20/40/60 escalating, compute separately
            tot = [0] * 16
            for p in (20, 40, 60):
                r2 = calc(att, dfn, '__power__' if False else move, atk_boost=atk_boost, def_boost=def_boost, crit=crit,
                          weather=weather, terrain=terrain, burned=burned, screen=screen, intimidated=intimidated,
                          def_full_hp=def_full_hp, hits=1, extra_power_mod=int(4096 * p / 20))
                tot = [a + b for a, b in zip(tot, r2)]
            return tot
        if move in MULTI:
            n = MULTI[move][1] if att.ability == 'スキルリンク' else (MULTI[move][0] if MULTI[move][0] == MULTI[move][1] else None)
            if n is None:
                n = 2 if att.item != 'いかさまダイス' else 4
                n = MULTI[move][0] if False else n
        else:
            n = 1
    if n and n > 1:
        rolls = [x * n for x in rolls]
    return rolls


def ko_text(rolls, hp, chip=0, max_hits=4):
    """Approx KO probability (independent rolls)."""
    if max(rolls) == 0:
        return '無効/0'
    lo, hi = rolls[0], rolls[-1]
    pct = f"{lo / hp * 100:.1f}-{hi / hp * 100:.1f}%"
    eff_hp = hp - chip
    for n in range(1, max_hits + 1):
        cnt = 0
        tot = 0
        for combo in itertools.product(rolls, repeat=n) if n <= 3 else []:
            tot += 1
            if sum(combo) >= eff_hp:
                cnt += 1
        if n > 3:
            if min(rolls) * n >= eff_hp:
                return f"{pct} 確定{n}発"
            if max(rolls) * n >= eff_hp:
                return f"{pct} 乱数{n}発"
            continue
        if cnt == tot:
            return f"{pct} 確定{n}発"
        if cnt > 0:
            return f"{pct} 乱数{n}発({cnt / tot * 100:.1f}%)"
    return f"{pct} {max_hits + 1}発以上"


def show(att, dfn, move, chip=0, **kw):
    r = calc(att, dfn, move, **kw)
    return f"{att.label} {move} → {dfn.label}: {r[0]}-{r[-1]} ({ko_text(r, dfn.stat['hp'], chip)})"


_L = json.load(open(os.path.join(HERE, 'data/learnsets.json')))
_MID = {m['id']: m for m in _M}


def learnset(species):
    p = POKE[species]
    ids = _L.get(str(p['id'])) or _L.get(str(p.get('baseId'))) or []
    if p.get('baseId'):
        ids = set(ids) | set(_L.get(str(p['baseId']), []))
    return {_MID[i]['ja'].translate(str.maketrans('０１２３４５６７８９', '0123456789')) for i in ids if i in _MID}
