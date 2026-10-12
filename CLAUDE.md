# このリポジトリについて

2つの独立したプロジェクトが入っています。依頼内容で使い分けてください。

| フォルダ | 内容 |
|---|---|
| `pokechamp/` | ポケモンチャンピオンズ（シングル）の構築・ダメージ計算・対戦補助（Python） |
| `starcrusade/`・ルートの `index.html` | Star Crusade（Webアプリ） |

## ポケモンの対戦・構築に関する依頼

- 「対戦を始める」「選出」「相手の6体」「次の行動」などは、スキル `pokechamp-battle`（`.claude/skills/pokechamp-battle/SKILL.md`）の手順に従う。
- 対戦の観測は `game_watch.py`（OBSの映像）だけで行う。PCBL（Battle Logger）と `pcbl_watch.py` は使わない。
- 作業フォルダは `pokechamp/tool/`。`python battle.py` / `python learn.py` を使う（Windows では `python`、他は `python3`）。
- このときは Star Crusade（ルートの `index.html` や `starcrusade/`）を起動・プレビュー・編集しない。
