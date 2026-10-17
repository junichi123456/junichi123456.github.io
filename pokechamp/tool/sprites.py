"""選出画面の相手6枠の絵（3Dモデルの小さな絵）を覚えて、次から一致した枠を即座に特定する。

  python sprites.py remember <選出画面の画像> <枠1の名前> ... <枠6の名前>   6体を記憶する（上の枠から順）
  python sprites.py match <選出画面の画像>                                  記憶と照合して各枠の候補を出す
記憶は data/sprite_memory.json（種族ごとに最大12個の特徴量）。枠の位置は右列のマゼンタ色の枠を探して決めるので、
キャプチャの余白や拡大率が違っても動く。
"""
import json, os, sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
MEM_P = os.path.join(HERE, 'data', 'sprite_memory.json')
FEAT = 24          # feature thumbnail size
KEEP = 12          # features kept per species
MATCH, MARGIN = 0.80, 0.05


def _magenta(a):
    r, g, b = a[..., 0].astype(int), a[..., 1].astype(int), a[..., 2].astype(int)
    return (r > 60) & (g < 45) & (b > 12) & (r > b * 1.4) & (r < 230)


def panels(img):
    """The six opponent panels in the right column: [(x0, y0, x1, y1), ...] top to bottom (pixels)."""
    W, H = img.size
    xs = int(W * 0.76)
    a = np.asarray(img.convert('RGB'))[:, xs:]
    m = _magenta(a)
    rows = m.mean(axis=1) > 0.30
    runs, s = [], None
    for y, v in enumerate(rows):
        if v and s is None:
            s = y
        if (not v or y == len(rows) - 1) and s is not None:
            e = y if not v else y + 1
            if e - s > H * 0.04:
                runs.append((s, e))
            s = None
    # panels are evenly spaced: take the spacing and height from the clean ones (a highlight band can hide part
    # of one panel) and lay out all six from the first
    runs = [r for r in runs if r[1] - r[0] < H * 0.2]
    if len(runs) < 4:
        return []
    hts = sorted(r[1] - r[0] for r in runs)
    h = hts[len(hts) // 2]
    full = [r for r in runs if r[1] - r[0] >= h * 0.85]
    steps = sorted(b[0] - a[0] for a, b in zip(full, full[1:]) if b[0] - a[0] < h * 1.6)
    if not steps:
        return []
    pitch = steps[len(steps) // 2]
    top = full[0][0]
    while top - pitch > -h * 0.2 and any(abs((top - pitch) - r[0]) < h * 0.3 for r in runs):
        top -= pitch
    # a panel above the first found one can be hidden by the highlight band (green triangles / lit panel): look at the
    # colour of the strip itself, else all six boxes sit one slot too low and every name is read off the wrong picture
    cols0 = np.where(m[full[0][0]:full[0][1]].mean(axis=0) > 0.3)[0]
    if len(cols0):
        c0, c1 = int(cols0[0]) + int((cols0[-1] - cols0[0]) * 0.5), int(cols0[-1])
        while top - pitch >= -h * 0.1 and m[max(0, top - pitch):top - pitch + h, c0:c1].mean() > 0.35:
            top -= pitch
    ys = [(int(top + i * pitch), int(top + i * pitch + h)) for i in range(6)]
    cols = np.where(m[full[0][0]:full[0][1]].mean(axis=0) > 0.3)[0]
    if not len(cols):
        return []
    x0, x1 = xs + int(cols[0]), xs + int(cols[-1])
    return [(x0, y0, x1, min(y1, H)) for y0, y1 in ys]


def sprite_boxes(img):
    """Where the picture sits in each panel: the left ~55% (the type icons and gender mark are on the right)."""
    return [(x0, y0, x0 + int((x1 - x0) * 0.55), y1) for x0, y0, x1, y1 in panels(img)]


def feature(crop):
    a = np.asarray(crop.convert('RGB').resize((FEAT, FEAT)), dtype=np.float32)
    bg = _magenta(a.astype(np.uint8))
    a[bg] = 0.0
    v = a.reshape(-1, 3)
    fg = ~bg.reshape(-1)
    if fg.sum() < 20:
        return None
    v = v - v[fg].mean(axis=0)
    v[~fg] = 0.0
    v = v.reshape(-1)
    n = np.linalg.norm(v)
    return (v / n).astype(np.float32) if n else None


def load():
    try:
        return json.load(open(MEM_P, encoding='utf-8'))
    except Exception:
        return {}


def remember(img, names):
    mem = load()
    boxes = sprite_boxes(img)
    if len(boxes) != 6:
        return 0
    added = 0
    for (x0, y0, x1, y1), n in zip(boxes, names):
        if not n or n in ('?', '-'):
            continue
        f = feature(img.crop((x0, y0, x1, y1)))
        if f is None:
            continue
        lst = mem.setdefault(n, [])
        if all(float(np.dot(f, np.array(g, np.float32))) < 0.98 for g in lst):   # skip near-duplicates
            lst.append([round(float(x), 4) for x in f])
            mem[n] = lst[-KEEP:]
            added += 1
    os.makedirs(os.path.dirname(MEM_P), exist_ok=True)
    json.dump(mem, open(MEM_P, 'w', encoding='utf-8'))
    return added


def match(img):
    """For each slot: [(similarity, name), ...] best first, from the memory."""
    mem = {n: np.array(v, np.float32) for n, v in load().items() if v}
    out = []
    for box in sprite_boxes(img):
        f = feature(img.crop(box))
        if f is None or not mem:
            out.append([])
            continue
        sc = sorted(((float((v @ f).max()), n) for n, v in mem.items()), reverse=True)
        out.append(sc[:3])
    return out


def confident(res):
    """Names of the slots matched surely (similarity >= MATCH and clearly ahead of the next species), else None."""
    names = []
    for sc in res:
        if sc and sc[0][0] >= MATCH and (len(sc) < 2 or sc[0][0] - sc[1][0] >= MARGIN):
            names.append(sc[0][1])
        else:
            names.append(None)
    return names


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    a = sys.argv[1:]
    if len(a) >= 8 and a[0] == 'remember':
        img = Image.open(a[1]).convert('RGB')
        print(f'{remember(img, a[2:8])} 枠の絵を記憶しました')
    elif len(a) >= 2 and a[0] == 'match':
        img = Image.open(a[1]).convert('RGB')
        res = match(img)
        names = confident(res)
        for i, (sc, n) in enumerate(zip(res, names)):
            print(f"枠{i + 1}: " + (f"記憶一致 {n}" if n else '記憶なし') + '  ' +
                  '、'.join(f'{nm}({s:.2f})' for s, nm in sc))
        if all(names):
            print('確定: ' + ' '.join(names))
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
