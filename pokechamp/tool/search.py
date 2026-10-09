"""Turn search on top of engine.py (the Showdown-faithful Champions simulator).

  decide(st, seconds)  -> (depth, [(value, action), ...])  best first

How the look-ahead works
  * Turn 1 (the decision turn): every legal action of ours against the opponent's most promising replies;
    each pair is expanded into its significant random outcomes (damage roll KO/not KO, accuracy, crit,
    full paralysis, secondary effects, sleep/freeze turns, ...) with engine.enumerate_step, weighted by
    probability.
  * Turns 2..D: pruned simultaneous-move tree (our best 3/2 actions x their best 2 replies) simulated with the
    most likely outcome; damage is scaled by accuracy / paralysis so the expectation is kept.
  * Turns D+1..8: greedy roll-out (both sides play their best heuristic action), then the static evaluation.
  * Iterative deepening D = 1, 2, ... ; the root actions are spread over CPU cores. D = 5 is reached in
    normal positions within the default 10 s; deeper if time remains. The answer of the deepest depth
    finished for every root action is returned.
  * Opponent model: value = 0.6 * worst reply + 0.4 * average reply (cautious but not paranoid).
"""
import math, os, sys, time
import engine as E
import dex

HORIZON = 8          # turns looked ahead (tree + roll-out)
MIN_DEPTH = 5        # tree depth the time budget is planned for
PESS = 0.6

_HAZ = ('stealthrock', 'spikes', 'toxicspikes', 'stickyweb')
_SCREENS = ('reflect', 'lightscreen', 'auroraveil')
_HEAL_MOVES = {'recover', 'slackoff', 'softboiled', 'milkdrink', 'roost', 'healorder', 'shoreup', 'synthesis',
               'morningsun', 'moonlight', 'rest', 'strengthsap', 'wish', 'lifedew', 'junglehealing'}


# ---------------------------------------------------------------- heuristics
_EC = {}
_VOLK = ('substitute', 'flashfire', 'charge', 'protosynthesis', 'quarkdrive', 'unburden', 'glaiverush', 'tarshot',
         'smackdown', 'magnetrise', 'roost', 'transformed', 'telekinesis')


def _mkey(m):
    v = m.vol
    return (m.form.ja, m.ability, m.item, m.status, m.hp, tuple(m.boosts.values()), m.types, m.added_type,
            m.busted, tuple((k, str(v[k])) for k in _VOLK if k in v))


def _fkey(st, side):
    c = st.sides[side].cond
    return (st.weather, st.terrain, tuple(sorted(st.pseudo)), c.get('reflect'), c.get('lightscreen'),
            c.get('auroraveil'), st.sides[1 - side].cond.get('tailwind'), c.get('tailwind'))


def est(st, i, mid, target=None):
    """Cached engine.estimate."""
    a = st.sides[i].mons[st.sides[i].act]
    t = target if target is not None else st.sides[1 - i].mons[st.sides[1 - i].act]
    k = (mid, _mkey(a), _mkey(t), _fkey(st, 1 - i))
    r = _EC.get(k)
    if r is None:
        if len(_EC) > 300000:
            _EC.clear()
        r = _EC[k] = E.estimate(st, i, mid, target)
    return r


def speed_of(st, i):
    m = st.sides[i].mons[st.sides[i].act]
    k = ('spe', _mkey(m), _fkey(st, i))
    r = _EC.get(k)
    if r is None:
        r = _EC[k] = E.action_speed_of(st, i)
    return r

def _foe(st, i):
    s = st.sides[1 - i]
    return s.mons[s.act]


def _me(st, i):
    s = st.sides[i]
    return s.mons[s.act]


def best_damage(st, i, target=None, attacker_slot=None):
    """Best expected damage fraction (of target's current HP) side i can deal this turn."""
    if attacker_slot is not None and attacker_slot != st.sides[i].act:
        st = _swap_view(st, i, attacker_slot)
    m = _me(st, i)
    best = 0.0
    for x in m.moves:
        if x in E.MOVES:
            best = max(best, est(st, i, x, target))
    return best


