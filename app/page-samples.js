// SPDX-License-Identifier: GPL-3.0-or-later
// Groupe Samples (hub Library) — deux natures d'un même fichier audio local (2026-09-15,
// docs/samples-backings.md) : `kind="short"` = les one-shots qui garnissent les kits RS5k et le
// bloc Sample ; `kind="song"` = un fichier long, stem d'un backing local (Tracks ▸ Backings). Le
// TYPE EST CHOISI PAR L'ONGLET OÙ L'ON DÉPOSE, jamais deviné par la durée ; « → Songs » / « → Short »
// corrige une erreur. Pré-écoute ▶, badge « used by » (suppression protégée côté bridge).
import { html, useState, useEffect, useRef, useAsync, cls, esc, setTopAction, setSubToolbar, useRev, saveClick } from './lib.js';
import { WaveTrack } from './wavetrack.js';   // même mini-DAW que Recordings : voir ET écouter

const fmtDur = d => d == null ? '' : d < 10 ? d.toFixed(1) + ' s' : d < 60 ? Math.round(d) + ' s'
  : Math.floor(d / 60) + ':' + String(Math.round(d % 60)).padStart(2, '0');
// « 02_kick_sub.wav » -> « kick sub » (le numéro de rangement d'un pack n'aide personne à reconnaître un son)
const pretty = n => String(n || '').replace(/\.[a-z0-9]+$/i, '').split('/').pop().replace(/^\d+[_\- ]+/, '').replace(/[_-]+/g, ' ') || n;
const CAT_LABEL = { kick: 'Kick', snare: 'Snare', clap: 'Clap', hat: 'Hi-hat', tom: 'Tom', cym: 'Cymbals', perc: 'Percussion' };
const fmtBytes = b => !b ? '—' : b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.round(b / 1e3) + ' kB';

