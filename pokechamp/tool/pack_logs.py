"""対戦後の記録をまとめて、評価用にリポジトリへ入れる（画像は含めない）。

  python pack_logs.py            logs/live の記録（判断・イベント・戦闘メッセージ・場の状態）を
                                 logs/sessions/<日時>/ にコピーし、要約 summary.txt を作る
その後 git add pokechamp/logs/sessions && git commit && git push で送る。
"""
import json, os, shutil, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.environ.get('POKECHAMP_LOGS', os.path.join(HERE, '..', 'logs'))
LIVE = os.path.join(LOGS, 'live')
FILES = ('decisions.jsonl', 'game_events.jsonl', 'battle_messages.jsonl', 'field_state.json', 'auto_state.json',
         'decision.json')


def load(p):
    try:
        return [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]
    except Exception:
        return []


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    dst = os.path.join(LOGS, 'sessions', time.strftime('%Y%m%d_%H%M'))
    os.makedirs(dst, exist_ok=True)
    for f in FILES:
        p = os.path.join(LIVE, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dst, f))
    cur = os.path.join(LOGS, 'current.json')
    if os.path.exists(cur):
        shutil.copy2(cur, os.path.join(dst, 'current.json'))
    evs = {e['seq']: e for e in load(os.path.join(LIVE, 'game_events.jsonl'))}
    L = ['seq\tphase\t画面検出→判断表示(秒)\t先読み\t判断']
    for d in load(os.path.join(LIVE, 'decisions.jsonl')):
        e = evs.get(d['seq'], {})
        t0 = e.get('screen_onset') or e.get('t')
        lag = f"{d['time'] - t0:.1f}" if t0 else '?'
        L.append(f"{d['seq']}\t{e.get('phase', '?')}\t{lag}\t{'○' if d.get('precomputed') else ''}{'（更新）' if d.get('update') else ''}\t{d['decision']}")
    open(os.path.join(dst, 'summary.txt'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('\n'.join(L[-30:]))
    print('→', os.path.normpath(dst))


if __name__ == '__main__':
    main()
