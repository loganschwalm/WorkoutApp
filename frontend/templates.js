// Workout templates: the built-in ones and the account's own, the Templates card on the Tracker, and the editor for
// making and changing one, supersets included.

let customTemplates = loadCustomTemplates();
let editingTemplateId = null;
let templateDraftExercises = [];
// [name, reps] for each exercise, or [name, seconds, 'timed'] for a hold.
const templates = [
  ['Push Day', [['Bench Press', 8], ['Overhead Press', 8], ['Tricep Pushdown', 12]]],
  ['Pull Day', [['Deadlift', 5], ['Barbell Row', 8], ['Lat Pulldown', 10], ['Bicep Curl', 12]]],
  ['Leg Day', [['Back Squat', 8], ['Romanian Deadlift', 10], ['Leg Press', 10], ['Calf Raise', 15]]],
  ['Upper Body', [['Bench Press', 8], ['Pull-up', 8], ['Dumbbell Row', 10], ['Lateral Raise', 12]]],
  ['Full Body', [['Goblet Squat', 10], ['Push-up', 10], ['Dumbbell Row', 10], ['Plank', 30, 'timed']]]
].map(([name, exercises]) => ({
  name, exercises:exercises.map(([exercise, reps, timed]) => ({ name:exercise, weight:'', reps:String(reps), ...(timed ? { timed:true } : {}) }))
}));

// Kept per account by offline.js, which uploads a change as soon as the server can be reached.
function loadCustomTemplates() {
  const stored = readLocalState('templates');
  return stored && Array.isArray(stored.value) ? stored.value : [];
}

function saveCustomTemplates() {
  saveLocalState('templates', customTemplates);
}

function getAllTemplates() {
  return [...templates.map((template, index) => ({ ...template, id:`built-in-${index}`, builtIn:true })),
    ...customTemplates.map(template => ({ ...template, builtIn:false }))];
}

// Templates fold away once there is something else to start from (saved workouts or a program), so someone new sees
// them straight away and everyone else sees their own workouts first. The Show/Hide button's choice holds while the
// page is open. Until the first load says whether there is anything, they stay folded, so they never jump away.
let templatesChoice = null;

function syncTemplateArea() {
  const hasOwn = savedWorkouts.length > 0 || Object.keys(lastPerformance).length > 0 || Boolean(currentProgram);
  const open = templatesChoice ?? (!hasOwn && initialLoadDone);
  $('templateArea').hidden = !open;
  $('templatesToggle').textContent = open ? 'Hide templates' : `Show templates (${programDefinitions.length + getAllTemplates().length})`;
  $('templatesToggle').setAttribute('aria-expanded', String(open));
}

// Training programs (program.js) come first, then the single-workout templates. program.js calls this when the program
// changes, which also changes what Start again offers and whether the templates stay folded.
function renderTemplates() {
  const action = (template, kind, style, label) =>
    `<button class="${style}" type="button" data-template-action="${kind}" data-template-id="${escapeHTML(template.id)}">${label}</button>`;
  $('templateList').innerHTML = programTemplateCards() + getAllTemplates().map(template => '<article class="template-card">'
    + `<div><h3>${escapeHTML(template.name)}</h3>`
    + `<p>${template.exercises.map(item => `${escapeHTML(item.name)} (${escapeHTML(describeTemplateTarget(item))})`).join(' &middot; ')}</p></div>`
    + `<div class="template-actions">${action(template, 'start', 'primary', 'Start workout')}${action(template, 'duplicate', 'secondary', 'Duplicate')}`
    + `${template.builtIn ? '' : action(template, 'edit', 'secondary', 'Edit') + action(template, 'delete', 'danger', 'Delete')}</div></article>`).join('');
  renderRecentWorkouts();
  syncTemplateArea();
  renderExerciseSuggestions();
}

