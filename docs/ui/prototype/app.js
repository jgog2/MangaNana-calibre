/* Local visual demo only. No provider, file, clipboard, storage, or Calibre APIs. */
'use strict';
(() => {
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const records = [
    {id:'atlas-dex', title:'The Quiet Atlas', author:'A. Mori', source:'MangaDex', edition:'Original edition', cover:0},
    {id:'moon-pill', title:'Paper Moon', author:'Y. Aoki', source:'MangaPill', edition:'Original edition', cover:1},
    {id:'blue-central', title:'Blue Hour', author:'N. Sora', source:'WeebCentral', edition:'Original edition', cover:2},
    {id:'atlas-color', title:'The Quiet Atlas', author:'A. Mori', source:'MangaDex', edition:'Colored edition', cover:0}
  ];
  const demoBooks = [
    {id:'import-1', title:'The Quiet Atlas', number:'01', pages:192, size:42, source:'Local CBZ'},
    {id:'import-2', title:'Paper Moon', number:'02', pages:160, size:36, source:'Local PDF'}
  ];
  const sliderDefinitions = [
    ['brightness','Brightness',0,200,100,1,'%'], ['contrast','Contrast',0,200,100,1,'%'],
    ['gamma','Gamma',0.2,3,1,0.05,''], ['saturation','Saturation',0,200,100,1,'%'],
    ['sharpness','Sharpness',0,200,100,1,'%']
  ];
  const stageNames = ['Choose Manga','Book Customization','Finalization'];
  const state = {stage:0, mode:'volumes', selected:null, inventory:[], chosen:new Set(), excluded:new Set(), results:[...records], query:'', gray:'off',  metadata:{title:'The Quiet Atlas', series:'The Quiet Atlas', author:'A. Mori'}, logs:['Ready. Local demonstration only.'], savedPresets:new Map()};

  function cover(record, size = '') {
    return `<span class="book-cover cover-${record.cover || 0} ${size}" aria-hidden="true"><span>DEMO<br>EDITION</span><b>${String((record.cover || 0) + 1).padStart(2,'0')}</b><span>READING<br>SAMPLE</span></span>`;
  }
  function notice(message) {
    $('#status-text').textContent = message;
    state.logs.push(message);
    if (state.logs.length > 80) state.logs.shift();
    $('#activity-text').textContent = state.logs.join('\n');
  }
  function showDialog(title, html) {
    $('#dialog-title').textContent = title;
    $('#dialog-body').innerHTML = html;
    $('#demo-dialog').showModal();
  }
  function renderResults() {
    let rows = [...state.results];
    if ($('#sort').value === 'title') rows.sort((a,b) => a.title.localeCompare(b.title));
    else if ($('#prefer-colored').checked) rows.sort((a,b) => Number(b.edition === 'Colored edition') - Number(a.edition === 'Colored edition'));
    $('#search-results').innerHTML = rows.length ? rows.map(record => `<button class="result-row" data-record="${record.id}" aria-pressed="${state.selected?.id === record.id}" aria-label="Select ${escapeHTML(record.title)}, ${record.source}, ${record.edition}">${cover(record)}<span class="result-text"><strong>${record.title}</strong><small>${record.author} · ${record.edition}</small><span class="source-pill">${record.source}</span></span><span class="result-action">${state.selected?.id === record.id ? '✓ Selected' : 'Select →'}</span></button>`).join('') : '<p class="muted">No results to show. Search by title or try “Atlas”.</p>';
    $('#result-count').textContent = `${rows.length} example${rows.length === 1 ? '' : 's'}`;
  }
  function renderTrending() {
    $('#recommendation-list').innerHTML = records.slice(0,3).map(record => `<button class="recommendation" data-record="${record.id}" aria-label="Choose trending ${record.title}">${cover(record)}<span><strong>${record.title}</strong><small>${record.author}</small></span></button>`).join('');
  }
  function clearJob() {
    state.selected = null;
    state.inventory = [];
    state.chosen.clear();
    state.excluded.clear();

    state.metadata = {title:'The Quiet Atlas', series:'The Quiet Atlas', author:'A. Mori'};
    $('#book-title').value = state.metadata.title;
    $('#book-series').value = state.metadata.series;
    $('#book-author').value = state.metadata.author;
    $('#book-title').readOnly = false;
    renderSelection();
  }
  function chooseMode(mode) {
    if (mode === state.mode) return;
    state.mode = mode;
    clearJob();
    state.results = [];
    state.query = '';
    $$('[data-mode]').forEach(button => button.setAttribute('aria-pressed', button.dataset.mode === mode));
    $('#online-discovery').hidden = mode === 'import';
    $('#import-discovery').hidden = mode !== 'import';
    $('#import-list').innerHTML = '<p class="muted">Your example books will appear here.</p>';
    renderResults();
    $('#search-note').textContent = `${mode === 'chapters' ? 'Chapter' : 'Volume'} mode · Search to see fictional example records.`;
    notice(mode === 'import' ? 'Import demo. Load the example books to begin.' : `Mode changed to ${mode}. Search when ready.`);
  }
  function selectRecord(id) {
    if (!state.mode) { notice('Choose Volumes or Chapters before selecting a manga.'); $('[data-mode="volumes"]').focus(); return; }
    if (state.mode === 'import') return;
    const record = records.find(item => item.id === id);
    if (!record) return;
    state.selected = record;
    state.inventory = Array.from({length:state.mode === 'volumes' ? 4 : 8}, (_,i) => ({id:`${record.id}-${i}`, number:String(i+1).padStart(2,'0'), title:record.title, pages:state.mode === 'volumes' ? 192+i*8 : 24, size:state.mode === 'volumes' ? 42+i*2 : 5.2, source:record.source}));
    state.chosen = new Set([state.inventory[0].id]);
    state.excluded.clear();
    state.metadata = {title:record.title, series:record.title, author:record.author};
    for (const [key,value] of Object.entries(state.metadata)) $(`#book-${key}`).value = value;
    $('#book-title').readOnly = false;

    $('#metadata-status').textContent = 'Example metadata';
    renderResults(); renderSelection();
    notice(`${record.title} selected · ${record.source} · Example inventory loaded.`);
  }
  function renderSelection() {
    const populated = state.selected !== null;
    $('#selection-empty').hidden = populated;
    $('#selection-filled').hidden = !populated;
    if (!populated) return;
    const record = state.selected;
    $('#selected-summary').innerHTML = `${cover(record,'large')}<div><h3>${escapeHTML(record.title)}</h3><p class="small muted">${escapeHTML(record.author)} · Fictional example</p><p><span class="source-pill">${escapeHTML(record.source)}</span></p><p class="small muted">${state.mode === 'import' ? 'Each input stays an independent book.' : escapeHTML(record.edition) + ' · ' + escapeHTML($('#language').value)}</p></div>`;
    $('#inventory-heading').textContent = state.mode === 'import' ? 'Imported Books' : state.mode === 'chapters' ? 'Chapters' : 'Volumes';
    $('#inventory-list').innerHTML = state.inventory.map(item => `<label class="inventory-row"><input class="round-check" type="checkbox" data-inventory="${item.id}" ${state.chosen.has(item.id) ? 'checked' : ''}><span class="item-text">${state.mode === 'import' ? escapeHTML(item.title) : (state.mode === 'chapters' ? 'Chapter ' : 'Volume ') + item.number}<small>${state.mode === 'import' ? item.source : state.mode === 'chapters' ? 'Standalone chapter' : 'Original volume'} · ${item.pages} example pages</small></span><span class="small muted">~${item.size.toFixed(1)} MB</span></label>`).join('');
    updateSelectionCount();
  }
  function updateSelectionCount() {
    $('#selection-count').textContent = `${state.chosen.size} of ${state.inventory.length} selected`;
    if (state.mode === 'import') {
      const chosen = state.inventory.filter(item => state.chosen.has(item.id));
      const multiple = chosen.length > 1;
      $('#book-title').readOnly = multiple;
      $('#book-title').value = multiple ? 'Multiple imported titles' : chosen[0]?.title || '';
      state.metadata.title = $('#book-title').value;
    }
  }
  function loadImports() {
    state.selected = {title:'2 imported books', author:'Example collection', source:'Local CBZ / PDF', cover:0};
    state.inventory = demoBooks.map(item => ({...item}));
    state.chosen = new Set(demoBooks.map(item => item.id));
    state.excluded.clear();
    state.metadata = {title:'Multiple imported titles', series:'', author:''};
    for (const [key,value] of Object.entries(state.metadata)) $(`#book-${key}`).value = value;
    $('#import-list').innerHTML = demoBooks.map(item => `<div class="result-row">${cover({cover:item.number === '01' ? 0 : 1})}<span class="result-text"><strong>${item.title}</strong><small>${item.source} · Example book</small></span><span class="status-pill">Loaded</span></div>`).join('');
    renderSelection(); notice('Two example books loaded. No files were accessed.');
  }
  function stageTo(index) {
    state.stage = Math.max(0,Math.min(2,index));
    $$('.stage').forEach((section,i) => { section.hidden = i !== state.stage; });
    $$('[data-stage]').forEach((button,i) => { if (i === state.stage) button.setAttribute('aria-current','step'); else button.removeAttribute('aria-current'); });
    $('#back').hidden = state.stage === 0;
    $('#next').hidden = state.stage === 2;
    $('#next').innerHTML = `Next: ${stageNames[state.stage+1] || ''} <span aria-hidden="true">→</span>`;
    if (state.stage === 2) renderOutputs();
    document.title = `MangaAnkā · ${stageNames[state.stage]}`;
    notice(state.stage === 0 ? 'Choose Manga · Demo session.' : !state.selected ? `${stageNames[state.stage]} · Using sample content for this view.` : `${stageNames[state.stage]} · Your demo selection is preserved.`);
    $$('.stage')[state.stage].querySelector('h2').focus({preventScroll:true});
  }
  function sliderValue(input) { return input.id === 'gamma' ? Number(input.value).toFixed(2) : `${input.value}%`; }
  function syncSlider(input) {
    input.style.setProperty('--fill',`${(Number(input.value)-Number(input.min))/(Number(input.max)-Number(input.min))*100}%`);
    input.nextElementSibling.value = sliderValue(input);
  }
  function setGray(value) {
    state.gray = value;
    $$('[data-gray]').forEach(button => button.setAttribute('aria-pressed',button.dataset.gray === value));
  }
  function syncDither() {
    $('#dither-strength').disabled = $('#dithering').value === 'Off';
    $('#dither-hint').textContent = $('#dither-strength').disabled ? 'Choose a dithering method to adjust strength.' : 'Demo setting · Sample artwork stays unchanged.';
  }
  function markSettingsChanged() {
    $('#preset').value = 'Custom';
    $('#preview-status').textContent = 'Settings changed · Refresh to review layout';
  }
  function settingsSnapshot() {
    return {sliders:Object.fromEntries(sliderDefinitions.map(([id]) => [id,$(`#${id}`).value])), gray:state.gray, depth:$('#output-depth').value, dither:$('#dithering').value, strength:$('#dither-strength').value};
  }
  function applyPreset(name) {
    const saved = state.savedPresets.get(name);
    for (const [id,, , ,value] of sliderDefinitions) $(`#${id}`).value = saved ? saved.sliders[id] : value;
    if (!saved && name === 'Crisp eInk') { $('#contrast').value = 115; $('#sharpness').value = 120; }
    setGray(saved ? saved.gray : ['Crisp eInk','Manga B&W'].includes(name) ? 'on' : 'off');
    $('#output-depth').value = saved ? saved.depth : state.gray === 'on' ? '8-bit grayscale' : 'Original';
    $('#dithering').value = saved ? saved.dither : name === 'Crisp eInk' ? 'Atkinson' : 'Off';
    $('#dither-strength').value = saved ? saved.strength : 100;
    $$('.slider').forEach(syncSlider); syncDither();

    notice(`${name} preset selected for the demo. Sample images are unchanged.`);
  }
  function samplePage(index) {
    return `<div class="sample-page variant-${index%3}" aria-hidden="true"><span class="sample-label">SAMPLE ${String(index+1).padStart(2,'0')}</span><div class="sample-panels"><span></span><span></span><span></span></div><span class="sample-label">LAYOUT STUDY</span></div>`;
  }
  function renderPreview() {
    const landscape = $('input[name="layout"]:checked').value === 'landscape';
    const rtl = $('#reading-direction').selectedIndex === 0;
    $('#thumbnail-grid').classList.toggle('landscape',landscape);
    $('#thumbnail-grid').innerHTML = Array.from({length:landscape ? 3 : 6},(_,i) => `<figure class="thumbnail">${landscape ? `<div class="page-spread">${samplePage(i*2+(rtl ? 1 : 0))}${samplePage(i*2+(rtl ? 0 : 1))}</div>` : samplePage(i)}<figcaption>${landscape ? 'Paired sample ' : 'Output page '}${i+1}<span>${landscape ? 'Landscape · two pages' : 'Portrait · individual page'}</span></figcaption></figure>`).join('');
    $('#preview-status').textContent = landscape ? '3 paired samples' : '6 sample pages';
    $('#preview-helper').textContent = `${$('#ereader').value} · Static samples only. Image adjustments and display simulation are not rendered.`;
  }
  function outputItems() {
    if (!state.selected) return [{id:'sample',title:'The Quiet Atlas',number:'01',pages:192,size:42,source:'MangaDex'}];
    return state.inventory.filter(item => state.chosen.has(item.id));
  }
  function renderOutputs() {
    const items = outputItems();
    const importMode = state.mode === 'import';
    const imported = importMode && state.selected;
    const type = imported ? 'Import' : state.mode === 'chapters' ? 'Chapter' : 'Volume';
    const format = $('#output-format').value;
    $('#chapter-output').hidden = state.mode !== 'chapters';
    $('#use-cover-label').textContent = importMode ? 'Use imported cover page in Calibre metadata' : state.mode === 'chapters' ? 'Use series cover in Calibre metadata' : 'Use source volume cover in Calibre metadata';
    // Demo imports have no series index for numbered metadata covers.
    $('#zero-pad-option').hidden = importMode;
    $('#zero-pad').disabled = importMode;
    $('#cover-helper').textContent = importMode
      ? 'Metadata covers are separate from reading pages. Imported reading pages stay in sequence.'
      : 'Metadata covers are separate from reading pages.';
    $('#output-rows').innerHTML = items.map(item => {
      const title = imported && items.length > 1 ? item.title : state.metadata.title || item.title;
      const suffix = imported ? '' : ` · ${type === 'Chapter' ? 'Ch.' : 'Vol.'} ${$('#zero-pad').checked ? item.number : Number(item.number)}`;
      return `<tr><td><input class="round-check" type="checkbox" data-output="${item.id}" aria-label="Include ${escapeHTML(title + suffix)}" ${state.excluded.has(item.id) ? '' : 'checked'}></td><td>${$('#use-cover').checked ? cover(state.selected || records[0],'tiny') : '—'}</td><td>${type}</td><td>${escapeHTML(title + suffix)}<br><span class="muted">${format}</span></td><td>${item.source}</td><td>${item.pages}</td><td>~${item.size.toFixed(1)} MB</td><td><span class="status-pill${state.excluded.has(item.id) ? ' unavailable' : ''}">${state.excluded.has(item.id) ? 'Excluded' : 'Ready'}</span></td></tr>`;
    }).join('');
    $('#outputs-empty').hidden = items.length > 0;
    updateOutputTotals();
  }
  function updateOutputTotals() {
    const included = outputItems().filter(item => !state.excluded.has(item.id));
    $('#output-totals').textContent = `${included.length} book${included.length === 1 ? '' : 's'} · ${included.reduce((sum,item) => sum+item.pages,0)} pages · ~${included.reduce((sum,item) => sum+item.size,0).toFixed(1)} MB`;
    const layout = $('input[name="layout"]:checked').value === 'portrait' ? 'Portrait pages' : 'Landscape paired pages';
    $('#output-context').textContent = `${layout} · ${state.mode === 'import' ? 'Imported books' : $('#language').value} · ${$('#output-format').value}`;
    $('#process').disabled = included.length === 0;
    $('#output-demo-note').textContent = included.length ? `${state.selected ? 'Example output plan' : 'Sample content for stage review'} · Page counts and sizes are illustrative, independent of layout settings.` : 'Select at least one output to enable the process demonstration.';
  }

  // Navigation never invokes preparation, import, processing, or production code.
  $$('[data-stage]').forEach(button => button.addEventListener('click',() => stageTo(Number(button.dataset.stage))));
  $('#back').addEventListener('click',() => stageTo(state.stage-1));
  $('#next').addEventListener('click',() => stageTo(state.stage+1));
  $$('[data-mode]').forEach(button => button.addEventListener('click',() => chooseMode(button.dataset.mode)));
  for (const selector of ['#search-results','#recommendation-list']) $(selector).addEventListener('click',event => { const button = event.target.closest('[data-record]'); if (button) selectRecord(button.dataset.record); });
  $('#search-form').addEventListener('submit',event => {
    event.preventDefault();
    if (!state.mode) { notice('Choose Volumes or Chapters before searching.'); $('[data-mode="volumes"]').focus(); return; }
    state.query = $('#search-query').value.trim();
    state.results = records.filter(record => `${record.title} ${record.author}`.toLowerCase().includes(state.query.toLowerCase()));
    renderResults();
    $('#search-note').textContent = state.query ? `Examples matching “${state.query}” · Fictional titles and metadata.` : 'All fictional examples · No provider requests.';
    notice(`${state.results.length} demo results. Select a record to continue.`);
  });
  $('#direct-form').addEventListener('submit',event => {
    event.preventDefault();
    if (!state.mode) { notice('Choose Volumes or Chapters before loading the URL demo.'); return; }
    let supported = false;
    try { const url = new URL($('#direct-url').value); supported = ['http:','https:'].includes(url.protocol) && ['mangadex.org','www.mangadex.org'].includes(url.hostname) && url.pathname.startsWith('/title/'); } catch { /* Inline feedback below. */ }
    if (!supported) { notice('Enter a MangaDex title URL to demonstrate direct loading.'); return; }
    state.results = [records[0]]; selectRecord(records[0].id);
    $('#search-note').textContent = 'Direct URL demonstration · Substituted the fictional Atlas record.';
    notice('URL demo loaded the Atlas example. The URL was not contacted.');
  });
  $('#sort').addEventListener('change',renderResults);
  $('#prefer-colored').addEventListener('change',renderResults);
  $('#language').addEventListener('change',() => {  renderSelection(); notice(`${$('#language').value} selected. Demo inventory is illustrative.`); });
  $('#find-manga').addEventListener('click',() => { if (state.mode === 'import') $('#load-import').focus(); else $('#search-query').focus(); });
  $('#load-import').addEventListener('click',loadImports);
  $('#inventory-list').addEventListener('change',event => {
    const id = event.target.dataset.inventory; if (!id) return;
    if (event.target.checked) state.chosen.add(id); else state.chosen.delete(id);
     updateSelectionCount();
    notice(`${state.chosen.size} example item${state.chosen.size === 1 ? '' : 's'} selected.`);
  });
  for (const [id,all] of [['select-all',true],['clear-selection',false]]) $(`#${id}`).addEventListener('click',() => { state.chosen = new Set(all ? state.inventory.map(item => item.id) : []);  renderSelection(); notice(`${state.chosen.size} example items selected.`); });
  $('#adjustment-sliders').innerHTML = sliderDefinitions.map(([id,label,min,max,value,step]) => `<div class="setting-row"><label for="${id}">${label}</label><div class="slider-control"><input id="${id}" class="slider" type="range" min="${min}" max="${max}" value="${value}" step="${step}"><output for="${id}"></output></div></div>`).join('');
  $$('.slider').forEach(input => { syncSlider(input); input.addEventListener('input',() => { syncSlider(input); markSettingsChanged(); }); });
  $$('[data-gray]').forEach(button => button.addEventListener('click',() => { setGray(button.dataset.gray); markSettingsChanged(); }));
  $('#dithering').addEventListener('change',() => { syncDither(); markSettingsChanged(); });
  $('#output-depth').addEventListener('change',markSettingsChanged);
  $('#preset').addEventListener('change',() => { if ($('#preset').value !== 'Custom') applyPreset($('#preset').value); });
  $('#save-preset').addEventListener('click',() => {
    showDialog('Save Preset','<p class="muted">Keep these settings for this demo session.</p><label class="stacked-field">Preset name<input id="preset-name" class="line-input" value="My reading preset" maxlength="50"></label><button id="confirm-preset" class="button primary" type="button">Save for this session</button><p id="preset-error" role="status" class="small muted"></p>');
    $('#confirm-preset').addEventListener('click',() => {
      const name = $('#preset-name').value.trim();
      if (!name || ['Original','Manga B&W','Crisp eInk','Custom'].includes(name)) { $('#preset-error').textContent = 'Enter a unique name for your preset.'; return; }
      if (!state.savedPresets.has(name)) $('#preset').add(new Option(name,name));
      state.savedPresets.set(name,settingsSnapshot()); $('#preset').value = name; $('#demo-dialog').close(); notice(`Preset “${name}” saved for this session only.`);
    });
  });
  $('#manage-presets').addEventListener('click',() => {
    showDialog('Manage Presets',`<p class="muted">Session presets disappear when this page is reloaded.</p>${state.savedPresets.size ? [...state.savedPresets.keys()].map(name => `<div class="row-between"><span>${escapeHTML(name)}</span><button type="button" class="button secondary compact" data-remove-preset="${escapeHTML(name)}">Remove</button></div>`).join('') : '<p>No session presets saved yet.</p>'}`);
    $$('[data-remove-preset]').forEach(button => button.addEventListener('click',() => {
      const name = button.dataset.removePreset; state.savedPresets.delete(name);
      if ($('#preset').value === name) $('#preset').value = 'Custom';
      [...$('#preset').options].find(option => option.value === name)?.remove();
      button.parentElement.remove(); notice(`Session preset “${name}” removed.`);
    }));
  });
  $$('input[name="layout"]').forEach(input => input.addEventListener('change',() => {  $('#preview-status').textContent = 'Layout changed · Refresh Preview'; }));
  $('#reading-direction').addEventListener('change',() => {  $('#preview-status').textContent = 'Direction changed · Refresh Preview'; });
  $('#ereader').addEventListener('change',() => { $('#preview-helper').textContent = `${$('#ereader').value} selected · This prototype does not simulate the display.`; });
  $('#refresh-preview').addEventListener('click',() => { renderPreview(); notice('Static preview refreshed. No images processed or downloaded.'); });
  for (const id of ['book-title','book-series','book-author']) $(`#${id}`).addEventListener('input',() => { $('#metadata-status').textContent = 'Edits pending · Apply Metadata'; });
  $('#apply-metadata').addEventListener('click',() => {
    state.metadata = {title:$('#book-title').value, series:$('#book-series').value, author:$('#book-author').value};
    $('#metadata-status').textContent = 'Metadata applied to demo'; renderOutputs(); notice('Metadata applied to example outputs.');
  });
  for (const id of ['output-format','use-cover','zero-pad','cover-mode']) $(`#${id}`).addEventListener('change',renderOutputs);
  $('#output-rows').addEventListener('change',event => {
    const id = event.target.dataset.output; if (!id) return;
    if (event.target.checked) state.excluded.delete(id); else state.excluded.add(id);
    const pill = event.target.closest('tr').querySelector('.status-pill');
    pill.textContent = event.target.checked ? 'Ready' : 'Excluded'; pill.classList.toggle('unavailable',!event.target.checked);
    updateOutputTotals();
  });
  $('#preview-cover').addEventListener('click',() => { showDialog('Preview Cover',`<div class="selected-summary">${cover(state.selected || records[0],'large')}<div><h3>${escapeHTML(state.metadata.title)}</h3><p>${escapeHTML($('#cover-mode').value)}</p><p class="small muted">Static cover placeholder. No cover generation or stamping is performed.</p></div></div>`); });
  $('#process').addEventListener('click',() => { notice('Demo complete. No books were processed or added to Calibre.'); showDialog('Demo complete','<p>You’ve reached the end of the three-stage flow.</p><p class="muted">No files were created and Calibre was not opened. Go Back to keep exploring your settings.</p>'); });
  $('#toggle-log').addEventListener('click',() => { const opened = $('#activity-panel').hidden; $('#activity-panel').hidden = !opened; $('#toggle-log').setAttribute('aria-expanded',opened); });
  $$('[data-notice]').forEach(button => button.addEventListener('click',() => {
    const kind = button.dataset.notice;
    const messages = {
      preferences:['Preferences','Persistent defaults will remain in Preferences. This prototype keeps all settings in memory for the current session.'],
      sources:['Manga Sources','MangaDex, MangaPill, and WeebCentral appear as source labels on fictional records. Provider configuration and connections are outside this visual demo.'],
      about:['MangaAnkā','From jgog. Judgement visual prototype · Three stages, one reading workflow.'],
      destination:['Destination','The displayed destination is the development Test-Library. A real folder picker is outside this demo; nothing is read or written.']
    };
    if (kind === 'copy-log' || kind === 'save-log') {
      showDialog(kind === 'copy-log' ? 'Copy Log · demo' : 'Save Log · demo',`<p class="muted">Selectable log preview. This demonstration does not copy to the clipboard or save a file.</p><textarea class="line-input" aria-label="Demo log text" readonly>${escapeHTML(state.logs.join('\n'))}</textarea>`);
    } else { const [title,message] = messages[kind]; showDialog(title,`<p>${message}</p>`); }
  }));
  renderTrending(); renderResults(); renderPreview(); renderOutputs();
})();
