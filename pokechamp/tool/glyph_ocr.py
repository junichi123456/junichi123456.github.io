"""ゲームの字体に合わせた文字読み取り（見本照合）。Windows の文字認識が「ミ→三」「ぎ→き」と読み違えるのを減らす。

  python glyph_ocr.py learn <マスク画像> "<正しい文字列>"   1行ぶんの文字画像から見本を追加（text_mask の出力と同じ白黒画像）
  python glyph_ocr.py build                                    logs/live/msgcrops/ に溜まった読み取り結果から見本を作る
  python glyph_ocr.py read <マスク画像>                        見本で読んで文字列を表示
  python glyph_ocr.py stats                                    見本の数を表示
見本は data/glyph_templates.json（文字 → 24x24 の2値画像のビット列、最大 KEEP 個）。
読み取りの入口は read_line(mask_img)。見本が少ない・点数が低いときは None を返し、呼び出し側が従来の読み取りへ戻る。
"""
import json, os, sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TPL_P = os.path.join(HERE, 'data', 'glyph_templates.json')
LOGS = os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs'))
CROPS = os.path.join(LOGS, 'live', 'msgcrops')
N = 24            # template cell
KEEP = 8          # templates kept per character
SHEAR = 0.2       # the game text is italic: lean it back upright first (same as MsgWatch.panel_name)
MIN_CHARS = 150   # characters with a template before the reader is trusted at all
ACCEPT = 0.55     # a character reads as its best template when the overlap is at least this

_TPL = {'mtime': None, 'chars': [], 'mat': None, 'matd': None}


def ink(mask_img):
    """text_mask output (black text on white) -> bool array, text = True, leaned upright."""
    g = mask_img.convert('L')
    if SHEAR:
        g = g.transform((g.width + int(g.height * SHEAR), g.height), Image.AFFINE, (1, -SHEAR, 0, 0, 1, 0), fillcolor=255)
    return np.asarray(g) < 128


