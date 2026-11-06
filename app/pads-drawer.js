// SPDX-License-Identifier: GPL-3.0-or-later
// LE TIROIR DU BLOC PADS — v2 (maquette mockups/pads-drawer-v2.html, 2026-10-14 : « l'UX doit avoir 4 mois »).
// On JOUE les pads ici (tap = écouter, à travers la lane, sur les enceintes), ils ont la forme et la place de l'AKAI
// (rangée du bas = pads 1-4), ils disent ce qu'ils sont (le rôle General MIDI de leur note), et un pad frappé sur
// l'AKAI s'allume. Changer un son = un NAVIGATEUR par famille, avec écoute — fini le menu de 48 fichiers où trois
// « 01_kick » se ressemblaient. Les kits sont des objets de bibliothèque (library/kits) ; un kit d'usine ne s'écrase
// pas : modifié, il se garde sous un nouveau nom.
import { html, useState, useEffect, useRef, cls, esc, post } from './lib.js';

// le rôle d'une note General MIDI (canal 10) et sa famille — la couleur du pad
const GM = {
  35: ['Kick', 'kick'], 36: ['Kick', 'kick'], 37: ['Rim', 'perc'], 38: ['Snare', 'snare'], 39: ['Clap', 'clap'],
  40: ['Snare 2', 'snare'], 41: ['Low tom', 'tom'], 42: ['Hi-hat', 'hat'], 43: ['Floor tom', 'tom'],
  44: ['Pedal hat', 'hat'], 45: ['Mid tom', 'tom'], 46: ['Open hat', 'hat'], 47: ['Mid tom 2', 'tom'],
  48: ['High tom', 'tom'], 49: ['Crash', 'cym'], 50: ['High tom 2', 'tom'], 51: ['Ride', 'cym'], 52: ['China', 'cym'],
  53: ['Ride bell', 'cym'], 54: ['Tambourine', 'perc'], 55: ['Splash', 'cym'], 56: ['Cowbell', 'perc'],
  57: ['Crash 2', 'cym'], 59: ['Ride 2', 'cym'],
};
const CATS = [['kick', 'Kick'], ['snare', 'Snare'], ['clap', 'Clap'], ['hat', 'Hi-hat'], ['tom', 'Tom'],
              ['cym', 'Cym'], ['perc', 'Perc'], ['', 'All']];
const MODE_TXT = { oneshot: ['One-shot', 'to the end, however short your hit', '▶|'],
                   gate: ['Gate', 'stops when you let go of the pad', '⏵'],
                   toggle: ['Toggle', 'tap to start, tap again to stop', '⇄'] };
const roleOf = n => GM[n] || ['Pad', 'perc'];
// « 02_kick_sub » -> « kick sub »
const pretty = s => String(s || '').replace(/\.[a-z0-9]+$/i, '').split('/').pop().replace(/^\d+[_\- ]+/, '').replace(/[_-]+/g, ' ');

