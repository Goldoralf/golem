// SPDX-License-Identifier: GPL-3.0-or-later
// ÉTAT DES BLOCS (docs/block-status.md §4) — la feuille d'une tuile en erreur, le bandeau de chargement.
// Un bloc qui manque ici est barré et coupé ; le taper propose : Download · Replace · Keep it off.
// Remplacer est TOUJOURS un choix humain : la suggestion par nom est montrée, jamais posée d'office.
import { html, useState, useEffect, api, post, esc } from './lib.js';

export const fmtMB = bytes => {
  if (!bytes) return '';
  const mb = bytes / (1024 * 1024);
  return mb >= 10 ? Math.round(mb) + ' MB' : mb >= 1 ? mb.toFixed(1) + ' MB' : '< 1 MB';
};

const SRC = { 'golem.fm': 'golem.fm', tone3000: 'TONE3000' };

export { blockSig } from './block-status-model.mjs';

// le bandeau « 3 blocks missing — ⬇ Download all (38 MB) ». `empty` n'y entre pas : un bloc qu'on vient de
// poser sans capture a déjà son ∅, et le bandeau parle de ce qui ARRIVE incomplet, pas de ce qu'on édite.
export function MissingBanner({ sum, fetching, onDownloadAll, onClose }) {
  if (!sum) return '';
  const dl = sum.download || { n: 0, bytes: 0, unknown: 0 };
  const na = sum.unavailable || 0;
  const n = dl.n + na;
  if (!n) return '';
  const size = [fmtMB(dl.bytes), dl.unknown ? `${dl.unknown} from TONE3000` : ''].filter(Boolean).join(' + ');
  return html`<div class="dsn-arrived bs-banner" data-doc="designer.missing">
    <span>⚠ ${n} block${n > 1 ? 's' : ''} missing on this rack${na && dl.n ? html` <small>· ${na} not available here</small>` : ''}
      ${na && !dl.n ? html` <small>— not available here, tap a barred block to replace it</small>` : ''}</span>
    ${fetching ? html`<span class="bs-prog">⬇ downloading ${fetching.done}/${fetching.total}…</span>`
      : dl.n ? html`<button class="mini primary" onClick=${onDownloadAll}>⬇ Download all${size ? ` (${size})` : ''}</button>` : ''}
    <button class="mini dsn-arr-x" title="dismiss — the barred blocks stay off" onClick=${onClose}>×</button>
  </div>`;
}

// la feuille d'une tuile en erreur
// `onVstHost` : seulement sur un poste Windows/macOS (le bloc VST Host n'existe pas sur un golem Linux) —
// un bloc qui ne joue pas ICI se remplace aussi par un plugin à soi, posé à sa place.
export function BlockStatusSheet({ block, st, role, name, fetching, onDownload, onReplaceType, onPickCapture, onUseSuggestion, onPlayable, playBusy, onVstHost, onRemove, onClose }) {
  // `format` : la capture est bonne mais le moteur NAM de cette machine ne lit pas son format (A2 hors Linux) — on en choisit une autre
  const capture = st.reason === 'capture' || st.reason === 'format' || st.state === 'empty' || (st.state === 'download');
  const [alts, setAlts] = useState(null);
  const [sug, setSug] = useState(null);
  useEffect(() => {
    let dead = false;
    if (!capture) {
      api(`/api/blocks/alternatives?type=${encodeURIComponent(block.type)}&role=${encodeURIComponent(role || '')}`)
        .then(r => !dead && setAlts(r.blocks || [])).catch(() => !dead && setAlts([]));
    } else if (block.label || block.name) {
      post('/api/blocks/suggest', { block }).then(r => !dead && setSug(r.suggestion)).catch(() => {});
    }
    return () => { dead = true; };
  }, [block.id, block.type]);
  const busy = !!fetching;
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card sm bs-sheet" data-doc="designer.block-status">
      <button class="close" onClick=${onClose}>×</button>
      <h2>${st.state === 'download' ? '⬇' : '✕'} ${esc(name)}</h2>
      <p class="muted bs-why">${esc(st.why || '')}${st.title ? html` — <b>${esc(st.title)}</b>` : ''}</p>
      <p class="muted bs-off">This block is <b>off</b> on this rack until it is fixed — the rest of the chain plays.</p>
      <div class="bs-actions">
        ${st.state === 'download' ? html`<button class="row-btn primary" disabled=${busy} onClick=${onDownload}>
          ⬇ Download${st.bytes ? ` (${fmtMB(st.bytes)})` : ''}<small>from ${SRC[st.source] || st.source} — the block plays as soon as it lands</small></button>` : ''}
        ${st.reason === 'format' && onPlayable ? html`<button class="row-btn primary" disabled=${playBusy} onClick=${onPlayable}>
          ${playBusy ? '⏳ downloading from TONE3000…' : '⬇ Download the playable version'}
          <small>the same capture in the classic NAM format, from TONE3000 — the patch is not changed</small></button>` : ''}
        ${capture ? html`
          ${/* la suggestion par nom qui retombe sur le MÊME pack ne sert à rien pour un défaut de format
                (vécu 2026-10-03 : « Fender Twin Pack » reposait la même capture A2, le bloc restait barré) */''}
          ${sug && !(st.reason === 'format' && String(sug.ref) === String(block.ref || '').replace(/^.*\//, '').replace(/^t3k:/, '')) ? html`<button class="row-btn" onClick=${() => onUseSuggestion(sug)}>≈ ${esc(sug.title)}
            <small>suggested by name, ${sug.source === 'rack' ? 'on this rack' : 'on golem.fm'}${sug.retyped ? ' — the block becomes ' + sug.retyped : ''} · not the capture that was chosen</small></button>` : ''}
          <button class="row-btn" onClick=${onPickCapture}>↺ Pick another capture…<small>${st.reason === 'format' ? 'a non-A2 capture plays on this machine' : 'from this rack or TONE3000'}</small></button>`
        : html`
          <div class="bs-alts">
            <small class="muted">Replace with a ${esc(block.type)}-like block available here:</small>
            ${alts === null ? html`<span class="muted">…</span>`
              : alts.length ? alts.map(a => html`<button class="chip" onClick=${() => onReplaceType(a.type)}>${esc(a.name)}</button>`)
              : html`<span class="muted">nothing in this category on this rack</span>`}
          </div>
          ${onVstHost ? html`<button class="row-btn" onClick=${onVstHost}>▣ Use your own plugin (VST Host)…
            <small>pick a VST3 or CLAP installed on this computer — it takes this block's place</small></button>` : ''}`}
        ${/* côte à côte : avec la ligne VST Host, la feuille dépassait les 600 px (2026-10-20) */''}
        <div class="bs-foot">
          ${onRemove ? html`<button class="row-btn" onClick=${onRemove}>Remove block</button>` : ''}
          <button class="row-btn" onClick=${onClose}>Keep it off<small>it plays on a rack that has it</small></button>
        </div>
      </div>
    </div></div>`;
}
