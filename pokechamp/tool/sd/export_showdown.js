// Pokémon Showdown（Champions mod）から、使用可能なポケモン・技・特性・持ち物のデータを書き出す。
//   git clone https://github.com/smogon/pokemon-showdown && cd pokemon-showdown && npm install && node build
//   node export_showdown.js <pokemon-showdownのフォルダ> <出力.json>
// 関数で書かれた仕様（basePowerCallback, onModifyAtk など）は名前だけを書き出し、battle.py / calc.py 側で実装する。
const path = require('path');
const fs = require('fs');
const root = path.resolve(process.argv[2]);
const {Dex} = require(path.join(root, 'dist/sim'));
const d = Dex.mod('champions');

function plain(o, depth = 0) {
  if (o === null || o === undefined) return o;
  if (typeof o === 'function') return '__fn__';
  if (Array.isArray(o)) return o.map(x => plain(x, depth + 1));
  if (typeof o === 'object') {
    if (depth > 4) return '__deep__';
    const r = {};
    for (const k of Object.keys(o)) {
      const v = o[k];
      if (v === undefined) continue;
      r[k] = plain(v, depth + 1);
    }
    return r;
  }
  return o;
}
function callbacks(o) {
  const out = [];
  for (const k of Object.keys(o)) if (typeof o[k] === 'function') out.push(k);
  for (const sub of ['condition', 'self', 'secondary']) {
    if (o[sub] && typeof o[sub] === 'object') {
      for (const k of Object.keys(o[sub])) if (typeof o[sub][k] === 'function') out.push(sub + '.' + k);
    }
  }
  return out;
}

const species = d.species.all().filter(s => !s.isNonstandard && s.tier !== 'Illegal');
const learn = new Set();
const learnsets = {};
for (const s of species) {
  const ls = d.species.getLearnsetData(s.id);
  let moves = ls && ls.learnset ? Object.keys(ls.learnset) : [];
  if (!moves.length && s.baseSpecies !== s.name) {
    const b = d.species.getLearnsetData(d.species.get(s.baseSpecies).id);
    moves = b && b.learnset ? Object.keys(b.learnset) : [];
  }
  learnsets[s.id] = moves.filter(m => !d.moves.get(m).isNonstandard);
  learnsets[s.id].forEach(m => learn.add(m));
}
const moveKeys = ['name', 'num', 'type', 'category', 'basePower', 'accuracy', 'pp', 'priority', 'target', 'flags',
  'critRatio', 'willCrit', 'drain', 'recoil', 'heal', 'selfSwitch', 'forceSwitch', 'multihit', 'multiaccuracy',
  'status', 'volatileStatus', 'sideCondition', 'slotCondition', 'weather', 'terrain', 'pseudoWeather', 'boosts',
  'self', 'secondaries', 'selfdestruct', 'ohko', 'hasCrashDamage', 'mindBlownRecoil', 'struggleRecoil',
  'ignoreDefensive', 'ignoreEvasion', 'ignoreImmunity', 'ignoreAbility', 'overrideOffensiveStat', 'overrideOffensivePokemon',
  'overrideDefensiveStat', 'breaksProtect', 'stallingMove', 'sleepUsable', 'thawsTarget', 'damage', 'selfBoost',
  'hasSheerForce', 'hasSheerForceBoost', 'smartTarget', 'tracksTarget', 'stealsBoosts', 'condition', 'shortDesc', 'desc'];
const moves = {};
for (const id of [...learn].sort()) {
  const m = d.moves.get(id);
  const o = {};
  for (const k of moveKeys) if (m[k] !== undefined && m[k] !== null && (m[k] !== false || k === 'ignoreImmunity')) o[k] = plain(m[k]);
  if (o.condition) o.condition = {duration: m.condition.duration, callbacks: callbacks(m.condition)};
  o.callbacks = callbacks(m);
  moves[id] = o;
}
const abilities = {};
for (const s of species) for (const a of Object.values(s.abilities)) {
  const ab = d.abilities.get(a);
  if (!abilities[ab.id]) abilities[ab.id] = {name: ab.name, num: ab.num, shortDesc: ab.shortDesc, desc: ab.desc,
    flags: plain(ab.flags), callbacks: callbacks(ab)};
}
const items = {};
for (const it of d.items.all()) {
  if (it.isNonstandard) continue;
  items[it.id] = {name: it.name, num: it.num, shortDesc: it.shortDesc, desc: it.desc, megaStone: plain(it.megaStone),
    isBerry: !!it.isBerry, fling: plain(it.fling), naturalGift: plain(it.naturalGift), callbacks: callbacks(it),
    boosts: plain(it.boosts)};
}
const sp = {};
for (const s of species) sp[s.id] = {name: s.name, num: s.num, baseSpecies: s.baseSpecies, forme: s.forme, types: s.types,
  baseStats: s.baseStats, abilities: s.abilities, weightkg: s.weightkg, isMega: !!s.isMega, requiredItem: s.requiredItem,
  tier: s.tier, gender: s.gender || undefined};
const conditions = {};
for (const id of ['brn', 'par', 'slp', 'frz', 'psn', 'tox', 'confusion', 'flinch', 'trapped', 'partiallytrapped',
  'sandstorm', 'raindance', 'sunnyday', 'snowscape', 'stall']) {
  const c = d.conditions.get(id);
  conditions[id] = {duration: c.duration, callbacks: callbacks(c)};
}
fs.writeFileSync(process.argv[3], JSON.stringify({species: sp, learnsets, moves, abilities, items, conditions}, null, 0));
console.log('species', species.length, 'moves', Object.keys(moves).length, 'abilities', Object.keys(abilities).length,
  'items', Object.keys(items).length);
