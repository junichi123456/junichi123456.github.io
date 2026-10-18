# このリポジトリについて

2つの独立したプロジェクトが入っています。依頼内容で使い分けてください。

| フォルダ | 内容 |
|---|---|
| `pokechamp/` | ポケモンチャンピオンズ（シングル）の構築・ダメージ計算・対戦補助（Python） |
| `starcrusade/`・ルートの `index.html` | Star Crusade（Webアプリ） |

## ポケモンの対戦・構築に関する依頼

- 「対戦を始める」「選出」「相手の6体」「次の行動」などは、スキル `pokechamp-battle`（`.claude/skills/pokechamp-battle/SKILL.md`）の手順に従う。
- 対戦の観測は `game_watch.py`（OBSの映像）だけで行う。PCBL は使わない（OBS WebSocket の映像だけを入力にする）。
- 作業フォルダは `pokechamp/tool/`。`python battle.py` / `python learn.py` を使う（Windows では `python`、他は `python3`）。
- このときは Star Crusade（ルートの `index.html` や `starcrusade/`）を起動・プレビュー・編集しない。

## 作業の進め方（すべての依頼に適用）

- 仕様書（何をどう直すか・受け入れ条件）は Opus 5.5（`claude-opus-5-5`）が書く。
- プログラムの実装・編集は Sonnet 5.5（`claude-sonnet-5-5`）が行う（Agent ツールで `model: sonnet` のサブエージェントに仕様書を渡して実装させる）。
- 仕様書は `pokechamp/specs/`（ポケモン）に置き、実装後に Opus が受け入れ条件を確認してから報告する。
