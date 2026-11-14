// SPDX-License-Identifier: GPL-3.0-or-later
// LIBRARY ▸ KEYS, LES BRIQUES COMMUNES (docs/preset-preview.md §9.1, maquette validée le 2026-11-14) : chaque son
// clavier DESSINÉ par golem-fx (keysUnit : piano droit, clavier FM et ses familles — tine, reed, clav, clavecin,
// mallet —, orgue à tirettes, synthé à la couleur de son style) et ENTENDU par sa démo : la phrase MIDI de référence
// rendue à travers l'instrument seul (bridge/sound_preview.py). Ici : le dessin, le lecteur (une démo à la fois) et
// la barre qui dit ce qui joue.
import { html, useState, useEffect } from './lib.js';
import { GP } from './tones-ui.js';

/** un dessin keysUnit (chaîne SVG) ; '' tant que les visuels ne sont pas chargés */
export const keysSvg = opts => { const P = GP(); return P && P.keysUnit ? P.keysUnit(opts) : ''; };

/** la valeur de chaque macro d'un preset Vital, pour les potards du dessin */
export const macrosOf = s => (s.macros || []).map((name, i) => ({ name, value: (s.macro_vals || [])[i] || 0 }));

const mmss = t => { t = Math.max(0, Math.round(t || 0)); return Math.floor(t / 60) + ':' + String(t % 60).padStart(2, '0'); };
export const dur = s => (s && s.seconds ? mmss(s.seconds) : '');

// UN lecteur pour toute la Library ▸ Keys : toucher un autre son coupe le précédent
let _audio = null;
const audio = () => (_audio = _audio || new Audio());

/** le lecteur : play(son) lance sa démo (ou l'arrête si c'est elle qui joue) ; `cur` = le son qui joue */
export function useClip() {
  const [st, setSt] = useState({ cur: null, playing: false, t: 0, d: 0 });
  useEffect(() => {
    const a = audio();
    const tick = () => setSt(s => ({ ...s, t: a.currentTime, d: a.duration || s.d }));
    const end = () => setSt(s => ({ ...s, playing: false, t: 0 }));
    a.addEventListener('timeupdate', tick); a.addEventListener('ended', end);
    return () => { a.removeEventListener('timeupdate', tick); a.removeEventListener('ended', end); a.pause(); };
  }, []);
  const play = s => {
    if (!s || !s.clip) return;
    const a = audio();
    if (st.cur && st.cur.sound === s.sound && st.playing) { a.pause(); setSt(x => ({ ...x, playing: false })); return; }
    if (!st.cur || st.cur.sound !== s.sound) { a.src = s.clip; a.currentTime = 0; }
    a.play().then(() => setSt(x => ({ ...x, cur: s, playing: true, d: a.duration || s.seconds || 0 })))
      .catch(() => setSt(x => ({ ...x, cur: s, playing: false })));
    setSt(x => ({ ...x, cur: s }));
  };
  const playing = s => !!(s && st.cur && st.cur.sound === s.sound && st.playing);
  return { st, play, playing };
}

/** l'indicateur d'un son : l'égaliseur quand il joue, ▶ quand il a une démo */
export const Mark = ({ on, s }) => on ? html`<b class="tn-eq" aria-hidden="true"><i></i><i></i><i></i></b>`
  : s && s.status === 'ready' ? html`<span class="ky-play" aria-hidden="true">▶</span>` : '';

/** la barre du bas : ce qui joue, la phrase, où on en est */
export function ClipBar({ cl, hint }) {
  const s = cl.st.cur;
  if (!s) return html`<div class="ky-bar muted">${hint || 'Touch a sound to hear it: the same phrase plays through every sound of its kind.'}</div>`;
  const pct = cl.st.d ? Math.min(100, 100 * cl.st.t / cl.st.d) : 0;
  return html`<div class="ky-bar">
    <button class="ky-pp" onClick=${() => cl.play(s)} aria-label=${cl.st.playing ? 'Pause' : 'Play'}>${cl.st.playing ? '❚❚' : '▶'}</button>
    <span class="ky-now"><b>${s.title || s.name}</b><small>${s.phrase ? 'phrase: ' + s.phrase : ''}</small></span>
    <span class="ky-prog" aria-hidden="true"><i style=${'width:' + pct + '%'}></i></span>
    <span class="ky-time">${mmss(cl.st.t)} / ${mmss(cl.st.d || s.seconds)}</span>
  </div>`;
}
