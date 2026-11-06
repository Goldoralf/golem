// SPDX-License-Identifier: GPL-3.0-or-later
// ── BALANCE : APPLIQUER CETTE LANE À TOUTE LA SETLIST (docs/band-scenes.md §4, écran 6 — 2026-09-15) ──
// Le modèle copie fait payer chaque retouche de balance autant de fois qu'il y a de morceaux. Ce geste
// est un dépôt EN MASSE, explicite et annulable : la lane (blocs, potards, captures, états) remplace la
// lane du même rôle dans les morceaux cochés. Chaque scène garde son état par nom, chaque bloc son pied,
// chaque scène son niveau. Le serveur fait le plan (bridge/lane_apply.py) ; ici on le montre et on coche.
import { html, useState, useEffect, cls, esc, post } from './lib.js';

export function LaneApplySheet({ doc, lane, laneName, onClose }) {
  const [plan, setPlan] = useState(null);
  const [picked, setPicked] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const load = () => post('/api/lane-apply/plan', { doc, lane }).then(r => {
    setPlan(r || { error: 'the rack did not answer' });
    setPicked(new Set(((r && r.songs) || []).filter(s => s.ok).map(s => s.preset)));
  }).catch(() => setPlan({ error: 'the rack did not answer' }));
  useEffect(() => { load(); }, []);
  const toggle = pid => setPicked(cur => { const n = new Set(cur); n.has(pid) ? n.delete(pid) : n.add(pid); return n; });
  const apply = async () => {
    setBusy(true);
    const r = await post('/api/lane-apply', { doc, lane, presets: [...picked] }).catch(() => null);
    setBusy(false); setDone(r || { ok: false, error: 'the rack did not answer' });
  };
  const undo = async () => { setBusy(true); const r = await post('/api/lane-apply/undo', {}).catch(() => null); setBusy(false);
    setDone(null); setPlan(null); load(); if (r && r.ok === false) setDone(r); };
  const songs = (plan && plan.songs) || [];
  // ce qui change, tous morceaux cochés confondus : la même ligne compte une fois, avec son nombre de morceaux
  const changes = (() => { const m = new Map();
    songs.filter(s => s.ok && picked.has(s.preset)).forEach(s => (s.changes || []).forEach(c => m.set(c, (m.get(c) || 0) + 1)));
    return [...m.entries()].sort((a, b) => b[1] - a[1]); })();
  const setName = (plan && plan.setlist && plan.setlist.name) || 'the setlist';
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card lap-card">
      <button class="close" onClick=${onClose}>×</button>
      <h3 class="lap-title">Apply « ${esc(laneName)} » to the songs of « ${esc(setName)} »</h3>
      ${!plan ? html`<p class="muted">Reading the songs…</p>`
      : plan.error ? html`<p class="lap-err">${esc(plan.error)}</p>`
      : done && done.ok ? html`<div class="lap-done">
          <b>✓ « ${esc(laneName)} » is now in ${done.applied.length} song${done.applied.length === 1 ? '' : 's'}.</b>
          ${done.skipped && done.skipped.length ? html`<p class="muted">Skipped: ${done.skipped.map(s => s.preset + ' (' + s.why + ')').join(', ')}</p>` : ''}
          <p class="muted">Each song kept its scenes, switches and levels. The next recall of a song plays the new lane.</p>
          <div class="lap-acts">${done.undo ? html`<button class="mini" disabled=${busy} onClick=${undo}>↶ Undo for all ${done.applied.length}</button>` : ''}
            <button class="mini primary" onClick=${onClose}>Done</button></div>
        </div>`
      : html`
        <p class="muted lap-sub">What changes in the songs you tick — the lane's blocks, knobs, captures and states. Scenes, switches and levels stay as each song has them.</p>
        <div class="lap-diff">
          ${changes.length ? changes.slice(0, 8).map(([c, n]) => html`<span>${esc(c)}${n > 1 ? html` <i>×${n}</i>` : ''}</span>`)
            : html`<span class="muted">Nothing differs in the ticked songs — they already have this lane.</span>`}
          ${changes.length > 8 ? html`<span class="muted">+ ${changes.length - 8} more</span>` : ''}
        </div>
        <div class="lap-songs">
          ${songs.map(s => html`<label class=${cls('lap-song', !s.ok && 'no')} title=${s.ok ? (s.states.length ? 'uses ' + s.states.join(', ') : 'no named state') : s.why}>
            <input id=${'lap-' + s.preset} type="checkbox" disabled=${!s.ok} checked=${s.ok && picked.has(s.preset)} onChange=${() => toggle(s.preset)} />
            <b>${esc(s.title)}</b><small>${s.ok ? (s.states.join(' · ') || '—') : esc(s.why)}</small></label>`)}
          ${!songs.length ? html`<p class="muted">No song in this setlist.</p>` : ''}
        </div>
        ${plan.undo ? html`<p class="muted lap-undo">Last apply: « ${esc(plan.undo.lane)} » from ${esc(plan.undo.source)} to ${plan.undo.count} song${plan.undo.count === 1 ? '' : 's'} at ${esc(plan.undo.at)} — <button class="mini" disabled=${busy} onClick=${undo}>↶ Undo it</button></p>` : ''}
        ${done && !done.ok ? html`<p class="lap-err">${esc(done.error || 'failed')}</p>` : ''}
        <div class="lap-acts">
          <span class="muted">${picked.size} song${picked.size === 1 ? '' : 's'} get this lane · undo for all is one tap</span>
          <button class="mini" onClick=${onClose}>Cancel</button>
          <button class="mini primary" disabled=${!picked.size || busy} onClick=${apply}>${busy ? 'Applying…' : 'Apply to ' + picked.size + ' song' + (picked.size === 1 ? '' : 's')}</button>
        </div>`}
    </div>
  </div>`;
}
