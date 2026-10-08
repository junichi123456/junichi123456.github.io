"""選出画面（見せ合い）の相手6体を特定する補助。

選出画面では相手のポケモン名が表示されず、3Dモデルの小さな絵とタイプアイコンだけが出る。
  1. 右列6枠のタイプアイコンを、白い記号の形（data/type_glyphs.json）と照合してタイプを読む
     ※ 色ではなく形で判定する（例: どく=紫地に「丘と丸」、むし=黄緑地の記号 は見間違えやすい）
  2. そのタイプ構成の使用可能ポケモンを使用率順に並べ、PokeAPI の HOME 3Dモデル画像と
     枠の絵を並べた照合シート（identify_sheet.png）を作る → Claude が見比べて確定する

  python identify.py <選出画面の画像> [--out 出力画像]
出力: 各枠のタイプ判定と候補（使用率順、色の近さ順位つき）、照合シート画像のパス
"""
import argparse, json, math, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from calc import POKE, JT  # noqa: E402

GLYPH = json.load(open(os.path.join(HERE, 'data', 'type_glyphs.json'), encoding='utf-8'))
N = GLYPH['size']
CACHE = os.path.join(HERE, 'data', 'home_cache')

# 16:9 の選出画面（1280x720 実機キャプチャで計測）における相手6枠の位置（画面幅・高さに対する割合）
SLOT_Y0, SLOT_DY, SLOT_H = 0.143, 0.1167, 0.107
SPRITE_X = (0.838, 0.907)
ICON_X = [(0.9094, 0.9336), (0.9367, 0.9609)]
ICON_Y_OFF, ICON_H = 0.0098, 0.0486


def usage_rank(n):
    try:
        import sets
        return sets.usage_rank(n)
    except Exception:
        return 300


GAME_GLYPH_P = os.path.join(HERE, 'data', 'type_glyphs_game.json')
try:
    GAME_GLYPH = json.load(open(GAME_GLYPH_P, encoding='utf-8'))
except FileNotFoundError:
    GAME_GLYPH = {}
# templates per type: op.gg glyph + glyphs captured from real game screens (learned with --learn)
TEMPLATES = [(t, int(s, 2)) for t, s in GLYPH['glyphs'].items()] + \
            [(t, int(b, 2)) for t, lst in GAME_GLYPH.items() for b in lst]


def white_mask(img):
    g = img.convert('RGB').resize((N, N))
    data = g.get_flattened_data() if hasattr(g, 'get_flattened_data') else g.getdata()
    v = 0
    for r, gg, b in data:
        v = (v << 1) | (1 if (r > 165 and gg > 165 and b > 165 and max(r, gg, b) - min(r, gg, b) < 60) else 0)
    return v


def match_type(icon):
    m = white_mask(icon)
    if bin(m).count('1') < N * N * 0.04:
        return None, 0.0
    best, bs = None, -1.0
    for t, gv in TEMPLATES:
        u = bin(m | gv).count('1')
        iou = bin(m & gv).count('1') / u if u else 0
        if iou > bs:
            best, bs = t, iou
    return best, bs


def read_slots(img, dx=0.0, dy=0.0, sx=1.0, sy=1.0, sprites=True):
    """Read the 6 slots with the layout mapped as p' = d + s*p (fractions of the frame)."""
    W, H = img.size
    X = lambda f: int((dx + sx * f) * W)
    Y = lambda f: int((dy + sy * f) * H)
    out, score = [], 0.0
    for i in range(6):
        y0 = SLOT_Y0 + SLOT_DY * i
        spr = img.crop((X(SPRITE_X[0]), Y(y0), X(SPRITE_X[1]), Y(y0 + SLOT_H))) if sprites else None
        iy = y0 + ICON_Y_OFF
        types = []
        for x0, x1 in ICON_X:
            t, sc = match_type(img.crop((X(x0), Y(iy), X(x1), Y(iy + ICON_H))))
            if t and sc >= 0.3:
                types.append((t, round(sc, 2)))
                score += sc
        out.append((spr, types))
    return out, score


def trim(img):
    """Cut off black/flat borders around the game picture (letterbox, capture margins)."""
    g = img.convert('L')
    W, H = g.size
    px = g.load()
    def busy_row(y):
        return sum(1 for x in range(0, W, 8) if px[x, y] > 30) > W / 8 * 0.3
    def busy_col(x):
        return sum(1 for y in range(0, H, 8) if px[x, y] > 30) > H / 8 * 0.3
    top = next((y for y in range(H) if busy_row(y)), 0)
    bot = next((y for y in range(H - 1, -1, -1) if busy_row(y)), H - 1)
    left = next((x for x in range(W) if busy_col(x)), 0)
    right = next((x for x in range(W - 1, -1, -1) if busy_col(x)), W - 1)
    if right - left > W * 0.6 and bot - top > H * 0.6:
        return img.crop((left, top, right + 1, bot + 1))
    return img


def slots(img):
    """Read the 6 opponent slots. The capture framing (borders, crop, scaling) can differ from the
    reference, so search offset/scale coarse-to-fine and keep the layout whose icons match best."""
    small = img.resize((640, int(640 * img.height / img.width)))
    best = (0.0, 0.0, 1.0, 1.0, -1.0)
    # the frame is already trimmed to the game picture, so only small corrections are searched
    for sx in (0.99, 1.0, 1.01):
        for sy in (0.97, 0.985, 1.0, 1.015, 1.03):
            for dy in [x / 1000 for x in range(-30, 31, 5)]:
                for dx in [x / 1000 for x in range(-10, 11, 5)]:
                    sc = read_slots(small, dx, dy, sx, sy, False)[1] - 2 * (abs(dx) + abs(dy))
                    if sc > best[4]:
                        best = (dx, dy, sx, sy, sc)
    slots.layout = best[:4]
    return read_slots(img, *best[:4])[0]


