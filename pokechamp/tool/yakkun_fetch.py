"""PCで動かす: ポケモン徹底攻略(yakkun.com)のパーティ掲示板から新着の構築記事を取得して保存する。

  python yakkun_fetch.py [--max N] [--pages N] [--push] [--headless]

クラウド（Claude Code on the web）からは Cloudflare に止められるため、普通のChromeが入ったPCで動かす。
1. data/regulation.json の現行シーズン範囲で一覧URLを組み立て、新着順に記事リンクを集める。
2. 保存済みの記事は飛ばし、新しい記事の本文を logs/study/yakkun/<id>.json に保存（最終レート2000以上／順位のみなら
   1000位以内だけ。study.py と同じ基準）。基準に届かない記事は index.json に「skip」と記録して再取得しない。
3. --push なら logs/study/yakkun だけをコミットして、現在のブランチへ push。
   取り込み（構築データ化・ガイド作成）はクラウド側で行う。最初の数件は構造確認用に生のHTMLを _samples/ に残す。
ブラウザはログイン済みChromeではなく専用プロファイル(logs/study/yakkun/_profile)を使う。確認画面が出たら90秒待つ
(出たままなら画面で手動で通す。通れば次回以降はクッキーで通りやすい)。
"""
import datetime, json, os, re, subprocess, sys, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import regulation  # noqa: E402

OUT = os.path.join(HERE, '..', 'logs', 'study', 'yakkun')
INDEX_P = os.path.join(OUT, 'index.json')
BASE = 'https://yakkun.com/bbs/party/list/'
JST = datetime.timezone(datetime.timedelta(hours=9))


def list_url(page=1):
    cfg = regulation.load()
    lo, hi = regulation.season_range(cfg)
    y = cfg.get('yakkun') or {}
    q = {'soft': y.get('soft', 4), 'min_season': lo, 'max_season': hi, 'rule': y.get('rule', 0), 'sort': 'new'}
    if page > 1:
        q['page'] = page
    return BASE + '?' + urllib.parse.urlencode(q)


def load_index():
    try:
        return json.load(open(INDEX_P, encoding='utf-8'))
    except Exception:
        return {}


def save_index(ix):
    os.makedirs(OUT, exist_ok=True)
    json.dump(ix, open(INDEX_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)


def wait_clear(pg, sec=90):
    """Cloudflareの確認画面が消えるのを待つ。"""
    for _ in range(sec):
        t = pg.title()
        if 'Just a moment' not in t and 'お待ちください' not in t:
            return True
        time.sleep(1)
    return False


def article_links(pg):
    hrefs = pg.eval_on_selector_all('a[href*="/bbs/party/"]', 'els => els.map(e => [e.href, e.innerText])')
    out, seen = [], set()
    for h, txt in hrefs:
        u = h.split('#')[0]
        path = urllib.parse.urlparse(u).path
        if '/list' in path or not re.search(r'\d', path.rstrip('/').split('/')[-1]):
            continue
        aid = re.sub(r'[^\w-]', '_', path.strip('/').split('bbs/party/')[-1])
        if aid and aid not in seen:
            seen.add(aid)
            out.append((aid, u, ' '.join((txt or '').split())))
    return out


def qualifies(title, body):
    try:
        import study
        return study.qualifies(*study.rating(title, body, None)), study.rating(title, body, None)
    except Exception as e:
        print('rating check unavailable:', e, flush=True)
        return True, None


def run(a):
    from playwright.sync_api import sync_playwright
    mx = int(a[a.index('--max') + 1]) if '--max' in a else 40
    pages = int(a[a.index('--pages') + 1]) if '--pages' in a else 5
    os.makedirs(os.path.join(OUT, '_samples'), exist_ok=True)
    ix = load_index()
    got = 0
    with sync_playwright() as p:
        kw = dict(user_data_dir=os.path.join(OUT, '_profile'), headless='--headless' in a, locale='ja-JP',
                  viewport={'width': 1280, 'height': 900})
        try:
            ctx = p.chromium.launch_persistent_context(channel='chrome', **kw)
        except Exception as e:
            print('Chrome not found, using bundled chromium:', str(e)[:80], flush=True)
            ctx = p.chromium.launch_persistent_context(**kw)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        for n in range(1, pages + 1):
            url = list_url(n)
            print('list', url, flush=True)
            pg.goto(url, wait_until='domcontentloaded', timeout=90000)
            if not wait_clear(pg):
                print('Cloudflareの確認画面を通れませんでした。開いたウィンドウで手動で通してください。', flush=True)
                break
            pg.wait_for_timeout(2500)
            if n == 1 or not os.path.exists(os.path.join(OUT, '_samples', 'list.html')):
                open(os.path.join(OUT, '_samples', 'list.html'), 'w', encoding='utf-8').write(pg.content())
            links = article_links(pg)
            new = [x for x in links if x[0] not in ix]
            print(f'  links {len(links)} / new {len(new)}', flush=True)
            if not links or not new:
                break
            for aid, u, lt in new:
                if got >= mx:
                    break
                try:
                    pg.goto(u, wait_until='domcontentloaded', timeout=90000)
                    if not wait_clear(pg, 60):
                        print('  blocked', u, flush=True)
                        continue
                    pg.wait_for_timeout(1500)
                    title = (pg.title() or lt).strip()
                    text = pg.inner_text('body')
                    alts = pg.eval_on_selector_all('img[alt]', 'els => els.map(e => e.alt).filter(x => x)')
                    ok, info = qualifies(title + ' ' + lt, text[:400])
                    row = {'url': u, 'title': title, 'list_text': lt, 'fetched': datetime.datetime.now(JST).isoformat(timespec='seconds')}
                    if ok:
                        row['status'] = 'saved'
                        json.dump({**row, 'rating': info, 'text': text[:20000], 'alts': alts[:200],
                                   'regulation': regulation.current()},
                                  open(os.path.join(OUT, aid + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
                        if len([f for f in os.listdir(os.path.join(OUT, '_samples')) if f != 'list.html']) < 3:
                            open(os.path.join(OUT, '_samples', aid + '.html'), 'w', encoding='utf-8').write(pg.content())
                    else:
                        row['status'] = 'skip'
                    ix[aid] = row
                    got += 1
                    print(' ', row['status'], title[:40], info, flush=True)
                    save_index(ix)
                except Exception as e:
                    print('  error', u, str(e)[:80], flush=True)
                time.sleep(3 + (got % 3))
            if got >= mx:
                break
        ctx.close()
    return got


def push():
    top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=HERE, capture_output=True, text=True).stdout.strip()
    br = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=top, capture_output=True, text=True).stdout.strip()
    rel = os.path.relpath(os.path.abspath(OUT), top)
    g = lambda *c: subprocess.run(['git', *c], cwd=top, capture_output=True, text=True)
    g('add', '--', rel)
    g('reset', '-q', '--', rel + '/_profile')
    if not g('diff', '--cached', '--name-only', '--', rel).stdout.strip():
        print('push: 変更なし')
        return
    r = g('commit', '-m', 'やっくん構築記事を取得', '--', rel)
    print(r.stdout[-200:], r.stderr[-200:])
    print(g('pull', '--rebase', '--autostash', 'origin', br).stderr[-200:])
    print(g('push', 'origin', br).stderr[-300:])


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv[1:]
    n = run(a)
    print('取得:', n, '件', flush=True)
    if '--push' in a and n:
        push()


if __name__ == '__main__':
    main()
