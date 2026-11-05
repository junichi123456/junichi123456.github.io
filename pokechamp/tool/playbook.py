"""構築記事の「運用方法（動き方）」を機械可読の規則 guide.play にし、シミュレーションの根行動に適用する。
仕様: pokechamp/specs/SPEC_PLAYBOOK.md

  validate(play, team, text)   規則の検証（拒否理由のリスト。空＝合格）
  load_all()                   known_teams.json の guide.play（空でないもの）
  play_sig(plays)              結果ファイルに残す署名
  PB                           1試合・1側ぶんの規則の適用（decide = 根行動、chooser = 交代先）
  ranked(bst, i, depth)        側 i の根行動の値一覧（policy.ranked_root の一般化）
"""
import hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle as B  # noqa: E402
import engine as E  # noqa: E402
import prep  # noqa: E402
import search as S  # noqa: E402
from calc import JT  # noqa: E402

PLAYBOOK_VERSION = 1
PB_LOSS = -50.0
PB_GAP = 1.5
PB_MAX_SWITCH = 2
PB_MAX_DEFAULT = 6
PB_STUCK = 3
PB_MAX_RULES = 10

TYPE_JA = {ja: en for en, ja in JT.items()}
# 判定語彙。True = replace でも可（※）
VOCAB_WHEN = {'turn': True, 'lead': False, 'foe': True, 'foe_type': True, 'foe_shown': False, 'foe_boosted': True,
              'my_hp': True, 'foe_hp': True, 'my_sub': False, 'foe_sub': False, 'trickroom': True,
              'rocks_on_foe': True, 'rocks_on_me': True, 'mega_used': True, 'foe_faster': False, 'foe_can_ko': False,
              'can_ko': False, 'bad_matchup': False, 'bench_alive': True, 'foe_left': True, 'my_left': True,
              'after': True}
VOCAB_DO = ('move', 'best_damage', 'switch', 'avoid', 'preserve', 'mega')
RULE_KEYS = {'id', 'who', 'phase', 'when', 'do', 'until', 'max', 'origin', 'note', 'src'}

_JA2ID = {m.ja: k for k, m in E.MOVES.items()}


def _bn(n):
    return B._base(n)


def _nows(s):
    return re.sub(r'\s+', '', str(s))


# ---------------------------------------------------------------- validate
def _check_range(v, lo_b=None, hi_b=None, nullable=False):
    if not (isinstance(v, list) and len(v) == 2):
        return False
    a, b = v
    for x in (a, b):
        if x is None:
            if not nullable:
                return False
        elif isinstance(x, bool) or not isinstance(x, (int, float)):
            return False
        elif (lo_b is not None and x < lo_b) or (hi_b is not None and x > hi_b):
            return False
    return not (a is not None and b is not None and a > b)


