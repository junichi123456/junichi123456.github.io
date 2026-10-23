"""上位構築の総当たり（4手読み同士のブラインド戦）。仕様: pokechamp/specs/SPEC_ROUNDROBIN.md

  python3 roundrobin.py plan --tier 1|2|3 [--tier1-size 24] [--no-select] [--procs 4] [--force] [--out-dir D]
  python3 roundrobin.py run  [--max-games N] [--procs 4] [--retry-errors] [--games-per-pair 2] [--out-dir D]
  python3 roundrobin.py report [--out-dir D]
  python3 roundrobin.py selftest [--quick] [--out-dir D]
  python3 roundrobin.py show <id>
  python3 roundrobin.py adapt plan|run|report|selftest   (SPEC_ADAPT.md)
"""
import argparse, collections, hashlib, itertools, json, math, os, re, statistics, sys, time, traceback, zlib
import multiprocessing as mp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle as B  # noqa: E402
import refine as R  # noqa: E402
import prep  # noqa: E402
import design  # noqa: E402
import safeio  # noqa: E402
from calc import Mon, POKE  # noqa: E402

RR_VERSION = 'rr1'
DEPTH = (4, 4)
DEF_OUT = os.path.join(HERE, '..', 'logs', 'refine')
DEF_MD = os.path.join(HERE, '..', 'logs', 'ROUNDROBIN.md')
GUIDE_OVERRIDES = os.path.join(HERE, 'data', 'rr_guide_overrides.json')
_FW = str.maketrans('ＸＹＺ', 'XYZ')

ABBR = {'マンダ': 'ボーマンダ', 'グロス': 'メタグロス', 'ガブ': 'ガブリアス', 'リザ': 'リザードン', 'ブリ': 'ブリジュラス',
        'グソク': 'グソクムシャ', 'ガルド': 'ギルガルド', 'セグ': 'セグレイブ', 'アマガ': 'アーマーガア', 'イエ': 'イエッサン',
        'カメ': 'カメックス', 'エッテ': 'フラエッテ', 'カバ': 'カバルドン', 'ニューラ': 'オオニューラ', 'ガモス': 'ウルガモス',
        'ミミ': 'ミミッキュ', 'ルカ': 'ルカリオ', 'ヒトム': 'ヒートロトム', 'ウォッシュ': 'ウォッシュロトム'}


def paths(out_dir=None):
    d = out_dir or DEF_OUT
    return {'dir': d, 'plan': os.path.join(d, 'rr_plan.json'), 'games': os.path.join(d, 'rr_games.json'),
            'logs': os.path.join(d, 'rr_logs.jsonl'), 'csv': os.path.join(d, 'rr_matrix.csv'),
            'timing': os.path.join(d, 'rr_timing.json'),
            'md': os.path.join(d, 'ROUNDROBIN.md') if out_dir else DEF_MD}


# ---------------------------------------------------------------- 構築の正規化 (3.1)
def raw_teams():
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))['teams']
    if os.path.exists(R.NEW_P):
        ids = {t['id'] for t in data}
        data += [t for t in json.load(open(R.NEW_P, encoding='utf-8'))['teams'] if t['id'] not in ids]
    return data


def _ap(ap):
    return {('def' if k == 'defn' else k): v for k, v in (ap or {}).items()}


def _mega_by_stone(base, item):
    it = (item or '').translate(_FW)
    cands = B.MEGA_OF.get(base, [])
    hit = [m for m in cands if B.STONE_FOR.get(m) == it]
    if len(hit) == 1:
        return hit[0]
    if len(cands) == 1:
        return cands[0]
    suf = it[-1] if it[-1:] in ('X', 'Y', 'Z') else ''
    hit = [m for m in cands if suf and m[-1:] == {'X': 'Ｘ', 'Y': 'Ｙ', 'Z': 'Ｚ'}[suf]]
    if len(hit) == 1:
        return hit[0]
    raise ValueError(f'メガ種族が決まらない: {base} {item}')


def rr_mon(m):
    name = B.norm(m['name'])
    base = B._base(name)
    item = m.get('item') or ''
    stone = False
    if name in B.BASE_OF:                                   # 1: 名前がメガ名
        species, mega, ab, bab = name, True, m['ability'], m.get('base_ability') or POKE[base]['ab'][0]
    elif 'ナイト' in item and base in B.MEGA_OF:             # 2: 名前は基本名だがメガストーン持ち
        species = _mega_by_stone(base, item)
        mega, ab, bab = True, POKE[species]['ab'][0], m['ability']
        stone = True
    else:
        species, mega, ab, bab = name, False, m['ability'], m['ability']
    return {'base': base, 'species': species, 'mega': mega, 'nature': m['nature'], 'ap': _ap(m.get('ap')),
            'ability': ab, 'base_ability': bab, 'item': item, 'moves': list(m['moves']), 'stone': stone}


def rr_team(t):
    r = t.get('rating') or {}
    return {'id': t['id'], 'title': t.get('title', ''), 'rank': r.get('rank'), 'final': r.get('final'),
            'peak': r.get('peak'), 'weight': design.team_weight(t),
            'mons': [rr_mon(m) for m in t['team']]}


def r11_team():
    party = json.load(open(os.path.join(R.PARTY_D, 'ADOPTED.json'), encoding='utf-8'))
    mons = []
    for e in party:
        sp = e['species']
        mega = sp in B.BASE_OF
        base = B.BASE_OF.get(sp, sp)
        mons.append({'base': base, 'species': sp, 'mega': mega, 'nature': e['nature'], 'ap': _ap(e.get('ap') or e.get('defn')),
                     'ability': e['ability'], 'base_ability': POKE[base]['ab'][0] if mega else e['ability'],
                     'item': e.get('item') or '', 'moves': list(e['moves']), 'stone': False})
    return {'id': 'R11', 'title': 'R11（採用パーティ）', 'rank': None, 'final': None, 'peak': None, 'weight': 1.0, 'mons': mons}


def article_form(rt, orig=None):
    d = dict(orig) if orig else {'id': rt['id'], 'title': rt['title']}
    d['team'] = [{'name': m['species'], 'nature': m['nature'], 'ability': m['ability'], 'base_ability': m['base_ability'],
                  'item': m['item'] or None, 'moves': list(m['moves']), 'ap': dict(m['ap'])} for m in rt['mons']]
    return d


def sort_key(rt):
    return (rt['rank'] or 10 ** 6, -max(rt['final'] or 0, rt['peak'] or 0), rt['id'])


# ---------------------------------------------------------------- 適用 (3.2, 3.3)
def rr_apply(team):
    ms = team['mons']
    items = [m['item'] for m in ms if m['item']]
    assert len(set(items)) == len(items), f'持ち物重複 {items}'
    for m in ms:
        assert m['species'] in POKE and m['base'] in POKE, m['species']
        assert 1 <= len(m['moves']) <= 4 and len(set(m['moves'])) == len(m['moves']), m['moves']
        assert all(x in B.MOVE for x in m['moves']), m['moves']
        assert sum(m['ap'].values()) <= 66 and all(0 <= v <= 32 for v in m['ap'].values()), m['ap']
    B.TEAM[:] = [Mon(m['species'], m['nature'], m['ap'], m['ability'], m['item'] or None, m['moves'], label=m['base']) for m in ms]
    my = {}
    for m, mon in zip(ms, B.TEAM):
        if m['mega']:
            my[m['base']] = (Mon(m['base'], m['nature'], m['ap'], m['base_ability'], m['item'] or None, m['moves'], label=m['base']), mon)
        else:
            my[m['base']] = (mon, None)
    B.MY.clear()
    B.MY.update(my)
    B.MY_TYPES = tuple(tuple(m.types) for m in B.TEAM)
    B._OPP_CACHE.clear()


_INIT = {'done': False}
_TEAMS = {}


def _rr_init(rr_teams):
    """ワーカー初期化（冪等）: refine.teams() を1度呼び、KNOWN_TEAMS を rr 構築から作った記事形式に置き換える。"""
    if _INIT['done']:
        return
    R.teams()
    orig = {t['id']: t for t in B.KNOWN_TEAMS}
    B.KNOWN_TEAMS[:] = [article_form(rt, orig.get(rt['id'])) for rt in rr_teams.values()]
    _INIT['done'] = True


def _worker_init(teams):
    global _TEAMS
    _TEAMS = teams
    _rr_init(teams)


# ---------------------------------------------------------------- ガイドの読み取り (4)
def resolve(text, bases):
    s = str(text).translate(_FW).strip()
    if not s:
        return None
    cands = [s]
    if s.startswith('メガ'):
        cands.append(s[2:])
    for c in list(cands):
        if c and c[-1] in 'XYZ':
            cands.append(c[:-1])
    for c in list(cands):
        if c.startswith('H'):
            cands.append('ヒスイ' + c[1:])
        if c.startswith('A'):
            cands.append('アローラ' + c[1:])
    for c in cands:
        if not c:
            continue
        if c in bases:
            return c
        if B._base(c) in bases:
            return B._base(c)
    for c in cands:
        if c in ABBR and ABBR[c] in bases:
            return ABBR[c]
    for c in cands:
        if len(c) >= 2:
            hits = [b for b in bases if c in b]
            if len(hits) == 1:
                return hits[0]
    return None


def _lead_from_note(note, bases):
    note = str(note or '')
    i = note.find('先発')
    if i <= 0:
        return None
    pre = note[:i]
    for L in range(min(10, len(pre)), 1, -1):
        r = resolve(pre[-L:], bases)
        if r:
            return r
    return None


def parse_pick(pick, note, bases):
    """{'ok', 'why', 'full', 'names', 'choices', 'mega', 'free', 'lead'}"""
    names, choices, mega, free = [], [], 0, 0
    for el in pick or []:
        el = str(el).strip()
        r = resolve(el, bases)
        if r:
            names.append(r)
            continue
        parts = [p.strip() for p in re.split(r'\s+or\s+|または|か', el)]
        if len(parts) >= 2:
            rs = [resolve(p, bases) for p in parts]
            if all(rs):
                choices.append(rs)
                continue
        e2 = el.translate(_FW)
        if re.fullmatch(r'メガ(枠)?', e2):
            mega += 1
            continue
        if re.search(r'メガ.*[2２二]体', e2):
            return {'ok': False, 'why': f'メガ2体を求める項目: {el}'}
        if e2.startswith(('@', '＠', '+', '＋')) or any(k in e2 for k in ('枠', '駒', '1体')):
            m = re.search(r'(\d)体', e2)
            free += int(m.group(1)) if m else 1
            continue
        return {'ok': False, 'why': f'読めない要素: {el}'}
    if len(set(names)) != len(names):
        return {'ok': False, 'why': '指名が重複'}
    total = len(names) + len(choices) + mega + free
    lead = _lead_from_note(note, bases)
    first = resolve(pick[0], bases) if pick else None
    if len(names) == 3 and not (choices or mega or free):
        ld = lead if lead in names else (first if first in names else names[0])
        return {'ok': True, 'full': True, 'names': names, 'choices': [], 'mega': 0, 'free': 0, 'lead': ld}
    if len(names) >= 4:
        return {'ok': False, 'why': f'指名が{len(names)}体'}
    if total > 3:
        return {'ok': False, 'why': f'枠が{total}'}
    if not (names or choices or mega):
        return {'ok': False, 'why': '指名なし'}
    ld = lead if lead else (first if first in names else None)
    return {'ok': True, 'full': False, 'names': names, 'choices': choices, 'mega': mega, 'free': free, 'lead': ld}


_NEG = re.compile('ない|以外|にくい|づらい|危険|止め|欲しい|たい|多い|っぽい|そう|その他|無理|保証|必要')
_NAME_KEYS = None


def _name_keys():
    global _NAME_KEYS
    if _NAME_KEYS is None:
        d = {}
        for n in POKE:
            if len(n) >= 3:
                d[n] = B._base(n)
        d.update(ABBR)
        _NAME_KEYS = sorted(d.items(), key=lambda kv: -len(kv[0]))
    return _NAME_KEYS


def names_in(term):
    text, found = term.translate(_FW), []
    for k, v in _name_keys():
        if k in text:
            found.append(v)
            text = text.replace(k, '\0')
    return found


def classify_when(when):
    w = str(when or '').strip()
    if w.startswith('基本') or '最多' in w:
        return 'basic', None
    if _NEG.search(w):
        return 'unreadable', None
    groups = []
    for grp in re.split('[・／/、]', w):
        names, ok = [], True
        for term in re.split('[＋+]', grp):
            ns = names_in(term)
            if not ns:
                ok = False
                break
            names += ns
        if ok and names:
            groups.append(sorted(set(names)))
    return ('cond', groups) if groups else ('unreadable', None)


def holds(groups, b6):
    s = set(b6)
    return any(all(n in s for n in g) for g in groups)


def norm_order(o, bases):
    return [o[0]] + sorted(o[1:], key=bases.index)


def all_orders(rt):
    """除外（メガ持ち2体以上）後の選出（先発, 後発2体は構築の並び順）。"""
    bases = [m['base'] for m in rt['mons']]
    mg = {m['base'] for m in rt['mons'] if m['mega']}
    out = []
    for lead in bases:
        rest = [b for b in bases if b != lead]
        for p in itertools.combinations(rest, 2):
            o = [lead, *p]
            if sum(x in mg for x in o) <= 1:
                out.append(o)
    return out


def satisfying(pr, rt, universe):
    mg = {m['base'] for m in rt['mons'] if m['mega']}
    out = []
    for o in universe:
        s = set(o)
        if not all(n in s for n in pr['names']):
            continue
        if not all(any(c in s for c in ch) for ch in pr['choices']):
            continue
        if pr['mega'] and not (s & mg):
            continue
        if pr['lead'] and o[0] != pr['lead']:
            continue
        out.append(o)
    return out


def analyze_guide(rt, orig, overrides=None):
    """-> gitems（使える項目）, unreadable, rejected_guide"""
    bases = [m['base'] for m in rt['mons']]
    mg = {m['base'] for m in rt['mons'] if m['mega']}
    uni = all_orders(rt)
    items, unread, rej = [], [], []
    ov = (overrides or {}).get(rt['id'])
    if ov:
        for e in (ov if isinstance(ov, list) else [ov]):
            o = norm_order(list(e['order']), bases)
            if e.get('when_any'):
                items.append({'kind': 'cond', 'groups': [sorted(g) for g in e['when_any']], 'full': True, 'orders': [o], 'when': 'override', 'pick': e['order']})
            else:
                items.append({'kind': 'basic', 'groups': None, 'full': True, 'orders': [o], 'when': 'override', 'pick': e['order']})
        return items, unread, rej
    for g in ((orig or {}).get('guide') or {}).get('picks') or []:
        when, pick, note = g.get('when', ''), g.get('pick') or [], g.get('note', '')
        pr = parse_pick(pick, note, bases)
        if not pr['ok']:
            unread.append({'when': when, 'pick': pick, 'why': pr['why']})
            continue
        kind, groups = classify_when(when)
        if pr['full']:
            o = norm_order([pr['lead']] + [n for n in pr['names'] if n != pr['lead']], bases)
            if sum(x in mg for x in o) >= 2:
                rej.append({'order': o, 'why': 'メガ2体（除外）', 'when': when})
                continue
            orders = [o]
        else:
            orders = satisfying(pr, rt, uni)
            if not orders:
                unread.append({'when': when, 'pick': pick, 'why': '部分の条件を満たす選出なし'})
                continue
        if kind == 'unreadable':
            unread.append({'when': when, 'pick': pick, 'why': 'whenが読めない（選出は候補に入れる）'})
        items.append({'kind': kind, 'groups': groups, 'full': pr['full'], 'orders': orders, 'when': when, 'pick': pick,
                      'usable': kind != 'unreadable'})
    return items, unread, rej


def guide_class(art_orders_ok, gitems):
    if art_orders_ok:
        return 'article'
    us = [i for i in gitems if i.get('usable', True) and i['kind'] in ('cond', 'basic')]
    if any(i['kind'] == 'cond' for i in us):
        return 'guide-cond'
    b = next((i for i in us if i['kind'] == 'basic'), None)
    if b and b['full']:
        return 'guide-fixed'
    if us:
        return 'guide-partial'
    return 'none'


