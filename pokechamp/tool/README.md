# ポケモンチャンピオンズ ダメージ計算・構築診断ツール

Lv50・能力ポイント制（合計66／各32）のダメージ計算機と、構築診断スクリプト。

| ファイル | 内容 |
|---|---|
| `calc.py` | 実数値・ダメージ計算（乱数16段階、4096分率補正チェーン、五捨五超入）、タイプ相性、覚える技の参照 |
| `meta.py` | シーズンM-6使用率上位の採用型（最多採用の性格・能力P・持ち物・技） |
| `team.py` | 構築6体 |
| `keycalcs.py` | 主要ダメージ計算の一覧を出力 |
| `coverage.py` | 1対1簡易判定と、補完枠の総当たり探索 |
| `report.py` | `../index.html`（構築レポート）を `template.html` から生成 |
| `data/` | レギュM-Cで使用可能なポケモン・技・覚える技（damekei.com のデータから抽出） |

```sh
python3 keycalcs.py   # ダメージ計算
python3 coverage.py   # 補完枠探索
python3 report.py     # レポート再生成
```

例:

```python
from calc import Mon, show
a = Mon('メガルカリオＺ', 'おくびょう', dict(hp=2, spa=32, spe=32), 'はどうのぼうご', 'ルカリオナイトZ')
d = Mon('メガボーマンダ', 'いじっぱり', dict(hp=1, atk=32, defn=1, spe=32), 'スカイスキン', 'ボーマンダナイト')
print(show(a, d, 'ラスターカノン', atk_boost=2))
```
