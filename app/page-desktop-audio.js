// SPDX-License-Identifier: GPL-3.0-or-later
// Native REAPER audio settings for Windows ASIO and macOS CoreAudio.
import { html, useAsync, useState, useEffect, post } from './lib.js';
import { activeForSelection, currentAudioForm, useDeviceValue } from './desktop-audio-model.mjs';

const numeric = e => Number(e.target.value);
const options = (items, selected) => [...new Set([...items, selected].filter(Boolean))];

export function DesktopAudioPage({ onDone }) {
  const { data, err, reload } = useAsync(async () => {
    const r = await fetch('/api/desktop/audio');
    if (!r.ok) throw new Error((await r.json()).error || `Audio settings → ${r.status}`);
    return r.json();
  }, []);
  const [form, setForm] = useState(null);
  const [phase, setPhase] = useState('idle');
  const [message, setMessage] = useState('');
  useEffect(() => {
    if (!data) return;
    setForm(currentAudioForm(data));
    if (data.apply && !['idle', 'done', 'error'].includes(data.apply.phase)) setPhase(data.apply.phase);
  }, [data]);
  useEffect(() => {
    if (['idle', 'done', 'error'].includes(phase)) return;
    const timer = setInterval(async () => {
      try {
        const r = await fetch('/api/desktop/audio/status').then(x => x.json());
        setPhase(r.phase);
        if (r.phase === 'error') setMessage(r.error || 'Audio configuration failed');
        if (r.phase === 'done') {
          setMessage((r.saved_project ? `Project saved as sets/${r.saved_project}. ` : '') +
            'Settings applied. Check the active audio device below.');
          reload(); setTimeout(reload, 4000);
          if (onDone) onDone();
        }
      } catch (e) { setMessage(String(e)); setPhase('error'); }
    }, 1000);
    return () => clearInterval(timer);
  }, [phase]);
  if (err) return html`<div class="pg-body"><p class="perf-err">${String(err)}</p><button onClick=${reload}>Retry</button></div>`;
  if (!form) return html`<div class="pg-body muted">Loading audio devices…</div>`;
  const mac = form.platform === 'macos';
  const change = (key, value) => setForm(f => ({ ...f, [key]: value }));
  const busy = !['idle', 'done', 'error'].includes(phase);
  const apply = async () => {
    setMessage('');
    try {
      const body = { sample_rate: form.sample_rate, sample_rate_use: form.sample_rate_use,
        buffer_size: form.buffer_size, buffer_size_use: form.buffer_size_use };
      if (mac) Object.assign(body, { input_device: form.input_device, output_device: form.output_device });
      else Object.assign(body, { driver: form.driver, input_first: form.input_first,
        input_last: form.input_last, output_first: form.output_first, output_last: form.output_last });
      const result = await post('/api/desktop/audio', body);
      setPhase(result.apply.phase);
    } catch (e) { setMessage((e.body && e.body.error) || String(e)); setPhase('error'); }
  };
  const field = (label, control) => html`<label class="da-field"><span>${label}</span>${control}</label>`;
  const select = (key, items, cast = x => x, disabled = false, off = () => false) => html`<select value=${String(form[key])} disabled=${disabled}
    onChange=${e => change(key, cast(e.target.value))}>
    ${items.map(item => html`<option value=${String(item)} disabled=${off(item)}>${item}${off(item) ? ' (not offered by the driver)' : ''}</option>`)}</select>`;
  // les tailles que le PILOTE ASIO accepte (bridge/asio_probe.py) — connues pour le pilote configuré seulement
  const bufOff = sz => !!(form.buffer_sizes_ok && form.driver === (data && data.driver) && !form.buffer_sizes_ok.includes(sz));
  const channel = key => html`<input type="number" min="1" max="128" value=${form[key] + 1}
    onChange=${e => change(key, numeric(e) - 1)} />`;
  const toggle = key => html`<label class="da-toggle"><input type="checkbox" checked=${!form[`${key}_use`]}
    onChange=${e => setForm(f => useDeviceValue(f, key, e.target.checked))} /> Use device value</label>`;
  const active = activeForSelection(form);
  return html`<div class="pg-body da-page">
    <h2>Audio device</h2>
    <p class="muted">${mac ? 'CoreAudio' : 'ASIO'} settings used by REAPER. Applying closes and reopens REAPER.
      An untitled project is saved automatically in golem’s sets folder; REAPER may still ask to save changes to a named project.</p>
    <div class="da-grid">
      ${mac ? html`
        ${field('Input device', select('input_device', options(form.inputs, form.input_device)))}
        ${field('Output device', select('output_device', options(form.outputs, form.output_device)))}`
        : html`
        ${field('ASIO driver', select('driver', options(form.drivers, form.driver)))}
        ${field('Input channels', html`<span class="da-range">${channel('input_first')} to ${channel('input_last')}</span>`)}
        ${field('Output channels', html`<span class="da-range">${channel('output_first')} to ${channel('output_last')}</span>`)}`}
      ${field('Sample rate', html`<span class="da-row">${select('sample_rate', options(form.sample_rates, form.sample_rate), Number, !form.sample_rate_use)} Hz ${toggle('sample_rate')}</span>`)}
      ${field('Buffer size', html`<span class="da-row">${select('buffer_size', options(form.buffer_sizes, form.buffer_size), Number, !form.buffer_size_use, bufOff)} samples ${toggle('buffer_size')}</span>`)}
    </div>
    <p class="muted">“Use device value” lets the driver choose. Uncheck it to request a value on Apply. ${!active ? 'The selected device is not open, so its current values cannot be read yet.' : ''}</p>
    ${form.enumeration_warning ? html`<p class="perf-err">${form.enumeration_warning}</p>` : ''}
    ${data.native_advice && form.driver === data.native_advice.generic ? html`<p class="perf-err da-native">
      ⚠ REAPER uses <b>${data.native_advice.generic}</b>, a generic wrapper, while this sound card has its own driver,
      <b>${data.native_advice.native}</b>. A wrapper can drop or swap inputs (measured: a Volt 276 lost its input 2).
      <button class="mini" onClick=${() => change('driver', data.native_advice.native)}>Use ${data.native_advice.native}</button>
      then Apply. Your input roles carry over.</p>` : ''}
    ${form.actual ? html`<p class="da-actual">Active in REAPER: ${form.actual.MODE || 'device closed'}
      ${form.actual.IDENT_IN ? ` · input ${form.actual.IDENT_IN}` : ''}
      ${form.actual.IDENT_OUT ? ` · output ${form.actual.IDENT_OUT}` : ''}
      ${form.actual.SRATE ? ` · ${form.actual.SRATE} Hz` : ''}
      ${form.actual.BSIZE ? ` · ${form.actual.BSIZE} samples` : ''}
      ${form.actual.INPUT_COUNT != null ? ` · ${form.actual.INPUT_COUNT} enabled inputs / ${form.actual.OUTPUT_COUNT} enabled outputs` : ''}</p>` : ''}
    <button class="primary" disabled=${busy || (!mac && !form.drivers.length)} onClick=${apply}>
      ${busy ? 'Applying…' : 'Apply audio settings'}</button>
    ${phase === 'waiting_for_reaper' ? html`<p class="muted">Waiting for REAPER to close. Check its save prompt.</p>` : ''}
    ${message ? html`<p class=${phase === 'error' ? 'perf-err' : 'muted'}>${message}</p>` : ''}
  </div>`;
}
