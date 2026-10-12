"""HP欄の数字（斜体）をテンプレート照合で読む。OCR は斜体の数字を読み違える（136/157 → 7365/ など）ため。

  read_hp(panel_crop, side) -> 相手: 0〜100（%） / 自分: (現在HP, 最大HP)。読めなければ None
テンプレートは data/hp_digits.json（数字ごとに 10x14 の白黒パターンを複数）。録画から集めて登録した。
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
TPL_P = os.path.join(HERE, 'data', 'hp_digits.json')
FW, FH = 10, 14
# where the number is inside each panel crop (fractions): x from, x to, y from, y to
ZONE = {'opp': (0.55, 0.95, 0.55, 0.92), 'me': (0.36, 0.88, 0.45, 0.88)}
try:
    TPL = json.load(open(TPL_P, encoding='utf-8'))
except Exception:
    TPL = {}
_T = None


def white(img):
    import numpy as np
    f = np.asarray(img.convert('RGB'), dtype=np.int16)
    mn, mx = f.min(2), f.max(2)
    return (mn > 185) & (mx - mn < 60)


def components(mask):
    """Connected white blobs: list of (x0, y0, x1, y1, pixels) (4-neighbours)."""
    H, W = mask.shape
    seen = mask.copy()
    out = []
    for y in range(H):
        for x in range(W):
            if not seen[y, x]:
                continue
            stack, pts = [(y, x)], []
            seen[y, x] = False
            while stack:
                cy, cx = stack.pop()
                pts.append((cy, cx))
                for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if 0 <= ny < H and 0 <= nx < W and seen[ny, nx]:
                        seen[ny, nx] = False
                        stack.append((ny, nx))
            ys = [p[0] for p in pts]; xs = [p[1] for p in pts]
            out.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1, pts))
    return out


def feature(c):
    import numpy as np
    x0, y0, x1, y1, pts = c
    w, h = x1 - x0, y1 - y0
    g = np.zeros((h, w), dtype=np.uint8)
    for y, x in pts:
        g[y - y0, x - x0] = 1
    from PIL import Image
    im = Image.fromarray(g * 255).resize((FW, FH))
    return (np.asarray(im) > 100).astype(np.uint8).flatten()


def glyphs(panel, side):
    """The digit-like blobs of the number, left to right: [(x0, y0, x1, y1, feature)]."""
    W, H = panel.size
    zx0, zx1, zy0, zy1 = ZONE[side]
    box = (int(W * zx0), int(H * zy0), int(W * zx1), int(H * zy1))
    m = white(panel.crop(box))
    cs = [c for c in components(m) if c[3] - c[1] >= 6 and len(c[4]) >= 12]
    if not cs:
        return []
    top = max(c[3] - c[1] for c in cs)
    cs = [c for c in cs if c[3] - c[1] >= top * 0.45]
    cs.sort(key=lambda c: c[0])
    return [(c[0], c[1], c[2], c[3], feature(c)) for c in cs]


def _templates():
    global _T
    if _T is None:
        import numpy as np
        _T = [(d, np.array([int(ch) for ch in s], dtype=np.uint8)) for d, lst in TPL.items() for s in lst]
    return _T


def classify(f):
    """(label, distance) of the closest template; label is '0'..'9', '/', '%' or None."""
    best = (None, 1e9)
    for d, t in _templates():
        dist = int((f != t).sum())
        if dist < best[1]:
            best = (d, dist)
    return best


def read_hp(panel, side, max_dist=22):
    gs = glyphs(panel, side)
    if not gs or not TPL:
        return None
    labs = []
    for x0, y0, x1, y1, f in gs:
        d, dist = classify(f)
        if d == '_':
            continue            # a piece of the bar / panel edge / light, not part of the number
        if d is None or dist > max_dist:
            return None
        labs.append((d, y1 - y0))
    if side == 'opp':
        s = ''.join(d for d, _ in labs if d.isdigit())
        if not s or len(s) > 3 or int(s) > 100:
            return None
        return int(s)
    # ours: 「cur /max」 with the current HP in big digits and the maximum in small ones (the thin 「/」 may be lost)
    digs = [(d, h) for d, h in labs if d.isdigit()]
    if not digs:
        return None
    top = max(h for _, h in digs)
    big = ''.join(d for d, h in digs if h >= top * 0.8)
    small = ''.join(d for d, h in digs if h < top * 0.8)
    if not big or len(small) < 2 or len(big) > 3 or len(small) > 3 or int(big) > int(small):
        return None
    return int(big), int(small)


def learn(panel, side, value):
    """Add the glyphs of a panel whose number is known (value: '80' / '136/157') to the templates."""
    gs = [g for g in glyphs(panel, side) if classify(g[4])[0] != '_']
    digits = [ch for ch in str(value) if ch.isdigit()]
    if len(gs) != len(digits):
        return 0
    n = 0
    for g, ch in zip(gs, digits):
        s = ''.join(str(int(v)) for v in g[4])
        if s not in TPL.setdefault(ch, []):
            TPL[ch].append(s); n += 1
    json.dump(TPL, open(TPL_P, 'w', encoding='utf-8'))
    global _T
    _T = None
    return n


if __name__ == '__main__':
    # python hpdigits.py <画面の画像> [--learn-me 136/157] [--learn-opp 80]
    import sys
    from PIL import Image
    sys.path.insert(0, HERE)
    import game_watch as G
    img = Image.open(sys.argv[1]).convert('RGB').resize((1280, 720))
    for side, box in (('me', G.MY_PANEL), ('opp', G.OPP_PANEL)):
        pc = G._crop(img, box)
        if f'--learn-{side}' in sys.argv:
            print(side, '学習:', learn(pc, side, sys.argv[sys.argv.index(f'--learn-{side}') + 1]), '個')
        print(side, '表示あり' if G.panel_present(pc, side) else '表示なし', '読み:', read_hp(pc, side))
