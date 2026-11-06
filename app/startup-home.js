// SPDX-License-Identifier: GPL-3.0-or-later
// L'ACCUEIL AU DÉMARRAGE, côté /live (maquette mockups/startup-home.html, écran 3) : le chip ⌂ dit ce que golem
// ouvre au démarrage ; au tap, la feuille des trois politiques — cet objet / le dernier joué / la bank 00 — et
// « Clear ». L'objet se POSE depuis son menu ⋯ (Designer, lignes de presets et de chansons), pas ici.
import { html, useState, post, del, cls, esc } from './lib.js';
import { chipLabel } from './startup-model.mjs';

const KIND = { preset: 'preset', patch: 'patch', song: 'song', setlist: 'setlist', bank: 'bank' };

export function StartupChip({ st }) {
  const s = (st && st.startup) || { policy: 'bank0', home: null };
  const [open, setOpen] = useState(/[?&]home=open/.test(location.search));   // ?home=open : la feuille ouverte d'emblée (captures de vérification)
  const [busy, setBusy] = useState(false);
  const h = s.home;
  const setPolicy = async policy => { setBusy(true); await post('/api/startup', { policy }).catch(() => {}); setBusy(false); };
  const clear = async () => { setBusy(true); await del('/api/startup/home').catch(() => {}); setBusy(false); setOpen(false); };
  const title = s.policy === 'last' ? 'at startup: the last one played — tap to change'
    : s.policy === 'home' && h ? (h.missing ? 'at startup: « ' + (h.name || h.id) + ' » is ' + h.missing + ' — the first bank plays instead. Tap to change'
                                            : 'at startup: ' + KIND[h.kind] + ' « ' + (h.name || h.id) + ' » — tap to change')
    : 'at startup: the first bank of the active setlist — tap to change';
  return html`<span class=${cls('live-inf', 'live-home', s.policy === 'home' && h && h.missing && 'warn')} title=${title}
      onClick=${() => setOpen(true)}>${chipLabel(s)}</span>
    ${open ? html`<div class="sc-audio-overlay" onClick=${() => setOpen(false)}>
      <div class="sc-audio-dialog sh-sheet" onClick=${e => e.stopPropagation()}>
        <h2>What golem opens at startup</h2>
        <p class="sub">On /live, once the engine and the sound card are up. One choice, for every start.</p>
        ${h ? html`<div class=${cls('sh-opt', s.policy === 'home' && 'rec')} onClick=${() => !busy && setPolicy('home')}>
          <span class="r"></span><div><b>${esc(h.name || h.id)} <span class="kind">${KIND[h.kind]}</span></b>
            <span>${h.missing ? '⚠ ' + h.missing + ' — the first bank plays instead until you pick another one.' : 'Set from its ⋯ menu. A song also loads its arrangement; a setlist, its first bank.'}</span></div></div>`
          : html`<div class="sh-opt dim"><span class="r"></span><div><b>An object of yours</b><span>Pick it from its ⋯ menu — a preset or patch in the Designer, a preset or song in its list.</span></div></div>`}
        <div class=${cls('sh-opt', s.policy === 'last' && 'rec')} onClick=${() => !busy && setPolicy('last')}>
          <span class="r"></span><div><b>The last one played before golem was stopped</b><span>Whatever was on /live at shutdown — preset, patch or song — comes back.</span></div></div>
        <div class=${cls('sh-opt', s.policy === 'bank0' && 'rec')} onClick=${() => !busy && setPolicy('bank0')}>
          <span class="r"></span><div><b>The first bank of the active setlist</b><span>The first bank that holds something — bank 00 when it does. The default when nothing is set.</span></div></div>
        <div class="sh-acts">${h ? html`<button disabled=${busy} onClick=${clear}>Clear the startup choice</button>` : ''}<button class="p" onClick=${() => setOpen(false)}>Done</button></div>
      </div></div>` : ''}`;
}
