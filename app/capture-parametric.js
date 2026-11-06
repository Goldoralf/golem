// SPDX-License-Identifier: GPL-3.0-or-later
// Le VST est balayé dans un REAPER séparé. Les réglages demandés ensuite sont des exportations
// du modèle appris, pas un EQ ajouté derrière une capture fixe.
import { html, useEffect, useRef, useState, cls, esc } from './lib.js';

const ROOT = '/api/vst-host/capture/parametric';
const RUNNING = ['render', 'train', 'test', 'install', 'cancelling'];
async function request(url, body) {
  const r = await fetch(url, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || 'Control capture unavailable');
  return d;
}

export function ParametricCapture({ block, patchName, onReplace, stamp }) {
  const [st, setSt] = useState(null), [err, setErr] = useState(''), [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState({}), [query, setQuery] = useState('');
  const [samples, setSamples] = useState(''), [validation, setValidation] = useState('');
  const [preview, setPreview] = useState(null), [confirmed, setConfirmed] = useState(false);
  const [gear, setGear] = useState('amp-cab'), [name, setName] = useState(''), [again, setAgain] = useState(false);
  const [step, setStep] = useState(0);
  const q = `block=${encodeURIComponent(block.id)}&plugin=${encodeURIComponent(block.plugin || '')}`;
  const load = () => request(ROOT + '?' + q).then(setSt).catch(e => setErr(e.message));
  useEffect(() => { load(); }, [block.id, stamp]);
  const c = st?.check || {}, job = st?.job || {}, setup = st?.setup || {};
  const mine = job.block === block.id && job.mode === 'parametric';
  const running = RUNNING.includes(job.state), installing = setup.state === 'running';
  useEffect(() => {
    if (!running && !installing) return;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [running, installing, block.id]);
  const controls = Object.values(selected);
  const spec = () => ({ controls, samples: samples === '' ? Math.max(32, 15 * controls.length) : Number(samples),
                        validation: validation === '' ? Math.max(8, 3 * controls.length) : Number(validation), seed: 0 });
  const act = async fn => {
    setErr(''); setBusy(true);
    try { await fn(); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const toggle = p => {
    setPreview(null);
    setSelected(prev => {
      const next = { ...prev };
      if (next[p.i]) delete next[p.i];
      else next[p.i] = { i: p.i, name: p.name, min: /gain|drive|volume/i.test(p.name) ? 0.05 : 0, max: 1 };
      return next;
    });
  };
  const range = (i, key, percent) => {
    setPreview(null);
    setSelected(prev => ({ ...prev, [i]: { ...prev[i], [key]: Number(percent) / 100 } }));
  };
  const use = () => act(async () => {
    const d = await request('/api/vst-host/capture/replacement?' + q);
    onReplace(d.blocks, 'new', job.new_patch);
  });
  const done = mine && job.state === 'done' && !again;
  return html`<div class="pcap">
    <h3>Capture the plugin's controls</h3>
    <p class="vh-hint">Learn how gain and tone controls interact. Choose their travel ranges; other settings stay fixed.</p>
    ${err ? html`<p class="vst-host-error" role="alert">${esc(err)}</p>` : ''}
    ${!st ? html`<p class="vh-hint">Reading the plugin…</p>` : installing
      ? html`<p class="vh-cap-run">${esc(setup.msg)}</p>` : running
      ? html`<p class="vh-cap-run">${esc(job.msg)}</p>
          ${job.progress ? html`<progress value=${job.progress.done} max=${job.progress.total}></progress>
            <span class="vh-hint">${job.progress.done}/${job.progress.total} settings captured</span>` : ''}
          <button class="vh-cap-btn ghost" disabled=${busy || job.state === 'cancelling'}
            onClick=${() => act(async () => { await request('/api/vst-host/capture/cancel', {}); await load(); })}>Cancel capture</button>` : done
      ? html`<p class="vh-cap-ok">✓ Model and ${job.result?.controls?.length || 0} controls saved</p>
          <p class="vh-hint">Unseen settings: mean ESR ${job.result.validation.mean_esr.toFixed(4)} · worst ${job.result.validation.worst_esr.toFixed(4)}</p>
          ${job.warning ? html`<p class="vh-cap-warn">${esc(job.warning)}</p>` : ''}
          <button class="vh-cap-btn" disabled=${busy} onClick=${use}>Create a new patch with these controls</button>
          <a class="vh-link" href=${ROOT + '/download?ref=' + encodeURIComponent(job.result.core[0].ref)} download>Download parametric .nam</a>
          <button class="vh-cap-btn ghost" onClick=${() => setAgain(true)}>Capture again</button>`
      : html`
          ${step === 1 && !c.env?.ready ? html`<button class="vh-cap-btn" disabled=${busy} onClick=${() => act(async () => {
            await request(ROOT + '/setup', {}); await load();
          })}>Install parametric capture tools</button>` : ''}
          ${setup.state === 'error' ? html`<p class="vst-host-error">${esc(setup.error)}</p>` : ''}
          ${(c.blockers || []).length ? html`<p class="vh-cap-warn">Turn off: ${esc(c.blockers.map(x => x.label).join(', '))}. Open the plugin, then tap Done.</p>` : ''}
          ${step === 0 ? html`
          <input class="vh-in" aria-label="Find a plugin control" placeholder="Find gain, bass, treble…" value=${query}
            onInput=${e => setQuery(e.target.value)} />
          <div class="pcap-list">${(c.controls || []).filter(p => selected[p.i] || p.name.toLowerCase().includes(query.toLowerCase())).map(p => html`
            <div class=${cls('pcap-row', selected[p.i] && 'pcap-selected')} key=${p.i}>
              <label title=${p.why || p.display || ''}><input type="checkbox" checked=${!!selected[p.i]}
                disabled=${!p.available || (!selected[p.i] && controls.length >= (c.max_controls || 12))}
                onChange=${() => toggle(p)} />${esc(p.name)} <small>${esc(p.display || '')}</small></label>
              ${selected[p.i] ? html`<div class="pcap-range">
                <label>From <input type="number" min="0" max="100" step="0.1" value=${selected[p.i].min * 100}
                  onInput=${e => range(p.i, 'min', e.target.value)} aria-label=${p.name + ' minimum percent'} />%</label>
                <label>to <input type="number" min="0" max="100" step="0.1" value=${selected[p.i].max * 100}
                  onInput=${e => range(p.i, 'max', e.target.value)} aria-label=${p.name + ' maximum percent'} />%</label>
              </div>` : ''}
            </div>`)}</div>
          <p class="vh-hint">${controls.length} selected · % of the original control's travel</p>` : html`
          <p class="vh-hint">${esc(controls.map(k => k.name).join(' · '))}
            <button class="vh-link" onClick=${() => setStep(0)}>change controls</button></p>
          <div class="pcap-budget">
            <label>Training settings <input type="number" min=${2 * controls.length + 3} max="448" value=${samples}
              placeholder=${String(Math.max(32, 15 * controls.length))} onInput=${e => { setSamples(e.target.value); setPreview(null); }} /></label>
            <label>Unseen checks <input type="number" min="2" max="64" value=${validation}
              placeholder=${String(Math.max(8, 3 * controls.length))} onInput=${e => { setValidation(e.target.value); setPreview(null); }} /></label>
          </div>
          ${c.recipe === false ? html`<label class="vh-chk"><input type="checkbox" checked=${confirmed}
            onChange=${e => setConfirmed(e.target.checked)} />I've checked — only drive, amp, EQ and cab are on.</label>
            <label class="vh-hint">Plugin cab <select value=${gear} onChange=${e => setGear(e.target.value)}>
              <option value="amp-cab">On</option><option value="amp">None</option></select></label>` : ''}
          <label class="vh-hint">Name <input class="vh-in" value=${name} placeholder=${patchName + ' — controls'} onInput=${e => setName(e.target.value)} /></label>
          `}
          <button class="vh-cap-btn ghost" disabled=${busy || !controls.length} onClick=${() => act(async () => {
            setPreview(await request(ROOT + '/plan', { block: block.id, plugin: block.plugin, plan: spec() }));
            setStep(1);
          })}>Preview capture plan</button>
          ${preview ? html`<p class="vh-hint">${preview.samples} training settings + ${preview.validation} unseen settings.${' '}
            ${Math.ceil((preview.samples * 38 + preview.validation * 9) / 60)} min of training audio, plus rendering and training time.
            Captures include combined control changes. Missing renders resume when you retry with the same plugin settings.</p>` : ''}
          ${step === 1 ? html`<button class="vh-cap-btn" disabled=${busy || !preview || !c.ok || (c.recipe === false && !confirmed)} onClick=${() => act(async () => {
            await request(ROOT, { block: block.id, plugin: block.plugin, patch: patchName, plan: spec(),
                                 name: name.trim() || undefined, dest: 'new', confirmed, gear });
            setAgain(false); await load();
          })}>Start capture with controls</button>` : ''}
          ${mine && job.state === 'error' ? html`<p class="vst-host-error">${esc(job.error)}</p>` : ''}
          ${mine && job.state === 'cancelled' ? html`<p class="vh-hint">Last control capture cancelled.</p>` : ''}`}
  </div>`;
}

export function ParametricControls({ tone, model, onModel }) {
  const [st, setSt] = useState(null), [values, setValues] = useState({});
  const [busy, setBusy] = useState(false), [err, setErr] = useState('');
  const generation = useRef(0);
  const ref = tone?.id;
  useEffect(() => {
    const g = ++generation.current;
    setSt(null); setErr('');
    if (!tone?.parametric) return;
    request(ROOT + '/model?ref=' + encodeURIComponent(ref) + '&model=' + encodeURIComponent(model || '')).then(d => {
      if (g === generation.current) { setSt(d); setValues(d.values); }
    }).catch(e => { if (g === generation.current) setErr(e.message); });
    return () => { ++generation.current; };
  }, [ref, model, !!tone?.parametric]);
  const apply = async () => {
    setErr(''); setBusy(true);
    const g = generation.current;
    try {
      const d = await request(ROOT + '/bake', { ref, values });
      if (g === generation.current) onModel(d.model);
    } catch (e) { if (g === generation.current) setErr(e.message); }
    finally { setBusy(false); }
  };
  if (!tone?.parametric) return '';
  return html`<div class="pcap-play">
    <h4>Captured plugin controls</h4>
    ${err ? html`<p class="vst-host-error" role="alert">${esc(err)}</p>` : ''}
    ${(st?.controls || []).map(k => html`<label class="pcap-play-row" key=${k.i}>
      <span>${esc(k.name)}</span><input type="range" min=${k.min} max=${k.max} step="0.001"
        value=${values[k.name] ?? k.default} disabled=${busy || !st.ready} aria-label=${k.name}
        onInput=${e => setValues(v => ({ ...v, [k.name]: Number(e.target.value) }))} />
      <output>${((values[k.name] ?? k.default) * 100).toFixed(1)}%</output></label>`)}
    <button class="mini" disabled=${busy || !st?.ready} onClick=${apply}>${busy ? 'Preparing setting…' : 'Apply control settings'}</button>
    <p class="vh-hint">Applies to this block in all scenes. A new NAM setting loads after you apply.
      ${st && !st.ready ? 'Install the parametric capture tools on this computer to prepare new settings.' : ''}</p>
    <a class="vh-link" href=${ROOT + '/download?ref=' + encodeURIComponent(ref)} download>Download the full parametric model</a>
  </div>`;
}
