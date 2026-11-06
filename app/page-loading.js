// SPDX-License-Identifier: GPL-3.0-or-later
// L'ÉCRAN DE CHARGEMENT (maquette mockups/loading.html, 2026-10-11) — à la place de /live tant que le premier
// preset ne joue pas. Il ne lit que des FAITS datés par le bridge (state.boot) ; les délais sont par module
// (app/boot-model.mjs). « Open the app anyway » n'apparaît QUE si quelque chose traîne (« quand il y a une
// erreur, on fait apparaître le bouton ; sinon on va au bout ») — un démarrage normal se finit tout seul.
import { html, useState, post, go } from './lib.js';
import { bootRows } from './boot-model.mjs';

const DOT = { ok: '✓', on: '', wait: '', late: '!', skip: '–' };

export function LoadingPage({ rig, linkLost, onSkip }) {
  const st = (rig && rig.state) || {};
  const [extra, setExtra] = useState({});            // « Keep waiting » : +30 s sur le module qui traîne
  const [busy, setBusy] = useState('');
  const r = bootRows(st, extra);
  const act = async (row, a) => {
    if (a === 'wait') { setExtra(e => ({ ...e, reaper: (e.reaper || 0) + 30, osc: (e.osc || 0) + 30, audio: (e.audio || 0) + 30, preset: (e.preset || 0) + 30 })); return; }
    setBusy(a);
    try {
      if (a === 'restart') await post('/api/system/reaper-restart', {});
      // régler golem.fm / TONE3000 : Settings ▸ Connect ; la licence REAPER : Settings ▸ About ▸ REAPER — l'écran s'efface
      if (a === 'setup') { onSkip(); go(row.id === 'lic' ? 'system/about/reaper' : row.id === 't3k' ? 'system/connect/tone3000' : 'system/connect/golemfm'); }
    } catch (e) { /* l'état WebSocket dira la suite */ }
    setTimeout(() => setBusy(''), 3000);
  };
  const label = { restart: 'Restart REAPER', wait: 'Keep waiting', setup: 'Set up' };
  return html`<div class="ld">
    ${linkLost ? html`<div class="link-lost">⚠ Bridge link lost — reconnecting…</div>` : ''}
    <div class="ld-body">
      <div class="ld-mark" aria-label="loading"><span class="s">/</span><span class="g">loading</span><span class="cur">_</span></div>
      <div class="ld-sub">starting golem${r.os ? ' on ' + r.os : ''}</div>
      <div class="ld-mods">
        ${r.rows.map(row => html`<div class=${'ld-m ' + row.state} key=${row.id}>
          <span class="d">${DOT[row.state] || ''}</span>
          <span class="n">${row.name}</span>
          <span class="t" title=${row.text}>${row.text}</span>
          ${row.state === 'late' && row.actions && row.actions.length ? html`<span class="acts">
            ${row.actions.map(a => html`<button class=${a === 'wait' ? '' : 'p'} disabled=${!!busy} onClick=${() => act(row, a)}>${busy === a ? '…' : label[a]}</button>`)}</span>`
            : html`<span class="ms">${row.ms}</span>`}
        </div>`)}
      </div>
    </div>
    <div class="ld-foot">
      <span>golem${r.os ? ' · ' + r.os : ''}${r.lastTook ? ' · last start took ' + r.lastTook + ' s' : ''} · the app opens by itself when the first preset plays</span>
      ${r.late ? html`<button class="ld-skip" onClick=${onSkip}>Open the app anyway →</button>` : ''}
    </div>
  </div>`;
}
