// SPDX-License-Identifier: GPL-3.0-or-later
// Un bloc, plusieurs étages appris ; les commandes ne reconstruisent jamais la chaîne.
import { html, useState, useEffect, useRef, cls } from './lib.js';

export function CaptureModuleControls({ controls, values, onChange, foot, onFoot, scene }) {
  const groups = [...new Set(controls.map(c => c.group || 'Captured controls'))];
  return html`<div class="gcap-controls">
    <p class="gcap-hint">Live capture controls${scene ? ' · scene ' + scene : ''}</p>
    ${groups.map(group => html`<fieldset class="gcap-group"><legend>${group}</legend>
      ${controls.filter(c => (c.group || 'Captured controls') === group).map(c => {
        const value = values[c.id] ?? c.default;
        return c.kind === 'toggle' ? html`<div class="gcap-switch">
          <button class=${cls('gcap-power', !!value && 'gcap-on')} aria-pressed=${!!value}
            onClick=${() => onChange(c.id, value ? 0 : 1)}>${c.name} · ${value ? 'ON' : 'OFF'}</button>
          ${onFoot ? html`<label>MIDI switch <select value=${foot?.[c.id] || ''} aria-label=${c.name + ' MIDI switch'}
            onChange=${e => onFoot(c.id, e.target.value ? Number(e.target.value) : null)}>
            <option value="">Unassigned</option>${[6, 7, 8, 9, 10].map(sw => html`<option value=${sw}>${sw}</option>`)}
          </select></label>` : foot?.[c.id] ? html`<small>MIDI #${foot[c.id]}</small>` : ''}
        </div>` : html`<label class="gcap-knob"><span>${c.name}</span>
          <input type="range" min=${c.min} max=${c.max} step=${(c.max - c.min) / 1000} value=${value}
            aria-label=${c.name} onInput=${e => onChange(c.id, Number(e.target.value))} />
          <output>${(value * 100).toFixed(1)}%</output></label>`;
      })}
    </fieldset>`)}</div>`;
}

export function PhoneCaptures({ preset, scene, lane }) {
  const [rows, setRows] = useState([]), [error, setError] = useState('');
  const work = useRef({ pending: {}, sending: false, timer: null, alive: false });
  useEffect(() => {
    const w = { pending: {}, sending: false, timer: null, alive: true };
    work.current = w; setRows([]); setError('');
    const refresh = async () => {
      try {
        const r = await fetch('/api/lane/capture'); const d = await r.json();
        if (!r.ok) throw new Error(d.error || 'Cannot read capture controls');
        if (w.alive && !w.sending && !Object.keys(w.pending).length && d.preset === preset && d.scene === scene)
          setRows((d.modules || []).filter(m => m.lane === lane));
      } catch (e) { if (w.alive) setError(e.message); }
    };
    refresh(); const poll = setInterval(refresh, 700);
    return () => { w.alive = false; clearInterval(poll); clearTimeout(w.timer); };
  }, [preset, scene, lane]);
  const change = (block, id, value) => {
    const w = work.current;
    setRows(prev => prev.map(r => r.block === block ? { ...r, values: { ...r.values, [id]: value } } : r));
    w.pending[block] = { ...w.pending[block], [id]: value };
    const send = async () => {
      w.timer = null;
      if (!w.alive || w.sending) return;
      w.sending = true;
      try {
        while (w.alive && Object.keys(w.pending).length) {
          const target = Object.keys(w.pending)[0], values = w.pending[target]; delete w.pending[target];
          const r = await fetch('/api/lane/capture', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ preset, scene, block: target, values }) });
          const d = await r.json();
          if (!r.ok || !d.ok) throw new Error(d.error || 'The rack refused the control change');
          if (w.alive) setError('');
        }
      } catch (e) { w.pending = {}; if (w.alive) setError(e.message); }
      finally { w.sending = false; }
    };
    // Cadencer pendant le geste : un debounce n'enverrait rien avant de lâcher le potard.
    if (!w.timer && !w.sending) w.timer = setTimeout(send, 45);
  };
  return html`<div class="gcap-phone">${rows.map(row => html`<section class="c-card" key=${row.block}>
    <b>${row.name}</b><${CaptureModuleControls} controls=${row.controls} values=${row.values} foot=${row.foot}
      scene=${scene} onChange=${(id, v) => change(row.block, id, v)} />
  </section>`)}${error ? html`<p class="c-err" role="alert">${error}</p>` : ''}</div>`;
}