# ---------------------------------------------------------------- 候補24通り (3.4)
def build_candidates(rt, orig, w, overrides=None):
    bases = [m['base'] for m in rt['mons']]
    mg = {m['base'] for m in rt['mons'] if m['mega']}
    nm = sum(1 for m in rt['mons'] if m['mega'])
    uni = all_orders(rt)
    lr = {b: B.lead_rate(b) for b in bases}

    def score(o):
        p = 1.0
        for x in o:
            p *= w[x]
        return p * lr[o[0]] / sum(lr[x] for x in o)

    gitems, unread, rej = analyze_guide(rt, orig, overrides)
    rejected = list(rej)
    art, art_all = [], []
    for pk in (orig or {}).get('picks') or []:
        ms = [B._base(x) for x in pk['mons']]
        if len(ms) == 3 and len(set(ms)) == 3 and all(x in bases for x in ms):
            o = norm_order(ms, bases)
            art_all.append(o)
            if sum(x in mg for x in o) >= 2:
                rejected.append({'order': o, 'why': 'メガ2体（除外）', 'when': '記事'})
            elif o not in art:
                art.append(o)
    L, seen = [], set()

    def add(o):
        t = tuple(o)
        if t not in seen and o in uni:
            seen.add(t)
            L.append(o)

    for o in art:
        add(o)
    for it in gitems:
        if it['full']:
            add(it['orders'][0])
    for it in gitems:
        if not it['full']:
            for o in sorted(it['orders'], key=lambda o: (-score(o), str(o)))[:3]:
                add(o)
    for o in sorted(uni, key=lambda o: (-score(o), str(o))):
        add(o)
    if nm == 0:
        cand, no_mega = L[:24], True
    else:
        no_mega = False
        c0 = [o for o in L if not (set(o) & mg)]
        c1 = [o for o in L if len(set(o) & mg) == 1]
        q = min(4, len(c0))
        k1 = min(24 - q, len(c1))
        keep = {tuple(o) for o in c0[:q]} | {tuple(o) for o in c1[:k1]}
        cand = [o for o in L if tuple(o) in keep]
    cs = {tuple(o) for o in cand}
    for it in gitems:
        if it['full'] and tuple(it['orders'][0]) not in cs:
            rejected.append({'order': it['orders'][0], 'why': '枠の上限で外れた', 'when': it['when']})
    for o in art:
        if tuple(o) not in cs:
            rejected.append({'order': o, 'why': '枠の上限で外れた', 'when': '記事'})
    art_ok = [o for o in art if tuple(o) in cs]
    return {'candidates': cand, 'n_cand': len(cand), 'no_mega': no_mega, 'article_orders': art_ok, 'gitems': gitems,
            'unreadable': unread, 'rejected': rejected, 'gclass': guide_class(bool(art_ok), gitems), 'n_mega': nm}


# ---------------------------------------------------------------- 選出 (5)
def rr_select(A, Bid, allowed):
    """A が B の6体だけを見て allowed（タプルの集合）から選ぶ。"""
    import sets as _sets
    ta, tb = _TEAMS[A], _TEAMS[Bid]
    bases = [m['base'] for m in ta['mons']]
    allowed = {tuple(o) for o in allowed}
    saved = (B.match_known, B._load_select_rules, B._focus_mons, _sets.EXCLUDE, B._KNOWN_CTX['team'])
    t0 = time.time()
    try:
        rr_apply(ta)
        _sets.EXCLUDE = {A, Bid}
        B._OPP_CACHE.clear()
        B.match_known = lambda *a, **k: None
        B._load_select_rules = lambda: []
        B._focus_mons = lambda opp6: {}
        B.set_known_context(None)
        best, top, _ = B.select([m['base'] for m in tb['mons']], ignore_stored=True,
                                order_filter=lambda o: tuple(norm_order(list(o), bases)) in allowed)
    finally:
        B.match_known, B._load_select_rules, B._focus_mons, _sets.EXCLUDE, B._KNOWN_CTX['team'] = saved
        B._OPP_CACHE.clear()
    return {'order': norm_order(list(best), bases), 'top3': [[round(float(s), 3), o] for s, o in top[:3]], 'sec': round(time.time() - t0, 2)}


def decide_pair(A, Bid):
    ta, tb = _TEAMS[A], _TEAMS[Bid]
    cs = {tuple(o) for o in ta['candidates']}
    b6 = [m['base'] for m in tb['mons']]
    fb = []

    def rec(order, src, extra=None):
        d = {'src': src, 'fallback': fb, 'sec': 0}
        if order is not None:
            d['order'] = list(order)
        d.update(extra or {})
        return d

    def pick(orders, src):
        allowed = []
        for o in orders:
            if tuple(o) in cs and tuple(o) not in [tuple(x) for x in allowed]:
                allowed.append(o)
        if not allowed:
            fb.append(f'{src}: 候補に無い')
            return None
        if len(allowed) == 1:
            return rec(allowed[0], src)
        return rec(**{'order': None, 'src': src}, extra=rr_select(A, Bid, allowed))

    arts = ta['article_orders']
    if arts:
        r = pick(arts, 'article')
        if r:
            return r
    for it in ta['gitems']:
        if it['kind'] == 'cond' and it.get('usable', True) and holds(it['groups'], b6):
            r = pick(it['orders'], 'guide-cond')
            if r:
                return r
    b = next((i for i in ta['gitems'] if i['kind'] == 'basic' and i.get('usable', True)), None)
    if b:
        r = pick(b['orders'], 'guide-basic')
        if r:
            return r
    return rec(**{'order': None, 'src': 'basic'}, extra=rr_select(A, Bid, ta['candidates']))


def _job_decide(a):
    A, Bid = a
    try:
        return f'{A}|{Bid}', decide_pair(A, Bid)
    except Exception:
        return f'{A}|{Bid}', {'error': traceback.format_exc()[-600:]}


def _job_select(a):
    A, Bid, allowed = a
    return rr_select(A, Bid, allowed)


def _job_static(A):
    ta = _TEAMS[A]
    art = next(t for t in B.KNOWN_TEAMS if t['id'] == A)
    a6 = [m['base'] for m in ta['mons']]
    acc, n = {b: 0.0 for b in a6}, 0
    try:
        for F, tf in _TEAMS.items():
            if F == A:
                continue
            rr_apply(tf)
            B._KNOWN_CTX['team'] = art
            B._OPP_CACHE.clear()
            w = B.opp_pick_weights(a6, list(B.MY.values()))
            for b in a6:
                acc[b] += w[b]
            n += 1
    finally:
        B._KNOWN_CTX['team'] = None
        B._OPP_CACHE.clear()
    return A, {b: v / n for b, v in acc.items()}


# ---------------------------------------------------------------- 対戦 (6)
def pair_ab(x, y):
    return (x, y) if x < y else (y, x)


def game_key(a, b, k):
    return f'{a}|{b}|{k}'


def game_seed(a, b, k):
    return zlib.crc32(f'rr{a}{b}{k}'.encode())


def game_sides(a, b, k):
    return (a, b) if k % 2 == 0 else (b, a)


def _job_game(a):
    key, X, Y, selX, selY, seed = a
    t0 = time.time()
    try:
        rr_apply(_TEAMS[X])
        r = R.blind_play((None, Y, selX, selY, seed, DEPTH[0], DEPTH[1], False, None, False, (X,)))
    except Exception:
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    r['key'] = key
    r['sec'] = round(time.time() - t0, 2)
    return r


def make_pool(procs, teams):
    ctx = mp.get_context('fork' if hasattr(os, 'fork') else 'spawn')
    return ctx.Pool(procs, initializer=_worker_init, initargs=(teams,))


def game_record(job, r, rematch):
    key, X, Y, selX, selY, seed = job
    a, b, k = key.split('|')
    res = r.get('res')
    w = None if res is None else (X if res == 1 else (Y if res == -1 else None))
    return {'a': a, 'b': b, 'k': int(k), 'side0': X, 'side1': Y, 'sel0': selX, 'sel1': selY, 'seed': seed, 'res': res, 'winner': w,
            'judged': r.get('judged'), 'turns': r.get('turns'), 'left': r.get('left'), 'faints': r.get('faints'),
            'sec': r.get('sec'), 'error': r.get('error'), 'rematch': rematch}


# ---------------------------------------------------------------- ファイル
def load_plan(P):
    if not os.path.exists(P['plan']):
        raise SystemExit(f"{P['plan']} がありません。先に plan を実行してください")
    return json.load(open(P['plan'], encoding='utf-8'))


def save_plan(P, plan):
    os.makedirs(P['dir'], exist_ok=True)
    safeio.write_json(P['plan'], plan)


def load_games(P, sig):
    if os.path.exists(P['games']):
        g = json.load(open(P['games'], encoding='utf-8'))
        if g.get('plan_sig') != sig:
            raise SystemExit('rr_games.json の plan_sig が rr_plan.json と違います')
        return g
    return {'version': RR_VERSION, 'plan_sig': sig, 'depth': list(DEPTH), 'games': {}}


def save_games(P, g):
    safeio.write_json(P['games'], g)


def read_jsonl(path):
    out = []
    if os.path.exists(path):
        for line in open(path, encoding='utf-8', errors='replace'):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def append_log(P, key, log):
    p = P['logs']
    need_nl = False
    if os.path.exists(p) and os.path.getsize(p) > 0:
        with open(p, 'rb') as f:
            f.seek(-1, 2)
            need_nl = f.read(1) != b'\n'
    with open(p, 'a', encoding='utf-8') as f:
        if need_nl:
            f.write('\n')
        f.write(json.dumps({'key': key, 'log': log}, ensure_ascii=False) + '\n')
        f.flush()


# ---------------------------------------------------------------- plan
def timing_info(P):
    try:
        return json.load(open(P['timing'], encoding='utf-8'))
    except Exception:
        return None


