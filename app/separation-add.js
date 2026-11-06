// SPDX-License-Identifier: GPL-3.0-or-later
// « + Add engine » en STEPPER (2026-10-12 — mockups/separation-add-stepper.html) : une question par écran, comme
// Calibration ▸ Calibrate (carte .detail-card.cal-card, pastilles .cal-steps, Back / Next en pied). Remplace le formulaire
// unique du tiroir. Rien n'est NOMMÉ par golem : le chemin, la commande et les fichiers sont ceux que l'utilisateur
// apporte ; l'exemple est fictif ; les aides par symptôme sont génériques (avis de l'avocat du 2026-10-12, separation.md §4 ter).
import { html, useState, useEffect, useRef, post, del, cls, saveFile } from './lib.js';
import { fillFields, fieldsMissing } from './separation-fields.js';

const STEM_CHOICES = ['', 'vocals', 'drums', 'bass', 'guitar', 'piano', 'keys', 'strings', 'wind', 'other'];
const FLOWS = {
  program: [['what', 'What'], ['program', 'Program'], ['command', 'Command'], ['try', 'Try it'], ['name', 'Name'], ['test', 'Test']],
  onnx: [['what', 'What'], ['model', 'Model file'], ['name', 'Name'], ['test', 'Test']],
  combine: [['what', 'What'], ['first', 'First pass'], ['second', 'Second pass'], ['name', 'Name'], ['test', 'Test']],
};
const mmss = t => `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, '0')}`;

// l'extrait de test (§6) : un enregistrement de l'UTILISATEUR, choisi ici ; il reste sur ce golem
export function Excerpt({ x, onDone }) {
  const [msg, setMsg] = useState('');
  const pick = async ev => {
    const f = ev.target.files && ev.target.files[0];
    ev.target.value = '';
    if (!f) return;
    setMsg('reading…');
    const r = await fetch('/api/separation/excerpt?name=' + encodeURIComponent(f.name), { method: 'POST', body: f })
      .then(r => r.json()).catch(() => ({ why: 'upload failed' }));
    setMsg(r.ok ? '' : '✗ ' + (r.why || 'not accepted'));
    onDone();
  };
  return html`<div class=${cls('sep-excerpt', !x && 'missing')}>
    <span>${x ? html`Test excerpt: <b>${x.name}</b> <span class="muted">· ${x.seconds} s from ${mmss(x.start || 0)} — every engine is tried on it</span>`
      : 'Choose a test excerpt — a recording of yours with several instruments. It stays on this golem.'}</span>
    <label class="mini sep-pick edit-only">${x ? 'Change…' : 'Choose a file…'}
      <input type="file" accept="audio/*,.wav,.flac,.mp3,.ogg,.m4a,.aif,.aiff,.opus" onChange=${pick} /></label>
    ${msg ? html`<span class=${msg.startsWith('✗') ? 'warnish' : 'muted'}>${msg}</span>` : ''}
  </div>`;
}

// « Browse… » : les dossiers, et les fichiers qui peuvent servir (exécutables, .onnx, tout fichier) — ou, en `dir`,
// le dossier lui-même (« Use this folder »). En `audio` (Separate a folder) : on choisit le DOSSIER, ses morceaux
// se voient mais ne se tapent pas.
export function Browser({ want, start, onPick, onClose }) {
  const pickDir = want === 'dir' || want === 'audio';
  const [at, setAt] = useState(start || '');
  const [d, setD] = useState(null);
  useEffect(() => {
    fetch('/api/separation/browse?want=' + want + '&path=' + encodeURIComponent(at || '')).then(r => r.json())
      .then(setD).catch(() => setD({ why: 'not readable' }));
  }, [at]);
  return html`<div class="sw-browse">
    <div class="sep-row"><code class="sw-browse__at">${(d && d.path) || '…'}</code>
      <span class="sep-row__r">${d && d.parent ? html`<button class="mini" onClick=${() => setAt(d.parent)}>↑ Up</button>` : ''}
        ${pickDir && d && d.path ? html`<button class="mini primary" onClick=${() => onPick(d.path)}>Use this folder</button>` : ''}
        <button class="mini" onClick=${onClose}>Cancel</button></span></div>
    <div class="sw-browse__list">
      ${!d ? html`<span class="muted">reading…</span>` : d.why ? html`<span class="warnish">${d.why}</span>` : html`
        ${d.dirs.map(n => html`<button class="sw-browse__it dir" onClick=${() => setAt(d.path + '/' + n)}>📁 ${n}</button>`)}
        ${d.files.map(n => want === 'audio'
          ? html`<span class="sw-browse__it file off">${/\.(gp|lrc)$/i.test(n) ? '🎼' : '🎵'} ${n}</span>`
          : html`<button class="sw-browse__it file" onClick=${() => onPick(d.path + '/' + n)}>${want === 'onnx' ? '◆' : want === 'file' ? '📄' : '⌨'} ${n}</button>`)}
        ${!d.dirs.length && !d.files.length ? html`<span class="muted">${pickDir ? 'no sub-folder — use this one, or go up' : 'nothing here'}</span>` : ''}`}
    </div>
  </div>`;
}

