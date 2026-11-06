// SPDX-License-Identifier: GPL-3.0-or-later
// Vue CHART de la page Live — la grille du standard, en grand, sur scène.
//
// ── POURQUOI PAS UN MODE ────────────────────────────────────────────────────────────────
// `mode.ui.live` aiguille DÉJÀ la vue (« pedalboard » / « timeline », docs/archive/show-mode.md §6).
// Le mécanisme existait : il fallait une troisième valeur, pas un cinquième mode. Un mode dit
// ce que le RIG fait (quels services, quel matériel, quelle nav) ; une vue dit ce qu'une PAGE
// montre. Créer un mode « grille » aurait mélangé les deux — et il aurait fallu en sortir pour
// jouer le morceau suivant.
//
// ── ET LA VUE EST UNE CONSÉQUENCE, PAS UN CHOIX (2026-08-04) ────────────────────────────
// Il y avait ici un sélecteur `LiveViews` (Pedalboard | Timeline | Chart) publié dans la topbar.
// Il a été retiré : porter un bloc Standard EST la déclaration « ce preset se joue sur sa
// grille », au même titre qu'un bloc qui revendique une entrée ou un switch. Le seul arbitrage
// qui restait — vouloir la grille au mur mais le pédalier à l'écran — est devenu un réglage du
// BLOC (param `live_view`, tiroir ▸ Song), donc une décision de conception, pas un geste de scène.
//
// ── CE QUI NE DOIT PAS PARTIR AVEC LUI ──────────────────────────────────────────────────
// Le sélecteur était aussi le seul chemin de retour. Sans lui, une vue plein écran devient un
// cul-de-sac — la faute déjà payée avec le kiosk sans échappatoire. D'où la barre `BankBar`
// EN HAUT de cette vue : mêmes ◀▶, même BANK #NN, mêmes navigateurs que le pédalier. On change
// de morceau depuis la grille sans passer par le pied.
import { html, useState, useEffect, useAsync, useRef, cls, esc, post } from './lib.js';
import { BankBar } from './live-bankbar.js';
import { ICONS } from './icons.js';                 // les instruments AU TRAIT, jamais d'emoji (2026-10-17)

// Le bloc Standard du preset courant. On lit `standard_block` et pas `standard_switches` :
// le second ne liste que les blocs ASSIGNÉS AU PIED, et un standard lancé depuis l'écran
// aurait alors une page Live sans sa grille.
const stdParams = st => st.standard_block || null;

