"""Nightly study of new team articles on pokesol.app (run by a scheduled routine).

  python study.py [--max N] [--dry]          記事の取り込み（シミュレーションはしない）
  python study.py pending                    ガイド未記入の構築（id・題名・本文ファイル）を列挙
  python study.py note <id> <json-file>      ガイドを known_teams.json に書き込む

1. Reads the newest team articles (https://pokesol.app/?tab=new&category=team, newest first).
2. Keeps singles articles under our rules (regulation M-C, any season) whose article states a final or reached
   rating of 2000+ (or, when no rating is written, a final rank of 1000 or better). Higher rank / rating first.
3. Stores each team's six (sets) in data/known_teams.json with its rating, and the article text in
   logs/study/text/<id>.txt. No battles are simulated.
4. The routine's Claude reads each pending article and writes a short `guide` (型・軸・運用・選出基準・重い相手・注意)
   with `note`. battle.py shows the guides of similar lineups (3+ of the opponent's six) when it meets them:
   a thing to keep in the back of the head, never a rule that overrides the reading of the battle.
"""
import datetime, html, json, os, re, sys, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle as B  # noqa: E402
import pokesol  # noqa: E402
import prep  # noqa: E402
from calc import POKE  # noqa: E402

LIST_URL = 'https://pokesol.app/?tab=new&category=team&page={}'
OUT_D = os.path.join(HERE, '..', 'logs', 'study')
TEXT_D = os.path.join(OUT_D, 'text')
REPORT_P = os.path.join(HERE, '..', 'logs', 'STUDY.md')
JST = datetime.timezone(datetime.timedelta(hours=9))
MIN_RATE = 2000
MAX_RANK_NO_RATE = 1000      # rank only: top 1000 was ~2200 in M-6 (967th = R2228)


def now():
    return datetime.datetime.now(JST)


def list_articles(max_pages=15, max_days=60):
    out = []
    for p in range(1, max_pages + 1):
        try:
            d = pokesol._stream(pokesol.fetch(LIST_URL.format(p)))['loaderData']['routes/_index']
        except Exception as e:
            print('list page', p, e, flush=True)
            break
        arts = d.get('articles') or []
        for a in arts:
            ts = a.get('publishedAt')
            ts = ts[1] / 1000 if isinstance(ts, list) and len(ts) > 1 else None
            a['_ts'] = ts
            out.append(a)
        if not arts or p >= (d.get('totalPages') or p):
            break
        if arts[-1]['_ts'] and time.time() - arts[-1]['_ts'] > max_days * 86400:
            break
    return out


def _season_no(s):
    m = re.match(r'm-(\d+)', s or '')
    return int(m.group(1)) if m else None


_NUM = r'([12]\d{3})'


def _other_season(t, i, season):
    """True when the 14 characters before position i name a different season (前期・M-4 etc.)."""
    ctx = t[max(0, i - 14):i]
    if '前期' in ctx or '前シーズン' in ctx:
        return True
    m = re.findall(r'(?:[MＭ]\s*-?\s*|S|シーズン\s*)(\d+)', ctx)
    return bool(m) and season is not None and int(m[-1]) != season


def _contest(t, i):
    """A placing in a tournament (AsOne, MCS, ...) rather than on the ladder: a Latin word just before it."""
    return bool(re.search(r'[A-Za-z]{3,}[\w\s]{0,10}$', t[max(0, i - 14):i]))


def rating(title, body='', season=None):
    """(final rank, final rating, reached rating): from the title first, the body only for what the title lacks.
    Mentions of other seasons and mid-season ranks (最終日N位) are ignored."""
    def scan(t, is_title):
        t = t.replace('，', ',').replace('　', ' ').translate(str.maketrans('０１２３４５６７８９', '0123456789'))
        t = re.sub(r'(\d),(\d{3})', r'\1\2', t)
        rank = final = peak = None
        for m in re.finditer(r'(?:最終順位|最終(?!日))\s*[:：]?\s*(\d{1,5})\s*位', t):
            if not _other_season(t, m.start(), season) and not _contest(t, m.start()):
                rank = int(m.group(1)); break
        if rank is None and is_title:          # in the title any 「N位」 is the article's own result
            for m in re.finditer(r'(?<![\d日])(\d{1,5})\s*位', t):
                pre = t[max(0, m.start() - 14):m.start()]
                if '日' not in pre[-3:] and '前期' not in pre and not _other_season(t, m.start(), season) \
                        and not _contest(t, m.start()):
                    rank = int(m.group(1)); break
        if rank is None and is_title:      # 「最終815」: up to three digits after 最終 is a rank
            m = re.search(r'最終(?!日)\s*(\d{1,3})(?![\d位桁])', t)
            if m and not _other_season(t, m.start(), season):
                rank = int(m.group(1))
        for m in re.finditer(r'(?:最終レート|最終\s*R|最終(?!日))\s*[:：]?\s*' + _NUM + r'(?!\s*位)', t):
            if not _other_season(t, m.start(), season):
                final = max(final or 0, int(m.group(1)))
        for m in re.finditer(r'(?:最高レート|最高\s*R|最高|到達レート|到達|最大)\s*[:：]?\s*' + _NUM, t):
            if not _other_season(t, m.start(), season):
                peak = max(peak or 0, int(m.group(1)))
        for m in re.finditer(r'(?:レート|(?<![A-Za-z])R)\s*[:：]?\s*' + _NUM + r'(?!\s*位)', t):
            if _other_season(t, m.start(), season):
                continue
            v = int(m.group(1))
            if re.search(r'最高|到達', t[max(0, m.start() - 6):m.start()]):
                peak = max(peak or 0, v)
            elif not re.search(r'→', t[m.end():m.end() + 2]):
                final = max(final or 0, v)
        for m in re.finditer(_NUM + r'\s*(?:到達|達成|↑)', t):
            if not _other_season(t, m.start(), season):
                peak = max(peak or 0, int(m.group(1)))
        ok = lambda v: v if v and 1000 <= v <= 2900 else None
        return rank, ok(final), ok(peak)
    a, b = scan(title, True), scan(body, False)
    return tuple(x if x is not None else y for x, y in zip(a, b))


