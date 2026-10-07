"""Pokemon Champions Battle Logger (PCBL) のライブ画面を読み取り続ける。

PCBL が PC 上で表示している Live Scan 画面（既定 http://127.0.0.1:8000/live）をブラウザで開き、
表示されている文字とスクリーンショットを数秒おきに保存する。PCBL の内部データや通信は読まない
（人が画面を見るのと同じ情報だけを使う）。

  pip install playwright
  （Edge か Chrome が入っていればそれを使う。無ければ python -m playwright install chromium）
  python pcbl_watch.py [--url http://127.0.0.1:8000/live] [--interval 2]

出力（../logs/live/）:
  latest.txt     画面の文字（最新）
  latest.png     画面のスクリーンショット（最新）
  parsed.json    文字から拾ったポケモン名・HP%・ターン数（ヒューリスティック）
  stream.jsonl   変化があった時刻ごとの文字の履歴
"""
import argparse, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs')), 'live')


def load_names():
    names = set()
    for f in ('pokemon.json',):
        for p in json.load(open(os.path.join(HERE, 'data', f), encoding='utf-8')):
            names.add(p['ja'])
    try:
        names |= set(json.load(open(os.path.join(HERE, 'data', 'usage_sets.json'), encoding='utf-8')))
    except Exception:
        pass
    return sorted(names, key=len, reverse=True)


def load_moves():
    try:
        return sorted({m['ja'] for m in json.load(open(os.path.join(HERE, 'data', 'moves.json'), encoding='utf-8'))},
                      key=len, reverse=True)
    except Exception:
        return []


def parse(text, names, moves):
    """Pick out Pokémon names with nearby HP%, turn number and move names. Best effort."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    found = []
    for i, l in enumerate(lines):
        for n in names:
            if n in l:
                window = ' '.join(lines[i:i + 3])
                hp = re.search(r'(\d{1,3}(?:\.\d)?)\s*%', window)
                frac = re.search(r'(\d{1,3})\s*/\s*(\d{2,3})', window)
                found.append({'line': i, 'name': n, 'hp_pct': float(hp.group(1)) if hp else None,
                              'hp': [int(frac.group(1)), int(frac.group(2))] if frac else None, 'text': l})
                break
    turn = re.search(r'(?:ターン|Turn|TURN)\s*[:：]?\s*(\d+)', text)
    mv = []
    for l in lines:
        for m in moves:
            if len(m) >= 2 and m in l:
                mv.append({'move': m, 'text': l})
                break
    return {'turn': int(turn.group(1)) if turn else None, 'pokemon': found, 'moves': mv[-12:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:8000/live')
    ap.add_argument('--interval', type=float, default=2.0)
    ap.add_argument('--headed', action='store_true', help='ブラウザを表示する')
    ap.add_argument('--chrome', help='使うブラウザの実行ファイル（省略時は自動）')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('playwright が必要です: pip install playwright && python -m playwright install chromium')
        return 1
    os.makedirs(OUT, exist_ok=True)
    names, moves = load_names(), load_moves()
    last = None
    with sync_playwright() as p:
        b = None
        tries = [dict(executable_path=a.chrome)] if a.chrome else [{}, dict(channel='msedge'), dict(channel='chrome')]
        for kw in tries:  # bundled Chromium → installed Edge → installed Chrome
            try:
                b = p.chromium.launch(headless=not a.headed, **kw); break
            except Exception as e:
                err = e
        if b is None:
            print('ブラウザを起動できません:', err); return 1
        page = b.new_page(viewport={'width': 1600, 'height': 1000})
        while True:  # wait until PCBL is up
            try:
                page.goto(a.url, wait_until='domcontentloaded'); break
            except Exception as e:
                print(f'{a.url} に接続できません（PCBL が起動していない／URLが違う可能性）。5秒後に再試行します: {str(e).splitlines()[0]}')
                time.sleep(5)
        print(f'watching {a.url} → {os.path.normpath(OUT)}  (Ctrl+C で終了)')
        while True:
            try:
                text = page.inner_text('body')
            except Exception as e:
                print('読み取り失敗、再読み込みします:', e)
                time.sleep(a.interval)
                try:
                    page.goto(a.url, wait_until='domcontentloaded')
                except Exception:
                    pass
                continue
            if text != last:
                last = text
                ts = time.strftime('%Y-%m-%dT%H:%M:%S')
                open(os.path.join(OUT, 'latest.txt'), 'w', encoding='utf-8').write(text)
                try:
                    page.screenshot(path=os.path.join(OUT, 'latest.png'), full_page=True)
                except Exception:
                    pass
                parsed = parse(text, names, moves)
                parsed['time'] = ts
                json.dump(parsed, open(os.path.join(OUT, 'parsed.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                with open(os.path.join(OUT, 'stream.jsonl'), 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'time': ts, 'text': text}, ensure_ascii=False) + '\n')
                print(ts, 'updated', [x['name'] for x in parsed['pokemon']][:6])
            time.sleep(a.interval)


if __name__ == '__main__':
    sys.exit(main())
