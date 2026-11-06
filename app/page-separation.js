// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Separation (hub System) — docs/separation.md §9. Le golem est livré VIDE : les moteurs de la liste de
// golem.fm (un geste : Install) et ceux que l'utilisateur ajoute lui-même (ONNX ou programme, case de responsabilité).
// Un moteur n'est activable qu'après un test qui LIT ses sorties. Aucun nom, aucun lien vers un moteur hors de la liste.
import { html, useState, useEffect, useAsync, post, del, LoadGuard, SHELL_RO, saveFile } from './lib.js';
import { useConfirm } from './confirm-modal.js';
import { AddStepper, Excerpt, exportEngine } from './separation-add.js';
import { BatchStepper, BatchStrip, QueueModal, batchAct } from './separation-batch.js';   // « Separate a folder… » (mockups/separation-folder.html)   // « + Add engine » en stepper (mockups/separation-add-stepper.html)

// Ce qu'un moteur EST, montré EN CLAIR sur ce golem (2026-10-12 : « c'est magique ») — la commande d'un programme,
// les métadonnées d'un ONNX. Local seulement : jamais journalisé, jamais envoyé (§1).
function EngineDetails({ e }) {
  const [saved, setSaved] = useState('');
  const doExport = async () => { const r = await exportEngine(e); setSaved(r.where ? '✓ saved to ' + r.where : '✓ downloaded'); };
  return html`<div class="sep-det">
    ${e.kind === 'combined' ? html`<div><span class="muted">Path</span><span>1 · ${e.first_label} → ${(e.keep || []).join(', ')} · the rest → 2 · ${e.second_label}</span></div>` : ''}
    ${e.kind === 'program' ? html`<div><span class="muted">Command</span><code>${[e.program, ...(e.args || [])].join(' \\\n  ')}</code></div>`
      : e.kind === 'onnx' ? html`<div><span class="muted">Model file</span><code>ONNX · ${(e.declared_stems || []).join(', ')} · segment ${e.segment || '?'} samples</code></div>` : ''}
    ${e.licence ? html`<div><span class="muted">License</span><span>${e.licence}</span></div>` : ''}
    ${e.attribution ? html`<div><span class="muted">Attribution</span><span>${e.attribution}</span></div>` : ''}
    ${e.kind === 'program' && e.map && Object.keys(e.map).length ? html`<div><span class="muted">Outputs</span><code>${Object.entries(e.map).map(([f, st]) => `${f} → ${st}`).join('\n')}</code></div>` : ''}
    ${e.test && !e.test.ok && (e.test.log_tail || (e.test.files || []).length) ? html`<div><span class="muted">What happened</span><div>
      ${(e.test.files || []).length ? html`<small class="muted">files written: ${e.test.files.join(', ')}</small>` : ''}
      ${e.test.log_tail ? html`<pre class="sep-log">${e.test.log_tail}</pre>` : ''}</div></div>` : ''}
    ${e.kind === 'program' || e.kind === 'combined' ? html`<div class="edit-only"><span class="muted">Share</span><span><button class="mini" onClick=${doExport}>Export engine file</button>
      <small class=${saved ? 'sep-saved' : 'muted'}> ${saved || '— keep it, or share it outside golem; it holds no key.'}</small></span></div>` : ''}
    ${e.test && e.test.tested_at ? html`<div><span class="muted">Tested</span><span>${e.test.tested_at.replace('T', ' ')}${e.test.analysis && e.test.analysis.residual_db != null ? ` · stems add up to the mix at ${e.test.analysis.residual_db} dB` : ''}</span></div>` : ''}
  </div>`;
}

const ORIGIN = e => e.kind === 'combined' ? 'combined' : e.origin === 'listed' ? 'checked by golem.fm' : 'your own · ' + (e.kind === 'onnx' ? 'ONNX' : 'program');

function TestState({ e, busy }) {
  const t = e.test || {};
  return busy ? html`<span class="sep-st run">testing…</span>`
    : t.ok ? html`<span class="sep-st ok">✓ passed</span>`
    : t.why ? html`<span class="sep-st bad" title=${t.why}>✗ ${t.why}</span>`
    : html`<span class="sep-st">not tested</span>`;
}

