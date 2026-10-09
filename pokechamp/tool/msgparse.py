"""戦闘メッセージ（OCR文字）から、そのターンに起きたことを抜き出す。

  parse_turn(lines) -> dict   1ターン分のメッセージ行（出現順）を解析
  FieldTracker               ターンをまたいで場の状態（天候・フィールド・能力ランク・持ち物・状態異常・
                             ステロ・メガシンカ・場のポケモン）を追跡し logs/live/field_state.json に保存

文言は本編（SV）の日本語メッセージに準拠。チャンピオンズの実際の言い回しと違う場合は PATTERNS を直す。
OCR の誤読に備えて、空白・句読点・全角半角の違いは無視して照合する。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from calc import POKE, MOVE  # noqa: E402

NAMES = sorted({n for n in POKE if len(n) >= 2}, key=len, reverse=True)
ABILITIES = sorted({a for p in POKE.values() for a in p.get('ab', []) if len(a) >= 2}, key=len, reverse=True)
try:
    from sets import MEGAS
    BASE = {m: b for b, ms in MEGAS.items() for m in ms}
except Exception:
    BASE = {}
MOVES = sorted({m for m in MOVE if len(m) >= 2}, key=len, reverse=True)
STAT = {'こうげき': 'atk', '攻撃': 'atk', 'ぼうぎょ': 'def', '防御': 'def', 'とくこう': 'spa', '特攻': 'spa',
        'とくぼう': 'spd', '特防': 'spd', 'すばやさ': 'spe', '素早さ': 'spe', 'めいちゅうりつ': 'acc', '命中率': 'acc',
        'かいひりつ': 'eva', '回避率': 'eva'}
UP = {'': 1, 'ぐーんと': 2, 'ぐぐーんと': 3, 'ぐんと': 2}
DOWN = {'': 1, 'がくっと': 2, 'がくーんと': 3}


def norm(s):
    s = s.translate(str.maketrans('０１２３４５６７８９！？', '0123456789!?'))
    return re.sub(r'[\s　、。・…]', '', s)


def find_name(s):
    for n in NAMES:
        if n in s:
            return n
    return None


def find_move(s):
    for m in MOVES:
        if m in s:
            return m
    return None


def side_of(s):
    return 'opp' if ('相手の' in s or 'あいての' in s) else 'me'


WEATHER_START = [('sun', ('日差しが強くなった', 'ひざしがつよくなった', '日差しがとても強くなった')),
                 ('rain', ('雨が降り始めた', 'あめがふりはじめた', '強い雨が降り始めた')),
                 ('sand', ('砂あらしが吹き始めた', 'すなあらしがふきはじめた', '砂嵐が吹き始めた')),
                 ('snow', ('雪が降り始めた', 'ゆきがふりはじめた'))]
WEATHER_END = ('日差しが元に戻った', 'ひざしがもとにもどった', '雨が止んだ', 'あめがやんだ', '砂あらしがおさまった',
               'すなあらしがおさまった', '雪が止んだ', 'ゆきがやんだ')
TERRAIN_START = [('grassy', ('草がいっぱいに生えた', 'くさがいっぱいにはえた', 'グラスフィールド')),
                 ('electric', ('電気が駆けめぐる', 'でんきがかけめぐる', 'エレキフィールド')),
                 ('psychic', ('不思議な感じに', 'ふしぎなかんじに', 'サイコフィールド')),
                 ('misty', ('霧が立ち込めた', 'きりがたちこめた', 'ミストフィールド'))]
TERRAIN_END = ('草が消え去った', '電気が消え去った', '不思議な感じが消え去った', '霧が消え去った', 'もとにもどった足元',
               'フィールドが消え去った')
STATUS = [('brn', ('やけどを負った', 'やけどをおった')), ('par', ('まひして', 'まひした')),
          ('tox', ('もうどくをあびた', '猛毒を浴びた')), ('psn', ('どくをあびた', '毒を浴びた')),
          ('slp', ('眠ってしまった', 'ねむってしまった')), ('frz', ('凍りついた', 'こおりついた'))]
TR_START = ('時空をゆがめた', 'じくうをゆがめた')
TR_END = ('時空が元に戻った', 'じくうがもとにもどった')
SUB_UP = ('身代わりが現れた', 'みがわりがあらわれた', 'みがわりが現れた')
SUB_DOWN = ('身代わりは消えてしまった', 'みがわりはきえてしまった', 'みがわりは消えてしまった')
RAMPAGE = {'げきりん', 'あばれる', 'はなびらのまい'}
CURE = ('治った', 'なおった', '目を覚ました', 'めをさました', '溶けた', 'とけた')
ITEM_MSG = [('きあいのタスキ', True, ('きあいのタスキで',)), ('オボンのみ', True, ('オボンのみで', 'オボンのみを')),
            ('いのちのたま', False, ('いのちのたまで', '命が少し削られた', 'いのちがすこしけずられた')),
            ('ゴツゴツメット', False, ('ゴツゴツメットで',)), ('たべのこし', False, ('たべのこしで',)),
            ('ふうせん', False, ('ふうせんで浮いている', 'ふうせんでういている')), ('ふうせん', True, ('ふうせんが割れた', 'ふうせんがわれた')),
            ('しろいハーブ', True, ('しろいハーブで',)), ('メンタルハーブ', True, ('メンタルハーブで',)),
            ('ラムのみ', True, ('ラムのみで',)), ('レッドカード', True, ('レッドカードを',)),
            ('だっしゅつボタン', True, ('だっしゅつボタンで',)), ('ノーマルジュエル', True, ('ノーマルジュエルで',)),
            ('サイコシード', True, ('サイコシードで',)), ('エレキシード', True, ('エレキシードで',)),
            ('グラスシード', True, ('グラスシードで',)), ('ミストシード', True, ('ミストシードで',))]


def parse_turn(lines):
    ev = {'moves': [], 'boosts': [], 'weather': None, 'weather_end': False, 'terrain': None, 'terrain_end': False,
          'items': [], 'status': [], 'cured': [], 'hazards': [], 'faint': [], 'switch': [], 'mega': [], 'crit': 0,
          'super_effective': 0, 'abilities': [], 'trick_room': False, 'trick_room_end': False, 'sub': [], 'sub_end': []}
    seen = set()
    for raw in lines:
        s = norm(raw)
        if not s or s in seen:
            continue
        seen.add(s)
        side = side_of(s)
        name = find_name(s)
        if any(k in s for k in TR_END):
            ev['trick_room_end'] = True; continue
        if any(k in s for k in TR_START):
            ev['trick_room'] = True; continue
        if name and any(k in s for k in SUB_UP):
            ev['sub'].append({'side': side, 'mon': name}); continue
        if name and any(k in s for k in SUB_DOWN):
            ev['sub_end'].append({'side': side, 'mon': name}); continue
        # move use: 「(相手の)Xの Y！」
        mv = find_move(s)
        if name and mv and s.find(name) < s.find(mv) and not any(k in s for k in STAT) and 'で' not in s[s.find(mv) + len(mv):][:1]:
            ev['moves'].append({'side': side, 'mon': name, 'move': mv})
            continue
        # stat change
        m = re.search(r'の(こうげき|攻撃|ぼうぎょ|防御|とくこう|特攻|とくぼう|特防|すばやさ|素早さ|命中率|回避率)が(ぐぐーんと|ぐーんと|ぐんと|がくーんと|がくっと)?(上がった|あがった|下がった|さがった)', s)
        if m and name:
            up = m.group(3) in ('上がった', 'あがった')
            mag = (UP if up else DOWN).get(m.group(2) or '', 1)
            ev['boosts'].append({'side': side, 'mon': name, 'stat': STAT[m.group(1)], 'delta': mag if up else -mag})
            continue
        for w, keys in WEATHER_START:
            if any(k in s for k in keys):
                ev['weather'] = w
        if any(k in s for k in WEATHER_END):
            ev['weather_end'] = True
        for t, keys in TERRAIN_START:
            if any(k in s for k in keys) and not any(k in s for k in TERRAIN_END):
                ev['terrain'] = t
        if any(k in s for k in TERRAIN_END):
            ev['terrain_end'] = True
        for st, keys in STATUS:
            if any(k in s for k in keys) and name:
                ev['status'].append({'side': side, 'mon': name, 'status': st})
                break
        if name and any(k in s for k in CURE) and not any(k in s for _, ks in STATUS for k in ks):
            ev['cured'].append({'side': side, 'mon': name})
        for item, consumed, keys in ITEM_MSG:
            if any(k in s for k in keys):
                ev['items'].append({'side': side, 'mon': name, 'item': item, 'consumed': consumed})
        if 'とがった岩' in s or 'とがったいわ' in s:
            if 'ただよい' in s:
                ev['hazards'].append({'side': 'opp' if ('相手の周り' in s or 'あいてのまわり' in s) else 'me', 'hazard': 'rocks'})
        if name and ('倒れた' in s or 'たおれた' in s):
            ev['faint'].append({'side': side, 'mon': name})
        if name and ('繰り出した' in s or 'くりだした' in s):
            ev['switch'].append({'side': 'opp', 'mon': name})
        elif name and (s.startswith('ゆけっ') or s.startswith('いけっ') or s.startswith('行け') or 'がんばれ' in s or 'たのんだ' in s):
            ev['switch'].append({'side': 'me', 'mon': name})
        if 'メガシンカ' in s and name:
            ev['mega'].append({'side': side, 'mon': name})
            continue
        if name and len(s) <= len(name) + 14:
            ab = next((a for a in ABILITIES if a in s[s.find(name) + len(name):]), None)
            if ab:
                ev['abilities'].append({'side': side, 'mon': name, 'ability': ab})
        if '急所に当たった' in s or 'きゅうしょにあたった' in s:
            ev['crit'] += 1
        if '効果はバツグン' in s or 'こうかはばつぐん' in s:
            ev['super_effective'] += 1
    first = ev['moves'][0]['side'] if ev['moves'] else None
    ev['first'] = first
    return ev


class FieldTracker:
    """Keeps the running field state across turns."""

    def __init__(self, path):
        self.path = path
        self.s = {'turn': 0, 'weather': None, 'weather_turns': 0, 'terrain': None, 'terrain_turns': 0, 'trick_room': 0,
                  'rocks_me': False, 'rocks_opp': False, 'active': {'me': None, 'opp': None},
                  'mons': {'me': {}, 'opp': {}}, 'mega_used': {'me': False, 'opp': False}, 'history': []}

    def mon(self, side, name):
        mega = name in BASE
        name = BASE.get(name, name)
        m = self.s['mons'][side].setdefault(name, {'boosts': {}, 'item_consumed': None, 'items_seen': [],
                                                   'status': None, 'fainted': False, 'moves_seen': [],
                                                   'mega': False, 'ability': None})
        if mega:
            m['mega'] = True
        return m

    def apply(self, ev):
        s = self.s
        s['turn'] += 1
        for t, key in (('weather', 'weather_turns'), ('terrain', 'terrain_turns')):
            if s[key]:
                s[key] -= 1
                if s[key] == 0:
                    s[t] = None
        if s.get('trick_room'):
            s['trick_room'] -= 1
        if ev.get('trick_room_end'):
            s['trick_room'] = 0
        elif ev.get('trick_room'):
            s['trick_room'] = 4  # 5 turns including the one it was set up on
        for side in ('me', 'opp'):
            for mm in s['mons'][side].values():
                mm['glaive'] = False
        if ev['weather_end']:
            s['weather'], s['weather_turns'] = None, 0
        if ev['weather']:
            s['weather'], s['weather_turns'] = ev['weather'], 5
        if ev['terrain_end']:
            s['terrain'], s['terrain_turns'] = None, 0
        if ev['terrain']:
            s['terrain'], s['terrain_turns'] = ev['terrain'], 5
        for sw in ev['switch']:
            old = s['active'][sw['side']]
            if old:
                om = self.mon(sw['side'], old)
                om['boosts'] = {}
                om.update(sub=0, last_move=None, rampage=False, toxn=0)
            s['active'][sw['side']] = BASE.get(sw['mon'], sw['mon'])
            self.mon(sw['side'], sw['mon'])
        for m in ev['moves']:
            if not s['active'][m['side']]:
                s['active'][m['side']] = BASE.get(m['mon'], m['mon'])
            mm = self.mon(m['side'], m['mon'])
            if m['move'] not in mm['moves_seen']:
                mm['moves_seen'].append(m['move'])
            mm['rampage'] = m['move'] in RAMPAGE and not (mm.get('rampage') and mm.get('last_move') == m['move'])
            mm['last_move'] = m['move']
            mm['glaive'] = m['move'] == 'きょけんとつげき'
        for b in ev['boosts']:
            mb = self.mon(b['side'], b['mon'])['boosts']
            mb[b['stat']] = max(-6, min(6, mb.get(b['stat'], 0) + b['delta']))
        for it in ev['items']:
            side, name = it['side'], it['mon'] or s['active'][it['side']]
            if not name:
                continue
            mm = self.mon(side, name)
            if it['item'] not in mm['items_seen']:
                mm['items_seen'].append(it['item'])
            if it['consumed']:
                mm['item_consumed'] = it['item']
        for st in ev['status']:
            self.mon(st['side'], st['mon'])['status'] = st['status']
            self.mon(st['side'], st['mon'])['toxn'] = 0
        for sb in ev.get('sub', []):
            self.mon(sb['side'], sb['mon'])['sub'] = 25
        for sb in ev.get('sub_end', []):
            self.mon(sb['side'], sb['mon'])['sub'] = 0
        for side in ('me', 'opp'):
            act = s['active'][side]
            if act and self.mon(side, act).get('status') == 'tox':
                self.mon(side, act)['toxn'] = self.mon(side, act).get('toxn', 0) + 1
        for c in ev['cured']:
            self.mon(c['side'], c['mon'])['status'] = None
        for h in ev['hazards']:
            s['rocks_' + h['side']] = True
        for f in ev['faint']:
            self.mon(f['side'], f['mon'])['fainted'] = True
        for mg in ev['mega']:
            s['mega_used'][mg['side']] = True
            self.mon(mg['side'], mg['mon'])['mega'] = True
        for ab in ev['abilities']:
            self.mon(ab['side'], ab['mon'])['ability'] = ab['ability']
        s['history'].append({k: v for k, v in ev.items() if v})
        s['history'] = s['history'][-20:]
        self.save()

    def save(self):
        tmp = self.path + '.tmp'
        json.dump(self.s, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    lines = [l for l in open(sys.argv[1], encoding='utf-8').read().splitlines()] if len(sys.argv) > 1 else sys.stdin.read().splitlines()
    print(json.dumps(parse_turn(lines), ensure_ascii=False, indent=1))