def qualifies(rank, final, peak):
    best = max(final or 0, peak or 0)
    if best:
        return best >= MIN_RATE
    return rank is not None and rank <= MAX_RANK_NO_RATE


def priority(c):
    rank, final, peak = c['rating']
    return (rank if rank is not None else 10 ** 6, -(max(final or 0, peak or 0)))


RULES = ('mc',)          # same rules as ours (regulation M-C): any season is fine


def candidates():
    arts = [a for a in list_articles() if a.get('battleFormat') == 'single' and a.get('category') == 'team']
    out = [a for a in arts if a.get('regulation') in RULES]
    return out, sorted({a.get('season') for a in out if a.get('season')})


def load_article(a):
    url = f"https://pokesol.app/u/{a['author']['username']}/articles/{a['id']}"
    page = pokesol.fetch(url)
    root = pokesol._stream(page)['loaderData']['routes/u.$username.articles.$id']
    raw = str((root.get('article') or {}).get('body', ''))
    full = html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'</(p|h\d|li|div)>', '\n', raw)))
    full = re.sub(r'\n{3,}', '\n\n', full).strip()
    body = html.unescape(re.sub(r'<[^>]+>', ' ', raw))
    t = pokesol.parse(page, url)
    t['_text'] = full
    for m in t['team']:
        m['moves'] = [x for x in m['moves'] if x]
    body = ' '.join(body.split())[:200]       # the author's own result is stated at the top; later text cites others
    if len(t['team']) > 6:                     # a 7th card is an alternative member
        t['team'] = t['team'][:6]
    return t, rating(t['title'], body, _season_no(a.get('season')))


def valid_team(t):
    if len(t['team']) != 6:
        return False
    for m in t['team']:
        if B._base(m['name']) not in POKE:                # ギルガルド(盾) / ストリンダー(ハイ): the base form
            n2 = re.sub(r'\(.*?\)$', '', m['name'])
            if B._base(n2) in POKE:
                m['name'] = n2
        m['moves'] = [x for x in m['moves'] if x in B.MOVE]
        if not m['moves'] or B._base(m['name']) not in POKE:
            print('   unknown:', m['name'], m['moves'], flush=True)
            return False
    return True


def save(t, info):
    """Adds / updates the team (sets, rating) and keeps the article text for the guide. Existing study / counter /
    guide / picks / notes of the same team are kept."""
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    old = next((x for x in data['teams'] if x['id'] == t['id']), None)
    text = t.pop('_text', '')
    if old:
        for k in ('picks', 'notes', 'study', 'counter', 'guide'):
            if k in old:
                t[k] = old[k]
    t['rating'] = {'rank': info[0], 'final': info[1], 'peak': info[2]}
    if old:
        data['teams'][data['teams'].index(old)] = t
    else:
        data['teams'].append(t)
    json.dump(data, open(prep.KNOWN_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.makedirs(TEXT_D, exist_ok=True)
    open(os.path.join(TEXT_D, t['id'] + '.txt'), 'w', encoding='utf-8').write(
        f"{t['title']}\n{t['url']}\n\n" + text[:12000])


def pending():
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))['teams']
    return [t for t in data if not t.get('guide') and os.path.exists(os.path.join(TEXT_D, t['id'] + '.txt'))]


GUIDE_KEYS = ('type', 'core', 'plan', 'picks', 'heavy', 'notes')