def _swap_view(st, i, j):
    """Shallow view of the state with bench mon j of side i as the active one (for estimates only)."""
    n = st.clone()
    n.sides[i].act = j
    n.sides[i].owned.discard(j)
    return n


def faster(st, i):
    """1 if side i's active acts first in a plain move-vs-move exchange, 0 if slower, .5 on ties."""
    a, b = speed_of(st, i), speed_of(st, 1 - i)
    return 1.0 if a > b else 0.0 if a < b else 0.5


def switch_score(st, i, j):
    """How good it is for side i to bring in bench mon j against the current foe."""
    s = st.sides[i]
    m = s.mons[j]
    foe = _foe(st, i)
    if not foe.alive:
        return m.hp / m.maxhp
    take = 0.0
    for x in foe.moves:
        if x in E.MOVES:
            take = max(take, est(st, 1 - i, x, target=m) * m.hp / max(1, m.maxhp))
    give = best_damage(st, i, attacker_slot=j)
    haz = 0.0
    c = s.cond
    if c.get('stealthrock'):
        haz += 0.12
    haz += 0.06 * c.get('spikes', 0)
    return 0.7 * min(give, 1.2) - 0.8 * min(take, 1.0) - haz + 0.25 * m.hp / m.maxhp


def chooser(st, side, opts):
    """Replacement after a faint / U-turn: the best matchup against the foe's active."""
    return max(opts, key=lambda j: switch_score(st, side, j))


def action_scores(st, i, acts=None):
    """Heuristic score of every legal action of side i (higher is better)."""
    if acts is None:
        acts = E.actions(st, i)
    me, foe = _me(st, i), _foe(st, i)
    if not me.alive:
        return [(switch_score(st, i, a[1]), a) for a in acts]
    fast = faster(st, i)
    out = []
    hp = me.hp / me.maxhp
    foe_threat = best_damage(st, 1 - i)
    for a in acts:
        if a[0] == 's':
            out.append((switch_score(st, i, a[1]) - 0.15 + (0.3 if foe_threat >= 1 and not fast else 0), a))
            continue
        mid = a[1]
        md = E.MOVES.get(mid)
        if md is None:
            out.append((0.0, a))
            continue
        if md.cat != 'status':
            d = est(st, i, mid)
            pri = md.pri > 0
            if d >= 1:
                s = 1.5 + (0.4 if (fast >= 1 or pri) else 0)
            else:
                s = d
                if foe_threat >= 1 and not fast and not pri:
                    s *= 0.5          # we probably faint before moving
            if md.self_switch and d < 1:
                s += 0.15
            if md.recoil:
                s -= 0.05
            out.append((s, a))
            continue
        s = 0.1
        if md.boosts and md.target == 'self' or md.self_boost:
            up = sum(v for v in (md.boosts or {}).values() if v > 0)
            cur = sum(max(0, v) for v in me.boosts.values())
            s = 0.45 if hp > 0.6 and cur < 4 and foe_threat < 0.6 else 0.05
            s += 0.05 * up
        elif md.status:
            s = -1 if foe.status or 'substitute' in foe.vol else 0.45
        elif md.side in _HAZ and md.target == 'foeSide':
            c = st.sides[1 - i].cond
            s = 0.4 if not c.get(md.side) or md.side in ('spikes', 'toxicspikes') and c.get(md.side, 0) < 2 else -1
        elif md.side in _SCREENS:
            s = -1 if st.sides[i].cond.get(md.side) else 0.35
        elif md.stalling:
            s = -0.5 if 'stall' in me.vol else 0.2
        elif md.heal or mid in _HEAL_MOVES:
            s = 0.9 * (1 - hp) - 0.15
        elif md.weather:
            s = -1 if st.weather == md.weather else 0.25
        elif md.terrain:
            s = -1 if st.terrain == md.terrain else 0.25
        elif mid == 'trickroom':
            s = 0.4 if not st.pseudo.get('trickroom') and not fast else -0.6
        elif md.volatile == 'substitute':
            s = 0.3 if 'substitute' not in me.vol and hp > 0.5 else -1
        elif md.volatile in ('taunt', 'encore', 'yawn', 'leechseed', 'destinybond', 'confusion', 'attract'):
            s = 0.3 if md.volatile not in foe.vol else -1
            if md.volatile == 'destinybond':
                s = 0.6 if hp < 0.35 and st.lastmove != 'destinybond' else -0.5
        elif md.force_switch:
            s = 0.15 + 0.1 * sum(max(0, v) for v in foe.boosts.values())
        out.append((s, a))
    return out


