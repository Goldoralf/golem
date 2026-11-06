// SPDX-License-Identifier: GPL-3.0-or-later
// « Separate a folder… » (docs/separation-batch.md, maquette mockups/separation-folder.html, 2026-10-20) : un GESTE
// ponctuel, donc un modal en trois étapes comme « + Add engine » — Folder, Songs, How. Le suivi vit dans la carte du
// moteur en service (BatchStrip) et dans le modal Queue. golem LIT le dossier, il n'y écrit jamais : chaque morceau
// devient un .golem dans la bibliothèque (Library ▸ Tracks ▸ Backings). Rien ne part vers golem.fm (phase 2).
import { html, useState, useEffect, post, del, cls } from './lib.js';
import { Browser } from './separation-add.js';

const STEPS = [['folder', 'Folder'], ['songs', 'Songs'], ['how', 'How']];
export const hm = s => {
  if (s == null) return '—';
  const m = Math.max(1, Math.round(s / 60));
  return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + String(m % 60).padStart(2, '0');
};
const mmss = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const isVoice = s => /^(vocals|voice)(-|$)/.test(s);
const pct = p => p && p.total ? Math.round(100 * (p.done || 0) / p.total) : null;
// la déclaration d'origine licite que l'avocat demande À CHAQUE DÉPÔT vers golem.fm, à l'unité ou en lot — sa formule du
// 2026-10-21 (note « tablatures en lot », point 2), qui couvre aussi les tablatures. Jamais en local : lire un fichier
// de son disque ne demande rien.
export const DECLARATION = "I declare that I hold the rights to, or own a lawfully acquired copy of, the recordings "
  + "and tablatures I store in my private space on golem.fm.";

