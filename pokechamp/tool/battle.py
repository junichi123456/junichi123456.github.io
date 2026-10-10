"""Real-time battle assistant for Pokémon Champions singles (6→3).

  python3 battle.py select <相手6体...>      選出順を出す
  python3 battle.py turn state.json [秒数]   次の行動を出す（5ターン木＋ロールアウトで8ターン先まで）
  python3 battle.py infer <相手> [obs.json]  相手の型の事後確率（上位5）

対戦のシミュレーションは engine.py（Pokémon Showdown の Champions ルールを移植。全ての技・特性・持ち物・
場の状態を実装し、Showdown と差分テスト済み）で行い、探索は search.py が担当する。

State JSON (logger の表示を写す):
{
  "me":  [{"name": "ガブリアス", "hp": 185, "status": null, "boosts": {}, "item": true, "mega": false}, ...],
  "opp": [{"name": "ボーマンダ", "hp_pct": 100, "status": null, "boosts": {}, "item": true, "mega": false,
           "moves_seen": ["すてみタックル"], "item_seen": null,
           "obs": [ ...infer.py の観測... ]}, ...],
  # 相手の型は sets.py の候補（使用率258種＋役割推定）を infer.py で観測から絞り込んで決める。
  # learn.py turn で記録した観測（logs/current.json）も自動で読み込む。
  "active_me": 0, "active_opp": 0,
  "rocks_me": false, "rocks_opp": false,   # 自分側/相手側にステロがあるか
  "cond_me": {}, "cond_opp": {},           # 任意: {"spikes": 2, "toxicspikes": 1, "stickyweb": true,
                                           #        "reflect": 3, "lightscreen": 2, "auroraveil": 4, "tailwind": 2}
  "mega_used_me": false, "mega_used_opp": false,
  "weather": null, "weather_turns": 0, "terrain": null, "terrain_turns": 0,
  "opp_last_move": null, "trick_room": 0,       # トリックルームの残りターン
  "pseudo": {}                                  # 任意: {"gravity": 3, "magicroom": 2, "wonderroom": 4}
}
各ポケモンに任意で: "last_move"（こだわり固定）, "rampage": true（げきりん等の継続中）, "sub": 25（みがわりHP%）,
"glaive": true（前ターンにきょけんとつげき）, "toxn": 2（もうどくの経過ターン）, "status": "psn"/"tox"/...,
"confusion"/"leechseed"/"perishsong"/"curse"/"saltcure"/"healblock"/"torment": true（場に出ている側のみ）
確率: 1ターン目は乱数（確定/乱数KO）・命中・急所・まひ・追加効果・ねむり/こおりのターン数を確率分岐し、
2ターン目以降は最もありうる結果（命中率・まひはダメージ期待値に反映）で読む。
"""
import copy, itertools, json, math, os, sys, time
from functools import lru_cache
from calc import Mon, MOVE, POKE, calc, eff, learnset
from meta import META
from team import TEAM

# ---------------------------------------------------------------- set database
MEGA_OF = {}  # base species -> mega species name in data
for _p in POKE.values():
    if _p.get('form') and 'mega' in _p['form'] and _p.get('baseId'):
        for _b in POKE.values():
            if _b['id'] == _p['baseId'] and not _b.get('form'):
                MEGA_OF.setdefault(_b['ja'], []).append(_p['ja'])
BASE_OF = {m: b for b, ms in MEGA_OF.items() for m in ms}

STONE_FOR = {}
for b, ms in MEGA_OF.items():
    for m in ms:
        suf = m[-1] if m[-1] in 'ＸＹＺ' else ''
        STONE_FOR[m] = b + 'ナイト' + {'Ｘ': 'X', 'Ｙ': 'Y', 'Ｚ': 'Z'}.get(suf, '')

SPECIES_ALIAS = {'イダイトウ（オス）': 'イダイトウ', 'イダイトウ(オス)': 'イダイトウ', 'イダイトウ（メス）': 'イダイトウ♀',
                 'イエッサン(オス)': 'イエッサン', 'イエッサン(メス)': 'イエッサン♀', 'フラエッテ(永遠)': 'フラエッテ',
                 'ギルガルド(ブレード)': 'ブレードギルガルド'}


def norm(name):
    name = SPECIES_ALIAS.get(name, name)
    return name.replace('Z', 'Ｚ').replace('X', 'Ｘ').replace('Y', 'Ｙ') if name.startswith('メガ') else name


USAGE_RANK = {}
for i, n in enumerate("""ガブリアス ボーマンダ アシレーヌ セグレイブ ルカリオ グソクムシャ カバルドン ブリジュラス サーフゴー ミミッキュ
ゴリランダー リザードン マスカーニャ アーマーガア キラフロル オオニューラ エースバーン ギャラドス イダイトウ メタグロス ギルガルド
イエッサン ゲッコウガ カイリュー カメックス アローラキュウコン パーモット ウォッシュロトム ウルガモス ラグラージ ゲンガー ラウドボーン
エンペルト ヒートロトム ドドゲザン サザンドラ ライチュウ ニンフィア バシャーモ ブラッキー マフォクシー ハッサム ドヒドイデ バンギラス
ムクホーク ペリッパー ジュペッタ ピクシー ミロカロス マンムー メタモン オーロンゲ ミミロップ アブソル""".split()):
    USAGE_RANK[n] = i + 1


def meta_set(base):
    """Return (base_mon, mega_mon or None) for an opponent species from usage data."""
    cands = [m for _, m in META if BASE_OF.get(m.species, m.species) == base]
    if cands:
        # prefer the most common entry (first listed); mega if the listed set holds the stone
        m = cands[0]
        mega = None
        if m.species != base:
            mega = m
            bp = POKE[base]
            babil = bp['ab'][-1] if base in ('ボーマンダ', 'ギャラドス') else bp['ab'][0]
            if base == 'グソクムシャ': babil = 'ききかいひ'
            if base == 'ガブリアス': babil = 'さめはだ'
            if base == 'セグレイブ': babil = 'ねつこうかん'
            if base == 'ボーマンダ': babil = 'いかく'
            if base == 'ギャラドス': babil = 'いかく'
            basemon = Mon(base, m.nature, m.spv, babil, m.item, m.moves, label=base)
            return basemon, mega
        return m, None
    return generic_set(base), None


GOOD_STATUS = {'どくどく', 'キノコのほうし', 'さいみんじゅつ', 'ねむりごな', 'つるぎのまい', 'りゅうのまい', 'わるだくみ', 'めいそう', 'ステルスロック', 'おにび', 'でんじは', 'あくび', 'はねやすめ',
               'じこさいせい', 'なまける', 'ちょうのまい', 'からをやぶる', 'キングシールド', 'まもる', 'アンコール', 'ちょうはつ'}


def generic_set(sp):
    p = POKE[sp]
    bs = p['bs']
    phys = bs['attack'] >= bs['specialAttack']
    cat = 'physical' if phys else 'special'
    L = learnset(sp)
    nature = ('いじっぱり' if phys else 'ひかえめ') if bs['speed'] < 70 else ('ようき' if phys else 'おくびょう')
    spv = dict(hp=2, atk=32, spe=32) if phys else dict(hp=2, spa=32, spe=32)
    bad = {'はかいこうせん', 'ギガインパクト', 'だいばくはつ', 'じばく', 'すてみタックル' if 'normal' not in p['types'] else '',
           'ソーラービーム', 'ソーラーブレード', 'いのちがけ', 'げきりん' if False else '', 'あばれる', 'はなびらのまい'}
    moves = []
    pool = [MOVE[m] for m in L if m in MOVE and MOVE[m]['cat'] == cat and (MOVE[m]['pow'] or 0) > 0 and m not in bad
            and (MOVE[m]['acc'] or 100) >= 80 and not MOVE[m]['ja'].startswith('Ｇ')]
    for t in p['types']:
        st = sorted([m for m in pool if m['type'] == t], key=lambda m: -(m['pow'] * (m['acc'] or 100)))
        if st: moves.append(st[0]['ja'])
    covered = {MOVE[m]['type'] for m in moves}
    my_types = [m.types for m in TEAM]
    rest = sorted([m for m in pool if m['type'] not in covered],
                  key=lambda m: -(m['pow'] * sum(max(eff(m['type'], t), 0.5) for t in my_types)))
    for m in rest:
        if len(moves) >= 4: break
        if m['type'] in {MOVE[x]['type'] for x in moves}: continue
        moves.append(m['ja'])
    ab = p['ab'][0]
    return Mon(sp, nature, spv, ab, None, moves[:4], label=sp)


