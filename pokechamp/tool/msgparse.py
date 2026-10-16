"""戦闘メッセージ（OCR文字）から、そのターンに起きたことを抜き出す。

  parse_turn(lines) -> dict   1ターン分のメッセージ行（出現順）を解析
  FieldTracker               ターンをまたいで場の状態（天候・フィールド・能力ランク・持ち物・状態異常・
                             ステロ・メガシンカ・場のポケモン）を追跡し logs/live/field_state.json に保存

文言は本編（SV）の日本語メッセージに準拠。チャンピオンズの実際の言い回しと違う場合は PATTERNS を直す。
OCR の誤読に備えて、空白・句読点・全角半角の違いは無視して照合する。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from calc import POKE, MOVE  # noqa: E402
import safeio  # noqa: E402

NAMES = sorted({n for n in POKE if len(n) >= 2}, key=len, reverse=True)
ABILITIES = sorted({a for p in POKE.values() for a in p.get('ab', []) if len(a) >= 2}, key=len, reverse=True)
try:
    from sets import MEGAS
    BASE = {m: b for b, ms in MEGAS.items() for m in ms}
except Exception:
    BASE = {}
MOVES = sorted({m for m in MOVE if len(m) >= 2}, key=len, reverse=True)
STAT = {'こうげき': 'atk', '攻撃': 'atk', 'ぼうぎょ': 'def', '防御': 'def', 'とくこう': 'spa', '特攻': 'spa',
        'とくぼう': 'spd', '特防': 'spd', 'すばやさ': 'spe', '素早さ': 'spe', 'めいちゅうりつ': 'acc', '命中率': 'acc',
        'かいひりつ': 'eva', '回避率': 'eva'}
UP = {'': 1, 'ぐーんと': 2, 'ぐぐーんと': 3, 'ぐんと': 2}
DOWN = {'': 1, 'がくっと': 2, 'がくーんと': 3}


def norm(s):
    s = s.translate(str.maketrans('０１２３４５６７８９！？', '0123456789!?'))
    return re.sub(r'[\s　、。・…]', '', s)


_VOICED = str.maketrans('ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポヴがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ',
                        'カキクケコサシスセソタチツテトハヒフヘホハヒフヘホウかきくけこさしすせそたちつてとはひふへほはひふへほ')


_LOOKALIKE = str.maketrans('力口工二一夕卜ヰ三', 'カロエニータトキミ')


_SMALL = str.maketrans('ァィゥェォッャュョヮぁぃぅぇぉっゃゅょゎ', 'アイウエオツヤユヨワあいうえおつやゆよわ')


# katakana the OCR mixes up with each other in this font (グソクムシャ → ブソフムシャ, ン ↔ ソ, シ ↔ ツ): the same
# letter when comparing names closely
_LOOSE = str.maketrans('フソツ', 'クンシ')


def loose(s):
    return s.translate(_LOOSE)


def best_of(s, names, th=0.5):
    """The closest of a few given names in s (e.g. the opponent's six in 「…を 繰り出した」), or None."""
    d = loose(devoice(s))
    best = None
    for n in names:
        dn = loose(devoice(n))
        for L in (len(dn) - 1, len(dn), len(dn) + 1):
            for i in range(0, max(0, len(d) - L) + 1):
                r = difflib.SequenceMatcher(None, d[i:i + L], dn).ratio()
                if r >= th and (best is None or r > best[0]):
                    best = (r, n)
    return best[1] if best else None


def devoice(s):
    """OCR often drops 濁点/半濁点 (ゴリランダー → コリランター, メガシンカ → メカシンカ), reads katakana as look-alike
    kanji (メガシノ力 → カ) and small kana as large ones (ウツボット → ウツボツト): compare without them."""
    return s.translate(_VOICED).translate(_LOOKALIKE).translate(_SMALL)


NAMES_DV = [(devoice(n), n) for n in NAMES]
MOVES_DV = [(devoice(m), m) for m in MOVES]


def locate_name(s):
    """(name, start, end) of the first mon name in s: exact, then without 濁点, then a close match among the
    mons of this battle."""
    s = apply_fixes(s)
    for n in NAMES:
        i = s.find(n)
        if i >= 0:
            return n, i, i + len(n)
    d = devoice(s)
    for dn, n in NAMES_DV:
        i = d.find(dn) if len(dn) >= 3 else -1
        if i >= 0:
            return n, i, i + len(dn)
    context()
    return _fuzzy(s, 'name')


def find_name_any(s):
    """find_name, and when the six of this battle do not explain the text (the preview may have been misread):
    a strict close match among ALL mons (for the HP panel's name, which holds nothing but the name)."""
    r = find_name(s)
    if r:
        return r
    d = loose(devoice(apply_fixes(s)))
    if len(d) < 3:
        return None
    best = None
    for n in NAMES:
        dn = loose(devoice(n))
        if len(dn) < 4:
            continue
        for L in (len(dn) - 1, len(dn), len(dn) + 1):
            for i in range(0, max(0, len(d) - L) + 1):
                r = difflib.SequenceMatcher(None, d[i:i + L], dn).ratio()
                if r >= 0.8 and (best is None or r > best[0]):
                    best = (r, n)
    return best[1] if best else None


def exact_name(s):
    """A mon name read correctly (exactly, or only without 濁点): trusted even when it is not among the six the
    team preview was taken to show (the preview can be misidentified)."""
    s = apply_fixes(s)
    for n in NAMES:
        if n in s:
            return n
    d = devoice(s)
    for dn, n in NAMES_DV:
        if len(dn) >= 4 and dn in d:
            return n
    return None


def find_name(s):
    r = locate_name(s)
    return r[0] if r else None


def has(s, keys):
    """Any of the phrases in s, also when the OCR dropped 濁点."""
    d = devoice(s)
    return any(k in s or devoice(k) in d for k in keys)


def find_move(s):
    for m in MOVES:
        if m in s:
            return m
    d = devoice(s)
    for dm, m in MOVES_DV:
        if len(dm) >= 4 and dm in d:
            return m
    return None


def side_marked(s):
    """True when the line says whose it is: 「相手の」, its furigana 「あいて」, or 「手の」 near the start
    (OCR often loses 相)."""
    return '相手' in s or 'あいて' in s or '手の' in s[:6]


def side_of(s):
    return 'opp' if side_marked(s) else 'me'


# 「メガシンカした」 as the OCR reads it: メカシンカ / メガシノ力 / メガシフカ / メカシラカ ... (not the bare button label)
MEGA_RE = re.compile(r'メ[カガ]シ.[カ力][しシ]')


def move_use(s):
    """「(相手の) Xの Y！」 -> (side, X, Y) or None. Y is read right after 「Xの」, also when the OCR garbled it."""
    s = apply_fixes(s)
    loc = locate_name(s)
    if not loc:
        return None
    name, _, end = loc
    tail = s[end:]
    if not tail.startswith('の'):
        return None
    tail = tail[1:]
    if any(k in tail for k in STAT) or len(tail) < 2:
        return None
    mv = next((m for m in MOVES if tail.startswith(m)), None)
    if not mv:
        context()
        f = _fuzzy(tail, 'move')
        mv = f[0] if f else None
    if not mv or 'で' in tail[len(mv):][:1]:
        return None
    return side_of(s[:loc[1] + 1] + s), name, mv


# ---------------------------------------------------------------- names / moves of this battle (fuzzy)
# The OCR drops or swaps characters (ギャラドス → ャラドス / ヰャラドス, ガブリアス → カプリアス, じしん → ししん).
# Only the 12 mons in this battle and their moves can appear, so a close match among them is safe.
LOGS = os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs'))
_CTX = {'key': None, 'names': [], 'moves': []}


def context():
    """(names, moves) that can appear in this battle: our team and the opponent's six (logs/current.json)."""
    if _CTX['key'] == 'manual':
        return _CTX['names'], _CTX['moves']
    p = os.path.join(LOGS, 'current.json')
    try:
        key = os.path.getmtime(p)
    except OSError:
        key = None
    if _CTX['key'] != key or not _CTX['names']:
        names, moves = set(), set()
        try:
            from team import TEAM
            for m in TEAM:
                names.add(BASE.get(m.species, m.species)); names.add(m.species)
                if m.species.endswith('ロトム'):
                    names.add('ロトム')
                moves.update(m.moves)
        except Exception:
            pass
        opp = []
        try:
            opp = json.load(open(p, encoding='utf-8')).get('opp_team') or []
        except Exception:
            pass
        from calc import learnset
        for n in opp:
            b = BASE.get(n, n)
            names.add(b)
            try:
                moves.update(learnset(b))
            except Exception:
                pass
        _CTX.update(key=key, names=sorted(names, key=len, reverse=True), moves=sorted(moves, key=len, reverse=True))
        _fuzzy.cache_clear()
    return _CTX['names'], _CTX['moves']


PIVOT = {'ボルトチェンジ', 'とんぼがえり', 'クイックターン', 'すてゼリフ', 'バトンタッチ', 'テレポート', 'しっぽきり',
         'さよならのあいさつ'}
# 交代する技（ボルトチェンジ・とんぼがえり・クイックターン）: 技が成功すると手持ち画面が開き交代先を自由に選べる。
# 防がれた・外れた・効果がない、相手のレッドカード（こちらがランダムに交代）・だっしゅつボタン／にげごし／ききかいひ
# （相手だけが交代しこちらは交代できない）、ゴツゴツメット等でひんしになった場合は手持ち画面は開かない。
PIVOT_FAIL = ('当たらなかった', 'あたらなかった', '外れた', 'はずれた', '守った', 'まもった', '防いだ', 'ふせいだ',
              '効果がない', 'こうかがない', 'うまく決まらなかった', 'うまくきまらなかった', '技は失敗', 'わざはしっぱい')
PIVOT_BLOCKED_BY_FOE = ('だっしゅつボタン', 'にげごし', 'ききかいひ', 'レッドカード')


def pivot_outcome(msgs):
    """What happened to our pivot move in this turn's messages: None (no pivot move seen yet), 'ok' (a party screen will
    open), 'fail' (blocked / missed / no effect), 'forced' (the foe's レッドカード switched us at random),
    'blocked' (the foe's だっしゅつボタン / にげごし / ききかいひ: only they switch). Only the lines right after
    the move, up to the next move, count."""
    state = None
    for raw in msgs:
        s = norm(raw)
        mu = move_use(s)
        if mu:
            if state is not None:
                break               # the next move: the pivot move's own messages are over
            if mu[0] == 'me' and mu[2] in PIVOT:
                state = 'ok'
            continue
        if state is None:
            continue
        if has(s, ('レッドカード',)):
            return 'forced'
        if has(s, PIVOT_BLOCKED_BY_FOE):
            return 'blocked'
        if has(s, PIVOT_FAIL):
            return 'fail'
    return state


def _in_team(side, name):
    b = BASE.get(name, name)
    if side == 'me':
        return not MY_BASES or any(m == b or m.endswith(b) or b.endswith(m) for m in MY_BASES)
    opp = _opp_team()
    return not opp or b in opp


def _team_side_only_me(name):
    """Ours and not in the opponent's six (so a message naming it is not about their side)."""
    b = BASE.get(name, name)
    return bool(MY_BASES) and any(m == b or m.endswith(b) or b.endswith(m) for m in MY_BASES) and b not in _opp_team()


def _team_side(name):
    """'me' / 'opp' when only one team has this mon, else None."""
    b = BASE.get(name, name)
    opp = _opp_team()
    in_me = any(m == b or m.endswith(b) or b.endswith(m) for m in MY_BASES) if MY_BASES else False
    in_opp = b in opp
    return ('me' if in_me else 'opp') if in_me != in_opp else None


def _opp_team():
    try:
        rec = json.load(open(os.path.join(LOGS, 'current.json'), encoding='utf-8'))
        return [BASE.get(x, x) for x in rec.get('opp_team') or []]
    except Exception:
        return []


def set_context(opp_team):
    """For tests / tools without current.json."""
    _CTX['key'] = None
    names, moves = context()
    names, moves = list(names), list(moves)
    from calc import learnset
    for n in opp_team:
        b = BASE.get(n, n)
        if b not in names:
            names.append(b)
            try:
                moves.extend(m for m in learnset(b) if m not in moves)
            except Exception:
                pass
    _CTX['names'] = sorted(set(names), key=len, reverse=True)
    _CTX['moves'] = sorted(set(moves), key=len, reverse=True)
    _CTX['key'] = 'manual'
    _fuzzy.cache_clear()


# ---------------------------------------------------------------- what the OCR misread, remembered
# Each time a close match fixes a misread word (三ミツキュ → ミミッキュ, ゆけつ → ゆけっ ...), the pair is counted in
# data/ocr_fixes.json. A misread seen twice is then replaced directly before any matching, so the same quirk of the
# game's font no longer depends on a close match.
FIX_P = os.path.join(HERE, 'data', 'ocr_fixes.json')
try:
    FIXES = json.load(open(FIX_P, encoding='utf-8'))
except Exception:
    FIXES = {}
_FIX_SORTED = []


def _fixes_sorted():
    if len(_FIX_SORTED) != sum(1 for v in FIXES.values() if v.get('n', 0) >= 2):
        _FIX_SORTED[:] = sorted(((k, v['to']) for k, v in FIXES.items() if v.get('n', 0) >= 2), key=lambda x: -len(x[0]))
    return _FIX_SORTED


def learn_fix(seen, right):
    """Count one misread: the text the OCR gave for a word, and the word it was."""
    if not seen or seen == right or len(seen) < 3 or len(seen) > 14:
        return
    e = FIXES.get(seen)
    if e and e['to'] != right:
        e['bad'] = e.get('bad', 0) + 1      # read as two different words: not a safe fix
        return
    FIXES[seen] = {'to': right, 'n': (e['n'] if e else 0) + 1}
    try:
        safeio.write_json(FIX_P, FIXES, indent=0)
    except Exception:
        pass


def apply_fixes(s):
    for seen, right in _fixes_sorted():
        if seen in s and not FIXES[seen].get('bad'):
            s = s.replace(seen, right)
    return s


from functools import lru_cache  # noqa: E402
import difflib  # noqa: E402


@lru_cache(maxsize=4096)
def _fuzzy(s, kind):
    """Best fuzzy occurrence of a context name ('name') in s, or the move a tail starts with ('move').
    Returns (word, start, end) or None."""
    names, moves = _CTX['names'], _CTX['moves']
    d = devoice(s)
    best = None
    if kind == 'name':
        dl = loose(d)
        for n in names:
            dn = loose(devoice(n))
            if len(dn) < 3:
                continue
            for L in (len(dn) - 1, len(dn), len(dn) + 1):
                for i in range(0, max(0, len(d) - L) + 1):
                    r = difflib.SequenceMatcher(None, dl[i:i + L], dn).ratio()
                    if r >= 0.75 and (best is None or r > best[0] or (r == best[0] and len(n) > len(best[1]))):
                        best = (r, n, i, i + L)
    else:
        t = re.sub(r'[!/！?]+$', '', d)
        for m in moves:
            dm = devoice(m)
            if len(dm) < 2:
                continue
            r = difflib.SequenceMatcher(None, t[:len(dm) + 1], dm).ratio()
            if r >= (0.7 if len(dm) >= 4 else 0.85) and (best is None or r > best[0]):
                best = (r, m, 0, len(dm))
    if best and best[0] < 1.0:
        learn_fix(s[best[2]:best[3]] if kind == 'name' else re.sub(r'[!/！?]+$', '', s)[:best[3]], best[1])
    return best[1:] if best else None


WEATHER_START = [('sun', ('日差しが強くなった', 'ひざしがつよくなった', '日差しがとても強くなった')),
                 ('rain', ('雨が降り始めた', 'あめがふりはじめた', '強い雨が降り始めた')),
                 ('sand', ('砂あらしが吹き始めた', 'すなあらしがふきはじめた', '砂嵐が吹き始めた')),
                 ('snow', ('雪が降り始めた', 'ゆきがふりはじめた'))]
WEATHER_END = ('日差しが元に戻った', 'ひざしがもとにもどった', '雨が止んだ', 'あめがやんだ', '砂あらしがおさまった',
               'すなあらしがおさまった', '雪が止んだ', 'ゆきがやんだ')
TERRAIN_START = [('grassy', ('草がいっぱいに生えた', 'くさがいっぱいにはえた', 'グラスフィールド')),
                 ('electric', ('電気が駆けめぐる', 'でんきがかけめぐる', 'エレキフィールド')),
                 ('psychic', ('不思議な感じに', 'ふしぎなかんじに', 'サイコフィールド')),
                 ('misty', ('霧が立ち込めた', 'きりがたちこめた', 'ミストフィールド'))]
TERRAIN_END = ('草が消え去った', '電気が消え去った', '不思議な感じが消え去った', '霧が消え去った', 'もとにもどった足元',
               'フィールドが消え去った')
# the status line at the top of the party / info screens: 「あめ状態」「エレキフィールド状態」 ...
BAR_WEATHER = [('sun', ('はれ', 'にほんばれ', 'ひざしがつよい')), ('rain', ('あめ',)), ('sand', ('すなあらし',)),
               ('snow', ('ゆき',))]
BAR_TERRAIN = [('grassy', ('グラスフィールド',)), ('electric', ('エレキフィールド',)), ('psychic', ('サイコフィールド',)),
               ('misty', ('ミストフィールド',))]
STATUS = [('brn', ('やけどを負った', 'やけどをおった')), ('par', ('まひして', 'まひした')),
          ('tox', ('もうどくをあびた', '猛毒を浴びた')), ('psn', ('どくをあびた', '毒を浴びた')),
          ('slp', ('眠ってしまった', 'ねむってしまった')), ('frz', ('凍りついた', 'こおりついた'))]
TR_START = ('時空をゆがめた', 'じくうをゆがめた')
TR_END = ('時空が元に戻った', 'じくうがもとにもどった')
SUB_UP = ('身代わりが現れた', 'みがわりがあらわれた', 'みがわりが現れた')
SUB_DOWN = ('身代わりは消えてしまった', 'みがわりはきえてしまった', 'みがわりは消えてしまった')
# あばれる状態（げきりん・あばれる・はなびらのまい）: 2〜3ターン同じ技を出し続け、その間は行動選択画面が出ない。終わると混乱する。
RAMPAGE = {'げきりん', 'あばれる', 'はなびらのまい'}
CONF_START = ('混乱した', 'こんらんした', '混乱している', 'こんらんしている')
CONF_END = ('混乱が解けた', 'こんらんがとけた', '混乱がとけた', '混乱が治った', 'こんらんがなおった')
CURE = ('治った', 'なおった', '目を覚ました', 'めをさました', '溶けた', 'とけた')
ITEM_MSG = [('きあいのタスキ', True, ('きあいのタスキで',)), ('オボンのみ', True, ('オボンのみで', 'オボンのみを')),
            ('いのちのたま', False, ('いのちのたまで', '命が少し削られた', 'いのちがすこしけずられた')),
            ('ゴツゴツメット', False, ('ゴツゴツメットで',)), ('たべのこし', False, ('たべのこしで',)),
            ('ふうせん', False, ('ふうせんで浮いている', 'ふうせんでういている')), ('ふうせん', True, ('ふうせんが割れた', 'ふうせんがわれた')),
            ('しろいハーブ', True, ('しろいハーブで',)), ('メンタルハーブ', True, ('メンタルハーブで',)),
            ('ラムのみ', True, ('ラムのみで',)), ('レッドカード', True, ('レッドカードを',)),
            ('だっしゅつボタン', True, ('だっしゅつボタンで',)), ('ノーマルジュエル', True, ('ノーマルジュエルで',)),
            ('サイコシード', True, ('サイコシードで',)), ('エレキシード', True, ('エレキシードで',)),
            ('グラスシード', True, ('グラスシードで',)), ('ミストシード', True, ('ミストシードで',))]


try:
    from calc import JT as _JT
    TYPE_JA = sorted(((ja, en) for en, ja in _JT.items()), key=lambda x: -len(x[0]))
except Exception:
    TYPE_JA = []


def type_change(s):
    """「Xは ほのおタイプに なった！」 (へんげんじざい / リベロ / みずびたし / マジカルシャイン...) -> ('set', [type]);
    「Xに くさタイプが 追加された！」 (もりののろい / ハロウィン) -> ('add', type). None otherwise."""
    d = devoice(s)
    for ja, en in TYPE_JA:
        dj = devoice(ja)
        i = d.find(dj + 'タイフ')
        if i < 0:
            continue
        rest = d[i + len(dj) + 3:]
        if rest.startswith('に') and ('なった' in rest or 'へんかした' in rest or '変化' in rest):
            return 'set', [en]
        if rest.startswith('か') and ('追加' in rest or 'ついか' in rest):
            return 'add', en
    return None


# abilities that set the weather / terrain when the mon comes in (the popup names the ability)
ABILITY_FIELD = {'あめふらし': ('weather', 'rain'), 'ひでり': ('weather', 'sun'), 'すなおこし': ('weather', 'sand'),
                 'ゆきふらし': ('weather', 'snow'), 'エレキメイカー': ('terrain', 'electric'),
                 'グラスメイカー': ('terrain', 'grassy'), 'サイコメイカー': ('terrain', 'psychic'),
                 'ミストメイカー': ('terrain', 'misty')}


def parse_turn(lines, dedupe=True):
    """dedupe=False when the lines come from the message-box watcher (each message once, in order): the same
    message twice (「効果は いまひとつだ」 for two moves) then means it happened twice."""
    ev = {'moves': [], 'boosts': [], 'weather': None, 'weather_end': False, 'terrain': None, 'terrain_end': False,
          'items': [], 'status': [], 'cured': [], 'hazards': [], 'faint': [], 'switch': [], 'mega': [], 'crit': 0,
          'super_effective': 0, 'abilities': [], 'trick_room': False, 'trick_room_end': False, 'sub': [], 'sub_end': [],
          'types': [], 'confusion': [], 'confusion_end': []}
    seen = set()
    ctx = {'side': None, 'name': None}  # whose message the previous line was (a message often spans two lines)
    came_in = {'moved': False}          # the mon each side sent in last, and whether a move was used since
    on_field = {}                       # the mon last seen in play on each side
    for raw in lines:
        s = norm(raw)
        if not s or (dedupe and s in seen):
            continue
        seen.add(s)
        side = side_of(s)
        name = find_name(s)
        prev = dict(ctx)
        # a mon named in a message is on the field at that moment (unless the message takes it out)
        if name:
            psd = _team_side(name) or side
            if not _in_team(psd, name) and not (psd == 'opp' and exact_name(s) == name and not _team_side_only_me(name)):
                psd = None               # not a mon of that side (side lost by the OCR): say nothing
        if name and psd:
            if has(s, ('引っこめ', 'ひっこめ', '戻れ', 'もどれ', 'たおれ', '倒れ', '戻っていく', 'もどっていく')):
                on_field[psd] = None
            elif not has(s, ('繰り出し', 'ゆけっ', 'いけっ')):
                on_field[psd] = name
        if name or side_marked(s):
            ctx = {'side': side if side_marked(s) or name else ctx['side'], 'name': name}
        if name and has(s, CONF_END):
            ev['confusion_end'].append({'side': side, 'mon': name}); continue
        if name and has(s, CONF_START) and not has(s, ('こんらんして', '混乱して')) or (name and has(s, ('混乱した', 'こんらんした'))):
            ev['confusion'].append({'side': side, 'mon': name}); continue
        tc = type_change(s)
        if tc:
            # the type changed (an ability or a move): only the message says so
            ev['types'].append({'side': side if (name or side_marked(s)) else (prev['side'] or side),
                                'mon': name or prev.get('name'), 'mode': tc[0], 'type': tc[1]})
            continue
        if has(s, TR_END):
            ev['trick_room_end'] = True; continue
        if has(s, TR_START):
            ev['trick_room'] = True; continue
        if name and has(s, SUB_UP):
            ev['sub'].append({'side': side, 'mon': name}); continue
        if name and has(s, SUB_DOWN):
            ev['sub_end'].append({'side': side, 'mon': name}); continue
        # move use: 「(相手の)Xの Y！」
        mu = move_use(s)
        if mu:
            ev['moves'].append({'side': side, 'mon': mu[1], 'move': mu[2]})
            came_in['moved'] = True
            continue
        # stat change
        # (OCR reads 「っ」 as 「つ」 and 「が」 as 「か」: 下がつた / 下かった)
        m = re.search(r'の(こうげき|攻撃|ぼうぎょ|防御|とくこう|特攻|とくぼう|特防|すばやさ|素早さ|命中率|回避率)[がか]'
                      r'(ぐぐーんと|ぐーんと|ぐんと|がくーんと|がく[っつ]と)?(上[がか][っつ]た|あ[がか][っつ]た|下[がか][っつ]た|さ[がか][っつ]た)', s)
        if m and name:
            up = m.group(3)[0] in '上あ'
            mag = (UP if up else DOWN).get((m.group(2) or '').replace('つ', 'っ'), 1)
            ev['boosts'].append({'side': side, 'mon': name, 'stat': STAT[m.group(1)], 'delta': mag if up else -mag})
            other = 'opp' if side == 'me' else 'me'
            if STAT[m.group(1)] == 'atk' and not up and mag == 1 and not came_in['moved'] and came_in.get(other):
                # attack -1 right after the other side sent a mon in, before any move: its いかく
                if not any(x['ability'] == 'いかく' and x['mon'] == came_in[other] for x in ev['abilities']):
                    ev['abilities'].append({'side': other, 'mon': came_in[other], 'ability': 'いかく', 'inferred': True})
            continue
        for w, keys in WEATHER_START:
            if has(s, keys):
                ev['weather'] = w
        if has(s, WEATHER_END):
            ev['weather_end'] = True
        for t, keys in TERRAIN_START:
            if has(s, keys) and not has(s, TERRAIN_END):
                ev['terrain'] = t
        if has(s, TERRAIN_END):
            ev['terrain_end'] = True
        for st, keys in STATUS:
            if has(s, keys) and name:
                ev['status'].append({'side': side, 'mon': name, 'status': st})
                break
        if name and has(s, CURE) and not any(has(s, ks) for _, ks in STATUS):
            ev['cured'].append({'side': side, 'mon': name})
        for item, consumed, keys in ITEM_MSG:
            if has(s, keys):
                ev['items'].append({'side': side, 'mon': name, 'item': item, 'consumed': consumed})
        if has(s, ('とがった岩', 'とがったいわ', 'った岩')):
            # set (「…周りに とがった岩が ただよい始めた」) or hit on switch-in (「…に とがった岩が 食いこんだ」)
            if has(s, ('ただよ', 'よい始め', '食い', 'くいこ', 'いこんだ', 'いんだ')):
                hs = side if side_marked(s) else (prev['side'] or 'me')
                if not any(x['side'] == hs for x in ev['hazards']):
                    ev['hazards'].append({'side': hs, 'hazard': 'rocks'})
        if name and has(s, ('倒れた', 'たおれた')):
            ev['faint'].append({'side': side, 'mon': name})
        if has(s, ('繰り出した', 'くりだした', '繰り出し')):
            # the opponent sent one of its six in: pick the closest of them even when the OCR garbled the name
            opp6 = _opp_team()
            ex = exact_name(s)
            n2 = ex if ex and not _team_side_only_me(ex) else \
                (name if name and (not opp6 or BASE.get(name, name) in opp6) else (best_of(s, opp6) if opp6 else None))
            if n2:
                ev['switch'].append({'side': 'opp', 'mon': n2})
                came_in.update(opp=n2, moved=False)
                on_field['opp'] = n2
        if has(s, ('引っこめた', 'ひっこめた')):
            ev.setdefault('withdraw', []).append({'side': 'opp'})
        elif name and (devoice(s)[:5].startswith(('ゆけつ', 'いけつ', '行け')) or 'がんばれ' in s or 'たのんだ' in s):
            ev['switch'].append({'side': 'me', 'mon': name})
            came_in.update(me=name, moved=False)
            on_field['me'] = name
        if MEGA_RE.search(devoice(s).replace('力', 'カ')) or MEGA_RE.search(s):
            # 「(相手の) Xは メガXに メガシンカした！」; the first half may be on the line before
            # (or the 「…ナイトと …リングが 反応した」 line); with no name the tracker uses the mon in play
            mside = 'opp' if side_marked(s) or prev['side'] == 'opp' else ('me' if name or prev['name'] else None)
            if not any(x['side'] == mside for x in ev['mega']):
                ev['mega'].append({'side': mside, 'mon': name or prev['name']})
            continue
        if name and len(s) <= len(name) + 14:
            ab = next((a for a in ABILITIES if a in s[s.find(name) + len(name):]), None)
            if ab:
                ev['abilities'].append({'side': side, 'mon': name, 'ability': ab})
                w = ABILITY_FIELD.get(ab)
                if w and w[0] == 'weather' and not ev['weather']:
                    ev['weather'] = w[1]
                elif w and w[0] == 'terrain' and not ev['terrain']:
                    ev['terrain'] = w[1]
        if '急所に当たった' in s or 'きゅうしょにあたった' in s:
            ev['crit'] += 1
        h = HIT_RE.search(s)
        if h and ev['moves']:
            ev['moves'][-1]['hits'] = int(h.group(1))
        if has(s, ('効果はバツグン', 'こうかはばつぐん', 'バツグンだ', 'ばつぐんだ')):
            ev['super_effective'] += 1
    ev['on_field'] = on_field
    first = ev['moves'][0]['side'] if ev['moves'] else None
    ev['first'] = first
    return ev


HIT_RE = re.compile(r'(\d+)回(当たった|あたった)')
# messages that belong to the move just used (the HP shown after them is still that move's result)
FOLLOW = ('効果はバツグン', 'こうかはばつぐん', '効果はいまひとつ', 'こうかはいまひとつ', '急所に当たった', 'きゅうしょにあたった')
MISS = ('外れた', 'はずれた', '当たらなかった', 'あたらなかった', '効果がないよう', 'こうかがないよう', '防いだ', 'ふせいだ',
        '守った', 'まもった', 'うまく決まらなかった', 'うまくきまらなかった', '身代わりが', 'みがわりが')


UI_WORDS = ('用語', '説明', '閉じる', '閉しる', '持ち物', '特性', 'COMMAND', '様子を見る', '威力', '命中', '技分類',
            'こうかあり', 'こうかあ', 'ログを見る', 'つよさの表示', 'ステータス', 'たたかう')
MSG_WORDS = ('効果', 'こうか', '急所', '当たった', 'あたった', 'たおれた', '倒れた', '繰り出した', 'くりだした', 'ゆけっ', 'いけっ',
             '戻れ', 'もどれ', '上がった', '下がった', 'あがった', 'さがった', '回復', 'かいふく', 'ダメージ', '受けた', 'うけた',
             '反応', 'メガシンカ', '状態', '雨', '日差し', 'ひざし', '砂あらし', 'すなあらし', '雪', 'フィールド', '岩', 'まきびし',
             '身代わり', 'みがわり', '外れた', 'はずれた', '防い', '守', '眠', 'ねむ', 'まひ', 'やけど', 'どく', 'こおり', '混乱',
             'こんらん', 'ひるんで', '動けない', 'うごけない', '体力', '削られた', 'けずられた', '吸い取', '戻っていく',
             'もどっていく', '時空', '勝負', 'しょうぶ', 'しようぶ', 'おいかぜ', 'かべ', 'リフレクター', 'オーロラベール', 'ちょうはつ',
             'アンコール', 'たべのこし', 'オボン', 'タスキ', 'いのちのたま', 'ゴツゴツメット', '逃げ')


def is_message(raw):
    """A read of the message box that is a battle message (not the move list / timer / descriptions that cover the
    same place, nor noise from the background): it names a mon of this battle or says something battles say."""
    if re.search(r'\d{1,2}\s*[:：;i]\s*\d{2}', raw):
        return False            # the timer of the move-selection screen
    body = re.sub(r'\s', '', raw)
    junk = len(re.findall(r'[^ぁ-んァ-ヶ一-龥ー/!！?、。・…ぁ-ゖ]', body))
    if body and junk / len(body) > 0.25:
        return False            # mostly noise: the moving background or a menu read as text
    s = norm(raw)
    if len(re.findall(r'[ぁ-んァ-ヶ一-龥]', s)) < 4 or has(s, UI_WORDS):
        return False
    return bool(locate_name(s)) or has(s, MSG_WORDS)


def _items():
    try:
        import engine as _E
        return sorted({v['ja'] for v in _E.ITEMS.values() if len(v.get('ja') or '') >= 3}, key=len, reverse=True)
    except Exception:
        return [k for k, _, _ in ITEM_MSG]


ITEM_NAMES = None


def popup_read(raw):
    """The ability / item popup shown beside a mon (「レントラーの いかく」「ニョロトノの だっしゅつボタン」):
    (name, 'ability' | 'item', what) or None. Abilities and items are matched closely (OCR errors), within the
    abilities of this battle's mons first."""
    global ITEM_NAMES
    s = apply_fixes(norm(raw))
    loc = locate_name(s)
    if not loc:
        return None
    name, _, end = loc
    tail = s[end:]
    if tail.startswith('の'):
        tail = tail[1:]
    tail = re.sub(r'[!/！?。、・]+$', '', tail)
    if len(tail) < 2:
        return None
    if ITEM_NAMES is None:
        ITEM_NAMES = _items()
    dt = devoice(tail)
    best = None
    for kind, words in (('ability', ABILITIES), ('item', ITEM_NAMES)):
        for w in words:
            dw = devoice(w)
            if abs(len(dw) - len(dt)) > 2:
                continue
            r = 1.0 if dw == dt else difflib.SequenceMatcher(None, dt, dw).ratio()
            if r >= 0.75 and (best is None or r > best[0]):
                best = (r, kind, w)
    if best and best[0] < 1.0:
        learn_fix(tail, best[2])
    return (name, best[1], best[2]) if best else None


def damage_events(timeline, hp0=None, active0=None):
    """How much each move took off its target, from the message box and the HP panels read together.

    timeline: in order, {'msg': text} for each message shown, and {'side': 'me'|'opp', 'hp': value} for each HP
    panel reading (ours = real HP, theirs = %). hp0: {'me': hp, 'opp': pct} on the command screen before the turn.
    A move's damage = the target's HP before the move message → the last reading before the next message that is
    not about that same hit (「効果は バツグンだ」「急所に当たった」「N回 当たった」 are). Readings are trusted only
    when the panel was seen after anything else could have changed that HP (items, weather, recoil ...).
    active0: {'me': name, 'opp': name} out at the start of the turn (followed through switches / moves).
    Returns [{'side': attacker, 'mon', 'move', 'target': side, 'target_mon', 'before', 'after', 'hits', 'crit'}]."""
    active = dict(active0 or {})
    cur = dict(hp0 or {})
    fresh = {k: True for k in cur}           # the value is the panel's latest, nothing changed it unseen
    last_t = {}
    out, pend = [], None

    def close():
        nonlocal pend
        if pend and pend.get('seen') and not pend.get('miss') and pend['before'] is not None:
            tg = pend['target']
            pend['after'] = cur.get(tg)
            if pend['after'] is not None and pend['after'] <= pend['before']:
                out.append({k: pend[k] for k in ('side', 'mon', 'move', 'target', 'target_mon', 'before', 'after',
                                                 'hits', 'crit')})
        pend = None

    for e in timeline:
        if 'msg' not in e:
            if e.get('gone'):
                # the panel went away: the HP shown last is final only if it had stopped moving
                if pend and e['side'] == pend['target'] and e.get('t', 0) - last_t.get(e['side'], -9) < 0.6:
                    pend['seen'] = False
                continue
            if 'hp' not in e:
                continue             # panel events (switch / form change seen on the HP panel)
            cur[e['side']], fresh[e['side']] = e['hp'], True
            last_t[e['side']] = e.get('t', 0)
            if pend and e['side'] == pend['target']:
                pend['seen'] = True
            continue
        s = norm(e['msg'])
        if not s:
            continue
        if pend and (has(s, FOLLOW) or HIT_RE.search(s)):
            if '急所' in s or 'きゅうしょ' in s:
                pend['crit'] = True
            h = HIT_RE.search(s)
            if h:
                pend['hits'] = int(h.group(1))
            continue
        if pend and has(s, MISS):
            pend['miss'] = True
            continue
        if pend and has(s, ('倒れた', 'たおれた')) and side_of(s) == pend['target']:
            cur[pend['target']], pend['seen'] = 0, True     # the panel turns grey at 0: the faint message says it
        close()
        mu = move_use(s)
        name, mv = (mu[1], mu[2]) if mu else (None, None)
        if mu and MOVE.get(mv, {}).get('cat') != 'status':
            side = side_of(s)
            tg = 'me' if side == 'opp' else 'opp'
            active[side] = name
            pend = {'side': side, 'mon': name, 'move': mv, 'target': tg, 'target_mon': active.get(tg),
                    'hits': None, 'crit': False,
                    'before': cur.get(tg) if fresh.get(tg) else None, 'seen': False}
        else:
            pt = parse_turn([e['msg']])
            for sw in pt['switch']:
                active[sw['side']] = sw['mon']
                fresh[sw['side']] = False        # a new mon: its HP is not known until its panel is read
            if pt['switch'] or pt['mega'] or pt['boosts'] or pt['weather'] or pt['terrain'] or pt['trick_room'] or \
                    has(s, ('反応した', 'はんのうした', '戻れ', 'もどれ', '戻っていく', 'もどっていく')):
                continue             # these do not change anyone's HP
            for k in fresh:          # anything else (items, weather, recoil, switching ...) may have changed HP
                fresh[k] = False
    close()
    return out


def _my_bases():
    try:
        from team import TEAM
        return [BASE.get(m.species, m.species) for m in TEAM]
    except Exception:
        return []


MY_BASES = _my_bases()


def canon(side, name, opp_team=()):
    """The game shows some forms by the species name only (our ヒートロトム appears as 「ロトム」): map a name to the
    member of that side's team it means."""
    if not name:
        return name
    name = BASE.get(name, name)
    team = MY_BASES if side == 'me' else [BASE.get(x, x) for x in opp_team]
    if not team or name in team:
        return name
    hit = [b for b in team if b.endswith(name) or name.endswith(b)]
    return hit[0] if len(hit) == 1 else name


class FieldTracker:
    """Keeps the running field state across turns."""

    def __init__(self, path):
        self.path = path
        self.s = {'turn': 0, 'weather': None, 'weather_turns': 0, 'terrain': None, 'terrain_turns': 0, 'trick_room': 0,
                  'rocks_me': False, 'rocks_opp': False, 'active': {'me': None, 'opp': None},
                  'mons': {'me': {}, 'opp': {}}, 'mega_used': {'me': False, 'opp': False}, 'history': []}

    def opp_team(self):
        try:
            rec = json.load(open(os.path.join(os.path.dirname(self.path), '..', 'current.json'), encoding='utf-8'))
            return rec.get('opp_team') or []
        except Exception:
            return []

    def whose(self, side, name):
        """(side, name) of a message whose side / name the OCR may have lost: a mon only one team has decides the
        side; with no name, the mon in play on that side."""
        if name:
            b = BASE.get(name, name)
            opp = [BASE.get(x, x) for x in self.opp_team()]
            in_me = any(m == b or m.endswith(b) or b.endswith(m) for m in MY_BASES)
            in_opp = any(m == b or m.endswith(b) or b.endswith(m) for m in opp)
            if in_me != in_opp:
                side = 'me' if in_me else 'opp'
        if side and not name:
            name = self.s['active'][side]
        return side, name

    def unlock(self, side):
        """We are choosing a move again, so our あばれる状態 (げきりん etc.) is over: while it lasts the game skips the
        move-selection screen (2-3 turns). Their lock is not affected by our screens."""
        act = self.s['active'].get(side)
        if act and act in self.s['mons'][side]:
            self.s['mons'][side][act]['rampage'] = False

    def add_opp(self, name):
        """A mon of theirs that was not in the six read from the team preview: add it to the battle record, so the
        sets and the decisions know it (the preview was misidentified)."""
        b = BASE.get(name, name)
        p = os.path.join(os.path.dirname(self.path), '..', 'current.json')
        try:
            rec = json.load(open(p, encoding='utf-8'))
        except Exception:
            return
        team = rec.get('opp_team') or []
        if not team or b in [BASE.get(x, x) for x in team]:
            return
        rec['opp_team'] = team + [b]
        rec.setdefault('opp_team_fixed', []).append(b)
        try:
            safeio.write_json(p, rec)
            _CTX['key'] = None           # names / moves of this battle changed
        except Exception:
            pass

    def mon(self, side, name):
        mega = name in BASE
        raw = name
        name = canon(side, name, self.opp_team() if side == 'opp' else ())
        m = self.s['mons'][side].setdefault(name, {'boosts': {}, 'item_consumed': None, 'items_seen': [],
                                                   'status': None, 'fainted': False, 'moves_seen': [],
                                                   'mega': False, 'ability': None})
        if mega:
            m['mega'] = True
            m['mega_name'] = raw
        return m

    def apply(self, ev):
        s = self.s
        # the turns of an あばれる状態 have no move-selection screen: their messages arrive together, one 'me' move each
        s['turn'] += max(1, sum(1 for m in ev['moves'] if m['side'] == 'me' and m['move'] in RAMPAGE))
        for t, key in (('weather', 'weather_turns'), ('terrain', 'terrain_turns')):
            if s[key]:
                s[key] -= 1
                if s[key] == 0:
                    s[t] = None
        if s.get('trick_room'):
            s['trick_room'] -= 1
        if ev.get('trick_room_end'):
            s['trick_room'] = 0
        elif ev.get('trick_room'):
            s['trick_room'] = 4  # 5 turns including the one it was set up on
        for side in ('me', 'opp'):
            for mm in s['mons'][side].values():
                mm['glaive'] = False
        if ev['weather_end']:
            s['weather'], s['weather_turns'] = None, 0
        if ev['weather']:
            s['weather'], s['weather_turns'] = ev['weather'], 5
        if ev['terrain_end']:
            s['terrain'], s['terrain_turns'] = None, 0
        if ev['terrain']:
            s['terrain'], s['terrain_turns'] = ev['terrain'], 5
        for w in ev.get('withdraw', []):
            if not any(sw['side'] == w['side'] for sw in ev['switch']):
                s['active'][w['side']] = None      # taken back and the newcomer not read: unknown, not the old one
        for sw in ev['switch']:
            if sw['side'] == 'opp':
                self.add_opp(sw['mon'])
            old = s['active'][sw['side']]
            if old:
                om = self.mon(sw['side'], old)
                om['boosts'] = {}
                om.update(sub=0, last_move=None, rampage=False, toxn=0, types=None, added_type=None, confusion=False)
            s['active'][sw['side']] = canon(sw['side'], sw['mon'], self.opp_team() if sw['side'] == 'opp' else ())
            self.mon(sw['side'], sw['mon'])
        for m in ev['moves']:
            if not s['active'][m['side']]:
                s['active'][m['side']] = canon(m['side'], m['mon'], self.opp_team() if m['side'] == 'opp' else ())
            mm = self.mon(m['side'], m['mon'])
            if m['move'] not in mm['moves_seen']:
                mm['moves_seen'].append(m['move'])
            mm['rampage'] = m['move'] in RAMPAGE and not (mm.get('rampage') and mm.get('last_move') == m['move'])
            mm['last_move'] = m['move']
            mm['glaive'] = m['move'] == 'きょけんとつげき'
        for b in ev['boosts']:
            mb = self.mon(b['side'], b['mon'])['boosts']
            mb[b['stat']] = max(-6, min(6, mb.get(b['stat'], 0) + b['delta']))
        for it in ev['items']:
            side, name = it['side'], it['mon'] or s['active'][it['side']]
            if not name:
                continue
            mm = self.mon(side, name)
            if it['item'] not in mm['items_seen']:
                mm['items_seen'].append(it['item'])
            if it['consumed']:
                mm['item_consumed'] = it['item']
        for st in ev['status']:
            self.mon(st['side'], st['mon'])['status'] = st['status']
            self.mon(st['side'], st['mon'])['toxn'] = 0
        for sb in ev.get('sub', []):
            self.mon(sb['side'], sb['mon'])['sub'] = 25
        for sb in ev.get('sub_end', []):
            self.mon(sb['side'], sb['mon'])['sub'] = 0
        for side in ('me', 'opp'):
            act = s['active'][side]
            if act and self.mon(side, act).get('status') == 'tox':
                self.mon(side, act)['toxn'] = self.mon(side, act).get('toxn', 0) + 1
        for c in ev['cured']:
            self.mon(c['side'], c['mon'])['status'] = None
        for h in ev['hazards']:
            s['rocks_' + h['side']] = True
        for f in ev['faint']:
            self.mon(f['side'], f['mon'])['fainted'] = True
        for mg in ev['mega']:
            side, name = self.whose(mg.get('side'), mg.get('mon'))
            if not side or not name:
                continue
            s['mega_used'][side] = True
            self.mon(side, name)['mega'] = True
        for ab in ev['abilities']:
            side, name = self.whose(ab['side'], ab['mon'])    # the ability popup has no 「相手の」: the team decides
            if side and name:
                self.mon(side, name)['ability'] = ab['ability']
        for cf in ev.get('confusion', []):
            side, name = self.whose(cf.get('side'), cf.get('mon'))
            if side and name:
                self.mon(side, name)['confusion'] = True
        for cf in ev.get('confusion_end', []):
            side, name = self.whose(cf.get('side'), cf.get('mon'))
            if side and name:
                self.mon(side, name)['confusion'] = False
        for fc in ev.get('forms', []):      # a form change seen on the HP panel (not a mega evolution)
            side, name = self.whose(fc.get('side'), fc.get('mon'))
            if side and name:
                mm = self.mon(side, name)
                mm['form_changes'] = mm.get('form_changes', 0) + 1
                if BASE.get(name, name) == 'イルカマン':
                    mm['hero'] = True
        for tc in ev.get('types', []):
            side, name = self.whose(tc.get('side'), tc.get('mon'))
            if not side or not name:
                continue
            mm = self.mon(side, name)
            if tc['mode'] == 'set':
                mm['types'], mm['added_type'] = tc['type'], None
            else:
                mm['added_type'] = tc['type']
        for side, n in (ev.get('on_field') or {}).items():
            if n:   # the last mon a message showed in play (catches a switch whose own message was misread)
                s['active'][side] = canon(side, n, self.opp_team() if side == 'opp' else ())
        for side in ('me', 'opp'):        # a changed type lasts only while the mon stays in
            act = s['active'].get(side)
            for n, mm in s['mons'][side].items():
                if n != act and (mm.get('types') or mm.get('added_type')):
                    mm['types'] = mm['added_type'] = None
        s['history'].append({k: v for k, v in ev.items() if v})
        s['history'] = s['history'][-20:]
        self.save()

    def observe_bar(self, text):
        """The field-status line shown on the party / info screens (「あめ状態」「トリックルーム状態」 ...).
        Only adds what the messages missed; returns what was added."""
        t = text.replace(' ', '')
        s, added = self.s, []
        for key, names in BAR_WEATHER:
            if any(n + '状態' in t for n in names) and s['weather'] != key:
                s['weather'], s['weather_turns'] = key, 5
                added.append(key)
        for key, names in BAR_TERRAIN:
            if any(n + '状態' in t for n in names) and s['terrain'] != key:
                s['terrain'], s['terrain_turns'] = key, 5
                added.append(key)
        if 'トリックルーム状態' in t and not s.get('trick_room'):
            s['trick_room'] = 4
            added.append('trick_room')
        return added

    def save(self):
        safeio.write_json(self.path, self.s, indent=1)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    lines = [l for l in open(sys.argv[1], encoding='utf-8').read().splitlines()] if len(sys.argv) > 1 else sys.stdin.read().splitlines()
    print(json.dumps(parse_turn(lines), ensure_ascii=False, indent=1))
