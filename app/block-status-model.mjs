// SPDX-License-Identifier: GPL-3.0-or-later
// signature des blocs d'un document : l'état n'est redemandé que si un bloc, un type ou une capture change
export const blockSig = p => {
  const out = [];
  const walk = o => {
    if (Array.isArray(o)) { o.forEach(walk); return; }
    if (!o || typeof o !== 'object') return;
    if (o.type && o.id) out.push(`${o.id}:${o.type}:${o.ref || ''}:${o.model || ''}:${o.plugin || ''}`);
    for (const k in o) if (k !== 'scenes' && k !== 'params' && k !== 'states') walk(o[k]);
  };
  walk([p && p.lanes, p && p.guitar, p && p.voice, p && p.keys, p && p.config]);
  return out.join('|');
};
