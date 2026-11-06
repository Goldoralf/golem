// SPDX-License-Identifier: GPL-3.0-or-later
// La comparaison de deux configurations de carte (docs/card-setups-exchange.md, maquette mockups/soundcard-sync.html) :
// pur, testé (card-setups-model.test.mjs). `local` et `sibling` ont la forme du contrat {inputs, outputs, midi_in,
// midi_out} ; les icônes viennent du catalogue d'instruments de l'input map (jamais une table ici) ; les personnes
// du roster ({id: name}) — un id inconnu s'affiche tel quel, en italique c'est à l'écran de le dire.

export const iconOf = (role, instruments) => {
  const it = (instruments || []).find(i => i.id === role);
  return it ? (it.icon || '') : (role === 'none' || !role ? '·' : '');
};

// « 🎤 Voice 1 · alex » — le libellé d'une entrée ou d'une sortie telle que la carte la nomme
export const labelOf = (e, instruments, people) => {
  if (!e) return '—';
  const role = e.role || 'none';
  const nm = e.name || (role === 'none' ? 'unassigned' : role);
  const who = e.person ? ' · ' + ((people || {})[e.person] || e.person) : '';
  const ic = iconOf(role, instruments);
  return (ic ? ic + ' ' : '') + nm + who;
};

const outLabel = (o, people) => {
  if (!o) return '—';
  const t = o.type ? ' (' + o.type + ')' : '';
  const who = o.person ? ' · ' + ((people || {})[o.person] || o.person) : '';
  return (o.role || 'other') + t + who;
};

const key = (e, kind) => e.slot || ((kind === 'in' ? 'IN ' : 'OUT ') + (e.ch || '?'));
const sameIn = (a, b) => !!a && !!b && (a.role || 'none') === (b.role || 'none') && Number(a.nth || 1) === Number(b.nth || 1)
  && (a.person || null) === (b.person || null);
const sameOut = (a, b) => !!a && !!b && (a.role || 'other') === (b.role || 'other') && (a.type || null) === (b.type || null)
  && (a.person || null) === (b.person || null);

// les lignes de la table : entrées audio (les ports USB sont ceux du rack, pas de la carte), sorties, MIDI
export const setupRows = (local, sibling, instruments, people) => {
  const L = local || {}, S = sibling || {};
  const rows = [];
  const ins = e => (e.inputs || []).filter(x => (x.kind || 'audio') === 'audio' && !/^USB/i.test(x.slot || ''));
  const keys = [];
  [...ins(L), ...ins(S)].forEach(e => { const k = key(e, 'in'); if (!keys.includes(k)) keys.push(k); });
  keys.sort((a, b) => parseInt(a.replace(/\D/g, ''), 10) - parseInt(b.replace(/\D/g, ''), 10));
  keys.forEach(k => {
    const a = ins(L).find(e => key(e, 'in') === k) || null, b = ins(S).find(e => key(e, 'in') === k) || null;
    rows.push({ k, here: labelOf(a, instruments, people), there: labelOf(b, instruments, people), same: sameIn(a, b), kind: 'in' });
  });
  const okeys = [];
  [...(L.outputs || []), ...(S.outputs || [])].forEach(o => { const k = key(o, 'out'); if (!okeys.includes(k)) okeys.push(k); });
  okeys.forEach(k => {
    const a = (L.outputs || []).find(o => key(o, 'out') === k) || null, b = (S.outputs || []).find(o => key(o, 'out') === k) || null;
    rows.push({ k, here: outLabel(a, people), there: outLabel(b, people), same: sameOut(a, b), kind: 'out' });
  });
  const midi = m => 'in: ' + (m.midi_in || '—') + ' · out: ' + (m.midi_out || '—');
  rows.push({ k: 'MIDI', here: midi(L), there: midi(S), same: (L.midi_in || null) === (S.midi_in || null) && (L.midi_out || null) === (S.midi_out || null), kind: 'midi' });
  return rows;
};

// le libellé du chip : une proposition passe avant une divergence
export const chipLabel = cs => {
  if (!cs) return null;
  const offers = cs.offers || [];
  if (offers.length) return '⇄ setup offered by ' + (offers[0].from_name || offers[0].from_rack || 'another rack');
  const diff = (cs.siblings || []).filter(s => !s.same && !s.separate);
  if (diff.length) return '⇄ ' + (diff[0].rack_name || 'Rack') + ' setup differs';
  return null;
};
