// SPDX-License-Identifier: GPL-3.0-or-later
// Tiroir d'un bloc VST : l'interface d'ORIGINE du plugin, dans sa fenêtre ouverte par REAPER. Décision le mainteneur,
// 2026-10-05 : « le tiroir est illisible », puis « trop de paramètres, personne n'utilisera cela » — la
// grille des paramètres (121 pour une suite d'ampli commerciale) est retirée. Le tiroir ouvre la fenêtre et dit si
// ses réglages sont CAPTURÉS dans le patch (état natif complet, vst_chunk). Les réglages par scène posés
// AVANT (block.params / overrides de scène) restent appliqués : l'en-tête les compte.
import { html, useState, useEffect, useRef, esc, cls } from './lib.js';
import { PowerBtn } from './designer-sheets.js';
import { ParametricCapture } from './capture-parametric.js';

const hhmm = d => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

export function VstHostSheet({ block, sceneId, sceneOff, ovr, onParam, onCapture, onNativeState,
                               onApplyAll, onBypass, onScene, onMove, onRemove, onOpen, onClose, powerOn, onPower, multiScene,
                               patchName, onReplace }) {
  const [openError, setOpenError] = useState('');
  const [opened, setOpened] = useState(false);          // fenêtre ouverte depuis ce tiroir, pas encore capturée
  const [capture, setCapture] = useState(null);         // { at: Date } | { busy: true }
  // La capture n'était VISIBLE nulle part : un échec au retour dans l'app perdait les réglages sans un mot.
  const captureNative = async () => {
    setCapture({ busy: true });
    try {
      const r = await fetch('/api/vst-host/state/' + encodeURIComponent(block.id));
      const state = await r.json();
      if (!r.ok) throw new Error(state.error || 'Native state unavailable');
      onNativeState(state);
      setOpenError('');
      setOpened(false);
      setCapture({ at: new Date() });
    } catch (e) {
      setCapture(null);
      throw e;
    }
  };
  useEffect(() => {
    const onFocus = () => { setTimeout(() => captureNative().catch(e =>
      setOpenError(String(e.message || e))), 250); };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [block.id, onNativeState]);
  const scene = ovr || {};
  const open = () => Promise.resolve(onOpen()).then(r => {
    if (r && r.error) throw new Error(r.error);
    setOpenError(''); setOpened(true);
  }).catch(e => setOpenError(String(e.message || e)));
  const done = () => captureNative().catch(e => setOpenError(String(e.message || e)));
  const [plugName, vendor] = (() => {
    const raw = String(block.plugin || block.label || 'VST plugin').replace(/^(VST3?i?|CLAPi?):\s*/, '');
    const m = raw.match(/^(.*?)\s*\(([^)]*)\)\s*$/);
    return m ? [m[1], m[2]] : [raw, ''];
  })();

  return html`<div class="sheet-scrim" onClick=${e => e.target.classList.contains('sheet-scrim') && onClose()}>
    <div class="sheet vst-host-sheet" style="--tc:#8b9fd7">
      <button class="sheet-tab" onClick=${onClose}><span class="sheet-ic">◈</span>
        <b>${esc(block.label || block.plugin || 'VST Host')}</b><span class="sheet-tab-x">▾</span></button>
      <div class="sheet-head">
        <${PowerBtn} on=${powerOn} onPower=${onPower} sceneId=${multiScene ? sceneId : null} />
        ${multiScene && Object.keys(scene).length ? html`<button class="mini" onClick=${onApplyAll} title="this scene's values become the block's settings in every scene">Use in all scenes</button>` : ''}
        <span class="grow"></span>
        <button class="mini" onClick=${() => onMove(-1)}>←</button>
        <button class="mini" onClick=${() => onMove(1)}>→</button>
        <button class="mini danger" onClick=${onRemove}>🗑</button>
      </div>
      ${openError ? html`<p class="vst-host-error">${esc(openError)}</p>` : ''}
      <div class="sheet-body vh-plugin">
        <div class="vh-card">
          <div class="vh-name">${esc(plugName)}</div>
          ${vendor ? html`<div class="vh-vendor">${esc(vendor)}</div>` : ''}
          <button class="vh-open" onClick=${open}>⧉ Open plugin window</button>
          <p class="vh-hint">The plugin's own interface opens in a separate window. Set it up there, then come back and tap <b>Done</b>.</p>
          <div class="vh-capture">
            <span class=${cls('vh-state', capture?.at && 'ok', opened && !capture?.at && 'pending')}>
              ${capture?.busy ? 'Capturing plugin settings…'
                : opened ? 'Plugin window open — changes not captured yet'
                : capture?.at ? '✓ Plugin settings captured into the patch · ' + hhmm(capture.at)
                : 'Plugin settings are captured when you tap Done'}</span>
            <button class="vh-done" onClick=${done} disabled=${!!capture?.busy}>Done</button>
          </div>
        </div>
        <${CaptureMode} block=${block} patchName=${patchName} onReplace=${onReplace} stamp=${capture?.at} />
      </div>
    </div>
  </div>`;
}

