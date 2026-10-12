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
                     command  2ターン目以降の行動選択画面
                     replace  次に出すポケモンを選ぶ画面（自分のポケモンがひんしになった後、または
                              ボルトチェンジ・とんぼがえり等で交代するとき。replace_mode = faint / pivot）
  game_NNNN_preview_KKK.png  選出画面の間も撮り続けた画像（文字が変わるたび／2秒ごと、最大120枚）
  frames/NNNN/KKKKK_時分秒.jpg  対戦開始（選出画面の終わり）から次の選出画面まで0.5秒ごとの画面
                     （NNNN は選出画面のイベント番号。直近3対戦分だけ残す。--record-every で間隔を変更）

画面の判定（scene）: 文字を読まずに、色だけで0.15秒ごとに判定する。
  - 選出画面: 左上の自分の名前欄（紫）と右上の相手の名前欄（ピンク）が高い位置にある
  - 交代画面: 2つの名前欄が少し低い位置にある。「ポケモン」ボタンから開いたとき（直前に行動選択画面）は見ているだけ。
    それ以外（ひんし・ボルトチェンジ等の後に自然に出た）ときだけ replace を出す
  - 行動選択画面: 右下の「たたかう」「ポケモン」ボタン
  交代画面の上に出る「あめ状態」「トリックルーム状態」などは、メッセージで拾い損ねた天気・フィールドの補正に使う。

