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
MAX_CROPS = 3000  # message pictures kept
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
    rs = a.sum(axis=1)
    rows = np.where(rs >= max(2, 0.12 * rs.max()))[0] if rs.max() else np.array([])    # furigana / specks above the text are thin
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
    pitch = h * 1.15
    merged = []
    for r in runs:
        if merged and (r[1] - merged[-1][0] <= pitch * 1.25) and (r[0] - merged[-1][1] <= pitch * 0.15):
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
                out.append((s, e))
            s = None
    if not out:
        return []
    big = max(e - s for s, e in out)
    ink_rows = a.sum(axis=1)
    keep = [(s, e) for s, e in out if (e - s) >= 0.65 * big and ink_rows[s:e].sum() >= 40]
    # the furigana line over kanji can be a line of its own: it is thin
    return [mask_img.crop((0, max(0, s - 4), mask_img.width, min(mask_img.height, e + 2))) for s, e in keep]


def read_box(mask_img):
    """The whole message box: lines joined by a space (the game wraps a sentence over two lines). None = not usable."""
    parts, low = [], 1.0
    for ln in split_lines(mask_img):
        r = read_line(ln)
        if r is None:
            return None
        parts.append(r[0]); low = min(low, r[1])
    return (' '.join(parts), low) if parts else None


def learn_line(mask_img, text, stage=None):
    """Add templates from one line whose correct text is known. Only when the number of cut characters equals the
    number of characters (spaces ignored), so a bad cut never spoils the templates. Returns the number added."""
    text = ''.join(text.split())
    a = ink(mask_img)
    cols, band = segment(a)
    if not cols or len(cols) != len(text):
        return 0
    if stage is not None:          # collected first, checked against each other, written by write_stage()
        stage.append([(ch, cell(a, x0, x1, band)) for (x0, x1), ch in zip(cols, text)])
        return len(text)
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


def save_crop(mask_img, text, n=None):
    """Called by game_watch for each message it reads: keep the picture and the OCR text so templates can be built later.
    Named by time (a new run never overwrites the crops of an earlier one); the oldest go beyond MAX_CROPS."""
    try:
        import time
        os.makedirs(CROPS, exist_ok=True)
        base = os.path.join(CROPS, time.strftime('%m%d_%H%M%S') + f'_{time.time_ns() % 1000000:06d}')
        mask_img.save(base + '.png')
        json.dump({'ocr': text}, open(base + '.json', 'w', encoding='utf-8'), ensure_ascii=False)
        names = sorted(f for f in os.listdir(CROPS) if f.endswith('.png'))
        for f in names[:max(0, len(names) - MAX_CROPS)]:
            for ext in ('.png', '.json'):
                try:
                    os.remove(os.path.join(CROPS, f[:-4] + ext))
                except OSError:
                    pass
    except Exception:
        pass


STAT_JA = {'atk': '攻撃', 'def': '防御', 'spa': '特攻', 'spd': '特防', 'spe': '素早さ', 'acc': '命中率', 'eva': '回避率'}
FIXED = ('効果はばつぐんだ！', '効果はいまひとつだ', '効果はいまひとつだ…', '効果はいまひとつのようだ', '効果はいまひとつのようだ…',
         '効果がないようだ…', '急所に当たった！', 'メガシンカした！')


