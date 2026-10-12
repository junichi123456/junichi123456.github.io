"""Nightly study of new team articles on pokesol.app (run by a scheduled routine, 0:01-7:00 JST).

  python study.py [--until HH:MM | --slot] [--depth 4] [--dry] [--max N]

1. Reads the newest team articles (https://pokesol.app/?tab=new&category=team, newest first).
2. Keeps singles articles of the current season or the one before it whose article states a final or reached
   rating of 2000+ (or, when no rating is written, a final rank of 1000 or better). Articles without any rating or
   rank are skipped. Higher final rank / rating first.
3. For each (until --until, JST): adds the team to data/known_teams.json and plays every one of our 60 orders
   against every likely selection of theirs, both sides reading --depth turns ahead (default 4), one game each.
4. Stores the hardest selection of theirs (the one that beats the orders we would bring most often), the order of
   ours that did best against it, and that order's average win rate over all their selections:
   known_teams.json ("study", and "counter" so battle.py select uses it when all six match) and logs/STUDY.md.
"""
import datetime, html, json, os, re, sys, time, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle as B  # noqa: E402
import pokesol  # noqa: E402
import prep  # noqa: E402
import refine as R  # noqa: E402
from calc import POKE  # noqa: E402

LIST_URL = 'https://pokesol.app/?tab=new&category=team&page={}'
OUT_D = os.path.join(HERE, '..', 'logs', 'study')
REPORT_P = os.path.join(HERE, '..', 'logs', 'STUDY.md')
JST = datetime.timezone(datetime.timedelta(hours=9))
MIN_RATE = 2000
MAX_RANK_NO_RATE = 1000      # rank only: top 1000 was ~2200 in M-6 (967th = R2228)


def now():
    return datetime.datetime.now(JST)


def list_articles(max_pages=8, max_days=21):
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


def rating(title, body='', season=None):
    """(final rank, final rating, reached rating): from the title first, the body only for what the title lacks.
    Mentions of other seasons and mid-season ranks (最終日N位) are ignored."""
    def scan(t, is_title):
        t = t.replace('，', ',').replace('　', ' ').translate(str.maketrans('０１２３４５６７８９', '0123456789'))
        t = re.sub(r'(\d),(\d{3})', r'\1\2', t)
        rank = final = peak = None
        for m in re.finditer(r'(?:最終順位|最終(?!日))\s*[:：]?\s*(\d{1,5})\s*位', t):
            if not _other_season(t, m.start(), season):
                rank = int(m.group(1)); break
        if rank is None and is_title:          # in the title any 「N位」 is the article's own result
            for m in re.finditer(r'(?<![\d日])(\d{1,5})\s*位', t):
                pre = t[max(0, m.start() - 14):m.start()]
                if '日' not in pre[-3:] and '前期' not in pre and not _other_season(t, m.start(), season):
                    rank = int(m.group(1)); break
        if rank is None and is_title:      # 「最終815」: up to three digits after 最終 is a rank
            m = re.search(r'最終(?!日)\s*(\d{1,3})(?![\d位])', t)
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


def candidates():
    arts = [a for a in list_articles() if a.get('battleFormat') == 'single' and a.get('category') == 'team']
    seasons = sorted({_season_no(a.get('season')) for a in arts if _season_no(a.get('season'))})
    targets = set(seasons[-2:])      # the season being played and the one that just ended
    out = []
    for a in arts:
        if _season_no(a.get('season')) not in targets or (a.get('regulation') not in (None, 'mc')):
            continue
        out.append(a)
    return out, targets


def load_article(a):
    url = f"https://pokesol.app/u/{a['author']['username']}/articles/{a['id']}"
    page = pokesol.fetch(url)
    root = pokesol._stream(page)['loaderData']['routes/u.$username.articles.$id']
    body = html.unescape(re.sub(r'<[^>]+>', ' ', str((root.get('article') or {}).get('body', ''))))
    t = pokesol.parse(page, url)
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


