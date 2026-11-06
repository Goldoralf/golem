// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Grooves (hub Library) — les patterns MIDI de batterie (.mid GM) que le bloc
// drums référence (param patterns/fills). Liste + import de .mid GM standard + delete.
// Un groove = library/grooves/<id>.mid, convention batterie General MIDI (36/38/42…).
import { useFactoryShow, keepFactory } from './factory-show.js';
import { html, useState, useEffect, useAsync, useRef, cls, esc, setTopAction, setSubToolbar, useRev, saveClick } from './lib.js';
import { useGenreLabel } from './genres.js';

// Un groove n'a pas de forme d'onde — c'est du MIDI. Ce qu'on veut VOIR, ce sont les frappes :
// mini piano-roll, même gabarit que la piste-DAW de Recordings (rangée, grille, hauteur).
// Les notes GM de batterie sont NOMMÉES : « kick · snare · hats », pas « 36 · 38 · 42 ».
const GM = { 35: 'Kick', 36: 'Kick', 37: 'Rim', 38: 'Snare', 39: 'Clap', 40: 'Snare', 41: 'Tom', 42: 'Hats',
  43: 'Tom', 44: 'Pedal hat', 45: 'Tom', 46: 'Open hat', 47: 'Tom', 48: 'Tom', 49: 'Crash', 50: 'Tom',
  51: 'Ride', 52: 'China', 53: 'Bell', 54: 'Tambourine', 55: 'Splash', 56: 'Cowbell', 57: 'Crash', 59: 'Ride' };

function PianoRoll({ file }) {
  const [d, setD] = useState(null);
  const box = useRef(null), asked = useRef(false);
  useEffect(() => {                                  // chargé seulement à l'entrée dans l'écran
    const el = box.current;
    if (!el || asked.current) return;
    const io = new IntersectionObserver(es => {
      if (!es.some(e => e.isIntersecting) || asked.current) return;
      asked.current = true; io.disconnect();
      fetch('/api/groove-notes?file=' + encodeURIComponent(file)).then(r => r.json()).then(setD).catch(() => setD({ notes: [] }));
    }, { rootMargin: '250px' });
    io.observe(el);
    return () => io.disconnect();
  }, [file]);
  const notes = (d && d.notes) || [];
  const ppq = (d && d.ppq) || 480;
  const span = Math.max(1, (d && d.beats) || 1);
  const pitches = [...new Set(notes.map(n => n.n))].sort((a, b) => b - a);   // grave en bas
  const H = 100, rows = Math.max(1, pitches.length);
  const rh = H / rows;
  return html`<div class="wv pr" ref=${box}>
    ${notes.length ? html`<svg class="wv-svg" viewBox=${'0 0 1000 ' + H} preserveAspectRatio="none">
      ${Array.from({ length: Math.ceil(span) }, (_, b) => html`<line class="pr-beat"
        x1=${(b / span * 1000).toFixed(1)} x2=${(b / span * 1000).toFixed(1)} y1="0" y2=${H} />`)}
      ${notes.map(n => {
        const x = n.t / ppq / span * 1000, w = Math.max(6, n.d / ppq / span * 1000);
        const y = pitches.indexOf(n.n) * rh;
        return html`<rect class="pr-note" x=${x.toFixed(1)} y=${(y + rh * 0.18).toFixed(1)}
          width=${w.toFixed(1)} height=${(rh * 0.64).toFixed(1)} rx="1.5"
          opacity=${(0.45 + 0.55 * (n.v || 100) / 127).toFixed(2)} />`;
      })}
    </svg>` : html`<div class="wv-load"></div>`}
    ${pitches.length ? html`<span class="pr-legend">${pitches.map(pn => GM[pn] || pn).filter((v, i, a) => a.indexOf(v) === i).join(' · ')}</span>` : ''}
  </div>`;
}

const fmtBytes = b => !b ? '—' : b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.round(b / 1e3) + ' kB';