// le moteur EN SERVICE, en tête : ce que golem.fm voit de lui (stems, vitesse mesurée) et la file des morceaux
function InUse({ e, caps, jobs, busy, onAct, onCancel, strip }) {
  const [open, setOpen] = useState(false);
  const t = e.test || {};
  const cur = jobs.current;
  return html`<section class="card-panel sep-hero">
    <div class="sep-row"><span class="sep-chip act">in use</span><b class="sep-hero__name">${e.label}</b>
      <span class="sep-chip">${ORIGIN(e)}</span>
      <span class="sep-row__r"><button class="mini" onClick=${() => setOpen(!open)}>${open ? 'Hide details' : 'Details'}</button>
        <button class="mini edit-only" disabled=${busy} onClick=${() => onAct('test', e)}>Test again</button>
        <button class="mini edit-only" onClick=${() => onAct('off', e)}>Stop using</button></span></div>
    <div class="sep-stems">${((caps && caps.stems) || t.stems || []).map(s => html`<span>${s}</span>`)}</div>
    ${strip || ''}
    <div class="sep-kpi">
      <div><b>${caps && caps.rtf != null ? caps.rtf.toFixed(2) + '×' : '—'}</b><small>real time (measured)</small></div>
      <div><${TestState} e=${e} busy=${busy} /><small>test${t.tested_at ? ' · ' + t.tested_at.slice(11, 16) : ''}</small></div>
      <div><b>${cur ? cur.phase + (cur.progress ? ` ${cur.progress.done}/${cur.progress.total}` : '') : jobs.last ? (jobs.last.ok ? '✓ ' : '✗ ') + jobs.last.at : '—'}</b>
        <small>${cur ? html`separating a song <button class="mini edit-only" onClick=${onCancel}>Cancel</button>` : 'last song separated'}</small></div>
      <div><b>${(jobs.queued || 0) + (jobs.waiting ? 1 : 0)}</b><small>${jobs.waiting ? 'waiting: ' + jobs.waiting : 'songs waiting'}</small></div>
    </div>
    ${open ? html`<${EngineDetails} e=${e} />` : ''}
  </section>`;
}

function Other({ e, busy, onAct }) {
  const [open, setOpen] = useState(false);
  const t = e.test || {};
  return html`<div class="sep-eng">
    <div class="sep-row"><b>${e.label}</b><span class="sep-chip">${ORIGIN(e)}</span>
      <span class="muted sep-eng__sum">${t.ok ? `${(t.stems || []).length} stems · ${t.rtf != null ? t.rtf.toFixed(2) + '× real time' : ''}` : ''}${(e.used_by || []).length ? ` · used by “${e.used_by.join('”, “')}”` : ''}</span>
      <${TestState} e=${e} busy=${busy} />
      <span class="sep-row__r"><button class="mini" onClick=${() => setOpen(!open)}>${open ? 'Hide' : 'Details'}</button>
        <button class="mini edit-only" disabled=${!t.ok || busy} onClick=${() => onAct('use', e)}>Use this engine</button>
        <button class="mini edit-only" disabled=${busy} onClick=${() => onAct('test', e)}>${t.tested_at ? 'Test again' : 'Test'}</button>
        <button class="mini danger edit-only" disabled=${busy} onClick=${() => onAct('remove', e)}>Remove</button></span></div>
    ${open ? html`<${EngineDetails} e=${e} />` : ''}
  </div>`;
}

// La coquille LECTURE SEULE de golem.fm (?shell=ro, docs/shell.md) SANS la page d'un rack de référence : l'instantané
// ordinaire ne relève pas /api/separation (le nom de l'extrait, des chemins saisis) — l'écran dit ce qu'il fait.
function SeparationShell() {
  return html`<div class="sep-page">
    <p class="muted sep-intro">A separation engine splits a recording into stems, so you can mute, solo or slow each part. golem separates the songs of your own library, on this machine. The stems go back to your private library.</p>
    <div class="sep-grid">
      <section class="card-panel sep-col"><h3>Installed</h3>
        <p class="muted">The engines installed on a golem, each tested on a recording of its owner before it can be used.</p></section>
      <section class="card-panel sep-col"><h3>Add an engine</h3>
        <p class="muted"><b>Your own engine</b> — a model file (ONNX) or a program you bring yourself.</p></section>
    </div>
  </div>`;
}

// L'instantané d'usine porte la page du rack de référence (shell_snapshot --separation-from) : elle se rend comme sur
// un golem, Details compris, chaque action `edit-only` retirée
export function SeparationPage() {
  return html`<${SeparationLive} />`;
}

