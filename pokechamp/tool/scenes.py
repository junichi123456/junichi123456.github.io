"""画面（シーン）の判定。OCR を使わず、色と位置だけで 0.15 秒ごとに判定できるものだけで構成する。

シーン（1フレームの分類）
  preview   選出画面（上部中央の「シングルバトル」、左右の名前欄が高い位置）。「対戦準備中」もここ
  party     手持ちの一覧（名前欄が少し低い位置）。交代先を選ぶ画面・ポケモンボタンで開く一覧
  input     行動入力中: 右上の「COMMAND ○○ / X 様子を見る」の表示がある。たたかう・技一覧・状態確認・手持ち確認のすべてを含む
  vs        「VS」の画面（左下に青、右下にピンクの帯）
  result    対戦後の結果画面（下に3つのボタン。右端が黄緑）
  battle    対戦中の演出・メッセージ（HP欄は出ているが入力表示がない）
  other     上記以外（メニュー、暗転、読み込み）

SceneTracker は1フレームごとの分類をつないで、次の出来事を出す（時間はすべて秒・ヒステリシス付き）。
  input_start   行動入力の開始（1ターンに1回。技一覧・状態確認・手持ち確認を開いても続きとみなす）
  input_end     行動入力の終了（演出に入った）
  party_forced  行動入力を経ずに手持ち一覧が出た（ひんし・交代技の後に出す相手を選ぶ画面）
  preview_start / preview_end / vs / result
"""
import numpy as np


def _arr(img, w, h):
    return np.asarray(img.convert('RGB').resize((w, h)), dtype=np.int16)


def hud_input(img):
    """右上の「X 様子を見る」の帯（暗い紺色の台形）が出ているか。技一覧・状態確認でも出ている。"""
    W, H = img.size
    c = img.crop((int(0.84 * W), int(0.345 * H), W, int(0.38 * H)))
    f = np.asarray(c.convert('RGB'), dtype=np.int16)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    navy = ((b > r + 12) & (b > g + 8) & (f.max(2) < 140)).mean()
    white = (f.min(2) > 200).mean()
    return navy > 0.45 and 0.02 < white < 0.25


def is_vs(img):
    f = _arr(img, 160, 90)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    band = slice(int(90 * 0.86), int(90 * 0.97))
    left = ((b > 150) & (r < 110) & (g < 130))[band, :80].mean()
    right = ((r > 170) & (g < 90) & (b > 70))[band, 80:].mean()
    return left > 0.35 and right > 0.35


def is_result(img):
    f = _arr(img, 160, 90)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    band = slice(int(90 * 0.93), int(90 * 0.985))
    yg = ((r > 170) & (g > 200) & (b < 120))[band, int(160 * 0.72):int(160 * 0.95)].mean()
    vio = ((b > 120) & (b - r > 30) & (b - g > 40))[band, int(160 * 0.05):int(160 * 0.30)].mean()
    return yg > 0.4 and vio > 0.3


def classify(img):
    import game_watch as G
    sc = G.scene(img)            # preview / party / command (the old, colour-only detector)
    if sc in ('preview', 'party'):
        return sc
    if sc == 'command' or hud_input(img):
        return 'input'
    if is_vs(img):
        return 'vs'
    if is_result(img):
        return 'result'
    for side, box in (('opp', G.OPP_PANEL), ('me', G.MY_PANEL)):
        if G.panel_present(G._crop(img, box), side):
            return 'battle'
    return 'other'


class SceneTracker:
    ON = 0.3             # seconds of input needed to open a session
    OFF = 1.6            # seconds without input before the session is over
    PARTY_BROWSE = 4.0   # a party list within this long of input is the player looking at it, not a forced choice
    CONFIRM = 0.3
    PARTY_GAP = 8.0      # a forced party list is one episode until it has been gone this long
    BATTLE_RECENT = 60.0 # input counts only if a battle picture (HP panels) was seen this recently: the menus also have buttons

    def __init__(self):
        self.state = 'idle'          # idle / preview / input / battle
        self.input_since = None
        self.last_input = -1e9
        self.last_non_input = None
        self.party_since = None
        self.party_open = False
        self.vs_seen = False
        self.result_since = None
        self.preview_since = None
        self.last_preview = -1e9
        self.session_id = 0
        self.label = 'other'
        self.events = []
        self.battle_seen = -1e9
        self.party_last = -1e9
        self.party_gap = 1e9

    def step(self, label, now):
        out = []
        self.label = label
        if label == 'battle':
            self.battle_seen = now
        # ---- input session
        if label == 'input':
            self.last_input = now
            self.hits = [t for t in getattr(self, 'hits', []) if now - t <= 1.2] + [now]   # tolerate a flickering frame
            if self.input_since is None:
                self.input_since = now
            if self.state != 'input' and len(self.hits) >= 2 and now - self.battle_seen <= self.BATTLE_RECENT:
                self.state = 'input'
                self.session_id += 1
                out.append(('input_start', now))
        else:
            self.input_since = None if label != 'party' else self.input_since
            if self.state == 'input' and label != 'party' and now - self.last_input >= self.OFF:
                self.state = 'battle'
                out.append(('input_end', now))
        # ---- party list
        if label == 'party':
            if self.party_since is None:
                self.party_since = now
                self.party_gap = now - self.party_last      # how long the list had been gone
            if not self.party_open and now - self.party_since >= self.CONFIRM:
                self.party_open = True
                if now - self.last_input > self.PARTY_BROWSE and self.party_gap > self.PARTY_GAP:
                    out.append(('party_forced', now))
            self.party_last = now
        else:
            self.party_since, self.party_open = None, False
        # ---- preview
        if label == 'preview':
            self.last_preview = now
            if self.preview_since is None:
                self.preview_since = now
            if self.state != 'preview' and now - self.preview_since >= self.CONFIRM:
                self.state = 'preview'
                out.append(('preview_start', now))
        else:
            self.preview_since = None
            if self.state == 'preview' and now - self.last_preview >= 3.0:
                self.state = 'battle'
                out.append(('preview_end', now))
        # ---- vs / result
        if label == 'vs' and not self.vs_seen:
            self.vs_seen = True
            out.append(('vs', now))
        if label != 'vs' and label != 'preview':
            pass
        if label == 'preview':
            self.vs_seen = False
        if label == 'result':
            if self.result_since is None:
                self.result_since = now
            elif now - self.result_since >= 1.0 and self.state != 'idle':
                self.state = 'idle'
                out.append(('result', now))
        else:
            self.result_since = None
        self.events.extend(out)
        return out