def my_sets():
    out = {}
    for m in TEAM:
        if m.species in BASE_OF:
            base = BASE_OF[m.species]
            babil = POKE[base]['ab'][0]
            out[base] = (Mon(base, m.nature, m.spv, babil, m.item, m.moves, label=base), m)
        else:
            out[m.species] = (m, None)
    return out


MY = my_sets()

# ---------------------------------------------------------------- battle model
PRIORITY = {m: MOVE[m]['pri'] for m in MOVE}
PRIORITY['グラススライダー'] = 0  # +1 only in grassy terrain (handled)
RECOIL = {'すてみタックル': 1 / 3, 'ウェーブタックル': 1 / 3, 'フレアドライブ': 1 / 3, 'ブレイブバード': 1 / 3, 'ウッドハンマー': 1 / 3,
          'もろはのずつき': 1 / 2, 'ボルテッカー': 1 / 3, 'とびひざげり': 0}
SELF_DROP = {'オーバーヒート': {'spa': -2}, 'りゅうせいぐん': {'spa': -2}, 'ゴールドラッシュ': {'spa': -2}, 'リーフストーム': {'spa': -2},
             'インファイト': {'def': -1, 'spd': -1}, 'アーマーキャノン': {'def': -1, 'spd': -1}, 'ばかぢから': {'atk': -1, 'def': -1},
             'でんこうそうげき': {}, 'ドラゴンアロー': {}}
SETUP = {'つるぎのまい': {'atk': 2}, 'りゅうのまい': {'atk': 1, 'spe': 1}, 'わるだくみ': {'spa': 2}, 'めいそう': {'spa': 1, 'spd': 1},
         'ちょうのまい': {'spa': 1, 'spd': 1, 'spe': 1}, 'からをやぶる': {'atk': 2, 'spa': 2, 'spe': 2, 'def': -1, 'spd': -1},
         'ビルドアップ': {'atk': 1, 'def': 1}, 'てっぺき': {'def': 2}, 'こうそくいどう': {'spe': 2}, 'のろい': {'atk': 1, 'def': 1, 'spe': -1},
         'ほのおのまい': {}, 'ニトロチャージ': {}}
ON_HIT_SELF = {'ほのおのまい': {'spa': 1}, 'ニトロチャージ': {'spe': 1}, 'くさわけ': {'spe': 1}, 'スケイルショット': {'spe': 1, 'def': -1},
               'がんせきふうじ': None, 'こごえるかぜ': None, 'マッドショット': None}
TARGET_DROP = {'がんせきふうじ': {'spe': -1}, 'こごえるかぜ': {'spe': -1}, 'マッドショット': {'spe': -1}, 'じならし': {'spe': -1},
               'ドラムアタック': {'spe': -1}, 'トリックフラワー': {}}
HEAL = {'はねやすめ': .5, 'じこさいせい': .5, 'なまける': .5, 'あさのひざし': .5, 'つきのひかり': .5, 'さいきのいのり': 0, 'ミルクのみ': .5}
PIVOT = {'とんぼがえり', 'ボルトチェンジ', 'クイックターン'}
PHAZE = {'ふきとばし', 'ほえる', 'ドラゴンテール'}
PROTECT = {'まもる', 'キングシールド', 'みきり', 'トーチカ'}
DRAIN = {'きゅうけつ': .5, 'ドレインパンチ': .5, 'ギガドレイン': .5, 'ドレインキッス': .75}
SLOW_PIVOT_ALWAYS_FIRST = {'であいがしら', 'ねこだまし'}
CHOICE = {'こだわりスカーフ', 'こだわりハチマキ', 'こだわりメガネ'}
RAMPAGE = {'げきりん', 'あばれる', 'はなびらのまい'}
SLEEP_MOVES = {'キノコのほうし', 'ねむりごな', 'さいみんじゅつ', 'くさぶえ', 'ダークホール'}
POWDER = {'キノコのほうし', 'ねむりごな'}
BLOCKED_BY_SUB = {'おにび', 'でんじは', 'あくび', 'どくどく'} | SLEEP_MOVES
SOUND = {'ハイパーボイス', 'ばくおんぱ', 'りんしょう', 'むしのさざめき', 'スケイルノイズ', 'ブレイククロー', 'オーバードライブ',
         'サイコノイズ', 'みわくのボイス', 'フレアソング', 'うたかたのアリア', 'いびき'}
ALWAYS_CRIT = {'あんこくきょうだ', 'すいりゅうれんだ', 'トリックフラワー', 'こおりのいぶき', 'やまあらし'}
TRAP = {'かげふみ', 'ありじごく', 'じりょく'}
PARA_P = 0.125   # full paralysis chance
CRIT_P = 1 / 24


class BM:
    """Battle mon (mutable)."""
    __slots__ = ('base', 'mega', 'cur', 'hp', 'maxhp', 'status', 'boosts', 'item', 'disguise', 'can_mega', 'moves',
                 'sleep', 'encore', 'taunt', 'yawn', 'side', 'name', 'revealed', 'first_turn', 'prot', 'lock', 'rampage',
                 'glaive', 'toxn', 'sub', 'dbond')

    def __init__(self, base, mega=None, hp_frac=1.0):
        self.base, self.mega, self.cur = base, mega, base
        self.maxhp = base.stat['hp']
        self.hp = max(0, round(self.maxhp * hp_frac))
        self.status = None
        self.boosts = dict(atk=0, defn=0, spa=0, spd=0, spe=0)
        self.item = base.item
        self.disguise = base.ability == 'ばけのかわ'
        self.can_mega = mega is not None
        self.moves = list(base.moves)
        self.sleep = 0
        self.encore = None
        self.taunt = 0
        self.yawn = 0
        self.name = base.species
        self.first_turn = True
        self.prot = 0
        self.lock = None      # choice-locked move
        self.rampage = None   # (move, forced turns left) for げきりん etc.
        self.glaive = 0       # きょけんとつげき: takes double damage until end of next turn
        self.toxn = 0         # toxic counter
        self.sub = 0          # substitute HP
        self.dbond = False    # みちづれ active

    def clone(self):
        n = BM.__new__(BM)
        n.base, n.mega, n.cur, n.hp, n.maxhp, n.status = self.base, self.mega, self.cur, self.hp, self.maxhp, self.status
        n.boosts = self.boosts.copy(); n.item, n.disguise, n.can_mega = self.item, self.disguise, self.can_mega
        n.moves = self.moves; n.sleep, n.encore, n.taunt, n.yawn = self.sleep, self.encore, self.taunt, self.yawn
        n.name, n.first_turn, n.prot = self.name, self.first_turn, self.prot
        n.lock, n.rampage, n.glaive, n.toxn, n.sub, n.dbond = self.lock, self.rampage, self.glaive, self.toxn, self.sub, self.dbond
        return n

    @property
    def alive(self):
        return self.hp > 0

    def speed(self, field):
        s = self.cur.stat['spe']
        b = self.boosts['spe']
        s = s * (2 + b) // 2 if b >= 0 else s * 2 // (2 - b)
        if self.item == 'こだわりスカーフ': s = s * 3 // 2
        if self.status == 'par': s //= 2
        return s


class State:
    __slots__ = ('sides', 'act', 'rocks', 'mega_used', 'weather', 'wt', 'terrain', 'tt', 'turn', 'last', 'tr')

    def clone(self):
        n = State.__new__(State)
        n.sides = [[m.clone() for m in s] for s in self.sides]
        n.act = list(self.act); n.rocks = list(self.rocks); n.mega_used = list(self.mega_used)
        n.weather, n.wt, n.terrain, n.tt, n.turn = self.weather, self.wt, self.terrain, self.tt, self.turn
        n.last = list(self.last); n.tr = self.tr
        return n

    def active(self, i):
        return self.sides[i][self.act[i]]

    def done(self):
        a = any(m.alive for m in self.sides[0]); b = any(m.alive for m in self.sides[1])
        return None if a and b else (1 if a else -1 if b else 0)