// les arguments en ÉTIQUETTES : on tape, Entrée ajoute ; ✕ retire ; les jetons s'insèrent par leurs pastilles
function ArgTags({ args, setArgs }) {
  const [draft, setDraft] = useState('');
  const box = useRef(null);
  const push = v => { v = v.trim(); if (v) setArgs([...args, v]); setDraft(''); };
  return html`<div class="sw-args" onClick=${() => box.current && box.current.focus()}>
    ${args.map((a, i) => html`<span class=${cls('sw-arg', /^\{[a-z_]+\}$/.test(a) && 'tok')}>${a}
      <button title="remove" onClick=${ev => { ev.stopPropagation(); setArgs(args.filter((_, k) => k !== i)); }}>✕</button></span>`)}
    <input ref=${box} class="sw-args__in" spellcheck="false" placeholder=${args.length ? 'type an argument, Enter…' : 'type the first argument, Enter…'}
      value=${draft} onInput=${e => setDraft(e.target.value)}
      onKeyDown=${e => { if (e.key === 'Enter') { e.preventDefault(); push(draft); }
        else if (e.key === 'Backspace' && !draft && args.length) setArgs(args.slice(0, -1)); }}
      onBlur=${() => draft && push(draft)} />
  </div>`;
}

// le fichier de moteur (golem-engine/1) : dans les Téléchargements de la machine, ou sur l'appareil distant (lib.saveFile)
export async function exportEngine(e) {
  const doc = await fetch(`/api/separation/engines/${e.id}/export`).then(r => r.json());
  const name = (e.label || 'engine').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') + '.golem-engine.json';
  return saveFile(name, { blob: new Blob([JSON.stringify(doc, null, 1)], { type: 'application/json' }) });
}

// L'aide que le PROGRAMME donne sur lui-même (2026-10-12) : ses options deviennent des pastilles qu'un tap ajoute
// aux arguments ; le texte complet se déplie, avec un filtre. Lue, jamais devinée — golem n'y ajoute rien.
function ProgramHelp({ help, open, setOpen, q, setQ, args, onAdd }) {
  if (!help) return '';
  if (help.loading) return html`<div class="sw-help"><span class="sw-run"><span class="sw-spin"></span><span class="muted">reading the program's help…</span></span></div>`;
  if (!help.ok) return html`<div class="sw-help"><span class="muted">${help.why}</span></div>`;
  const used = new Set(args);
  const lines = help.text.split('\n');
  const shown = q ? lines.filter(l => l.toLowerCase().includes(q.toLowerCase())) : lines;
  return html`<div class="sw-help">
    <div class="sep-row"><b>The program's options</b><span class="muted">from its ${help.flag} — tap one to add it</span>
      <span class="sep-row__r"><button class="chip" onClick=${() => setOpen(!open)}>${open ? 'Hide its help' : 'Show its help'}</button></span></div>
    <div class="sw-opts">${help.options.map(o => html`<button class=${cls('sw-opt', used.has(o) && 'used')} title=${used.has(o) ? 'already in the command' : 'add ' + o}
      onClick=${() => onAdd(o)}>${o}</button>`)}</div>
    ${open ? html`<input class="sw-help__q" placeholder="filter the help — e.g. output, format, model" value=${q} onInput=${e => setQ(e.target.value)} />
      <pre class="sw-help__txt">${shown.join('\n') || '(nothing matches)'}${help.truncated ? '\n…' : ''}</pre>` : ''}
  </div>`;
}

const Hints = ({ list }) => list && list.length ? html`<div class="sw-hint"><b>What usually causes this</b>${list.map(h => html`<span>• ${h}</span>`)}</div>` : '';