行動選択画面（start / command）では、画面の文字（場のポケモン・HP）と記録から battle.py auto --screen で
すぐに次の行動を計算し、このウィンドウに大きく表示して decision.json に書く（約5秒。--no-decide で無効）。
対戦中の Claude は  python wait_event.py  をバックグラウンドで実行して待ち、イベント（判断つき）を受け取る。
"""
import argparse, base64, io, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import safeio  # noqa: E402
OUT = os.path.join(os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs')), 'live')

# 選出画面にいる間ずっと見えている文字（カーソルを動かして中央が詳細表示に変わっても残るもの）
PREVIEW_KEYS = ('選出してください', '匹選出', '戦うポケモンを', '選出完了', '有利な相手', '不利な相手')
# 対戦中のステータス確認画面（「つよさの表示」「特性」「持ち物」も出る）を選出画面と取り違えない
IN_BATTLE_KEYS = ('COMMAND', '様子を見る', 'ログを見る', '能力補正', 'トリックルーム状態', 'フィールド状態')
REPLACE_KEYS = ('交代する', '繰り出す', '戦闘に出す', '次のポケモン', 'ポケモンを選', 'つよさの表示', 'ステータス')
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


PIVOT_MOVES = ('ボルトチェンジ', 'とんぼがえり', 'クイックターン', 'すてゼリフ', 'バトンタッチ', 'テレポート', 'しっぽきり',
               'さよならのあいさつ')


def _my_names():
    try:
        from team import TEAM
        import msgparse as _mp
        out = set()
        for m in TEAM:
            b = _mp.BASE.get(m.species, m.species)
            out.add(b)
            if b.endswith('ロトム'):
                out.add('ロトム')        # the game shows our ヒートロトム as 「ロトム」
        return out
    except Exception:
        return set()


MY_NAMES = _my_names()


def party_read(text):
    """Our party as listed on the switch-in screen, in order, with HP: [(name, 'cur/max'), ...]."""
    import re as _re
    out = []
    lines = [l.replace(' ', '') for l in text.splitlines() if l.strip()]
    for i, l in enumerate(lines):
        n = next((x for x in sorted(MY_NAMES, key=len, reverse=True) if x in l), None)
        if not n or any(n == o[0] for o in out):
            continue
        m = _re.search(r'(\d{1,3})[/／](\d{2,3})', ' '.join(lines[i:i + 2]))
        out.append((n, f'{m.group(1)}/{m.group(2)}' if m else None))
    return out


def is_party(text, bscore):
    """The screen listing our party to choose who comes in (after a faint or a U-turn type move, or when browsing):
    several of our names with 「cur/max」 HP, and no 「たたかう」/「ポケモン」 buttons."""
    import re as _re
    t = text.replace(' ', '')
    names = sum(1 for n in MY_NAMES if n in t)
    fracs = len(_re.findall(r'\d{1,3}[/／]\d{2,3}', t))
    return bscore < 0.5 and names >= 2 and fracs >= 2


def classify(text):
    t = text.replace(' ', '').replace('\n', '')
    if any(k in t for k in PREVIEW_KEYS) and not any(k in t for k in IN_BATTLE_KEYS):
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

    def grab(self, w=1280, h=720):
        from PIL import Image
        r = self.cl.get_source_screenshot(self.source, 'png', w, h, -1)
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


# ---------------------------------------------------------------- fast scene detection (no OCR)
def _disk(w, h, cx, cy, r):
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


_BTN = {}


def button_score(img):
    """How much the image looks like the move-selection screen: the 「たたかう」 and 「ポケモン」 buttons at the bottom
    right are one yellow-green and one purple disk (which one is yellow depends on the cursor). 0..1, >0.5 = the
    input screen (two recorded battles: input screens 0.7-0.8, everything else below 0.5)."""
    import numpy as np
    w, h = 240, 135
    if not _BTN:
        _BTN['a'] = _disk(w, h, 222.5, 88.75, 8)     # たたかう
        _BTN['b'] = _disk(w, h, 211.25, 116.25, 8)   # ポケモン
    f = np.asarray(img.convert('RGB').resize((w, h)), dtype=np.int16)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    yg = (r > 150) & (g > 180) & (b < 120)                      # the highlighted button
    pu = (b > 190) & (r < 200) & (b - g > 25)                    # the other button
    vi = (b > 110) & (b - r > 40) & (g < 90)                     # the emblem on the highlighted button
    wh = (r > 180) & (g > 180) & (b > 180)                       # icon / label on either button
    btn = yg | pu | vi | wh
    A, B = _BTN['a'], _BTN['b']
    if max(yg[A].mean(), yg[B].mean()) < 0.2:
        return 0.0
    return (btn[A].mean() + btn[B].mean()) / 2


def scene(img):
    """Which screen is up, from the player-name boxes only (no OCR). Our name is a violet pill at the top left,
    the opponent's a pink pill at the top right:
      - 'preview': both pills high (1080p: y~95-140; 「ランクバトル シングルバトル」 above them) = team preview
      - 'party'  : both pills lower (1080p: y~165-210) = the list to choose who comes in (after a faint, U-turn type
                   moves, or when browsing via 「ポケモン」)
      - 'command': the 「たたかう」/「ポケモン」 buttons (button_score)
      - None     : anything else (animation, messages, result screen)
    Checked on three recorded battles: every preview / party / command frame and no other frame."""
    import numpy as np
    f = np.asarray(img.convert('RGB').resize((240, 135)), dtype=np.int16)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    vio = ((b > 140) & (b - r > 50) & (b - g > 70) & (r > 50))[:, 24:58].mean(1)
    pink = ((r > 160) & (r - g > 90) & (b > 70) & (b < 150))[:, 197:228].mean(1)
    def band(row, lo, hi):        # a full band starting between rows lo..hi, with no band just above it
        ys = [y for y in range(lo, hi + 1) if row[y] > 0.8]
        return bool(ys) and row[max(0, ys[0] - 3)] <= 0.8
    if band(pink, 11, 13) and band(vio, 11, 13):
        return 'preview'
    if band(pink, 20, 23) and band(vio, 20, 23):
        return 'party'
    if button_score(img) > FastWatch.ON:
        return 'command'
    return None


class FastWatch:
    """Looks at a small screenshot several times a second (colours only, no OCR), so the screens that need an answer
    are known within ~0.3 s instead of waiting for the next full OCR pass:
      - onset: the move-selection screen (buttons) is up
      - forced: the party screen came up on its own (not opened from the move-selection screen), i.e. we must send a
        mon in: after a faint or our U-turn type move. Browsing via 「ポケモン」 comes straight from the buttons."""
    EVERY, ON, OFF = 0.15, 0.7, 0.5   # input screens score 0.77-0.87; the result screen reaches 0.61
    BROWSE = 1.5      # party screen within this many seconds after the buttons = opened from the command screen
    GAP = 4.0         # party screen gone this long = the episode is over

    def __init__(self, make_source, thread=True):
        import threading
        self.make_source, self.onset, self.wake = make_source, None, threading.Event()
        self.forced = None          # time a forced party screen appeared (cleared by the caller once handled)
        self.scene = None
        self._hits = self._miss = 0
        self._btn_t = self._party_t = -1e9
        self._party_hits, self._episode_forced = 0, False
        if thread:
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        src = None
        while True:
            t0 = time.time()
            try:
                src = src or self.make_source()
                img = src.grab(320, 180) if isinstance(src, OBSSource) else src.grab()
            except Exception:
                src, img = None, None
                time.sleep(1.0)
            self.step(img, time.time())
            time.sleep(max(0.0, self.EVERY - (time.time() - t0)))

    def step(self, img, now):
        try:
            v = button_score(img) if img is not None else 0.0
            sc = 'command' if v > self.ON else scene(img) if img is not None else None
        except Exception:
            v, sc = 0.0, None
        self.scene = sc
        if v > self.ON:
            self._btn_t = now
            self._hits, self._miss = self._hits + 1, 0
            if self._hits >= 2 and self.onset is None:
                self.onset = now
                self.wake.set()
        elif v < self.OFF:
            self._miss += 1
            if self._miss >= 3:
                self._hits, self.onset = 0, None
        if sc == 'party':
            if now - self._party_t > self.GAP:          # a new party-screen episode
                self._party_hits = 0
                self._episode_forced = now - self._btn_t > self.BROWSE
            self._party_t = now
            self._party_hits += 1
            if self._party_hits == 2 and self._episode_forced:
                self.forced = now
                self.wake.set()


FIELD_KEYS = ('boosts', 'status', 'cured', 'weather', 'weather_end', 'terrain', 'terrain_end', 'hazards', 'items', 'mega',
              'sub', 'sub_end', 'trick_room', 'trick_room_end', 'abilities')


class Speculator:
    """During the turn's animation (20-40 s) the HP panels keep showing both mons and their HP. When what they show
    is stable for two frames, the move for that position is computed ahead of time, so the answer is ready the
    moment the command screen appears (if nothing else changed: boosts, weather, status, items ...)."""

    def __init__(self, sec):
        self.sec = sec
        self.reset()

    def reset(self):
        self.key, self.stable, self.running, self.done, self.opp_team = None, 0, False, {}, None
        self.watch = None      # (key, seq, line shown) of the command screen now waiting for input

    def read(self, text):
        try:
            import battle as _B
            if self.opp_team is None:
                rec = json.load(open(os.path.join(OUT, '..', 'current.json'), encoding='utf-8'))
                self.opp_team = rec.get('opp_team') or None
            me, hp_me, opp, hp_opp = _B.screen_read(text, self.opp_team or [])
            return (me, hp_me, opp, hp_opp) if me and opp and hp_me is not None and hp_opp is not None else None
        except Exception:
            return None

    LEVELS = (5.0, 10.0, 20.0)     # keep reading the same position deeper while the animation lasts

    def feed(self, text):
        key = self.read(text)
        if key is None:
            return
        self.stable = self.stable + 1 if key == self.key else 1
        self.key = key
        have = self.done.get(key)
        nxt = next((x for x in self.LEVELS if not have or x > have[2]), None)
        if self.stable >= 2 and nxt and not self.running:
            self.start(key, nxt)

    def start(self, key, sec):
        import subprocess, threading
        self.running = True

        def run():
            me, hp_me, opp, hp_opp = key
            try:
                r = subprocess.run([sys.executable, os.path.join(HERE, 'battle.py'), 'auto', '--me', me, '--opp', opp,
                                    '--hp', str(hp_me), str(hp_opp), '--sec', str(sec)],
                                   capture_output=True, text=True, encoding='utf-8', timeout=sec + 25)
                out = (r.stdout or '').strip()
                line = next((l for l in out.splitlines() if l.startswith('次:')), None)
                if line:
                    self.done[key] = (line, out, sec)
                    w = self.watch
                    if w and w[0] == key and line != w[2]:      # the answer already shown changed with deeper reading
                        publish(w[1], line, out + f'\n（深読み{sec:.0f}秒で更新）', 0.0, update=True)
                        self.watch = (key, w[1], line)
            except Exception:
                pass
            self.running = False
            if key == self.key and (self.watch is None or self.watch[0] == key):
                nxt = next((x for x in self.LEVELS if x > sec), None)
                if nxt:
                    self.start(key, nxt)
        threading.Thread(target=run, daemon=True).start()

    def answer(self, text, turn):
        """The precomputed move for the command screen in `text`, or None (position differs or the field changed)."""
        if any(turn.get(k) for k in FIELD_KEYS):
            return None
        key = self.read(text)
        return self.done.get(key) if key else None

    def shown(self, text, seq, line):
        key = self.read(text)
        self.watch = (key, seq, line) if key else None
        if key and not self.running:          # keep deepening this position until the next screen
            have = self.done.get(key)
            nxt = next((x for x in self.LEVELS if not have or x > have[2]), None)
            if nxt:
                self.start(key, nxt)


def publish(seq, line, out, seconds, update=False):
    rec = {'seq': seq, 'decision': line, 'full': out, 'seconds': round(seconds, 1), 'time': time.time(),
           'update': update, 'precomputed': '先読み済み' in (out or '')}
    try:
        safeio.write_json(os.path.join(OUT, 'decision.json'), rec)
        with open(os.path.join(OUT, 'decisions.jsonl'), 'a', encoding='utf-8') as f:   # every answer, for review
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass
    bar = '=' * 44
    print(f'\n{bar}\n  #{seq} {"（更新）" if update else ""}{line}   （{seconds:.1f}秒）\n{bar}\n', flush=True)


def decide_async(seq, sec, phase='command', party=None):
    """The move for this command screen, computed right away from the screen text (who is out, both HPs) and the
    tracked field: battle.py auto --screen. Printed here in big letters and written to decision.json, so the answer is
    there about 5 seconds after the screen appears, before anyone reads the image."""
    import subprocess, threading

    def run():
        t0 = time.time()
        try:
            args = ['auto', '--sec', str(sec)] + (['--screen'] if phase not in ('replace', 'pivot') else []) + \
                (['--switch'] if phase == 'pivot' else []) + \
                (['--party', ','.join(f'{n}={hp or ""}' for n, hp in party)] if party else [])
            r = subprocess.run([sys.executable, os.path.join(HERE, 'battle.py')] + args,
                               capture_output=True, text=True, encoding='utf-8', timeout=sec + 25)
            out = (r.stdout or '').strip() or (r.stderr or '').strip()[-300:]
        except Exception as e:
            out = f'判断に失敗: {e}'
        line = next((l for l in out.splitlines() if l.startswith('次:')), out.splitlines()[0] if out else '')
        publish(seq, line, out, time.time() - t0)
    threading.Thread(target=run, daemon=True).start()


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
    ap.add_argument('--decide-sec', type=float, default=5.0, help='行動選択画面で自動判断する探索秒数')
    ap.add_argument('--no-decide', action='store_true', help='行動選択画面での自動判断をしない')
    ap.add_argument('--no-fast', action='store_true', help='ボタンの色による行動選択画面の高速検出をしない')
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
    spec = Speculator(a.decide_sec)
    fast = FastWatch(make_source) if not a.no_fast else None
    import msgparse
    field_p = os.path.join(OUT, 'field_state.json')
    tracker = msgparse.FieldTracker(field_p)
    turn_lines, last_lines = [], set()
    last_command_t = 0.0
    pending_pivot, pivot_done, replace_mode = None, set(), 'faint'
    pending_replace, replace_done = None, set()
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
        try:
            bscore = button_score(img)
        except Exception:
            bscore = 1.0
        try:
            sc = scene(img)
        except Exception:
            sc = None
        if sc == 'preview' and phase != 'preview':
            phase = 'preview'          # the name boxes are at the team-preview position even if the OCR missed the text
        party = sc == 'party' or is_party(text, bscore)
        if party and preview_seq and not det.in_preview and tracker.observe_bar(text):
            tracker.save()             # 「あめ状態」 etc. on the party screen: weather / terrain the messages missed
        if phase == 'command' and party:
            phase = 'party'            # the switch-in list also shows move names: it is not the move-selection screen
        if fast and fast.onset and phase == 'other' and not det.in_preview and preview_seq:
            phase = 'command'          # the buttons are up: the OCR text may still lag behind
        img.save(os.path.join(OUT, 'game.tmp.png'))
        safeio.replace(os.path.join(OUT, 'game.tmp.png'), os.path.join(OUT, 'game.png'))
        # collect battle messages shown between screens (new lines only, in order of appearance)
        lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().endswith('状態')]
        new = [l for l in lines if l not in last_lines]
        last_lines = set(lines)
        if new and not det.in_preview:
            turn_lines.extend(new)
            if preview_seq:
                cur_turn = msgparse.parse_turn(turn_lines)
                for f in cur_turn['faint']:
                    if f['side'] == 'me' and f['mon'] not in replace_done and not pending_replace:
                        pending_replace = (time.time(), f['mon'])
                for mv in cur_turn['moves']:
                    key = ('pivot', len(turn_lines), mv['mon'])
                    if mv['side'] == 'me' and mv['move'] in PIVOT_MOVES and not pending_pivot and \
                            mv['mon'] not in pivot_done:
                        pending_pivot = time.time()
                        pivot_done.add(mv['mon'])
        now = time.time()
        if not det.in_preview and preview_seq and not a.no_decide and phase != 'command':
            spec.feed(text)            # HP panels during the animation: compute the next move ahead of time
        event = det.update(phase, now)
        if event is None and fast and fast.onset and det.command_armed and not det.in_preview and preview_seq:
            event, det.command_armed = 'command', False      # the button watcher is sure enough on its own
        if event == 'command' and not turn_lines and now - last_command_t < 60:
            event = None       # back on the same input screen after looking at the log / party: not a new turn
        if fast and fast.forced:
            # the party screen came up by itself (not from the 「ポケモン」 button): a mon must be sent in
            if event is None and not det.in_preview and preview_seq:
                event, replace_mode = 'replace', 'pivot' if pending_pivot else 'faint'
                if pending_replace:
                    replace_done.add(pending_replace[1])
                pending_pivot, pending_replace = None, None
            fast.forced = None
        if pending_pivot and event is None and party and not det.in_preview and not fast:
            event, pending_pivot, replace_mode = 'replace', None, 'pivot'    # choose who comes in after our U-turn
        if pending_pivot and now - pending_pivot > 30:
            pending_pivot = None       # the move failed / missed: no party screen came
        if pending_replace and event is None and phase != 'command' and not det.in_preview and not fast and \
                (party or any(k in text.replace(' ', '') for k in REPLACE_KEYS) or now - pending_replace[0] > 2.5):
            replace_mode = 'faint'
            # our mon fainted: the screen to send the next one (no command screen comes before it)
            event = 'replace'
            replace_done.add(pending_replace[1])
            pending_replace = None
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
            ev = {'seq': seq, 'phase': phase, 'time': ts, 'image': snap, 'text': text, 't': now,
                  'screen_onset': fast.onset if fast else None}
            if phase in ('command', 'start', 'replace'):
                last_command_t = now
                if phase != 'replace':
                    pivot_done, pending_pivot, pending_replace = set(), None, None    # a new turn: our pivot move may be used again
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
                spec.reset()
                pending_replace, replace_done = None, set()
                tracker.save()
                turn_lines = []
                # pictures seen in earlier battles: slots matching the memory are named at once
                try:
                    import sprites as _sp
                    sm = _sp.match(img)
                    sure = _sp.confident(sm)
                    ev['sprite_match'] = [{'slot': i + 1, 'name': n, 'top': [(nm, round(sc, 2)) for sc, nm in m]}
                                          for i, (n, m) in enumerate(zip(sure, sm))]
                    if all(sure):
                        import subprocess
                        r = subprocess.run([sys.executable, os.path.join(HERE, 'battle.py'), 'select'] + sure + ['--no-remember'],
                                           capture_output=True, text=True, encoding='utf-8', timeout=60)
                        ev['auto_select'] = {'six': sure, 'out': (r.stdout or '').strip()}
                        line = next((l for l in (r.stdout or '').splitlines() if l.startswith('選出順')), '')
                        bar = '=' * 44
                        print(f'\n{bar}\n  相手: {" ".join(sure)}（記憶から特定）\n  {line}\n{bar}\n', flush=True)
                except Exception as e:
                    ev['sprite_match'] = f'sprite match failed: {e}'
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
            if phase in ('command', 'start', 'replace') and not a.no_decide:
                pre = spec.answer(text, ev.get('turn_events') or {}) if phase == 'command' else None
                if pre:
                    publish(seq, pre[0], pre[1] + f'\n（演出中に先読み済み・{pre[2]:.0f}秒読み）', 0.0)
                    spec.shown(text, seq, pre[0])
                else:
                    decide_async(seq, a.decide_sec, 'pivot' if phase == 'replace' and replace_mode == 'pivot' else phase,
                                 party_read(text) if phase == 'replace' else None)
                ev['replace_mode'] = replace_mode if phase == 'replace' else None
        safeio.write_json(state_p, {'phase': phase, 'seq': seq, 'time': time.time(), 'text': text})
        if fast:
            fast.wake.clear()
            fast.wake.wait(max(0.0, a.interval - (time.time() - t0)))   # the button watcher can wake us early
        else:
            time.sleep(max(0.0, a.interval - (time.time() - t0)))


if __name__ == '__main__':
    sys.exit(main())
