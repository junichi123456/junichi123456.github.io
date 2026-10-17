"""yakkun_fetch.py が保存した記事(logs/study/yakkun/*.json)を、known_teams.json と同じ形の構築に変換する。

記事本文の形式（やっくん）:
  イエッサン♂@こだわりスカーフ(おくびょう)サイコメイカー      名前@持ち物(性格)特性
  HP:2 / 特攻:32 / 素早:32                                    努力値（ポイント）
  ワイドフォースマジカルシャインマジカルフレイムトリック       技4つ（区切りなしで連結）
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
YK_D = os.path.join(HERE, '..', 'logs', 'study', 'yakkun')
HEAD = re.compile(r'^(.+?)@(.+?)\(([^()]+)\)(.+)$')
AP_KEY = {'HP': 'hp', '攻撃': 'atk', '防御': 'def', '特攻': 'spa', '特防': 'spd', '素早': 'spe'}


def split_moves(s, moves):
    """区切りなしの技名を、技名の一覧に当てはめて分ける（最長一致・全体が埋まる分け方）。"""
    names = sorted(moves, key=len, reverse=True)
    out, memo = [], {}

    def go(i):
        if i == len(s):
            return []
        if i in memo:
            return memo[i]
        for n in names:
            if s.startswith(n, i):
                r = go(i + len(n))
                if r is not None:
                    memo[i] = [n] + r
                    return memo[i]
        memo[i] = None
        return None
    r = go(0)
    return r


def intro(text):
    """投稿者の自己紹介部分（シーズン表記の行から「使用ポケモン」まで）。日付は除く（年がレートに見えるため）。"""
    m = re.search(r'シーズン\s*M-\d+', text)
    body = text[m.end():] if m else text
    body = body.split('使用ポケモン')[0]
    return re.sub(r'\d{4}/\d{1,2}/\d{1,2}(\s+\d{1,2}:\d{2})?', ' ', body)[:600]


def regulation_of(text):
    m = re.search(r'#レギュレーション\s*([A-Za-z])\s*[-ー]?\s*([A-Za-z])', text)
    return (m.group(1) + m.group(2)).lower() if m else None


def season_of(text):
    m = re.search(r'シーズン\s*M-(\d+)', text)
    return int(m.group(1)) if m else None


def parse(d, B, POKE):
    """(team dict or None, 理由)。B=battle, POKE=calc.POKE。"""
    text = d['text']
    lines = [l.strip() for l in text.split('\n')]
    party = text.split('使用ポケモン', 1)[-1]
    lines = [l.strip() for l in party.split('\n') if l.strip()]
    team = []
    i = 0
    while i < len(lines) and len(team) < 6:
        m = HEAD.match(lines[i])
        if not m or i + 1 >= len(lines) or not re.match(r'(HP|攻撃|防御|特攻|特防|素早)\s*:', lines[i + 1]):
            i += 1
            continue
        name, item, nature, ability = (x.strip() for x in m.groups())
        name = re.sub(r'[♂♀]$', '', name)
        ap = {}
        for k, v in re.findall(r'(HP|攻撃|防御|特攻|特防|素早)\s*:\s*(\d+)', lines[i + 1]):
            ap[AP_KEY[k]] = int(v)
        j = i + 2
        while j < len(lines) and (lines[j].startswith('(') or lines[j].startswith('実数値')):
            j += 1
        mv = split_moves(lines[j].replace(' ', ''), B.MOVE) if j < len(lines) else None
        if not mv:
            return None, f'技を読めない: {name} {lines[j][:30] if j < len(lines) else ""}'
        base = B._base(name)
        if base not in POKE and name not in POKE:
            return None, f'不明なポケモン: {name}'
        base_ab = ability
        if name != base and name in POKE:           # メガ: 特性はメガ後。メガ前の特性は種族の先頭の特性で代用
            base_ab = POKE[base]['ab'][0]
        team.append({'name': name, 'nature': nature, 'ability': ability, 'base_ability': base_ab, 'item': item,
                     'moves': mv[:4], 'ap': ap})
        i = j + 1
    if len(team) != 6:
        return None, f'6体読めない({len(team)})'
    return team, ''


def load_all():
    out = []
    for f in sorted(os.listdir(YK_D)):
        if f.endswith('.json') and f != 'index.json':
            out.append((f[:-5], json.load(open(os.path.join(YK_D, f), encoding='utf-8'))))
    return out
