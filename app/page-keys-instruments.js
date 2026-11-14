// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Instruments (hub Library ▸ Keys) — ce que le rack LIVRE pour la lane Keys, en lecture seule (décision
// 2026-09-15) : le piano SFZ (sfizz, Salamander Grand), l'e-piano FM (Dexed, banques DX7 de library/dx7/) et l'orgue
// à roues phoniques (setBfree). Un nouvel instrument arrive par une mise à jour du rack.
// 2026-11-14 (maquette validée, docs/preset-preview.md §9.1) : les trois instruments DESSINÉS par golem-fx, côte à
// côte, et chaque son qui a une démo s'ENTEND au toucher ; la fiche E-Piano montre les 32 sons d'une banque (une
// douzaine choisis ont leur démo, le dessin suit la famille du son : tine, reed, clav, clavecin, mallet, FM).
import { html, useState, useAsync, cls, esc } from './lib.js';
import { useVisuals, Drawing } from './tones-ui.js';
import { keysSvg, useClip, Mark, ClipBar, dur } from './keys-ui.js';

const j = u => fetch(u).then(r => r.json());
const ENGINE = { piano: 'sfizz', ep: 'dexed', organ: 'b3' };

export function KeysInstrumentsPage() {
  const vis = useVisuals();
  const { data } = useAsync(() => j('/api/keys/sounds').catch(() => null), []);
  const cl = useClip();
  const [ep, setEp] = useState(false);
  const ins = (data && data.instruments) || [];
  const by = t => ins.find(i => i.type === t) || {};
  if (ep) return html`<div class="library tn-page"><${EPiano} ins=${by('ep')} vis=${vis} cl=${cl} onClose=${() => setEp(false)} /></div>`;

  const pianos = by('piano').sounds || [];
  const banks = by('ep').banks || [];
  const epReady = banks.flatMap(b => b.programs.filter(p => p.status === 'ready').map(p => ({ ...p, bank: b.bank })));
  const organ = (by('organ').sounds || [])[0];
  const row = (s, label) => html`<button class=${cls('ky-row', cl.playing(s) && 'on')} disabled=${s.status !== 'ready'}
      onClick=${() => cl.play({ ...s, title: label })}>
    <${Mark} on=${cl.playing(s)} s=${s} /><span class="nm">${label}</span><em>${dur(s)}</em></button>`;
  const Tile = ({ kind, title, name, sub, children }) => html`<div class="ky-inst">
    <div class="ky-art">${vis ? html`<${Drawing} svg=${keysSvg({ kind, title })} align="xMidYMid" />` : ''}</div>
    <div class="ky-body">
      <div class="ky-hd"><b>${name}</b><span class=${'kit-badge e-' + ENGINE[kind === 'epiano' ? 'ep' : kind]}>${ENGINE[kind === 'epiano' ? 'ep' : kind]}</span></div>
      <div class="ky-sub">${sub}</div>
      ${children}
    </div></div>`;

  return html`<div class="library tn-page"><div class="tn-col ky-col">
    <div class="ky-stand">
      <${Tile} kind="piano" title="Grand" name="Piano"
        sub=${pianos.length ? `Salamander Grand · ${pianos.length} variant${pianos.length > 1 ? 's' : ''}` : 'Not installed: it comes with the golem installer, as an optional pack (714 MB).'}>
        <div class="ky-rows">${pianos.map(s => row(s, s.name))}</div></${Tile}>
      <${Tile} kind="epiano" title="E.Piano 1" name="E-Piano"
        sub=${`${banks.length} DX7 banks · ${banks.reduce((n, b) => n + b.programs.length, 0)} sounds · ${epReady.length} to hear`}>
        <div class="ky-chips">${epReady.slice(0, 4).map(s => html`<button class=${cls('ky-chip', cl.playing(s) && 'on')}
            onClick=${() => cl.play({ ...s, title: s.name })}><${Mark} on=${cl.playing(s)} s=${s} /> ${esc(s.name)}</button>`)}
          <button class="ky-more" onClick=${() => setEp(true)}>All ${banks.reduce((n, b) => n + b.programs.length, 0)} ›</button></div></${Tile}>
      <${Tile} kind="organ" title="Tonewheel" name="Organ" sub="Tonewheel · drawbars and Leslie are block knobs, per scene">
        <div class="ky-rows">${organ ? row(organ, 'Tonewheel') : ''}</div></${Tile}>
    </div>
    <${ClipBar} cl=${cl} />
  </div></div>`;
}

/** la fiche E-Piano : une banque à la fois, ses 32 sons ; le dessin suit le son choisi */
function EPiano({ ins, vis, cl, onClose }) {
  const banks = ins.banks || [];
  const first = banks.findIndex(b => b.programs.some(p => p.status === 'ready'));
  const [bi, setBi] = useState(Math.max(0, first));
  const bank = banks[bi] || { programs: [] };
  const [sel, setSel] = useState(() => bank.programs.find(p => p.status === 'ready') || bank.programs[0]);
  const cur = sel && bank.programs.includes(sel) ? sel : bank.programs[0];
  const pick = p => { setSel(p); if (p.status === 'ready') cl.play({ ...p, title: p.name }); };
  return html`<div class="tn-col ky-col">
    <div class="ky-detail">
      <div class="ky-left">
        <button class="tn-back" onClick=${onClose}>‹ Instruments</button>
        <div class="ky-art big">${vis && cur ? html`<${Drawing} svg=${keysSvg({ kind: 'epiano', title: cur.name })} align="xMidYMid" />` : ''}</div>
        <div class="ky-title"><b>${cur ? cur.name : ''}</b><span>${esc(bank.bank || '')} · sound ${cur ? cur.n + 1 : ''}${cur && cur.status === 'ready' ? ' · ' + (cur.phrase || '') : ''}</span></div>
        <h6 class="ky-h6">Bank</h6>
        <div class="ky-banks">${banks.map((b, i) => { const n = b.programs.filter(p => p.status === 'ready').length;
          return html`<button class=${cls('ky-bank', i === bi && 'on')} onClick=${() => { setBi(i); setSel(null); }}>${b.bank}${n ? html` <em>· ${n}</em>` : ''}</button>`; })}</div>
      </div>
      <div class="ky-progs">${bank.programs.map(p => html`<button class=${cls('ky-pg', p.status === 'ready' && 'has', cur === p && 'sel', cl.playing(p) && 'on')}
          title=${p.status === 'ready' ? 'hear it' : 'no demo for this sound: pick it in the E-Piano block to play it'} onClick=${() => pick(p)}>
          <${Mark} on=${cl.playing(p)} s=${p} /><span>${p.n + 1} · ${esc(p.name)}</span></button>`)}</div>
    </div>
    <${ClipBar} cl=${cl} hint="▶ marks the sounds that have a demo. The others play in the E-Piano block of a Keys lane." />
  </div>`;
}
