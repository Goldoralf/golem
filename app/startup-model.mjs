// SPDX-License-Identifier: GPL-3.0-or-later
// L'accueil au démarrage (mockups/startup-home.html) : pur, testé (startup-model.test.mjs). `startup` = state.startup
// {policy: bank0|last|home, home: {kind, id, name, setlist, line, slot, missing}|null}.

const KIND_LABEL = { preset: 'preset', patch: 'patch', song: 'song', setlist: 'setlist', bank: 'bank' };

// le chip de /live : « ⌂ Velvetine », « ⌂ last played », « ⌂ first bank », « ⌂ missing »
export const chipLabel = s => {
  if (!s) return '⌂ first bank';
  if (s.policy === 'last') return '⌂ last played';
  if (s.policy === 'home' && s.home) return s.home.missing ? '⌂ missing' : '⌂ ' + (s.home.name || s.home.id || KIND_LABEL[s.home.kind] || 'home');
  return '⌂ first bank';
};

// cet objet est-il l'accueil ? (clé = kind + id, ou setlist+line pour une chanson, ou slot pour une bank)
export const isHome = (s, key) => {
  const h = s && s.home;
  if (!h || !key || h.kind !== key.kind) return false;
  if (key.kind === 'song') return h.setlist === key.setlist && h.line === key.line;
  if (key.kind === 'bank') return String(h.slot) === String(key.slot);
  return h.id === key.id;
};

// l'entrée du menu ⋯ : ce qu'elle dit, et ce qu'elle remplace
export const menuEntry = (s, key) => {
  if (isHome(s, key)) return { label: '⌂ Opens at startup ✓', small: 'tap to remove', remove: true };
  const h = s && s.home;
  const sm = (key.kind !== 'preset' ? KIND_LABEL[key.kind] : '') + (h && s.policy === 'home' ? (key.kind !== 'preset' ? ' · ' : '') + 'replaces ' + (h.name || h.id || KIND_LABEL[h.kind]) : '');
  return { label: '⌂ Open at startup', small: sm, remove: false };
};
