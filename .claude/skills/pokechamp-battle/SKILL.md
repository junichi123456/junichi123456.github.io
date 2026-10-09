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

## 自動進行モード（ユーザーのチャット不要・推奨）

ユーザーが `python game_watch.py --password <OBSのWebSocketパスワード>` を起動していれば（`pokechamp/logs/live/game_state.json` が数秒以内に更新されている）、次のループで進める。ユーザーにチャットや合図を求めない。

1. `cd pokechamp/tool && python wait_event.py` を **バックグラウンド実行**（run_in_background）して待つ。終了すると自動で起こされる。
2. 出力 JSON の `phase` で分岐し、`image`（その瞬間のゲーム画面）を Read で読む:
   - `preview`（選出画面）: 相手の名前は表示されない（3Dモデルの小さな絵とタイプアイコンのみ）。
     イベントの `identify`（各枠のタイプ判定と候補）と `identify_sheet`（左端=画面の枠、右=候補の HOME 3Dモデル画像）を Read で見て、6体を見比べて確定する。
     タイプは必ず `identify` の判定（アイコンの記号の形で判定）を使い、色で推測しない。特に **どく=紫地に丘と丸**、**むし=黄緑地の記号**、**ゴースト=紫地のおばけ** は見間違えやすい。
     候補に一致する絵が無いときだけ、別タイプの読み違いを疑って `python identify.py <画像>` を再実行する。
     確定したら `python battle.py select <6体>` を実行し「選出順」を出力。
     対戦後、相手6体のタイプが確定したら（判定が違っていた場合は特に）
     `python identify.py <その選出画面の画像> --learn <枠1のタイプ> ... <枠6のタイプ>`（複合は「むし/みず」）で
     実画面のアイコンを学習させる。未学習のタイプ（あく・ドラゴン・こおり）が出たら必ず学習させる。
   - `command`（自分の行動選択画面）: イベントの `turn_events` に、前の判断以降に流れた戦闘メッセージから抜き出した出来事（使われた技と行動順・能力ランク変化・天候/フィールドの開始と終了・持ち物の消費・状態異常・ステロ・交代・ひんし・メガシンカ・特性・急所）が入っている。累積した場の状態は `pokechamp/logs/live/field_state.json`。
     画面（`image`）からは HP%（と必要なら場のポケモン）だけを読み、state.json は場のポケモンとHPだけ書けばよい（天候・フィールド・ランク・消費した持ち物・状態異常・ステロ・メガ・判明した技は battle.py が field_state.json から自動で補う。画面で明らかに違うときだけ state.json に明記して上書きする）。
     `turn_events` を観測として `learn.py turn` に記録（moves→move、items→item、first→order、ダメージ%→dealt/taken）し、`python battle.py turn state.json` を実行して「次に何をするか」を出力。
     メッセージの読み取り結果は `pokechamp/logs/live/battle_messages.jsonl` に生の行と一緒に残る。抜き出しに失敗している言い回しを見つけたら `msgparse.py` の文言を直す（対戦の合間に）。
   - `timeout`: 何も出力せず 1 に戻る。
3. 出力したら **すぐに 1 に戻って** 次を待つ。対戦終了（勝敗画面）を画像で確認したら `learn.py end` で記録し、そのまま次の対戦を待つ。
4. 画像の読み取りから出力まで 13 秒以内を目標にする（選出は90秒、行動は45秒の制限）。

## 手順

0. **PCBL（Battle Logger）の画面読み取りを起動**（PC上のセッションで、PCBLの Live Scan が動いているとき）:
   PCBL の Live Scan は専用ウィンドウで動く。`cd pokechamp/tool && python pcbl_watch.py --window "<タイトルの一部>"` をバックグラウンドで実行し続ける（タイトルは `--list` で確認。ブラウザ表示の場合は `--window` なしで URL 読み取り）。
   ウィンドウ版は `pokechamp/logs/live/latest.png` に最新画面、`shots/` に変化ごとの画像が保存されるので、毎ターン latest.png を画像として読んで状況（両者のポケモン・HP%・技・ターン）を把握する。
   画面の文字が `pokechamp/logs/live/latest.txt`、スクリーンショットが `latest.png`、拾ったポケモン名・HP%・ターン・技が `parsed.json` に数秒おきに更新される。
   見せ合い・各ターンの情報はまずここから読む（足りなければ `latest.png` を画像として見る。それでも不明な点だけユーザーに聞く）。
   初回は `latest.txt` と `latest.png` を見比べ、名前・HP%の読み取りが正しいか確認する。
   起動できない場合は `pip install playwright` を実行（Edge/Chrome があればそれを使う）。
   **最新画面の自動読み込み**: `.claude/settings.json` の UserPromptSubmit フック（`pokechamp/tool/hook_latest.py`）が、latest.png が30分以内に更新されていれば毎回その場所を知らせる。知らされたら返答前に必ず Read で latest.png を読む（ユーザーにスクショを求めない）。
   **時間制限**: 選出は `battle.py select`（約10秒）、各ターンは `battle.py turn state.json`（既定10秒）。画像読み取りを含め13秒以内に答える。
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
   画面から分かれば state.json の各ポケモンに `last_move`（こだわり固定）・`rampage`・`sub`・`glaive`・`toxn`、全体に `trick_room`（残りターン）を書く（省略時は field_state.json から補完）。まきびし・どくびし・ねばねばネット・壁・おいかぜは `cond_me`/`cond_opp`、じゅうりょく・マジックルーム・ワンダールームは `pseudo` に書く。
   → 出力の行動を伝える。battle.py は `logs/current.json` の観測を自動で読み、候補（使用率258種の持ち物×性格×能力P、データが無ければ種族値からの役割推定）の事後確率を更新し、最も確からしい型で、Showdown準拠の engine.py 上で5ターン木＋ロールアウトの計8ターン先まで読む（search.py、全CPUコア並列）。
   推定が割れているときは `python3 battle.py infer <相手>` で上位候補を確認してよい（チャットには書かない）。
4. **終了**: `python3 learn.py end win|lose|draw <負け筋メモ>`
   → `logs/battles.jsonl` に追記され、`logs/knowledge.json` と `logs/TRENDS.md` が更新される。
5. **保存**: ログをコミットして push する（`pokechamp/logs/`）。次のセッションはここから学習結果を読み込む。

## 学習が反映される箇所

- 相手の型: 使用率データ（全258種）または役割推定の候補に、過去ログで推定した型・観測した持ち物を事前確率として上乗せし、対戦中の観測でベイズ更新（`sets.py` / `infer.py` / `battle.opp_sets`）。最速でも抜けない相手に先に動かれた回数が2回以上ならスカーフとみなす。
- 相手の選出予測: 見せ合いに出た回数に対する選出率・先発率（`pick_rate` / `lead_rate`）。
- 自分の選出: 過去の「自分のポケモン×相手の選出ポケモン」勝率を小さく加点（`history_bonus`）。

10戦ごとを目安に `python3 learn.py report` の「要対策」を見て、構築（team.py）や技の変更をユーザーに提案する。提案は対戦中ではなく対戦の合間に行う。
