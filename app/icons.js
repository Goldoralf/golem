// SPDX-License-Identifier: GPL-3.0-or-later
// GoleM — pack d'icônes SVG flat monochrome (currentColor, style lucide), remplace les
// EMOJIS partout où des rôles/modes sont affichés — et, depuis le 2026-10-14, les blocs-instruments aussi.
// Taille : 1em (suit le font-size du parent). Clés = rôles du patch + destinations +
// rôles MIDI DIN + ids de modes. `Icon` rend le fallback (emoji du bridge) si clé inconnue.
import { html } from './lib.js';

const S = inner => html`<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;

export const ICONS = {
  // — instruments (entrées) —
  guitar: S(html`<circle cx="8.5" cy="15.5" r="4.5"/><path d="M11.8 12.2 20 4"/><path d="M17.5 3.5 20.5 6.5"/><circle cx="8.5" cy="15.5" r="1" fill="currentColor" stroke="none"/>`),
  bass: S(html`<circle cx="8" cy="16" r="5"/><path d="M11.6 12.4 21 3"/><path d="M18 3.5 20.5 6"/><path d="M6 16h4"/>`),
  voice: S(html`<rect x="9" y="3" width="6" height="10" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>`),
  keys: S(html`<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7.5 5v8"/><path d="M12 5v8"/><path d="M16.5 5v8"/>`),
  drums: S(html`<ellipse cx="12" cy="8.5" rx="8" ry="3.2"/><path d="M4 8.5V16c0 1.8 3.6 3.2 8 3.2s8-1.4 8-3.2V8.5"/>`),
  pads: S(html`<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>`),
  'keys-pads': S(html`<rect x="3.5" y="3.5" width="7.5" height="6" rx="1.4"/><rect x="13" y="3.5" width="7.5" height="6" rx="1.4"/><rect x="3.5" y="12.5" width="17" height="8" rx="1.6"/><path d="M9 12.5v5"/><path d="M15 12.5v5"/>`),
  line: S(html`<path d="M2.5 12c2-4.5 4-4.5 6 0s4 4.5 6 0 4-4.5 7 0"/>`),
  none: S(html`<circle cx="12" cy="12" r="8" stroke-dasharray="3.5 3.5"/>`),
  // — actions live (cluster topbar /live, charte 2026-07-24) —
  // accordeur : le CADRAN d'un accordeur digital (arc gradué + aiguille), pas un cadran
  // rond générique qui se lisait comme un compteur de vitesse.
  tuner: S(html`<path d="M4 17.5a8 8 0 0 1 16 0"/><path d="M12 17.5 13.8 10.8"/><circle cx="12" cy="17.5" r="1.3" fill="currentColor" stroke="none"/><path d="M12 8.7V5.7" opacity=".55"/><path d="M6 11.5 4.3 9.8" opacity=".55"/><path d="M18 11.5l1.7-1.7" opacity=".55"/>`),
  // click : un MÉTRONOME mécanique (corps trapézoïdal, tige, masselotte sur la tige).
  // bloc Drum Kit (docs/drums-kit.md) : grosse caisse de face (deux cercles), caisse claire en bas à gauche,
  // cymbale inclinée en haut à droite — lisible à 18 px sur une tuile, même trait que le métronome du Click
  // — instruments-BLOCS (2026-10-14 : « des icônes plus dans le style du golem » à la place des emojis) —
  synth: S(html`<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M6 11c1.2-3.2 2.4-3.2 3.6 0s2.4 3.2 3.6 0"/><circle cx="16.5" cy="9" r="1.6"/><path d="M3 15h18"/><path d="M7.5 15v5M12 15v5M16.5 15v5"/>`),
  organ: S(html`<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 7v6M10.3 7v4M13.7 7v7M17 7v3"/><circle cx="7" cy="13" r="1" fill="currentColor"/><circle cx="10.3" cy="11" r="1" fill="currentColor"/><circle cx="13.7" cy="14" r="1" fill="currentColor"/><circle cx="17" cy="10" r="1" fill="currentColor"/><path d="M3 17h18"/>`),
  ep: S(html`<path d="M3 10.5c0-3 2-5.5 9-5.5s9 2.5 9 5.5"/><rect x="3" y="10.5" width="18" height="9" rx="2"/><path d="M7.5 10.5v5M12 10.5v5M16.5 10.5v5"/><path d="M8 7.6h8"/>`),
  window: S(html`<rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 9h18"/><path d="M13 14.5l3-3m0 0h-2.4m2.4 0v2.4"/>`),
  timeline: S(html`<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M8 7v10M14 7v10"/><path d="M11 4v16" stroke-width="2.2"/><path d="M9.5 4h3"/>`),
  drumkit: S(html`<circle cx="11" cy="14" r="7"/><circle cx="11" cy="14" r="2.3"/><path d="M14.5 5.5l7-2.2"/><path d="M18 4.4v3.2"/>`),
  // bloc Riff (docs/compo.md) : une FLAMME — l'idée qui prend, qu'on garde avant qu'elle s'éteigne
  riff: S(html`<path d="M12 2.6c.4 2.8 2 4 3.4 5.6 1.3 1.5 2.1 3 2.1 4.8a5.5 5.5 0 0 1-11 0c0-2 .9-3.4 2.1-4.5.2 1 .7 1.7 1.4 2-.1-2.7.6-5.1 2-7.9z"/><path d="M12 11.6c1.3 1.6 2 2.5 2 3.6a2 2 0 0 1-4 0c0-1.1.7-2 2-3.6z"/>`),
  metronome: S(html`<path d="M9.8 3.2h4.4l4 17.4H5.8z"/><path d="M12 18.4 15.2 6.6"/><rect x="12.5" y="11.7" width="2.2" height="1.7" rx=".3" fill="currentColor" stroke="none" transform="rotate(-15 13.6 12.55)"/>`),
  lock: S(html`<rect x="5.5" y="11" width="13" height="9" rx="2"/><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3"/>`),
  unlock: S(html`<rect x="5.5" y="11" width="13" height="9" rx="2"/><path d="M8.5 11V8a3.5 3.5 0 0 1 6.8-1.2"/>`),
  rec: S(html`<circle cx="12" cy="12" r="6.5" fill="currentColor" stroke="none"/>`),
  stop: S(html`<rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" stroke="none"/>`),
  // mixer : trois faders verticaux, curseurs à des hauteurs différentes (docs/mixer.md)
  mixer: S(html`<path d="M6 4v16"/><path d="M12 4v16"/><path d="M18 4v16"/><rect x="4.2" y="8" width="3.6" height="3" rx=".8" fill="currentColor" stroke="none"/><rect x="10.2" y="13" width="3.6" height="3" rx=".8" fill="currentColor" stroke="none"/><rect x="16.2" y="6" width="3.6" height="3" rx=".8" fill="currentColor" stroke="none"/>`),
  // — destinations (sorties) —
  monitors: S(html`<rect x="6" y="3" width="12" height="18" rx="2"/><circle cx="12" cy="14.5" r="3.4"/><circle cx="12" cy="7" r="1.4"/>`),
  pa: S(html`<path d="M3 10.5v3l13.5 4.5v-12L3 10.5Z"/><path d="M18.5 8.5a5 5 0 0 1 0 7"/>`),
  amp: S(html`<path d="M9 3v5"/><path d="M15 3v5"/><rect x="5.5" y="8" width="13" height="8" rx="2"/><path d="M12 16v5"/>`),
  other: S(html`<circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none"/>`),
  // — rôles MIDI DIN —
  fcb: S(html`<rect x="2.5" y="8" width="19" height="9" rx="2"/><circle cx="7" cy="12.5" r="1.4"/><circle cx="12" cy="12.5" r="1.4"/><circle cx="17" cy="12.5" r="1.4"/>`),
  controller: S(html`<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7.5 5v8"/><path d="M12 5v8"/><path d="M16.5 5v8"/>`),
  'whammy-dt': S(html`<path d="M4 18 19 10v8H4Z"/><path d="M14 7l3.5-3.5"/><path d="M17.5 7V3.5H14"/>`),
  // — modes (ids de config/modes/*.json) —
  pedalboard: S(html`<rect x="2.5" y="8" width="19" height="9" rx="2"/><circle cx="7" cy="12.5" r="1.4"/><circle cx="12" cy="12.5" r="1.4"/><circle cx="17" cy="12.5" r="1.4"/>`),
  studio: S(html`<path d="M3 11 12 4l9 7"/><path d="M5.5 9.5V20h13V9.5"/>`),
  // Jam (id historique `accompaniment`) : une boucle qui joue — backing, standards, drums, looper
  accompaniment: S(html`<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 3.5V8h-4.5"/><path d="M10 9v6l5-3z"/>`),
  rehearsal: S(html`<ellipse cx="12" cy="8.5" rx="8" ry="3.2"/><path d="M4 8.5V16c0 1.8 3.6 3.2 8 3.2s8-1.4 8-3.2V8.5"/>`),
  gig: S(html`<rect x="9" y="3" width="6" height="10" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>`),
  // show : le PUPITRE — un écran qui joue une timeline (lecture + barre de position),
  // pas une scène : ce qui distingue Show de Gig, c'est que la machine déroule le set.
  show: S(html`<rect x="2.5" y="4.5" width="19" height="15" rx="2.5"/><path d="M10.2 9.3l4.4 2.5-4.4 2.5z" fill="currentColor" stroke="none"/><path d="M6 17h12" opacity=".5"/>`),
};

