// Your own program: the editor that builds one, a name and up to seven days, each named and done from a template, and
// changes it. What a built program is, and how its days become workouts, is customProgram in program-definitions.js;
// program.js shows and runs it like any other. Loaded after templates.js, whose templates the days are.

// The days being edited, [{ name, template }], and whether it is the program being followed that is changed.
let builderDraft = null;

// A new program starts from your own templates, in the order you made them; with none, push, pull and legs.
function defaultBuilderDays() {
  const own = getAllTemplates().filter(template => !template.builtIn).slice(0, customProgramDayLimit);
  const templates = own.length ? own : getAllTemplates().slice(0, 3);
  return templates.map(template => ({ name:'', template:template.id }));
}

function renderBuilderDays() {
  const templates = getAllTemplates();
  const { days } = builderDraft;
  const rowAction = (index, kind, style, label, symbol, disabled) =>
    `<button class="${style}" type="button" data-builder-action="${kind}" data-index="${index}" aria-label="${label}"${disabled ? ' disabled' : ''}>${symbol}</button>`;
  $('builderDays').innerHTML = days.map((day, index) => {
    const template = templates.find(item => item.id === day.template);
    // A day whose template has since been deleted asks for another.
    const option = item => `<option value="${escapeHTML(item.id)}"${item.id === day.template ? ' selected' : ''}>${escapeHTML(item.name)}</option>`;
    const group = (label, items) => items.length ? `<optgroup label="${label}">${items.map(option).join('')}</optgroup>` : '';
    const options = (template ? '' : '<option value="" selected>Choose a template</option>')
      + group('Your templates', templates.filter(item => !item.builtIn)) + group('Built-in', templates.filter(item => item.builtIn));
    return `<li class="builder-day"><div><label for="builderDayName${index}">Day ${index + 1}</label>`
      + `<input id="builderDayName${index}" type="text" maxlength="60" autocomplete="off" value="${escapeHTML(day.name)}" placeholder="${escapeHTML(template ? template.name : 'Name')}" data-builder-field="name" data-index="${index}" />`
        + `</div>`
      + `<div><label for="builderDayTemplate${index}">Template</label><select id="builderDayTemplate${index}" data-builder-field="template" data-index="${index}">${options}</select></div>`
      + `<div class="template-row-actions">${rowAction(index, 'up', 'secondary', `Move day ${index + 1} up`, '&#8593;', index === 0)}`
      + rowAction(index, 'down', 'secondary', `Move day ${index + 1} down`, '&#8595;', index === days.length - 1)
      + rowAction(index, 'remove', 'danger', `Remove day ${index + 1}`, '&times;', days.length === 1) + '</div></li>';
  }).join('');
  $('builderAddDay').disabled = days.length >= customProgramDayLimit;
}

function showBuilderError(message, element) {
  $('builderError').textContent = message;
  $('builderError').hidden = false;
  if (element) element.focus();
}

// Building a program while following another replaces it, as setting up one of the others does.
function openProgramBuilder(program = null) {
  const editing = Boolean(program);
  const replacing = !editing && Boolean(currentProgram);
  rememberOpener('builder');
  builderDraft = { editing, days:editing ? program.days.map(day => ({ ...day })) : defaultBuilderDays() };
  $('builderModalTitle').textContent = editing ? `Edit ${program.name}` : 'Build your program';
  $('builderName').value = editing ? program.name : '';
  $('builderIntro').textContent = [editing
    ? 'Change, add or reorder the days. A day done this week stays done while it keeps its place and template.'
    : 'Name your program and choose its days, in the order you train them. Each day is one of your templates, so changing the template changes the day. A template exercise with sets and a rep range goes up on its own once every set reaches the top; Create template makes one.',
  replacing ? `This replaces ${programDefinition(currentProgram).name}, which you are following now; its finished workouts stay in your history.` : ''].filter(Boolean).join(' ');
  $('builderSubmit').textContent = editing ? 'Save changes' : replacing ? 'Switch program' : 'Start program';
  $('builderError').hidden = true;
  renderBuilderDays();
  $('builderModal').hidden = false;
  $('builderName').focus();
}