// (la 5e case, « un service payant en ligne », est retirée avec les services payants : v0.6, 2026-10-31)
export function AddStepper({ excerpt, engines = [], onExcerpt, onClose, onDone }) {
  const [kind, setKind] = useState(null);                 // 'program' | 'onnx'
  const [step, setStep] = useState('what');
  const [program, setProgram] = useState('');
  const [checks, setChecks] = useState(null);
  const [args, setArgs] = useState(['{input}', '{outdir}']);
  const [found, setFound] = useState(null);               // §4 quinquies : les programmes libres DÉTECTÉS ici
  const [recipe, setRecipe] = useState(null);             // la recette choisie : sa plomberie + ses CHAMPS
  const [vals, setVals] = useState({});                   // ce que l'utilisateur tape dans les champs (le modèle…)
  const [fieldBrowse, setFieldBrowse] = useState(null);   // le champ dont on parcourt les fichiers
  const [probe, setProbe] = useState(null);
  const [map, setMap] = useState({});
  const [source, setSource] = useState('');
  const [info, setInfo] = useState(null);
  const [label, setLabel] = useState('');
  const [licence, setLicence] = useState('');
  const [accepted, setAccepted] = useState(false);
  const [engine, setEngine] = useState(null);             // l'id ajouté
  const [result, setResult] = useState(null);             // le test LU
  const [browse, setBrowse] = useState(null);
  const [busy, setBusy] = useState('');
  const [help, setHelp] = useState(null);                 // l'aide du programme (--help, sinon -h), lue
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpQ, setHelpQ] = useState('');
  // « Combine two of my engines » (mockups/separation-combine.html)
  const [first, setFirst] = useState(null);
  const [keep, setKeep] = useState([]);
  const [second, setSecond] = useState(null);
  const [imported, setImported] = useState(null);         // un fichier de moteur COMBINÉ : {doc, form}
  const eligible = engines.filter(e => e.kind !== 'combined' && (e.test || {}).ok);
  const eng = id => engines.find(e => e.id === id);
  const stemsOf = e => ((e && e.test) || {}).stems || [];
  const [err, setErr] = useState('');
  const flow = FLOWS[kind || 'program'];
  const idx = flow.findIndex(([k]) => k === step);
  const go = k => { setErr(''); setStep(k); };

  // l'AIDE du programme, chargée dès que l'étape Program est au vert : l'étape Command l'a déjà sous la main
  useEffect(() => {
    if (!(checks && checks.ok) || (help && help.program === program)) return;
    setHelp({ program, loading: true });
    post('/api/separation/program-help', { program }).then(r => setHelp({ ...r, program }))
      .catch(() => setHelp({ program, ok: false, why: 'the help could not be read' }));
  }, [checks && checks.ok, program]);
  // ② les programmes libres trouvés sur ce golem (lus une fois)
  useEffect(() => {
    if (step !== 'program' || found) return;
    fetch('/api/separation/programs').then(r => r.json()).then(d => setFound(d.programs || [])).catch(() => setFound([]));
  }, [step]);
  // ② le programme : vérifié à chaque changement (léger délai)
  useEffect(() => {
    if (step !== 'program' || !program) { setChecks(null); return; }
    const t = setTimeout(() => post('/api/separation/check-program', { program }).then(setChecks).catch(() => setChecks(null)), 250);
    return () => clearTimeout(t);
  }, [program, step]);
  // ⑥ le test : relu jusqu'à son verdict
  useEffect(() => {
    if (step !== 'test' || !engine || result) return;
    const t = setInterval(async () => {
      const d = await fetch('/api/separation?remote=false').then(r => r.json()).catch(() => null);
      if (!d) return;
      const e = (d.engines || []).find(x => x.id === engine);
      if (e && (!d.test || d.test.id !== engine) && e.test && e.test.tested_at) { setResult(e); onDone(); }
      else setBusy(d.test && d.test.id === engine ? (d.test.phase === 'silence' ? 'testing on 30 s of silence…' : 'testing on your excerpt…') : 'starting the test…');
    }, 1200);
    return () => clearInterval(t);
  }, [step, engine, result]);

  const runProbe = async () => {
    setProbe({ running: true });
    const r = await post('/api/separation/probe', { program, args: run }).catch(e => e.body || { error: String(e) });
    if (r && r.ok) setMap(Object.fromEntries(r.files.map(x => [x, (r.guess || {})[x] || ''])));
    setProbe(r && r.ok ? r : { ok: false, error: (r && (r.error || r.why)) || 'the try failed', log_tail: r && r.log_tail,
      files: (r && r.files) || [], hints: (r && r.hints) || [] });
  };
  const readModel = async () => {
    setBusy('reading the file…'); setInfo(null); setErr('');
    const r = await post('/api/separation/inspect', { source }).catch(e => e.body || { why: String(e) });
    setBusy('');
    if (r && r.ok) { setInfo(r); if (!label && r.name) setLabel(r.name); if (!licence && r.licence) setLicence(r.licence); }
    else setErr((r && r.why) || 'this file could not be read');
  };
  const importFile = async ev => {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = '';
    if (!file) return;
    let doc = null;
    try { doc = JSON.parse(await file.text()); } catch { setErr('not a golem engine file'); return; }
    const r = await post('/api/separation/import', doc).catch(e => e.body);
    if (!(r && r.ok)) { setErr((r && r.why) || 'not a golem engine file'); return; }
    const f = r.form;
    if (f.kind === 'combined') {                         // deux programmes + la règle : relus, puis installés et testés
      setImported({ doc, form: f }); setKind('combine'); setLabel(f.label); go('name'); return;
    }
    setKind('program'); setProgram(f.program); setArgs(f.args); setLabel(f.label); setLicence(f.licence);
    setMap(f.outputs || {}); setProbe(Object.keys(f.outputs || {}).length ? { ok: true, files: Object.keys(f.outputs), imported: true } : null);
    go('name');                                            // tout est rempli : on relit, on coche, on teste
  };
  const addAndTest = async () => {
    setBusy('adding…'); setErr('');
    if (kind === 'combine' && imported) {
      const r = await post('/api/separation/import-combined', { doc: imported.doc, accepted }).catch(e => e.body || { why: String(e) });
      if (!(r && r.ok)) { setBusy(''); setErr((r && r.why) || 'could not import'); return; }
      go('test');
      const t = setInterval(async () => {                // les deux moteurs, puis la combinaison, chacun testé
        const d = await fetch('/api/separation?remote=false').then(x => x.json()).catch(() => null);
        const im = d && d.import;
        if (!im) return;
        if (im.phase === 'done') { clearInterval(t); setEngine(im.engine); onDone(); }
        else if (im.phase === 'failed') { clearInterval(t); setBusy(''); setErr(im.error); onDone(); }
        else setBusy(im.phase + '…');
      }, 1200);
      return;
    }
    if (kind === 'combine') {
      const r = await post('/api/separation/combine', { first, keep, second, label, accepted }).catch(e => e.body || { why: String(e) });
      setBusy('');
      if (!(r && r.ok)) { setErr((r && r.why) || 'could not combine'); return; }
      setEngine(r.engine); setResult(null); go('test'); onDone();
      return;
    }
    const body = kind === 'onnx'
      ? { kind, source: (info && info.source) || source, label, licence, accepted }
      : { kind, program, args: run, label, licence, accepted, outputs: probe && probe.ok ? map : null };
    const r = await post('/api/separation/engines', body).catch(e => e.body || { why: String(e) });
    setBusy('');
    if (!(r && r.ok)) { setErr((r && r.why) || 'could not add'); return; }
    setEngine(r.engine); setResult(null); go('test'); onDone();
  };
  const backFromFailedTest = async () => {
    if (engine) await del('/api/separation/engines/' + engine).catch(() => null);   // on corrige, puis on rajoute
    setEngine(null); setResult(null); onDone();
    go(kind === 'onnx' ? 'model' : kind === 'combine' ? 'first' : 'command');
  };
  const useIt = async () => {
    const r = await post(`/api/separation/engines/${engine}/activate`, {}).catch(e => e.body);
    if (r && r.ok === false) { setErr(r.why || 'could not use it'); return; }
    onDone(); onClose();
  };

  const fields = (recipe && recipe.fields) || [];
  const run = recipe ? fillFields(args, fields, vals) : args;      // les arguments RÉELS (champs remplis)
  const missing = recipe ? fieldsMissing(args, fields, vals) : [];
  // un fichier choisi : le champ prend son NOM ou son chemin (`value`), et son dossier va dans `fills` — le fichier
  // choisi dit où il est, un dossier tapé avant ne doit pas le contredire
  const pickField = (f, p) => {
    const dir = p.replace(/[\\/][^\\/]*$/, ''), name = p.split(/[\\/]/).pop();
    const v = { ...vals, [f.token]: f.browse === 'file' && f.value === 'name' ? name : p };
    if (f.fills) v[f.fills] = dir;
    setVals(v); setProbe(null);
  };
  const fieldStart = f => String(vals[f.fills] || '').trim() || (f.browse === 'dir' ? String(vals[f.token] || '').trim() : '');
  const toks = ['{input}', '{outdir}'].map(t => args.filter(a => a === t).length);
  const tokOk = toks[0] === 1 && toks[1] === 1 && !args.some(a => a !== '{input}' && a !== '{outdir}' && /\{(input|outdir)\}/.test(a));
  const mapped = Object.values(map).filter(Boolean).length;
  const dupes = [...new Set(Object.values(map).filter((v, i, a) => v && a.indexOf(v) !== i))];   // un stem pour deux fichiers
  const short = p => p.split('/').pop();
  const preview = [short(program || 'program'), ...run.map(a => a === '{input}' ? 'input.wav' : a === '{outdir}' ? 'out/' : a)];

  // ── les écrans ─────────────────────────────────────────────────────────────────────────────────────────────────
  let body, nav;
  if (step === 'what') {
    body = html`<span class="sw-q">What do you have?</span>
      <div class="sw-tiles">
        <button class=${cls('sw-tile', kind === 'program' && 'on')} onClick=${() => setKind('program')}><span class="sw-ic">⌨</span><b>A program on this machine</b>
          <span class="muted">A separation tool you installed. golem gives it a WAV and reads the WAV files it writes.</span></button>
        <button class=${cls('sw-tile', kind === 'onnx' && 'on')} onClick=${() => setKind('onnx')}><span class="sw-ic">◆</span><b>A model file (ONNX)</b>
          <span class="muted">A file that follows the golem engine contract. golem runs it itself.</span></button>
        <label class="sw-tile"><span class="sw-ic">⇩</span><b>An engine file</b>
          <span class="muted">A .golem-engine.json someone shared with you — everything is filled in, you check it.</span>
          <input class="sw-file" type="file" accept=".json,application/json" onChange=${importFile} /></label>
        <button class=${cls('sw-tile', kind === 'combine' && 'on')} disabled=${eligible.length < 2}
          title=${eligible.length < 2 ? 'add two engines that pass their test first' : ''} onClick=${() => setKind('combine')}>
          <span class="sw-ic">⧉</span><b>Combine two of my engines</b>
          <span class="muted">${eligible.length < 2 ? 'Add two engines first — then keep the best of each.' : 'Keep the best of each: one engine for some stems, a second one for the rest.'}</span></button>
      </div>
      <${Excerpt} x=${excerpt} onDone=${onExcerpt} />`;
    nav = html`<span class="grow"></span><button class="primary" disabled=${!kind || !excerpt} title=${!excerpt ? 'choose a test excerpt first' : ''}
        onClick=${() => go(kind === 'onnx' ? 'model' : kind === 'combine' ? 'first' : 'program')}>Next</button>`;
  } else if (step === 'first' || step === 'second') {
    const isFirst = step === 'first';
    const list = isFirst ? eligible : eligible.filter(e => e.id !== first);
    const sel = isFirst ? first : second;
    const pick = e => {
      if (isFirst) { setFirst(e.id); const st = stemsOf(e); setKeep(st.includes('vocals') ? ['vocals'] : st.slice(0, 1)); if (second === e.id) setSecond(null); }
      else setSecond(e.id);
    };
    const e1 = eng(first), e2 = eng(second);
    const st1 = stemsOf(e1), st2 = stemsOf(e2);
    const fromSecond = st2.filter(k => !keep.includes(k));
    const residue = st2.some(k => keep.includes(k));
    // garde-fou (2026-10-14 — vécu : « 6 stems puis voix » rendait voix + other, basse/batterie/guitare perdues) :
    // une combinaison qui rend MOINS de stems qu'un de ses moteurs seul est presque toujours montée à l'envers
    const total = new Set([...keep, ...fromSecond, ...(residue ? ['other'] : [])]).size;
    const best = Math.max(st1.length, st2.length);
    const swap = () => {
      const k = keep.filter(x => st2.includes(x));
      setFirst(e2.id); setSecond(e1.id);
      setKeep(k.length && k.length < st2.length ? k : st2.includes('vocals') ? ['vocals'] : st2.slice(0, 1));
    };
    body = html`<span class="sw-q">${isFirst ? 'Which engine goes first?' : 'Which engine takes the rest of the song?'}</span>
      <div class="sw-engs">${list.map(e => html`<button class=${cls('sw-eng', sel === e.id && 'on')} onClick=${() => pick(e)}>
        <span class="sw-rad"></span><b>${e.label}</b><span class="muted">${stemsOf(e).length} stems${e.test.rtf != null ? ' · ' + e.test.rtf.toFixed(2) + '× real time' : ''}</span>
        <span class="sw-eng__st">${stemsOf(e).map(k => html`<span class="sw-st">${k}</span>`)}</span></button>`)}</div>
      ${isFirst && e1 ? html`<span class="sw-q sw-q--s">From “${e1.label}”, keep:</span>
        <div class="sw-keep">${st1.map(k => { const on = keep.includes(k);
          return html`<button class=${cls('sw-st', on ? 'keep' : 'pass')} onClick=${() => setKeep(on ? keep.filter(x => x !== k) : [...keep, k])}>
            ${on ? '✓ ' + k + ' — keep' : '→ ' + k + ' — goes to the second engine'}</button>`; })}</div>
        <small class="muted">Tap a stem to switch it. What you don't keep is added together and becomes the input of the second engine.</small>` : ''}
      ${!isFirst && e1 && e2 ? html`<div class="sw-flow"><span class="sw-box">your song</span><span>→</span>
          <span class="sw-box a"><i>1</i><b>${e1.label}</b><small>keeps ${keep.join(', ')}</small></span><span>→</span>
          <span class="sw-box b"><i>2</i><b>${e2.label}</b><small>on the rest</small></span></div>
        <div class="sw-final">${keep.map(k => html`<span><i class="a">1</i>${k}</span>`)}${fromSecond.map(k => html`<span><i class="b">2</i>${k}${k === 'other' && residue ? html` <small class="muted">+ what it finds of ${keep.join(', ')}</small>` : ''}</span>`)}
          ${residue && !fromSecond.includes('other') && !keep.includes('other') ? html`<span><i class="b">2</i>other <small class="muted">= what it finds of ${keep.join(', ')}</small></span>` : ''}</div>
        ${total < best ? html`<div class="sw-warn"><span class="warnish">⚠ The result will only have ${total} stem${total > 1 ? 's' : ''} —
            ${st1.length > st2.length ? html`“${e1.label}” alone gives ${st1.length}.` : html`“${e2.label}” alone gives ${st2.length}.`}${' '}The engine that separates the most should usually go second.</span>
          ${st1.length > st2.length ? html`<button class="mini" onClick=${swap}>⇅ Swap the order</button>` : ''}</div>` : ''}
        <small class="muted">Both engines run one after the other: about ${((e1.test.rtf || 0) + (e2.test.rtf || 0)).toFixed(2)}× real time on this machine.</small>` : ''}`;
    const okFirst = first && keep.length && keep.length < st1.length;
    nav = html`<button class="chip" onClick=${() => go(isFirst ? 'what' : 'first')}>← Back</button><span class="grow"></span>
      <button class="primary" disabled=${isFirst ? !okFirst : !second} onClick=${() => {
        if (!isFirst && !label && e1 && e2) setLabel(e1.label + ' + ' + e2.label);
        go(isFirst ? 'second' : 'name'); }}>Next</button>`;
  } else if (step === 'program') {
    body = html`<span class="sw-q">Where is the program?</span>
      ${browse ? html`<${Browser} want="program" start=${program ? program.replace(/\/[^/]*$/, '') : ''}
          onPick=${p => { setProgram(p); setBrowse(null); }} onClose=${() => setBrowse(null)} />` : html`
        ${(found || []).length ? html`<div class="sw-found">${found.map(f => html`<button class=${cls('sw-eng', recipe && recipe.id === f.id && program === f.path && 'on')}
            onClick=${() => { setProgram(f.path); setRecipe(f); setArgs(f.args); setVals({}); setProbe(null); if (!licence) setLicence(f.licence); }}>
            <span class="sw-rad"></span><b>${f.name}</b><span class="muted">found on this golem · ${f.licence}</span>
            <span class="sw-eng__st muted">${f.path}</span></button>`)}
          <small class="muted">golem fills in how to call it. You choose the model yourself, on the next step.</small></div>` : ''}
        <div class="sep-row"><input class="sw-field" spellcheck="false" placeholder="/path/to/separate-tool" value=${program} onInput=${e => setProgram(e.target.value)} />
          <button class="mini" onClick=${() => setBrowse('program')}>Browse…</button></div>
        ${checks ? html`<div class="sw-checks">
          <span class=${checks.exists ? 'ok' : 'bad'}>${checks.exists ? '✓' : '✗'} the file exists</span>
          ${checks.exists ? html`<span class=${checks.runnable ? 'ok' : 'bad'}>${checks.runnable ? '✓' : '✗'} it can be run</span>
          <span class=${checks.not_script ? 'ok' : 'bad'}>${checks.not_script ? '✓' : '✗'} it is a program, not a script for the system shell</span>` : ''}
          ${checks.why ? html`<span class="warnish">${checks.why}</span>` : ''}</div>` : ''}
        <small class="muted">golem starts it directly — never through a shell — with a low priority, and stops it if golem gets busy.</small>`}`;
    nav = html`<button class="chip" onClick=${() => go('what')}>← Back</button><span class="grow"></span>
      <button class="primary" disabled=${!(checks && checks.ok)} onClick=${() => go('command')}>Next</button>`;
  } else if (step === 'command') {
    body = html`<span class="sw-q">How do you call it?</span>
      ${fieldBrowse ? html`<${Browser} want=${fieldBrowse.browse} start=${fieldStart(fieldBrowse)}
          onPick=${p => { pickField(fieldBrowse, p); setFieldBrowse(null); }} onClose=${() => setFieldBrowse(null)} />`
      : fields.filter(f => args.includes(f.token)).map(f => html`<div class="sw-fld"><b>${f.label}${f.required ? ' *' : ''}</b>
        <span class="sep-row"><input class="sw-field" spellcheck="false" placeholder=${f.placeholder || ''} value=${vals[f.token] || ''}
          onInput=${e => { setVals({ ...vals, [f.token]: e.target.value }); setProbe(null); }} />
          ${f.browse ? html`<button class="mini" onClick=${() => setFieldBrowse(f)}>Browse…</button>` : ''}</span>
        <small class="muted">${f.help || ''}</small></div>`)}
      <${ArgTags} args=${args} setArgs=${a => { setArgs(a); setProbe(null); }} />
      <div class="sep-row"><button class="sw-pill" onClick=${() => { setArgs([...args, '{input}']); setProbe(null); }}>+ {input}</button>
        <button class="sw-pill" onClick=${() => { setArgs([...args, '{outdir}']); setProbe(null); }}>+ {outdir}</button>
        <small class="muted">{input} = a stereo WAV golem writes · {outdir} = an empty folder for the program's files</small></div>
      <small class="muted">What golem will run:</small>
      <div class="sw-pre">${preview.map((a, i) => html`${i ? ' ' : ''}${a === 'input.wav' || a === 'out/' ? html`<b>${a}</b>` : a}`)}</div>
      <span class=${tokOk ? 'ok sw-small' : 'warnish sw-small'}>${tokOk ? '✓ {input} once · ✓ {outdir} once'
        : '{input} and {outdir} must each appear exactly once, as a whole argument'}</span>
      ${recipe ? '' : html`<small class="muted">Example, with a made-up tool: <code>separate-tool</code> · <code>--in</code> · <code>{input}</code> · <code>--out</code> · <code>{outdir}</code></small>`}
      <${ProgramHelp} help=${help} open=${helpOpen} setOpen=${setHelpOpen} q=${helpQ} setQ=${setHelpQ} args=${args}
        onAdd=${o => { setArgs([...args, o]); setProbe(null); }} />`;
    nav = html`<button class="chip" onClick=${() => go('program')}>← Back</button><span class="grow"></span>
      ${missing.length ? html`<span class="warnish sw-small">${missing.map(f => f.label).join(', ')}: required</span>` : ''}
      <button class="primary" disabled=${!tokOk || missing.length > 0} onClick=${() => { go('try'); runProbe(); }}>Next — try it</button>`;
  } else if (step === 'try') {
    body = !probe || probe.running ? html`<span class="sw-q">Trying it on 10 s of your excerpt…</span>
        <div class="sw-run"><span class="sw-spin"></span><span class="muted">the program runs on this machine — the first time, it may download what it needs</span></div>`
      : !probe.ok ? html`<span class="sw-q bad">✗ ${probe.error}</span>
        <${Hints} list=${probe.hints} />
        ${probe.files && probe.files.length ? html`<small class="muted">files written: ${probe.files.join(', ')}</small>` : ''}
        ${probe.log_tail ? html`<small class="muted">The last lines it printed (kept on this golem):</small><pre class="sep-log">${probe.log_tail}</pre>` : ''}`
      : html`<div class="sep-row"><span class="sw-q">${probe.imported ? 'From the engine file:' : `It wrote ${probe.files.length} file${probe.files.length > 1 ? 's' : ''} in ${probe.took} s.`}</span>
          <span class="muted">Match each one to a stem — golem guessed from the names.</span></div>
        <div class="sep-map">${probe.files.map(x => html`<div class="sep-row" key=${x}><code title=${x}>${x}</code>
          <select value=${map[x] || ''} onChange=${e => setMap({ ...map, [x]: e.target.value })}>
            ${STEM_CHOICES.map(c => html`<option value=${c}>${c || '— ignore'}</option>`)}</select></div>`)}</div>
        <span class=${mapped >= 2 && !dupes.length ? 'ok sw-small' : 'warnish sw-small'}>${dupes.length ? `two files are set to ${dupes.join(', ')} — choose another stem for one of them`
          : mapped >= 2 ? `✓ ${mapped} stems` : 'match at least two files to a stem'}</span>`;
    nav = html`<button class="chip" onClick=${() => go('command')}>${probe && !probe.ok ? '← Back to the command' : '← Back'}</button><span class="grow"></span>
      ${probe && !probe.running ? html`<button class="chip" onClick=${runProbe}>Try again</button>` : ''}
      <button class="primary" disabled=${!(probe && probe.ok && mapped >= 2 && !dupes.length)} onClick=${() => go('name')}>Next</button>`;
  } else if (step === 'model') {
    body = html`<span class="sw-q">Which model file?</span>
      ${browse ? html`<${Browser} want="onnx" start=${source && !/^https?:/.test(source) ? source.replace(/\/[^/]*$/, '') : ''}
          onPick=${p => { setSource(p); setInfo(null); setBrowse(null); }} onClose=${() => setBrowse(null)} />` : html`
        <div class="sep-row"><input class="sw-field" spellcheck="false" placeholder="/path/to/model.onnx, or a URL" value=${source}
            onInput=${e => { setSource(e.target.value); setInfo(null); }} />
          <button class="mini" onClick=${() => setBrowse('onnx')}>Browse…</button>
          <button class="mini" disabled=${!source || busy} onClick=${readModel}>Read it</button></div>
        ${busy ? html`<span class="muted">${busy}</span>` : ''}
        ${info ? html`<small class="muted">What the file says about itself:</small>
          <div class="sw-info">
            <div><b>Stems</b><span>${info.stems.join(' · ')}</span></div>
            <div><b>Segment</b><span>${Math.round(info.segment / info.sample_rate)} s at ${(info.sample_rate / 1000).toFixed(1)} kHz, ${Math.round(100 * info.overlap / info.segment)} % overlap</span></div>
            <div><b>License (written in the file)</b><span>${info.licence || '— none written'}</span></div>
            <div><b>Size</b><span>${Math.round(info.size_bytes / 1e6)} MB · copied onto this golem</span></div></div>
          <span class="ok sw-small">✓ follows the golem engine contract</span>` : ''}`}`;
    nav = html`<button class="chip" onClick=${() => go('what')}>← Back</button><span class="grow"></span>
      <button class="primary" disabled=${!info} onClick=${() => go('name')}>Next</button>`;
  } else if (step === 'name' && kind === 'combine') {
    const f = imported && imported.form;
    body = html`<span class="sw-q">Name it.</span>
      ${f ? html`<small class="muted">From the engine file: two programs, combined — golem adds each one, tests it, then tests the combination.</small>
          <div class="sw-pre">1 · ${f.first.label || 'first engine'}: ${[f.first.program.split('/').pop(), ...f.first.args].join(' ')}
2 · ${f.second.label || 'second engine'}: ${[f.second.program.split('/').pop(), ...f.second.args].join(' ')}
keep from 1: ${f.keep.join(', ')} — the rest goes to 2</div>`
        : html`<small class="muted">1 · ${(eng(first) || {}).label} → keeps ${keep.join(', ')} · the rest → 2 · ${(eng(second) || {}).label}</small>`}
      <div class="sw-grid"><label>Name</label><input spellcheck="false" placeholder="shown on this screen only" value=${label} onInput=${e => setLabel(e.target.value)} /></div>
      <label class="sep-consent"><input type="checkbox" checked=${accepted} onChange=${e => setAccepted(e.target.checked)} />
        <span>${f ? 'I add these engines myself and checked that their licenses allow my use. golem does not provide, recommend or check third-party engines.'
          : 'I combine these engines myself. Each keeps its own license.'}</span></label>`;
    nav = html`<button class="chip" onClick=${() => go(f ? 'what' : 'second')}>← Back</button>
      <span class="grow"></span>${busy ? html`<span class="muted">${busy}</span>` : ''}
      <button class="primary" disabled=${!accepted || busy} onClick=${addAndTest}>${f ? 'Add and test' : 'Combine and test'}</button>`;
  } else if (step === 'name') {
    body = html`<span class="sw-q">Name it.</span>
      ${kind === 'program' ? html`<div class="sw-pre">${preview.join(' ')}</div>
        ${mapped ? html`<small class="muted">outputs: ${Object.entries(map).filter(([, s]) => s).map(([f, s]) => `${f.split('/').pop()} → ${s}`).join(' · ')}</small>` : ''}` : ''}
      <div class="sw-grid"><label>Name</label><input spellcheck="false" placeholder="shown on this screen only" value=${label} onInput=${e => setLabel(e.target.value)} />
        <label>License</label><input spellcheck="false" placeholder="as you know it — shown here, never checked" value=${license} onInput=${e => setLicence(e.target.value)} /></div>
      <label class="sep-consent"><input type="checkbox" checked=${accepted} onChange=${e => setAccepted(e.target.checked)} />
        <span>I add this engine myself and checked that its license allows my use. golem does not provide, recommend or check third-party engines.</span></label>`;
    nav = html`<button class="chip" onClick=${() => go(kind === 'onnx' ? 'model' : (probe && probe.imported ? 'command' : 'try'))}>← Back</button>
      <span class="grow"></span>${busy ? html`<span class="muted">${busy}</span>` : ''}
      <button class="primary" disabled=${!accepted || busy} onClick=${addAndTest}>Add and test</button>`;
  } else {
    const t = (result && result.test) || {};
    body = !result ? html`<span class="sw-q">Testing…</span>
        <div class="sw-run"><span class="sw-spin"></span><span class="muted">${busy || 'starting the test…'}</span></div>
        <small class="muted">golem runs it on your excerpt, then on 30 s of silence, and reads what comes out.</small>`
      : t.ok ? html`<span class="sw-q ok">✓ Passed — “${result.label}” is ready.</span>
        <div class="sep-stems">${(t.stems || []).map(s => html`<span>${s}</span>`)}</div>
        <div class="sep-kpi"><div><b>${t.rtf != null ? t.rtf.toFixed(2) + '×' : '—'}</b><small>real time on this machine</small></div>
          <div><b>${t.analysis && t.analysis.residual_db != null ? Math.round(t.analysis.residual_db) + ' dB' : '—'}</b><small>the stems add up to the song</small></div>
          <div><b>✓</b><small>silence stays silent</small></div></div>
        <small class="muted">Once in use, golem separates the songs of your library with it — only when golem is free.</small>`
      : html`<span class="sw-q bad">✗ ${t.why || 'the test failed'}</span>
        <${Hints} list=${t.hints} />
        ${(t.files || []).length ? html`<small class="muted">files written: ${t.files.join(', ')}</small>` : ''}
        ${t.log_tail ? html`<small class="muted">The last lines it printed (kept on this golem):</small><pre class="sep-log">${t.log_tail}</pre>` : ''}`;
    nav = !result ? html`<span class="grow"></span>`
      : (result.test || {}).ok ? html`${kind === 'program' || kind === 'combine' ? html`<button class="chip" onClick=${async () => {
          const r = await exportEngine(result); setErr(''); setBusy(r.where ? '✓ saved to ' + r.where : '✓ downloaded'); }}>Export engine file</button>` : ''}
        <span class="grow"></span>${busy && busy.startsWith('✓') ? html`<span class="sep-saved">${busy}</span>` : ''}
        <button class="chip" onClick=${onClose}>Keep it for later</button>
        <button class="primary" onClick=${useIt}>Use this engine</button>`
      : html`<button class="chip" onClick=${backFromFailedTest}>← Back to ${kind === 'onnx' ? 'the file' : kind === 'combine' ? 'the engines' : 'the command'}</button>
        <span class="grow"></span><button class="chip" onClick=${onClose}>Close</button>`;
  }

  return html`<div class="detail sw-scrim" onClick=${e => e.target.classList.contains('sw-scrim') && onClose()}>
    <div class="detail-card cal-card sw-card">
      <button class="close" onClick=${onClose}>×</button>
      <h2>${kind === 'combine' ? 'Combine two engines' : kind ? 'Add your own engine' : 'Add an engine'} <small class="muted">${kind === 'combine' ? '' : '— ' + (kind === 'onnx' ? 'a model file (ONNX)' : kind === 'program' ? 'a program on this machine' : 'one you bring yourself')}</small></h2>
      <div class="cal-steps sw-steps">${(kind ? flow : FLOWS.program.slice(0, 1).concat(FLOWS.program.slice(1))).map(([k, lab], i) => html`
        <span class=${cls('cal-dot', i === idx && 'on', i < idx && 'done')}>${i < idx ? '✓' : i + 1}</span><span class=${cls('sw-lab', i === idx && 'on')}>${lab}</span>`)}</div>
      <div class="sw-body">${body}${err ? html`<span class="warnish">✗ ${err}</span>` : ''}</div>
      <div class="cal-nav">${nav}</div>
    </div>
  </div>`;
}
