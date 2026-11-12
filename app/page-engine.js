// SPDX-License-Identifier: GPL-3.0-or-later
// Settings ▸ Engines ▸ Audio — COQUILLE (2026-10-06), contrat docs/audio-engine-choice.md (maquette ①).
// Une carte par moteur, au même gabarit ; le moteur choisi se reconnaît à son ÉTAT, pas à sa place.
// Tout vient des descripteurs (GET /api/engines ← config/engines/*.json) : l'écran ne connaît aucun
// moteur par son nom. Aujourd'hui un seul est sélectionnable (Reaper) ; « Select » vers un autre
// moteur passe par POST /api/engine, qui refuse avec la raison du descripteur. La bascule réelle
// (arrêt, démarrage, reconstruction vérifiée, retour automatique : bridge/engine/switch.py, lot E3) est suivie
// par GET /api/engine/switch ; l'écran ne fait que la montrer. Deux temps, comme ↻ restart : le son coupe.
import { html, useAsync, useState, useEffect, post, cls } from './lib.js';

const PHASE = { stopping: 'stopping the current engine…', starting: 'starting the new engine…',
  remounting: 'rebuilding the patch on it…', reverting: 'it did not answer — going back…' };

const LICENSE = { commercial: 'commercial', 'gpl-2.0-or-later': 'free · GPL' };

function EngineCard({ e, features, current, running, busy, armed, onSelect }) {
  const on = e.id === current;
  const caps = e.capabilities || {};
  const yes = features.filter(f => caps[f.id] === 'yes').length;
  const planned = features.filter(f => caps[f.id] === 'planned').length;
  const state = on ? (running ? 'running' : 'stopped') : null;
  return html`<section class=${cls('eng-card', on && 'eng-on', !e.available && 'eng-off')}>
    <h3>
      <b>${e.name}</b>
      ${on ? html`<span class=${cls('eng-chip', running ? 'go' : 'warn')}>● Selected · ${state}</span>`
        : !e.available ? html`<span class="eng-chip">${e.reason}</span>` : ''}
      <span class="sp"></span>
      <span class="eng-chip">${LICENSE[e.license] || e.license}${e.license === 'commercial' && e.by ? ' · ' + e.by : ''}</span>
    </h3>
    ${e.license !== 'commercial' && e.by ? html`<div class="eng-by">${e.by}</div>` : ''}
    <p class="eng-sum">${e.summary || ''}</p>
    <div class="eng-row"><span class="k">Features</span>
      <span class="v">${yes === features.length ? 'All ' + features.length : yes + ' of ' + features.length}</span>
      ${planned ? html`<span class="dim">· ${planned} planned</span>` : ''}</div>
    <div class="eng-feat">
      ${features.map(f => html`<span class=${cls('f', caps[f.id] === 'no' && 'no', caps[f.id] === 'planned' && 'plan')}
        title=${caps[f.id] === 'no' ? 'not on this engine' : caps[f.id] === 'planned' ? 'planned' : ''}>${f.label}</span>`)}
    </div>
    <div class="eng-foot">
      ${on ? html`<span class="muted">The engine golem drives on this machine.</span>`
        : html`<span class="muted">${e.available ? 'Switching rebuilds every preset on this engine.' : 'Not selectable yet.'}</span>`}
      <span class="sp"></span>
      <button class=${cls('eng-btn ro-inert', on && 'on')} disabled=${on || !e.available || busy}
        title=${!e.available ? e.reason : ''} onClick=${() => onSelect(e.id)}>
        ${on ? '✓ Selected' : armed === e.id ? 'Tap again — sound stops for a few seconds' : 'Select'}</button>
    </div>
  </section>`;
}

export function EnginePanel({ rig }) {
  const { data, reload } = useAsync(() => fetch('/api/engines').then(r => r.json()), []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [armed, setArmed] = useState(null);                 // le moteur armé par un premier appui (4 s)
  const [sw, setSw] = useState(null);                       // la bascule en cours : {phase, to, error?}
  const running = !!((rig && rig.state) || {}).reaper_running;
  useEffect(() => { if (!armed) return; const t = setTimeout(() => setArmed(null), 4000); return () => clearTimeout(t); }, [armed]);
  useEffect(() => {
    if (!sw || !PHASE[sw.phase]) return;
    const t = setInterval(async () => {
      const s = await fetch('/api/engine/switch').then(r => r.json()).catch(() => null);
      if (!s) return;
      setSw(s);
      if (!PHASE[s.phase]) { setBusy(false); if (s.phase === 'failed') setErr(s.error || 'switch failed'); reload(); }
    }, 700);
    return () => clearInterval(t);
  }, [sw && sw.phase]);
  const select = async id => {
    if (armed !== id) { setArmed(id); return; }
    setArmed(null); setBusy(true); setErr(null);
    const r = await post('/api/engine', { id }).catch(e => (e && e.body) || { error: String(e) });
    if (r && r.error) { setErr(r.error); setBusy(false); await reload(); return; }
    if (r && r.switch_pending) { setSw(r.switch || { phase: 'stopping' }); return; }
    await reload();
    setBusy(false);
  };
  if (!data) return html`<div class="eng-page"><p class="muted">reading engines…</p></div>`;
  return html`<div class="eng-page">
    <div class="eng-grid">
      ${(data.engines || []).map(e => html`<${EngineCard} key=${e.id} e=${e} features=${data.features} current=${data.current}
        running=${running} busy=${busy} armed=${armed} onSelect=${select} />`)}
    </div>
    ${sw && PHASE[sw.phase] ? html`<div class="eng-strip">⟳ <b>Switching engine</b> — ${PHASE[sw.phase]}</div>` : ''}
    ${sw && sw.phase === 'done' ? html`<div class="eng-strip">✓ <b>Engine switched.</b>${sw.warning ? ' ' + sw.warning : ''}</div>` : ''}
    ${err ? html`<div class="eng-err">✗ ${err}${sw && sw.phase === 'failed' ? ' — golem went back to the previous engine' : ''}</div>` : ''}
    <div class="eng-strip">🔒 <b>One engine runs at a time.</b> Your presets, setlists and takes stay as they are — the engine you pick rebuilds them.</div>
  </div>`;
}