function closeProgramBuilder() {
  $('builderModal').hidden = true;
  builderDraft = null;
  returnFocus('builder');
}

$('builderDays').addEventListener('input', event => {
  const index = Number(event.target.dataset.index), field = event.target.dataset.builderField;
  const day = builderDraft && builderDraft.days[index];
  if (!day || !field) return;
  day[field] = event.target.value;
  // A day left unnamed takes its template's name, which its box shows meanwhile.
  if (field === 'template') $(`builderDayName${index}`).placeholder = getAllTemplates().find(item => item.id === day.template)?.name || 'Name';
});

$('builderDays').addEventListener('click', event => {
  const button = event.target.closest('[data-builder-action]');
  if (!button || !builderDraft) return;
  const days = builderDraft.days, index = Number(button.dataset.index), action = button.dataset.builderAction;
  if (action === 'remove' && days.length > 1) days.splice(index, 1);
  if (action === 'up' && index > 0) [days[index - 1], days[index]] = [days[index], days[index - 1]];
  if (action === 'down' && index < days.length - 1) [days[index + 1], days[index]] = [days[index], days[index + 1]];
  renderBuilderDays();
  // The keyboard carries on from the same button where it is still there, and from the day after a removed one.
  const focus = action === 'up' ? index - 1 : action === 'down' ? index + 1 : Math.min(index, days.length - 1);
  ($(`builderDays`).querySelector(`[data-builder-action="${action}"][data-index="${focus}"]:not(:disabled)`) || $(`builderDayName${focus}`))?.focus();
});

// A new day does the next template not used yet, or else the first.
$('builderAddDay').onclick = () => {
  if (!builderDraft || builderDraft.days.length >= customProgramDayLimit) return;
  const templates = getAllTemplates();
  const unused = templates.find(template => !builderDraft.days.some(day => day.template === template.id)) || templates[0];
  builderDraft.days.push({ name:'', template:unused.id });
  renderBuilderDays();
  $(`builderDayName${builderDraft.days.length - 1}`).focus();
};

$('builderForm').onsubmit = event => {
  event.preventDefault();
  const name = $('builderName').value.trim();
  if (!name) return showBuilderError('Give your program a name.', $('builderName'));
  const templates = getAllTemplates();
  const missing = builderDraft.days.findIndex(day => !templates.some(template => template.id === day.template));
  if (missing !== -1) return showBuilderError(`Choose a template for day ${missing + 1}.`, $(`builderDayTemplate${missing}`));
  const days = builderDraft.days.map(day => ({ name:day.name.trim() || templates.find(template => template.id === day.template).name, template:day.template }));
  const editing = builderDraft.editing && currentProgram && programDefinition(currentProgram).custom;
  // A day already done this week stays done if it is still in its place with its template; anything moved starts again.
  const done = editing ? Object.fromEntries(Object.entries(currentProgram.done).filter(([key]) => {
    const day = Number(key.split('-')[1]);
    return Boolean(days[day]) && currentProgram.days[day]?.template === days[day].template;
  })) : {};
  const base = editing ? currentProgram : { definition:'custom', unit:weightUnit(), startedAt:Date.now(), cycle:1, lastRollover:null };
  const settled = settleProgram(normalizeProgram({ ...base, trainingMaxes:{}, stalls:{}, options:{}, done, name, days }));
  saveProgram(settled.program);
  closeProgramBuilder();
  if (settled.rolledOver) showFeedback(nextUpMessage(settled.program, true), 'success');
  else showFeedback(editing ? `${name} updated. ${nextUpMessage(settled.program, false)}` : `${name} is set up. ${nextUpMessage(settled.program, false)}`, 'success');
  $('programCard').scrollIntoView({ behavior:'smooth', block:'start' });
};

$('closeBuilder').onclick = closeProgramBuilder;
$('cancelBuilder').onclick = closeProgramBuilder;
$('builderModal').onclick = event => { if (event.target === $('builderModal')) closeProgramBuilder(); };
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('builderModal').hidden) closeProgramBuilder(); });