export function GroovesPage() {
  const facShow = useFactoryShow();          // l'usine masquée par sorte (Settings ▸ Content ▸ Factory)
  const [tick, setTick] = useState(0);
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data } = useAsync(() => fetch('/api/grooves').then(r => r.json()), [tick, libRev]);
  const [armDel, setArmDel] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(null);
  const [q, setQ] = useState('');
  const [genreF, setGenreF] = useState('all');
  const [packF, setPackF] = useState('all');
  const fileRef = useRef(null);
  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" onClick=${() => fileRef.current && fileRef.current.click()}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, []);

  // import MULTI-fichiers (un gros lot de .mid GM en une fois)
  const importMids = async files => {
    const arr = Array.from(files || []);
    if (!arr.length) return;
    setErr(null); let ok = 0, lastErr = null;
    for (const f of arr) {
      setBusy(`importing ${ok + 1}/${arr.length}…`);
      const r = await fetch('/api/groove/import?name=' + encodeURIComponent(f.name),
        { method: 'POST', body: f }).then(x => x.json()).catch(e => ({ error: String(e) }));
      if (r && r.ok) ok++; else lastErr = (r && r.error) || 'import failed';
    }
    setBusy(null);
    if (lastErr) setErr(arr.length > 1 ? `${ok}/${arr.length} imported · ${lastErr}` : lastErr);
    setTick(t => t + 1);
  };

  const del = async id => {
    if (armDel !== id) { setArmDel(id); setTimeout(() => setArmDel(a => a === id ? null : a), 2500); return; }
    setArmDel(null);
    await fetch('/api/groove/' + encodeURIComponent(id), { method: 'DELETE' }).catch(() => null);
    setTick(t => t + 1);
  };

  const grooves = (data && data.grooves) || [];
  // le genre d'un groove = UN id, de sous-genre ou de famille (forme choisie par golem.fm, docs/genres.md) : on
  // affiche son libellé ; un ancien texte libre s'affiche tel quel
  const genreLabel = useGenreLabel();
  const genres = [...new Set(grooves.map(g => g.genre).filter(Boolean))].sort();
  // packs d'origine (Addendum 14) : les grooves poussés seuls tombent sous « (no pack) »
  const packs = [...new Set(grooves.map(g => g.pack).filter(Boolean))].sort();
  const shown = grooves.filter(keepFactory(facShow, 'grooves')).filter(g => (genreF === 'all' || g.genre === genreF)
    && (packF === 'all' || (packF === '(none)' ? !g.pack : g.pack === packF))
    && (!q || (g.name || '').toLowerCase().includes(q)));
  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search groove…"
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      ${packs.length ? html`<select class="flt-sel" value=${packF} onChange=${e => setPackF(e.target.value)} title="Pack / song of origin">
        <option value="all">Pack · all</option>
        ${packs.map(p => html`<option value=${p} selected=${p === packF}>${p}</option>`)}
        <option value="(none)" selected=${packF === '(none)'}>(no pack)</option>
      </select>` : ''}
      ${genres.length ? html`<select class="flt-sel" value=${genreF} onChange=${e => setGenreF(e.target.value)} title="Genre">
        <option value="all">Genre · all</option>
        ${genres.map(g => html`<option value=${g} selected=${g === genreF}>${genreLabel(g)}</option>`)}
      </select>` : ''}
      ${busy ? html`<span class="syn-busy">${esc(busy)}</span>` : ''}
      ${err ? html`<span class="lib-err" title=${esc(err)}>⚠ ${esc(err)}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [genreF, packF, genres.length, packs.length, busy, err]);
  return html`<div class="library">
    <input ref=${fileRef} type="file" accept=".mid,.midi" multiple style="display:none"
      onChange=${e => { importMids(e.target.files); e.target.value = ''; }} />
    <div class="lib-grid">
      ${shown.length ? html`<div class="rec-day">
        <div class="rec-day-lb">Grooves<em>${shown.length} pattern${shown.length > 1 ? 's' : ''}</em></div>
        <div class="rec-grid">
        ${shown.map(g => html`<div class="rec-card solo"><div class="rec-body"><div class="wv-row">
          <span class="wv-n">🥁</span>
          <span class="wv-info">
            <b class="wv-name">${g.factory ? html`<span class="slv-own" title="ships with golem — not deletable">◆ factory</span> ` : ''}${esc(g.name)}</b>
            <em class="wv-tech">${g.bars != null ? g.bars + (g.bars > 1 ? ' bars' : ' bar') : '—'} · ${g.notes != null ? g.notes + ' hits' : '—'} · ${fmtBytes(g.bytes)}${g.pack ? ' · ♫ ' + g.pack : ''}</em>
          </span>
          <${PianoRoll} file=${g.file} />
          <a class="wv-dl edit-only" href=${'/api/groove/' + encodeURIComponent(g.id)} onClick=${saveClick('/api/groove/' + encodeURIComponent(g.id))} title="download the .mid">⬇</a>
          ${g.factory ? '' : html`<button class=${cls('rec-del', armDel === g.id && 'arm')}
            onClick=${() => del(g.id)}>${armDel === g.id ? 'sure?' : '🗑'}</button>`}
        </div></div></div>`)}
        </div>
      </div>` : html`<div class="empty">No grooves yet — tap <b>+ Add</b> to import General-MIDI drum patterns
          (<code>.mid</code>, 36 kick / 38 snare / 42 hi-hat…). Multi-select works. Grooves feed the <b>Drum Machine</b> block in the Designer.</div>`}
    </div>
  </div>`;
}