def segment(a):
    """Bool ink image -> [(x0, x1), ...] character column ranges and the text band (y0, y1). Gaps between ink columns
    split characters; pieces of one character (the dots of が, the strokes of い) are merged up to one character width;
    a run much wider than a character (two touching) is split evenly."""
    rows = np.where(a.sum(axis=1) > 0)[0]
    if len(rows) < 6:
        return [], None
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    h = y1 - y0
    cols = a[y0:y1].sum(axis=0) > 0
    runs, s = [], None
    for x, v in enumerate(cols):
        if v and s is None:
            s = x
        if (not v or x == len(cols) - 1) and s is not None:
            runs.append([s, x if not v else x + 1])
            s = None
    pitch = h * 1.05
    merged = []
    for r in runs:
        if merged and (r[1] - merged[-1][0] <= pitch * 0.95) and (r[0] - merged[-1][1] <= pitch * 0.3):
            merged[-1][1] = r[1]
        else:
            merged.append(list(r))
    out = []
    for x0, x1 in merged:
        w = x1 - x0
        k = int(round(w / pitch)) if w > pitch * 1.45 else 1
        for i in range(k):
            out.append((x0 + (w * i) // k, x0 + (w * (i + 1)) // k))
    return out, (y0, y1)


def cell(a, x0, x1, band):
    """One character -> N*N bool, centred in a square of the band's height."""
    y0, y1 = band
    c = a[y0:y1, x0:x1]
    side = max(c.shape)
    sq = np.zeros((side, side), dtype=bool)
    oy, ox = (side - c.shape[0]) // 2, (side - c.shape[1]) // 2
    sq[oy:oy + c.shape[0], ox:ox + c.shape[1]] = c
    im = Image.fromarray((sq * 255).astype(np.uint8)).resize((N, N), Image.BILINEAR)
    return np.asarray(im) > 90


def _bits(b):
    return ''.join('1' if v else '0' for v in b.reshape(-1))


def _arr(s):
    return np.frombuffer(s.encode('ascii'), dtype=np.uint8).reshape(N, N) == 49


def load():
    try:
        mt = os.path.getmtime(TPL_P)
    except OSError:
        _TPL.update(mtime=None, chars=[], mat=None, matd=None)
        return _TPL
    if _TPL['mtime'] != mt:
        d = json.load(open(TPL_P, encoding='utf-8'))
        chars, rows = [], []
        for ch, lst in d.items():
            for s in lst:
                chars.append(ch)
                rows.append(_arr(s).reshape(-1))
        mat = np.array(rows, dtype=bool) if rows else None
        _TPL.update(mtime=mt, chars=chars, mat=mat, matd=_dilate_rows(mat) if rows else None)
    return _TPL


def _dilate(b):
    d = b.copy()
    d[1:] |= b[:-1]; d[:-1] |= b[1:]; d[:, 1:] |= b[:, :-1]; d[:, :-1] |= b[:, 1:]
    return d


def match_char(b, tpl):
    """[(score, char), ...] best first (best per character). Score: overlap of the two glyphs, each allowed to be one
    pixel off (so a slightly different slant or position still matches)."""
    mat, matd = tpl['mat'], tpl['matd']
    v = b.reshape(-1)
    vd = _dilate(b).reshape(-1)
    cov_t = (mat & vd).sum(axis=1) / np.maximum(1, mat.sum(axis=1))      # template pixels the glyph covers
    cov_g = (matd & v).sum(axis=1) / max(1, v.sum())                     # glyph pixels the template covers
    sc = np.minimum(cov_t, cov_g)
    best = {}
    for s, ch in zip(sc, tpl['chars']):
        if s > best.get(ch, -1):
            best[ch] = float(s)
    return sorted(((s, ch) for ch, s in best.items()), reverse=True)[:3]


def _dilate_rows(mat):
    m = mat.reshape(-1, N, N)
    d = m.copy()
    d[:, 1:] |= m[:, :-1]; d[:, :-1] |= m[:, 1:]; d[:, :, 1:] |= m[:, :, :-1]; d[:, :, :-1] |= m[:, :, 1:]
    return d.reshape(len(mat), -1)


def read_line(mask_img):
    """(text, min_score) for a line of text_mask output, or None when there are not enough templates / the line is not
    readable. Characters below ACCEPT are returned as the best guess anyway, and flagged by the min score."""
    tpl = load()
    if tpl['mat'] is None or len(set(tpl['chars'])) < MIN_CHARS:
        return None
    a = ink(mask_img)
    cols, band = segment(a)
    if not cols:
        return None
    out, low = [], 1.0
    for x0, x1 in cols:
        m = match_char(cell(a, x0, x1, band), tpl)
        if not m:
            return None
        out.append(m[0][1])
        low = min(low, m[0][0])
    return ''.join(out), round(low, 2)


def split_lines(mask_img):
    """A message box can hold two lines: rows of ink separated by an empty band."""
    a = np.asarray(mask_img.convert('L')) < 128
    rows = a.sum(axis=1) > 0
    out, s = [], None
    for y, v in enumerate(rows):
        if v and s is None:
            s = y
        if (not v or y == len(rows) - 1) and s is not None:
            e = y if not v else y + 1
            if e - s >= 8:
                out.append(mask_img.crop((0, max(0, s - 2), mask_img.width, min(mask_img.height, e + 2))))
            s = None
    return out


def read_box(mask_img):
    """The whole message box: lines joined by a space (the game wraps a sentence over two lines). None = not usable."""
    parts, low = [], 1.0
    for ln in split_lines(mask_img):
        r = read_line(ln)
        if r is None:
            return None
        parts.append(r[0]); low = min(low, r[1])
    return (' '.join(parts), low) if parts else None


def learn_line(mask_img, text):
    """Add templates from one line whose correct text is known. Only when the number of cut characters equals the
    number of characters (spaces ignored), so a bad cut never spoils the templates. Returns the number added."""
    text = ''.join(text.split())
    a = ink(mask_img)
    cols, band = segment(a)
    if not cols or len(cols) != len(text):
        return 0
    try:
        d = json.load(open(TPL_P, encoding='utf-8'))
    except Exception:
        d = {}
    added = 0
    for (x0, x1), ch in zip(cols, text):
        b = cell(a, x0, x1, band)
        if b.sum() < 4:
            continue
        lst = d.setdefault(ch, [])
        cur = [_arr(s) for s in lst]
        if all(float((b & c).sum() / max(1, (b | c).sum())) < 0.93 for c in cur):
            lst.append(_bits(b))
            d[ch] = lst[-KEEP:]
            added += 1
    os.makedirs(os.path.dirname(TPL_P), exist_ok=True)
    json.dump(d, open(TPL_P, 'w', encoding='utf-8'), ensure_ascii=False)
    return added


def save_crop(mask_img, text, n):
    """Called by game_watch for each message it reads: keep the picture and the OCR text so templates can be built later."""
    try:
        os.makedirs(CROPS, exist_ok=True)
        base = os.path.join(CROPS, f'{n % 1500:04d}')
        mask_img.save(base + '.png')
        json.dump({'ocr': text}, open(base + '.json', 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception:
        pass


def build(verbose=True):
    """Templates from the saved crops: lines whose OCR text, after the usual corrections (msgparse), is one of this
    battle's mon / move sentences and whose character count matches the cut. Misread lines are left out.
    The reasons for skipped crops are counted and printed (why 0 templates?)."""
    import msgparse as mp
    why = {'crop数': 0, '技の文ではない': 0, '2行・空など(1行ではない)': 0, '文字数が合わない': 0, '追加した行': 0}
    shown = 0
    names = sorted(os.listdir(CROPS)) if os.path.isdir(CROPS) else []
    for f in names:
        if not f.endswith('.png'):
            continue
        try:
            ocr = json.load(open(os.path.join(CROPS, f[:-4] + '.json'), encoding='utf-8')).get('ocr') or ''
        except Exception:
            continue
        why['crop数'] += 1
        s = mp.apply_fixes(mp.norm(ocr))
        mu = mp.move_use(s)
        if not (mu and mu[1] in s):       # the move may be misread: it is taken from the corrected parse
            why['技の文ではない'] += 1
            continue
        lines = split_lines(Image.open(os.path.join(CROPS, f)))
        text = ('相手の' if mu[0] == 'opp' else '') + mu[1] + 'の' + mu[2] + '！'      # the sentence as the game prints it
        if len(lines) != 1:
            why['2行・空など(1行ではない)'] += 1
            continue
        n_add = learn_line(lines[0], text)
        if n_add:
            why['追加した行'] += 1
        else:
            cols, _ = segment(ink(lines[0]))
            why['文字数が合わない'] += 1
            if verbose and shown < 5:
                shown += 1
                print(f'  例 {f}: 期待 {len(text)} 文字「{text}」/ 切り出し {len(cols)} 文字')
    print(f'見本づくり: ' + ' / '.join(f'{k} {v}' for k, v in why.items()))
    if not os.path.isdir(CROPS):
        print(f'crop の保存先がありません: {os.path.abspath(CROPS)}（game_watch.py を先に動かしてください）')
    stats()


def stats():
    t = load()
    print(f"見本: {len(t['chars'])} 個 / {len(set(t['chars']))} 文字（{MIN_CHARS} 文字を超えると読み取りに使います）")


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == 'learn':
        print(learn_line(Image.open(a[1]), a[2]), '個の見本を追加しました')
    elif len(a) >= 2 and a[0] == 'read':
        print(read_line(Image.open(a[1])))
    elif a[:1] == ['build']:
        build()
    else:
        stats()


if __name__ == '__main__':
    main()
