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

メッセージの記録（MsgWatch）: 画面下のメッセージ欄と、左下（自分: 実数HP）・右上（相手: %）のHP欄だけを
0.25秒ごとに読み（メッセージは白い文字だけを白黒にしてOCR、名前と技はこの対戦の12体とその技に絞って照合。
HPの数字は斜体の0〜9の形を登録したテンプレートで読む: hpdigits.py）、
HP欄のアイコンと名前も見て、名前が同じでアイコンが変わったらメガシンカ／フォルムチェンジ、名前が変わったら交代と
判断する（メッセージを取りこぼしても分かる）。すべてのメッセージを出た順に1回ずつ記録する（messages.jsonl。1つのメッセージは1.3〜2.6秒しか出ない）。
メッセージとその時のHPを並べて、技ごとのダメージ（連続技の回数・急所込み）を持ち物・天気・状態異常・特性による
増減と分けて切り出し（battle_messages.jsonl の damage）、相手の型（持ち物・性格・能力）の推定に使う。--no-msg で無効。

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


# where things are on the 16:9 battle screen (fractions of width / height; from 1920x1080 captures)
MSG_BOX = (0.13, 0.72, 0.87, 0.87)        # the battle message box (bottom centre)
OPP_PANEL = (0.70, 0.0, 1.0, 0.19)        # opponent's name + HP %  (top right)
MY_PANEL = (0.0, 0.82, 0.30, 1.0)         # our name + HP cur/max   (bottom left)


def _crop(img, box):
    W, H = img.size
    return img.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)))


def _sig(img, w=48, h=12):
    import numpy as np
    return np.asarray(img.convert('L').resize((w, h)), dtype=np.int16)


def _changed(a, b, th=10.0):
    return a is None or b is None or float(abs(a - b).mean()) > th


def text_mask(img, scale=2):
    """White game text (with its dark outline) as black on white, enlarged: what OCR reads well. Without this the
    animated background behind the message box makes the OCR drop and swap characters."""
    import numpy as np
    from PIL import Image as _I
    f = np.asarray(img.convert('RGB'), dtype=np.int16)
    mn, mx = f.min(2), f.max(2)
    m = (mn > 185) & (mx - mn < 60)
    out = _I.fromarray(np.where(m, 0, 255).astype(np.uint8)).convert('RGB')
    return out.resize((out.width * scale, out.height * scale))


def panel_present(img, side):
    """The HP panel is up: the opponent's has a pink name bar, ours a violet one."""
    import numpy as np
    f = np.asarray(img.convert('RGB').resize((60, 20)), dtype=np.int16)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    if side == 'opp':
        m = (r > 160) & (r - g > 90) & (b > 70) & (b < 150)
    else:
        m = (b > 140) & (b - r > 50) & (b - g > 70) & (r > 50)
    return m.mean() > 0.04


# where the HP bar is inside each panel crop (fractions of the crop): x from, x to, rows searched
BAR = {'opp': (0.466, 0.866, 0.50, 0.68), 'me': (0.322, 0.708, 0.50, 0.68)}


def bar_pct(panel, side='opp'):
    g = bar_geom(panel, side)
    return g[0] if g else None