def note(tid, path):
    """guide = {type: 構築の型, core: [軸のポケモン], plan: 運用の要点, picks: [{when, pick, note}], heavy: [重い相手], notes: 注意}"""
    g = json.load(open(path, encoding='utf-8'))
    g = {k: g[k] for k in GUIDE_KEYS if k in g}
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    t = next(x for x in data['teams'] if x['id'] == tid)
    g['date'] = now().strftime('%Y-%m-%d')
    t['guide'] = g
    json.dump(data, open(prep.KNOWN_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    report()


ARTSETS_P = os.path.join(HERE, 'data', 'article_sets.json')


def build_article_sets(teams_extra=()):
    """Every set from high-rated articles (known_teams.json + the qualifying new articles) by species, for the set
    guesser (sets.py): what strong players actually run, next to the usage data."""
    import sets as _sets
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))['teams']
    by_id = {t['id']: t for t in data}
    for t in teams_extra:
        by_id.setdefault(t['id'], t)
    out = {}
    for tid, t in by_id.items():
        for m in t['team']:
            b = B._base(m['name'])
            if b not in POKE:
                continue
            moves = [x for x in m.get('moves', []) if x in B.MOVE]
            if not moves or not m.get('nature'):
                continue
            mega = _sets.mega_for(b, m.get('item'))
            ap = {k: v for k, v in (m.get('ap') or {}).items() if v}
            e = {'nature': m['nature'], 'ap': ap, 'item': m.get('item'), 'moves': moves[:4],
                 'ability': m.get('base_ability') or m.get('ability') or POKE[b]['ab'][0],
                 'mega': mega, 'mega_ability': (POKE[mega]['ab'][0] if mega else None), 'teams': [tid]}
            lst = out.setdefault(b, [])
            same = next((x for x in lst if {k: x[k] for k in ('nature', 'ap', 'item')} ==
                         {k: e[k] for k in ('nature', 'ap', 'item')} and sorted(x['moves']) == sorted(e['moves'])), None)
            if same:
                if tid not in same['teams']:
                    same['teams'].append(tid)
            else:
                lst.append(e)
    json.dump(out, open(ARTSETS_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    return out


def report():
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    rows = [t for t in data['teams'] if t.get('guide')]
    rows.sort(key=lambda t: ((t.get('rating') or {}).get('rank') or 10 ** 6,
                             -max((t.get('rating') or {}).get('final') or 0, (t.get('rating') or {}).get('peak') or 0)))
    L = ['# 新着構築の記録（study.py が自動生成）', '',
         'pokesol の新着構築記事（シングル・レギュレーションM-C・シーズン不問・最終/到達レート2000以上。レートの記載がない場合は最終1000位以内）の、',
         '構築の型・運用・選出基準の記録です。対戦はシミュレーションしていません。',
         '実戦では相手の6体のうち3体以上が一致する構築のガイドを、頭の片隅に置く参考として表示します（battle.py）。', '']
    for t in rows:
        r, g = t.get('rating') or {}, t['guide']
        rr = ' '.join(x for x in [f"{r['rank']}位" if r.get('rank') else '', f"最終{r['final']}" if r.get('final') else '',
                                  f"最高{r['peak']}" if r.get('peak') else ''] if x)
        L += [f"## [{t['title'][:40]}]({t['url']})", f"- {rr}／{g.get('type', '')}／{' '.join(m['name'] for m in t['team'])}"]
        if g.get('plan'):
            L.append(f"- 運用: {g['plan']}")
        for p in g.get('picks') or []:
            L.append(f"- 選出: {p.get('when', '')} → {' / '.join(p.get('pick') or [])} {p.get('note', '')}")
        if g.get('heavy'):
            L.append(f"- 重い相手: {'、'.join(g['heavy'])}")
        if g.get('notes'):
            L.append(f"- 注意: {g['notes']}")
        L.append('')
    open(REPORT_P, 'w', encoding='utf-8').write('\n'.join(L) + '\n')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv[1:]
    if a[:1] == ['pending']:
        for t in pending():
            print(t['id'], t['title'], os.path.join(TEXT_D, t['id'] + '.txt'))
        return
    if a[:1] == ['note']:
        note(a[1], a[2])
        return
    cands, targets = candidates()
    print(f'{len(cands)} articles (regulation {RULES}, seasons {targets})', flush=True)
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    have = {t['id'] for t in data['teams'] if os.path.exists(os.path.join(TEXT_D, t['id'] + '.txt'))}
    todo = []
    for art in cands:
        if art['id'] in have:
            continue
        try:
            t, info = load_article(art)
        except Exception as e:
            print('skip (fetch)', art['id'], e, flush=True)
            continue
        if not qualifies(*info):
            print(f"skip (rating {info})", t['title'][:40], flush=True)
            continue
        if not valid_team(t):
            print('skip (team)', t['title'][:40], flush=True)
            continue
        todo.append({'t': t, 'rating': info})
    todo.sort(key=priority)
    if '--max' in a:
        todo = todo[:int(a[a.index('--max') + 1])]
    arts = build_article_sets([c['t'] for c in todo])
    print(f"article sets: {sum(len(v) for v in arts.values())} sets of {len(arts)} species", flush=True)
    print('new:', [(c['t']['title'][:24], c['rating']) for c in todo], flush=True)
    if '--dry' in a:
        return
    for c in todo:
        save(c['t'], c['rating'])
        print('saved', c['t']['title'][:40], flush=True)
    print(f'pending guides: {len(pending())}', flush=True)


if __name__ == '__main__':
    main()