export function SamplesPage({ kind = 'short' } = {}) {
  const song = kind === 'song';
  const [tick, setTick] = useState(0);
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data } = useAsync(() => fetch('/api/kits').then(r => r.json()), [tick, libRev]);
  // sample KITS (sets ordonnés du bloc Sample) — distinction UX « pile » (2026-07-24) :
  // un kit = pile de cartes + badge ×N, dépliable ; un sample seul = carte plate.
  const { data: setsD, reload: reloadSets } = useAsync(() => fetch('/api/sample-sets').then(r => r.json()), [tick, libRev]);
  const [playing, setPlaying] = useState(null);      // clé de l'élément en lecture (un seul à la fois)
  const [busy, setBusy] = useState(null);
  const [armDel, setArmDel] = useState(null);
  const [q, setQ] = useState('');
  // RANGER (2026-10-15 : « des cards plus petites, et un moyen de les trier ou regrouper ») : les one-shots se
  // regroupent par TYPE (la famille lue dans le nom : Kick, Snare… — la même que le tiroir Pads) ou par KIT ; les fichiers
  // longs n'ont pas de famille, ils se TRIENT (nom, durée, taille).
  const [order, setOrder] = useState(song ? 'name' : 'type');
  useEffect(() => { setOrder(song ? 'name' : 'type'); }, [song]);
  const fileRef = useRef(null);
  const audioRef = useRef(null);                     // un seul one-shot à la fois
  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" title=${song ? 'upload a long file' : 'upload one-shots for the pads'} onClick=${() => fileRef.current && fileRef.current.click()}>+ Add</button></div>`);
    return () => { setTopAction(null); if (audioRef.current) audioRef.current.pause(); };
  }, [song]);

  const samples = ((data && data.samples) || []).filter(s2 => (s2.kind || 'short') === kind);
  const usage = {};                                  // sample -> [kit names]
  ((data && data.kits) || []).forEach(k => (k.pads || []).forEach(p => {
    if (p.sample && !(usage[p.sample] || []).includes(k.name)) (usage[p.sample] = usage[p.sample] || []).push(k.name);
  }));
  const shown = samples.filter(s => !q || s.name.toLowerCase().includes(q));
  const kitName = id => (((data && data.kits) || []).find(k => k.id === id) || {}).name || id;
  const byName = (a, b) => pretty(a.name).localeCompare(pretty(b.name));
  // les groupes à afficher, dans l'ordre : une famille / un kit par section ; « A–Z » et les tris = une seule section
  const groupsOf = list => {
    const one = label => [{ label, items: list, first: true }];
    if (song) {
      const cmp = order === 'dur' ? (a, b) => (b.dur || 0) - (a.dur || 0) : order === 'bytes' ? (a, b) => (b.bytes || 0) - (a.bytes || 0) : byName;
      list = list.slice().sort(cmp); return one('Songs');
    }
    if (order === 'name') { list = list.slice().sort(byName); return one('All samples'); }
    const keyOf = order === 'kit' ? x => x.kit || '' : x => x.cat || 'perc';
    const keys = order === 'kit' ? [...new Set(list.map(keyOf))].sort((a, b) => (a === '') - (b === '') || kitName(a).localeCompare(kitName(b)))
      : Object.keys(CAT_LABEL).filter(c => list.some(x => keyOf(x) === c));
    return keys.map((key, i) => ({ label: order === 'kit' ? (key ? kitName(key) : 'My samples') : CAT_LABEL[key],
      items: list.filter(x => keyOf(x) === key).sort(byName), first: i === 0 }));
  };
  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search sample…"
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      <div class="tb-seg smp-order" title=${song ? 'sort' : 'group by'}>
        ${(song ? [['name', 'A–Z'], ['dur', 'Length'], ['bytes', 'Size']] : [['type', 'Type'], ['kit', 'Kit'], ['name', 'A–Z']])
          .map(([id, lb]) => html`<button class=${cls(order === id && 'on')} onClick=${() => setOrder(id)}>${lb}</button>`)}
      </div>
      ${busy ? html`<span class="syn-busy">${esc(busy)}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [busy, order, song]);

  const upload = async files => {
    const arr = Array.from(files || []);
    if (!arr.length) return;
    let ok = 0;
    for (const f of arr) {
      setBusy(`uploading ${ok + 1}/${arr.length}…`);
      await fetch('/api/sample/upload?name=' + encodeURIComponent(f.name) + '&kind=' + kind, { method: 'POST', body: f }).catch(() => null);
      ok++;
    }
    setBusy(null);
    setTick(t => t + 1);
  };
  // écoute d'un tap : un seul son à la fois ; retaper la carte qui joue l'arrête (un fichier long dure des minutes)
  const play = s => {
    const k = 'f:' + s.file;
    if (audioRef.current) audioRef.current.pause();
    if (playing === k) { setPlaying(null); return; }
    const a = new Audio('/api/sample?file=' + encodeURIComponent(s.file));
    a.onended = () => setPlaying(p => p === k ? null : p);
    audioRef.current = a; setPlaying(k);
    a.play().catch(() => setPlaying(null));
  };
  // corriger le type (short ↔ song) : refusé si le sample est un stem d'un backing
  const rekind = async s => {
    const r = await fetch('/api/sample/kind', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file: s.file, kind: song ? 'short' : 'song' }) }).then(x => x.json()).catch(() => ({}));
    if (r.error) { setBusy(r.error); setTimeout(() => setBusy(null), 4000); }
    setTick(t => t + 1);
  };
  const del = async s => {
    if (armDel !== s.file) { setArmDel(s.file); setTimeout(() => setArmDel(a => a === s.file ? null : a), 2500); return; }
    setArmDel(null);
    const r = await fetch('/api/sample?file=' + encodeURIComponent(s.file), { method: 'DELETE' }).then(x => x.json()).catch(() => ({}));
    if (r.error) { setBusy(r.error); setTimeout(() => setBusy(null), 4000); }
    setTick(t => t + 1);
  };

  return html`<div class="library">
    <input ref=${fileRef} type="file" accept=".wav,.flac,.mp3,.ogg,.aif,.aiff" multiple style="display:none"
      onChange=${e => { upload(e.target.files); e.target.value = ''; }} />
    <div class="lib-grid">
      ${(() => {
        // Grammaire de /songs/recordings : carte pleine largeur, contenu TOUJOURS visible,
        // une ligne par élément avec sa forme d'onde et son bouton play. On voit ce qu'on écoute.
        const sets = ((setsD || {}).sets || []).filter(st => !q || st.name.toLowerCase().includes(q));
        const aud = f => '/api/sample?file=' + encodeURIComponent(f);
        const pks = f => '/api/peaks?file=' + encodeURIComponent(f);
        return html`
        ${sets.length && !song ? html`<div class="rec-day">
          <div class="rec-day-lb">Sample kits<em>ordered sets for the Sample block — the foot cycles them</em></div>
          <div class="rec-grid">
            ${sets.map(st => html`<div class="rec-card multi">
              <div class="rec-head">
                <span class="rec-glyph">▤</span>
                <span class="rec-title"><span class="rec-name">${esc(st.name)}</span>
                  ${st.origin === 'factory' ? html`<span class="sset-org">factory</span>`
                    /* écrit 'golemfm' depuis le 2026-10-15 ; 'maestrium' (l'ancien nom) reste sur les racks d'avant */
                    : (st.origin === 'golemfm' || st.origin === 'maestrium') ? html`<span class="sset-org">golem.fm</span>` : ''}</span>
                <span class="rec-count">×${(st.samples || []).length}</span>
                ${/* deux taps, comme toute suppression de la page (le 🗑 d'un kit partait au premier, 2026-10-22) */''}
                ${st.origin !== 'factory' ? html`<button class=${cls('rec-del', armDel === 'set:' + st.slug && 'arm')} title="delete the kit (its samples stay in the library)"
                  onClick=${async () => { const k = 'set:' + st.slug;
                    if (armDel !== k) { setArmDel(k); setTimeout(() => setArmDel(a => a === k ? null : a), 2500); return; }
                    setArmDel(null); await fetch('/api/sample-sets/' + st.slug, { method: 'DELETE' }); reloadSets(); }}>${armDel === 'set:' + st.slug ? 'sure?' : '🗑'}</button>` : ''}
              </div>
              <div class="rec-body">
                ${(st.samples || []).map((x, i) => { const k = 's:' + st.slug + ':' + x.file;
                  return html`<${WaveTrack} key=${k} audio=${aud(x.file)} peaks=${pks(x.file)}
                    name=${x.name || x.file.split('/').pop()} num=${i + 1}
                    on=${playing === k} onToggle=${go => setPlaying(go ? k : null)} />`; })}
              </div>
            </div>`)}
          </div>
        </div>` : ''}
        ${shown.length ? groupsOf(shown).map(g => html`<div class="rec-day">
          <div class="rec-day-lb">${g.label}<em>${g.items.length} ${song ? 'long file' : 'one-shot'}${g.items.length > 1 ? 's' : ''}${song && g.first ? ' — stems for a local backing (Tracks ▸ Backings)' : ''}</em></div>
          <div class="smp-grid">
            ${g.items.map(s2 => { const used = usage[s2.file], k = 'f:' + s2.file, on = playing === k;
              return html`<div class=${cls('smp-tile', 'f-' + (song ? 'song' : (s2.cat || 'perc')), on && 'on')}>
                <button class="smp-tap" title=${on ? 'stop' : 'listen'} onClick=${() => play(s2)}>
                  <span class="smp-pl">${on ? '❚❚' : '▶'}</span>
                  <span class="smp-tx">
                    <b class="smp-nm" title=${s2.name}>${esc(pretty(s2.name))}</b>
                    <span class="smp-meta">${fmtDur(s2.dur)}${fmtDur(s2.dur) ? ' · ' : ''}${fmtBytes(s2.bytes)}</span>
                  </span>
                </button>
                <div class="smp-ft">
                  ${used ? html`<span class="smp-used-tag" title=${'used by ' + used.join(', ') + ' — protected'}>● ${esc(used.join(', '))}</span>`
                    : html`<span class="smp-free">unused</span>`}
                  <a class="smp-ic edit-only" href=${aud(s2.file)} onClick=${saveClick(aud(s2.file), s2.file.split('/').pop())} title="download">⬇</a>
                  ${!used ? html`<button class="smp-ic" title=${song ? 'this is a one-shot for the pads — move to Short' : 'this is a long file: a stem for a local backing — move to Songs'} onClick=${() => rekind(s2)}>${song ? '→ Short' : '→ Songs'}</button>
                    <button class=${cls('smp-ic', 'smp-del', armDel === s2.file && 'arm')} title="delete" onClick=${() => del(s2)}>${armDel === s2.file ? 'sure?' : '🗑'}</button>` : ''}
                </div>
              </div>`; })}
          </div>
        </div>`) : html`<div class="empty">${song
            ? html`No song samples${q ? ' matching' : ''} — tap <b>+ Add</b> to upload a long file (a bounce, a click, a pad…). The Sample block plays them, and a song can place them on its arrangement.`
            : html`No samples${q ? ' matching' : ''} — tap <b>+ Add</b> to upload one-shots (<code>.wav</code>, <code>.flac</code>…). They feed the pad kits and the Sample block.`}</div>`}`;
      })()}
    </div>
  </div>`;
}