def candidates(types):
    want = set(types)
    rows = []
    for n, p in POKE.items():
        if p.get('champ') and set(p['types']) == want and not (p.get('form') and 'mega' in p['form']) \
                and p.get('form') not in ('blade',):
            rows.append((usage_rank(n), n, p['id']))
    rows.sort()
    return rows


def home_image(pid):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f'{pid}.png')
    if not os.path.exists(path):
        url = f'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/home/{pid}.png'
        try:
            urllib.request.urlretrieve(url, path)
        except Exception:
            return None
    try:
        return Image.open(path).convert('RGBA')
    except Exception:
        return None


def color_sig(img, mask_bg=True):
    """Hue histogram of the sprite's non-background pixels (rough colour signature)."""
    im = img.convert('RGBA').resize((48, 48))
    hist = [0.0] * 12
    tot = 0
    for r, g, b, a in (im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()):
        if a < 128:
            continue
        if mask_bg and r > 110 and g < 60 and b > 30:  # crimson card background
            continue
        mx, mn = max(r, g, b), min(r, g, b)
        if mx < 40:
            k = 11  # dark
        elif mx - mn < 30:
            k = 10  # grey/white
        else:
            if mx == r:
                h = ((g - b) / (mx - mn)) % 6
            elif mx == g:
                h = (b - r) / (mx - mn) + 2
            else:
                h = (r - g) / (mx - mn) + 4
            k = int(h / 6 * 10) % 10
        hist[k] += 1
        tot += 1
    return [x / tot for x in hist] if tot else hist


def sim(a, b):
    return sum(min(x, y) for x, y in zip(a, b))


def font(size):
    for f in ('C:/Windows/Fonts/meiryo.ttc', 'C:/Windows/Fonts/msgothic.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def learn(img, labels):
    """Store the icon glyphs of a real screen under their correct types."""
    rev = {v: k for k, v in JT.items()}
    slots(img)
    dx, dy, sx, sy = slots.layout
    W, H = img.size
    X = lambda f: int((dx + sx * f) * W)
    Y = lambda f: int((dy + sy * f) * H)
    added = 0
    for i, lab in enumerate(labels):
        ts = [rev.get(t, t) for t in lab.split('/')]
        iy = SLOT_Y0 + SLOT_DY * i + ICON_Y_OFF
        boxes = [ICON_X[1]] if len(ts) == 1 else ICON_X
        for t, (x0, x1) in zip(ts, boxes):
            m = white_mask(img.crop((X(x0), Y(iy), X(x1), Y(iy + ICON_H))))
            b = format(m, f'0{N * N}b')
            lst = GAME_GLYPH.setdefault(t, [])
            if b not in lst:
                lst.append(b); added += 1
    json.dump(GAME_GLYPH, open(GAME_GLYPH_P, 'w', encoding='utf-8'))
    print(f'{added} 個のアイコンを学習しました（{len(GAME_GLYPH)} タイプ）')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--out', default=None)
    ap.add_argument('--k', type=int, default=10)
    ap.add_argument('--learn', nargs=6, metavar='TYPES',
                    help='正解のタイプを6枠分（例: むし/みず じめん エスパー/ノーマル ...）指定してアイコンを学習')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    img = trim(Image.open(a.image).convert('RGB'))
    if a.learn:
        learn(img, a.learn)
        return
    res = slots(img)
    T = 150
    sheet = Image.new('RGB', (T * (a.k + 1), T * 6), 'white')
    d = ImageDraw.Draw(sheet)
    f = font(16)
    for i, (spr, types) in enumerate(res):
        sp = spr.resize((T, int(T * spr.height / spr.width)))
        sheet.paste(sp, (0, i * T))
        tnames = [t for t, _ in types]
        cands = candidates(tnames) if tnames else []
        sig = color_sig(spr)
        scored = []
        for r, n, pid in cands[:30]:
            h = home_image(pid)
            scored.append((sim(sig, color_sig(h, False)) if h else 0, r, n, pid, h))
        by_color = sorted(scored, key=lambda x: -x[0])
        # show the colour-closest candidates first so the right one is never cut off
        order = by_color[:a.k]
        jt = '・'.join(JT[t] for t in tnames) or '不明'
        print(f"枠{i + 1}: タイプ={jt} {types}  色が近い順: " + '、'.join(n for _, _, n, _, _ in by_color[:3]))
        print('   候補(色の近い順・使用率): ' + '、'.join(f'{j + 1}.{n}({r if r < 300 else "圏外"}位)' for j, (_, r, n, _, _) in enumerate(order)))
        d.text((4, i * T + 2), f'{i + 1} {jt}', fill='black', font=f)
        for j, (_, r, n, pid, h) in enumerate(order):
            if h:
                hh = h.resize((T - 20, T - 20))
                sheet.paste(hh, (T * (j + 1) + 10, i * T + 4), hh)
            d.text((T * (j + 1) + 4, i * T + T - 22), f'{j + 1}.{n}', fill='black', font=f)
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.image)), 'identify_sheet.png')
    sheet.save(out)
    print('照合シート:', os.path.normpath(out))


if __name__ == '__main__':
    main()
