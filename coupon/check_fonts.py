"""仕様書 §8-1: 許可書体の存在確認。不足があれば代替せずに exit 1 で停止する。"""
import glob, json, os, sys
from fontTools.ttLib import TTFont, TTCollection

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT = "".join(json.load(open(os.path.join(HERE, "text.json"), encoding="utf-8")).values())

def faces():
    paths = glob.glob(os.path.join(HERE, "fonts", "*")) + glob.glob("/usr/share/fonts/**/*", recursive=True)
    for p in paths:
        ext = p.lower().rsplit(".", 1)[-1]
        try:
            fonts = TTCollection(p).fonts if ext == "ttc" else [TTFont(p)] if ext in ("ttf", "otf") else []
        except Exception:
            continue
        for i, f in enumerate(fonts):
            n = f["name"]
            names = {str(r) for r in n.names if r.nameID in (1, 4, 6, 16)}
            yield p, i, names, f.getBestCmap() or {}

REQUIRED = {  # 書体名: 名前に含まれるべき文字列（いずれか）
    "ニタラゴルイカ": ["NitalagoRuika", "ニタラゴルイカ"],
    "ヒラギノ角ゴ": ["Hiragino Kaku Gothic", "Hiragino Sans", "HiraKaku", "HiraginoSans", "ヒラギノ角ゴ"],
    "明朝体(Noto Serif JP / ヒラギノ明朝 / しっぽり明朝)": ["Noto Serif JP", "Hiragino Mincho", "HiraMin", "Shippori Mincho", "ヒラギノ明朝"],
}

found, missing = {}, []
all_faces = list(faces())
for label, keys in REQUIRED.items():
    hits = [(p, i, sorted(nm)[0]) for p, i, nm, cm in all_faces
            if any(k.lower() in x.lower() for x in nm for k in keys)
            and all(ord(c) in cm for c in set(TEXT))]
    if hits:
        found[label] = hits
    else:
        missing.append(label)

for label, hits in found.items():
    print(f"OK   {label}: " + ", ".join(f"{os.path.basename(p)}[{i}] {n}" for p, i, n in hits))
if missing:
    print("ERROR 不足フォント: " + " / ".join(missing), file=sys.stderr)
    sys.exit(1)
