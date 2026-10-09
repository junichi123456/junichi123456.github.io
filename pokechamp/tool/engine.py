"""Pokémon Champions singles battle engine (port of Pokémon Showdown's gen9 "champions" mod).

Every move, ability, item and field condition that is legal in Champions is modelled here, following the
order of Showdown's event system (beforeTurn → switches → mega evolution → moves by priority/speed →
residual → replacements).  Randomness goes through an RNG object so the search can either take the
expected/most-likely outcome (ExpectedRNG) or branch over the outcomes that matter (EnumRNG).

  State      battle state (two Sides, field) — cheap clone()
  step(st, a0, a1, rng, chooser) -> new State
  Action     ('m', move_id) | ('s', bench_index)
"""
import math
import dex
from dex import MOVES, TYPEMOD, STATUS_IMMUNE, BERRIES, ITEMS, TYPES
for _t in TYPES + ['???']:
    TYPEMOD[_t, '???'] = 0
    TYPEMOD['???', _t] = 0

BOOSTS = ('atk', 'def', 'spa', 'spd', 'spe', 'accuracy', 'evasion')
STATS = ('atk', 'def', 'spa', 'spd', 'spe')
NATURE = {  # name: (up, down)
    'いじっぱり': ('atk', 'spa'), 'ようき': ('spe', 'spa'), 'ひかえめ': ('spa', 'atk'), 'おくびょう': ('spe', 'atk'),
    'わんぱく': ('def', 'spa'), 'ずぶとい': ('def', 'atk'), 'しんちょう': ('spd', 'spa'), 'おだやか': ('spd', 'atk'),
    'ゆうかん': ('atk', 'spe'), 'れいせい': ('spa', 'spe'), 'のんき': ('def', 'spe'), 'なまいき': ('spd', 'spe'),
    'むじゃき': ('spe', 'spd'), 'せっかち': ('spe', 'def'), 'やんちゃ': ('atk', 'spd'), 'うっかりや': ('spa', 'spd'),
    'さみしがり': ('atk', 'def'), 'おっとり': ('spa', 'def'), 'おとなしい': ('spd', 'def'), 'のうてんき': ('def', 'spd'),
}
PROTECTS = ('protect', 'detect', 'kingsshield', 'spikyshield', 'banefulbunker', 'obstruct', 'silktrap', 'burningbulwark')
SEMI_INV = ('fly', 'bounce', 'dig', 'dive', 'phantomforce', 'shadowforce')
WEATHER_ITEM = {'sunnyday': 'heatrock', 'raindance': 'damprock', 'sandstorm': 'smoothrock', 'snowscape': 'icyrock'}
TERRAINS = ('electricterrain', 'grassyterrain', 'mistyterrain', 'psychicterrain')
RESIST_BERRY = {'occaberry': 'fire', 'passhoberry': 'water', 'wacanberry': 'electric', 'rindoberry': 'grass',
                'yacheberry': 'ice', 'chopleberry': 'fighting', 'kebiaberry': 'poison', 'shucaberry': 'ground',
                'cobaberry': 'flying', 'payapaberry': 'psychic', 'tangaberry': 'bug', 'chartiberry': 'rock',
                'kasibberry': 'ghost', 'habanberry': 'dragon', 'colburberry': 'dark', 'babiriberry': 'steel',
                'roseliberry': 'fairy', 'chilanberry': 'normal'}
TYPE_ITEM = {'charcoal': 'fire', 'mysticwater': 'water', 'magnet': 'electric', 'miracleseed': 'grass',
             'nevermeltice': 'ice', 'blackbelt': 'fighting', 'poisonbarb': 'poison', 'softsand': 'ground',
             'sharpbeak': 'flying', 'twistedspoon': 'psychic', 'silverpowder': 'bug', 'hardstone': 'rock',
             'spelltag': 'ghost', 'dragonfang': 'dragon', 'blackglasses': 'dark', 'metalcoat': 'steel',
             'fairyfeather': 'fairy', 'silkscarf': 'normal'}
SKINS = {'aerilate': 'flying', 'pixilate': 'fairy', 'refrigerate': 'ice', 'dragonize': 'dragon', 'galvanize': 'electric'}
NO_SKIN = ('judgment', 'multiattack', 'naturalgift', 'revelationdance', 'technoblast', 'terrainpulse', 'weatherball')
SEEDS = {'electricseed': ('electricterrain', 'def'), 'grassyseed': ('grassyterrain', 'def'),
         'mistyseed': ('mistyterrain', 'spd'), 'psychicseed': ('psychicterrain', 'spd')}
STATUS_BERRY = {'cheriberry': ('par',), 'chestoberry': ('slp',), 'pechaberry': ('psn', 'tox'), 'rawstberry': ('brn',),
                'aspearberry': ('frz',)}
# abilities that mold breaker ignores (Showdown flags.breakable)
BREAKABLE = frozenset(k for k, v in dex.ABILITIES.items() if (v.get('flags') or {}).get('breakable'))
CANT_SUPPRESS = frozenset(k for k, v in dex.ABILITIES.items() if (v.get('flags') or {}).get('cantsuppress'))
MOLD = ('moldbreaker', 'teravolt', 'turboblaze', 'myceliummight')
HEAL_MOVES_TRIAGE = None


def pokeround(x):
    f = math.floor(x)
    return f if x - f <= 0.5 else f + 1


def modify(v, mod4096):
    """Showdown battle.modify with a 4096-based modifier."""
    return (v * mod4096 + 2047) // 4096


def chain(a, b):
    return (a * b + 2048) >> 12


def m4096(x):
    return int(x * 4096)


def jsround(x):
    """JavaScript Math.round (halves round up)."""
    return math.floor(x + 0.5)


# ---------------------------------------------------------------- static data per species form
class Form:
    __slots__ = ('ja', 'sid', 'num', 'types', 'stats', 'weight', 'ability', 'base', 'is_mega', 'name')

    def __init__(self, ja, nature, ap, ability):
        s = dex.SPECIES[ja]
        self.ja, self.sid, self.num, self.name = ja, s['id'], s['num'], s['name']
        self.types = tuple(t.lower() for t in s['types'])
        bs = s['baseStats']
        up, dn = NATURE.get(nature, (None, None))
        st = {'hp': bs['hp'] + 75 + ap.get('hp', 0)}
        for k in STATS:
            v = bs[k] + 20 + ap.get(k, 0)
            if k == up:
                v = v * 110 // 100
            elif k == dn:
                v = v * 90 // 100
            st[k] = v
        self.stats = st
        self.weight = int(round(s['weightkg'] * 10))
        self.ability = ability
        self.base = s['baseSpecies']
        self.is_mega = s.get('isMega', False)

    def __repr__(self):
        return self.ja


CALLS_MOVE = frozenset(('copycat', 'sleeptalk', 'metronome', 'assist', 'mefirst', 'mirrormove', 'naturepower'))


class Mon:
    __slots__ = ('name', 'form', 'base_form', 'mega_form', 'ability', 'item', 'moves', 'hp', 'maxhp', 'status',
                 'stime', 'tox', 'boosts', 'vol', 'types', 'added_type', 'last_move', 'last_item', 'ate_berry',
                 'active_turns', 'move_actions', 'times_attacked', 'hurt', 'raised', 'lowered', 'used_item',
                 'fainted', 'can_mega', 'switch_flag', 'force_switch', 'damaged_by', 'newly', 'last_result',
                 'this_result', 'busted', 'stats', 'side', 'idx', 'set_item', 'set_ability', 'move_used',
                 'protean', 'syrup', 'hero', 'abstate', 'faint_queued', 'times_hit_turn', 'nature', 'ap', 'pp',
                 'gender')

    def __init__(self, base_form, moves, item='', mega_form=None, side=0, idx=0):
        self.name = base_form.ja
        self.form = self.base_form = base_form
        self.mega_form = mega_form
        self.ability = self.set_ability = base_form.ability
        self.item = self.set_item = item
        self.moves = tuple(m for m in moves if m in MOVES) or ('struggle',)
        self.maxhp = self.hp = base_form.stats['hp']
        self.status = ''
        self.stime = 0
        self.tox = 0
        self.boosts = dict.fromkeys(BOOSTS, 0)
        self.vol = {}
        self.types = None
        self.added_type = None
        self.last_move = None
        self.last_item = ''
        self.ate_berry = False
        self.active_turns = 0
        self.move_actions = 0
        self.times_attacked = 0
        self.hurt = False
        self.raised = self.lowered = False
        self.used_item = False
        self.fainted = False
        self.can_mega = mega_form is not None
        # fixed gender of the species, else 'M' (what Showdown's sample(['M', 'F']) gives the test oracle)
        g = (dex.SPECIES.get(base_form.ja) or {}).get('gender')
        self.gender = '' if g == 'N' else (g or 'M')
        self.switch_flag = False
        self.force_switch = False
        self.damaged_by = None     # (damage, category, this_turn) of the last hit taken
        self.newly = True
        self.last_result = None
        self.this_result = None
        self.busted = False
        self.stats = None          # overridden stats (power trick etc.); None = form stats
        self.side, self.idx = side, idx
        self.move_used = ()
        self.protean = False
        self.syrup = False
        self.hero = False
        self.abstate = None
        self.faint_queued = False
        self.times_hit_turn = 0
        self.nature, self.ap = 'まじめ', {}
        self.pp = None             # {move: remaining PP} once a move has been used

    def clone(self):   # replaced below by a generated version (faster than getattr/setattr)
        n = Mon.__new__(Mon)
        for k in Mon.__slots__:
            setattr(n, k, getattr(self, k))
        n.boosts = self.boosts.copy()
        if self.pp is not None:
            n.pp = dict(self.pp)
        n.vol = _copy_vol(self.vol) if self.vol else {}
        return n

    @property
    def alive(self):
        return self.hp > 0 and not self.fainted

    def stat(self, k):
        return (self.stats or self.form.stats)[k]

    def __repr__(self):
        return f'{self.form.ja}({self.hp}/{self.maxhp})'


def _copy_vol(vol):
    return {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in vol.items()}


_src = ['def _mon_clone(self):', '    n = _new(Mon)']
_src += [f'    n.{k} = self.{k}' for k in Mon.__slots__ if k not in ('boosts', 'vol', 'pp')]
_src += ['    n.boosts = self.boosts.copy()', '    n.pp = dict(self.pp) if self.pp is not None else None',
         '    n.vol = _copy_vol(self.vol) if self.vol else {}', '    return n']
_ns = {'_new': object.__new__, 'Mon': Mon, '_copy_vol': _copy_vol}
exec('\n'.join(_src), _ns)
Mon.clone = _ns['_mon_clone']


class Side:
    """One player's side. Only the active mon is copied when the state is cloned; bench mons are shared
    with the parent state until own(j) makes a private copy (copy-on-write)."""
    __slots__ = ('mons', 'act', 'cond', 'slot', 'mega_used', 'fainted_total', 'fainted_last', 'owned')

    def clone(self):
        n = Side.__new__(Side)
        n.mons = list(self.mons)
        n.mons[self.act] = self.mons[self.act].clone()
        n.owned = {self.act}
        n.act = self.act
        n.cond = dict(self.cond)
        n.slot = {k: (list(v) if isinstance(v, list) else v) for k, v in self.slot.items()} if self.slot else {}
        n.mega_used = self.mega_used
        n.fainted_total = self.fainted_total
        n.fainted_last = self.fainted_last
        return n

    def own(self, j):
        if j not in self.owned:
            self.mons[j] = self.mons[j].clone()
            self.owned.add(j)
        return self.mons[j]


class State:
    __slots__ = ('sides', 'weather', 'wturns', 'terrain', 'tturns', 'pseudo', 'turn', 'winner', 'lastmove')

    def clone(self):
        n = State.__new__(State)
        n.sides = [s.clone() for s in self.sides]
        n.weather, n.wturns, n.terrain, n.tturns = self.weather, self.wturns, self.terrain, self.tturns
        n.pseudo = dict(self.pseudo)
        n.turn = self.turn
        n.winner = self.winner
        n.lastmove = self.lastmove
        return n

    def active(self, i):
        return self.sides[i].mons[self.sides[i].act]

    def done(self):
        """None while running, else +1 (side 0 wins) / -1 / 0."""
        if self.winner is not None:
            return self.winner
        a = any(m.alive for m in self.sides[0].mons)
        b = any(m.alive for m in self.sides[1].mons)
        return None if a and b else (1 if a else -1 if b else 0)


def new_side(mons):
    s = Side.__new__(Side)
    s.mons = mons
    s.act = 0
    s.cond = {}
    s.slot = {}
    s.mega_used = False
    s.fainted_total = 0
    s.fainted_last = False
    s.owned = set(range(len(mons)))
    for i, m in enumerate(mons):
        m.idx = i
    return s


def new_state(side0, side1):
    st = State.__new__(State)
    st.sides = [new_side(side0), new_side(side1)]
    for i in (0, 1):
        for m in st.sides[i].mons:
            m.side = i
    st.weather = st.terrain = ''
    st.wturns = st.tturns = 0
    st.pseudo = {}
    st.turn = 0
    st.winner = None
    st.lastmove = None
    return st


# ---------------------------------------------------------------- randomness
class ExpectedRNG:
    """Most likely outcome for every random event; accuracy and full paralysis scale the damage instead."""
    expected = True

    def chance(self, p, kind='', matters=False):
        return p > 0.5

    def roll(self, rolls, hp):
        return 7

    def sample(self, opts, kind=''):
        # opts: list of (value, prob)
        return max(opts, key=lambda x: x[1])[0]


class EnumRNG:
    """Replays a script of earlier answers, then answers the default (most likely) outcome and records the
    alternatives that are worth branching on."""
    expected = False

    def __init__(self, script=(), thresh=0.08, branch=True):
        self.script = script
        self.trace = []
        self.alts = []
        self.prob = 1.0
        self.thresh = thresh
        self.branch = branch

    def _q(self, opts, matters):
        pos = len(self.trace)
        if pos < len(self.script):
            v, p = self.script[pos]
            self.trace.append((v, p))
            self.prob *= p
            return v
        opts = sorted(opts, key=lambda x: -x[1])
        v0, p0 = opts[0]
        sig = [(v, p) for v, p in opts[1:] if p > 0 and (p >= self.thresh or (matters and p >= 0.02))]
        if sig and self.branch:
            tot = p0 + sum(p for _, p in sig)
            for v, p in sig:
                self.alts.append((pos, (v, p / tot)))
            self.trace.append((v0, p0 / tot))
            self.prob *= p0 / tot
        else:
            self.trace.append((v0, 1.0))
        return v0

    def chance(self, p, kind='', matters=False):
        if p >= 1:
            return True
        if p <= 0:
            return False
        return self._q([(True, p), (False, 1 - p)], matters)

    def roll(self, rolls, hp):
        k = sum(1 for x in rolls if x < hp)
        if k == 0 or k == 16 or hp <= 0:
            return 7
        lo, hi = (k - 1) // 2, (k + 15) // 2
        return self._q([(lo, k / 16), (hi, (16 - k) / 16)], True)

    def sample(self, opts, kind=''):
        if len(opts) == 1:
            return opts[0][0]
        return self._q(list(opts), False)


class TestRNG(ExpectedRNG):
    """Deterministic most-likely outcomes without damage scaling (matches sd/oracle.js)."""
    expected = False
    pessimistic_ties = True


EXPECTED = ExpectedRNG()


def enumerate_step(st, a0, a1, chooser=None, max_leaves=12, thresh=0.08):
    """All significantly different outcomes of one turn: [(prob, state)] (probabilities sum to 1)."""
    out = []
    stack = [()]
    while stack:
        script = stack.pop()
        rng = EnumRNG(script, thresh, branch=len(out) + len(stack) + 1 < max_leaves)
        s2 = step(st, a0, a1, rng, chooser)
        out.append([rng.prob, s2])
        for pos, alt in rng.alts:
            if len(out) + len(stack) < max_leaves:
                stack.append(tuple(rng.trace[:pos]) + (alt,))
    tot = sum(p for p, _ in out) or 1
    return [(p / tot, s) for p, s in out]


# ---------------------------------------------------------------- the battle runtime (one turn)
class _GameOver(Exception):
    pass