_DMG = {}


def rolls(att, dfn, move, st, crit=False):
    """16 damage rolls (ascending) of att's move into dfn in the current state."""
    a, d = att.cur, dfn.cur
    mv = MOVE[move]
    if mv['cat'] == 'physical':
        ab, db = att.boosts['atk'], dfn.boosts['defn']
    else:
        ab, db = att.boosts['spa'], dfn.boosts['spd']
    if move == 'ボディプレス':
        ab = att.boosts['defn']
    full = dfn.hp == dfn.maxhp
    terr = st.terrain
    knock = move == 'はたきおとす' and removable(dfn)
    crit = crit or move in ALWAYS_CRIT
    key = (id(a), a.item if att.item else None, id(d), dfn.item, move, ab, db, att.status == 'brn', full and d.ability in ('マルチスケイル',),
           st.weather, terr, dfn.disguise, crit, dfn.glaive > 0, knock)
    r = _DMG.get(key)
    if r is None:
        aa = a
        if att.item != a.item:
            aa = copy.copy(a); aa.item = att.item
        dd = d
        if dfn.item != d.item:
            dd = copy.copy(d); dd.item = dfn.item
        if a.species == 'ギルガルド':
            aa = Mon('ブレードギルガルド', a.nature, a.spv, 'バトルスイッチ', att.item, a.moves)
        if d.ability == 'ばけのかわ' and dfn.disguise:
            r = (0,) * 16
        else:
            r = tuple(calc(aa, dd, move, atk_boost=ab, def_boost=db, burned=att.status == 'brn', weather=st.weather,
                           terrain=terr, def_full_hp=full, crit=crit, glaive=dfn.glaive > 0,
                           extra_power_mod=6144 if knock else None))
        _DMG[key] = r
    return r


def dmg(att, dfn, move, st):
    r = rolls(att, dfn, move, st)
    return r[7], r[0]


def removable(m):
    return bool(m.item) and 'ナイト' not in m.item and m.cur is not m.mega


def hit_prob(a, d, move, st):
    acc = MOVE[move]['acc']
    if not acc or acc >= 100 or d.glaive or 'ノーガード' in (a.cur.ability, d.cur.ability):
        return 1.0
    if move == 'ふぶき' and st.weather == 'snow': return 1.0
    if move in ('かみなり', 'ぼうふう') and st.weather == 'rain': return 1.0
    if move in ('かみなり', 'ぼうふう') and st.weather == 'sun': acc = 50
    if move == 'どくどく' and 'poison' in a.cur.types: return 1.0
    if a.cur.ability == 'ふくがん': acc = acc * 1.3
    return min(1.0, acc / 100)


