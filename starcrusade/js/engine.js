/* Star Crusade CCG 再現版 — ルールエンジン
 * 状態はすべて JSON 化可能なプレーンオブジェクト(セーブ/AI の複製に使う)。
 * 参照: 指揮官は 'c0' / 'c1'、ユニットは数値 uid。
 */
(function () {
  const D = window.SC_DATA;
  const CARDS = {}; D.cards.forEach(c => { CARDS[c.id] = c; });
  const MODS = {}; D.modules.forEach(m => { MODS[m.id] = m; });
  const BOARD_MAX = 7, HAND_MAX = 10, SUPPLY_MAX = 10, PSY_MAX = 10, ENERGY_MAX = 30;
  const BASE_MODULE = { ANN: 'psychic_charge', HIE: 'restore', SHA: 'release_mutagen', HAJ: 'thrash', CON: 'redeem_contract', TER: 'call_marines', VRX: 'scout_ahead' };

  const rnd = n => Math.floor(Math.random() * n);
  const pick = a => a.length ? a[rnd(a.length)] : null;
  function shuffle(a) { for (let i = a.length - 1; i > 0; i--) { const j = rnd(i + 1); [a[i], a[j]] = [a[j], a[i]]; } return a; }
  const card = id => CARDS[id];
  const ja = id => (CARDS[id] ? CARDS[id].ja : id);

  // ---------- 生成 ----------
  function makePlayer(cfg, idx) {
    const mods = [BASE_MODULE[cfg.faction]].concat((cfg.modules || []).filter(m => MODS[m] && !MODS[m].base)).slice(0, 3);
    let hp = cfg.cards.length;
    const kw = {};
    mods.forEach(m => { const d = MODS[m]; if (d.hp) hp += d.hp; if (d.cmdKw) for (const k in d.cmdKw) kw[k] = (kw[k] || 0) + d.cmdKw[k]; });
    hp = Math.max(10, hp);
    return {
      idx, name: cfg.name || ('プレイヤー' + (idx + 1)), faction: cfg.faction, ai: !!cfg.ai, deckName: cfg.deckName || '',
      hp, maxHp: hp, deck: shuffle(cfg.cards.slice()), hand: [], board: [], maxSupply: 0, supply: 0, energy: 0, psy: 0,
      modules: mods.map(id => ({ id, used: false, count: 0 })), weapon: null, kw, mods: [], attacks: 0,
      credit: 0, fatigue: 0, cyphers: [], tacticDiscount: 0, nextDiscount: 0, bone: false, pride: false,
      st: { dmg: 0, taken: 0, played: 0, kills: 0, cards: {} }
    };
  }

  function newGame(cfg) {
    const s = { v: 1, turn: 0, active: 0, uid: 1, log: [], fx: [], q: [], winner: null, mode: cfg.mode || 'ai', diff: cfg.diff || 'normal', noEnergyTurn: -1, started: Date.now(), players: [] };
    s.players = [makePlayer(cfg.p0, 0), makePlayer(cfg.p1, 1)];
    s.first = rnd(2);
    s.active = s.first;
    const second = 1 - s.first;
    draw(s, s.first, 3, null, true);
    draw(s, second, 4, null, true);
    addHand(s, second, 'supply_crate');
    log(s, `${P(s, s.first).name} が先攻。後攻の ${P(s, second).name} はイニシアチブを得た。`);
    // マリガン(引き直し):CPU は自動、人間は UI から選ぶ
    s.phase = 'mulligan';
    s.mull = s.players.map(pl => false);
    s.players.forEach((pl, i) => { if (pl.ai || cfg.mulligan === false) autoMulligan(s, i); });
    if (s.mull.every(Boolean)) beginPlay(s);
    return s;
  }
  function autoMulligan(s, p) {
    const pl = s.players[p];
    const pickCost = pl.ai ? 5 : 99;
    mulligan(s, p, pl.hand.filter(h => h.id !== 'supply_crate' && card(h.id).c >= pickCost).map(h => h.uid));
  }
  function mulligan(s, p, uids) {
    const pl = s.players[p];
    if (s.phase !== 'mulligan' || s.mull[p]) return false;
    const back = pl.hand.filter(h => uids.includes(h.uid) && h.id !== 'supply_crate');
    pl.hand = pl.hand.filter(h => !back.includes(h));
    back.forEach(h => pl.deck.push(h.id));
    shuffle(pl.deck);
    for (const h of back) { const id = pl.deck.shift(); const nh = addHand(s, p, id); if (nh) { const i = pl.hand.indexOf(nh); pl.hand.splice(i, 1); pl.hand.splice(pl.hand.length - (pl.hand.some(x => x.id === 'supply_crate') ? 1 : 0), 0, nh); } }
    s.mull[p] = true;
    if (back.length) log(s, `${pl.name} は ${back.length} 枚を引き直した。`);
    return true;
  }
  function beginPlay(s) { s.phase = 'play'; startTurn(s); }

  // ---------- ヘルパー ----------
  function P(s, i) { return s.players[i]; }
  function log(s, m) { s.log.push({ t: s.turn, m }); if (s.log.length > 300) s.log.splice(0, s.log.length - 300); }
  function fx(s, e) { s.fx.push(e); if (s.fx.length > 60) s.fx.shift(); }
  function findUnit(s, uid) {
    for (const p of s.players) { const i = p.board.findIndex(u => u.uid === uid); if (i >= 0) return { u: p.board[i], p: p.idx, i }; }
    return null;
  }
  function getChar(s, ref) {
    if (typeof ref === 'string' && ref[0] === 'c') { const p = +ref[1]; return { cmd: true, p, o: s.players[p] }; }
    const f = findUnit(s, ref); return f ? { cmd: false, p: f.p, o: f.u, i: f.i } : null;
  }
  function charName(s, ref) { const c = getChar(s, ref); if (!c) return '?'; return c.cmd ? c.o.name + '(指揮官)' : ja(c.o.id); }
  function groupsOf(u) { return (u.groups || (card(u.id).g || [])); }

  function has(o, k) {
    let v = (o.kw && o.kw[k]) || 0;
    if (o.mods) for (const m of o.mods) if (m.k === k) v += m.v;
    if (o.weapon && card(o.weapon.id).wkw) v += card(o.weapon.id).wkw[k] || 0;
    if (k === 'VULNERABILITY' && o.bone) v += 1;
    return v;
  }
  function trigs(u, name) {
    const out = [];
    if (!u.nulled) { const on = card(u.id).on; if (on && on[name]) out.push(on[name]); }
    if (u.xt) for (const x of u.xt) if (x.trig === name) out.push(x.fx);
    return out;
  }
  function auraOf(u) { return u.nulled ? null : card(u.id).aura || null; }

  function atkOf(s, ref) {
    const c = getChar(s, ref); if (!c) return 0;
    const o = c.o;
    if (c.cmd) {
      let a = o.weapon ? o.weapon.a : 0;
      a += has(o, 'ATK') + (o.bone ? 1 : 0);
      return Math.max(0, a);
    }
    let a = o.atk + has(o, 'ATK');
    const me = s.players[c.p], op = s.players[1 - c.p];
    if (has(o, 'SWARM')) a += me.board.length - 1;
    if (has(o, 'ZEAL')) a += op.board.length;
    for (const u of me.board) {
      if (u === o) continue;
      const au = auraOf(u);
      if (au && au.a && (!au.g || groupsOf(o).includes(au.g))) a += au.a;
    }
    return Math.max(0, a);
  }

  function costOf(s, p, h) {
    const c = card(h.id);
    let v = c.c + (h.cm || 0);
    const pl = s.players[p];
    if (c.kw && c.kw.CREDIT) { for (const u of pl.board) { const au = auraOf(u); if (au && au.creditRed) v -= au.creditRed; } }
    if (c.t === 'T') v -= pl.tacticDiscount;
    v -= pl.nextDiscount;
    if (c.psyDiscount) v -= pl.psy;
    return Math.max(0, v);
  }

  function val(s, ctx, n) {
    if (typeof n === 'number') return n;
    const me = s.players[ctx.p], op = s.players[1 - ctx.p];
    switch (n) {
      case 'psy': return me.psy;
      case 'psy+2': return me.psy + 2;
      case 'psy*2': return me.psy * 2;
      case 'rev': return op.hand.filter(h => h.rev).length;
      case 'rend': return 2 + (ctx.modCount || 0);
      case 'damagedAllies': return me.board.filter(u => u.hp < u.maxHp).length;
      case 'allies': return me.board.length;
      case 'others': return Math.max(0, me.board.length - 1);
      default: return 0;
    }
  }

  // ---------- 対象 ----------
  function targetable(s, p, ref, srcKind) {
    const c = getChar(s, ref); if (!c) return false;
    if (c.cmd) return true;
    if (c.p !== p) {
      if (has(c.o, 'CLOAK')) return false;
      if (has(c.o, 'BUNKER') && (srcKind === 'tactic' || srcKind === 'module')) return false;
    }
    return true;
  }
  function validTargets(s, p, spec, srcKind, selfUid) {
    if (!spec) return [];
    const out = [];
    const sides = spec.side === 'ally' ? [p] : spec.side === 'enemy' ? [1 - p] : [p, 1 - p];
    for (const sd of sides) {
      const pl = s.players[sd];
      if (spec.kind === 'char') {
        if (!spec.mutable || sd === p) out.push('c' + sd);
      }
      for (const u of pl.board) {
        if (spec.notSelf && u.uid === selfUid) continue;
        if (spec.g && !groupsOf(u).includes(spec.g)) continue;
        if (spec.gs && !spec.gs.some(g => groupsOf(u).includes(g))) continue;
        if (spec.maxAtk !== undefined && atkOf(s, u.uid) > val(s, { p }, spec.maxAtk)) continue;
        if (spec.maxHp !== undefined && u.hp > spec.maxHp) continue;
        if (spec.mutable && !trigs(u, 'mutate').length) continue;
        out.push(u.uid);
      }
    }
    return out.filter(r => targetable(s, p, r, srcKind));
  }

  function resolveT(s, ctx, t) {
    const me = s.players[ctx.p], op = s.players[1 - ctx.p];
    let sel = t, g = null, mut = false;
    if (t && typeof t === 'object') { sel = t.s; g = t.g; mut = !!t.mut; }
    const fil = arr => arr.filter(u => (!g || groupsOf(u).includes(g)) && (!mut || trigs(u, 'mutate').length)).map(u => u.uid);
    switch (sel) {
      case 'T': return ctx.T !== undefined && ctx.T !== null && getChar(s, ctx.T) ? [ctx.T] : [];
      case 'self': return ctx.self !== undefined && getChar(s, ctx.self) ? [ctx.self] : [];
      case 'ac': return ['c' + ctx.p];
      case 'ec': return ['c' + (1 - ctx.p)];
      case 'AE': return fil(op.board);
      case 'AA': return fil(me.board);
      case 'OA': return fil(me.board.filter(u => u.uid !== ctx.self));
      case 'AU': return fil(me.board.concat(op.board));
      case 'RE': { const a = fil(op.board); return a.length ? [pick(a)] : []; }
      case 'REA': { const a = fil(op.board).concat(['c' + (1 - ctx.p)]); return [pick(a)]; }
      case 'RA': { const a = fil(me.board); return a.length ? [pick(a)] : []; }
      case 'ROA': { const a = fil(me.board.filter(u => u.uid !== ctx.self)); return a.length ? [pick(a)] : []; }
      default: return [];
    }
  }

  function cond(s, ctx, c) {
    const me = s.players[ctx.p], op = s.players[1 - ctx.p];
    if (c.energy !== undefined && me.energy < c.energy) return false;
    if (c.psy !== undefined && me.psy < c.psy) return false;
    if (c.psyLt !== undefined && me.psy >= c.psyLt) return false;
    if (c.rev !== undefined && op.hand.filter(h => h.rev).length < c.rev) return false;
    if (c.hasGroup && !me.board.some(u => u.uid !== ctx.self && groupsOf(u).includes(c.hasGroup))) return false;
    if (c.onlyGroup && (!me.board.length || !me.board.every(u => groupsOf(u).includes(c.onlyGroup)))) return false;
    if (c.allies !== undefined && me.board.length < c.allies) return false;
    if (c.hasKw && !me.board.some(u => has(u, c.hasKw))) return false;
    if (c.tDead) { const t = ctx.T !== undefined && ctx.T !== null ? getChar(s, ctx.T) : null; if (t && !t.cmd && t.o.hp > 0 && !t.o.dead) return false; }
    if (c.groupCount && me.board.filter(u => groupsOf(u).includes(c.groupCount[0])).length < c.groupCount[1]) return false;
    return true;
  }

  // ---------- ユニット生成 ----------
  function makeUnit(s, id, p, over) {
    const c = card(id);
    const u = { uid: s.uid++, id, p, atk: c.a || 0, hp: c.h || 1, maxHp: c.h || 1, kw: Object.assign({}, c.kw || {}), mods: [], xt: [], attacks: 0, sick: true, disabled: 0, mut: 0 };
    delete u.kw.CREDIT;
    if (over) Object.assign(u, over);
    return u;
  }
  function summon(s, p, id, over) {
    const pl = s.players[p];
    if (pl.board.length >= BOARD_MAX) { log(s, `${pl.name} の場がいっぱいで ${ja(id)} を配備できない。`); return null; }
    const u = makeUnit(s, id, p, over);
    pl.board.push(u);
    fx(s, { ref: u.uid, k: 'summon' });
    return u;
  }

  // ---------- 手札・ドロー ----------
  function addHand(s, p, id, extra) {
    const pl = s.players[p];
    if (pl.hand.length >= HAND_MAX) { log(s, `${pl.name} の手札がいっぱいで ${ja(id)} は失われた。`); return null; }
    const h = Object.assign({ uid: s.uid++, id, rev: false, cm: 0 }, extra || {});
    pl.hand.push(h); return h;
  }
  function draw(s, p, n, filter, silent) {
    const pl = s.players[p];
    for (let i = 0; i < n; i++) {
      let idx = 0;
      if (filter) { idx = pl.deck.findIndex(id => (!filter.t || card(id).t === filter.t) && (!filter.g || (card(id).g || []).includes(filter.g))); if (idx < 0) { log(s, '該当するカードが山札にない。'); return; } }
      if (!pl.deck.length) {
        pl.fatigue++;
        log(s, `${pl.name} の山札が尽きている!消耗ダメージ ${pl.fatigue}。`);
        damage(s, 'c' + p, pl.fatigue, { p, kind: 'fatigue' });
        continue;
      }
      const id = pl.deck.splice(idx, 1)[0];
      const h = addHand(s, p, id);
      if (h && !silent) s.lastDraw = { p, uid: h.uid };
    }
  }

  // ---------- ダメージ ----------
  function damage(s, ref, n, src) {
    n = Math.max(0, Math.floor(n));
    const c = getChar(s, ref);
    if (!c || n <= 0) return 0;
    const o = c.o;
    if (!c.cmd && has(o, 'INVINCIBLE') && (src.kind === 'unit' || src.kind === 'ability')) { fx(s, { ref, k: 'immune' }); return 0; }
    if (has(o, 'SHIELD')) { removeKw(o, 'SHIELD'); fx(s, { ref, k: 'shield' }); log(s, `${charName(s, ref)} の SHIELD がダメージを防いだ。`); return 0; }
    n += has(o, 'VULNERABILITY');
    if (src.kind === 'unit' && has(o, 'ARMORED') && !src.ignoreArmor) n = Math.min(n, 1);
    n -= has(o, 'SOAK');
    if (n <= 0) { fx(s, { ref, k: 'soak' }); return 0; }
    if (c.cmd) {
      if (o.pride) { o.pride = false; removeKw(o, 'SCREEN'); }
      let absorbed = 0;
      if (o.psy > 0) { absorbed = Math.min(o.psy, n); o.psy -= absorbed; n -= absorbed; }
      o.hp -= n;
      o.st.taken += n + absorbed;
      fx(s, { ref, k: 'dmg', n: n + absorbed });
      if (src.p !== undefined && src.p !== c.p) {
        s.players[src.p].st.dmg += n + absorbed;
        gainEnergy(s, src.p, 1);
        if (src.uid) { const su = findUnit(s, src.uid); if (su) for (const f of trigs(su.u, 'hitCmd')) s.q.push({ k: 'run', p: su.p, self: su.u.uid, fx: f }); }
      }
      return n + absorbed;
    }
    o.hp -= n;
    if (src.crit) o.dead = true;
    if (src.p !== undefined && src.p !== c.p) s.players[src.p].st.dmg += n;
    fx(s, { ref, k: 'dmg', n });
    if (trigs(o, 'fury').length) s.q.push({ k: 'fury', uid: o.uid });
    if (src.tag !== 'berserk') for (const w of s.players[c.p].board) for (const f of trigs(w, 'allyDamaged')) s.q.push({ k: 'run', p: c.p, self: w.uid, fx: f });
    return n;
  }
  function removeKw(o, k) { if (o.kw) delete o.kw[k]; if (o.mods) o.mods = o.mods.filter(m => m.k !== k); }
  function gainEnergy(s, p, n) { if (s.noEnergyTurn === s.turn && n > 0) return; const pl = s.players[p]; pl.energy = Math.max(0, Math.min(ENERGY_MAX, pl.energy + n)); }
  function heal(s, ref, n) {
    const c = getChar(s, ref); if (!c) return;
    const before = c.o.hp; c.o.hp = Math.min(c.o.maxHp, c.o.hp + n);
    if (c.o.hp > before) fx(s, { ref, k: 'heal', n: c.o.hp - before });
  }

  // ---------- 死亡処理 ----------
  function resolve(s) {
    let guard = 0;
    while (guard++ < 200) {
      if (s.q.length) {
        const e = s.q.shift();
        if (e.k === 'fury') { const f = findUnit(s, e.uid); if (f && f.u.hp > 0 && !f.u.dead) for (const fl of trigs(f.u, 'fury')) run(s, { p: f.p, self: f.u.uid, srcKind: 'ability' }, fl); }
        else if (e.k === 'run') run(s, { p: e.p, self: e.self, srcKind: 'ability', mem: e.mem }, e.fx);
        continue;
      }
      const dead = [];
      for (const pl of s.players) for (const u of pl.board) if (u.hp <= 0 || u.dead) dead.push(u);
      if (!dead.length) break;
      for (const u of dead) {
        const pl = s.players[u.p];
        const i = pl.board.indexOf(u); if (i >= 0) pl.board.splice(i, 1);
        log(s, `${ja(u.id)} は破壊された。`);
        fx(s, { ref: u.uid, k: 'die' });
        const killer = 1 - u.p;
        gainEnergy(s, killer, 1);
        s.players[killer].st.kills++;
        const rv = trigs(u, 'revenge');
        if (rv.length) {
          for (const f of rv) s.q.push({ k: 'run', p: u.p, self: u.uid, fx: f, mem: u.id });
          for (const pl2 of s.players) for (const w of pl2.board) for (const f of trigs(w, 'revengeAny')) s.q.push({ k: 'run', p: pl2.idx, self: w.uid, fx: f });
        }
      }
    }
    checkWin(s);
  }
  function checkWin(s) {
    if (s.winner !== null) return;
    const d0 = s.players[0].hp <= 0, d1 = s.players[1].hp <= 0;
    if (d0 && d1) s.winner = -1; else if (d0) s.winner = 1; else if (d1) s.winner = 0;
    if (s.winner !== null) log(s, s.winner === -1 ? '引き分け!' : `${s.players[s.winner].name} の勝利!`);
  }

  // ---------- 効果実行 ----------
  function run(s, ctx, list) {
    if (!list) return;
    for (const e of list) { if (s.winner !== null) return; op(s, ctx, e); }
  }
  function forT(s, ctx, t, f) { for (const r of resolveT(s, ctx, t)) { const c = getChar(s, r); if (c) f(c, r); } }
  function addMod(s, o, k, v, e) {
    const m = { k, v };
    if (e.temp) m.exp = s.turn; else if (e.until === 'next') m.exp = s.turn + 2;
    if (m.exp === undefined) { if (k === 'ATK') o.atk += v; else o.kw[k] = (o.kw[k] || 0) + v; }
    else o.mods.push(m);
  }

  function op(s, ctx, e) {
    const me = s.players[ctx.p], opp = s.players[1 - ctx.p];
    const spell = ctx.srcKind === 'tactic';
    switch (e.op) {
      case 'dmg': {
        let n = val(s, ctx, e.n);
        if (spell && !e.calc) n += firepower(s, ctx.p);
        forT(s, ctx, e.t, (c, r) => {
          const dealt = damage(s, r, n, { p: ctx.p, kind: ctx.srcKind === 'tactic' ? 'tactic' : ctx.srcKind === 'module' ? 'module' : 'ability', uid: ctx.self, tag: e.tag });
          if (dealt) log(s, `${charName(s, r)} に ${dealt} ダメージ。`);
        });
        if (ctx.self) { const f = findUnit(s, ctx.self); if (f) removeKw(f.u, 'CLOAK'); }
        break;
      }
      case 'heal': forT(s, ctx, e.t, (c, r) => heal(s, r, val(s, ctx, e.n))); break;
      case 'regen': forT(s, ctx, e.t, (c, r) => heal(s, r, 999)); break;
      case 'destroy': forT(s, ctx, e.t, (c) => { if (!c.cmd) c.o.dead = true; }); break;
      case 'buff': forT(s, ctx, e.t, (c, r) => {
        const a = val(s, ctx, e.a || 0), h = val(s, ctx, e.h || 0);
        if (a) { if (c.cmd) addMod(s, c.o, 'ATK', a, { temp: 1 }); else addMod(s, c.o, 'ATK', a, e); }
        if (h && !c.cmd) { c.o.maxHp += h; c.o.hp += h; }
        fx(s, { ref: r, k: 'buff' });
      }); break;
      case 'kw': forT(s, ctx, e.t, (c) => addMod(s, c.o, e.k, e.v || 1, e)); break;
      case 'lose': forT(s, ctx, e.t, (c) => removeKw(c.o, e.k)); break;
      case 'soakBreak': {
        for (const pl of s.players) for (const u of pl.board.slice()) if (has(u, 'SOAK')) { removeKw(u, 'SOAK'); damage(s, u.uid, 1, { p: ctx.p, kind: 'ability' }); }
        break;
      }
      case 'draw': draw(s, ctx.p, val(s, ctx, e.n), e.filter); break;
      case 'summon': for (let i = 0; i < (e.n || 1); i++) summon(s, e.side === 'enemy' ? 1 - ctx.p : ctx.p, e.id); log(s, `${me.name} は ${ja(e.id)} を配備。`); break;
      case 'summonRandom': { const id = pick(e.ids); summon(s, ctx.p, id); log(s, `${me.name} は ${ja(id)} を雇った。`); break; }
      case 'supply': me.supply += val(s, ctx, e.n); break;
      case 'energy': me.energy = Math.max(0, me.energy + e.n); break;
      case 'psy': { const before = me.psy; me.psy = Math.max(0, Math.min(PSY_MAX, me.psy + val(s, ctx, e.n))); fx(s, { ref: 'c' + ctx.p, k: 'psy' });
        if (me.psy > before) for (const w of me.board) for (const f of trigs(w, 'psyGain')) s.q.push({ k: 'run', p: ctx.p, self: w.uid, fx: f });
        break; }
      case 'spendPsy': { const n = me.psy; me.psy = 0; for (let i = 0; i < n; i++) run(s, ctx, e.fx); break; }
      case 'repeat': { const n = val(s, ctx, e.n); for (let i = 0; i < n; i++) run(s, ctx, e.fx); break; }
      case 'control': forT(s, ctx, e.t, (c) => {
        if (c.cmd || c.p === ctx.p) return;
        if (me.board.length >= BOARD_MAX) { c.o.dead = true; log(s, '場がいっぱいのため奪ったユニットは破壊された。'); return; }
        const from = s.players[c.p]; from.board.splice(from.board.indexOf(c.o), 1);
        c.o.p = ctx.p; c.o.sick = true; c.o.attacks = 0;
        if (e.until === 'next') { c.o.ctrlBack = s.turn + 2; c.o.owner = 1 - ctx.p; }
        me.board.push(c.o);
        log(s, `${me.name} は ${ja(c.o.id)} のコントロールを得た。`);
      }); break;
      case 'bounce': forT(s, ctx, e.t, (c) => {
        if (c.cmd) return;
        const pl = s.players[c.p]; pl.board.splice(pl.board.indexOf(c.o), 1);
        const owner = c.o.owner !== undefined ? c.o.owner : c.p;
        if (!card(c.o.id).token) addHand(s, owner, c.o.id);
        log(s, `${ja(c.o.id)} は手札に戻った。`);
      }); break;
      case 'returnSelf': if (ctx.mem) addHand(s, ctx.p, ctx.mem); break;
      case 'transform': forT(s, ctx, e.t, (c) => { if (c.cmd) return; const nc = card(e.id); Object.assign(c.o, { id: e.id, atk: nc.a, hp: nc.h, maxHp: nc.h, kw: Object.assign({}, nc.kw || {}), mods: [], xt: [], nulled: false, groups: undefined }); log(s, `${ja(e.id)} に変身した。`); }); break;
      case 'becomeCopy': forT(s, ctx, e.t, (c) => {
        if (c.cmd) return; const f = findUnit(s, ctx.self); if (!f) return;
        const nc = card(c.o.id);
        Object.assign(f.u, { id: c.o.id, atk: nc.a, hp: nc.h, maxHp: nc.h, kw: Object.assign({}, nc.kw || {}), groups: Array.from(new Set((nc.g || []).concat(['Cyborg']))) });
        delete f.u.kw.CREDIT; log(s, `レプリカントは ${ja(c.o.id)} のコピーになった。`);
      }); break;
      case 'nullify': forT(s, ctx, e.t, (c) => { if (c.cmd) return; c.o.kw = {}; c.o.mods = c.o.mods.filter(m => m.k === 'ATK'); c.o.xt = []; c.o.nulled = true; log(s, `${ja(c.o.id)} は NULLIFY された。`); }); break;
      case 'disable': forT(s, ctx, e.t, (c) => { if (!c.cmd) { c.o.disabled = 1; if (c.p === s.active) c.o.attacks = 0; } }); break;
      case 'grant': forT(s, ctx, e.t, (c) => { if (c.cmd) return; const x = { trig: e.trig, fx: e.fx }; if (e.temp) x.exp = s.turn; c.o.xt.push(x); }); break;
      case 'crate': addHand(s, e.side === 'enemy' ? 1 - ctx.p : ctx.p, 'supply_crate'); break;
      case 'addHand': for (let i = 0; i < (e.n || 1); i++) addHand(s, ctx.p, e.id); break;
      case 'mutate': forT(s, ctx, e.t, (c, r) => mutate(s, r)); break;
      case 'mutagen': forT(s, ctx, e.t, (c, r) => {
        if (c.cmd) { damage(s, r, 1, { p: ctx.p, kind: 'ability' }); addMod(s, c.o, 'ATK', 2, { temp: 1 }); log(s, `${c.o.name} は変異原を自らに放出(攻撃力+2)。`); }
        else mutate(s, r);
      }); break;
      case 'if': run(s, ctx, cond(s, ctx, e.c) ? e.then : (e.else || [])); break;
      case 'remember': forT(s, ctx, e.t, (c) => { if (!c.cmd) ctx.mem = c.o.id; }); break;
      case 'summonRemembered': if (ctx.mem) { summon(s, ctx.p, ctx.mem, { atk: e.a, hp: e.h, maxHp: e.h }); log(s, `${ja(ctx.mem)} の ${e.a}/${e.h} コピーを配備。`); } break;
      case 'noEnergy': s.noEnergyTurn = s.turn; break;
      case 'echo': forT(s, ctx, e.t, (c) => { if (c.cmd) return; for (let i = 0; i < e.n; i++) summon(s, ctx.p, c.o.id, { atk: 1, hp: 1, maxHp: 1 }); log(s, `${ja(c.o.id)} の1/1コピーを${e.n}体作った。`); }); break;
      case 'mirrorWeapon': if (opp.weapon) { me.weapon = { id: opp.weapon.id, a: opp.weapon.a, ch: opp.weapon.ch + 1 }; log(s, `${me.name} は ${ja(opp.weapon.id)} のコピーを装備。`); } break;
      case 'equip': { const w = card(e.id); me.weapon = { id: e.id, a: w.a, ch: w.ch }; log(s, `${me.name} は ${w.ja} を装備。`); break; }
      case 'weaponUp': if (me.weapon) { me.weapon.a += e.a; me.weapon.ch += e.ch; } break;
      case 'stealCypher': if (opp.cyphers.length) { const i = rnd(opp.cyphers.length); const cy = opp.cyphers.splice(i, 1)[0]; me.cyphers.push(cy); log(s, `${me.name} は敵の CYPHER「${ja(cy.id)}」を奪った!`); } break;
      case 'copyEnemyHand': for (let i = 0; i < e.n; i++) { const h = pick(opp.hand); if (h) { addHand(s, ctx.p, h.id); log(s, `${me.name} は相手の手札から ${ja(h.id)} をコピーした。`); } } break;
      case 'dupHand': { const h = pick(me.hand); if (h) addHand(s, ctx.p, h.id); break; }
      case 'reveal': {
        const n = val(s, ctx, e.n);
        for (let i = 0; i < n; i++) {
          const cand = opp.hand.filter(h => !h.rev);
          if (!cand.length) break;
          const blocker = opp.board.find(u => has(u, 'NOREVEAL'));
          if (blocker) { blocker.atk += 1; blocker.maxHp += 1; blocker.hp += 1; log(s, `${ja(blocker.id)} が REVEAL を防いだ(+1/+1)。`); break; }
          const h = pick(cand); h.rev = true; ctx.lastRev = h.uid;
          log(s, `${opp.name} の手札「${ja(h.id)}」が公開された。`);
        }
        break;
      }
      case 'pillageCost': {
        const h = opp.hand.find(x => x.uid === ctx.lastRev);
        if (h) { const n = opp.hand.filter(x => x.rev).length; const base = card(h.id).c + h.cm; const add = Math.max(0, Math.min(n, 10 - base)); h.cm += add; if (add) log(s, `PILLAGE:${ja(h.id)} のコスト+${add}。`); }
        break;
      }
      case 'copyRevealed': { const cheap = ctx.flags && ctx.flags.cheap; for (const h of opp.hand.filter(x => x.rev)) addHand(s, ctx.p, h.id, { cm: cheap ? -1 : 0 }); break; }
      case 'flag': ctx.flags = ctx.flags || {}; ctx.flags[e.k] = true; break;
      case 'setModule': me.modules[e.slot] = { id: e.id, used: false, count: 0 }; log(s, `${me.name} の左端のモジュールが ${MODS[e.id].ja} に置き換わった。`); break;
      case 'extraAttack': forT(s, ctx, e.t, (c) => { if (!c.cmd) c.o.attacks += 1; }); break;
      case 'refresh': forT(s, ctx, e.t, (c) => { if (!c.cmd) { c.o.attacks = Math.max(c.o.attacks, 0) + 1; c.o.sick = false; c.o.disabled = 0; } }); break;
      case 'tacticDiscount': me.tacticDiscount = e.n; break;
      case 'nextDiscount': me.nextDiscount = e.n; break;
      case 'captainsPride': if (!me.board.some(u => has(u, 'SCREEN')) && me.hp > opp.hp && !has(me, 'SCREEN')) { me.kw.SCREEN = 1; me.pride = true; } break;
      case 'boneSpurs': me.bone = true; break;
      case 'atkFromHp': forT(s, ctx, e.t, (c) => { if (!c.cmd) c.o.atk += c.o.hp; }); break;
      case 'cmdAttack': me.attacks += e.n; break;
      case 'maxSupply': me.maxSupply = Math.min(SUPPLY_MAX, me.maxSupply + e.n); me.supply += e.n; log(s, `${me.name} の最大サプライが ${me.maxSupply} になった。`); break;
      case 'creditPay': me.credit = Math.max(0, me.credit - e.n); break;
      case 'stealEnergy': { const n = Math.min(opp.energy, e.n); opp.energy -= n; me.energy += n; break; }
      case 'healFromTarget': forT(s, ctx, e.t, (c) => { if (!c.cmd) heal(s, 'c' + ctx.p, Math.max(0, c.o.hp)); }); break;
      case 'breakWeapon': me.weapon = null; break;
      case 'tuck': forT(s, ctx, e.t, (c) => {
        if (c.cmd) return;
        const pl = s.players[c.p]; pl.board.splice(pl.board.indexOf(c.o), 1);
        const owner = s.players[c.o.owner !== undefined ? c.o.owner : c.p];
        if (!card(c.o.id).token) owner.deck.splice(rnd(owner.deck.length + 1), 0, c.o.id);
        log(s, `${ja(c.o.id)} は山札に戻された。`);
      }); break;
      case 'shuffleIn': me.deck.splice(rnd(me.deck.length + 1), 0, e.id); log(s, `${ja(e.id)} が山札に加わった。`); break;
      default: console.warn('unknown op', e.op);
    }
  }
  function firepower(s, p) { let f = 0; for (const u of s.players[p].board) f += has(u, 'FIREPOWER'); return f; }

  function mutate(s, ref) {
    const c = getChar(s, ref); if (!c || c.cmd) return;
    const list = trigs(c.o, 'mutate');
    if (!list.length) return;
    c.o.mut++;
    log(s, `${ja(c.o.id)} が MUTATE した。`);
    fx(s, { ref, k: 'mutate' });
    for (const f of list) run(s, { p: c.p, self: c.o.uid, srcKind: 'ability' }, f);
  }

  // ---------- サイファー ----------
  function cypherCheck(s, ownerP, on, T) {
    const pl = s.players[ownerP];
    for (let i = 0; i < pl.cyphers.length; i++) {
      const cy = pl.cyphers[i]; const d = card(cy.id).cy;
      if (d.on !== on) continue;
      pl.cyphers.splice(i, 1);
      log(s, `${pl.name} の CYPHER「${ja(cy.id)}」が発動!`);
      fx(s, { ref: 'c' + ownerP, k: 'cypher', id: cy.id });
      run(s, { p: ownerP, T, srcKind: 'tactic' }, d.fx);
      return true;
    }
    return false;
  }

  // ---------- ターン ----------
  function startTurn(s) {
    s.turn++;
    const p = s.active, pl = s.players[p];
    pl.maxSupply = Math.min(SUPPLY_MAX, pl.maxSupply + 1);
    pl.supply = Math.max(0, pl.maxSupply - pl.credit);
    if (pl.credit) log(s, `${pl.name} は CREDIT の返済でサプライを ${pl.credit} 失った。`);
    pl.credit = 0;
    pl.bone = false;
    gainEnergy(s, p, 3 - pl.modules.length);
    pl.attacks = 1;
    pl.modules.forEach(m => { m.used = false; });
    for (const u of pl.board) {
      u.sick = false;
      u.attacks = has(u, 'ASSAULT') ? 2 : 1;
      if (u.disabled) { u.attacks = 0; u.disabled = 0; u.wasDisabled = true; } else u.wasDisabled = false;
    }
    log(s, `── ターン${s.turn}:${pl.name} ──`);
    draw(s, p, 1);
    for (const m of pl.modules) { const d = MODS[m.id]; if (d.start) run(s, { p, srcKind: 'module' }, d.start); }
    for (const u of pl.board.slice()) for (const f of trigs(u, 'startTurn')) run(s, { p, self: u.uid, srcKind: 'ability' }, f);
    resolve(s);
  }

  function endTurn(s) {
    if (s.winner !== null) return;
    const p = s.active, pl = s.players[p];
    for (const u of pl.board.slice()) for (const f of trigs(u, 'endTurn')) { if (findUnit(s, u.uid)) run(s, { p, self: u.uid, srcKind: 'ability' }, f); }
    for (const m of pl.modules) { const d = MODS[m.id]; if (d.end) run(s, { p, srcKind: 'module' }, d.end); }
    resolve(s);
    if (s.winner !== null) return;
    // 一時効果の失効
    for (const x of s.players) {
      x.mods = x.mods.filter(m => m.exp === undefined || m.exp > s.turn);
      for (const u of x.board) {
        u.mods = u.mods.filter(m => m.exp === undefined || m.exp > s.turn);
        u.xt = u.xt.filter(t => t.exp === undefined || t.exp > s.turn);
      }
    }
    // 一時的に奪ったユニットの返却
    for (const x of s.players) for (const u of x.board.slice()) if (u.ctrlBack !== undefined && u.ctrlBack <= s.turn) {
      const back = s.players[u.owner];
      x.board.splice(x.board.indexOf(u), 1);
      delete u.ctrlBack; u.p = u.owner; delete u.owner;
      if (back.board.length < BOARD_MAX) { back.board.push(u); log(s, `${ja(u.id)} のコントロールが戻った。`); } else log(s, `${ja(u.id)} は戻る場所がなく消滅した。`);
    }
    s.active = 1 - p;
    startTurn(s);
  }

  // ---------- 行動判定 ----------
  function canPlay(s, p, h) {
    if (s.winner !== null || s.active !== p || s.phase === 'mulligan') return false;
    const pl = s.players[p], c = card(h.id);
    if (costOf(s, p, h) > pl.supply) return false;
    if (c.t === 'U' && pl.board.length >= BOARD_MAX) return false;
    if (c.needs === 'enemyWeapon' && !s.players[1 - p].weapon) return false;
    if (c.needs === 'ownWeapon' && !pl.weapon) return false;
    if (c.tg && !c.tg.opt && !validTargets(s, p, c.tg, c.t === 'T' ? 'tactic' : 'ability').length) return false;
    return true;
  }
  function moduleCost(m) { const d = MODS[m.id]; return d.ct === 'passive' ? null : { type: d.ct, n: d.c }; }
  function canUseModule(s, p, i) {
    const pl = s.players[p], m = pl.modules[i]; if (!m || s.active !== p || s.winner !== null) return false;
    const d = MODS[m.id]; if (d.ct === 'passive' || m.used) return false;
    if (d.ct === 'supply' && pl.supply < d.c) return false;
    if (d.ct === 'energy' && pl.energy < d.c) return false;
    if (d.tg && !validTargets(s, p, d.tg, 'module').length) return false;
    if (d.id === 'rend_mod' && !s.players[1 - p].board.length) return false;
    return true;
  }
  function canAttack(s, ref) {
    const c = getChar(s, ref); if (!c || c.p !== s.active || s.winner !== null) return false;
    if (c.cmd) return c.o.attacks > 0 && atkOf(s, ref) > 0;
    const u = c.o;
    if (u.attacks <= 0 || has(u, 'PACIFIST') || atkOf(s, ref) <= 0) return false;
    if (u.sick && !has(u, 'MOBILITY')) return false;
    return true;
  }
  function attackTargets(s, ref) {
    const c = getChar(s, ref); if (!c) return [];
    const op = s.players[1 - c.p];
    const vis = op.board.filter(u => !has(u, 'CLOAK'));
    const screens = vis.filter(u => has(u, 'SCREEN')).map(u => u.uid);
    if (has(op, 'SCREEN')) return ['c' + op.idx];
    if (screens.length) return screens;
    return vis.map(u => u.uid).concat(['c' + op.idx]);
  }

  // ---------- 行動 ----------
  function play(s, handUid, T, energize) {
    const p = s.active, pl = s.players[p];
    const hi = pl.hand.findIndex(h => h.uid === handUid); if (hi < 0) return false;
    const h = pl.hand[hi], c = card(h.id);
    if (!canPlay(s, p, h)) return false;
    const srcKind = c.t === 'T' ? 'tactic' : 'ability';
    if (c.tg) {
      const vt = validTargets(s, p, c.tg, srcKind);
      if (T !== undefined && T !== null && !vt.includes(T)) return false;
      if (!c.tg.opt && (T === undefined || T === null)) return false;
    }
    const cost = costOf(s, p, h);
    pl.supply -= cost;
    pl.hand.splice(hi, 1);
    if (c.t === 'T') pl.tacticDiscount = 0;
    pl.nextDiscount = 0;
    pl.st.played++; pl.st.cards[h.id] = (pl.st.cards[h.id] || 0) + 1;
    if (c.kw && c.kw.CREDIT) pl.credit += c.kw.CREDIT;
    let en = null;
    if (energize !== undefined && energize !== null && c.energize && c.energize[energize] && pl.energy >= c.energize[energize].n) {
      en = c.energize[energize]; pl.energy -= en.n;
    }
    log(s, `${pl.name} は ${c.ja} をプレイ${en ? `(ENERGIZE ${en.n})` : ''}。`);
    fx(s, { k: 'play', p, id: h.id });
    for (const u of pl.board.slice()) for (const f of trigs(u, 'cardPlayed')) s.q.push({ k: 'run', p, self: u.uid, fx: f });
    if (c.kw && c.kw.CREDIT) for (const u of pl.board.slice()) for (const f of trigs(u, 'creditPlayed')) s.q.push({ k: 'run', p, self: u.uid, fx: f });
    const ctx = { p, T, srcKind, energized: !!en };
    if (c.t === 'U') {
      const u = summon(s, p, h.id);
      if (u) {
        ctx.self = u.uid;
        if (c.on && c.on.play) run(s, ctx, c.on.play);
        if (en) run(s, ctx, en.fx);
        resolve(s);
        if (findUnit(s, u.uid)) cypherCheck(s, 1 - p, 'enemyUnitPlayed', u.uid);
      }
    } else if (c.t === 'W') {
      pl.weapon = { id: h.id, a: c.a, ch: c.ch };
      if (c.on && c.on.play) run(s, ctx, c.on.play);
    } else {
      if (c.cy) { pl.cyphers.push({ uid: h.uid, id: h.id }); log(s, `${pl.name} は CYPHER を伏せた。`); }
      else {
        if (en && en.pre) run(s, ctx, en.fx);
        if (c.on && c.on.play) run(s, ctx, c.on.play);
        if (en && !en.pre) run(s, ctx, en.fx);
      }
    }
    resolve(s);
    return true;
  }

  function useModule(s, i, T) {
    const p = s.active, pl = s.players[p];
    if (!canUseModule(s, p, i)) return false;
    const m = pl.modules[i], d = MODS[m.id];
    if (d.tg) { const vt = validTargets(s, p, d.tg, 'module'); if (!vt.includes(T)) return false; }
    if (d.ct === 'supply') pl.supply -= d.c; else pl.energy -= d.c;
    m.used = true;
    log(s, `${pl.name} はモジュール「${d.ja}」を使用。`);
    fx(s, { k: 'module', p, id: m.id });
    run(s, { p, T, srcKind: 'module', modCount: m.count }, d.fx);
    m.count++;
    resolve(s);
    return true;
  }

  function attack(s, aRef, tRef) {
    if (!canAttack(s, aRef)) return false;
    if (!attackTargets(s, aRef).includes(tRef)) return false;
    const a = getChar(s, aRef), t = getChar(s, tRef);
    const p = a.p;
    a.o.attacks--;
    gainEnergy(s, p, 1);
    if (!a.cmd) removeKw(a.o, 'CLOAK');
    log(s, `${charName(s, aRef)} が ${charName(s, tRef)} を攻撃。`);
    fx(s, { ref: aRef, k: 'attack', to: tRef });
    if (!a.cmd) for (const f of trigs(a.o, 'attack')) run(s, { p, self: a.o.uid, srcKind: 'ability' }, f);
    if (t.cmd && !a.cmd) { cypherCheck(s, t.p, 'enemyAttackCmd', aRef); resolve(s); if (!getChar(s, aRef) || a.o.hp <= 0 || a.o.dead || s.winner !== null) return true; }
    const aAtk = atkOf(s, aRef);
    const tAtk = t.cmd ? 0 : atkOf(s, tRef);
    const bothUnits = !a.cmd && !t.cmd;
    const ia = has(a.o, 'IGNORE ARMOR') > 0;
    // 隣接(ARC ATTACK)
    let adj = [];
    if (!t.cmd && has(a.o, 'ARC ATTACK')) { const b = s.players[t.p].board; const i = b.indexOf(t.o); adj = [b[i - 1], b[i + 1]].filter(Boolean).map(u => u.uid); }
    damage(s, tRef, aAtk, { p, kind: 'unit', uid: a.cmd ? null : a.o.uid, crit: bothUnits && has(a.o, 'CRITICAL') > 0, ignoreArmor: ia });
    for (const r of adj) damage(s, r, aAtk, { p, kind: 'unit', uid: a.o.uid, ignoreArmor: ia });
    if (!t.cmd && tAtk > 0) damage(s, aRef, tAtk, { p: t.p, kind: 'unit', uid: t.o.uid, crit: bothUnits && has(t.o, 'CRITICAL') > 0, ignoreArmor: has(t.o, 'IGNORE ARMOR') > 0 });
    if (!t.cmd) removeKw(t.o, 'CLOAK');
    if (a.cmd && a.o.weapon) { a.o.weapon.ch--; if (a.o.weapon.ch <= 0) { log(s, `${ja(a.o.weapon.id)} は壊れた。`); a.o.weapon = null; } }
    const victimDead = !t.cmd && (t.o.hp <= 0 || t.o.dead);
    const attackerAlive = a.cmd ? a.o.hp > 0 : (a.o.hp > 0 && !a.o.dead);
    const victimId = t.cmd ? null : t.o.id;
    if (victimDead && attackerAlive && !a.cmd) for (const f of trigs(a.o, 'devour')) s.q.push({ k: 'run', p, self: a.o.uid, fx: f, mem: victimId });
    resolve(s);
    return true;
  }

  function act(s, a) {
    if (s.winner !== null) return false;
    s.fx = [];
    let ok = false;
    if (a.type === 'mulligan') { ok = mulligan(s, a.p, a.uids || []); if (ok && s.mull.every(Boolean)) beginPlay(s); return ok; }
    if (s.phase === 'mulligan') return false;
    if (a.type === 'play') ok = play(s, a.uid, a.T, a.en);
    else if (a.type === 'attack') ok = attack(s, a.from, a.to);
    else if (a.type === 'module') ok = useModule(s, a.i, a.T);
    else if (a.type === 'end') { endTurn(s); ok = true; }
    if (ok && a.type !== 'end') checkWin(s);
    return ok;
  }

  function legalActions(s) {
    const p = s.active, pl = s.players[p], out = [];
    if (s.winner !== null || s.phase === 'mulligan') return out;
    for (const h of pl.hand) {
      if (!canPlay(s, p, h)) continue;
      const c = card(h.id);
      const ens = [null];
      if (c.energize) c.energize.forEach((e, i) => { if (pl.energy >= e.n) ens.push(i); });
      const ts = c.tg ? validTargets(s, p, c.tg, c.t === 'T' ? 'tactic' : 'ability', null) : [];
      const tl = c.tg ? (ts.length ? ts : (c.tg.opt ? [null] : [])) : [null];
      if (c.tg && c.tg.needEn) tl.push(null);
      for (const T of tl) for (const en of ens) out.push({ type: 'play', uid: h.uid, T, en });
    }
    pl.modules.forEach((m, i) => {
      if (!canUseModule(s, p, i)) return;
      const d = MODS[m.id];
      if (d.tg) for (const T of validTargets(s, p, d.tg, 'module')) out.push({ type: 'module', i, T });
      else out.push({ type: 'module', i });
    });
    const attackers = pl.board.map(u => u.uid).concat(['c' + p]);
    for (const r of attackers) if (canAttack(s, r)) for (const t of attackTargets(s, r)) out.push({ type: 'attack', from: r, to: t });
    out.push({ type: 'end' });
    return out;
  }

  // ---------- デッキ ----------
  function poolFor(faction) { return D.cards.filter(c => !c.token && !c.retired && (c.f === faction || c.f === 'NEU')); }
  function modulePoolFor(faction) { return D.modules.filter(m => !m.base && !m.hidden && (m.f === faction || m.f === 'ANY')); }
  function validateDeck(d) {
    const errs = [];
    if (d.cards.length < 25 || d.cards.length > 40) errs.push('デッキは25〜40枚です。');
    const cnt = {};
    d.cards.forEach(id => { cnt[id] = (cnt[id] || 0) + 1; });
    for (const id in cnt) {
      const c = card(id); if (!c) { errs.push('不明なカード: ' + id); continue; }
      if (c.retired) errs.push(`${c.ja} は調査で誤りと分かり除外されたカードです。`);
      else if (c.f !== 'NEU' && c.f !== d.faction) errs.push(`${c.ja} は別勢力のカードです。`);
      const lim = c.r === 'P' ? 1 : 2;
      if (cnt[id] > lim) errs.push(`${c.ja} は${lim}枚までです。`);
    }
    if ((d.modules || []).length > 2) errs.push('追加モジュールは2個まで(基本モジュールと合わせて3個)。');
    return errs;
  }
  function randomDeck(faction, size) {
    faction = faction || pick(Object.keys(BASE_MODULE));
    size = size || 25 + rnd(6);
    const pool = shuffle(poolFor(faction).slice());
    const fac = pool.filter(c => c.f === faction), neu = pool.filter(c => c.f === 'NEU');
    const cards = [];
    const addCopies = (c) => { const lim = c.r === 'P' ? 1 : 2; let n = 0; while (n < lim && cards.length < size) { cards.push(c.id); n++; } };
    // 勢力カードを優先し、コスト曲線が偏りすぎないよう高コストを制限
    let high = 0;
    for (const c of fac.concat(neu)) {
      if (cards.length >= size) break;
      if (c.c >= 7) { if (high >= 4) continue; high += c.r === 'P' ? 1 : 2; }
      if (c.f === 'NEU' && Math.random() < 0.35) continue;
      addCopies(c);
    }
    for (const c of neu) { if (cards.length >= size) break; if (!cards.includes(c.id)) addCopies(c); }
    const mp = shuffle(modulePoolFor(faction).slice());
    const nm = rnd(3);
    return { name: `${D.factions[faction].ja}・ランダム`, faction, cards: cards.slice(0, size), modules: mp.slice(0, nm).map(m => m.id) };
  }

  window.SC = {
    CARDS, MODS, BASE_MODULE, BOARD_MAX, HAND_MAX,
    newGame, act, legalActions, canPlay, canAttack, canUseModule, attackTargets, validTargets,
    atkOf, costOf, has, getChar, findUnit, card, ja, groupsOf, trigs, val,
    randomDeck, validateDeck, poolFor, modulePoolFor, moduleCost, shuffle
  };
})();
