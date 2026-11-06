// SPDX-License-Identifier: GPL-3.0-or-later
// L'ACCORDEUR de /live, sorti de page-live.js le 2026-10-15 : les deux vues (pédalier, Timeline) l'ouvrent par le même
// bouton (live-tools.js) — un composant partagé ne peut pas vivre dans un fichier qui importe celui qui l'utilise.
import { html, useState, useEffect, useRef, cls, esc } from './lib.js';

// Les cordes affichées suivent le RÔLE de la lane écoutée (state.tuner.role, posé par le bridge) :
// guitare 8 cordes (F#1 → E4, les 6 cordes en sont le haut) ou basse 5 cordes (B0 → G2).
// La détection reste chromatique : une puce s'allume seulement si la note tombe sur une corde.
const NOTE_SHARP = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const NOTE_FLAT = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];
const TUNER_STRINGS = {
  guitar: [['F#', 1], ['B', 1], ['E', 2], ['A', 2], ['D', 3], ['G', 3], ['B', 3], ['E', 4]],
  bass:   [['B', 0], ['E', 1], ['A', 1], ['D', 2], ['G', 2]],
};
export function TunerOverlay({ t, onClose, panel = false }) {   // exporté : rendu à part par les vérifications
  const [disp, setDisp] = useState({ cents: 0, note: null, octave: null, freq: 0 });
  const pend = useRef({ note: null, n: 0 });
  useEffect(() => {
    if (!(t.active && t.note)) return;
    const raw = Math.max(-50, Math.min(50, t.cents || 0));
    setDisp(d => {
      const same = d.note === t.note && d.octave === t.octave;
      if (!same) {                                   // note différente : 3 confirmations avant bascule
        pend.current = pend.current.note === t.note ? { note: t.note, n: pend.current.n + 1 }
                                                    : { note: t.note, n: 1 };
        if (pend.current.n < 3) return d;
      }
      pend.current = { note: null, n: 0 };
      const k = same ? 0.25 : 1;                     // lissage seulement à note stable
      return { note: t.note, octave: t.octave, cents: d.cents + (raw - d.cents) * k,
               freq: d.freq + ((t.freq || 0) - d.freq) * (same ? 0.25 : 1) };
    });
  }, [t.seq]);

  const active = t.active && disp.note;
  const cents = disp.cents;
  const inTune = active && Math.abs(cents) <= 4;
  const flat = active && cents < -4, sharp = active && cents > 4;
  // arc gradué : 11 segments de -50 à +50 ¢, celui qui contient la mesure s'allume
  const seg = Math.round((cents + 50) / 100 * 10);
  // LES CORDES DE L'ACCORDAGE CHOISI (2026-10-08) : le bloc Tuner de la lane porte un accordage (table copiée
  // de golem.fm) — 6, 7 ou 8 cordes, basse 4 ou 5 ; sans lui, l'ancienne liste par rôle. On compare en MIDI : le
  // JSFX nomme en dièses (« D# »), l'accordage peut être en bémols (« Eb ») — c'est la même corde.
  const tmidi = (t.tuning && Array.isArray(t.tuning.midi) && t.tuning.midi.length) ? t.tuning.midi : null;
  const flats = !!(t.tuning && /(^|-)eb(-|$)/.test(t.tuning.id || ''));   // eb-std, bass-4-eb : les cordes se lisent en bémols
  const strings = tmidi ? tmidi.map(m => [(flats ? NOTE_FLAT : NOTE_SHARP)[m % 12], Math.floor(m / 12) - 1, m])
    : TUNER_STRINGS[t.role === 'bass' ? 'bass' : 'guitar'].map(([n, o]) => [n, o, 12 * (o + 1) + NOTE_SHARP.indexOf(n)]);
  const heard = active ? 12 * ((disp.octave ?? 0) + 1) + NOTE_SHARP.indexOf(String(disp.note).replace('♯', '#')) : null;
  // PANNEAU (2026-10-15) : l'accordeur ne prend plus tout l'écran — il s'ouvre SOUS le top menu, au gabarit du
  // Mixer (en-tête « Tuner » + Done) ; un tap sur le top menu le ferme (live-tools.js). Sans `panel` : l'ancien plein écran.
  const body = html`${active ? html`
      <div class="tuner-gauge">
        ${Array.from({ length: 11 }, (_, i) => html`<span class=${cls('tg-seg',
          i === 5 && 'mid', active && i === seg && (inTune ? 'lit ok' : 'lit'),
          active && !inTune && ((i < 5 && flat && i >= seg) || (i > 5 && sharp && i <= seg)) && 'trail')}></span>`)}
      </div>
      <div class=${cls('tuner-note', inTune && 'intune')}>${flats && NOTE_SHARP.includes(disp.note) ? NOTE_FLAT[NOTE_SHARP.indexOf(disp.note)] : disp.note}<sub>${disp.octave ?? ''}</sub></div>
      <div class="tuner-dir">
        <span class=${cls('td-arrow', flat && 'on')}>◀ tune up</span>
        <span class=${cls('td-ok', inTune && 'on')}>● IN TUNE</span>
        <span class=${cls('td-arrow', sharp && 'on')}>tune down ▶</span>
      </div>
      <div class="tuner-cents">${cents > 0 ? '+' : ''}${Math.round(cents)}¢ · ${Math.round(disp.freq)} Hz</div>
    ` : html`<div class="tuner-listen">listening…</div>`}
    <div class="tuner-strings">
      ${strings.map(([n, o, m], i) => html`<span class=${cls('ts-chip',
        active && heard === m && 'on')}>${strings.length - i}<b>${n}</b></span>`)}
    </div>
    ${t.tuning ? html`<div class="tuner-tuning">${esc(t.tuning.label)}</div>` : ''}`;
  if (panel) return html`<div class="lmx ltn">
    <section class="card-panel lmx-head">
      <b>Tuner</b>
      <span class="lmx-dest">${t.role ? 'listening to the ' + esc(t.role) + ' lane' : 'listening'}</span>
      <span class="lmx-spacer" />
      <button class="chip" onClick=${onClose}>Done</button>
    </section>
    <section class="card-panel ltn-body">${body}</section>
  </div>`;
  return html`<div class="tuner" onClick=${onClose}>
    <button class="close tuner-x" onClick=${e => { e.stopPropagation(); onClose(); }}>×</button>
    ${body}
    <div class="tuner-hint">tap to close</div>
  </div>`;
}

