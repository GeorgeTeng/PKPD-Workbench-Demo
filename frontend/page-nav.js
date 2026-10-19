/* Breadcrumb links on pages opened from the workflow keep the current run. */
'use strict';
(() => {
 const session = new URLSearchParams(location.search).get('session') || '';
 const flow = session ? '/?flow=' + encodeURIComponent(session) : '/';
 const targets = {
  workflow: flow + '#view=workflow',
  species: '/assets/animal-pk-control.html?session=' + encodeURIComponent(session)
 };
 for(const link of document.querySelectorAll('[data-crumb]')) {
  const kind = link.dataset.crumb;
  link.href = kind === 'stage' ? flow + '#view=module&module=' + encodeURIComponent(link.dataset.module) : targets[kind] || flow;
 }
})();