def prune(st, i, k):
    sc = action_scores(st, i)
    sc.sort(key=lambda x: -x[0])
    return [a for _, a in sc[:k]]


# ---------------------------------------------------------------- evaluation
def _mon_value(st, i, m, active):
    if not m.alive:
        return 0.0
    f = m.hp / m.maxhp
    v = 1.0 + 1.2 * f
    if active:
        b = m.boosts
        phys = m.stat('atk') >= m.stat('spa')
        off = b['atk'] if phys else b['spa']
        v += 0.09 * max(off, 0) - 0.06 * max(-off, 0)
        v += 0.05 * max(b['spe'], 0) - 0.03 * max(-b['spe'], 0)
        v += 0.03 * (b['def'] + b['spd'])
        if 'substitute' in m.vol:
            v += 0.4 * m.vol['substitute'] / m.maxhp
    st_ = m.status
    if st_:
        a = m.ability
        pen = {'brn': 0.15 if m.stat('atk') > m.stat('spa') else 0.05, 'par': 0.12, 'slp': 0.12 + 0.04 * m.stime,
               'frz': 0.25, 'psn': 0.08, 'tox': 0.15}.get(st_, 0)
        if st_ in ('psn', 'tox') and a == 'poisonheal' or a in ('guts', 'quickfeet', 'marvelscale'):
            pen = -0.05
        v -= pen
    it = m.item
    if it == 'focussash' and f >= 1:
        v += 0.05
    elif it in ('leftovers', 'blacksludge', 'sitrusberry'):
        v += 0.03
    if m.ability == 'disguise' and not m.busted:
        v += 0.08
    if m.can_mega and not st.sides[i].mega_used:
        v += 0.05
    return v


def side_value(st, i):
    s = st.sides[i]
    v = 0.0
    alive = 0
    for j, m in enumerate(s.mons):
        if m.alive:
            alive += 1
            v += _mon_value(st, i, m, j == s.act)
    c = s.cond
    bench = max(0, alive - 1)
    if c.get('stealthrock'):
        v -= 0.1 * bench
    v -= 0.05 * c.get('spikes', 0) * bench + 0.05 * c.get('toxicspikes', 0) * bench
    if c.get('stickyweb'):
        v -= 0.04 * bench
    for k in _SCREENS:
        if c.get(k):
            v += 0.03 * c[k]
    if c.get('tailwind'):
        v += 0.05 * c['tailwind']
    return v


def evaluate(st):
    if st.winner is not None:
        base = 100.0 * st.winner        # engine: 1 = we won, -1 = they won, 0 = draw
        return base + side_value(st, 0) - side_value(st, 1)
    v = side_value(st, 0) - side_value(st, 1)
    a, b = _me(st, 0), _me(st, 1)
    if a.alive and b.alive:
        give, take = min(best_damage(st, 0), 1.2), min(best_damage(st, 1), 1.2)
        fs = faster(st, 0)
        edge = give - take
        if give >= 1 and fs >= 1:
            edge += 0.6
        if take >= 1 and fs <= 0:
            edge -= 0.6
        v += 0.3 * math.tanh(1.5 * edge)
    return v


# ---------------------------------------------------------------- tree search
class _Timeout(Exception):
    pass


def _widths(ply):
    """(our width, their width) at tree ply (0 = the decision turn, handled separately)."""
    return (3, 2) if ply == 1 else (2, 2)


def rollout(st, turns):
    for _ in range(turns):
        if st.winner is not None:
            break
        a0 = _top(st, 0)
        a1 = _top(st, 1)
        st = E.step(st, a0, a1, chooser=chooser)
    return st