ICONS.link = S(html`<path d="M9.5 14.5l5-5"/><path d="M11 7l1-1a3.5 3.5 0 0 1 5 5l-1 1"/><path d="M13 17l-1 1a3.5 3.5 0 0 1-5-5l1-1"/>`);

// Icon : SVG du pack si connu, sinon le fallback (emoji venu du bridge) — jamais de trou.
export const Icon = ({ id, fallback }) => ICONS[id] || (fallback ? html`<span class="ic-fb">${fallback}</span>` : '');

// Icône d'un MODE. Les modes d'usine ont un SVG à leur id (pedalboard/studio/…) ; un mode
// créé par l'utilisateur porte une CLÉ d'icône choisie au picker (`icon`), pas un emoji —
// d'où l'essai en deux temps avant le repli emoji.
export const ModeIcon = ({ mode }) => ICONS[mode.id] || ICONS[mode.icon]
  || (mode.icon ? html`<span class="ic-fb">${mode.icon}</span>` : '');

// Les 8 icônes proposées à la création d'un mode. Volontairement DISJOINTES de celles des
// modes d'usine : l'icône est l'identité du mode (elle part dans le badge de la topbar),
// deux modes ne doivent pas se ressembler.
export const MODE_ICON_CHOICES = ['amp', 'monitors', 'pa', 'rec', 'metronome', 'controller', 'tuner', 'lock'];

// icône FOOTSWITCH monochrome (currentColor) — le badge « au pied » des tuiles (cible devant le n° du switch).
// UNE définition : la tuile Arrangement l'avait réécrite en « SW4 » faute de la trouver (2026-10-01).
export const FOOTSW = () => html`<svg class="footsw-ic" viewBox="0 0 10 10" aria-hidden="true">
  <circle cx="5" cy="5" r="3.6" fill="none" stroke="currentColor" stroke-width="1.4" />
  <circle cx="5" cy="5" r="1.4" fill="currentColor" /></svg>`;
