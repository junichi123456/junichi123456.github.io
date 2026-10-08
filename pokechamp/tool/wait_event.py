"""次の「選出画面」または「行動選択画面」を待って、検出したら内容を出力して終了する。

対戦中の Claude はこれをバックグラウンド実行し、終了通知で起こされる（ユーザーのチャット不要）。
  python wait_event.py [--after <seq>] [--timeout 900]
出力: 検出イベントの JSON 1行（phase, seq, image, text）。タイムアウト時は {"phase": "timeout"}。
"""
import argparse, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs')), 'live')
EV = os.path.join(OUT, 'game_events.jsonl')


def last_event():
    try:
        with open(EV, encoding='utf-8') as f:
            lines = [l for l in f if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except FileNotFoundError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--after', type=int, help='この seq より後のイベントを待つ（省略時は現在の最新より後）')
    ap.add_argument('--timeout', type=float, default=900)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ev = last_event()
    after = a.after if a.after is not None else (ev['seq'] if ev else 0)
    t_end = time.time() + a.timeout
    while time.time() < t_end:
        ev = last_event()
        if ev and ev['seq'] > after:
            print(json.dumps(ev, ensure_ascii=False))
            return 0
        time.sleep(0.3)
    print(json.dumps({'phase': 'timeout', 'seq': after}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