def circle_pairs(ids):
    t = list(ids)
    if len(t) % 2:
        t.append(None)
    n = len(t)
    out = []
    for _ in range(n - 1):
        for i in range(n // 2):
            x, y = t[i], t[n - 1 - i]
            if x is not None and y is not None:
                out.append(pair_ab(x, y))
        t = [t[0], t[-1]] + t[1:-1]
    return out


def tier_ids(plan, t):
    return plan['tiers'][str(t)]


def main_keys(plan, t, gpp=2):
    """段階 t で新しく増える本戦の鍵（円環法の順、k=0 を全て → k=1 を全て）。"""
    ids = tier_ids(plan, t)
    prev = set(tier_ids(plan, t - 1)) if t > 1 else set()
    pairs = [p for p in circle_pairs(ids) if not (p[0] in prev and p[1] in prev)]
    ks = range(gpp if t == 3 else 2)
    return [(a, b, k) for k in ks for a, b in pairs]


def estimate(plan, P, tier1_size=None):
    tm = timing_info(P)
    ns = {t: len(tier_ids(plan, t)) for t in (1, 2, 3)}
    games = {1: ns[1] * (ns[1] - 1), 2: ns[2] * (ns[2] - 1) - ns[1] * (ns[1] - 1), 3: ns[3] * (ns[3] - 1) - ns[2] * (ns[2] - 1)}
    games[2] += 40
    games[3] += 40
    T = (tm or {}).get('mean') or 50.0
    wall = T / ((tm or {}).get('procs') or 4)
    sel_s = (tm or {}).get('select_mean') or 7.0
    lines = [f"見積り（1戦ワーカー時間 T={T:.1f}秒{'（実測）' if tm else '（既定）'}、実時間/戦 {wall:.1f}秒、選出 {sel_s:.1f}秒/回）"]
    tot = 0
    for t in (1, 2, 3):
        h = (games[t] * wall + games[t] * sel_s / 4 / 2) / 3600
        tot += h
        lines.append(f'  段階{t}: 構築{ns[t]} 増分{games[t]}戦 約{h:.1f}時間')
    lines.append(f'  合計 約{tot:.1f}時間')
    if games[1] * wall / 3600 > 5:
        lines.append(f'  警告: 第1段階が5時間を超える見込み。--tier1-size 20（210組・420戦）に縮小を検討')
    return lines


def cmd_plan(a):
    P = paths(a.out_dir)
    os.makedirs(P['dir'], exist_ok=True)
    raw = raw_teams()
    rts = []
    for t in raw:
        if len(t['team']) == 6 and all(B._base(m['name']) in POKE for m in t['team']):
            rts.append((rr_team(t), t))
    rts.sort(key=lambda x: sort_key(x[0]))
    orig = {rt['id']: t for rt, t in rts}
    rr = {rt['id']: rt for rt, _ in rts}
    order = [rt['id'] for rt, _ in rts]
    r11 = r11_team()
    rr['R11'] = r11
    sig = hashlib.sha256((json.dumps([rr[i] for i in order + ['R11']], ensure_ascii=False, sort_keys=True) + RR_VERSION).encode()).hexdigest()
    plan = None
    if os.path.exists(P['plan']):
        old = json.load(open(P['plan'], encoding='utf-8'))
        if old.get('sig') == sig:
            plan = old
        elif not a.force:
            raise SystemExit('rr_plan.json の sig が違います（--force で退避して作り直し）')
        else:
            os.replace(P['plan'], P['plan'][:-5] + time.strftime('.%Y%m%d_%H%M%S.json'))
    n1 = a.tier1_size
    tiers = {'1': order[:n1] + ['R11'], '2': order[:49] + ['R11'], '3': order + ['R11']}
    if getattr(a, 'test_ids', None):
        tiers['1'] = a.test_ids.split(',')
    if plan is None:
        plan = {'version': RR_VERSION, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'depth': list(DEPTH), 'sig': sig, 'order': order,
                'tiers': tiers, 'teams': {}, 'sel': {}, 'rematch': {}, 'timing': None}
    else:
        plan['tiers']['1'] = tiers['1']
    plan['max_tier'] = max(a.tier, plan.get('max_tier', 0))
    if len(plan['teams']) < len(rr):
        t0 = time.time()
        print(f'静的スコア計算（{len(rr)}構築、{a.procs}プロセス）...', flush=True)
        _rr_init_main(rr)
        with make_pool(a.procs, rr) as pool:
            ws = dict(pool.imap_unordered(_job_static, list(rr)))
        ov = json.load(open(GUIDE_OVERRIDES, encoding='utf-8')) if os.path.exists(GUIDE_OVERRIDES) else None
        _worker_init(rr)
        for i, rt in rr.items():
            info = build_candidates(rt, orig.get(i), ws[i], ov)
            plan['teams'][i] = {**rt, **info, 'static': ws[i]}
        print(f'  {time.time() - t0:.0f}秒', flush=True)
        save_plan(P, plan)
    if not a.no_select:
        cmd_select(P, plan, a.tier, a.procs)
    print(f"tier{a.tier}: 構築数 " + ' / '.join(f"{t}:{len(tier_ids(plan, int(t)))}" for t in ('1', '2', '3') if int(t) <= a.tier))
    nm = sum(len(main_keys(plan, t)) for t in range(1, a.tier + 1))
    print(f'本戦の鍵 {nm}（再戦は別）')
    for l in estimate(plan, P):
        print(l)
    return plan


def _rr_init_main(rr):
    global _TEAMS
    _TEAMS = rr
    _rr_init(rr)


def need_sel(plan, t_from, t_to):
    out = []
    for t in range(t_from, t_to + 1):
        for a, b, k in main_keys(plan, t):
            for x, y in ((a, b), (b, a)):
                if f'{x}|{y}' not in plan['sel'] and (x, y) not in out:
                    out.append((x, y))
    return out


def cmd_select(P, plan, tier, procs, pairs=None):
    pairs = pairs if pairs is not None else need_sel(plan, 1, tier)
    pairs = [p for p in pairs if f'{p[0]}|{p[1]}' not in plan['sel']]
    if not pairs:
        return
    print(f'選出の計算 {len(pairs)}組...', flush=True)
    t0 = time.time()
    with make_pool(procs, plan['teams']) as pool:
        for n, (k, r) in enumerate(pool.imap_unordered(_job_decide, pairs, chunksize=1), 1):
            if 'error' in r:
                print('  選出エラー', k, r['error'][-200:])
                continue
            plan['sel'][k] = r
            save_plan(P, plan)
            if n % 50 == 0:
                print(f'  [{n}/{len(pairs)}] {time.time() - t0:.0f}秒', flush=True)


# ---------------------------------------------------------------- run
def _wr(g, x):
    if g['res'] is None:
        return None
    if g['res'] == 0:
        return 0.5
    return 1.0 if g['winner'] == x else 0.0


def team_stats(plan, games, ids):
    ids = set(ids)
    st = {i: {'G': 0, 'W': 0.0, 'J': 0, 'JW': 0, 'hp': [], 'strong': [0, 0.0], 'src': collections.Counter(), 'sels': collections.Counter(), 'mega': 0, 'err': 0}
          for i in ids}
    for key, g in games['games'].items():
        if g.get('rematch'):
            continue
        if g['res'] is None:
            for x in (g['a'], g['b']):
                if x in st:
                    st[x]['err'] += 1
            continue
        for side, x in ((0, g['side0']), (1, g['side1'])):
            if x not in st:
                continue
            s = st[x]
            w = _wr(g, x)
            s['G'] += 1
            s['W'] += w
            if g.get('judged'):
                s['J'] += 1
                s['JW'] += w
            hp = [h for _, h in (g['left'] or [[], []])[side]] if g.get('left') else []
            s['hp'].append(0 if w == 0 else (sum(hp) / 3 if hp else 0))
            opp = g['side1'] if side == 0 else g['side0']
            if plan['teams'][opp]['weight'] >= 1.0:
                s['strong'][0] += 1
                s['strong'][1] += w
            sel = g['sel0'] if side == 0 else g['sel1']
            s['sels'][' / '.join(sel)] += 1
            tm = plan['teams'][x]
            mg = {m['base'] for m in tm['mons'] if m['mega']}
            if set(sel) & mg:
                s['mega'] += 1
            ss = plan['sel'].get(f'{x}|{opp}')
            if ss:
                s['src'][ss['src']] += 1
    return st


def h2h(games, x, y):
    w = n = 0.0
    for g in games['games'].values():
        if g['res'] is None or {g['side0'], g['side1']} != {x, y}:
            continue
        n += 1
        w += _wr(g, x)
    return (w / n) if n else None


def ranking(plan, games, ids):
    import functools
    st = team_stats(plan, games, ids)

    def wr(i):
        return st[i]['W'] / st[i]['G'] if st[i]['G'] else 0.0

    def hp(i):
        return sum(st[i]['hp']) / len(st[i]['hp']) if st[i]['hp'] else 0.0

    def cmp(x, y):
        if abs(wr(x) - wr(y)) > 1e-9:
            return -1 if wr(x) > wr(y) else 1
        h = h2h(games, x, y)
        if h is not None and abs(h - 0.5) > 1e-9:
            return -1 if h > 0.5 else 1
        if abs(hp(x) - hp(y)) > 1e-9:
            return -1 if hp(x) > hp(y) else 1
        return -1 if x < y else (1 if x > y else 0)
    return sorted(ids, key=functools.cmp_to_key(cmp)), st


def done_game(games, key, retry):
    g = games['games'].get(key)
    return bool(g) and (g['res'] is not None or not retry)


def run_batch(P, plan, games, items, procs, t_start, tot_all, base_done, retry=False):
    """items: [(a, b, k, rematch)]。選出が未計算なら先に計算してから戦う。"""
    if not items:
        return 0
    need = []
    for a, b, k, rm in items:
        for x, y in ((a, b), (b, a)):
            if f'{x}|{y}' not in plan['sel']:
                need.append((x, y))
    cmd_select(P, plan, 0, procs, list(dict.fromkeys(need)))
    jobs = []
    for a, b, k, rm in items:
        X, Y = game_sides(a, b, k)
        jobs.append((game_key(a, b, k), X, Y, plan['sel'][f'{X}|{Y}']['order'], plan['sel'][f'{Y}|{X}']['order'], game_seed(a, b, k)))
    meta = {j[0]: (j, items[n][3]) for n, j in enumerate(jobs)}
    n = 0
    with make_pool(procs, plan['teams']) as pool:
        for r in pool.imap_unordered(_job_game, jobs, chunksize=1):
            n += 1
            job, rm = meta[r['key']]
            games['games'][r['key']] = game_record(job, r, rm)
            save_games(P, games)
            if r.get('log') is not None:
                append_log(P, r['key'], r['log'])
            mark = '例外' if r.get('res') is None else ('勝' if r['res'] == 1 else '負')
            print(f"[{base_done + n}/{tot_all}] {r['key']} {job[1]}側{mark} {r.get('turns')}手 {r['sec']:.0f}秒 {(time.time() - t_start) / 60:.1f}分", flush=True)
    return n


def cmd_run(a):
    P = paths(a.out_dir)
    plan = load_plan(P)
    games = load_games(P, plan['sig'])
    t_start = time.time()
    budget = a.max_games if a.max_games else 10 ** 9
    maxt = plan.get('max_tier', 1)
    total_main = sum(len(main_keys(plan, t, a.games_per_pair)) for t in range(1, maxt + 1))
    done_total = 0
    for t in range(1, maxt + 1):
        keys = main_keys(plan, t, a.games_per_pair)
        pend = [(x, y, k, False) for x, y, k in keys if not done_game(games, game_key(x, y, k), not a.retry_errors)]
        done_total += len(keys) - len(pend)
        pend = pend[:budget]
        if pend:
            n = run_batch(P, plan, games, pend, a.procs, t_start, total_main, done_total, a.retry_errors)
            budget -= n
            done_total += n
        if budget <= 0:
            break
        if t >= 2 and all(done_game(games, game_key(x, y, k), True) for x, y, k in keys) and all(
                done_game(games, game_key(x, y, k), True) for tt in range(1, t) for x, y, k in main_keys(plan, tt, a.games_per_pair)):
            if str(t) not in plan['rematch']:
                rk, _ = ranking(plan, games, tier_ids(plan, t))
                top = rk[:5]
                plan['rematch'][str(t)] = [list(pair_ab(x, y)) for x, y in itertools.combinations(top, 2)]
                save_plan(P, plan)
            rm = [(x, y, k, True) for x, y in plan['rematch'][str(t)] for k in (2, 3, 4, 5)
                  if not done_game(games, game_key(x, y, k), not a.retry_errors)]
            rm = rm[:budget]
            if rm:
                n = run_batch(P, plan, games, rm, a.procs, t_start, total_main, done_total, a.retry_errors)
                budget -= n
        if budget <= 0:
            break
    print(f'完了 {(time.time() - t_start) / 60:.1f}分')


# ---------------------------------------------------------------- report
def wilson(w, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def cmd_report(a):
    P = paths(a.out_dir)
    plan = load_plan(P)
    games = load_games(P, plan['sig'])
    maxt = plan.get('max_tier', 1)
    ids = sorted({x for g in games['games'].values() for x in (g['side0'], g['side1'])}, key=lambda i: plan['order'].index(i) if i in plan['order'] else 10 ** 6)
    if not ids:
        ids = tier_ids(plan, 1)
    rk, st = ranking(plan, games, ids)
    tm = timing_info(P)
    gs = list(games['games'].values())
    L = ['# 上位構築の総当たり（4手読み同士のブラインド戦）', '']
    L += ['## 1. 条件', '', '- 両者4手読み、相手の6体だけを見て選出（相手の記事の型は使わない）。型の推測は使用率・他の記事・見えた技から。',
          '- 選出: 記事の選出 → ガイドの条件項目 → ガイドの基本項目 → 基本の選出（候補24通り）。',
          '- 種 = crc32("rr{a}{b}{k}")、1組2戦（左右入れ替え）。30ターンで決着しない場合は評価値の符号で判定。',
          f"- 対象と段階: 第1段階 {len(tier_ids(plan, 1))}構築、第2段階 {len(tier_ids(plan, 2))}、第3段階 {len(tier_ids(plan, 3))}（R11は全段階）"]
    for t in range(1, 4):
        ks = main_keys(plan, t)
        d = sum(1 for x, y, k in ks if done_game(games, game_key(x, y, k), True))
        L.append(f'- 段階{t}の本戦（増分）: {d}/{len(ks)}' + ('（未計画）' if t > maxt else ''))
    if tm:
        L.append(f"- 実測: 1戦のワーカー時間 中央値{tm.get('median', 0):.0f}秒・平均{tm.get('mean', 0):.0f}秒、実時間/戦 {tm.get('wall_per_game', 0):.1f}秒")
    L += ['', '## 2. 順位表', '', '| 順位 | 構築 | rank | 勝率 | 95%区間 | 判定(勝/数) | 平均残HP | 強い相手への勝率 | 選出の出どころ |', '|---|---|---|---|---|---|---|---|---|']
    for n, i in enumerate(rk, 1):
        s, t = st[i], plan['teams'][i]
        G = s['G']
        lo, hi = wilson(s['W'], G)
        sr = f"{s['strong'][1] / s['strong'][0] * 100:.0f}%" if s['strong'][0] else '-'
        src = ' '.join(f'{k}{v * 100 // max(1, sum(s["src"].values()))}%' for k, v in s['src'].most_common())
        L.append(f"| {n} | {t['title'][:28]}({i[:8]}) | {t['rank'] or ('R' if i == 'R11' else '-')} | {s['W']:g}/{G}={s['W'] / G * 100 if G else 0:.1f}% | {lo * 100:.0f}-{hi * 100:.0f}% | "
                 f"{s['JW']:g}/{s['J']} | {sum(s['hp']) / len(s['hp']) if s['hp'] else 0:.0f}% | {sr} | {src} |")
    if 'R11' in st:
        i = 'R11'
        L += ['', '## 3. R11', '', f"順位 {rk.index(i) + 1}/{len(rk)}  勝率 {st[i]['W']:g}/{st[i]['G']}"]
        good, bad = [], []
        for o in ids:
            if o == i:
                continue
            ws = [_wr(g, i) for g in gs if g['res'] is not None and not g.get('rematch') and {g['side0'], g['side1']} == {i, o}]
            if len(ws) == 2 and sum(ws) == 2:
                good.append(o)
            elif len(ws) == 2 and sum(ws) == 0:
                bad.append(o)
        L.append('- 得意（2戦2勝）: ' + ', '.join(f"{plan['teams'][o]['title'][:16]}({o[:6]})" for o in good))
        L.append('- 苦手（2戦0勝）: ' + ', '.join(f"{plan['teams'][o]['title'][:16]}({o[:6]})" for o in bad))
        L.append('- 選出の分布: ' + ', '.join(f'{k}×{v}' for k, v in st[i]['sels'].most_common(8)))
    t1 = tier_ids(plan, 1)
    L += ['', '## 4. 勝敗行列（第1段階、行の構築視点の勝数/戦数）', '', '| | ' + ' | '.join(x[:4] for x in t1) + ' |', '|' + '---|' * (len(t1) + 1)]
    M = collections.defaultdict(lambda: [0.0, 0])
    for g in gs:
        if g['res'] is None or g.get('rematch'):
            continue
        for x, y in ((g['side0'], g['side1']), (g['side1'], g['side0'])):
            M[(x, y)][0] += _wr(g, x)
            M[(x, y)][1] += 1
    for x in t1:
        L.append(f'| {x[:4]} | ' + ' | '.join('-' if x == y or not M[(x, y)][1] else f'{M[(x, y)][0]:g}/{M[(x, y)][1]}' for y in t1) + ' |')
    with open(P['csv'], 'w', encoding='utf-8') as f:
        f.write('id,' + ','.join(ids) + '\n')
        for x in ids:
            f.write(x + ',' + ','.join('' if x == y or not M[(x, y)][1] else f'{M[(x, y)][0]:g}/{M[(x, y)][1]}' for y in ids) + '\n')
    L += ['', '## 5. 選出の分布', '']
    for i in rk:
        s = st[i]
        tot = max(1, sum(s['src'].values()))
        L.append(f"- {plan['teams'][i]['title'][:24]}({i[:6]}): 区分{plan['teams'][i]['gclass']} " + ' '.join(f'{k}{v * 100 // tot}%' for k, v in s['src'].most_common()) +
                 f" メガ入り{s['mega'] * 100 // max(1, s['G'])}% 上位: " + ', '.join(f'{k}({v})' for k, v in s['sels'].most_common(3)))
    L += ['', '## 6. 再戦表', '']
    for t, prs in sorted(plan['rematch'].items()):
        L.append(f'段階{t}（上位5）')
        for x, y in prs:
            ws = [(g['k'], g['winner']) for g in gs if {g['a'], g['b']} == {x, y} and g['res'] is not None]
            L.append(f"- {x[:6]} vs {y[:6]}: {x[:6]}の勝 {sum(1 for _, w in ws if w == x)}/{len(ws)}")
    L += ['', '## 7. 判定決着・例外', '']
    L.append(f"- 判定決着 {sum(1 for g in gs if g.get('judged'))}戦、例外 {sum(1 for g in gs if g['res'] is None)}戦")
    for g in gs:
        if g['res'] is None:
            L.append(f"  - 例外 {g['a'][:6]}|{g['b'][:6]}|{g['k']}: {str(g.get('error'))[-120:]}")
    L.append('- 評価値0で side 1 勝ちになった件数は blind_play の戻り値からは分からない（判定決着の中に含まれる）')
    L += ['', '## 8. ガイド判定不能一覧と除外された選出', '']
    for i in plan['order'] + ['R11']:
        t = plan['teams'][i]
        for u in t['unreadable']:
            L.append(f"- {i[:8]} when「{u['when']}」pick{u['pick']}: {u['why']}")
        for r in t['rejected']:
            L.append(f"- {i[:8]} 除外 {r['order']}: {r['why']}（{r.get('when', '')}）")
    L += ['', '## 9. 誤差の注意', '',
          '- 第1段階は1構築48戦で95%区間の幅が約±14ポイント、第3段階は166戦で約±7.6ポイント。区間が重なる順位差は確かでない。',
          '- 選出は組ごとに固定なので、結果は「その選出どうしの相性＋乱数」。型の推測は使用率データに依る。ガイドの読み取りは機械的で誤りうる。']
    os.makedirs(os.path.dirname(P['md']), exist_ok=True)
    open(P['md'], 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print(f"書きました: {P['md']} （{len(gs)}戦）")


def cmd_show(a):
    plan = load_plan(paths(a.out_dir))
    i = next((k for k in plan['teams'] if k.startswith(a.id)), None)
    if not i:
        raise SystemExit('見つかりません')
    t = plan['teams'][i]
    print(i, t['title'], '区分', t['gclass'], 'メガ', t['n_mega'], '候補', t['n_cand'])
    for n, o in enumerate(t['candidates'], 1):
        print(f'  {n:2d} {" / ".join(o)}')
    for u in t['unreadable']:
        print('  読めない:', u)
    for r in t['rejected']:
        print('  除外:', r)


# ---------------------------------------------------------------- selftest
def sha_files():
    pats = []
    D = os.path.join(HERE, 'data')
    for f in ('known_teams.json', 'new_teams_m6b.json', 'select_rules.json', 'article_sets.json'):
        pats.append(os.path.join(D, f))
    for root in (os.path.join(D, 'party'),):
        pats += [os.path.join(root, f) for f in os.listdir(root) if f.endswith('.json')]
    lg = os.path.join(HERE, '..', 'logs')
    for root, _, fs in os.walk(os.path.join(lg, 'refine')):
        pats += [os.path.join(root, f) for f in fs if f.endswith('.json') and not f.startswith('rr_')]
    pats += [os.path.join(lg, f) for f in os.listdir(lg) if f.endswith('.md') and f != 'ROUNDROBIN.md']
    return {p: hashlib.sha256(open(p, 'rb').read()).hexdigest() for p in sorted(pats) if os.path.exists(p)}


def cmd_selftest(a):
    import shutil, subprocess, tempfile, copy
    keep = bool(a.out_dir)
    D = a.out_dir or tempfile.mkdtemp(prefix='rrtest_')
    os.makedirs(D, exist_ok=True)
    results = []

    def ok(n, cond, msg=''):
        results.append((n, bool(cond)))
        print(f"{'○' if cond else '×'} {n} {msg}", flush=True)

    before = sha_files()
    # 1
    p = subprocess.run([sys.executable, '-m', 'py_compile', 'roundrobin.py', 'refine.py'], cwd=HERE, capture_output=True, text=True)
    ok('1 py_compile', p.returncode == 0, p.stderr[-200:])
    # 10 (先に: refine.apply_party が B.TEAM の元の種族を覚えるため)
    try:
        import sets as _sets
        party = R.party_now()
        kt = B.KNOWN_TEAMS[0]
        my = [B.BASE_OF.get(m['species'], m['species']) for m in party[:3]]
        r = R.blind_play((party, kt['id'], my, [B._base(m['name']) for m in kt['team'][:3]], 1, 3, 3))
        ok('10 後方互換(7要素)', r.get('res') is not None and _sets.EXCLUDE == {kt['id']}, f"res={r.get('res')} EXCLUDE={_sets.EXCLUDE}")
    except Exception:
        ok('10 後方互換(7要素)', False, traceback.format_exc()[-300:])
    # plan
    class A_:
        pass
    pa = A_()
    pa.out_dir, pa.tier, pa.tier1_size, pa.no_select, pa.procs, pa.force, pa.test_ids = os.path.join(D, 'main'), 1, 24, True, a.procs, True, None
    print('plan 作成（静的スコアを含む。数分）...', flush=True)
    plan = cmd_plan(pa)
    T = plan['teams']
    rr = {i: {k: v for k, v in t.items()} for i, t in T.items()}
    _worker_init(T)
    # 2
    bad, n_stone, n_stone_ok = [], 0, 0
    ids = list(T)
    for n, i in enumerate(ids):
        try:
            rr_apply(T[i])
            j = ids[(n + 1) % len(ids)]
            B._KNOWN_CTX['team'] = None
            R._ctx(j)
            B.engine_game(T[i]['candidates'][0], T[j]['candidates'][0])
            for m in [x for x in T[i]['mons'] if x.get('stone')]:
                others = [x['base'] for x in T[i]['mons'] if not x['mega']][:2]
                if len(others) < 2:
                    continue
                n_stone += 1
                order = [m['base']] + others
                B._KNOWN_CTX['team'] = None
                R._ctx(i)
                st2 = B.engine_game(order, order)
                s0 = next(mon for mon in st2.sides[0].mons if B._base(mon.name) == m['base'])
                s1 = next(mon for mon in st2.sides[1].mons if B._base(mon.name) == m['base'])
                if s0.can_mega and s1.can_mega:
                    n_stone_ok += 1
        except Exception as e:
            bad.append((i[:8], repr(e)[:80]))
    ok('2 全構築が適用・engine_game', not bad, f'失敗{bad[:3]}')
    ok('2 ストーン持ち(名前がメガでない)が両側で can_mega', n_stone == n_stone_ok and n_stone > 0, f'{n_stone_ok}/{n_stone}')
    ok('2 teams() を置換後に呼んでいない', {t['id'] for t in B.KNOWN_TEAMS} == set(T), f'{len(B.KNOWN_TEAMS)}')
    # 3
    errs = []
    for i, t in T.items():
        c = [tuple(o) for o in t['candidates']]
        bases = [m['base'] for m in t['mons']]
        mg = {m['base'] for m in t['mons'] if m['mega']}
        nm = len(mg)
        n0 = sum(1 for o in c if not set(o) & mg)
        n1 = sum(1 for o in c if len(set(o) & mg) == 1)
        if len(c) > 24: errs.append((i[:6], 'n>24'))
        if len(set(c)) != len(c): errs.append((i[:6], 'dup'))
        if any(not set(o) <= set(bases) or len(set(o)) != 3 for o in c): errs.append((i[:6], 'mon'))
        if any(len(set(o) & mg) >= 2 for o in c): errs.append((i[:6], 'mega2'))
        if n0 > (3 if nm == 3 else 4) and nm: errs.append((i[:6], f'n0={n0}'))
        if nm >= 1 and n1 < 20: errs.append((i[:6], f'n1={n1}'))
        for it in t['gitems']:
            if it['full'] and tuple(it['orders'][0]) not in c and not any(r['order'] == it['orders'][0] for r in t['rejected']):
                errs.append((i[:6], 'guide missing'))
    ok('3 候補の制約', not errs, str(errs[:4]))
    ncand = collections.Counter(t['n_cand'] for t in T.values())
    print('   候補数の分布', dict(ncand))
    # 5
    cnt = collections.Counter(t['gclass'] for t in T.values())
    nun = sum(len(t['unreadable']) for t in T.values())
    ncomp = sum(1 for t in T.values() for it in t['gitems'] if it['full'])
    npart = sum(1 for t in T.values() for it in t['gitems'] if not it['full'])
    print('5 ガイド区分', dict(cnt), f'完全{ncomp} 部分{npart} 読めなかった{nun} (目安: 完全121 部分131 使えない54)')
    results.append(('5 ガイド区分表', True))
    # 4
    none_ids = [i for i, t in T.items() if t['gclass'] == 'none']
    fails = []
    oppn = none_ids[0] if none_ids else ids[0]
    for i, t in T.items():
        if t['gclass'] == 'guide-fixed':
            r = decide_pair(i, oppn if oppn != i else ids[1])
            b = next(x for x in t['gitems'] if x['kind'] == 'basic' and x.get('usable', True))
            if not (r['src'] == 'guide-basic' and r['order'] == b['orders'][0]):
                fails.append(('a', i[:6], r['src'], r['fallback']))
    ok('4a guide-fixed → guide-basic', not [f for f in fails if f[0] == 'a'], str(fails[:3]))
    nb, tested = 0, 0
    for i, t in T.items():
        if tested >= 5: break
        if t['gclass'] != 'guide-cond': continue
        its = [x for x in t['gitems'] if x['kind'] == 'cond' and x.get('usable', True)]
        opp = next((j for j in ids if j != i and any(holds(x['groups'], [m['base'] for m in T[j]['mons']]) for x in its)), None)
        if not opp:
            print('   4b 飛ばす（条件を満たす相手なし）', i[:6]); continue
        tested += 1
        b6 = [m['base'] for m in T[opp]['mons']]
        it = next(x for x in its if holds(x['groups'], b6))
        r = decide_pair(i, opp)
        good = r['src'] == 'guide-cond' and tuple(r['order']) in {tuple(o) for o in it['orders']}
        if not good:
            nb += 1
            print('   4b NG', i[:6], r['src'], r['order'], it['when'], r['fallback'])
    ok('4b guide-cond → guide-cond', nb == 0 and tested > 0, f'{tested}件')
    na, tested = 0, 0
    for i, t in T.items():
        if tested >= 4: break
        if t['gclass'] != 'article': continue
        tested += 1
        opp = ids[0] if ids[0] != i else ids[1]
        r = decide_pair(i, opp)
        if not (r['src'] == 'article' and tuple(r['order']) in {tuple(o) for o in t['article_orders']}):
            na += 1
            print('   4c NG', i[:6], r['src'], r['order'])
    ok('4c article', na == 0 and tested > 0, f'{tested}件')
    nd, tested = 0, 0
    for i in none_ids[:4]:
        tested += 1
        r = decide_pair(i, ids[0] if ids[0] != i else ids[1])
        if r['src'] != 'basic' or tuple(r['order']) not in {tuple(o) for o in T[i]['candidates']}:
            nd += 1
    ok('4d none → basic', nd == 0, f'{tested}件')
    # 6 鏡合わせ
    n6 = 2 if a.quick else 8
    top3 = [i for i in plan['tiers']['1'] if i != 'R11'][:3]
    jobs = []
    for i in top3:
        s = decide_pair(i, i)
        for k in range(n6):
            jobs.append((f'{i}|{i}|m{k}', i, i, s['order'], s['order'], zlib.crc32(f'rrmirror{i}{k}'.encode())))
    t0 = time.time()
    with make_pool(a.procs, T) as pool:
        out6 = pool.map(_job_game, jobs, chunksize=1)
    w0 = sum(1 for r in out6 if r.get('res') == 1)
    e6 = sum(1 for r in out6 if r.get('res') is None)
    rate = w0 / len(out6)
    ok('6 鏡合わせ', e6 == 0 and 0.25 <= rate <= 0.75, f'side0勝率 {w0}/{len(out6)}={rate * 100:.0f}% 例外{e6} {time.time() - t0:.0f}秒')
    # 7 再開
    rdir = os.path.join(D, 'resume')
    os.makedirs(rdir, exist_ok=True)
    p7 = copy.deepcopy(plan)
    p7['tiers']['1'] = top3
    p7['max_tier'] = 1
    P7 = paths(rdir)
    save_plan(P7, p7)
    cmd_select(P7, p7, 1, a.procs)
    ra = A_()
    ra.out_dir, ra.max_games, ra.procs, ra.retry_errors, ra.games_per_pair = rdir, 2, a.procs, False, 2
    cmd_run(ra)
    g1 = set(json.load(open(P7['games'], encoding='utf-8'))['games'])
    open(P7['games'] + '.tmp', 'w').write('{broken')
    with open(P7['logs'], 'a') as f:
        f.write('{"key": "x", "log": [')
    cmd_run(ra)
    g2 = set(json.load(open(P7['games'], encoding='utf-8'))['games'])
    lg = read_jsonl(P7['logs'])
    ok('7 再開', len(g1) == 2 and len(g2) == 4 and g1 < g2 and all('key' in x for x in lg), f'{len(g1)}→{len(g2)} ログ{len(lg)}行')
    # 8 再現性
    k8 = sorted(g1)[0]
    gg = json.load(open(P7['games'], encoding='utf-8'))['games'][k8]
    job = (k8, gg['side0'], gg['side1'], gg['sel0'], gg['sel1'], game_seed(gg['a'], gg['b'], gg['k']))
    with make_pool(2, T) as pool:
        r8 = pool.map(_job_game, [job, job], chunksize=1)
    jj = lambda v: json.loads(json.dumps(v))
    same = all(jj(r8[0].get(x)) == jj(r8[1].get(x)) == gg.get(x) for x in ('res', 'turns', 'left'))
    ok('8 再現性', same and gg['seed'] == zlib.crc32(f"rr{gg['a']}{gg['b']}{gg['k']}".encode()), f"res={r8[0].get('res')}/{r8[1].get('res')}/{gg['res']}")
    # 11 所要時間
    n11 = 2 if a.quick else 8
    t1 = [i for i in plan['tiers']['1']]
    prs = circle_pairs(t1)[:n11]
    need = list(dict.fromkeys([(x, y) for a_, b_ in prs for x, y in ((a_, b_), (b_, a_))]))
    with make_pool(a.procs, T) as pool:
        sels = dict(pool.map(_job_decide, need, chunksize=1))
    jobs = []
    for x, y in prs:
        X, Y = game_sides(x, y, 0)
        jobs.append((game_key(x, y, 0), X, Y, sels[f'{X}|{Y}']['order'], sels[f'{Y}|{X}']['order'], game_seed(x, y, 0)))
    t0 = time.time()
    with make_pool(a.procs, T) as pool:
        out11 = pool.map(_job_game, jobs, chunksize=1)
    wall = (time.time() - t0) / len(jobs)
    secs = [r['sec'] for r in out11]
    with make_pool(1, T) as pool:
        ssec = [r['sec'] for r in pool.map(_job_select, [(x, y, T[x]['candidates']) for x, y in circle_pairs(t1)[-3:]], chunksize=1)]
    tmj = {'game_sec': secs, 'median': statistics.median(secs), 'mean': statistics.mean(secs), 'wall_per_game': wall,
           'select_sec': ssec, 'select_mean': statistics.mean(ssec), 'procs': a.procs, 'errors': sum(1 for r in out11 if r.get('res') is None)}
    safeio.write_json(paths(D)['timing'], tmj, indent=1)
    safeio.write_json(paths(os.path.join(D, 'main'))['timing'], tmj, indent=1)
    ok('11 所要時間の実測', tmj['errors'] == 0, f"1戦ワーカー 中央値{tmj['median']:.0f}秒 平均{tmj['mean']:.0f}秒 実時間/戦 {wall:.1f}秒 選出{[round(x, 1) for x in ssec]}秒")
    print('\n'.join(estimate(plan, paths(os.path.join(D, 'main')))))
    # 9
    after = sha_files()
    ok('9 既存ファイル sha256 不変', before == after, f'{len(before)}ファイル')
    print('\n結果:', 'すべて ○' if all(c for _, c in results) else '×あり: ' + ', '.join(n for n, c in results if not c))
    if not keep:
        shutil.rmtree(D, ignore_errors=True)


# ---------------------------------------------------------------- deny モード (SPEC_DENY.md)
def deny_paths(out_dir=None):
    d = out_dir or DEF_OUT
    return {'dir': d, 'games': os.path.join(d, 'rr_deny_games.json'), 'logs': os.path.join(d, 'rr_deny_logs.jsonl'),
            'md': os.path.join(d, 'rr_deny_report.md')}


def _job_deny(a):
    key, X, Y, selX, selY, seed, deny = a
    t0 = time.time()
    try:
        rr_apply(_TEAMS[X])
        r = R.blind_play((None, Y, selX, selY, seed, DEPTH[0], DEPTH[1], False, None, False, (X,), deny))
    except Exception:
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    r['key'] = key
    r['sec'] = round(time.time() - t0, 2)
    return r


def deny_record(job, r):
    key, X, Y, selX, selY, seed, deny = job
    a, b, k = key.split(':', 1)[1].split('|')[-3:]
    res = r.get('res')
    w = None if res is None else (X if res == 1 else (Y if res == -1 else None))
    rec = {'a': a, 'b': b, 'k': int(k), 'side0': X, 'side1': Y, 'sel0': selX, 'sel1': selY, 'seed': seed, 'res': res, 'winner': w,
           'judged': r.get('judged'), 'turns': r.get('turns'), 'left': r.get('left'), 'faints': r.get('faints'),
           'sec': r.get('sec'), 'error': r.get('error'), 'rematch': False, 'deny': list(deny)}
    if r.get('deny_stats') is not None:
        rec['deny_stats'] = r['deny_stats']
    return rec


def load_dgames(PD, sig):
    if os.path.exists(PD['games']):
        g = json.load(open(PD['games'], encoding='utf-8'))
        if g.get('plan_sig') != sig:
            raise SystemExit('rr_deny_games.json の plan_sig が rr_plan.json と違います')
        return g
    return {'version': RR_VERSION, 'plan_sig': sig, 'depth': list(DEPTH), 'mode': 'deny', 'games': {}}


def _mk_job(plan, key, a, b, k, deny):
    X, Y = game_sides(a, b, k)
    if f'{X}|{Y}' not in plan['sel'] or f'{Y}|{X}' not in plan['sel']:
        raise SystemExit(f'rr_plan.json に選出がありません: {X}|{Y}')
    return (key, X, Y, plan['sel'][f'{X}|{Y}']['order'], plan['sel'][f'{Y}|{X}']['order'], game_seed(a, b, k), tuple(deny))


TOP2 = ('bab22dcc629688e8', '096193444e19a2f0')


def deny_jobs_full(plan):
    pairs = circle_pairs(tier_ids(plan, 1))
    return [_mk_job(plan, f'full:{a}|{b}|{k}', a, b, k, (True, True)) for k in range(6) for a, b in pairs]


def deny_jobs_r11(plan):
    out = []
    for o in tier_ids(plan, 1):
        if o == 'R11':
            continue
        a, b = pair_ab('R11', o)
        for k in (0, 1):
            X, Y = game_sides(a, b, k)
            out.append(_mk_job(plan, f'deny:R11|{a}|{b}|{k}', a, b, k, (X == 'R11', Y == 'R11')))
    return out


def deny_jobs_top2(plan):
    A, Bn = TOP2
    a, b = pair_ab(A, Bn)
    out = []
    for k in range(10):
        X, Y = game_sides(a, b, k)
        out.append(_mk_job(plan, f'deny:{A}|{a}|{b}|{k}', a, b, k, (X == A, Y == A)))
        out.append(_mk_job(plan, f'deny:{Bn}|{a}|{b}|{k}', a, b, k, (X == Bn, Y == Bn)))
        if k >= 6:
            out.append(_mk_job(plan, f'base:{a}|{b}|{k}', a, b, k, (False, False)))
    return out


def run_deny_jobs(PD, plan, games, jobs, procs, retry, max_games, label=''):
    todo = [j for j in jobs if not done_game(games, j[0], not retry)]
    tot = len(jobs)
    base = tot - len(todo)
    if max_games:
        todo = todo[:max_games]
    print(f'{label}全体 {tot}戦、済み {base}、今回 {len(todo)}戦', flush=True)
    if not todo:
        return 0
    os.makedirs(PD['dir'], exist_ok=True)
    t0 = time.time()
    n = 0
    with make_pool(procs, plan['teams']) as pool:
        for r in pool.imap_unordered(_job_deny, todo, chunksize=1):
            n += 1
            job = next(j for j in todo if j[0] == r['key'])
            games['games'][r['key']] = deny_record(job, r)
            safeio.write_json(PD['games'], games)
            if r.get('log') is not None:
                lg = {'logs': PD['logs']}
                append_log(lg, r['key'], r['log'])
            mark = '例外' if r.get('res') is None else ('勝' if r['res'] == 1 else '負')
            el = (time.time() - t0) / 60
            rem = el / n * (len(todo) - n)
            print(f"[{base + n}/{tot}] {r['key']} {job[1][:8]}側{mark} {r.get('turns')}手 {r['sec']:.0f}秒 経過{el:.1f}分 残り約{rem:.1f}分", flush=True)
    return n


def cmd_deny_run(a, full=False):
    plan = load_plan(paths(None))
    PD = deny_paths(a.out_dir)
    games = load_dgames(PD, plan['sig'])
    if full:
        run_deny_jobs(PD, plan, games, deny_jobs_full(plan), a.procs, a.retry_errors, a.max_games, 'full ')
        return
    jobs = []
    if a.part in ('r11', 'all'):
        jobs += deny_jobs_r11(plan)
    if a.part in ('top2', 'all'):
        jobs += deny_jobs_top2(plan)
    run_deny_jobs(PD, plan, games, jobs, a.procs, a.retry_errors, a.max_games)


def _binom_p(b, c):
    n = b + c
    if n == 0:
        return 1.0
    m = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, x) for x in range(m + 1)) / 2 ** n)


