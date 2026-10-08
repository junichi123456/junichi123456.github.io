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

0. **PCBL（Battle Logger）の画面読み取りを起動**（PC上のセッションで、PCBLの Live Scan が動いているとき）:
   PCBL の Live Scan は専用ウィンドウで動く。`cd pokechamp/tool && python pcbl_watch.py --window "<タイトルの一部>"` をバックグラウンドで実行し続ける（タイトルは `--list` で確認。ブラウザ表示の場合は `--window` なしで URL 読み取り）。
   ウィンドウ版は `pokechamp/logs/live/latest.png` に最新画面、`shots/` に変化ごとの画像が保存されるので、毎ターン latest.png を画像として読んで状況（両者のポケモン・HP%・技・ターン）を把握する。
   画面の文字が `pokechamp/logs/live/latest.txt`、スクリーンショットが `latest.png`、拾ったポケモン名・HP%・ターン・技が `parsed.json` に数秒おきに更新される。
   見せ合い・各ターンの情報はまずここから読む（足りなければ `latest.png` を画像として見る。それでも不明な点だけユーザーに聞く）。
   初回は `latest.txt` と `latest.png` を見比べ、名前・HP%の読み取りが正しいか確認する。
   起動できない場合は `pip install playwright` を実行（Edge/Chrome があればそれを使う）。
   **最新画面の自動読み込み**: `.claude/settings.json` の UserPromptSubmit フック（`pokechamp/tool/hook_latest.py`）が、latest.png が30分以内に更新されていれば毎回その場所を知らせる。知らされたら返答前に必ず Read で latest.png を読む（ユーザーにスクショを求めない）。
   **時間制限**: 選出は `battle.py select`（約3秒）、各ターンは `battle.py turn state.json`（既定7秒）。画像読み取りを含め10秒以内に答える。
1. **開始前**: `pokechamp/logs/TRENDS.md` を読み、要対策の相手と想定外の型を頭に入れる（チャットには書かない）。
2. **見せ合い**: 相手6体が分かったら
   `cd pokechamp/tool && python3 battle.py select <相手6体>`
   → 出力の選出順を伝える（記録 `logs/current.json` が自動で作られる）。実際に選んだ順が違えば `python3 learn.py pick <順>` で直す。
3. **各ターン（型推定を毎ターン必ず行う）**: ターンの結果が分かったら、まず観測つきで記録する:
   `python3 learn.py turn '{"turn":N,"me":"…","opp":"…","my_action":"…","opp_action":"…","first":"me|opp","opp_item":"…","opp_mega":true,"ko":["me|opp"],"obs":[…]}'`
   `obs` には次を毎ターン漏れなく入れる（形式は `infer.py` 冒頭）:
   - `dealt`: 自分の技で相手のHP%が何%→何%になったか（急所・ランク補正・天候も）
   - `taken`: 相手の技で自分が受けた実ダメージ
   - `order`: 同じ優先度の技でどちらが先に動いたか（スカーフ・素早さ配分の判定）
   - `move` / `item` / `ability` / `mega`: 判明したもの
   次に state.json を作り（形式は battle.py 冒頭）、
   `python battle.py turn state.json`
   → 出力の行動を伝える。battle.py は `logs/current.json` の観測を自動で読み、候補（使用率258種の持ち物×性格×能力P、データが無ければ種族値からの役割推定）の事後確率を更新し、最も確からしい型で先読みする。
   推定が割れているときは `python3 battle.py infer <相手>` で上位候補を確認してよい（チャットには書かない）。
4. **終了**: `python3 learn.py end win|lose|draw <負け筋メモ>`
   → `logs/battles.jsonl` に追記され、`logs/knowledge.json` と `logs/TRENDS.md` が更新される。
5. **保存**: ログをコミットして push する（`pokechamp/logs/`）。次のセッションはここから学習結果を読み込む。

## 学習が反映される箇所

- 相手の型: 使用率データ（全258種）または役割推定の候補に、過去ログで推定した型・観測した持ち物を事前確率として上乗せし、対戦中の観測でベイズ更新（`sets.py` / `infer.py` / `battle.opp_sets`）。最速でも抜けない相手に先に動かれた回数が2回以上ならスカーフとみなす。
- 相手の選出予測: 見せ合いに出た回数に対する選出率・先発率（`pick_rate` / `lead_rate`）。
- 自分の選出: 過去の「自分のポケモン×相手の選出ポケモン」勝率を小さく加点（`history_bonus`）。

10戦ごとを目安に `python3 learn.py report` の「要対策」を見て、構築（team.py）や技の変更をユーザーに提案する。提案は対戦中ではなく対戦の合間に行う。