// Each exercise of a template: its name, whether it is timed and the buttons to move or remove it, then how many sets
// (blank for as many as you like), its reps (or seconds) and the top of a rep range (blank for none), and an optional
// rest after each set (blank for the default in Settings).
function renderTemplateExerciseEditor() {
  const rowAction = (index, kind, style, label, symbol) =>
    `<button class="${style}" type="button" data-template-row-action="${kind}" data-index="${index}" aria-label="${label}">${symbol}</button>`;
  const number = (index, id, label, field, value, attributes, wrapper = '') => `<div${wrapper}><label for="${id}${index}" id="${id}${index}Label">${label}</label>`
    + `<input id="${id}${index}" type="number" inputmode="numeric" ${attributes} value="${escapeHTML(value ?? '')}" data-template-field="${field}" data-index="${index}" /></div>`;
  $('templateExerciseEditor').innerHTML = templateDraftExercises.map((exercise, index) => '<div class="template-exercise-row">'
    + `<div class="template-exercise-name"><label for="templateExercise${index}">Exercise</label>`
    + `<input id="templateExercise${index}" type="text" list="exerciseNames" autocomplete="off" value="${escapeHTML(exercise.name)}"`
    + ` data-template-field="name" data-index="${index}" required /></div>`
    + '<label class="setting-check template-timed">'
    + `<input type="checkbox" data-template-field="timed" data-index="${index}"${exercise.timed ? ' checked' : ''} /> Timed</label>`
    + `<div class="template-row-actions">${rowAction(index, 'up', 'secondary', 'Move exercise up', '&#8593;')}`
    + rowAction(index, 'down', 'secondary', 'Move exercise down', '&#8595;')
    + rowAction(index, 'remove', 'danger', 'Remove exercise', '&times;') + '</div>'
    + number(index, 'templateSets', 'Sets', 'setCount', exercise.setCount, 'min="1" max="20" step="1" placeholder="Any"')
    + number(index, 'templateReps', exercise.timed ? 'Seconds' : 'Reps', 'reps', exercise.reps, 'min="1" required')
    + number(index, 'templateRepsMax', 'Up to', 'repsMax', exercise.repsMax, 'min="2" max="100" step="1" placeholder="—"',
      ` class="template-reps-max"${exercise.timed ? ' hidden' : ''}`)
    + number(index, 'templateRest', 'Rest (s)', 'rest', exercise.rest || '', `min="15" max="600" step="1" placeholder="${getWorkoutSettings().restDuration}"`)
    + (index < templateDraftExercises.length - 1 ? '<label class="setting-check template-superset">'
      + `<input type="checkbox" data-template-field="superset" data-index="${index}"${exercise.superset ? ' checked' : ''} />`
      + ' Superset with the next exercise</label>' : '')
    + '</div>').join('');
}

// What a template keeps of an exercise: its name and reps, and its sets, rep range, rest, timing and superset when it
// has them. A template exercise with sets is planned set by set when a workout starts (see templateSession).
function templateExercise(item) {
  return {
    name:item.name, reps:item.reps,
    ...(item.setCount ? { setCount:item.setCount } : {}), ...(item.repsMax && !isTimed(item) ? { repsMax:item.repsMax } : {}),
    ...(item.rest ? { rest:item.rest } : {}), ...(isTimed(item) ? { timed:true } : {}), ...(item.group ? { group:item.group } : {})
  };
}

// "3 × 8–12 reps", "3 × 5 reps", "30 s", "8 reps": how a template card and the editor's summary write an exercise.
function describeTemplateTarget(item) {
  const count = isTimed(item) ? `${item.reps} s` : `${item.reps}${item.repsMax ? `–${item.repsMax}` : ''} reps`;
  return item.setCount ? `${item.setCount} × ${count}` : count;
}

// A template's exercises with the editor's "Superset with the next" ticks turned into groups: each run of exercises
// joined that way shares one group, which is how a workout knows its supersets.
function withSupersetGroups(drafts) {
  let group = null, count = 0;
  return drafts.map((item, index) => {
    const { superset, group:old, ...exercise } = item;
    const joinsNext = Boolean(superset) && index < drafts.length - 1;
    const joinedByPrevious = index > 0 && Boolean(drafts[index - 1].superset);
    if (!joinsNext && !joinedByPrevious) return exercise;
    if (!joinedByPrevious) group = `s${++count}`;
    return { ...exercise, group };
  });
}

function openTemplateEditor(template = null) {
  rememberOpener('template');
  editingTemplateId = template?.id || null;
  $('templateModalTitle').textContent = template ? 'Edit template' : 'Create template';
  $('templateName').value = template?.name || '';
  templateDraftExercises = template
    ? template.exercises.map((item, index, all) => ({ ...templateExercise(item), superset:Boolean(item.group) && all[index + 1]?.group === item.group }))
    : [{ name:'', reps:'8' }];
  renderTemplateExerciseEditor();
  $('templateModal').hidden = false;
  $('templateName').focus();
}

function closeTemplateEditor() {
  $('templateModal').hidden = true;
  editingTemplateId = null;
  returnFocus('template');
}