function CaptureMode(props) {
  const [controls, setControls] = useState(false);
  return html`<div class="vh-card vh-capture-mode">
    <div class="vh-seg" aria-label="Capture scope">
      <button class=${cls('vh-seg-b', !controls && 'on')} onClick=${() => setControls(false)}>Current setting</button>
      <button class=${cls('vh-seg-b', controls && 'on')} onClick=${() => setControls(true)}>With controls</button>
    </div>
    ${controls ? html`<${ParametricCapture} ...${props} />` : html`<${NamCapture} ...${props} />`}
  </div>`;
}


// ── CONVERTIR EN CAPTURE NAM (2026-10-05, docs/plugin-capture.md) ────────────────────────────────
// Le son du bloc devient une capture NAM qui joue partout, Linux compris. Le bridge dit d'abord si c'est
// possible (recette du plugin, pédale de modulation allumée, machine prête) ; la capture tourne en tâche
// de fond (rendu ~1 min, entraînement ~7 min sur une RTX 4070, mesure) ; « Use in this patch » remplace le
// bloc par la capture et ses sections traduites (gate, delay, reverb), qui sont des APPROXIMATIONS : dit.
// LE BILAN (maquette mockups/vst-capture-panel.html, 2026-10-10) : golem ne coupe rien à la place du musicien.
// Il NOMME ce qui empêche la capture (« Chorus », sa place, son réglage), ce que la capture contiendra, ce qui
// deviendra des blocs golem (et ce qui s'y perd) ; le musicien règle son plugin, tape Done, golem revérifie.
// Un plugin sans recette se capture aussi, entier, après confirmation. Le (i) dit ce qu'une capture peut contenir.
const RUNNING = ['render', 'train', 'test', 'install', 'cancelling'];
const listOf = a => { a = a || []; return a.length < 2 ? a.join('') : a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1]; };
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