def _top(st, i):
    """Roll-out policy: strongest attack (KO first), status/setup by the heuristic; switches only when the
    active mon has nothing useful."""
    acts = E.actions(st, i)
    if not acts:
        return None
    if len(acts) == 1:
        return acts[0]
    moves = [a for a in acts if a[0] == 'm']
    if moves:
        sc = action_scores(st, i, moves)
        s, a = max(sc, key=lambda x: x[0])
        if s > 0.12:
            return a
    return prune(st, i, 1)[0]


class Searcher:
    def __init__(self, deadline):
        self.deadline = deadline
        self.nodes = 0

    def value(self, st, depth, ply):
        """Value of a position after `ply` turns, searching `depth` more tree turns then rolling out."""
        self.nodes += 1
        if st.winner is not None:
            return evaluate(st) + 0.3 * st.winner * (HORIZON - ply)   # sooner wins / later losses first
        if depth <= 0:
            return evaluate(rollout(st, max(0, HORIZON - ply)))
        if time.time() > self.deadline:
            raise _Timeout
        k0, k1 = _widths(ply)
        my = prune(st, 0, k0) if E.actions(st, 0) else [None]
        op = prune(st, 1, k1) if E.actions(st, 1) else [None]
        best = -1e9
        for a in my:
            vals = [self.value(E.step(st, a, b, chooser=chooser), depth - 1, ply + 1) for b in op]
            v = PESS * min(vals) + (1 - PESS) * sum(vals) / len(vals)
            best = max(best, v)
        return best

    def root_action(self, st, a, replies, depth):
        """Value of our root action `a`: chance-expanded turn 1, then the tree."""
        vals = []
        for b in replies:
            tot = 0.0
            for p, s2 in E.enumerate_step(st, a, b, chooser=chooser, max_leaves=6, thresh=0.1):
                tot += p * self.value(s2, depth - 1, 1)
            vals.append(tot)
        return PESS * min(vals) + (1 - PESS) * sum(vals) / len(vals)


def _root_replies(st, k=4):
    acts = E.actions(st, 1)
    if not acts:
        return [None]
    return prune(st, 1, k)


def _work(args):
    """Worker: chance-expanded value of one (our action, their reply) pair at a fixed tree depth
    (None if the deadline passed)."""
    st, a, b, deadline, depth = args
    s = Searcher(deadline)
    try:
        tot = 0.0
        for p, s2 in E.enumerate_step(st, a, b, chooser=chooser, max_leaves=6, thresh=0.1):
            tot += p * s.value(s2, depth - 1, 1)
        return tot, s.nodes
    except _Timeout:
        return None, s.nodes


def _depth_plan(max_depth):
    """Depths actually searched: a quick depth-1 answer, then MIN_DEPTH - 2, MIN_DEPTH, and deeper."""
    plan = [1, max(2, MIN_DEPTH - 2), MIN_DEPTH] + list(range(MIN_DEPTH + 1, max_depth + 1))
    return [d for k, d in enumerate(plan) if d <= max_depth and d not in plan[:k]]


def decide(st, seconds=10.0, procs=None, max_depth=HORIZON):
    """Best action for side 0 with iterative deepening. Returns (depth, [(value, action)] best first, nodes)."""
    t0 = time.time()
    deadline = t0 + max(0.5, seconds - 0.3)
    acts = E.actions(st, 0)
    if not acts:
        return 0, [(0.0, None)], 0
    if len(acts) == 1:
        return 0, [(0.0, acts[0])], 0
    replies = _root_replies(st)
    pairs = [(a, b) for a in acts for b in replies]
    procs = min(procs or os.cpu_count() or 1, len(pairs))
    pool = None
    if procs > 1:
        try:
            import multiprocessing as mp
            ctx = mp.get_context('fork') if hasattr(os, 'fork') else mp.get_context('spawn')
            pool = ctx.Pool(procs)
        except Exception:
            pool = None
    best, nodes, last_t, last_d = None, 0, 0.0, 0
    try:
        for d in _depth_plan(max_depth):
            left = deadline - time.time()
            growth = 3.3 ** (d - last_d)
            if best is not None and d > MIN_DEPTH and last_t * growth > left:
                break   # the next depth cannot finish in time
            ts = time.time()
            jobs = [(st, a, b, deadline, d) for a, b in pairs]
            res = pool.map(_work, jobs, chunksize=1) if pool else [_work(j) for j in jobs]
            nodes += sum(n for _, n in res)
            if any(v is None for v, _ in res):
                break
            by = {}
            for (a, _), (v, _) in zip(pairs, res):
                by.setdefault(a, []).append(v)
            vals = [(PESS * min(v) + (1 - PESS) * sum(v) / len(v), a) for a, v in by.items()]
            best = (d, sorted(vals, key=lambda x: -x[0]))
            last_t, last_d = time.time() - ts, d
            if os.environ.get("SEARCH_DEBUG"):
                print("depth", d, round(last_t, 2), "s", file=sys.stderr)
    finally:
        if pool:
            pool.terminate()
    if best:
        return best[0], best[1], nodes
    sc = sorted(action_scores(st, 0), key=lambda x: -x[0])
    return 0, [(s, a) for s, a in sc], nodes


