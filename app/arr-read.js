// SPDX-License-Identifier: GPL-3.0-or-later
// L'ARRANGEMENT EN PISTE, LU — partagé par le détail de ligne des setlists et le tiroir Arrangement du Designer.
import { html, cls, esc } from './lib.js';
import { sectionLook } from './designer-model.js';
import { secSeconds } from './designer-arrangement.js';

const mmss = sec => Math.floor(sec / 60) + ':' + String(Math.floor(sec % 60)).padStart(2, '0');

// ── L'ARRANGEMENT EN PISTE, LU (2026-09-30 : « les sections en ligne qui s'enchaînent — ce qui existe déjà,
// qui est bien, mais en lecture seule ») : LE rendu de la piste de Songs (arr-track, arr-sec, couleur de partie,
// scène dans le bloc), en largeur au temps. Des <div>, jamais des boutons : on ne rend pas un éditeur désactivé
// (CLAUDE.md, `hidden`), on rend une image. Modifier = le lien, vers la chanson.
export function ArrRead({ parts, bpm, preset, onEdit, editLabel, title }) {
  const base = { num: 4, den: 4 };
  const secs = parts.map(p => secSeconds(p, base, bpm || 120));
  const total = secs.reduce((a, x) => a + x, 0) || 1;
  const bars = parts.reduce((a, p) => a + (+p.bars || 0), 0);
  let acc = 0, bar = 1;
  let lastX = -99;                                     // deux débuts trop proches (une demi-mesure de 2/4) : un seul numéro
  const marks = parts.map((p, i) => { const m = { x: acc / total * 100, bar }; acc += secs[i]; bar += (+p.bars || 0); return m; })
    .filter(m => { if (m.x - lastX < 3) return false; lastX = m.x; return true; });
  const scName = id => (((preset || {}).scenes || []).find(x => x.id === id) || {}).name || '';
  return html`<div class="arr-ro" data-doc="arr.read">
    <div class="arr-ro-hd"><b>${title || 'Arrangement'}</b>
      <span class="muted">${parts.length} part${parts.length === 1 ? '' : 's'} · ${bars} bars · ${mmss(total)} at ${+bpm || 120} BPM</span>
      <span class="grow"></span>
      ${onEdit ? html`<button class="linkish" onClick=${onEdit}>${editLabel || 'Edit in the song'} ›</button>` : ''}</div>
    <div class="arr-lanes arr-ro-lane">
      <div class="arr-ruler">${marks.map(m => html`<span class="arr-tick arr-tick-hi" style=${'left:' + m.x.toFixed(3) + '%'}><b>${m.bar}</b></span>`)}</div>
      <div class="arr-track">${parts.map((p, i) => html`<div class=${cls('arr-sec arr-ro-sec', !p.scene && 'arr-nocue')}
          style=${`width:${(secs[i] / total * 100).toFixed(3)}%; --pc:${sectionLook(p).color}; --bars:${Math.max(1, p.bars || 1)}`}
          title=${(p.name || '—') + ' — ' + (p.bars || 0) + ' bars · ' + mmss(secs[i]) + (p.scene ? ' · scene ' + p.scene + (scName(p.scene) ? ' ' + scName(p.scene) : '') : '')}>
        <span class="arr-cap">${esc(p.name || '—')}</span>
        <span class="arr-body arr-grid"><span class="arr-meta">${p.scene ? html`<b class="arr-sc">${p.scene}</b>` : ''} ${p.bars || 0}</span></span>
      </div>`)}</div>
    </div>
  </div>`;
}