function NamCapture({ block, patchName, onReplace, stamp }) {
  const [st, setSt] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [again, setAgain] = useState(false);          // relancer après une capture terminée (l'autre mode, par ex.)
  // LES OPTIONS AVANT DE LANCER (2026-10-05 : « un patch que j'aime, je ne vais pas avoir envie de
  // l'écraser ») : quoi capturer, le nom de la capture, et où va le résultat — un NOUVEAU patch par défaut.
  const plugShort = String(block.plugin || block.label || 'VST').replace(/^(VST3?i?|CLAPi?):\s*/, '').replace(/\s*\(.*\)\s*$/, '');
  const [mode, setMode] = useState(null);             // null = le défaut (par effet si possible)
  const [capName, setCapName] = useState('');
  const [dest, setDest] = useState('new');
  const [newName, setNewName] = useState('');
  const [renaming, setRenaming] = useState(false);     // le nom de la capture : replié (1024×600, sans défilement)
  const [info, setInfo] = useState(false);
  const [confirmed, setConfirmed] = useState(false);   // plugin sans recette : « I've checked »
  const [gear, setGear] = useState('amp-cab');          // … et son baffle est-il dans le son ? (dit, pas deviné)
  const [cleared, setCleared] = useState([]);          // ce que le musicien vient de couper : rappelé une fois
  const [whole, setWhole] = useState(false);           // sans recette : « Capture the whole plugin… » choisi
  const prevBlockers = useRef([]);
  const q = `block=${encodeURIComponent(block.id)}&plugin=${encodeURIComponent(block.plugin || '')}`;
  const load = () => fetch('/api/vst-host/capture?' + q).then(r => r.json()).then(setSt).catch(() => {});
  const job = st?.job || {};
  const mine = job.block === block.id;
  const running = mine && RUNNING.includes(job.state);
  const setup = st?.setup || {};
  const installing = setup.state === 'running';
  // revérifier quand le musicien revient de la fenêtre du plugin (Done, ou simplement le focus)
  useEffect(() => { load(); }, [block.id, stamp]);
  useEffect(() => {
    const onFocus = () => setTimeout(load, 600);
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [block.id]);
  useEffect(() => {
    const now = (st?.check?.blockers || []).map(b => b.label);
    const gone = prevBlockers.current.filter(l => !now.includes(l));
    if (gone.length && !now.length) setCleared(gone);
    if (now.length) setCleared([]);
    prevBlockers.current = now;
  }, [st]);
  useEffect(() => {
    if (!running && !installing) return;
    const t = setInterval(() => { load(); setNow(Date.now()); }, 2000);
    return () => clearInterval(t);
  }, [running, installing]);
  const install = async () => {
    setErr(''); setBusy(true);
    try {
      const r = await fetch('/api/vst-host/capture/setup', { method: 'POST' });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Installation refused');
      await load();
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };
  const start = async mode => {
    setErr(''); setBusy(true);
    try {
      const r = await fetch('/api/vst-host/capture', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ block: block.id, plugin: block.plugin, patch: patchName, mode,
                               name: capName.trim() || undefined, dest, new_patch: newName.trim() || undefined,
                               confirmed: c.recipe === false ? confirmed : undefined, gear: c.recipe === false ? gear : undefined }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Capture refused');
      setAgain(false);
      await load();
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };
  const stop = async () => {
    setErr(''); setBusy(true);
    try { await fetch('/api/vst-host/capture/cancel', { method: 'POST' }); await load(); }
    catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };
  const use = async () => {
    setErr(''); setBusy(true);
    try {
      const r = await fetch('/api/vst-host/capture/replacement?' + q);
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Replacement unavailable');
      onReplace(d.blocks, job.dest || 'replace', job.new_patch);
    } catch (e) { setErr(String(e.message || e)); setBusy(false); }
  };
  if (!st) return '';
  const c = st.check || {};
  const t = job.test || {};
  const esrs = Object.values(job.train || {}).map(x => x && x.validation_esr).filter(x => x != null);
  const esr = esrs.length ? Math.max(...esrs) : null;
  const warn = job.warning && mine ? html`<p class="vh-cap-warn">⚠ ${esc(job.warning)}</p>` : '';
  return html`<div class="vh-card vh-cap">
    <div class="vh-cap-ttl"><span class="vh-cap-title">Convert to NAM capture</span>
      <button class=${cls('vh-info', info && 'on')} onClick=${() => setInfo(!info)} title="What a NAM capture can hold">i</button></div>
    ${info ? html`<${CaptureInfo} onClose=${() => setInfo(false)} />` : ''}
    ${installing ? html`<p class="vh-cap-run">${esc(setup.msg || 'Installing…')} <span class="vh-cap-time">${mmss((now / 1000) - (setup.started || now / 1000))}</span></p>
          <p class="vh-hint">One-time setup of the capture tools (a few GB). You can keep playing.</p>`
      : !c.ok && c.env && !c.env.ready ? html`<p class="vh-hint">Capturing needs tools this computer doesn't have yet: ${esc((c.env.missing || []).join(', '))}.</p>
          <button class="vh-cap-btn" onClick=${install} disabled=${busy}>Install capture tools</button>
          ${setup.state === 'error' ? html`<p class="vst-host-error">Installation failed: ${esc(setup.error)}</p>` : ''}`
      : !c.ok && !(mine && job.state === 'done') && !(c.blockers || []).length ? html`<p class="vh-cap-why">${esc(c.why || 'Not available')}</p>`
      : running ? html`<p class="vh-cap-run">${esc(job.msg || 'Working…')} <span class="vh-cap-time">${mmss((now / 1000) - (job.started || now / 1000))}</span></p>
          ${warn}
          <p class="vh-hint">${job.mode === 'split' ? 'About 17 min' : 'About 10 min'} on ${esc(c.env?.device || 'this computer')} (~7 min per trained capture). You can keep playing.</p>
          <button class="vh-cap-btn ghost vh-cancel" onClick=${stop} disabled=${busy || job.state === 'cancelling'}>
            ${job.state === 'cancelling' ? 'Cancelling…' : 'Cancel capture'}</button>`
      : mine && job.state === 'done' && !again ? html`
          <p class="vh-cap-ok">✓ In your library: ${esc((job.result?.core || []).map(b => b.label.replace(job.result.name, '').trim() || 'full rig').join(' · '))}</p>
          ${warn}
          <p class="vh-hint">Matches the plugin ${t.synth ? `to ${t.synth.null_db.toFixed(1)} dB (null on a test guitar)` : ''}${esr != null ? ` · training ESR ${esr.toFixed(4)}` : ''}</p>
          <button class="vh-cap-btn" onClick=${use} disabled=${busy}>${job.dest === 'new'
            ? html`Create the patch “${esc(job.new_patch || 'capture')}”` : 'Replace in this patch'}</button>
          <p class="vh-hint">${job.dest === 'new' ? 'A copy of this patch where' : 'In this patch,'} the VST block becomes ${job.mode === 'split' ? 'one capture block per effect' : 'the capture block'}, plus a gate, delay and reverb set like the plugin (approximate).${job.dest === 'new' ? ' This patch stays as it is.' : ''}</p>
          <button class="vh-cap-btn ghost" onClick=${() => setAgain(true)}>Capture again</button>`
      : (() => {
          const split = (c.split || []).length > 0;
          const m = mode || (split ? 'split' : 'full');
          const blocked = (c.blockers || []).length > 0;
          const generic = c.recipe === false;
          const canStart = !blocked && (!generic || confirmed);
          // sans recette : d'abord la voie golem.fm (docs/plugin-recipes.md), la capture entière en second
          if (generic && !whole) return html`<${RecipePanel} block=${block} onWhole=${() => setWhole(true)} onReady=${load} />`;
          return html`
          <${Verdict} c=${c} cleared=${cleared} />
          ${blocked ? html`<p class="vh-how"><b>To capture:</b> open the plugin window (left), turn ${(c.blockers.length > 1 ? 'them' : 'it')} off, then tap <b>Done</b>. golem checks again on its own.</p>
              <button class="vh-cap-btn" disabled>Start capture</button>`
          : html`
          ${generic ? html`
            <label class=${cls('vh-chk', confirmed && 'on')}><input type="checkbox" checked=${confirmed} onChange=${e => setConfirmed(e.target.checked)} />
              I've checked — only drive, amp, EQ and cab are on in the plugin.</label>
            <div class="vh-opt">
              <span class="vh-opt-l">Its cab</span>
              <div class="vh-seg">
                <button class=${cls('vh-seg-b', gear === 'amp-cab' && 'on')} onClick=${() => setGear('amp-cab')}>On (full rig)</button>
                <button class=${cls('vh-seg-b', gear === 'amp' && 'on')} onClick=${() => setGear('amp')}>None (amp only)</button>
              </div>
            </div>` : ''}
          ${split ? html`<div class="vh-opt">
            <span class="vh-opt-l">Capture</span>
            <div class="vh-seg">
              <button class=${cls('vh-seg-b', m === 'full' && 'on')} onClick=${() => setMode('full')}>One capture</button>
              <button class=${cls('vh-seg-b', m === 'split' && 'on')} onClick=${() => setMode('split')}
                title="one NAM capture per pedal and amp, the cab as an impulse response — measured more faithful">
                ${'Per effect · ' + c.split.map(x => x.label).join(', ')}</button>
            </div>
          </div>` : ''}
          ${renaming ? html`<div class="vh-opt">
            <span class="vh-opt-l">Name</span>
            <input class="vh-in" value=${capName} placeholder=${patchName + ' — ' + plugShort} onInput=${e => setCapName(e.target.value)} />
          </div>` : html`<p class="vh-hint vh-named">Saved as “${esc(capName.trim() || patchName + ' — ' + plugShort)}”${dest === 'new' ? html`, in the new patch “${esc(newName.trim() || patchName + ' — capture')}”` : ''} ·
            <button class="vh-link" onClick=${() => setRenaming(true)}>rename</button></p>`}
          <div class="vh-opt">
            <span class="vh-opt-l">Result</span>
            <div class="vh-seg">
              <button class=${cls('vh-seg-b', dest === 'new' && 'on')} onClick=${() => setDest('new')}>New patch</button>
              <button class=${cls('vh-seg-b', dest === 'replace' && 'on')} onClick=${() => setDest('replace')}>Replace in this patch</button>
            </div>
          </div>
          ${dest === 'new' ? (!renaming ? '' : html`<div class="vh-opt"><span class="vh-opt-l">Patch</span>
            <input class="vh-in" value=${newName} placeholder=${patchName + ' — capture'} onInput=${e => setNewName(e.target.value)} /></div>`)
            : html`<p class="vh-hint vh-warn">The VST block of this patch will be replaced. Pick “New patch” to keep it.</p>`}
          <button class="vh-cap-btn" onClick=${() => start(m)} disabled=${busy || !canStart}>Start capture</button>
          <p class="vh-hint">${generic ? 'Captures the whole plugin as it is set.' : 'Gate, delay and reverb become golem blocks.'} Plays on any golem, Linux included.</p>`}
          ${mine && job.state === 'error' ? html`<p class="vst-host-error">Last attempt failed: ${esc(job.error)}</p>` : ''}
          ${mine && job.state === 'cancelled' ? html`<p class="vh-hint">Last capture cancelled.</p>` : ''}`;
        })()}
    ${err ? html`<p class="vst-host-error">${esc(err)}</p>` : ''}
  </div>`;
}


// le bandeau et les lignes du bilan (ce qui bloque, ce qui est capturé, ce qui devient des blocs golem)
function Verdict({ c, cleared }) {
  const det = x => x.detail ? html` <small>${esc(x.detail)}</small>` : '';
  const blockers = c.blockers || [];
  if (c.recipe === false) return html`
    <div class="vh-ban unk"><span class="vh-ban-i">?</span><div><b>golem can't read this plugin's pedals</b>
      <span>Check its window yourself — golem captures whatever is on.</span></div></div>
    <div class="vh-what">
      <div class="vh-row"><span class="vh-k g">✓ Leave on</span><span>Drive, boost, amp, EQ, cab</span></div>
      <div class="vh-row"><span class="vh-k r">✕ Turn off</span><span>Modulation, pitch, glitch, delay, reverb, gate <small>— see (i)</small></span></div>
    </div>`;
  return html`
    ${blockers.length ? html`
      <div class="vh-ban bad"><span class="vh-ban-i">⛔</span><div>
        <b>Can't capture yet — ${blockers.length} effect${blockers.length > 1 ? 's are' : ' is'} on</b>
        <span>A capture is a fixed snapshot of the sound. ${blockers.length > 1 ? 'These effects move' : 'This effect moves'} over time or change${blockers.length > 1 ? '' : 's'} the pitch, so ${blockers.length > 1 ? 'they' : 'it'} can't be in it.</span></div></div>
      ${blockers.map(b => html`<div class="vh-blk"><span class="vh-blk-ic">${b.kind === 'pitch' ? '♯' : '≋'}</span>
        <div class="vh-blk-t"><b>${esc(b.label)}</b><small>${esc([b.where, b.detail].filter(Boolean).join(' · '))}</small></div>
        <span class="vh-blk-tag">TURN OFF</span></div>`)}`
    : html`<div class="vh-ban ok"><span class="vh-ban-i">✓</span><div><b>Ready — nothing blocks the capture</b>
        ${c.source?.from === 'golem.fm' ? html`<span>Recipe from golem.fm, checked on this golem${c.source.shared ? ' and on others' : ''}.</span>` : ''}
        ${cleared.length ? html`<span>${esc(cleared.join(' and '))} ${cleared.length > 1 ? 'are' : 'is'} off. Missing ${cleared.length > 1 ? 'them' : 'it'}? Add ${cleared.length > 1 ? 'golem ' + esc(cleared.join(' and ')) + ' blocks' : 'a golem ' + esc(cleared[0]) + ' block'} before the capture afterwards.</span>` : ''}</div></div>`}
    <div class="vh-what">
      ${(c.captured || []).length ? html`<div class="vh-row"><span class="vh-k g">✓ Captured</span>
        <span>${(c.captured).map((x, i) => html`${i ? ' · ' : ''}${esc(x.label)}${det(x)}`)}</span></div>` : ''}
      ${(c.rebuilt || []).length ? html`<div class="vh-row"><span class="vh-k a">↻ golem blocks</span>
        <span>${(c.rebuilt).map((x, i) => html`${i ? ' · ' : ''}${esc(x.label)}${det(x)}${x.loss ? html` <small class="vh-loss">— ${esc(x.loss)}</small>` : ''}`)}</span></div>` : ''}
    </div>`;
}

// le (i) : ce qu'une capture NAM peut contenir — pour TOUT plugin, avec ou sans recette
function CaptureInfo({ onClose }) {
  return html`<div class="vh-pop">
    <div class="vh-pop-h"><b>What a NAM capture can hold</b><button onClick=${onClose}>×</button></div>
    <p>A capture is a snapshot of how the plugin shapes your sound <b>at one instant</b>. Anything that moves over time,
      changes pitch or repeats can't be in it.</p>
    <div class="vh-grp g"><h4>✓ Captured</h4><div>Boost · overdrive · distortion · fuzz · preamp · amp · EQ · cab <i>— compressors only roughly</i></div></div>
    <div class="vh-grp a"><h4>↻ Rebuilt as golem blocks</h4><div>Noise gate · delay · reverb <i>— when they sit after the amp. Close to the plugin, not identical.</i></div></div>
    <div class="vh-grp r"><h4>✕ Can't be captured — turn them off</h4><div>
      <b>Modulation</b> <i>chorus, flanger, phaser, tremolo, vibrato, rotary, uni-vibe</i><br />
      <b>Pitch</b> <i>whammy, octaver, harmonizer, detune</i><br />
      <b>Glitch</b> <i>stutter, beat repeat, granular, freeze, reverse</i><br />
      <b>Reacts to your playing</b> <i>auto-wah, envelope filter, ducking, sidechain</i></div></div>
  </div>`;
}


// ── LA RECETTE D'UN PLUGIN INCONNU (docs/plugin-recipes.md, maquette mockups/vst-recipe-validate.html) ─────────
// golem.fm (son IA) PROPOSE, ce golem MESURE chaque affirmation, le musicien VALIDE — et peut corriger une ligne
// (renommer, retirer) avant (2026-10-10). Une recette déjà validée ailleurs passe par le même écran.
const RECIPE_BUSY = ['analyzing', 'verifying'];
const GROUPS = [['captured', 'Captured'], ['refuse', 'Blocks a capture'], ['translate', 'Becomes golem blocks'],
                ['split', 'Per-effect capture']];

function RecipePanel({ block, onWhole, onReady }) {
  const [rec, setRec] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [edits, setEdits] = useState({});            // id -> {label?} | {removed: true}
  const [editing, setEditing] = useState(null);
  const plugin = block.plugin || '';
  const load = () => fetch('/api/vst-host/recipe?plugin=' + encodeURIComponent(plugin)).then(r => r.json())
    .then(d => { setRec(d); if (d.state === 'validated') onReady(); }).catch(() => {});
  useEffect(() => { load(); }, [plugin]);
  useEffect(() => {
    if (!rec || !RECIPE_BUSY.includes(rec.state)) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [rec && rec.state]);
  const post = async (url, body) => {
    setErr(''); setBusy(true);
    try {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Refused');
      await load();
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };
  const ask = () => post('/api/vst-host/recipe/analyze', { block: block.id, plugin, restart: true });
  const discard = () => { setEdits({}); post('/api/vst-host/recipe/forget', { plugin }); };
  const validate = () => post('/api/vst-host/recipe/validate', {
    plugin, edits: Object.entries(edits).map(([id, e]) => ({ id, ...e })) });
  if (!rec) return '';
  const s = rec.state;

  if (RECIPE_BUSY.includes(s)) {
    const step = rec.step || (s === 'verifying' ? 'measure' : 'sheet');
    const order = ['sheet', 'ai', 'measure', 'check'];
    const at = order.indexOf(step);
    const row = (k, n, label, detail) => { const i = order.indexOf(k);
      return html`<div class=${cls('vh-step', i < at && 'ok', i === at && 'on')}><span class="vh-step-d">${i < at ? '✓' : n}</span>${label}
        ${detail ? html`<small>${detail}</small>` : ''}</div>`; };
    const sc = rec.sheet_counts;
    return html`
      <div class="vh-ban ai"><span class="vh-ban-i">✨</span><div><b>Building a recipe for ${esc(plugin.replace(/^[A-Z0-9]+i?:\s*/, '').replace(/\s*\(.*$/, ''))}</b>
        <span>${rec.shared ? 'golem.fm already knows this plugin — measuring it here.' : 'You can close this drawer and keep playing.'}</span></div></div>
      <div class="vh-steps">
        ${row('sheet', 1, 'Read the plugin', sc ? `${sc.params} settings, ${sc.switches} switches` : '')}
        ${rec.shared ? '' : row('ai', 2, "golem.fm's AI drafts a recipe", '')}
        ${row('measure', 3, 'Measure each claim on this golem', rec.claims ? `${rec.claims} claims` : '')}
        ${row('check', 4, 'Your check', '')}
      </div>
      ${rec.waiting ? html`<p class="vh-wait">⏸ Waiting — ${esc(rec.waiting)}. Measuring starts again when it stops.</p>` : ''}
      <button class="vh-cap-btn ghost" onClick=${discard} disabled=${busy}>Cancel</button>
      ${err ? html`<p class="vst-host-error">${esc(err)}</p>` : ''}`;
  }

  if (s === 'to-validate' && rec.draft) {
    const v = rec.verification || {};
    const rejected = Object.fromEntries((v.rejected || []).map(r => [r.id, r.why]));
    const verified = new Set(v.verified || []);
    const d = rec.draft;
    const lists = { captured: d.full?.captured || [], refuse: d.full?.refuse || [], translate: d.translate || [],
                    split: d.split?.parts || [] };
    const line = c => {
      const rej = rejected[c.id], e = edits[c.id] || {}, gone = e.removed;
      const label = e.label || c.label || c.show || c.block || c.id;
      const pill = rej ? ['r', 'REJECTED'] : verified.has(c.id) ? ['m', 'MEASURED'] : ['d', 'DECLARED'];
      return html`<div class=${cls('vh-cl', rej && 'rej', gone && 'gone')}>
        <div class="vh-cl-t">${editing === c.id
          ? html`<input class="vh-in" value=${label} autoFocus onBlur=${() => setEditing(null)}
              onKeyDown=${ev => ev.key === 'Enter' && setEditing(null)}
              onInput=${ev => setEdits({ ...edits, [c.id]: { label: ev.target.value } })} />`
          : html`<b>${esc(label)}</b>`}
          <small>${esc(rej || c.why || '')}</small></div>
        <span class=${'vh-pill ' + pill[0]}>${gone ? 'REMOVED' : pill[1]}</span>
        ${rej ? '' : html`<button class="vh-cl-b" title="Rename" onClick=${() => setEditing(c.id)}>✎</button>
          <button class="vh-cl-b" title=${gone ? 'Keep' : 'Remove'} onClick=${() => {
            const n = { ...edits }; if (gone) delete n[c.id]; else n[c.id] = { removed: true }; setEdits(n); }}>${gone ? '↺' : '✕'}</button>`}
      </div>`;
    };
    return html`
      <div class="vh-ban ai"><span class="vh-ban-i">✨</span><div><b>Check the recipe</b>
        <span>${rec.shared ? `golem.fm's recipe, validated on ${rec.shared_validations || 'other'} golem${rec.shared_validations === 1 ? '' : 's'}, measured again here.`
          : 'Compare with the plugin. Rename (✎) or remove (✕) a wrong line.'}</span></div></div>
      <div class="vh-claims">
        ${GROUPS.filter(([k]) => lists[k].length).map(([k, title]) => html`<div class="vh-grp-t">${title}</div>${lists[k].map(line)}`)}
      </div>
      <p class="vh-hint vh-legend"><b class="m">MEASURED</b> by the sound · <b>DECLARED</b> unmeasurable ·${' '}<b class="r">REJECTED</b> unused</p>
      <div class="vh-acts">
        <button class="vh-cap-btn ghost" onClick=${discard} disabled=${busy}>Discard</button>
        <button class="vh-cap-btn" onClick=${validate} disabled=${busy}>This matches my plugin</button>
      </div>
      ${err ? html`<p class="vst-host-error">${esc(err)}</p>` : ''}`;
  }

  // pas encore de recette, ou un échec dit : la demande, puis la capture entière en second
  const why = { unsupported: "golem.fm can't build a recipe for this plugin (an instrument, or pedals that can be reordered).",
                failed: rec.error || 'The recipe could not be built.',
                rejected: 'The measures rejected the recipe golem.fm proposed.' }[s];
  return html`
    <div class="vh-ban ai"><span class="vh-ban-i">✨</span><div><b>golem has no recipe for this plugin yet</b>
      <span>With one, golem names what blocks a capture and can capture effect by effect.</span></div></div>
    ${why ? html`<p class="vh-cap-why">${esc(why)}</p>` : ''}
    ${s === 'unsupported' ? '' : html`<button class="vh-cap-btn ai" onClick=${ask} disabled=${busy}>${s ? 'Ask golem.fm again' : 'Ask golem.fm to analyze it'}</button>
      <p class="vh-hint vh-small">golem.fm's AI reads the plugin's settings (no audio leaves this computer). This golem then${' '}<b>measures every claim</b> — about 1 min. You check the result before anything is used.</p>`}
    <div class="vh-or">or capture the whole plugin now</div>
    <button class="vh-cap-btn ghost" onClick=${onWhole}>Capture the whole plugin…</button>
    ${err ? html`<p class="vst-host-error">${esc(err)}</p>` : ''}`;
}

