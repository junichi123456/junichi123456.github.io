// Runs one turn of a Champions (BSS Reg M-C) battle in Pokémon Showdown with a deterministic "most likely"
// RNG, for differential testing of engine.py.
//   node oracle.js <pokemon-showdown folder>   (JSON scenarios on stdin, one per line; results on stdout)
// RNG policy (must match engine.TestRNG): randomChance(n, d) -> n/d > 1/2; damage roll index 7 (92%);
// random(100) -> 50 (secondaries happen iff chance > 50%); random(a, b) -> a; sample -> most common (first on ties);
// speed ties -> player 2 first.
const path = require('path');
const root = path.resolve(process.argv[2]);
const {Battle} = require(path.join(root, 'dist/sim'));
const readline = require('readline');

function sideOf(x) {
  if (!x) return 0;
  if (x.side && typeof x.side.n === 'number') return x.side.n;
  if (x.pokemon && x.pokemon.side) return x.pokemon.side.n;
  if (x.effectHolder && x.effectHolder.side) return x.effectHolder.side.n;
  if (typeof x.n === 'number') return x.n;
  return 0;
}
let cur = null, curSc = null;
const prng = {
  random(from, to) {
    if (from === undefined) return 0.5;
    if (to === undefined) {
      if (from === 16) return 8;
      if (from === 100) return 50;
      return 0;
    }
    return from;
  },
  randomChance(num, den) { return num / den > 0.5; },
  sample(items) {
    if (items.length && items[0] && items[0].set && curSc) {
      // random switch-in (Roar / Dragon Tail / Red Card): first in original team order, like the engine
      const order = curSc[items[0].side.id].team.map(t => t.species);
      return items.slice().sort((a, b) => order.indexOf(a.set.species) - order.indexOf(b.set.species))[0];
    }
    const cnt = new Map();
    for (const x of items) cnt.set(x, (cnt.get(x) || 0) + 1);
    let best = items[0], bc = -1;
    for (const x of items) { if (cnt.get(x) > bc) { bc = cnt.get(x); best = x; } }
    return best;
  },
  shuffle(list, start = 0, end = list.length) {
    const part = list.slice(start, end);
    part.sort((a, b) => sideOf(b) - sideOf(a));
    for (let i = start; i < end; i++) list[i] = part[i - start];
  },
  next() { return 0; },
  getSeed() { return [0, 0, 0, 0]; },
  get startingSeed() { return [0, 0, 0, 0]; },
  clone() { return prng; },
};

function applyState(battle, side, s) {
  for (let i = 0; i < s.mons.length; i++) {
    const p = side.pokemon[i];
    const d = s.mons[i];
    if (d.hp !== undefined) { p.hp = d.hp; if (!p.hp) { p.fainted = true; p.status = 'fnt'; side.pokemonLeft--; } }
    if (d.status) {
      p.status = d.status;
      p.statusState = battle.initEffectState({id: d.status, target: p});
      if (d.status === 'slp' || d.status === 'frz') { p.statusState.time = d.stime; p.statusState.startTime = d.stime; }
      if (d.status === 'tox') p.statusState.stage = d.tox || 0;
    }
    if (d.boosts) for (const k in d.boosts) p.boosts[k] = d.boosts[k];
    if (d.item !== undefined) p.item = d.item;
  }
  for (const [k, v] of Object.entries(s.cond || {})) {
    side.addSideCondition(k, side.foe.active[0]);
    if (side.sideConditions[k]) {
      if (typeof v === 'number' && ['spikes', 'toxicspikes'].includes(k)) side.sideConditions[k].layers = v;
      else if (typeof v === 'number') side.sideConditions[k].duration = v;
    }
  }
}

function dump(battle) {
  const out = {};
  for (const side of battle.sides) {
    out[side.id] = side.pokemon.map(p => ({
      species: p.transformed ? p.baseSpecies.name : p.species.name, hp: p.hp, status: p.status === 'fnt' ? '' : p.status, item: p.item,
      boosts: Object.fromEntries(Object.entries(p.boosts).filter(([k, v]) => v)), active: p.isActive,
      fainted: p.fainted, ability: p.ability,
    }));
    out[side.id + 'cond'] = Object.fromEntries(Object.entries(side.sideConditions).map(
      ([k, v]) => [k, v.layers || v.duration || true]));
  }
  out.weather = battle.field.weather;
  out.terrain = battle.field.terrain;
  out.pseudo = Object.keys(battle.field.pseudoWeather);
  out.winner = battle.winner;
  out.ended = battle.ended;
  return out;
}