def sentence_candidates(ocr):
    """Sentences the game may have printed for this OCR read, built from what msgparse understands of it (the names,
    moves and stat changes are taken from the corrected parse, the wording from the game's patterns). Several are
    returned when the wording varies (ぐーんと / ぐんと); the caller picks the one whose length fits the cut."""
    import msgparse as mp
    s = mp.apply_fixes(mp.norm(ocr))
    out = []
    mu = mp.move_use(s)
    if mu and mu[1] in s:
        pre = '相手の' if mu[0] == 'opp' else ''
        out.append(pre + mu[1] + 'の' + mu[2] + '！')
    try:
        ev = mp.parse_turn([ocr], dedupe=False)
    except Exception:
        ev = {}
    for b in ev.get('boosts') or []:
        pre = '相手の' if b['side'] == 'opp' else ''
        st = STAT_JA.get(b['stat'])
        if not st:
            continue
        up = b['delta'] > 0
        for adv in ({1: [''], 2: ['ぐーんと', 'ぐんと'], 3: ['ぐぐーんと']} if up else {1: [''], 2: ['がくっと'], 3: ['がくーんと']}).get(abs(b['delta']), ['']):
            out.append(f"{pre}{b['mon']}の{st}が{adv}{'上がった' if up else '下がった'}！")
    for f in ev.get('faint') or []:
        pre = '相手の' if f['side'] == 'opp' else ''
        out += [pre + f['mon'] + 'はたおれた！', pre + f['mon'] + 'は倒れた！']       # the game prints it in kana
    for sw in ev.get('switch') or []:
        if sw.get('side') == 'opp' and not sw.get('from'):
            out += [f"相手のトレーナーは{sw['mon']}を繰り出した！", f"トレーナーは{sw['mon']}を繰り出した！"]
    body = s.replace('/', '')
    names = [n for n in dict.fromkeys(mp.find_name(x) for x in [t for t in (mp.norm(l) for l in ocr.splitlines())]) if n]
    side_pre = lambda t: '相手の' if mp.side_marked(t) else ''
    flat = body
    # 〇〇、戻れ！ / ゆけっ！〇〇！ (our own switches: the comma may be missing from the read, the length decides)
    if '戻れ' in flat or 'もどれ' in flat:
        for n in names:
            out += [f'{n}、戻れ！', f'{n}戻れ！']
    if 'ゆけっ' in flat or 'ゆけつ' in flat:
        for n in names:
            out += [f'ゆけっ！{n}！', f'ゆけっ！{n}！']
    # mega evolution: 〇〇は メガ〇〇に メガシンカした！
    if 'メガシ' in flat or 'メカシ' in flat:
        for n in names:
            pre = side_pre(flat)
            out += [f'{pre}{n}はメガ{n}にメガシンカした！', f'{n}はメガ{n}にメガシンカした！', f'相手の{n}はメガ{n}にメガシンカした！']
    if '効果が' in flat or '効果か' in flat:
        for n in names:
            out += [f'{side_pre(flat)}{n}には効果がないようだ…', f'相手の{n}には効果がないようだ…', f'{n}には効果がないようだ…']
    if 'ひる' in flat:
        for n in names:
            out += [f'{n}はひるんで技がだせない！', f'相手の{n}はひるんで技がだせない！']
    if flat.startswith('効果'):
        out += list(FIXED)
    import difflib
    for f in FIXED:
        if difflib.SequenceMatcher(None, body, f).ratio() >= 0.75:
            out.append(f)
    return list(dict.fromkeys(out))


def write_stage(stage, verbose=True):
    """Write staged lines, leaving out the lines whose characters disagree with the same characters elsewhere: a line
    whose cut happened to give the right count with the wrong cells (「ま」 got the picture of half a 「い」) would put
    wrong pictures under right names. A cell is compared with its closest cell on other lines; a line is dropped when
    fewer than 60% of its comparable cells (3 or more) have the same name there."""
    flat = [(i, ch, b) for i, cells in enumerate(stage) for ch, b in cells if b.sum() >= 4]
    drop = set()
    if len(flat) > 3:
        M = np.array([b.reshape(-1) for _, _, b in flat], dtype=bool)
        Md = _dilate_rows(M)
        inter = (M[:, None, :] & Md[None, :, :]).sum(axis=2) / np.maximum(1, M.sum(axis=1))[:, None]     # i covered by j
        sc = np.minimum(inter, inter.T)
        line = np.array([i for i, _, _ in flat])
        sc[line[:, None] == line[None, :]] = -1
        agree, comp = {}, {}
        for k, (i, ch, _) in enumerate(flat):
            j = int(sc[k].argmax())
            if sc[k, j] >= 0.65:
                comp[i] = comp.get(i, 0) + 1
                agree[i] = agree.get(i, 0) + (flat[j][1] == ch)
        drop = {i for i, n in comp.items() if n >= 3 and agree.get(i, 0) / n < 0.6}
    try:
        d = json.load(open(TPL_P, encoding='utf-8'))
    except Exception:
        d = {}
    for i, cells in enumerate(stage):
        if i in drop:
            continue
        for ch, b in cells:
            if b.sum() < 4:
                continue
            lst = d.setdefault(ch, [])
            if all(float((b & _arr(x)).sum() / max(1, (b | _arr(x)).sum())) < 0.93 for x in lst):
                lst.append(_bits(b))
                d[ch] = lst[-KEEP:]
    os.makedirs(os.path.dirname(TPL_P), exist_ok=True)
    json.dump(d, open(TPL_P, 'w', encoding='utf-8'), ensure_ascii=False)
    return len(drop)


