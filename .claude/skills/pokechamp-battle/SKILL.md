---
name: pokechamp-battle
description: ポケモンチャンピオンズ（シングル）の対戦中に、選出順と各ターンの行動を決め、対戦ログを蓄積して次回以降の判断に反映する。相手の6体・対戦画面の状況・Battle Loggerの表示が届いたら使う。
---

# 対戦中の判断と学習

構築は `pokechamp/tool/team.py`、判断エンジンは `pokechamp/tool/battle.py`、学習は `pokechamp/tool/learn.py`。

## チャットへの出力ルール（厳守）

対戦中のチャットには次の2行だけを書く。理由・計算・補足は書かない。

```
選出順：A → B → C
次に何をするか：<技名 / ○○に交代 / メガシンカ＋技名>
```

## 手順

1. **開始前**: `pokechamp/logs/TRENDS.md` を読み、要対策の相手と想定外の型を頭に入れる（チャットには書かない）。
2. **見せ合い**: 相手6体が分かったら
   `cd pokechamp/tool && python3 battle.py select <相手6体>`
   → 出力の選出順を伝える（記録 `logs/current.json` が自動で作られる）。実際に選んだ順が違えば `python3 learn.py pick <順>` で直す。
3. **各ターン**: 画面（またはロガー表示）から state.json を作り（形式は battle.py 冒頭）、
   `python3 battle.py turn state.json 15`
   → 出力の行動を伝える。ターンの結果が分かったら必ず記録する:
   `python3 learn.py turn '{"turn":N,"me":"…","opp":"…","my_action":"…","opp_action":"…","first":"me|opp","opp_item":"…","opp_mega":true,"ko":["me|opp"]}'`
   判明した相手の技・持ち物・特性・素早さの前後は漏らさず入れる（次戦の型予測とスカーフ判定に使う）。
4. **終了**: `python3 learn.py end win|lose|draw <負け筋メモ>`
   → `logs/battles.jsonl` に追記され、`logs/knowledge.json` と `logs/TRENDS.md` が更新される。
5. **保存**: ログをコミットして push する（`pokechamp/logs/`）。次のセッションはここから学習結果を読み込む。

## 学習が反映される箇所

- 相手の型: 自分のログで観測した技・持ち物を使用率データより優先（`battle.opp_sets`）。最速でも抜けない相手に先に動かれた回数が2回以上ならスカーフとみなす。
- 相手の選出予測: 見せ合いに出た回数に対する選出率・先発率（`pick_rate` / `lead_rate`）。
- 自分の選出: 過去の「自分のポケモン×相手の選出ポケモン」勝率を小さく加点（`history_bonus`）。

10戦ごとを目安に `python3 learn.py report` の「要対策」を見て、構築（team.py）や技の変更をユーザーに提案する。提案は対戦中ではなく対戦の合間に行う。
