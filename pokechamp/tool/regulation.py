"""現行レギュレーションの管理（構築記事の学習が、古いレギュレーションの構築を混ぜないようにする）。

  python regulation.py                 現在の設定と、保存済み構築のレギュレーション別の件数
  python regulation.py switch <コード> [開始シーズン]   手で切り替える（例: switch md 8）

data/regulation.json:
  current        現行レギュレーション（pokesol の regulation コード。いまは mc = M-C）
  min_season     現行レギュレーションの最初のシーズン番号（やっくん等のシーズン絞り込みに使う）
  max_season     設定上の最終シーズン番号（latest_season が大きければそちらを使う）
  latest_season  study.py が記事から読んだ、現行レギュレーションの最新シーズン
  yakkun         やっくんの一覧URLの固定パラメータ（soft / rule）

切り替わると、現行以外の構築は data/known_teams_archive.json に移り（消さない）、battle.py・prep.py などは
現行の構築だけを見る。study.py は新しいレギュレーションの記事が増えたのを検出すると自動で切り替える。
"""
import datetime, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_P = os.path.join(HERE, 'data', 'regulation.json')
KNOWN_P = os.path.join(HERE, 'data', 'known_teams.json')
ARCHIVE_P = os.path.join(HERE, 'data', 'known_teams_archive.json')
DEFAULT = {'current': 'mc', 'min_season': 6, 'max_season': 7, 'latest_season': 7,
           'yakkun': {'soft': 4, 'rule': 0}, 'history': []}


def load():
    try:
        cfg = json.load(open(CFG_P, encoding='utf-8'))
    except Exception:
        cfg = {}
    return {**DEFAULT, **cfg}


def save(cfg):
    json.dump(cfg, open(CFG_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def current():
    return load()['current']


def team_reg(t, cfg=None):
    """構築のレギュレーション。タグのない古いデータは、タグを付ける前の現行（history の先頭 or current）。"""
    return t.get('regulation') or (cfg or load()).get('legacy') or (cfg or load())['current']


def is_current(t, cfg=None):
    return team_reg(t, cfg) == (cfg or load())['current']


def season_range(cfg=None):
    cfg = cfg or load()
    return cfg['min_season'], max(cfg['max_season'], cfg.get('latest_season') or 0)


def switch(code, min_season=None, why='手動'):
    """現行を code に切り替え、それ以外の構築を archive に移す（既存の archive とはマージ）。"""
    cfg = load()
    if code == cfg['current']:
        return cfg
    data = json.load(open(KNOWN_P, encoding='utf-8'))
    keep, old = [], []
    for t in data['teams']:
        (keep if team_reg(t, cfg) == code else old).append(t)
    arc = json.load(open(ARCHIVE_P, encoding='utf-8')) if os.path.exists(ARCHIVE_P) else {'teams': []}
    ids = {t['id'] for t in arc['teams']}
    arc['teams'] += [t for t in old if t['id'] not in ids]
    for t in old:
        t.setdefault('regulation', cfg['current'])
    data['teams'] = keep
    json.dump(data, open(KNOWN_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(arc, open(ARCHIVE_P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    cfg['history'] = (cfg.get('history') or []) + [{
        'date': datetime.date.today().isoformat(), 'from': cfg['current'], 'to': code, 'why': why}]
    cfg['current'] = code
    if min_season:
        cfg['min_season'] = cfg['max_season'] = cfg['latest_season'] = int(min_season)
    save(cfg)
    return cfg


def main():
    cfg = load()
    a = sys.argv[1:]
    if a[:1] == ['switch'] and len(a) >= 2:
        cfg = switch(a[1], a[2] if len(a) > 2 else None)
        print('切り替えました:', cfg['current'], '／シーズン', season_range(cfg))
        return
    n = {}
    for t in json.load(open(KNOWN_P, encoding='utf-8'))['teams']:
        n[team_reg(t, cfg)] = n.get(team_reg(t, cfg), 0) + 1
    print('現行:', cfg['current'], '／シーズン', season_range(cfg), '／保存済み(現行側):', n)
    if os.path.exists(ARCHIVE_P):
        print('archive:', len(json.load(open(ARCHIVE_P, encoding='utf-8'))['teams']), '件')


if __name__ == '__main__':
    main()
