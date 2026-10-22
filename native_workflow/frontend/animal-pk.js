'use strict';
function animalPkControlUrl(){return '/assets/animal-pk-control.html?session='+encodeURIComponent(flow?.session_id||'');}
function renderAnimalPkEntry(n){return '';}
const pkPlanningEntries = new Set();
function enterAnimalPkDraft(){const upstream=getNode('dispatch');if(!flow?.session_id||!upstream?.state.approved)return;const key=flow.session_id+JSON.stringify(upstream.state.artifacts.map(a=>a.sha256));if(pkPlanningEntries.has(key))return;pkPlanningEntries.add(key);json(`/ui-api/workflow/sessions/${encodeURIComponent(flow.session_id)}/animal-pk/planning/enter`,{method:'POST'}).catch(e=>toast(e.message));}
function bindAnimalPkEntry(){if(selected==='pk')enterAnimalPkDraft();if($('#open-animal-pk'))$('#open-animal-pk').onclick=openAnimalPk;}
function openAnimalPk(){window.location.assign(animalPkControlUrl());}