def _avg(l):
    l = [x for x in l if x is not None]
    return sum(l) / len(l) if l else 0.0


def cmd_deny_report(a):
    P0 = paths(None)
    plan = load_plan(P0)
    base = load_games(P0, plan['sig'])
    PD = deny_paths(a.out_dir)
    dg = load_dgames(PD, plan['sig'])['games']
    ids1 = tier_ids(plan, 1)
    ttl = lambda i: f"{plan['teams'][i]['title'][:16]}({i[:6]})"
    L = ['# deny モード（相手の勝ち筋を潰す読み）の結果', '', f'- 条件: 4手読み・rr_plan.json の選出・種規則は本戦と同じ。deny 結果 {len(dg)}戦（{PD["games"]}）', '']
    # --- 順位比較
    full = {k: v for k, v in dg.items() if k.startswith('full:')}
    nbase = {k: v for k, v in base['games'].items() if not v.get('rematch') and v['side0'] in ids1 and v['side1'] in ids1}
    if full:
        rk0, st0 = ranking(plan, {'games': nbase}, ids1)
        rk1, st1 = ranking(plan, {'games': full}, ids1)
        L += ['## 通常 対 deny（第1段階・両側 deny）', '', '| 構築 | 通常 勝率 | 通常 順位 | deny 勝率 | deny 順位 | 順位差 | deny 95% | 判定(通常/deny) | 平均ターン(通常/deny) |', '|---|---|---|---|---|---|---|---|---|']
        trn = lambda gs, x: _avg([g['turns'] for g in gs.values() if g['res'] is not None and x in (g['side0'], g['side1'])])
        moved = []
        for n1, i in enumerate(rk1, 1):
            n0 = rk0.index(i) + 1
            s0, s1 = st0[i], st1[i]
            lo, hi = wilson(s1['W'], s1['G'])
            L.append(f"| {ttl(i)} | {s0['W']:g}/{s0['G']}={s0['W'] / max(1, s0['G']) * 100:.1f}% | {n0} | {s1['W']:g}/{s1['G']}={s1['W'] / max(1, s1['G']) * 100:.1f}% | {n1} | {n0 - n1:+d} | "
                     f"{lo * 100:.0f}-{hi * 100:.0f}% | {s0['J']}/{s1['J']} | {trn(nbase, i):.1f}/{trn(full, i):.1f} |")
            if abs(n0 - n1) >= 5:
                moved.append(f'{ttl(i)} {n0}位→{n1}位')
        L += ['', f"- R11 の順位: 通常 {rk0.index('R11') + 1}位 → deny {rk1.index('R11') + 1}位（/{len(ids1)}）" if 'R11' in ids1 else '- R11 は第1段階に無い']
        jn = sum(1 for g in nbase.values() if g.get('judged'))
        jd = sum(1 for g in full.values() if g.get('judged'))
        L.append(f"- 判定決着: 通常 {jn}/{len(nbase)}、deny {jd}/{len(full)}。平均ターン: 通常 {_avg([g['turns'] for g in nbase.values() if g['res'] is not None]):.1f}、deny {_avg([g['turns'] for g in full.values() if g['res'] is not None]):.1f}")
        L.append('- 順位が5以上動いた構築: ' + ('、'.join(moved) if moved else 'なし'))
        f01 = {k: v for k, v in full.items() if v['k'] in (0, 1)}
        L += ['', '### k=0,1 だけの勝率（同じ種どうし）', '', '| 構築 | 通常 | deny(k=0,1) |', '|---|---|---|']
        for i in rk1:
            s0 = st0[i]
            s1 = team_stats(plan, {'games': f01}, [i])[i]
            L.append(f"| {ttl(i)} | {s0['W']:g}/{s0['G']} | {s1['W']:g}/{s1['G']} |")
        L += ['', '- 注記: 通常は1ペア2戦、deny は6戦で戦数が違う。順位差は区間の幅を見て読むこと。', '']
    # --- r11
    r11 = {k: v for k, v in dg.items() if k.startswith('deny:R11|')}
    if r11:
        rows = []
        for k, g in r11.items():
            nk = k.split(':', 1)[1].split('|', 1)[1]
            n = base['games'].get(nk)
            if n and g['res'] is not None and n['res'] is not None:
                rows.append((g, n))
        wn = sum(_wr(n, 'R11') for _, n in rows)
        wd = sum(_wr(g, 'R11') for g, _ in rows)
        N = len(rows)
        lo, hi = wilson(wd, N)
        L += ['## A/B 1: R11 が deny（対 他24構築 × k=0,1）', '',
              f'- 通常 {wn:g}/{N}、deny {wd:g}/{N}（deny の Wilson 95%: {lo * 100:.0f}-{hi * 100:.0f}%）',
              f"- 判定決着 通常/deny: {sum(1 for _, n in rows if n.get('judged'))}/{sum(1 for g, _ in rows if g.get('judged'))}、平均ターン {_avg([n['turns'] for _, n in rows]):.1f}/{_avg([g['turns'] for g, _ in rows]):.1f}、平均秒 {_avg([n['sec'] for _, n in rows]):.1f}/{_avg([g['sec'] for g, _ in rows]):.1f}"]
        flips, up, dn = [], 0, 0
        per = collections.defaultdict(lambda: [0, 0])
        for g, n in rows:
            o = g['a'] if g['b'] == 'R11' else g['b']
            x, y = _wr(n, 'R11'), _wr(g, 'R11')
            per[o][0] += x
            per[o][1] += y
            if x != y:
                flips.append(f"{ttl(o)} k={g['k']}: 通常{'勝' if x == 1 else '負' if x == 0 else '分'} → deny{'勝' if y == 1 else '負' if y == 0 else '分'}")
                up += y > x
                dn += y < x
        L += ['- 勝敗が入れ替わった対戦: ' + (str(len(flips)) + '件')] + [f'  - {f}' for f in flips]
        L.append('- 相手構築ごとの勝数の変化（通常→deny）: ' + '、'.join(f'{ttl(o)} {v[0]:g}→{v[1]:g}' for o, v in per.items() if v[0] != v[1]))
        L.append(f'- 符号検定（McNemar 正確）: 通常負→deny勝 {up}、通常勝→deny負 {dn}、p={_binom_p(up, dn):.3f}。48戦では有意差は期待しにくい。判断材料は勝ち数と入れ替わりの中身。')
        L.append('')
    # --- top2
    A, Bn = TOP2
    t2 = {k: v for k, v in dg.items() if k.startswith(('deny:' + A, 'deny:' + Bn, 'base:'))}
    if t2:
        a, b = pair_ab(A, Bn)
        cond = {'N': {}, 'DA': {}, 'DB': {}}
        for k in range(10):
            ng = base['games'].get(f'{a}|{b}|{k}') if k < 6 else dg.get(f'base:{a}|{b}|{k}')
            if ng:
                cond['N'][k] = ng
            if f'deny:{A}|{a}|{b}|{k}' in dg:
                cond['DA'][k] = dg[f'deny:{A}|{a}|{b}|{k}']
            if f'deny:{Bn}|{a}|{b}|{k}' in dg:
                cond['DB'][k] = dg[f'deny:{Bn}|{a}|{b}|{k}']
        L += ['## A/B 2: 上位2構築（A=' + ttl(A) + '、B=' + ttl(Bn) + '）', '', '| 条件 | A側の勝ち | 判定決着 | 平均ターン |', '|---|---|---|---|']
        wins = {}
        for c, gs in cond.items():
            gs = {k: g for k, g in gs.items() if g['res'] is not None}
            wins[c] = {k: _wr(g, A) for k, g in gs.items()}
            L.append(f"| {c} | {sum(wins[c].values()):g}/{len(gs)} | {sum(1 for g in gs.values() if g.get('judged'))} | {_avg([g['turns'] for g in gs.values()]):.1f} |")
        for c, nm in (('DA', 'DA−N（A が deny を使った効果）'), ('DB', 'N−DB（B が deny を使った効果）')):
            ks = sorted(set(wins[c]) & set(wins['N']))
            up = sum(1 for k in ks if (wins[c][k] > wins['N'][k]) == (c == 'DA') and wins[c][k] != wins['N'][k])
            dn = sum(1 for k in ks if wins[c][k] != wins['N'][k]) - up
            L.append(f'- {nm}: 共通{len(ks)}戦で向きが変わった {up + dn}件（効果の向き {up}、逆 {dn}）、McNemar p={_binom_p(up, dn):.3f}')
        L += ['- 注記: 戦数が少なく有意差は期待しにくい。', '']
    # --- deny_stats
    tot = collections.Counter()
    turns = 0
    for g in dg.values():
        for s in (g.get('deny_stats') or {}).values():
            tot.update(s.get('kinds', {}))
            turns += s.get('turns', 0)
    L += ['## deny_stats（根で勝ち筋の手が見つかった件数・種類別）', '', f'- 該当ターン延べ {turns}、種類別: ' + (', '.join(f'{k}×{v}' for k, v in tot.most_common()) or 'なし'), '']
    os.makedirs(PD['dir'], exist_ok=True)
    open(PD['md'], 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print(f"書きました: {PD['md']}")


def _sha_all():
    d = {}
    for root, _, fs in os.walk(os.path.join(HERE, '..', 'logs', 'refine')):
        for f in fs:
            p = os.path.join(root, f)
            d[p] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    d.update(sha_files())
    return d


def _setup_moves(m):
    out = []
    for x in m.moves:
        md = E_MOVES.get(x)
        if md is None:
            continue
        bs = md.boosts if (md.boosts and md.target == 'self') else ((md.self_boost or {}).get('boosts') or {})
        if any(bs.get(k, 0) > 0 for k in ('atk', 'spa', 'spe')):
            out.append(x)
    return out


def _prio_moves(m):
    return [x for x in m.moves if E_MOVES.get(x) is not None and E_MOVES[x].pri > 0 and E_MOVES[x].cat != 'status']


def cmd_deny_selftest(a):
    import shutil, subprocess, tempfile, statistics as stt
    import search as S
    import engine as E
    global E_MOVES
    E_MOVES = E.MOVES
    keep = bool(a.out_dir)
    D = a.out_dir or tempfile.mkdtemp(prefix='rrdeny_')
    os.makedirs(D, exist_ok=True)
    results = []

    def ok(n, cond, msg=''):
        results.append((n, bool(cond)))
        print(f"{'○' if cond else '×'} {n} {msg}", flush=True)

    P0 = paths(None)
    before = _sha_all()
    p = subprocess.run([sys.executable, '-m', 'py_compile', 'search.py', 'refine.py', 'roundrobin.py'], cwd=HERE, capture_output=True, text=True)
    ok('1 py_compile', p.returncode == 0, p.stderr[-200:])
    plan = load_plan(P0)
    base = load_games(P0, plan['sig'])['games']
    logs = {r['key']: r['log'] for r in read_jsonl(P0['logs'])}
    _worker_init(plan['teams'])
    j = lambda o: json.loads(json.dumps(o))

    # ---- 局面の記録つきでゲームを回す
    rec = []
    calls = []
    orig = S.lookahead_action

    def wrap(st, i=0, depth=3, k_self=3, k_opp=2, mode=None, info=None):
        calls.append((i, mode))
        if mode is None:
            rec.append((st.clone(), i, depth))
        return orig(st, i, depth, k_self, k_opp, mode=mode, info=info)

    def inproc(key, deny=None, variant=None):
        a_, b_, k_ = key.split('|')
        job = _mk_job(plan, key, a_, b_, int(k_), (False, False))
        calls.clear()
        S.lookahead_action = wrap
        try:
            args = (None, job[2], job[3], job[4], job[5], DEPTH[0], DEPTH[1], False, None, False, (job[1],))
            if variant == 'none':
                args += (None,)
            elif variant == 'tuple':
                args += (deny,)
            rr_apply(_TEAMS[job[1]])
            return R.blind_play(args)
        finally:
            S.lookahead_action = orig

    r11 = sorted([k for k, g in base.items() if 'R11' in (g['a'], g['b']) and not g.get('rematch') and g['res'] is not None], key=lambda k: base[k]['turns'])
    A_, B_ = TOP2
    t2 = [k for k, g in base.items() if {g['a'], g['b']} == {A_, B_} and not g.get('rematch') and g['res'] is not None]
    keys = [r11[0], r11[1], t2[0]]
    allok = True
    for key in keys:
        r = inproc(key)
        g = base[key]
        same = all(j(r[f]) == j(g[f]) for f in ('res', 'turns', 'judged', 'left', 'faints')) and j(r['log']) == j(logs[key])
        allok &= same
        print(f'   従来 {key[:24]}.. 一致={same}', flush=True)
    ok('2a 従来3戦 res/turns/judged/left/faints/log 完全一致', allok)
    key0 = keys[0]
    for nm, var, dn in (('args[11]=None', 'none', None), ('args[11]=(False,False)', 'tuple', (False, False))):
        r = inproc(key0, dn, var)
        g = base[key0]
        same = all(j(r[f]) == j(g[f]) for f in ('res', 'turns', 'judged', 'left', 'faints')) and j(r['log']) == j(logs[key0]) and 'deny_stats' not in r
        ok(f'2b {nm} で同一', same)
    positions = list(rec)
    # ---- 片側 deny
    r = inproc(key0, (True, False), 'tuple')
    s0 = {i for i, m in calls if m == 'deny'}
    n0 = {i for i, m in calls if m is None}
    ok('4a (True,False): 側0だけ deny', s0 == {0} and n0 == {1} and set(r.get('deny_stats', {})) == {0}, f"deny側={s0} 通常側={n0} stats={list(r.get('deny_stats', {}))}")
    r = inproc(key0, (False, True), 'tuple')
    s0 = {i for i, m in calls if m == 'deny'}
    n0 = {i for i, m in calls if m is None}
    ok('4b (False,True): 側1だけ deny', s0 == {1} and n0 == {0} and set(r.get('deny_stats', {})) == {1}, f"deny側={s0} 通常側={n0} stats={list(r.get('deny_stats', {}))}")
    # ---- 局面テスト
    def both(st, i, d=4):
        info = {}
        S._EC.clear()
        a1 = S.lookahead_action(st, i, d)
        S._EC.clear()
        a2 = S.lookahead_action(st, i, d, mode='deny', info=info)
        return a1, a2, info

    def fmt_a(x):
        return None if x is None else (x[1] if x[0] == 'm' else f'交代{x[1]}')

    def show(tag, i, a1, a2, info):
        print(f"   {tag} 側{i}: 従来={fmt_a(a1)} deny={fmt_a(a2)} threats_root={[(k, fmt_a(x)) for k, x in info.get('threats_root', [])]}", flush=True)

    pos0 = [(st, i) for st, i, d in positions if len(E.actions(st, i)) > 1]
    cnt = {'T1': [0, 0], 'T2': [0, 0], 'T3': [0, 0], 'T4': [0, 0]}
    shown = collections.Counter()

    def rec_test(t, st, i, tag):
        a1, a2, info = both(st, i)
        cnt[t][0] += 1
        cnt[t][1] += a1 != a2
        if shown[t] < 3 or (a1 != a2 and shown[t + 'd'] < 2):
            show(f'{t} {tag}', i, a1, a2, info)
            shown[t] += 1
            shown[t + 'd'] += a1 != a2
        return a1, a2, info

    def mons(st, i):
        me = st.sides[i].mons[st.sides[i].act]
        foe = st.sides[1 - i].mons[st.sides[1 - i].act]
        return me, foe

    sample = pos0[::max(1, len(pos0) // 12)][:12]
    for st, i in sample:
        # T1: 相手に積み技を持たせる（無ければ つるぎのまい を足す）
        s = st.clone()
        me, foe = mons(s, i)
        if not me.alive or not foe.alive:
            continue
        if not _setup_moves(foe):
            foe.moves = list(foe.moves) + ['swordsdance']
        rec_test('T1', s, i, '積み技持ち')
        # T2: 相手が +2
        s = st.clone()
        me, foe = mons(s, i)
        foe.boosts['atk'] = 2
        foe.boosts['spa'] = 2
        rec_test('T2', s, i, '相手+2')
        # T3: 先制技圏内
        s = st.clone()
        me, foe = mons(s, i)
        if not _prio_moves(foe):
            foe.moves = list(foe.moves) + ['extremespeed']
        me.hp = max(1, me.maxhp // 12)
        me.boosts['spe'] = 6
        rec_test('T3', s, i, '先制圏内')
        # T4: 脅威なし（積み・先制技を除く、ランク0）
        s = st.clone()
        me, foe = mons(s, i)
        foe.moves = [x for x in foe.moves if x not in _setup_moves(foe) and x not in _prio_moves(foe)]
        foe.boosts = dict.fromkeys(foe.boosts, 0)
        rec_test('T4', s, i, '脅威なし')
    for t in ('T1', 'T2', 'T3', 'T4'):
        print(f'   {t}: 手が違った {cnt[t][1]}/{cnt[t][0]}', flush=True)
    ok('3 deny: T1〜T3 のうち2つ以上で手が異なる', sum(1 for t in ('T1', 'T2', 'T3') if cnt[t][1] > 0) >= 2, str({t: cnt[t] for t in cnt}))
    ok('3 対照T4: 手が一致（脅威なし）', cnt['T4'][1] == 0, f'{cnt["T4"][1]}/{cnt["T4"][0]} 件で違い')
    # ---- 時間比
    sel = [(st, i) for st, i in pos0]
    sel = sel[::max(1, len(sel) // 40)][:40]
    ratios = {0: [], 1: []}
    changed = 0
    for st, i in sel:
        S._EC.clear()
        t0 = time.time()
        a1 = S.lookahead_action(st, i, 4)
        t1 = time.time() - t0
        S._EC.clear()
        t0 = time.time()
        a2 = S.lookahead_action(st, i, 4, mode='deny')
        t2_ = time.time() - t0
        ratios[i].append(t2_ / max(t1, 1e-3))
        changed += a1 != a2
    allr = ratios[0] + ratios[1]
    print(f'   時間比: 局面{len(sel)}（側0 {len(ratios[0])}, 側1 {len(ratios[1])}）手が違った{changed}件', flush=True)
    for i in (0, 1):
        if ratios[i]:
            print(f'   側{i}: 中央値{stt.median(ratios[i]):.2f} 最大{max(ratios[i]):.2f}', flush=True)
    ok('5a 時間比 30局面以上・中央値≤1.5・最大≤2.0（側0/側1）', len(sel) >= 30 and all(ratios[i] for i in (0, 1)) and stt.median(allr) <= 1.5 and max(allr) <= 2.0
       and all(stt.median(ratios[i]) <= 1.5 and max(ratios[i]) <= 2.0 for i in (0, 1) if ratios[i]))
    # ---- 一時フォルダでの run / full
    def cli(*args):
        p = subprocess.run([sys.executable, 'roundrobin.py', 'deny', *args], cwd=HERE, capture_output=True, text=True)
        print('   ' + ' '.join(args) + f' -> rc={p.returncode}', flush=True)
        if p.returncode:
            print(p.stderr[-400:])
        return p

    Dr = os.path.join(D, 'r11')
    cli('run', '--part', 'r11', '--max-games', '1', '--procs', '1', '--out-dir', Dr)
    gd = json.load(open(os.path.join(Dr, 'rr_deny_games.json'), encoding='utf-8'))['games']
    k1 = list(gd)[0]
    nk = k1.split(':', 1)[1].split('|', 1)[1]
    ok('5b r11 の1戦 deny の sec が従来の2倍以内', gd[k1]['sec'] <= 2 * base[nk]['sec'], f"deny {gd[k1]['sec']}秒 / 従来 {base[nk]['sec']}秒 (res {gd[k1]['res']})")
    Dt = os.path.join(D, 'top2')
    cli('run', '--part', 'top2', '--max-games', '2', '--procs', '2', '--out-dir', Dt)
    g1 = set(json.load(open(os.path.join(Dt, 'rr_deny_games.json'), encoding='utf-8'))['games'])
    cli('run', '--part', 'top2', '--max-games', '2', '--procs', '2', '--out-dir', Dt)
    g2 = set(json.load(open(os.path.join(Dt, 'rr_deny_games.json'), encoding='utf-8'))['games'])
    ok('7 top2 再開: 2戦→さらに2戦（重複なし）', len(g1) == 2 and len(g2) == 4 and g1 < g2, f'{sorted(g1)} -> {len(g2)}戦')
    Df = os.path.join(D, 'full')
    cli('full', '--max-games', '3', '--procs', '3', '--out-dir', Df)
    f1 = json.load(open(os.path.join(Df, 'rr_deny_games.json'), encoding='utf-8'))['games']
    ds = all(set(g.get('deny_stats', {})) == {'0', '1'} for g in f1.values())
    exp = [f'full:{x}|{y}|0' for x, y in circle_pairs(tier_ids(plan, 1))[:3]]
    ok('9a full: 鍵 full: ・k=0 から・(True,True)', set(f1) == set(exp) and ds and all(g['deny'] == [True, True] for g in f1.values()), f'{sorted(f1)} deny_stats両側={ds}')
    cli('full', '--max-games', '1', '--procs', '1', '--out-dir', Df)
    f2 = json.load(open(os.path.join(Df, 'rr_deny_games.json'), encoding='utf-8'))['games']
    nx = f'full:{circle_pairs(tier_ids(plan, 1))[3][0]}|{circle_pairs(tier_ids(plan, 1))[3][1]}|0'
    ok('9b full 再実行で続きから', len(f2) == 4 and set(f2) - set(f1) == {nx}, f'新規={sorted(set(f2) - set(f1))}')
    cli('report', '--out-dir', Df)
    md = open(os.path.join(Df, 'rr_deny_report.md'), encoding='utf-8').read()
    ok('10 report: 比較表の列と R11 順位行', '| 構築 | 通常 勝率 | 通常 順位 | deny 勝率 | deny 順位 | 順位差 |' in md and 'R11 の順位' in md and 'R11' in md, md[:0])
    after = _sha_all()
    ok('6 既存ファイルの sha256 不変', before == after, f'{len(before)}件')
    ok('11 本番の deny ファイルが作られていない', not any(os.path.exists(os.path.join(DEF_OUT, f)) for f in ('rr_deny_games.json', 'rr_deny_logs.jsonl', 'rr_deny_report.md')))
    print('\n結果:', 'すべて ○' if all(c for _, c in results) else '×あり: ' + ', '.join(n for n, c in results if not c))
    if not keep:
        shutil.rmtree(D, ignore_errors=True)


def cmd_deny(a):
    {'run': lambda: cmd_deny_run(a), 'full': lambda: cmd_deny_run(a, True), 'report': lambda: cmd_deny_report(a),
     'selftest': lambda: cmd_deny_selftest(a)}[a.what]()


# ---------------------------------------------------------------- adapt: 適応選出 500戦 (SPEC_ADAPT.md)
import contextlib  # noqa: E402

AD_VERSION = 'ad1'
AD_MAIN = 'db0baa2843d2bd4b'
AD_LAMBDA, AD_COEF, AD_BONUS = 0.7, 0.15, 0.01
DEF_ADMD = os.path.join(HERE, '..', 'logs', 'ADAPT.md')
_AD = {'sel1': {}}
_AD_PLAY = R.blind_play
_AD_EVAL = None            # selftest 用: (order, opp_order, smart) -> v


def ad_paths(out_dir=None):
    d = out_dir or DEF_OUT
    return {'dir': d, 'plan': os.path.join(d, 'ad_plan.json'), 'games': os.path.join(d, 'ad_games.json'),
            'logs': os.path.join(d, 'ad_logs.jsonl'), 'md': os.path.join(d, 'ADAPT.md') if out_dir else DEF_ADMD}


def _pw(v):
    return 1.0 / (1.0 + math.exp(-max(-500.0, min(500.0, v)) / 20.0))


def _ad_val(o, c, smart):
    if _AD_EVAL is not None:
        return _AD_EVAL(o, c, smart)
    return B._game_job((list(o), list(c), smart, None))


@contextlib.contextmanager
def _ad_blind(A, Bid):
    import sets as _sets
    saved = (B.match_known, B._load_select_rules, B._focus_mons, _sets.EXCLUDE, B._KNOWN_CTX['team'])
    try:
        rr_apply(_TEAMS[A])
        _sets.EXCLUDE = {A, Bid}
        B._OPP_CACHE.clear()
        B.match_known = lambda *a, **k: None
        B._load_select_rules = lambda: []
        B._focus_mons = lambda opp6: {}
        B.set_known_context(None)
        yield
    finally:
        B.match_known, B._load_select_rules, B._focus_mons, _sets.EXCLUDE, B._KNOWN_CTX['team'] = saved
        B._OPP_CACHE.clear()


def _ad_prior(Bid):
    """A 側が rr_apply 済み・ブラインド状態で呼ぶ。相手の並びの事前分布（上位4組×先発按分）。"""
    b6 = [m['base'] for m in _TEAMS[Bid]['mons']]
    w = B.opp_pick_weights(b6, list(B.MY.values()))
    trip = []
    for c in itertools.combinations(b6, 3):
        p = 1.0
        for n in c:
            p *= w[n]
        trip.append((p, c))
    trip.sort(key=lambda x: -x[0])
    trip = trip[:4]
    tot = sum(p for p, _ in trip)
    pr = {}
    for p, c in trip:
        lw = [B.lead_rate(B.BASE_OF.get(B.norm(x), B.norm(x))) for x in c]
        for lead, l in zip(c, lw):
            pr[(lead,) + tuple(x for x in c if x != lead)] = p / tot * l / sum(lw)
    return pr


def _ad_q(prior, hist):
    m = len(hist)
    n = m + 1
    h = {}
    for e in hist:
        c = tuple(e['theirs'])
        h[c] = h.get(c, 0.0) + AD_LAMBDA ** (n - 1 - e['n'])
    hs = sum(h.values())
    pi = 1.0 / (1 + m)
    pr = {c: p for c, p in prior.items() if c not in h}
    ps = sum(pr.values())
    q = {}
    if hs and ps:
        for c, v in h.items():
            q[c] = (1 - pi) * v / hs
        for c, v in pr.items():
            q[c] = q.get(c, 0.0) + pi * v / ps
    elif hs:
        q = {c: v / hs for c, v in h.items()}
    else:
        q = {c: v / ps for c, v in pr.items()}
    return q, pi


def ad_q(A, Bid, hist):
    """テスト用: (q, pi_new, prior)"""
    with _ad_blind(A, Bid):
        prior = _ad_prior(Bid)
    q, pi = _ad_q(prior, hist)
    return q, pi, prior


def adapt_select(A, Bid, hist):
    """A が Bid を相手に選ぶ。第1戦は sel1、第2戦以降は 3.3。戻り値 (order, 記録)。"""
    t0 = time.time()
    ta = _TEAMS[A]
    if not hist:
        s = _AD['sel1'].get(f'{A}|{Bid}') or decide_pair(A, Bid)
        return list(s['order']), {'src': s.get('src'), 'order': list(s['order']), 'hist_len': 0, 'sec': round(time.time() - t0, 2)}
    cands = [tuple(o) for o in ta['candidates']]
    banned = None
    if len(hist) >= 2 and tuple(hist[-1]['mine']) == tuple(hist[-2]['mine']) and tuple(hist[-1]['mine']) in cands:
        banned = tuple(hist[-1]['mine'])
    cl = [o for o in cands if o != banned]
    with _ad_blind(A, Bid):
        prior = _ad_prior(Bid)
        q, pi = _ad_q(prior, hist)
        qs = sorted(q.items(), key=lambda x: -x[1])
        C, cum = [], 0.0
        for c, p in qs:
            if len(C) >= 10 or cum >= 0.95:
                break
            C.append((c, p))
            cum += p
        tq = sum(p for _, p in C)
        C = [(c, p / tq) for c, p in C]
        vals = {}
        for o in cl:
            for c, _ in C:
                vals[(o, c)] = _pw(_ad_val(o, c, False))

        def EW(o):
            e = sum(p * vals[(o, c)] for c, p in C)
            ws = [vals[(o, c)] for c, p in C if p >= 0.05] or [vals[(o, C[0][0])]]
            return e, min(ws)
        ew = {o: EW(o) for o in cl}
        top8 = sorted(cl, key=lambda o: (-ew[o][0], cl.index(o)))[:8]
        for o in top8:
            for c, _ in C[:5]:
                vals[(o, c)] = _pw(_ad_val(o, c, True))
        ew.update({o: EW(o) for o in top8})
    guide = {tuple(o) for o in ta['article_orders']}
    for it in ta['gitems']:
        if it['kind'] == 'basic' and it.get('usable', True):
            guide |= {tuple(o) for o in it['orders']}
    score = {}
    for o in top8:
        e, w = ew[o]
        n_, s_ = 0, 0.0
        for e_ in hist:
            if tuple(e_['mine']) == o:
                n_ += 1
                s_ += e_['res_for_A']
        rh = (s_ + 1) / (n_ + 2) if n_ else 0.5
        if n_:
            rh = (s_ + 1) / (n_ + 2)
        sc = (1 - pi) * e + pi * w + AD_COEF * (rh - 0.5) + (AD_BONUS if o in guide else 0.0)
        score[o] = (sc, e, w, rh)
    best = None
    for o in cl:
        if o in score and (best is None or score[o][0] > score[best][0] + 1e-12):
            best = o
    st = sorted(top8, key=lambda o: (-score[o][0], cl.index(o)))[:3]
    why = {'src': 'adapt', 'order': list(best), 'hist_len': len(hist), 'pi_new': round(pi, 4),
           'q_top': [[round(p, 4), list(c)] for c, p in C[:5]],
           'score_top': [[round(score[o][0], 4), round(score[o][1], 4), round(score[o][2], 4), round(score[o][3], 4), list(o)] for o in st],
           'banned_streak': list(banned) if banned else None, 'sec': round(time.time() - t0, 2)}
    return list(best), why


_AD_SELECT = adapt_select


def ad_seed(X, k):
    return zlib.crc32(f'ad{X}{k}'.encode())


def _job_adapt(a):
    key, X, k, s0, s1, h0, h1 = a
    t0 = time.time()
    o0 = o1 = w0 = w1 = None
    try:
        o0, w0 = _AD_SELECT(s0, s1, h0)
        o1, w1 = _AD_SELECT(s1, s0, h1)
        sec_sel = round(time.time() - t0, 2)
        rr_apply(_TEAMS[s0])
        r = _AD_PLAY((None, s1, o0, o1, ad_seed(X, k), DEPTH[0], DEPTH[1], False, None, False, (s0,), (True, True)))
    except Exception:
        sec_sel = round(time.time() - t0, 2)
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    r.update({'key': key, 'sel0': o0, 'sel1': o1, 'why0': w0, 'why1': w1, 'sec_sel': sec_sel, 'sec': round(time.time() - t0, 2)})
    return r


def ad_load_plan(P):
    if not os.path.exists(P['plan']):
        raise SystemExit(f"{P['plan']} がありません。先に adapt plan を実行してください")
    return json.load(open(P['plan'], encoding='utf-8'))


def cmd_adapt_plan(a):
    P = ad_paths(a.out_dir)
    os.makedirs(P['dir'], exist_ok=True)
    rp = load_plan(paths(None))
    T = rp['teams']
    L = a.main
    elig = [i for i in rp['order'] if i != L and i != 'R11' and (T[i].get('rank') or T[i].get('final') or T[i].get('peak'))]
    if len(elig) < a.n_opp:
        raise SystemExit(f'適格 {len(elig)} < {a.n_opp}: フォールバック未実装')
    _worker_init(T)
    skipped = []
    try:
        rr_apply(T[L])
    except Exception as e:
        raise SystemExit(f'主構築が適用できません: {e}')
    opps = []
    for i in elig:
        if len(opps) >= a.n_opp:
            break
        try:
            rr_apply(T[i])
            opps.append(i)
        except Exception as e:
            skipped.append({'id': i, 'why': str(e)[:120]})
            print(f'  除外 {i}: {e}', flush=True)
    if len(opps) < a.n_opp:
        raise SystemExit('適格が足りません（フォールバック未実装）')
    sig = hashlib.sha256((rp['sig'] + L + ','.join(opps) + AD_VERSION).encode()).hexdigest()
    plan = None
    if os.path.exists(P['plan']):
        old = json.load(open(P['plan'], encoding='utf-8'))
        if old.get('sig') == sig:
            plan = old
        elif not a.force:
            raise SystemExit('ad_plan.json の sig が違います（--force で退避して作り直し）')
        else:
            os.replace(P['plan'], P['plan'][:-5] + time.strftime('.%Y%m%d_%H%M%S.json'))
    if plan is None:
        plan = {'version': AD_VERSION, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'rr_sig': rp['sig'], 'sig': sig, 'main': L,
                'games_per_pair': a.games, 'depth': list(DEPTH), 'deny': [True, True], 'opponents': opps, 'skipped': skipped, 'sel1': {}}
    need = []
    for X in opps:
        for k in (f'{L}|{X}', f'{X}|{L}'):
            if k in plan['sel1']:
                continue
            if k in rp['sel'] and 'order' in rp['sel'][k]:
                plan['sel1'][k] = rp['sel'][k]
            else:
                need.append(tuple(k.split('|')))
    print(f'対戦相手 {len(opps)}（除外 {len(skipped)}）、sel1: rr_plan から流用 {len(plan["sel1"])}、計算 {len(need)}', flush=True)
    if need:
        t0 = time.time()
        with make_pool(a.procs, T) as pool:
            for k, d in pool.imap_unordered(_job_decide, need, chunksize=1):
                if 'error' in d:
                    raise SystemExit(f'選出計算エラー {k}: {d["error"]}')
                plan['sel1'][k] = d
        print(f'  sel1 計算 {time.time() - t0:.0f}秒', flush=True)
    safeio.write_json(P['plan'], plan)
    print(f"書きました: {P['plan']}（sig {sig[:12]}）")
    return plan


def ad_load_games(P, sig):
    if os.path.exists(P['games']):
        g = json.load(open(P['games'], encoding='utf-8'))
        if g.get('plan_sig') != sig:
            raise SystemExit('ad_games.json の plan_sig が ad_plan.json と違います')
        return g
    return {'version': AD_VERSION, 'plan_sig': sig, 'main': None, 'depth': list(DEPTH), 'deny': [True, True], 'games': {}}


def ad_hist(games, X, A, upto, L):
    """A 視点の履歴（第1〜upto戦、古い順）。"""
    out = []
    for k in range(upto):
        g = games['games'][f'ad:{X}|{k}']
        mine, theirs = (g['sel0'], g['sel1']) if g['side0'] == A else (g['sel1'], g['sel0'])
        res = g['res']
        r = 0.5 if res == 0 else (1 if (res == 1) == (g['side0'] == A) else 0)
        out.append({'n': k + 1, 'mine': list(mine), 'theirs': list(theirs), 'res_for_A': r})
    return out


def ad_record(job, r, L):
    key, X, k, s0, s1 = job[:5]
    res = r.get('res')
    w = None if res is None else (s0 if res == 1 else (s1 if res == -1 else None))
    rec = {'side0': s0, 'side1': s1, 'sel0': r.get('sel0'), 'sel1': r.get('sel1'), 'seed': ad_seed(X, k), 'res': res, 'winner': w,
           'judged': r.get('judged'), 'turns': r.get('turns'), 'left': r.get('left'), 'faints': r.get('faints'), 'sec': r.get('sec'),
           'error': r.get('error'), 'deny': [True, True], 'opp': X, 'k': k, 'n': k + 1, 'main_side': 0 if s0 == L else 1,
           'why0': r.get('why0'), 'why1': r.get('why1'), 'sec_sel': r.get('sec_sel')}
    if r.get('deny_stats') is not None:
        rec['deny_stats'] = r['deny_stats']
    return rec


def cmd_adapt_run(a):
    P = ad_paths(a.out_dir)
    plan = ad_load_plan(P)
    rp = load_plan(paths(None))
    if rp['sig'] != plan['rr_sig']:
        raise SystemExit('rr_plan.json の sig が ad_plan.json と違います')
    L, opps, G = plan['main'], plan['opponents'], plan['games_per_pair']
    games = ad_load_games(P, plan['sig'])
    games['main'] = L
    _AD['sel1'] = plan['sel1']
    gm = games['games']

    def next_k(X):
        for k in range(G):
            g = gm.get(f'ad:{X}|{k}')
            if g is None:
                return k
            if g['res'] is None:
                return k if a.retry_errors else None
        return None

    tot = len(opps) * G
    base = sum(1 for g in gm.values() if g['res'] is not None)
    print(f'全体 {tot}戦、済み {base}、今回 最大 {a.max_games or "全部"}', flush=True)
    os.makedirs(P['dir'], exist_ok=True)
    active, n_disp, n_done = {}, 0, 0
    t0 = time.time()
    with make_pool(a.procs, rp['teams']) as pool:
        while True:
            for X in opps:
                if len(active) >= a.procs or (a.max_games and n_disp >= a.max_games):
                    break
                if X in active:
                    continue
                k = next_k(X)
                if k is None:
                    continue
                s0, s1 = (L, X) if k % 2 == 0 else (X, L)
                job = (f'ad:{X}|{k}', X, k, s0, s1, ad_hist(games, X, s0, k, L), ad_hist(games, X, s1, k, L))
                active[X] = (pool.apply_async(_job_adapt, (job,)), job)
                n_disp += 1
            if not active:
                break
            got = False
            for X, (ar, job) in list(active.items()):
                if not ar.ready():
                    continue
                got = True
                r = ar.get()
                del active[X]
                n_done += 1
                gm[job[0]] = ad_record(job, r, L)
                safeio.write_json(P['games'], games)
                if r.get('log') is not None:
                    append_log(P, job[0], r['log'])
                mark = '例外' if r.get('res') is None else ('勝' if (r['res'] == 1) == (job[3] == L) and r['res'] != 0 else ('分' if r['res'] == 0 else '負'))
                el = (time.time() - t0) / 60
                rem = el / n_done * max(0, (min(a.max_games, tot - base) if a.max_games else tot - base) - n_done)
                print(f"[{base + n_done}/{tot}] {job[0]} L{mark} {r.get('turns')}手 {r['sec']:.0f}秒(選出{r.get('sec_sel') or 0:.0f}) 経過{el:.1f}分 残り約{rem:.1f}分", flush=True)
            if not got:
                time.sleep(0.05)
    return n_done


# ---- report
def _lw(g, L):
    """L 視点の結果 1 / 0.5 / 0（res None は None）。"""
    r = g['res']
    if r is None:
        return None
    return 0.5 if r == 0 else (1.0 if (r == 1) == (g['main_side'] == 0) else 0.0)


def _rate(rs):
    n = len(rs)
    w = sum(rs)
    lo, hi = wilson(w, n)
    return f'{w:g}/{n} = {(w / n * 100 if n else 0):.1f}% [{lo * 100:.1f}-{hi * 100:.1f}]'


def _ostr(o):
    return '/'.join(o) if o else '-'


def cmd_adapt_report(a):
    P = ad_paths(a.out_dir)
    plan = ad_load_plan(P)
    rp = load_plan(paths(None))
    T = rp['teams']
    L, opps = plan['main'], plan['opponents']
    games = ad_load_games(P, plan['sig'])['games']
    recs = [g for g in games.values() if g.get('opp') in opps]
    ok_ = [g for g in recs if g['res'] is not None]
    out = [f'# 適応選出 {len(opps)}構築 × {plan["games_per_pair"]}戦（{T[L]["title"][:30]}）', '']
    # 1
    rs = [_lw(g, L) for g in ok_]
    jd = [g for g in ok_ if g.get('judged')]
    out += ['## 1. 全体', f'- L の戦績: {_rate(rs)}（{len(ok_)}/{len(opps) * plan["games_per_pair"]}戦）',
            f'- 判定決着: {len(jd)}戦、判定のみの勝率 {_rate([_lw(g, L) for g in jd])}',
            f'- エラー: {sum(1 for g in recs if g["res"] is None)}、平均ターン {_avg([g["turns"] for g in ok_ if g.get("turns")]):.1f}', '']
    # 2
    out += ['## 2. 戦を重ねるごとの推移']
    for nm, ks in (('第1-3戦', range(0, 3)), ('第4-6戦', range(3, 6)), ('第7-10戦', range(6, 10))):
        out.append(f'- {nm}: {_rate([_lw(g, L) for g in ok_ if g["k"] in ks])}')
    for s in (0, 1):
        out.append(f'- L が side{s}: {_rate([_lw(g, L) for g in ok_ if g["main_side"] == s])}')
    out.append('')
    # 3
    out += ['## 3. 相手構築ごと', '| # | 構築 | rank | 10戦 | 勝 | 1-3 | 4-6 | 7-10 |', '|---|---|---|---|---|---|---|---|']
    by = {X: sorted([g for g in ok_ if g['opp'] == X], key=lambda g: g['k']) for X in opps}
    wr = {}
    for i, X in enumerate(opps, 1):
        s, wsum = '', 0.0
        seg = [0.0, 0.0, 0.0]
        for g in by[X]:
            v = _lw(g, L)
            j = g.get('judged')
            s += ('o' if j else '○') if v == 1 else (('x' if j else '●') if v == 0 else '△')
            wsum += v
            seg[0 if g['k'] < 3 else (1 if g['k'] < 6 else 2)] += v
        wr[X] = wsum / len(by[X]) if by[X] else 0
        out.append(f"| {i} | {T[X]['title'][:24]} | {T[X].get('rank')} | {s} | {wsum:g} | {seg[0]:g} | {seg[1]:g} | {seg[2]:g} |")
    out.append('')
    # 4
    out += ['## 4. 適応による選出の変化']
    chg, ad_r, k0_r = 0, [], []
    lo_cnt = collections.Counter()
    lo_q = {}
    for X in opps:
        ls, ts = [], []
        for g in by[X]:
            lo = g['sel0'] if g['main_side'] == 0 else g['sel1']
            to = g['sel1'] if g['main_side'] == 0 else g['sel0']
            wh = g['why0'] if g['main_side'] == 0 else g['why1']
            ls.append(tuple(lo or ()))
            ts.append(tuple(to or ()))
            lo_cnt[tuple(lo or ())] += 1
            if wh and wh.get('q_top') and tuple(lo or ()) not in lo_q:
                lo_q[tuple(lo or ())] = wh['q_top']
            v = _lw(g, L)
            if g['k'] == 0:
                k0_r.append(v)
            elif wh and wh.get('src') == 'adapt':
                ad_r.append(v)
            if g['k'] >= 1 and ls and ls[-1] != ls[0]:
                chg += 1
        if ls:
            out.append(f"- {T[X]['title'][:16]}: L {len(set(ls))}種 [{' > '.join(l[0] if l else '-' for l in ls)}] / 相手 {len(set(ts))}種 [{' > '.join(t[0] if t else '-' for t in ts)}]")
    out.append(f'- 第1戦と異なる並びにした戦数: {chg}')
    out.append(f'- adapt 選出の勝率: {_rate(ad_r)} / 第1戦の選出の勝率: {_rate(k0_r)}')
    out.append('- L の最頻の並びトップ3と q 上位（相手の予測）:')
    for o, n in lo_cnt.most_common(3):
        out.append(f"  - {_ostr(o)} ×{n}; q上位: {[[q, _ostr(c)] for q, c in (lo_q.get(o) or [])[:3]]}")
    out.append('')
    # 5
    out += ['## 5. 勝てない相手トップ10']
    rank_ = {X: i for i, X in enumerate(opps)}
    for X in sorted(opps, key=lambda x: (wr[x], rank_[x]))[:10]:
        fl, fo, oo = collections.Counter(), collections.Counter(), collections.Counter()
        for g in by[X]:
            first = next((f for f in (g.get('faints') or []) if f[1] == g['main_side']), None)
            if first:
                fl[first[2]] += 1
            for f in (g.get('faints') or []):
                if f[1] == g['main_side']:
                    fo[f[3]] += 1
            oo[_ostr(g['sel1'] if g['main_side'] == 0 else g['sel0'])] += 1
        out.append(f"- {T[X]['title'][:22]} 勝率{wr[X] * 100:.0f}%: 最初に倒れたL側 {fl.most_common(3)} / 倒した相手 {fo.most_common(3)} / 相手の並び {oo.most_common(2)}")
    out.append('')
    # 6
    out += ['## 6. L の選出別勝率', '### 並び（先発込み）']
    po, pt = collections.defaultdict(list), collections.defaultdict(list)
    for g in ok_:
        lo = tuple((g['sel0'] if g['main_side'] == 0 else g['sel1']) or ())
        po[lo].append(_lw(g, L))
        pt[tuple(sorted(lo))].append(_lw(g, L))
    for o, v in sorted(po.items(), key=lambda x: -len(x[1])):
        out.append(f'- {_ostr(o)}: {len(v)}戦 {sum(v) / len(v) * 100:.0f}%')
    out.append('### 3体組')
    for o, v in sorted(pt.items(), key=lambda x: -len(x[1])):
        out.append(f'- {_ostr(o)}: {len(v)}戦 {sum(v) / len(v) * 100:.0f}%')
    out.append('')
    # 7
    out += ['## 7. 比較（非適応・両側 deny: rr_deny_games.json）']
    dp = deny_paths(None)
    dg = json.load(open(dp['games'], encoding='utf-8'))['games'] if os.path.exists(dp['games']) else {}
    tA = tB = tC = 0.0
    nA = nB = nC = 0
    out += ['| 相手 | 非適応 | 適応10戦 | 適応第1戦 |', '|---|---|---|---|']
    for X in opps:
        d = [g for g in dg.values() if g.get('res') is not None and {g['side0'], g['side1']} == {L, X}]
        if not d:
            continue
        dv = [0.5 if g['res'] == 0 else (1.0 if (g['res'] == 1) == (g['side0'] == L) else 0.0) for g in d]
        av = [_lw(g, L) for g in by[X]]
        a1 = [_lw(g, L) for g in by[X] if g['k'] == 0]
        out.append(f"| {T[X]['title'][:20]} | {sum(dv):g}/{len(dv)} | {sum(av):g}/{len(av)} | {sum(a1):g}/{len(a1)} |")
        tA += sum(dv); nA += len(dv); tB += sum(av); nB += len(av); tC += sum(a1); nC += len(a1)
    out += [f'- 合計: 非適応 {_rate_s(tA, nA)} / 適応10戦 {_rate_s(tB, nB)} / 適応第1戦 {_rate_s(tC, nC)}', '- 参考: 非適応全体 100/144（69.4%）', '']
    # 8
    out += ['## 8. 設定', f'- depth {plan["depth"]}、deny {plan["deny"]}、λ={AD_LAMBDA}、α=1（π_new=1/(1+m)）、戦績係数 {AD_COEF}、ガイド加点 {AD_BONUS}、'
            f'seed=crc32("ad{{X}}{{k}}")、ad_plan sig {plan["sig"]}']
    os.makedirs(os.path.dirname(P['md']), exist_ok=True)
    open(P['md'], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f"書きました: {P['md']}")


def _rate_s(w, n):
    return f'{w:g}/{n} = {(w / n * 100 if n else 0):.1f}%'


def cmd_adapt_selftest(a):
    import shutil, subprocess, tempfile, statistics as stt
    global _AD_PLAY, _AD_SELECT, _AD_EVAL
    D = a.out_dir or tempfile.mkdtemp(prefix='adtest_')
    os.makedirs(D, exist_ok=True)
    results = []

    def ok(n, cond, msg=''):
        results.append((n, bool(cond)))
        print(f"{'○' if cond else '×'} {n} {msg}", flush=True)

    before = _sha_all()
    p = subprocess.run([sys.executable, '-m', 'py_compile', 'roundrobin.py'], cwd=HERE, capture_output=True, text=True)
    ok('1 py_compile', p.returncode == 0, p.stderr[-200:])
    rp = load_plan(paths(None))
    T = rp['teams']
    D2 = os.path.join(D, 'plan')

    class A_:
        pass
    pa = A_()
    pa.out_dir, pa.main, pa.n_opp, pa.games, pa.procs, pa.force = D2, AD_MAIN, 50, 10, a.procs, True
    t0 = time.time()
    plan = cmd_adapt_plan(pa)
    P2 = ad_paths(D2)
    L, opps = plan['main'], plan['opponents']
    elig = [i for i in rp['order'] if i != L and i != 'R11' and (T[i].get('rank') or T[i].get('final') or T[i].get('peak'))]
    _worker_init(T)
    _AD['sel1'] = plan['sel1']
    try:
        for i in [L] + opps:
            rr_apply(T[i])
        applied = True
    except Exception:
        applied = False
    ok('2 相手集合', len(opps) == 50 and L not in opps and 'R11' not in opps and opps == elig[:50] and
       all(T[i].get('rank') or T[i].get('final') or T[i].get('peak') for i in opps) and applied and len(plan['sel1']) == 100,
       f'適格{len(elig)} sel1={len(plan["sel1"])} plan作成{time.time() - t0:.0f}秒')
    good = True
    for i in [L] + opps:
        cs = [tuple(o) for o in T[i]['candidates']]
        ao = {tuple(o) for o in all_orders(T[i])}
        mega = {m['base'] for m in T[i]['mons'] if m['mega']}
        good &= len(cs) == 24 and set(cs) <= ao and all(len(mega & set(c)) <= 1 for c in cs) and \
            sum(1 for c in cs if not (mega & set(c))) <= 4
    ok('3a 24通りの制約', good)
    # 4 履歴依存・決定性
    t_sel, diff, det, inc = [], 0, True, True
    for X in opps[:4]:
        cs = [tuple(o) for o in T[X]['candidates']]
        a_ = cs[0]
        b_ = next(c for c in cs if set(c) != set(a_))
        mk = lambda c: [{'n': n, 'mine': list(T[L]['candidates'][0]), 'theirs': list(c), 'res_for_A': 1 if n % 2 else 0} for n in (1, 2, 3)]
        t0 = time.time()
        r1, w1 = adapt_select(L, X, mk(a_))
        t_sel.append(time.time() - t0)
        r2, _ = adapt_select(L, X, mk(b_))
        r1b, _ = adapt_select(L, X, mk(a_))
        diff += r1 != r2
        det &= r1 == r1b
        inc &= tuple(r1) in {tuple(o) for o in T[L]['candidates']} and tuple(r2) in {tuple(o) for o in T[L]['candidates']}
        print(f'   {X[:8]} H1={_ostr(a_)}->{_ostr(r1)} H2={_ostr(b_)}->{_ostr(r2)} ({t_sel[-1]:.1f}秒)', flush=True)
    ok('3b adapt_select の結果は candidates 内', inc)
    ok('4 履歴で選出が変わる組>=1・決定性', diff >= 1 and det, f'違い{diff}/4 決定性={det}')
    # 5 q
    X = opps[0]
    cs = [tuple(o) for o in T[X]['candidates']]
    a_ = cs[0]
    b_ = next(c for c in cs if set(c) != set(a_))
    H = lambda seq: [{'n': i + 1, 'mine': [], 'theirs': list(c), 'res_for_A': 1} for i, c in enumerate(seq)]
    q3, _, _ = ad_q(L, X, H([a_, a_, a_]))
    q1, _, _ = ad_q(L, X, H([a_, a_, b_]))
    q2, _, _ = ad_q(L, X, H([b_, a_, a_]))
    q0, _, pr = ad_q(L, X, [])
    ok('5 q の性質', q3[a_] >= 0.6 and q1.get(b_, 0) > q2.get(b_, 0) and all(abs(q0[c] - pr[c]) < 1e-9 for c in pr) and len(q0) == len(pr),
       f'q(a)={q3[a_]:.2f} q(b) {q1.get(b_, 0):.3f}>{q2.get(b_, 0):.3f}')
    # 6 連続3回禁止
    tgt = tuple(T[L]['candidates'][5])
    _AD_EVAL = lambda o, c, smart: 100.0 if tuple(o) == tgt else -100.0
    try:
        oth = tuple(T[L]['candidates'][0])
        hh = lambda mines: [{'n': i + 1, 'mine': list(m), 'theirs': list(a_), 'res_for_A': 0.5} for i, m in enumerate(mines)]
        r_ban, w_ban = adapt_select(L, X, hh([tgt, tgt]))
        r_ok, _ = adapt_select(L, X, hh([oth, tgt]))
    finally:
        _AD_EVAL = None
    ok('6 連続3回禁止', tuple(r_ok) == tgt and tuple(r_ban) != tgt and w_ban['banned_streak'] == list(tgt), f'禁止時 {_ostr(r_ban)}')
    # 7 順序・再開（偽の対戦・偽の選出）
    def fake_select(A, Bid, hist):
        o = list(_TEAMS[A]['candidates'][len(hist) % 24])
        return o, {'src': 'fake', 'order': o, 'hist_len': len(hist)}

    def fake_play(args):
        seed = args[4]
        if seed in _FAKE_ERR:
            return {'res': None, 'error': 'fake'}
        return {'res': 1 if seed % 2 else -1, 'log': ['x'], 'faints': [(3, 0, 'ガブリアス', 'ミミッキュ')], 'left': [1, 0], 'turns': 7, 'judged': False}
    _AD_SELECT, _AD_PLAY = fake_select, fake_play
    _FAKE_ERR = set()
    D7 = os.path.join(D, 'fake')
    os.makedirs(D7, exist_ok=True)
    p7 = dict(plan)
    p7['opponents'] = opps[:3]
    p7['sel1'] = {k: v for k, v in plan['sel1'].items() if any(f'{L}|{x}' == k or f'{x}|{L}' == k for x in opps[:3])}
    safeio.write_json(os.path.join(D7, 'ad_plan.json'), p7)

    class R_:
        pass
    ra = R_()
    ra.out_dir, ra.procs, ra.max_games, ra.retry_errors = D7, 3, 7, False
    try:
        cmd_adapt_run(ra)
        g7 = json.load(open(os.path.join(D7, 'ad_games.json'), encoding='utf-8'))['games']
        n7 = len(g7)
        ra.max_games = 0
        cmd_adapt_run(ra)
        g7 = json.load(open(os.path.join(D7, 'ad_games.json'), encoding='utf-8'))['games']
        seq = all(all(f'ad:{x}|{k}' in g7 for k in range(10)) for x in opps[:3])
        why = all(g['why0']['hist_len'] == g['k'] and g['why1']['hist_len'] == g['k'] for g in g7.values())
        side = all((g['side0'] == L) == (g['k'] % 2 == 0) and g['seed'] == zlib.crc32(f'ad{g["opp"]}{g["k"]}'.encode()) for g in g7.values())
        ok('7a 順序・再開', n7 == 7 and len(g7) == 30 and seq and why and side, f'7戦で停止後{n7}→{len(g7)}戦 連続={seq} 履歴長={why} 側/seed={side}')
        D7b = os.path.join(D, 'fake_err')
        os.makedirs(D7b, exist_ok=True)
        safeio.write_json(os.path.join(D7b, 'ad_plan.json'), p7)
        _FAKE_ERR.add(ad_seed(opps[1], 3))
        ra.out_dir = D7b
        cmd_adapt_run(ra)
        gb = json.load(open(os.path.join(D7b, 'ad_games.json'), encoding='utf-8'))['games']
        stop = [k for k in range(10) if f'ad:{opps[1]}|{k}' in gb]
        ok_stop = stop == [0, 1, 2, 3] and gb[f'ad:{opps[1]}|3']['res'] is None and len(gb) == 24
        _FAKE_ERR.clear()
        ra.retry_errors = True
        cmd_adapt_run(ra)
        gb = json.load(open(os.path.join(D7b, 'ad_games.json'), encoding='utf-8'))['games']
        ok('7b エラーでペア停止・--retry-errors で続行', ok_stop and len(gb) == 30 and all(g['res'] is not None for g in gb.values()), f'停止時 k={stop}')
        # 10 report
        ra2 = R_()
        ra2.out_dir = D7
        cmd_adapt_report(ra2)
        md = open(os.path.join(D7, 'ADAPT.md'), encoding='utf-8').read()
        heads = ['## 1. 全体', '## 2. 戦を重ねるごとの推移', '## 3. 相手構築ごと', '## 4. 適応による選出の変化', '## 5. 勝てない相手トップ10', '## 6. L の選出別勝率', '## 7. 比較', '## 8. 設定']
        ok('10 report', all(h in md for h in heads), f'{len(md)}字')
    except SystemExit as e:
        ok('7/10 fake', False, str(e))
    except Exception:
        ok('7/10 fake', False, traceback.format_exc()[-500:])
    finally:
        _AD_SELECT, _AD_PLAY = adapt_select, R.blind_play
    # 9 所要時間
    if not a.quick:
        _AD['sel1'] = plan['sel1']
        X = opps[0]
        cs = [tuple(o) for o in T[X]['candidates']]
        ts = []
        for A_id, Bid, c in ((L, opps[0], cs[1]), (L, opps[1], tuple(T[opps[1]]['candidates'][2])), (opps[2], L, tuple(T[L]['candidates'][3]))):
            h = [{'n': n, 'mine': list(T[A_id]['candidates'][0]), 'theirs': list(c), 'res_for_A': 1} for n in (1, 2, 3)]
            t0 = time.time()
            adapt_select(A_id, Bid, h)
            ts.append(time.time() - t0)
        ok('9a adapt_select 時間（中央値<=15・最大<=30）', stt.median(ts) <= 15 and max(ts) <= 30, f'{[round(t, 1) for t in ts]}')
        h0 = [{'n': 1, 'mine': list(plan['sel1'][f'{L}|{X}']['order']), 'theirs': list(plan['sel1'][f'{X}|{L}']['order']), 'res_for_A': 1}]
        h1 = [{'n': 1, 'mine': list(plan['sel1'][f'{X}|{L}']['order']), 'theirs': list(plan['sel1'][f'{L}|{X}']['order']), 'res_for_A': 0}]
        r = _job_adapt((f'ad:{X}|1', X, 1, X, L, h1, h0))
        print(f"   実戦1戦(k=1) res={r.get('res')} {r.get('turns')}手 全体{r['sec']}秒（選出{r['sec_sel']}秒）" + (' 警告: 120秒超' if r['sec'] > 120 else ''), flush=True)
        ok('9b 実戦1戦が完走', r.get('res') is not None or r.get('judged') is not None, str(r.get('error'))[-200:])
    after = _sha_all()
    ok('8a 既存ファイルの sha256 不変', before == after, f'{len(before)}件')
    ok('8b 既定の場所に ad_* / ADAPT.md が無い', not any(os.path.exists(os.path.join(DEF_OUT, f)) for f in ('ad_plan.json', 'ad_games.json', 'ad_logs.jsonl')) and not os.path.exists(DEF_ADMD))
    print('\n結果:', 'すべて ○' if all(c for _, c in results) else '×あり: ' + ', '.join(n for n, c in results if not c))
    if not a.keep and not a.out_dir:
        shutil.rmtree(D, ignore_errors=True)
    else:
        print('残した:', D)


def cmd_adapt(a):
    {'plan': cmd_adapt_plan, 'run': cmd_adapt_run, 'report': cmd_adapt_report, 'selftest': cmd_adapt_selftest}[a.what](a)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('plan')
    p.add_argument('--tier', type=int, required=True, choices=[1, 2, 3])
    p.add_argument('--tier1-size', type=int, default=24)
    p.add_argument('--no-select', action='store_true')
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--force', action='store_true')
    p.add_argument('--out-dir')
    p.add_argument('--test-ids')
    p = sp.add_parser('run')
    p.add_argument('--max-games', type=int, default=0)
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--retry-errors', action='store_true')
    p.add_argument('--games-per-pair', type=int, default=2)
    p.add_argument('--out-dir')
    p = sp.add_parser('report')
    p.add_argument('--out-dir')
    p = sp.add_parser('selftest')
    p.add_argument('--quick', action='store_true')
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--out-dir')
    p = sp.add_parser('show')
    p.add_argument('id')
    p.add_argument('--out-dir')
    p = sp.add_parser('deny')
    p.add_argument('what', choices=['run', 'full', 'report', 'selftest'])
    p.add_argument('--part', choices=['r11', 'top2', 'all'], default='all')
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--retry-errors', action='store_true')
    p.add_argument('--max-games', type=int, default=0)
    p.add_argument('--out-dir')
    p = sp.add_parser('adapt')
    p.add_argument('what', choices=['plan', 'run', 'report', 'selftest'])
    p.add_argument('--main', default=AD_MAIN)
    p.add_argument('--n-opp', type=int, default=50)
    p.add_argument('--games', type=int, default=10)
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--force', action='store_true')
    p.add_argument('--max-games', type=int, default=0)
    p.add_argument('--retry-errors', action='store_true')
    p.add_argument('--quick', action='store_true')
    p.add_argument('--keep', action='store_true')
    p.add_argument('--out-dir')
    a = ap.parse_args()
    {'adapt': cmd_adapt, 'deny': cmd_deny, 'plan': cmd_plan, 'run': cmd_run, 'report': cmd_report, 'selftest': cmd_selftest, 'show': cmd_show}[a.cmd](a)


if __name__ == '__main__':
    main()
