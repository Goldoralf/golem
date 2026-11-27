// SPDX-License-Identifier: GPL-3.0-or-later
// LES ANIMATIONS DES CASES DE /live, AILLEURS QUE SUR LE RACK (2026-11-26 : le mode Control du Companion, debout).
// Elles vivent dans app/style.css (`.anim-*`, `@keyframes lp-*`), mêlées au reste de l'app : le téléphone ne charge pas
// style.css, qui repeindrait tout. On le LIT une fois, on n'en garde que les règles d'animation (sélecteur qui nomme
// une classe anim-*, ou les cases figées `tiles-still`, keyframes lp-*, et les @media qui en contiennent), et on les
// pose dans une feuille à part. Une seule source : une animation ajoutée au rack arrive sur le téléphone sans copie.
// Une case animée = un élément positionné, `overflow:hidden`, la couleur dans `--pc` et la classe animClass(anim).

let _done = null;

const keep = r => {
  if (r.type === CSSRule.KEYFRAMES_RULE) return /^lp-/.test(r.name);
  if (r.type === CSSRule.STYLE_RULE) return /anim-|tiles-still/.test(r.selectorText || '');
  return false;
};

export function loadTileAnims() {
  if (_done) return _done;
  // RELATIF À CE MODULE, jamais « /app/style.css » : la coquille de golem.fm sert l'app sous /golem-app/<commit>/, où le
  // chemin absolu donnait 404 — le Companion en mode Control y perdait ses animations (vu sur le site, 2026-11-27)
  _done = fetch(new URL('./style.css', import.meta.url)).then(r => r.text()).then(txt => {
    const src = new CSSStyleSheet();
    src.replaceSync(txt.replace(/@import[^;]+;/g, ''));        // replaceSync refuse les @import
    const out = [];
    for (const r of src.cssRules) {
      if (keep(r)) out.push(r.cssText);
      else if (r.type === CSSRule.MEDIA_RULE) {
        const inner = [...r.cssRules].filter(keep).map(x => x.cssText);
        if (inner.length) out.push(`@media ${r.conditionText} {${inner.join('\n')}}`);
      }
    }
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(out.join('\n'));
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
    return out.length;
  }).catch(e => { console.warn('[anim-tiles] animations indisponibles :', e); _done = null; return 0; });
  return _done;
}