# ---------------------------------------------------------------- state import (battle.py's state.json)
_WEATHER = {'sun': 'sunnyday', 'rain': 'raindance', 'sand': 'sandstorm', 'snow': 'snowscape', 'hail': 'snowscape',
            'はれ': 'sunnyday', 'あめ': 'raindance', 'すなあらし': 'sandstorm', 'ゆき': 'snowscape'}
_TERRAIN = {'grassy': 'grassyterrain', 'electric': 'electricterrain', 'psychic': 'psychicterrain',
            'misty': 'mistyterrain', 'グラスフィールド': 'grassyterrain', 'エレキフィールド': 'electricterrain',
            'サイコフィールド': 'psychicterrain', 'ミストフィールド': 'mistyterrain'}
_COND_KEYS = ('stealthrock', 'spikes', 'toxicspikes', 'stickyweb', 'reflect', 'lightscreen', 'auroraveil',
              'tailwind', 'safeguard', 'mist')


def _emon(bm, side, idx, exact_hp):
    """battle.BM (set chosen by sets/infer + observed state) -> engine.Mon."""
    base, mega = bm.base, bm.mega
    item = (mega.item if mega is not None else base.item) or ''
    m = E.make_mon(base.species, base.nature, base.spv, base.ability, item, bm.moves, side, idx)
    is_mega = mega is not None and bm.cur is mega
    if is_mega and m.mega_form is not None:
        m.form = m.mega_form
        m.ability = m.mega_form.ability
        m.can_mega = False
    elif not bm.can_mega:
        m.can_mega = False
    if bm.item is None and not is_mega:
        m.last_item, m.item = m.item, ''
    if exact_hp and bm.maxhp == m.maxhp:
        m.hp = max(0, min(m.maxhp, bm.hp))
    else:
        m.hp = max(0, min(m.maxhp, round(m.maxhp * bm.hp / max(1, bm.maxhp))))
    if m.hp <= 0:
        m.hp, m.fainted = 0, True
    st_ = bm.status
    if st_:
        m.status = st_
        if st_ == 'slp':
            m.stime = bm.sleep or 2
        if st_ == 'frz':
            m.stime = 3
        if st_ == 'tox':
            m.tox = bm.toxn or 0
    for k, v in bm.boosts.items():
        m.boosts['def' if k == 'defn' else k] = v
    if not bm.disguise and m.ability == 'disguise':
        m.busted = 'done'
    return m