export function BatchStepper({ engine, rtf, onClose, onStarted }) {
  const [step, setStep] = useState('folder');
  const [scan, setScan] = useState(null);
  const [sel, setSel] = useState({});                     // clé -> coché
  const [edit, setEdit] = useState({});                   // clé -> {title, artist} corrigés à l'écran
  const [mode, setMode] = useState('full');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [store, setStore] = useState(false);
  const [declared, setDeclared] = useState(false);
  const [quota, setQuota] = useState(null);               // {online, songs: {used, limit}} — lu chez golem.fm
  useEffect(() => {
    if (step === 'how' && !quota) fetch('/api/golemfm/quotas').then(r => r.json()).then(setQuota).catch(() => setQuota({ online: false }));
  }, [step]);
  const stems = (engine && engine.test && engine.test.stems) || [];
  const canVocals = stems.some(isVoice);
  const idx = STEPS.findIndex(([k]) => k === step);

  const read = async dir => {
    setErr(''); setBusy('reading the folder…');
    const r = await post('/api/separation/batch/scan', { dir }).catch(e => e.body);
    setBusy('');
    if (!r || r.ok === false) { setErr((r && r.why) || 'not readable'); return; }
    setScan(r);
    setSel(Object.fromEntries(r.items.filter(i => i.state === 'new').map(i => [i.key, true])));
    setEdit({});
    setStep('songs');
  };
  const items = (scan && scan.items) || [];
  const chosen = items.filter(i => sel[i.key]);
  const total = chosen.reduce((a, i) => a + (i.duration_s || 0), 0);
  const field = (i, k) => (edit[i.key] && edit[i.key][k] != null) ? edit[i.key][k] : (i[k] || '');
  const setField = (i, k, v) => setEdit({ ...edit, [i.key]: { ...(edit[i.key] || {}), [k]: v } });
  const go = async () => {
    setErr(''); setBusy('starting…');
    const r = await post('/api/separation/batch', {
      dir: scan.dir, mode, store, declared: store && declared,
      items: chosen.map(i => ({ key: i.key, title: field(i, 'title'), artist: field(i, 'artist') })),
    }).catch(e => e.body);
    setBusy('');
    if (!r || r.ok === false) { setErr((r && r.why) || 'not started'); return; }
    onStarted(r.batch);
  };

  let body, nav;
  if (step === 'folder') {
    body = html`<span class="sw-q">Which folder?</span>
      <${Browser} want="audio" start="" onPick=${read} onClose=${onClose} />
      <span class="muted sw-small">golem reads this folder and its sub-folders. It never writes in it: each song becomes a${' '}
        <b>.golem</b> in this golem's library (Library ▸ Tracks ▸ Backings). Only your own files — golem never looks for a
        recording, a tablature or lyrics.</span>
      ${busy ? html`<span class="muted">${busy}</span>` : ''}`;
    nav = '';                                              // « Cancel » est déjà dans l'explorateur
  } else if (step === 'songs') {
    const n = k => items.filter(i => i.state === k).length;
    const fresh = items.filter(i => i.state === 'new');
    const allOn = fresh.length && fresh.every(i => sel[i.key]);
    body = html`<div class="sb-head"><span class="sw-q">${items.length} file${items.length === 1 ? '' : 's'} found</span>
        <span class="muted">· ${hm(scan.total_s)} of new audio${n('duplicate') ? ` · ${n('duplicate')} already on this golem` : ''}${n('unreadable') ? ` · ${n('unreadable')} not readable` : ''}</span>
        <span class="grow"></span>${fresh.length ? html`<button class="mini" onClick=${() => setSel(allOn ? {} : Object.fromEntries(fresh.map(i => [i.key, true])))}>${allOn ? 'Select none' : 'Select all'}</button>` : ''}</div>
      <div class="sb-list">
        <div class="sb-li sb-h"><span></span><span>Title</span><span>Artist</span><span>Length</span><span>With</span></div>
        ${items.map(i => {
          const ok = i.state !== 'unreadable';
          return html`<div class=${cls('sb-li', !sel[i.key] && 'off')} key=${i.key}>
            <input type="checkbox" disabled=${!ok} checked=${!!sel[i.key]} onChange=${e => setSel({ ...sel, [i.key]: e.target.checked })} />
            ${ok ? html`<input class="sb-in" value=${field(i, 'title')} title=${i.path} onInput=${e => setField(i, 'title', e.target.value)} />`
              : html`<span class="sb-path" title=${i.path}>${i.path}</span>`}
            ${ok ? html`<input class="sb-in" value=${field(i, 'artist')} placeholder="artist" onInput=${e => setField(i, 'artist', e.target.value)} />`
              : html`<span class="warnish">not readable</span>`}
            <span class="muted">${i.duration_s ? mmss(i.duration_s) : '—'}</span>
            <span>${i.state === 'duplicate' ? html`<small class="muted">on this golem</small>`
              : i.state === 'twice' ? html`<small class="muted">twice here</small>`
              : html`${i.gp ? html`<span class="sb-tag gp">.gp</span>` : ''}${i.lrc ? html`<span class="sb-tag lrc">.lrc</span>` : ''}${i.from === 'name' ? html`<small class="warnish">from file name</small>` : ''}`}</span>
          </div>`;
        })}
      </div>
      <span class="muted sw-small">Title and artist make the song's identity on golem — correct them before you start. Each song is filed as a cover.</span>`;
    nav = html`<button class="chip" onClick=${() => { setScan(null); setStep('folder'); }}>Back</button><span class="grow"></span>
      <span class="muted">${chosen.length} selected · ${hm(total)}</span>
      <button class="primary" disabled=${!chosen.length} onClick=${() => setStep('how')}>Next</button>`;
  } else {
    const gp = chosen.filter(i => i.gp).length, lrc = chosen.filter(i => i.lrc).length;
    body = html`<span class="sw-q">How should golem split them?</span>
      <div class="sw-tiles sb-tiles">
        <button class=${cls('sw-tile', mode === 'full' && 'on')} onClick=${() => setMode('full')}><span class="sw-ic">▤</span><b>Full stems</b>
          <span class="muted">Every stem the engine gives (${stems.join(', ')}). Mute, solo or slow each part.</span></button>
        <button class=${cls('sw-tile', mode === 'vocals' && 'on')} disabled=${!canVocals} title=${canVocals ? '' : 'the engine in use gives no vocals stem'}
          onClick=${() => setMode('vocals')}><span class="sw-ic">🎤</span><b>Vocals</b>
          <span class="muted">${canVocals ? 'The voice, and everything else in one backing stem. Lighter. Songs with a .lrc are ready to sing.' : 'The engine in use gives no vocals stem.'}</span></button>
      </div>
      <div class="sb-facts">
        <span class="muted">Engine</span><b>${engine.label}</b>
        <span class="muted">Time</span><span>${rtf ? html`<b>≈ ${hm(total * rtf)}</b> <span class="muted">at ${rtf.toFixed(2)}× real time</span>` : html`<span class="muted">not measured yet</span>`}<span class="muted"> — golem stops as soon as you play, and goes on after</span></span>
        <span class="muted">Where</span><span>${chosen.length} song${chosen.length === 1 ? '' : 's'} in <b>Library ▸ Tracks ▸ Backings</b>${gp ? ` — ${gp} with a tablature` : ''}${lrc ? `${gp ? ',' : ' —'} ${lrc} with lyrics` : ''}</span>
      </div>
      ${(() => {
        const sec = quota && quota.songs, left = sec && sec.limit != null ? Math.max(0, sec.limit - (sec.used || 0)) : null;
        const off = !(quota && quota.online);
        return html`<label class=${cls('sb-store', off && 'off')}><input type="checkbox" disabled=${off} checked=${store} onChange=${e => setStore(e.target.checked)} />
          <span>☁ <b>Store on golem.fm when done</b> — in your private library, to sync a tablature, analyse the harmony or add a tab
            <small class="muted"> · ${!quota ? 'reading golem.fm…' : off ? 'golem.fm not reachable, or this golem is not paired' : sec ? (sec.limit != null ? `${sec.used} of ${sec.limit} song places used` : `${sec.used} songs stored`) : ''}</small>
            ${store && left != null && left < chosen.length ? html`<small class="warnish"> · only ${left} place${left === 1 ? '' : 's'} left: the songs after that stay on this golem</small>` : ''}</span></label>
          ${store ? html`<label class="sb-decl"><input type="checkbox" checked=${declared} onChange=${e => setDeclared(e.target.checked)} /><span>${DECLARATION}</span></label>` : ''}`;
      })()}`;
    nav = html`<button class="chip" onClick=${() => setStep('songs')}>Back</button><span class="grow"></span>
      <button class="primary" disabled=${!!busy || (store && !declared)} onClick=${go}>${busy || `Separate ${chosen.length} song${chosen.length === 1 ? '' : 's'}`}</button>`;
  }
  return html`<div class="detail sw-scrim" onClick=${e => e.target.classList.contains('sw-scrim') && onClose()}>
    <div class="detail-card cal-card sw-card sb-card">
      <button class="close" onClick=${onClose}>×</button>
      <h2>Separate a folder <small class="muted">— ${scan ? scan.dir.split(/[\\/]/).filter(Boolean).pop() + (step === 'how' ? ` · ${chosen.length} songs · ${hm(total)}` : '') : 'your own recordings, into songs on this golem'}</small></h2>
      <div class="cal-steps sw-steps">${STEPS.map(([k, lab], i) => html`
        <span class=${cls('cal-dot', i === idx && 'on', i < idx && 'done')}>${i < idx ? '✓' : i + 1}</span><span class=${cls('sw-lab', i === idx && 'on')}>${lab}</span>`)}</div>
      <div class="sw-body">${body}${err ? html`<span class="warnish">✗ ${err}</span>` : ''}</div>
      ${nav ? html`<div class="cal-nav">${nav}</div>` : ''}
    </div>
  </div>`;
}