$('templateList').onclick = e => {
  const action = e.target.dataset.templateAction;
  const templateId = e.target.dataset.templateId;
  if (!action || !templateId) return;
  const template = getAllTemplates().find(item => item.id === templateId);
  if (!template) return;
  if (action === 'start') startWorkout(template);
  if (action === 'edit') openTemplateEditor(template);
  if (action === 'duplicate') {
    customTemplates.push({ id:`custom-${Date.now()}`, name:`${template.name} Copy`, exercises:template.exercises.map(templateExercise) });
    saveCustomTemplates();
    renderTemplates();
    showFeedback(`Created a copy of “${template.name}”.`, 'success');
  }
  if (action === 'delete' && confirm(`Delete template “${template.name}”?`)) {
    customTemplates = customTemplates.filter(item => item.id !== template.id);
    saveCustomTemplates();
    renderTemplates();
  }
};
$('templateExerciseEditor').oninput = e => {
  const index = Number(e.target.dataset.index);
  const field = e.target.dataset.templateField;
  if (!field || !templateDraftExercises[index]) return;
  if (field === 'superset') { templateDraftExercises[index].superset = e.target.checked; return; }
  if (field !== 'timed') { templateDraftExercises[index][field] = e.target.value; return; }
  // A timed exercise's count is in seconds, which its label says, and it is held for them rather than done in a range.
  templateDraftExercises[index].timed = e.target.checked;
  $(`templateReps${index}Label`).textContent = e.target.checked ? 'Seconds' : 'Reps';
  $(`templateRepsMax${index}`).closest('.template-reps-max').hidden = e.target.checked;
};
$('templateExerciseEditor').onclick = e => {
  const action = e.target.dataset.templateRowAction;
  const index = Number(e.target.dataset.index);
  if (!action || !templateDraftExercises[index]) return;
  if (action === 'remove' && templateDraftExercises.length > 1) templateDraftExercises.splice(index, 1);
  const drafts = templateDraftExercises;
  if (action === 'up' && index > 0) [drafts[index - 1], drafts[index]] = [drafts[index], drafts[index - 1]];
  if (action === 'down' && index < drafts.length - 1) [drafts[index + 1], drafts[index]] = [drafts[index], drafts[index + 1]];
  renderTemplateExerciseEditor();
};
$('addTemplateExercise').onclick = () => { templateDraftExercises.push({ name:'', reps:'8' }); renderTemplateExerciseEditor(); };
$('createTemplateBtn').onclick = () => openTemplateEditor();
$('closeTemplate').onclick = closeTemplateEditor;
$('cancelTemplate').onclick = closeTemplateEditor;
$('templateModal').onclick = event => { if (event.target === $('templateModal')) closeTemplateEditor(); };
$('templateForm').onsubmit = event => {
  event.preventDefault();
  const name = $('templateName').value.trim();
  // A rest left blank uses the default in Settings; one given is kept within the range Settings allows.
  const restOf = value => value === '' || value === undefined || !(Number(value) > 0) ? null : Math.min(600, Math.max(15, Math.round(Number(value))));
  // Sets left blank mean as many as you like; given, 1 to 20. The top of a rep range, when given, is above its bottom.
  const setsOf = value => Number(value) >= 1 ? Math.min(20, Math.floor(Number(value))) : null;
  const topOf = (value, reps) => Number(value) > reps ? Math.min(100, Math.floor(Number(value))) : null;
  const kept = templateDraftExercises.filter(item => item.name.trim() && Number(item.reps) >= 1);
  const upsideDown = kept.find(item => !item.timed && String(item.repsMax ?? '') !== '' && !topOf(item.repsMax, Math.floor(Number(item.reps))));
  if (upsideDown) return showFeedback(`A rep range goes up: ${upsideDown.name.trim()} is ${Math.floor(Number(upsideDown.reps))} up to ${upsideDown.repsMax}.`);
  const validExercises = withSupersetGroups(kept.map(item => {
    const reps = Math.floor(Number(item.reps));
    return {
      ...templateExercise({ name:item.name.trim(), reps:String(reps), setCount:setsOf(item.setCount), repsMax:item.timed ? null : topOf(item.repsMax, reps),
        rest:restOf(item.rest), timed:item.timed === true }),
      superset:item.superset
    };
  }));
  if (!name || !validExercises.length) return showFeedback('Add a template name and at least one valid exercise.');
  if (editingTemplateId) {
    const existing = customTemplates.find(item => item.id === editingTemplateId);
    if (existing) { existing.name = name; existing.exercises = validExercises; }
  } else customTemplates.push({ id:`custom-${Date.now()}`, name, exercises:validExercises });
  saveCustomTemplates();
  renderTemplates();
  closeTemplateEditor();
  showFeedback(`Template “${name}” saved.`, 'success');
};

$('templatesToggle').onclick = () => {
  templatesChoice = $('templateArea').hidden;
  syncTemplateArea();
};