class Battle:

    def __init__(self, st, rng=EXPECTED, chooser=None, log=None):
        self.st, self.rng, self.chooser, self.log = st, rng, chooser, log
        self.queue = []
        self.move = None
        self.user = self.target = None
        self.scale = 1.0
        self.ignore_ab = False
        self.faint_q = []
        self.moved = set()
        self.bypass_protect = False
        self.bounced = False
        self._ps_fail = False
        self.flags = {}
        self.infiltrates = False
        self.hit_sub = False
        self.sheer = False
        self.contact = False
        self.type = 'normal'
        self.cat = 'status'
        self.secondaries = []
        self.multihit = None
        self.fling_pending = None
        self.total = 0
        self.cur_hit = 1
        self.crit_hit = False
        self.in_move = False

    def L(self, *a):
        if self.log is not None:
            self.log.append(' '.join(str(x) for x in a))

    # ---- basic accessors
    def act(self, i):
        return self.st.sides[i].mons[self.st.sides[i].act]

    def foe(self, m):
        return self.act(1 - m.side)

    def is_active(self, m):
        return self.st.sides[m.side].act == m.idx and not m.fainted

    def ab(self, m):
        """Effective ability (suppressed by Gastro Acid; Mold Breaker handled by tab())."""
        if not m.ability:
            return ''
        if 'gastroacid' in m.vol and m.ability not in CANT_SUPPRESS:
            return ''
        return m.ability

    def tab(self, m):
        """Ability of a move's target: ignored by Mold Breaker & co when breakable."""
        a = self.ab(m)
        if a and self.ignore_ab and a in BREAKABLE and m is not self.user:
            return ''
        return a

    def it(self, m):
        if not m.item:
            return ''
        if 'magicroom' in self.st.pseudo or self.ab(m) == 'klutz':
            if not dex.ITEMS.get(m.item, {}).get('megaStone'):
                return ''
        return m.item

    def types(self, m):
        t = m.types if m.types is not None else m.form.types
        if 'roost' in m.vol and 'flying' in t:
            t = tuple(x for x in t if x != 'flying') or ('normal',)
        if m.added_type and m.added_type not in t:
            t = tuple(t) + (m.added_type,)
        return t

    def has_type(self, m, t):
        return t in self.types(m)

    def eff_weather(self, m=None):
        if self.in_move and self.user is not None and self.ab(self.user) == 'megasol':
            return 'sunnyday'
        w = self.st.weather
        if not w:
            return ''
        for i in (0, 1):
            a = self.act(i)
            if a.alive and self.ab(a) in ('cloudnine', 'airlock'):
                return ''
        return w

    def grounded(self, m, negate=False):
        if 'gravity' in self.st.pseudo or 'ingrain' in m.vol or 'smackdown' in m.vol:
            return True
        if self.it(m) == 'ironball':
            return True
        if not negate and self.has_type(m, 'flying'):
            return False
        if self.tab(m) in ('levitate', 'eelevate'):
            return None
        if 'magnetrise' in m.vol:
            return False
        return self.it(m) != 'airballoon'

    def status_immune(self, m, kind):
        """runStatusImmunity: types + abilities."""
        ts = STATUS_IMMUNE.get(kind, ())
        for t in self.types(m):
            if t in ts:
                return True
        a = self.tab(m)
        if kind == 'sandstorm' and (a in ('overcoat', 'sandforce', 'sandrush', 'sandveil') or 'dig' in m.vol or
                                    'dive' in m.vol):
            return True
        if kind == 'powder' and a == 'overcoat':
            return True
        if kind == 'frz' and a == 'magmaarmor':
            return True
        if kind == 'frz' and self.eff_weather(m) == 'sunnyday':
            return True
        if kind == 'trapped' and a == 'runaway':
            return True
        return False

    def weight(self, m):
        w = m.form.weight
        a = self.tab(m)
        if a == 'heavymetal':
            w *= 2
        elif a == 'lightmetal':
            w = w // 2
        return max(1, w)

    # ---- stats
    def boosted(self, v, b):
        b = max(-6, min(6, b))
        return v * (2 + b) // 2 if b >= 0 else v * 2 // (2 - b)

    def speed(self, m):
        s = self.boosted(m.stat('spe'), m.boosts['spe'])
        mod = 4096
        a, it = self.ab(m), self.it(m)
        w = self.eff_weather(m)
        if it == 'choicescarf':
            mod = chain(mod, 6144)
        if it == 'ironball':
            mod = chain(mod, 2048)
        if self.st.sides[m.side].cond.get('tailwind'):
            mod = chain(mod, 8192)
        if (a == 'chlorophyll' and w == 'sunnyday') or (a == 'swiftswim' and w == 'raindance') or \
                (a == 'sandrush' and w == 'sandstorm') or (a == 'slushrush' and w == 'snowscape') or \
                (a == 'surgesurfer' and self.st.terrain == 'electricterrain'):
            mod = chain(mod, 8192)
        if a == 'quickfeet' and m.status:
            mod = chain(mod, 6144)
        if a == 'unburden' and 'unburden' in m.vol and not m.item:
            mod = chain(mod, 8192)
        if a in ('protosynthesis', 'quarkdrive') and m.vol.get(a) == 'spe':
            mod = chain(mod, 6144)
        s = modify(s, mod)
        if m.status == 'par' and a != 'quickfeet':
            s = s * 50 // 100
        return min(s, 10000)

    def action_speed(self, m):
        s = self.speed(m)
        return -s if self.st.pseudo.get('trickroom') else s

    # ---- logging of faint / win
    def check_faint(self, m, source=None, effect=None):
        if m.hp <= 0 and not m.fainted and not m.faint_queued:
            m.hp = 0
            m.faint_queued = True
            self.faint_q.append((m, source, effect))

    def faint_messages(self):
        last = None
        n = 0
        while self.faint_q:
            m, source, effect = self.faint_q.pop(0)
            if m.fainted:
                continue
            side = self.st.sides[m.side]
            side.fainted_total += 1
            side.fainted_last = True
            self.L('faint', m.name)
            # Destiny Bond
            if 'destinybond' in m.vol and source is not None and source is not m and effect == 'move' and \
                    source.alive and source.side != m.side:
                source.hp = 0
                self.check_faint(source, m, 'dbond')
            m.fainted = True
            if 'transformed' in m.vol:
                m.form, m.stats, m.moves, m.ability = m.vol['transformed']
            m.vol = {}
            m.boosts = dict.fromkeys(BOOSTS, 0)
            m.status = ''
            m.faint_queued = False
            last = (m, source, effect)
            n += 1
        if last is None:
            return
        self.check_win(last[0].side)
        if self.st.winner is not None:
            return
        # AfterFaint (once, with the number of faints): Moxie & co on the attacker
        m, source, effect = last
        if source is not None and effect == 'move' and source.alive and source.side != m.side:
            a = self.ab(source)
            if a == 'moxie' or a == 'chillingneigh':
                self.boost(source, {'atk': n}, source, 'ability')
            elif a == 'grimneigh':
                self.boost(source, {'spa': n}, source, 'ability')
            elif a in ('beastboost', 'eelevate'):
                best = max(STATS, key=lambda k: self.boosted(source.stat(k), 0))
                self.boost(source, {best: n}, source, 'ability')

    def check_win(self, last_side=None):
        if self.st.winner is not None:
            return
        a = any(m.alive for m in self.st.sides[0].mons)
        b = any(m.alive for m in self.st.sides[1].mons)
        if not a and not b:
            # both sides out: the side whose Pokémon fainted last wins (Showdown gen5+)
            self.st.winner = 0 if last_side is None else (1 if last_side == 0 else -1)
        elif not a:
            self.st.winner = -1
        elif not b:
            self.st.winner = 1

    # ---- damage & healing
    def damage(self, m, d, source=None, effect='', instafaint=False):
        """spreadDamage for non-move damage and for move damage after calculation. Returns damage dealt."""
        if not m.alive or d is None:
            return 0
        if effect == 'weather' and self.status_immune(m, self.st.weather):
            return 0
        d = max(1, int(d)) if d > 0 else 0
        if not d:
            return 0
        a = self.ab(m) if effect != 'move' else self.tab(m)
        is_move = effect in ('move', 'confusion')
        # Damage event (by priority)
        if a == 'magicguard' and not is_move and effect not in ('recoil_struggle', 'direct'):
            return 0
        if effect in ('psn', 'tox') and a == 'poisonheal':
            self.heal(m, m.maxhp // 8, m, 'ability')
            return 0
        if effect == 'brn' and a == 'heatproof':
            d = d // 2
        if effect == 'recoil' and a == 'rockhead':
            return 0
        if is_move:
            if 'endure' in m.vol and d >= m.hp:
                d = m.hp - 1
            if a == 'sturdy' and m.hp == m.maxhp and d >= m.hp:
                d = m.hp - 1
            it = self.it(m)
            if it == 'focussash' and m.hp == m.maxhp and d >= m.hp:
                if self.use_item(m):
                    d = m.hp - 1
            elif it == 'focusband' and d >= m.hp and self.rng.chance(0.1, 'focusband', True):
                d = m.hp - 1
        if d <= 0:
            return 0
        if effect == 'move' and a in ('berserk', 'angershell') and not self.multihit:
            m.vol['berserk_wait'] = True
        d = min(d, m.hp)
        m.hp -= d
        m.hurt = True
        if m.hp <= 0:
            m.hp = 0
            self.check_faint(m, source, 'move' if effect == 'move' else effect)
        return d

    def heal(self, m, d, source=None, effect=''):
        if not m.alive or 'healblock' in m.vol:
            return 0
        if d and d <= 1:
            d = 1
        d = int(d)
        it = self.it(m)
        if effect in ('drain', 'leechseed', 'strengthsap'):
            if it == 'bigroot':
                d = modify(d, 5324)
            if source is not None and source is not m and self.ab(source) == 'liquidooze':
                self.damage(m, d, source, 'ability')
                return 0
        if effect == 'berry' and self.ab(m) == 'ripen':
            d *= 2
        if not d or m.hp >= m.maxhp:
            return 0
        d = min(d, m.maxhp - m.hp)
        m.hp += d
        return d

    # ---- stat stages
    def boost(self, m, boosts, source=None, effect='', is_secondary=False, is_self=False, kind=''):
        """Battle.boost. effect: 'move'|'ability'|'item'|'intimidate'|'' ; returns True if anything changed."""
        if not m.alive or not self.is_active(m):
            return False
        if all(x.fainted for x in self.st.sides[1 - m.side].mons):
            return False
        a = self.ab(m) if (source is m or effect != 'move') else self.tab(m)
        b = dict(boosts)
        # ChangeBoost
        if a == 'contrary':
            b = {k: -v for k, v in b.items()}
        if a == 'simple':
            b = {k: v * 2 for k, v in b.items()}
        if effect == 'berry' and a == 'ripen':
            b = {k: v * 2 for k, v in b.items()}
        # cap
        b = {k: v for k, v in b.items() if v}
        # TryBoost (only for drops caused by others)
        other = source is not None and source is not m
        if other:
            if 'mist' in self.st.sides[m.side].cond and effect == 'move' and not self.infiltrates:
                b = {k: v for k, v in b.items() if v > 0}
            if a in ('clearbody', 'whitesmoke', 'fullmetalbody'):
                b = {k: v for k, v in b.items() if v > 0}
            elif a == 'hypercutter':
                b = {k: v for k, v in b.items() if not (k == 'atk' and v < 0)}
            elif a == 'bigpecks':
                b = {k: v for k, v in b.items() if not (k == 'def' and v < 0)}
            elif a in ('keeneye', 'illuminate', 'mindseye'):
                b = {k: v for k, v in b.items() if not (k == 'accuracy' and v < 0)}
            elif a == 'flowerveil' and self.has_type(m, 'grass'):
                b = {k: v for k, v in b.items() if v > 0}
            elif a == 'mirrorarmor' and effect != 'mirrorarmor':
                neg = {k: v for k, v in b.items() if v < 0 and m.boosts[k] > -6}
                b = {k: v for k, v in b.items() if v > 0}
                if neg and source is not None and source.alive:
                    self.boost(source, neg, m, 'mirrorarmor')
            if effect == 'intimidate' and 'atk' in b:
                if a in ('innerfocus', 'oblivious', 'owntempo', 'scrappy'):
                    del b['atk']
                elif a == 'guarddog':
                    del b['atk']
                    self.boost(m, {'atk': 1}, m, 'ability')
        changed = False
        for k, v in b.items():
            old = m.boosts[k]
            new = max(-6, min(6, old + v))
            if new != old:
                m.boosts[k] = new
                changed = True
                if new > old:
                    m.raised = True
                else:
                    m.lowered = True
                # AfterEachBoost: Defiant / Competitive
                if new < old and other and source.side != m.side:
                    if a == 'defiant':
                        self.boost(m, {'atk': 2}, m, 'ability')
                    elif a == 'competitive':
                        self.boost(m, {'spa': 2}, m, 'ability')
        if effect == 'intimidate' and 'atk' in boosts and a == 'rattled':
            self.boost(m, {'spe': 1}, m, 'ability')
        # Opportunist on the foe copies positive boosts
        if changed and any(v > 0 for v in b.values()):
            f = self.foe(m)
            if f is not m and f.alive and self.ab(f) == 'opportunist' and effect not in ('opportunist',):
                pos = {k: v for k, v in b.items() if v > 0}
                self.boost(f, pos, f, 'opportunist')
        return changed

    def white_herb(self, m):
        if any(m.boosts[k] < 0 for k in BOOSTS) and self.use_item(m):
            for k in BOOSTS:
                if m.boosts[k] < 0:
                    m.boosts[k] = 0

    # ---- items
    def use_item(self, m):
        if not m.item or (not m.alive and not m.item.endswith('gem')) or not self.is_active(m):
            return False
        it = m.item
        m.last_item = it
        m.item = ''
        m.used_item = True
        if self.ab(m) == 'unburden':
            m.vol['unburden'] = True
        return True

    def eat_item(self, m, force=False):
        it = m.item
        if not it or it not in BERRIES or not m.alive:
            return False
        if not force:
            f = self.foe(m)
            if f.alive and self.ab(f) in ('unnerve', 'asone'):
                return False
        self.berry_effect(m, it)
        m.last_item = it
        m.item = ''
        m.used_item = True
        m.ate_berry = True
        if self.ab(m) == 'unburden':
            m.vol['unburden'] = True
        if self.ab(m) == 'cheekpouch':
            self.heal(m, m.maxhp // 3, m, 'ability')
        if self.ab(m) == 'cudchew':
            m.vol['cudchew'] = [it, 2]
        return True

    def berry_effect(self, m, it):
        if it == 'sitrusberry':
            self.heal(m, m.maxhp // 4, m, 'berry')
        elif it == 'oranberry':
            self.heal(m, 10, m, 'berry')
        elif it == 'lumberry':
            m.status = ''
            m.vol.pop('confusion', None)
        elif it in STATUS_BERRY:
            if m.status in STATUS_BERRY[it]:
                m.status = ''
        elif it == 'persimberry':
            m.vol.pop('confusion', None)
        elif it == 'leppaberry':
            pass

    def take_item(self, m, source=None):
        """Pokemon.takeItem — returns the item id or '' (failed)."""
        if not m.item:
            return ''
        if dex.ITEMS.get(m.item, {}).get('megaStone'):
            return ''
        if self.tab(m) == 'stickyhold' and m.alive and (source is not m):
            return ''
        it = m.item
        m.item = ''
        if self.ab(m) == 'unburden':
            m.vol['unburden'] = True
        return it

    def update(self, m):
        """'Update' event: berries & herbs & curing abilities."""
        if not m.alive or not self.is_active(m):
            return
        a = self.ab(m)
        if a == 'trace' and 'traceseek' in m.vol:
            f = self.foe(m)
            if f.alive and self.ab(f) and not (dex.ABILITIES.get(self.ab(f), {}).get('flags') or {}).get('notrace'):
                del m.vol['traceseek']
                m.ability = self.ab(f)
                self.ability_start(m)
                a = m.ability
        if m.status == 'slp' and a in ('insomnia', 'vitalspirit'):
            m.status = ''
        if m.status in ('psn', 'tox') and a == 'immunity':
            m.status = ''
        if m.status == 'par' and a == 'limber':
            m.status = ''
        if m.status == 'brn' and a in ('waterveil', 'waterbubble', 'thermalexchange'):
            m.status = ''
        if m.status == 'frz' and a == 'magmaarmor':
            m.status = ''
        if 'confusion' in m.vol and a == 'owntempo':
            del m.vol['confusion']
        if a == 'oblivious':
            m.vol.pop('taunt', None)
            m.vol.pop('attract', None)
        it = self.it(m)
        if not it:
            return
        if it in ('sitrusberry', 'oranberry') and m.hp * 2 <= m.maxhp:
            if 'berserk_wait' not in m.vol:
                self.eat_item(m)
        elif it == 'lumberry' and (m.status or 'confusion' in m.vol):
            self.eat_item(m)
        elif it in STATUS_BERRY and m.status in STATUS_BERRY[it]:
            self.eat_item(m)
        elif it == 'persimberry' and 'confusion' in m.vol:
            self.eat_item(m)
        elif it == 'mentalherb' and any(v in m.vol for v in ('attract', 'taunt', 'encore', 'torment', 'disable', 'healblock')):
            if self.use_item(m):
                for v in ('attract', 'taunt', 'encore', 'torment', 'disable', 'healblock'):
                    m.vol.pop(v, None)

    def herbs(self):
        """White Herb (onAnySwitchIn / onAnyAfterMove / onAnyAfterMega / residual)."""
        for i in (0, 1):
            x = self.act(i)
            if x.alive and self.it(x) == 'whiteherb':
                self.white_herb(x)

    def update_all(self):
        for i in (0, 1):
            m = self.act(i)
            self.update(m)
            if m.busted is True:
                # Disguise busted this hit: 1/8 damage
                m.busted = 'done'
                self.damage(m, m.maxhp // 8, m, 'disguise')

    # ---- status
    def set_status(self, m, status, source=None, by_move=False, secondary=False, ignore_imm=False, hazard=False,
                   replace=False):
        if not m.alive or not self.is_active(m):
            return False
        if m.status and (not replace or m.status == status):
            return False
        a = self.tab(m) if source is not m else self.ab(m)
        corrosion = source is not None and self.ab(source) == 'corrosion' and status in ('psn', 'tox')
        if not ignore_imm and not corrosion and self.status_immune(m, 'psn' if status == 'tox' else status):
            return False
        g = self.grounded(m)
        # SetStatus event
        if self.st.terrain == 'mistyterrain' and g and not self.semi_inv(m):
            return False
        if status == 'slp' and self.st.terrain == 'electricterrain' and g and not self.semi_inv(m):
            return False
        sg = self.st.sides[m.side].cond.get('safeguard')
        if sg and source is not None and source is not m and not (self.infiltrates and source.side != m.side):
            return False
        if status == 'slp' and a in ('insomnia', 'vitalspirit', 'sweetveil'):
            return False
        if status == 'slp':
            for i in (0, 1):
                x = self.act(i)
                if x.alive and 'uproar' in x.vol:
                    return False
        if status in ('psn', 'tox') and a == 'immunity':
            return False
        if status == 'par' and a == 'limber':
            return False
        if status == 'brn' and a in ('waterveil', 'waterbubble', 'thermalexchange'):
            return False
        if a == 'leafguard' and self.eff_weather(m) == 'sunnyday':
            return False
        if a == 'purifyingsalt' or a == 'comatose':
            return False
        if a == 'flowerveil' and self.has_type(m, 'grass') and source is not None and source is not m:
            return False
        if a == 'shieldsdown':
            return False
        m.status = status
        if status == 'slp' and replace:
            m.stime = 3
        elif status == 'slp':
            m.stime = self.rng.sample([(2, 1 / 3), (3, 2 / 3)], 'sleep')
        elif status == 'frz':
            m.stime = 3
        elif status == 'tox':
            m.tox = 0
        self.L('status', m.name, status)
        # AfterSetStatus: Synchronize, Lum Berry
        if a == 'synchronize' and source is not None and source is not m and status in ('brn', 'par', 'psn', 'tox') \
                and not hazard:
            self.set_status(source, status, m)
        if self.it(m) == 'lumberry' or (self.it(m) in STATUS_BERRY and status in STATUS_BERRY[self.it(m)]):
            self.eat_item(m)
        return True

    def semi_inv(self, m):
        return any(v in m.vol for v in SEMI_INV)

    def add_volatile(self, m, vid, source=None, effect='move', data=True):
        if not m.alive:
            return False
        if vid in m.vol and vid != 'stockpile':
            if vid == 'smackdown':
                for v in ('fly', 'bounce'):
                    m.vol.pop(v, None)
            return False
        a = self.tab(m) if (source is not None and source is not m) else self.ab(m)
        g = self.grounded(m)
        # TryAddVolatile
        if vid == 'confusion':
            if a == 'owntempo':
                return False
            if self.st.terrain == 'mistyterrain' and g and not self.semi_inv(m):
                return False
            if self.st.sides[m.side].cond.get('safeguard') and source is not None and source is not m and not self.infiltrates:
                return False
        if vid == 'flinch' and (a == 'innerfocus' or 'focuspunch' in m.vol):
            return False
        if vid == 'yawn':
            if a in ('insomnia', 'vitalspirit', 'sweetveil', 'purifyingsalt', 'comatose') or \
                    (a == 'leafguard' and self.eff_weather(m) == 'sunnyday') or \
                    (a == 'flowerveil' and self.has_type(m, 'grass')):
                return False
            if self.st.terrain == 'electricterrain' and g and not self.semi_inv(m):
                return False
            if self.st.sides[m.side].cond.get('safeguard') and source is not m:
                return False
        if vid in ('attract', 'disable', 'encore', 'healblock', 'taunt', 'torment') and a == 'aromaveil':
            return False
        if vid in ('taunt', 'attract') and a == 'oblivious':
            return False
        if vid == 'trapped' and self.status_immune(m, 'trapped'):
            return False
        # start
        if vid == 'confusion':
            mn = 3 if effect == 'axekick' else 2
            data = self.rng.sample([(t, 1 / (6 - mn)) for t in range(mn, 6)], 'confusion')
        elif vid == 'substitute':
            data = m.maxhp // 4
            m.vol.pop('partiallytrapped', None)
        elif vid == 'taunt':
            data = 3 + (1 if (m.active_turns and not self.will_move(m)) else 0)
        elif vid == 'encore':
            lm = m.last_move
            if not lm or lm in ('struggle', 'encore', 'mimic', 'transform', 'sketch', 'mirrormove', 'sleeptalk', 'copycat',
                                'assist', 'metronome') or lm not in m.moves:
                return False
            # champions: replaces the target's queued action right away
            for act in self.queue:
                if act[0] == 'move' and act[1] is m and act[2] != lm and self.it(m) != 'mentalherb':
                    act[2] = lm
            data = {'move': lm, 'dur': 3 + (0 if self.will_move(m) else 1)}
        elif vid == 'disable':
            lm = m.last_move
            if not lm or lm == 'struggle':
                return False
            data = {'move': lm, 'dur': 4 if self.will_move(m) else 5}
        elif vid == 'yawn':
            data = 2
        elif vid == 'perishsong':
            data = 4
        elif vid == 'magnetrise':
            if 'smackdown' in m.vol or 'ingrain' in m.vol or 'gravity' in self.st.pseudo:
                return False
            data = 5
        elif vid == 'throatchop':
            data = 2
        elif vid == 'syrupbomb':
            data = {'dur': 4, 'src': source.side if source is not None else 1 - m.side}
        elif vid == 'partiallytrapped':
            data = {'dur': self.rng.sample([(5, .5), (6, .5)], 'bind'),
                    'div': 6 if source is not None and self.it(source) == 'bindingband' else 8,
                    'src': (source.side, source.idx) if source is not None else None}
        elif vid == 'smackdown':
            applies = self.has_type(m, 'flying') or self.ab(m) in ('levitate', 'eelevate')
            if self.it(m) == 'ironball' or 'ingrain' in m.vol or 'gravity' in self.st.pseudo:
                applies = False
            for v in ('fly', 'bounce'):
                if m.vol.pop(v, None):
                    applies = True
                    m.vol.pop('twoturnmove', None)
            if m.vol.pop('magnetrise', None):
                applies = True
            if not applies:
                return False
        elif vid == 'focusenergy':
            if 'dragoncheer' in m.vol:
                return False
        elif vid == 'dragoncheer':
            if 'focusenergy' in m.vol:
                return False
            data = 2 if self.has_type(m, 'dragon') else 1
        elif vid == 'stockpile':
            st = m.vol.get('stockpile') or {'layers': 0, 'def': 0, 'spd': 0}
            if st['layers'] >= 3:
                return False
            st = dict(st)
            st['layers'] += 1
            cd, cs = m.boosts['def'], m.boosts['spd']
            m.vol['stockpile'] = st
            self.boost(m, {'def': 1, 'spd': 1}, m, 'move')
            if cd != m.boosts['def']:
                st['def'] -= 1
            if cs != m.boosts['spd']:
                st['spd'] -= 1
            return True
        elif vid == 'leechseed':
            data = 1 - m.side if source is None else source.side
        elif vid == 'attract':
            if source is None or {m.gender, source.gender} != {'M', 'F'}:
                return False
            data = (source.side, source.idx)
            m.vol[vid] = data
            if self.it(m) == 'destinyknot' and source is not m and 'attract' not in source.vol:
                self.add_volatile(source, 'attract', m)
            return True
        m.vol[vid] = data
        return True

    def will_move(self, m):
        for a in self.queue:
            if a[0] == 'move' and a[1] is m:
                return True
        return False

    def queued_move(self, m):
        for a in self.queue:
            if a[0] == 'move' and a[1] is m:
                return a[2]
        return None

    # ---- switching
    def can_switch(self, side):
        s = self.st.sides[side]
        return any(m.alive and j != s.act for j, m in enumerate(s.mons))

    def switch_out(self, m):
        a = self.ab(m)
        if m.alive:
            if a == 'regenerator':   # pokemon.heal(): no TryHeal event, so Heal Block does not stop it
                m.hp = min(m.maxhp, m.hp + m.maxhp // 3)
            elif a == 'naturalcure':
                m.status = ''
            elif a == 'zerotohero' and not m.hero and 'イルカマン(マイティ)' in dex.SPECIES:
                m.hero = True
                m.base_form = m.form = Form('イルカマン(マイティ)', m.nature, m.ap, 'zerotohero')
        if 'transformed' in m.vol:
            m.form, m.stats, m.moves, m.ability = m.vol['transformed']
        m.vol = {}
        m.boosts = dict.fromkeys(BOOSTS, 0)
        m.types = None
        m.added_type = None
        if m.form.ja == 'ブレードギルガルド' and m.base_form.ja == 'ギルガルド':
            m.form = m.base_form
        m.ability = m.set_ability if not m.form.is_mega else m.form.ability
        m.last_move = None
        m.last_result = m.this_result = None
        m.switch_flag = m.force_switch = False
        m.active_turns = 0
        m.move_actions = 0
        m.tox = 0
        m.protean = False
        m.times_attacked = 0
        m.newly = True
        m.stats = None
        m.raised = m.lowered = False
        m.damaged_by = None
        m.times_hit_turn = 0

    def switch_in(self, side, j, copy=None):
        """Switch the active mon of `side` to bench slot j and run switch-in effects."""
        s = self.st.sides[side]
        old = s.mons[s.act]
        passed = None
        if copy and old.alive:
            if copy == 'copyvolatile':
                passed = ({k: v for k, v in old.boosts.items()},
                          {k: v for k, v in old.vol.items() if k in ('substitute', 'confusion', 'leechseed', 'curse',
                                                                        'focusenergy', 'dragoncheer', 'ingrain',
                                                                        'aquaring', 'magnetrise', 'perishsong',
                                                                        'powertrick', 'gastroacid', 'octolock',
                                                                        'partiallytrapped', 'taunt', 'healblock',
                                                                        'embargo', 'laserfocus', 'telekinesis',
                                                                        'noretreat', 'tarshot', 'charge', 'throatchop',
                                                                        'stall')})
            elif copy == 'shedtail' and 'substitute' in old.vol:
                passed = ({}, {'substitute': old.vol['substitute']})
        if old.alive:
            self.switch_out(old)
        s.act = j
        m = s.own(j)
        m.newly = True
        m.active_turns = 0
        m.move_actions = 0
        m.move_used = ()
        if passed:
            m.boosts.update(passed[0])
            m.vol.update(passed[1])
        self.L('switch', side, m.name)
        self.run_switch([m])

    def run_switch(self, mons):
        """SwitchIn handlers: hazards & slot conditions, then abilities, then items; faster mon first."""
        mons = sorted(mons, key=lambda x: (-self.action_speed(x), -x.side))
        hp0 = {id(m): m.hp for m in mons}
        for m in mons:
            self.update(m)
        for m in mons:
            self.hazards(m)
            self.faint_messages()
            if self.st.winner is not None:
                return
        for m in mons:
            if m.alive:
                self.ability_start(m)
        for m in mons:
            if m.alive:
                self.item_start(m)
        for i in (0, 1):
            self.update(self.act(i))
        self.herbs()
        self.faint_messages()
        if len(mons) == 1:
            for m in mons:
                self.emergency_exit(m, hp0[id(m)])

    def emergency_exit(self, m, hp_before):
        """Emergency Exit / Wimp Out after non-move damage (hazards, residual)."""
        if m.alive and self.is_active(m) and self.ab(m) in ('emergencyexit', 'wimpout') and \
                m.hp * 2 <= m.maxhp < hp_before * 2 and self.can_switch(m.side) and self.st.winner is None:
            j = self.choose_switch(m.side)
            if j is not None:
                self.switch_in(m.side, j)

    def hazards(self, m):
        s = self.st.sides[m.side]
        if not m.alive:
            return
        hw = s.slot.pop('healingwish', None)
        if hw and (m.hp < m.maxhp or m.status):
            m.hp = m.maxhp
            m.status = ''
        elif hw:
            s.slot['healingwish'] = hw
        boots = self.it(m) == 'heavydutyboots'
        if s.cond.get('stealthrock') and not boots:
            tm = sum(TYPEMOD['rock', t] or 0 for t in self.types(m))
            self.damage(m, m.maxhp * (2 ** tm) // 8 if tm >= 0 else m.maxhp // (8 * 2 ** -tm), None, 'hazard')
        g = self.grounded(m)
        if s.cond.get('spikes') and g and not boots:
            self.damage(m, [0, 3, 4, 6][s.cond['spikes']] * m.maxhp // 24, None, 'hazard')
        if s.cond.get('toxicspikes') and g:
            if self.has_type(m, 'poison'):
                del s.cond['toxicspikes']
            elif not (self.has_type(m, 'steel') or boots):
                self.set_status(m, 'tox' if s.cond['toxicspikes'] >= 2 else 'psn', self.act(1 - m.side), hazard=True)
        if s.cond.get('stickyweb') and g and not boots:
            self.boost(m, {'spe': -1}, self.act(1 - m.side), 'move')
        if m.status == 'tox':
            m.tox = 0

    def ability_start(self, m):
        a = self.ab(m)
        f = self.foe(m)
        st = self.st
        if a == 'intimidate':
            if f.alive:
                if 'substitute' in f.vol:
                    pass
                else:
                    self.boost(f, {'atk': -1}, m, 'intimidate')
        elif a in ('drizzle', 'drought', 'sandstream', 'snowwarning'):
            self.set_weather({'drizzle': 'raindance', 'drought': 'sunnyday', 'sandstream': 'sandstorm',
                              'snowwarning': 'snowscape'}[a], m)
        elif a in ('electricsurge', 'grassysurge', 'mistysurge', 'psychicsurge'):
            self.set_terrain(a.replace('surge', 'terrain'), m)
        elif a == 'download':
            if f.alive:
                d = self.boosted(f.stat('def'), f.boosts['def'])
                sd = self.boosted(f.stat('spd'), f.boosts['spd'])
                self.boost(m, {'spa': 1} if d >= sd else {'atk': 1}, m, 'ability')
        elif a == 'trace':
            if f.alive and self.ab(f) and not (dex.ABILITIES.get(self.ab(f), {}).get('flags') or {}).get('notrace'):
                m.ability = self.ab(f)
                m.vol.pop('traceseek', None)
                self.ability_start(m)
            else:
                m.vol['traceseek'] = True
        elif a == 'imposter':
            if f.alive and 'substitute' not in f.vol:
                self.transform(m, f)
        elif a == 'screencleaner':
            for i in (0, 1):
                for c in ('reflect', 'lightscreen', 'auroraveil'):
                    st.sides[i].cond.pop(c, None)
        elif a == 'supremeoverlord':
            n = min(st.sides[m.side].fainted_total, 5)
            if n:
                m.vol['supremeoverlord'] = n
        elif a == 'supersweetsyrup' and not m.syrup:
            m.syrup = True
            if f.alive and 'substitute' not in f.vol:
                self.boost(f, {'evasion': -1}, m, 'intimidate')
        elif a == 'mimicry':
            self.mimicry(m)
        elif a == 'forecast':
            self.forecast(m)
        elif a == 'unnerve':
            pass
        elif a == 'pressure' or a == 'moldbreaker':
            pass
        elif a == 'protosynthesis' and (self.eff_weather(m) == 'sunnyday') or a == 'quarkdrive' and st.terrain == 'electricterrain':
            m.vol[a] = max(STATS, key=lambda k: self.boosted(m.stat(k), m.boosts[k]))

    def forecast(self, m):
        if m.form.base == 'Castform':
            w = self.eff_weather(m)
            m.types = {'sunnyday': ('fire',), 'raindance': ('water',), 'snowscape': ('ice',)}.get(w)

    def mimicry(self, m):
        t = {'electricterrain': ('electric',), 'grassyterrain': ('grass',), 'mistyterrain': ('fairy',),
             'psychicterrain': ('psychic',)}.get(self.st.terrain)
        m.types = t

    def item_start(self, m):
        it = self.it(m)
        if it in SEEDS and self.st.terrain == SEEDS[it][0]:
            if self.use_item(m):
                self.boost(m, {SEEDS[it][1]: 1}, m, 'item')
        elif it == 'metronome':
            m.vol['metronome'] = {'last': None, 'n': 0}

    def fling_drop(self):
        m, self.fling_pending = self.fling_pending, None
        if m is not None and m.item:
            m.last_item, m.item = m.item, ''
            m.used_item = True
            if self.ab(m) == 'unburden' and m.alive:
                m.vol['unburden'] = True

    def transform(self, m, f):
        if 'transformed' not in m.vol:
            m.vol['transformed'] = (m.form, m.stats, m.moves, m.ability)
        m.form = f.form
        m.types = self.types(f)
        m.stats = dict((f.stats or f.form.stats))
        m.stats['hp'] = m.maxhp
        m.ability = self.ab(f)
        m.moves = f.moves
        m.boosts = dict(f.boosts)

    def set_weather(self, w, source=None):
        st = self.st
        if st.weather == w:
            return False
        st.weather = w
        st.wturns = 8 if source is not None and self.it(source) == WEATHER_ITEM.get(w) else 5
        for i in (0, 1):
            m = self.act(i)
            if m.alive and self.ab(m) == 'forecast':
                self.forecast(m)
            if m.alive and self.ab(m) == 'protosynthesis' and w == 'sunnyday' and 'protosynthesis' not in m.vol:
                m.vol['protosynthesis'] = max(STATS, key=lambda k: self.boosted(m.stat(k), m.boosts[k]))
        return True

    def set_terrain(self, t, source=None):
        st = self.st
        if st.terrain == t:
            return False
        st.terrain = t
        st.tturns = 8 if source is not None and self.it(source) == 'terrainextender' else 5
        for i in (0, 1):
            m = self.act(i)
            if not m.alive:
                continue
            it = self.it(m)
            if it in SEEDS and SEEDS[it][0] == t and self.use_item(m):
                self.boost(m, {SEEDS[it][1]: 1}, m, 'item')
            if self.ab(m) == 'mimicry':
                self.mimicry(m)
            if self.ab(m) == 'quarkdrive' and t == 'electricterrain' and 'quarkdrive' not in m.vol:
                m.vol['quarkdrive'] = max(STATS, key=lambda k: self.boosted(m.stat(k), m.boosts[k]))
        return True

    def clear_terrain(self):
        if self.st.terrain:
            self.st.terrain = ''
            self.st.tturns = 0
            for i in (0, 1):
                m = self.act(i)
                if m.alive and self.ab(m) == 'mimicry':
                    self.mimicry(m)

    def choose_switch(self, side, forced=False):
        s = self.st.sides[side]
        opts = [j for j, m in enumerate(s.mons) if m.alive and j != s.act]
        if not opts:
            return None
        if self.chooser is not None:
            j = self.chooser(self.st, side, opts)
            if j in opts:
                return j
        return opts[0]

    def mega(self, m):
        s = self.st.sides[m.side]
        if not m.can_mega or s.mega_used or not m.mega_form:
            return
        m.form = m.mega_form
        m.ability = m.mega_form.ability
        m.types = None
        s.mega_used = True
        m.can_mega = False
        self.L('mega', m.name, '->', m.form.ja)
        self.ability_start(m)
        self.herbs()
        f = self.foe(m)
        if f.alive and self.ab(f) == 'opportunist':
            pass

    # ================================================================ damage calculation
    def move_type(self, m, md):
        """ModifyType: skins, Liquid Voice, Weather Ball, Terrain Pulse, Raging Bull, Aura Wheel ..."""
        t = md.type
        mid = md.id
        if mid == 'weatherball':
            t = {'sunnyday': 'fire', 'raindance': 'water', 'sandstorm': 'rock', 'snowscape': 'ice'}.get(self.eff_weather(m), t)
        elif mid == 'terrainpulse' and self.grounded(m):
            t = {'electricterrain': 'electric', 'grassyterrain': 'grass', 'mistyterrain': 'fairy',
                 'psychicterrain': 'psychic'}.get(self.st.terrain, t)
        elif mid == 'ragingbull':
            t = {'taurospaldeacombat': 'fighting', 'taurospaldeablaze': 'fire',
                 'taurospaldeaaqua': 'water'}.get(m.form.sid, t)
        elif mid == 'aurawheel':
            t = 'dark' if m.vol.get('hangry') else 'electric'
        elif mid == 'ivycudgel':
            pass
        a = self.ab(m)
        self.bp_override = None
        skin = False
        if t == 'normal' and a in SKINS and mid not in NO_SKIN:
            t = SKINS[a]
            skin = True
        if a == 'liquidvoice' and 'sound' in md.flags:
            t = 'water'
        if a == 'normalize':
            t = 'normal'
        if 'electrify' in m.vol:
            t = 'electric'
        return t, skin

    def typemod(self, tgt, mtype, md):
        """runEffectiveness sum of typemods (or None if immune via type chart)."""
        tot = 0
        u = self.user
        for dt in self.types(tgt):
            if md.id == 'freezedry' and dt == 'water':
                tm = 1
            else:
                tm = TYPEMOD[mtype, dt]
            if tm is None:
                ig = md.ignore_imm
                if ig is True or (isinstance(ig, dict) and ig.get(mtype.capitalize())) or \
                        (u is not None and self.ab(u) in ('scrappy', 'mindseye') and dt == 'ghost' and
                         mtype in ('normal', 'fighting')) or (mtype == 'ground' and dt == 'flying'):
                    tm = 0
                else:
                    return None
            if md.id == 'flyingpress':
                fm = TYPEMOD['flying', dt]
                tm += fm or 0
            tot += tm
        return tot

    def immune(self, tgt, mtype, md, user):
        """runImmunity (type chart / ground immunity), honouring Scrappy/ignoreImmunity, Iron Ball etc."""
        ig = md.ignore_imm
        if ig is True:
            return False
        a = self.ab(user)
        if mtype == 'ground':
            g = self.grounded(tgt)
            if md.id == 'thousandarrows':
                return False
            return not g
        for dt in self.types(tgt):
            if TYPEMOD[mtype, dt] is None:
                if a in ('scrappy', 'mindseye') and dt == 'ghost' and mtype in ('normal', 'fighting'):
                    continue
                if isinstance(ig, dict) and ig.get(mtype.capitalize()):
                    continue
                return True
        return False

    def base_power(self, src, tgt, md, mtype):
        mid = md.id
        bp = md.bp
        st = self.st
        if mid == 'acrobatics':
            bp = bp * 2 if not self.it(src) else bp
        elif mid in ('eruption', 'waterspout', 'dragonenergy'):
            bp = max(1, bp * src.hp // src.maxhp) if src.hp > 0 else 0
        elif mid in ('flail', 'reversal'):
            r = max(src.hp * 48 // src.maxhp, 1)
            bp = 200 if r < 2 else 150 if r < 5 else 100 if r < 10 else 80 if r < 17 else 40 if r < 33 else 20
        elif mid in ('grassknot', 'lowkick'):
            w = self.weight(tgt)
            bp = 120 if w >= 2000 else 100 if w >= 1000 else 80 if w >= 500 else 60 if w >= 250 else 40 if w >= 100 else 20
        elif mid in ('heavyslam', 'heatcrash'):
            tw, uw = self.weight(tgt), self.weight(src)
            bp = 120 if uw >= tw * 5 else 100 if uw >= tw * 4 else 80 if uw >= tw * 3 else 60 if uw >= tw * 2 else 40
        elif mid == 'gyroball':
            bp = min(150, 25 * self.speed(tgt) // max(1, self.speed(src)) + 1)
        elif mid == 'electroball':
            r = self.speed(src) // max(1, self.speed(tgt))
            bp = [40, 60, 80, 120, 150][min(r, 4)]
        elif mid in ('hex', 'infernalparade'):
            if tgt.status or self.ab(tgt) == 'comatose':
                bp *= 2
        elif mid == 'lastrespects':
            bp = 50 + 50 * st.sides[src.side].fainted_total
        elif mid in ('storedpower', 'powertrip'):
            bp = bp + 20 * sum(v for k, v in src.boosts.items() if v > 0)
        elif mid == 'tripleaxel':
            bp = 20 * self.cur_hit
        elif mid == 'ragefist':
            bp = min(350, 50 + 50 * src.times_attacked)
        elif mid == 'avalanche':
            db = src.damaged_by
            if db and db[2] and db[0] > 0 and db[3] == (tgt.side, tgt.idx):
                bp *= 2
        elif mid == 'payback':
            if not (tgt.newly or self.will_move(tgt)):
                bp *= 2
        elif mid in ('stompingtantrum', 'temperflare'):
            if src.last_result is False:
                bp *= 2
        elif mid == 'risingvoltage':
            if st.terrain == 'electricterrain' and self.grounded(tgt):
                bp *= 2
        elif mid == 'assurance':
            if tgt.hurt:
                bp *= 2
        elif mid == 'hardpress':
            bp = (100 * (100 * (tgt.hp * 4096 // tgt.maxhp)) + 2047) // 4096 // 100 or 1
        elif mid == 'weatherball':
            if self.eff_weather(src):
                bp *= 2
        elif mid == 'terrainpulse':
            if st.terrain and self.grounded(src):
                bp *= 2
        elif mid == 'spitup':
            bp = 100 * (src.vol.get('stockpile') or {}).get('layers', 0)
        elif mid == 'beatup':
            bp = 5 + (self.beatup[min(self.cur_hit, len(self.beatup)) - 1] if getattr(self, 'beatup', None) else POKE_ATK(src)) // 10
        elif mid == 'watershuriken':
            pass
        elif mid == 'fling':
            bp = (ITEMS.get(self.fling_item, {}).get('fling') or {}).get('basePower', 0) if self.fling_item else 0
        return bp

    def bp_mods(self, src, tgt, md, mtype, bp, skin, crit):
        """BasePower event chain (handler priority order)."""
        mod = 4096
        a, it = self.ab(src), self.it(src)
        ta = self.tab(tgt)
        st = self.st
        mid = md.id
        # technician (30): uses current modifier (1)
        if a == 'technician' and bp <= 60:
            mod = chain(mod, 6144)
        # skins / iron fist / reckless (23)
        if skin:
            mod = chain(mod, 4915)
        if a == 'ironfist' and 'punch' in md.flags:
            mod = chain(mod, 4915)
        if a == 'reckless' and (md.recoil or md.crash):
            mod = chain(mod, 4915)
        # 22: steely spirit (also boosts the holder)
        if a == 'steelyspirit' and mtype == 'steel':
            mod = chain(mod, 6144)
        # 21: tough claws, sheer force, sand force, analytic, supreme overlord
        if a == 'toughclaws' and self.contact:
            mod = chain(mod, 5325)
        if a == 'sheerforce' and self.sheer:
            mod = chain(mod, 5325)
        if a == 'sandforce' and self.eff_weather(src) == 'sandstorm' and mtype in ('rock', 'ground', 'steel'):
            mod = chain(mod, 5325)
        if a == 'analytic' and not self.will_move(tgt):
            mod = chain(mod, 5325)
        if a == 'supremeoverlord' and src.vol.get('supremeoverlord'):
            mod = chain(mod, [4096, 4506, 4915, 5325, 5734, 6144][src.vol['supremeoverlord']])
        # 20: fairy / dark aura
        for x in (src, tgt):
            xa = self.ab(x)
            if xa == 'fairyaura' and mtype == 'fairy' or xa == 'darkaura' and mtype == 'dark':
                mod = chain(mod, 5448)
                break
        # 19: mega launcher, strong jaw, sharpness
        if a == 'megalauncher' and 'pulse' in md.flags:
            mod = chain(mod, 6144)
        if a == 'strongjaw' and 'bite' in md.flags:
            mod = chain(mod, 6144)
        if a == 'sharpness' and 'slicing' in md.flags:
            mod = chain(mod, 6144)
        # 17: dry skin (target, fire)
        if ta == 'dryskin' and mtype == 'fire':
            mod = chain(mod, 5120)
        # 16: muscle band / wise glasses ; 15: type items
        if it == 'muscleband' and self.cat == 'physical':
            mod = chain(mod, 4505)
        if it == 'wiseglasses' and self.cat == 'special':
            mod = chain(mod, 4505)
        if TYPE_ITEM.get(it) == mtype:
            mod = chain(mod, 4915)
        # 14: gem
        if 'gem' in src.vol:
            mod = chain(mod, 5325)
        # 9: charge
        if 'charge' in src.vol and mtype == 'electric':
            mod = chain(mod, 8192)
        # 7: punk rock
        if a == 'punkrock' and 'sound' in md.flags:
            mod = chain(mod, 5325)
        # 6: terrains
        tr = st.terrain
        if tr:
            if tr == 'electricterrain' and mtype == 'electric' and self.grounded(src) and not self.semi_inv(src):
                mod = chain(mod, 5325)
            elif tr == 'grassyterrain':
                if mid in ('earthquake', 'bulldoze', 'magnitude') and self.grounded(tgt) and not self.semi_inv(tgt):
                    mod = chain(mod, 2048)
                elif mtype == 'grass' and self.grounded(src):
                    mod = chain(mod, 5325)
            elif tr == 'psychicterrain' and mtype == 'psychic' and self.grounded(src) and not self.semi_inv(src):
                mod = chain(mod, 5325)
            elif tr == 'mistyterrain' and mtype == 'dragon' and self.grounded(tgt) and not self.semi_inv(tgt):
                mod = chain(mod, 2048)
        # move onBasePower (priority 0)
        if mid == 'knockoff':
            if tgt.item and not ITEMS.get(tgt.item, {}).get('megaStone') and not (ta == 'stickyhold'):
                mod = chain(mod, 6144)
        elif mid == 'facade' and src.status and src.status != 'slp':
            mod = chain(mod, 8192)
        elif mid in ('venoshock', 'barbbarrage') and tgt.status in ('psn', 'tox'):
            mod = chain(mod, 8192)
        elif mid in ('solarbeam', 'solarblade') and self.eff_weather(src) in ('raindance', 'sandstorm', 'snowscape'):
            mod = chain(mod, 2048)
        elif mid == 'expandingforce' and st.terrain == 'psychicterrain' and self.grounded(src):
            mod = chain(mod, 6144)
        elif mid == 'mistyexplosion' and st.terrain == 'mistyterrain' and self.grounded(src):
            mod = chain(mod, 6144)
        elif mid == 'gravapple' and 'gravity' in st.pseudo:
            mod = chain(mod, 6144)
        elif mid == 'lashout' and src.lowered:
            mod = chain(mod, 8192)
        elif mid == 'ficklebeam':
            if self.rng.chance(0.3, 'ficklebeam'):
                mod = chain(mod, 8192)
        elif mid == 'psyblade' and st.terrain == 'electricterrain':
            mod = chain(mod, 6144)
        elif mid == 'hydrosteam':
            pass
        if a == 'rivalry' and src.gender and tgt.gender:
            mod = chain(mod, 5120 if src.gender == tgt.gender else 3072)
        return max(1, modify(bp, mod))

    def get_damage(self, src, tgt, md, crit=False, pb2=False):
        """Returns list of 16 damages (ascending), or None (no effect) / int fixed damage."""
        st = self.st
        mtype = self.type
        if md.ohko:
            return [tgt.maxhp] * 16
        mid = md.id
        if mid in ('seismictoss', 'nightshade'):
            return [50] * 16
        if mid == 'superfang':
            return [max(1, tgt.hp // 2)] * 16
        if mid == 'endeavor':
            return [max(0, tgt.hp - src.hp)] * 16
        if mid == 'finalgambit':
            return [src.hp] * 16
        if mid in ('counter', 'mirrorcoat', 'metalburst', 'comeuppance'):
            return None
        bp = self.base_power(src, tgt, md, mtype)
        if not bp:
            return None
        skin = self.flags.get('skin', False) if isinstance(self.flags, dict) else False
        bp = self.bp_mods(src, tgt, md, mtype, bp, skin, crit)
        cat = self.cat
        atk_mon = tgt if md.override_off_mon == 'target' else src
        off = md.override_off or ('atk' if cat == 'physical' else 'spa')
        dfs = md.override_def or ('def' if cat == 'physical' else 'spd')
        ab_boost = atk_mon.boosts[off]
        df_boost = tgt.boosts[dfs]
        # Wonder Room swaps only the stored stats; boosts and Modify{Def,SpD} handlers keep the original stat
        D_stat = tgt.stat({'def': 'spd', 'spd': 'def'}[dfs]) if 'wonderroom' in st.pseudo else tgt.stat(dfs)
        sa, ta = self.ab(src), self.tab(tgt)
        if crit:
            if ab_boost < 0:
                ab_boost = 0
            if df_boost > 0:
                df_boost = 0
        if md.ignore_def or sa == 'unaware' and not self.ignore_ab:
            df_boost = 0
        if ta == 'unaware':
            ab_boost = 0
        if sa == 'unaware':
            df_boost = 0
        A = self.boosted(atk_mon.stat(off), ab_boost)
        D = self.boosted(D_stat, df_boost)
        # ModifyAtk / ModifySpA (attacker handlers, then target's onSourceModify)
        amod = 4096
        catk = 'atk' if cat == 'physical' else 'spa'
        it = self.it(src)
        hp3 = src.hp <= src.maxhp // 3 if False else src.hp * 3 <= src.maxhp
        if catk == 'atk':
            if sa in ('hugepower', 'purepower'):
                amod = chain(amod, 8192)
            if sa == 'guts' and src.status:
                amod = chain(amod, 6144)
            if sa == 'gorillatactics':
                amod = chain(amod, 6144)
        else:
            if sa == 'solarpower' and self.eff_weather(src) == 'sunnyday':
                amod = chain(amod, 6144)
            if sa in ('plus', 'minus'):
                pass
        if (sa == 'blaze' and mtype == 'fire' or sa == 'torrent' and mtype == 'water' or
                sa == 'overgrow' and mtype == 'grass' or sa == 'swarm' and mtype == 'bug') and src.hp * 3 <= src.maxhp:
            amod = chain(amod, 6144)
        if sa == 'firemane' and mtype == 'fire':
            amod = chain(amod, 6144)
        if 'flashfire' in src.vol and mtype == 'fire' and sa == 'flashfire':
            amod = chain(amod, 6144)
        if sa == 'stakeout' and tgt.newly and not tgt.active_turns:
            amod = chain(amod, 8192)
        if sa == 'waterbubble' and mtype == 'water':
            amod = chain(amod, 8192)
        if sa in ('protosynthesis', 'quarkdrive') and src.vol.get(sa) == catk:
            amod = chain(amod, 5325)
        if sa == 'defeatist' and src.hp * 2 <= src.maxhp:
            amod = chain(amod, 2048)
        if sa == 'transistor' and mtype == 'electric':
            amod = chain(amod, 5325)
        if sa == 'dragonsmaw' and mtype == 'dragon':
            amod = chain(amod, 6144)
        if sa == 'rockypayload' and mtype == 'rock':
            amod = chain(amod, 6144)
        if sa == 'steelworker' and mtype == 'steel':
            amod = chain(amod, 6144)
        if it == 'lightball' and src.form.base == 'Pikachu':
            amod = chain(amod, 8192)
        if it == 'choiceband' and catk == 'atk' or it == 'choicespecs' and catk == 'spa':
            amod = chain(amod, 6144)
        # target-side (onSourceModifyAtk)
        if ta == 'thickfat' and mtype in ('fire', 'ice'):
            amod = chain(amod, 2048)
        if ta in ('heatproof', 'waterbubble') and mtype == 'fire':
            amod = chain(amod, 2048)
        if ta == 'purifyingsalt' and mtype == 'ghost':
            amod = chain(amod, 2048)
        A = modify(A, amod)
        if sa == 'hustle' and catk == 'atk':
            A = modify(A, 6144)
        # ModifyDef / ModifySpD
        dmod = 4096
        w = self.eff_weather(tgt)
        if dfs == 'def':
            if ta == 'furcoat':
                dmod = chain(dmod, 8192)
            if ta == 'marvelscale' and tgt.status:
                dmod = chain(dmod, 6144)
            if ta == 'grasspelt' and st.terrain == 'grassyterrain':
                dmod = chain(dmod, 6144)
        else:
            if self.it(tgt) == 'assaultvest':
                dmod = chain(dmod, 6144)
        if ta in ('protosynthesis', 'quarkdrive') and tgt.vol.get(ta) == dfs:
            dmod = chain(dmod, 5325)
        D = modify(D, dmod)
        if dfs == 'spd' and w == 'sandstorm' and self.has_type(tgt, 'rock'):
            D = modify(D, 6144)
        if dfs == 'def' and w == 'snowscape' and self.has_type(tgt, 'ice'):
            D = modify(D, 6144)
        A, D = max(1, A), max(1, D)
        base = (22 * bp * A // D) // 50
        # ---- modifyDamage
        base += 2
        if pb2:
            base = modify(base, 1024)   # Parental Bond second hit
        # weather
        wmod = 4096
        aw = self.eff_weather(src)
        if sa == 'megasol':
            aw = 'sunnyday'
        if mid == 'hydrosteam' and aw == 'sunnyday':
            wmod = chain(wmod, 6144)
        else:
            dw = 'sunnyday' if sa == 'megasol' else self.eff_weather(tgt)
            if dw == 'sunnyday':
                if mtype == 'fire':
                    wmod = chain(wmod, 6144)
                elif mtype == 'water':
                    wmod = chain(wmod, 2048)
            elif dw == 'raindance':
                if mtype == 'water':
                    wmod = chain(wmod, 6144)
                elif mtype == 'fire':
                    wmod = chain(wmod, 2048)
        if wmod != 4096:
            base = modify(base, wmod)
        if crit:
            base = base * 3 // 2
        # STAB
        stab = 4096
        if mtype in self.types(src):
            stab = 6144
            if sa == 'adaptability':
                stab = 8192
        tm = self.typemod(tgt, mtype, md) or 0
        if self.it(tgt) == 'ironball' and mtype == 'ground' and self.has_type(tgt, 'flying'):
            tm = 0
        # final modifiers (ModifyDamage chain)
        fmod = 4096
        if it == 'lifeorb':
            fmod = chain(fmod, 5324)
        if it == 'expertbelt' and tm > 0:
            fmod = chain(fmod, 4915)
        if sa == 'sniper' and crit:
            fmod = chain(fmod, 6144)
        if sa == 'tintedlens' and tm < 0:
            fmod = chain(fmod, 8192)
        if 'metronome' in src.vol and it == 'metronome':
            n = min(5, src.vol['metronome']['n'])
            fmod = chain(fmod, [4096, 4915, 5734, 6553, 7372, 8192][n])
        # target side
        if ta in ('multiscale', 'shadowshield') and tgt.hp >= tgt.maxhp:
            fmod = chain(fmod, 2048)
        if ta in ('filter', 'solidrock', 'prismarmor') and tm > 0:
            fmod = chain(fmod, 3072)
        if ta == 'fluffy':
            if mtype == 'fire':
                fmod = chain(fmod, 8192)
            if self.contact:
                fmod = chain(fmod, 2048)
        if ta == 'punkrock' and 'sound' in md.flags:
            fmod = chain(fmod, 2048)
        if ta == 'icescales' and self.cat == 'special':
            fmod = chain(fmod, 2048)
        if ta == 'auraguard' and self.contact:
            fmod = chain(fmod, 2048)
        if 'glaiverush' in tgt.vol:
            fmod = chain(fmod, 8192)
        if 'minimize' in tgt.vol and 'minimize' in md.flags:
            fmod = chain(fmod, 8192)
        if mid in ('earthquake', 'magnitude') and 'dig' in tgt.vol or mid in ('surf', 'whirlpool') and 'dive' in tgt.vol:
            fmod = chain(fmod, 8192)
        berry = self.it(tgt)
        if berry in RESIST_BERRY and RESIST_BERRY[berry] == mtype and (tm > 0 or mtype == 'normal') and \
                not (self.hit_sub):
            fmod = chain(fmod, 2048)
        # screens
        sc = st.sides[tgt.side].cond
        if not crit and not self.infiltrates:
            if sc.get('auroraveil') or (self.cat == 'physical' and sc.get('reflect')) or \
                    (self.cat == 'special' and sc.get('lightscreen')):
                fmod = chain(fmod, 2048)
        burn = src.status == 'brn' and self.cat == 'physical' and sa != 'guts' and mid != 'facade'
        out = []
        for r in range(16):
            d = base * (85 + r) // 100
            if stab != 4096:
                d = modify(d, stab)
            if tm > 0:
                d <<= tm
            elif tm < 0:
                for _ in range(-tm):
                    d //= 2
            if burn:
                d = modify(d, 2048)
            if fmod != 4096:
                d = modify(d, fmod)
            out.append(max(1, d) if d or True else 1)
        return out

    def crit_ratio(self, src, tgt, md):
        if md.will_crit:
            return 1.0
        r = md.crit or 1
        a, it = self.ab(src), self.it(src)
        if a == 'superluck':
            r += 1
        if it == 'scopelens':
            r += 1
        if it == 'leek' and src.form.base in ('Farfetch’d', "Farfetch'd", 'Sirfetch’d', "Sirfetch'd"):
            r += 2
        if 'focusenergy' in src.vol:
            r += 2
        if 'dragoncheer' in src.vol:
            r += src.vol['dragoncheer'] if isinstance(src.vol['dragoncheer'], int) else 1
        if a == 'merciless' and tgt.status in ('psn', 'tox'):
            return 1.0
        r = max(0, min(4, r))
        return [0, 1 / 24, 1 / 8, 1 / 2, 1][r]

    # ================================================================ move execution
    def legal_moves(self, m):
        return legal_moves(self.st, m)

    def run_move(self, m, mid, mega=False):
        """runMove: before-move checks, then useMove."""
        st = self.st
        if not m.alive or not self.is_active(m):
            return
        f = self.foe(m)
        if mid == 'recharge':
            m.vol.pop('mustrecharge', None)
            m.this_result = None
            return
        md = MOVES.get(mid) or MOVES['struggle']
        m.move_actions += 1
        self.scale = 1.0
        # ---- BeforeMove chain
        if 'glaiverush' in m.vol:
            del m.vol['glaiverush']
        if 'mustrecharge' in m.vol:
            del m.vol['mustrecharge']
            m.this_result = None
            self.L(m.name, 'must recharge')
            return
        if m.status == 'slp':
            m.stime -= 2 if self.ab(m) == 'earlybird' else 1
            if m.stime <= 0:
                m.status = ''
            elif not md.sleep_usable:
                self.L(m.name, 'is asleep')
                self.move_aborted(m, md)
                return
        if m.status == 'frz':
            if 'defrost' in md.flags:
                m.status = ''
            else:
                m.stime -= 1
                if m.stime <= 0 or self.rng.chance(0.25, 'thaw'):
                    m.status = ''
                else:
                    self.L(m.name, 'is frozen')
                    self.move_aborted(m, md)
                    return
        if 'flinch' in m.vol:
            del m.vol['flinch']
            if self.ab(m) == 'steadfast':
                self.boost(m, {'spe': 1}, m, 'ability')
            self.L(m.name, 'flinched')
            self.move_aborted(m, md)
            return
        dis = m.vol.get('disable')
        if dis and dis['move'] == mid and 'cantusetwice' not in md.flags:
            self.move_aborted(m, md)
            return
        if ('gravity' in st.pseudo and 'gravity' in md.flags) or ('throatchop' in m.vol and 'sound' in md.flags) or \
                ('healblock' in m.vol and 'heal' in md.flags):
            self.move_aborted(m, md)
            return
        if 'taunt' in m.vol and md.cat == 'status':
            self.move_aborted(m, md)
            return
        if 'imprison' in f.vol and mid in f.moves and mid != 'struggle':
            self.move_aborted(m, md)
            return
        if 'confusion' in m.vol:
            m.vol['confusion'] -= 1
            if m.vol['confusion'] <= 0:
                del m.vol['confusion']
            elif self.rng.chance(0.33, 'confusion', True):
                self.confusion_hit(m)
                self.move_aborted(m, md)
                return
        if 'attract' in m.vol and self.act(m.vol['attract'][0]).idx != m.vol['attract'][1]:
            del m.vol['attract']   # the source left the field
        if 'attract' in m.vol:
            if self.rng.expected:
                self.scale *= 0.5
            elif self.rng.chance(0.5, 'attract'):
                self.L(m.name, 'is immobilized by love')
                self.move_aborted(m, md)
                return
        if m.status == 'par':
            if self.rng.expected:
                self.scale *= 7 / 8
            elif self.rng.chance(0.125, 'para'):
                self.L(m.name, 'is fully paralyzed')
                self.move_aborted(m, md)
                return
        cl = m.vol.get('choicelock')
        if cl:
            if not ITEMS.get(m.item, {}).get('name', '').startswith('Choice'):
                del m.vol['choicelock']
            elif cl != mid and mid != 'struggle' and self.it(m):
                self.move_aborted(m, md)
                return
        if 'destinybond' in m.vol and mid != 'destinybond':
            del m.vol['destinybond']
        # focus punch lost focus
        if mid == 'focuspunch' and m.vol.get('focuspunch') == 'lost':
            m.this_result = False
            return
        locked = m.vol.get('lockedmove')
        m.last_move = mid
        if mid not in m.move_used:
            m.move_used = m.move_used + (mid,)
        if mid in m.moves and not m.vol.get('lockedmove') and mid != 'struggle':
            if m.pp is None:
                m.pp = {}
            left = m.pp.get(mid, MOVES[mid].pp)
            if left <= 0:
                m.this_result = False
                return
            left -= 1
            f = self.foe(m)
            if f.alive and self.ab(f) == 'pressure' and md.target not in ('self', 'allySide') and left > 0:
                left -= 1
            m.pp[mid] = left
        self.in_move = True
        self.prev_lastmove = st.lastmove
        st.lastmove = mid
        self.use_move(m, md)
        self.after_move(m, md)
        self.in_move = False
        self.ignore_ab = False
        self.faint_messages()

    def move_aborted(self, m, md):
        m.this_result = False
        m.vol.pop('destinybond', None)
        if 'twoturnmove' in m.vol:
            mv = m.vol.pop('twoturnmove')
            m.vol.pop(mv, None)
        m.vol.pop('lockedmove', None)
        if md.type == 'electric' and md.id != 'charge':
            m.vol.pop('charge', None)

    def confusion_hit(self, m):
        A = self.boosted(m.stat('atk'), m.boosts['atk'])
        D = self.boosted(m.stat('def'), m.boosts['def'])
        base = (22 * 40 * A // D) // 50 + 2
        r = self.rng.roll([base * (85 + i) // 100 for i in range(16)], m.hp)
        d = max(1, base * (85 + r) // 100)
        self.damage(m, d, m, 'confusion')

    def after_move(self, m, md):
        mid = md.id
        if mid == 'sparklingaria':
            f = self.foe(m)
            if f.vol.pop('sparklingaria', None) and f.status == 'brn' and f.alive:
                f.status = ''
        if 'charge' in m.vol and self.type == 'electric' and mid != 'charge':
            m.vol.pop('charge', None)
        lm = m.vol.get('lockedmove')
        if lm and lm['dur'] <= 1:
            pass
        if mid == 'spitup':
            self.end_stockpile(m)
        m.vol.pop('beakblast', None)
        m.vol.pop('gem', None)
        self.herbs()

    def end_stockpile(self, m):
        st = m.vol.pop('stockpile', None)
        if st and (st['def'] or st['spd']):
            b = {}
            if st['def']:
                b['def'] = st['def']
            if st['spd']:
                b['spd'] = st['spd']
            self.boost(m, b, m, 'move')

    def use_move(self, m, md):
        st = self.st
        mid = md.id
        f = self.foe(m)
        self.user = m
        self.move = md
        self.infiltrates = self.ab(m) == 'infiltrator'
        self.ignore_ab = self.ab(m) in MOLD
        self.hit_sub = False
        self.total = 0
        self.crit_hit = False
        self.fail_move = False
        mtype, skin = self.move_type(m, md)
        self.type = mtype
        self.flags = {'skin': skin}
        self.cat = md.cat
        self.contact = md.contact
        self.sheer = False
        self.secondaries = list(md.secondaries)
        self.multihit = md.multihit
        if mid == 'beatup':
            self.beatup = None
            for side in self.st.sides:
                if side.mons[side.act] is m:
                    others = [p for k, p in enumerate(side.mons) if k != side.act]
                    self.beatup = [POKE_ATK(p) for p in [m] + others if p is m or (p.alive and not p.status)]
            if self.beatup:
                self.multihit = len(self.beatup)
        sa = self.ab(m)
        it = self.it(m)
        # shell side arm
        if mid == 'shellsidearm' and f.alive:
            phys = ((22 * 90 * self.boosted(m.stat('atk'), m.boosts['atk'])) // max(1, self.boosted(f.stat('def'), f.boosts['def']))) // 50
            spec = ((22 * 90 * self.boosted(m.stat('spa'), m.boosts['spa'])) // max(1, self.boosted(f.stat('spd'), f.boosts['spd']))) // 50
            if phys > spec:
                self.cat = 'physical'
                self.contact = True
        if sa == 'stancechange' and m.form.base == 'Aegislash' and (md.cat != 'status' or mid == 'kingsshield'):
            want = 'ギルガルド' if mid == 'kingsshield' else 'ブレードギルガルド'
            if m.form.ja != want and want in dex.SPECIES:
                m.form = Form(want, m.nature, m.ap, 'stancechange')
        if sa == 'longreach':
            self.contact = False
        if self.it(m) == 'punchingglove' and 'punch' in md.flags:
            self.contact = False
        # ModifyMove: sheer force removes secondaries & self
        self_effect = md.self
        if sa == 'sheerforce' and md.sheer:
            self.sheer = True
            self.secondaries = []
            self_effect = None
        if sa == 'skilllink' and isinstance(self.multihit, list):
            self.multihit = self.multihit[1]
        if self.cat != 'status' and (it == 'kingsrock' or sa == 'stench'):
            if not any(s.get('volatileStatus') == 'flinch' for s in self.secondaries):
                self.secondaries.append({'chance': 10, 'volatileStatus': 'flinch'})
        if sa == 'serenegrace':
            self.secondaries = [dict(s, chance=min(100, s.get('chance', 100) * 2)) for s in self.secondaries]
        if ITEMS.get(it, {}).get('name', '').startswith('Choice') and 'choicelock' not in m.vol:
            m.vol['choicelock'] = mid

        # target
        tgt_self = md.target in ('self', 'allies', 'allySide', 'adjacentAllyOrSelf') or \
            (mid == 'curse' and not self.has_type(m, 'ghost'))
        tgt = m if tgt_self else f
        self.target = tgt
        # TryMove: charge moves, type-requiring moves, gravity
        if mid in ('burnup', 'doubleshock'):
            need = 'fire' if mid == 'burnup' else 'electric'
            if not self.has_type(m, need):
                m.this_result = None   # onTryMove returns null
                return
        charged = False
        if 'charge' in md.flags and mid not in ('focuspunch', 'beakblast', 'shelltrap'):
            if m.vol.get('twoturnmove') == mid:
                charged = True
                del m.vol['twoturnmove']
                m.vol.pop(mid, None)
            else:
                skip = False
                if mid in ('solarbeam', 'solarblade') and self.eff_weather(m) == 'sunnyday':
                    skip = True
                if mid == 'electroshot':
                    self.boost(m, {'spa': 1}, m, 'move')
                    if self.eff_weather(m) == 'raindance':
                        skip = True
                if mid == 'meteorbeam':
                    self.boost(m, {'spa': 1}, m, 'move')
                if not skip and it == 'powerherb':
                    if self.use_item(m):
                        skip = True
                if not skip:
                    m.vol['twoturnmove'] = mid
                    m.vol[mid] = True
                    m.this_result = None   # onTryMove returns null on the charge turn
                    self.L(m.name, 'charges', mid)
                    return
        # Metronome (item) consecutive-use counter (TryMove, priority -2)
        mt = m.vol.get('metronome')
        if mt is not None and mid not in CALLS_MOVE:
            if it != 'metronome':
                del m.vol['metronome']
            else:
                if mt['last'] == mid and m.last_result:
                    mt['n'] += 1
                elif charged:
                    mt['n'] = 1 if mt['last'] != mid else mt['n'] + 1
                else:
                    mt['n'] = 0
                mt['last'] = mid
        # selfdestruct always (explosion)
        if md.selfdestruct == 'always':
            for x in (0, 1):
                d = self.act(x)
                if d.alive and self.ab(d) == 'damp':
                    m.this_result = False
                    return
            m.hp = 0
            self.check_faint(m, m, 'self')
        self.L(m.name, 'uses', mid)
        # FoeTryMove: Armor Tail / Queenly Majesty / Dazzling stop priority moves (before Protean)
        if md.target not in ('self', 'foeSide', 'allySide', 'allyTeam', 'all') and f.alive and \
                self.tab(f) in ('armortail', 'queenlymajesty', 'dazzling') and \
                (self.called_pri if getattr(self, 'called_pri', None) is not None else self.priority_of(m, mid)) > 0.1:
            m.this_result = False
            return
        # ---- field / side moves
        if md.target in ('all', 'foeSide', 'allySide', 'allyTeam') and md.cat == 'status':
            ok = self.move_try(m, m, md)
            if ok:
                self.protean(m, mtype)
                ok = self.field_move(m, md)
            m.this_result = bool(ok)
            if md.self_switch and (ok or mid == 'chillyreception') and m.alive and self.can_switch(m.side):
                m.switch_flag = md.self_switch
            return
        if not f.alive and not tgt_self:
            m.this_result = False
            return
        # ---- trySpreadMoveHit: Try / PrepareHit
        ok = self.move_try(m, tgt, md)
        if ok is False or ok is None:
            m.this_result = False if ok is False else None
            if ok is False:
                self.move_fail(m, md)
            return
        if md.stalling:
            stall = m.vol.get('stall')
            p = 1.0 / stall if stall else 1.0
            if self.will_move_any_other(m) is False:
                m.this_result = False
                m.vol.pop('stall', None)
                return
            if p < 1 and not self.rng.chance(p, 'protect'):
                m.vol.pop('stall', None)
                m.this_result = False
                return
        self.fling_item = None
        self.fling_pending = None
        if mid == 'fling':
            it = self.it(m)
            if not it or ITEMS.get(it, {}).get('megaStone') or not ITEMS.get(it, {}).get('fling'):
                m.this_result = False
                return
            self.fling_item = it
            fl = ITEMS[it]['fling']
            if fl.get('status'):
                self.secondaries = [{'status': fl['status']}]
            elif fl.get('volatileStatus'):
                self.secondaries = [{'volatileStatus': fl['volatileStatus']}]
            self.protean(m, mtype)
            # the item stays held through the damage calculation; the fling volatile drops it at the next Update
            self.fling_pending = m
            res = self.hit_steps(m, tgt, md, self_effect)
            self.fling_drop()
            if res and tgt.alive:
                if it in BERRIES:
                    self.berry_effect(tgt, it)
                    tgt.ate_berry = True
                elif it == 'whiteherb':
                    for k in BOOSTS:
                        if tgt.boosts[k] < 0:
                            tgt.boosts[k] = 0
                elif it == 'mentalherb':
                    for v in ('attract', 'taunt', 'encore', 'torment', 'disable', 'healblock'):
                        tgt.vol.pop(v, None)
            m.this_result = bool(res)
            if not res:
                self.move_fail(m, md)
            return
        self.protean(m, mtype)
        res = self.hit_steps(m, tgt, md, self_effect)
        m.this_result = bool(res)
        if not res:
            self.move_fail(m, md)
            return
        # self boost (selfBoost e.g. scale shot handled after hits)
        if md.self_boost and res:
            self.boost(m, md.self_boost.get('boosts', {}), m, 'move', is_self=True)
        if not m.alive:
            self.check_faint(m, m, 'self')
        # AfterMoveSecondarySelf: life orb, shell bell, fell stinger, magician
        if self.cat != 'status' and not self.sheer:
            if self.it(m) == 'lifeorb' and m.alive and tgt is not m and not m.force_switch:
                self.damage(m, m.maxhp // 10, m, 'item')
            if self.it(m) == 'shellbell' and self.total > 0 and not m.force_switch:
                self.heal(m, self.total // 8, m, 'item')
        if mid == 'fellstinger' and not f.alive and m.alive:
            self.boost(m, {'atk': 3}, m, 'move')
        if sa == 'magician' and not m.item and self.cat != 'status' and self.total > 0 and f.alive:
            got = self.take_item(f, m)
            if got:
                m.item = got
        # Emergency exit on self (after life orb etc.)
        # self switch
        if md.self_switch and m.alive and self.can_switch(m.side) and not m.switch_flag and mid != 'revivalblessing':
            if mid == 'partingshot' and getattr(self, '_ps_fail', False):
                pass
            else:
                m.switch_flag = md.self_switch

    def protean(self, m, mtype):
        if self.ab(m) in ('protean', 'libero') and not m.protean and mtype != '???':
            if tuple(self.types(m)) != (mtype,):
                m.types = (mtype,)
                m.protean = True

    def will_move_any_other(self, m):
        """queue.willAct(): protect fails if it's the last action of the turn."""
        for a in self.queue:
            if a[0] == 'move':
                return True
        return False

    def move_fail(self, m, md):
        if md.crash and m.alive:
            self.damage(m, m.maxhp // 2, m, 'crash')
        if md.id == 'steelbeam' and m.alive and False:
            pass
        m.vol.pop('lockedmove', None) if md.id not in ('outrage', 'thrash', 'petaldance') else None

    def move_try(self, m, tgt, md):
        """move.onTry / onPrepareHit. Return False (fail), None (silently nothing) or True."""
        mid = md.id
        st = self.st
        f = self.foe(m)
        if mid in ('fakeout', 'firstimpression') and m.move_actions > 1:
            return False
        if mid == 'suckerpunch':
            qm = self.queued_move(f)
            if not qm or qm not in MOVES or MOVES[qm].cat == 'status' or 'mustrecharge' in f.vol:
                return False
        if mid == 'upperhand':
            qm = self.queued_move(f)
            if not qm or qm not in MOVES or MOVES[qm].cat == 'status' or self.priority_of(f, qm) <= 0:
                return False
        if mid == 'poltergeist' and not tgt.item:
            return False
        if mid == 'rest':
            if m.status == 'slp' or m.hp >= m.maxhp or self.ab(m) in ('insomnia', 'vitalspirit', 'comatose'):
                return None if m.status != 'slp' else False
        if mid in ('sleeptalk', 'snore') and m.status != 'slp':
            return False
        if mid == 'belch' and not m.ate_berry:
            return False
        if mid == 'stuffcheeks' and self.it(m) not in BERRIES:
            return False
        if mid == 'clangoroussoul' and (m.hp * 100 <= m.maxhp * 33):
            return False
        if mid in ('counter', 'mirrorcoat'):
            c = m.vol.get(mid)
            if not c or not c.get('dmg'):
                return False
        if mid in ('metalburst', 'comeuppance'):
            db = m.damaged_by
            if not db or not db[2]:
                return False
        if mid == 'aurawheel' and m.form.base != 'Morpeko':
            return None
        if mid == 'steelroller' and not st.terrain:
            return False
        if mid == 'auroraveil' and self.eff_weather(m) != 'snowscape':
            return False
        if mid == 'lastresort':
            others = [x for x in m.moves if x != 'lastresort']
            if 'lastresort' not in m.moves or not others or any(x not in m.move_used for x in others):
                return False
        if mid == 'spitup' or mid == 'swallow':
            if 'stockpile' not in m.vol:
                return False
        if mid == 'stockpile' and (m.vol.get('stockpile') or {}).get('layers', 0) >= 3:
            return False
        if mid == 'noretreat' and 'noretreat' in m.vol:
            return False
        if mid == 'destinybond':
            if m.vol.pop('destinybond', None):
                return False
        if mid in ('followme', 'ragepowder', 'allyswitch', 'helpinghand', 'afteryou', 'quash', 'aromatherapy',
                   'coaching', 'aromaticmist', 'holdhands'):
            return False
        if mid == 'futuresight':
            s = st.sides[1 - m.side]
            if 'futuremove' in s.slot:
                return False
            s.slot['futuremove'] = [3, m.side, m.idx]
            return None
        if mid == 'magnetrise' and ('smackdown' in m.vol or 'ingrain' in m.vol or 'gravity' in st.pseudo):
            return False
        return True

    def priority_of(self, m, mid):
        md = MOVES.get(mid)
        if md is None:
            return 0
        p = md.pri
        a = self.ab(m)
        if a == 'prankster' and md.cat == 'status':
            p += 1
        if a == 'galewings' and md.type == 'flying' and m.hp >= m.maxhp:
            p += 1
        if a == 'triage' and (md.heal or md.drain or mid in ('roost', 'synthesis', 'morningsun', 'moonlight', 'rest',
                                                              'strengthsap', 'wish', 'shoreup', 'lifedew')):
            p += 3
        if mid == 'grassyglide' and self.st.terrain == 'grassyterrain' and self.grounded(m):
            p += 1
        return p

    def protected(self, m, tgt, md):
        """TryHit for protection volatiles; returns True if the move is blocked (with side effects)."""
        sc = self.st.sides[tgt.side].cond
        if (sc.get('wideguard') or sc.get('quickguard')) and tgt is not m and 'protect' in md.flags and \
                not (self.ab(m) in ('unseenfist', 'piercingdrill') and self.contact):
            guard = sc.get('wideguard') and md.target in ('allAdjacent', 'allAdjacentFoes')
            if not guard and sc.get('quickguard'):
                pri = self.called_pri if getattr(self, 'called_pri', None) is not None else self.priority_of(m, md.id)
                guard = pri > 0.1
            if guard:
                lm = m.vol.get('lockedmove')
                if lm and lm['dur'] == 2:
                    m.vol.pop('lockedmove', None)
                self.L(tgt.name, 'guarded')
                return True
        prot = None
        for p in PROTECTS:
            if p in tgt.vol:
                prot = p
                break
        if prot is None:
            return False
        if 'protect' not in md.flags:
            if prot in ('kingsshield', 'obstruct', 'silktrap') and md.cat == 'status':
                return False
            return False
        if prot in ('kingsshield', 'obstruct', 'silktrap') and md.cat == 'status':
            return False
        if self.ab(m) in ('unseenfist', 'piercingdrill') and self.contact:
            self.bypass_protect = True
            return False
        lm = m.vol.get('lockedmove')
        if lm and lm['dur'] == 2:
            m.vol.pop('lockedmove', None)
        if self.contact and self.it(m) != 'protectivepads':
            if prot == 'kingsshield':
                self.boost(m, {'atk': -1}, tgt, 'move')
            elif prot == 'obstruct':
                self.boost(m, {'def': -2}, tgt, 'move')
            elif prot == 'silktrap':
                self.boost(m, {'spe': -1}, tgt, 'move')
            elif prot == 'spikyshield':
                self.damage(m, m.maxhp // 8, tgt, 'ability')
            elif prot == 'banefulbunker':
                self.set_status(m, 'psn', tgt)
            elif prot == 'burningbulwark':
                self.set_status(m, 'brn', tgt)
        self.L(tgt.name, 'protected')
        return True

    def hit_steps(self, m, tgt, md, self_effect):
        """trySpreadMoveHit steps for a single target. Returns truthy if the move 'hit'."""
        st = self.st
        mid = md.id
        mtype = self.type
        self.bypass_protect = False
        if tgt is not m:
            # Invulnerability
            if self.semi_inv(tgt) and not (self.ab(m) == 'noguard' or self.ab(tgt) == 'noguard'):
                ok = False
                if 'fly' in tgt.vol or 'bounce' in tgt.vol:
                    ok = mid in ('gust', 'twister', 'skyuppercut', 'thunder', 'hurricane', 'smackdown', 'thousandarrows')
                elif 'dig' in tgt.vol:
                    ok = mid in ('earthquake', 'magnitude')
                elif 'dive' in tgt.vol:
                    ok = mid in ('surf', 'whirlpool')
                if not ok:
                    self.L(mid, 'missed (semi-invulnerable)')
                    return False
            # TryHit: protection, psychic terrain, abilities
            if self.protected(m, tgt, md):
                return False
            pri = self.called_pri if getattr(self, 'called_pri', None) is not None else self.priority_of(m, mid)
            if st.terrain == 'psychicterrain' and self.grounded(tgt) and not self.semi_inv(tgt) and \
                    pri > 0 and md.target != 'self':
                return False
            ta = self.tab(tgt)
            if mid == 'uproar':
                for x in (self.act(0), self.act(1)):
                    if x.alive and x.status == 'slp':
                        x.status = ''
                        self.L(x.name, 'woke (uproar)')
            if md.cat == 'status' and ta == 'goodasgold':
                return False
            if 'reflectable' in md.flags and ta == 'magicbounce' and not getattr(self, 'bounced', False):
                self.bounced = True
                self.L(tgt.name, 'bounced', mid)
                self.use_move_bounced(tgt, m, md)
                self.bounced = False
                return False
            if ta and self.ability_absorbs(tgt, ta, mtype, md):
                return False
            if ta == 'soundproof' and 'sound' in md.flags:
                return False
            if ta == 'bulletproof' and 'bullet' in md.flags:
                return False
            if ta == 'overcoat' and 'powder' in md.flags:
                return False
            if ta == 'sturdy' and md.ohko:
                return False
            if mid == 'yawn' and (tgt.status or self.status_immune(tgt, 'slp')):
                return False
            if mid in ('substitute',):
                pass
            # Type immunity
            if md.cat != 'status' or md.ignore_imm is False:
                if self.immune(tgt, mtype, md, m):
                    self.L(tgt.name, 'immune')
                    if ta == 'flashfire' and mtype == 'fire':
                        pass
                    return False
            # TryImmunity: powder, prankster, move-specific
            if 'powder' in md.flags and self.status_immune(tgt, 'powder') and tgt is not m:
                return False
            if self.ab(m) == 'prankster' and (md.cat == 'status' or getattr(self, 'pranked', False)) and \
                    self.has_type(tgt, 'dark'):
                return False
            if mid == 'leechseed' and self.has_type(tgt, 'grass'):
                return False
            if mid == 'endeavor' and m.hp >= tgt.hp:
                return False
            if mid in ('trick', 'switcheroo') and self.tab(tgt) == 'stickyhold':
                return False
            if mid == 'octolock' and self.status_immune(tgt, 'trapped'):
                return False
            if mid in ('synchronoise',):
                pass
            # Accuracy
            if not self.accuracy_check(m, tgt, md):
                self.L(mid, 'missed')
                if mid in ('highjumpkick', 'jumpkick', 'supercellslam', 'axekick'):
                    pass
                return False
            # break protect
            if md.breaks_protect:
                for p in PROTECTS:
                    tgt.vol.pop(p, None)
        else:
            if mid == 'substitute' and ('substitute' in m.vol or m.hp <= m.maxhp // 4):
                return False
            if mid == 'shedtail' and (not self.can_switch(m.side) or 'substitute' in m.vol or m.hp <= (m.maxhp + 1) // 2):
                return False
            if mid == 'bellydrum' and (m.hp <= m.maxhp // 2 or m.boosts['atk'] >= 6):
                return False
            if md.boosts and mid not in ('clangoroussoul',) and all(
                    (m.boosts[k] >= 6 if v > 0 else m.boosts[k] <= -6) for k, v in md.boosts.items()) and \
                    not md.heal and not md.volatile:
                return False
        return self.hit_loop(m, tgt, md, self_effect)

    def use_move_bounced(self, user, tgt, md):
        """Magic Bounce: the bounced move is used by the bouncer against the original user."""
        saved = (self.user, self.move, self.type, self.cat, self.contact, self.secondaries, self.ignore_ab, self.infiltrates)
        self.user, self.move = user, md
        self.type, self.cat = md.type, md.cat
        self.ignore_ab = False
        self.secondaries = list(md.secondaries)
        self._ps_fail = False
        res = self.hit_steps(user, tgt, md, None)
        if res and md.self_switch and user.alive and self.can_switch(user.side) and not self._ps_fail:
            user.switch_flag = md.self_switch
        (self.user, self.move, self.type, self.cat, self.contact, self.secondaries, self.ignore_ab, self.infiltrates) = saved

    def ability_absorbs(self, tgt, ta, mtype, md):
        if md.target == 'self' or tgt is self.user:
            return False
        if ta in ('voltabsorb', 'waterabsorb', 'dryskin', 'eartheater'):
            need = {'voltabsorb': 'electric', 'waterabsorb': 'water', 'dryskin': 'water', 'eartheater': 'ground'}[ta]
            if mtype == need:
                self.heal(tgt, tgt.maxhp // 4, tgt, 'ability')
                return True
        elif ta in ('lightningrod', 'motordrive', 'stormdrain', 'sapsipper') and mtype == \
                {'lightningrod': 'electric', 'motordrive': 'electric', 'stormdrain': 'water', 'sapsipper': 'grass'}[ta]:
            self.boost(tgt, {'lightningrod': {'spa': 1}, 'motordrive': {'spe': 1}, 'stormdrain': {'spa': 1},
                             'sapsipper': {'atk': 1}}[ta], tgt, 'ability')
            return True
        elif ta == 'flashfire' and mtype == 'fire':
            tgt.vol['flashfire'] = True
            return True
        elif ta == 'wellbakedbody' and mtype == 'fire':
            self.boost(tgt, {'def': 2}, tgt, 'ability')
            return True
        elif ta == 'windrider' and 'wind' in md.flags:
            self.boost(tgt, {'atk': 1}, tgt, 'ability')
            return True
        return False

    def accuracy_check(self, m, tgt, md):
        acc = md.acc
        mid = md.id
        st = self.st
        if md.ohko:
            if self.ab(m) == 'noguard' or self.ab(tgt) == 'noguard' or 'glaiverush' in tgt.vol:
                return True
            if self.semi_inv(tgt):
                return False
            acc = 30
            return self.rng.chance(acc / 100, 'acc', True)
        # ModifyMove accuracy overrides
        if mid == 'blizzard' and self.eff_weather(m) == 'snowscape':
            acc = True
        if mid in ('thunder', 'hurricane', 'bleakwindstorm', 'wildboltstorm', 'sandsearstorm'):
            w = self.eff_weather(tgt)
            if w == 'raindance':
                acc = True
            elif w == 'sunnyday' and mid in ('thunder', 'hurricane'):
                acc = 50
        if acc is not True:
            # ModifyAccuracy (target's sand veil etc.) then boosts
            amod = 4096
            ta = self.tab(tgt)
            w = self.eff_weather(tgt)
            if ta == 'sandveil' and w == 'sandstorm' or ta == 'snowcloak' and w == 'snowscape':
                amod = chain(amod, 3277)
            if ta == 'tangledfeet' and 'confusion' in tgt.vol:
                amod = chain(amod, 2048)
            if self.it(tgt) == 'brightpowder':
                amod = chain(amod, 3686)
            if 'gravity' in st.pseudo:
                amod = chain(amod, 6840)
            sa = self.ab(m)
            if sa == 'compoundeyes':
                amod = chain(amod, 5325)
            if sa == 'hustle' and self.cat == 'physical':
                amod = chain(amod, 3277)
            if self.it(m) == 'widelens':
                amod = chain(amod, 4505)
            if self.it(m) == 'zoomlens' and not self.will_move(tgt):
                amod = chain(amod, 4915)
            if amod != 4096:
                acc = modify(acc, amod)
            boost = 0
            if True:
                b = m.boosts['accuracy']
                if self.tab(tgt) == 'unaware':
                    b = 0
                boost = b
            if not md.ignore_eva and not (self.ab(m) in ('keeneye', 'illuminate', 'mindseye', 'unaware')):
                boost = max(-6, min(6, boost - tgt.boosts['evasion']))
            if boost > 0:
                acc = acc * (3 + boost) // 3
            elif boost < 0:
                acc = acc * 3 // (3 - boost)
        if md.target == 'self' and md.cat == 'status':
            acc = True
        if mid == 'toxic' and self.has_type(m, 'poison'):
            acc = True
        # Accuracy event: no guard, glaive rush, minimize, lock-on
        if self.ab(m) == 'noguard' or self.ab(tgt) == 'noguard':
            acc = True
        if 'glaiverush' in tgt.vol:
            acc = True
        if 'minimize' in tgt.vol and 'minimize' in md.flags:
            acc = True
        if acc is True or acc >= 100:
            return True
        p = acc / 100
        if self.rng.expected:
            if md.cat == 'status':
                return p >= 0.7
            self.scale *= p
            return True
        return self.rng.chance(p, 'acc', True)

    def hit_loop(self, m, tgt, md, self_effect):
        """hitStepMoveHitLoop + spreadMoveHit for one target."""
        mid = md.id
        st = self.st
        hits = self.multihit or 1
        if isinstance(hits, list):
            if hits == [2, 5]:
                hits = self.rng.sample([(2, .35), (3, .35), (4, .15), (5, .15)], 'multihit')
                if hits < 4 and self.it(m) == 'loadeddice':
                    hits = self.rng.sample([(4, .5), (5, .5)], 'multihit')
            else:
                hits = hits[0]
        if hits == 10 and self.it(m) == 'loadeddice':
            hits = self.rng.sample([(h, 1 / 7) for h in range(4, 11)], 'multihit')
        if self.ab(m) == 'parentalbond' and hits == 1 and self.cat != 'status' and mid not in ('fling',) and \
                'charge' not in md.flags and not md.selfdestruct:
            hits = 2
            self.flags['pb'] = True
        any_hit = False
        total = 0
        nhits = 0
        self.total = 0
        for h in range(1, hits + 1):
            if h > 1 and m.status == 'slp' and not md.sleep_usable and not getattr(self, 'via_sleeptalk', False):
                break
            if not tgt.alive and tgt is not m:
                break
            if not m.alive and h > 1:
                break
            self.cur_hit = h
            if h > 1 and md.multiacc and not self.accuracy_check(m, tgt, md):
                break
            r = self.single_hit(m, tgt, md, self_effect, h)
            if self.fling_pending is not None:
                self.fling_drop()
            if r is False:
                if h == 1:
                    return False
                break
            any_hit = True
            self.update_all()
            if isinstance(r, int) and not isinstance(r, bool):
                total += r
                nhits += 1
                self.total = total
            if not m.alive:
                break
        self.update_all()
        if not any_hit:
            return False
        self.faint_messages()
        # recoil
        if md.id == 'struggle' and m.alive:
            self.damage(m, max(1, jsround(m.maxhp / 4)), m, 'recoil_struggle')
        elif total and (md.recoil or md.mindblown):
            if md.mindblown:
                self.damage(m, jsround(m.maxhp / 2), m, 'recoil_mb')
            else:
                rd = max(1, jsround(total * md.recoil[0] / md.recoil[1]))
                self.damage(m, rd, m, 'recoil')
            self.update_all()
        if tgt is not m and self.cat != 'status':
            tgt.times_attacked += nhits
        # AfterMoveSecondary (target items / abilities)
        if tgt is not m and tgt.vol.pop('berserk_wait', None):
            self.after_berserk = tgt
        else:
            self.after_berserk = None
        if tgt is not m and tgt.alive and self.cat != 'status' and not self.hit_sub:
            it = self.it(tgt)
            ta = self.ab(tgt)
            if ta == 'berserk' and total and tgt.hp * 2 <= tgt.maxhp < (tgt.hp + total) * 2:
                self.boost(tgt, {'spa': 1}, tgt, 'ability')
            if ta == 'angershell' and total and tgt.hp * 2 <= tgt.maxhp < (tgt.hp + total) * 2:
                self.boost(tgt, {'atk': 1, 'spa': 1, 'spe': 1, 'def': -1, 'spd': -1}, tgt, 'ability')
            if ta == 'pickpocket' and self.contact and not tgt.item and m.item:
                got = self.take_item(m, tgt)
                if got:
                    tgt.item = got
            if it == 'ejectbutton' and self.can_switch(tgt.side) and not tgt.switch_flag and not tgt.force_switch:
                if self.use_item(tgt):
                    tgt.switch_flag = True
            elif it == 'redcard' and m.alive and self.can_switch(m.side) and self.is_active(m):
                if self.use_item(tgt):
                    if self.tab(m) not in ('suctioncups', 'guarddog') and 'ingrain' not in m.vol:
                        m.force_switch = True
            if tgt.status == 'frz' and md.thaws:
                tgt.status = ''
            if ta in ('emergencyexit', 'wimpout') and total and tgt.hp * 2 <= tgt.maxhp < (tgt.hp + total) * 2 and \
                    self.can_switch(tgt.side):
                tgt.switch_flag = True
        if self.after_berserk is not None:
            self.update(self.after_berserk)
        return True

    def single_hit(self, m, tgt, md, self_effect, h):
        """spreadMoveHit for one hit. Returns damage dealt (int), True (non-damaging success) or False."""
        mid = md.id
        st = self.st
        if tgt is not m and h == 1 and mid in ('brickbreak', 'psychicfangs', 'ragingbull'):
            for c in ('reflect', 'lightscreen', 'auroraveil'):
                st.sides[tgt.side].cond.pop(c, None)
        if tgt is not m and self.cat != 'status':
            # Normal Gem (TryPrimaryHit)
            if self.it(m) == 'normalgem' and self.type == 'normal' and h == 1 and 'gem' not in m.vol:
                if self.use_item(m):
                    m.vol['gem'] = True
            # Substitute
            if 'substitute' in tgt.vol and 'bypasssub' not in md.flags and not self.infiltrates and \
                    'sound' not in md.flags:
                self.hit_sub = True
                rolls = self.calc_rolls(m, tgt, md, h)
                if rolls is None:
                    return False
                d = self.pick(rolls, tgt.vol['substitute'])
                d = min(d, tgt.vol['substitute'])
                tgt.vol['substitute'] -= d
                if tgt.vol['substitute'] <= 0:
                    del tgt.vol['substitute']
                    self.L(tgt.name, 'substitute broke')
                if self.it(tgt) == 'airballoon':
                    tgt.item = ''
                if md.drain and d:
                    self.heal(m, int(math.ceil(d * md.drain[0] / md.drain[1])), tgt, 'drain')
                if md.recoil and d:
                    pass
                if mid in ('rapidspin', 'mortalspin') and m.alive:
                    self.spin(m, mid)
                if mid in ('stoneaxe', 'ceaselessedge') and not self.sheer and m.alive:
                    self.hazard_from_move(m, mid)
                if mid in ('icespinner', 'steelroller') and m.alive:
                    self.clear_terrain()
                if self_effect and h == 1:
                    self.apply_self(m, self_effect, mid)
                for sec in self.secondaries:
                    ch = sec.get('chance', 100)
                    if sec.get('self') and (ch >= 100 or self.rng.chance(ch / 100, 'secondary', True)):
                        self.apply_secondary(m, tgt, md, sec)
                return d
            rolls = self.calc_rolls(m, tgt, md, h)
            if rolls is None:
                return False
            hp_before = tgt.hp
            d = self.pick(rolls, tgt.hp)
            if self.rng.expected and self.scale != 1.0 and not md.fixed and mid not in (
                    'superfang', 'endeavor', 'finalgambit'):
                d = max(1, int(d * self.scale))
            # Disguise
            ta = self.tab(tgt)
            if ta == 'disguise' and tgt.form.sid.startswith('mimikyu') and not tgt.busted and d > 0:
                tgt.busted = True
                self.L(tgt.name, 'disguise busted')
                d = 0
                dealt = 0
            else:
                if mid == 'finalgambit':
                    m.hp = 0
                    self.check_faint(m, m, 'self')
                dealt = self.damage(tgt, d, m, 'move')
            tgt.damaged_by = (dealt, self.cat, True, (m.side, m.idx))
            if mid in ('counter',) or True:
                c = tgt.vol.get('counter')
                if c is not None and self.cat == 'physical':
                    c['dmg'] = 2 * dealt
                c = tgt.vol.get('mirrorcoat')
                if c is not None and self.cat == 'special':
                    c['dmg'] = 2 * dealt
            if 'focuspunch' in tgt.vol and dealt:
                tgt.vol['focuspunch'] = 'lost'
            if dealt and md.drain:
                self.heal(m, jsround(dealt * md.drain[0] / md.drain[1]), tgt, 'drain')
            if 'beakblast' in tgt.vol and self.contact:
                self.set_status(m, 'brn', tgt)
            # resist berry consumption
            berry = self.it(tgt)
            if berry in RESIST_BERRY and RESIST_BERRY[berry] == self.type and \
                    ((self.typemod(tgt, self.type, md) or 0) > 0 or self.type == 'normal'):
                self.eat_item(tgt, force=True)
            if tgt.status == 'frz' and self.type == 'fire':
                tgt.status = ''
        else:
            dealt = None
        # ---- runMoveEffects (status moves & on-hit effects)
        ok = self.move_effects(m, tgt, md, dealt)
        if ok is False and dealt is None:
            return False
        # self drops (once)
        if self_effect and h == 1:
            self.apply_self(m, self_effect, mid)
        # secondaries
        if dealt is not None and self.secondaries and tgt.alive and tgt is not m:
            ta = self.tab(tgt)
            for sec in self.secondaries:
                if ta == 'shielddust' and not sec.get('self'):
                    continue
                if self.it(tgt) == 'covertcloak' and not sec.get('self'):
                    continue
                if 'substitute' in tgt.vol and not sec.get('self') and 'bypasssub' not in md.flags and \
                        not self.infiltrates and 'sound' not in md.flags:
                    continue
                ch = sec.get('chance', 100)
                if ch >= 100 or self.rng.chance(ch / 100, 'secondary', True):
                    self.apply_secondary(m, tgt, md, sec)
        elif dealt is not None and self.secondaries and tgt.alive is False:
            for sec in self.secondaries:
                ch = sec.get('chance', 100)
                if sec.get('self') and (ch >= 100 or self.rng.chance(ch / 100, 'secondary', True)):
                    self.apply_secondary(m, tgt, md, sec)
        return self.after_hit(m, tgt, md, dealt)

    def apply_self(self, m, self_effect, mid):
        if True:
            if self_effect.get('boosts'):
                ch = self_effect.get('chance')
                if ch is None or self.rng.chance(ch / 100, 'selfdrop'):
                    self.boost(m, self_effect['boosts'], m, 'move', is_self=True)
            if self_effect.get('volatileStatus'):
                v = self_effect['volatileStatus']
                if v == 'mustrecharge':
                    m.vol['mustrecharge'] = True
                elif v == 'glaiverush':
                    m.vol['glaiverush'] = True
                elif v == 'roost':
                    m.vol['roost'] = True
                elif v == 'uproar':
                    m.vol.setdefault('uproar', 3)
                elif v == 'lockedmove':
                    lm = m.vol.get('lockedmove')
                    if lm is None:
                        m.vol['lockedmove'] = {'move': mid, 'dur': 2,
                                               'true': self.rng.sample([(2, .5), (3, .5)], 'rampage')}
                    elif lm['true'] >= 2:
                        lm['dur'] = 2
                else:
                    self.add_volatile(m, v, m)

    def after_hit(self, m, tgt, md, dealt):
        mid = md.id
        # force switch
        if md.force_switch and tgt.alive and m.alive and self.can_switch(tgt.side):
            if self.tab(tgt) not in ('suctioncups', 'guarddog') and 'ingrain' not in tgt.vol:
                tgt.force_switch = True
        if dealt is not None and tgt is not m and mid == 'steelroller':
            self.clear_terrain()   # onHit (runMoveEffects) comes before DamagingHit
        # DamagingHit (target's contact abilities & items)
        if dealt is not None and tgt is not m:
            self.damaging_hit(m, tgt, md, dealt)
            # AfterHit
            if mid == 'knockoff':
                if tgt.item and not ITEMS.get(tgt.item, {}).get('megaStone') and self.tab(tgt) != 'stickyhold':
                    self.take_item(tgt, m)
            if mid in ('thief', 'covet') and not m.item and m.alive:
                got = self.take_item(tgt, m)
                if got:
                    m.item = got
            if mid in ('rapidspin', 'mortalspin') and not self.sheer:
                self.spin(m, mid)
            if mid in ('stoneaxe', 'ceaselessedge') and not self.sheer:
                self.hazard_from_move(m, mid)
            if mid == 'icespinner':
                self.clear_terrain()
            if mid == 'smackdown' or mid == 'thousandarrows':
                self.add_volatile(tgt, 'smackdown', m)
            if mid == 'spiritshackle' or mid == 'anchorshot':
                if m.alive:
                    self.add_volatile(tgt, 'trapped', m)
            if mid == 'jawlock':
                self.add_volatile(m, 'trapped', tgt)
                self.add_volatile(tgt, 'trapped', m)
            if mid == 'clearsmog' and tgt.alive:
                tgt.boosts = dict.fromkeys(BOOSTS, 0)
        return dealt if dealt is not None else True

    def spin(self, m, mid):
        m.vol.pop('leechseed', None)
        m.vol.pop('partiallytrapped', None)
        for c in ('spikes', 'toxicspikes', 'stealthrock', 'stickyweb'):
            self.st.sides[m.side].cond.pop(c, None)

    def hazard_from_move(self, m, mid):
        s = self.st.sides[1 - m.side]
        if mid == 'stoneaxe':
            s.cond['stealthrock'] = True
        else:
            s.cond['spikes'] = min(3, s.cond.get('spikes', 0) + 1)

    def damaging_hit(self, m, tgt, md, dealt):
        ta = self.ab(tgt)
        contact = self.contact and self.it(m) != 'protectivepads'
        sa = self.ab(m)
        if not tgt.alive:
            if ta == 'aftermath' and contact and m.alive:
                if not any(self.ab(x) == 'damp' for x in (m, tgt)):
                    self.damage(m, m.maxhp // 4, tgt, 'ability')
            if ta == 'innardsout' and m.alive:
                self.damage(m, dealt, tgt, 'ability')
        else:
            if ta == 'justified' and self.type == 'dark':
                self.boost(tgt, {'atk': 1}, tgt, 'ability')
            if ta == 'rattled' and self.type in ('dark', 'bug', 'ghost'):
                self.boost(tgt, {'spe': 1}, tgt, 'ability')
            if ta == 'stamina':
                self.boost(tgt, {'def': 1}, tgt, 'ability')
            if ta == 'weakarmor' and self.cat == 'physical':
                self.boost(tgt, {'def': -1, 'spe': 2}, tgt, 'ability')
            if ta == 'thermalexchange' and self.type == 'fire':
                self.boost(tgt, {'atk': 1}, tgt, 'ability')
            if ta == 'watercompaction' and self.type == 'water':
                self.boost(tgt, {'def': 2}, tgt, 'ability')
            if ta == 'steamengine' and self.type in ('water', 'fire'):
                self.boost(tgt, {'spe': 6}, tgt, 'ability')
            if ta == 'electromorphosis':
                tgt.vol['charge'] = True
            if ta == 'cottondown':
                self.boost(m, {'spe': -1}, tgt, 'ability')
        if ta == 'sandspit':
            self.set_weather('sandstorm', tgt)
        if ta == 'seedsower':
            self.set_terrain('grassyterrain', tgt)
        if ta == 'toxicdebris' and self.cat == 'physical':
            s = self.st.sides[m.side]
            if s.cond.get('toxicspikes', 0) < 2:
                s.cond['toxicspikes'] = s.cond.get('toxicspikes', 0) + 1
        if m.alive and contact:
            if ta in ('roughskin', 'ironbarbs'):
                self.damage(m, m.maxhp // 8, tgt, 'ability')
            if ta == 'static' and self.rng.chance(0.3, 'static'):
                self.set_status(m, 'par', tgt)
            elif ta == 'flamebody' and self.rng.chance(0.3, 'flamebody'):
                self.set_status(m, 'brn', tgt)
            elif ta == 'poisonpoint' and self.rng.chance(0.3, 'poisonpoint'):
                self.set_status(m, 'psn', tgt)
            elif ta == 'effectspore' and not self.status_immune(m, 'powder') and self.ab(m) != 'overcoat':
                r = self.rng.sample([('slp', .11), ('par', .10), ('psn', .09), ('', .70)], 'effectspore')
                if r:
                    self.set_status(m, r, tgt)
            elif ta in ('gooey', 'tanglinghair'):
                self.boost(m, {'spe': -1}, tgt, 'ability')
            elif ta == 'cutecharm':
                if self.rng.chance(0.3, 'cutecharm'):
                    self.add_volatile(m, 'attract', tgt)
            elif ta == 'mummy' or ta == 'lingeringaroma':
                if self.ab(m) not in CANT_SUPPRESS:
                    m.ability = ta
            elif ta == 'wanderingspirit':
                if self.ab(m) not in CANT_SUPPRESS:
                    m.ability, tgt.ability = tgt.ability, m.ability
                    self.ability_start(m)
                    self.ability_start(tgt)
            if self.it(tgt) == 'rockyhelmet' and m.alive:
                self.damage(m, m.maxhp // 6, tgt, 'item')
        if ta == 'cursedbody' and m.alive and 'disable' not in m.vol and self.rng.chance(0.3, 'cursedbody'):
            self.add_volatile(m, 'disable', tgt)
        if ta == 'spicyspray' and m.alive:
            self.set_status(m, 'brn', tgt)
        if sa == 'poisontouch' and contact and tgt.alive and self.tab(tgt) != 'shielddust' and \
                self.rng.chance(0.3, 'poisontouch'):
            self.set_status(tgt, 'psn', m)
        if self.it(tgt) == 'airballoon':
            tgt.item = ''
        if tgt.alive and ta == 'illusion':
            pass

    def calc_rolls(self, m, tgt, md, h):
        """getDamage with crit roll; returns list of 16 or None."""
        if self.cat == 'status':
            return None
        fixed = md.fixed
        if fixed == 'level':
            return [50] * 16
        if isinstance(fixed, int):
            return [fixed] * 16
        if md.id in ('counter', 'mirrorcoat'):
            c = m.vol.get(md.id) or {}
            return [c.get('dmg') or 1] * 16
        if md.id in ('metalburst', 'comeuppance'):
            db = m.damaged_by
            return [int(db[0] * 1.5) or 1] * 16
        cr = self.crit_ratio(m, tgt, md)
        ta = self.tab(tgt)
        crit = False
        pb2 = bool(self.flags.get('pb')) and h == 2
        if cr >= 1:
            crit = True
        elif cr > 0 and ta not in ('battlearmor', 'shellarmor'):
            if self.rng.expected:
                crit = False
            else:
                noc = self.get_damage(m, tgt, md, False, pb2)
                if noc is None:
                    return None
                c = self.get_damage(m, tgt, md, True, pb2)
                matters = c is not None and c[7] >= tgt.hp > noc[0]
                crit = self.rng.chance(cr, 'crit', matters)
                if not crit:
                    return noc
                self.crit_hit = True
                return c
        if ta in ('battlearmor', 'shellarmor'):
            crit = False
        if crit:
            self.crit_hit = True
        return self.get_damage(m, tgt, md, crit, pb2)

    def pick(self, rolls, hp):
        if rolls[0] == rolls[15]:
            return rolls[0]
        return rolls[self.rng.roll(rolls, hp)]

    def apply_secondary(self, m, tgt, md, sec):
        mid = md.id
        if sec.get('self'):
            s = sec['self']
            if s.get('boosts'):
                self.boost(m, s['boosts'], m, 'move', is_self=True)
            return
        if sec.get('boosts') and tgt.alive:
            self.boost(tgt, sec['boosts'], m, 'move', is_secondary=True)
        if sec.get('status') and tgt.alive:
            self.set_status(tgt, sec['status'], m, secondary=True)
        if sec.get('volatileStatus') and tgt.alive:
            v = sec['volatileStatus']
            if v == 'flinch':
                if self.will_move(tgt):
                    self.add_volatile(tgt, 'flinch', m)
            elif v == 'sparklingaria':
                tgt.vol['sparklingaria'] = True
            elif v == 'saltcure':
                tgt.vol['saltcure'] = True
            elif v == 'syrupbomb':
                self.add_volatile(tgt, 'syrupbomb', m)
            else:
                self.add_volatile(tgt, v, m, effect=mid)
        if sec.get('onHit') and tgt.alive:
            if mid == 'triattack':
                self.set_status(tgt, self.rng.sample([('brn', 1 / 3), ('par', 1 / 3), ('frz', 1 / 3)], 'triattack'), m)
            elif mid == 'direclaw':
                self.set_status(tgt, self.rng.sample([('psn', 1 / 3), ('par', 1 / 3), ('slp', 1 / 3)], 'direclaw'), m)
            elif mid == 'alluringvoice' and tgt.raised:
                self.add_volatile(tgt, 'confusion', m)
            elif mid == 'burningjealousy' and tgt.raised:
                self.set_status(tgt, 'brn', m)
            elif mid in ('spiritshackle', 'anchorshot'):
                self.add_volatile(tgt, 'trapped', m)
            elif mid == 'throatchop':
                self.add_volatile(tgt, 'throatchop', m)
            elif mid == 'eeriespell':
                pass

    def move_effects(self, m, tgt, md, dealt):
        """runMoveEffects: boosts/heal/status/volatile/side/weather/terrain/pseudoweather/onHit for the move."""
        mid = md.id
        st = self.st
        f = self.foe(m)
        did = None if dealt is None else True
        if md.cat == 'status' and tgt is not m and 'substitute' in tgt.vol and 'bypasssub' not in md.flags and \
                not self.infiltrates and mid not in ('transform',) and md.target not in ('all', 'foeSide'):
            return False
        if md.boosts and mid not in ('clangoroussoul',) and tgt.alive:
            if mid == 'growth' and self.eff_weather(m) == 'sunnyday':
                r = self.boost(tgt, {'atk': 2, 'spa': 2}, m, 'move')
            else:
                r = self.boost(tgt, md.boosts, m, 'move')
            did = bool(did) or bool(r)
        if md.heal and tgt.alive:
            if tgt.hp >= tgt.maxhp:
                return False if dealt is None else True
            amt = jsround(tgt.maxhp * md.heal[0] / md.heal[1])
            self.heal(tgt, amt, m, 'move')
            did = True
        if md.status and tgt.alive:
            r = self.set_status(tgt, md.status, m, by_move=True)
            if not r and md.cat == 'status':
                return False
            did = did or r
        if md.volatile and tgt.alive and mid not in ('curse',):
            v = md.volatile
            if v in PROTECTS or v == 'endure':
                tgt.vol[v] = True
                st_ = m.vol.get('stall')
                m.vol['stall'] = (st_ * 3 if st_ else 3)
                m.vol['stall_used'] = True
                did = True
            elif v in ('roost',):
                tgt.vol['roost'] = True
            elif v == 'substitute':
                if mid == 'shedtail':
                    self.damage(m, (m.maxhp + 1) // 2, m, 'direct')
                    m.vol['substitute'] = m.maxhp // 4
                    m.switch_flag = 'shedtail'
                else:
                    self.damage(m, m.maxhp // 4, m, 'direct')
                    m.vol['substitute'] = m.maxhp // 4
                    m.vol.pop('partiallytrapped', None)
                did = True
            elif v in ('glaiverush', 'mustrecharge', 'uproar', 'charge', 'destinybond', 'noretreat', 'powertrick',
                       'electrify', 'minimize', 'imprison', 'ingrain', 'aquaring', 'focusenergy', 'gastroacid',
                       'lockon', 'octolock'):
                if v in tgt.vol and v not in ('charge',):
                    if v == 'noretreat':
                        pass
                    if md.cat == 'status' and v not in ('destinybond',):
                        return False
                if v == 'octolock':
                    if self.status_immune(tgt, 'trapped'):
                        return False
                    tgt.vol['octolock'] = m.side
                elif v == 'gastroacid':
                    if self.ab(tgt) in CANT_SUPPRESS:
                        return False
                    tgt.vol['gastroacid'] = True
                elif v == 'powertrick':
                    s = dict(tgt.stats or tgt.form.stats)
                    s['atk'], s['def'] = s['def'], s['atk']
                    tgt.stats = s
                    tgt.vol['powertrick'] = True
                elif v == 'focusenergy':
                    r = self.add_volatile(tgt, 'focusenergy', m)
                    if not r:
                        return False
                else:
                    tgt.vol[v] = True
                did = True
            else:
                r = self.add_volatile(tgt, v, m, effect=mid)
                if not r and md.cat == 'status':
                    return False
                did = did or r
        if md.side and md.cat == 'status':
            pass
        if md.weather:
            r = self.set_weather(md.weather, m)
            did = did or r
            if not r and md.cat == 'status' and mid != 'chillyreception':
                return False
        if md.terrain:
            r = self.set_terrain(md.terrain, m)
            if not r and md.cat == 'status':
                return False
            did = True
        if md.slot:
            s = st.sides[m.side]
            if md.slot.lower() == 'wish':
                if 'wish' in s.slot:
                    return False
                s.slot['wish'] = [2, m.maxhp // 2]
            elif md.slot == 'healingwish':
                if not self.can_switch(m.side):
                    return False
                s.slot['healingwish'] = True
                m.hp = 0
                self.check_faint(m, m, 'self')
            elif md.slot == 'revivalblessing':
                fainted = [j for j, x in enumerate(s.mons) if x.fainted]
                if not fainted:
                    return False
                j = fainted[0]
                x = s.own(j)
                x.fainted = False
                x.faint_queued = False
                x.hp = x.maxhp // 2
                x.status = ''
                s.fainted_total = max(0, s.fainted_total)
            did = True
        if md.self_switch and mid in ('teleport', 'chillyreception'):
            did = True
        # ---- move-specific onHit
        r = self.on_hit(m, tgt, md, dealt)
        if r is False:
            return False
        if r is True:
            did = True
        if md.selfdestruct == 'ifHit':
            m.hp = 0
            self.check_faint(m, m, 'self')
        return True if did is None else did

    def on_hit(self, m, tgt, md, dealt):
        mid = md.id
        st = self.st
        if mid in ('recover', 'slackoff', 'softboiled', 'milkdrink', 'roost', 'healorder', 'shoreup'):
            if mid == 'shoreup' and self.eff_weather(m) == 'sandstorm':
                self.heal(m, modify(m.maxhp, 2732), m, 'move')
            return None
        if mid == 'healpulse':
            if not tgt.alive or tgt.hp >= tgt.maxhp or 'healblock' in tgt.vol:
                return False
            amt = modify(tgt.maxhp, 3072) if self.ab(m) == 'megalauncher' else -(-tgt.maxhp // 2)
            return bool(self.heal(tgt, amt, m, 'move'))
        if mid in ('synthesis', 'morningsun', 'moonlight'):
            w = self.eff_weather(m)
            fac = 0.667 if w == 'sunnyday' else 0.25 if w in ('raindance', 'sandstorm', 'snowscape') else 0.5
            if m.hp >= m.maxhp:
                return False
            self.heal(m, modify(m.maxhp, int(fac * 4096)), m, 'move')
            return True
        if mid == 'rest':
            if not self.set_status(m, 'slp', m, replace=True):
                return False
            m.stime = 3
            m.hp = m.maxhp
            return True
        if mid == 'painsplit':
            avg = (tgt.hp + m.hp) // 2 or 1
            tgt.hp = min(tgt.maxhp, avg)
            m.hp = min(m.maxhp, avg)
            return True
        if mid == 'bellydrum':
            self.damage(m, m.maxhp // 2, m, 'direct')
            self.boost(m, {'atk': 12}, m, 'move')
            return True
        if mid == 'clangoroussoul':
            if not self.boost(m, {'atk': 1, 'def': 1, 'spa': 1, 'spd': 1, 'spe': 1}, m, 'move'):
                return False
            self.damage(m, m.maxhp * 33 // 100, m, 'direct')
            return True
        if mid == 'curse':
            if not self.has_type(m, 'ghost'):
                return self.boost(m, {'spe': -1, 'atk': 1, 'def': 1}, m, 'move')
            if 'curse' in tgt.vol:
                return False
            self.damage(m, m.maxhp // 2, m, 'direct')
            tgt.vol['curse'] = True
            return True
        if mid == 'strengthsap':
            if tgt.boosts['atk'] == -6:
                return False
            atk = self.boosted(tgt.stat('atk'), tgt.boosts['atk'])
            ok = self.boost(tgt, {'atk': -1}, m, 'move')
            return bool(self.heal(m, atk, tgt, 'strengthsap') or ok)
        if mid == 'partingshot':
            ok = self.boost(tgt, {'atk': -1, 'spa': -1}, m, 'move')
            if not ok and self.ab(tgt) != 'mirrorarmor':
                self._ps_fail = True
                m.switch_flag = False
            else:
                self._ps_fail = False
            return True
        if mid in ('trick', 'switcheroo'):
            mine, theirs = m.item, tgt.item
            if ITEMS.get(mine, {}).get('megaStone') or ITEMS.get(theirs, {}).get('megaStone') or (not mine and not theirs):
                return False
            m.item, tgt.item = theirs, mine
            m.vol.pop('choicelock', None)
            tgt.vol.pop('choicelock', None)
            return True
        if mid == 'haze':
            for i in (0, 1):
                self.act(i).boosts = dict.fromkeys(BOOSTS, 0)
            return True
        if mid == 'topsyturvy':
            if not any(tgt.boosts.values()):
                return False
            tgt.boosts = {k: -v for k, v in tgt.boosts.items()}
            return True
        if mid == 'defog':
            ok = False
            if 'substitute' not in tgt.vol or self.infiltrates:
                ok = self.boost(tgt, {'evasion': -1}, m, 'move')
            for c in ('reflect', 'lightscreen', 'auroraveil', 'safeguard', 'mist'):
                st.sides[tgt.side].cond.pop(c, None)
            for i in (0, 1):
                for c in ('spikes', 'toxicspikes', 'stealthrock', 'stickyweb'):
                    if st.sides[i].cond.pop(c, None):
                        ok = True
            self.clear_terrain()
            return ok
        if mid == 'tidyup':
            for i in (0, 1):
                self.act(i).vol.pop('substitute', None)
                for c in ('spikes', 'toxicspikes', 'stealthrock', 'stickyweb'):
                    st.sides[i].cond.pop(c, None)
            self.boost(m, {'atk': 1, 'spe': 1}, m, 'move')
            return True
        if mid == 'courtchange':
            keys = ('mist', 'lightscreen', 'reflect', 'spikes', 'safeguard', 'tailwind', 'toxicspikes', 'stealthrock',
                    'stickyweb', 'auroraveil')
            a, b = st.sides[0].cond, st.sides[1].cond
            ma = {k: a.pop(k) for k in list(a) if k in keys}
            mb = {k: b.pop(k) for k in list(b) if k in keys}
            a.update(mb)
            b.update(ma)
            return bool(ma or mb)
        if mid in ('magneticflux', 'gearup'):
            if self.ab(m) not in ('plus', 'minus'):
                return False
            return self.boost(m, {'def': 1, 'spd': 1} if mid == 'magneticflux' else {'atk': 1, 'spa': 1}, m, 'move')
        if mid == 'reflecttype':
            base = tuple(tgt.types if tgt.types is not None else tgt.form.types)
            if not base:
                if not tgt.added_type:
                    return False
                base = ('normal',)
            m.types = base
            m.added_type = tgt.added_type
            return True
        if mid == 'soak':
            if tuple(self.types(tgt)) == ('water',):
                return False
            tgt.types = ('water',)
            return True
        if mid == 'magicpowder':
            tgt.types = ('psychic',)
            return True
        if mid == 'forestscurse':
            tgt.added_type = 'grass'
            return True
        if mid == 'trickortreat':
            tgt.added_type = 'ghost'
            return True
        if mid == 'burnup' and dealt is not None:
            m.types = tuple('???' if t == 'fire' else t for t in self.types(m))
        if mid == 'doubleshock' and dealt is not None:
            m.types = tuple('???' if t == 'electric' else t for t in self.types(m))
        if mid in ('skillswap',):
            if self.ab(tgt) in CANT_SUPPRESS or self.ab(m) in CANT_SUPPRESS:
                return False
            m.ability, tgt.ability = tgt.ability, m.ability
            self.ability_start(m)
            self.ability_start(tgt)
            return True
        if mid in ('worryseed', 'simplebeam', 'entrainment', 'roleplay'):
            new = {'worryseed': 'insomnia', 'simplebeam': 'simple'}.get(mid)
            if mid == 'entrainment':
                new = self.ab(m)
            if mid == 'roleplay':
                m.ability = self.ab(tgt)
                return True
            if self.ab(tgt) in CANT_SUPPRESS or self.ab(tgt) == new:
                return False
            tgt.ability = new
            if new == 'insomnia' and tgt.status == 'slp':
                tgt.status = ''
            return True
        if mid == 'transform':
            self.transform(m, tgt)
            return True
        if mid in ('psychup',):
            m.boosts = dict(tgt.boosts)
            return True
        if mid in ('powerswap', 'guardswap', 'speedswap', 'powersplit', 'guardsplit'):
            keys = {'powerswap': ('atk', 'spa'), 'guardswap': ('def', 'spd')}.get(mid)
            if keys:
                for k in keys:
                    m.boosts[k], tgt.boosts[k] = tgt.boosts[k], m.boosts[k]
            elif mid == 'speedswap':
                a = dict(m.stats or m.form.stats)
                b = dict(tgt.stats or tgt.form.stats)
                a['spe'], b['spe'] = b['spe'], a['spe']
                m.stats, tgt.stats = a, b
            else:
                ks = ('atk', 'spa') if mid == 'powersplit' else ('def', 'spd')
                a = dict(m.stats or m.form.stats)
                b = dict(tgt.stats or tgt.form.stats)
                for k in ks:
                    a[k] = b[k] = (a[k] + b[k]) // 2
                m.stats, tgt.stats = a, b
            return True
        if mid in ('bugbite', 'pluck') and m.alive:
            it = tgt.item
            if it in BERRIES:
                tgt.item = ''
                self.berry_effect(m, it)
                m.ate_berry = True
        if mid == 'corrosivegas':
            if tgt is not m and tgt.item:
                return bool(self.take_item(tgt, m))
            return False
        if mid == 'stuffcheeks':
            if not self.boost(m, {'def': 2}, m, 'move'):
                return None
            self.eat_item(m, force=True)
            return True
        if mid == 'teatime':
            for i in (0, 1):
                x = self.act(i)
                if x.item in BERRIES:
                    self.eat_item(x, force=True)
            return True
        if mid == 'swallow':
            layers = (m.vol.get('stockpile') or {}).get('layers', 1)
            ok = self.heal(m, modify(m.maxhp, [1024, 2048, 4096][layers - 1]), m, 'move')
            self.end_stockpile(m)
            return True
        if mid == 'recycle':
            if m.item or not m.last_item:
                return False
            m.item, m.last_item = m.last_item, ''
            return True
        if mid == 'acupressure':
            ks = [k for k in ('atk', 'def', 'spa', 'spd', 'spe', 'accuracy', 'evasion') if tgt.boosts[k] < 6]
            if not ks:
                return False
            k = self.rng.sample([(k, 1 / len(ks)) for k in ks], 'acupressure')
            return self.boost(tgt, {k: 2}, m, 'move')
        if mid == 'healbell':
            sd = st.sides[m.side]
            for j in range(len(sd.mons)):
                if sd.mons[j].status:
                    sd.own(j).status = ''
            return True
        if mid == 'spite':
            lm = tgt.last_move
            if not lm or lm not in tgt.moves or lm == 'struggle':
                return False
            pp = tgt.pp if tgt.pp is not None else {}
            cur = pp.get(lm, MOVES[lm].pp)
            if cur <= 0:
                return False
            pp[lm] = max(0, cur - 4)
            tgt.pp = pp
            return True
        if mid == 'instruct':
            lm = tgt.last_move
            if not tgt.alive or not lm or lm not in MOVES or lm not in tgt.moves:
                return False
            lmd = MOVES[lm]
            if 'failinstruct' in lmd.flags or 'charge' in lmd.flags or 'recharge' in lmd.flags or \
                    any(k in tgt.vol for k in ('beakblast', 'focuspunch', 'shelltrap')) or \
                    (tgt.pp is not None and tgt.pp.get(lm, 1) <= 0):
                return False
            self.queue.insert(0, ['move', tgt, lm, tgt.side])
            return True
        if mid == 'copycat':
            lm = getattr(self, 'prev_lastmove', None)
            if not lm or lm == 'copycat' or lm not in MOVES or 'failcopycat' in MOVES[lm].flags:
                return False
            st.lastmove = lm
            self.pranked = self.ab(m) == 'prankster'
            self.called_pri = self.priority_of(m, 'copycat')
            self.use_move(m, MOVES[lm])
            self.pranked = False
            self.called_pri = None
            st.lastmove = lm
            return True
        if mid == 'sleeptalk':
            opts = [x for x in m.moves if x not in ('sleeptalk', 'focuspunch', 'beakblast', 'solarbeam', 'solarblade',
                                                     'skyattack', 'meteorbeam', 'electroshot', 'fly', 'dig', 'dive',
                                                     'bounce', 'phantomforce', 'shadowforce', 'uproar', 'belch',
                                                     'copycat', 'assist', 'mefirst', 'metronome', 'mimic',
                                                     'mirrormove', 'sketch', 'chatter')]
            if not opts:
                return False
            mv = self.rng.sample([(x, 1 / len(opts)) for x in opts], 'sleeptalk')
            self.pranked = self.ab(m) == 'prankster'
            self.called_pri = self.priority_of(m, 'sleeptalk')
            self.via_sleeptalk = True
            self.use_move(m, MOVES[mv])
            self.via_sleeptalk = False
            self.pranked = False
            self.called_pri = None
            return True
        if mid == 'perishsong':
            for i in (0, 1):
                x = self.act(i)
                if x.alive and 'perishsong' not in x.vol and self.ab(x) != 'soundproof':
                    x.vol['perishsong'] = 4
            return True
        if mid in ('block', 'meanlook'):
            return self.add_volatile(tgt, 'trapped', m) or False
        if mid == 'futuresight' and tgt is not m:
            st.sides[tgt.side].slot['futuremove'] = [3, m.side, m.idx]
            return True
        if mid == 'smackdown':
            return None
        return None

    def field_move(self, m, md):
        """Moves targeting a side or the whole field (hazards, screens, weather, terrain, rooms, ...)."""
        st = self.st
        mid = md.id
        if md.side:
            c = md.side
            s = st.sides[1 - m.side] if md.target == 'foeSide' else st.sides[m.side]
            if md.target == 'foeSide':
                f = self.foe(m)
                if f.alive and self.ab(f) == 'magicbounce' and 'reflectable' in md.flags:
                    s = st.sides[m.side]
            if c == 'spikes':
                if s.cond.get('spikes', 0) >= 3:
                    return False
                s.cond['spikes'] = s.cond.get('spikes', 0) + 1
            elif c == 'toxicspikes':
                if s.cond.get('toxicspikes', 0) >= 2:
                    return False
                s.cond['toxicspikes'] = s.cond.get('toxicspikes', 0) + 1
            elif c in ('stealthrock', 'stickyweb'):
                if s.cond.get(c):
                    return False
                s.cond[c] = True
            elif c in ('reflect', 'lightscreen', 'auroraveil'):
                if s.cond.get(c):
                    return False
                s.cond[c] = 8 if self.it(m) == 'lightclay' else 5
            elif c == 'tailwind':
                if s.cond.get(c):
                    return False
                s.cond[c] = 4
            elif c == 'safeguard' or c == 'mist':
                if s.cond.get(c):
                    return False
                s.cond[c] = 5
            elif c in ('quickguard', 'wideguard'):
                if s.cond.get(c) or not self.will_move_any_other(m):
                    return False
                s.cond[c] = 1
                st_ = m.vol.get('stall')
                m.vol['stall'] = min(729, st_ * 3) if st_ else 3
                m.vol['stall_used'] = True
            elif c in ('craftyshield', 'matblock'):
                return False
            return True
        if md.weather:
            return self.set_weather(md.weather, m)
        if md.terrain:
            return self.set_terrain(md.terrain, m)
        if md.pseudo:
            p = md.pseudo
            if p in st.pseudo and p in ('trickroom', 'magicroom', 'wonderroom'):
                del st.pseudo[p]
                return True
            if p in st.pseudo:
                return False
            st.pseudo[p] = 5
            if p == 'gravity':
                for i in (0, 1):
                    x = self.act(i)
                    for v in ('fly', 'bounce', 'magnetrise'):
                        x.vol.pop(v, None)
            return True
        if mid == 'haze':
            for i in (0, 1):
                self.act(i).boosts = dict.fromkeys(BOOSTS, 0)
            return True
        if mid == 'perishsong':
            for i in (0, 1):
                x = self.act(i)
                if x.alive and 'perishsong' not in x.vol and self.ab(x) != 'soundproof':
                    x.vol['perishsong'] = 4
            return True
        if mid in ('courtchange', 'healbell', 'magneticflux'):
            return self.on_hit(m, m, md, None)
        if mid == 'teatime':
            return self.on_hit(m, m, md, None)
        return False

    # ================================================================ residual
    def residual(self):
        try:
            self._residual()
        except _GameOver:
            pass

    def rd(self, x, d, src=None, eff=''):
        """Residual damage: faints are processed right away and the turn ends with the battle."""
        r = self.damage(x, d, src, eff)
        self.faint_messages()
        if self.st.winner is not None:
            raise _GameOver
        return r

    def _residual(self):
        st = self.st
        order = sorted((self.act(i) for i in (0, 1)), key=lambda x: (-self.action_speed(x), -x.side))
        alive = lambda x: x.alive and self.is_active(x)
        hp_start = {id(x): x.hp for x in order}
        st0 = {id(x): x.status for x in order}
        # 1: weather
        if st.weather:
            st.wturns -= 1
            if st.wturns <= 0:
                st.weather = ''
                for x in order:
                    if x.alive and self.ab(x) == 'forecast':
                        self.forecast(x)
            else:
                w = self.eff_weather()
                for x in order:
                    if not alive(x):
                        continue
                    a = self.ab(x)
                    if w == 'sandstorm':
                        if not self.status_immune(x, 'sandstorm'):
                            self.damage(x, x.maxhp // 16, None, 'weather')
                    elif w == 'raindance':
                        if a in ('dryskin',):
                            self.heal(x, x.maxhp // 8, x, 'ability')
                        elif a == 'raindish':
                            self.heal(x, x.maxhp // 16, x, 'ability')
                    elif w == 'sunnyday':
                        if a in ('dryskin', 'solarpower'):
                            self.damage(x, x.maxhp // 8, x, 'ability')
                    elif w == 'snowscape':
                        if a == 'icebody':
                            self.heal(x, x.maxhp // 16, x, 'ability')
        self.faint_messages()
        if st.winner is not None:
            return
        # 3: future sight ; 4: wish
        for i in (0, 1):
            s = st.sides[i]
            fm = s.slot.get('futuremove')
            if fm:
                fm[0] -= 1
                if fm[0] <= 0:
                    del s.slot['futuremove']
                    x = self.act(i)
                    if x.alive:
                        self.future_hit(fm, x)
            w = s.slot.get('wish')
            if w:
                w[0] -= 1
                if w[0] <= 0:
                    del s.slot['wish']
                    x = self.act(i)
                    if x.alive:
                        self.heal(x, w[1], x, 'wish')
        self.faint_messages()
        if st.winner is not None:
            return
        # 5: grassy terrain heal (sub 2), hydration/shed skin (sub 3), leftovers (sub 4)
        for x in order:
            if not alive(x):
                continue
            if st.terrain == 'grassyterrain' and self.grounded(x) and not self.semi_inv(x):
                self.heal(x, x.maxhp // 16, x, 'terrain')
        for x in order:
            if not alive(x):
                continue
            a = self.ab(x)
            if x.status and a == 'hydration' and self.eff_weather(x) == 'raindance':
                x.status = ''
            elif x.status and a == 'shedskin' and self.rng.chance(0.33, 'shedskin'):
                x.status = ''
        for x in order:
            if alive(x) and self.it(x) == 'leftovers':
                self.heal(x, x.maxhp // 16, x, 'item')
            if alive(x) and self.it(x) == 'blacksludge':
                if self.has_type(x, 'poison'):
                    self.heal(x, x.maxhp // 16, x, 'item')
                else:
                    self.rd(x, x.maxhp // 8, x, 'item')
        # 6 aqua ring, 7 ingrain
        for x in order:
            if alive(x) and 'aquaring' in x.vol:
                self.heal(x, x.maxhp // 16, x, 'aquaring')
            if alive(x) and 'ingrain' in x.vol:
                self.heal(x, x.maxhp // 16, x, 'ingrain')
        # 8 leech seed
        for x in order:
            if alive(x) and 'leechseed' in x.vol:
                src = self.act(x.vol['leechseed'])
                if src.alive:
                    d = self.damage(x, x.maxhp // 8, src, 'leechseed')
                    if d:
                        self.heal(src, d, x, 'leechseed')
                    self.faint_messages()
                    if st.winner is not None:
                        raise _GameOver
        self.faint_messages()
        if st.winner is not None:
            return
        # 9 poison, 10 burn
        for x in order:
            if not alive(x):
                continue
            if x.status != st0[id(x)]:
                continue
            if x.status == 'psn':
                self.rd(x, x.maxhp // 8, None, 'psn')
            elif x.status == 'tox':
                x.tox = min(15, x.tox + 1)
                self.rd(x, max(1, x.maxhp // 16) * x.tox, None, 'tox')
        for x in order:
            if alive(x) and x.status == 'brn' and st0[id(x)] == 'brn':
                self.rd(x, x.maxhp // 16, None, 'brn')
        self.faint_messages()
        if st.winner is not None:
            return
        # 12 curse, 13 bind & salt cure, 14 octolock & syrup bomb
        for x in order:
            if not alive(x):
                continue
            if 'curse' in x.vol:
                self.rd(x, x.maxhp // 4, None, 'curse')
            pt = x.vol.get('partiallytrapped')
            if pt and alive(x):
                src = pt.get('src')
                srcm = st.sides[src[0]].mons[src[1]] if src else None
                pt['dur'] -= 1
                if pt['dur'] <= 0:
                    del x.vol['partiallytrapped']
                elif srcm is not None and (not srcm.alive or not self.is_active(srcm)):
                    del x.vol['partiallytrapped']
                else:
                    self.rd(x, x.maxhp // pt['div'], None, 'partiallytrapped')
            if 'saltcure' in x.vol and alive(x):
                self.rd(x, x.maxhp // (8 if (self.has_type(x, 'water') or self.has_type(x, 'steel')) else 16),
                            None, 'saltcure')
            if 'octolock' in x.vol and alive(x):
                src = self.act(x.vol['octolock'])
                if src.alive:
                    self.boost(x, {'def': -1, 'spd': -1}, src, 'move')
                else:
                    del x.vol['octolock']
            sb = x.vol.get('syrupbomb')
            if sb and alive(x):
                sb['dur'] -= 1
                if sb['dur'] <= 0:
                    del x.vol['syrupbomb']
                else:
                    self.boost(x, {'spe': -1}, self.act(sb['src']), 'move')
        self.faint_messages()
        if st.winner is not None:
            return
        # 15 taunt, 16 encore, 17 disable, 18 magnet rise, 22 throat chop, 23 yawn, 24 perish song, 25 roost
        for x in order:
            if not alive(x):
                continue
            v = x.vol
            if 'taunt' in v:
                v['taunt'] -= 1
                if v['taunt'] <= 0:
                    del v['taunt']
            if 'encore' in v:
                e = v['encore']
                e['dur'] -= 1
                if e['dur'] <= 0:
                    del v['encore']
            if 'disable' in v:
                d = v['disable']
                d['dur'] -= 1
                if d['dur'] <= 0:
                    del v['disable']
            if 'magnetrise' in v:
                v['magnetrise'] -= 1
                if v['magnetrise'] <= 0:
                    del v['magnetrise']
            if 'throatchop' in v:
                v['throatchop'] -= 1
                if v['throatchop'] <= 0:
                    del v['throatchop']
            if 'yawn' in v:
                v['yawn'] -= 1
                if v['yawn'] <= 0:
                    del v['yawn']
                    self.set_status(x, 'slp', self.foe(x))
            if 'perishsong' in v:
                v['perishsong'] -= 1
                if v['perishsong'] <= 0:
                    del v['perishsong']
                    x.hp = 0
                    self.check_faint(x, None, 'perish')
            v.pop('roost', None)
        self.faint_messages()
        if st.winner is not None:
            return
        # 26 side conditions, 27 field
        for i in (0, 1):
            c = st.sides[i].cond
            for k in ('reflect', 'lightscreen', 'safeguard', 'mist', 'tailwind', 'auroraveil', 'wideguard', 'quickguard'):
                if c.get(k):
                    c[k] -= 1
                    if c[k] <= 0:
                        del c[k]
        for k in list(st.pseudo):
            st.pseudo[k] -= 1
            if st.pseudo[k] <= 0:
                del st.pseudo[k]
        if st.terrain:
            st.tturns -= 1
            if st.tturns <= 0:
                self.clear_terrain()
        # 28: speed boost, moody, harvest, cud chew, uproar
        for x in order:
            if not alive(x):
                continue
            a = self.ab(x)
            if a == 'speedboost' and x.active_turns:
                self.boost(x, {'spe': 1}, x, 'ability')
            elif a == 'moody':
                up = [k for k in STATS if x.boosts[k] < 6]
                if up:
                    k = self.rng.sample([(k, 1 / len(up)) for k in up], 'moody')
                    dn = [k2 for k2 in STATS if x.boosts[k2] > -6 and k2 != k]
                    b = {k: 2}
                    if dn:
                        b[self.rng.sample([(k2, 1 / len(dn)) for k2 in dn], 'moody')] = -1
                    self.boost(x, b, x, 'ability')
            elif a == 'harvest' and not x.item and x.last_item in BERRIES:
                if self.eff_weather(x) == 'sunnyday' or self.rng.chance(0.5, 'harvest'):
                    x.item, x.last_item = x.last_item, ''
            cc = x.vol.get('cudchew')
            if cc:
                cc[1] -= 1
                if cc[1] <= 0:
                    del x.vol['cudchew']
                    self.berry_effect(x, cc[0])
            if 'uproar' in x.vol:
                x.vol['uproar'] -= 1
                if x.vol['uproar'] <= 0:
                    del x.vol['uproar']
        # 29: hunger switch, white herb etc.
        for x in order:
            if alive(x) and self.ab(x) == 'hungerswitch' and x.form.base == 'Morpeko':
                if x.vol.get('hangry'):
                    del x.vol['hangry']
                else:
                    x.vol['hangry'] = True
        for x in order:
            if alive(x):
                self.update(x)
        self.herbs()
        self.faint_messages()
        if st.winner is not None:
            return
        for x in order:
            self.emergency_exit(x, hp_start[id(x)])

    def future_hit(self, fm, tgt):
        _, src_side, src_idx = fm
        src = self.st.sides[src_side].mons[src_idx]
        md = MOVES['futuresight']
        save = (self.user, self.move, self.type, self.cat, self.contact, self.flags, self.secondaries, self.multihit)
        self.user, self.move, self.type, self.cat, self.contact, self.flags = src, md, 'psychic', 'special', False, {}
        self.secondaries, self.multihit = [], None
        if not any(TYPEMOD['psychic', t] is None for t in self.types(tgt)):
            rolls = self.get_damage(src, tgt, md, False)
            if rolls:
                d = self.damage(tgt, self.pick(rolls, tgt.hp), src, 'move')
                if d:
                    self.damaging_hit(src, tgt, md, d)
        (self.user, self.move, self.type, self.cat, self.contact, self.flags, self.secondaries, self.multihit) = save

    # ================================================================ turn driver
    def run_turn(self, a0, a1):
        st = self.st
        st.turn += 1
        acts = [a0, a1]
        for i in (0, 1):
            m = self.act(i)
            m.hurt = False
            m.raised = m.lowered = False
            m.used_item = False
            m.this_result = None
            m.times_hit_turn = 0
            if m.damaged_by:
                m.damaged_by = (m.damaged_by[0], m.damaged_by[1], False, m.damaged_by[3])
            st.sides[i].fainted_last = False
        self.update_all()
        # beforeTurnMove: counter / mirror coat
        for i in (0, 1):
            a = acts[i]
            if a and a[0] == 'm' and a[1] in ('counter', 'mirrorcoat'):
                self.act(i).vol[a[1]] = {'dmg': 0}
        # switches (order 103), faster first
        sw = [i for i in (0, 1) if acts[i] and acts[i][0] == 's']
        sw.sort(key=lambda i: (-self.action_speed(self.act(i)), -i))
        if len(sw) == 2 and self.action_speed(self.act(0)) == self.action_speed(self.act(1)) and \
                not self.rng.expected and not getattr(self.rng, 'pessimistic_ties', False):
            if self.rng.chance(0.5, 'tie'):
                sw.reverse()
        for i in sw:
            self.switch_in(i, acts[i][1])
            if st.winner is not None:
                return
        # mega evolution (order 104)
        megas = [i for i in (0, 1) if acts[i] and acts[i][0] == 'm' and len(acts[i]) > 2 and acts[i][2]]
        megas.sort(key=lambda i: (-self.action_speed(self.act(i)), -i))
        for i in megas:
            self.mega(self.act(i))
            self.update_all()
        # priority charge (focus punch / beak blast)
        for i in (0, 1):
            a = acts[i]
            if a and a[0] == 'm' and a[1] in ('focuspunch', 'beakblast'):
                self.act(i).vol[a[1]] = True
        # moves (order 200)
        self.queue = []
        for i in (0, 1):
            a = acts[i]
            if a and a[0] == 'm':
                m = self.act(i)
                self.queue.append(['move', m, a[1], i])
        self.sort_queue()
        while self.queue:
            act = self.queue.pop(0)
            _, m, mid, i = act[:4]
            if not m.alive or not self.is_active(m):
                continue
            self.run_move(m, mid)
            if st.winner is not None:
                return
            self.after_action()
            if st.winner is not None:
                return
            self.sort_queue()
        # residual
        self.residual()
        if st.winner is not None:
            return
        for i in (0, 1):
            m = self.act(i)
            if m.alive:
                m.last_result = m.this_result
            for p in PROTECTS + ('endure', 'flinch', 'counter', 'mirrorcoat', 'focuspunch', 'beakblast', 'electrify',
                                 'helpinghand', 'sparklingaria'):
                m.vol.pop(p, None)
            if 'stall' in m.vol and not m.vol.pop('stall_used', None):
                del m.vol['stall']
            if 'lockedmove' in m.vol:
                lm = m.vol['lockedmove']
                lm['true'] -= 1
                lm['dur'] -= 1
                if m.status == 'slp':
                    del m.vol['lockedmove']
                elif lm['dur'] <= 0:
                    del m.vol['lockedmove']
                    if lm['true'] <= 1:
                        self.add_volatile(m, 'confusion', m, effect='lockedmove')
        # replacements for fainted actives (again if a replacement faints on entry)
        for _ in range(4):
            repl = []
            for i in (0, 1):
                if not self.act(i).alive:
                    j = self.choose_switch(i, forced=True)
                    if j is not None:
                        st.sides[i].act = j
                        nm = st.sides[i].own(j)
                        nm.newly = True
                        nm.active_turns = 0
                        repl.append(nm)
            if not repl:
                break
            self.run_switch(repl)
            if st.winner is not None:
                return
        self.end_turn()

    def end_turn(self):
        for i in (0, 1):
            m = self.act(i)
            if m.alive:
                m.active_turns += 1
                m.newly = False

    def sort_queue(self):
        q = self.queue
        if len(q) < 2:
            return
        keys = []
        for a in q:
            m, mid = a[1], a[2]
            pri = self.priority_of(m, mid)
            if len(a) < 5:
                frac = 0.0
                md = MOVES.get(mid)
                if self.it(m) == 'quickclaw' and pri <= 0 and self.rng.chance(0.2, 'quickclaw'):
                    frac = 0.1
                elif self.ab(m) == 'quickdraw' and md is not None and md.cat != 'status' and self.rng.chance(0.3, 'quickdraw'):
                    frac = 0.1
                elif self.ab(m) == 'stall':
                    frac = -0.1
                a.append(frac)
            keys.append((pri + a[4], self.action_speed(m)))
        if keys[0] == keys[1]:
            if self.rng.expected or getattr(self.rng, 'pessimistic_ties', False):
                if q[0][3] == 0:      # pessimistic tie: opponent first
                    q.reverse()
            elif self.rng.chance(0.5, 'tie', True):
                q.reverse()
            return
        if keys[1] > keys[0]:
            q.reverse()

    def after_action(self):
        """Forced switches (Roar/Dragon Tail/Red Card), self switches (U-turn/Eject Button/Emergency Exit)."""
        st = self.st
        for i in (0, 1):
            m = self.act(i)
            if m.force_switch:
                m.force_switch = False
                if m.alive and self.can_switch(i):
                    s = st.sides[i]
                    opts = [j for j, x in enumerate(s.mons) if x.alive and j != s.act]
                    j = self.rng.sample([(j, 1 / len(opts)) for j in opts], 'drag')
                    self.switch_in(i, j)
        self.faint_messages()
        for i in (0, 1):
            m = self.act(i)
            if m.switch_flag:
                flag = m.switch_flag
                m.switch_flag = False
                if self.can_switch(i) and m.alive:
                    j = self.choose_switch(i)
                    if j is not None:
                        self.switch_in(i, j, flag if isinstance(flag, str) else None)
        self.faint_messages()


def POKE_ATK(m):
    return dex.SPECIES[m.form.ja]['baseStats']['atk']


# ---------------------------------------------------------------- legal actions
def trapped(st, i):
    B = Battle(st)
    m = B.act(i)
    f = B.act(1 - i)
    if not m.alive:
        return False
    if B.it(m) == 'shedshell' or B.has_type(m, 'ghost') or B.ab(m) == 'runaway':
        return False
    if any(v in m.vol for v in ('trapped', 'noretreat', 'ingrain', 'octolock')):
        return True
    pt = m.vol.get('partiallytrapped')
    if pt:
        src = pt.get('src')
        if src is None or (st.sides[src[0]].act == src[1] and st.sides[src[0]].mons[src[1]].alive):
            return True
    if 'fairylock' in st.pseudo:
        return True
    if f.alive:
        fa = B.ab(f)
        if fa == 'shadowtag' and B.ab(m) != 'shadowtag':
            return True
        if fa == 'arenatrap' and B.grounded(m):
            return True
        if fa == 'magnetpull' and B.has_type(m, 'steel'):
            return True
    return False


def legal_moves(st, m):
    """Selectable moves for mon m (choice lock, encore, taunt, disable, torment, gravity, throat chop, ...)."""
    B = Battle(st)
    if 'mustrecharge' in m.vol:
        return ['recharge']
    lm = m.vol.get('lockedmove')
    if lm:
        return [lm['move']]
    tt = m.vol.get('twoturnmove')
    if tt:
        return [tt]
    if 'uproar' in m.vol:
        return ['uproar']
    mv = list(m.moves)
    out = []
    enc = m.vol.get('encore')
    cl = m.vol.get('choicelock')
    for x in mv:
        md = MOVES.get(x)
        if md is None:
            continue
        if enc and enc['move'] in mv and x != enc['move']:
            continue
        if cl and cl in mv and x != cl and B.it(m) and ITEMS.get(B.it(m), {}).get('name', '').startswith('Choice'):
            continue
        if 'taunt' in m.vol and md.cat == 'status':
            continue
        d = m.vol.get('disable')
        if d and d['move'] == x:
            continue
        if 'torment' in m.vol and m.last_move == x:
            continue
        if 'gravity' in st.pseudo and 'gravity' in md.flags:
            continue
        if 'throatchop' in m.vol and 'sound' in md.flags:
            continue
        if 'healblock' in m.vol and 'heal' in md.flags:
            continue
        if x in ('fakeout', 'firstimpression') and m.move_actions > 0:
            continue
        if m.pp is not None and m.pp.get(x, 1) <= 0:
            continue
        if 'cantusetwice' in md.flags and m.last_move == x:
            continue
        f = B.foe(m)
        if 'imprison' in f.vol and x in f.moves:
            continue
        out.append(x)
    return out or ['struggle']


def actions(st, i):
    """All legal actions for side i: ('m', move, mega) and ('s', j)."""
    s = st.sides[i]
    m = s.mons[s.act]
    acts = []
    if m.alive:
        mega = m.can_mega and not s.mega_used and m.mega_form is not None
        for x in legal_moves(st, m):
            acts.append(('m', x, mega))
    locked = m.alive and (any(k in m.vol for k in ('lockedmove', 'twoturnmove', 'mustrecharge', 'uproar')) or
                          trapped(st, i))
    if not locked or not m.alive:
        for j, b in enumerate(s.mons):
            if j != s.act and b.alive:
                acts.append(('s', j))
    return acts


def step(st, a0, a1, rng=EXPECTED, chooser=None, log=None):
    """Advance one turn. a0/a1: actions of side 0/1 (None if the side has nothing to do)."""
    st = st.clone()
    B = Battle(st, rng, chooser, log)
    B.run_turn(a0, a1)
    return st


def start(st, rng=EXPECTED, chooser=None, log=None):
    """Lead switch-in: both leads' abilities/items in speed order."""
    st = st.clone()
    B = Battle(st, rng, chooser, log)
    B.run_switch([B.act(0), B.act(1)])
    B.end_turn()
    return st


# ---------------------------------------------------------------- building mons from sets
def make_mon(species_ja, nature='まじめ', ap=None, ability='', item='', moves=(), side=0, idx=0):
    """species/ability/item/moves in Japanese (or showdown ids). ap: {'hp','atk','def','spa','spd','spe'} 0..32.
    If the item is this species' mega stone, the mega form is attached (mega evolves when choosing ('m', x, True))."""
    ap = {('def' if k == 'defn' else k): v for k, v in (ap or {}).items()}
    if species_ja not in dex.SPECIES:
        raise KeyError(species_ja)
    ab = dex.ab_id(ability)
    s = dex.SPECIES[species_ja]
    if not ab:
        ab = dex.ab_id(s['abilities'].get('0', '').lower().replace(' ', '')) or \
            ''.join(c for c in s['abilities'].get('0', '').lower() if c.isalnum())
    it = dex.item_id(item)
    base = Form(species_ja, nature, ap, ab)
    mega = None
    if it in dex.MEGA_STONE:
        mj = dex.MEGA_STONE[it].get(species_ja)
        if mj and mj in dex.SPECIES:
            ms = dex.SPECIES[mj]
            mab = ''.join(c for c in ms['abilities'].get('0', '').lower() if c.isalnum())
            mega = Form(mj, nature, ap, mab)
    if s.get('isMega'):
        # already a mega species given: treat as mega-evolved base
        pass
    mv = tuple(dex.move_id(x) for x in moves if dex.move_id(x))
    m = Mon(base, mv, it, mega, side, idx)
    m.nature, m.ap = nature, ap
    return m