const label = b => `${b.counts.done} of ${b.items.length - b.counts.skipped} done`;

// le lot dans la carte du moteur (la carte montrait déjà « songs waiting »)
export function BatchStrip({ b, onQueue, onAct }) {
  const cur = b.current && b.items.find(i => i.key === b.current.key);
  const p = b.current && pct(b.current.progress);
  const n = b.items.length || 1;
  const failed = b.counts.failed, cancelled = b.counts.cancelled;
  return html`<div class=${cls('sb-strip', b.finished && 'done')}>
    <span class="sb-ic">📁</span>
    <div class="sb-mid">
      <div class="sb-row"><b>${b.name}</b><span class="muted">· ${b.mode === 'vocals' ? 'vocals' : 'full stems'} · ${label(b)}${b.store ? ` · ${b.stored} on golem.fm` : ''}${failed ? ` · ${failed} failed` : ''}${b.finished && cancelled ? ` · ${cancelled} cancelled` : ''}
        ${cur ? html` · now: <b class="sb-cur">${cur.title}</b>${p != null ? ` ${p} %` : ''}` : ''}</span>
        <span class="grow"></span><span class="muted">${b.finished ? '✓ finished' : b.paused ? 'paused' : b.waiting ? 'waiting: ' + b.waiting : b.left_s != null ? '≈ ' + hm(b.left_s) + ' left' : ''}</span></div>
      <div class="sb-bar"><i style=${'width:' + Math.round(100 * (b.counts.done + b.counts.failed) / n) + '%'}></i></div>
    </div>
    ${b.finished ? html`<button class="mini" onClick=${() => onAct('dismiss')}>Done</button>`
      : html`<button class="mini" onClick=${() => onAct(b.paused ? 'resume' : 'pause')}>${b.paused ? 'Resume' : 'Pause'}</button>`}
    <button class="mini" onClick=${onQueue}>Queue ›</button>
  </div>`;
}

const STATE = { done: '✓', running: '●', waiting: '○', failed: '✕', cancelled: '–', skipped: '–' };

const storeCell = (b, i, onAct) => !b.store || i.state !== 'done' ? ''
  : i.store === 'stored' ? html`<small class="ok"> · on golem.fm</small>`
  : i.store === 'sending' || i.store === 'waiting' ? html`<small class="muted"> · ${i.store === 'sending' ? 'storing…' : 'to store'}</small>`
  : i.store === 'failed' ? html`<small class="warnish" title=${i.store_error || ''}> · not stored</small>` : '';

