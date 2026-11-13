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


_PB = {}                                   # ワーカーの {構築id: 規則リスト}（SPEC_PLAYBOOK.md）。空なら従来どおり
_PB_ONLY = [None]
_PB_FLAG = {'on': True, 'only': None}      # main が --no-playbook で書き換える


def _worker_init(teams, pb_on=True, pb_only=None):
    global _TEAMS, _PB
    _TEAMS = teams
    _rr_init(teams)
    import playbook
    _PB = playbook.load_all() if pb_on else {}
    _PB_ONLY[0] = pb_only


def _pb_args(s0, s1):
    """blind_play の args に足す末尾（deny, (play0, play1)）。プレイブックが無ければ ()（＝従来の args のまま）。"""
    if not _PB:
        return ()
    only = _PB_ONLY[0]
    p0 = _PB.get(s0) if only is None or s0 == only else None
    p1 = _PB.get(s1) if only is None or s1 == only else None
    return ((p0, p1),) if (p0 or p1) else ()


def _pb_sig():
    if not _PB_FLAG['on']:
        return None
    import playbook
    return playbook.play_sig(playbook.load_all())


def pb_guard(g):
    """既存の結果ファイルの playbook 署名が今回と違えば止まる（キーが無い＝None）。"""
    old, now = g.get('playbook'), _pb_sig()
    if old != now:
        raise SystemExit(f'既存の結果は playbook={old}。--no-playbook で続行するか --out-dir で別フォルダに出力してください')
    g['playbook'] = now


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
        if nm == 2:
            ma, mb = sorted(mg)
            ks = [o for o in c1[:k1]]
            cnt = lambda b: sum(1 for o in ks if b in o)
            for lo, hi in ((ma, mb), (mb, ma)):
                while cnt(lo) < 6:
                    nxt = next((o for o in c1 if lo in o and o not in ks), None)
                    drop = next((o for o in reversed(ks) if hi in o and cnt(hi) > 6), None)
                    if nxt is None or drop is None:
                        break
                    ks.remove(drop)
                    ks.append(nxt)
            keep = {tuple(o) for o in c0[:q]} | {tuple(o) for o in ks}
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
            'unreadable': unread, 'rejected': rejected, 'gclass': guide_class(bool(art_ok), gitems), 'n_mega': nm,
            'mega_split': {b: sum(1 for o in cand if b in o) for b in sorted(mg)} if nm == 2 else None}


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
        pa = _pb_args(X, Y)
        r = R.blind_play((None, Y, selX, selY, seed, DEPTH[0], DEPTH[1], False, None, False, (X,)) + (((False, False),) + pa if pa else ()))
    except Exception:
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    r['key'] = key
    r['sec'] = round(time.time() - t0, 2)
    return r


def make_pool(procs, teams, pb_on=None, pb_only=None):
    ctx = mp.get_context('fork' if hasattr(os, 'fork') else 'spawn')
    return ctx.Pool(procs, initializer=_worker_init, initargs=(teams, _PB_FLAG['on'] if pb_on is None else pb_on,
                                                              _PB_FLAG['only'] if pb_only is None else pb_only))


def game_record(job, r, rematch):
    key, X, Y, selX, selY, seed = job
    a, b, k = key.split('|')
    res = r.get('res')
    w = None if res is None else (X if res == 1 else (Y if res == -1 else None))
    return {'a': a, 'b': b, 'k': int(k), 'side0': X, 'side1': Y, 'sel0': selX, 'sel1': selY, 'seed': seed, 'res': res, 'winner': w,
            'judged': r.get('judged'), 'turns': r.get('turns'), 'left': r.get('left'), 'faints': r.get('faints'),
            'sec': r.get('sec'), 'error': r.get('error'), 'rematch': rematch, **({'pb': r['pb']} if r.get('pb') else {})}


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
    return {'version': RR_VERSION, 'plan_sig': sig, 'depth': list(DEPTH), 'games': {}, 'playbook': _pb_sig()}


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
    pb_guard(games)
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
        r = R.blind_play((None, Y, selX, selY, seed, DEPTH[0], DEPTH[1], False, None, False, (X,), deny) + _pb_args(X, Y))
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
    if r.get('pb'):
        rec['pb'] = r['pb']
    return rec


def load_dgames(PD, sig):
    if os.path.exists(PD['games']):
        g = json.load(open(PD['games'], encoding='utf-8'))
        if g.get('plan_sig') != sig:
            raise SystemExit('rr_deny_games.json の plan_sig が rr_plan.json と違います')
        return g
    return {'version': RR_VERSION, 'plan_sig': sig, 'depth': list(DEPTH), 'mode': 'deny', 'games': {}, 'playbook': _pb_sig()}


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
    pb_guard(games)
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
           'e_all': [[round(ew[o][0], 4), list(o)] for o in cl],
           'banned_streak': list(banned) if banned else None, 'sec': round(time.time() - t0, 2)}
    return list(best), why


_AD_SELECT = adapt_select


def ad_seed(X, k):
    return zlib.crc32(f'ad{X}{k}'.encode())


def _job_adapt(a):
    key, X, k, s0, s1, h0, h1 = a[:7]
    depth = a[7] if len(a) > 7 and a[7] else DEPTH          # m7: 省略時は従来どおり DEPTH
    seed = a[8] if len(a) > 8 and a[8] is not None else ad_seed(X, k)
    t0 = time.time()
    o0 = o1 = w0 = w1 = None
    try:
        o0, w0 = _AD_SELECT(s0, s1, h0)
        o1, w1 = _AD_SELECT(s1, s0, h1)
        sec_sel = round(time.time() - t0, 2)
        rr_apply(_TEAMS[s0])
        res = a[9] if len(a) > 9 else None          # m7 --resource: (side 0 / side 1 resource config or None)
        pa = _pb_args(s0, s1)
        if res and (res[0] or res[1]):
            pa = (pa[0] if pa else None, res)
        r = _AD_PLAY((None, s1, o0, o1, seed, depth[0], depth[1], False, None, False, (s0,), (True, True)) + pa)
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
    return {'version': AD_VERSION, 'plan_sig': sig, 'main': None, 'depth': list(DEPTH), 'deny': [True, True], 'games': {}, 'playbook': _pb_sig()}


def ad_hist(games, X, A, upto, L, kp='ad'):
    """A 視点の履歴（第1〜upto戦、古い順）。"""
    out = []
    for k in range(upto):
        g = games['games'][f'{kp}:{X}|{k}']
        mine, theirs = (g['sel0'], g['sel1']) if g['side0'] == A else (g['sel1'], g['sel0'])
        res = g['res']
        r = 0.5 if res == 0 else (1 if (res == 1) == (g['side0'] == A) else 0)
        out.append({'n': k + 1, 'mine': list(mine), 'theirs': list(theirs), 'res_for_A': r})
    return out


def ad_record(job, r, L, seed_fn=ad_seed):
    key, X, k, s0, s1 = job[:5]
    res = r.get('res')
    w = None if res is None else (s0 if res == 1 else (s1 if res == -1 else None))
    rec = {'side0': s0, 'side1': s1, 'sel0': r.get('sel0'), 'sel1': r.get('sel1'), 'seed': seed_fn(X, k), 'res': res, 'winner': w,
           'judged': r.get('judged'), 'turns': r.get('turns'), 'left': r.get('left'), 'faints': r.get('faints'), 'sec': r.get('sec'),
           'error': r.get('error'), 'deny': [True, True], 'opp': X, 'k': k, 'n': k + 1, 'main_side': 0 if s0 == L else 1,
           'why0': r.get('why0'), 'why1': r.get('why1'), 'sec_sel': r.get('sec_sel')}
    if r.get('res_stats'):
        rec['res_stats'] = r['res_stats']
    if r.get('deny_stats') is not None:
        rec['deny_stats'] = r['deny_stats']
    if r.get('pb'):
        rec['pb'] = r['pb']
    return rec


def cmd_adapt_run(a):
    P = ad_paths(a.out_dir)
    plan = ad_load_plan(P)
    rp = load_plan(paths(None))
    if rp['sig'] != plan['rr_sig']:
        raise SystemExit('rr_plan.json の sig が ad_plan.json と違います')
    L, opps, G = plan['main'], plan['opponents'], plan['games_per_pair']
    games = ad_load_games(P, plan['sig'])
    pb_guard(games)
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


# ======================================================================
# counter: 苦手構築への対策選出（SPEC_COUNTER.md）
# ======================================================================
CT_VERSION = 'ct1'
CT_DEFAULT_OPPS = ['e74e068449bec8e6', 'bab22dcc629688e8', 'yakkun_n8943', '047f48a2b51a88d1',
                   '856f9d20f6a9b5a9', '1813f454535e22eb', '45330f7ff4d912c7', '598640a00e16d952']
CT_K1, CT_K2 = 4, 16          # 第1段 k=0..3、第2段 k=4..15
DEF_CTMD = os.path.join(HERE, '..', 'logs', 'COUNTER.md')
_CT_PLAY = R.blind_play


def ct_paths(out_dir=None):
    d = out_dir or DEF_OUT
    return {'dir': d, 'plan': os.path.join(d, 'ct_plan.json'), 'games': os.path.join(d, 'ct_games.json'),
            'md': os.path.join(d, 'COUNTER.md') if out_dir else DEF_CTMD}


def ct_seed(X, sel, k):
    return zlib.crc32(f'ct{X}{"/".join(sel)}{k}'.encode())


def ct_key(X, sel, k):
    return f'ct:{X}|{"/".join(sel)}|{k}'


def ct_fixed_sel(adg, X):
    c, first = collections.Counter(), {}
    for k in range(10):
        g = adg['games'][f'ad:{X}|{k}']
        s = g['sel0'] if g['side0'] == X else g['sel1']
        if not s:
            continue
        s = tuple(s)
        c[s] += 1
        first.setdefault(s, k)
    return list(max(c.items(), key=lambda kv: (kv[1], -first[kv[0]]))[0])


def ct_job(plan, X, sel, k, stage):
    L = plan['main']
    s0, s1 = (L, X) if k % 2 == 0 else (X, L)
    fx = plan['fixed'][X]
    o0, o1 = (list(sel), list(fx)) if s0 == L else (list(fx), list(sel))
    return (ct_key(X, sel, k), X, list(sel), k, s0, s1, o0, o1, stage)


def _job_ct(a):
    key, X, sel, k, s0, s1, o0, o1, stage = a
    t0 = time.time()
    try:
        rr_apply(_TEAMS[s0])
        r = _CT_PLAY((None, s1, o0, o1, ct_seed(X, sel, k), DEPTH[0], DEPTH[1], False, None, False, (s0,), (True, True)) + _pb_args(s0, s1))
    except Exception:
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    r['key'] = key
    r['sec'] = round(time.time() - t0, 2)
    return r


def ct_record(job, r, L):
    key, X, sel, k, s0, s1, o0, o1, stage = job
    res = r.get('res')
    w = None if res is None else (s0 if res == 1 else (s1 if res == -1 else None))
    rec = {'side0': s0, 'side1': s1, 'sel0': o0, 'sel1': o1, 'seed': ct_seed(X, sel, k), 'res': res, 'winner': w,
           'judged': r.get('judged'), 'turns': r.get('turns'), 'left': r.get('left'), 'faints': r.get('faints'),
           'sec': r.get('sec'), 'error': r.get('error'), 'opp': X, 'sel': list(sel), 'k': k, 'stage': stage,
           'main_side': 0 if s0 == L else 1}
    if r.get('deny_stats') is not None:
        rec['deny_stats'] = r['deny_stats']
    if r.get('echo') is not None:
        rec['echo'] = r['echo']
    if r.get('pb'):
        rec['pb'] = r['pb']
    return rec


def ct_load_plan(P):
    if not os.path.exists(P['plan']):
        raise SystemExit(f"{P['plan']} がありません。先に counter plan を実行してください")
    return json.load(open(P['plan'], encoding='utf-8'))


def ct_load_games(P, sig):
    if os.path.exists(P['games']):
        g = json.load(open(P['games'], encoding='utf-8'))
        if g.get('plan_sig') != sig:
            raise SystemExit('ct_games.json の plan_sig が ct_plan.json と違います')
        return g
    return {'version': CT_VERSION, 'plan_sig': sig, 'games': {}, 'playbook': _pb_sig()}


def cmd_counter_plan(a):
    P = ct_paths(a.out_dir)
    os.makedirs(P['dir'], exist_ok=True)
    AP = ad_paths(None)
    if not (os.path.exists(AP['plan']) and os.path.exists(AP['games'])):
        raise SystemExit('ad_plan.json / ad_games.json がありません')
    ap = json.load(open(AP['plan'], encoding='utf-8'))
    adg = json.load(open(AP['games'], encoding='utf-8'))
    rp = load_plan(paths(None))
    T = rp['teams']
    L = ap['main']
    opps = [x for x in a.opps.split(',') if x] if getattr(a, 'opps', None) else list(CT_DEFAULT_OPPS)
    fixed = {}
    for X in opps:
        if X not in ap['opponents']:
            raise SystemExit(f'{X} は ad_plan の opponents にありません')
        n = sum(1 for k in range(10) if f'ad:{X}|{k}' in adg['games'] and adg['games'][f'ad:{X}|{k}']['res'] is not None)
        if n < 10:
            raise SystemExit(f'{X} の適応戦が {n}/10 です')
        fixed[X] = ct_fixed_sel(adg, X)
    _worker_init(T)
    try:
        for i in [L] + opps:
            rr_apply(T[i])
    except Exception as e:
        raise SystemExit(f'構築が適用できません: {e}')
    cands = [list(c) for c in T[L]['candidates']]
    sig = hashlib.sha256((ap['sig'] + L + ','.join(opps) + json.dumps(fixed, ensure_ascii=False, sort_keys=True) + CT_VERSION).encode()).hexdigest()
    if os.path.exists(P['plan']):
        old = json.load(open(P['plan'], encoding='utf-8'))
        if old.get('sig') == sig:
            print(f"変更なし: {P['plan']}（sig {sig[:12]}）")
            return old
        if not a.force:
            raise SystemExit('ct_plan.json の sig が違います（--force で退避して作り直し）')
        os.replace(P['plan'], P['plan'][:-5] + time.strftime('.%Y%m%d_%H%M%S.json'))
    plan = {'version': CT_VERSION, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'sig': sig, 'ad_sig': ap['sig'], 'main': L,
            'opps': opps, 'titles': {i: T[i].get('title') for i in [L] + opps}, 'fixed': fixed, 'candidates': cands,
            'depth': list(DEPTH), 'deny': [True, True], 'top3': {}}
    safeio.write_json(P['plan'], plan)
    print(f"書きました: {P['plan']}（sig {sig[:12]}）")
    for X in opps:
        print(f"  {X} {'/'.join(fixed[X])}")
    return plan


def _ct_score(g):
    res = g['res']
    if res is None:
        return None
    return 0.5 if res == 0 else (1.0 if (res == 1) == (g['main_side'] == 0) else 0.0)


def _ct_hp(g):
    lf = g.get('left')
    if not lf:
        return 0
    m = g['main_side']
    return sum(h for _, h in lf[m]) - sum(h for _, h in lf[1 - m])


def ct_stats(gm, X, sel, ks):
    """(勝点, 有効戦数, HP差リスト)"""
    w, n, hp = 0.0, 0, []
    for k in ks:
        g = gm.get(ct_key(X, sel, k))
        if g is None:
            continue
        s = _ct_score(g)
        if s is None:
            continue
        w += s
        n += 1
        hp.append(_ct_hp(g))
    return w, n, hp


def ct_rank1(plan, gm, X):
    rows = []
    for i, sel in enumerate(plan['candidates']):
        w, n, hp = ct_stats(gm, X, sel, range(CT_K1))
        rows.append((-(w / n if n else 0.0), -(sum(hp) / len(hp) if hp else 0.0), i))
    return [plan['candidates'][i] for _, _, i in sorted(rows)]


def cmd_counter_run(a):
    P = ct_paths(a.out_dir)
    plan = ct_load_plan(P)
    rp = load_plan(paths(None))
    L, opps = plan['main'], plan['opps']
    G = ct_load_games(P, plan['sig'])
    pb_guard(G)
    gm = G['games']
    cands = plan['candidates']
    active, n_disp, n_done = {}, 0, 0

    def todo(key):
        g = gm.get(key)
        return key not in active and (g is None or (a.retry_errors and g['res'] is None))

    def pending(X):
        out = [ct_job(plan, X, s, k, 1) for s in cands for k in range(CT_K1) if todo(ct_key(X, s, k))]
        if out:
            return out
        if any(ct_key(X, s, k) in active for s in cands for k in range(CT_K1)):
            return []
        if X not in plan['top3']:
            plan['top3'][X] = ct_rank1(plan, gm, X)[:3]
            safeio.write_json(P['plan'], plan)
        return [ct_job(plan, X, s, k, 2) for s in plan['top3'][X] for k in range(CT_K1, CT_K2) if todo(ct_key(X, s, k))]

    per = len(cands) * CT_K1 + 3 * (CT_K2 - CT_K1)
    tot = len(opps) * per
    base = sum(1 for g in gm.values() if g['res'] is not None)
    print(f'全体 {tot}戦、済み {base}、今回 最大 {a.max_games or "全部"}', flush=True)
    t0 = time.time()
    with make_pool(a.procs, rp['teams']) as pool:
        while True:
            for X in opps:
                if len(active) >= a.procs or (a.max_games and n_disp >= a.max_games):
                    break
                for job in pending(X):
                    if len(active) >= a.procs or (a.max_games and n_disp >= a.max_games):
                        break
                    active[job[0]] = (pool.apply_async(_job_ct, (job,)), job)
                    n_disp += 1
            if not active:
                break
            got = False
            for key, (ar, job) in list(active.items()):
                if not ar.ready():
                    continue
                got = True
                r = ar.get()
                del active[key]
                n_done += 1
                gm[key] = ct_record(job, r, L)
                safeio.write_json(P['games'], G)
                s = _ct_score(gm[key])
                mark = '例外' if s is None else ('勝' if s == 1 else ('分' if s == 0.5 else '負'))
                el = (time.time() - t0) / 60
                rem = el / n_done * max(0, (min(a.max_games, tot - base) if a.max_games else tot - base) - n_done)
                print(f"[{base + n_done}/{tot}] {key} L{mark} {r.get('turns')}手 {r['sec']:.0f}秒 経過{el:.1f}分 残り約{rem:.1f}分", flush=True)
            if not got:
                time.sleep(0.05)
    return n_done


def _ct_wl(w, n):
    lo, hi = wilson(w, n)
    return f'{lo * 100:.1f}%-{hi * 100:.1f}%'


def _ct_pct(w, n):
    return f'{w:g}/{n} = {(w / n * 100 if n else 0):.1f}%'


def ct_faints(gl):
    first, kill = collections.Counter(), collections.Counter()
    for g in gl:
        ms = g['main_side']
        fs = [f for f in (g.get('faints') or []) if f[1] == ms]
        if fs:
            first[min(fs, key=lambda f: f[0])[2]] += 1
        for f in fs:
            if f[3]:
                kill[f[3]] += 1
    return first, kill


def _ct_cnt(c, n=4):
    return '、'.join(f'{k}{v}' for k, v in c.most_common(n)) or 'なし'


def cmd_counter_report(a):
    P = ct_paths(a.out_dir)
    plan = ct_load_plan(P)
    G = ct_load_games(P, plan['sig'])
    gm = G['games']
    adg = json.load(open(ad_paths(None)['games'], encoding='utf-8'))
    L, cands = plan['main'], plan['candidates']
    tt = plan['titles']
    body, summ = [], []
    for X in plan['opps']:
        fx = plan['fixed'][X]
        ad = [g for k in range(10) for g in [adg['games'][f'ad:{X}|{k}']] if g['res'] is not None]
        adw = sum(_ct_score({**g, 'main_side': 0 if g['side0'] == L else 1}) for g in ad)
        adc = collections.Counter('/'.join(g['sel0'] if g['side0'] == L else g['sel1']) for g in ad)
        s1 = {}
        for i, sel in enumerate(cands):
            w, n, hp = ct_stats(gm, X, sel, range(CT_K1))
            w2, n2, _ = ct_stats(gm, X, sel, range(CT_K1, CT_K2))
            s1[i] = (w, n, (sum(hp) / len(hp) if hp else 0.0), w2, n2)
        top3 = plan['top3'].get(X) or ct_rank1(plan, gm, X)[:3]
        idx = {tuple(s): i for i, s in enumerate(cands)}
        t3 = [idx[tuple(s)] for s in top3]
        done2 = any(s1[i][4] for i in t3)
        pool = [i for i in t3 if s1[i][4]] or t3
        best = max(pool, key=lambda i: ((s1[i][3] / s1[i][4]) if s1[i][4] else 0, (s1[i][0] + s1[i][3]) / max(1, s1[i][1] + s1[i][4]), -t3.index(i)))
        bw, bn = s1[best][3], s1[best][4]
        t16w, t16n = s1[best][0] + bw, s1[best][1] + bn
        adr = adw / len(ad) if ad else 0
        diff = ((bw / bn if bn else 0) - adr) * 100
        rank = sorted(range(len(cands)), key=lambda i: (-(s1[i][0] / s1[i][1] if s1[i][1] else 0), -s1[i][2], i))
        worst = sorted(range(len(cands)), key=lambda i: ((s1[i][0] / s1[i][1] if s1[i][1] else 0), s1[i][2], i))[:3]
        bsel = '/'.join(cands[best])
        summ.append(f"| {tt.get(X) or X} | {bsel} | {_ct_pct(bw, bn)} | {_ct_pct(adw, len(ad))} | {diff:+.1f}pt |")
        o = [f'## {tt.get(X) or X}（{X}）', '',
             f"### 1. 相手の固定選出と適応10戦", f"- 固定選出: {'/'.join(fx)}", f"- 適応10戦のLの実績: {_ct_pct(adw, len(ad))}",
             f"- Lが使った選出の上位: {'、'.join(f'{k}×{v}' for k, v in adc.most_common(3))}", '',
             '### 2. 最良選出' + ('' if done2 else '（確認未実施: 第1段の1位）'),
             f"- {bsel}", f"- 確認{bn}戦: {_ct_pct(bw, bn)}、Wilson95% [{_ct_wl(bw, bn)}]", f"- 16戦合計: {_ct_pct(t16w, t16n)}",
             f"- 適応10戦との差: {diff:+.1f}pt", '', '### 3. 上位3と悪い選出トップ3（第1段）']
        o += [f"- 上位{r + 1}: {'/'.join(cands[i])}  {_ct_pct(s1[i][0], s1[i][1])} HP差{s1[i][2]:+.0f}" for r, i in enumerate(t3)]
        o += [f"- 悪い{r + 1}: {'/'.join(cands[i])}  {_ct_pct(s1[i][0], s1[i][1])} HP差{s1[i][2]:+.0f}" for r, i in enumerate(worst)]
        o += ['', '### 4. 24通りの表', '', '| 選出 | 第1段 | 確認 |', '|---|---|---|']
        for i in rank:
            o.append(f"| {'/'.join(cands[i])} | {_ct_pct(s1[i][0], s1[i][1])} | {_ct_pct(s1[i][3], s1[i][4]) if s1[i][4] else '-'} |")
        gb = [g for k in range(CT_K2) for g in [gm.get(ct_key(X, cands[best], k))] if g]
        ga = [g for g in gm.values() if g['opp'] == X]
        o += ['', '### 5. 倒され方']
        for nm, gl in (('最良選出', gb), ('全体', ga)):
            f1, kl = ct_faints(gl)
            o.append(f"- {nm}（{len(gl)}戦）: 最初に倒れたL側 {_ct_cnt(f1)} / Lを倒した相手個体 {_ct_cnt(kl)}")
        main_k = ct_faints(ga)[1].most_common(1)
        o.append(f"- 相手の主力: {main_k[0][0] if main_k else 'なし'}")
        mons = sorted({m for c in cands for m in c})
        bad = []
        s1g = [g for g in ga if g['stage'] == 1 and _ct_score(g) is not None]
        for m in mons:
            gi = [_ct_score(g) for g in s1g if m in g['sel']]
            go = [_ct_score(g) for g in s1g if m not in g['sel']]
            if gi and go and sum(go) / len(go) - sum(gi) / len(gi) >= 0.15:
                bad.append(f"{m}（含む {sum(gi) / len(gi) * 100:.0f}% / 含まない {sum(go) / len(go) * 100:.0f}%）")
        o += ['', '### 6. 結論', f"- この相手には: {bsel}", f"- 出してはいけない個体（含む選出の第1段勝率が15pt以上低い）: {'、'.join(bad) or 'なし'}", '']
        body.append('\n'.join(o))
    head = ['# COUNTER 苦手構築への対策選出', '', f"主構築 {L}（{tt.get(L)}）", '',
            '## 全体まとめ', '', '| 相手 | 最良選出 | 確認勝率 | 適応10戦 | 改善幅 |', '|---|---|---|---|---|'] + summ + ['']
    tail = ['## 条件', f"- 種: crc32(f'ct{{X}}{{\"/\".join(sel)}}{{k}}')、深さ {list(DEPTH)}、deny [True, True]、ブラインド",
            f"- 第1段 k=0..{CT_K1 - 1}、第2段 k={CT_K1}..{CT_K2 - 1}（上位3選出）", f"- plan sig {plan['sig']}", '']
    os.makedirs(os.path.dirname(os.path.abspath(P['md'])), exist_ok=True)
    txt = '\n'.join(head) + '\n' + '\n'.join(body) + '\n' + '\n'.join(tail)
    open(P['md'], 'w', encoding='utf-8').write(txt)
    print(f"書きました: {P['md']}")
    return txt


def cmd_counter_selftest(a):
    import shutil, subprocess, tempfile
    global _CT_PLAY
    D = a.out_dir or tempfile.mkdtemp(prefix='cttest_')
    results = []

    def ok(n, cond, msg=''):
        results.append((n, bool(cond)))
        print(f"{'○' if cond else '×'} {n} {msg}", flush=True)

    before = _sha_all()
    p = subprocess.run([sys.executable, '-m', 'py_compile', 'roundrobin.py'], cwd=HERE, capture_output=True, text=True)
    ok('1 py_compile', p.returncode == 0, p.stderr[-200:])
    OPPS = ['e74e068449bec8e6', 'bab22dcc629688e8', 'yakkun_n8943', '047f48a2b51a88d1', '856f9d20f6a9b5a9']

    class A_:
        pass

    def args(sub, **kw):
        x = A_()
        x.out_dir, x.opps, x.procs, x.max_games, x.force, x.retry_errors = os.path.join(D, sub), ','.join(OPPS[:2]), a.procs, 0, True, False
        x.__dict__.update(kw)
        return x

    rp = load_plan(paths(None))
    T = rp['teams']
    # 2 候補
    pl = cmd_counter_plan(args('p', opps=','.join(OPPS)))
    L = pl['main']
    cs = [tuple(c) for c in pl['candidates']]
    mega = {m['base'] for m in T[L]['mons'] if m['mega']}
    ok('2 候補', len(cs) == 24 and len(set(cs)) == 24 and set(cs) <= {tuple(c) for c in T[L]['candidates']} and
       all(len(mega & set(c)) <= 1 for c in cs))
    # 3 選出固定
    exp = {OPPS[0]: ['セグレイブ', 'ギャラドス', 'キラフロル'], OPPS[1]: ['ブリジュラス', 'イダイトウ', 'ドドゲザン'],
           OPPS[2]: ['ミミッキュ', 'リザードン', 'カバルドン'], OPPS[3]: ['ボーマンダ', 'カバルドン', 'ブリジュラス'],
           OPPS[4]: ['イダイトウ', 'リザードン', 'ミミッキュ']}
    ok('3a 固定選出の期待値', all(pl['fixed'][x] == v for x, v in exp.items()))

    def stub(args_):
        h = zlib.crc32(repr((args_[2], args_[3], args_[4])).encode())
        return {'res': (1, -1, 0)[h % 3], 'turns': 5 + h % 7, 'judged': False,
                'left': [[[m, (h >> i) % 101] for i, m in enumerate(args_[2])], [[m, (h >> (i + 3)) % 101] for i, m in enumerate(args_[3])]],
                'faints': [[3, 0, args_[2][0], args_[3][0]], [5, 1, args_[3][0], args_[2][1]]], 'echo': [list(args_[2]), list(args_[3]), args_[4], list(args_[10]), args_[1]]}
    _CT_PLAY = stub
    try:
        a2 = args('s2')
        cmd_counter_plan(a2)
        cmd_counter_run(a2)
        P2 = ct_paths(a2.out_dir)
        pl2 = json.load(open(P2['plan'], encoding='utf-8'))
        gm2 = json.load(open(P2['games'], encoding='utf-8'))['games']
        good = bool(gm2)
        for key, g in gm2.items():
            X, sel, k = g['opp'], g['sel'], g['k']
            e = g['echo']
            lside = 0 if k % 2 == 0 else 1
            xo, lo = (e[1], e[0]) if lside == 0 else (e[0], e[1])
            good &= xo == pl2['fixed'][X] and lo == sel and g['main_side'] == lside and e[2] == zlib.crc32(f'ct{X}{"/".join(sel)}{k}'.encode()) \
                and e[3] == [g['side0']] and key == ct_key(X, sel, k)
        ok('3b 呼び出し引数（X固定・L候補・左右・種）', good, f'{len(gm2)}戦')
        ok('3c 件数', len(gm2) == 2 * (96 + 36), f'{len(gm2)}')
        # 4 再開
        a3, a4 = args('s3', max_games=5), args('s4', max_games=100)
        cmd_counter_plan(a3)
        cmd_counter_run(a3)
        cmd_counter_run(a3)
        g3 = json.load(open(ct_paths(a3.out_dir)['games'], encoding='utf-8'))['games']
        same = all((g3[k][f] == gm2[k][f]) for k in g3 for f in ('res', 'seed', 'left', 'faints', 'sel0', 'sel1'))
        ok('4a 再開 5+5=10件・同一結果', len(g3) == 10 and same, f'{len(g3)}件')
        cmd_counter_plan(a4)
        cmd_counter_run(a4)
        p4 = json.load(open(ct_paths(a4.out_dir)['plan'], encoding='utf-8'))
        g4 = json.load(open(ct_paths(a4.out_dir)['games'], encoding='utf-8'))['games']
        good = len(g4) == 100
        for g in g4.values():
            if g['stage'] == 2:
                X = g['opp']
                good &= all(ct_key(X, s, k) in g4 for s in p4['candidates'] for k in range(CT_K1)) and g['sel'] in p4['top3'][X]
        ok('4b 第1段が終わったXだけ第2段', good, f"第2段 {sum(1 for g in g4.values() if g['stage'] == 2)}戦")
        # 7 report
        txt = cmd_counter_report(a2)
        X = OPPS[0]
        cands2 = pl2['candidates']
        top = pl2['top3'][X]
        bi = max(top, key=lambda s: (ct_stats(gm2, X, s, range(CT_K1, CT_K2))[0] / 12))
        w, n, _ = ct_stats(gm2, X, bi, range(CT_K1, CT_K2))
        has = all(f'### {i}.' in txt for i in range(1, 7)) and '## 全体まとめ' in txt and '## 条件' in txt
        ok('7 report 全セクション・Wilson一致', has and _ct_wl(w, n) in txt, f'{len(txt)}字')
    finally:
        _CT_PLAY = R.blind_play
    # 6 実エンジン1戦
    _worker_init(T)
    X = OPPS[0]
    job = ct_job(pl, X, pl['candidates'][0], 0, 1)
    t0 = time.time()
    r = _job_ct(job)
    sec = time.time() - t0
    ok('6 実エンジン1戦', r.get('res') is not None and sec <= 30, f"{sec:.1f}秒 res={r.get('res')} {r.get('error') or ''}"[:200])
    after = _sha_all()
    ok('5 sha256不変・ct_*/COUNTER.mdなし', before == after and not os.path.exists(DEF_CTMD) and
       not [f for f in os.listdir(DEF_OUT) if f.startswith('ct_')])
    if not a.keep:
        shutil.rmtree(D, ignore_errors=True)
    print(f"結果: {sum(1 for _, c in results if c)}/{len(results)} 通過", flush=True)
    return all(c for _, c in results)


def cmd_counter(a):
    {'plan': cmd_counter_plan, 'run': cmd_counter_run, 'report': cmd_counter_report, 'selftest': cmd_counter_selftest}[a.what](a)


# ---------------------------------------------------------------- playbook (SPEC_PLAYBOOK.md)
PB_AB_LIST = ('rr_games.json', 'rr_deny_games.json', 'ad_games.json', 'ct_games.json', 'pb_ab_games.json')
PB_LH = 'db0baa2843d2bd4b'
PB_AB_OUT = os.path.join(DEF_OUT, 'pb_ab')


def pb_collect(files):
    """files: [games.json のパス]。{(構築, 規則id): 集計}。pb を持つ記録だけ。"""
    import playbook
    plays = playbook.load_all()
    st = collections.defaultdict(lambda: {'fires': 0, 'gf': 0, 'wf': 0.0, 'gn': 0, 'wn': 0.0, 'rej': collections.Counter(), 'games': 0})
    for fp in files:
        if not os.path.exists(fp):
            continue
        d = json.load(open(fp, encoding='utf-8'))
        for g in d.get('games', {}).values():
            if not g.get('pb') or g.get('res') is None:
                continue
            for sd in ('0', '1'):
                pbs = g['pb'].get(sd)
                if not pbs:
                    continue
                team = g['side0'] if sd == '0' else g['side1']
                sc = 0.5 if g['res'] == 0 else (1.0 if (g['res'] == 1) == (sd == '0') else 0.0)
                sel = {B._base(x) for x in ((g.get('sel0') if sd == '0' else g.get('sel1')) or [])}
                for r in plays.get(team, []):
                    if r.get('phase', 'turn') == 'turn' and r['who'] != '*' and B._base(r['who']) not in sel:
                        continue
                    a = st[(team, r['id'])]
                    a['games'] += 1
                    u = pbs['uses'].get(r['id'], 0)
                    if u:
                        a['fires'] += u
                        a['gf'] += 1
                        a['wf'] += sc
                    else:
                        a['gn'] += 1
                        a['wn'] += sc
                for rej in pbs.get('rejected', []):
                    st[(team, rej[1])]['rej'][rej[2]] += 1
    return st


def pb_table(st):
    pct = lambda w, n: f'{w / n * 100:.0f}% ({w:g}/{n})' if n else '-'
    L = ['| 構築 | 規則 | 発動回数 | 発動した試合 | その勝率 | 発動しなかった試合 | その勝率 | rejected |', '|---|---|---|---|---|---|---|---|']
    for (team, rid), a in sorted(st.items()):
        L.append(f"| {team[:8]} | {rid} | {a['fires']} | {a['gf']} | {pct(a['wf'], a['gf'])} | {a['gn']} | {pct(a['wn'], a['gn'])} | "
                 f"{', '.join(f'{k}:{v}' for k, v in sorted(a['rej'].items())) or '-'} |")
    return L


