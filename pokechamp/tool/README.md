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

## 対戦中の判断（battle.py）

```sh
python3 battle.py select ガブリアス ボーマンダ アシレーヌ セグレイブ カバルドン サーフゴー   # 選出順
python3 battle.py turn state.json 20                                                    # 次の行動（20秒探索）
```

- 選出: 相手6体から使用率と相性で相手の選出3体を推定し、自分の全60通り（3体×先発）を対戦シミュレーションで評価します。
- 行動: 両者同時選択の局面木を最大5ターン分探索し、残りを貪欲ロールアウトで延長して計8ターン先まで評価します（相手は最善応手と平均の混合）。
- `state.json` の形式は `battle.py` 冒頭のコメントを参照。Battle Logger のライブ表示（HP%・場のポケモン・使用技）を写して使います。

## 対戦ログの蓄積と学習（learn.py）

対戦ごとに `select → turn（毎ターン記録）→ end` で `../logs/battles.jsonl` に追記されます。`end` のたびに `knowledge.json`（相手ごとの選出率・先発率・観測した技/持ち物・スカーフ疑い、自分の選出別勝率）と `TRENDS.md`（傾向と対策）が更新され、`battle.py` が次の対戦から読み込みます。手順は `.claude/skills/pokechamp-battle/SKILL.md`。
