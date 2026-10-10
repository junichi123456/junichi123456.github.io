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
  game_events.jsonl  イベントごとに1行（seq つき）:
                     preview  選出画面が出た（image = 最初の1枚。選出はこの1枚で判断する）
                     start    選出画面が終わり対戦が始まった（相手の先発が出た時点、遅くとも20秒後）→ 1ターン目の判断
                     command  2ターン目以降の行動選択画面（ひんし後の交代画面を含む）
  game_NNNN_preview_KKK.png  選出画面の間も撮り続けた画像（文字が変わるたび／2秒ごと、最大120枚）
  frames/NNNN/KKKKK_時分秒.jpg  対戦開始（選出画面の終わり）から次の選出画面まで0.5秒ごとの画面
                     （NNNN は選出画面のイベント番号。直近3対戦分だけ残す。--record-every で間隔を変更）

対戦中の Claude は  python wait_event.py  をバックグラウンドで実行して待ち、終了通知を受けたら
イベントの画像を読んで判断する。ユーザーがチャットを送る必要はない。
"""
import argparse, base64, io, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import safeio  # noqa: E402
OUT = os.path.join(os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs')), 'live')

# 選出画面にいる間ずっと見えている文字（カーソルを動かして中央が詳細表示に変わっても残るもの）
PREVIEW_KEYS = ('選出してください', '匹選出', '戦うポケモンを', '選出完了', 'つよさの表示', '有利な相手', '不利な相手')
COMMAND_KEYS = ('たたかう', 'わざを選', '技を選', 'メガシンカ', 'ポケモン交代', 'にげる', 'こうさん')


def team_moves():
    try:
        sys.path.insert(0, HERE)
        from team import TEAM
        return {m for t in TEAM for m in t.moves}
    except Exception:
        return set()


MY_MOVES = team_moves()


class Detector:
    """Turns noisy per-frame classifications into one event per screen.

    - preview: once per team preview. Moving the cursor changes the centre panel (and can show our
      own move names), so while the preview is up nothing else is emitted. The preview ends only
      after it has been gone for PREVIEW_END seconds; a new preview needs PREVIEW_GAP seconds.
    - command: once per move-selection screen. The screen must be seen on CONFIRM consecutive
      frames, and the previous one must have been gone for COMMAND_RESET seconds (turn animation).
    - ended: set (for the caller) on the frame where the team preview is judged to be over.
    """
    CONFIRM, PREVIEW_END, PREVIEW_GAP, COMMAND_RESET = 2, 6.0, 100.0, 3.0
    START_TIMEOUT = 20.0     # 'start' at the latest this long after the preview is gone
    SKIP_WINDOW = 90.0       # the turn-1 command screen after 'start' is not reported again
    PREVIEW_SHOT_EVERY = 2.0  # seconds between preview recordings when nothing changes
    PREVIEW_SHOTS_MAX = 120

    def __init__(self):
        self.raw_prev, self.streak = None, 0
        self.in_preview, self.preview_seen, self.last_preview = False, 0.0, -1e9
        self.command_armed, self.command_off_since = True, None
        self.ended = False

    def update(self, raw, now):
        self.streak = self.streak + 1 if raw == self.raw_prev else 1
        self.raw_prev = raw
        if raw == 'preview':
            self.preview_seen = now
        if self.in_preview and now - self.preview_seen > self.PREVIEW_END:
            self.in_preview = False
            self.ended = True
        if raw == 'preview' and self.streak >= self.CONFIRM and not self.in_preview:
            self.in_preview = True
            if now - self.last_preview > self.PREVIEW_GAP:
                self.last_preview = now
                self.command_armed = True
                return 'preview'
            return None
        if self.in_preview:
            return None
        if raw == 'command':
            self.command_off_since = None
            if self.command_armed and self.streak >= self.CONFIRM:
                self.command_armed = False
                return 'command'
        else:
            if self.command_off_since is None:
                self.command_off_since = now
            if now - self.command_off_since >= self.COMMAND_RESET:
                self.command_armed = True
        return None


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


# ---------------------------------------------------------------- battle recording
class Recorder:
    """Saves a screenshot every `every` seconds while a battle is on (from the end of the team preview
    until the next preview), on its own thread and its own capture connection so OCR time does not slow it.
    Frames go to live/frames/<preview seq>/NNNNN.jpg; only the newest `keep` battles are kept."""

    def __init__(self, make_source, every=0.5, keep=3):
        import threading
        self.make_source, self.every, self.keep = make_source, every, keep
        self.dir, self.n = None, 0
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def begin(self, battle_seq):
        d = os.path.join(OUT, 'frames', f'{battle_seq:04d}')
        os.makedirs(d, exist_ok=True)
        with self.lock:
            self.dir, self.n = d, 0
        self._prune()

    def stop(self):
        with self.lock:
            self.dir = None

    def _prune(self):
        import shutil
        root = os.path.join(OUT, 'frames')
        try:
            ds = sorted(x for x in os.listdir(root) if x.isdigit())
        except OSError:
            return
        for x in ds[:-self.keep]:
            shutil.rmtree(os.path.join(root, x), ignore_errors=True)

    def _run(self):
        src = None
        nxt = time.time()
        while True:
            nxt += self.every
            with self.lock:
                d = self.dir
            if d is not None:
                try:
                    if src is None:
                        src = self.make_source()
                    img = src.grab()
                    with self.lock:
                        if self.dir == d:
                            self.n += 1
                            n = self.n
                        else:
                            n = None
                    if n is not None:
                        img.save(os.path.join(d, f'{n:05d}_{time.strftime("%H%M%S")}.jpg'), quality=80)
                except Exception:
                    src = None
            dt = nxt - time.time()
            if dt > 0:
                time.sleep(dt)
            else:
                nxt = time.time()


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
    ap.add_argument('--record-every', type=float, default=0.5,
                    help='対戦開始から次の選出画面まで、この秒数ごとに画面を保存（0で保存しない）')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    os.makedirs(OUT, exist_ok=True)
    def make_source():
        return WindowSource(a.window) if a.window else OBSSource(a.host, a.port, a.password, a.source)
    src = make_source()
    rec = Recorder(make_source, every=a.record_every) if a.record_every > 0 else None
    ocr = WinOCR()
    state_p = os.path.join(OUT, 'game_state.json')
    ev_p = os.path.join(OUT, 'game_events.jsonl')
    seq = 0
    try:
        seq = json.load(open(state_p, encoding='utf-8')).get('seq', 0)
    except Exception:
        pass
    det = Detector()
    import msgparse
    field_p = os.path.join(OUT, 'field_state.json')
    tracker = msgparse.FieldTracker(field_p)
    turn_lines, last_lines = [], set()
    start_wait = None          # time the preview ended, until the 'start' event is sent
    skip_command_until = 0.0   # the turn-1 command screen was already handled by 'start'
    preview_seq, preview_n, preview_last_t, preview_last_text = 0, 0, 0.0, None
    log_p = os.path.join(OUT, 'battle_messages.jsonl')
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
        safeio.replace(os.path.join(OUT, 'game.tmp.png'), os.path.join(OUT, 'game.png'))
        # collect battle messages shown between screens (new lines only, in order of appearance)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        new = [l for l in lines if l not in last_lines]
        last_lines = set(lines)
        if new and not det.in_preview:
            turn_lines.extend(new)
        now = time.time()
        event = det.update(phase, now)
        # keep recording the team preview (the pick uses only the first frame: the 'preview' event image)
        if det.in_preview and preview_seq and preview_n < det.PREVIEW_SHOTS_MAX and \
                (text != preview_last_text or now - preview_last_t >= det.PREVIEW_SHOT_EVERY):
            preview_n += 1
            preview_last_t, preview_last_text = now, text
            img.save(os.path.join(OUT, f'game_{preview_seq:04d}_preview_{preview_n:03d}.png'))
        if det.ended:
            det.ended = False
            if preview_seq:
                start_wait = now
                if rec:
                    rec.begin(preview_seq)
        if start_wait is not None and not det.in_preview:
            # first decision of the battle: as soon as the opponent's lead is out (or the first command screen)
            opp_out = any(sw.get('side') == 'opp' for sw in msgparse.parse_turn(turn_lines).get('switch', []))
            if event == 'command' or opp_out or now - start_wait > det.START_TIMEOUT:
                skip_command_until = 0.0 if event == 'command' else now + det.SKIP_WINDOW
                event = 'start'
                start_wait = None
        elif event == 'command' and now < skip_command_until:
            skip_command_until = 0.0
            event = None
            print(time.strftime('%Y-%m-%dT%H:%M:%S'), '1ターン目の行動選択画面（start で判断済み）')
        if event:
            phase = event
            seq += 1
            ts = time.strftime('%Y-%m-%dT%H:%M:%S')
            snap = os.path.join(OUT, f'game_{seq:04d}_{phase}.png')
            img.save(snap)
            ev = {'seq': seq, 'phase': phase, 'time': ts, 'image': snap, 'text': text}
            if phase in ('command', 'start'):
                # what happened since the previous decision: moves, stat changes, weather, items, ...
                turn = msgparse.parse_turn(turn_lines)
                tracker.apply(turn)
                ev['turn_events'] = {k: v for k, v in turn.items() if v}
                ev['field_state'] = field_p
                with open(log_p, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'seq': seq, 'time': ts, 'lines': turn_lines, 'parsed': ev['turn_events']},
                                       ensure_ascii=False) + '\n')
                turn_lines = []
            if phase == 'preview':
                preview_seq, preview_n, preview_last_t, preview_last_text = seq, 0, now, text
                if rec:
                    rec.stop()
                start_wait, skip_command_until = None, 0.0
                ev['preview_frames'] = os.path.join(OUT, f'game_{seq:04d}_preview_*.png')
                tracker = msgparse.FieldTracker(field_p)  # new battle
                tracker.save()
                turn_lines = []
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
        safeio.write_json(state_p, {'phase': phase, 'seq': seq, 'time': time.time(), 'text': text})
        time.sleep(max(0.0, a.interval - (time.time() - t0)))


if __name__ == '__main__':
    sys.exit(main())