def tail_learn(lines, counts, cands, stage=None):
    """「〇〇(相手の名前)は / △△を繰り出した！」: the first line is the opponent's player name (unknown), the rest is
    known. Learn the lines after the first when their count equals the end of a candidate sentence."""
    for c in cands:
        if 'を繰り出した' not in c:
            continue
        tail = c[c.index('は') + 1:] if 'トレーナーは' not in c else c[c.index('は') + 1:]
        for k in range(1, len(lines)):
            if sum(counts[k:]) == len(tail):
                i = 0
                for l, n in zip(lines[k:], counts[k:]):
                    learn_line(l, tail[i:i + n], stage); i += n
                return True
    return False


def build(verbose=True):
    """Templates from the saved crops: the OCR text of each crop is turned into the sentence the game printed
    (sentence_candidates); the candidate whose length equals the number of characters cut from the picture is used.
    Misread / unrecognised crops are left out. The reasons for skipped crops are counted and printed."""
    import difflib
    import msgparse as mp
    why = {'crop数': 0, '文を作れない': 0, '2行・空など': 0, '文字数が合わない': 0, '追加した行': 0}
    shown = 0
    stage = []
    names = sorted(os.listdir(CROPS)) if os.path.isdir(CROPS) else []
    for f in names:
        if not f.endswith('.png'):
            continue
        try:
            ocr = json.load(open(os.path.join(CROPS, f[:-4] + '.json'), encoding='utf-8')).get('ocr') or ''
        except Exception:
            continue
        why['crop数'] += 1
        cands = sentence_candidates(ocr)
        if not cands:
            why['文を作れない'] += 1
            continue
        lines = split_lines(Image.open(os.path.join(CROPS, f)))
        if not lines or len(lines) > 3:
            why['2行・空など'] += 1
            continue
        counts = [len(segment(ink(l))[0]) for l in lines]
        fit = [c for c in cands if len(c) == sum(counts)]
        body = mp.apply_fixes(mp.norm(ocr)).replace('/', '')
        sim = lambda c: difflib.SequenceMatcher(None, body, c).ratio()
        fit = sorted((c for c in fit if sim(c) >= 0.45), key=lambda c: -sim(c))     # same length, different sentence: the read decides
        if fit:
            i = 0
            for l, n in zip(lines, counts):
                learn_line(l, fit[0][i:i + n], stage)
                i += n
            why['追加した行'] += 1
        elif tail_learn(lines, counts, cands, stage):
            why['追加した行'] += 1
        else:
            why['文字数が合わない'] += 1
            if verbose and shown < 5:
                shown += 1
                print(f'  例 {f}: 候補 {[ (c, len(c)) for c in cands[:2] ]} / 切り出し {counts} 文字')
    dropped = write_stage(stage)
    why['食い違いで除いた行'] = dropped
    print('見本づくり: ' + ' / '.join(f'{k} {v}' for k, v in why.items()))
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