export function ChartLive({ rig, presets }) {
  const st = rig.state;
  const blk = stdParams(st) || {};
  const [chart, setChart] = useState(null);
  const [live, setLive] = useState(null);
  const playing = live && live.playing;
  // CE QUI JOUE, pas seulement le bloc du preset (2026-10-27, tools/check-use.py) : un standard lancé depuis Library ▸
  // Standards jouait pendant que cette vue montrait la grille du preset, avec le compteur de l'autre — « 12 / 32 » sur
  // une grille de 12 mesures. Quand un AUTRE standard joue, la vue montre le sien, sans les réglages du bloc.
  const other = playing && live.standard && live.standard !== blk.standard ? live.standard : null;
  const p = other ? { standard: other } : blk;
  const slug = p.standard || null;

  useEffect(() => {
    const t = setInterval(() => fetch('/api/standards/state').then(r => r.json())
      .then(setLive).catch(() => {}), playing ? 400 : 2000);
    return () => clearInterval(t);
  }, [playing]);

  const bpm = other ? (live.tempo || null) : (st.bpm || (st.preset && st.preset.bpm));
  useEffect(() => {
    if (!slug) { setChart(null); return; }
    let alive = true;
    fetch('/api/standards/' + encodeURIComponent(slug) + '/preview', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        key: p.key && p.key !== 'Original' ? p.key : null,
        feel: p.feel && p.feel !== 'auto' ? p.feel : null,
        // UN chorus : la grille montre la FORME, le compteur dit quel chorus joue (2026-10-17 : quatre chorus
        // déroulés = 128 mesures écrasées dans l'écran, illisibles)
        choruses: 1, bpm }),
    }).then(r => r.json()).then(r => alive && !r.error && setChart(r)).catch(() => {});
    return () => { alive = false; };
  }, [slug, p.key, p.feel, bpm]);

  // la mesure courante reste VISIBLE : sur scène, chercher où on en est du regard coûte
  // exactement le temps qu'on n'a pas.
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current && ref.current.querySelector('.lvc-bar.on');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }, [live && live.bar]);

  const bars = (chart && chart.bars) || [];
  const rows = [];
  let row = null;
  bars.forEach((b, i) => {
    if (!row || row.section !== b.section || row.cells.length >= 4) {
      row = { section: b.section, cells: [] }; rows.push(row);
    }
    row.cells.push({ ...b, i });
  });
  // L'étiquette de section ne se répète pas : « A1 » huit fois de suite n'informe de rien et
  // vole la seule colonne étroite de la page.
  rows.forEach((r, i) => { r.label = (i === 0 || rows[i - 1].section !== r.section) ? r.section : ''; });
  // la mesure jouée, ramenée dans la forme ; le chorus en cours (1-based) sur le nombre que le bloc joue
  const form = bars.length || 1;
  const cur = playing && live.bar >= 0 ? live.bar % form : -1;
  const chorus = playing && live.bar >= 0 ? Math.floor(live.bar / form) + 1 : 0;
  const choruses = p.choruses || 1;
  // ARRÊTER DEPUIS L'ÉCRAN (2026-10-17 : « à part au pied, pas moyen de couper ») — la vue rend le pédalier
  const stop = () => post('/api/standards/stop').catch(() => {});

  return html`<div class="lvc">
    <${BankBar} rig=${rig} presets=${presets} />
    <div class="lvc-top">
      <span class="lvc-nm">${esc((chart && chart.title) || slug || 'No standard')}</span>
      ${chart ? html`<span class="lvc-m">${esc(chart.key)} · ${bpm || chart.tempo} bpm · ${esc(chart.feel)}</span>` : ''}
      ${other ? html`<span class="lvc-m" title="started from Library ▸ Standards — not this preset's Standard block">· from the Library</span>` : ''}
      <span class="grow"></span>
      ${playing && cur >= 0
        ? html`<span class="lvc-bn"><b>${cur + 1}</b> / ${form}${choruses > 1 ? ` · chorus ${Math.min(chorus, choruses)}/${choruses}` : ''}</span>`
        : html`<span class="lvc-bn muted">${form} bars${choruses > 1 ? ` · ${choruses} choruses` : ''}</span>`}
      ${playing ? html`<button class="lvc-stop" onClick=${stop} title="stop the Standard — the pedalboard comes back">■ Stop</button>` : ''}
    </div>
    ${!slug ? html`<p class="muted lvc-blank">This preset has no Standard block.</p>`
      : html`<div class="lvc-grid" ref=${ref}>
        ${rows.map(r => html`<div class="lvc-row">
          <span class="lvc-sec">${esc(String(r.label || '').replace(/\d+$/, ''))}</span>
          ${r.cells.map(c => html`<span class=${cls('lvc-bar', c.i === cur && 'on')}>
            ${c.chords.length
              ? c.chords.map((ch, k) => html`<b class=${cls('lvc-sym', k && 'alt')}>${esc(ch.sym)}</b>`)
              : html`<i class="lvc-hold">%</i>`}</span>`)}
          ${Array.from({ length: 4 - r.cells.length }, () => html`<span class="lvc-bar pad"></span>`)}
        </div>`)}
      </div>`}
    <div class="lvc-foot">
      ${p.keys !== false ? html`<span class="lvc-part">${ICONS.keys} Piano</span>` : ''}
      ${p.bass !== false ? html`<span class="lvc-part">${ICONS.bass} Bass</span>` : ''}
      ${p.drums ? html`<span class="lvc-part">${ICONS.drums} Drums${p.groove && p.groove !== 'auto'
        ? ' — ' + p.groove.split('/').map(w => w.replace(/-/g, ' ')).join(' · ') : ''}</span>` : ''}
      <span class="grow"></span>
      <span class="muted">Foot: tap to start and stop · long-press restarts the form</span>
    </div>
  </div>`;
}
