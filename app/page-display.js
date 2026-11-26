// SPDX-License-Identifier: GPL-3.0-or-later
// SETTINGS ▸ SYSTEM ▸ DISPLAY (décision du 2026-11-25, bridge/display.py) : les animations de l'écran. Une case animée du
// Live fait redessiner l'écran sans arrêt — sur la machine qui joue le son, du temps volé à l'audio (docs/pitfalls/ui.md
// « An endless animation steals the audio thread ») ; sur une machine puissante, rien d'audible. Le choix revient au
// musicien : Auto (défaut : figées ici, animées sur une tablette), On, Off ; et les voyants qui clignotent ou non.
// Le réglage part dans l'état diffusé : chaque écran l'applique sans recharger (app/anim-stepper.mjs).
import { html, useState, useEffect, api, post, cls } from './lib.js';
import { isLocalHost, sortOf } from './anim-stepper.mjs';

const MODES = [
  ['auto', 'Auto', 'Still on the computer that plays the sound, moving on tablets and phones. The safe choice.'],
  ['on', 'On', 'Moving everywhere. For a computer with headroom: check Health for clicks after a song or two.'],
  ['off', 'Off', 'Still everywhere, tablets and phones included.'],
];

// CE QUE MONTRE UNE CASE FIGÉE (docs/anim-packs.md §8.4, 2026-11-26) — Pedals par défaut
const STILL_STYLES = [
  ['pedals', 'Pedals', 'Each stomp shows the pedal of its block; scenes show the still image of their effect.'],
  ['glyphs', 'Glyphs', 'The block symbol, large, in a corner of each tile; scenes show their letter. The plainest.'],
  ['textures', 'Textures', 'Every tile shows the still image of the effect chosen for it in the Designer.'],
];

export function DisplayPanel({ rig }) {
  const st = (rig && rig.state) || {};
  const [d, setD] = useState(st.display || null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { if (!st.display) api('/api/system/display').then(setD).catch(() => {}); }, []);
  useEffect(() => { if (st.display) setD(st.display); }, [st.display && st.display.animations, st.display && st.display.blinks, st.display && st.display.still_tiles]);
  const save = async body => {
    setBusy(true); setErr('');
    const r = await post('/api/system/display', body).catch(e => ({ error: (e.body && e.body.error) || 'refused' }));
    if (r.error) setErr(r.error); else setD({ animations: r.animations, blinks: r.blinks, still_tiles: r.still_tiles });
    setBusy(false);
  };
  if (!d) return html`<div class="dp-page"><div class="hv-m">Reading…</div></div>`;
  const local = isLocalHost(location.hostname);
  const still = sortOf('lp-tile', { tile: true }, { local, display: d }) === 'freeze';
  return html`<div class="dp-page">
    <div class="dp-card">
      <div class="dp-h"><b>Animations of the Live tiles</b>
        <span class="dp-now">Here: ${still ? 'still' : 'moving'} · ${local ? 'this is the computer that plays the sound' : 'this screen draws with its own processor'}</span></div>
      <div class="dp-modes" role="radiogroup" aria-label="Animations">
        ${MODES.map(([id, name, text]) => html`<button key=${id} role="radio" aria-checked=${d.animations === id} disabled=${busy}
            class=${cls('dp-mode edit-only', d.animations === id && 'on')} onClick=${() => d.animations !== id && save({ animations: id })}>
          <i></i><span><b>${name}</b><small>${text}</small></span></button>`)}
      </div>
      <p class="dp-why">Moving tiles redraw the screen non-stop. On the computer that plays the sound, that takes processor time
        from the audio: on a light laptop the sound clicks; on a strong one you hear nothing. If the sound clicks with
        animations on, Health offers to calm the screen.</p>
    </div>
    <div class="dp-card">
      <div class="dp-h"><b>Still tiles</b><span class="dp-now">what a tile shows when it does not move${still ? '' : ' · not used on this screen now'}</span></div>
      <div class="dp-modes" role="radiogroup" aria-label="Still tiles">
        ${STILL_STYLES.map(([id, name, text]) => html`<button key=${id} role="radio" aria-checked=${(d.still_tiles || 'pedals') === id} disabled=${busy}
            class=${cls('dp-mode edit-only', (d.still_tiles || 'pedals') === id && 'on')} onClick=${() => (d.still_tiles || 'pedals') !== id && save({ still_tiles: id })}>
          <i></i><span><b>${name}</b><small>${text}</small></span></button>`)}
      </div>
    </div>
    <div class="dp-card">
      <div class="dp-h"><b>Status lights</b><span class="dp-now">record, warnings, unsaved changes</span></div>
      <button class=${cls('dp-mode dp-tog edit-only', d.blinks && 'on')} role="switch" aria-checked=${d.blinks} disabled=${busy}
          onClick=${() => save({ blinks: !d.blinks })}>
        <i></i><span><b>${d.blinks ? 'They blink' : 'They stay lit'}</b><small>A blink costs almost nothing (two frames a second); off, they stay lit. While tiles are still, they stay lit anyway.</small></span></button>
    </div>
    ${err ? html`<div class="dp-err">Not saved: ${err}</div>` : ''}
  </div>`;
}