export function QueueModal({ b, onClose, onAct, ask }) {
  const unstored = b.items.filter(i => i.state === 'done' && i.store !== 'stored' && i.store !== 'sending' && i.store !== 'waiting');
  const storeAll = async () => {
    if (!await ask({ title: `Store ${unstored.length} song${unstored.length === 1 ? '' : 's'} on golem.fm?`, ok: 'Store', check: DECLARATION,
      body: 'They go to your private library on golem.fm — only you see them. There you can sync a tablature, analyse the harmony or add a tab.' })) return;
    onAct('store');
  };
  const cancelAll = async () => {
    if (!await ask({ title: 'Cancel the batch?', ok: 'Cancel the batch', danger: true, cancel: 'Keep going',
      body: 'The songs already done stay in your library. The others are not separated.' })) return;
    onAct('cancel');
  };
  return html`<div class="detail sw-scrim" onClick=${e => e.target.classList.contains('sw-scrim') && onClose()}>
    <div class="detail-card cal-card sw-card sb-card">
      <button class="close" onClick=${onClose}>×</button>
      <h2>${b.name} <small class="muted">— ${b.mode === 'vocals' ? 'vocals' : 'full stems'} · ${label(b)}${b.finished ? '' : b.left_s != null ? ' · ≈ ' + hm(b.left_s) + ' left' : ''}</small></h2>
      <div class="sb-bar"><i style=${'width:' + Math.round(100 * (b.counts.done + b.counts.failed) / (b.items.length || 1)) + '%'}></i></div>
      <div class="sw-body">
        <div class="sb-list">
          <div class="sb-li sb-q sb-h"><span></span><span>Title</span><span>Artist</span><span>Length</span><span>State</span></div>
          ${b.items.map(i => {
            const cur = b.current && b.current.key === i.key;
            const p = cur ? pct(b.current.progress) : null;
            return html`<div class=${cls('sb-li sb-q', 'st-' + i.state)} key=${i.key}>
              <span class="sb-st">${STATE[i.state] || ''}</span><span class="sb-t">${i.title}</span><span class="muted">${i.artist || ''}</span>
              <span class="muted">${i.duration_s ? mmss(i.duration_s) : '—'}</span>
              <span>${i.state === 'done' ? html`<span class="ok">in Backings</span>${storeCell(b, i, onAct)}`
                : i.state === 'running' ? (p != null ? html`<span class="sb-bar sm"><i style=${'width:' + p + '%'}></i></span>` : html`<span class="muted">${(b.current && b.current.phase) || 'working'}…</span>`)
                : i.state === 'failed' ? html`<span class="warnish" title=${i.error || ''}>failed</span> <button class="mini" onClick=${() => onAct('retry', i.key)}>Try again</button>`
                : i.state === 'cancelled' ? html`<span class="muted">cancelled</span> <button class="mini" onClick=${() => onAct('retry', i.key)}>Try again</button>`
                : html`<span class="muted">${i.state}</span>`}</span>
            </div>`;
          })}
        </div>
        ${b.waiting && !b.finished ? html`<span class="sb-wait">golem is waiting: <b>${b.waiting}</b>. The batch goes on by itself.</span>` : ''}
      </div>
      <div class="cal-nav">
        ${unstored.length && b.finished ? html`<button class="mini" title=${unstored.map(i => i.store_error).filter(Boolean)[0] || ''} onClick=${storeAll}>☁ Store ${unstored.length} on golem.fm…</button>` : ''}
        ${b.finished ? html`<button class="mini" onClick=${() => { onAct('dismiss'); onClose(); }}>Clear the batch</button>`
          : html`<button class="mini" onClick=${cancelAll}>Cancel the batch</button>`}
        <span class="grow"></span>
        ${b.finished ? '' : html`<button class="mini" onClick=${() => onAct(b.paused ? 'resume' : 'pause')}>${b.paused ? 'Resume' : 'Pause'}</button>`}
        <button class="primary" onClick=${onClose}>Close</button>
      </div>
    </div>
  </div>`;
}

// les gestes du lot, vers le bridge
export async function batchAct(what, key) {
  const r = what === 'pause' ? await post('/api/separation/batch/pause', { paused: true })
    : what === 'resume' ? await post('/api/separation/batch/pause', { paused: false })
    : what === 'cancel' ? await post('/api/separation/batch/cancel', {})
    : what === 'retry' ? await post('/api/separation/batch/retry', { key })
    : what === 'dismiss' ? await del('/api/separation/batch')
    : what === 'store' ? await post('/api/separation/batch/store', { declared: true }) : null;
  return r && r.batch !== undefined ? r.batch : null;
}
