"""Selection and action rules for the R9 party (spec: pokechamp/specs/SPEC_CORES.md).

  select_filter(opp6, relax)   S1-S3: which of our orders may be brought
  ranked_root(bst, depth)      S.lookahead_action's root, but every action with its value (best first)
  choose(st, bst, ranked, ctx) our real move for this turn: the search's first choice, overridden by rules
  make_chooser(ctx)            our replacement after a faint / U-turn (G1r, Z1, R1b), theirs stays S.chooser

The rules never look at the opponent's true sets: they use bst (battle.belief) and what is visible.
Only our own real move (the root) and our own switch-ins are changed; the search tree and the opponent
are untouched.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle  # noqa: E402
import engine as E  # noqa: E402
import search as S  # noqa: E402

POLICY_VERSION = 1
RISK = 0.85
ALL_RULES = ('K', 'R1', 'R1b', 'T1', 'D1', 'G1', 'G1r', 'M1', 'M2', 'Z1', 'Z2', 'X1', 'S9')
ROCKERS = ('カバルドン', 'エンペルト')
HEALS = ('recover', 'slackoff')


# ---------------------------------------------------------------- selection (S1-S3)

def select_filter(opp6, relax=()):
    ashi = 'アシレーヌ' in {battle._base(x) for x in opp6}

    def ok(order):
        s = set(order)
        rk = len(s & {'カバルドン', 'エンペルト'})
        if 'S1' not in relax and rk > 1:
            return False
        if 'S2' not in relax and rk < 1:
            return False
        if 'S3' not in relax and ashi and 'ドヒドイデ' not in s:
            return False
        return True
    return ok


def relaxed_filter(opp6, orders):
    """(filter, relaxed): the strictest filter that at least one of `orders` satisfies, dropping S3, then S1,
    then S2 one at a time (cumulative) when none does."""
    relax = []
    for r in (None, 'S3', 'S1', 'S2'):
        if r:
            relax.append(r)
        f = select_filter(opp6, tuple(relax))
        if any(f(o) for o in orders):
            return f, relax
    return select_filter(opp6, ('S1', 'S2', 'S3')), ['S3', 'S1', 'S2']


# ---------------------------------------------------------------- helpers

def base(m):
    return battle._base(m.name)


def is_mega(m):
    return m.mega_form is not None and m.form is m.mega_form


def find(acts, mid):
    for a in acts:
        if a[0] == 'm' and a[1] == mid:
            return a
    return None


def danger(bst):
    return S.best_damage(bst, 1)


def _pri(bst, m, mid):
    try:
        return E.Battle(bst).priority_of(m, mid)
    except Exception:
        md = E.MOVES.get(mid)
        return md.pri if md else 0


def ko_now(bst, a):
    if a is None or a[0] != 'm':
        return False
    md = E.MOVES.get(a[1])
    if md is None or md.cat == 'status':
        return False
    if S.est(bst, 0, a[1]) < 1.0:
        return False
    return S.faster(bst, 0) == 1.0 or _pri(bst, S._me(bst, 0), a[1]) > 0


def can_poison(bst, f):
    if not f.alive or f.status != '' or 'substitute' in f.vol:
        return False
    B = E.Battle(bst)
    types = set(B.types(f))
    if f.can_mega and f.mega_form is not None and not bst.sides[1].mega_used:
        types |= set(f.mega_form.types)
    if 'poison' in types or 'steel' in types:
        return False
    ab = B.ab(f)
    if ab in ('immunity', 'purifyingsalt', 'comatose', 'goodasgold', 'magicbounce', 'pastelveil', 'poisonheal'):
        return False
    if ab == 'leafguard' and bst.weather in ('sunnyday', 'desolateland'):
        return False
    if bst.sides[1].cond.get('safeguard'):
        return False
    if bst.terrain == 'mistyterrain' and B.grounded(f):
        return False
    return True


def rocks_useful(bst):
    s = bst.sides[1]
    return not s.cond.get('stealthrock') and any(m.alive for j, m in enumerate(s.mons) if j != s.act)


def _bench(st, i):
    s = st.sides[i]
    return [j for j, m in enumerate(s.mons) if j != s.act and m.alive]


def aname(st, a):
    if a is None:
        return '-'
    if a[0] == 's':
        return '→' + st.sides[0].mons[a[1]].name
    md = E.MOVES.get(a[1])
    return md.ja if md else a[1]


class Ctx:
    def __init__(self, opp6, rules=None):
        self.opp6 = [battle._base(x) for x in opp6]
        self.ashi = 'アシレーヌ' in self.opp6
        self.rules = set(ALL_RULES if rules is None else rules)
        self.turn = 0
        self.prev_move = None
        self.fired = []
        self.placed = 0            # times their side got stealth rock (counted as absent -> present)
        self.rocks_prev = False
        self.r1_fails = 0

    def on(self, rid):
        return rid in self.rules

    def fire(self, rid, orig, new):
        self.fired.append((self.turn, rid, orig, new))


# ---------------------------------------------------------------- search with every root action

def ranked_root(bst, depth, k_self=3, k_opp=2):
    """[(value, action), ...] best first; [0] is exactly S.lookahead_action(bst, 0, depth)."""
    i = 0
    acts = E.actions(bst, i)
    if len(acts) <= 1:
        return [(0.0, acts[0] if acts else None)]
    sign = 1
    j = 1

    def val(s, d):
        if s.winner is not None or d == 0:
            v = sign * S.evaluate(s)
            if s.winner is not None:
                v += 0.3 * sign * s.winner * d
            return v
        mine = S.prune(s, i, k_self) if E.actions(s, i) else [None]
        theirs = S.prune(s, j, k_opp) if E.actions(s, j) else [None]
        best = -1e9
        for a in mine:
            vs = [val(E.step(s, a, b, chooser=S.chooser), d - 1) for b in theirs]
            best = max(best, S.PESS * min(vs) + (1 - S.PESS) * sum(vs) / len(vs))
        return best

    theirs = S.prune(bst, j, k_opp + 1) if E.actions(bst, j) else [None]
    out = []
    for n, a in enumerate(acts):
        vs = [val(E.step(bst, a, b, chooser=S.chooser), depth - 1) for b in theirs]
        v = S.PESS * min(vs) + (1 - S.PESS) * sum(vs) / len(vs) + S.front_bias(bst, a)
        out.append((v, n, a))
    out.sort(key=lambda x: (-x[0], x[1]))      # ties: the earlier action, as lookahead_action's strict '>'
    return [(v, a) for v, _, a in out]


# ---------------------------------------------------------------- the action rules

def _forbidden(st, bst, ranked, ctx, me, foe, acts):
    """{action: rule id} of forbidden root actions."""
    ban = {}
    a0 = ranked[0][1]
    hpr = me.hp / max(1, me.maxhp)
    b = base(me)
    if ctx.on('X1'):
        for _, a in ranked:
            if a is not None and a[0] == 's':
                t = bst.sides[0].mons[a[1]]
                if t.item == 'focussash' and t.hp >= t.maxhp:
                    continue
                if S.best_damage(bst, 1, target=t) >= 1.0:
                    ban[a] = 'X1'
    if ctx.on('G1') and base(foe) == 'グソクムシャ' and foe.boosts['atk'] >= 2 and b == 'ドヒドイデ':
        for a in acts:
            if a[0] == 'm' and a[1] == 'recover':
                ban.setdefault(a, 'G1')
    if ctx.on('M2') and base(foe) == 'ミミッキュ' and foe.boosts['atk'] >= 2 and b in ROCKERS:
        for a in acts:
            if a[0] == 'm' and a[1] in ('stealthrock', 'yawn', 'slackoff'):
                ban.setdefault(a, 'M2')
    if ctx.on('D1') and b in ('ドヒドイデ', 'カバルドン') and hpr > 0.6:
        for a in acts:
            if a[0] == 'm' and a[1] in HEALS:
                ban.setdefault(a, 'D1')
    return ban


def _useless_status(bst, me, foe, hpr):
    """True if every status move of ours is pointless now (spec S9)."""
    for x in me.moves:
        md = E.MOVES.get(x)
        if md is None or md.cat != 'status':
            continue
        if x == 'stealthrock':
            if rocks_useful(bst):
                return False
        elif x == 'toxic':
            if can_poison(bst, foe):
                return False
        elif x == 'yawn':
            if foe.status == '' and 'yawn' not in foe.vol and 'substitute' not in foe.vol:
                return False
        elif x in HEALS:
            if hpr <= 0.6:
                return False
    return True


def choose(st, bst, ranked, ctx):
    """(action, rule id or None). st: true state (our legal moves); bst: our belief about theirs."""
    a0 = ranked[0][1]
    ctx.turn += 1
    me, foe = S._me(bst, 0), S._foe(bst, 0)
    rocks_now = bool(bst.sides[1].cond.get('stealthrock'))
    if rocks_now and not ctx.rocks_prev:
        ctx.placed += 1
        ctx.r1_fails = 0
    ctx.rocks_prev = rocks_now
    acts = E.actions(st, 0)
    if a0 is None or len(acts) <= 1 or a0[1:2] == ('recharge',) or \
            any(k in me.vol for k in ('lockedmove', 'twoturnmove', 'mustrecharge', 'uproar')):
        return a0, None
    assert a0 in acts, (a0, acts)
    if ctx.on('K') and ko_now(bst, a0):
        return a0, 'K'
    ban = _forbidden(st, bst, ranked, ctx, me, foe, acts)
    b = base(me)
    hpr = me.hp / max(1, me.maxhp)
    foe_ok = foe.alive

    def pick(a, rid):
        if a is None or a in ban or a not in acts:
            return None
        return a, rid

    sel = None
    if ctx.on('T1') and b == 'ドヒドイデ' and foe_ok:
        a = find(acts, 'toxic')
        if a and can_poison(bst, foe):
            sel = pick(a, 'T1')
    if sel is None and ctx.on('M1') and b in ROCKERS and base(foe) == 'ミミッキュ' and \
            foe.ability == 'disguise' and foe.busted is False:
        if b == 'カバルドン':
            a = find(acts, 'earthquake')
        else:
            a = find(acts, 'flipturn') if _bench(st, 0) else find(acts, 'surf')
        sel = pick(a, 'M1')
    if sel is None and ctx.on('R1') and b in ROCKERS and foe_ok and rocks_useful(bst) and ctx.placed < 2 and \
            ctx.r1_fails < 3 and danger(bst) < RISK and foe.ability != 'magicbounce':
        a = find(acts, 'stealthrock')
        sel = pick(a, 'R1')
        if sel:
            ctx.r1_fails += 1
    if sel is None and ctx.on('Z2') and b == 'マスカーニャ' and base(foe) == 'ガブリアス' and foe_ok:
        sel = pick(find(acts, 'tripleaxel'), 'Z2')
    if sel is None and ctx.on('S9') and foe_ok and S.best_damage(bst, 0) < 0.10 and \
            _useless_status(bst, me, foe, hpr):
        best, bd = None, 0.30
        for j in _bench(st, 0):
            a = ('s', j)
            if a in ban or a not in acts:
                continue
            d = S.best_damage(bst, 0, attacker_slot=j)
            if d >= bd:
                best, bd = a, d
        if best is not None:
            # X1 for this switch even if X1 was not evaluated on the ranked list
            t = bst.sides[0].mons[best[1]]
            if not (ctx.on('X1') and S.best_damage(bst, 1, target=t) >= 1.0 and
                    not (t.item == 'focussash' and t.hp >= t.maxhp)):
                sel = (best, 'S9')
    if sel is not None:
        a, rid = sel
        ctx.fire(rid, aname(st, a0), aname(st, a))
        return a, rid
    for _, a in ranked:
        if a is not None and a not in ban and a in acts:
            if a != a0:
                ctx.fire(ban[a0], aname(st, a0), aname(st, a))
            return a, ban.get(a0) if a != a0 else None
    return a0, None


# ---------------------------------------------------------------- our replacement after a faint / U-turn

def make_chooser(ctx):
    def chooser(st, side, opts):
        if side != 0 or not opts:
            return S.chooser(st, side, opts)
        foe = st.sides[1].mons[st.sides[1].act]
        mons = st.sides[0].mons
        # G1r
        if ctx.on('G1r') and foe.alive and base(foe) == 'グソクムシャ' and foe.boosts['atk'] >= 1:
            for j in opts:
                m = mons[j]
                if base(m) == 'グレンアルマ' and m.hp >= m.maxhp and m.item:
                    ctx.fire('G1r', '-', m.name)
                    return j
        # Z1
        if ctx.on('Z1') and foe.alive and is_mega(foe) and foe.form.ja.startswith('メガガブリアス') and \
                foe.form.ja.endswith(('Z', 'Ｚ')):
            for j in opts:
                if base(mons[j]) == 'マスカーニャ':
                    ctx.fire('Z1', '-', mons[j].name)
                    return j
        # R1b
        if ctx.on('R1b') and not st.sides[1].cond.get('stealthrock') and \
                any(m.alive for k, m in enumerate(st.sides[1].mons) if k != st.sides[1].act):
            sc = {j: S.switch_score(st, 0, j) for j in opts}
            top = max(sc.values())
            cand = [j for j in opts if base(mons[j]) in ROCKERS and sc[j] >= top - 0.15]
            if cand:
                j = max(cand, key=lambda k: sc[k])
                ctx.fire('R1b', '-', mons[j].name)
                return j
        return S.chooser(st, side, opts)
    return chooser