function run(sc) {
  const battle = new Battle({formatid: 'gen9championsbssregmc', seed: [1, 2, 3, 4]});
  battle.prng = prng;
  battle.setPlayer('p1', {team: sc.p1.team});
  battle.setPlayer('p2', {team: sc.p2.team});
  battle.makeChoices('team 123', 'team 123');
  const before = sc.dumpStart ? dump(battle) : null;
  if (sc.field) {
    if (sc.field.weather) { battle.field.weather = sc.field.weather; battle.field.weatherState = battle.initEffectState({id: sc.field.weather, duration: sc.field.wturns || 5}); }
    if (sc.field.weather === '') { battle.field.weather = ''; battle.field.weatherState = battle.initEffectState({id: ''}); }
    if (sc.field.terrain) { battle.field.terrain = sc.field.terrain; battle.field.terrainState = battle.initEffectState({id: sc.field.terrain, duration: sc.field.tturns || 5}); }
    for (const [k, v] of Object.entries(sc.field.pseudo || {})) battle.field.pseudoWeather[k] = battle.initEffectState({id: k, duration: v});

  }
  applyState(battle, battle.p1, sc.p1);
  applyState(battle, battle.p2, sc.p2);
  const log0 = battle.log.length;
  for (let t = 0; t < (sc.turns || 1) && !battle.ended; t++) {
    const ch = sc.choices[t] || sc.choices[0];
    battle.makeChoices(ch[0], ch[1]);
    let guard = 0;
    while (!battle.ended && battle.requestState === 'switch' && guard++ < 6) {
      const choices = [];
      for (const side of battle.sides) {
        const req = side.activeRequest;
        if (!req || req.wait || !req.forceSwitch || !req.forceSwitch[0]) { choices.push('pass'); continue; }
        // same policy as the engine: the first alive benched mon in original team order
        const order = sc[side.id].team.map(t => t.species);
        let best = -1, bo = 99;
        side.pokemon.forEach((p, i) => {
          if (p.fainted || p.isActive) return;
          const o = order.indexOf(p.set.species);
          if (o < bo) { bo = o; best = i; }
        });
        choices.push(best >= 0 ? 'switch ' + (best + 1) : 'pass');
      }
      battle.makeChoices(choices[0], choices[1]);
    }
  }
  const out = dump(battle);
  out.log = battle.log.slice(log0).filter(l => !l.startsWith('|t:|') && !l.startsWith('|split'));
  if (before) out.start = before;
  return out;
}

// session mode: {"cmd":"new", ...scenario without choices} then {"cmd":"turn","choices":[c1,c2]} ...

function turn(battle, sc, ch) {
  try {
    battle.makeChoices(ch[0], ch[1]);
  } catch (e) {
    const info = battle.sides.map(sd => {
      const r = sd.activeRequest || {};
      return {wait: r.wait, fs: r.forceSwitch, trapped: r.active && r.active[0] && r.active[0].trapped,
        moves: r.active && r.active[0] && r.active[0].moves.map(m => m.id + (m.disabled ? '(x)' : '')),
        mons: sd.pokemon.map(p => p.set.species + ':' + p.hp + (p.isActive ? '*' : ''))};
    });
    throw new Error(e.message + ' INFO ' + JSON.stringify(info));
  }
  let guard = 0;
  while (!battle.ended && battle.requestState === 'switch' && guard++ < 6) {
    const choices = [];
    for (const side of battle.sides) {
      const req = side.activeRequest;
      if (!req || req.wait || !req.forceSwitch || !req.forceSwitch[0]) { choices.push('pass'); continue; }
      const order = sc[side.id].team.map(t => t.species);
      const revive = !!side.slotConditions[0]['revivalblessing'];
      let best = -1, bo = 99;
      side.pokemon.forEach((p, i) => {
        if (revive ? !p.fainted : (p.fainted || p.isActive)) return;
        const o = order.indexOf(p.set.species);
        if (o < bo) { bo = o; best = i; }
      });
      choices.push(best >= 0 ? 'switch ' + (best + 1) : 'pass');
    }
    try {
      battle.makeChoices(choices[0], choices[1]);
    } catch (e) {
      throw new Error(e.message + ' choices=' + JSON.stringify(choices) + ' req=' +
        JSON.stringify(battle.sides.map(sd => sd.activeRequest && {fs: sd.activeRequest.forceSwitch, wait: sd.activeRequest.wait,
          rev: !!sd.slotConditions[0]['revivalblessing'], mons: sd.pokemon.map(p => [p.set.species, p.fainted, p.isActive])})));
    }
  }
}
function session(msg) {
  if (msg.cmd === 'new') {
    const sc = msg;
    const battle = new Battle({formatid: 'gen9championsbssregmc', seed: [1, 2, 3, 4]});
    battle.prng = prng;
    battle.setPlayer('p1', {team: sc.p1.team});
    battle.setPlayer('p2', {team: sc.p2.team});
    battle.makeChoices('team 123', 'team 123');
    if (sc.field) {
      if (sc.field.weather) { battle.field.weather = sc.field.weather; battle.field.weatherState = battle.initEffectState({id: sc.field.weather, duration: sc.field.wturns || 5}); }
      if (sc.field.terrain) { battle.field.terrain = sc.field.terrain; battle.field.terrainState = battle.initEffectState({id: sc.field.terrain, duration: sc.field.tturns || 5}); }
      for (const [k, v] of Object.entries(sc.field.pseudo || {})) battle.field.pseudoWeather[k] = battle.initEffectState({id: k, duration: v});
    }
    applyState(battle, battle.p1, sc.p1);
    applyState(battle, battle.p2, sc.p2);
    cur = battle; curSc = sc;
    const out = dump(battle);
    out.order = battle.sides.map(side => side.pokemon.map(p => p.set.species));
    return out;
  }
  const battle = cur;
  const log0 = battle.log.length;
  turn(battle, curSc, msg.choices);
  const out = dump(battle);
  out.log = battle.log.slice(log0).filter(l => !l.startsWith('|t:|') && !l.startsWith('|split') && !l.startsWith('|request'));
  out.order = battle.sides.map(side => side.pokemon.map(p => p.set.species));
  out.moves = battle.sides.map(side => side.active[0] ? side.active[0].moveSlots.map(m => m.id) : []);
  return out;
}

const rl = readline.createInterface({input: process.stdin});
rl.on('line', line => {
  if (!line.trim()) return;
  let res;
  try {
    const msg = JSON.parse(line);
    res = msg.cmd ? session(msg) : run(msg);
  } catch (e) {
    res = {error: String(e && e.stack || e).split('\n').slice(0, 4).join(' | ')};
  }
  process.stdout.write(JSON.stringify(res) + '\n');
});
