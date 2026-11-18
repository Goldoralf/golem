// SPDX-License-Identifier: GPL-3.0-or-later
// System ▸ System ▸ CPU cores (maquette mockups/cpu-cores.html, validée le 2026-11-18) : ce que chaque cœur fait PENDANT
// que ça joue, la part du son de golem dedans, et — sous le Golem Engine — ce que coûte chaque lane. Des MESURES
// (bridge/cpu_cores.py, GET /api/cpu/cores, relu toutes les 2,5 s), à côté de l'estimation d'avant de jouer.
// On ne dit PAS « telle lane tourne sur tel cœur » : le moteur distribue ses pistes sur ses fils à chaque cycle et le
// système déplace ces fils — la maquette le montrait, c'était faux.
import { html, useState, useEffect, useRef, useAsync, post, cls, esc } from './lib.js';

const fmt = v => v == null ? '—' : (v < 10 ? v.toFixed(1) : Math.round(v)) + ' %';
const lvl = p => p == null ? '' : p > 90 ? 'bad' : p > 70 ? 'warn' : 'ok';

export function CpuCoresPanel({ rig }) {
  const st = (rig && rig.state) || {};
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    const tick = () => fetch('/api/cpu/cores').then(r => r.json()).then(x => { if (alive.current) setD(x); }).catch(() => {});
    tick();
    const t = setInterval(tick, 2500);
    return () => { alive.current = false; clearInterval(t); };
  }, []);
  // ce qu'on peut charger : les patches et les presets du golem ; l'estimation et les scènes de ce qui joue
  const { data: patches } = useAsync(() => fetch('/api/patches').then(r => r.json()).catch(() => null), []);
  const { data: presets } = useAsync(() => fetch('/api/presets').then(r => r.json()).catch(() => null), []);
  const { data: cur } = useAsync(() => st.preset_id ? fetch('/api/preset/' + encodeURIComponent(st.preset_id)).then(r => r.ok ? r.json() : null).catch(() => null) : Promise.resolve(null), [st.preset_id]);
  const { data: est } = useAsync(() => st.preset_id ? fetch('/api/cpu/estimate?preset=' + encodeURIComponent(st.preset_id)).then(r => r.ok ? r.json() : null).catch(() => null) : Promise.resolve(null), [st.preset_id]);
  const recall = async body => {
    setBusy(true); setErr('');
    const r = await post('/api/recall', body).catch(e => (e && e.body) || { error: String(e) });
    if (r && r.error) setErr(r.error);
    setTimeout(() => setBusy(false), 1500);
  };
  if (!d) return html`<div class="cc-page"><p class="muted">measuring…</p></div>`;
  if (d.available === false) return html`<div class="cc-page"><p class="muted">${d.why || 'golem cannot measure the cores on this system yet'}</p></div>`;
  const scenes = (cur && cur.scenes) || [];
  const a = d.audio || {}, b = d.busiest;
  const lanes = d.lanes || null;
  const estBy = {};
  const laneName = {};
  for (const L of (est && est.lanes) || []) { estBy[L.id] = (L.by_scene || {})[st.scene_id]; laneName[L.id] = L.name; }
  const name = String(st.preset_name || '').replace(/^⛓\s*/, '') || 'nothing loaded';
  const pList = ((patches && patches.patches) || []).map(p => ['patch:' + p.id, p.name]);
  const sList = (Array.isArray(presets) ? presets : (presets && presets.presets) || []).filter(p => !String(p.id).startsWith('patch:')).map(p => [p.id, p.name || p.id]);
  return html`<div class="cc-page">
    <div class="cc-card cc-src">
      <h3>What to measure</h3>
      <div class="cc-now"><i class=${cls('cc-dot', st.preset_id && 'on')}></i><b>${esc(name)}</b><small>plays now</small></div>
      <select class="cc-load edit-only" aria-label="Load a patch or preset" disabled=${busy} value=""
        onChange=${e => { const v = e.target.value; e.target.value = ''; if (v) recall({ preset: v }); }}>
        <option value="">Load a patch or preset…</option>
        ${pList.length ? html`<optgroup label="Patches">${pList.map(([id, n]) => html`<option value=${id}>${n}</option>`)}</optgroup>` : ''}
        ${sList.length ? html`<optgroup label="Presets">${sList.map(([id, n]) => html`<option value=${id}>${n}</option>`)}</optgroup>` : ''}
      </select>
      ${scenes.length ? html`<h3 class="cc-h2">Scene</h3>
        <div class="cc-scenes">${scenes.slice(0, 5).map(s => html`<button class=${cls('cc-sc edit-only', st.scene_id === s.id && 'on')}
          aria-label=${'Scene ' + s.id} disabled=${busy} onClick=${() => recall({ scene: s.id })}>${s.id}</button>`)}</div>` : ''}
      ${err ? html`<p class="cc-err">✗ ${err}</p>` : ''}
      <div class="cc-facts">
        <span>Busiest core</span><b class=${'cc-' + lvl(b && b.pct)}>${b ? 'core ' + b.n + ' · ' + fmt(b.pct) : '…'}</b>
        <span>Engine load (whole cycle)</span><b class=${'cc-' + lvl(a.dsp_load)}>${a.dsp_load != null ? fmt(a.dsp_load) : '—'}</b>
        <span>Dropouts since start</span><b class=${a.xruns ? 'cc-warn' : 'cc-ok'}>${a.xruns != null ? a.xruns : '—'}</b>
        <span>Buffer</span><b>${a.buffer ? a.buffer + ' smp' + (a.cycle_ms ? ' · ' + a.cycle_ms + ' ms' : '') : '—'}</b>
      </div>
      <p class="cc-note">Measured over the last ${d.window_s || '…'} seconds. A lane runs on one core at a time: it is the busiest core, not their sum, that decides whether the sound drops out.</p>
    </div>
    <div class="cc-right">
      <div class="cc-card">
        <div class="cc-hd"><b>${d.cores.length} cores</b><small>${esc(d.cpu || '')}${d.cores.some(c => c.kind) ? ' · P = performance, E = efficiency' : ''}</small>
          <span class="cc-legend"><i class="g"></i>golem's sound<i class="o"></i>everything else</span></div>
        <div class=${cls('cc-cores', d.cores.length > 20 && 'dense')}>
          ${d.cores.map(c => html`<div class=${cls('cc-core', b && b.n === c.n && c.pct > 5 && 'busy')} key=${c.n}>
            <div class="n"><span>${c.n}</span>${c.kind ? html`<em class=${c.kind === 'E' ? 'e' : ''}>${c.kind}</em>` : ''}</div>
            <div class="bar"><div class="o" style=${'height:' + Math.min(100, c.pct || 0) + '%'}></div><div class="g" style=${'height:' + Math.min(100, c.engine_pct || 0) + '%'}></div></div>
            <b>${c.pct == null ? '…' : Math.round(c.pct)}<small> %</small></b></div>`)}
        </div>
      </div>
      <div class="cc-card cc-lanes">
        <h3>What the sound costs</h3>
        ${lanes === null ? html`<p class="cc-note">This engine does not say what each lane costs: the cores above are the measure.</p>`
        : !lanes.length ? html`<p class="cc-note">Nothing is loaded.</p>`
        : html`${lanes.slice(0, 4).map(L => html`<div class="cc-lane" key=${L.id}>
            <span class="nm">${esc(laneName[L.id] || L.id)}${L.branches ? html`<small>${L.branches} branches</small>` : ''}</span>
            <div class="track"><i class=${lvl(L.pct)} style=${'width:' + Math.min(100, L.pct || 0) + '%'}></i></div>
            <span class="pc">${fmt(L.pct)}</span>
            <span class="est">${estBy[L.id] != null ? 'estimated ' + fmt(estBy[L.id]) : ''}</span></div>`)}
          ${d.services_pct != null ? html`<div class="cc-lane"><span class="nm">golem's services<small>click, looper, takes</small></span>
            <div class="track"><i class="ok" style=${'width:' + Math.min(100, d.services_pct) + '%'}></i></div><span class="pc">${fmt(d.services_pct)}</span><span class="est"></span></div>` : ''}
          <p class="cc-note">What each lane's plugins took of one audio cycle. The estimate also counts the engine's own share.</p>`}
      </div>
    </div>
  </div>`;
}
