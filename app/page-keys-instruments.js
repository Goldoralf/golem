// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Instruments (hub Library ▸ Keys) — ce que le rack LIVRE pour la lane Keys, en lecture seule
// (décision 2026-09-15, même règle que Drums ▸ Drums) : le piano SFZ (sfizz, Salamander Grand,
// 714 Mo posés par provision/fetch-assets.sh), l'e-piano FM (Dexed, banques SysEx DX7 de
// library/dx7/) et l'orgue à roues phoniques (setBfree, tout est dans le plugin). Ni ajout, ni
// suppression : un nouvel instrument arrive par une mise à jour du rack. Les presets Vital, seul
// contenu clavier que l'utilisateur ajoute, restent dans Synths.
import { html, useAsync, esc, setSubToolbar, useEffect, useState } from './lib.js';

const j = u => fetch(u).then(r => r.json());

export function KeysInstrumentsPage() {
  const { data: sfz } = useAsync(() => j('/api/sfz').catch(() => ({})), []);
  const { data: dx7 } = useAsync(() => j('/api/dx7').catch(() => ({})), []);
  const { data: fx } = useAsync(() => j('/api/effects').catch(() => ({})), []);
  const [q, setQ] = useState('');
  useEffect(() => {
    setSubToolbar(html`<input class="search" type="search" placeholder="Search instrument…" onInput=${e => setQ(e.target.value.trim().toLowerCase())} />`);
    return () => setSubToolbar(null);
  }, []);
  const def = t => ((fx && fx.effects) || []).find(e => e.type === t) || {};
  const pianos = (sfz && sfz.instruments) || [];
  const banks = (dx7 && dx7.banks) || [];
  const cards = [
    { type: 'piano', glyph: '🎹', name: def('piano').name || 'Piano', engine: 'sfizz',
      meta: pianos.length ? `${pianos.length} SFZ instrument(s)` : 'no SFZ instrument on disk',
      lines: pianos.map(p => ({ name: p.name, sub: p.id.split('/').pop() })),
      note: pianos.length ? 'Sampled piano (sfizz). Pick the variant in the Piano block of a Keys lane — the sound is on this rack, nothing to download.'
        // un texte de MUSICIEN (2026-10-22) : il nommait un script de provision/ — le pack est un choix de l'installeur
        : 'The Salamander Grand Piano is not installed on this golem. It comes with the golem installer, as an optional pack (714 MB).' },
    { type: 'ep', glyph: '🎛', name: def('ep').name || 'E-Piano', engine: 'dexed',
      meta: banks.length ? `${banks.length} DX7 bank(s) · ${banks.reduce((n, b) => n + ((b.patches || []).length), 0)} sounds` : 'no DX7 bank on disk',
      lines: banks.map(b => ({ name: b.name, sub: (b.patches || []).length + ' sounds' })),
      note: 'FM electric piano (Dexed, a DX7). Bank and sound are chosen per scene in the E-Piano block.' },
    { type: 'organ', glyph: '🪗', name: def('organ').name || 'Organ', engine: 'b3',
      meta: 'tonewheel engine', lines: [],
      note: 'Tonewheel organ (setBfree) — drawbars, Leslie and percussion are block knobs, per scene. There is no file: the sound is the engine.' },
  ].filter(c => !q || c.name.toLowerCase().includes(q) || c.lines.some(l => l.name.toLowerCase().includes(q)));

  const Card = c => html`<div class="rec-card">
    <div class="rec-head">
      <span class="rec-glyph">${c.glyph}</span>
      <span class="rec-title">
        <span class="rec-name">${esc(c.name)}</span>
        <span class=${'kit-badge e-' + c.engine}>${c.engine}</span>
        <span class="rec-ctx">${esc(c.meta)}</span>
      </span>
      <span class="kit-factory" title="ships with the rack — a new instrument comes with a rack update; not deletable">Rack instruments</span>
    </div>
    <div class="rec-body">
      ${c.lines.length ? html`<div class="ki-lines">${c.lines.map(l => html`<div class="ki-line"><span>${esc(l.name)}</span><span class="muted">${esc(l.sub)}</span></div>`)}</div>` : ''}
      <div class="rec-meta muted">${esc(c.note)}</div>
    </div>
  </div>`;

  return html`<div class="library"><div class="lib-grid">
    <div class="rec-day"><div class="rec-grid">${cards.map(Card)}</div></div>
  </div></div>`;
}