def _check_cond(cond, rid, where, team_names, ids, replace, moves_all):
    err = []
    if not isinstance(cond, dict):
        return [f'{rid}: {where} が dict ではありません']
    for k, v in cond.items():
        if k not in VOCAB_WHEN:
            err.append(f'{rid}: {where} に未知のキー {k}')
            continue
        if replace and not VOCAB_WHEN[k]:
            err.append(f'{rid}: phase:replace の {where} で使えないキー {k}')
        if k == 'turn':
            if not ((isinstance(v, int) and not isinstance(v, bool)) or _check_range(v, 1, None, True)):
                err.append(f'{rid}: {where}.turn は int か [lo,hi]')
        elif k in ('lead', 'foe_boosted', 'my_sub', 'foe_sub', 'trickroom', 'rocks_on_foe', 'rocks_on_me', 'mega_used',
                   'foe_faster', 'foe_can_ko', 'can_ko', 'bad_matchup'):
            if not isinstance(v, bool):
                err.append(f'{rid}: {where}.{k} は bool')
        elif k in ('my_hp', 'foe_hp'):
            if not _check_range(v, 0, 1):
                err.append(f'{rid}: {where}.{k} は 0〜1 の [lo,hi]')
        elif k in ('foe_left', 'my_left'):
            if not _check_range(v, 0, 6, True):
                err.append(f'{rid}: {where}.{k} は [lo,hi]')
        elif k in ('foe', 'foe_type', 'foe_shown', 'bench_alive', 'after'):
            if not (isinstance(v, list) and v and all(isinstance(x, str) for x in v)):
                err.append(f'{rid}: {where}.{k} は文字列のリスト')
                continue
            for x in v:
                if k == 'foe' and not (x in B.POKE or _bn(x) in B.POKE):
                    err.append(f'{rid}: {where}.foe の {x} は知らないポケモン')
                elif k == 'foe_type' and x not in TYPE_JA:
                    err.append(f'{rid}: {where}.foe_type の {x} はタイプ和名にありません')
                elif k == 'foe_shown' and x not in B.MOVE:
                    err.append(f'{rid}: {where}.foe_shown の {x} は知らない技')
                elif k == 'bench_alive' and _bn(x) not in team_names:
                    err.append(f'{rid}: {where}.bench_alive の {x} は構築の6体にいません')
                elif k == 'after' and x not in ids:
                    err.append(f'{rid}: {where}.after の {x} は未定義の規則 id')
    return err


def validate(play, team, text=None):
    """拒否理由（日本語・規則 id 付き）のリスト。空なら合格。team: known_teams の team（和名の moves つき）。"""
    if not isinstance(play, list):
        return ['play がリストではありません']
    err = []
    if len(play) > PB_MAX_RULES:
        err.append(f'規則が {len(play)} 個（最大 {PB_MAX_RULES}）')
    team_names = {_bn(m['name']) for m in team}
    mv_by = {_bn(m['name']): set(m.get('moves') or []) for m in team}
    moves_all = set().union(*mv_by.values()) if mv_by else set()
    ids = []
    for r in play:
        if isinstance(r, dict) and isinstance(r.get('id'), str):
            ids.append(r['id'])
    seen_ids = set()
    ntext = _nows(text) if text is not None else None
    for n, r in enumerate(play):
        if not isinstance(r, dict):
            err.append(f'[{n}]: 規則が dict ではありません')
            continue
        rid = r.get('id')
        if not isinstance(rid, str) or not re.fullmatch(r'[a-z0-9_]{1,12}', rid):
            err.append(f'[{n}]: id は ^[a-z0-9_]{{1,12}}$ ({rid!r})')
            rid = f'[{n}]'
        elif rid in seen_ids:
            err.append(f'{rid}: id が重複')
        seen_ids.add(rid)
        for k in r:
            if k not in RULE_KEYS:
                err.append(f'{rid}: 未知のキー {k}')
        phase = r.get('phase', 'turn')
        if phase not in ('turn', 'replace'):
            err.append(f'{rid}: phase は turn/replace')
        replace = phase == 'replace'
        who = r.get('who')
        if replace:
            if who != '*':
                err.append(f'{rid}: phase:replace の who は "*"')
        elif who != '*' and (not isinstance(who, str) or _bn(who) not in team_names):
            err.append(f'{rid}: who {who!r} は構築の6体にいません')
        if 'when' not in r:
            err.append(f'{rid}: when がありません')
        else:
            w = r['when']
            for c in (w if isinstance(w, list) else [w]):
                err += _check_cond(c, rid, 'when', team_names, ids, replace, moves_all)
            if isinstance(w, list) and not w:
                err.append(f'{rid}: when のリストが空')
        if 'until' in r:
            if not isinstance(r['until'], dict):
                err.append(f'{rid}: until は dict のみ')
            else:
                err += _check_cond(r['until'], rid, 'until', team_names, ids, replace, moves_all)
        if 'max' in r and (isinstance(r['max'], bool) or not isinstance(r['max'], int) or r['max'] < 1):
            err.append(f'{rid}: max は 1 以上の整数')
        org = r.get('origin', 'article')
        if org not in ('article', 'user'):
            err.append(f'{rid}: origin は article/user')
        if not isinstance(r.get('note'), str) or not r.get('note').strip():
            err.append(f'{rid}: note がありません')
        elif len(r['note']) > 40:
            err.append(f'{rid}: note は40字以内')
        src = r.get('src', '')
        if org == 'article':
            if not isinstance(src, str) or not src.strip():
                err.append(f'{rid}: origin:article には src が必要')
            elif len(src) > 60:
                err.append(f'{rid}: src は60字以内')
            elif ntext is not None and _nows(src) not in ntext:
                err.append(f'{rid}: src が本文に含まれません ({src[:20]}…)')
        do = r.get('do')
        if not isinstance(do, dict):
            err.append(f'{rid}: do がありません')
            continue
        for k in do:
            if k not in VOCAB_DO:
                err.append(f'{rid}: do に未知のキー {k}')
        kinds = [k for k in do if k in VOCAB_DO and k != 'mega']
        if len(kinds) != 1:
            err.append(f'{rid}: do の種類は ちょうど1つ（{len(kinds)}個: {kinds}）')
            continue
        kind = kinds[0]
        if 'mega' in do:
            if not isinstance(do['mega'], bool):
                err.append(f'{rid}: do.mega は bool')
            if kind not in ('move', 'best_damage'):
                err.append(f'{rid}: do.mega は move/best_damage 以外と併用できません')
        if replace and kind not in ('switch', 'preserve'):
            err.append(f'{rid}: phase:replace の do は switch/preserve のみ')
        v = do[kind]
        if kind == 'best_damage':
            if v is not True:
                err.append(f'{rid}: do.best_damage は true')
            continue
        if not (isinstance(v, list) and v and all(isinstance(x, str) for x in v)):
            err.append(f'{rid}: do.{kind} は文字列のリスト')
            continue
        for x in v:
            if kind in ('move', 'avoid'):
                have = moves_all if who == '*' else mv_by.get(_bn(who), set()) if isinstance(who, str) else set()
                if x not in have:
                    err.append(f'{rid}: do.{kind} の {x} は {who} の技構成にありません')
            else:
                if _bn(x) not in team_names:
                    err.append(f'{rid}: do.{kind} の {x} は構築の6体にいません')
    return err