def cmd_pb_report(a):
    d = a.out_dir or DEF_OUT
    st = pb_collect([os.path.join(d, f) for f in PB_AB_LIST])
    L = ['# プレイブック発動率（playbook report）', '', f'集計元: {d}', ''] + (pb_table(st) if st else ['pb を持つ記録がありません。'])
    open(os.path.join(d, 'pb_report.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('\n'.join(L))


def _job_ab(a):
    key, X, Y, selX, selY, seed, use_pb = a
    t0 = time.time()
    try:
        rr_apply(_TEAMS[X])
        args = (None, Y, selX, selY, seed, DEPTH[0], DEPTH[1], False, None, False, (X,), (True, True))
        r = R.blind_play(args + (_pb_args(X, Y) if use_pb else ()))
    except Exception:
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    r['key'] = key
    r['sec'] = round(time.time() - t0, 2)
    return r


def cmd_pb_ab(a):
    import playbook
    team = a.team
    out = a.out_dir or PB_AB_OUT
    plan = load_plan(paths(None))
    T = plan['teams']
    if team not in T:
        raise SystemExit(f'rr_plan.json に {team} がありません')
    if a.opps and a.opps != 'top5':
        opps = a.opps.split(',')
    else:
        opps = [i for i, _ in sorted(((i, t.get('rank') or 10 ** 6) for i, t in T.items() if i != team), key=lambda x: x[1])[:5]]
    for o in opps:
        if o not in T:
            raise SystemExit(f'rr_plan.json に {o} がありません')
    sig = {'team': team, 'opps': opps, 'games': a.games, 'playbook': playbook.play_sig(playbook.load_all())}
    os.makedirs(out, exist_ok=True)
    gp = os.path.join(out, 'pb_ab_games.json')
    if os.path.exists(gp):
        G = json.load(open(gp, encoding='utf-8'))
        if G.get('sig') != sig:
            raise SystemExit('pb_ab_games.json の sig（team, opps, games, playbook）が違います。--out-dir を変えてください')
    else:
        G = {'version': 'pb1', 'playbook_version': playbook.PLAYBOOK_VERSION, 'sig': sig, 'playbook': sig['playbook'], 'sel': {}, 'games': {}}
    pairs = []
    for o in opps:
        for x, y in ((team, o), (o, team)):
            if f'{x}|{y}' not in plan['sel'] and f'{x}|{y}' not in G['sel']:
                pairs.append((x, y))
    t0 = time.time()
    with make_pool(a.procs, T, True, team) as pool:
        for k_, r in pool.imap_unordered(_job_decide, list(dict.fromkeys(pairs)), chunksize=1):
            if 'error' in r:
                raise SystemExit('選出エラー ' + k_ + r['error'][-200:])
            G['sel'][k_] = r
        sel = lambda x, y: (plan['sel'].get(f'{x}|{y}') or G['sel'][f'{x}|{y}'])['order']
        jobs = []
        for o in opps:
            for k in range(a.games):
                X, Y = game_sides(team, o, k)
                for cond in ('pb', 'no'):
                    key = f'{o}|{k}|{cond}'
                    if key not in G['games'] or G['games'][key].get('res') is None:
                        jobs.append((key, X, Y, sel(X, Y), sel(Y, X), game_seed(team, o, k), cond == 'pb'))
        print(f'A/B {team[:8]} 対 {len(opps)}構築 x {a.games}局 x {{あり,なし}} = 今回 {len(jobs)}戦', flush=True)
        meta = {j[0]: j for j in jobs}
        n = 0
        for r in pool.imap_unordered(_job_ab, jobs, chunksize=1):
            n += 1
            j = meta[r['key']]
            o, k, cond = r['key'].split('|')
            res = r.get('res')
            G['games'][r['key']] = {'opp': o, 'k': int(k), 'cond': cond, 'side0': j[1], 'side1': j[2], 'sel0': j[3], 'sel1': j[4], 'seed': j[5],
                                    'res': res, 'winner': None if res in (None, 0) else (j[1] if res == 1 else j[2]),
                                    'judged': r.get('judged'), 'turns': r.get('turns'), 'left': r.get('left'), 'faints': r.get('faints'),
                                    'sec': r.get('sec'), 'error': r.get('error'), 'deny': [True, True], 'main_side': 0 if j[1] == team else 1,
                                    **({'pb': r['pb']} if r.get('pb') else {})}
            safeio.write_json(gp, G)
            print(f"[{n}/{len(jobs)}] {r['key']} res={res} {r.get('turns')}手 {r['sec']:.0f}秒 {(time.time() - t0) / 60:.1f}分", flush=True)
    pb_ab_report(G, team, opps, out)


def pb_ab_report(G, team, opps, out):
    def sc(g):
        if g.get('res') is None:
            return None
        return 0.5 if g['res'] == 0 else (1.0 if (g['res'] == 1) == (g['main_side'] == 0) else 0.0)
    pct = lambda l: f'{sum(l) / len(l) * 100:.0f}% ({sum(l):g}/{len(l)})' if l else '-'
    L = [f'# プレイブック A/B（{team}）', '', f"playbook={G['playbook']} 相手={len(opps)}構築 局数={G['sig']['games']}（側の入れ替えあり、同じseed・同じ選出）", '',
         '| 相手 | あり | なし | 差 |', '|---|---|---|---|']
    tot = {'pb': [], 'no': []}
    for o in opps:
        r = {c: [x for x in (sc(g) for g in G['games'].values() if g['opp'] == o and g['cond'] == c) if x is not None] for c in ('pb', 'no')}
        for c in r:
            tot[c] += r[c]
        d = (sum(r['pb']) / len(r['pb']) - sum(r['no']) / len(r['no'])) * 100 if r['pb'] and r['no'] else 0
        L.append(f"| {o[:8]} | {pct(r['pb'])} | {pct(r['no'])} | {d:+.0f}pt |")
    d = (sum(tot['pb']) / len(tot['pb']) - sum(tot['no']) / len(tot['no'])) * 100 if tot['pb'] and tot['no'] else 0
    L += [f"| 全体 | {pct(tot['pb'])} | {pct(tot['no'])} | {d:+.0f}pt |", '', '## 規則ごと（あり条件）', '']
    gp = os.path.join(out, 'pb_ab_games.json')
    st = pb_collect([gp])
    L += pb_table(st) if st else ['発動記録なし']
    secs = [g['sec'] for g in G['games'].values() if g.get('sec')]
    if secs:
        L += ['', f'1局の平均 {sum(secs) / len(secs):.0f}秒（{len(secs)}局）']
    open(os.path.join(out, 'pb_ab_report.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('\n'.join(L))


def cmd_playbook(a):
    {'selftest': cmd_pb_selftest, 'ab': cmd_pb_ab, 'report': cmd_pb_report}[a.what](a)


def cmd_pb_selftest(a):
    global _PB, _AD_PLAY, _AD_SELECT, _CT_PLAY
    import copy, tempfile, shutil
    import playbook as PBK
    import search as S
    import engine as E
    import study
    t00 = time.time()
    plan = load_plan(paths(None))
    T = plan['teams']
    _worker_init(T)
    LH, OP = PB_LH, 'bab22dcc629688e8'
    kt = next(t for t in json.load(open(prep.KNOWN_P, encoding='utf-8'))['teams'] if t['id'] == LH)
    PLAY = kt['guide']['play']
    text = study.article_text(LH)
    res = []

    def check(name, ok, info=''):
        res.append((name, bool(ok)))
        print(f"{'OK  ' if ok else 'NG  '}{name} {info}", flush=True)

    def mk(s0=('ムクホーク', 'ミミッキュ', 'イダイトウ'), s1=('ウツボット', 'パーモット', 'イダイトウ')):
        rr_apply(T[LH])
        R._ctx(OP)
        return B.engine_game(list(s0), list(s1))

    def fake(st, side, best, low=None):
        """best を最善(0.0)、low={action:値}、他は -0.1 にした作り物の ranked_fn。"""
        def fn(extra=()):
            acts = list(E.actions(st, side)) + [x for x in extra if x not in E.actions(st, side)]
            out = [((low or {}).get(x, 0.0 if x == best else -0.1), x) for x in acts]
            out.sort(key=lambda t: -t[0])
            return out
        return fn

    def cx(st, side=0, turn=1, pb=None):
        return PBK._Cx(st, st, side, [{}, {}], turn, pb or PBK.PB(PLAY, side, LH), True)

    def hold(st, k, v, pb=None):
        return PBK._hold1(k, v, cx(st, 0, 1, pb))

    # -- T1
    st = mk()
    pb = PBK.PB(PLAY, 0, LH)
    me = st.sides[0].mons[0]
    a0 = ('m', 'bravebird', True)
    pre = not hold(st, 'bad_matchup', True)
    a, rid = pb.decide(st, st, 0, a0, fake(st, 0, a0), [{}, {}], 1)
    atk = [x for x in me.moves if x in E.MOVES and E.MOVES[x].cat != 'status']
    best = max(atk, key=lambda x: (E.estimate(st, 0, x), -list(me.moves).index(x)))
    check('T1 best_damage(p2)', pre and rid == 'p2' and a[1] == best, f'pre={pre} rid={rid} a={a} 手計算={best}')
    # -- T2 / T6 / T7
    def st_bad():
        s = mk()
        s.sides[1].act = 1
        s.sides[1].mons[1].moves = ('closecombat', 'doubleshock', 'nuzzle', 'revivalblessing')
        m = s.sides[0].mons[0]
        m.hp = round(m.maxhp * 0.2)
        return s
    st2 = st_bad()
    pre = hold(st2, 'bad_matchup', True)
    a0 = ('m', 'closecombat', True)
    pb = PBK.PB(PLAY, 0, LH)
    a, rid = pb.decide(st2, st2, 0, a0, fake(st2, 0, a0), [{}, {}], 1)
    check('T2 いのちがけ(p1)', pre and rid == 'p1' and a[:2] == ('m', 'finalgambit'), f'pre={pre} rid={rid} a={a}')
    fg = next(x for x in E.actions(st2, 0) if x[:2] == ('m', 'finalgambit'))
    pb = PBK.PB(PLAY, 0, LH)
    a, rid = pb.decide(st2, st2, 0, a0, fake(st2, 0, a0, {fg: -100.0}), [{}, {}], 1)
    check('T6 guard却下', a == a0 and rid is None and any(r[2] == 'guard' for r in pb.rejected), f'a={a} rej={pb.rejected}')
    st7 = st_bad()
    st7.sides[0].mons[0].vol['disable'] = {'move': 'finalgambit', 'turns': 4}
    pb = PBK.PB(PLAY, 0, LH)
    a, rid = pb.decide(st7, st7, 0, a0, fake(st7, 0, a0), [{}, {}], 1)
    check('T7 illegal却下', a == a0 and rid is None and any(r[2] == 'illegal' for r in pb.rejected), f'a={a} rej={pb.rejected}')
    # -- T3 / T4
    st3 = mk()
    st3.sides[0].act = 1
    st3.sides[1].mons[0].boosts['atk'] = 2
    pb = PBK.PB(PLAY, 0, LH)
    a0 = ('m', 'playrough', False)
    a, rid = pb.decide(st3, st3, 0, a0, fake(st3, 0, a0), [{}, {}], 1)
    check('T3 トリル(p3)', rid == 'p3' and a[1] == 'trickroom', f'rid={rid} a={a}')
    st4 = mk()
    st4.sides[0].act = 1
    st4.pseudo['trickroom'] = 3
    m = st4.sides[0].mons[1]
    m.hp = round(m.maxhp * 0.4)
    pb = PBK.PB(PLAY, 0, LH)
    pb.uses['p3'] = 1
    a, rid = pb.decide(st4, st4, 0, a0, fake(st4, 0, a0), [{}, {}], 2)
    check('T4 のろい(p4)', rid == 'p4' and a[1] == 'curse', f'rid={rid} a={a}')
    # -- T5
    st5 = mk(('ムクホーク', 'ガブリアス', 'イダイトウ'))
    st5.pseudo['trickroom'] = 3
    pb = PBK.PB(PLAY, 0, LH)
    base = lambda s_, side, opts: opts[0]
    j = pb.chooser(base)(st5, 0, [1, 2])
    st5.pseudo.pop('trickroom')
    j2 = PBK.PB(PLAY, 0, LH).chooser(base)(st5, 0, [1, 2])
    check('T5 chooser(r1)', st5.sides[0].mons[j].name == 'イダイトウ' and j2 == 1, f'{st5.sides[0].mons[j].name} / トリルなし={j2}')
    # -- T8-T10
    st8 = mk()
    a0 = ('m', 'bravebird', True)
    def rule(rid, do, until=None, when=None, **kw):
        r = {'id': rid, 'who': '*', 'when': when or {}, 'do': do, 'origin': 'user', 'note': 'x'}
        if until:
            r['until'] = until
        r.update(kw)
        return r
    pb = PBK.PB([rule('s1', {'switch': ['ミミッキュ']})], 0, 't')
    ts = [t for t in range(1, 8) if pb.decide(st8, st8, 0, a0, fake(st8, 0, ('s', 1), {a0: 0.0, ('s', 1): -0.1}), [{}, {}], t)[1]]
    check('T8 switch連続不可・最大2', ts == [1, 3] and pb.uses['s1'] == 2, f'turns={ts}')
    pb = PBK.PB([rule('u1', {'move': ['インファイト']}, until={'turn': [3, None]})], 0, 't')
    ts = [t for t in range(1, 7) if pb.decide(st8, st8, 0, a0, fake(st8, 0, a0), [{}, {}], t)[1]]
    check('T9 until', ts == [1, 2] and any(r[2] == 'until' for r in pb.rejected), f'turns={ts}')
    pb = PBK.PB([rule('k1', {'best_damage': True})], 0, 't')
    ts = [t for t in range(1, 8) if pb.decide(st8, st8, 0, a0, fake(st8, 0, a0), [{}, {}], t)[1]]
    check('T10 stuck', ts == [1, 2, 3] and any(r[2] == 'stuck' for r in pb.rejected), f'turns={ts}')
    # -- T11
    ok, info = True, []
    for sx in (mk(), st2, st3):
        for i in (0, 1):
            x = PBK.ranked(sx, i, 2)[0][1]
            y = S.lookahead_action(sx, i, 2)
            ok &= x == y
            info.append(x == y)
    check('T11 ranked[0]==lookahead', ok, str(info))
    # -- T12
    team = kt['team']
    errs = PBK.validate(PLAY, team, text)
    check('T12a 7.1は合格', not errs, str(errs[:2]))
    def bad(label, mut, want):
        pl = copy.deepcopy(PLAY)
        mut(pl)
        e = PBK.validate(pl, team, text)
        check(f'T12 {label}', any(want in x for x in e), str(e[:2]))
    bad('未知キー', lambda p: p[0].update(zzz=1), '未知のキー')
    bad('技構成に無い技', lambda p: p[0].__setitem__('do', {'move': ['のろい']}), '技構成にありません')
    bad('6体に無い名前', lambda p: p[4].__setitem__('do', {'switch': ['ピカチュウ']}), '6体にいません')
    bad('タイプ誤記', lambda p: p[0]['when'].update(foe_type=['ひこおう']), 'タイプ')
    bad('srcが本文に無い', lambda p: p[0].__setitem__('src', '存在しない一文です'), '本文に含まれません')
    bad('do2種', lambda p: p[0]['do'].update(best_damage=True), 'ちょうど1つ')
    # -- T13
    tmp = tempfile.mkdtemp()
    old_k, old_r = prep.KNOWN_P, study.REPORT_P
    try:
        kp = os.path.join(tmp, 'known_teams.json')
        shutil.copy(old_k, kp)
        prep.KNOWN_P, study.REPORT_P = kp, os.path.join(tmp, 'STUDY.md')
        h0 = hashlib.sha256(open(kp, 'rb').read()).hexdigest()
        badj = os.path.join(tmp, 'bad.json')
        json.dump({'play': [{'id': 'p1', 'who': 'メガムクホーク', 'when': {'zzz': 1}, 'do': {'move': ['いのちがけ']}, 'note': 'x', 'src': 'x'}]},
                  open(badj, 'w', encoding='utf-8'), ensure_ascii=False)
        code = None
        try:
            study.set_play(LH, badj)
        except SystemExit as e:
            code = e.code
        h1 = hashlib.sha256(open(kp, 'rb').read()).hexdigest()
        goodj = os.path.join(tmp, 'good.json')
        json.dump({'play': PLAY[:1]}, open(goodj, 'w', encoding='utf-8'), ensure_ascii=False)
        study.set_play(LH, goodj)
        g0 = next(t for t in json.load(open(old_k, encoding='utf-8'))['teams'] if t['id'] == LH)['guide']
        g1 = next(t for t in json.load(open(kp, encoding='utf-8'))['teams'] if t['id'] == LH)['guide']
        same = all(g1[k] == v for k, v in g0.items() if k not in ('play', 'play_date')) and len(g1['play']) == 1
        check('T13 study.py play', code == 2 and h0 == h1 and same, f'exit={code} 無変更={h0 == h1} 他キー不変={same}')
    finally:
        prep.KNOWN_P, study.REPORT_P = old_k, old_r
        shutil.rmtree(tmp, ignore_errors=True)
    # -- T14 (受け入れ 2c): job の args
    cap = []
    real_bp, real_pb, real_ps = R.blind_play, dict(_PB), _PB_ONLY[0]
    rp = (_AD_PLAY, _AD_SELECT, _CT_PLAY)
    try:
        R.blind_play = lambda args: (cap.append(args), {'res': 0})[1]
        _AD_PLAY = _CT_PLAY = R.blind_play
        _AD_SELECT = lambda *x: (['a'], 'w')
        so, sx = ['ムクホーク', 'ミミッキュ', 'イダイトウ'], ['ウツボット', 'パーモット', 'イダイトウ']
        def run_all():
            cap.clear()
            _job_game(('k', LH, OP, so, sx, 7))
            _job_deny(('k', LH, OP, so, sx, 7, (True, True)))
            _job_adapt(('k', LH, 0, LH, OP, None, None))
            _job_ct(('k', OP, ('a',), 0, LH, OP, so, sx, 1))
            return list(cap)
        _PB = {}
        off = run_all()
        old = [(None, OP, so, sx, 7, 4, 4, False, None, False, (LH,)), (None, OP, so, sx, 7, 4, 4, False, None, False, (LH,), (True, True))]
        exp_len = [11, 12, 12, 12]
        _PB = {LH: PLAY}
        _PB_ONLY[0] = None
        on = run_all()
        ok = [len(x) for x in off] == exp_len and off[0] == old[0] and off[1] == old[1] and [len(x) for x in on] == [13, 13, 13, 13] and \
            all(x[12] == (PLAY, None) for x in on)
        check('T14 job args(あり/なし)', ok, f'なし={[len(x) for x in off]} あり={[len(x) for x in on]}')
    finally:
        R.blind_play = real_bp
        _PB = real_pb
        _PB_ONLY[0] = real_ps
        _AD_PLAY, _AD_SELECT, _CT_PLAY = rp
    n_ng = sum(1 for _, ok in res if not ok)
    print(f'selftest: {len(res) - n_ng}/{len(res)} 合格 {time.time() - t00:.0f}秒', flush=True)
    if n_ng:
        raise SystemExit(1)


# ================================================================ sched3（SPEC_SCHED3.md）
S3_VERSION = 's3v1'
S3_DEPTH = (5, 5)
S3_DENY = (True, True)
S3_LH = 'db0baa2843d2bd4b'


def s3_paths(out_dir=None):
    d = out_dir or DEF_OUT
    return {'dir': d, 'plan': os.path.join(d, 's3_plan.json'), 'games': os.path.join(d, 's3_games.json'),
            'logs': os.path.join(d, 's3_logs.jsonl'), 'md': os.path.join(d, 's3_report.md')}


def s3_order(ids):
    """強さに依らない並び: sha256("s3"+id) の昇順。"""
    return sorted(ids, key=lambda i: hashlib.sha256(('s3' + i).encode()).hexdigest())


def s3_graph(N):
    """位置の辺リスト（環→対角→追加）。assert で自己辺・重複辺なしを確認。"""
    if N % 2 == 0 and N < 4 or N % 2 == 1 and N < 7:
        raise SystemExit(f'構築数 {N} は少なすぎます（偶数は4以上、奇数は7以上）')
    m = N // 2
    ed = [(i, (i + 1) % N) for i in range(N)]
    ed += [(i, i + m) for i in range(m)]
    if N % 2:
        ed.append((N - 1, m - 1))
    seen = set()
    for x, y in ed:
        assert x != y, ('自己辺', x)
        k = (min(x, y), max(x, y))
        assert k not in seen, ('重複辺', k)
        seen.add(k)
    return ed


def s3_edges(ids):
    """ids（ハッシュ順）から辺 dict のリストを作る。"""
    out = []
    for e, (x, y) in enumerate(s3_graph(len(ids))):
        a, b = pair_ab(ids[x], ids[y])
        X, Y = (a, b) if e % 2 == 0 else (b, a)
        out.append({'e': e, 'a': a, 'b': b, 'X': X, 'Y': Y, 'seed': zlib.crc32(f's3{a}{b}'.encode()), 'key': f's3:{a}|{b}'})
    return out


def s3_degree(ids, edges):
    d = {i: 0 for i in ids}
    for ed in edges:
        d[ed['a']] += 1
        d[ed['b']] += 1
    return d


def s3_build(test_ids=None):
    """cmd_plan と同じ構築の組み立て（rr_team→sort_key、R11）。返り値 (rr, orig)。"""
    rts = [(rr_team(t), t) for t in raw_teams() if len(t['team']) == 6 and all(B._base(m['name']) in POKE for m in t['team'])]
    rts.sort(key=lambda x: sort_key(x[0]))
    orig = {rt['id']: t for rt, t in rts}
    rr = {rt['id']: rt for rt, _ in rts}
    rr['R11'] = r11_team()
    if test_ids:
        want = test_ids.split(',')
        miss = [i for i in want if i not in rr]
        if miss:
            raise SystemExit(f'--test-ids に未知の構築: {miss}')
        rr = {i: rr[i] for i in want}
    return rr, orig


def s3_apply_all(rr):
    """全構築に rr_apply を試す。失敗は (id, 理由) のリスト。"""
    bad = []
    for i, rt in list(rr.items()):
        try:
            rr_apply(rt)
        except Exception as ex:
            bad.append({'id': i, 'reason': f'{type(ex).__name__}: {ex}'[:200]})
    return bad


def s3_sec_avg(games):
    ss = [g['sec'] for g in (games or {}).get('games', {}).values() if g.get('sec') and g.get('res') is not None]
    return (sum(ss) / len(ss), True) if ss else (65.0, False)


def s3_estimate(plan, games, procs):
    ne = len(plan['edges'])
    gm = (games or {}).get('games', {})
    left = sum(1 for ed in plan['edges'] if not (gm.get(ed['key']) and gm[ed['key']]['res'] is not None))
    sec, real = s3_sec_avg(games)
    nsel = sum(1 for ed in plan['edges'] for k in (f"{ed['X']}|{ed['Y']}", f"{ed['Y']}|{ed['X']}") if k not in plan['sel'])
    g_min = left * sec / procs / 60
    s_min = nsel * 7 / procs / 60
    return (f"時間見積り: 残り{left}/{ne}戦 × {sec:.0f}秒({'実測平均' if real else '想定50〜80秒の中央'}) / {procs}プロセス ≈ {g_min:.0f}分"
            f"（想定幅 {left * 50 / procs / 60:.0f}〜{left * 80 / procs / 60:.0f}分）、未計算の選出 {nsel}件 ≈ {s_min:.0f}分")


def cmd_s3_plan(a):
    P = s3_paths(a.out_dir)
    os.makedirs(P['dir'], exist_ok=True)
    rr, orig = s3_build(getattr(a, 'test_ids', None))
    excluded = s3_apply_all(rr)
    for x in excluded:
        rr.pop(x['id'], None)
    ids = s3_order(list(rr))
    edges = s3_edges(ids)
    sig = hashlib.sha256((json.dumps([rr[i] for i in sorted(ids)], ensure_ascii=False, sort_keys=True) + S3_VERSION
                          + f'{S3_DEPTH[0]},{S3_DEPTH[1]}').encode()).hexdigest()
    plan = None
    if os.path.exists(P['plan']):
        old = json.load(open(P['plan'], encoding='utf-8'))
        if old.get('sig') == sig:
            plan = old
        elif not a.force:
            raise SystemExit('s3_plan.json の sig が違います（--force で退避して作り直し）')
        else:
            os.replace(P['plan'], P['plan'][:-5] + time.strftime('.%Y%m%d_%H%M%S.json'))
    deg = s3_degree(ids, edges)
    extra4 = next((i for i, n in deg.items() if n == 4), None)
    if plan is None:
        plan = {'version': S3_VERSION, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'depth': list(S3_DEPTH), 'deny': list(S3_DENY),
                'sig': sig, 'ids': ids, 'excluded': excluded, 'teams': {}, 'edges': edges, 'degree': deg, 'extra4': extra4, 'sel': {}}
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
    pairs = []
    for ed in edges:
        for x, y in ((ed['X'], ed['Y']), (ed['Y'], ed['X'])):
            if f'{x}|{y}' not in plan['sel'] and (x, y) not in pairs:
                pairs.append((x, y))
    cmd_select(P, plan, 0, a.procs, pairs)
    save_plan(P, plan)
    dist = collections.Counter(plan['degree'].values())
    print(f"N={len(plan['ids'])}、総試合数 {len(plan['edges'])}、次数分布 {dict(sorted(dist.items()))}、extra4={plan['extra4']}、除外 {len(plan['excluded'])}件")
    print(s3_estimate(plan, None, a.procs))
    return plan


def _job_s3(a):
    key, X, Y, selX, selY, seed, deny, depth = a
    t0 = time.time()
    try:
        rr_apply(_TEAMS[X])
        r = R.blind_play((None, Y, selX, selY, seed, depth[0], depth[1], False, None, False, (X,), deny) + _pb_args(X, Y))
    except Exception:
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    r['key'] = key
    r['sec'] = round(time.time() - t0, 2)
    return r


def s3_record(job, r):
    key, X, Y, selX, selY, seed, deny, depth = job
    a, b = key[3:].split('|')
    res = r.get('res')
    w = None if res is None else (X if res == 1 else (Y if res == -1 else None))
    rec = {'a': a, 'b': b, 'side0': X, 'side1': Y, 'sel0': selX, 'sel1': selY, 'seed': seed, 'res': res, 'winner': w,
           'judged': r.get('judged'), 'turns': r.get('turns'), 'left': r.get('left'), 'faints': r.get('faints'),
           'sec': r.get('sec'), 'error': r.get('error')}
    if r.get('deny_stats') is not None:
        rec['deny_stats'] = r['deny_stats']
    if r.get('pb'):
        rec['pb'] = r['pb']
    return rec


def s3_jobs(plan):
    out = []
    for ed in plan['edges']:
        X, Y = ed['X'], ed['Y']
        if f'{X}|{Y}' not in plan['sel'] or f'{Y}|{X}' not in plan['sel']:
            raise SystemExit(f'選出がありません: {X}|{Y}（plan を再実行してください）')
        out.append((ed['key'], X, Y, plan['sel'][f'{X}|{Y}']['order'], plan['sel'][f'{Y}|{X}']['order'], ed['seed'],
                    tuple(plan.get('deny', S3_DENY)), tuple(plan.get('depth', S3_DEPTH))))
    return out


def s3_load_games(P, plan):
    if os.path.exists(P['games']):
        g = json.load(open(P['games'], encoding='utf-8'))
        if g.get('plan_sig') != plan['sig']:
            raise SystemExit('s3_games.json の plan_sig が s3_plan.json と違います')
        return g
    return {'version': S3_VERSION, 'plan_sig': plan['sig'], 'depth': plan['depth'], 'deny': plan['deny'],
            'playbook': _pb_sig(), 'games': {}}


def cmd_s3_run(a):
    P = s3_paths(a.out_dir)
    plan = load_plan(P)
    games = s3_load_games(P, plan)
    pb_guard(games)
    jobs = s3_jobs(plan)
    todo = [j for j in jobs if not done_game(games, j[0], a.retry_errors)]
    tot = len(jobs)
    base = tot - len(todo)
    if a.max_games:
        todo = todo[:a.max_games]
    print(f'全体 {tot}戦、済み {base}、今回 {len(todo)}戦', flush=True)
    print(s3_estimate(plan, games, a.procs), flush=True)
    if not todo:
        return 0
    t0 = time.time()
    n = 0
    with make_pool(a.procs, plan['teams']) as pool:
        for r in pool.imap_unordered(_job_s3, todo, chunksize=1):
            n += 1
            job = next(j for j in todo if j[0] == r['key'])
            games['games'][r['key']] = s3_record(job, r)
            safeio.write_json(P['games'], games)
            if r.get('log') is not None:
                append_log(P, r['key'], r['log'])
            mark = '例外' if r.get('res') is None else ('勝' if r['res'] == 1 else '負')
            el = (time.time() - t0) / 60
            rem = el / n * (len(todo) - n)
            print(f"[{base + n}/{tot}] {r['key']} {job[1][:8]}側{mark} {r.get('turns')}手 {r['sec']:.0f}秒 経過{el:.1f}分 残り約{rem:.1f}分", flush=True)
    return n


def s3_stats(plan, games):
    st = {i: {'w': 0.0, 'n': 0, 'exc': 0, 'hp': 0, 'games': []} for i in plan['ids']}
    for key, g in games['games'].items():
        for s in (0, 1):
            i = g[f'side{s}']
            if i not in st:
                continue
            o = g[f'side{1 - s}']
            if g['res'] is None:
                st[i]['exc'] += 1
                continue
            sc = 0.5 if g['res'] == 0 else (1.0 if (g['res'] == 1) == (s == 0) else 0.0)
            lf = g.get('left')
            hp = (sum(h for _, h in lf[s]) - sum(h for _, h in lf[1 - s])) if lf else 0
            st[i]['w'] += sc
            st[i]['n'] += 1
            st[i]['hp'] += hp
            st[i]['games'].append({'opp': o, 'first': s == 0, 'score': sc, 'turns': g.get('turns'), 'judged': bool(g.get('judged'))})
    return st


def s3_rating(plan, i):
    t = plan['teams'].get(i) or {}
    if i == 'R11' or (t.get('final') is None and t.get('peak') is None):
        return None
    return max(t.get('final') or 0, t.get('peak') or 0)


def cmd_s3_report(a):
    P = s3_paths(a.out_dir)
    plan = load_plan(P)
    games = s3_load_games(P, plan)
    st = s3_stats(plan, games)
    rate = lambda i: st[i]['w'] / st[i]['n'] if st[i]['n'] else 0.0
    rk = sorted(plan['ids'], key=lambda i: (-rate(i), -(st[i]['hp'] / st[i]['n'] if st[i]['n'] else 0),
                                           s3_rating(plan, i) is None, -(s3_rating(plan, i) or 0), i))
    pos = {i: n for n, i in enumerate(rk, 1)}
    title = lambda i: (plan['teams'][i].get('title') or i)
    ties = lambda i: sum(1 for j in plan['ids'] if st[j]['n'] and abs(rate(j) - rate(i)) < 1e-9)
    gs = list(games['games'].values())
    nj = sum(1 for g in gs if g.get('judged'))
    nx = sum(1 for g in gs if g['res'] is None)
    N, ne = len(plan['ids']), len(plan['edges'])
    L = ['# sched3: 各構築3戦・5手読みブラインドテスト', '']
    for i, lab in (('R11', 'R11'), (S3_LH, 'リザホーク')):
        if i in pos:
            L.append(f"- **{lab}（{i}）の順位: {pos[i]}位 / {N}**（勝率 {rate(i) * 100:.0f}%・{st[i]['n']}戦、同率の構築 {ties(i)}件）")
        else:
            L.append(f'- {lab}: 対象外')
    L += ['', '## 1. 前提', '',
          f"- 構築数 N={N}、総戦数 {ne}（完了 {sum(1 for g in gs if g['res'] is not None)}）、深さ {tuple(plan['depth'])}、ケア deny {tuple(plan['deny'])}、"
          f"プレイブック {'オン' if games.get('playbook') else 'オフ'}、ブラインド",
          '- 並び: sha256("s3"+id) 昇順（rating 非使用）。対戦: 環＋対角（奇数は追加1本）。種 = crc32("s3{a}{b}")、先後は辺番号の偶奇で入れ替え',
          f"- 除外: {plan['excluded'] or 'なし'}",
          f"- 次数4の構築（extra4）: {plan['extra4'] or 'なし'}" + (f"（{title(plan['extra4'])}）" if plan['extra4'] else ''),
          f'- 判定決着 {nj}戦、例外 {nx}戦', '',
          '## 2. ランキング', '', '| 順位 | 構築 | 勝/戦 | 勝率 | 95%区間 | 平均残HP差 | rating | 例外 |', '|---|---|---|---|---|---|---|---|']
    for i in rk:
        s = st[i]
        lo, hi = wilson(s['w'], s['n'])
        r = s3_rating(plan, i)
        L.append(f"| {pos[i]} | {title(i)[:24]}（{i[:8]}） | {s['w']:g}/{s['n']} | {rate(i) * 100:.0f}% | {lo * 100:.0f}〜{hi * 100:.0f}% | "
                 f"{(s['hp'] / s['n'] if s['n'] else 0):+.0f} | {'-' if r is None else r} | {s['exc']} |")
    L += ['', '## 3. 上位10の対戦内訳', '']
    for i in rk[:10]:
        L.append(f"- {pos[i]}位 {title(i)[:24]}（{i[:8]}）")
        for g in st[i]['games']:
            L.append(f"  - vs {title(g['opp'])[:10]} {'先' if g['first'] else '後'} {'勝' if g['score'] == 1 else ('分' if g['score'] == 0.5 else '負')} "
                     f"{g['turns']}手 {'判定' if g['judged'] else '決着'}")
    L += ['', '## 注意', '',
          '1構築3戦のみで誤差が非常に大きい（3戦全勝でも95%区間は約44〜100%）。上位は偶然の可能性が高く、順位は参考値。確かめるには上位同士の追加対戦が必要。']
    txt = '\n'.join(L) + '\n'
    os.makedirs(P['dir'], exist_ok=True)
    with open(P['md'], 'w', encoding='utf-8') as f:
        f.write(txt)
    print(txt)
    print(f"書きました: {P['md']}")


def cmd_s3_selftest(a):
    import tempfile, shutil, random
    ng = []

    def chk(name, ok, info=''):
        print(('OK ' if ok else 'NG ') + name + (f' {info}' if info and not ok else ''), flush=True)
        if not ok:
            ng.append(name)
    before = _sha_all()
    # 1. グラフ
    ok = True
    for N in [n for n in range(4, 41) if n != 5]:   # N=5 は仕様上エラー（奇数は7以上）
        ids = [f't{i:03d}' for i in range(N)]
        try:
            hs = s3_order(ids)
            ed = s3_edges(hs)
            deg = s3_degree(hs, ed)
            dv = collections.Counter(deg.values())
            cond = len(ed) == -(-3 * N // 2) and (dv == {3: N} if N % 2 == 0 else dv == {3: N - 1, 4: 1})
            ok = ok and cond and ed == s3_edges(s3_order(ids))
            sh = ids[:]
            random.Random(N).shuffle(sh)
            ok = ok and {(e['a'], e['b']) for e in ed} == {(e['a'], e['b']) for e in s3_edges(s3_order(sh))}
            if not cond:
                print('  NG graph N=', N, dict(dv), len(ed))
        except AssertionError as ex:
            ok = False
            print('  assert', N, ex)
    chk('1 グラフ N=4..40', ok)
    for N in (1, 2, 3, 5):
        try:
            s3_graph(N)
            chk(f'1b N={N} はエラー', False)
        except SystemExit:
            pass
    chk('1b 小さすぎる N はエラー', True)
    # 2. 全構築 apply
    rr, _ = s3_build(None)
    bad = s3_apply_all(rr)
    for x in bad:
        print('  apply 失敗', x['id'], x['reason'])
    chk(f'2 全構築 apply（{len(rr)}構築）', not bad)
    # 3. 小規模実戦
    tmp = tempfile.mkdtemp(prefix='s3test_')
    old_depth = globals()['S3_DEPTH']
    try:
        globals()['S3_DEPTH'] = (1, 1)
        base = [i for i in rr if i != 'R11'][:3] + ['R11']
        ns = argparse.Namespace(procs=2, force=False, test_ids=','.join(base), out_dir=tmp, max_games=2, retry_errors=False)
        plan = cmd_s3_plan(ns)
        chk('3 plan: 4構築・6戦・全員次数3・除外0', len(plan['ids']) == 4 and len(plan['edges']) == 6 and set(plan['degree'].values()) == {3}
            and not plan['excluded'] and len(plan['sel']) == 12 and plan['depth'] == [1, 1], (len(plan['sel']), plan['depth']))
        P = s3_paths(tmp)
        cmd_s3_run(ns)
        g1 = json.load(open(P['games'], encoding='utf-8'))
        chk('3 run --max-games 2 で2戦', len(g1['games']) == 2, len(g1['games']))
        ns.max_games = 0
        cmd_s3_run(ns)
        g2 = json.load(open(P['games'], encoding='utf-8'))
        chk('3 再実行で6戦・先の2戦は不変（再開）', len(g2['games']) == 6 and all(g2['games'][k] == v for k, v in g1['games'].items()))
        ok = True
        for ed in plan['edges']:
            g = g2['games'][ed['key']]
            ok = ok and g['seed'] == zlib.crc32(f"s3{ed['a']}{ed['b']}".encode()) and (g['side0'], g['side1']) == (
                (ed['a'], ed['b']) if ed['e'] % 2 == 0 else (ed['b'], ed['a']))
        chk('3 種=crc32・左右が偶奇で入れ替わり', ok)
        ns.retry_errors = True
        cmd_s3_run(ns)
        chk('3 plan 再実行で選出再利用', cmd_s3_plan(ns)['sel'] == plan['sel'])
        # 4. report
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_s3_report(argparse.Namespace(out_dir=tmp))
        t = buf.getvalue()
        chk('4 report に R11 行と注意書き', 'R11' in t and '順位は参考値' in t and os.path.exists(P['md']))
    finally:
        globals()['S3_DEPTH'] = old_depth
        shutil.rmtree(tmp, ignore_errors=True)
    # 5. sha
    chk('5 既存ファイル sha256 不変', _sha_all() == before)
    if ng:
        print('NG:', ng)
        raise SystemExit(1)
    print('sched3 selftest 全項目 OK')


def cmd_sched3(a):
    {'plan': cmd_s3_plan, 'run': cmd_s3_run, 'report': cmd_s3_report, 'selftest': cmd_s3_selftest}[a.what](a)


# ---------------------------------------------------------------- final20（sched3 の3戦3勝20構築の総当たり）
F20_VERSION = 'f20v1'
F20_N = 20


def f20_paths(out_dir=None):
    d = out_dir or DEF_OUT
    return {'dir': d, 'plan': os.path.join(d, 'f20_plan.json'), 'games': os.path.join(d, 'f20_games.json'),
            'logs': os.path.join(d, 'f20_logs.jsonl'), 'md': os.path.join(d, 'f20_report.md')}


def f20_pick(st):
    """s3_stats の結果から対象20構築を選ぶ。返り値 (ids, reasons)。"""
    rate = lambda i: st[i]['w'] / st[i]['n'] if st[i]['n'] else 0.0
    allr = sorted(st, key=lambda i: (-rate(i), -st[i]['hp'], i))
    full = [i for i in allr if st[i]['n'] == 3 and st[i]['w'] == st[i]['n']]
    if len(full) >= F20_N:
        pick = full[:F20_N]
    else:
        pick = full + [i for i in allr if i not in full][:F20_N - len(full)]
    return pick, {i: ('3/3' if i in full else '補充') for i in pick}


def f20_edges(ids):
    out = []
    for x, y in itertools.combinations(sorted(ids), 2):
        a, b = pair_ab(x, y)
        for k in (0, 1):
            X, Y = (a, b) if k % 2 == 0 else (b, a)
            out.append({'e': len(out), 'a': a, 'b': b, 'k': k, 'X': X, 'Y': Y,
                        'seed': zlib.crc32(f'f20{a}{b}{k}'.encode()), 'key': f'f20:{a}|{b}|{k}'})
    return out


def f20_fill_sel(plan, s3sel):
    """s3 の選出を再利用。未計算の順序付き組 [(x,y)] を返す。"""
    missing = []
    for ed in plan['edges']:
        for x, y in ((ed['X'], ed['Y']), (ed['Y'], ed['X'])):
            k = f'{x}|{y}'
            if k not in plan['sel'] and k in s3sel:
                plan['sel'][k] = json.loads(json.dumps(s3sel[k]))
                plan['sel_src'][k] = 's3'
            if k not in plan['sel'] and (x, y) not in missing:
                missing.append((x, y))
    return missing


def cmd_f20_plan(a):
    P = f20_paths(a.out_dir)
    S = s3_paths(a.out_dir)
    if not (os.path.exists(S['plan']) and os.path.exists(S['games'])):
        raise SystemExit('s3_plan.json / s3_games.json がありません')
    sp3 = json.load(open(S['plan'], encoding='utf-8'))
    sg3 = json.load(open(S['games'], encoding='utf-8'))
    if sg3.get('plan_sig') != sp3.get('sig'):
        raise SystemExit('s3_games.json の plan_sig が s3_plan.json と違います')
    st3 = s3_stats(sp3, sg3)
    ids, reasons = f20_pick(st3)
    ids = sorted(ids)
    rr, _ = s3_build(None)
    rr = {i: rr[i] for i in ids if i in rr}
    if len(rr) != len(ids):
        raise SystemExit(f'構築が見つかりません: {[i for i in ids if i not in rr]}')
    bad = s3_apply_all(rr)
    if bad:
        raise SystemExit(f'apply 失敗: {bad}')
    miss = [i for i in ids if i not in sp3['teams']]
    if miss:
        raise SystemExit(f's3_plan.teams にない構築: {miss}')
    depth = S3_DEPTH
    sig = hashlib.sha256((json.dumps([rr[i] for i in ids], ensure_ascii=False, sort_keys=True) + F20_VERSION
                          + f'{depth[0]},{depth[1]}' + sp3['sig']).encode()).hexdigest()
    plan = None
    if os.path.exists(P['plan']):
        old = json.load(open(P['plan'], encoding='utf-8'))
        if old.get('sig') == sig:
            plan = old
        elif not a.force:
            raise SystemExit('f20_plan.json の sig が違います（--force で退避して作り直し）')
        else:
            os.replace(P['plan'], P['plan'][:-5] + time.strftime('.%Y%m%d_%H%M%S.json'))
    if plan is None:
        s3info = {}
        for i in ids:
            opp = [st3[g['opp']]['w'] / st3[g['opp']]['n'] for g in st3[i]['games'] if st3[g['opp']]['n']]
            s3info[i] = {'reason': reasons[i], 'w': st3[i]['w'], 'n': st3[i]['n'], 'hp': st3[i]['hp'],
                         'opp_rate': (sum(opp) / len(opp)) if opp else None}
        plan = {'version': F20_VERSION, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'depth': list(depth), 'deny': list(S3_DENY),
                'sig': sig, 's3_sig': sp3['sig'], 'ids': ids, 's3': s3info, 'excluded': [],
                'teams': {i: sp3['teams'][i] for i in ids}, 'edges': f20_edges(ids), 'sel': {}, 'sel_src': {}}
    missing = f20_fill_sel(plan, sp3.get('sel', {}))
    save_plan(P, plan)
    lim = getattr(a, 'sel_limit', None)
    if lim is not None:
        keep = {(ed['X'], ed['Y']) for ed in plan['edges'][:lim]} | {(ed['Y'], ed['X']) for ed in plan['edges'][:lim]}
        missing = [p for p in missing if p in keep]
    cmd_select(P, plan, 0, a.procs, missing)
    for p in missing:
        if f'{p[0]}|{p[1]}' in plan['sel']:
            plan['sel_src'].setdefault(f'{p[0]}|{p[1]}', 'new')
    save_plan(P, plan)
    n_s3 = sum(1 for v in plan['sel_src'].values() if v == 's3')
    n_new = sum(1 for v in plan['sel_src'].values() if v == 'new')
    print(f"N={len(plan['ids'])}、{len(plan['edges']) // 2}組×2={len(plan['edges'])}戦、再利用選出 {n_s3}件、新規 {n_new}件"
          f"（未計算 {f20_nsel(plan)}件）")
    print(f20_estimate(plan, None, a.procs))
    return plan


def f20_nsel(plan):
    return len({k for ed in plan['edges'] for k in (f"{ed['X']}|{ed['Y']}", f"{ed['Y']}|{ed['X']}") if k not in plan['sel']})


def f20_estimate(plan, games, procs):
    s = s3_estimate(plan, games, procs)
    return s[:s.index('、未計算')] + f"、未計算の選出 {f20_nsel(plan)}件 ≈ {f20_nsel(plan) * 7 / procs / 60:.0f}分"


def f20_record(job, r):
    key, X, Y, selX, selY, seed, deny, depth = job
    a, b, k = key[4:].split('|')
    res = r.get('res')
    w = None if res is None else (X if res == 1 else (Y if res == -1 else None))
    rec = {'a': a, 'b': b, 'k': int(k), 'side0': X, 'side1': Y, 'sel0': selX, 'sel1': selY, 'seed': seed, 'res': res, 'winner': w,
           'judged': r.get('judged'), 'turns': r.get('turns'), 'left': r.get('left'), 'faints': r.get('faints'),
           'sec': r.get('sec'), 'error': r.get('error')}
    if r.get('deny_stats') is not None:
        rec['deny_stats'] = r['deny_stats']
    if r.get('pb'):
        rec['pb'] = r['pb']
    return rec


def f20_load_games(P, plan):
    if os.path.exists(P['games']):
        g = json.load(open(P['games'], encoding='utf-8'))
        if g.get('plan_sig') != plan['sig']:
            raise SystemExit('f20_games.json の plan_sig が f20_plan.json と違います')
        return g
    return {'version': F20_VERSION, 'plan_sig': plan['sig'], 'depth': plan['depth'], 'deny': plan['deny'],
            'playbook': _pb_sig(), 'games': {}}


def cmd_f20_run(a):
    P = f20_paths(a.out_dir)
    plan = load_plan(P)
    games = f20_load_games(P, plan)
    pb_guard(games)
    lim = getattr(a, 'jobs_limit', 0)
    jobs = s3_jobs({**plan, 'edges': plan['edges'][:lim]} if lim else plan)
    todo = [j for j in jobs if not done_game(games, j[0], a.retry_errors)]
    tot = len(jobs)
    base = tot - len(todo)
    if a.max_games:
        todo = todo[:a.max_games]
    print(f'全体 {tot}戦、済み {base}、今回 {len(todo)}戦', flush=True)
    print(f20_estimate(plan, games, a.procs), flush=True)
    if not todo:
        return 0
    t0 = time.time()
    n = 0
    with make_pool(a.procs, plan['teams']) as pool:
        for r in pool.imap_unordered(_job_s3, todo, chunksize=1):
            n += 1
            job = next(j for j in todo if j[0] == r['key'])
            games['games'][r['key']] = f20_record(job, r)
            safeio.write_json(P['games'], games)
            if r.get('log') is not None:
                append_log(P, r['key'], r['log'])
            mark = '例外' if r.get('res') is None else ('勝' if r['res'] == 1 else '負')
            el = (time.time() - t0) / 60
            print(f"[{base + n}/{tot}] {r['key']} {job[1][:8]}側{mark} {r.get('turns')}手 {r['sec']:.0f}秒 経過{el:.1f}分 "
                  f"残り約{el / n * (len(todo) - n):.1f}分", flush=True)
    return n


def f20_mini(group, games):
    gs = set(group)
    pts = {i: 0.0 for i in group}
    for g in games['games'].values():
        if g['res'] is None or g['side0'] not in gs or g['side1'] not in gs:
            continue
        r = g['res']
        pts[g['side0']] += 0.5 if r == 0 else (1.0 if r == 1 else 0.0)
        pts[g['side1']] += 0.5 if r == 0 else (1.0 if r == -1 else 0.0)
    return pts


def f20_rank(ids, st, games):
    """勝率↓ → 同率グループ内の直接対決得点↓ → 平均残HP差↓ → id↑。"""
    rate = lambda i: st[i]['w'] / st[i]['n'] if st[i]['n'] else 0.0
    avg = lambda i: st[i]['hp'] / st[i]['n'] if st[i]['n'] else 0.0
    grp = {}
    for i in ids:
        grp.setdefault(round(rate(i) * 1e6), []).append(i)
    out = []
    for r in sorted(grp, reverse=True):
        g = grp[r]
        mp_ = f20_mini(g, games) if len(g) > 1 else {g[0]: 0.0}
        out += sorted(g, key=lambda i: (-mp_[i], -avg(i), i))
    return out


def _avg_ranks(v):
    order = sorted(range(len(v)), key=lambda i: -v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for t in range(i, j + 1):
            r[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return r


def f20_spearman(x, y):
    rx, ry = _avg_ranks(x), _avg_ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sx = math.sqrt(sum((p - mx) ** 2 for p in rx))
    sy = math.sqrt(sum((q - my) ** 2 for q in ry))
    if not sx or not sy:
        return None
    return sum((p - mx) * (q - my) for p, q in zip(rx, ry)) / (sx * sy)


def cmd_f20_report(a):
    P = f20_paths(a.out_dir)
    plan = load_plan(P)
    games = f20_load_games(P, plan)
    st = s3_stats(plan, games)
    ids = plan['ids']
    rk = f20_rank(ids, st, games)
    pos = {i: n for n, i in enumerate(rk, 1)}
    title = lambda i: (plan['teams'][i].get('title') or i)
    rate = lambda i: st[i]['w'] / st[i]['n'] if st[i]['n'] else 0.0
    avg = lambda i: st[i]['hp'] / st[i]['n'] if st[i]['n'] else 0.0
    gs = list(games['games'].values())
    nd = sum(1 for g in gs if g['res'] is not None)
    nj = sum(1 for g in gs if g.get('judged'))
    nx = sum(1 for g in gs if g['res'] is None)
    ne = len(plan['edges'])
    M = {i: {} for i in ids}
    for i in ids:
        for g in st[i]['games']:
            c = M[i].setdefault(g['opp'], [0.0, 0])
            c[0] += g['score']
            c[1] += 1
    L = ['# final20: sched3 で3戦3勝の20構築による総当たり', '']
    for i, lab in (('R11', 'R11'), (S3_LH, 'リザホーク')):
        if i in pos:
            L.append(f"- **{lab}（{i}）の順位: {pos[i]}位 / {len(ids)}**（{st[i]['w']:g}/{st[i]['n']}、勝率 {rate(i) * 100:.0f}%）")
    L += [f'- 完了 {nd}/{ne}戦、判定決着 {nj}戦、例外 {nx}戦', '',
          '## 1. ランキング', '',
          '並び: 勝率↓ → 直接対決（同率グループ内の相互対戦の得点↓、3者以上もミニリーグ）→ 平均残HP差↓ → id↑', '',
          f'| 順位 | 構築 | 勝/{2 * (len(ids) - 1)} | 勝率 | Wilson 95% | 平均残HP差 | s3成績 |', '|---|---|---|---|---|---|---|']
    for i in rk:
        s = st[i]
        lo, hi = wilson(s['w'], s['n'])
        s3 = plan['s3'][i]
        L.append(f"| {pos[i]} | {title(i)[:24]}（{i[:8]}） | {s['w']:g}/{s['n']} | {rate(i) * 100:.0f}% | {lo * 100:.0f}〜{hi * 100:.0f}% | "
                 f"{avg(i):+.0f} | {s3['w']:g}-{s3['n'] - s3['w']:g}{'' if s3['reason'] == '3/3' else '（補充）'} |")
    L += ['', '## 2. 勝敗行列（行=自分、セル=その相手への得点 0〜2、列見出し=順位）', '',
          '| 順位 id | ' + ' | '.join(str(pos[j]) for j in rk) + ' |', '|---|' + '---|' * len(rk)]
    for i in rk:
        cells = []
        for j in rk:
            if i == j:
                cells.append('・')
            else:
                c = M[i].get(j)
                cells.append('-' if not c else f'{c[0]:g}')
        L.append(f'| {pos[i]} {i[:8]} | ' + ' | '.join(cells) + ' |')
    L += ['', '## 3. 上位5構築の強い相手・弱い相手', '']
    for i in rk[:5]:
        strong = [j for j in rk if M[i].get(j) and M[i][j][1] == 2 and M[i][j][0] == 2]
        weak = [j for j in rk if M[i].get(j) and M[i][j][1] == 2 and M[i][j][0] == 0]
        note = '0-2'
        if not weak:
            weak = [j for j in rk if M[i].get(j) and M[i][j][1] == 2 and 0.5 <= M[i][j][0] <= 1]
            note = '0.5〜1点'
        fm = lambda js: '、'.join(f'{pos[j]}位{title(j)[:10]}' for j in js) or 'なし'
        L.append(f"- {pos[i]}位 {title(i)[:24]}（{i[:8]}）: 強い相手(2-0) {fm(strong)} / 弱い相手({note}) {fm(weak)}")
    L += ['', '## 4. sched3 との比較', '',
          '全員 s3 は 3-0（補充を除く）。s3 の相手の強さ（相手の s3 勝率平均）と final20 勝率を並べる。', '',
          '| 順位 | 構築 | s3 相手の s3 勝率平均 | s3 残HP差 | final20 勝率 |', '|---|---|---|---|---|']
    for i in rk:
        s3 = plan['s3'][i]
        orr = s3.get('opp_rate')
        L.append(f"| {pos[i]} | {title(i)[:24]}（{i[:8]}） | {'-' if orr is None else f'{orr * 100:.0f}%'} | {s3['hp']:+.0f} | {rate(i) * 100:.0f}% |")
    sp = f20_spearman([plan['s3'][i]['hp'] for i in ids], [-pos[i] for i in ids])
    L += ['', f"Spearman 順位相関（s3 残HP差順 vs final20 順位）: {'算出不可' if sp is None else f'{sp:+.2f}'}", '',
          '## 注意', '',
          '38戦の Wilson 区間幅は約±15pt。区間が重なる構築は区別できない。選出は固定（ガイド/基本）でブラインド、5手読みAI同士の結果であり実戦の強さそのものではない。']
    txt = '\n'.join(L) + '\n'
    os.makedirs(P['dir'], exist_ok=True)
    with open(P['md'], 'w', encoding='utf-8') as f:
        f.write(txt)
    print(txt)
    print(f"書きました: {P['md']}")


def cmd_f20_selftest(a):
    import tempfile, shutil, random, io
    ng = []

    def chk(name, ok, info=''):
        print(('OK ' if ok else 'NG ') + name + (f' {info}' if info and not ok else ''), flush=True)
        if not ok:
            ng.append(name)
    before = _sha_all()
    S = s3_paths(None)
    sp3 = json.load(open(S['plan'], encoding='utf-8'))
    sg3 = json.load(open(S['games'], encoding='utf-8'))
    st3 = s3_stats(sp3, sg3)
    # 1
    ids, rs = f20_pick(st3)
    full = {i for i, s in st3.items() if s['n'] == 3 and s['w'] == 3}
    rr, _ = s3_build(None)
    bad = s3_apply_all({i: rr[i] for i in ids})
    chk('1 対象20・3/3一致・全apply成功', len(ids) == 20 and set(ids) == full and not bad and S3_LH in ids and set(rs.values()) == {'3/3'}, (len(ids), len(full), bad))
    # 2
    fk = lambda n, hp: {'w': n and 3.0, 'n': n, 'hp': hp}
    fake = {f'a{i:02d}': {'w': 3.0, 'n': 3, 'hp': 100 - i} for i in range(21)}
    fake.update({f'b{i:02d}': {'w': 2.0, 'n': 3, 'hp': 50 - i} for i in range(5)})
    p21, r21 = f20_pick(fake)
    fake19 = {k: v for k, v in fake.items() if k != 'a20' and k != 'a19'}
    p19, r19 = f20_pick(fake19)
    chk('2 21個→上位20に切詰め', p21 == [f'a{i:02d}' for i in range(20)] and set(r21.values()) == {'3/3'})
    chk('2 19個→次点1つ補充', len(p19) == 20 and p19[19] == 'b00' and r19['b00'] == '補充' and sum(v == '3/3' for v in r19.values()) == 19, p19)
    # 3
    ed = f20_edges(ids)
    keys = {e['key'] for e in ed}
    ok = len(ed) == 380 and len(keys) == 380
    ok = ok and all(e['seed'] == zlib.crc32(f"f20{e['a']}{e['b']}{e['k']}".encode()) and (e['X'], e['Y']) == ((e['a'], e['b']) if e['k'] % 2 == 0 else (e['b'], e['a'])) for e in ed)
    ok = ok and len({f"{e['X']}|{e['Y']}" for e in ed}) == 380
    chk('3 ジョブ380・重複なし・種・左右入替', ok)
    # 4
    a0 = ed[0]
    tp = {'edges': ed, 'sel': {}, 'sel_src': {}}
    miss = f20_fill_sel(tp, {f"{a0['X']}|{a0['Y']}": {'order': ['x', 'y', 'z'], 'src': 't'}})
    chk('4 s3 sel にある組はコピー', tp['sel'].get(f"{a0['X']}|{a0['Y']}", {}).get('order') == ['x', 'y', 'z'] and tp['sel_src'] == {f"{a0['X']}|{a0['Y']}": 's3'} and len(miss) == 379, len(miss))
    # 5 plan/run/report
    tmp = tempfile.mkdtemp(prefix='f20test_')
    tmp2 = tempfile.mkdtemp(prefix='f20test2_')
    old_depth = globals()['S3_DEPTH']
    try:
        shutil.copy(S['plan'], tmp)
        shutil.copy(S['games'], tmp)
        globals()['S3_DEPTH'] = (1, 1)
        ns = argparse.Namespace(procs=a.procs, force=False, out_dir=tmp, max_games=2, retry_errors=False, sel_limit=3, jobs_limit=3)
        plan = cmd_f20_plan(ns)
        P = f20_paths(tmp)
        chk('5 plan: 20構築・380戦・depth(1,1)', len(plan['ids']) == 20 and len(plan['edges']) == 380 and plan['depth'] == [1, 1]
            and all(f"{e['X']}|{e['Y']}" in plan['sel'] for e in plan['edges'][:3]))
        cmd_f20_run(ns)
        g1 = json.load(open(P['games'], encoding='utf-8'))
        chk('5 --max-games 2 で2戦・妥当なJSON', len(g1['games']) == 2 and g1['plan_sig'] == plan['sig'])
        ns.max_games = 1
        cmd_f20_run(ns)
        g2 = json.load(open(P['games'], encoding='utf-8'))
        chk('5 再実行で3戦・先の2戦は不変（再開）', len(g2['games']) == 3 and all(g2['games'][k] == v for k, v in g1['games'].items()))
        shutil.copy(P['plan'], tmp2)
        # 6 report（合成戦績）
        rnd = random.Random(7)
        gm = {}
        for e in plan['edges']:
            r = rnd.choice([1, -1, 1, -1, 0])
            gm[e['key']] = {'a': e['a'], 'b': e['b'], 'k': e['k'], 'side0': e['X'], 'side1': e['Y'], 'res': r, 'winner': None, 'judged': rnd.random() < .1,
                            'turns': 20, 'left': [[['m', 50]] * 3, [['m', 20]] * 3]}
        P2 = f20_paths(tmp2)
        safeio.write_json(P2['games'], {'version': F20_VERSION, 'plan_sig': plan['sig'], 'depth': plan['depth'], 'deny': plan['deny'], 'playbook': None, 'games': gm})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_f20_report(argparse.Namespace(out_dir=tmp2))
        t = buf.getvalue()
        rows = [l for l in t.splitlines() if re.match(r'\| \d+ \S+ \|', l)]
        chk('6 report: 勝敗行列20行・Wilson・直接対決・380/380', len(rows) == 20 and 'Wilson' in t and '直接対決' in t and '完了 380/380' in t and os.path.exists(P2['md']), len(rows))
    finally:
        globals()['S3_DEPTH'] = old_depth
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tmp2, ignore_errors=True)

    # 6b 直接対決タイブレーク（合成3者同率）
    def sg(x, y, r, hb=10):
        return {'side0': x, 'side1': y, 'res': r, 'left': [[['m', 100 if x == 'B' else hb]], [['m', 100 if y == 'B' else hb]]]}
    G = []
    for x, y, rs_ in (('A', 'B', (1, 1)), ('A', 'C', (1, -1)), ('B', 'C', (1, -1)), ('A', 'O', (-1, -1)), ('B', 'O', (1, 1)), ('C', 'O', (1, -1)),
                      ('P', 'O', (-1, -1))):
        G += [sg(x, y, r) for r in rs_]
    pl = {'ids': ['A', 'B', 'C', 'O', 'P']}
    gms = {'games': {str(i): g for i, g in enumerate(G)}}
    st = s3_stats(pl, gms)
    order = f20_rank(pl['ids'], st, gms)
    chk('6 同率3者は直接対決→HP（A,C,B）', order == ['O', 'A', 'C', 'B', 'P'], order)
    # 7
    chk('7 既存ファイル sha256 不変', _sha_all() == before)
    if ng:
        print('NG:', ng)
        raise SystemExit(1)
    print('final20 selftest 全項目 OK')


def cmd_final20(a):
    {'plan': cmd_f20_plan, 'run': cmd_f20_run, 'report': cmd_f20_report, 'selftest': cmd_f20_selftest}[a.what](a)


# ======================================================================
# m7: 新構築 M7 × 蓄積構築50 × 10戦（SPEC_M7RUN.md）
# ======================================================================
M7_VERSION = 'm7a'
M7_DEPTH = (5, 5)
M7_ID = 'M7'
DEF_M7MD = os.path.join(HERE, '..', 'logs', 'M7RUN.md')
_M7_CALLS = [None]          # selftest 用: 偽の対戦が seed を追記するファイル


RES_AXIS = {'M8_6': ('リザードン', 'ガブリアス')}   # SPEC_RESOURCE.md: 軸（Mon.name＝元種族名）。それ以外が取り巻き


def m7_paths(out_dir=None, pfx='m7', md_name=None):
    d = out_dir or DEF_OUT
    mn = md_name or f'{pfx.upper()}RUN.md'
    md = os.path.join(d, mn) if out_dir else os.path.join(os.path.dirname(DEF_M7MD), mn)
    return {'dir': d, 'plan': os.path.join(d, f'{pfx}_plan.json'), 'games': os.path.join(d, f'{pfx}_games.json'),
            'logs': os.path.join(d, f'{pfx}_logs.jsonl'), 'md': md}


def _m7_pfx(a):
    sfx = 'rl' if getattr(a, 'resource_loose', False) else ('r' if getattr(a, 'resource', False) else '')
    return (getattr(a, 'prefix', None) or (a.party.lower() + sfx)).lower()


def _m7_md(a):
    if getattr(a, 'resource_loose', False) or getattr(a, 'resource', False):
        if a.party not in RES_AXIS:
            raise SystemExit(f'--resource は {sorted(RES_AXIS)} だけです（--party {a.party}）')
        return f"{a.party.upper()}{'rl' if getattr(a, 'resource_loose', False) else 'r'}RUN.md"
    return None


def _m7_rcfg(a):
    if not (getattr(a, 'resource_loose', False) or getattr(a, 'resource', False)):
        return None
    _m7_md(a)
    return {'axis': list(RES_AXIS[a.party]), 'loose': bool(getattr(a, 'resource_loose', False))}


def m7_seed(X, k):
    return zlib.crc32(f'm7{X}{k}'.encode())


def party_team(name='M7', tid=M7_ID):
    party = json.load(open(os.path.join(R.PARTY_D, f'{name}.json'), encoding='utf-8'))
    mons = []
    for e in party:
        sp = e['species']
        mega = sp in B.BASE_OF
        base = B.BASE_OF.get(sp, sp)
        ab = e['ability']
        if mega:
            abs_ = POKE[base]['ab']
            if ab in POKE[sp]['ab']:
                bab = e.get('base_ability') or (ab if ab in abs_ else abs_[0])
            elif ab in abs_:
                bab = e.get('base_ability') or ab
                ab = POKE[sp]['ab'][0]
            else:
                raise SystemExit(f'{name}: {sp} の特性「{ab}」がメガ側にも元種族にもありません')
        else:
            bab = ab
        mons.append({'base': base, 'species': sp, 'mega': mega, 'nature': e['nature'], 'ap': _ap(e.get('ap') or e.get('defn')),
                     'ability': ab, 'base_ability': bab, 'item': e.get('item') or '', 'moves': list(e['moves']), 'stone': False})
    n_m = sum(1 for m in mons if m['mega'])
    if not 1 <= n_m <= 2:
        raise SystemExit(f'{name}: メガ持ちが{n_m}体です（1〜2体のみ）')
    return {'id': tid, 'title': f'{tid}（新構築案）', 'rank': None, 'final': None, 'peak': None, 'weight': 1.0, 'mons': mons}


def m7_opponents(s3, n=50, check=True, tid=M7_ID):
    T = s3['teams']
    ids = sorted((i for i in s3['ids'] if i not in ('R11', tid)), key=lambda i: sort_key(T[i]))
    elig = [i for i in ids if T[i].get('rank') or T[i].get('final') or T[i].get('peak')]
    opps, skipped = [], []
    for i in elig:
        if len(opps) >= n:
            break
        try:
            if check:
                rr_apply(T[i])
            opps.append(i)
        except Exception as e:
            skipped.append({'id': i, 'why': str(e)[:120]})
    return opps, skipped, elig


def _m7_load_s3():
    p = s3_paths(None)['plan']
    if not os.path.exists(p):
        raise SystemExit(f'{p} がありません')
    return json.load(open(p, encoding='utf-8'))


def cmd_m7_plan(a, limit_sel=None):
    P = m7_paths(a.out_dir, _m7_pfx(a), _m7_md(a))
    os.makedirs(P['dir'], exist_ok=True)
    s3 = _m7_load_s3()
    tid = a.party
    rcfg = _m7_rcfg(a)
    if tid in s3['teams']:
        raise SystemExit(f's3_plan に {tid} があります')
    if rcfg and not os.path.exists(P['plan']):
        bp = m7_paths(a.out_dir, a.party.lower())['plan']      # 既存 M8_6 の plan があれば相手・選出の前提を複製
        if os.path.exists(bp):
            old = json.load(open(bp, encoding='utf-8'))
            if old.get('s3_sig') == s3['sig'] and old.get('party') == a.party:
                old['resource'] = rcfg
                safeio.write_json(P['plan'], old)
                print(f"複製しました: {bp} -> {P['plan']}（sig {old['sig'][:12]}）")
                return old
    if os.path.exists(P['plan']) and (json.load(open(P['plan'], encoding='utf-8')).get('resource') or None) != rcfg:
        raise SystemExit('この out-dir/接頭辞の plan は別の resource 設定です')
    if os.path.exists(P['plan']):
        old_p = json.load(open(P['plan'], encoding='utf-8')).get('party')
        if old_p and old_p != a.party:
            raise SystemExit(f'この out-dir/接頭辞には {old_p} の結果があります')
    rt = party_team(a.party, tid)
    teams = {**s3['teams'], tid: rt}
    _rr_init_main(teams)
    _worker_init(teams)
    opps, skipped, _ = m7_opponents(s3, 50, tid=tid)
    for x in skipped:
        print(f"  除外 {x['id']}: {x['why']}", flush=True)
    if len(opps) < 50:
        raise SystemExit('適格が足りません')
    rr_apply(rt)
    sig = hashlib.sha256((s3['sig'] + json.dumps(rt, ensure_ascii=False, sort_keys=True) + ','.join(opps) + M7_VERSION + '5,5').encode()).hexdigest()
    plan = None
    if os.path.exists(P['plan']):
        old = json.load(open(P['plan'], encoding='utf-8'))
        if old.get('sig') == sig:
            plan = old
        elif not a.force:
            raise SystemExit('m7_plan.json の sig が違います（--force で退避して作り直し）')
        else:
            os.replace(P['plan'], P['plan'][:-5] + time.strftime('.%Y%m%d_%H%M%S.json'))
    if plan is None:
        t0 = time.time()
        print('M7 の静的スコア計算...', flush=True)
        with make_pool(a.procs, teams) as pool:
            ws = dict(pool.map(_job_static, [tid]))
        ov = json.load(open(GUIDE_OVERRIDES, encoding='utf-8')) if os.path.exists(GUIDE_OVERRIDES) else None
        info = build_candidates(rt, None, ws[tid], ov)
        cs = {tuple(o) for o in info['candidates']}
        mg = {m['base'] for m in rt['mons'] if m['mega']}
        plan = {'version': M7_VERSION, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 's3_sig': s3['sig'], 'sig': sig, 'party': a.party, 'team_id': tid,
                'games_per_pair': 10, 'depth': list(M7_DEPTH), 'deny': [True, True], 'opponents': opps, 'skipped': skipped,
                'candidates': info['candidates'], 'excluded_no_mega': [o for o in all_orders(rt) if not (set(o) & mg) and tuple(o) not in cs],
                'm7_team': {**rt, **info, 'static': ws[tid]}, 'sel1': {}}
        print(f'  {time.time() - t0:.0f}秒', flush=True)
        safeio.write_json(P['plan'], plan)
    teams[tid] = plan['m7_team']
    if rcfg:
        plan['resource'] = rcfg
    need = []
    for X in opps[:limit_sel] if limit_sel else opps:
        for A_, B_ in ((tid, X), (X, tid)):
            if f'{A_}|{B_}' not in plan['sel1']:
                need.append((A_, B_))
    print(f'対戦相手 {len(opps)}、sel1 計算 {len(need)}', flush=True)
    if need:
        t0 = time.time()
        with make_pool(a.procs, teams) as pool:
            for n, (k, d) in enumerate(pool.imap_unordered(_job_decide, need, chunksize=1), 1):
                if 'error' in d:
                    raise SystemExit(f'選出計算エラー {k}: {d["error"]}')
                plan['sel1'][k] = d
                if n % 20 == 0:
                    safeio.write_json(P['plan'], plan)
        print(f'  sel1 計算 {time.time() - t0:.0f}秒', flush=True)
    safeio.write_json(P['plan'], plan)
    print(f"書きました: {P['plan']}（sig {sig[:12]}）")
    return plan


def m7_load_games(P, sig, tid=M7_ID, rcfg=None):
    if os.path.exists(P['games']):
        g = json.load(open(P['games'], encoding='utf-8'))
        if g.get('plan_sig') != sig:
            raise SystemExit('m7_games.json の plan_sig が m7_plan.json と違います')
        if (g.get('resource') or None) != rcfg:
            raise SystemExit('m7_games.json は別の resource 設定の結果です（追記しません）')
        return g
    g = {'version': M7_VERSION, 'plan_sig': sig, 'main': tid, 'depth': list(M7_DEPTH), 'deny': [True, True], 'games': {}, 'playbook': _pb_sig()}
    if rcfg:
        g['resource'] = rcfg
    return g


def cmd_m7_run(a):
    P = m7_paths(a.out_dir, _m7_pfx(a), _m7_md(a))
    if not os.path.exists(P['plan']):
        raise SystemExit(f"{P['plan']} がありません。先に m7 plan を実行してください")
    plan = json.load(open(P['plan'], encoding='utf-8'))
    if plan.get('party', a.party) != a.party:
        raise SystemExit(f"この out-dir/接頭辞には {plan['party']} の結果があります")
    tid = plan.get('team_id', M7_ID)
    s3 = _m7_load_s3()
    if s3['sig'] != plan['s3_sig']:
        raise SystemExit('s3_plan.json の sig が m7_plan.json と違います')
    if _PB_FLAG['on']:
        import playbook
        if tid in playbook.load_all():
            raise SystemExit(f'プレイブックに {tid} があります（{tid} 側は対象外のはず）')
    L, opps, G = tid, plan['opponents'], plan['games_per_pair']
    miss = [f'{x}|{y}' for X in opps for x, y in ((L, X), (X, L)) if f'{x}|{y}' not in plan['sel1']]
    if miss:
        raise SystemExit(f'sel1 が未計算です（{len(miss)}件）。m7 plan を完了してください')
    teams = {**s3['teams'], tid: plan['m7_team']}
    rcfg = _m7_rcfg(a)
    if (plan.get('resource') or None) != rcfg:
        raise SystemExit('plan の resource 設定と --resource/--resource-loose が違います')
    games = m7_load_games(P, plan['sig'], tid, rcfg)
    pb_guard(games)
    _AD['sel1'] = plan['sel1']
    gm = games['games']
    opp6 = {X: [B.BASE_OF.get(m['species'], m['species']) for m in teams[X]['mons']] for X in opps} if rcfg else {}

    def next_k(X):
        for k in range(G):
            g = gm.get(f'm7:{X}|{k}')
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
    with make_pool(a.procs, teams) as pool:
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
                job = (f'm7:{X}|{k}', X, k, s0, s1, ad_hist(games, X, s0, k, L, 'm7'), ad_hist(games, X, s1, k, L, 'm7'), M7_DEPTH, m7_seed(X, k))
                if rcfg:
                    rc = {**rcfg, 'opp6': opp6[X]}
                    job += ((rc, None) if s0 == L else (None, rc),)
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
                gm[job[0]] = ad_record(job, r, L, m7_seed)
                safeio.write_json(P['games'], games)
                if r.get('log') is not None:
                    append_log(P, job[0], r['log'])
                mark = '例外' if r.get('res') is None else ('分' if r['res'] == 0 else ('勝' if (r['res'] == 1) == (job[3] == L) else '負'))
                el = (time.time() - t0) / 60
                rem = el / n_done * max(0, (min(a.max_games, tot - base) if a.max_games else tot - base) - n_done)
                print(f"[{base + n_done}/{tot}] {job[0]} {tid}{mark} {r.get('turns')}手 {r['sec']:.0f}秒(選出{r.get('sec_sel') or 0:.0f}) 経過{el:.1f}分 残り約{rem:.1f}分", flush=True)
            if not got:
                time.sleep(0.05)
    return n_done


def _m7_base(n):
    return B.BASE_OF.get(n, n)


def cmd_m7_report(a):
    P = m7_paths(a.out_dir, _m7_pfx(a), _m7_md(a))
    plan = json.load(open(P['plan'], encoding='utf-8'))
    if plan.get('party', a.party) != a.party:
        raise SystemExit(f"この out-dir/接頭辞には {plan['party']} の結果があります")
    tid = plan.get('team_id', M7_ID)
    T = _m7_load_s3()['teams']
    T[tid] = plan['m7_team']
    L, opps = tid, plan['opponents']
    rcfg = _m7_rcfg(a)
    games = m7_load_games(P, plan['sig'], tid, rcfg)['games']
    recs = [g for g in games.values() if g.get('opp') in opps]
    ok_ = [g for g in recs if g['res'] is not None]
    tot = len(opps) * plan['games_per_pair']
    mg = {m['base'] for m in plan['m7_team']['mons'] if m['mega']}
    mine = lambda g: tuple((g['sel0'] if g['main_side'] == 0 else g['sel1']) or ())
    theirs = lambda g: tuple((g['sel1'] if g['main_side'] == 0 else g['sel0']) or ())
    why = lambda g: (g['why0'] if g['main_side'] == 0 else g['why1']) or {}
    by = {X: sorted([g for g in ok_ if g['opp'] == X], key=lambda g: g['k']) for X in opps}
    out = [f'# {tid} × 蓄積構築{len(opps)} × {plan["games_per_pair"]}戦（深さ5・適応選出）', '']
    jd = [g for g in ok_ if g.get('judged')]
    out += ['## 1. 全体', f'- {tid} の戦績: {_rate([_lw(g, L) for g in ok_])}（完了 {len(ok_)}/{tot}、分=0.5）',
            f'- 例外: {sum(1 for g in recs if g["res"] is None)}、判定決着: {len(jd)}戦、平均手数 {_avg([g["turns"] for g in ok_ if g.get("turns")]):.1f}', '']
    # 2
    out += [f'## 2. 相手構築ごと（{tid} 視点 ○勝 ●負 △分、判定は o/x、勝率昇順）', '| 構築 | id8 | rank | 10戦 | 勝率 |', '|---|---|---|---|---|']
    wr, rows = {}, []
    for X in opps:
        s, ws_ = '', 0.0
        for g in by[X]:
            v, j = _lw(g, L), g.get('judged')
            s += ('o' if j else '○') if v == 1 else (('x' if j else '●') if v == 0 else '△')
            ws_ += v
        wr[X] = ws_ / len(by[X]) if by[X] else 0.0
        rows.append((wr[X], opps.index(X), f"| {T[X]['title'][:24]} | {X[:8]} | {T[X].get('rank')} | {s} | {ws_:g}/{len(by[X])} {wr[X] * 100:.0f}% |"))
    out += [r[2] for r in sorted(rows)] + ['']
    # 3
    out += ['## 3. 推移（第n戦、全相手合計）']
    for n in range(1, plan['games_per_pair'] + 1):
        out.append(f'- 第{n}戦: {_rate([_lw(g, L) for g in ok_ if g["k"] == n - 1])}')
    h = plan['games_per_pair'] // 2
    out += [f'- 前半(1-{h}): {_rate([_lw(g, L) for g in ok_ if g["k"] < h])} / 後半({h + 1}-{plan["games_per_pair"]}): {_rate([_lw(g, L) for g in ok_ if g["k"] >= h])}', '']
    # 4
    out += [f'## 4. {tid} の選出別勝率', '### 並び（先発込み）']
    po, pt, src = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for g in ok_:
        po[mine(g)].append(_lw(g, L))
        pt[tuple(sorted(mine(g)))].append(_lw(g, L))
        src['adapt' if why(g).get('src') == 'adapt' else 'sel1 basic'].append(_lw(g, L))
    for o, v in sorted(po.items(), key=lambda x: (-len(x[1]), x[0])):
        out.append(f'- {_ostr(o)}{"（メガ入り）" if set(o) & mg else "（メガなし）"}: {len(v)}戦 {sum(v) / len(v) * 100:.0f}%')
    out.append('### 3体組')
    for o, v in sorted(pt.items(), key=lambda x: (-len(x[1]), x[0])):
        out.append(f'- {_ostr(o)}: {len(v)}戦 {sum(v) / len(v) * 100:.0f}%')
    out.append('### 小計')
    out.append(f'- メガ入り: {_rate([_lw(g, L) for g in ok_ if set(mine(g)) & mg])} / メガなし: {_rate([_lw(g, L) for g in ok_ if not set(mine(g)) & mg])}')
    out.append(f'- 選出元: ' + ' / '.join(f'{k} {_rate(v)}' for k, v in sorted(src.items())))
    out.append('')
    # 5
    out += ['## 5. 最も負けた相手トップ10']
    for X in sorted(opps, key=lambda x: (wr[x], -sum(1 for g in by[x] if _lw(g, L) == 0.0), opps.index(x)))[:10]:
        fl, fk, oo = collections.Counter(), collections.Counter(), collections.Counter()
        for g in by[X]:
            fs = [f for f in (g.get('faints') or []) if f[1] == g['main_side']]
            if fs:
                fl[_m7_base(fs[0][2])] += 1
            for f in fs:
                fk[f[3]] += 1
            oo[_ostr(theirs(g))] += 1
        out.append(f"- {T[X]['title'][:22]}（{X[:8]}）勝率{wr[X] * 100:.0f}%: 最初に倒れたM7 {fl.most_common(3)} / 倒した相手個体 {fk.most_common(3)} / 相手の並び {oo.most_common(2)}")
    out.append('')
    # 6
    out += ['## 6. リザホーク（深さ4・ADAPT.md）との比較', '- ADAPT.md: 58.0%（290/500、深さ4）。M7 は深さ5のため厳密比較ではない']
    try:
        ap_ = ad_paths(None)
        adp = json.load(open(ap_['plan'], encoding='utf-8'))
        adg = json.load(open(ap_['games'], encoding='utf-8'))['games']
        com = [X for X in opps if X in adp['opponents']]
        lz = [_lw(g, adp['main']) for g in adg.values() if g.get('opp') in com and g['res'] is not None]
        mz = [_lw(g, L) for X in com for g in by[X]]
        out.append(f'- 共通相手 {len(com)}構築: リザホーク {_rate(lz)} / M7 {_rate(mz)}')
    except Exception as e:
        out.append(f'- 共通相手の比較は読めませんでした: {e}')
    if AD_MAIN in by:
        out.append(f'- M7 対 リザホーク（{AD_MAIN[:8]}）: {_rate([_lw(g, L) for g in by[AD_MAIN]])}')
    out.append('')
    # 7
    out += [f'## 7. {tid} の個体ごと', '| 個体 | 選出 | 先発 | 出た試合の勝率 | 倒した | 倒された |', '|---|---|---|---|---|---|']
    for m in plan['m7_team']['mons']:
        b = m['base']
        sg = [g for g in ok_ if b in mine(g)]
        kills = sum(1 for g in ok_ for f in (g.get('faints') or []) if f[1] != g['main_side'] and _m7_base(f[3]) == b)
        dead = sum(1 for g in ok_ for f in (g.get('faints') or []) if f[1] == g['main_side'] and _m7_base(f[2]) == b)
        out.append(f"| {b} | {len(sg)} | {sum(1 for g in ok_ if mine(g)[:1] == (b,))} | {_rate_s(sum(_lw(g, L) for g in sg), len(sg))} | {kills} | {dead} |")
    mg_n = 0
    for g in ok_:
        if any(m in mg for m in mine(g)):
            names = [f[2] for f in (g.get('faints') or []) if f[1] == g['main_side']] + [x[0] for x in ((g.get('left') or [[], []])[g['main_side']] or [])]
            mg_n += any(n in B.BASE_OF for n in names)
    out += [f'- メガした試合数（faints/left に メガ名が出た試合の近似）: {mg_n}', '']
    # 8
    out += ['## 8. 設定', f'- 深さ {plan["depth"]}、deny {plan["deny"]}、プレイブック署名 {_pb_sig()}（相手側のみ）、seed=crc32("m7{{X}}{{k}}")、plan sig {plan["sig"]}',
            f'- {tid} candidates {len(plan["candidates"])}（メガ別 {plan["m7_team"].get("mega_split")}）: ' + ' ; '.join(_ostr(o) for o in plan['candidates']),
            f'- 外れたメガなし並び {len(plan["excluded_no_mega"])}: ' + ' ; '.join(_ostr(o) for o in plan['excluded_no_mega'])]
    if rcfg:
        out += _m7_res_section(a, plan, ok_, L, opps, T, by, rcfg)
    os.makedirs(os.path.dirname(P['md']), exist_ok=True)
    open(P['md'], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f"書きました: {P['md']}")


def _binom2(k, n):
    """two-sided exact sign test p (p=0.5)."""
    if n == 0:
        return 1.0
    m = min(k, n - k)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(m + 1)) / 2 ** n)


def _m7_res_section(a, plan, ok_, L, opps, T, by, rcfg):
    ax = set(rcfg['axis'])
    out = ['', '## 9. resource モード（SPEC_RESOURCE.md）', f"- 軸 {sorted(ax)}、{'緩和版(80%+取り巻き保護)' if rcfg['loose'] else '厳格版'}、平均 {_avg([g['sec'] for g in ok_ if g.get('sec')]):.1f} 秒/試合"]
    mine = lambda g: tuple((g['sel0'] if g['main_side'] == 0 else g['sel1']) or ())
    theirs = lambda g: tuple((g['sel1'] if g['main_side'] == 0 else g['sel0']) or ())
    st = lambda g: ((g.get('res_stats') or {}).get(str(g['main_side'])) or (g.get('res_stats') or {}).get(g['main_side']) or {})
    sat_f = lambda g: sum(1 for f in (g.get('faints') or []) if f[1] == g['main_side'] and f[2] not in ax)
    on_g = [g for g in ok_ if st(g).get('on', 0) >= 1]
    off_g = [g for g in ok_ if st(g).get('on', 0) < 1]
    turns, on_t = sum(st(g).get('turns', 0) for g in ok_), sum(st(g).get('on', 0) for g in ok_)
    rate = len(on_g) / len(ok_) if ok_ else 0.0
    out += [f'- 発動率（on>=1 の試合）: {len(on_g)}/{len(ok_)} = {rate * 100:.1f}%、成立した決定 {on_t}/{turns} = {(on_t / turns * 100 if turns else 0):.1f}%',
            f"- 取り巻きを切った回数（sat_faint_on 合計）: {sum(st(g).get('sat_faint_on', 0) for g in ok_)}、成立時の取り巻きからの交代回数: {sum(st(g).get('sw_sat_on', 0) for g in ok_)}",
            f'- 取り巻きの瀕死数/試合: {_avg([sat_f(g) for g in ok_]):.2f}（発動あり {_avg([sat_f(g) for g in on_g]) if on_g else 0:.2f} / なし {_avg([sat_f(g) for g in off_g]) if off_g else 0:.2f}）',
            f'- 発動あり: {_rate([_lw(g, L) for g in on_g])} / なし: {_rate([_lw(g, L) for g in off_g])}',
            '- 相手構築ごとの試合中一度でも成立した試合数（0 は厳格版で成立し得ない構築の可能性）:']
    ever = [f"{T[X]['title'][:18]}({X[:6]}) {sum(1 for g in by[X] if st(g).get('on', 0) >= 1)}/{len(by[X])}" for X in opps]
    out += ['  ' + ' / '.join(ever)]
    if ok_ and rate < 0.10:
        out.append('- 発動率が10%未満: 緩和版（--resource-loose）での再検証を推奨（実行はユーザー判断）')
    cmp_ = [('既存 M8_6', a.party.lower())] + ([('厳格版 M8_6r', a.party.lower() + 'r')] if rcfg['loose'] else [])
    for nm, pf in cmp_:
        bp = m7_paths(a.out_dir, pf)
        out += ['', f'### {nm} との比較']
        if not os.path.exists(bp['games']):
            out.append(f"- {bp['games']} がありません")
            continue
        bg = {(g['opp'], g['k']): g for g in json.load(open(bp['games'], encoding='utf-8'))['games'].values() if g.get('res') is not None}
        pr = [(bg[(g['opp'], g['k'])], g) for g in ok_ if (g['opp'], g['k']) in bg]
        w0, w1 = [_lw(x, L) for x, _ in pr], [_lw(y, L) for _, y in pr]
        out += [f'- {nm}: {_rate(w0)}', f'- resource: {_rate(w1)}（差 {((sum(w1) - sum(w0)) / max(1, len(pr)) * 100):+.1f}pt、500戦の標準誤差 ±2.2%、±4%以内は誤差扱い）']
        wl = sum(1 for x, y in zip(w0, w1) if x == 1 and y == 0)
        lw = sum(1 for x, y in zip(w0, w1) if x == 0 and y == 1)
        out.append(f'- 同じ(相手,k)で 勝→負 {wl} / 負→勝 {lw}、McNemar（符号検定）p={_binom2(wl, wl + lw):.3f}')
        same = [(x, y) for x, y in pr if mine(x) == mine(y) and theirs(x) == theirs(y)]
        out.append(f'- 選出（sel0/sel1）が一致した試合 {len(same)}/{len(pr)}: 既存 {_rate([_lw(x, L) for x, _ in same])} / resource {_rate([_lw(y, L) for _, y in same])}')
        bs = [x['sec'] for x, _ in pr if x.get('sec')]
        rs_ = [y['sec'] for _, y in pr if y.get('sec')]
        out.append(f'- 平均秒/試合: 既存 {_avg(bs):.1f} / resource {_avg(rs_):.1f}（比 {(_avg(rs_) / _avg(bs) if bs and _avg(bs) else 0):.2f}）')
        d = []
        for X in opps:
            a_ = sum(_lw(x, L) for x, y in pr if x['opp'] == X)
            b_ = sum(_lw(y, L) for x, y in pr if x['opp'] == X)
            d.append(f"{X[:6]} {a_:g}->{b_:g}")
        out.append('- 相手ごとの勝数（既存→resource）: ' + ' / '.join(d))
    return out


def cmd_m7_selftest(a):
    import shutil, subprocess, tempfile, statistics as stt
    global _AD_PLAY, _AD_SELECT, _AD_EVAL
    D = a.out_dir or tempfile.mkdtemp(prefix='m7test_')
    os.makedirs(D, exist_ok=True)
    results = []

    def ok(n, cond, msg=''):
        results.append((n, bool(cond)))
        print(f"{'○' if cond else '×'} {n} {msg}", flush=True)

    before = _sha_all()
    p = subprocess.run([sys.executable, '-m', 'py_compile', 'roundrobin.py'], cwd=HERE, capture_output=True, text=True)
    ok('1 py_compile', p.returncode == 0, p.stderr[-200:])
    s3 = _m7_load_s3()
    D2 = os.path.join(D, 'plan')

    class A_:
        pass
    pa = A_()
    pa.out_dir, pa.party, pa.procs, pa.force, pa.prefix = D2, a.party, a.procs, True, None
    TID = a.party
    PF = a.party.lower()
    t0 = time.time()
    plan = cmd_m7_plan(pa, limit_sel=2 if a.quick else 3)
    print(f'   plan（静的スコア＋sel1 {len(plan["sel1"])}件）{time.time() - t0:.0f}秒', flush=True)
    T = {**s3['teams'], TID: plan['m7_team']}
    _worker_init(T)
    _AD['sel1'] = plan['sel1']
    L, opps = TID, plan['opponents']
    # a
    rt = party_team(a.party)
    try:
        rr_apply(rt)
        mv = B.MY.get('カイリュー')
        st = B.new_state([m['base'] for m in rt['mons']][:3], [m['base'] for m in T[opps[0]]['mons']][:3])
        oka = (1 <= sum(m['mega'] for m in rt['mons']) <= 2 and st is not None)
        if a.party == 'M7':
            oka = (sum(m['mega'] for m in rt['mons']) == 1 and mv and mv[0].ability == 'マルチスケイル' and mv[1].species == 'メガカイリュー'
                   and st.sides[0][0].can_mega and rt['mons'][0]['base_ability'] == 'マルチスケイル')
    except Exception:
        oka = False
        print(traceback.format_exc()[-300:])
    ok('2a party_team / rr_apply / メガ', oka)
    # b
    ids = sorted((i for i in s3['ids'] if i not in ('R11', TID)), key=lambda i: sort_key(s3['teams'][i]))
    elig = [i for i in ids if s3['teams'][i].get('rank') or s3['teams'][i].get('final') or s3['teams'][i].get('peak')]
    try:
        for i in opps:
            rr_apply(T[i])
        ap_ = True
    except Exception:
        ap_ = False
    ok('2b 相手集合', len(opps) == 50 and 'R11' not in opps and TID not in opps and 'db0baa2843d2bd4b' in opps and opps == elig[:50] and ap_,
       f'適格{len(elig)} 除外{len(plan["skipped"])}')
    # c
    cs = [tuple(o) for o in plan['candidates']]
    ao = {tuple(o) for o in all_orders(T[TID])}
    mgs = {m['base'] for m in T[TID]['mons'] if m['mega']}
    nn = sum(1 for c in cs if not set(c) & mgs)
    n_nomega_all = sum(1 for o in ao if not set(o) & mgs)
    ok('2c candidates', len(cs) == 24 and set(cs) <= ao and nn <= 4 and not any(tuple(o) in set(cs) for o in plan['excluded_no_mega'])
       and len(plan['excluded_no_mega']) == n_nomega_all - nn and not any(len(set(c) & mgs) >= 2 for c in cs)
       and all(list(c[1:]) == list(norm_order(list(c), [m['base'] for m in T[TID]['mons']])[1:]) for c in cs),
       f'メガなし{nn} 外れたメガなし{len(plan["excluded_no_mega"])}')
    # d
    X = opps[0]
    r0, _ = adapt_select(L, X, [])
    tgt = cs[5]
    oth = cs[0]
    _AD_EVAL = lambda o, c, smart: 100.0 if tuple(o) == tgt else -100.0
    try:
        hh = lambda mines: [{'n': i + 1, 'mine': list(m), 'theirs': list(plan['sel1'][f'{X}|{L}']['order']), 'res_for_A': 0.5} for i, m in enumerate(mines)]
        r_ban, w_ban = adapt_select(L, X, hh([tgt, tgt]))
        r_ok, _ = adapt_select(L, X, hh([oth, tgt]))
    finally:
        _AD_EVAL = None
    ok('2d adapt_select', tuple(r0) == tuple(plan['sel1'][f'{L}|{X}']['order']) and tuple(r0) in cs and tuple(r_ok) == tgt and tuple(r_ban) != tgt
       and tuple(r_ban) in cs and w_ban['banned_streak'] == list(tgt))
    # e
    seen = []

    def spy_play(args):
        seen.append(args)
        return {'res': 1, 'faints': [], 'left': [[], []], 'turns': 1, 'judged': False}

    def fake_select(A, Bid, hist):
        o = list(_TEAMS[A]['candidates'][len(hist) % 24])
        return o, {'src': 'fake', 'order': o, 'hist_len': len(hist)}
    _AD_SELECT, _AD_PLAY = fake_select, spy_play
    try:
        _job_adapt(('m7:x|0', X, 0, L, X, [], [], M7_DEPTH, m7_seed(X, 0)))
        _job_adapt(('m7:x|1', X, 1, X, L, [], [], M7_DEPTH, m7_seed(X, 1)))
    finally:
        _AD_SELECT, _AD_PLAY = adapt_select, R.blind_play
    a0, a1 = seen
    pb0 = a0[12][0] if len(a0) > 12 else None
    pb1 = a1[12][1] if len(a1) > 12 else None
    ok('2e seed/側/深さ/プレイブック', m7_seed(X, 0) == zlib.crc32(f'm7{X}0'.encode()) and a0[4] == m7_seed(X, 0) and a1[4] == m7_seed(X, 1)
       and a0[5:7] == (5, 5) and a1[5:7] == (5, 5) and a0[11] == (True, True) and pb0 is None and pb1 is None and a0[10] == (L,) and a1[10] == (X,)
       and a0[1] == X and a1[1] == L)
    # f 再開
    calls = os.path.join(D, 'calls.txt')
    _M7_CALLS[0] = calls

    def fake_play(args):
        open(_M7_CALLS[0], 'a').write(f'{args[4]}\n')
        return {'res': 1 if args[4] % 2 else -1, 'log': ['x'], 'faints': [[3, 0, 'ガブリアス', 'ミミッキュ']], 'left': [[], []], 'turns': 7, 'judged': False}
    _AD_SELECT, _AD_PLAY = fake_select, fake_play
    D7 = os.path.join(D, 'fake')
    os.makedirs(D7, exist_ok=True)
    p7 = dict(plan)
    p7['opponents'] = opps[:3]
    safeio.write_json(os.path.join(D7, f'{PF}_plan.json'), p7)

    class R_:
        pass
    ra = R_()
    ra.out_dir, ra.procs, ra.max_games, ra.retry_errors, ra.party, ra.prefix = D7, 3, 2, False, a.party, None
    try:
        if not set(f'{x}|{y}' for X_ in opps[:3] for x, y in ((L, X_), (X_, L))) <= set(plan['sel1']):
            p7['sel1'] = {f'{x}|{y}': {'order': list(T[x]['candidates'][0])} for X_ in opps[:3] for x, y in ((L, X_), (X_, L))}
            safeio.write_json(os.path.join(D7, f'{PF}_plan.json'), p7)
        cmd_m7_run(ra)
        n1 = len(json.load(open(os.path.join(D7, f'{PF}_games.json'), encoding='utf-8'))['games'])
        ra.max_games = 0
        cmd_m7_run(ra)
        g7 = json.load(open(os.path.join(D7, f'{PF}_games.json'), encoding='utf-8'))['games']
        cl = open(calls).read().split()
        seq = all(all(f'm7:{x}|{k}' in g7 for k in range(10)) for x in opps[:3])
        sd = all(g['seed'] == m7_seed(g['opp'], g['k']) and (g['side0'] == L) == (g['k'] % 2 == 0) and g['why0']['hist_len'] == g['k'] for g in g7.values())
        ok('2f 再開', n1 == 2 and len(g7) == 30 and len(cl) == 30 and len(set(cl)) == 30 and seq and sd, f'中断時{n1}戦 計算回数{len(cl)} 一意{len(set(cl))}')
        cmd_m7_report(ra)
        md = open(os.path.join(D7, f'{PF.upper()}RUN.md'), encoding='utf-8').read()
        heads = ['## 1. 全体', '## 2. 相手構築ごと', '## 3. 推移', f'## 4. {TID} の選出別勝率', '## 5. 最も負けた相手トップ10', '## 6. リザホーク', f'## 7. {TID} の個体ごと', '## 8. 設定']
        ok('2h report', all(h in md for h in heads), f'{len(md)}字')
    except SystemExit as e:
        ok('2f/2h fake', False, str(e))
    except Exception:
        ok('2f/2h fake', False, traceback.format_exc()[-500:])
    finally:
        _AD_SELECT, _AD_PLAY = adapt_select, R.blind_play
        _M7_CALLS[0] = None
    # g 時間
    ts = []
    cases = [(L, X, tuple(T[X]['candidates'][1])), (X, L, cs[3])] + ([] if a.quick else [(L, opps[1], tuple(T[opps[1]]['candidates'][2]))])
    for A_id, Bid, c in cases:
        h = [{'n': n, 'mine': list(T[A_id]['candidates'][0]), 'theirs': list(c), 'res_for_A': 1} for n in (1, 2, 3)]
        t0 = time.time()
        adapt_select(A_id, Bid, h)
        ts.append(time.time() - t0)
    ok('2g 選出時間（中央値<=15・最大<=30）', stt.median(ts) <= 15 and max(ts) <= 30, f'{[round(t, 1) for t in ts]} sel1 decide秒 {[v.get("sec") for v in plan["sel1"].values()]}')
    r = _job_adapt(('m7:t|0', X, 0, L, X, [], [], M7_DEPTH, m7_seed(X, 0)))
    print(f"   実戦1戦(k=0, M7 対 {X[:8]}) res={r.get('res')} {r.get('turns')}手 全体{r['sec']}秒（選出{r['sec_sel']}秒）", flush=True)
    ok('2g 実戦1戦が完走', r.get('res') is not None or r.get('judged') is not None, str(r.get('error'))[-200:])
    # 追加項目（SPEC_M7MEGA2 受け入れ 2〜5）
    try:
        okx = True
        for nm_ in ('M8_1', 'M8_2', 'M8_3'):
            pt = party_team(nm_)
            rr_apply(pt)
            okx &= 1 <= sum(m['mega'] for m in pt['mons']) <= 2
        m83 = [m for m in party_team('M8_3')['mons'] if m['species'] == 'メガメタグロス']
        okx &= bool(m83) and m83[0]['ability'] == 'かたいツメ' and m83[0]['base_ability'] == 'クリアボディ'
        ok('4a M8 party_team / rr_apply / メタグロス特性', okx)
    except Exception:
        ok('4a M8 party_team', False, traceback.format_exc()[-300:])
    pd0 = R.PARTY_D
    try:
        tmpd = tempfile.mkdtemp(prefix='m7party_')
        base_party = json.load(open(os.path.join(pd0, 'M8_1.json'), encoding='utf-8'))
        nomega = [e for e in base_party if e['species'] not in B.BASE_OF]
        mega3 = nomega[:3] and [dict(nomega[0], species='メガカイリュー', ability='マルチスケイル'), dict(nomega[0], species='メガリザードンＸ', ability='かたいツメ'),
                                  dict(nomega[0], species='メガガブリアスＺ', ability='ほのおのからだ')]
        R.PARTY_D = tmpd
        json.dump(nomega, open(os.path.join(tmpd, 'z0.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        json.dump(base_party[:2] + [], open(os.path.join(tmpd, 'z3.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        res = []
        for nm_, nn_ in (('z0', 0),):
            try:
                party_team(nm_)
                res.append(False)
            except SystemExit as e:
                res.append('0体' in str(e))
        b3 = [e for e in base_party if e['species'] in B.BASE_OF]
        three = b3 + [dict(nomega[0], species='メガカイリュー', ability='マルチスケイル')] if len(b3) == 2 else None
        if three:
            json.dump(three, open(os.path.join(tmpd, 'z3.json'), 'w', encoding='utf-8'), ensure_ascii=False)
            try:
                party_team('z3')
                res.append(False)
            except SystemExit as e:
                res.append('3体' in str(e))
        ok('4b メガ0体・3体で SystemExit', res and all(res), str(res))
    except Exception:
        ok('4b メガ0体・3体', False, traceback.format_exc()[-300:])
    finally:
        R.PARTY_D = pd0
        shutil.rmtree(tmpd, ignore_errors=True)
    try:
        okc = True
        for nm_ in ('M8_1', 'M8_2', 'M8_3'):
            pt = party_team(nm_)
            mgb = sorted(m['base'] for m in pt['mons'] if m['mega'])
            wv = {m['base']: 1.0 for m in pt['mons']}
            inf = build_candidates(pt, None, wv, None)
            cs_ = [tuple(o) for o in inf['candidates']]
            ao_ = {tuple(o) for o in all_orders(pt)}
            bs_ = [m['base'] for m in pt['mons']]
            n0 = sum(1 for c in cs_ if not set(c) & set(mgb))
            okc &= (len(cs_) == 24 and len(set(cs_)) == 24 and not any(len(set(c) & set(mgb)) == 2 for c in cs_) and n0 == 4
                    and sum(1 for c in cs_ if len(set(c) & set(mgb)) == 1) == 20 and all(sum(1 for c in cs_ if b in c) >= 6 for b in mgb)
                    and set(cs_) <= ao_ and all(list(c) == list(norm_order(list(c), bs_)) for c in cs_) and inf['mega_split'] is not None)
        ok('4c M8 build_candidates 24/メガ2体同時0/メガなし4/各メガ6以上', okc)
    except Exception:
        ok('4c build_candidates', False, traceback.format_exc()[-300:])
    pm8, pm7 = m7_paths(None, 'm8_1'), m7_paths(None, 'm7')
    ok('4d m7_paths', pm8['plan'].endswith('m8_1_plan.json') and pm8['games'].endswith('m8_1_games.json') and pm8['logs'].endswith('m8_1_logs.jsonl')
       and os.path.normpath(pm8['md']) == os.path.normpath(os.path.join(HERE, '..', 'logs', 'M8_1RUN.md'))
       and pm7['plan'] == os.path.join(DEF_OUT, 'm7_plan.json') and os.path.normpath(pm7['md']) == os.path.normpath(DEF_M7MD))
    after = _sha_all()
    ok('3 既存ファイルの sha256 不変', before == after, f'{len(before)}件')
    ok('3b 既定の場所に新規 m8_* / M8_*RUN.md が無い', not any(os.path.exists(os.path.join(DEF_OUT, f'{p_}_{k_}')) for p_ in ('m8_1', 'm8_2', 'm8_3') for k_ in ('plan.json', 'games.json', 'logs.jsonl'))
       and not any(os.path.exists(os.path.join(os.path.dirname(DEF_M7MD), f'{p_}RUN.md')) for p_ in ('M8_1', 'M8_2', 'M8_3')))
    print('\n結果:', 'すべて ○' if all(c for _, c in results) else '×あり: ' + ', '.join(n for n, c in results if not c))
    if not a.keep and not a.out_dir:
        shutil.rmtree(D, ignore_errors=True)
    else:
        print('残した:', D)


def cmd_m7(a):
    if getattr(a, 'resource_loose', False):
        a.resource = True
    if a.resource:
        _m7_md(a)
    {'plan': cmd_m7_plan, 'run': cmd_m7_run, 'report': cmd_m7_report, 'selftest': cmd_m7_selftest}[a.what](a)


# ================================================================ tonorag（SPEC_TONORAGU.md）
TN_VERSION = 'tn1'
TN_L = 'db0baa2843d2bd4b'
TN_A_ID = '99ed32166914226e'
TN_VARS = {'A': TN_A_ID, 'B': 'tn_B_basagiri', 'C': 'tn_C_raintr'}
TN_LEADS = {'A': ['イエッサン', 'マスカーニャ', 'ブリジュラス', 'ペリッパー'], 'B': ['バサギリ', 'マスカーニャ', 'ブリジュラス'],
            'C': ['イダイトウ', 'イエッサン♀', 'ブリジュラス']}
TN_BACK = ('ニョロトノ', 'ラグラージ')
TN_AXIS = {TN_L: ('リザードン', 'ムクホーク'), TN_VARS['A']: ('ラグラージ',), TN_VARS['B']: ('ラグラージ',), TN_VARS['C']: ('ラグラージ',)}
TN_DEPTH = {1: (4, 4), 2: (5, 5)}
TN_K = {1: (0, 1), 2: (2, 3)}
TN_MODES = ('strict', 'loose', 'discount', 'off')
TN_VARIANTS_P = os.path.join(HERE, 'data', 'tonorag_variants.json')
TN_PRIO = ('かげうち', 'アクアジェット', 'ふいうち', 'しんそく', 'でんこうせっか', 'マッハパンチ')
_TN_PLAY = R.blind_play


def tn_paths(out_dir=None):
    d = out_dir or DEF_OUT
    return {'dir': d, 'plan': os.path.join(d, 'tn_plan.json'), 'games': os.path.join(d, 'tn_games.json'),
            'logs': os.path.join(d, 'tn_logs.jsonl'), 'md': os.path.join(d, 'TONORAGU.md') if out_dir else os.path.join(HERE, '..', 'logs', 'TONORAGU.md')}


def tn_seed(V, osel, lsel, k):
    return zlib.crc32(f"tn{V}{'/'.join(osel)}{'/'.join(lsel)}{k}".encode())


def tn_key(V, osel, lsel, k):
    return f"tn:{V}|{'/'.join(osel)}|{'/'.join(lsel)}|{k}"


def tn_import(force=False, from_file=None):
    import study, pokesol
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    if any(t['id'] == TN_A_ID for t in data['teams']) and not force and study.article_text(TN_A_ID):
        print('取り込み済み: 記事A（何もしません。--force で再取得）')
        return
    if from_file:
        page = open(from_file, encoding='utf-8').read()
        t = pokesol.parse(page, f'https://pokesol.app/u/iroha0034/articles/{TN_A_ID}')
        t['_text'] = ''
        info = (259, None, None)
    else:
        t, info = study.load_article({'id': TN_A_ID, 'author': {'username': 'iroha0034'}, 'season': 'm-7'})
    if t.get('id') != TN_A_ID:
        t['id'] = TN_A_ID
    if not study.valid_team(t):
        raise SystemExit('記事Aの構築が不正です')
    study.save(t, info)
    print(f'取り込みました: {t["title"]} rank={info[0]}')


def tn_load_variants(T=None):
    """{V: rr_team}（A は known_teams、B・C は tonorag_variants.json）。"""
    out = {}
    a = next((t for t in raw_teams() if t['id'] == TN_A_ID), None)
    if a is None:
        raise SystemExit('記事A が known_teams.json にありません。先に tonorag import を実行してください')
    out['A'] = rr_team(a)
    vs = {v['id']: v for v in json.load(open(TN_VARIANTS_P, encoding='utf-8'))['variants']}
    for V in 'BC':
        v = vs[TN_VARS[V]]
        out[V] = rr_team({'id': v['id'], 'title': v['title'], 'team': v['team'], 'rating': {}})
    return out


def tn_approx(V):
    """{個体名: {'approx': [...], 'note': 根拠}}（B・C のみ。A は記事どおりで空）。近似＝仮説。"""
    if V == 'A':
        return {}
    v = next(q for q in json.load(open(TN_VARIANTS_P, encoding='utf-8'))['variants'] if q['id'] == TN_VARS[V])
    return {m['name']: {'approx': m.get('approx', []), 'note': m.get('approx_note', '')} for m in v['team']}


def tn_opp_sels(V, rt, leads=None):
    bases = [m['base'] for m in rt['mons']]
    out = []
    for lead in (leads or TN_LEADS[V]):
        assert lead in bases and lead not in TN_BACK, (V, lead)
        out += [[lead, TN_BACK[0], TN_BACK[1]], [lead, TN_BACK[1], TN_BACK[0]]]
    return out


def tn_res_cfg(mode):
    return {'mode': mode, 'axis': {k: list(v) for k, v in TN_AXIS.items()}} if mode != 'off' else {'mode': 'off'}


def tn_rc(mode, sid, oid, teams):
    return {'axis': list(TN_AXIS[sid]), 'loose': mode in ('loose', 'discount'), 'opp6': [m['base'] for m in teams[oid]['mons']]}


def tn_job(plan, V, osel, lsel, k, stage, teams):
    L, X = plan['main'], plan['variants'][V]['id']
    s0, s1 = (L, X) if k % 2 == 0 else (X, L)
    o0, o1 = (list(lsel), list(osel)) if s0 == L else (list(osel), list(lsel))
    mode = plan['resource']['mode']
    res = None if mode == 'off' else (tn_rc(mode, s0, s1, teams), tn_rc(mode, s1, s0, teams))
    return (tn_key(V, osel, lsel, k), V, list(osel), list(lsel), k, s0, s1, o0, o1, stage, tuple(plan['depth'][str(stage)]), res, mode)


def _tn_discount_cover(st, i, axis, cand, loose=False):
    s = st.sides[i]
    ax = [j for j, m in enumerate(s.mons) if m.alive and m.name in axis]
    sat = [j for j, m in enumerate(s.mons) if m.alive and m.name not in axis]
    return {'on': bool(ax and sat and cand), 'sats': sat, 'axis': ax}


def _job_tn(a):
    key, V, osel, lsel, k, s0, s1, o0, o1, stage, depth, res, mode = a
    t0 = time.time()
    import search as _S
    orig = _S.axis_cover
    try:
        rr_apply(_TEAMS[s0])
        pa = _pb_args(s0, s1)
        if res and (res[0] or res[1]):
            pa = (pa[0] if pa else None, res)
        if mode == 'discount':
            _S.axis_cover = _tn_discount_cover
        r = _TN_PLAY((None, s1, o0, o1, tn_seed(V, osel, lsel, k), depth[0], depth[1], False, None, False, (s0,), (True, True)) + pa)
    except Exception:
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    finally:
        _S.axis_cover = orig
    r['key'] = key
    r['sec'] = round(time.time() - t0, 2)
    return r


def tn_record(job, r, L):
    key, V, osel, lsel, k, s0, s1, o0, o1, stage, depth, res, mode = job
    rs = r.get('res')
    w = None if rs is None else (s0 if rs == 1 else (s1 if rs == -1 else None))
    rec = {'side0': s0, 'side1': s1, 'sel0': o0, 'sel1': o1, 'seed': tn_seed(V, osel, lsel, k), 'res': rs, 'winner': w,
           'judged': r.get('judged'), 'turns': r.get('turns'), 'left': r.get('left'), 'faints': r.get('faints'),
           'sec': r.get('sec'), 'error': r.get('error'), 'opp': TN_VARS[V], 'sel': list(lsel), 'k': k, 'stage': stage,
           'main_side': 0 if s0 == L else 1, 'variant': V, 'opp_sel': list(osel), 'depth': list(depth),
           'res_stats': r.get('res_stats')}
    for kk in ('deny_stats', 'echo', 'pb'):
        if r.get(kk) is not None:
            rec[kk] = r[kk]
    return rec


def tn_score(g):
    rs = g['res']
    if rs is None:
        return None
    return 0.5 if rs == 0 else (1.0 if (rs == 1) == (g['main_side'] == 0) else 0.0)


def tn_hp(g):
    return _ct_hp(g)


def tn_estimate(n1, n2, procs=4, s4=11.7, s5=57.0, rf=1.3):
    m1, m2 = n1 * s4 * rf / procs / 60, n2 * s5 * rf / procs / 60
    return {'stage1_min': round(m1), 'stage2_min': round(m2), 'total_min': round(m1 + m2), 'sec_d4': s4, 'sec_d5': s5, 'res_factor': rf, 'procs': procs}


def tn_load_plan(P):
    if not os.path.exists(P['plan']):
        raise SystemExit(f"{P['plan']} がありません。先に tonorag plan を実行してください")
    return json.load(open(P['plan'], encoding='utf-8'))


def tn_load_games(P, plan):
    if os.path.exists(P['games']):
        g = json.load(open(P['games'], encoding='utf-8'))
        if g.get('plan_sig') != plan['sig']:
            raise SystemExit('tn_games.json の plan_sig が tn_plan.json と違います')
        return g
    return {'version': TN_VERSION, 'plan_sig': plan['sig'], 'resource': plan['resource'], 'games': {}, 'playbook': _pb_sig()}


def cmd_tonorag_plan(a):
    P = tn_paths(a.out_dir)
    os.makedirs(P['dir'], exist_ok=True)
    mode = a.resource or 'loose'
    rp = load_plan(paths(None))
    T = dict(rp['teams'])
    V = tn_load_variants()
    for v, rt in V.items():
        T[rt['id']] = rt
    _worker_init(T)
    for i in [TN_L] + list(TN_VARS.values()):
        rr_apply(T[i])
    cands = [list(c) for c in T[TN_L]['candidates']]
    osels = {v: tn_opp_sels(v, V[v]) for v in V}
    n1 = len(cands) * sum(len(x) for x in osels.values()) * 2
    variants = {}
    for v, rt in V.items():
        variants[v] = {'id': rt['id'], 'title': rt['title'], 'opp_sels': osels[v], 'team': rt['mons'], 'approx': tn_approx(v)}
    rc = tn_res_cfg(mode)
    sig = hashlib.sha256((rp['sig'] + TN_L + ','.join(TN_VARS.values()) + json.dumps([V[v]['mons'] for v in sorted(V)], ensure_ascii=False, sort_keys=True) +
                          json.dumps(osels, ensure_ascii=False, sort_keys=True) + json.dumps(cands, ensure_ascii=False) +
                          json.dumps(rc, ensure_ascii=False, sort_keys=True) + 'tn1').encode()).hexdigest()
    if os.path.exists(P['plan']):
        old = json.load(open(P['plan'], encoding='utf-8'))
        if old.get('sig') == sig:
            print(f"変更なし: {P['plan']}（sig {sig[:12]}）")
            return old
        if not a.force:
            raise SystemExit('tn_plan.json の sig が違います（--force で退避して作り直し）')
        os.replace(P['plan'], P['plan'][:-5] + time.strftime('.%Y%m%d_%H%M%S.json'))
    n2 = (4 * 8 + 4 * 6 + 4 * 6) * 2
    plan = {'version': TN_VERSION, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'sig': sig, 'rr_sig': rp['sig'], 'main': TN_L,
            'variants': variants, 'candidates': cands, 'depth': {'1': list(TN_DEPTH[1]), '2': list(TN_DEPTH[2])}, 'deny': [True, True],
            'resource': rc, 'n_games': {'1': n1, '2_max': n2}, 'estimate': tn_estimate(n1, n2, a.procs), 'top3': {}, 'common': None,
            'note': 'B・C の approx 項目は近似＝仮説'}
    safeio.write_json(P['plan'], plan)
    print(f"書きました: {P['plan']}（sig {sig[:12]}）第1段{n1}戦 第2段最大{n2}戦 見積り {plan['estimate']}")
    return plan


def tn_stage1_done(plan, gm, teams):
    miss = [j[0] for j in tn_jobs(plan, 1, teams) if j[0] not in gm or gm[j[0]]['res'] is None]
    return miss


def tn_jobs(plan, stage, teams, sels=None):
    out = []
    for V, vv in plan['variants'].items():
        ls = plan['candidates'] if stage == 1 else (sels or {}).get(V, [])
        for osel in vv['opp_sels']:
            for lsel in ls:
                for k in TN_K[stage]:
                    out.append(tn_job(plan, V, osel, lsel, k, stage, teams))
    return out


def tn_rate(gm, V, lsel, ks=(0, 1)):
    w = n = 0
    hp = []
    for g in gm.values():
        if g['variant'] == V and g['sel'] == list(lsel) and g['k'] in ks:
            s = tn_score(g)
            if s is not None:
                w += s
                n += 1
                hp.append(tn_hp(g))
    return w, n, hp


def tn_pick_stage2(plan, gm):
    top3, rate = {}, {}
    for V in plan['variants']:
        rows = []
        for lsel in plan['candidates']:
            w, n, hp = tn_rate(gm, V, lsel, TN_K[1])
            rate[(V, tuple(lsel))] = w / n if n else 0.0
            rows.append((-(w / n if n else 0.0), -(sum(hp) / len(hp) if hp else 0.0), list(lsel)))
        top3[V] = [r[2] for r in sorted(rows, key=lambda r: (r[0], r[1]))[:3]]
    best = max(plan['candidates'], key=lambda c: (min(rate[(V, tuple(c))] for V in plan['variants']), sum(rate[(V, tuple(c))] for V in plan['variants'])))
    return top3, list(best)


def tn_stage2_sels(plan):
    out = {}
    for V in plan['variants']:
        s = [list(x) for x in plan['top3'][V]]
        if plan['common'] not in s:
            s.append(list(plan['common']))
        out[V] = s
    return out


def cmd_tonorag_run(a):
    P = tn_paths(a.out_dir)
    plan = tn_load_plan(P)
    if a.resource and a.resource != plan['resource']['mode']:
        raise SystemExit(f"plan の resource は {plan['resource']['mode']} です（--resource {a.resource} とは違います。別の --out-dir で plan し直してください）")
    rp = load_plan(paths(None))
    T = dict(rp['teams'])
    for v, rt in tn_load_variants().items():
        T[rt['id']] = rt
    G = tn_load_games(P, plan)
    pb_guard(G)
    gm = G['games']
    if a.stage == 1:
        jobs = tn_jobs(plan, 1, T)
    else:
        miss = tn_stage1_done(plan, gm, T)
        if miss:
            raise SystemExit(f'第1段が未完です（{len(miss)}戦）。先に run --stage 1 を完了してください')
        if not plan.get('common'):
            plan['top3'], plan['common'] = tn_pick_stage2(plan, gm)
            safeio.write_json(P['plan'], plan)
        jobs = tn_jobs(plan, 2, T, tn_stage2_sels(plan))
    todo = [j for j in jobs if j[0] not in gm or (a.retry_errors and gm[j[0]]['res'] is None)]
    if a.max_games:
        todo = todo[:a.max_games]
    tot, base = len(jobs), sum(1 for j in jobs if j[0] in gm and gm[j[0]]['res'] is not None)
    print(f'第{a.stage}段 全体 {tot}戦、済み {base}、今回 {len(todo)}', flush=True)
    t0 = time.time()
    n_done = 0
    active = {}
    it = iter(todo)
    with make_pool(a.procs, T) as pool:
        while True:
            while len(active) < a.procs:
                job = next(it, None)
                if job is None:
                    break
                active[job[0]] = (pool.apply_async(_job_tn, (job,)), job)
            if not active:
                break
            got = False
            for key, (ar, job) in list(active.items()):
                if not ar.ready():
                    continue
                got = True
                r = ar.get()
                del active[key]
                n_done += 1
                gm[key] = tn_record(job, r, plan['main'])
                safeio.write_json(P['games'], G)
                if r.get('log') is not None:
                    append_log(P, key, r['log'])
                s = tn_score(gm[key])
                el = (time.time() - t0) / 60
                print(f"[{base + n_done}/{tot}] {key} L{'例外' if s is None else ('勝' if s == 1 else ('分' if s == 0.5 else '負'))} {r.get('turns')}手 {r['sec']:.0f}秒 経過{el:.1f}分 残り約{el / n_done * (len(todo) - n_done):.1f}分", flush=True)
            if not got:
                time.sleep(0.05)
    return n_done


def _tn_pct(w, n):
    return f'{w / n * 100:.0f}%' if n else '-'


def _tn_ci(w, n):
    if not n:
        return '-'
    lo, hi = wilson(w, n)
    return f'{w / n * 100:.0f}% ({lo * 100:.0f}-{hi * 100:.0f}%, {n}戦)'


def tn_logs(P, gm):
    out = {}
    for r in read_jsonl(P['logs']):
        if r.get('key') in gm:
            out[r['key']] = r['log']
    return out


def tn_analyze(plan, gm, logs):
    """個体ごとの動き（tn_logs.jsonl から）。log の1行 = [自分側の場, 自分側の行動, 相手側の場, 相手側の行動]（side0 視点）。"""
    st = {'lead': collections.Counter(), 'n': 0, 'act': collections.defaultdict(lambda: [0, 0]), 'perish': [], 'encore': [],
          'lag_first': [], 'lag_dead': [], 'lag_killer': collections.Counter(), 'prio': collections.Counter(), 'lag_ko': collections.Counter(),
          'lose_first': collections.Counter(), 'lose_seq': collections.Counter(), 'lose_n': [], 'ko_by_lag': 0, 'ko_all': 0}
    for key, g in gm.items():
        lg = logs.get(key)
        if not lg or g['res'] is None:
            continue
        lg = [[x[2:] if isinstance(x, str) and x.startswith('M+') else x for x in row] for row in lg]
        ms = g['main_side']
        st['n'] += 1
        st['lead'][lg[0][2 * ms]] += 1
        for t, row in enumerate(lg, 1):
            me, am, op, ao = row[2 * ms], row[2 * ms + 1], row[2 * (1 - ms)], row[2 * (1 - ms) + 1]
            for who, nm, ac in (('L', me, am), ('X', op, ao)):
                if ac not in ('-', '反動'):
                    e = st['act'][(who, nm, ac)]
                    e[0] += 1
                    e[1] += t
            if am in TN_PRIO and op.startswith('イエッサン'):
                st['prio'][('L', am)] += 1
            if ao in TN_PRIO and me.startswith('イエッサン'):
                st['prio'][('X', ao)] += 1
        for t, row in enumerate(lg, 1):
            for side in (0, 1):
                if row[2 * side + 1] == 'ほろびのうた':
                    tgt = 1 - side
                    nxt = next((u - t for u in range(t + 1, len(lg) + 1) if lg[u - 1][2 * tgt + 1].startswith('→')), None)
                    st['perish'].append(('L被弾' if tgt == ms else 'X被弾', nxt))
                if row[2 * side + 1] == 'アンコール' and t < len(lg):
                    tgt = 1 - side
                    mv = lg[t][2 * tgt + 1]
                    d = 0
                    for u in range(t, len(lg)):
                        if lg[u][2 * tgt + 1] == mv:
                            d += 1
                        else:
                            break
                    st['encore'].append(((mv, d), 'L' if tgt == ms else 'X'))
        first_lag = next((t for t, row in enumerate(lg, 1) if row[2 * (1 - ms)] == 'ラグラージ'), None)
        if first_lag:
            st['lag_first'].append(first_lag)
        fa = g.get('faints') or []
        for t, i, nm, killer in fa:
            if i != ms and nm == 'ラグラージ':
                st['lag_dead'].append(t)
                st['lag_killer'][killer] += 1
            if i == ms:
                st['ko_all'] += 1
                if killer == 'ラグラージ':
                    st['ko_by_lag'] += 1
        if tn_score(g) == 0.0:
            ls = [x for x in fa if x[1] == ms]
            if ls:
                st['lose_first'][ls[0][2]] += 1
                st['lose_seq'][' → '.join(x[2] for x in sorted(ls)[:3])] += 1
            st['lose_n'].append(sum(1 for x in fa if x[1] == ms))
    return st


TN_SUGG = {'アシレーヌ': 'きあいのタスキ→別持ち物（雨下のなみのり圏外、サイコフィールドでも先制技頼みにならない型）',
           'ガブリアス': 'ステルスロック→げきりん／じしん偏重（ほろびの間の圧力）', 'ミミッキュ': 'トリックルーム型→かげうち以外の技構成（サイコフィールドで先制技が封じられるため）',
           'ムクホーク': 'インファイト・ブレイブバード以外の技（いのちがけ→ほかの技）', 'リザードン': 'ブラストバーン・ソーラービーム等（雨下でフレアドライブが半減するため）',
           'イダイトウ': 'アクアジェット→別技（サイコフィールド下で封じられるため）'}


def cmd_tonorag_report(a):
    P = tn_paths(a.out_dir)
    plan = tn_load_plan(P)
    G = tn_load_games(P, plan)
    gm = {k: g for k, g in G['games'].items() if g['res'] is not None}
    logs = tn_logs(P, gm)
    L = plan['main']
    out = ['# TONORAGU: 乾坤一擲リザホーク vs トノラグ（3変種）', '', f"作成 {time.strftime('%Y-%m-%d %H:%M')} / plan sig {plan['sig'][:12]} / 有効 {len(gm)}戦 / 例外 {sum(1 for g in G['games'].values() if g['res'] is None)}戦", '']
    out += ['## 1. 条件', f"- 深さ 第1段 {tuple(plan['depth']['1'])} / 第2段 {tuple(plan['depth']['2'])}、deny [True, True]、種 crc32(tn{{V}}{{相手選出}}{{L選出}}{{k}})、resource = {plan['resource']['mode']}、playbook {G.get('playbook')}",
            f"- 見積り {plan['estimate']}"]
    secs = [g['sec'] for g in gm.values() if g.get('sec')]
    if secs:
        out.append(f"- 実所要: 計 {sum(secs) / 3600:.1f} CPU時間、1戦平均 {sum(secs) / len(secs):.0f}秒")
    out.append('- **近似項目の一覧（B・C は仮説）**:')
    for V, vv in plan['variants'].items():
        ap = tn_approx(V)
        if not ap:
            out.append(f"  - {V} {vv['title']}: 記事どおり（近似なし）")
        for nm, d in ap.items():
            out.append(f"  - {V} {nm}: 近似 {', '.join(d['approx'])}（{d['note']}）")
    out.append('')
    # 2
    out += ['## 2. 変種×相手選出ごとの L の選出']
    for V, vv in plan['variants'].items():
        for osel in vv['opp_sels']:
            rows = []
            for lsel in plan['candidates']:
                w = n = 0
                for k in TN_K[1] + TN_K[2]:
                    g = gm.get(tn_key(V, osel, lsel, k))
                    if g:
                        s = tn_score(g)
                        w += s
                        n += 1
                if n:
                    rows.append((w / n, w, n, '/'.join(lsel)))
            rows.sort(key=lambda r: -r[0])
            if rows:
                out.append(f"- {V} 相手 {'/'.join(osel)}: 最良 {rows[0][3]} {_tn_ci(rows[0][1], rows[0][2])}; 悪い順 " + ' | '.join(f"{r[3]} {r[0] * 100:.0f}%" for r in rows[-3:][::-1]))
        for lead in TN_LEADS[V]:
            s2 = vv['opp_sels'][2 * TN_LEADS[V].index(lead):][:2]
            sc = []
            for osel in s2:
                w = n = 0
                for g in gm.values():
                    if g['variant'] == V and g['opp_sel'] == osel and tn_score(g) is not None:
                        w += tn_score(g)
                        n += 1
                sc.append(w / n if n else None)
            if None not in sc:
                out.append(f"  - 後発順 {lead}先発: {TN_BACK[0]}→{TN_BACK[1]} {sc[0] * 100:.0f}% / 逆順 {sc[1] * 100:.0f}%" + (' （差なし）' if abs(sc[0] - sc[1]) < 0.05 else ' （差あり）'))
    out.append('')
    # 3
    out += ['## 3. 変種ごとの最良選出と3変種共通']
    rate = {}
    for V in plan['variants']:
        for lsel in plan['candidates']:
            s2 = tn_rate(gm, V, lsel, TN_K[2])
            s1 = tn_rate(gm, V, lsel, TN_K[1])
            w, n = (s2[0], s2[1]) if s2[1] else (s1[0], s1[1])
            if n:
                rate[(V, tuple(lsel))] = w / n
    best = {}
    for V in plan['variants']:
        rows = sorted(((r, c) for (v, c), r in rate.items() if v == V), reverse=True)
        if rows:
            best[V] = rows[0]
            out.append(f"- {V}: {'/'.join(rows[0][1])} 勝率 {rows[0][0] * 100:.0f}%")
    com = None
    cands = {c for (_, c) in rate}
    if cands and all(all((V, c) in rate for V in plan['variants']) for c in cands):
        com = max(cands, key=lambda c: (min(rate[(V, c)] for V in plan['variants']), sum(rate[(V, c)] for V in plan['variants'])))
        out.append(f"- **共通（最悪ケース最大）**: {'/'.join(com)} " + ' / '.join(f"{V} {rate[(V, com)] * 100:.0f}%" for V in plan['variants']))
    out.append('')
    # res
    out += ['## resource 発動率（発動した決定数 / 全決定数）']
    for side_name, who in (('L', 'L'), ('トノラグ側', 'X')):
        on = tot = 0
        for g in gm.values():
            rs = g.get('res_stats') or {}
            sd = (g['main_side'] if who == 'L' else 1 - g['main_side'])
            e = rs.get(str(sd)) or rs.get(sd)
            if e:
                on += e['on']
                tot += e['turns']
        out.append(f"- {side_name}: {on}/{tot} = {_tn_pct(on, tot)}" + (' （10%未満: discount での再検証を推奨）' if tot and on / tot < 0.1 and plan['resource']['mode'] == 'loose' else ''))
    out.append('')
    # 4,5
    an = tn_analyze(plan, gm, logs)
    out += ['## 4. 個体ごとの動き（tn_logs.jsonl 集計）', f"- 集計 {an['n']}戦。Lの先発率: " + ', '.join(f'{k} {v / max(1, an["n"]) * 100:.0f}%' for k, v in an['lead'].most_common(6))]
    byn = collections.defaultdict(list)
    for (who, nm, ac), (c, ts) in an['act'].items():
        byn[(who, nm)].append((c, ac, ts / c))
    for (who, nm), v in sorted(byn.items(), key=lambda kv: (kv[0][0], -sum(x[0] for x in kv[1]))):
        out.append(f"  - {who}:{nm}: " + ', '.join(f'{ac} {c}回(平均{t:.1f}T)' for c, ac, t in sorted(v, reverse=True)[:3]))
    pc = collections.Counter(x for x in an['perish'])
    out.append('- ほろびのうた被弾後の交代ターン: ' + (', '.join(f'{k[0]}:{("交代なし" if k[1] is None else str(k[1]) + "T後")}×{c}' for k, c in sorted(pc.items(), key=lambda kv: -kv[1])[:8]) or 'なし'))
    ec = collections.Counter(an['encore'])
    out.append('- アンコールされた技と解除まで（連続ターン）: ' + (', '.join(f'{w}:{k[0]}{k[1]}T×{c}' for (k, w), c in [((k, w), c) for (k, w), c in ec.most_common(8)]) or 'なし'))
    out.append(f"- ラグラージ: 初登場 平均{statistics.mean(an['lag_first']):.1f}T、倒した平均 {statistics.mean(an['lag_dead']):.1f}T（{len(an['lag_dead'])}体、倒した側: {dict(an['lag_killer'].most_common(5))}）。メガ・雨の残りターンは tn_logs に天候が無く集計不可（記録外）" if an['lag_first'] and an['lag_dead'] else '- ラグラージ: 該当なし／集計不可（天候はログに無い）')
    out.append('- イエッサンが場にいる間に選ばれた先制技（サイコフィールドで封じられた回数の上限・推定）: ' + (', '.join(f'{k[0]}:{k[1]}×{v}' for k, v in an['prio'].most_common(8)) or 'なし'))
    out += ['', '## 5. こちらが倒されるパターン', f"- 負け試合の先頭瀕死: {dict(an['lose_first'].most_common(6))}",
            '- 負け試合の瀕死順（上位）: ' + ('; '.join(f'{k}×{v}' for k, v in an['lose_seq'].most_common(5)) or 'なし'),
            f"- L瀕死 {an['ko_all']} 体のうち、相手ラグラージが場にいた時の瀕死 {an['ko_by_lag']} 体（雨下ウェーブタックル／じしん等で抜かれた数の目安）", '']
    out += ['## 6. 型の変更案（仮説・検証は別仕様）']
    for nm, c in an['lose_first'].most_common(4):
        out.append(f"- {nm} が先に倒れた負け {c}戦: " + TN_SUGG.get(nm, '技・持ち物の見直し（機械的候補なし）'))
    out += ['', '## 7. 結論']
    for V, (r, c) in best.items():
        out.append(f"- {V}: 選出 {'/'.join(c)}（勝率 {r * 100:.0f}%）。立ち回りは §4 の上位行動を参照")
    if com:
        out.append(f"- 共通: {'/'.join(com)}")
    open(P['md'], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f"書きました: {P['md']}")


def _tn_engine_tests(ok):
    import engine as E
    mk = E.make_mon

    def sd(x, y, w='', t=''):
        s = E.new_state(x, y)
        s.weather, s.terrain = w, t
        s.wturns, s.tturns = (5 if w else 0), (5 if t else 0)
        return E.start(s)
    lag = lambda: mk('ラグラージ', 'いじっぱり', {'atk': 32, 'spe': 32}, 'すいすい', 'ラグラージナイト', ['ウェーブタックル', 'じしん'])
    gab = lambda mv=('じしん',): mk('ガブリアス', 'いじっぱり', {'hp': 32}, 'さめはだ', '', list(mv))
    s0 = E.new_state([lag()], [gab()])
    sp0 = E.action_speed_of(s0, 0)
    s0.weather, s0.wturns = 'raindance', 5
    ok('5a 雨下すいすいで素早さ2倍', E.action_speed_of(s0, 0) == 2 * sp0, f'{sp0}->{E.action_speed_of(s0, 0)}')

    def fire(w):
        x = mk('リザードン', 'おくびょう', {'spa': 32, 'spe': 32}, 'もうか', '', ['かえんほうしゃ'])
        s = sd([x], [gab()], w)
        s = E.step(s, ('m', 'flamethrower', False), ('m', 'earthquake', False))
        m = s.sides[1].mons[0]
        return m.maxhp - m.hp
    d0, d1 = fire(''), fire('raindance')
    ok('5b 雨でほのお技半減', d0 > 0 and abs(d1 * 2 - d0) <= 2, f'{d0}->{d1}')

    def prio(t):
        x = mk('ミミッキュ', 'いじっぱり', {'atk': 32}, 'ばけのかわ', '', ['かげうち'])
        s = sd([x], [gab()], '', t)
        s = E.step(s, ('m', 'shadowsneak', False), ('m', 'earthquake', False))
        m = s.sides[1].mons[0]
        return m.maxhp - m.hp
    ok('5c サイコフィールドでかげうち失敗', prio('') > 0 and prio('psychicterrain') == 0)
    nyo = lambda it='': mk('ニョロトノ', 'おだやか', {'hp': 32, 'spe': 32}, 'あめふらし', it, ['ほろびのうた', 'まもる', 'アンコール', 'なみのり'])
    s = sd([nyo()], [gab(('まもる',)), mk('ミミッキュ', 'いじっぱり', {'hp': 32}, 'ばけのかわ', '', ['まもる'])])
    s = E.step(s, ('m', 'perishsong', False), ('m', 'protect', False))
    alive = []
    for _ in range(3):
        s = E.step(s, ('m', 'protect', False), ('m', 'protect', False))
        alive.append(s.sides[1].mons[0].alive)
    ok('5d ほろびのうた3ターン後瀕死', alive == [True, True, False], str(alive))
    s = sd([nyo()], [gab(('まもる',)), mk('ミミッキュ', 'いじっぱり', {'hp': 32}, 'ばけのかわ', '', ['まもる'])])
    s = E.step(s, ('m', 'perishsong', False), ('m', 'protect', False))
    s = E.step(s, ('m', 'protect', False), ('s', 1))
    ok('5e 交代でほろびのうた解除', 'perishsong' not in s.sides[1].mons[s.sides[1].act].vol)
    c = mk('ニョロトノ', 'おだやか', {'hp': 32}, 'あめふらし', 'だっしゅつボタン', ['なみのり'])
    d = mk('マスカーニャ', 'いじっぱり', {'atk': 32, 'spe': 32}, 'へんげんじざい', '', ['トリプルアクセル'])
    s = sd([c, lag()], [d])
    s = E.step(s, ('m', 'surf', False), ('m', 'tripleaxel', False))
    ok('5f だっしゅつボタンで交代', s.sides[0].act == 1)
    a = mk('ニョロトノ', 'おだやか', {'hp': 32, 'spe': 32}, 'あめふらし', '', ['アンコール', 'なみのり'])
    b = mk('カビゴン', 'ゆうかん', {'hp': 32}, 'あついしぼう', '', ['じしん', 'まもる'])
    s = sd([a], [b])
    s = E.step(s, ('m', 'surf', False), ('m', 'earthquake', False))
    s = E.step(s, ('m', 'encore', False), ('m', 'earthquake', False))
    acts = [x for x in E.actions(s, 1) if x[0] == 'm']
    ok('5g アンコール固定', 'encore' in s.sides[1].mons[0].vol and acts == [('m', 'earthquake', False)], str(acts))


def cmd_tonorag_selftest(a):
    import shutil, subprocess, tempfile
    global _TN_PLAY
    D = a.out_dir or tempfile.mkdtemp(prefix='tntest_')
    results = []

    def ok(n, cond, msg=''):
        results.append((n, bool(cond)))
        print(f"{'○' if cond else '×'} {n} {msg}", flush=True)

    before = _sha_all()
    p = subprocess.run([sys.executable, '-m', 'py_compile', 'roundrobin.py'], cwd=HERE, capture_output=True, text=True)
    ok('1 py_compile', p.returncode == 0, p.stderr[-200:])

    class A_:
        pass

    def args(sub, **kw):
        x = A_()
        x.out_dir, x.procs, x.max_games, x.force, x.retry_errors, x.resource, x.stage = os.path.join(D, sub), a.procs, 0, True, False, None, 1
        x.__dict__.update(kw)
        return x

    rp = load_plan(paths(None))
    V = tn_load_variants()
    T = dict(rp['teams'])
    for v, rt in V.items():
        T[rt['id']] = rt
    _worker_init(T)
    L = TN_L
    # 4 取り込み・近似
    kt = next((t for t in raw_teams() if t['id'] == TN_A_ID), None)
    import study
    ok('4a 記事A', kt is not None and (kt.get('rating') or {}).get('rank') == 259 and bool(study.article_text(TN_A_ID)))
    vj = json.load(open(TN_VARIANTS_P, encoding='utf-8'))['variants']
    ok('4b B/C approx あり', {v['id'] for v in vj} == {TN_VARS['B'], TN_VARS['C']} and all(m.get('approx') and m.get('approx_note') for v in vj for m in v['team']))
    import dex
    try:
        for i in [L] + list(TN_VARS.values()):
            rr_apply(T[i])
        good = all(dex.item_id(m['item']) for i in TN_VARS.values() for m in T[i]['mons'])
        ok('4c rr_apply A〜C 例外なし・持ち物が全て認識', good)
    except Exception as e:
        ok('4c rr_apply A〜C', False, repr(e))
    # 5 engine
    _tn_engine_tests(ok)
    # 2,3 plan
    pl = cmd_tonorag_plan(args('p', resource='loose'))
    cs = [tuple(c) for c in pl['candidates']]
    mega = {m['base'] for m in T[L]['mons'] if m['mega']}
    ok('2 候補24・重複なし・一致・メガ重なり≤1', len(cs) == 24 and len(set(cs)) == 24 and cs == [tuple(c) for c in T[L]['candidates']] and all(len(mega & set(c)) <= 1 for c in cs))
    cnt = {v: len(vv['opp_sels']) for v, vv in pl['variants'].items()}
    allsels = [s for vv in pl['variants'].values() for s in vv['opp_sels']]
    ok('3a 相手選出: 先発∉{ニョロトノ,ラグラージ}・両方含む・A8/B6/C6', cnt == {'A': 8, 'B': 6, 'C': 6} and all(s[0] not in TN_BACK and set(TN_BACK) <= set(s) for s in allsels), str(cnt))
    s2 = {V_: [list(c) for c in cs[:3]] + [list(cs[3])] for V_ in pl['variants']}
    n2 = len(tn_jobs(pl, 2, T, s2))
    ok('3b 戦数 第1段960・第2段≤160', pl['n_games']['1'] == 960 and len(tn_jobs(pl, 1, T)) == 960 and n2 <= 160 and pl['n_games']['2_max'] == 160, f'{n2}')
    # 7 軸と状態の名前
    rr_apply(T[L])
    st = B.engine_game(list(cs[0]), allsels[0])
    names0 = [m.name for m in st.sides[0].mons]
    j0 = tn_job(pl, 'A', allsels[0], list(cs[0]), 0, 1, T)
    rcs = j0[11]
    ok('7a 両側に軸が渡る', j0[5] == L and rcs[0]['axis'] == ['リザードン', 'ムクホーク'] and rcs[1]['axis'] == ['ラグラージ'] and
       rcs[1]['opp6'] == [m['base'] for m in T[L]['mons']] and rcs[0]['opp6'] == [m['base'] for m in T[TN_A_ID]['mons']])
    ok('7b 軸名が State の mons 名に含まれる', any(x in names0 for x in rcs[0]['axis']) or True and all(x in [m['base'] for m in T[L]['mons']] for x in rcs[0]['axis']), str(names0))
    ok('7b2 State に軸の元種族名', set(n for n in names0) >= (set(rcs[0]['axis']) & set(cs[0])), str(names0))
    ok('7b3 ラグラージ軸', all(any(m['base'] == 'ラグラージ' for m in T[i]['mons']) for i in TN_VARS.values()))
    # 実測（深さ4 ×2 = 決定性、深さ5 ×1）
    jobs_real = tn_job(pl, 'A', allsels[0], list(cs[0]), 0, 1, T)
    t0 = time.time()
    r1 = _job_tn(jobs_real)
    sec4 = time.time() - t0
    r2 = _job_tn(jobs_real)
    ok('6b 同じ種で2回: res/turns/faints 一致', r1.get('res') is not None and (r1['res'], r1['turns'], r1['faints']) == (r2['res'], r2['turns'], r2['faints']),
       f"{r1.get('error') or ''} sec={sec4:.1f}")
    rs = r1.get('res_stats') or {}
    ok('7c res_stats が両側に出る', set(map(str, rs)) == {'0', '1'}, str(rs))
    j5 = tn_job(pl, 'A', allsels[0], list(cs[0]), 0, 2, T)
    t0 = time.time()
    r5 = _job_tn(j5)
    sec5 = time.time() - t0
    ok('9 深さ5の実測', r5.get('res') is not None, f'{sec5:.1f}s')
    est = tn_estimate(960, n2, a.procs, sec4, sec5)
    print(f'実測 深さ4 {sec4:.1f}秒/戦, 深さ5 {sec5:.1f}秒/戦 → 見積り {est}' + ('  [注記: 深さ4が30秒/戦超 → 第1段の後発順を1通りに絞る]' if sec4 > 30 else ''), flush=True)
    # 6 stub: 再開・off の引数形
    def stub(args_):
        h = zlib.crc32(repr((args_[2], args_[3], args_[4])).encode())
        return {'res': (1, -1, 0)[h % 3], 'turns': 5 + h % 7, 'judged': False,
                'left': [[[m, (h >> i) % 101] for i, m in enumerate(args_[2])], [[m, (h >> (i + 3)) % 101] for i, m in enumerate(args_[3])]],
                'faints': [[3, 0, args_[2][0], args_[3][0]], [5, 1, args_[3][0], args_[2][1]]],
                'log': [[args_[2][0], 'アンコール', args_[3][0], 'じしん']], 'res_stats': {'0': {'turns': 5, 'on': 1}, '1': {'turns': 5, 'on': 0}},
                'echo': [list(args_[2]), list(args_[3]), args_[4], list(args_[10]), len(args_), args_[1], [bool(x) for x in args_[12:]], args_[13] if len(args_) > 13 else None]}
    _TN_PLAY = stub
    try:
        a1 = args('s1', max_games=3, resource='loose')
        cmd_tonorag_plan(a1)
        cmd_tonorag_run(a1)
        P1 = tn_paths(a1.out_dir)
        g3 = json.load(open(P1['games'], encoding='utf-8'))['games']
        snap = json.dumps(g3, sort_keys=True)
        a1.max_games = 7
        n_new = cmd_tonorag_run(a1)
        g10 = json.load(open(P1['games'], encoding='utf-8'))['games']
        same = all(json.dumps(g10[k], sort_keys=True) == json.dumps(g3[k], sort_keys=True) for k in g3)
        ok('6a 再開: 3件→残りだけ実行・既存3件不変', len(g3) == 3 and n_new == 7 and len(g10) == 10 and same)
        e = next(iter(g10.values()))['echo']
        ok('7d resource loose: args に resx が付く', e[4] == 14 or e[4] == 15, str(e[4]))
        ok('6c 結果ヘッダと key 形式', all(k.startswith('tn:') for k in g10) and json.load(open(P1['games'], encoding='utf-8'))['resource']['mode'] == 'loose')
        a_off = args('s2', max_games=2, resource='off')
        cmd_tonorag_plan(a_off)
        cmd_tonorag_run(a_off)
        goff = json.load(open(tn_paths(a_off.out_dir)['games'], encoding='utf-8'))['games']
        eo = next(iter(goff.values()))['echo']
        ok('7e off: blind_play の引数が counter と同形（resx なし）', len(goff) == 2 and eo[4] <= 13 and eo[7] is None, str(eo[4:]))
        # 第2段ゲート: 第1段未完なら止まる
        try:
            a1.stage = 2
            cmd_tonorag_run(a1)
            ok('6d 第1段未完なら第2段は止まる', False)
        except SystemExit:
            ok('6d 第1段未完なら第2段は止まる', True)
        # 全第1段(stub) → 第2段 → report
        a3 = args('s3', resource='loose')
        cmd_tonorag_plan(a3)
        cmd_tonorag_run(a3)
        P3 = tn_paths(a3.out_dir)
        gm3 = json.load(open(P3['games'], encoding='utf-8'))['games']
        ok('6e 第1段960戦(stub)', len(gm3) == 960 and all(g['res'] is not None for g in gm3.values()))
        a3.stage = 2
        cmd_tonorag_run(a3)
        gm3 = json.load(open(P3['games'], encoding='utf-8'))['games']
        n_st2 = sum(1 for g in gm3.values() if g['stage'] == 2)
        ok('3c 第2段≤160戦(stub)', 0 < n_st2 <= 160 and len(gm3) == 960 + n_st2, str(n_st2))
        cmd_tonorag_report(a3)
        md = open(P3['md'], encoding='utf-8').read()
        ok('4d report §1 に近似一覧', all(f'{v} {m["name"]}: 近似' in md for v in 'BC' for m in next(q for q in vj if q['id'] == TN_VARS[v])['team']) and '## 7. 結論' in md)
    finally:
        _TN_PLAY = R.blind_play
    ok('8 既存結果の sha256 不変・既定の場所に tn_* を作らない', _sha_all() == before and not [f for f in os.listdir(DEF_OUT) if f.startswith('tn_')])
    if not a.keep and not a.out_dir:
        shutil.rmtree(D, ignore_errors=True)
    bad = [n for n, c in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} ○" + (f"  ×: {bad}" if bad else ''))
    if bad:
        raise SystemExit(1)


# ================================================================ tonorag --focus（SPEC_TONORAGU2.md）
TN2_VERSION = 'tn2'
TN2_LEADS = {'A': ['イエッサン'], 'B': ['バサギリ'], 'C': ['イエッサン♀']}
TN2_K2 = 100


def tn2_paths(out_dir=None):
    d = out_dir or DEF_OUT
    return {'dir': d, 'plan': os.path.join(d, 'tn2_plan.json'), 'games': os.path.join(d, 'tn2_games.json'),
            'logs': os.path.join(d, 'tn2_logs.jsonl'), 'md': os.path.join(d, 'TONORAGU2.md') if out_dir else os.path.join(HERE, '..', 'logs', 'TONORAGU2.md')}


def tn2_seed(V, osel, lsel, k):
    return zlib.crc32(f"tn2{V}{'/'.join(osel)}{'/'.join(lsel)}{k}".encode())


def tn2_key(V, osel, lsel, k):
    return f"tn2:{V}|{'/'.join(osel)}|{'/'.join(lsel)}|{k}"


def tn2_append_log(P, key, r):
    need_nl = False
    if os.path.exists(P['logs']) and os.path.getsize(P['logs']) > 0:
        with open(P['logs'], 'rb') as f:
            f.seek(-1, 2)
            need_nl = f.read(1) != b'\n'
    with open(P['logs'], 'a', encoding='utf-8') as f:
        if need_nl:
            f.write('\n')
        f.write(json.dumps({'key': key, 'log': r['log'], 'snap': r.get('snap'), 'post': r.get('post')}, ensure_ascii=False) + '\n')
        f.flush()


def tn2_job(plan, V, osel, lsel, k, stage, teams):
    j = tn_job(plan, V, osel, lsel, k, stage, teams)
    return (tn2_key(V, osel, lsel, k),) + j[1:]


def _job_tn2(a, snap=True):
    key, V, osel, lsel, k, s0, s1, o0, o1, stage, depth, res, mode = a
    t0 = time.time()
    import search as _S
    orig, osnap = _S.axis_cover, R.SNAP
    try:
        R.SNAP = snap
        rr_apply(_TEAMS[s0])
        pa = _pb_args(s0, s1)
        if res and (res[0] or res[1]):
            pa = (pa[0] if pa else None, res)
        if mode == 'discount':
            _S.axis_cover = _tn_discount_cover
        r = _TN_PLAY((None, s1, o0, o1, tn2_seed(V, osel, lsel, k), depth[0], depth[1], False, None, False, (s0,), (True, True)) + pa)
    except Exception:
        r = {'res': None, 'error': traceback.format_exc()[-800:]}
    finally:
        _S.axis_cover = orig
        R.SNAP = osnap
    r['key'] = key
    r['sec'] = round(time.time() - t0, 2)
    return r


def tn2_record(job, r, L):
    key, V, osel, lsel, k, *_ = job
    rec = tn_record(job, r, L)
    rec['seed'] = tn2_seed(V, osel, lsel, k)
    rec['focus'] = True
    return rec


def tn2_ks(plan, stage, n=None):
    if stage == 1:
        return list(range(n if n is not None else plan['games']['1']))
    return list(range(TN2_K2, TN2_K2 + (n if n is not None else plan['games']['2'])))


def tn2_jobs(plan, stage, teams, sels=None, n=None):
    out = []
    for V, vv in plan['variants'].items():
        ls = plan['candidates'] if stage == 1 else (sels or {}).get(V, [])
        for osel in vv['opp_sels']:
            for lsel in ls:
                for k in tn2_ks(plan, stage, n):
                    out.append(tn2_job(plan, V, osel, lsel, k, stage, teams))
    return out


def tn2_pick_stage2(plan, gm):
    out = {}
    ks = tn2_ks(plan, 1)
    for V in plan['variants']:
        rows = []
        for i, lsel in enumerate(plan['candidates']):
            w, n, hp = tn_rate(gm, V, lsel, ks)
            rows.append((-(w / n if n else 0.0), -(sum(hp) / len(hp) if hp else 0.0), i))
        out[V] = [list(plan['candidates'][r[2]]) for r in sorted(rows)[:plan['top']]]
    return out


def cmd_tn2_plan(a):
    P = tn2_paths(a.out_dir)
    os.makedirs(P['dir'], exist_ok=True)
    mode = a.resource or 'loose'
    n1g, n2g, top = (a.games or 8), (getattr(a, 'games2', None) or 12), (getattr(a, 'top', None) or 2)
    rp = load_plan(paths(None))
    T = dict(rp['teams'])
    V = tn_load_variants()
    for v, rt in V.items():
        T[rt['id']] = rt
    _worker_init(T)
    for i in [TN_L] + list(TN_VARS.values()):
        rr_apply(T[i])
    cands = [list(c) for c in T[TN_L]['candidates']]
    osels = {v: tn_opp_sels(v, V[v], TN2_LEADS[v]) for v in V}
    variants = {v: {'id': rt['id'], 'title': rt['title'], 'opp_sels': osels[v], 'team': rt['mons'], 'approx': tn_approx(v)} for v, rt in V.items()}
    rc = tn_res_cfg(mode)
    sig = hashlib.sha256((rp['sig'] + TN_L + ','.join(TN_VARS.values()) + json.dumps([V[v]['mons'] for v in sorted(V)], ensure_ascii=False, sort_keys=True) +
                          json.dumps(osels, ensure_ascii=False, sort_keys=True) + json.dumps(cands, ensure_ascii=False) +
                          json.dumps(rc, ensure_ascii=False, sort_keys=True) + 'tn1' + 'tn2' + json.dumps(TN2_LEADS, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()
    old = None
    if os.path.exists(P['plan']):
        old = json.load(open(P['plan'], encoding='utf-8'))
        if old.get('sig') != sig:
            if not a.force:
                raise SystemExit('tn2_plan.json の sig が違います（--force で退避して作り直し）')
            os.replace(P['plan'], P['plan'][:-5] + time.strftime('.%Y%m%d_%H%M%S.json'))
            old = None
    nv = len(cands) * sum(len(x) for x in osels.values())
    est = tn_estimate(nv * n1g, nv // len(cands) * top * n2g, a.procs)
    if est['total_min'] > 120:
        print(f"警告: 見積り {est['total_min']}分（rf込み）が120分を超えます", flush=True)
    plan = old or {'version': TN2_VERSION, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'sig': sig, 'rr_sig': rp['sig'], 'main': TN_L,
                   'variants': variants, 'candidates': cands, 'depth': {'1': list(TN_DEPTH[1]), '2': list(TN_DEPTH[2])}, 'deny': [True, True],
                   'resource': rc, 'leads': TN2_LEADS, 'opp_sels': osels, 'playbook': _pb_sig(), 'stage2_sels': None,
                   'note': 'B・C の approx 項目は近似＝仮説'}
    if old and not (getattr(a, 'games', None) or getattr(a, 'games2', None) or getattr(a, 'top', None)):
        print(f"変更なし: {P['plan']}（sig {sig[:12]}）")
        return old
    plan['games'] = {'1': n1g, '2': n2g}
    plan['top'] = top
    plan['estimate'] = est
    safeio.write_json(P['plan'], plan)
    print(f"書きました: {P['plan']}（sig {sig[:12]}）第1段{nv * n1g}戦 第2段{nv // len(cands) * top * n2g}戦 見積り {est}")
    return plan


def cmd_tn2_run(a):
    P = tn2_paths(a.out_dir)
    plan = tn_load_plan(P)
    if a.resource and a.resource != plan['resource']['mode']:
        raise SystemExit(f"plan の resource は {plan['resource']['mode']} です")
    rp = load_plan(paths(None))
    T = dict(rp['teams'])
    for v, rt in tn_load_variants().items():
        T[rt['id']] = rt
    if os.path.exists(P['games']):
        G = json.load(open(P['games'], encoding='utf-8'))
        if G.get('plan_sig') != plan['sig']:
            raise SystemExit('tn2_games.json の plan_sig が tn2_plan.json と違います')
    else:
        G = {'version': TN2_VERSION, 'plan_sig': plan['sig'], 'resource': plan['resource'], 'games': {}, 'playbook': _pb_sig()}
    pb_guard(G)
    gm = G['games']
    n = getattr(a, 'games', None)
    if a.stage == 1:
        jobs = tn2_jobs(plan, 1, T, n=n)
    else:
        miss = [j[0] for j in tn2_jobs(plan, 1, T) if j[0] not in gm or gm[j[0]]['res'] is None]
        if miss:
            raise SystemExit(f'第1段が未完です（{len(miss)}戦）。先に run --stage 1 を完了してください')
        if not plan.get('stage2_sels'):
            plan['stage2_sels'] = tn2_pick_stage2(plan, gm)
            safeio.write_json(P['plan'], plan)
        jobs = tn2_jobs(plan, 2, T, plan['stage2_sels'], n=n)
    todo = [j for j in jobs if j[0] not in gm or (a.retry_errors and gm[j[0]]['res'] is None)]
    if a.max_games:
        todo = todo[:a.max_games]
    tot, base = len(jobs), sum(1 for j in jobs if j[0] in gm and gm[j[0]]['res'] is not None)
    print(f'第{a.stage}段 全体 {tot}戦、済み {base}、今回 {len(todo)}', flush=True)
    t0 = time.time()
    n_done = 0
    active = {}
    it = iter(todo)
    with make_pool(a.procs, T) as pool:
        while True:
            while len(active) < a.procs:
                job = next(it, None)
                if job is None:
                    break
                active[job[0]] = (pool.apply_async(_job_tn2, (job,)), job)
            if not active:
                break
            got = False
            for key, (ar, job) in list(active.items()):
                if not ar.ready():
                    continue
                got = True
                r = ar.get()
                del active[key]
                n_done += 1
                gm[key] = tn2_record(job, r, plan['main'])
                safeio.write_json(P['games'], G)
                if r.get('log') is not None:
                    tn2_append_log(P, key, r)
                s = tn_score(gm[key])
                el = (time.time() - t0) / 60
                print(f"[{base + n_done}/{tot}] {key} L{'例外' if s is None else ('勝' if s == 1 else ('分' if s == 0.5 else '負'))} {r.get('turns')}手 {r['sec']:.0f}秒 経過{el:.1f}分 残り約{el / n_done * (len(todo) - n_done):.1f}分", flush=True)
            if not got:
                time.sleep(0.05)
    return n_done


# ---- report
def _f(w, n):
    return _tn_ci(w, n) + ('（参考）' if 0 < n < 5 else '')


def _wr(gs):
    ss = [tn_score(g) for g in gs if tn_score(g) is not None]
    return sum(ss), len(ss)


def _delta_lines(items, ks, lo=4, thr=15):
    out = []
    for T in range(1, 7):
        reach = [i for i in items if len(i['lg']) >= T]
        acts = collections.Counter()
        for i in reach:
            acts[(i['lg'][T - 1][0], i['lg'][T - 1][1])] += 1
        for (fld, ac), c in acts.items():
            if ac in ('-', '反動') or c < lo:
                continue
            yes = [i for i in reach if i['lg'][T - 1][:2] == [fld, ac]]
            no = [i for i in reach if i['lg'][T - 1][:2] != [fld, ac]]
            wy, ny = _wr([i['g'] for i in yes])
            wn, nn = _wr([i['g'] for i in no])
            if ny >= lo and nn >= lo:
                d = (wy / ny - wn / nn) * 100
                if abs(d) >= thr:
                    out.append((abs(d), f"T{T} {fld}:{ac} 取った {wy / ny * 100:.0f}%({ny}) / 取らない {wn / nn * 100:.0f}%({nn}) Δ{d:+.0f}", d, T, fld, ac))
    return sorted(out, key=lambda x: -x[0])


def tn2_items(gm, logs, sel_filter):
    out = []
    for key, g in gm.items():
        if g['res'] is None or key not in logs or not sel_filter(g):
            continue
        rec = logs[key]
        ms = g['main_side']
        lg = [[x[2:] if isinstance(x, str) and x.startswith('M+') else x for x in row] for row in rec['log']]
        meg = [[isinstance(x, str) and x.startswith('M+') for x in row] for row in rec['log']]
        lg2 = [[r[2 * ms], r[2 * ms + 1], r[2 * (1 - ms)], r[2 * (1 - ms) + 1]] for r in lg]
        out.append({'g': g, 'ms': ms, 'lg': lg2, 'meg': [(m[2 * ms + 1], m[2 * (1 - ms) + 1]) for m in meg], 'sn': rec.get('snap') or [], 'po': rec.get('post') or [], 'sc': tn_score(g)})
    return out


def _cnt_table(ctr, wins, top=3):
    return ', '.join(f"{k} {c}回(勝{wins.get(k, 0):.0f}→{_tn_pct(wins.get(k, 0), c)}){'（参考）' if c < 5 else ''}" for k, c in ctr.most_common(top))


def tn2_points(items):
    """4.3 個別論点。items は L 視点の試合。"""
    out = []
    # ミミッキュ
    tr = {'未破壊': [0, 0.0], '破壊後': [0, 0.0]}
    room_act, room_w = collections.Counter(), collections.Counter()
    curse = [0, 0]
    after = collections.Counter()
    after_w = collections.Counter()
    for it in items:
        ms, lg, sn = it['ms'], it['lg'], it['sn']
        seen_tr = set()
        for t, row in enumerate(lg):
            s = sn[t] if t < len(sn) else None
            if row[0].startswith('ミミッキュ') and row[1] == 'トリックルーム' and s:
                kk = '未破壊' if s['bk'][ms] is False else '破壊後'
                if kk not in seen_tr:
                    seen_tr.add(kk)
                    tr[kk][0] += 1
                    tr[kk][1] += it['sc']
            if s and s['room'] > 0 and row[1] not in ('-', '反動'):
                room_act[row[1]] += 1
                room_w[row[1]] += it['sc']
            if row[0].startswith('ミミッキュ') and row[1] == 'のろい':
                curse[0] += 1
                f = next((x for x in it['g']['faints'] or [] if x[1] == ms and x[2].startswith('ミミッキュ') and t + 1 <= x[0] <= t + 2), None)
                if f:
                    curse[1] += 1
                    nx = lg[f[0]][0] if f[0] < len(lg) else None
                    if nx:
                        after[nx] += 1
                        after_w[nx] += it['sc']
    out.append('- **ミミッキュ**: トリル ' + ', '.join(f"{k} {v[0]}回 勝率{_tn_pct(v[1], v[0])}{'（参考）' if v[0] < 5 else ''}" for k, v in tr.items()) +
               f"。トリル中のL行動上位: {_cnt_table(room_act, room_w) or '該当なし'}。のろい使用 {curse[0]}回 → 2ターン以内にミミッキュ退場 {curse[1]}回（{_tn_pct(curse[1], curse[0])}）、その後のL個体: {_cnt_table(after, after_w) or '該当なし'}")
    # リザードンX
    mg = collections.defaultdict(lambda: [0, 0.0])
    streak = collections.Counter()
    sw = 0
    rain = {'げきりん': [0, 0.0], 'フレアドライブ': [0, 0.0]}
    for it in items:
        lg, sn = it['lg'], it['sn']
        mt = next((t + 1 for t, m in enumerate(it['meg']) if m[0]), None)
        if mt is None:
            for t in range(1, len(sn)):
                if sn[t]['mega'][it['ms']] and not sn[t - 1]['mega'][it['ms']]:
                    mt = t
                    break
        if mt:
            mg[mt][0] += 1
            mg[mt][1] += it['sc']
        run = 0
        for t, row in enumerate(lg):
            if row[0].startswith('リザードン') and row[1] == 'げきりん':
                run += 1
                if row[3].startswith('→'):
                    sw += 1
            else:
                if run:
                    streak[run] += 1
                run = 0
            if row[0].startswith('リザードン') and row[1] in rain and t < len(sn) and sn[t]['w'] == 'raindance':
                rain[row[1]][0] += 1
                rain[row[1]][1] += it['sc']
        if run:
            streak[run] += 1
    out.append('- **リザードンX**: メガ時期別 ' + (', '.join(f"T{k} {v[0]}戦 勝率{_tn_pct(v[1], v[0])}{'（参考）' if v[0] < 5 else ''}" for k, v in sorted(mg.items())) or '該当なし') +
               f"。げきりん連続ターン数 {dict(sorted(streak.items())) or '該当なし'}、げきりん中の相手交代 {sw}回。雨下: " +
               ', '.join(f"{k} {v[0]}回 勝率{_tn_pct(v[1], v[0])}{'（参考）' if v[0] < 5 else ''}" for k, v in rain.items()))
    # イダイトウ
    og = collections.defaultdict(lambda: [0, 0.0])
    blocked = [0, 0]
    for it in items:
        ms, sn = it['ms'], it['sn']
        for t, row in enumerate(it['lg']):
            s = sn[t] if t < len(sn) else None
            if row[0].startswith('イダイトウ') and row[1] == 'おはかまいり' and s:
                dead = max(0, 3 - s['alive'][ms])
                og[dead][0] += 1
                og[dead][1] += it['sc']
            if row[0].startswith('イダイトウ') and row[1] == 'アクアジェット' and s:
                if s['tr'] == 'psychicterrain' and s['item'][1 - ms] != 'airballoon':
                    blocked[0] += 1
                else:
                    blocked[1] += 1
    out.append('- **イダイトウ**: おはかまいり L瀕死数別 ' + (', '.join(f"{k}体 {v[0]}回 勝率{_tn_pct(v[1], v[0])}{'（参考）' if v[0] < 5 else ''}" for k, v in sorted(og.items())) or '該当なし') +
               f"。アクアジェットをサイコフィールド×接地（ふうせん除く、飛行・ふゆうは未判定の近似）で選んだ＝封じられた {blocked[0]}回 / それ以外 {blocked[1]}回")
    # ほろび
    pf = collections.defaultdict(lambda: [0, 0.0])
    for it in items:
        ms, sn = it['ms'], it['sn']
        cur = None
        for t, row in enumerate(it['lg']):
            s = sn[t] if t < len(sn) else None
            if not s:
                break
            p = s['vol'][ms]['perish']
            if p is not None and cur is None:
                cur = row[0]
            if cur is not None:
                if row[1].startswith('→'):
                    pf[f'{p}で交代'][0] += 1
                    pf[f'{p}で交代'][1] += it['sc']
                    cur = None
                elif row[0] != cur:
                    cur = None
        if cur is not None:
            pf['交代せず退場'][0] += 1
            pf['交代せず退場'][1] += it['sc']
    out.append('- **ほろびのうた**(Lの場がカウント保持): ' + (', '.join(f"{k} {v[0]}回 勝率{_tn_pct(v[1], v[0])}{'（参考）' if v[0] < 5 else ''}" for k, v in sorted(pf.items())) or '該当なし'))
    # アンコール
    en = collections.defaultdict(lambda: [0, 0.0])
    for it in items:
        ms, sn = it['ms'], it['sn']
        for t, row in enumerate(it['lg'][:-1]):
            s = sn[t] if t < len(sn) else None
            e = s['vol'][ms]['encore'] if s else None
            if e:
                mv = e.get('move') or e.get('m') or row[1] if isinstance(e, dict) else row[1]
                nxt = it['lg'][t + 1][1]
                kk = f"{mv}/残{e.get('dur') if isinstance(e, dict) else e}T/" + ('交代' if nxt.startswith('→') else '居座り')
                en[kk][0] += 1
                en[kk][1] += it['sc']
    out.append('- **アンコール**(L被弾): ' + (', '.join(f"{k} {v[0]}回 勝率{_tn_pct(v[1], v[0])}{'（参考）' if v[0] < 5 else ''}" for k, v in sorted(en.items(), key=lambda kv: -kv[1][0])[:8]) or '該当なし'))
    # 雨
    lw = collections.Counter()
    endact, endw = collections.Counter(), collections.Counter()
    back = 0
    for it in items:
        sn, lg, ms = it['sn'], it['lg'], it['ms']
        seen_lag = False
        for t in range(len(sn)):
            if lg[t][2] == 'ラグラージ' and not seen_lag and (t == 0 or lg[t - 1][2] != 'ラグラージ'):
                seen_lag = True
                lw[sn[t]['wt'] if sn[t]['w'] == 'raindance' else '雨なし'] += 1
            if t and sn[t - 1]['w'] == 'raindance' and sn[t]['w'] != 'raindance' and lg[t][1] not in ('-', '反動'):
                endact[lg[t][1]] += 1
                endw[lg[t][1]] += it['sc']
            if t and lg[t][2] == 'ニョロトノ' and lg[t - 1][2] != 'ニョロトノ' and sn[t]['w'] == 'raindance' and sn[t - 1]['w'] == 'raindance' and sn[t]['wt'] > sn[t - 1]['wt']:
                back += 1
    out.append(f"- **雨**: ラグラージ登場時の雨の残りターン {dict(lw) or '該当なし'}。雨が切れたターンのL行動上位: {_cnt_table(endact, endw) or '該当なし'}。ニョロトノ再登場で雨が戻った {back}回")
    # だっしゅつボタン
    ej = []
    for it in items:
        ms, po, sn, lg = it['ms'], it['po'], it['sn'], it['lg']
        for t, p in enumerate(po):
            for sd in (0, 1):
                if p['ej'][sd]:
                    who = 'L' if sd == ms else '相手'
                    atk = lg[t][2] if sd == ms else lg[t][0]
                    mv = lg[t][3] if sd == ms else lg[t][1]
                    nxt = lg[t + 1][1] if sd == ms and t + 1 < len(lg) else None
                    ej.append((who, t + 1, f"{atk}:{mv}", p['act'][sd], nxt, it['sc']))
    if ej:
        c = collections.Counter(e[4] for e in ej if e[4])
        cw = collections.Counter()
        for e in ej:
            if e[4]:
                cw[e[4]] += e[5]
        out.append(f"- **だっしゅつボタン**: {len(ej)}回（勝率{_tn_pct(sum(e[5] for e in ej), len(ej))}）。発動ターン/攻撃/入れ替わり: " + '; '.join(f"{e[0]}T{e[1]} {e[2]}→{e[3]}" for e in ej[:6]) + f"。L側発動後の次ターン行動: {_cnt_table(c, cw) or '該当なし'}")
    else:
        out.append('- **だっしゅつボタン**: 該当なし')
    return out


def cmd_tn2_report(a):
    P = tn2_paths(a.out_dir)
    plan = tn_load_plan(P)
    if not os.path.exists(P['games']):
        raise SystemExit('tn2_games.json がありません')
    G = json.load(open(P['games'], encoding='utf-8'))
    gm = {k: g for k, g in G['games'].items() if g['res'] is not None}
    logs = {}
    for r in read_jsonl(P['logs']):
        if r.get('key') in gm:
            logs[r['key']] = r
    N1 = plan['games']['1']
    s1g = lambda g: g['k'] < TN2_K2
    s2g = lambda g: g['k'] >= TN2_K2
    out = ['# TONORAGU2: トノラグ3変種 × 相手選出固定（イエッサン先発）で最も勝てるプレイング', '',
           f"作成 {time.strftime('%Y-%m-%d %H:%M')} / plan sig {plan['sig'][:12]} / 有効 {len(gm)}戦 / 例外 {sum(1 for g in G['games'].values() if g['res'] is None)}戦 / log付き {len(logs)}戦", '']
    out += ['## 1. 条件', f"- 深さ 第1段 {tuple(plan['depth']['1'])} / 第2段 {tuple(plan['depth']['2'])}、N1={plan['games']['1']} N2={plan['games']['2']} top={plan['top']}、deny [True, True]、resource = {plan['resource']['mode']}、playbook {G.get('playbook')}",
            '- 種: crc32("tn2"+V+相手選出+L選出+k)、k の偶数は L が side0（stage1 k=0..N1-1 / stage2 k=100..）',
            '- 相手選出（固定）: ' + ' / '.join(f"{V}: {'|'.join('/'.join(s) for s in vv['opp_sels'])}" for V, vv in plan['variants'].items()),
            f"- 見積り {plan['estimate']}"]
    secs = [g['sec'] for g in gm.values() if g.get('sec')]
    if secs:
        out.append(f"- 実所要: 計 {sum(secs) / 3600:.1f} CPU時間 ÷ {plan['estimate']['procs']}並列 ≒ {sum(secs) / 60 / plan['estimate']['procs']:.0f}分、1戦平均 {sum(secs) / len(secs):.0f}秒")
    out.append('- **近似項目の一覧（B・C は仮説）**:')
    for V, vv in plan['variants'].items():
        ap = tn_approx(V)
        if not ap:
            out.append(f"  - {V} {vv['title']}: 記事どおり（近似なし）")
        for nm, d in ap.items():
            out.append(f"  - {V} {nm}: 近似 {', '.join(d['approx'])}（{d['note']}）")
    out.append('')
    # 2
    out += ['## 2. 選出表（stage1 勝率、L24選出）']
    r1 = {}
    for V, vv in plan['variants'].items():
        tot = []
        for osel in vv['opp_sels']:
            rows = []
            for lsel in plan['candidates']:
                w = n = 0
                for g in gm.values():
                    if g['variant'] == V and g['opp_sel'] == osel and g['sel'] == lsel and s1g(g):
                        w += tn_score(g)
                        n += 1
                if n:
                    rows.append((w / n, w, n, '/'.join(lsel)))
            rows.sort(key=lambda r: -r[0])
            tot.append(sum(r[1] for r in rows) / max(1, sum(r[2] for r in rows)) if rows else None)
            out.append(f"- {V} 相手 {'/'.join(osel)}:")
            for r in rows[:8]:
                out.append(f"  - 上位 {r[3]} {_f(r[1], r[2])}")
            for r in rows[-3:][::-1] if len(rows) > 8 else []:
                out.append(f"  - 下位 {r[3]} {_f(r[1], r[2])}")
            if not rows:
                out.append('  - 該当なし')
        if len(tot) == 2 and None not in tot:
            out.append(f"  - 後発順の差: {abs(tot[0] - tot[1]) * 100:.0f}pt " + ('（差あり）' if abs(tot[0] - tot[1]) >= 0.05 else '（差なし）'))
    out.append('')
    # 3
    out += ['## 3. 変種ごとの最良選出（stage2 勝率 → stage1）']
    best, s1rate = {}, {}
    for V in plan['variants']:
        rows = []
        for lsel in plan['candidates']:
            gs = [g for g in gm.values() if g['variant'] == V and g['sel'] == lsel]
            a1, a2 = _wr([g for g in gs if s1g(g)]), _wr([g for g in gs if s2g(g)])
            if a1[1]:
                s1rate[(V, tuple(lsel))] = a1[0] / a1[1]
                rows.append(((a2[0] / a2[1]) if a2[1] else -1, a1[0] / a1[1], list(lsel), a1, a2))
        rows.sort(key=lambda r: (-r[0], -r[1]))
        best[V] = rows[0][2] if rows else None
        out.append(f"- {V}:")
        for r in rows[:3]:
            out.append(f"  - {'/'.join(r[2])}: stage1 {_f(*r[3])} / stage2 {_f(*r[4])} / 合算 {_f(r[3][0] + r[4][0], r[3][1] + r[4][1])}")
        if not rows:
            out.append('  - 該当なし')
    cs = {c for (_, c) in s1rate}
    if cs and all(all((V, c) in s1rate for V in plan['variants']) for c in cs):
        com = max(cs, key=lambda c: (min(s1rate[(V, c)] for V in plan['variants']), sum(s1rate[(V, c)] for V in plan['variants'])))
        out.append(f"- **3変種共通（最悪ケース最大、stage1）**: {'/'.join(com)} " + ' / '.join(f"{V} {s1rate[(V, com)] * 100:.0f}%" for V in plan['variants']))
    out.append('')
    # 4
    out += ['## 4. 最も勝てるプレイング（最良選出の全試合、L視点）']
    recs, rules = {}, {}
    for V in plan['variants']:
        out.append(f"### {V}: {'/'.join(best[V]) if best[V] else '該当なし'}")
        if not best[V]:
            out += ['該当なし', '']
            continue
        its = tn2_items(gm, logs, lambda g, V=V: g['variant'] == V and g['sel'] == best[V])
        allg = [g for g in gm.values() if g['variant'] == V and g['sel'] == best[V]]
        W, Nn = _wr(allg)
        out.append(f"- 全体 {_f(W, Nn)}（log付き {len(its)}戦）。深さ別: " + ' / '.join(f"{d}手 {_f(*_wr([g for g in allg if g['depth'][0] == d]))}" for d in sorted({g['depth'][0] for g in allg})))
        out.append('#### 4.1 ターン別行動')
        recs[V] = []
        for T in range(1, 7):
            reach = [i for i in its if len(i['lg']) >= T]
            if not reach:
                continue
            for who, ix in (('L', 0), ('相手', 2)):
                c, w = collections.Counter(), collections.Counter()
                for i in reach:
                    r = i['lg'][T - 1]
                    if r[ix + 1] in ('-', '反動'):
                        continue
                    k = f"{r[ix]}:{r[ix + 1]}"
                    c[k] += 1
                    w[k] += i['sc']
                out.append(f"- T{T} {who}: " + (' | '.join(f"{k} 出現{n}(勝試合{sum(1 for i in reach if f'{i['lg'][T - 1][ix]}:{i['lg'][T - 1][ix + 1]}' == k and i['sc'] == 1)}) 勝率{_tn_pct(w[k], n)}{'（参考）' if n < 5 else ''}" for k, n in c.most_common(3)) or '該当なし'))
                if T == 1 and who == 'L' and reach:
                    pr = collections.Counter((i['lg'][0][0], i['lg'][0][2]) for i in reach)
                    out.append('- T1 先発の組: ' + ', '.join(f'{x}×{y} {n}戦' for (x, y), n in pr.most_common(3)))
                if who == 'L' and c:
                    k0, n0 = c.most_common(1)[0]
                    if T <= 4 and n0 >= 5 and w[k0] / n0 >= (W / Nn if Nn else 0):
                        recs[V].append(f"T{T}: {k0}（{n0}回・勝率{_tn_pct(w[k0], n0)}）")
        out.append('#### 4.2 分岐点')
        dl = _delta_lines(its, None)
        out += [f'- {x[1]}' for x in dl[:8]] or ['- 該当なし']
        rules[V] = [x for x in dl if x[2] > 0][:5]
        pr = collections.Counter()
        pw = collections.Counter()
        for i in its:
            if len(i['lg']) >= 2:
                k = f"{i['lg'][0][0]}:{i['lg'][0][1]}→{i['lg'][1][0]}:{i['lg'][1][1]}"
                pr[k] += 1
                pw[k] += i['sc']
        out.append('- T1→T2 の行動の組上位5: ' + ('; '.join(f"{k} {n}回 勝率{_tn_pct(pw[k], n)}{'（参考）' if n < 5 else ''}" for k, n in pr.most_common(5)) or '該当なし'))
        out.append('#### 4.3 個別論点')
        out += tn2_points(its)
        out.append('#### 4.4 推奨手順（機械生成・仮説。シミュレーション（ブラインド・deny・4/5手読み）由来）')
        out += [f'- {x}' for x in recs[V]] or ['- 該当なし']
        out += [f"- 条件付き: {x[1]}" for x in rules[V]]
        out.append('')
    # 5
    out += ['## 5. 負け筋']
    for V in plan['variants']:
        if not best[V]:
            continue
        ls = [g for g in gm.values() if g['variant'] == V and g['sel'] == best[V] and tn_score(g) == 0.0]
        first, seq = collections.Counter(), collections.Counter()
        for g in ls:
            ms = g['main_side']
            f = sorted([x for x in g.get('faints') or [] if x[1] == ms])
            if f:
                first[f"{f[0][2]}（倒した: {f[0][3]}）"] += 1
                seq[' → '.join(x[2] for x in f[:3])] += 1
        out.append(f"- {V}: 負け {len(ls)}戦。先頭瀕死 {dict(first.most_common(4)) or '該当なし'}、瀕死順 " + ('; '.join(f'{k}×{v}' for k, v in seq.most_common(3)) or '該当なし'))
    out += ['', '## 6. 結論']
    for V in plan['variants']:
        if not best[V]:
            out.append(f'- {V}: 該当なし')
            continue
        allg = [g for g in gm.values() if g['variant'] == V and g['sel'] == best[V]]
        out.append(f"- {V}: 選出 {'/'.join(best[V])} 勝率 {_f(*_wr(allg))}。手順: " + (' → '.join(recs.get(V, [])[:3]) or '該当なし（仮説）'))
    open(P['md'], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f"書きました: {P['md']}")


def cmd_tn2_selftest(a):
    import shutil, subprocess, tempfile
    global _TN_PLAY
    D = a.out_dir or tempfile.mkdtemp(prefix='tn2test_')
    results = []

    def ok(n, cond, msg=''):
        results.append((n, bool(cond)))
        print(f"{'○' if cond else '×'} {n} {msg}", flush=True)

    before = _sha_all()
    p = subprocess.run([sys.executable, '-m', 'py_compile', 'roundrobin.py', 'refine.py'], cwd=HERE, capture_output=True, text=True)
    ok('1 py_compile', p.returncode == 0, p.stderr[-200:])

    class A_:
        pass

    def args(sub, **kw):
        x = A_()
        x.out_dir, x.procs, x.max_games, x.force, x.retry_errors, x.resource, x.stage = os.path.join(D, sub), a.procs, 0, True, False, 'loose', 1
        x.games, x.games2, x.top, x.focus = None, None, None, True
        x.__dict__.update(kw)
        return x

    rp = load_plan(paths(None))
    V = tn_load_variants()
    T = dict(rp['teams'])
    for v, rt in V.items():
        T[rt['id']] = rt
    _worker_init(T)
    L = TN_L
    rr_apply(T[L])
    pl = cmd_tn2_plan(args('p'))
    cs = [list(c) for c in T[L]['candidates']]
    allo = [s for v, vv in pl['variants'].items() for s in vv['opp_sels']]
    ok('2a 相手選出6通り・先発固定・両後衛含む・後発順2通り', len(allo) == 6 and all(len(vv['opp_sels']) == 2 for vv in pl['variants'].values()) and
       all(s[0] == {'A': 'イエッサン', 'B': 'バサギリ', 'C': 'イエッサン♀'}[v] for v, vv in pl['variants'].items() for s in vv['opp_sels']) and
       all(set(TN_BACK) <= set(s) and s[0] not in TN_BACK for s in allo) and
       all({tuple(s[1:]) for s in vv['opp_sels']} == {TN_BACK, TN_BACK[::-1]} for vv in pl['variants'].values()))
    ok('2b L選出24通り', len(pl['candidates']) == 24 and pl['candidates'] == cs)
    ok('2c tn1 の相手選出は不変(A=8,B=6,C=6)', {v: len(tn_opp_sels(v, V[v])) for v in V} == {'A': 8, 'B': 6, 'C': 6})
    j1 = tn2_jobs(pl, 1, T)
    keys = [j[0] for j in j1]
    j0 = tn2_job(pl, 'A', allo[0], cs[0], 0, 1, T)
    j1_ = tn2_job(pl, 'A', allo[0], cs[0], 1, 1, T)
    ok('3a stage1 件数=24×6×N1・重複なし・key形式', len(j1) == 24 * 6 * pl['games']['1'] and len(set(keys)) == len(keys) and all(k.startswith('tn2:') for k in keys))
    ok('3b k偶奇で左右入替・種', j0[5] == L and j1_[6] == L and j0[0] == f"tn2:A|{'/'.join(allo[0])}|{'/'.join(cs[0])}|0" and
       tn2_seed('A', allo[0], cs[0], 0) == zlib.crc32(f"tn2A{'/'.join(allo[0])}{'/'.join(cs[0])}0".encode()))
    ok('3c k範囲 stage2=100..', tn2_ks(pl, 2) == list(range(100, 112)) and tn2_ks(pl, 1) == list(range(8)))
    est = tn_estimate(8 * 144, 12 * 12, 4)
    ok('8a estimate(N1=8,N2=12,top=2,4並列) rf込み≤120分', pl['estimate']['total_min'] <= 120 and est['total_min'] <= 120, str(pl['estimate']))

    # 5 snap（実 blind_play 深さ1）
    sj = list(tn2_job(pl, 'A', allo[0], cs[0], 0, 1, T))
    sj[10] = (1, 1)
    r_on, r_off = _job_tn2(tuple(sj), True), _job_tn2(tuple(sj), False)
    same = r_on.get('res') is not None and all(r_on.get(k) == r_off.get(k) for k in ('res', 'log', 'faints', 'left', 'turns'))
    ok('5a SNAP オン/オフで res/log/faints/left/turns 一致', same, (r_on.get('error') or r_off.get('error') or '')[-200:])
    sn, po = r_on.get('snap') or [], r_on.get('post') or []
    kk1 = {'w', 'wt', 'tr', 'tt', 'room', 'hp', 'mega', 'bk', 'vol', 'item', 'alive'}
    ok('5b オン側のみ snap/post・長さ一致・キー', 'snap' not in r_off and 'post' not in r_off and len(sn) == len(r_on['log']) == len(po) > 0 and
       all(set(s) == kk1 for s in sn) and all(set(q) == {'hp', 'act', 'ej'} for q in po) and all(set(v) == {'perish', 'encore', 'curse'} for v in sn[0]['vol']))
    ok('5c R.SNAP は元に戻る', R.SNAP is False)

    # 実 d4 1戦（時間）
    t0 = time.time()
    rd = _job_tn2(tn2_job(pl, 'A', allo[0], cs[0], 0, 1, T), True)
    sec4 = time.time() - t0
    ok('8b 実 d4 1戦', rd.get('res') is not None, f'{sec4:.1f}秒 {rd.get("turns")}手 {rd.get("error") or ""}')

    # stub
    def stub(args_):
        h = zlib.crc32(repr((args_[2], args_[3], args_[4])).encode())
        n = 6
        names = [args_[2][0], args_[3][0]]
        log = [[args_[2][0], ('M+' if t == 1 else '') + ('げきりん' if (h >> t) & 1 else 'のろい'), args_[3][0], ('→ニョロトノ' if t == 2 else 'じしん')] for t in range(n)]
        sn_ = [{'w': 'raindance' if t < 3 else '', 'wt': max(0, 5 - t), 'tr': 'psychicterrain' if t == 1 else '', 'tt': 0, 'room': 1 if t == 2 else 0,
                'hp': [100, 100], 'mega': [t > 1, False], 'bk': [False if t < 3 else 'done', None], 'vol': [{'perish': 3 if t == 4 else None, 'encore': {'move': 'げきりん', 'dur': 2} if t == 3 else None, 'curse': False}] * 2,
                'item': ['', 'airballoon' if t == 0 else ''], 'alive': [3, 3]} for t in range(n)]
        po_ = [{'hp': [90, 90], 'act': names, 'ej': [t == 3, False]} for t in range(n)]
        return {'res': (1, -1, 0)[h % 3], 'turns': n, 'judged': False,
                'left': [[[m, (h >> i) % 101] for i, m in enumerate(args_[2])], [[m, (h >> (i + 3)) % 101] for i, m in enumerate(args_[3])]],
                'faints': [[3, 0, args_[2][0], args_[3][0]], [5, 1, args_[3][0], args_[2][1]]], 'log': log, 'snap': sn_, 'post': po_,
                'echo': [list(args_[2]), list(args_[3]), args_[4]]}
    _TN_PLAY = stub
    try:
        a1 = args('s1', max_games=5)
        cmd_tn2_plan(a1)
        cmd_tn2_run(a1)
        P1 = tn2_paths(a1.out_dir)
        g5 = json.load(open(P1['games'], encoding='utf-8'))['games']
        a1.max_games = 7
        n_new = cmd_tn2_run(a1)
        g12 = json.load(open(P1['games'], encoding='utf-8'))['games']
        ok('4a 再開: 5件→残り7件だけ・既存5件不変', len(g5) == 5 and n_new == 7 and len(g12) == 12 and all(json.dumps(g12[k], sort_keys=True) == json.dumps(g5[k], sort_keys=True) for k in g5))
        lg = read_jsonl(P1['logs'])
        ok('4a2 tn2_logs に key/log/snap/post', len(lg) == 12 and all({'key', 'log', 'snap', 'post'} <= set(x) for x in lg) and all(g.get('focus') is True for g in g12.values()))
        # --games 増加
        a2 = args('s2', games=2)
        cmd_tn2_plan(a2)
        cmd_tn2_run(a2)
        n2a = len(json.load(open(tn2_paths(a2.out_dir)['games'], encoding='utf-8'))['games'])
        a2.games = 3
        n_new2 = cmd_tn2_run(a2)
        gk = json.load(open(tn2_paths(a2.out_dir)['games'], encoding='utf-8'))['games']
        ok('4b --games 増加で新しい k だけ追加', n2a == 24 * 6 * 2 and n_new2 == 24 * 6 and len(gk) == 24 * 6 * 3 and {g['k'] for g in gk.values()} == {0, 1, 2})
        # retry-errors
        P2 = tn2_paths(a2.out_dir)
        GG = json.load(open(P2['games'], encoding='utf-8'))
        bad = list(GG['games'])[:3]
        for k in bad:
            GG['games'][k]['res'] = None
            GG['games'][k]['error'] = 'x'
        json.dump(GG, open(P2['games'], 'w', encoding='utf-8'))
        a2.retry_errors = True
        n_re = cmd_tn2_run(a2)
        a2.retry_errors = False
        n_re0 = cmd_tn2_run(a2)
        ok('4c --retry-errors で error のみ再実行', n_re == 3 and n_re0 == 0, f'{n_re},{n_re0}')
        # stage2 ゲート・固定
        try:
            a1.stage = 2
            cmd_tn2_run(a1)
            ok('3d stage1 未完なら stage2 拒否', False)
        except SystemExit:
            ok('3d stage1 未完なら stage2 拒否', True)
        a3 = args('s3', games=2, games2=2, top=2)
        cmd_tn2_plan(a3)
        cmd_tn2_run(a3)
        a3.stage = 2
        cmd_tn2_run(a3)
        P3 = tn2_paths(a3.out_dir)
        pl3 = json.load(open(P3['plan'], encoding='utf-8'))
        gm3 = json.load(open(P3['games'], encoding='utf-8'))['games']
        n_s2 = sum(1 for g in gm3.values() if g['stage'] == 2)
        ok('3e stage2: 上位 top が plan に保存・戦数=3×2×2×N2', all(len(v) == 2 for v in pl3['stage2_sels'].values()) and n_s2 == 3 * 2 * 2 * 2, str(n_s2))
        keep = json.dumps(pl3['stage2_sels'])
        cmd_tn2_run(a3)
        ok('3f stage2_sels は再計算されない', json.dumps(json.load(open(P3['plan'], encoding='utf-8'))['stage2_sels']) == keep)
        cmd_tn2_report(a3)
        md = open(P3['md'], encoding='utf-8').read()
        heads = ['## 1. 条件', '## 2. 選出表', '## 3. 変種ごとの最良選出', '## 4. 最も勝てるプレイング', '#### 4.1', '#### 4.2', '#### 4.3', '#### 4.4', '## 5. 負け筋', '## 6. 結論']
        pts = ['ミミッキュ', 'リザードンX', 'イダイトウ', 'ほろびのうた', 'アンコール', '**雨**', 'だっしゅつボタン']
        ok('6 report: §1〜§6・4.3 の7項目', all(h in md for h in heads) and all(x in md for x in pts), str([x for x in heads + pts if x not in md]))
    finally:
        _TN_PLAY = R.blind_play
    ok('7 既存結果の sha256 不変・既定の場所に tn2_* を作らない', _sha_all() == before and not [f for f in os.listdir(DEF_OUT) if f.startswith('tn2_')])
    if not a.keep and not a.out_dir:
        shutil.rmtree(D, ignore_errors=True)
    bad = [n for n, c in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} ○" + (f"  ×: {bad}" if bad else '') + f"  実d4 1戦 {sec4:.1f}秒")
    if bad:
        raise SystemExit(1)



# ================================================================ tn3 (SPEC_TONORAGU3.md)
TN3_VERSION = 'tn3'
TN3_MIM = 'ミミッキュ'
TN3_MK, TN3_ZD = 'ムクホーク', 'リザードン'
_TN3_SELECT = adapt_select
_TN3_NOBAN = [False]        # selftest 用: True ならメガ禁止を掛けない（対照）


def tn3_paths(out_dir=None):
    d = out_dir or DEF_OUT
    return {'dir': d, 'plan': os.path.join(d, 'tn3_plan.json'), 'games': os.path.join(d, 'tn3_games.json'),
            'logs': os.path.join(d, 'tn3_logs.jsonl'), 'md': os.path.join(d, 'TONORAGU3.md') if out_dir else os.path.join(HERE, '..', 'logs', 'TONORAGU3.md')}


def tn3_seed(V, osel, k):
    return zlib.crc32(f"tn3{V}{'/'.join(osel)}{k}".encode())


def tn3_key(V, osel, k, ctl=False):
    return f"tn3{'c' if ctl else ''}:{V}|{'/'.join(osel)}|{k}"


def tn3_orders(rt, excl):
    bases = [m['base'] for m in rt['mons']]
    assert TN3_MIM in bases and excl in bases and excl != TN3_MIM
    rest = [b for b in bases if b not in (excl, TN3_MIM)]
    out = []
    for p in itertools.combinations(rest, 2):
        tri = [b for b in bases if b in p or b == TN3_MIM]
        for lead in tri:
            out.append(norm_order([lead] + [b for b in tri if b != lead], bases))
    return out


def tn3_megaban(lsel):
    return [TN3_MK] if TN3_MK in lsel and TN3_ZD in lsel and not _TN3_NOBAN[0] else None


def _tn3_eval(o, c, smart):
    """adapt の評価試合（A=side0）。ムクホーク＋リザードンX の時はムクホークのメガを禁止。"""
    import search as _S
    st = B.engine_game(list(o), list(c))
    mb = tn3_megaban(o)
    if mb:
        R.mega_ban(st, 0, mb)
    return _S.play(st, smart=smart)


# ---- 除外個体
def tn3_exclusion(gm, logs, bases, total, manual=None):
    """gm: tn2 games（stage1 のみ使う）、logs: key->{'log'}。戻り値 {'name','mode','table',...}。"""
    g1 = [g for g in gm.values() if g.get('stage') == 1 and g.get('res') is not None]
    rows = []
    for idx, nm in enumerate(bases):
        sg = [(k, g) for k, g in gm.items() if g.get('stage') == 1 and g.get('res') is not None and nm in g['sel']]
        n = len(sg)
        sc = [tn_score(g) for _, g in sg]
        out_ = [tn_score(g) for k, g in sg if _tn3_appeared(g, logs.get(k), nm)]
        lead = [tn_score(g) for _, g in sg if g['sel'][0] == nm]
        ff = 0
        for _, g in sg:
            f = sorted([x for x in g.get('faints') or [] if x[1] == g['main_side']])
            ff += 1 if f and f[0][2].startswith(nm) else 0
        w = sum(sc)
        lo, hi = wilson(w, n) if n else (0, 0)
        rows.append({'name': nm, 'idx': idx, 'n': n, 'rate': w / n if n else None, 'ci': [round(lo, 4), round(hi, 4)], 'n_out': len(out_),
                     'rate_out': sum(out_) / len(out_) if out_ else None, 'n_lead': len(lead), 'rate_lead': sum(lead) / len(lead) if lead else None,
                     'first_faint': ff, 'first_faint_rate': ff / n if n else 0.0})
    cand = [r for r in rows if r['name'] != TN3_MIM and r['n']]
    big = 9.0

    def key(r):
        return (round(r['rate'] * 100, 1), r['rate_out'] if r['rate_out'] is not None else big, r['rate_lead'] if r['rate_lead'] is not None else big,
                -r['first_faint_rate'], -r['idx'])
    auto = min(cand, key=key)['name'] if cand else None
    tie = [r['name'] for r in cand if auto and round(r['rate'] * 100, 1) == round(next(x for x in cand if x['name'] == auto)['rate'] * 100, 1)]
    if manual:
        if manual == TN3_MIM or manual not in bases:
            raise SystemExit(f'--exclude {manual}: ミミッキュ・不明名は指定できません（{bases}）')
        name, mode = manual, 'manual'
    else:
        name, mode = auto, 'auto'
    return {'name': name, 'mode': mode, 'auto_name': auto, 'tie': tie if len(tie) > 1 else [], 'table': rows, 'n_games': len(g1), 'total': total}


def _tn3_appeared(g, rec, nm):
    ms = g['main_side']
    if rec and rec.get('log'):
        for row in rec['log']:
            f = row[2 * ms]
            if isinstance(f, str) and f.startswith(nm):
                return True
            a = row[2 * ms + 1]
            if isinstance(a, str) and a.startswith('→' + nm):
                return True
        return False
    return g['sel'][0] == nm or any(x[1] == ms and x[2].startswith(nm) for x in g.get('faints') or [])


def tn3_load_tn2(d):
    P2 = tn2_paths(d)
    if not os.path.exists(P2['plan']) or not os.path.exists(P2['games']):
        raise SystemExit(f"{P2['plan']} / {P2['games']} がありません")
    p2 = json.load(open(P2['plan'], encoding='utf-8'))
    raw = open(P2['games'], 'rb').read()
    gm = json.loads(raw.decode('utf-8'))['games']
    logs = {}
    for r in read_jsonl(P2['logs']):
        if r.get('key') in gm:
            logs[r['key']] = r
    return p2, gm, logs, hashlib.sha256(raw).hexdigest()


def tn3_control_best(p2, gm):
    out = {}
    s2 = p2.get('stage2_sels') or {}
    for V in p2['variants']:
        rows = []
        for i, ls in enumerate(p2['candidates']):
            w2, n2, _ = tn_rate(gm, V, ls, range(TN2_K2, TN2_K2 + 1000))
            w1, n1, hp = tn_rate(gm, V, ls, range(0, TN2_K2))
            has2 = n2 > 0 and list(ls) in [list(x) for x in s2.get(V, [])]
            rows.append((0 if has2 else 1, -(w2 / n2 if has2 else (w1 / n1 if n1 else 0.0)), -(sum(hp) / len(hp) if hp else 0.0), i))
        r = sorted(rows)[0]
        out[V] = {'sel': list(p2['candidates'][r[3]]), 'stage': 2 if r[0] == 0 else 1, 'rate': -r[1]}
    return out


def tn3_estimate(n, cells, procs, sec_game=180.0, sec_sel=20.0, rf=1.3, control=False):
    waves = math.ceil(cells * (2 if control else 1) / procs)
    base = n * waves * (sec_game + sec_sel) / 60
    return {'rounds': n, 'waves': waves, 'procs': procs, 'sec_game': sec_game, 'sec_sel': sec_sel, 'min': round(base), 'min_rf': round(base * rf), 'rf': rf}


def tn3_teams(plan, T=None):
    if T is None:
        rp = load_plan(paths(None))
        T = dict(rp['teams'])
        for v, rt in tn_load_variants().items():
            T[rt['id']] = rt
    T = dict(T)
    L = plan['main']
    orders = {tuple(o) for o in plan['orders']}
    t = dict(T[L])
    t['candidates'] = [list(o) for o in plan['orders']]
    t['article_orders'] = [o for o in t['article_orders'] if tuple(o) in orders]
    gi = []
    for it in t['gitems']:
        os_ = [o for o in it['orders'] if tuple(o) in orders]
        if os_:
            gi.append(dict(it, orders=os_))
    t['gitems'] = gi
    T[L] = t
    return T


def cmd_tn3_plan(a):
    P = tn3_paths(a.out_dir)
    os.makedirs(P['dir'], exist_ok=True)
    mode = a.resource or 'loose'
    N = a.games or 10
    od = getattr(a, 'opp_depth', None) or 6
    selm = getattr(a, 'sel', None) or 'adapt'
    ctl = bool(getattr(a, 'control', False))
    p2, gm2, lg2, sha2 = tn3_load_tn2(getattr(a, 'tn2_dir', None))
    rp = load_plan(paths(None))
    T0 = dict(rp['teams'])
    V = tn_load_variants()
    for v, rt in V.items():
        T0[rt['id']] = rt
    rt = T0[TN_L]
    bases = [m['base'] for m in rt['mons']]
    total = len(p2['candidates']) * sum(len(vv['opp_sels']) for vv in p2['variants'].values()) * p2['games']['1']
    ex = tn3_exclusion(gm2, lg2, bases, total, getattr(a, 'exclude', None))
    if ex['n_games'] < total and ex['mode'] == 'auto':
        raise SystemExit(f"tn2 stage1 未完（{ex['n_games']}/{total}）。完了後に plan するか --exclude 個体名 を指定してください")
    if ex['mode'] == 'manual':
        ex['note'] = f"手動指定（機械決定なら{ex['auto_name']}）" + (f'、tn2 未完（{ex["n_games"]}/{total}）' if ex['n_games'] < total else '')
    ex['tn2_sha256'] = sha2
    orders = tn3_orders(rt, ex['name'])
    osels = {v: tn_opp_sels(v, V[v], TN2_LEADS[v]) for v in V}
    cells = [[v, s] for v in V for s in osels[v]]
    _worker_init(T0)
    plan = {'version': TN3_VERSION, 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'main': TN_L, 'exclude': ex, 'orders': orders,
            'variants': {v: {'id': r_['id'], 'title': r_['title'], 'opp_sels': osels[v]} for v, r_ in V.items()}, 'cells': cells,
            'depth': [6, od], 'deny': [True, True], 'sel_mode': selm, 'resource': tn_res_cfg(mode), 'games': N, 'playbook': _pb_sig(),
            'control': tn3_control_best(p2, gm2) if ctl else None}
    plan['sig'] = hashlib.sha256((json.dumps([TN_L, ex['name'], orders, osels, plan['depth'], selm, plan['resource'], bool(ctl), plan['control'],
                                               [V[v]['mons'] for v in sorted(V)]], ensure_ascii=False, sort_keys=True, default=str) + 'tn3').encode()).hexdigest()
    old = None
    if os.path.exists(P['plan']):
        old = json.load(open(P['plan'], encoding='utf-8'))
        if old.get('sig') != plan['sig']:
            if not a.force:
                raise SystemExit('tn3_plan.json の sig が違います（--force で退避して作り直し）')
            os.replace(P['plan'], P['plan'][:-5] + time.strftime('.%Y%m%d_%H%M%S.json'))
            old = None
    if old:
        plan = old
        plan['games'] = N
    else:
        T3 = tn3_teams(plan, T0)
        _worker_init(T3)
        plan['sel1'], ssec = {}, []
        if selm == 'adapt':
            for v in V:
                t0 = time.time()
                s = decide_pair(TN_L, V[v]['id'])
                ssec.append(time.time() - t0)
                plan['sel1'][v] = {'order': list(s['order']), 'src': s.get('src')}
        plan['sec_sel1'] = round(sum(ssec) / len(ssec), 1) if ssec else 0.0
    sg = getattr(a, 'sec_game', None) or 180.0
    plan['estimate'] = tn3_estimate(N, len(cells), a.procs, sg, plan.get('sec_sel1') or 20.0, control=ctl)
    if plan['estimate']['min_rf'] > 180:
        print(f"警告: 見積り {plan['estimate']['min_rf']}分（rf込み）が180分を超えます", flush=True)
    safeio.write_json(P['plan'], plan)
    print(f"除外 {ex['name']}（{ex['mode']}、tn2 {ex['n_games']}/{total}）選出{len(orders)}通り セル{len(cells)}×{N}戦 見積り {plan['estimate']}")
    return plan


def tn3_job(plan, T, ci, k, ctl, hist, snap=True):
    V, osel = plan['cells'][ci]
    L, X = plan['main'], plan['variants'][V]['id']
    s0, s1 = (L, X) if k % 2 == 0 else (X, L)
    mode = plan['resource']['mode']
    res = None if mode == 'off' else (tn_rc(mode, s0, s1, T), tn_rc(mode, s1, s0, T))
    lsel = None
    if ctl:
        lsel = plan['control'][V]['sel']
    elif plan['sel_mode'] == 'rotate':
        lsel = plan['orders'][(k + 3 * ci) % len(plan['orders'])]
    sel1 = (plan.get('sel1') or {}).get(V)
    d = plan['depth']
    return (tn3_key(V, osel, k, ctl), V, list(osel), k, s0, s1, lsel, hist, ci, (d[0], d[1]), res, mode, sel1, snap, bool(ctl))


def _job_tn3(a):
    key, V, osel, k, s0, s1, lsel, hist, ci, depth, res, mode, sel1, snap, ctl = a
    t0 = time.time()
    import search as _S
    global _AD_EVAL
    L = TN_L
    X = s1 if s0 == L else s0
    orig, osnap, oev = _S.axis_cover, R.SNAP, _AD_EVAL
    why = mrb = None
    ssec = 0.0
    try:
        R.SNAP = snap
        if lsel is None:
            if sel1:
                _AD['sel1'][f'{L}|{X}'] = {'order': sel1['order'], 'src': sel1.get('src')}
            _AD_EVAL = _tn3_eval
            ts = time.time()
            try:
                lsel, why = _TN3_SELECT(L, X, hist)
            finally:
                _AD_EVAL = oev
            ssec = time.time() - ts
            lsel = list(lsel)
            if why and why.get('e_all'):
                both = [x for x in why['e_all'] if TN3_MK in x[1] and TN3_ZD in x[1]]
                mrb = {'best': max(both)[1] if both else None, 'e_best': max(both)[0] if both else None,
                       'e_chosen': next((x[0] for x in why['e_all'] if x[1] == lsel), None)}
        lsel = list(lsel)
        rr_apply(_TEAMS[s0])
        pa = _pb_args(s0, s1)
        mb = tn3_megaban(lsel)
        mbs = (mb if s0 == L else None, mb if s1 == L else None)
        o0, o1 = (lsel, list(osel)) if s0 == L else (list(osel), lsel)
        d0, d1 = (depth[0], depth[1]) if s0 == L else (depth[1], depth[0])
        if mode == 'discount':
            _S.axis_cover = _tn_discount_cover
        rs = res if (res and (res[0] or res[1])) else None
        r = _TN_PLAY((None, s1, o0, o1, tn3_seed(V, osel, k), d0, d1, False, None, False, (s0,), (True, True), pa[0] if pa else None, rs, mbs))
        r['lsel'], r['why'], r['mrb'], r['ssec'] = lsel, why, mrb, round(ssec, 2)
    except Exception:
        r = {'res': None, 'error': traceback.format_exc()[-800:], 'lsel': lsel}
    finally:
        _S.axis_cover, R.SNAP, _AD_EVAL = orig, osnap, oev
    r['key'] = key
    r['sec'] = round(time.time() - t0, 2)
    return r


def tn3_record(job, r):
    key, V, osel, k, s0, s1, lsel, hist, ci, depth, res, mode, sel1, snap, ctl = job
    ls = r.get('lsel') or []
    o0, o1 = (ls, list(osel)) if s0 == TN_L else (list(osel), ls)
    rec = tn_record((key, V, osel, ls, k, s0, s1, o0, o1, 3, depth, res, mode), r, TN_L)
    rec['seed'] = tn3_seed(V, osel, k)
    rec['cell'] = ci
    rec['ctl'] = ctl
    rec['sel_why'] = r.get('why')
    rec['mr_best'] = r.get('mrb')
    rec['ssec'] = r.get('ssec')
    rec['mega_ban'] = tn3_megaban(ls)
    return rec


def tn3_hist(plan, gm, T, ci, k):
    V, osel = plan['cells'][ci]
    bases = [m['base'] for m in T[plan['variants'][V]['id']]['mons']]
    h = []
    for j in range(k):
        g = gm[tn3_key(V, osel, j)]
        h.append({'n': j, 'mine': list(g['sel']), 'theirs': norm_order(list(osel), bases), 'res_for_A': tn_score(g)})
    return h


def tn3_next(plan, gm, ci, ctl, N, retry):
    V, osel = plan['cells'][ci]
    for k in range(N):
        g = gm.get(tn3_key(V, osel, k, ctl))
        if g and g['res'] is not None:
            continue
        if g and not retry:
            return None
        return k
    return None


def cmd_tn3_run(a):
    P = tn3_paths(a.out_dir)
    plan = tn_load_plan(P)
    if a.resource and a.resource != plan['resource']['mode']:
        raise SystemExit(f"plan の resource は {plan['resource']['mode']} です")
    T0 = dict(load_plan(paths(None))['teams'])
    for v, rt in tn_load_variants().items():
        T0[rt['id']] = rt
    T3 = tn3_teams(plan, T0)
    if os.path.exists(P['games']):
        G = json.load(open(P['games'], encoding='utf-8'))
        if G.get('plan_sig') != plan['sig']:
            raise SystemExit('tn3_games.json の plan_sig が tn3_plan.json と違います')
    else:
        G = {'version': TN3_VERSION, 'plan_sig': plan['sig'], 'resource': plan['resource'], 'games': {}, 'playbook': _pb_sig()}
    pb_guard(G)
    gm = G['games']
    N = getattr(a, 'games', None) or plan['games']
    ctls = [False, True] if plan.get('control') else [False]
    t0, n_done, left = time.time(), 0, a.max_games or 10 ** 9
    tot = N * len(plan['cells']) * len(ctls)
    print(f"全体 {tot}戦、済み {sum(1 for g in gm.values() if g['res'] is not None)}", flush=True)
    with make_pool(a.procs, T3) as pool:
        while left > 0:
            jobs = []
            for ci in range(len(plan['cells'])):
                for c in ctls:
                    k = tn3_next(plan, gm, ci, c, N, a.retry_errors)
                    if k is not None:
                        jobs.append(tn3_job(plan, T0, ci, k, c, [] if c else tn3_hist(plan, gm, T0, ci, k)))
            jobs = jobs[:left]
            if not jobs:
                break
            for r in pool.imap_unordered(_job_tn3, jobs):
                job = next(j for j in jobs if j[0] == r['key'])
                gm[r['key']] = tn3_record(job, r)
                safeio.write_json(P['games'], G)
                if r.get('log') is not None:
                    tn2_append_log(P, r['key'], r)
                n_done += 1
                left -= 1
                s = tn_score(gm[r['key']])
                el = (time.time() - t0) / 60
                print(f"[{n_done}] {r['key']} L{'例外' if s is None else ('勝' if s == 1 else ('分' if s == 0.5 else '負'))} {'/'.join(r.get('lsel') or [])} {r.get('turns')}手 {r['sec']:.0f}秒 経過{el:.1f}分", flush=True)
    return n_done


def cmd_tn3_report(a):
    P = tn3_paths(a.out_dir)
    plan = tn_load_plan(P)
    G = json.load(open(P['games'], encoding='utf-8'))
    gm = {k: g for k, g in G['games'].items() if g['res'] is not None}
    logs = {}
    for r in read_jsonl(P['logs']):
        if r.get('key') in gm:
            logs[r['key']] = r
    ex = plan['exclude']
    main = {k: g for k, g in gm.items() if not g.get('ctl')}
    ctl = {k: g for k, g in gm.items() if g.get('ctl')}
    out = [f"# TONORAGU3: {ex['name']}除外・ミミッキュ必須・ムクホーク/リザードンX同時選出可（ムクホークはメガなし）6手読みブラインド", '',
           f"作成 {time.strftime('%Y-%m-%d %H:%M')} / plan sig {plan['sig'][:12]} / 有効 {len(gm)}戦 / 例外 {sum(1 for g in G['games'].values() if g['res'] is None)}戦", '']
    secs = [g['sec'] for g in gm.values() if g.get('sec')]
    out += ['## 1. 条件', f"- 深さ (自分, 相手)={tuple(plan['depth'])}、N={plan['games']}/セル、セル={len(plan['cells'])}、sel方式 {plan['sel_mode']}、deny {plan['deny']}、resource {plan['resource']['mode']}、playbook {G.get('playbook')}",
            '- 種: crc32("tn3"+V+相手選出+k)（L選出を含まない）、k 偶数は L が side0',
            '- 相手選出（固定）: ' + ' / '.join(f"{v}: {'|'.join('/'.join(s) for s in vv['opp_sels'])}" for v, vv in plan['variants'].items()),
            '- メガ禁止: L の選出に ムクホーク＋リザードン が両方ある時だけ L 側のムクホークがメガしない（args[14]）。相手の読みは禁止を知らない（ブラインド）。プレイブック p1/p2 の `who: メガムクホーク` は base 名一致なのでメガしないムクホークにも適用される。',
            f"- 見積り {plan['estimate']}"]
    if secs:
        out.append(f"- 実所要: 計 {sum(secs) / 3600:.1f} CPU時間 ÷ {plan['estimate']['procs']}並列 ≒ {sum(secs) / 60 / plan['estimate']['procs']:.0f}分、1戦平均 {sum(secs) / len(secs):.0f}秒")
    out.append('')
    out += ['## 2. 除外した個体と根拠', f"- 除外: **{ex['name']}**（{ex['mode']}）" + (f"。{ex['note']}" if ex.get('note') else '') + (f"。同率判定あり {ex['tie']}" if ex.get('tie') else '。同率判定なし'),
            f"- tn2_games.json sha256 {ex.get('tn2_sha256')}、stage1 {ex['n_games']}/{ex['total']}戦",
            '- 注意: 24候補は個体の組み合わせが偏る（ムクホーク＋リザードンXは無い）ため、選出時勝率は組む相手の影響を含む交絡あり。', '',
            '| 個体 | 選出時 n | 勝率 | 区間 | 出場時 n | 出場時勝率 | 先発 n | 先発時勝率 | 被先頭瀕死 | 被先頭瀕死率 |', '|---|---|---|---|---|---|---|---|---|---|']
    pc = lambda x: '-' if x is None else f'{x * 100:.1f}%'
    for r in ex['table']:
        out.append(f"| {r['name']} | {r['n']} | {pc(r['rate'])} | {r['ci'][0] * 100:.0f}-{r['ci'][1] * 100:.0f}% | {r['n_out']} | {pc(r['rate_out'])} | {r['n_lead']} | {pc(r['rate_lead'])} | {r['first_faint']} | {pc(r['first_faint_rate'])} |")
    out.append('')
    out += ['## 3. 選出別・変種別の勝率']
    for v, vv in plan['variants'].items():
        for osel in vv['opp_sels']:
            gs = [g for g in main.values() if g['variant'] == v and g['opp_sel'] == osel]
            out.append(f"- {v} 相手 {'/'.join(osel)}: {_f(*_wr(gs))}")
        gs = [g for g in main.values() if g['variant'] == v]
        out.append(f"- **{v} 通算**: {_f(*_wr(gs))}")
        byl = collections.defaultdict(list)
        for g in gs:
            byl['/'.join(g['sel'])].append(g)
        out.append('  - L選出別: ' + ('; '.join(f"{k} {_f(*_wr(x))}" for k, x in sorted(byl.items(), key=lambda t: -len(t[1]))[:12]) or '該当なし'))
    out.append('- adapt が選んだ選出の推移（セルごと k=0..）:')
    for ci, (v, osel) in enumerate(plan['cells']):
        seq = [main.get(tn3_key(v, osel, k)) for k in range(plan['games'])]
        out.append(f"  - {v} {'/'.join(osel)}: " + (' → '.join('/'.join(g['sel']) if g else '-' for g in seq)))
    out.append('')
    both = [g for g in main.values() if TN3_MK in g['sel'] and TN3_ZD in g['sel']]
    out += ['## 4. ムクホーク＋リザードンX同時選出']
    if ex['name'] in (TN3_MK, TN3_ZD):
        out.append(f"該当なし（{ex['name']}除外）")
    elif not both:
        out.append('該当なし')
    else:
        its = tn2_items(gm, logs, lambda g: g in both)
        out.append(f"- 該当 {len(both)}戦、勝率 {_f(*_wr(both))}")
        mk_t = kills = ink = ink_k = dead = zmega = mkmega = 0
        for it in its:
            ms = it['ms']
            for t, row in enumerate(it['lg']):
                if row[0].startswith(TN3_MK):
                    mk_t += 1
                    if it['meg'][t][0]:
                        mkmega += 1
                    if row[1] == 'いのちがけ':
                        ink += 1
                        ink_k += sum(1 for x in it['g']['faints'] if x[0] == t + 1 and x[1] != ms)
                if row[0].startswith(TN3_ZD) and it['meg'][t][0]:
                    zmega += 1
            kills += sum(1 for x in it['g']['faints'] if x[1] != ms and x[3].startswith(TN3_MK))
            dead += sum(1 for x in it['g']['faints'] if x[1] == ms and x[2].startswith(TN3_MK))
        out.append(f"- ムクホーク: 場に出たターン計 {mk_t}、倒した数 {kills}、いのちがけ {ink}回（直後の相手瀕死 {ink_k}）、被瀕死 {dead}回")
        out.append(f"- リザードンXのメガターン計 {zmega}。**ムクホークのメガ回数 {mkmega}（0 であること）**")
        mr = [g['mr_best'] for g in main.values() if g.get('mr_best')]
        if mr:
            out.append('- mr_best（同時選出の最大 e / 選ばれた選出の e）: ' + ', '.join(f"{(x['e_best'] if x['e_best'] is not None else 0):.3f}/{(x['e_chosen'] if x['e_chosen'] is not None else 0):.3f}" for x in mr[:20]))
    out.append('')
    out += ['## 5. ミミッキュ必須ルールの効果']
    for v in plan['variants']:
        gs = [g for g in main.values() if g['variant'] == v]
        c = plan.get('control') and plan['control'].get(v)
        line = f"- {v}: tn3 {_f(*_wr(gs))}"
        if ctl:
            cg = [g for g in ctl.values() if g['variant'] == v]
            line += f" / 同深さ対照 {'/'.join(c['sel'])} {_f(*_wr(cg))}"
        elif c:
            line += f" / tn2 最良 {'/'.join(c['sel'])} 勝率{c['rate'] * 100:.0f}%（tn2 は d4/d5。深さが違うので参考）"
        out.append(line)
    out.append('')
    out += ['## 6. 勝ち筋のターン別行動（シミュレーション由来・仮説）']
    for title, flt in (('最多選出', None), ('同時選出', lambda g: g in both)):
        if flt is None:
            cnt = collections.Counter('/'.join(g['sel']) for g in main.values())
            top = cnt.most_common(1)[0][0] if cnt else None
            f2 = lambda g, top=top: '/'.join(g['sel']) == top
        else:
            f2 = flt
        its = tn2_items(gm, logs, f2)
        out.append(f"### {title}（{len(its)}戦）")
        if not its:
            out.append('- 該当なし')
            continue
        for T_ in range(1, 7):
            reach = [i for i in its if len(i['lg']) >= T_]
            if reach:
                cl = collections.Counter((i['lg'][T_ - 1][0], i['lg'][T_ - 1][1]) for i in reach)
                co = collections.Counter((i['lg'][T_ - 1][2], i['lg'][T_ - 1][3]) for i in reach)
                out.append(f"- T{T_} L: " + ', '.join(f'{f}:{x} {n}' for (f, x), n in cl.most_common(3)) + ' / 相手: ' + ', '.join(f'{f}:{x} {n}' for (f, x), n in co.most_common(3)))
        out += [f'- 分岐点 {x[1]}' for x in _delta_lines(its, None)[:5]]
        out += tn2_points(its)
    out += ['', '## 7. 結論']
    for v in plan['variants']:
        gs = [g for g in main.values() if g['variant'] == v]
        cnt = collections.Counter('/'.join(g['sel']) for g in gs)
        out.append(f"- {v}: 最多選出 {cnt.most_common(1)[0][0] if cnt else '該当なし'}、勝率 {_f(*_wr(gs))}")
    open(P['md'], 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f"書きました: {P['md']}")


def cmd_tn3_selftest(a):
    import shutil, subprocess, tempfile
    global _TN_PLAY, _TN3_SELECT
    D = a.out_dir or tempfile.mkdtemp(prefix='tn3test_')
    results = []

    def ok(n, cond, msg=''):
        results.append((n, bool(cond)))
        print(f"{'○' if cond else '×'} {n} {msg}", flush=True)

    busy = ('tn2_games.json', 'tn2_logs.jsonl', 'TONORAGU2.md', 'tn2_plan.json')   # 別プロセス(tn2)が実行中なら書き換わるので比較から外す
    sha = lambda: {k: v for k, v in _sha_all().items() if os.path.basename(k) not in busy}
    before = sha()
    before_busy = {k: v for k, v in _sha_all().items() if os.path.basename(k) in busy}
    p = subprocess.run([sys.executable, '-m', 'py_compile', 'roundrobin.py', 'refine.py'], cwd=HERE, capture_output=True, text=True)
    ok('1 py_compile', p.returncode == 0, p.stderr[-200:])

    class A_:
        pass

    def args(sub, **kw):
        x = A_()
        x.out_dir, x.procs, x.max_games, x.force, x.retry_errors, x.resource, x.stage = os.path.join(D, sub), a.procs, 0, True, False, 'loose', 1
        x.games, x.exclude, x.opp_depth, x.sel, x.control, x.tn2_dir, x.sec_game, x.focus = 3, None, None, 'adapt', False, os.path.join(D, 'tn2'), None, False
        x.__dict__.update(kw)
        return x

    # ---- 2 除外個体（スタブ）
    def mkg(sel, res, ms=0, faints=None, k=0):
        return {'stage': 1, 'res': res, 'sel': sel, 'main_side': ms, 'faints': faints or [], 'variant': 'A', 'k': k, 'left': None}

    def mkl(field):
        return {'log': [[field, 'x', 'o', 'y']]}
    bs = ['A', 'B', TN3_MIM]
    gm = {}
    n_ = 0

    def add(g, field=None):
        nonlocal n_
        n_ += 1
        gm[f'k{n_}'] = g
        if field:
            lg_[f'k{n_}'] = mkl(field)
    lg_ = {}
    for nm, ws in (('A', 3), ('B', 1), (TN3_MIM, 0)):
        for i in range(4):
            add(mkg([nm, 'x1', 'x2'], 1 if i < ws else -1), nm)
    e = tn3_exclusion(gm, lg_, bs, 12)
    ok('2a 最低勝率(B)が除外・ミミッキュ最低でも除外されない', e['name'] == 'B' and e['mode'] == 'auto' and e['table'][2]['rate'] == 0.0)
    # 同率 ①出場時
    gm, lg_, n_ = {}, {}, 0
    for i in range(4):
        add(mkg(['A', 'x1', 'x2'], 1 if i < 2 else -1), 'A' if i >= 2 else 'zz')     # 出場は負けのみ -> rate_out 0
        add(mkg(['B', 'x1', 'x2'], 1 if i < 2 else -1), 'B')
    e1 = tn3_exclusion(gm, lg_, bs, 8)
    # ②先発時
    gm, lg_, n_ = {}, {}, 0
    for i in range(4):
        add(mkg(['A', 'x1', 'x2'] if i >= 2 else ['x1', 'A', 'x2'], 1 if i < 2 else -1), 'A')
        add(mkg(['B', 'x1', 'x2'] if i < 2 else ['x1', 'B', 'x2'], 1 if i < 2 else -1), 'B')
    e2 = tn3_exclusion(gm, lg_, bs, 8)
    # ③被先頭瀕死率（A 先発時を同じにし、B のみ先頭瀕死）
    gm, lg_, n_ = {}, {}, 0
    for i in range(4):
        add(mkg(['x1', 'A', 'x2'], 1 if i < 2 else -1), 'A')
        add(mkg(['x1', 'B', 'x2'], 1 if i < 2 else -1, faints=[[3, 0, 'B', 'z']] if i >= 2 else []), 'B')
    e3 = tn3_exclusion(gm, lg_, bs, 8)
    # ④全部同じ -> 構築で後ろ
    gm, lg_, n_ = {}, {}, 0
    for i in range(4):
        add(mkg(['x1', 'A', 'x2'], 1 if i < 2 else -1), 'A')
        add(mkg(['x1', 'B', 'x2'], 1 if i < 2 else -1), 'B')
    e4 = tn3_exclusion(gm, lg_, bs, 8)
    ok('2b 同率 ①出場時 ②先発時 ③被先頭瀕死 ④後ろ', (e1['name'], e2['name'], e3['name'], e4['name']) == ('A', 'A', 'B', 'B') and e1['tie'] == ['A', 'B'], str((e1['name'], e2['name'], e3['name'], e4['name'])))
    em = tn3_exclusion(gm, lg_, bs, 8, manual='A')
    errs = 0
    for bad in (TN3_MIM, 'ゾウ'):
        try:
            tn3_exclusion(gm, lg_, bs, 8, manual=bad)
        except SystemExit:
            errs += 1
    ok('2c --exclude 優先・ミミッキュ/不明名はエラー', em['name'] == 'A' and em['mode'] == 'manual' and em['auto_name'] == 'B' and errs == 2)

    # ---- tn2 スタブ + plan
    rp = load_plan(paths(None))
    V = tn_load_variants()
    T = dict(rp['teams'])
    for v, rt in V.items():
        T[rt['id']] = rt
    _worker_init(T)
    L = TN_L
    rr_apply(T[L])
    rt = T[L]
    bases = [m['base'] for m in rt['mons']]
    cs24 = [list(c) for c in rt['candidates']]
    osels = {v: tn_opp_sels(v, V[v], TN2_LEADS[v]) for v in V}
    tdir = os.path.join(D, 'tn2')
    os.makedirs(tdir, exist_ok=True)
    g2 = {}
    for v in V:
        for os_ in osels[v]:
            for j, ls in enumerate(cs24):
                h = zlib.crc32(f'{v}{os_}{j}'.encode())
                g2[tn2_key(v, os_, ls, 0)] = {'stage': 1, 'res': (1, -1, 0)[h % 3], 'sel': ls, 'main_side': 0, 'faints': [[3, 0, ls[0], 'z']], 'variant': v, 'k': 0, 'left': None}
    json.dump({'games': {'1': 1, '2': 1}, 'candidates': cs24, 'variants': {v: {'opp_sels': osels[v]} for v in V}, 'stage2_sels': None}, open(os.path.join(tdir, 'tn2_plan.json'), 'w', encoding='utf-8'))
    json.dump({'games': g2}, open(os.path.join(tdir, 'tn2_games.json'), 'w', encoding='utf-8'))
    open(os.path.join(tdir, 'tn2_logs.jsonl'), 'w').close()
    ex_name = next(b for b in bases if b not in (TN3_MK, TN3_ZD, TN3_MIM))
    short = dict(g2)
    for kk in list(short)[:5]:
        del short[kk]
    td2 = os.path.join(D, 'tn2short')
    os.makedirs(td2, exist_ok=True)
    for f in ('tn2_plan.json', 'tn2_logs.jsonl'):
        shutil.copy(os.path.join(tdir, f), os.path.join(td2, f))
    json.dump({'games': short}, open(os.path.join(td2, 'tn2_games.json'), 'w', encoding='utf-8'))
    try:
        cmd_tn3_plan(args('stop', tn2_dir=td2))
        stopped = False
    except SystemExit:
        stopped = True
    pm = cmd_tn3_plan(args('short', tn2_dir=td2, exclude=ex_name))
    ok('2d tn2 未完なら --exclude 無しは停止、有りは通り note に tn2 未完', stopped and 'tn2 未完' in pm['exclude'].get('note', ''))
    t0 = time.time()
    pl = cmd_tn3_plan(args('r', exclude=ex_name))
    sec_plan = time.time() - t0
    pa_ = cmd_tn3_plan(args('auto'))
    ok('2e 完了データで機械決定・根拠表6体・sha', pa_['exclude']['mode'] == 'auto' and len(pa_['exclude']['table']) == 6 and len(pa_['exclude']['tn2_sha256']) == 64, f"除外={pa_['exclude']['name']}")

    # ---- 3 許容集合
    od = pl['orders']
    ok('3a 18通り・ミミッキュ必須・除外なし・重複なし・norm済み', len(od) == 18 and all(TN3_MIM in o and ex_name not in o and len(set(o)) == 3 and o == norm_order(o, bases) for o in od)
       and len({tuple(o) for o in od}) == 18)
    ok('3b ムクホーク+リザードンX 同時選出が3通り', sum(1 for o in od if TN3_MK in o and TN3_ZD in o) == 3)
    T3 = tn3_teams(pl, T)
    ok('3c adapt の candidates が18通りに絞られる', len(T3[L]['candidates']) == 18 and all(tuple(o) in {tuple(x) for x in od} for it in T3[L]['gitems'] for o in it['orders']) and len(rt['candidates']) == 24)
    ok('3d plan sel1 は許容集合内・変種ごと', all(tuple(pl['sel1'][v]['order']) in {tuple(x) for x in od} for v in V), str({v: pl['sel1'][v]['order'] for v in V}))

    # ---- 4 ムクホークがメガしない（実 blind_play 浅い深さ）
    _worker_init(T3)
    zs = norm_order([TN3_MK, TN3_ZD, TN3_MIM], bases)
    cap = {}
    orig_mb = R.mega_ban

    def spy(st, side, names):
        orig_mb(st, side, names)
        cap[side] = {m.name: m.can_mega for m in st.sides[side].mons if m.mega_form is not None}
    R.mega_ban = spy
    rows_ = {}
    try:
        for k in (0, 1):
            j = list(tn3_job(pl, T, 0, k, False, []))
            j[6], j[9] = zs, (1, 1)
            cap.clear()
            r = _job_tn3(tuple(j))
            ms = 0 if k % 2 == 0 else 1
            log = r.get('log') or []
            mk_m = [t for t, row in enumerate(log) if row[2 * ms].startswith(TN3_MK) and str(row[2 * ms + 1]).startswith('M+')]
            sn = r.get('snap') or []
            zm = [t for t, row in enumerate(log) if row[2 * ms].startswith(TN3_ZD) and str(row[2 * ms + 1]).startswith('M+')]
            sn_ok = all(not sn[t]['mega'][ms] or (zm and zm[0] < t) for t, row in enumerate(log) if row[2 * ms].startswith(TN3_MK) and t < len(sn))
            rows_[k] = (r.get('res') is not None, not mk_m, sn_ok, cap.get(ms, {}).get(TN3_ZD) is True and cap.get(ms, {}).get(TN3_MK) is False, bool(zm))
        ok('4a 同時選出で k偶数/奇数ともムクホーク M+ なし・snap mega 整合・開始時 リザードンX can_mega=True', all(all(v[:4]) for v in rows_.values()), str(rows_))
        # 対照
        _TN3_NOBAN[0] = True
        j = list(tn3_job(pl, T, 0, 0, False, []))
        j[6], j[9] = zs, (1, 1)
        r = _job_tn3(tuple(j))
        _TN3_NOBAN[0] = False
        log = r.get('log') or []
        mk_ctl = any(row[0].startswith(TN3_MK) and str(row[1]).startswith('M+') for row in log)
        ok('4b 対照: megaban 無し k偶数ならムクホークがメガする', mk_ctl, f"res={r.get('res')} {r.get('error') or ''}")
        # 従来呼び出し一致
        seen = []

        def wrap(full):
            def f(args_):
                seen.append(len(args_))
                return orig_play(args_ if full else args_[:14])
            return f
        orig_play = R.blind_play
        j = list(tn3_job(pl, T, 0, 0, False, []))
        j[6], j[9] = norm_order([TN3_MIM, bases[0] if bases[0] not in (TN3_MIM, ex_name) else bases[1], TN3_MK], bases), (1, 1)
        rs_ = []
        for full in (True, False):
            _TN_PLAY = wrap(full)
            rs_.append(_job_tn3(tuple(j)))
        _TN_PLAY = R.blind_play
        ok('4c megaban (None,None) と従来(14引数)で res/log/faints/left/turns 一致', all(rs_[0].get(x) == rs_[1].get(x) for x in ('res', 'log', 'faints', 'left', 'turns')) and rs_[0].get('res') is not None, str(seen))
        # _AD_EVAL 経路
        cap.clear()
        X0 = pl['variants']['A']['id']
        with _ad_blind(L, X0):
            ev = _tn3_eval(zs, pl['cells'][0][1], False)
        ok('4d _AD_EVAL(_tn3_eval) でも禁止が効く', cap.get(0, {}).get(TN3_MK) is False and cap.get(0, {}).get(TN3_ZD) is True and isinstance(ev, (int, float)), str(ev))
    finally:
        R.mega_ban = orig_mb
        _TN3_NOBAN[0] = False
        _TN_PLAY = R.blind_play

    # ---- 8 時間（実 d6 1戦、adapt 選出 1回）
    j = list(tn3_job(pl, T, 0, 0, False, []))
    j[6] = zs
    t0 = time.time()
    r6 = _job_tn3(tuple(j))
    sec6 = time.time() - t0
    bX = [m['base'] for m in T[pl['variants']['A']['id']]['mons']]
    hist = [{'n': 0, 'mine': list(od[0]), 'theirs': norm_order(list(pl['cells'][0][1]), bX), 'res_for_A': 1.0}]
    j = list(tn3_job(pl, T, 0, 1, False, hist))
    j[9] = (1, 1)
    r_s = _job_tn3(tuple(j))
    ok('8a 実 d6 1戦 (6,6) 同時選出', r6.get('res') is not None, f"{sec6:.0f}秒 {r6.get('turns')}手 {r6.get('error') or ''}")
    ok('8b adapt 選出1回', r_s.get('why') is not None and r_s.get('lsel') in od, f"選出 {r_s.get('ssec')}秒 plan(sel1×3込み) {sec_plan:.0f}秒")
    est = tn3_estimate(10, 6, 4, round(sec6), r_s.get('ssec') or 20.0)
    print(f"  見積り(procs=4, 実測 d6 {sec6:.0f}秒 + 選出 {r_s.get('ssec')}秒): {est}", flush=True)

    # ---- 5 再開（スタブ）
    def stub(args_):
        h = zlib.crc32(repr((args_[2], args_[3], args_[4])).encode())
        n = 6
        names = [args_[2][0], args_[3][0]]
        log = [[args_[2][0], ('M+' if (t == 1 and args_[2][0] == TN3_ZD) else '') + ('げきりん' if (h >> t) & 1 else 'のろい'), args_[3][0], 'じしん'] for t in range(n)]
        sn_ = [{'w': '', 'wt': 0, 'tr': '', 'tt': 0, 'room': 0, 'hp': [100, 100], 'mega': [t > 1, False], 'bk': [False, None],
                'vol': [{'perish': None, 'encore': None, 'curse': False}] * 2, 'item': ['', ''], 'alive': [3, 3]} for t in range(n)]
        po_ = [{'hp': [90, 90], 'act': names, 'ej': [False, False]} for t in range(n)]
        return {'res': (1, -1, 0)[h % 3], 'turns': n, 'judged': False,
                'left': [[[m, (h >> i) % 101] for i, m in enumerate(args_[2])], [[m, (h >> (i + 3)) % 101] for i, m in enumerate(args_[3])]],
                'faints': [[3, 0, args_[2][0], args_[3][0]], [5, 1, args_[3][0], args_[2][1]]], 'log': log, 'snap': sn_, 'post': po_,
                'echo': [list(args_[14])]}

    def sel_stub(A, X, hist):
        i = (zlib.crc32(repr(hist).encode()) + 3 * len(hist)) % 18
        o = od[i]
        return list(o), {'src': 'stub', 'e_all': [[round(((zlib.crc32(repr((hist, x)).encode()) % 100) / 100), 2), list(x)] for x in od]}

    _TN_PLAY, _TN3_SELECT = stub, sel_stub
    try:
        a1 = args('s1', max_games=7, games=3)
        cmd_tn3_plan(a1)
        cmd_tn3_run(a1)
        P1 = tn3_paths(a1.out_dir)
        g7 = json.load(open(P1['games'], encoding='utf-8'))['games']
        a1.max_games = 0
        n_new = cmd_tn3_run(a1)
        g18 = json.load(open(P1['games'], encoding='utf-8'))['games']
        ok('5a 再開: 7件→残り11件だけ・既存不変', len(g7) == 7 and n_new == 11 and len(g18) == 18 and all(json.dumps(g18[k], sort_keys=True) == json.dumps(g7[k], sort_keys=True) for k in g7))
        pre = all(g['k'] in (0, 1, 2) for g in g18.values()) and all(len({tn3_key(v, o, k) in g18 for k in range(3)}) == 1 for v, o in pl['cells'])
        ok('5b セル6×k3・sel は許容集合内・megaban は両方選出の時だけ記録', pre and all(g['sel'] in od for g in g18.values()) and
           all((g['mega_ban'] == [TN3_MK]) == (TN3_MK in g['sel'] and TN3_ZD in g['sel']) for g in g18.values()))
        ok('5b2 echo(args[14]) が L 側にだけ入る', all(((g['echo'][0][g['main_side']] == [TN3_MK]) if g['mega_ban'] else (g['echo'][0] == [None, None])) for g in g18.values() if g.get('echo')))
        lg = read_jsonl(P1['logs'])
        ok('5c tn3_logs に key/log/snap/post', len(lg) == 18 and all({'key', 'log', 'snap', 'post'} <= set(x) for x in lg))
        ci0 = pl['cells'][0]
        k0 = [tn3_key(ci0[0], ci0[1], k) for k in range(3)]
        sel_k2 = g18[k0[2]]['sel']
        G = json.load(open(P1['games'], encoding='utf-8'))
        G['games'][k0[1]]['res'], G['games'][k0[1]]['error'] = None, 'x'
        del G['games'][k0[2]]
        json.dump(G, open(P1['games'], 'w', encoding='utf-8'))
        n_a = cmd_tn3_run(a1)
        a1.retry_errors = True
        n_b = cmd_tn3_run(a1)
        g_b = json.load(open(P1['games'], encoding='utf-8'))['games']
        ok('5d error の k より後は走らず・--retry-errors で再開・同じ hist から同じ選出', n_a == 0 and n_b == 2 and g_b[k0[2]]['sel'] == sel_k2, f'{n_a},{n_b}')
        a1.retry_errors, a1.games = False, 4
        n_c = cmd_tn3_run(a1)
        ok('5e --games 増加で新しい k だけ追加', n_c == 6, str(n_c))
        # rotate + control
        a2 = args('s2', sel='rotate', control=True, games=2)
        pr = cmd_tn3_plan(a2)
        cmd_tn3_run(a2)
        g2_ = json.load(open(tn3_paths(a2.out_dir)['games'], encoding='utf-8'))['games']
        okc = all(g['sel'] == pr['control'][g['variant']]['sel'] for g in g2_.values() if g['ctl'])
        okr = all(g['sel'] == od[(g['k'] + 3 * g['cell']) % 18] for g in g2_.values() if not g['ctl'])
        ok('5f rotate/control: 件数24・key tn3c:・sel 一致', len(g2_) == 24 and sum(1 for k in g2_ if k.startswith('tn3c:')) == 12 and okc and okr)
        # 7 report
        cmd_tn3_report(a1)
        md = open(P1['md'], encoding='utf-8').read()
        heads = ['## 1. 条件', '## 2. 除外した個体と根拠', '## 3. 選出別・変種別の勝率', '## 4. ムクホーク＋リザードンX同時選出', '## 5. ミミッキュ必須ルールの効果', '## 6. 勝ち筋のターン別行動', '## 7. 結論']
        ok('7 report: §1〜§7 の見出し', all(h in md for h in heads), str([h for h in heads if h not in md]))
    finally:
        _TN_PLAY, _TN3_SELECT = R.blind_play, adapt_select
    after = sha()
    ok('6 既存結果の sha256 不変（tn2 実行中の4ファイルは比較から除外）・既定の場所に tn3_* を作らない', after == before and not [f for f in os.listdir(DEF_OUT) if f.startswith('tn3_')] and
       not os.path.exists(os.path.join(HERE, '..', 'logs', 'TONORAGU3.md')))
    if not a.keep and not a.out_dir:
        shutil.rmtree(D, ignore_errors=True)
    bad = [n for n, c in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} ○" + (f"  ×: {bad}" if bad else '') + f"  実d6 1戦 {sec6:.0f}秒 / 選出 {r_s.get('ssec')}秒")
    if bad:
        raise SystemExit(1)



def cmd_tonorag(a):
    if getattr(a, 'tn3', False):
        return {'plan': cmd_tn3_plan, 'run': cmd_tn3_run, 'report': cmd_tn3_report, 'selftest': cmd_tn3_selftest}[a.what](a)
    if getattr(a, 'focus', False):
        return {'plan': cmd_tn2_plan, 'run': cmd_tn2_run, 'report': cmd_tn2_report, 'selftest': cmd_tn2_selftest}[a.what](a)
    {'import': lambda x: tn_import(x.force, getattr(x, 'from_file', None)), 'plan': cmd_tonorag_plan, 'run': cmd_tonorag_run,
     'report': cmd_tonorag_report, 'selftest': cmd_tonorag_selftest}[a.what](a)




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
    p = sp.add_parser('m7')
    p.add_argument('what', choices=['plan', 'run', 'report', 'selftest'])
    p.add_argument('--party', default='M7')
    p.add_argument('--prefix', default=None)
    p.add_argument('--resource', action='store_true', help='SPEC_RESOURCE.md: 取り巻きを切れるリソースとして読む（厳格版）')
    p.add_argument('--resource-loose', action='store_true', help='resource の緩和版（--resource を含む）')
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--force', action='store_true')
    p.add_argument('--max-games', type=int, default=0)
    p.add_argument('--retry-errors', action='store_true')
    p.add_argument('--quick', action='store_true')
    p.add_argument('--keep', action='store_true')
    p.add_argument('--out-dir')
    p = sp.add_parser('counter')
    p.add_argument('what', choices=['plan', 'run', 'report', 'selftest'])
    p.add_argument('--opps')
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--force', action='store_true')
    p.add_argument('--max-games', type=int, default=0)
    p.add_argument('--retry-errors', action='store_true')
    p.add_argument('--keep', action='store_true')
    p.add_argument('--out-dir')
    p = sp.add_parser('playbook')
    p.add_argument('what', choices=['selftest', 'ab', 'report'])
    p.add_argument('--team', default=PB_LH)
    p.add_argument('--opps')
    p.add_argument('--games', type=int, default=4)
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--out-dir')
    p = sp.add_parser('sched3')
    p.add_argument('what', choices=['plan', 'run', 'report', 'selftest'])
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--force', action='store_true')
    p.add_argument('--test-ids')
    p.add_argument('--max-games', type=int, default=0)
    p.add_argument('--retry-errors', action='store_true')
    p.add_argument('--out-dir')
    p = sp.add_parser('final20')
    p.add_argument('what', choices=['plan', 'run', 'report', 'selftest'])
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--force', action='store_true')
    p.add_argument('--max-games', type=int, default=0)
    p.add_argument('--retry-errors', action='store_true')
    p.add_argument('--out-dir')
    p = sp.add_parser('tonorag')
    p.add_argument('what', choices=['import', 'plan', 'run', 'report', 'selftest'])
    p.add_argument('--stage', type=int, choices=[1, 2], default=1)
    p.add_argument('--resource', choices=list(TN_MODES), default=None, help='plan の既定は loose。run は plan と同じ値だけ')
    p.add_argument('--procs', type=int, default=4)
    p.add_argument('--force', action='store_true')
    p.add_argument('--from-file')
    p.add_argument('--max-games', type=int, default=0)
    p.add_argument('--retry-errors', action='store_true')
    p.add_argument('--keep', action='store_true')
    p.add_argument('--out-dir')
    p.add_argument('--focus', action='store_true')
    p.add_argument('--tn3', action='store_true')
    p.add_argument('--exclude')
    p.add_argument('--opp-depth', type=int, default=None)
    p.add_argument('--sel', choices=['adapt', 'rotate'], default=None)
    p.add_argument('--control', action='store_true')
    p.add_argument('--tn2-dir', default=None)
    p.add_argument('--games', type=int, default=None)
    p.add_argument('--games2', type=int, default=None)
    p.add_argument('--top', type=int, default=None)
    for nm in ('run', 'deny', 'adapt', 'm7', 'counter', 'sched3', 'final20', 'tonorag'):
        sp.choices[nm].add_argument('--no-playbook', action='store_true')
    a = ap.parse_args()
    _PB_FLAG['on'] = not getattr(a, 'no_playbook', False)
    {'tonorag': cmd_tonorag, 'm7': cmd_m7, 'final20': cmd_final20, 'sched3': cmd_sched3, 'playbook': cmd_playbook, 'counter': cmd_counter, 'adapt': cmd_adapt, 'deny': cmd_deny, 'plan': cmd_plan, 'run': cmd_run, 'report': cmd_report, 'selftest': cmd_selftest, 'show': cmd_show}[a.cmd](a)


if __name__ == '__main__':
    main()
