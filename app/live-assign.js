// SPDX-License-Identifier: GPL-3.0-or-later
// LE PÉDALIER S'ASSIGNE SUR /live (2026-09-16, maquette « Designer allégé », écrans 7 et 8).
//
// La grille de Live EST le pédalier, pavé par pavé : assigner ailleurs obligeait à faire correspondre
// de tête un plan et une pédale. Une puce ✎ Assign dans la barre du haut ouvre l'éditeur — le MÊME
// composant que l'onglet du Designer d'hier — par-dessus la page, et un tap en sort.
//
// ⚠ ICI ON ÉCRIT LE PRESET, PAS LA SANDBOX. Le Designer, lui, édite son brouillon (`presets/.sandbox.json`,
// CLAUDE.md) : si son brouillon porte CE preset, une sauvegarde d'ici serait écrasée à sa prochaine
// audition. On fait donc les trois gestes que fait déjà « ＋ New scene for a part » : écrire le preset,
// pousser la même mutation dans la sandbox si elle porte ce preset, et l'enfiler pour un Designer qui
// s'ouvrirait plus tard (`queueDraftMutation`).
import { html, useState, useEffect, useRef, useAsync, cls, esc, LIVE_PALETTE, savePresetEverywhere } from './lib.js';
import { Icon } from './icons.js';
import { PedalboardEditor } from './designer-pedalboard.js';
import { ICON, ROLE_ICON, hydrateBlockMeta, laneIdentity, laneLineName, laneMutedIn } from './designer-model.js';
import { pbItemsOf, pbServicesOf, pbPut, pbRemove, pbFree, pbMoveSwitch, pbAddService, pbOwnedOf } from './pedalboard-model.js';

export function LiveAssign({ presetId, inputmap, onClose }) {
  const { data: fxData } = useAsync(() => fetch('/api/effects').then(r => r.json())
    .then(d => { hydrateBlockMeta(d.effects || d, d); return d; }), []);
  const { data: loaded } = useAsync(() => presetId
    ? fetch('/api/preset/' + encodeURIComponent(presetId)).then(r => r.ok ? r.json() : null).catch(() => null)
    : Promise.resolve(null), [presetId]);
  const [p, setP] = useState(null);
  const [said, setSaid] = useState('');
  const timer = useRef(null);
  useEffect(() => { if (loaded && loaded.id) setP(loaded); }, [loaded && loaded.id]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const fx = (fxData && (fxData.effects || fxData)) || [];
  const fxDef = type => (fx || []).find(e => e.type === type) || {};
  const fxIcon = type => type === 'click' ? html`<span class="tile-svg"><${Icon} id="metronome" /></span>`
    : (ICON[type] || fxDef(type).icon || '▫');

  // une mutation = un document neuf + une sauvegarde débouncée (tirer une case ne coûte pas un POST
  // par pixel), et la MÊME mutation rejouée dans le brouillon du Designer
  const upd = mut => {
    setP(prev => {
      if (!prev) return prev;
      const n = structuredClone(prev);
      mut(n);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => save(n, mut), 450);
      return n;
    });
  };
  const save = async (doc, mut) => {
    const r = await savePresetEverywhere(doc, mut);        // fichier + Designer ouvert plus tard + Designer ouvert maintenant
    if (r && r.error) { setSaid('✗ ' + r.error); setTimeout(() => setSaid(''), 2500); return; }
    setSaid('✓ saved'); setTimeout(() => setSaid(''), 1200);
  };

  // AU GABARIT DU MIXER (2026-10-15) : un panneau SOUS le top menu, plus un calque par-dessus — le top menu reste
  // visible et cliquable (un tap dessus ferme le panneau, live-tools.js)
  const head = (sub, extra) => html`<section class="card-panel lmx-head">
    <b>Assigning the pedalboard</b>${sub ? html`<span class="lmx-dest">${sub}</span>` : ''}
    <span class="lmx-spacer" />${extra || ''}<button class="chip" onClick=${onClose}>Done</button></section>`;
  if (!presetId) return html`<div class="lmx lva2">${head()}
    <section class="card-panel lva-empty"><b>No preset loaded</b><p>Load a song first: the switches belong to a preset.</p></section></div>`;
  if (!p) return html`<div class="lmx lva2">${head()}<section class="card-panel lva-empty"><b>Loading the preset…</b></section></div>`;

  const lanes = p.lanes || [];
  const laneTitle = L => (L && L.name) || (L && L.id) || '';
  const sceneIdx = Math.max(0, (p.scenes || []).findIndex(s => s.id === ((p.scenes || [])[0] || {}).id));
  return html`<div class="lmx lva2">
    ${head(esc(p.name || p.id) + ' · drag a block from one switch to another', said ? html`<span class="lva-said">${said}</span>` : '')}
    <section class="card-panel lva-body">
      <${PedalboardEditor} items=${pbItemsOf(p, laneTitle)} services=${pbServicesOf(p, fx)}
        scenes=${p.scenes || []} sceneIdx=${sceneIdx}
        colorOf=${(k, i) => { const n = +k; const s = n <= 5 ? (p.scenes || [])[n - 1] : null;
          return (p.colors || {})[s ? s.id : k] || LIVE_PALETTE[i % 5]; }}
        looperOwned=${pbOwnedOf(p)} fxDef=${fxDef} fxIcon=${fxIcon}
        onPut=${(id, sw) => upd(x => pbPut(x, id, sw))}
        onRemove=${id => upd(x => pbRemove(x, id))}
        onMoveSwitch=${(a, b) => upd(x => pbMoveSwitch(x, a, b))}
        onAddService=${(t, sw) => upd(x => pbAddService(x, t, sw))}
        onFreeSwitch=${sw => upd(x => pbFree(x, sw))}
        sceneLines=${sc => lanes.map(L => ({ g: ICON[(laneIdentity(L, sc) || {}).type] || ROLE_ICON[L.role] || '•',
          t: laneLineName(p, L, sc), lane: L.role, laneId: L.id, off: laneMutedIn(sc, L) }))}
        onSettings=${null} />
    </section>
  </div>`;
}
