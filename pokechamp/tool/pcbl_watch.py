"""Pokemon Champions Battle Logger (PCBL) のライブ画面を読み取り続ける。

■ ウィンドウ版（PCBL の Live Scan が専用ウィンドウで動いている場合）
  pip install pillow pygetwindow
  python pcbl_watch.py --list                      ウィンドウ一覧を表示
  python pcbl_watch.py --window "Champions"        タイトルにこの文字を含むウィンドウを2秒おきに撮影
  → ../logs/live/latest.png（最新の画面）と shots/ に変化があった時の画像を保存。
    対戦中の Claude はこの画像を見て状況を読む。

■ ブラウザ版（http://127.0.0.1:8000/live で表示される場合）

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


def _dpi_aware():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def list_windows():
    import pygetwindow as gw
    for w in gw.getAllWindows():
        if w.title.strip() and w.width > 200:
            print(f'{w.title}  ({w.width}x{w.height})')


def grab_background(hwnd, w, h):
    """Capture a window even when other windows cover it (Win32 PrintWindow). Returns PIL image or None."""
    try:
        import ctypes
        from ctypes import wintypes
        from PIL import Image
        u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
        hdc = u32.GetWindowDC(hwnd)
        mdc = g32.CreateCompatibleDC(hdc)
        bmp = g32.CreateCompatibleBitmap(hdc, w, h)
        g32.SelectObject(mdc, bmp)
        ok = u32.PrintWindow(hwnd, mdc, 2)  # PW_RENDERFULLCONTENT

        class BMI(ctypes.Structure):
            _fields_ = [('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
                        ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                        ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                        ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]
        bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
        g32.DeleteObject(bmp); g32.DeleteDC(mdc); u32.ReleaseDC(hwnd, hdc)
        if not ok:
            return None
        img = Image.frombuffer('RGB', (w, h), buf, 'raw', 'BGRX', 0, 1)
        if img.convert('L').getextrema()[1] < 10:  # all black → not supported by this window
            return None
        return img
    except Exception:
        return None


def watch_window(title, interval, background=False):
    """Capture the PCBL window by title every `interval` seconds; keep images that changed."""
    _dpi_aware()
    import pygetwindow as gw
    from PIL import ImageGrab, ImageChops
    shots = os.path.join(OUT, 'shots')
    os.makedirs(shots, exist_ok=True)
    last = None
    print(f'「{title}」を含むウィンドウを撮影します → {os.path.normpath(OUT)}  (Ctrl+C で終了)')
    while True:
        wins = [w for w in gw.getWindowsWithTitle(title) if w.width > 200 and w.height > 200]
        if not wins:
            print(f'「{title}」を含むウィンドウが見つかりません。--list でタイトルを確認してください。5秒後に再試行')
            time.sleep(5); continue
        w = wins[0]
        if w.isMinimized:
            print('ウィンドウが最小化されています。表示してください'); time.sleep(3); continue
        img = grab_background(w._hWnd, w.width, w.height) if background else None
        if background and img is None and not getattr(watch_window, '_warned', False):
            print('背面キャプチャに失敗したため通常の画面撮影に切り替えます（PCBLを前面に出してください）')
            watch_window._warned = True
        try:
            if img is None:
                img = ImageGrab.grab(bbox=(w.left, w.top, w.right, w.bottom), all_screens=True)
        except Exception as e:
            print('撮影失敗:', e); time.sleep(interval); continue
        small = img.convert('L').resize((160, 90))
        changed = last is None or ImageChops.difference(small, last).getbbox() is not None and \
            sum(ImageChops.difference(small, last).histogram()[16:]) > 40
        if changed:
            last = small
            ts = time.strftime('%Y%m%d-%H%M%S')
            img.save(os.path.join(OUT, 'latest.png'))
            img.save(os.path.join(shots, f'{ts}.png'))
            json.dump({'time': ts, 'window': w.title, 'size': [w.width, w.height]},
                      open(os.path.join(OUT, 'latest.json'), 'w', encoding='utf-8'), ensure_ascii=False)
            print(ts, 'updated')
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:8000/live')
    ap.add_argument('--interval', type=float, default=2.0)
    ap.add_argument('--headed', action='store_true', help='ブラウザを表示する')
    ap.add_argument('--chrome', help='使うブラウザの実行ファイル（省略時は自動）')
    ap.add_argument('--window', help='PCBL のウィンドウタイトルの一部（ウィンドウ版）')
    ap.add_argument('--list', action='store_true', help='ウィンドウ一覧を表示')
    ap.add_argument('--background', action='store_true', help='他のウィンドウに隠れていても撮影する（Win32 PrintWindow）')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    os.makedirs(OUT, exist_ok=True)
    if a.list or a.window:
        try:
            import pygetwindow  # noqa
            from PIL import ImageGrab  # noqa
        except ImportError:
            print('pip install pillow pygetwindow を実行してください'); return 1
        if a.list:
            list_windows(); return 0
        try:
            watch_window(a.window, a.interval, a.background)
        except KeyboardInterrupt:
            return 0
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
