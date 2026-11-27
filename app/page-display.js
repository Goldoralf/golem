// SPDX-License-Identifier: GPL-3.0-or-later
// SETTINGS ▸ SYSTEM ▸ DISPLAY (décision du 2026-11-25, bridge/display.py) : les animations de l'écran. Une case animée du
// Live fait redessiner l'écran sans arrêt — sur la machine qui joue le son, du temps volé à l'audio (docs/pitfalls/ui.md
// « An endless animation steals the audio thread ») ; sur une machine puissante, rien d'audible. Le choix revient au
// musicien : Auto (défaut : figées ici, animées sur une tablette), On, Off ; les voyants qui clignotent suivent (2026-11-27 :
// la carte « What blinks » est retirée, un réglage de moins).
// Le réglage part dans l'état diffusé : chaque écran l'applique sans recharger (app/anim-stepper.mjs).
// + LE PLEIN ÉCRAN AU PREMIER TAP (2026-11-26) : sur tout téléphone ou tablette qui ouvre l'app dans un navigateur, le
// premier tap passe en plein écran et ne fait rien d'autre (app/fullscreen.mjs) ; activé par défaut.
// LA PAGE TIENT SANS DÉFILER (2026-11-26) : deux colonnes — à gauche les cases du Live (animations, cases figées), à droite
// le plein écran des téléphones et tablettes. Chaque choix montre UNE phrase, celle de l'option choisie.
import { html, useState, useEffect, api, post, cls } from './lib.js';
import { isLocalHost, sortOf } from './anim-stepper.mjs';

// AUTO EST UN INTERRUPTEUR, PAS UNE TROISIÈME CASE (2026-11-27) : allumé, il CHOISIT On ou Off pour cet écran (figées
// sur la machine qui joue le son, animées sur une tablette ou un téléphone) et le montre ; toucher l'autre choix l'éteint
// et pose ce choix partout. Le réglage stocké reste auto|on|off (bridge/display.py).
const MODES = [
  ['on', 'On', 'Moving tiles.'],
  ['off', 'Off', 'Still tiles; nothing blinks.'],
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
  const sd = st.display || {};
  useEffect(() => { if (st.display) setD(st.display); }, [sd.animations, sd.still_tiles, sd.fullscreen]);
  const save = async body => {
    setBusy(true); setErr('');
    const r = await post('/api/system/display', body).catch(e => ({ error: (e.body && e.body.error) || 'refused' }));
    if (r.error) setErr(r.error); else setD({ animations: r.animations, still_tiles: r.still_tiles, fullscreen: r.fullscreen });
    setBusy(false);
  };
  if (!d) return html`<div class="dp-page"><div class="hv-m">Reading…</div></div>`;
  const local = isLocalHost(location.hostname);
  const still = sortOf('lp-tile', { tile: true }, { local, display: d }) === 'freeze';
  const stillStyle = d.still_tiles || 'pedals';
  const full = d.fullscreen !== false;
  // un choix parmi trois : des boutons courts, et la phrase de celui qui est choisi dessous
  const seg = (label, list, cur, key, off = false) => html`
    <div class=${cls('dp-seg', off && 'dim')} role="radiogroup" aria-label=${label} aria-disabled=${off}>
      ${list.map(([id, name]) => html`<button key=${id} role="radio" aria-checked=${cur === id} disabled=${busy || off}
          class=${cls('dp-sb edit-only', cur === id && 'on')} onClick=${() => cur !== id && save({ [key]: id })}>${name}</button>`)}
    </div>
    <p class=${cls('dp-say', off && 'dim')}>${(list.find(x => x[0] === cur) || list[0])[2]}</p>`;
  // les animations : Auto choisit pour cet écran ; aller contre son choix l'éteint
  const auto = d.animations === 'auto';
  const eff = still ? 'off' : 'on';                       // ce que cet écran fait en ce moment
  const pickAnim = id => { if (id === eff && auto) return; if (id !== d.animations) save({ animations: id }); };
  const toggle = (on, key, yes, no, text) => html`
    <button class=${cls('dp-sw edit-only', on && 'on')} role="switch" aria-checked=${on} disabled=${busy} onClick=${() => save({ [key]: !on })}>
      <span class="dp-sw-t"><b>${on ? yes : no}</b><small>${text}</small></span><i><em></em></i></button>`;
  return html`<div class="dp-page">
    <div class="dp-card dp-tiles">
      <div class="dp-h"><b>Live tiles</b><span class="dp-now">here: ${still ? 'still' : 'moving'} · ${local ? 'the computer that plays the sound' : 'this screen draws on its own'}</span></div>
      <p class="dp-warn">On some computers, moving tiles make the sound crackle.</p>
      <div class="dp-lbl">Animations</div>
      <div class="dp-anim">
        <div class="dp-seg dp-seg2" role="radiogroup" aria-label="Animations">
          ${MODES.map(([id, name]) => html`<button key=${id} role="radio" aria-checked=${eff === id} disabled=${busy}
              class=${cls('dp-sb edit-only', eff === id && 'on', eff === id && auto && 'auto')} onClick=${() => pickAnim(id)}>
            ${name}${eff === id && auto ? html`<small>auto</small>` : ''}</button>`)}
        </div>
        <button class=${cls('dp-sw dp-auto edit-only', auto && 'on')} role="switch" aria-checked=${auto} disabled=${busy}
            onClick=${() => save({ animations: auto ? eff : 'auto' })} title="golem chooses On or Off for each screen">
          <span class="dp-sw-t"><b>Auto</b></span><i><em></em></i></button>
      </div>
      <p class="dp-say">${auto ? 'golem chooses: still on the computer that plays the sound, moving on tablets and phones. Tap the other choice to decide yourself.'
        : (MODES.find(x => x[0] === eff) || MODES[0])[2] + ' On every screen.'}</p>
      <div class="dp-lbl">A still tile shows${still ? '' : html` <small>· only when the tiles are still (Off)</small>`}</div>
      ${seg('Still tiles', STILL_STYLES, stillStyle, 'still_tiles', !still)}
    </div>
    <div class="dp-side">
      <div class="dp-card">
        <div class="dp-h"><b>Phones and tablets</b></div>
        ${toggle(full, 'fullscreen', 'Full screen at the first tap', 'Full screen: off',
          full ? 'On any phone or tablet that opens golem in a browser, the first tap hides the address and status bars. That tap does nothing else.'
               : 'The app opens with the browser bars. Each device can still go full screen from its own Display page.')}
        <p class="dp-why">A browser never starts in full screen by itself: it needs a tap. After a reload, the first tap again. Not on iPhone (Safari has no full screen).</p>
      </div>
      ${err ? html`<div class="dp-err">Not saved: ${err}</div>` : ''}
    </div>
  </div>`;
}
