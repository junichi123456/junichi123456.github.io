"""ゲーム画面そのものを監視し、「選出画面」「技選択（行動決定）」を検出する。

PCBL のライブスキャンは選出画面を拾えないため、OBS が受け取っているゲーム映像を直接見る。
  - 映像: OBS WebSocket の GetSourceScreenshot（OBS 28 以降内蔵。PCBL と同じ WebSocket 設定でよい）
          取れない場合は --window でウィンドウ撮影（OBS のプロジェクター等）
  - 文字: Windows 標準 OCR（日本語）で画面の文字を読む

  pip install obsws-python winsdk pillow pygetwindow
  python game_watch.py --password <OBS WebSocketのパスワード> [--source "映像キャプチャデバイス"]

出力（../logs/live/）
  game.png         最新のゲーム画面
  game_state.json  {"phase": "preview"|"command"|"other", "seq": 連番, "time": ..., "text": OCR文字}
  game_events.jsonl  phase が preview / command に入るたびに1行（seq つき）

対戦中の Claude は  python wait_event.py  をバックグラウンドで実行して待ち、終了通知（=選出画面 or
自分の行動選択画面になった）を受けたら game.png を読んで判断する。ユーザーがチャットを送る必要はない。
"""
import argparse, base64, io, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs')), 'live')

PREVIEW_KEYS = ('選出してください', '匹選出', '戦うポケモンを')
COMMAND_KEYS = ('たたかう', 'わざを選', '技を選', 'メガシンカ', 'ポケモン交代', 'にげる', 'こうさん')


def team_moves():
    try:
        sys.path.insert(0, HERE)
        from team import TEAM
        return {m for t in TEAM for m in t.moves}
    except Exception:
        return set()


MY_MOVES = team_moves()


def classify(text):
    t = text.replace(' ', '').replace('\n', '')
    if any(k in t for k in PREVIEW_KEYS):
        return 'preview'
    hits = sum(1 for m in MY_MOVES if m in t)
    if hits >= 2 or any(k in t for k in COMMAND_KEYS):
        return 'command'
    return 'other'


# ---------------------------------------------------------------- frame sources
class OBSSource:
    def __init__(self, host, port, password, source):
        import obsws_python as obs
        self.cl = obs.ReqClient(host=host, port=port, password=password, timeout=3)
        self.source = source or self.cl.get_current_program_scene().current_program_scene_name

    def grab(self):
        from PIL import Image
        r = self.cl.get_source_screenshot(self.source, 'png', 1280, 720, -1)
        data = r.image_data.split(',', 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(data))).convert('RGB')


class WindowSource:
    def __init__(self, title):
        import pygetwindow as gw
        self.gw, self.title = gw, title

    def grab(self):
        from PIL import ImageGrab
        ws = [w for w in self.gw.getWindowsWithTitle(self.title) if w.width > 200]
        if not ws:
            raise RuntimeError(f'window not found: {self.title}')
        w = ws[0]
        return ImageGrab.grab(bbox=(w.left, w.top, w.right, w.bottom), all_screens=True)


# ---------------------------------------------------------------- OCR (Windows built-in)
class WinOCR:
    def __init__(self):
        import asyncio
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language
        self.asyncio = asyncio
        self.engine = OcrEngine.try_create_from_language(Language('ja')) or OcrEngine.try_create_from_user_profile_languages()
        if self.engine is None:
            raise RuntimeError('日本語OCRが使えません（Windowsの言語設定に日本語のOCRを追加してください）')

    def read(self, img):
        from winsdk.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
        from winsdk.windows.storage.streams import DataWriter
        rgba = img.convert('RGBA')
        w, h = rgba.size
        b = rgba.tobytes('raw', 'BGRA')
        dw = DataWriter()
        dw.write_bytes(b)
        sb = SoftwareBitmap.create_copy_from_buffer(dw.detach_buffer(), BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED)

        async def run():
            r = await self.engine.recognize_async(sb)
            return '\n'.join(line.text for line in r.lines)
        return self.asyncio.run(run())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='localhost')
    ap.add_argument('--port', type=int, default=4455)
    ap.add_argument('--password', default=os.environ.get('OBS_WS_PASSWORD', ''))
    ap.add_argument('--source', help='OBSのソース名またはシーン名（省略時は現在の番組シーン）')
    ap.add_argument('--window', help='OBSを使わずにこのタイトルのウィンドウを撮影する')
    ap.add_argument('--interval', type=float, default=0.7)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    os.makedirs(OUT, exist_ok=True)
    src = WindowSource(a.window) if a.window else OBSSource(a.host, a.port, a.password, a.source)
    ocr = WinOCR()
    state_p = os.path.join(OUT, 'game_state.json')
    ev_p = os.path.join(OUT, 'game_events.jsonl')
    seq = 0
    try:
        seq = json.load(open(state_p, encoding='utf-8')).get('seq', 0)
    except Exception:
        pass
    last_phase = None
    print(f'ゲーム画面の監視を開始 → {os.path.normpath(OUT)}  (Ctrl+C で終了)')
    while True:
        t0 = time.time()
        try:
            img = src.grab()
            text = ocr.read(img)
        except Exception as e:
            print('取得失敗:', e)
            time.sleep(2)
            continue
        phase = classify(text)
        img.save(os.path.join(OUT, 'game.tmp.png'))
        os.replace(os.path.join(OUT, 'game.tmp.png'), os.path.join(OUT, 'game.png'))
        if phase != last_phase and phase in ('preview', 'command'):
            seq += 1
            ts = time.strftime('%Y-%m-%dT%H:%M:%S')
            snap = os.path.join(OUT, f'game_{seq:04d}_{phase}.png')
            img.save(snap)
            ev = {'seq': seq, 'phase': phase, 'time': ts, 'image': snap, 'text': text}
            if phase == 'preview':
                # identify the opponent's six right away: type icons + reference sheet
                try:
                    import subprocess
                    sheet = os.path.join(OUT, f'game_{seq:04d}_identify.png')
                    r = subprocess.run([sys.executable, os.path.join(HERE, 'identify.py'), snap, '--out', sheet],
                                       capture_output=True, text=True, encoding='utf-8', timeout=20)
                    ev['identify'] = r.stdout
                    ev['identify_sheet'] = sheet
                except Exception as e:
                    ev['identify'] = f'identify failed: {e}'
            with open(ev_p, 'a', encoding='utf-8') as f:
                f.write(json.dumps(ev, ensure_ascii=False) + '\n')
            print(ts, '検出:', phase, f'#{seq}')
        last_phase = phase
        tmp = state_p + '.tmp'
        json.dump({'phase': phase, 'seq': seq, 'time': time.time(), 'text': text}, open(tmp, 'w', encoding='utf-8'),
                  ensure_ascii=False)
        os.replace(tmp, state_p)
        time.sleep(max(0.0, a.interval - (time.time() - t0)))


if __name__ == '__main__':
    sys.exit(main())