def load_all(path=None):
    data = json.load(open(path or prep.KNOWN_P, encoding='utf-8'))['teams']
    return {t['id']: t['guide']['play'] for t in data if t.get('guide') and t['guide'].get('play')}


def play_sig(plays):
    return hashlib.sha256(json.dumps(sorted(plays.items()), ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:12]


# ---------------------------------------------------------------- 根行動の値一覧
def ranked(bst, i, depth, k_self=3, k_opp=2, extra=()):
    """[(value, action), ...] best first; [0] is exactly S.lookahead_action(bst, i, depth). extra: 追加で値を付ける行動。"""
    acts = E.actions(bst, i)
    if len(acts) <= 1 and not extra:
        return [(0.0, acts[0] if acts else None)]
    sign = 1 if i == 0 else -1
    j = 1 - i

    def pair(a, b):
        return (a, b) if i == 0 else (b, a)

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
            vs = [val(E.step(s, *pair(a, b), chooser=S.chooser), d - 1) for b in theirs]
            best = max(best, S.PESS * min(vs) + (1 - S.PESS) * sum(vs) / len(vs))
        return best

    theirs = S.prune(bst, j, k_opp + 1) if E.actions(bst, j) else [None]
    out = []
    for n, a in enumerate(list(acts) + [x for x in extra if x not in acts]):
        vs = [val(E.step(bst, *pair(a, b), chooser=S.chooser), depth - 1) for b in theirs]
        v = S.PESS * min(vs) + (1 - S.PESS) * sum(vs) / len(vs) + (S.front_bias(bst, a) if i == 0 else 0)
        out.append((v, n, a))
    out.sort(key=lambda x: (-x[0], x[1]))
    return [(v, a) for v, _, a in out]


def aname(st, i, a):
    if a is None:
        return '-'
    if a[0] == 's':
        return '→' + st.sides[i].mons[a[1]].name
    md = E.MOVES.get(a[1])
    return md.ja if md else a[1]


# ---------------------------------------------------------------- 条件の判定
def _rng(v, x):
    lo, hi = v
    return (lo is None or x >= lo) and (hi is None or x <= hi)


class _Cx:
    __slots__ = ('st', 'bst', 'side', 'seen', 'turn', 'pb', 'full')

    def __init__(self, st, bst, side, seen, turn, pb, full):
        self.st, self.bst, self.side, self.seen, self.turn, self.pb, self.full = st, bst, side, seen, turn, pb, full


def _types(st, m):
    return E.Battle(st).types(m)


def _hold1(k, v, c):
    """1つの条件キー。full=False（replace）では ※ のキーだけ（他は False）。"""
    i = c.side
    if not c.full and not VOCAB_WHEN.get(k):
        return False
    bst = c.bst
    me, foe = S._me(bst, i), S._foe(bst, i)
    if k == 'turn':
        return c.turn == v if isinstance(v, int) else _rng(v, c.turn)
    if k == 'lead':
        return v == (c.pb.lead_slot is not None and not c.pb.changed and bst.sides[i].act == c.pb.lead_slot)
    if k == 'foe':
        return _bn(foe.name) in {_bn(x) for x in v}
    if k == 'foe_type':
        t = _types(bst, foe)
        return any(TYPE_JA.get(x) in t for x in v)
    if k == 'foe_shown':
        sh = (c.seen[1 - i] if c.seen else {}).get(bst.sides[1 - i].act, [])
        return any(_JA2ID.get(x) in sh for x in v)
    if k == 'foe_boosted':
        return v == any(b >= 1 for b in foe.boosts.values())
    if k == 'my_hp':
        return _rng(v, me.hp / max(1, me.maxhp))
    if k == 'foe_hp':
        return _rng(v, foe.hp / max(1, foe.maxhp))
    if k == 'my_sub':
        return v == ('substitute' in me.vol)
    if k == 'foe_sub':
        return v == ('substitute' in foe.vol)
    if k == 'trickroom':
        return v == bool(bst.pseudo.get('trickroom'))
    if k == 'rocks_on_foe':
        return v == bool(bst.sides[1 - i].cond.get('stealthrock'))
    if k == 'rocks_on_me':
        return v == bool(bst.sides[i].cond.get('stealthrock'))
    if k == 'mega_used':
        return v == bool(bst.sides[i].mega_used)
    if k == 'foe_faster':
        return v == (S.faster(bst, i) == 0.0)
    if k == 'foe_can_ko':
        return v == (S.best_damage(bst, 1 - i) >= 1.0)
    if k == 'can_ko':
        return v == (S.best_damage(bst, i) >= 1.0)
    if k == 'bad_matchup':
        fk = S.best_damage(bst, 1 - i) >= 1.0
        bad = fk and not (S.best_damage(bst, i) >= 1.0 and S.faster(bst, i) == 1.0)
        return v == bad
    if k == 'bench_alive':
        s = bst.sides[i]
        nm = {_bn(m.name) for j, m in enumerate(s.mons) if j != s.act and m.alive}
        return any(_bn(x) in nm for x in v)
    if k == 'foe_left':
        return _rng(v, sum(1 for m in bst.sides[1 - i].mons if m.alive))
    if k == 'my_left':
        return _rng(v, sum(1 for m in bst.sides[i].mons if m.alive))
    if k == 'after':
        return any(c.pb.uses.get(x, 0) >= 1 for x in v)
    return False


def _hold(when, c):
    if isinstance(when, list):
        return any(_hold(w, c) for w in when)
    return all(_hold1(k, v, c) for k, v in when.items())


def _sig(bst, i):
    me, foe = S._me(bst, i), S._foe(bst, i)
    return (bst.sides[i].act, bst.sides[1 - i].act, round(100 * me.hp / max(1, me.maxhp)), round(100 * foe.hp / max(1, foe.maxhp)))


# ---------------------------------------------------------------- 適用
class PB:
    def __init__(self, play, side, team_id):
        self.rules = list(play or [])
        self.side = side
        self.team_id = team_id
        self.uses = {}
        self.fired = []
        self.rejected = []
        self.dead = set()
        self.last_turn = {}
        self.streak = {}
        self.lead_slot = None
        self.changed = False
        self.turn = 0
        self.cur_preserve = set()

    # -- helpers
    def _live(self, r):
        rid = r['id']
        if rid in self.dead:
            return False
        mx = r.get('max', PB_MAX_SWITCH if 'switch' in r['do'] else PB_MAX_DEFAULT)
        return self.uses.get(rid, 0) < mx

    def _reject(self, turn, rid, why, extra=None):
        self.rejected.append([turn, rid, why] + ([extra] if extra is not None else []))

    def _fire(self, turn, rid, orig, new, same=False):
        self.uses[rid] = self.uses.get(rid, 0) + 1
        self.fired.append({'t': turn, 'rid': rid, 'from': orig, 'to': new, 'same': same})

    def _legal(self, r, st, bst, acts, me, ban_mv, ban_sw):
        """規則 r の行動（合法かつ禁止外）。無ければ None。"""
        do = r['do']
        side = self.side
        mega = do.get('mega')

        def fix(a):
            if a[0] == 'm' and mega is False and a[2]:
                return ('m', a[1], False)
            return a

        if 'move' in do:
            for ja in do['move']:
                mid = _JA2ID.get(ja)
                if mid is None or mid in ban_mv:
                    continue
                for a in acts:
                    if a[0] == 'm' and a[1] == mid:
                        return fix(a)
            return None
        if 'best_damage' in do:
            cand = [a for a in acts if a[0] == 'm' and a[1] not in ban_mv and a[1] in E.MOVES and E.MOVES[a[1]].cat != 'status']
            if not cand:
                return None
            order = {x: n for n, x in enumerate(me.moves)}
            best = max(cand, key=lambda a: (S.est(bst, side, a[1]), -order.get(a[1], 99)))
            return fix(best)
        if 'switch' in do:
            s = st.sides[side]
            for nm in do['switch']:
                for j, m in enumerate(s.mons):
                    if j != s.act and m.alive and _bn(m.name) == _bn(nm) and ('s', j) in acts and _bn(m.name) not in ban_sw:
                        return ('s', j)
            return None
        return None

    # -- 根行動
    def decide(self, st, bst, side, a0, ranked_fn, seen, turn):
        self.turn = turn
        act = st.sides[side].act
        if self.lead_slot is None:
            self.lead_slot = act
        elif act != self.lead_slot:
            self.changed = True
        me = st.sides[side].mons[act]
        acts = E.actions(st, side)
        if a0 is None or len(acts) <= 1 or a0[1:2] == ('recharge',) or \
                any(k in me.vol for k in ('lockedmove', 'twoturnmove', 'mustrecharge', 'uproar')):
            return a0, None
        c = _Cx(st, bst, side, seen, turn, self, True)
        bme = S._me(bst, side)
        for r in self.rules:
            if r.get('phase', 'turn') != 'turn' or r['id'] in self.dead:
                continue
            if r.get('until') and _hold(r['until'], c):
                self.dead.add(r['id'])
                self._reject(turn, r['id'], 'until')
        hit = []
        for r in self.rules:
            if r.get('phase', 'turn') != 'turn' or not self._live(r):
                continue
            if r['who'] != '*' and _bn(r['who']) != _bn(bme.name):
                continue
            if 'switch' in r['do'] and self.last_turn.get(r['id']) == turn - 1:
                continue
            if _hold(r['when'], c):
                hit.append(r)
        self.cur_preserve = set()
        if not hit:
            return a0, None
        ban_mv, ban_sw = set(), set()
        for r in hit:
            if 'avoid' in r['do']:
                ban_mv |= {_JA2ID[x] for x in r['do']['avoid'] if x in _JA2ID}
            if 'preserve' in r['do']:
                ban_sw |= {_bn(x) for x in r['do']['preserve']}
        self.cur_preserve = set(ban_sw)
        cache = {}

        def rk():
            if 'v' not in cache:
                ex = ()
                if any(r['do'].get('mega') is False for r in hit):
                    ex = tuple(('m', a[1], False) for a in acts if a[0] == 'm' and a[2])
                cache['v'] = ranked_fn(ex)
            return cache['v']

        def value(a):
            for v, x in rk():
                if x == a:
                    return v
            return None

        for r in hit:
            if not any(k in r['do'] for k in ('move', 'best_damage', 'switch')):
                continue
            a = self._legal(r, st, bst, acts, me, ban_mv, ban_sw)
            if a is None:
                self._reject(turn, r['id'], 'illegal')
                continue
            if a != a0:
                lst = rk()
                v0 = lst[0][0]
                vr = value(a)
                if vr is not None and ((vr <= PB_LOSS < v0) or (v0 - vr > PB_GAP)):
                    self._reject(turn, r['id'], 'guard', round(v0 - vr, 3))
                    continue
            return self._adopt(r, turn, st, bst, side, a0, a)
        # 制約が a0 を禁止している
        bad = (a0[0] == 'm' and a0[1] in ban_mv) or (a0[0] == 's' and _bn(st.sides[side].mons[a0[1]].name) in ban_sw)
        if bad:
            cons = [r for r in hit if 'avoid' in r['do'] or 'preserve' in r['do']]
            for v, a in rk():
                if a is None:
                    continue
                if (a[0] == 'm' and a[1] in ban_mv) or (a[0] == 's' and _bn(st.sides[side].mons[a[1]].name) in ban_sw):
                    continue
                if a in acts:
                    return self._adopt(cons[0], turn, st, bst, side, a0, a)
        return a0, None

    def _adopt(self, r, turn, st, bst, side, a0, a):
        rid = r['id']
        self._fire(turn, rid, aname(st, side, a0), aname(st, side, a), a == a0)
        sg = (_sig(bst, side), a)
        prev = self.streak.get(rid)
        n = prev[1] + 1 if prev and prev[0] == turn - 1 and prev[2] == sg[0] else 1
        self.streak[rid] = (turn, n, sg[0])
        self.last_turn[rid] = turn
        if n >= PB_STUCK:
            self.dead.add(rid)
            self._reject(turn, rid, 'stuck')
        return a, rid

    # -- 交代先
    def chooser(self, base):
        def ch(st, side, opts):
            if side != self.side or not opts:
                return base(st, side, opts)
            c = _Cx(st, st, side, None, self.turn, self, False)
            s = st.sides[side]
            pres = set(self.cur_preserve)
            for r in self.rules:
                if r.get('phase', 'turn') != 'replace' or not self._live(r):
                    continue
                if r.get('until') and _hold(r['until'], c):
                    self.dead.add(r['id'])
                    self._reject(self.turn, r['id'], 'until')
                    continue
                if not _hold(r['when'], c):
                    continue
                if 'preserve' in r['do']:
                    pres |= {_bn(x) for x in r['do']['preserve']}
            for r in self.rules:
                if r.get('phase', 'turn') != 'replace' or not self._live(r) or 'switch' not in r['do']:
                    continue
                if not _hold(r['when'], c):
                    continue
                for nm in r['do']['switch']:
                    for j in opts:
                        if _bn(s.mons[j].name) == _bn(nm) and _bn(nm) not in pres:
                            self._fire(self.turn, r['id'], '-', s.mons[j].name)
                            return j
            left = [j for j in opts if _bn(s.mons[j].name) not in pres]
            return base(st, side, left or opts)
        return ch

    def stats(self):
        return {'v': PLAYBOOK_VERSION, 'fired': list(self.fired), 'rejected': list(self.rejected), 'uses': dict(self.uses)}
