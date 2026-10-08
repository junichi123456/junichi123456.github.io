"""UserPromptSubmit hook: point Claude at the latest PCBL screenshot so it reads it every turn.

Prints a hook JSON with additionalContext when pokechamp/logs/live/latest.png was updated recently
(i.e. pcbl_watch.py is running). Prints nothing otherwise, so normal sessions are unaffected.
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs')), 'live')
FRESH = 30 * 60  # seconds


def main():
    try:
        sys.stdin.read()
    except Exception:
        pass
    png = os.path.normpath(os.path.join(LIVE, 'latest.png'))
    if not os.path.exists(png):
        return 0
    age = time.time() - os.path.getmtime(png)
    if age > FRESH:
        return 0
    ctx = (f"[PCBL最新画面] {png}（{int(age)}秒前に更新）。"
           "ポケモンの対戦に関する入力なら、返答の前に必ず Read ツールでこの画像を読み込み、"
           "画面から状況（見せ合いの相手6体／場のポケモン・HP%・使われた技・ターン）を把握してから"
           "pokechamp-battle スキルの手順で判断すること。計算は battle.py（選出・各ターンとも10秒以内）。")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())