def study_team(t, depth):
    """All 60 orders x their likely selections, both sides `depth` turns ahead, one game each."""
    party = R.party_now()
    cp = os.path.join(OUT_D, t['id'] + '.json')
    if os.path.exists(cp):
        c = json.load(open(cp, encoding='utf-8'))
        if c.get('sig') == R.sig(party) and c.get('depth') == depth:
            return c
    B.KNOWN_TEAMS[:] = [x for x in B.KNOWN_TEAMS if x['id'] != t['id']] + [t]
    opp6 = [B._base(m['name']) for m in t['team']]
    trips = prep.opp_trips(t, opp6)
    jobs, meta = [], []
    for o in prep.all_orders():
        for pw, oos in trips:
            for oo in oos:
                jobs.append((o, oo, t['id'], zlib.crc32(repr((o, oo, 'study')).encode()), depth))
                meta.append((o, oo, pw / len(oos)))
    t0 = time.time()
    res = prep.pool_map(R.game, jobs)
    games = [{'order': o, 'opp': oo, 'w': w, 'res': r[0], 'faints': r[2]} for (o, oo, w), r in zip(meta, res)]
    st = R.team_stats(games)
    top = {r[3] for r in st['rows'][:10]}
    sel = {}
    for g in games:
        d = sel.setdefault(tuple(g['opp']), [0, 0, 0, 0])
        if tuple(g['order']) in top:
            d[0] += g['res'] == 1
            d[1] += 1
        d[2] += g['res'] == 1
        d[3] += 1
    hard = min(sel, key=lambda k: (sel[k][0] / max(1, sel[k][1]), sel[k][2] / sel[k][3]))
    avg = {r[3]: r[1] for r in st['rows']}           # weighted average over their selections
    vs_hard = {tuple(g['order']): g['res'] == 1 for g in games if tuple(g['opp']) == hard}
    best = max(vs_hard, key=lambda o: (vs_hard[o], avg[o]))
    ranked = sorted(vs_hard, key=lambda o: (-vs_hard[o], -avg[o]))
    c = {'sig': R.sig(party), 'depth': depth, 'games': len(games), 'seconds': round(time.time() - t0),
         'hardest': list(hard), 'hardest_rate_top10': round(sel[hard][0] / max(1, sel[hard][1]), 3),
         'hardest_rate_all': round(sel[hard][2] / sel[hard][3], 3),
         'best_vs_hardest': list(best), 'best_won_vs_hardest': vs_hard[best], 'best_avg': round(avg[best], 3),
         'alternatives': [{'order': list(o), 'won_vs_hardest': vs_hard[o], 'avg': round(avg[o], 3)} for o in ranked[1:5]],
         'date': now().strftime('%Y-%m-%d %H:%M')}
    os.makedirs(OUT_D, exist_ok=True)
    json.dump(c, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
    return c


def save(t, info, c):
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    old = next((x for x in data['teams'] if x['id'] == t['id']), None)
    if old:
        t['picks'] = old.get('picks', [])
        t['notes'] = old.get('notes', t.get('notes'))
    t['rating'] = {'rank': info[0], 'final': info[1], 'peak': info[2]}
    t['study'] = {k: v for k, v in c.items() if k != 'sig'}
    t['counter'] = {'order': c['best_vs_hardest'], 'score': c['best_avg'], 'worst': c['hardest_rate_top10'],
                    'alternatives': [{'order': a['order'], 'score': a['avg']} for a in c['alternatives']],
                    'mode': f"study.py: 全60通り×相手の想定選出・各1戦・両者{c['depth']}手読み（最も厳しい相手選出に最も善戦した選出）"}
    if old:
        data['teams'][data['teams'].index(old)] = t
    else:
        data['teams'].append(t)
    json.dump(data, open(prep.KNOWN_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def report():
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    rows = [t for t in data['teams'] if t.get('study')]
    rows.sort(key=lambda t: ((t.get('rating') or {}).get('rank') or 10 ** 6,
                             -max((t.get('rating') or {}).get('final') or 0, (t.get('rating') or {}).get('peak') or 0)))
    L = ['# 新着構築の学習（study.py が毎晩自動生成）', '',
         'pokesol の新着構築記事（シングル・該当シーズン・最終/到達レート2000以上。レートの記載がない場合は最終1000位以内）を、',
         'こちらの60通りの選出×相手の想定選出・各1戦・両者4手読みで対戦させた結果です。乱数あり。',
         '「最も厳しい相手選出」は、こちらが実際に出す上位10選出に最も勝つ相手選出。「最善の選出」はそれに最も善戦した選出、',
         '「平均勝率」はその選出の相手全選出への平均です。実戦では相手の6体が完全一致したときだけ参照します。', '',
         '| 構築 | 順位・レート | 最も厳しい相手選出（こちら上位10選出の勝率） | 最善の選出 | その選出の平均勝率 | 学習日 |',
         '|---|---|---|---|---|---|']
    for t in rows:
        r, s = t.get('rating') or {}, t['study']
        rr = ' '.join(x for x in [f"{r['rank']}位" if r.get('rank') else '', f"最終{r['final']}" if r.get('final') else '',
                                  f"最高{r['peak']}" if r.get('peak') else ''] if x)
        L.append(f"| [{t['title'][:30]}]({t['url']}) | {rr} | {' → '.join(s['hardest'])}（{s['hardest_rate_top10']:.0%}） | "
                 f"{' → '.join(s['best_vs_hardest'])}{'' if s['best_won_vs_hardest'] else '（勝てず）'} | {s['best_avg']:.0%} | {s['date'][:10]} |")
    open(REPORT_P, 'w', encoding='utf-8').write('\n'.join(L) + '\n')


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv[1:]
    until = a[a.index('--until') + 1] if '--until' in a else '07:00'
    if '--slot' in a:      # one run of the nightly routine: about two hours, never past 07:00
        until = min(now() + datetime.timedelta(minutes=110), now().replace(hour=7, minute=0, second=0, microsecond=0)
                     if now().hour < 7 else now() + datetime.timedelta(minutes=110)).strftime('%H:%M')
    depth = int(a[a.index('--depth') + 1]) if '--depth' in a else 4
    hh, mm = map(int, until.split(':'))
    end = now().replace(hour=hh, minute=mm, second=0, microsecond=0)
    if end < now():
        end += datetime.timedelta(days=1)
    R.teams()
    cands, targets = candidates()
    print(f'{len(cands)} articles of seasons {sorted(targets)}; until {end:%m-%d %H:%M}', flush=True)
    data = json.load(open(prep.KNOWN_P, encoding='utf-8'))
    have = {t['id']: t for t in data['teams'] if t.get('study')}
    todo = []
    for art in cands:
        if art['id'] in have and have[art['id']]['study'].get('depth') == depth:
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
    print('to study:', [(c['t']['title'][:24], c['rating']) for c in todo], flush=True)
    if '--dry' in a:
        return
    per = None
    if '--max' in a:
        todo = todo[:int(a[a.index('--max') + 1])]
    for c in todo:
        left = (end - now()).total_seconds()
        if per and left < per * 1.2:
            print('time is up', flush=True)
            break
        t0 = time.time()
        try:
            res = study_team(c['t'], depth)
        except Exception as e:
            import traceback
            print('error', c['t']['title'][:40], traceback.format_exc()[-600:], flush=True)
            continue
        per = max(per or 0, time.time() - t0)
        save(c['t'], c['rating'], res)
        report()
        print(f"{c['t']['title'][:30]}: 厳しい {' → '.join(res['hardest'])} / 最善 {' → '.join(res['best_vs_hardest'])} "
              f"平均 {res['best_avg']:.0%} ({res['seconds']}s)", flush=True)
    report()


if __name__ == '__main__':
    main()
