"""Champions (Showdown "champions" mod) data for the battle engine.

data/champ.json is produced by sd/export_showdown.js + sd/build_data.py from Pokémon Showdown.
Abilities, items and moves are referred to by Showdown ids (e.g. 'intimidate', 'choicescarf', 'uturn');
the Japanese names used everywhere else are converted with ab_id / item_id / move_id.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
_C = json.load(open(os.path.join(HERE, 'data', 'champ.json'), encoding='utf-8'))

TYPES = ['normal', 'fire', 'water', 'electric', 'grass', 'ice', 'fighting', 'poison', 'ground',
         'flying', 'psychic', 'bug', 'rock', 'ghost', 'dragon', 'dark', 'steel', 'fairy']
_SE = {
    'normal': ((), ('rock', 'steel'), ('ghost',)),
    'fire': (('grass', 'ice', 'bug', 'steel'), ('fire', 'water', 'rock', 'dragon'), ()),
    'water': (('fire', 'ground', 'rock'), ('water', 'grass', 'dragon'), ()),
    'electric': (('water', 'flying'), ('electric', 'grass', 'dragon'), ('ground',)),
    'grass': (('water', 'ground', 'rock'), ('fire', 'grass', 'poison', 'flying', 'bug', 'dragon', 'steel'), ()),
    'ice': (('grass', 'ground', 'flying', 'dragon'), ('fire', 'water', 'ice', 'steel'), ()),
    'fighting': (('normal', 'ice', 'rock', 'dark', 'steel'), ('poison', 'flying', 'psychic', 'bug', 'fairy'), ('ghost',)),
    'poison': (('grass', 'fairy'), ('poison', 'ground', 'rock', 'ghost'), ('steel',)),
    'ground': (('fire', 'electric', 'poison', 'rock', 'steel'), ('grass', 'bug'), ('flying',)),
    'flying': (('grass', 'fighting', 'bug'), ('electric', 'rock', 'steel'), ()),
    'psychic': (('fighting', 'poison'), ('psychic', 'steel'), ('dark',)),
    'bug': (('grass', 'psychic', 'dark'), ('fire', 'fighting', 'poison', 'flying', 'ghost', 'steel', 'fairy'), ()),
    'rock': (('fire', 'ice', 'flying', 'bug'), ('fighting', 'ground', 'steel'), ()),
    'ghost': (('psychic', 'ghost'), ('dark',), ('normal',)),
    'dragon': (('dragon',), ('steel',), ('fairy',)),
    'dark': (('psychic', 'ghost'), ('fighting', 'dark', 'fairy'), ()),
    'steel': (('ice', 'rock', 'fairy'), ('fire', 'water', 'electric', 'steel'), ()),
    'fairy': (('fighting', 'dragon', 'dark'), ('fire', 'poison', 'steel'), ()),
}
# typemod: +1 super effective, -1 resisted, None immune  (Showdown getEffectiveness / getImmunity)
TYPEMOD = {}
for _a in TYPES:
    for _d in TYPES:
        se, nve, imm = _SE[_a]
        TYPEMOD[_a, _d] = None if _d in imm else 1 if _d in se else -1 if _d in nve else 0
STATUS_IMMUNE = {'brn': ('fire',), 'par': ('electric',), 'psn': ('poison', 'steel'), 'tox': ('poison', 'steel'),
                 'frz': ('ice',), 'sandstorm': ('rock', 'ground', 'steel'), 'hail': ('ice',), 'trapped': ('ghost',),
                 'powder': ('grass',), 'prankster': ('dark',)}

_FW = str.maketrans('０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ', '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')


def _key(s):
    return s.translate(_FW).replace(' ', '')


class MoveData:
    __slots__ = ('id', 'ja', 'type', 'cat', 'bp', 'acc', 'pri', 'target', 'flags', 'crit', 'will_crit', 'drain', 'recoil',
                 'heal', 'self_switch', 'force_switch', 'multihit', 'multiacc', 'status', 'volatile', 'side', 'slot',
                 'weather', 'terrain', 'pseudo', 'boosts', 'self', 'secondaries', 'selfdestruct', 'crash', 'mindblown',
                 'ignore_def', 'ignore_eva', 'ignore_imm', 'override_off', 'override_off_mon', 'override_def',
                 'breaks_protect', 'stalling', 'sleep_usable', 'thaws', 'fixed', 'ohko', 'self_boost', 'callbacks',
                 'contact', 'sheer', 'pp')

    def __init__(self, ja, d):
        self.id, self.ja = d['id'], ja
        self.type = d['type'].lower()
        self.cat = d['category'].lower()
        self.bp = d.get('basePower', 0)
        self.acc = True if d.get('accuracy', True) is True else d['accuracy']
        self.pri = d.get('priority', 0)
        self.target = d.get('target', 'normal')
        self.flags = frozenset(k for k, v in d.get('flags', {}).items() if v)
        self.contact = 'contact' in self.flags
        self.crit = d.get('critRatio', 1)
        self.will_crit = d.get('willCrit')
        self.drain = d.get('drain')
        self.recoil = d.get('recoil')
        self.heal = d.get('heal')
        self.self_switch = d.get('selfSwitch')
        self.force_switch = d.get('forceSwitch', False)
        self.multihit = d.get('multihit')
        self.multiacc = d.get('multiaccuracy', False)
        self.status = d.get('status')
        self.volatile = d.get('volatileStatus')
        self.side = d.get('sideCondition')
        self.slot = d.get('slotCondition')
        self.weather = (d.get('weather') or '').lower() or None
        self.terrain = d.get('terrain')
        self.pseudo = d.get('pseudoWeather')
        self.boosts = d.get('boosts')
        self.self = d.get('self')
        secs = []
        for s in d.get('secondaries') or []:
            s = dict(s)
            if s.get('onHit') == '__fn__':
                s['onHit'] = True
            if s.get('self') and isinstance(s['self'], dict) and s['self'].get('onHit') == '__fn__':
                s['self'] = dict(s['self'], onHit=True)
            secs.append(s)
        self.secondaries = tuple(secs)
        # Sheer Force applies when the move has secondaries (even empty ones like Stone Axe) or hasSheerForceBoost
        self.sheer = bool(d.get('secondaries')) or bool(d.get('hasSheerForceBoost'))
        self.selfdestruct = d.get('selfdestruct')
        self.crash = d.get('hasCrashDamage', False)
        self.mindblown = d.get('mindBlownRecoil', False)
        self.ignore_def = d.get('ignoreDefensive', False)
        self.ignore_eva = d.get('ignoreEvasion', False)
        self.ignore_imm = d.get('ignoreImmunity')
        self.override_off = d.get('overrideOffensiveStat')
        self.override_off_mon = d.get('overrideOffensivePokemon')
        self.override_def = d.get('overrideDefensiveStat')
        self.breaks_protect = d.get('breaksProtect', False)
        self.stalling = d.get('stallingMove', False)
        self.sleep_usable = d.get('sleepUsable', False)
        self.thaws = d.get('thawsTarget', False)
        self.fixed = d.get('damage')
        self.ohko = d.get('ohko')
        self.self_boost = d.get('selfBoost')
        self.callbacks = frozenset(d.get('callbacks', ()))
        pp = min(20, d.get('pp', 5))
        # Champions: (pp / 5 + 1) * 4 uses (no PP Ups for Revival Blessing)
        self.pp = pp if self.id == 'revivalblessing' else int((pp / 5 + 1) * 4)

    def __repr__(self):
        return f'<{self.id}>'


MOVES = {}       # showdown id -> MoveData
MOVE_JA = {}     # Japanese (normalized) -> id
for _ja, _d in _C['moves'].items():
    _m = MoveData(_ja, _d)
    MOVES[_m.id] = _m
    MOVE_JA[_key(_ja)] = _m.id
# Struggle is not in any learnset: typeless 50 BP physical contact, 1/4 max HP recoil
MOVES['struggle'] = MoveData('わるあがき', {'id': 'struggle', 'type': '???', 'category': 'Physical', 'basePower': 50,
                                           'accuracy': True, 'pp': 1, 'priority': 0, 'target': 'randomNormal',
                                           'flags': {'contact': 1, 'protect': 1}, 'ignoreImmunity': True})
MOVE_JA[_key('わるあがき')] = 'struggle'
ABILITY_JA = {_key(k): v['id'] for k, v in _C['abilities'].items()}
ABILITIES = {v['id']: dict(v, ja=k) for k, v in _C['abilities'].items()}
ITEM_JA = {_key(k): v['id'] for k, v in _C['items'].items()}
ITEMS = {v['id']: dict(v, ja=k) for k, v in _C['items'].items()}
BERRIES = {k for k, v in ITEMS.items() if v.get('isBerry')}
SPECIES = _C['species']   # Japanese species name -> showdown species data
_SP_BY_NAME = {v['name']: k for k, v in SPECIES.items()}
# mega stone item id -> {base species ja: mega species ja}
MEGA_STONE = {}
for _iid, _it in ITEMS.items():
    if _it.get('megaStone'):
        MEGA_STONE[_iid] = {_SP_BY_NAME.get(b, b): _SP_BY_NAME.get(m, m) for b, m in _it['megaStone'].items()}


def move_id(ja):
    """Japanese move name (or showdown id) -> showdown id, or None."""
    if ja in MOVES:
        return ja
    return MOVE_JA.get(_key(ja))


def ab_id(ja):
    if not ja:
        return ''
    if ja in ABILITIES:
        return ja
    return ABILITY_JA.get(_key(ja), '')


def item_id(ja):
    if not ja:
        return ''
    if ja in ITEMS:
        return ja
    return ITEM_JA.get(_key(ja), '')


def species(ja):
    return SPECIES.get(ja)