function SeparationLive() {
  const { data, err, reload, setData } = useAsync(() => fetch('/api/separation').then(r => r.json()), []);
  const [sheet, setSheet] = useState(null);
  const [ask, confirmEl] = useConfirm();
  const [msg, setMsg] = useState('');
  // LE LOT d'un dossier (docs/separation-batch.md) : relu toutes les 2 s tant qu'il travaille
  const [batch, setBatch] = useState(null);
  const [batchSheet, setBatchSheet] = useState(null);      // 'new' | 'queue'
  const readBatch = () => fetch('/api/separation/batch').then(r => r.json()).then(r => setBatch(r.batch || null)).catch(() => {});
  useEffect(() => { readBatch(); }, []);
  const batchLive = batch && !batch.finished;
  useEffect(() => {
    if (!batchLive) return;
    const t = setInterval(readBatch, 2000);
    return () => clearInterval(t);
  }, [batchLive]);
  const onBatch = async (what, key) => {
    setMsg('');
    try { const b = await batchAct(what, key); setBatch(b); if (what === 'dismiss') setBatchSheet(null); }
    catch (x) { setMsg('✗ ' + ((x.body && x.body.why) || 'failed')); }
  };
  const testing = data && data.test && data.test.id;
  const jobRunning = data && data.jobs && (data.jobs.current || data.jobs.waiting);
  // un test ou un job en cours : l'état se relit (sans la liste distante, qui ne bouge pas)
  useEffect(() => {
    if (!testing && !jobRunning) return;
    const t = setInterval(() => fetch('/api/separation?remote=false').then(r => r.json())
      .then(d => setData(prev => ({ ...d, list: prev && prev.list }))).catch(() => {}), 1500);
    return () => clearInterval(t);
  }, [testing, jobRunning]);
  if (!data) return html`<${LoadGuard} err=${err} reload=${reload} />`;
  if (SHELL_RO && !Array.isArray(data.engines)) return html`<${SeparationShell} />`;

  const act = async (what, e) => {
    setMsg('');
    let r;
    if (what === 'test') r = await post(`/api/separation/engines/${e.id}/test`, {}).catch(x => x.body);
    else if (what === 'use') {
      let accepted = false;
      if (e.needs_consent) {
        accepted = await ask({ title: 'Use “' + e.label + '”?', ok: 'I understand — use it',
          body: 'You add this engine yourself. Check that its license allows your use. golem does not provide, recommend or check third-party engines.' });
        if (!accepted) return;
      }
      r = await post(`/api/separation/engines/${e.id}/activate`, { accepted }).catch(x => x.body);
    } else if (what === 'off') r = await post('/api/separation/deactivate', {}).catch(x => x.body);
    else if (what === 'remove') {
      const also = (e.used_by || []).length ? `It is used by ${e.used_by.map(x => '“' + x + '”').join(', ')} — removed with it.` : '';
      if (!await ask({ title: 'Remove “' + e.label + '”?', ok: 'Remove', danger: true,
        body: [e.kind === 'combined' ? 'The two engines it combines stay on golem.'
          : e.kind === 'program' ? 'The program and its files stay on this machine — only golem forgets it.'
          : 'golem deletes its copy of this engine.', also] })) return;
      r = await del(`/api/separation/engines/${e.id}`);
    }
    if (r && r.ok === false) setMsg('✗ ' + (r.why || 'failed'));
    reload();
  };
  const active = data.engines.find(e => e.active);
  const canBatch = !!(active && active.test && active.test.ok) && !batchLive;
  const strip = batch ? html`<${BatchStrip} b=${batch} onQueue=${() => setBatchSheet('queue')} onAct=${onBatch} />` : '';
  const others = data.engines.filter(e => !e.active);
  const jobs = data.jobs || {};
  return html`<div class="sep-page sep-v2">
    <div class="sep-row sep-top"><span class="muted">golem separates the songs of your own library, on this machine. The engine runs only when golem is free, never while you play.</span>
      <span class="sep-row__r">
        <button class="mini sep-addbtn edit-only" disabled=${!canBatch} onClick=${() => setBatchSheet('new')}
          title=${batchLive ? 'a batch is running — see the engine card' : !canBatch ? 'choose an engine that passed its test first' : 'separate every song of a folder, into songs on this golem'}>⇣ Separate a folder…</button>
        <button class="mini primary sep-addbtn edit-only" onClick=${() => setSheet('any')}>+ Add engine</button></span></div>
    ${active ? html`<${InUse} e=${active} caps=${data.caps} jobs=${jobs} busy=${testing === active.id} onAct=${act} strip=${strip}
        onCancel=${() => post('/api/separation/cancel', {}).then(reload)} />`
      : html`<section class="card-panel sep-hero sep-hero--none"><b>No engine in use</b>
        <span class="muted">${data.engines.length ? 'Choose one below — it must pass its test first.' : 'Add one: an engine checked by golem.fm, or one you bring yourself.'}</span>${strip}</section>`}
    <div class="sep-list">${others.map(e => html`<${Other} key=${e.id} e=${e} busy=${testing === e.id} onAct=${act} />`)}</div>
    <${Excerpt} x=${data.excerpt} onDone=${reload} />
    <div class="sep-row sep-foot2 muted">${msg ? html`<span class=${msg.startsWith('✗') ? 'warnish' : ''}>${msg}</span>` : ''}
      <span class="sep-row__r ro-inert">Threads
        <select value=${data.threads} onChange=${ev => post('/api/separation/settings', { threads: +ev.target.value }).then(reload)}>
          ${[1, 2, 3, 4, 6, 8].map(n => html`<option value=${n}>${n}${n === data.threads_default ? ' (default)' : ''}</option>`)}
        </select></span></div>
    ${confirmEl}
    ${batchSheet === 'new' && active ? html`<${BatchStepper} engine=${active} rtf=${data.caps && data.caps.rtf} onClose=${() => setBatchSheet(null)}
      onStarted=${b => { setBatch(b); setBatchSheet(null); }} />` : ''}
    ${batchSheet === 'queue' && batch ? html`<${QueueModal} b=${batch} ask=${ask} onAct=${onBatch} onClose=${() => setBatchSheet(null)} />` : ''}
    ${sheet ? html`<${AddStepper} excerpt=${data.excerpt} engines=${data.engines} onExcerpt=${reload} onClose=${() => setSheet(null)} onDone=${reload} />` : ''}
  </div>`;
}