def from_battle(bst, js=None):
    """battle.State (BM based) + the raw state.json -> engine.State, ready for decide()."""
    js = js or {}
    sides = []
    for i in (0, 1):
        sides.append([_emon(bm, i, j, i == 0) for j, bm in enumerate(bst.sides[i])])
    st = E.new_state(sides[0], sides[1])
    for i in (0, 1):
        s = st.sides[i]
        s.act = bst.act[i]
        s.mega_used = bool(bst.mega_used[i])
        if s.mega_used:
            for m in s.mons:
                m.can_mega = False
        if bst.rocks[i]:
            s.cond['stealthrock'] = True
        extra = js.get('cond_me' if i == 0 else 'cond_opp') or {}
        for k, v in extra.items():
            if k in _COND_KEYS and v:
                s.cond[k] = v if k in ('spikes', 'toxicspikes', 'reflect', 'lightscreen', 'auroraveil', 'tailwind',
                                       'safeguard', 'mist') and v is not True else \
                    (5 if k in ('reflect', 'lightscreen', 'auroraveil', 'safeguard', 'mist') else
                     4 if k == 'tailwind' else 1 if k in ('spikes', 'toxicspikes') else True)
        # the active mon's battle state
        bm = bst.sides[i][bst.act[i]]
        m = s.mons[s.act]
        if bm.lock and E.ITEMS.get(m.item, {}).get('name', '').startswith('Choice'):
            mid = dex.move_id(bm.lock)
            if mid:
                m.vol['choicelock'] = mid
                m.last_move = mid
        if bm.rampage:
            mid = dex.move_id(bm.rampage[0])
            if mid:
                m.vol['lockedmove'] = {'move': mid, 'dur': 1, 'true': 1}
        if bm.sub:
            m.vol['substitute'] = bm.sub
        if bm.glaive:
            m.vol['glaiverush'] = True
        if bm.encore:
            mid = dex.move_id(bm.encore[0])
            if mid:
                m.vol['encore'] = {'move': mid, 'dur': bm.encore[1]}
        if bm.taunt:
            m.vol['taunt'] = bm.taunt
        if bm.yawn:
            m.vol['yawn'] = bm.yawn
        d = (js.get('me' if i == 0 else 'opp') or [{}] * 6)
        d = d[bst.act[i]] if bst.act[i] < len(d) else {}
        lm = d.get('last_move')
        if lm and dex.move_id(lm):
            m.last_move = dex.move_id(lm)
        for k in ('confusion', 'leechseed', 'perishsong', 'curse', 'saltcure', 'healblock', 'torment'):
            if d.get(k):
                m.vol[k] = d[k] if not isinstance(d[k], bool) else (3 if k in ('confusion', 'perishsong') else True)
    w = bst.weather
    if w:
        st.weather = _WEATHER.get(w, w)
        st.wturns = bst.wt or 5
    t = bst.terrain
    if t:
        st.terrain = _TERRAIN.get(t, t)
        st.tturns = bst.tt or 5
    if bst.tr:
        st.pseudo['trickroom'] = bst.tr
    for k, v in (js.get('pseudo') or {}).items():
        st.pseudo[k] = v
    st.turn = bst.turn or 1
    if bst.last[1]:
        st.lastmove = dex.move_id(bst.last[1])
    return st


def fmt(st, a):
    """Japanese text for our action."""
    if a is None:
        return '待機'
    if a[0] == 's':
        return f"{st.sides[0].mons[a[1]].name}に交代"
    md = E.MOVES.get(a[1])
    name = md.ja if md else a[1]
    return ('メガシンカ＋' if len(a) > 2 and a[2] else '') + name


# ---------------------------------------------------------------- whole-game play-outs (team selection)
def smart_action(st, i=0, roll=2):
    """1-turn look-ahead for side i against the opponent's heuristic reply, plus a short roll-out."""
    acts = E.actions(st, i)
    if len(acts) <= 1:
        return acts[0] if acts else None
    opp = _top(st, 1 - i)
    best, bv = None, -1e9
    for a in prune(st, i, 4):
        pair = (a, opp) if i == 0 else (opp, a)
        v = evaluate(rollout(E.step(st, pair[0], pair[1], chooser=chooser), roll))
        v = v if i == 0 else -v
        if v > bv:
            best, bv = a, v
    return best


def play(st, max_turns=20, smart=False):
    """Play the game out (our side greedy or 1-turn look-ahead, theirs greedy); returns the final evaluation."""
    for _ in range(max_turns):
        if st.winner is not None:
            break
        a0 = smart_action(st, 0) if smart else _top(st, 0)
        a1 = _top(st, 1)
        st = E.step(st, a0, a1, chooser=chooser)
    return evaluate(st)
