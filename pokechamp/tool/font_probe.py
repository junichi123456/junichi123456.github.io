"""ゲームの文字と、あるフォントがどれくらい近いかを数字にする（ニタラゴルイカなど候補フォントの比較用）。

  python font_probe.py <フォントファイル> [<フォントファイル> ...] [--templates data/glyph_templates.json] [--worst 15]

比べる相手は、実際のゲーム画面から集めた文字の見本（glyph_ocr.py が作る data/glyph_templates.json）。
各フォントで同じ文字を描き、見本と同じ正規化（行の高さ基準・正方形・24x24）にして重なりを測る。
  近似度     … 同じ文字どうしの重なり（0〜1。高いほど字形が近い）
  正答率     … そのフォントで描いた文字を、見本の全文字の中から探したとき、正しい文字が1位になる割合
               （高いほど、そのフォントを見本の代わりに使っても文字を取り違えにくい）
  弱い文字   … 近似度が低い文字（フォントに無い文字は「無し」）
見本が少ないうちは数字が安定しません（目安: 100文字以上）。濁音（が・ぎ・ば…）の有無もここで分かります。
Windows に入っている meiryo / msgothic も比較に出します（見つかれば）。
"""
import json, os, sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import glyph_ocr as G

HERE = os.path.dirname(os.path.abspath(__file__))
REF = 'ガブリアスのじしんがぐーんと上がったミミッキュ'     # tall and short characters: sets the text band
BASELINES = ('C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/YuGothB.ttc')
SIZE = 96


def _font(path):
    try:
        return ImageFont.truetype(path, SIZE)
    except Exception:
        return None


def _has(font, ch):
    """The font really draws this character (not an empty box / the missing-glyph box)."""
    try:
        m = font.getmask(ch)
        miss = font.getmask('\uffff')
        return m.getbbox() is not None and (m.size != miss.size or bytes(m) != bytes(miss))
    except Exception:
        return False


def _ink(font, ch, stroke=0):
    im = Image.new('L', (SIZE * 2, SIZE * 2), 0)
    ImageDraw.Draw(im).text((SIZE // 2, SIZE // 2), ch, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    return np.asarray(im) > 110


def band_of(font, stroke=0):
    ys = []
    for c in REF:
        a = _ink(font, c, stroke)
        r = np.where(a.any(axis=1))[0]
        if len(r):
            ys.append((r[0], r[-1] + 1))
    if not ys:
        return None
    return int(min(y[0] for y in ys)), int(max(y[1] for y in ys))


def render_cell(font, ch, band, stroke=0):
    """The character as glyph_ocr.cell() would cut it from a line drawn in this font."""
    a = _ink(font, ch, stroke)
    cols = np.where(a.any(axis=0))[0]
    if not len(cols):
        return None
    return G.cell(a, int(cols[0]), int(cols[-1]) + 1, band)


def score(b, mat, matd):
    v = b.reshape(-1)
    vd = G._dilate(b).reshape(-1)
    cov_t = (mat & vd).sum(axis=1) / np.maximum(1, mat.sum(axis=1))
    cov_g = (matd & v).sum(axis=1) / max(1, v.sum())
    return np.minimum(cov_t, cov_g)


def probe(path, tpl, worst=15):
    font = _font(path)
    if font is None:
        print(f'{path}: 開けません')
        return None
    band = band_of(font)
    mat, matd, chars = tpl['mat'], tpl['matd'], np.array(tpl['chars'])
    per, top1, missing = {}, 0, []
    uniq = sorted(set(tpl['chars']))
    for ch in uniq:
        if not _has(font, ch):
            missing.append(ch)
            continue
        b = render_cell(font, ch, band)
        if b is None or band is None:
            missing.append(ch)
            continue
        sc = score(b, mat, matd)
        own = sc[chars == ch]
        per[ch] = float(own.max())
        best = chars[int(sc.argmax())]
        top1 += best == ch
    n = len(per)
    print(f'\n== {os.path.basename(path)}  （見本のある {len(uniq)} 文字中、描ける {n} 文字）')
    if not n:
        return None
    mean = sum(per.values()) / n
    print(f'近似度 {mean:.2f}   正答率 {top1 / n:.0%}   フォントに無い文字 {len(missing)}')
    ws = sorted(per.items(), key=lambda x: x[1])[:worst]
    print('弱い文字: ' + ' '.join(f'{c}({s:.2f})' for c, s in ws))
    if missing:
        print('無し: ' + ''.join(missing[:60]))
    return mean, top1 / n


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv[1:]
    worst = 15
    if '--worst' in a:
        i = a.index('--worst'); worst = int(a[i + 1]); del a[i:i + 2]
    if '--templates' in a:
        i = a.index('--templates'); G.TPL_P = a[i + 1]; del a[i:i + 2]
    tpl = G.load()
    if tpl['mat'] is None:
        print('文字の見本がありません。先に実戦で見本を溜めてください（python glyph_ocr.py stats で数を確認）。')
        return 1
    fonts = [x for x in a if not x.startswith('--')]
    G_n = len(set(tpl['chars']))
    print(f'見本: {len(tpl["chars"])} 個 / {G_n} 文字' + ('  ※100文字未満: 数字は目安' if G_n < 100 else ''))
    res = {}
    for p in fonts + [b for b in BASELINES if os.path.exists(b) and b not in fonts]:
        r = probe(p, tpl, worst)
        if r:
            res[os.path.basename(p)] = r
    if len(res) > 1:
        print('\n--- まとめ（近似度 / 正答率）')
        for k, (m, t) in sorted(res.items(), key=lambda x: -x[1][0]):
            print(f'  {k}: {m:.2f} / {t:.0%}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
