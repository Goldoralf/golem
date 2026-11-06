// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Loops (hub Library) — les PERFORMANCES enregistrées (perf rec : le mix
// stéréo complet — guitare + looper + pads + backing — capturé côté Reaper,
// contrat perf_rec). Le REC se déclenche sur /live (réglage de mode) ; ici = la liste
// des prises (Recordings) avec player audio, taille/date, suppression 2-tap.
import { html, useState, useEffect, useAsync, cls, esc, setTopAction, setSubToolbar, saveClick } from './lib.js';
import { WaveTrack } from './wavetrack.js';   // la mini-piste de DAW, partagée avec la Library

const fmtBytes = b => !b ? '—' : b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.round(b / 1e3) + ' kB';
const sameDay = (a, b) => a.toDateString() === b.toDateString();
// libellé de SECTION : les prises du jour ne se lisent pas comme celles d'il y a trois semaines
const dayLabel = t => {
  const d = new Date(t * 1000), now = new Date(), y = new Date();
  y.setDate(now.getDate() - 1);
  if (sameDay(d, now)) return 'Today';
  if (sameDay(d, y)) return 'Yesterday';
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'long', year: 'numeric' });
};
const hhmm = t => new Date(t * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
const url = p => '/api/loop/' + p.split('/').map(encodeURIComponent).join('/');
const peaksUrl = p => '/api/loop-peaks/' + p.split('/').map(encodeURIComponent).join('/');

export function LoopsPage() {
  const [tick, setTick] = useState(0);
  const { data } = useAsync(() => fetch('/api/loops').then(r => r.json()), [tick]);
  const [perf, setPerf] = useState(null);
  const [armDel, setArmDel] = useState(null);
  const [playing, setPlaying] = useState(null);      // fichier dans le player
  // ACCORDÉON (2026-10-15 : « pour gagner de la place et de la lisibilité ») : une prise se replie sur son
  // en-tête. Repliée, ses pistes ne sont PAS rendues (pas de `hidden`, qu'une règle d'auteur peut défaire —
  // CLAUDE.md) ; la taille, le tempo et la scène remontent dans l'en-tête.
  const [opened, setOpened] = useState(() => new Set());
  const toggle = key => setOpened(prev => { const n = new Set(prev); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  // modes machine : le badge de CONTEXTE de chaque prise (« Home », « Gig »…). On lit la
  // définition côté bridge plutôt que de recopier les libellés ici — un mode renommé ou
  // ajouté (les modes sont de la DONNÉE, cf. docs/modes.md) suit tout seul.
  const { data: modesData } = useAsync(() => fetch('/api/modes').then(r => r.json()), []);
  // Place disque (roadmap 0.a) : c'est ICI qu'on la montre, parce que c'est ici qu'on la
  // reprend — la corbeille est à trois centimètres. Une jauge sur un écran où l'on ne peut
  // rien faire ne serait qu'une source d'inquiétude.
  const { data: rigState } = useAsync(() => fetch('/api/state').then(r => r.json()), [tick]);
  const { data: bandData } = useAsync(() => fetch('/api/band').then(r => r.json()), [tick]);
  const knownBands = (bandData || {}).bands || [];
  const [bandPick, setBandPick] = useState(null);     // id de session dont le sélecteur est ouvert
  // NOMMER une prise : le seul champ d'agrément qu'un humain écrit dans un manifeste. Le titre
  // voyage jusqu'à golem.fm, qui le respecte s'il est là (sinon il titre depuis le backing, le
  // standard, la compo ou le preset). Vider le champ rend son nom automatique à la prise.
  const [renaming, setRenaming] = useState(null);    // delKey de la prise en cours de renommage
  const [draft, setDraft] = useState('');
  const setTitle = async (dir, title) => {
    setRenaming(null);
    await fetch('/api/take/title', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dir, title }) }).catch(() => null);
    setTick(t => t + 1);
  };
  // Retaguer = corriger une OBSERVATION. On vise la session entière par défaut : c'est l'unité
  // de la répète, et c'est ce qui rend la correction assez peu chère pour qu'on n'ait jamais à
  // poser la question au moment d'enregistrer.
  const setBand = async (target, band) => {
    await fetch('/api/take/band', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...target, band }) }).catch(() => null);
    setBandPick(null); setTick(t => t + 1);
  };
  const disk = (rigState || {}).disk || {};
  const transcribe = async dir => {
    const r = await fetch('/api/take/transcribe', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dir }) })
      .then(x => x.json()).catch(e => ({ error: String(e) }));
    if (r && r.error) alert(r.error);      // un refus DOIT se dire : sinon le bouton a l'air mort
    setTick(t => t + 1);
  };
  const perfErr = (rigState || {}).perf_error || '';
  const MODES = {};
  (((modesData || {}).modes) || []).forEach(m => { MODES[m.id] = m; });
  // (le bouton Click a été RETIRÉ d'ici : le métronome se pilote depuis la topbar /live,
  // le pied ou le bloc Click du preset — cette page ne fait que lister les prises.)
  useEffect(() => { setTopAction(null); }, []);

  // poll du statut : léger, et seulement pendant qu'on enregistre (ou au montage)
  const loadPerf = () => fetch('/api/perf').then(r => r.json()).then(setPerf).catch(() => {});
  useEffect(() => { loadPerf(); }, [tick]);
  useEffect(() => {
    if (!perf || !perf.recording) return;
    const t = setInterval(loadPerf, 2000);
    return () => clearInterval(t);
  }, [perf && perf.recording]);

  // le déclenchement du REC a migré sur /live (réglage de mode off/manuel/auto) ; cette page
  // ne fait plus que LISTER les prises. On garde le poll perf pour rafraîchir quand une prise finit.
  const rec = !!(perf && perf.recording);
  const del = async fn => {
    if (armDel !== fn) { setArmDel(fn); setTimeout(() => setArmDel(a => a === fn ? null : a), 2500); return; }
    setArmDel(null);
    if (playing === fn) setPlaying(null);
    await fetch('/api/loop/' + encodeURIComponent(fn), { method: 'DELETE' }).catch(() => null);
    setTick(t => t + 1);
  };

  const loops = (data && data.loops) || [];
  useEffect(() => {
    setSubToolbar(rec ? html`
      <span class="rec-live" title="recording in progress — controlled from the Live page">● REC</span>` : null);
    return () => setSubToolbar(null);
  }, [rec]);
  const takes = (data && data.takes) || [];
  const delTake = async d => {
    if (armDel !== d) { setArmDel(d); setTimeout(() => setArmDel(a => a === d ? null : a), 2500); return; }
    setArmDel(null);
    await fetch('/api/take/' + encodeURIComponent(d), { method: 'DELETE' }).catch(() => null);
    setTick(t => t + 1);
  };
  // ── UNE SEULE liste. Une prise appartient à UN groupe et un seul, décidé par son NOMBRE DE
  // PISTES et non par sa forme de stockage : un dossier qui ne contient qu'un .wav est une prise
  // SIMPLE, pas une multipiste (avant, tout dossier atterrissait dans « multitrack » et les .wav
  // à plat dans une seconde liste — la même prise semblait figurer deux fois).
  const items = [
    ...takes.map(t => {
      const man = t.manifest || {};
      const mids = t.midi || [];
      return { key: 'd:' + t.dir, multi: (t.files.length + mids.length) > 1, files: t.files,
               midi: mids, mtime: t.mtime,
               bytes: t.bytes, man, labels: t.labels || {}, name: man.preset_name || t.dir.replace(/^perf-/, ''),
               path: f => t.dir + '/' + f, delKey: t.dir, onDel: () => delTake(t.dir), rpp: t.dir,
               // transcription : le dossier EST la clé du travail, et l'état vient du rack
               dir: t.dir, score: t.score, can_transcribe: t.can_transcribe,
               no_transcribe: t.no_transcribe };
    }),
    ...loops.map(l => ({ key: 'f:' + l.file, multi: false, files: [l.file], mtime: l.mtime,
                         bytes: l.bytes, man: l.manifest || {}, labels: l.labels || {},
                         name: (l.labels && l.labels[l.file]) || l.file.replace(/\.wav$/i, ''),
                         path: () => l.file, delKey: l.file, onDel: () => del(l.file), rpp: l.file })),
  ].sort((a, b) => b.mtime - a.mtime);           // plus récent d'abord, toutes formes confondues

  // ── SECTIONS PAR SESSION, plus par jour ──────────────────────────────────────────────────
  // Une répète, c'est douze prises : retaguer douze cartes une par une, personne ne le fera.
  // La session EST l'unité de correction, donc l'unité d'affichage. Une prise sans session
  // (antérieure au journal) retombe sur son jour — on ne perd rien, on ne ment pas.
  const days = [];
  items.forEach(it => {
    const sid = it.man.session || null;
    const lb = dayLabel(it.mtime);
    const last = days[days.length - 1];
    if (!last || (sid ? last.sid !== sid : (last.sid || last.lb !== lb)))
      days.push({ lb, sid, items: [] });
    days[days.length - 1].items.push(it);
  });
  // le groupe d'une session = celui de ses prises quand elles sont d'accord ; sinon « mixte »,
  // et c'est une information, pas un défaut à masquer.
  days.forEach(d => {
    const ids = [...new Set(d.items.map(i => (i.man.band || {}).id || null))];
    d.band = ids.length === 1 ? (d.items[0].man.band || null) : undefined;   // undefined = mixte
    if (d.band === undefined) {                       // session mixte : on marque les intrus
      const major = ids.map(id => [id, d.items.filter(i => ((i.man.band || {}).id || null) === id).length])
        .sort((a, b) => b[1] - a[1])[0][0];
      d.items.forEach(i => { i.odd = ((i.man.band || {}).id || null) !== major; });
      d.band = (d.items.find(i => !i.odd) || {}).man.band || null;
    }
  });
  const untagged = items.filter(i => i.man.kind === 'take' && !i.man.band);

  // ── LE BOUTON DE TRANSCRIPTION (docs/archive/tablature-study.md §12) ────────────────────────────
  // Quatre états, et ce sont ceux qui existent VRAIMENT — pas un état idéal :
  //   · transcriptible      -> « Transcribe »
  //   · en cours            -> l'avancement, source par source (un travail muet de 30 s est
  //                            indiscernable d'un bouton cassé)
  //   · déjà faite          -> le bouton devient l'ACCÈS à la partition, et dit son nombre de
  //                            mesures ; tap long = refaire
  //   · rien à transcrire   -> grisé ET la raison, avec la sortie (passer le Rec en Multi + DI)
  const tr = (rigState || {}).transcribe || {};
  const trBusy = (tr.current || {}).dir;
  const TranscribeBtn = it => {
    const done = it.score;
    const last = (tr.last || {})[it.dir];
    // ⚠ le garde `trBusy &&` n'est pas décoratif : sans lui, quand rien ne tourne, `undefined
    // === undefined` est VRAI et TOUTES les prises s'affichent « en cours » (constaté).
    if (trBusy && trBusy === it.dir) {
      const c = tr.current || {};
      return html`<span class="rec-tr run" title=${'transcribing ' + (c.source || '')}>
        ◌ ${Math.round((c.progress || 0) * 100)} %${c.source ? ' · ' + esc(c.source) : ''}</span>`;
    }
    if (!it.can_transcribe) {
      return html`<span class="rec-tr off" title=${it.no_transcribe || 'nothing to transcribe'}>♫</span>`;
    }
    if (last && last.ok === false) {
      return html`<button class="rec-tr fail" title=${'failed: ' + (last.error || '')}
        onClick=${() => transcribe(it.dir)}>♫ retry</button>`;
    }
    if (done) {
      // Une couleur d'alerte pour l'état NORMAL se lit comme une panne : le brouillon est la
      // règle (l'audio passe par un modèle), l'exact est l'exception (le MIDI est déjà des
      // notes). On marque donc l'exception dans le LIBELLÉ, pas la règle dans la couleur.
      const allExact = done.exact && !done.draft;
      return html`<button class=${cls('rec-tr done')}
        title=${done.sources + ' score' + (done.sources > 1 ? 's' : '') + ' · ' + done.bars + ' bars'
                + (done.draft ? ' · audio parts are a DRAFT (fingering to review)' : '')
                + (done.exact ? ' · ' + done.exact + ' exact from MIDI' : '')
                + ' — tap to re-transcribe'}
        onClick=${() => transcribe(it.dir)}>♫ ${done.bars} bars${allExact ? ' · exact' : ''}</button>`;
    }
    return html`<button class="rec-tr" title="transcribe this take into scores & tabs — background, lowest priority"
      onClick=${() => transcribe(it.dir)}>♫ Transcribe</button>`;
  };

  // La carte EST le mini-DAW de la prise, repliable depuis le 2026-10-15 (accordéon). Même gabarit pour une prise
  // simple — c'est juste une carte à une seule piste.
  const card = it => { const ctx = MODES[it.man.machine_mode], bk = it.man.backing;
    const isOpen = opened.has(it.delKey);
    // un tap sur l'en-tête plie/déplie — sauf sur ses boutons, liens et champ (renommer, transcrire, .rpp, corbeille)
    const onHead = e => { if (!e.target.closest('button, a, input')) toggle(it.delKey); };
    return html`<div class=${cls('rec-card', it.multi && 'multi', isOpen ? 'rec-open' : 'rec-shut')}>
    <div class="rec-head" onClick=${onHead}
      title=${it.name + ' · ' + hhmm(it.mtime) + (it.man.scene ? ' · scene ' + it.man.scene : '')
              + ' · ' + (it.multi ? it.files.length + ' tracks' : 'single track')}>
      <span class="rec-chev" aria-hidden="true">${isOpen ? '▾' : '▸'}</span>
      <span class="rec-glyph">${it.multi ? '▤' : '▪'}</span>
      <span class="rec-title">
        ${renaming === it.delKey
          ? html`<input class="rec-rename" value=${draft} autofocus
              placeholder=${it.name}
              onInput=${e => setDraft(e.target.value)}
              onKeyDown=${e => { if (e.key === 'Enter') setTitle(it.delKey, draft);
                                 if (e.key === 'Escape') setRenaming(null); }}
              onBlur=${() => setTitle(it.delKey, draft)} />`
          : html`<span class="rec-name" title=${it.man.title ? 'named — ' + it.name : it.name}
              onDblClick=${() => { setDraft(it.man.title || ''); setRenaming(it.delKey); }}>
              ${esc(it.man.title || it.name)}</span>
            <button class="rec-ren" title="name this take (double-click the name too)"
              onClick=${() => { setDraft(it.man.title || ''); setRenaming(it.delKey); }}>✎</button>`}
        ${ctx ? html`<span class=${'rec-ctx m-' + it.man.machine_mode}
          title=${'recorded in ' + ctx.name + ' mode'}>${ctx.icon} ${esc(ctx.name)}</span>` : ''}
        ${/* LE GROUPE (roadmap 0.c) : c'est lui qui décide de la destination, donc il se voit.
              Une prise SANS groupe reste ici — on le dit, sinon son immobilité passerait pour
              une panne le jour où la montée existera. */''}
        ${/* le groupe vit sur l'EN-TÊTE DE SESSION. Ici on ne montre que l'EXCEPTION : la prise
              que le duo est venu jouer au milieu de ta répète. Répéter douze fois la même
              information, c'est la rendre invisible. */''}
        ${it.odd ? (it.man.band
          ? html`<span class="rec-band" title=${'exception — this take belongs to ' + it.man.band.name}>◈ ${esc(it.man.band.name)}</span>`
          : html`<span class="rec-band none" title="no band on this take — it stays on the rack until it gets one">◇ no band</span>`) : ''}
        ${/* le JOURNAL de la prise (roadmap 0.b) : combien de morceaux la machine a vu passer.
              C'est le seul retour visible que les marques fonctionnent — sans lui, une prise
              journalisée et une prise muette se ressemblent trait pour trait. */''}
        ${(() => { const mk = it.man.marks || [];
          const songs = mk.filter(m => m.kind === 'preset');
          if (!mk.length) return '';
          const names = songs.map(m => m.name || m.value).join(' → ');
          return html`<span class="rec-marks" title=${'journal: ' + mk.length + ' mark'
              + (mk.length > 1 ? 's' : '') + (names ? ' · ' + names : '')}>
            ⌁ ${songs.length || mk.length} ${songs.length ? 'song' + (songs.length > 1 ? 's' : '') : 'marks'}</span>`;
        })()}
        ${bk ? html`<a class=${cls('rec-bk', !bk.played && 'idle')} href="#/library/tracks/backing"
          title=${(bk.played ? 'played over this backing track' : 'backing track loaded (never played)')
                  + ' — open Backings'}>♫ ${esc(bk.title)}</a>` : ''}
      </span>
      ${/* TRANSCRIPTION (docs/archive/tablature-study.md §12) : le geste vit ICI, dans la zone d'actions
            de la prise, à côté de la puce +DI qui en est justement la précondition. C'est aussi
            le SEUL chemin capable de transcrire ce qui a été enregistré avant que la fonction
            existe — 35 DI dormaient sur le disque le jour où on l'a écrite. */''}
      ${!isOpen ? html`<span class="rec-sum muted">${fmtBytes(it.bytes)}${it.man.bpm ? ' · ♩' + it.man.bpm : ''}${it.man.scene ? ' · ' + esc(it.man.scene) : ''}</span>` : ''}
      ${it.multi ? TranscribeBtn(it) : ''}
      ${it.man.mode === 'tracks_di' ? html`<span class="sset-org">+DI</span>` : ''}
      <span class="rec-time">${hhmm(it.mtime)}</span>
      ${/* OUVRIR CETTE PRISE DANS REAPER (2026-10-11) : un .rpp écrit à côté de l'audio — une piste par fichier,
            chemins relatifs, tempo du manifeste — le dossier s'ouvre tel quel ailleurs. Pas d'effets : l'audio pris. */''}
      ${/* la clé du .rpp : le DOSSIER d'une prise (même à une seule piste), le fichier d'une boucle à plat — `it.file`
            n'existait pas : une prise à une piste demandait /api/take/rpp/undefined (2026-10-22) */''}
      <a class="rec-rpp edit-only" href=${'/api/take/rpp/' + encodeURIComponent(it.rpp)} onClick=${saveClick('/api/take/rpp/' + encodeURIComponent(it.rpp))}
        title=${'REAPER project (.rpp) of this take — ' + (it.multi ? it.files.length + ' tracks' : '1 track') + ', audio as recorded, no effects; written next to the audio files'}>.rpp</a>
      ${it.multi ? html`<span class="rec-count">×${it.files.length}</span>` : ''}
      <button class=${cls('rec-del', armDel === it.delKey && 'arm')}
        title=${it.multi ? 'delete take' : 'delete'}
        onClick=${it.onDel}>${armDel === it.delKey ? 'sure?' : '🗑'}</button>
    </div>
    ${isOpen ? html`<div class="rec-body">
      ${it.files.map((f, i) => { const pk = it.path(f);
        return html`<${WaveTrack} key=${pk} audio=${url(pk)} peaks=${peaksUrl(pk)}
          label=${f.replace(/\.wav$/i, '')}
          name=${(it.labels && it.labels[f]) || f.replace(/\.wav$/i, '')}
          num=${it.multi ? i + 1 : 0} on=${playing === pk}
          onToggle=${go => setPlaying(go ? pk : null)}
          extra=${html`<a class="wv-dl edit-only" href=${url(pk)} onClick=${saveClick(url(pk), (it.multi ? it.dir.split('/').pop() + '-' : '') + f)} title="download">⬇</a>`} />`; })}
      ${(it.midi || []).map(f => { const pk = it.path(f);
        // capture MIDI : rien à écouter ici (ce sont des notes, pas du son) — on montre ce
        // qu'elle contient et on la donne à télécharger. C'est la « DI » d'un instrument MIDI.
        return html`<div class="wv-row midi">
          <span class="wv-n">♪</span>
          <span class="wv-info">
            <b class="wv-name">${esc((it.labels && it.labels[f]) || f)}</b>
            <em class="wv-tech">${esc(f)}</em>
          </span>
          <span class="wv-midi-tag">MIDI</span>
          <a class="wv-dl edit-only" href=${url(pk)} onClick=${saveClick(url(pk), (it.multi ? it.dir.split('/').pop() + '-' : '') + f)} title="download the .mid">⬇</a>
        </div>`; })}
      <div class="rec-meta muted">${fmtBytes(it.bytes)}${it.man.bpm ? ' · ♩' + it.man.bpm : ''}${it.man.scene ? ' · scene ' + esc(it.man.scene) : ''}</div>
    </div>` : ''}
  </div>`; };

  const gb = b => (b / 1e9).toFixed(1);
  const mins = Math.floor((disk.seconds || 0) / 60);
  const low = disk.seconds != null && mins < (disk.warn_minutes || 15);
  return html`<div class="library">
    <div class="lib-grid">
      ${/* le refus au PIED n'a pas de réponse HTTP à afficher : l'écran est le seul endroit où
            l'on peut apprendre pourquoi rien ne s'est passé quand on a appuyé. */''}
      ${perfErr ? html`<div class="rec-diskerr">⚠ ${esc(perfErr)}</div>` : ''}
      ${disk.free != null ? html`<div class=${cls('rec-disk', low && 'low')}
        title=${'takes ' + gb(disk.takes) + ' GB · ' + (disk.lanes || 1) + ' track'
                + ((disk.lanes || 1) > 1 ? 's' : '') + ' at ' + (disk.rate / 1e6).toFixed(2) + ' MB/s'
                + (disk.measured ? ' (measured)' : ' (estimated)')}>
        <span class="rd-lb">Disk</span>
        <span class="rd-bar"><i style=${'width:' + Math.min(100, Math.round(100 * (disk.takes || 0) / Math.max(1, (disk.takes || 0) + (disk.free || 0)))) + '%'}></i></span>
        <b>${gb(disk.free)} GB free</b>
        <em>${mins >= 60 ? Math.floor(mins / 60) + ' h ' + (mins % 60) + ' min' : mins + ' min'} of recording</em>
      </div>` : ''}
      ${/* LES PRISES EN ATTENTE — une ligne, pas une alerte. C'est un ÉTAT : le tag décide de
            la destination, donc une prise sans groupe reste ici. Sans ce rappel, le jour où la
            montée existera, leur immobilité passera pour une panne. */''}
      ${untagged.length && knownBands.length ? html`<div class="rec-wait">
        <b>${untagged.length} take${untagged.length > 1 ? 's' : ''} without a band</b>
        <span class="muted">— they stay on the rack</span>
        <span class="grow"></span>
        ${knownBands.map(b => html`<button class="mini" title=${'tag them all as ' + b.name}
          onClick=${() => setBand({ dirs: untagged.map(i => i.delKey) }, { id: b.id })}>◈ ${esc(b.name)}</button>`)}
      </div>` : ''}
      ${days.length ? days.map(d => html`<div class="rec-day">
        <div class="rec-day-lb">${d.lb}<em>${d.items.length} take${d.items.length > 1 ? 's' : ''}</em>
          ${/* LE GROUPE VIT ICI, sur la session — pas sur chaque carte (docs §4). Un tap
                retague toute la répète. Le rack ne PROPOSE que ce qu'il connaît : il
                sélectionne, il n'invente pas de groupe (docs/identity.md). */''}
          ${d.sid && knownBands.length ? html`<span class="rec-sess">
            <button class=${cls('rec-band', 'rec-band-btn', !d.band && 'none')}
              title=${d.band ? 'this session belongs to ' + d.band.name + ' — tap to change'
                             : 'no band on this session — it stays on the rack. Tap to assign.'}
              onClick=${() => setBandPick(bandPick === d.sid ? null : d.sid)}>
              ${d.band ? '◈ ' + d.band.name : '◇ no band'}</button>
            ${bandPick === d.sid ? html`<span class="rec-bandpop">
              ${/* L'ESPACE PERSONNEL EN TÊTE, et nommé pour ce qu'il est : « → my space » est
                    le geste du musicien qui récupère SA prise d'une répète de groupe (ou
                    l'inverse). Le noyer dans la liste des groupes, c'est le rendre
                    introuvable le soir où il sert. */''}
              ${knownBands.filter(b => b.kind === 'personal').map(b => html`<button
                class=${cls('mini', 'rec-mine', d.band && d.band.id === b.id && 'on')}
                title=${'move this session to ' + b.name + ' — your own space'}
                onClick=${() => setBand({ session: d.sid }, { id: b.id })}>👤 → my space</button>`)}
              ${knownBands.filter(b => b.kind !== 'personal').map(b => html`<button
                class=${cls('mini', d.band && d.band.id === b.id && 'on')}
                onClick=${() => setBand({ session: d.sid }, { id: b.id })}>◈ ${esc(b.name)}</button>`)}
              <button class="mini" onClick=${() => setBand({ session: d.sid }, null)}>◇ none</button>
            </span>` : ''}
          </span>` : ''}
        </div>
        <div class="rec-grid">${d.items.map(card)}</div>
      </div>`) : html`<div class="empty">No takes yet — tap the record button of the Live screen (or the Rec footswitch), play,
          then stop. Each take lands here, in the format set in the Rec block.</div>`}
    </div>
  </div>`;
}