def bar_geom(panel, side='opp'):
    """HP % from the length of the HP bar in a panel crop (no OCR: the italic digits read badly). The bar is a
    coloured fill (green / yellow / red) followed by the grey empty part, at a fixed place in the panel.
    None if the bar is not where it should be (panel sliding in, covered ...)."""
    import numpy as np
    f = np.asarray(panel.convert('RGB'), dtype=np.int16)
    H, W = f.shape[:2]
    x0, x1, y0, y1 = BAR[side]
    X0, X1 = int(W * x0), int(W * x1)
    L = X1 - X0
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    mx, mn = f.max(2), f.min(2)
    fill = ((g > 180) & (b < 130) & (r < 250) & (g > r - 10)) | ((r > 215) & (g > 130) & (g < 205) & (b < 70)) | \
           ((r > 200) & (g < 70) & (b < 100))
    empty = (mx - mn < 28) & (mn > 35) & (mx < 100)
    vals = []
    for y in range(int(H * y0), int(H * y1)):
        fr, er = fill[y], empty[y]
        # the run must start at the bar's left end and reach its right end
        lo = max(1, X0 - L // 12)
        for start in range(lo, X0 + L // 12):
            if not (fr[start] or er[start]) or (fr[start - 1] or er[start - 1]) and start > lo:
                continue
            x, nf, ne, gap, last_e = start, 0, 0, 0, False
            while x < W and gap <= 2:
                if fr[x] and not last_e:
                    nf, gap = nf + 1, 0
                elif er[x]:
                    ne, gap, last_e = ne + 1, 0, True
                else:
                    gap += 1
                x += 1
            n = nf + ne
            if abs(n - L) <= L * 0.08:
                vals.append((nf / n, start))
                break
    if len(vals) < 2:
        return None
    vals.sort()
    starts = sorted(v[1] for v in vals)
    # (HP %, how far the panel sits from its usual place, as a fraction of the crop width)
    return round(100 * vals[len(vals) // 2][0], 1), (starts[len(starts) // 2] - X0) / W


# the mon's picture and name inside each panel crop (fractions of the crop): x from, y from, x to, y to
ICON = {'opp': (0.30, 0.22, 0.44, 0.72), 'me': (0.12, 0.32, 0.27, 0.76)}
PNAME = {'opp': (0.42, 0.21, 0.80, 0.48), 'me': (0.20, 0.24, 0.62, 0.44)}


def _frac_crop(img, box, dx=0.0):
    W, H = img.size
    return img.crop((int((box[0] + dx) * W), int(box[1] * H), int((box[2] + dx) * W), int(box[3] * H)))


def icon_feature(panel, side, dx=0.0):
    """The panel's picture of the mon as a unit vector (panel colour masked out). It follows the current form:
    a mega evolution or a form change (イルカマン, ギルガルド, ...) changes it while the name stays."""
    import numpy as np
    a = np.asarray(_frac_crop(panel, ICON[side], dx).convert('RGB').resize((20, 24)), dtype=np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    if side == 'opp':
        bg = (r > 110) & (r - g > 60) & (b - g > 20)                 # pink (bright or dim)
    else:
        bg = (b > 90) & (b - r > 30) & (b - g > 40)                   # violet (bright when selected, dim otherwise)
    bg |= (a.max(2) < 40)                                              # dark outline / outside
    bg |= (g > 180) & (b < 90) & (r < 215)                             # the yellow-green glow of the selected panel
    a[bg] = 0.0
    v = a.reshape(-1, 3)
    fg = ~bg.reshape(-1)
    if fg.sum() < 30:
        return None
    v = v - v[fg].mean(axis=0)
    v[~fg] = 0.0
    v = v.reshape(-1)
    n = float(np.linalg.norm(v))
    return v / n if n else None


def icon_sim(a, b):
    import numpy as np
    return float(np.dot(a, b)) if a is not None and b is not None else None


class MsgWatch:
    """Reads only the message box and the two HP panels, 4 times a second, so that every battle message is
    recorded once and in order (each stays up only ~1.3-2.6 s) together with the HP shown at that moment.
    HP is read from the panels' digits by templates of the italic digits (hpdigits.py), not by OCR.
    A move's damage is then known exactly (msgparse.damage_events): multi-hit counts, criticals, and what
    items / weather / status / abilities took or gave back are kept apart from it.

    take() returns the new entries since the last call: {'t', 'msg'} or {'t', 'side', 'hp', 'max'?}."""
    EVERY = 0.25

    def __init__(self, make_source, ocr_factory, log_path=None, skip=None):
        import threading
        self.make_source, self.ocr_factory, self.log_path = make_source, ocr_factory, log_path
        self.skip = skip or (lambda: False)     # True while the move list / party screen covers the message box
        self.lock = threading.Lock()
        self.new, self.alive, self.errors = [], False, 0
        self.last_msg, self.gap, self.last_entry, self.last_t = None, True, None, -1e9
        self._sig = {'msg': None, 'opp': None, 'me': None}
        self._hp = {'opp': None, 'me': None}
        self._shown = {}
        self._icon, self._iname, self._ipend, self._itry = {}, {}, {}, {}
        threading.Thread(target=self._run, daemon=True).start()

    def take(self):
        with self.lock:
            out, self.new = self.new, []
        return out

    def _emit(self, e):
        with self.lock:
            self.new.append(e)
        if self.log_path:
            try:
                with open(self.log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(e, ensure_ascii=False) + '\n')
            except Exception:
                pass

    def add_msg(self, text, now):
        """One OCR read of the message box. Messages appear over several reads (and the text may still be typing
        out): a read that continues / nearly equals the previous one updates it instead of adding a message.
        The same text again within 3 s (a noisy read in between) is still the same message."""
        import difflib, re
        import msgparse as _mp
        if not _mp.is_message(text):
            self.gap = True        # box empty (or noise / menus): the next text is a new message even if the same
            return
        shown = ' '.join(text.split())
        import re as _re
        m_end = _re.search(r'.{5,}?[/!！]', shown)      # a message is one sentence ending in 「！」 (read as / or !)
        if m_end:
            shown = shown[:m_end.end()]      # drop noise read after the end of the message
        t = _mp.norm(shown)
        last = self.last_msg
        near = not self.gap or now - self.last_t < 3.0
        if last and near and (t == last or t.startswith(last) or last.startswith(t) or
                              difflib.SequenceMatcher(None, t, last).ratio() >= 0.75):
            if len(t) > len(last) and self.last_entry is not None:
                self.last_entry['msg'] = shown
                self.last_msg = t
                self._emit({'t': now, 'msg_update': shown})
            self.gap, self.last_t = False, now
            return
        e = {'t': now, 'msg': shown}
        self.last_msg, self.gap, self.last_entry, self.last_t = t, False, e, now
        self._emit(e)

    def add_panel(self, side, v, now):
        """HP shown on a panel (hpdigits): theirs in %, ours as (cur, max)."""
        if v is None:
            return
        e = {'t': now, 'side': side, 'hp': v} if side == 'opp' else {'t': now, 'side': side, 'hp': v[0], 'max': v[1]}
        if self._hp[side] != e['hp']:
            self._hp[side] = e['hp']
            self._emit(e)

    CHANGED, SAME = 0.45, 0.6     # picture similarity: same mon 0.6-1.0, another mon / another form <= 0.35

    def panel_name(self, side, pc, ocr, dx=0.0):
        import msgparse as _mp
        try:
            from PIL import Image as _I
            m = text_mask(_frac_crop(pc, PNAME[side], dx), 3)
            W, H = m.size
            k = 0.2              # the name is in italics: lean it back upright, the OCR reads it much better
            m = m.transform((W + int(H * k), H), _I.AFFINE, (1, -k, 0, 0, 1, 0), fillcolor='white')
            t = ocr.read(m)
            return _mp.find_name(_mp.norm(t))
        except Exception:
            return None

    def watch_icon(self, side, pc, ocr, now, dx=0.0):
        """Compare the panel's picture with the one seen before. A different picture with the same name = the mon
        changed its form (mega evolution, イルカマン, ...): {'side', 'form_change': name}. A different name = another
        mon came in: {'side', 'switch_seen': name}. Both are known even if the message was missed."""
        f = icon_feature(pc, side, dx)
        if f is None:
            return
        ref = self._icon.get(side)
        if ref is None:
            self._icon[side], self._iname[side], self._ipend[side] = f, self.panel_name(side, pc, ocr, dx), 0
            return
        sim = icon_sim(f, ref)
        if sim >= self.SAME:
            self._ipend[side] = 0
            if self._iname.get(side) is None and now - self._itry.get(side, -9) >= 1.0:
                self._itry[side] = now                      # the name was not read yet: try again
                self._iname[side] = self.panel_name(side, pc, ocr)
            return
        if sim >= self.CHANGED:
            return
        self._ipend[side] = self._ipend.get(side, 0) + 1
        if self._ipend[side] < 3:
            return                                  # 3 times in a row: not a flash of an animation
        name = self.panel_name(side, pc, ocr)
        old = self._iname.get(side)
        self._icon[side], self._ipend[side] = f, 0
        if name and old and name == old:
            self._emit({'t': now, 'side': side, 'form_change': name})     # same mon, other picture
        elif name and name != old:
            self._emit({'t': now, 'side': side, 'switch_seen': name})
        else:
            self._emit({'t': now, 'side': side, 'icon_change': True})     # name not read: not decided
        self._iname[side] = name

    def step(self, img, ocr, now):
        msg = _crop(img, MSG_BOX)
        if self.skip():
            self.gap = True
        else:
            # read again whenever the white text in the box changed (the background moves all the time)
            import numpy as np
            f = np.asarray(msg.convert('RGB'), dtype=np.int16)
            w = (f.min(2) > 185) & (f.max(2) - f.min(2) < 60)
            H, W = (w.shape[0] // 6) * 6, (w.shape[1] // 6) * 6
            m = w[:H, :W].reshape(H // 6, 6, W // 6, 6).any(axis=(1, 3))     # 6x6 blocks with any text pixel
            prev = self._sig['msg']
            if not m.any():
                self.gap = True
            elif prev is None or prev.shape != m.shape or (m ^ prev).mean() > 0.01:
                self.add_msg(ocr.read(text_mask(msg, 2 if msg.width < 1400 else 1)), now)
            self._sig['msg'] = m
        for side, box in (('opp', OPP_PANEL), ('me', MY_PANEL)):
            pc = _crop(img, box)
            if not panel_present(pc, side):
                if self._shown.get(side):
                    self._shown[side] = False
                    self._emit({'t': now, 'side': side, 'gone': True})   # (a reading just before may be mid-drain)
                continue
            self._shown[side] = True
            sg = _sig(pc)
            if _changed(sg, self._sig[side], 3.0):
                self._sig[side] = sg
                import hpdigits
                self.add_panel(side, hpdigits.read_hp(pc, side), now)
            g = bar_geom(pc, side)
            if g is not None:       # the panel is in place (not sliding in); g[1]: its shift (highlighted or not)
                self.watch_icon(side, pc, ocr, now)

    def _run(self):
        src = ocr = None
        while True:
            t0 = time.time()
            try:
                src = src or self.make_source()
                ocr = ocr or self.ocr_factory()
                img = src.grab(1280, 720) if isinstance(src, OBSSource) else src.grab()
                self.step(img, ocr, time.time())
                self.alive, self.errors = True, 0
            except Exception:
                src = None
                self.errors += 1
                if self.errors >= 5:
                    self.alive = False
                time.sleep(1.0)
            time.sleep(max(0.0, self.EVERY - (time.time() - t0)))


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

    def read(self, text, hp=None):
        try:
            import battle as _B
            if self.opp_team is None:
                rec = json.load(open(os.path.join(OUT, '..', 'current.json'), encoding='utf-8'))
                self.opp_team = rec.get('opp_team') or None
            me, hp_me, opp, hp_opp = _B.screen_read(text, self.opp_team or [])
            if hp:            # the HP digits read from the panels (hpdigits) beat the whole-screen OCR
                hp_me = hp[0] if hp[0] is not None else hp_me
                hp_opp = hp[1] if hp[1] is not None else hp_opp
            return (me, hp_me, opp, hp_opp) if me and opp and hp_me is not None and hp_opp is not None else None
        except Exception:
            return None

    LEVELS = (5.0, 10.0, 20.0)     # keep reading the same position deeper while the animation lasts

    def feed(self, text, hp=None):
        key = self.read(text, hp)
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

    def answer(self, text, turn, hp=None):
        """The precomputed move for the command screen in `text`, or None (position differs or the field changed)."""
        if any(turn.get(k) for k in FIELD_KEYS):
            return None
        key = self.read(text, hp)
        return self.done.get(key) if key else None

    def shown(self, text, seq, line, hp=None):
        key = self.read(text, hp)
        self.watch = (key, seq, line) if key else None
        if key and not self.running:          # keep deepening this position until the next screen
            have = self.done.get(key)
            nxt = next((x for x in self.LEVELS if not have or x > have[2]), None)
            if nxt:
                self.start(key, nxt)


def panel_events(timeline, turn, tracker):
    """What the HP panels showed (MsgWatch.watch_icon) added to the turn read from the messages: a mon that came in
    (switch_seen) or changed its form (form_change) without the message being read. A form change of a mon that
    can still mega evolve is its mega evolution; of イルカマン, its マイティフォルム."""
    import msgparse as _mp
    try:
        from sets import MEGAS
    except Exception:
        MEGAS = {}
    for e in timeline:
        side = e.get('side')
        if 'switch_seen' in e:
            n = e['switch_seen']
            if not any(sw['side'] == side and _mp.BASE.get(sw['mon'], sw['mon']) == _mp.BASE.get(n, n)
                       for sw in turn['switch']):
                turn['switch'].append({'side': side, 'mon': n, 'from': 'panel'})
        elif 'form_change' in e:
            n = e['form_change']
            b = _mp.BASE.get(n, n)
            info = tracker.s['mons'][side].get(_mp.canon(side, b, tracker.opp_team() if side == 'opp' else ())) or {}
            if MEGAS.get(b) and not info.get('mega') and not tracker.s['mega_used'][side]:
                if not any(mg.get('side') == side for mg in turn['mega']):
                    turn['mega'].append({'side': side, 'mon': n, 'from': 'panel'})
            else:
                turn.setdefault('forms', []).append({'side': side, 'mon': n})


def damage_context(dmg, tracker, turn):
    """Add what the damage depended on (from the field state before the turn): stat stages of attacker and
    target, weather / terrain, burn, mega. Used to infer the opponent's set (infer.py: dealt / taken)."""
    try:
        from calc import MOVE
        import msgparse as _mp
    except Exception:
        return dmg
    s = tracker.s
    megas = {(m['side'], _mp.BASE.get(m['mon'], m['mon'])) for m in turn.get('mega', [])}
    out = []
    for d in dmg:
        try:
            cat = MOVE.get(d['move'], {}).get('cat')
            a_st, d_st = ('atk', 'def') if cat == 'physical' else ('spa', 'spd')
            def mon(side, name):
                if not name:
                    return {}
                n = _mp.canon(side, _mp.BASE.get(name, name), tracker.opp_team() if side == 'opp' else ())
                return s['mons'][side].get(n) or {}
            am, dm = mon(d['side'], d['mon']), mon(d['target'], d.get('target_mon'))
            base = lambda n: _mp.BASE.get(n, n)
            d = dict(d, atk_boost=(am.get('boosts') or {}).get(a_st, 0), def_boost=(dm.get('boosts') or {}).get(d_st, 0),
                     weather=s.get('weather'), terrain=s.get('terrain'), burned=am.get('status') == 'brn',
                     att_mega=bool(am.get('mega')) or (d['side'], base(d['mon'])) in megas,
                     def_mega=bool(dm.get('mega')) or (d['target'], base(d.get('target_mon') or '')) in megas)
        except Exception:
            pass
        out.append(d)
    return out


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


def screen_hp(img):
    """(our HP 'cur/max', their HP %) read from the panels' digits (hpdigits: templates of the italic digits),
    None where a panel is not up or not readable."""
    import hpdigits
    out = []
    for side, box in (('me', MY_PANEL), ('opp', OPP_PANEL)):
        try:
            pc = _crop(img, box)
            v = hpdigits.read_hp(pc, side) if panel_present(pc, side) else None
            out.append(f'{v[0]}/{v[1]}' if side == 'me' and v else v)
        except Exception:
            out.append(None)
    return tuple(out)


def decide_async(seq, sec, phase='command', party=None, bar=None):
    """The move for this command screen, computed right away from the screen text (who is out, both HPs) and the
    tracked field: battle.py auto --screen. Printed here in big letters and written to decision.json, so the answer is
    there about 5 seconds after the screen appears, before anyone reads the image."""
    import subprocess, threading

    def run():
        t0 = time.time()
        try:
            args = ['auto', '--sec', str(sec)] + (['--screen'] if phase not in ('replace', 'pivot') else []) + \
                (['--switch'] if phase == 'pivot' else []) + \
                (['--party', ','.join(f'{n}={hp or ""}' for n, hp in party)] if party else []) + \
                (['--panel'] + ['-' if v is None else str(v) for v in bar] if bar and any(v is not None for v in bar) else [])
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
    ap.add_argument('--no-msg', action='store_true', help='メッセージ欄とHP欄だけを0.25秒ごとに読む監視をしない')
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
    msgw = MsgWatch(make_source, WinOCR, os.path.join(OUT, 'messages.jsonl'),
                    skip=(lambda: fast.scene in ('command', 'party', 'preview')) if fast else None) if not a.no_msg else None
    timeline = []              # this turn's messages and HP panel readings from msgw, in order
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
        if not det.in_preview:
            turn_lines.extend(new)
        mnew = [e for e in (msgw.take() if msgw else []) if 'msg_update' not in e]
        if not det.in_preview:
            timeline.extend(mnew)
        msg_ok = bool(msgw and msgw.alive)

        def turn_msgs():
            # every message once, in order, from the message-box watcher; the whole-screen text if it is not running
            return [e['msg'] for e in timeline if 'msg' in e] if msg_ok else turn_lines

        if (new or mnew) and not det.in_preview:
            if preview_seq:
                cur_turn = msgparse.parse_turn(turn_msgs(), dedupe=not msg_ok)
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
        hp_now = screen_hp(img) if preview_seq and not det.in_preview else (None, None)
        if not det.in_preview and preview_seq and not a.no_decide and phase != 'command':
            spec.feed(text, hp_now)            # HP panels during the animation: compute the next move ahead of time
        event = det.update(phase, now)
        if event is None and fast and fast.onset and det.command_armed and not det.in_preview and preview_seq:
            event, det.command_armed = 'command', False      # the button watcher is sure enough on its own
        if event == 'command' and not turn_msgs() and not turn_lines and now - last_command_t < 60:
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
            opp_out = any(sw.get('side') == 'opp' for sw in msgparse.parse_turn(turn_msgs(), dedupe=not msg_ok).get('switch', []))
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
                turn = msgparse.parse_turn(turn_msgs(), dedupe=not msg_ok)
                if msg_ok:
                    panel_events(timeline, turn, tracker)
                if msg_ok:
                    ev['damage'] = damage_context(msgparse.damage_events(timeline, None, tracker.s.get('active')),
                                                  tracker, turn)
                tracker.apply(turn)
                ev['turn_events'] = {k: v for k, v in turn.items() if v}
                ev['field_state'] = field_p
                with open(log_p, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'seq': seq, 'time': ts, 'lines': turn_msgs(), 'parsed': ev['turn_events'],
                                        'damage': ev.get('damage'), 'timeline': timeline if msg_ok else None},
                                       ensure_ascii=False) + '\n')
                turn_lines, timeline = [], []
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
                turn_lines, timeline = [], []
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
                pre = spec.answer(text, ev.get('turn_events') or {}, hp_now) if phase == 'command' else None
                if pre:
                    publish(seq, pre[0], pre[1] + f'\n（演出中に先読み済み・{pre[2]:.0f}秒読み）', 0.0)
                    spec.shown(text, seq, pre[0], hp_now)
                else:
                    decide_async(seq, a.decide_sec, 'pivot' if phase == 'replace' and replace_mode == 'pivot' else phase,
                                 party_read(text) if phase == 'replace' else None,
                                 hp_now if phase != 'replace' else None)
                ev['replace_mode'] = replace_mode if phase == 'replace' else None
        safeio.write_json(state_p, {'phase': phase, 'seq': seq, 'time': time.time(), 'text': text})
        if fast:
            fast.wake.clear()
            fast.wake.wait(max(0.0, a.interval - (time.time() - t0)))   # the button watcher can wake us early
        else:
            time.sleep(max(0.0, a.interval - (time.time() - t0)))


if __name__ == '__main__':
    sys.exit(main())
