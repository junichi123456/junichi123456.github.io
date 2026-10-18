"""ゲームの字体に合わせた文字読み取り（見本照合）。Windows の文字認識が「ミ→三」「ぎ→き」と読み違えるのを減らす。

  python glyph_ocr.py learn <マスク画像> "<正しい文字列>"   1行ぶんの文字画像から見本を追加（text_mask の出力と同じ白黒画像）
  python glyph_ocr.py build                                    logs/live/msgcrops/ に溜まった読み取り結果から見本を作る
  python glyph_ocr.py read <マスク画像>                        見本で読んで文字列を表示
  python glyph_ocr.py purge                                    文字に見えない見本（ごく小さい断片など）を除く
  python glyph_ocr.py seed [--font P] [--weight W] [--index I]  フォント（ニタラゴルイカ等）で補助見本 data/glyph_seed.json を作る
  python glyph_ocr.py eval [--crops D] [--font P] [--weight W] [--folds 2] [--simulate-free] [--json OUT]
                                                               補助見本あり/なしの読み取りを msgcrops で比べる（実戦の見本は書き換えない）
  python glyph_ocr.py stats                                    見本の数を表示
補助見本: 実戦の見本が無い文字だけ、フォントで描いた文字で補う（POKECHAMP_FONT か data/font_seed.json で指定。
フォントはリポジトリに入れない）。read_line / read_box の seed=True, detail=True で使い、game_watch は
Windows OCR と一致したときだけ採用する（adopt_seed）。仕様: pokechamp/specs/SPEC_FONT_SEED.md
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


PUNCT = set('！？、。…・ー「」（）')


def glyph_like(b, ch):
    """A cut that can be a character: enough ink for its name (a mark of a few pixels, a ruby fragment or a speck is not),
    punctuation excepted."""
    return b.sum() >= (4 if ch in PUNCT else 20)


def _bits(b):
    return ''.join('1' if v else '0' for v in b.reshape(-1))


def _arr(s):
    return np.frombuffer(s.encode('ascii'), dtype=np.uint8).reshape(N, N) == 49


SEED_P = os.path.join(HERE, 'data', 'glyph_seed.json')
CFG_P = os.path.join(HERE, 'data', 'font_seed.json')
SEED_PEN = 0.05        # a seed (font) glyph's score is lowered by this: a real glyph that looks as much wins
SEED_ACCEPT = 0.60     # a character read from a seed glyph is "sure" only at this score (after the penalty)
SEED_MIN_REAL = 60     # characters with a real template before seeds are used at all
SEED_MAX_FRAC = 0.3    # at most this share of a line may be read from seeds
_TPLS = {'key': None}


def _load_json(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return None


def load(seed=False):
    """Templates: real ones (data/glyph_templates.json). seed=True adds the font seeds of characters that have no real
    template ('is_seed' marks them; 'real_chars' = number of characters with a real template)."""
    try:
        mt = os.path.getmtime(TPL_P)
    except OSError:
        _TPL.update(mtime=None, chars=[], mat=None, matd=None)
        mt = None
    if mt is not None and _TPL['mtime'] != mt:
        d = json.load(open(TPL_P, encoding='utf-8'))
        chars, rows = [], []
        for ch, lst in d.items():
            for s in lst:
                chars.append(ch)
                rows.append(_arr(s).reshape(-1))
        mat = np.array(rows, dtype=bool) if rows else None
        _TPL.update(mtime=mt, chars=chars, mat=mat, matd=_dilate_rows(mat) if rows else None)
    if not seed:
        return _TPL
    try:
        smt = os.path.getmtime(SEED_P)
    except OSError:
        smt = None
    key = (mt, smt, SEED_P)
    if _TPLS['key'] != key:
        chars, rows = list(_TPL['chars']), ([] if _TPL['mat'] is None else list(_TPL['mat']))
        real = set(chars)
        is_seed = [False] * len(chars)
        sd = (_load_json(SEED_P) or {}).get('glyphs') or {}
        for ch, bits in sd.items():
            if ch in real or len(bits) != N * N:
                continue
            chars.append(ch); rows.append(_arr(bits).reshape(-1)); is_seed.append(True)
        mat = np.array(rows, dtype=bool) if rows else None
        _TPLS.update(key=key, chars=chars, mat=mat, matd=_dilate_rows(mat) if rows else None,
                     is_seed=np.array(is_seed, dtype=bool), real_chars=len(real))
    return _TPLS


def _dilate(b):
    d = b.copy()
    d[1:] |= b[:-1]; d[:-1] |= b[1:]; d[:, 1:] |= b[:, :-1]; d[:, :-1] |= b[:, 1:]
    return d


def _match(b, tpl):
    """[(score, char, is_seed), ...] best first, one per character (top 3). Score: overlap of the two glyphs, each
    allowed to be one pixel off (so a slightly different slant or position still matches); seed glyphs lose SEED_PEN."""
    mat, matd = tpl['mat'], tpl['matd']
    v = b.reshape(-1)
    vd = _dilate(b).reshape(-1)
    cov_t = (mat & vd).sum(axis=1) / np.maximum(1, mat.sum(axis=1))      # template pixels the glyph covers
    cov_g = (matd & v).sum(axis=1) / max(1, v.sum())                     # glyph pixels the template covers
    sc = np.minimum(cov_t, cov_g)
    seeds = tpl.get('is_seed')
    if seeds is not None:
        sc = sc - SEED_PEN * seeds
    out, seen = [], set()
    for i in np.argsort(-sc)[:40]:
        ch = tpl['chars'][i]
        if ch in seen:
            continue
        seen.add(ch)
        out.append((float(sc[i]), ch, bool(seeds[i]) if seeds is not None else False))
        if len(out) == 3:
            break
    return out


def match_char(b, tpl):
    return [(s, c) for s, c, _ in _match(b, tpl)]


def _dilate_rows(mat):
    m = mat.reshape(-1, N, N)
    d = m.copy()
    d[:, 1:] |= m[:, :-1]; d[:, :-1] |= m[:, 1:]; d[:, :, 1:] |= m[:, :, :-1]; d[:, :, :-1] |= m[:, :, 1:]
    return d.reshape(len(mat), -1)


def _gate(tpl, seed, gate=True):
    """May the reader be used? Real templates alone: MIN_CHARS characters. With seeds: SEED_MIN_REAL real characters
    and MIN_CHARS characters in all."""
    if tpl['mat'] is None:
        return False
    if not gate:
        return True
    if not seed:
        return len(set(tpl['chars'])) >= MIN_CHARS
    return tpl.get('real_chars', 0) >= SEED_MIN_REAL and len(set(tpl['chars'])) >= MIN_CHARS


def _read_line(mask_img, tpl):
    """[(char, score, is_seed), ...] or None."""
    a = ink(mask_img)
    cols, band = segment(a)
    if not cols:
        return None
    out = []
    for x0, x1 in cols:
        m = _match(cell(a, x0, x1, band), tpl)
        if not m:
            return None
        out.append((m[0][1], m[0][0], m[0][2]))
    return out


def read_line(mask_img, seed=False, detail=False):
    """(text, min_score) for a line of text_mask output, or None when there are not enough templates / the line is not
    readable. Characters below ACCEPT are returned as the best guess anyway, and flagged by the min score.
    seed=True also uses the font seeds; detail=True returns the dict described in read_box."""
    tpl = load(seed)
    if not _gate(tpl, seed):
        return None
    r = _read_line(mask_img, tpl)
    if r is None:
        return None
    if detail:
        return _detail([r])
    return ''.join(c for c, _, _ in r), round(min(s for _, s, _ in r), 2)


def _detail(lines):
    chars = [{'ch': c, 'score': round(s, 3), 'seed': sd} for ln in lines for c, s, sd in ln]
    n, sn = len(chars), sum(1 for c in chars if c['seed'])
    return {'text': ' '.join(''.join(c for c, _, _ in ln) for ln in lines), 'low': round(min(c['score'] for c in chars), 2),
            'chars': chars, 'n': n, 'seed_n': sn, 'confidence': 'seed' if sn else 'high'}


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


def read_box(mask_img, seed=False, detail=False, gate=True):
    """The whole message box: lines joined by a space (the game wraps a sentence over two lines). None = not usable.
    detail=True returns {'text', 'low', 'chars': [{'ch','score','seed'}], 'n', 'seed_n', 'confidence': 'high'|'seed'}
    instead of (text, min_score). gate=False (eval only) ignores the character-count gate."""
    tpl = load(seed)
    if not _gate(tpl, seed, gate):
        return None
    lines = []
    for ln in split_lines(mask_img):
        r = _read_line(ln, tpl)
        if r is None:
            return None
        lines.append(r)
    if not lines:
        return None
    if detail:
        return _detail(lines)
    return ' '.join(''.join(c for c, _, _ in ln) for ln in lines), round(min(s for ln in lines for _, s, _ in ln), 2)


def _k(x):
    import msgparse as mp
    return mp.apply_fixes(mp.norm(x)).replace(' ', '').replace('/', '')


def adopt_seed(d, ocr_text, why=False):
    """May a reading that used font seeds replace the Windows OCR text? (a) it is a message, (b) every real character
    scores >= ACCEPT and every seed character >= SEED_ACCEPT, (c) at most SEED_MAX_FRAC of the characters are seeds,
    (d) the two readings are of the same sentence (ratio >= 0.6), (e) each seed character sits where the OCR agrees.
    Characters read from real templates may differ from the OCR (that is the point: 三 -> ミ). why=True returns
    (bool, reason)."""
    def res(ok, r):
        return (ok, r) if why else ok
    import difflib, msgparse as mp
    if not d or not ocr_text or not mp.is_message(ocr_text):
        return res(False, 'a')
    for c in d['chars']:
        if c['score'] < (SEED_ACCEPT if c['seed'] else ACCEPT):
            return res(False, 'b')
    if d['seed_n'] > SEED_MAX_FRAC * d['n']:
        return res(False, 'c')
    g, o = d['text'].replace(' ', ''), _k(ocr_text)
    kg = _k(g)
    if difflib.SequenceMatcher(None, kg, o).ratio() < 0.6:
        return res(False, 'd')
    if d['seed_n']:
        if len(kg) != len(g):
            return res(False, 'e')
        ok = set()
        for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, kg, o).get_opcodes():
            if tag == 'equal':
                ok.update(range(i1, i2))
        pos = 0
        for c in d['chars']:
            if c['seed'] and pos not in ok:
                return res(False, 'e')
            pos += 1
    return res(True, 'ok')


SEED_EXTRA = ('相手のトレーナーは繰り出した戻れゆけっ倒れた上がった下がったひるんで技がだせないメガシンカ効果はばつぐんだ'
              'いまひとつのようだ急所に当たった攻撃防御特攻特防素早さ命中率回避率勝負に勝負け反応した元へ戻っていくぐーんとがくっと')
SIMFREE_EXCLUDE = set('ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ戻繰')


def font_config():
    """{'path', 'weight', 'index'} of the font that makes the seeds, or None (not set / missing / cannot be opened):
    POKECHAMP_FONT (+ POKECHAMP_FONT_WEIGHT / POKECHAMP_FONT_INDEX) first, then data/font_seed.json."""
    try:
        path, weight, index = os.environ.get('POKECHAMP_FONT'), 0, 0
        if path:
            weight = int(os.environ.get('POKECHAMP_FONT_WEIGHT') or 0)
            index = int(os.environ.get('POKECHAMP_FONT_INDEX') or 0)
        else:
            c = _load_json(CFG_P) or {}
            if not c.get('path') or c.get('enabled') is False:
                return None
            path, weight, index = c['path'], int(c.get('weight') or 0), int(c.get('index') or 0)
        if not os.path.isfile(path):
            return None
        from PIL import ImageFont
        ImageFont.truetype(path, 24, index=index)
        return {'path': path, 'weight': max(0, min(3, weight)), 'index': index}
    except Exception:
        return None


def seed_charset():
    """Characters a message can contain: kana, ー, punctuation, the names of Pokemon / abilities / moves and the
    fixed sentences. Digits and Latin letters are left out. About 500 characters."""
    cs = set(chr(c) for c in range(0x3041, 0x3097)) | set(chr(c) for c in range(0x30A1, 0x30FB)) | {'ー'} | PUNCT
    for fn, keys in (('pokemon.json', ('ja', 'ab')), ('moves.json', ('ja',))):
        for e in _load_json(os.path.join(HERE, 'data', fn)) or []:
            for k in keys:
                v = e.get(k) or ''
                cs.update(''.join(v) if isinstance(v, list) else v)
    cs.update(SEED_EXTRA)
    cs.update(''.join(FIXED))
    cs.update(''.join(STAT_JA.values()))
    return ''.join(sorted(c for c in cs if not c.isascii() and not c.isspace() and not ('０' <= c <= '９')))


def make_seed(cfg=None, out=None, verbose=True, simfree=False):
    """Draw every character of seed_charset() with the font (cfg or font_config()) in the same normalisation as the real
    templates and write data/glyph_seed.json (a cache: nothing is done when its meta still fits). Returns the number of
    glyphs, 0 when no font. simfree=True treats voiced / small kana and 戻繰 as missing from the font (eval only)."""
    import hashlib
    cfg = cfg or font_config()
    if not cfg:
        return 0
    out = out or SEED_P
    try:
        import font_probe as fp
        from PIL import ImageFont
        cs = seed_charset()
        st = os.stat(cfg['path'])
        meta = {'font': os.path.basename(cfg['path']), 'size': st.st_size, 'mtime': st.st_mtime, 'weight': cfg['weight'],
                'index': cfg['index'], 'charset': hashlib.sha1(cs.encode('utf-8')).hexdigest()[:12],
                'simfree': bool(simfree), 'ver': 1}
        old = _load_json(out)
        if old and old.get('meta') == meta:
            return len(old.get('glyphs') or {})
        font = ImageFont.truetype(cfg['path'], fp.SIZE, index=cfg['index'])
        band = fp.band_of(font, cfg['weight'])
        glyphs, missing = {}, []
        for ch in cs:
            nodaku = simfree and (ch in SIMFREE_EXCLUDE or any(u in __import__('unicodedata').normalize('NFD', ch) for u in ('\u3099', '\u309a')))
            if nodaku or not fp._has(font, ch) or band is None:
                missing.append(ch)
                continue
            b = fp.render_cell(font, ch, band, cfg['weight'])
            if b is None or not glyph_like(b, ch):
                missing.append(ch)
                continue
            glyphs[ch] = _bits(b)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + '.tmp'
        json.dump({'meta': meta, 'glyphs': glyphs, 'missing': ''.join(missing)}, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
        os.replace(tmp, out)
        if verbose:
            print(f'補助見本: {len(glyphs)} 文字（フォントに無い {len(missing)} 文字）')
        return len(glyphs)
    except Exception as e:
        if verbose:
            print('補助見本を作れません:', e)
        return 0


def learn_line(mask_img, text, stage=None):
    """Add templates from one line whose correct text is known. Only when the number of cut characters equals the
    number of characters (spaces ignored), so a bad cut never spoils the templates. Returns the number added."""
    text = ''.join(text.split())
    a = ink(mask_img)
    cols, band = segment(a)
    if not cols or len(cols) != len(text):
        return 0
    if stage is not None:          # collected first, checked against each other, written by write_stage()
        cs = [(ch, cell(a, x0, x1, band)) for (x0, x1), ch in zip(cols, text)]
        stage.append([(ch, b) for ch, b in cs if glyph_like(b, ch)])
        return len(text)
    try:
        d = json.load(open(TPL_P, encoding='utf-8'))
    except Exception:
        d = {}
    added = 0
    for (x0, x1), ch in zip(cols, text):
        b = cell(a, x0, x1, band)
        if not glyph_like(b, ch):
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
    flat = [(i, ch, b) for i, cells in enumerate(stage) for ch, b in cells if glyph_like(b, ch)]
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
            if not glyph_like(b, ch):
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


def _truth(png_path, ocr):
    """What the game printed in this crop. Returns (status, lines, counts, cands, sentence): status 'nosentence' (no
    candidate), 'lines' (no / too many lines), 'fit' (sentence = the candidate that matches the cut and the read) or
    'nofit' (candidates exist but none fits; tail_learn may still use lines / counts / cands)."""
    import difflib
    import msgparse as mp
    cands = sentence_candidates(ocr)
    if not cands:
        return 'nosentence', None, None, None, None
    lines = split_lines(Image.open(png_path))
    if not lines or len(lines) > 3:
        return 'lines', None, None, cands, None
    counts = [len(segment(ink(l))[0]) for l in lines]
    fit = [c for c in cands if len(c) == sum(counts)]
    body = mp.apply_fixes(mp.norm(ocr)).replace('/', '')
    sim = lambda c: difflib.SequenceMatcher(None, body, c).ratio()
    fit = sorted((c for c in fit if sim(c) >= 0.45), key=lambda c: -sim(c))     # same length, different sentence: the read decides
    return ('fit' if fit else 'nofit'), lines, counts, cands, (fit[0] if fit else None)


def _crops(d):
    out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith('.png'):
            try:
                ocr = json.load(open(os.path.join(d, f[:-4] + '.json'), encoding='utf-8')).get('ocr') or ''
            except Exception:
                continue
            out.append((f, os.path.join(d, f), ocr))
    return out


def build(verbose=True):
    """Templates from the saved crops: the OCR text of each crop is turned into the sentence the game printed
    (sentence_candidates); the candidate whose length equals the number of characters cut from the picture is used.
    Misread / unrecognised crops are left out. The reasons for skipped crops are counted and printed."""
    why = {'crop数': 0, '文を作れない': 0, '2行・空など': 0, '文字数が合わない': 0, '追加した行': 0}
    shown = 0
    stage = []
    for f, path, ocr in _crops(CROPS):
        why['crop数'] += 1
        st, lines, counts, cands, sent = _truth(path, ocr)
        if st == 'nosentence':
            why['文を作れない'] += 1
        elif st == 'lines':
            why['2行・空など'] += 1
        elif st == 'fit':
            i = 0
            for l, n in zip(lines, counts):
                learn_line(l, sent[i:i + n], stage)
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


def evaluate(crops_dir=None, cfg=None, folds=2, templates=None, simfree=False, out_json=None):
    """Compare ways of reading the message box on saved crops whose sentence is known (see _truth): the Windows OCR,
    the real templates as now, real templates alone, real + font seeds, and real + seeds + the adoption rule. Real
    templates are built on the other folds into a temp file (data/glyph_templates.json is not touched); with
    templates=PATH that file is used as it is. Prints a table; out_json saves the numbers."""
    import difflib, tempfile, time
    global TPL_P, SEED_P
    items = []
    for f, path, ocr in _crops(crops_dir or os.path.join(HERE, '..', 'logs', 'sessions', 'msgcrops')):
        st, lines, counts, cands, sent = _truth(path, ocr)
        if st == 'fit':
            items.append({'f': f, 'path': path, 'ocr': ocr, 'lines': lines, 'counts': counts, 'T': sent})
    print(f'正解のある crop: {len(items)} 枚')
    if not items:
        return None
    cfg = cfg or font_config()
    save_tpl, save_seed = TPL_P, SEED_P
    tmpd = tempfile.mkdtemp()
    R = {m: {'ok': 0, 'tot': 0, 'lines': 0, 'n': 0} for m in ('OCR', '今の方式', '実戦のみ(素)', '補助あり(素)', '補助あり+採用条件')}
    seed_chars = seed_err = adopt_chars = adopt_err = 0
    why_n, ms, adopted, tried = {}, [], 0, 0
    miss_cnt, bad_chars, bad_crops = {}, 0, 0
    try:
        if cfg:
            SEED_P = os.path.join(tmpd, 'seed.json')
            make_seed(cfg, out=SEED_P, verbose=False, simfree=simfree)
            missing = set((_load_json(SEED_P) or {}).get('missing') or '')
        else:
            SEED_P = os.path.join(tmpd, 'none.json')
            missing = set()
            print('フォントなし: 補助ありの列は評価しません')
        for fo in range(1 if templates else folds):
            test = items if templates else [x for i, x in enumerate(items) if i % folds == fo]
            if templates:
                TPL_P = templates
            else:
                stage = []
                for x in (y for i, y in enumerate(items) if i % folds != fo):
                    i0 = 0
                    for l, n in zip(x['lines'], x['counts']):
                        learn_line(l, x['T'][i0:i0 + n], stage); i0 += n
                TPL_P = os.path.join(tmpd, f'tpl{fo}.json')
                if os.path.exists(TPL_P):
                    os.remove(TPL_P)
                write_stage(stage)
            _TPL['mtime'] = None
            _TPLS['key'] = None
            real_set = set(load()['chars'])
            for x in test:
                T = x['T']
                mask = Image.open(x['path'])
                ocr_t = _k(x['ocr'])
                cur_gate = _gate(load(), False)
                real = read_box(mask, detail=True, gate=False)
                now = real['text'].replace(' ', '') if (cur_gate and real and real['low'] >= ACCEPT) else ocr_t
                d = None
                if cfg:
                    t0 = time.perf_counter()
                    d = read_box(mask, seed=True, detail=True, gate=False)
                    ms.append((time.perf_counter() - t0) * 1000)
                preds = {'OCR': ocr_t, '今の方式': now,
                         '実戦のみ(素)': (real['text'].replace(' ', '') if real else ocr_t),
                         '補助あり(素)': (d['text'].replace(' ', '') if d else None)}
                fin = now
                if d is not None and not (cur_gate and real and real['low'] >= ACCEPT):
                    tpl = load(True)
                    if _gate(tpl, True):
                        tried += 1
                        ok, why = adopt_seed(d, x['ocr'], why=True)
                        why_n[why] = why_n.get(why, 0) + 1
                        if ok:
                            adopted += 1
                            fin = d['text'].replace(' ', '')
                            for i, c in enumerate(d['chars']):
                                if c['seed']:
                                    adopt_chars += 1
                                    adopt_err += (i < len(T) and T[i] != c['ch'])
                preds['補助あり+採用条件'] = fin if cfg else None
                for m, pr in preds.items():
                    if pr is None:
                        continue
                    sm = difflib.SequenceMatcher(None, T, pr)
                    R[m]['ok'] += sum(b.size for b in sm.get_matching_blocks())
                    R[m]['tot'] += len(T)
                    R[m]['lines'] += (pr == T)
                    R[m]['n'] += 1
                if d is not None:
                    bad_here = False
                    for i, c in enumerate(d['chars']):
                        wrong = i >= len(T) or T[i] != c['ch']
                        if c['seed']:
                            seed_chars += 1
                            seed_err += wrong
                        if wrong:
                            ch = T[i] if i < len(T) else ''
                            if ch and ch not in real_set and ch in missing:
                                miss_cnt[ch] = miss_cnt.get(ch, 0) + 1
                                bad_chars += 1
                                bad_here = True
                    bad_crops += bad_here
    finally:
        TPL_P, SEED_P = save_tpl, save_seed
        _TPL['mtime'] = None
        _TPLS['key'] = None
    print('\n方式                    文字一致率  行の完全一致')
    for m, r in R.items():
        if r['n']:
            print(f"  {m:<20} {r['ok'] / max(1, r['tot']):6.1%}   {r['lines'] / r['n']:6.1%}")
    res = {'crops': len(items), 'methods': {m: {'char': r['ok'] / max(1, r['tot']), 'line': r['lines'] / max(1, r['n'])}
                                          for m, r in R.items() if r['n']}}
    if cfg:
        print(f'\n補助見本で読んだ文字: {seed_chars} / 誤読 {seed_err}（{seed_err / max(1, seed_chars):.1%}）'
              f'  採用された crop 内: {adopt_chars} 文字 / 誤読 {adopt_err}（{adopt_err / max(1, adopt_chars):.1%}）')
        print(f'採用: {adopted} / {tried} crop（落ちた条件 {why_n}）')
        miss_sorted = sorted(miss_cnt.items(), key=lambda kv: -kv[1])
        print('フォントに無くて読めなかった文字: ' + (' '.join(f'{c}×{n}' for c, n in miss_sorted[:20]) or 'なし'))
        A = bad_chars / max(1, seed_err + bad_chars)      # share of wrong characters (seed run) the font lacks
        B = bad_crops / len(items)
        print(f'  割合A（読み取り失敗のうちフォントの欠け）= {A:.0%} / 割合B（その欠けで読み切れない crop）= {B:.0%}')
        print(f'処理時間（補助ありの読み取り1回）: 平均 {sum(ms) / max(1, len(ms)):.1f}ms / 最大 {max(ms) if ms else 0:.1f}ms')
        res.update(seed_chars=seed_chars, seed_err=seed_err, adopt_chars=adopt_chars, adopt_err=adopt_err, adopted=adopted,
                   tried=tried, why=why_n, missing=dict(miss_sorted), A=A, B=B,
                   ms_avg=sum(ms) / max(1, len(ms)), ms_max=max(ms) if ms else 0)
    if out_json:
        json.dump(res, open(out_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


def stats():
    t = load()
    print(f"見本: {len(t['chars'])} 個 / {len(set(t['chars']))} 文字（{MIN_CHARS} 文字を超えると読み取りに使います）")
    sd = _load_json(SEED_P)
    if sd:
        g = set(sd.get('glyphs') or {})
        real = set(t['chars'])
        print(f"補助見本: {len(g)} 文字（実戦と重なるので使わない {len(g & real)} 文字 / フォントに無い {len(sd.get('missing') or '')} 文字）"
              f" フォント {sd.get('meta', {}).get('font')}")
    else:
        print('補助見本: なし（POKECHAMP_FONT か data/font_seed.json を設定して python glyph_ocr.py seed）')


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
    elif a[:1] == ['purge']:
        d = json.load(open(TPL_P, encoding='utf-8'))
        n = 0
        for ch in list(d):
            keep = [x for x in d[ch] if glyph_like(_arr(x), ch)]
            n += len(d[ch]) - len(keep)
            d[ch] = keep
            if not keep:
                del d[ch]
        json.dump(d, open(TPL_P, 'w', encoding='utf-8'), ensure_ascii=False)
        print(f'{n} 個の見本（文字に見えないもの）を除きました')
    elif a[:1] == ['build']:
        build()
    elif a[:1] in (['seed'], ['eval']):
        opt = lambda k, dv=None: a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else dv
        cfg = None
        if opt('--font'):
            cfg = {'path': opt('--font'), 'weight': int(opt('--weight', 0)), 'index': int(opt('--index', 0))}
        elif opt('--weight') is not None and font_config():
            cfg = dict(font_config(), weight=int(opt('--weight')))
        if a[0] == 'seed':
            n = make_seed(cfg, verbose=True)
            print('作れませんでした（フォント未設定か開けません）' if not n else f'{n} 文字を {SEED_P} に保存しました')
        else:
            evaluate(opt('--crops'), cfg, int(opt('--folds', 2)), opt('--templates'), '--simulate-free' in a, opt('--json'))
    else:
        stats()


if __name__ == '__main__':
    main()
