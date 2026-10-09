"""次の「選出画面」または「行動選択画面」を待って、検出したら内容を出力して終了する。

対戦中の Claude はこれをバックグラウンド実行し、終了通知で起こされる（ユーザーのチャット不要）。
  python wait_event.py [--after <seq>] [--timeout 900]
出力: 検出イベントの JSON 1行（phase, seq, image, text, missed）。タイムアウト時は {"phase": "timeout"}。
前回渡したイベントの seq を logs/live/wait_last.json に覚えておき、Claude が判断している間に次の画面が
来ていた場合もすぐに（最新の1件を）返す。missed はその間に飛ばしたイベント数。
"""
import argparse, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import safeio  # noqa: E402
OUT = os.path.join(os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs')), 'live')
EV = os.path.join(OUT, 'game_events.jsonl')


def last_event():
    try:
        with open(EV, encoding='utf-8') as f:
            lines = [l for l in f if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except FileNotFoundError:
        return None


LAST = os.path.join(OUT, 'wait_last.json')


def delivered():
    """seq of the last event this script handed to Claude (None if unknown)."""
    try:
        return json.load(open(LAST, encoding='utf-8')).get('seq')
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--after', type=int,
                    help='この seq より後のイベントを待つ（省略時は前回渡したイベントの次。'
                         'Claude が判断している間に来た画面も取りこぼさない）')
    ap.add_argument('--timeout', type=float, default=900)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ev = last_event()
    latest = ev['seq'] if ev else 0
    if a.after is not None:
        after = a.after
    else:
        d = delivered()
        # game_watch restarted with a lower seq, or nothing delivered yet: start from the newest event
        after = d if d is not None and d <= latest and latest - d <= 20 else latest
        if d is not None and d < latest and ev and time.time() - _ts(ev) > 600:
            after = latest   # the pending events are from an old session
        if after != d:
            try:
                safeio.write_json(LAST, {'seq': after})   # baseline for the next call
            except Exception:
                pass
    t_end = time.time() + a.timeout
    while time.time() < t_end:
        ev = last_event()
        if ev and ev['seq'] > after:
            # several screens may have passed while Claude was busy: hand over the newest one
            ev = dict(ev, missed=ev['seq'] - after - 1)
            try:
                safeio.write_json(LAST, {'seq': ev['seq']})
            except Exception:
                pass
            print(json.dumps(ev, ensure_ascii=False))
            return 0
        time.sleep(0.3)
    print(json.dumps({'phase': 'timeout', 'seq': after}))
    return 0


def _ts(ev):
    try:
        return time.mktime(time.strptime(ev['time'], '%Y-%m-%dT%H:%M:%S'))
    except Exception:
        return time.time()


if __name__ == '__main__':
    sys.exit(main())