def chance(st, i, act, oact):
    """Luck outcomes of side i's action as [(prob, spec)]: full paralysis, miss, KO / no-KO roll, crit.
    The roll is given as an index into the 16 rolls so it stays valid if the state changes mid-turn."""
    if act[0] != 'm': return [(1.0, None)]
    a = st.active(i)
    if not a.alive or (a.status == 'slp' and a.sleep > 0): return [(1.0, None)]
    move = act[1]
    d = st.sides[1 - i][oact[1]] if oact[0] == 's' else st.active(1 - i)
    pp = PARA_P if a.status == 'par' else 0.0
    acc = hit_prob(a, d, move, st)
    hits = [(1.0, ('r', 7))]
    if MOVE[move]['cat'] != 'status' and d.alive:
        r = rolls(a, d, move, st)
        hp = d.sub if (d.sub and move not in SOUND) else d.hp
        k = sum(1 for x in r if x < hp)  # rolls that do not KO
        if move in ALWAYS_CRIT:
            hits = [(1.0, ('c',))]
        else:
            if 0 < k < 16:
                hits = [(k / 16, ('r', (k - 1) // 2)), (1 - k / 16, ('r', (k + 15) // 2))]
            if k > 0 and d.cur.ability not in ('シェルアーマー', 'カブトアーマー') and rolls(a, d, move, st, True)[7] >= hp:
                hits = [(p * (1 - CRIT_P), sp) for p, sp in hits] + [(CRIT_P, ('c',))]
    out = []
    if pp: out.append((pp, ('skip',)))
    if acc < 1: out.append(((1 - pp) * (1 - acc), ('miss',)))
    out += [((1 - pp) * acc * p, sp) for p, sp in hits]
    return out


def legal_moves(m):
    mv = [x for x in m.moves if x in MOVE]
    if m.rampage and m.rampage[0] in mv:
        return [m.rampage[0]]
    if m.lock and m.item in CHOICE and m.lock in mv:
        return [m.lock]
    if m.encore and m.encore[0] in mv:
        return [m.encore[0]]
    if m.taunt:
        mv = [x for x in mv if MOVE[x]['cat'] != 'status'] or mv
    return mv


def actions(st, i):
    m = st.active(i)
    acts = [('m', x) for x in legal_moves(m)] if m.alive else []
    if m.alive and (m.rampage or trapped(st, i)):
        return acts
    for j, b in enumerate(st.sides[i]):
        if j != st.act[i] and b.alive:
            acts.append(('s', j))
    return acts


def trapped(st, i):
    m, o = st.active(i), st.active(1 - i)
    if not o.alive or 'ghost' in m.cur.types or m.item == 'きれいなぬけがら':
        return False
    ab = o.cur.ability
    if ab == 'かげふみ': return m.cur.ability != 'かげふみ'
    if ab == 'ありじごく': return 'flying' not in m.cur.types and m.cur.ability != 'ふゆう' and m.item != 'ふうせん'
    if ab == 'じりょく': return 'steel' in m.cur.types
    return False


def apply_boost(m, ch):
    if m.cur.ability == 'あまのじゃく':
        ch = {k: -v for k, v in ch.items()}
    for k, v in ch.items():
        k = 'defn' if k == 'def' else k
        m.boosts[k] = max(-6, min(6, m.boosts[k] + v))


def hazard_in(st, i, m):
    if st.rocks[i] and m.alive and m.item != 'あつぞこブーツ':
        m.hp -= max(1, int(m.maxhp * eff('rock', m.cur.types) / 8))
        if m.hp <= 0: m.hp = 0; m.disguise = m.disguise


def switch_in(st, i, j):
    old = st.active(i)
    old.boosts = dict(atk=0, defn=0, spa=0, spd=0, spe=0)
    old.encore = None; old.taunt = 0; old.yawn = 0
    old.lock = None; old.rampage = None; old.sub = 0; old.dbond = False; old.toxn = 0
    if old.cur.ability == 'さいせいりょく' and old.alive:
        old.hp = min(old.maxhp, old.hp + old.maxhp // 3)
    st.act[i] = j
    m = st.active(i)
    m.first_turn = True
    hazard_in(st, i, m)
    opp = st.active(1 - i)
    ab = m.cur.ability
    if ab == 'いかく' and opp.alive:
        if opp.cur.ability not in ('せいしんりょく', 'どんかん', 'マイペース', 'クリアボディ'):
            apply_boost(opp, {'atk': -1})
            if opp.cur.ability in ('まけんき',): apply_boost(opp, {'atk': 2})
    weather_ab = {'すなおこし': 'sand', 'ひでり': 'sun', 'あめふらし': 'rain', 'ゆきふらし': 'snow'}
    if ab in weather_ab: st.weather, st.wt = weather_ab[ab], 5
    terr_ab = {'グラスメイカー': 'grassy', 'サイコメイカー': 'psychic', 'エレキメイカー': 'electric', 'ミストメイカー': 'misty'}
    if ab in terr_ab: st.terrain, st.tt = terr_ab[ab], 5


def do_mega(st, i):
    m = st.active(i)
    if m.can_mega and not st.mega_used[i]:
        m.cur = m.mega; m.can_mega = False; st.mega_used[i] = True
        m.name = m.mega.species
        ab = m.cur.ability
        weather_ab = {'すなおこし': 'sand', 'ひでり': 'sun', 'あめふらし': 'rain', 'ゆきふらし': 'snow'}
        if ab in weather_ab: st.weather, st.wt = weather_ab[ab], 5
        terr = {'エレキメイカー': 'electric'}
        if ab in terr: st.terrain, st.tt = terr[ab], 5
        if ab == 'いかく':
            apply_boost(st.active(1 - i), {'atk': -1})


def best_switch(st, i):
    opp = st.active(1 - i)
    best, bv = None, -1e9
    for j, m in enumerate(st.sides[i]):
        if m.alive and j != st.act[i]:
            v = matchup(m, opp, st)
            if v > bv: best, bv = j, v
    return best


def matchup(m, o, st):
    """quick 1v1 score of mon m vs o (positive = m favoured)."""
    if not o.alive: return 0
    out = max((dmg(m, o, x, st)[0] / max(o.hp, 1) for x in m.moves if MOVE[x]['cat'] != 'status'), default=0)
    inc = max((dmg(o, m, x, st)[0] / max(m.hp, 1) for x in o.moves if MOVE[x]['cat'] != 'status'), default=0)
    fast = m.speed(st) > o.speed(st)
    return min(out, 1.5) - min(inc, 1.5) + (0.25 if fast else 0)


def use_move(st, i, move, fx):
    """luck = fx['luck<i>']: None = expected value (deep nodes), ('skip',) full paralysis, ('miss',),
    ('r', k) roll index k, ('c',) critical hit."""
    a = st.active(i); d = st.active(1 - i)
    if not a.alive: return
    if a.status == 'slp':
        if a.sleep > 0:
            a.sleep -= 1; return
        a.status = None
    if fx.get('flinch_' + str(i)):
        return
    luck = fx.get('luck' + str(i))
    if luck == ('skip',):
        a.rampage = None
        return
    mv = MOVE[move]
    prev = st.last[i]
    st.last[i] = move
    a.dbond = False
    if a.item in CHOICE: a.lock = move
    if move in RAMPAGE:
        a.rampage = None if a.rampage else (move, 1)
    elif a.rampage:
        a.rampage = None
    miss = luck == ('miss',)
    if mv['cat'] == 'status':
        if miss:
            return
        blocked = d.prot or (d.sub and move in BLOCKED_BY_SUB)
        if move in SETUP and SETUP[move]:
            apply_boost(a, SETUP[move])
        elif move == 'ステルスロック':
            st.rocks[1 - i] = True
        elif move == 'おにび':
            if d.status is None and 'fire' not in d.cur.types and d.cur.ability not in ('ねつこうかん', 'みずのベール') and not blocked:
                d.status = 'brn'
        elif move == 'でんじは':
            if d.status is None and 'electric' not in d.cur.types and eff('electric', d.cur.types) > 0 and not blocked:
                d.status = 'par'
        elif move == 'どくどく':
            if d.status is None and not set(d.cur.types) & {'poison', 'steel'} and not blocked:
                d.status, d.toxn = 'tox', 0
        elif move in SLEEP_MOVES:
            grounded = 'flying' not in d.cur.types and d.cur.ability != 'ふゆう'
            if d.status is None and not blocked and not (move in POWDER and ('grass' in d.cur.types or d.cur.ability == 'ぼうじん')) \
                    and not (grounded and st.terrain in ('electric', 'misty')) and d.cur.ability not in ('ふみん', 'やる気'):
                d.status, d.sleep = 'slp', 2
        elif move == 'あくび':
            if d.status is None and not d.yawn and not blocked: d.yawn = 2
        elif move in HEAL:
            a.hp = min(a.maxhp, a.hp + int(a.maxhp * HEAL[move]))
        elif move == 'いたみわけ':
            if not d.sub:
                tot = (a.hp + d.hp) // 2; a.hp = min(a.maxhp, tot); d.hp = min(d.maxhp, tot)
        elif move == 'アンコール':
            if st.last[1 - i] and not d.prot: d.encore = (st.last[1 - i], 3)
        elif move == 'ちょうはつ':
            if not d.prot: d.taunt = 3
        elif move in PROTECT:
            a.prot = 1
        elif move == 'みがわり':
            if not a.sub and a.hp > a.maxhp // 4:
                a.hp -= a.maxhp // 4; a.sub = a.maxhp // 4
        elif move == 'みちづれ':
            a.dbond = prev != 'みちづれ'
        elif move == 'トリックルーム':
            st.tr = 0 if st.tr else 5
        elif move in PHAZE:
            pass
        return
    if d.prot:
        a.rampage = None
        return
    if move in SLOW_PIVOT_ALWAYS_FIRST and not a.first_turn:
        return
    if move == 'ふいうち' and fx.get('opp_status_or_switch_' + str(1 - i)):
        return
    if move == 'でんこうそうげき' and 'electric' not in a.cur.types:
        return
    if not d.alive:
        return
    if miss:
        a.rampage = None
        return
    if luck is None:  # expected value: weight by accuracy and full paralysis
        f = hit_prob(a, d, move, st) * (1 - PARA_P if a.status == 'par' else 1.0)
        dmg_ = int(rolls(a, d, move, st)[7] * f)
    elif luck[0] == 'c':
        dmg_ = rolls(a, d, move, st, True)[7]
    else:
        dmg_ = rolls(a, d, move, st)[luck[1]]
    if move == 'ゆきなだれ' and fx.get('hit_' + str(i)):
        dmg_ *= 2
    if move == 'きょけんとつげき':
        a.glaive = 2
    if d.sub and move not in SOUND and a.cur.ability != 'すりぬけ':
        dealt = min(d.sub, dmg_)
        d.sub -= dealt
        fx['hit_' + str(1 - i)] = True
        if move in RECOIL and RECOIL[move]: a.hp -= int(dealt * RECOIL[move])
        if a.item == 'いのちのたま' and dealt > 0: a.hp -= a.maxhp // 10
        if move in SELF_DROP and SELF_DROP[move]: apply_boost(a, SELF_DROP[move])
        a.hp = max(0, a.hp)
        if move in PIVOT and a.hp > 0: fx['pivot_' + str(i)] = True
        return
    if dmg_ == 0 and d.cur.ability == 'ばけのかわ' and d.disguise:
        d.disguise = False
        d.hp = max(0, d.hp - d.maxhp // 8)
        return
    if dmg_ == 0:
        return
    full = d.hp == d.maxhp
    dealt = min(d.hp, dmg_)
    if full and dmg_ >= d.hp:
        if d.item == 'きあいのタスキ':
            dealt = d.hp - 1; d.item = None
        elif d.cur.ability == 'がんじょう' and a.cur.ability != 'かたやぶり':
            dealt = d.hp - 1
    d.hp -= dealt
    fx['hit_' + str(1 - i)] = True
    if move == 'ねこだまし' and d.cur.ability != 'せいしんりょく':
        fx['flinch_' + str(1 - i)] = True
    if move == 'でんこうそうげき':
        a.cur = copy.copy(a.cur); a.cur.types = [t for t in a.cur.types if t != 'electric'] or ['normal']
    if move == 'はたきおとす' and removable(d):
        d.item = None
    # after-effects
    if d.hp > 0 and d.item == 'オボンのみ' and d.hp * 2 <= d.maxhp:
        d.hp += d.maxhp // 4; d.item = None
    if mv['contact']:
        if d.item == 'ゴツゴツメット': a.hp -= a.maxhp // 6
        if d.cur.ability in ('さめはだ', 'てつのトゲ'): a.hp -= a.maxhp // 8
    if move in RECOIL and RECOIL[move]:
        a.hp -= int(dealt * RECOIL[move])
    if move in DRAIN:
        a.hp = min(a.maxhp, a.hp + int(dealt * DRAIN[move]))
    if a.item == 'いのちのたま' and dealt > 0:
        a.hp -= a.maxhp // 10
    if move in SELF_DROP and SELF_DROP[move]:
        apply_boost(a, SELF_DROP[move])
    if move in ON_HIT_SELF and ON_HIT_SELF[move]:
        apply_boost(a, ON_HIT_SELF[move])
    if move in TARGET_DROP and TARGET_DROP[move] and d.hp > 0:
        apply_boost(d, TARGET_DROP[move])
    if move == 'ドラゴンテール' and d.hp > 0:
        fx['phaze_' + str(1 - i)] = True
    if d.hp <= 0 and d.dbond:
        a.hp = 0
    a.hp = max(0, a.hp)
    if move in PIVOT and a.hp > 0:
        fx['pivot_' + str(i)] = True


def end_of_turn(st):
    for i in (0, 1):
        m = st.active(i)
        if not m.alive: continue
        if st.weather == 'sand' and not set(m.cur.types) & {'rock', 'ground', 'steel'} and m.cur.ability not in ('すなかき', 'すながくれ', 'すなのちから', 'ぼうじん'):
            m.hp -= m.maxhp // 16
        if m.status == 'brn': m.hp -= m.maxhp // 16
        if m.status in ('psn', 'tox'):
            if m.cur.ability == 'ポイズンヒール':
                m.hp = min(m.maxhp, m.hp + m.maxhp // 8)
            elif m.status == 'psn':
                m.hp -= m.maxhp // 8
            else:
                m.toxn = min(15, m.toxn + 1)
                m.hp -= max(1, m.maxhp * m.toxn // 16)
        if m.glaive: m.glaive -= 1
        if m.item == 'たべのこし': m.hp = min(m.maxhp, m.hp + m.maxhp // 16)
        if st.terrain == 'grassy' and 'flying' not in m.cur.types and m.cur.ability != 'ふゆう':
            m.hp = min(m.maxhp, m.hp + m.maxhp // 16)
        if m.yawn:
            m.yawn -= 1
            if m.yawn == 0 and m.status is None and st.terrain not in ('electric', 'misty'):
                m.status, m.sleep = 'slp', 2
        if m.encore:
            m.encore = (m.encore[0], m.encore[1] - 1) if m.encore[1] > 1 else None
        if m.taunt: m.taunt -= 1
        m.prot = 0
        m.first_turn = False
        m.hp = max(0, m.hp)
    if st.wt:
        st.wt -= 1
        if not st.wt: st.weather = None
    if st.tt:
        st.tt -= 1
        if not st.tt: st.terrain = None
    if st.tr: st.tr -= 1
    st.turn += 1


def order(st, a0, a1):
    def key(i, a):
        m = st.active(i)
        if a[0] == 's': return (10, 0)
        pr = PRIORITY.get(a[1], 0)
        if a[1] == 'グラススライダー' and st.terrain == 'grassy': pr = 1
        return (pr, -m.speed(st) if st.tr else m.speed(st))
    k0, k1 = key(0, a0), key(1, a1)
    return [0, 1] if k0 > k1 else [1, 0]  # ties: opponent first (pessimistic)


def step(st, a0, a1, luck=None):
    st = st.clone()
    acts = [a0, a1]
    fx = {}
    if luck:
        fx['luck0'], fx['luck1'] = luck
    # switches first
    for i in order(st, a0, a1):
        if acts[i][0] == 's':
            switch_in(st, i, acts[i][1])
    for i in (0, 1):
        if acts[i][0] == 'm':
            do_mega(st, i)
            if MOVE[acts[i][1]]['cat'] == 'status' or acts[i][0] == 's':
                fx['opp_status_or_switch_' + str(i)] = True
        else:
            fx['opp_status_or_switch_' + str(i)] = True
    for i in order(st, a0, a1):
        if acts[i][0] != 'm': continue
        if not st.active(i).alive: continue
        use_move(st, i, acts[i][1], fx)
        if fx.pop('pivot_' + str(i), False):
            j = best_switch(st, i)
            if j is not None: switch_in(st, i, j)
        if fx.pop('phaze_' + str(1 - i), False):
            alive = [j for j, m in enumerate(st.sides[1 - i]) if m.alive and j != st.act[1 - i]]
            if alive: switch_in(st, 1 - i, alive[0])
    end_of_turn(st)
    # forced replacements
    for i in (0, 1):
        if not st.active(i).alive:
            j = best_switch(st, i)
            if j is not None: switch_in(st, i, j)
    return st


# ---------------------------------------------------------------- evaluation / search
def side_value(side, st, i):
    v = 0.0
    for m in side:
        if not m.alive: continue
        f = m.hp / m.maxhp
        b = m.boosts
        boost = 0.08 * max(b['atk'], b['spa'], 0) + 0.05 * max(b['spe'], 0) + 0.03 * (b['defn'] + b['spd'])
        boost -= 0.06 * max(-min(b['atk'], 0), -min(b['spa'], 0))
        stat_pen = {'brn': 0.15 if m.cur.stat['atk'] > m.cur.stat['spa'] else 0.05, 'par': 0.12, 'slp': 0.2,
                    'psn': 0.08, 'tox': 0.15}.get(m.status, 0)
        if m.status in ('psn', 'tox') and m.cur.ability == 'ポイズンヒール': stat_pen = -0.05
        v += 1.0 + 1.2 * f + boost - stat_pen + (0.05 if m.item == 'きあいのタスキ' else 0) + (0.08 if m.disguise else 0)
        v += 0.4 * m.sub / m.maxhp
    if st.rocks[i]:
        v -= 0.1 * sum(1 for m in side if m.alive)
    return v


def evaluate(st):
    d = st.done()
    if d is not None:
        return 100 * d + side_value(st.sides[0], st, 0) - side_value(st.sides[1], st, 1)
    v = side_value(st.sides[0], st, 0) - side_value(st.sides[1], st, 1)
    v += 0.25 * math.tanh(matchup(st.active(0), st.active(1), st))
    return v


def prune(st, i, acts, k):
    """keep k most promising actions for side i by 1-ply heuristic."""
    if len(acts) <= k: return acts
    me, op = st.active(i), st.active(1 - i)
    sc = []
    for a in acts:
        if a[0] == 's':
            s = matchup(st.sides[i][a[1]], op, st) - 0.3
        else:
            mv = MOVE[a[1]]
            if mv['cat'] == 'status':
                s = 0.35 if a[1] in GOOD_STATUS else 0.0
                if a[1] in SETUP and me.hp < me.maxhp * 0.5: s -= 0.3
                if a[1] == 'ステルスロック' and st.rocks[1 - i]: s = -1
                if (a[1] in ('おにび', 'でんじは', 'あくび', 'どくどく') or a[1] in SLEEP_MOVES) and (op.status or op.sub): s = -1
                if a[1] == 'みがわり': s = 0.3 if not me.sub and me.hp > me.maxhp // 2 else -1
                if a[1] == 'みちづれ': s = 0.6 if me.hp < me.maxhp * 0.35 and st.last[i] != 'みちづれ' else -0.5
                if a[1] == 'トリックルーム':
                    slower = sum(1 for m in st.sides[i] if m.alive and m.speed(st) < op.speed(st))
                    s = 0.5 if not st.tr and slower >= 2 else -0.6
                if a[1] in HEAL and me.hp > me.maxhp * 0.7: s = -0.5
            else:
                s = min(dmg(me, op, a[1], st)[0] / max(op.hp, 1), 1.2)
        sc.append((s, a))
    sc.sort(key=lambda x: -x[0])
    return [a for _, a in sc[:k]]


class Search:
    def __init__(self, deadline, k_me=3, k_opp=2, pess=0.6, roll=3, chance=1):
        self.deadline, self.k_me, self.k_opp, self.pess, self.roll = deadline, k_me, k_opp, pess, roll
        self.chance = chance
        self.nodes = 0

    def child(self, st, a, b, depth, ply):
        """Value after (a, b). The first `chance` plies branch on luck (paralysis, miss, KO roll, crit);
        deeper plies use expected damage."""
        if ply >= self.chance:
            return self.value(step(st, a, b), depth - 1, ply + 1)
        o0, o1 = chance(st, 0, a, b), chance(st, 1, b, a)
        if len(o0) == 1 and len(o1) == 1:
            return self.value(step(st, a, b, (o0[0][1], o1[0][1])), depth - 1, ply + 1)
        return sum(p0 * p1 * self.value(step(st, a, b, (s0, s1)), depth - 1, ply + 1)
                   for p0, s0 in o0 for p1, s1 in o1 if p0 * p1 > 0)

    def value(self, st, depth, ply=0):
        self.nodes += 1
        d = st.done()
        if d is not None:
            return evaluate(st)
        if depth == 0:
            return evaluate(rollout(st, self.roll))
        if time.time() > self.deadline:
            raise TimeoutError
        my = prune(st, 0, actions(st, 0), self.k_me)
        op = prune(st, 1, actions(st, 1), self.k_opp)
        best = -1e9
        for a in my:
            vals = [self.child(st, a, b, depth, ply) for b in op]
            v = self.pess * min(vals) + (1 - self.pess) * sum(vals) / len(vals)
            best = max(best, v)
        return best

    def root(self, st, depth):
        my = actions(st, 0)
        op = prune(st, 1, actions(st, 1), self.k_opp + 1)
        res = []
        for a in my:
            vals = [self.child(st, a, b, depth, 0) for b in op]
            res.append((self.pess * min(vals) + (1 - self.pess) * sum(vals) / len(vals), a))
        res.sort(key=lambda x: -x[0])
        return res


def rollout(st, n):
    for _ in range(n):
        if st.done() is not None: break
        a0 = prune(st, 0, actions(st, 0), 1)[0]
        a1 = prune(st, 1, actions(st, 1), 1)[0]
        st = step(st, a0, a1)
    return st


def decide(st, seconds=10.0, horizon=8):
    """Iterative deepening within a hard time budget: full tree for `depth` turns + greedy rollout
    up to `horizon` turns (5〜8手先). Always returns an answer (1-ply fallback if time is very short)."""
    t0 = time.time()
    best = None
    for depth in range(1, horizon + 1):
        s = Search(t0 + seconds, roll=max(0, horizon - depth))
        try:
            best = (depth, s.root(st, depth))
        except TimeoutError:
            break
    if best is None:
        best = (0, [(0.0, a) for a in prune(st, 0, actions(st, 0), 6)])
    return best


# ---------------------------------------------------------------- selection
def build_side(names, sets_fn, hp=None):
    side = []
    for k, n in enumerate(names):
        base, mega = sets_fn(n)
        side.append(BM(base, mega, 1.0 if hp is None else hp[k]))
    return side


import infer as _infer
import sets as _sets
try:
    import learn as _learn
    KNOW = _learn.knowledge()
except Exception:
    KNOW = {'n_battles': 0, 'species': {}, 'my_orders': {}, 'vs': {}}
_OPP_CACHE = {}


def _with_learning(base_name_, mon):
    """Overlay moves/items observed in our own battle logs onto the usage-based set."""
    if mon is None: return None
    k = KNOW['species'].get(base_name_)
    if not k: return mon
    obs = [m for m in k.get('moves', {}) if m in MOVE]
    moves = (obs + [m for m in mon.moves if m not in obs])[:4]
    item = mon.item
    items = k.get('items', {})
    if items:
        top, c = max(items.items(), key=lambda x: x[1])
        if c >= 2 or c / max(1, k.get('picked', 1)) >= 0.5:
            if not (('ナイト' in str(item)) ^ ('ナイト' in top)):
                item = top
    if k.get('scarf_evidence', 0) >= 2 and 'ナイト' not in str(item):
        item = 'こだわりスカーフ'
    if moves == mon.moves and item == mon.item: return mon
    return Mon(mon.species, mon.nature, mon.spv, mon.ability, item, moves, label=mon.label)


def prior_boost_for(b):
    k = KNOW['species'].get(b)
    if not k: return None
    inferred, items = k.get('inferred', {}), k.get('items', {})
    def f(c):
        w = 1 + 2 * inferred.get(c.key, 0)
        if items:
            hit = items.get(c.base.item, 0) + (sum(v for i, v in items.items() if 'ナイト' in i) if c.mega else 0)
            w *= (1 + hit) if hit else 1 / (1 + sum(items.values()))
        return w
    return f


MY_TYPES = tuple(tuple(m.types) for m in TEAM)


# ---------------------------------------------------------------- known teams (data/known_teams.json)
def _load_known():
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'known_teams.json')
        return json.load(open(p, encoding='utf-8'))['teams']
    except Exception:
        return []


KNOWN_TEAMS = _load_known()
_KNOWN_CTX = {'team': None}


def _base(n):
    return BASE_OF.get(norm(n), norm(n))


def match_known(opp_names, min_overlap=4):
    """The known team (from published team articles) that the opponent's six match, or None."""
    bases = {_base(x) for x in opp_names}
    best, bo = None, 0
    for t in KNOWN_TEAMS:
        o = len(bases & {_base(m['name']) for m in t['team']})
        if o > bo:
            best, bo = t, o
    return best if bo >= min_overlap else None


def set_known_context(opp_names):
    _KNOWN_CTX['team'] = match_known(opp_names) if opp_names else None
    _OPP_CACHE.clear()
    return _KNOWN_CTX['team']


def known_set(b, obs=()):
    """(base, mega) from the matched known team, if it is consistent with what we have seen."""
    t = _KNOWN_CTX['team']
    if not t:
        return None
    for m in t['team']:
        if _base(m['name']) != b:
            continue
        name = norm(m['name'])
        is_mega = name != b and name in POKE
        for o in obs:
            k = o.get('kind')
            if k == 'move' and o.get('move') not in m['moves']:
                return None
            if k == 'item' and o.get('item') not in (m['item'], None):
                return None
            if k == 'mega' and not is_mega:
                return None
        try:
            if is_mega:
                base = Mon(b, m['nature'], m['ap'], m['base_ability'], m['item'], m['moves'], label=b)
                mega = Mon(name, m['nature'], m['ap'], m['ability'], m['item'], m['moves'], label=b)
                return base, mega
            return Mon(b, m['nature'], m['ap'], m['ability'], m['item'], m['moves'], label=b), None
        except Exception:
            return None
    return None


def opp_sets(n, obs=()):
    """Most probable (base, mega) set: a matching published team first, then usage/role candidates × our past
    logs × this battle's observations."""
    b = BASE_OF.get(norm(n), norm(n))
    obs = list(obs)
    key = (b, json.dumps(obs, ensure_ascii=False, sort_keys=True))
    if key not in _OPP_CACHE:
        ks = known_set(b, obs)
        if ks:
            _OPP_CACHE[key] = ks
            return ks
        if b in POKE:
            base, mega, _ = _infer.best_set(b, obs, MY_TYPES, prior_boost_for(b))
            if not obs:
                base, mega = _with_learning(b, base), _with_learning(b, mega)
        else:
            base, mega = meta_set(b)
        _OPP_CACHE[key] = (base, mega)
    return _OPP_CACHE[key]


def battle_obs(species):
    """Observations already recorded for this species in the running battle (logs/current.json)."""
    try:
        rec = _learn._load(_learn.CURRENT, None) or {}
        return list(rec.get('opp_revealed', {}).get(species, {}).get('obs', []))
    except Exception:
        return []


def pick_rate(b, prior=0.5, strength=3):
    k = KNOW['species'].get(b, {})
    return (k.get('picked', 0) + prior * strength) / (k.get('seen', 0) + strength)


def lead_rate(b, strength=3):
    k = KNOW['species'].get(b, {})
    return (k.get('led', 0) + strength / 3) / (k.get('picked', 0) + strength)


def history_bonus(order_, opp_names):
    """Small bonus from our past results with these mons vs these opponents."""
    tot, n = 0.0, 0
    for m in order_:
        for o in opp_names:
            g, w = KNOW['vs'].get(f'{m}|{BASE_OF.get(norm(o), norm(o))}', [0, 0])
            if g:
                tot += (w + 1.5) / (g + 3) - 0.5; n += g
    return 20 * tot * n / (n + 6) if n else 0.0


def mine(n):
    return MY[BASE_OF.get(norm(n), norm(n))]


def new_state(me_names, opp_names):
    st = State()
    st.sides = [build_side(me_names, mine), build_side(opp_names, opp_sets)]
    # only one mega per side: keep the first mega-capable for opponent
    seen = False
    for m in st.sides[1]:
        if m.can_mega:
            if seen: m.can_mega = False
            seen = True
    st.act = [0, 0]; st.rocks = [False, False]; st.mega_used = [False, False]
    st.weather = st.terrain = None; st.wt = st.tt = 0; st.turn = 1; st.last = [None, None]; st.tr = 0
    for i in (0, 1):
        st.act[i] = 0
        st.active(i).first_turn = True
    for i in (0, 1):  # simultaneous entry: abilities after both are on the field
        a, o = st.active(i), st.active(1 - i)
        if a.cur.ability == 'いかく' and o.cur.ability not in ('せいしんりょく', 'どんかん', 'マイペース', 'クリアボディ'):
            apply_boost(o, {'atk': -1})
        weather_ab = {'すなおこし': 'sand', 'ひでり': 'sun', 'あめふらし': 'rain', 'ゆきふらし': 'snow'}
        if a.cur.ability in weather_ab: st.weather, st.wt = weather_ab[a.cur.ability], 5
        terr_ab = {'グラスメイカー': 'grassy', 'サイコメイカー': 'psychic', 'エレキメイカー': 'electric', 'ミストメイカー': 'misty'}
        if a.cur.ability in terr_ab: st.terrain, st.tt = terr_ab[a.cur.ability], 5
    return st


def engine_game(me_names, opp_names):
    """Engine state at the start of a game (leads sent out, switch-in abilities applied)."""
    import search as _search, engine as _E
    st = State()
    st.sides = [build_side(me_names, mine), build_side(opp_names, opp_sets)]
    seen = False
    for m in st.sides[1]:
        if m.can_mega:
            if seen: m.can_mega = False
            seen = True
    st.act = [0, 0]; st.rocks = [False, False]; st.mega_used = [False, False]
    st.weather = st.terrain = None; st.wt = st.tt = 0; st.turn = 1; st.last = [None, None]; st.tr = 0
    return _E.start(_search.from_battle(st), chooser=_search.chooser)


def _game_job(args):
    order_, oorder, smart, kid = args
    if kid != ((_KNOWN_CTX['team'] or {}).get('id')):   # spawn-start workers (Windows) begin without context
        _KNOWN_CTX['team'] = next((t for t in KNOWN_TEAMS if t['id'] == kid), None)
        _OPP_CACHE.clear()
    import search as _search
    return _search.play(engine_game(order_, oorder), smart=smart)


def _run_games(jobs):
    """Play many games in parallel (all CPU cores)."""
    try:
        import multiprocessing as mp
        ctx = mp.get_context('fork') if hasattr(os, 'fork') else mp.get_context('spawn')
        with ctx.Pool(os.cpu_count() or 1) as pool:
            return pool.map(_game_job, jobs, chunksize=4)
    except Exception:
        return [_game_job(j) for j in jobs]


def quick_play(st, max_turns=25):
    """both sides play 1-ply greedy (fast), return final evaluation."""
    for _ in range(max_turns):
        if st.done() is not None: break
        acts = []
        for i in (0, 1):
            cand = prune(st, i, actions(st, i), 1)
            acts.append(cand[0])
        st = step(st, acts[0], acts[1])
    return evaluate(st)


def smart_play(st, max_turns=20):
    for _ in range(max_turns):
        if st.done() is not None: break
        s = Search(time.time() + 5, k_me=3, k_opp=2, roll=1)
        a0 = s.root(st, 1)[0][1]
        a1 = prune(st, 1, actions(st, 1), 1)[0]
        st = step(st, a0, a1)
    return evaluate(st)


def opp_pick_weights(opp6, my6):
    w = {}
    for n in opp6:
        base = BASE_OF.get(norm(n), norm(n))
        u = (1.0 / (1 + _sets.usage_rank(base) / 30)) ** 0.5  # minor picks are usually brought on purpose
        b, m = opp_sets(n)
        mon = m or b
        sc = 0
        for mm in my6:
            o = BM(mm[1] or mm[0]); x = BM(mon)
            st = State(); st.weather = st.terrain = None; st.tr = 0
            sc += matchup(x, o, st)
        w[n] = u * math.exp(0.35 * sc) * pick_rate(base) / 0.5
    return w


def select(opp6, seconds=10.0, ignore_stored=False, return_all=False):
    """Choose 3 of our 6 and the lead: every order is played out on the engine against the opponent's likely
    picks and leads (greedy play), then the best 12 are replayed with a 1-turn look-ahead for our side."""
    my_names = [BASE_OF.get(m.species, m.species) for m in TEAM]
    kt = set_known_context(opp6)
    w = opp_pick_weights(opp6, list(MY.values()))
    trip = []
    for c in itertools.combinations(opp6, 3):
        p = 1
        for n in c: p *= w[n]
        trip.append((p, c))
    trip.sort(key=lambda x: -x[0])
    trip = trip[:6]
    fixed = set()   # selections written in the team's article: lead first
    if kt and kt.get('picks'):
        by_base = {_base(x): x for x in opp6}
        known = []
        for pk in kt['picks']:
            c = tuple(by_base.get(_base(x)) for x in pk['mons'])
            if all(c) and len(set(c)) == 3:
                known.append((pk['weight'], c))
        if known:
            hp = sum(p for p, _ in trip) or 1
            kw = sum(p for p, _ in known)
            trip = [(0.6 * p / kw, c) for p, c in known] + [(0.4 * p / hp, c) for p, c in trip if c not in [k for _, k in known]][:4]
            fixed = {c for _, c in known}
            trip.sort(key=lambda x: -x[0])
    tot = sum(p for p, _ in trip)
    kid = kt['id'] if kt else None

    def score_orders(orders, trips, smart):
        jobs, meta = [], []
        for order_ in orders:
            for p, c in trips:
                if c in fixed:
                    jobs.append((order_, list(c), smart, kid))
                    meta.append((tuple(order_), p, c, 1.0))
                    continue
                lw = [lead_rate(BASE_OF.get(norm(x), norm(x))) for x in c]
                for olead, l in zip(c, lw):
                    oorder = [olead] + [x for x in c if x != olead]
                    jobs.append((order_, oorder, smart, kid))
                    meta.append((tuple(order_), p, c, l / sum(lw)))
        vals = _run_games(jobs)
        sc = {}
        ptot = sum(p for p, _ in trips)
        for (o, p, c, lw), v in zip(meta, vals):
            sc[o] = sc.get(o, 0.0) + p / ptot * lw * v
        for o in sc:
            sc[o] += sum(p / ptot * history_bonus(list(o), c) for p, c in trips)
        return sorted(((v, list(o)) for o, v in sc.items()), key=lambda x: -x[0])

    orders = []
    for mine3 in itertools.combinations(my_names, 3):
        for lead in mine3:
            orders.append([lead] + [x for x in mine3 if x != lead])
    if kt and kt.get('counter') and not ignore_stored and not return_all:
        # prepared offline by prep.py (both sides look ahead, real randomness): use it as is
        c = kt['counter']
        top = [(c['score'], c['order'])] + [(a['score'], a['order']) for a in c.get('alternatives', [])]
        return c['order'], top, trip
    results = score_orders(orders, trip, False)
    if return_all:
        return results
    t2 = score_orders([o for _, o in results[:12]], trip[:5], True)
    results = t2 + results[12:]
    return results[0][1], results[:5], trip


# ---------------------------------------------------------------- state loading
def field_defaults(js):
    """Fill in what state.json leaves out from logs/live/field_state.json (written by game_watch.py
    from the battle messages): weather/terrain, hazards, mega used, and per-mon boosts, consumed
    items, status and moves seen."""
    try:
        live = os.path.join(_learn.LOGS, 'live', 'field_state.json')
        fs = json.load(open(live, encoding='utf-8'))
    except Exception:
        return js
    js = dict(js)
    for k in ('weather', 'weather_turns', 'terrain', 'terrain_turns', 'rocks_me', 'rocks_opp', 'trick_room'):
        if k not in js and fs.get(k) is not None:
            js[k] = fs[k]
    if 'mega_used_me' not in js: js['mega_used_me'] = fs['mega_used']['me']
    if 'mega_used_opp' not in js: js['mega_used_opp'] = fs['mega_used']['opp']
    for side in ('me', 'opp'):
        out = []
        for d in js.get(side, []):
            d = dict(d)
            nm = norm(d['name']); base = BASE_OF.get(nm, nm)
            info = fs['mons'][side].get(base)
            if info:
                if 'boosts' not in d and info.get('boosts'): d['boosts'] = info['boosts']
                if 'status' not in d and info.get('status'): d['status'] = info['status']
                if 'item' not in d and info.get('item_consumed'): d['item'] = False
                if info.get('mega') and 'mega' not in d: d['mega'] = True
                for k in ('sub', 'last_move', 'glaive', 'toxn', 'rampage'):
                    if k not in d and info.get(k): d[k] = info[k]
                if side == 'opp':
                    seen = d.get('moves_seen', [])
                    d['moves_seen'] = seen + [m for m in info.get('moves_seen', []) if m not in seen]
                    if not d.get('item_seen') and info.get('items_seen'):
                        d['item_seen'] = info['items_seen'][0]
            out.append(d)
        js[side] = out
    return js


def load_state(js):
    js = field_defaults(js)
    team6 = js.get('opp_team')
    if not team6:
        try:
            team6 = (_learn._load(_learn.CURRENT, None) or {}).get('opp_team')
        except Exception:
            team6 = None
    set_known_context(team6 or [d['name'] for d in js.get('opp', [])])
    st = State()
    me = []
    for d in js['me']:
        base, mega = mine(d['name'])
        m = BM(base, mega)
        nm = norm(d['name'])
        if d.get('mega') or nm.startswith('メガ'):
            m.cur = mega; m.can_mega = False; m.name = mega.species
        m.maxhp = m.cur.stat['hp'] if False else base.stat['hp']
        if 'hp' in d: m.hp = d['hp']
        elif 'hp_pct' in d: m.hp = round(m.maxhp * d['hp_pct'] / 100)
        m.status = d.get('status'); fill_boosts(m, d.get('boosts', {}))
        if d.get('item') is False: m.item = None
        if d.get('disguise') is False: m.disguise = False
        if d.get('sleep'): m.sleep = d['sleep']
        extra_state(m, d)
        me.append(m)
    opp = []
    for d in js['opp']:
        nm = norm(d['name'])
        bname = BASE_OF.get(nm, nm)
        obs = list(d.get('obs', [])) + battle_obs(bname) + [{'kind': 'move', 'move': mv} for mv in d.get('moves_seen', [])]
        if d.get('item_seen'): obs.append({'kind': 'item', 'item': d['item_seen']})
        if d.get('mega') or nm.startswith('メガ'): obs.append({'kind': 'mega'})
        base, mega = opp_sets(bname, obs)
        m = BM(base, mega)
        if d.get('mega') or nm.startswith('メガ'):
            if mega: m.cur = mega; m.name = mega.species
            m.can_mega = False
        m.maxhp = base.stat['hp']
        m.hp = round(m.maxhp * d.get('hp_pct', 100) / 100)
        m.status = d.get('status'); fill_boosts(m, d.get('boosts', {}))
        if d.get('item') is False: m.item = None
        if d.get('disguise') is False: m.disguise = False
        for mv in d.get('moves_seen', []):
            if mv in MOVE and mv not in m.moves:
                m.moves = [mv] + m.moves[:3]
        if d.get('item_seen'): m.item = d['item_seen'] if d.get('item') is not False else None
        extra_state(m, d)
        opp.append(m)
    st.sides = [me, opp]
    st.act = [js.get('active_me', 0), js.get('active_opp', 0)]
    st.rocks = [js.get('rocks_me', False), js.get('rocks_opp', False)]
    st.mega_used = [js.get('mega_used_me', any(not m.can_mega and m.mega for m in me)),
                    js.get('mega_used_opp', any(m.cur is m.mega and m.mega for m in opp))]
    if st.mega_used[0]:
        for m in me: m.can_mega = False
    if st.mega_used[1]:
        for m in opp: m.can_mega = False
    st.weather, st.wt = js.get('weather'), js.get('weather_turns', 5 if js.get('weather') else 0)
    st.terrain, st.tt = js.get('terrain'), js.get('terrain_turns', 5 if js.get('terrain') else 0)
    st.turn = js.get('turn', 1); st.last = [None, js.get('opp_last_move')]
    st.tr = js.get('trick_room', 0) or 0
    for i, side in ((0, me), (1, opp)):  # locks only persist on the mon still in
        for j, m in enumerate(side):
            if j != st.act[i]: m.lock = m.rampage = None; m.sub = 0; m.glaive = 0
    a1 = opp[st.act[1]]
    if js.get('opp_last_move') and a1.item in CHOICE and not a1.lock: a1.lock = js['opp_last_move']
    return st


def extra_state(m, d):
    """Optional per-mon battle state: last_move (choice lock / rampage), sub (substitute HP %),
    glaive (used きょけんとつげき last turn), toxn (toxic counter)."""
    lm = d.get('last_move')
    if lm in MOVE:
        if m.item in CHOICE: m.lock = lm
        if lm in RAMPAGE and d.get('rampage'): m.rampage = (lm, 1)
    if d.get('sub'): m.sub = max(1, round(m.maxhp * (d['sub'] if d['sub'] is not True else 25) / 100))
    if d.get('glaive'): m.glaive = 1
    if d.get('toxn'): m.toxn = d['toxn']


def fill_boosts(m, b):
    for k, v in b.items():
        m.boosts['defn' if k in ('def', 'B') else {'A': 'atk', 'C': 'spa', 'D': 'spd', 'S': 'spe'}.get(k, k)] = v


def fmt_action(st, a):
    if a[0] == 's':
        return f"{st.sides[0][a[1]].name}に交代"
    m = st.active(0)
    pre = 'メガシンカ＋' if m.can_mega and not st.mega_used[0] else ''
    return f"{pre}{a[1]}"


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    if len(sys.argv) >= 3 and sys.argv[1] == 'select':
        best, top, _ = select([x for x in sys.argv[2:] if not x.startswith('--')])
        print('選出順: ' + ' → '.join(best))
        kt = _KNOWN_CTX['team']
        if kt:
            print(f"（既知構築: {kt['title']}。型は記事どおり、対策は logs/COUNTERS.md）")
        if '--no-log' not in sys.argv:
            try:  # start a battle record so turns can be appended with learn.py
                _learn.start()
                r = _learn.cur(); r['opp_team'] = [BASE_OF.get(norm(x), norm(x)) for x in sys.argv[2:] if not x.startswith('--')]
                r['my_order'] = best; _learn._save(_learn.CURRENT, r)
            except Exception:
                pass
    elif len(sys.argv) >= 3 and sys.argv[1] == 'turn':
        js = json.load(open(sys.argv[2], encoding='utf-8'))
        sec = float(sys.argv[3]) if len(sys.argv) > 3 and not sys.argv[3].startswith('-') else 10
        st = load_state(js)
        import search as _search
        est = _search.from_battle(st, js)
        if not est.sides[0].mons[est.sides[0].act].alive:
            opts = [j for j, m in enumerate(est.sides[0].mons) if m.alive]
            j = _search.chooser(est, 0, opts)
            print(f"次: {est.sides[0].mons[j].name}を出す"); return
        depth, res, nodes = _search.decide(est, sec)
        print(f"次: {_search.fmt(est, res[0][1])}")
        if '-v' in sys.argv:
            for m in st.sides[1]:
                print('  相手推定:', m.name, m.cur.nature, m.cur.sp_str(), m.cur.item, m.moves)
            print(f'木{depth}ターン+ロールアウト（計{_search.HORIZON}ターン） 局面数{nodes}',
                  [(round(v, 2), _search.fmt(est, a)) for v, a in res])
    elif len(sys.argv) >= 3 and sys.argv[1] == 'types':
        # 選出画面のタイプアイコンから相手候補を絞る: python battle.py types ほのお かくとう
        from calc import JT
        rev = {v: k for k, v in JT.items()}
        want = {rev.get(t, t) for t in sys.argv[2:]}
        rows = []
        for n, p in POKE.items():
            if p.get('champ') and set(p['types']) == want and not (p.get('form') and 'mega' in p['form']):
                rows.append((_sets.usage_rank(n), n))
        for r, n in sorted(rows)[:12]:
            print(f"{n}（使用率{r if r < 300 else '圏外'}位）")
    elif len(sys.argv) >= 3 and sys.argv[1] == 'infer':
        sp = BASE_OF.get(norm(sys.argv[2]), norm(sys.argv[2]))
        obs = json.load(open(sys.argv[3], encoding='utf-8')) if len(sys.argv) > 3 else []
        obs = obs + battle_obs(sp)
        for p, c in _infer.posterior(sp, obs, MY_TYPES, prior_boost_for(sp))[:5]:
            m = c.mega or c.base
            print(f"{p:.2f} {c.key} {m.stat_str()} {c.base.moves}")
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