export function PadsDrawer({ data, kitId, blockId, onKit, onSaved }) {
  const padKits = data.kits.filter(k => k.role === 'pad');
  const cur = padKits.find(k => k.id === kitId) || null;
  const kitName = id => { const k = data.kits.find(x => x.id === id); return k ? k.name : id; };
  const notes = data.default_notes || [36, 37, 38, 39, 40, 41, 42, 43];
  const blank = n => ({ note: n, sample: '', mode: 'oneshot', level: 0 });
  const [bank, setBank] = useState(0);
  const [pads, setPads] = useState(null);         // null = le kit tel qu'il est ; sinon l'édition en cours
  const [sel, setSel] = useState(null);           // index du pad dans l'inspecteur (null = fermé)
  const [cat, setCat] = useState(null);           // famille du navigateur (null = celle du pad)
  const [hit, setHit] = useState({});             // note -> instant du dernier coup reçu de l'AKAI
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const lastSeq = useRef(null);
  const holdT = useRef(null);

  useEffect(() => { setPads(null); setSel(null); setNaming(false); }, [kitId]);
  // UN PAD FRAPPÉ S'ALLUME : la dernière note vue par la lane (knob-tap -> /api/calibrate/live), sondée tant que le
  // tiroir est ouvert
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await fetch('/api/calibrate/live').then(x => x.json()).catch(() => null);
      if (!alive) return;
      const nt = r && r.note;
      if (nt && lastSeq.current != null && nt.seq !== lastSeq.current && nt.vel > 0) {
        const n = nt.num; setHit(h => ({ ...h, [n]: Date.now() }));
        setTimeout(() => alive && setHit(h => { const c = { ...h }; if (Date.now() - (c[n] || 0) >= 170) delete c[n]; return c; }), 190);
      }
      if (nt) lastSeq.current = nt.seq;
      setTimeout(() => alive && tick(), 120);
    };
    tick();
    return () => { alive = false; };
  }, []);

  const shown = pads || notes.map(n => (cur && cur.pads.find(p => p.note === n)) || blank(n));
  const edited = !!pads;
  const edit = (i, patch) => setPads(shown.map((p, j) => j === i ? { ...p, ...patch } : p));
  const listen = (file, db) => file && post('/api/kit/audition', { file, db: db || 0, block: blockId }).catch(() => {});
  const tapPad = i => { const p = shown[i]; if (sel != null) { setSel(i); setCat(null); } listen(p.sample, p.level); };
  const down = i => { holdT.current = setTimeout(() => { holdT.current = 'done'; setSel(i); setCat(null); }, 450); };
  const up = i => { if (holdT.current === 'done') { holdT.current = null; return; } clearTimeout(holdT.current); holdT.current = null; tapPad(i); };

  const save = async asNew => {
    const nm = asNew ? name.trim() : (cur ? cur.name : name.trim());
    if (!nm) return;
    const kid = asNew ? 'pads-' + nm.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') : cur.id;
    setBusy(true);
    const r = await post('/api/kit', { id: kid, name: nm, role: 'pad', pads: shown.filter(p => p.sample) }).catch(e => ({ error: String(e) }));
    setBusy(false);
    if (r && r.ok) { setPads(null); setNaming(false); setName(''); onSaved(r.kit.id); }
  };
  const upload = async f => {
    setBusy(true);
    await fetch('/api/sample/upload?name=' + encodeURIComponent(f.name), { method: 'POST', body: f }).catch(() => null);
    setBusy(false); onSaved(kitId);
  };

  const order = [4, 5, 6, 7, 0, 1, 2, 3].map(o => bank * 8 + o);
  const padTile = i => {
    const p = shown[i]; if (!p) return '';
    const [role, fam] = roleOf(p.note);
    const smp = data.samples.find(s => s.file === p.sample);
    const lvl = Math.max(0, Math.min(100, ((p.level || 0) + 30) / 36 * 100));
    return html`<button class=${cls('pdv-pad', 'f-' + fam, !p.sample && 'empty', sel === i && 'sel', hit[p.note] && 'hit')}
      onPointerDown=${() => down(i)} onPointerUp=${() => up(i)} onPointerLeave=${() => { if (holdT.current && holdT.current !== 'done') { clearTimeout(holdT.current); holdT.current = null; } }}
      title=${p.sample ? 'tap: hear it · hold: change its sound' : 'hold: give this pad a sound'}>
      <span class="pdv-n">PAD ${(i % 8) + 1 + bank * 8} · ${p.note}</span>
      <span class="pdv-role">${role}</span>
      <span class="pdv-smp">${p.sample ? esc(pretty(p.sample)) + (smp && smp.kit ? ' · ' + esc(kitName(smp.kit)) : '') : 'no sound'}</span>
      ${p.sample ? html`<span class="pdv-play">▶</span>` : ''}
      <span class="pdv-ft"><b>${(MODE_TXT[p.mode] || MODE_TXT.oneshot)[2]}</b><i><u style=${'width:' + lvl + '%'}></u></i>
        <small>${(p.level || 0) > 0 ? '+' : ''}${p.level || 0} dB</small></span>
    </button>`;
  };

  // l'inspecteur du pad ouvert
  const insp = () => {
    const i = sel; const p = shown[i]; if (!p) return '';
    const [role, fam] = roleOf(p.note);
    const c = cat == null ? fam : cat;
    const list = data.samples.filter(s => s.kind !== 'song' && (!c || s.cat === c));
    const groups = [];
    for (const s of list) { const g = s.kit ? kitName(s.kit) : 'My samples';
      let e = groups.find(x => x[0] === g); if (!e) { e = [g, []]; groups.push(e); } e[1].push(s); }
    // le kit courant d'abord, « My samples » en dernier
    const rank = g => g === (cur && cur.name) ? 0 : g === 'My samples' ? 2 : 1;
    groups.sort((a, b) => rank(a[0]) - rank(b[0]));
    const mt = MODE_TXT[p.mode] || MODE_TXT.oneshot;
    return html`<div class=${cls('pdv-insp', 'f-' + fam)}>
      <div class="pdv-ih"><b>Pad ${(i % 8) + 1 + bank * 8} · ${role}</b><small>note ${p.note}</small>
        <span class="grow"></span>
        ${p.sample ? html`<button class="mini" onClick=${() => edit(i, { sample: '' })} title="this pad plays nothing">Clear</button>` : ''}
        <button class="pdv-x" onClick=${() => setSel(null)} title="close">✕</button></div>
      <div class="pdv-cats">${CATS.map(([k, lb]) => html`<button class=${cls(c === k && 'on')} onClick=${() => setCat(k)}>${lb}</button>`)}</div>
      <div class="pdv-list">
        ${groups.map(([g, arr]) => html`<div class="pdv-grp">${esc(g)}</div>
          ${arr.map(s => html`<div class=${cls('pdv-row', s.file === p.sample && 'on')}
              onClick=${() => { edit(i, { sample: s.file }); listen(s.file, p.level); }}>
            <button class="pdv-pl" onClick=${e => { e.stopPropagation(); listen(s.file, p.level); }} title="hear it">▶</button>
            <span>${esc(pretty(s.name))}</span>
            <small>${s.dur != null ? s.dur + ' s' : ''}${s.file === p.sample ? ' · on this pad' : ''}</small></div>`)}`)}
        ${!groups.length ? html`<div class="pdv-row muted">no sound in this family yet</div>` : ''}
        <div class="pdv-row pdv-add" onClick=${() => fileRef.current && fileRef.current.click()}>
          <span class="pdv-pl">⬆</span><span>Add a sample…</span><small>.wav .flac .mp3</small></div>
      </div>
      <div class="pdv-line"><b>Plays</b><div class="tb-seg">
        ${(data.modes || ['oneshot', 'gate', 'toggle']).map(m => html`<button class=${cls(p.mode === m && 'on')}
          onClick=${() => edit(i, { mode: m })}>${(MODE_TXT[m] || [m])[0]}</button>`)}</div></div>
      <small class="pdv-sub">${mt[1]}</small>
      <div class="pdv-line"><b>Level</b><input type="range" min="-30" max="6" step="1" value=${p.level || 0}
        onInput=${e => edit(i, { level: Number(e.target.value) })} onChange=${() => listen(p.sample, shown[i].level)} />
        <small>${(p.level || 0) > 0 ? '+' : ''}${p.level || 0} dB</small></div>
    </div>`;
  };

  return html`<div class="pdv">
    <div class="pdv-kits"><span class="pdv-lb">Kit</span>
      ${padKits.map(k => html`<button class=${cls('pdv-kit', k.id === kitId && 'on')} onClick=${() => onKit(k.id)}
        title=${k.factory ? 'factory kit' : 'your kit'}>${k.factory ? html`<i>◆</i>` : ''}${esc(k.name)}</button>`)}
      <span class="grow"></span>
      ${edited ? html`<span class="pdv-edited">● edited</span>
        ${naming ? html`<input class="pdv-name" placeholder="name of the new kit" value=${name}
            onInput=${e => setName(e.target.value)} onKeyDown=${e => e.key === 'Enter' && save(true)} />
          <button class="mini primary" disabled=${busy || !name.trim()} onClick=${() => save(true)}>Save</button>
          <button class="mini" onClick=${() => setNaming(false)}>Cancel</button>`
        : html`<button class="mini" onClick=${() => setPads(null)} title="back to the kit as it was">Revert</button>
          <button class="mini" onClick=${() => setNaming(true)}>Save as new…</button>
          ${cur && !cur.factory ? html`<button class="mini primary" disabled=${busy} onClick=${() => save(false)}>Save</button>` : ''}`}`
      : notes.length > 8 ? html`<div class="tb-seg">
          <button class=${cls(bank === 0 && 'on')} onClick=${() => setBank(0)}>Bank A</button>
          <button class=${cls(bank === 1 && 'on')} onClick=${() => setBank(1)}>Bank B</button></div>` : ''}
    </div>
    <div class=${cls('pdv-body', sel != null && 'open')}>
      <div class="pdv-akai">
        <div class="pdv-pads">${order.map(padTile)}</div>
        <div class="pdv-hint"><span><b>tap</b> = hear it</span><span><b>hold</b> = change its sound</span>
          <span>a pad lights up when you hit it on the keyboard</span>
          ${edited && notes.length > 8 ? html`<span class="grow"></span><span>Bank ${bank ? 'B' : 'A'}</span>` : ''}</div>
      </div>
      ${sel != null ? insp() : ''}
    </div>
    <input ref=${fileRef} type="file" accept=".wav,.flac,.mp3,.ogg,.aif,.aiff" style="display:none"
      onChange=${e => { if (e.target.files && e.target.files[0]) upload(e.target.files[0]); e.target.value = ''; }} />
  </div>`;
}
