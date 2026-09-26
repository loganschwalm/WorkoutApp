// Training programs: a whole plan of workouts, with one number per lift (a training max or a working weight) that the
// program moves as the lifter progresses. This file is what every program shares; program-definitions.js says what
// each program is. The program being followed is kept per account beside settings and templates (offline.js saves it
// on this device first and uploads it). Loaded before script.js, whose startWorkout begins the program's workouts.
let currentProgram = loadProgram();
let programForm = null;

function findProgramDefinition(id) {
  return programDefinitions.find(definition => definition.id === id) || null;
}

function programDefinition(program) {
  return findProgramDefinition(program.definition);
}

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function positiveWeight(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 && number < 10000 ? number : null;
}

function storedNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : 0;
}

// Never below one step, so a tiny training max cannot round down to nothing.
function roundToStep(value, step) {
  // The outer rounding clears float noise such as 142.49999999 from multiplying by 2.5.
  return Math.max(step, Math.round(Math.round(value / step) * step * 100) / 100);
}

// Epley's formula, the usual way to read a one-rep max off a set of several reps.
function estimateOneRepMax(weight, reps) {
  return Math.round(reps <= 1 ? weight : weight * (1 + reps / 30));
}

// A select's choices and default in a unit. A program can offer weights per unit: choices as a function of the unit,
// and a default of { lbs, kg }.
function optionChoices(option, unit) {
  return typeof option.choices === 'function' ? option.choices(unit) : option.choices;
}

function optionDefault(option, unit) {
  return option.default !== null && typeof option.default === 'object' ? option.default[unit] : option.default;
}

// Each option's stored value, or its default: a check's own default, a select's default choice or else its first.
function normalizeOptions(definition, given, unit) {
  return Object.fromEntries(definition.options.map(option => {
    if (option.type === 'check') return [option.id, typeof given[option.id] === 'boolean' ? given[option.id] : option.default];
    const choices = optionChoices(option, unit);
    const choice = choices.find(item => String(item.value) === String(given[option.id]))
      || choices.find(item => item.value === optionDefault(option, unit));
    return [option.id, (choice || choices[0]).value];
  }));
}

// A stored program is used only if it is whole: anything unreadable counts as no program rather than breaking the page.
function normalizeProgram(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const definition = findProgramDefinition(value.definition);
  if (!definition) return null;
  const maxes = value.trainingMaxes && typeof value.trainingMaxes === 'object' ? value.trainingMaxes : {};
  const trainingMaxes = {};
  for (const lift of definition.lifts) {
    trainingMaxes[lift.key] = positiveWeight(maxes[lift.key]);
    if (trainingMaxes[lift.key] === null) return null;
  }
  // Missed sessions in a row, per lift, for programs that deload after repeated misses.
  const stalls = {};
  definition.lifts.forEach(lift => { const misses = Math.floor(storedNumber(value.stalls?.[lift.key])); if (misses) stalls[lift.key] = misses; });
  const done = {};
  Object.entries(value.done && typeof value.done === 'object' ? value.done : {}).forEach(([key, entry]) => {
    if (!/^\d+-\d+$/.test(key) || !entry || typeof entry !== 'object') return;
    const amrap = entry.amrap && typeof entry.amrap === 'object' ? { weight:storedNumber(entry.amrap.weight), reps:storedNumber(entry.amrap.reps), target:storedNumber(entry.amrap.target) } : null;
    done[key] = { at:storedNumber(entry.at), skipped:entry.skipped === true, amrap, hit:typeof entry.hit === 'boolean' ? entry.hit : null };
  });
  const rollover = value.lastRollover && typeof value.lastRollover === 'object' && Array.isArray(value.lastRollover.changes) ? {
    cycle:storedNumber(value.lastRollover.cycle),
    changes:value.lastRollover.changes.filter(change => change && definition.lifts.some(lift => lift.key === change.lift)).map(change => ({ lift:change.lift, from:storedNumber(change.from), to:storedNumber(change.to), reset:change.reset === true }))
  } : null;
  // The unit its numbers are in; programs from before kilograms existed are in pounds.
  const unit = recordUnit(value);
  const options = normalizeOptions(definition, value.options && typeof value.options === 'object' ? value.options : {}, unit);
  return { definition:definition.id, unit, startedAt:storedNumber(value.startedAt), cycle:Math.max(1, Math.floor(storedNumber(value.cycle))), trainingMaxes, stalls, options, done, lastRollover:rollover };
}

// The same program in the other unit, for when Settings change it. Its numbers are converted and rounded to steps the
// program uses in that unit (definition.roundNumber); an option that is a weight (rounding, the heaviest dumbbells)
// moves to the nearest choice in the new unit; anything else (a percentage) stays. Results already recorded convert too.
function programInUnit(program, to) {
  if (!program || program.unit === to) return program;
  const definition = programDefinition(program);
  const convert = value => convertWeight(value, program.unit, to);
  const options = Object.fromEntries(definition.options.map(option => {
    const value = program.options[option.id];
    if (!option.weight) return [option.id, value];
    const target = convert(value);
    const nearest = optionChoices(option, to).reduce((best, choice) => Math.abs(choice.value - target) < Math.abs(best.value - target) ? choice : best);
    return [option.id, nearest.value];
  }));
  const converted = { ...program, unit:to, options };
  const round = (lift, value) => definition.roundNumber ? definition.roundNumber(converted, lift, value) : Math.round(value * 2) / 2;
  converted.trainingMaxes = Object.fromEntries(definition.lifts.map(lift => [lift.key, round(lift, convert(program.trainingMaxes[lift.key]))]));
  converted.done = Object.fromEntries(Object.entries(program.done).map(([key, entry]) => [key, entry.amrap ? { ...entry, amrap:{ ...entry.amrap, weight:convert(entry.amrap.weight) } } : entry]));
  if (program.lastRollover) converted.lastRollover = { ...program.lastRollover, changes:program.lastRollover.changes.map(change => ({ ...change, from:convert(change.from), to:convert(change.to) })) };
  return converted;
}

function loadProgram() {
  const stored = readLocalState('program');
  return normalizeProgram(stored ? stored.value : null);
}

function saveProgram(program) {
  currentProgram = program;
  saveLocalState('program', program);
  renderProgram();
  renderTemplates();
}

// Called once the server's copy has loaded, which may be newer than the one this page started with.
function reloadProgram() {
  const loaded = loadProgram();
  const inShownUnit = programInUnit(loaded, weightUnit());
  const settled = settleProgram(inShownUnit);
  if (settled.rolledOver || inShownUnit !== loaded) saveProgram(settled.program);
  else {
    currentProgram = settled.program;
    renderProgram();
  }
}

// ---- The plan -------------------------------------------------------------

function programWeeks(program) {
  return programDefinition(program).weeks(program);
}

function programDays(program) {
  return programDefinition(program).days(program);
}

function dayKey(week, day) {
  return `${week}-${day}`;
}

// "Deadlift Day, week 1" in a program of several weeks a block; just the day's name when a block is one week.
function dayLabel(program, week, day) {
  const name = programDays(program)[day].name;
  return programWeeks(program).length > 1 ? `${name}, week ${week + 1}` : name;
}

// Where a workout sits in the program, as History shows it: "Cycle 1, week 2 · 3s week", or "Week 3".
function blockLabel(program, week) {
  const weeks = programWeeks(program);
  const block = `${capitalize(programDefinition(program).block)} ${program.cycle}`;
  return weeks.length > 1 ? `${block}, week ${week + 1} · ${weeks[week].name}` : block;
}

function nextProgramDay(program) {
  const weeks = programWeeks(program), days = programDays(program);
  for (let week = 0; week < weeks.length; week += 1) {
    for (let day = 0; day < days.length; day += 1) if (!program.done[dayKey(week, day)]) return { week, day };
  }
  return null;
}

function doneInWeek(program, week) {
  return programDays(program).filter((entry, day) => program.done[dayKey(week, day)]).length;
}

// One day of the current block, in the shape startWorkout takes. programDay says which day of which run of the
// program it is, so finishing the workout can mark that day done.
function programWorkout(program, week, day) {
  const definition = programDefinition(program);
  return {
    name:`${definition.shortName} ${programDays(program)[day].name}`,
    notes:'',
    unit:program.unit,
    exercises:definition.workout(program, week, day),
    programDay:{ definition:definition.id, startedAt:program.startedAt, cycle:program.cycle, week, day, label:blockLabel(program, week) }
  };
}

// What a saved workout keeps about the program day it came from, for History. Kept under a different name from the
// session's programDay, so starting a saved workout again never passes for a day of the program.
function programInfo(programDay) {
  const definition = findProgramDefinition(programDay.definition);
  return { name:definition ? definition.name : '', cycle:storedNumber(programDay.cycle), week:storedNumber(programDay.week) + 1, label:String(programDay.label || '') };
}

// ---- Progress -------------------------------------------------------------

// How the + set went, read from a workout's exercises: whatever was logged in the + set's place in the plan.
function amrapResult(exercises) {
  for (const exercise of exercises) {
    const plan = Array.isArray(exercise.plan) ? exercise.plan : [];
    const index = plan.findIndex(set => set && set.amrap);
    if (index === -1) continue;
    const logged = (exercise.sets || [])[index];
    return logged ? { weight:storedNumber(logged.weight), reps:storedNumber(logged.reps), target:storedNumber(plan[index].reps) } : null;
  }
  return null;
}

function missedAmrap(result) {
  return Boolean(result) && result.reps < result.target;
}

// Whether the day's main lift (its first exercise) got every planned rep of every work set; null if it was not tried.
function mainLiftHit(exercises) {
  const main = exercises[0];
  if (!main || !Array.isArray(main.plan) || !(main.sets || []).length) return null;
  return main.plan.every((set, index) => set.warmup || (Boolean(main.sets[index]) && storedNumber(main.sets[index].reps) >= storedNumber(set.reps)));
}

// The next block starts once every day of this one is done. That normally happens as its last day is saved, but a
// change of options (dropping the deload week), or a copy from another device, can also leave one finished.
function rollOver(program) {
  const definition = programDefinition(program);
  return { ...program, cycle:program.cycle + 1, done:{}, lastRollover:null, ...(definition.nextBlock ? definition.nextBlock(program) : {}) };
}

function settleProgram(program) {
  return program && !nextProgramDay(program) ? { program:rollOver(program), rolledOver:true } : { program, rolledOver:false };
}

function describeChanges(program, changes) {
  return changes.map(change => {
    const lift = programDefinition(program).lifts.find(item => item.key === change.lift);
    return `${lift.name} ${formatWeight(change.to)} ${weightUnit()} (${change.reset ? 'reset after a missed + set' : `+${Math.round((change.to - change.from) * 100) / 100}`})`;
  }).join(', ');
}

function nextUpMessage(program, rolledOver) {
  const definition = programDefinition(program);
  const next = nextProgramDay(program);
  const nextUp = `Next in ${definition.name}: ${dayLabel(program, next.week, next.day)}.`;
  if (!rolledOver) return nextUp;
  const complete = `${capitalize(definition.block)} ${program.cycle - 1} of ${definition.name} is complete.`;
  return program.lastRollover?.changes.length ? `${complete} New ${definition.numbersLabel.toLowerCase()}: ${describeChanges(program, program.lastRollover.changes)}.` : `${complete} ${nextUp}`;
}

// Saves a day as done, starting the next block once every day of this one is. Returns a sentence saying what comes next.
function recordProgramDay(program, week, day, entry) {
  const settled = settleProgram({ ...program, done:{ ...program.done, [dayKey(week, day)]:entry } });
  saveProgram(settled.program);
  return nextUpMessage(settled.program, settled.rolledOver);
}

// Called by finishWorkout for a workout started from the program with at least one set logged. A workout from a
// program that has since been ended, restarted or moved on to its next block is saved, but marks nothing done.
function completeProgramWorkout(session) {
  const { programDay } = session;
  const program = currentProgram;
  if (!programDay || !program || program.startedAt !== programDay.startedAt || program.cycle !== programDay.cycle || !programWeeks(program)[programDay.week] || !programDays(program)[programDay.day]) return '';
  const entry = { at:Date.now(), skipped:false, amrap:amrapResult(session.exercises), hit:mainLiftHit(session.exercises) };
  const definition = programDefinition(program);
  const progress = definition.afterWorkout ? definition.afterWorkout(program, programDay.day, entry, session.exercises) : { program, note:'' };
  return [progress.note, recordProgramDay(progress.program, programDay.week, programDay.day, entry)].filter(Boolean).join(' ');
}

// ---- Formatting -----------------------------------------------------------

function formatReps(set) {
  return set.repsMax ? `${set.reps}–${set.repsMax}` : `${set.reps}${set.amrap ? '+' : ''}`;
}

// "85 lbs × 5+", or "8–12 reps" when the plan leaves the weight to the lifter. Weights are in the unit shown.
function formatPlannedSet(set) {
  return set.weight === '' || set.weight === undefined || set.weight === null ? `${formatReps(set)} reps` : `${formatWeight(set.weight)} ${weightUnit()} × ${formatReps(set)}`;
}

// Accessories with a rep range go up in weight once every set reaches the top of it; says so before the first set.
function rangeAdvice(exercise, previous) {
  const top = exercise.plan[0].repsMax;
  if (!top || exercise.sets.length || !previous || previous.sets.length < exercise.plan.length) return '';
  return previous.sets.every(set => set.reps >= top) ? ` Last time every set reached ${top}, so go heavier.` : '';
}

// The line under an exercise with a plan during a workout: what the next set is, or how the + set went. `previous` is
// last time's performance of the exercise.
function plannedTarget(exercise, previous) {
  const plan = exercise.plan;
  const next = plan[exercise.sets.length];
  const note = exercise.note ? ` ${exercise.note}.` : '';
  if (next) {
    const share = next.percent ? ` (${next.percent}% of your training max)` : '';
    return `Set ${exercise.sets.length + 1} of ${plan.length}${next.warmup ? ', warm-up' : ''}: ${formatPlannedSet(next)}${share}.${next.amrap ? ' As many reps as you can.' : ''}${rangeAdvice(exercise, previous)}${note}`;
  }
  const result = amrapResult([exercise]);
  const done = plan.length === 1 ? 'The planned set is done.' : `All ${plan.length} planned sets done.`;
  return result && result.weight && result.reps ? `${done} Your + set of ${formatWeight(result.weight)} ${weightUnit()} × ${result.reps} puts your one-rep max near ${estimateOneRepMax(result.weight, result.reps)} ${weightUnit()}.` : done;
}

// Sets written the way programs write them: "4 × 5, 1 × 5+ at 135 lbs", "3 × 8–12", or one by one when the weight
// changes from set to set: "65 × 5 · 75 × 5 · 85 × 5+".
function describeSets(sets) {
  if (!sets.every(set => set.weight === sets[0].weight)) return sets.map(set => `${formatWeight(set.weight)} × ${formatReps(set)}`).join(' · ');
  const runs = [];
  sets.forEach(set => {
    const last = runs[runs.length - 1];
    if (last && formatReps(last.set) === formatReps(set)) last.count += 1;
    else runs.push({ set, count:1 });
  });
  const scheme = runs.map(run => `${run.count} × ${formatReps(run.set)}`).join(', ');
  return sets[0].weight === '' ? scheme : `${scheme} at ${formatWeight(sets[0].weight)} ${weightUnit()}`;
}

// "Bench Press 4 × 5, 1 × 5+ at 135 lbs", work sets only.
function describeExercisePlan(exercise) {
  return `${exercise.name} ${describeSets(exercise.plan.filter(set => !set.warmup))}`;
}

// ---- The program card -----------------------------------------------------

function programTemplateCards() {
  return programDefinitions.map(definition => {
    const following = Boolean(currentProgram) && currentProgram.definition === definition.id;
    const action = following ? '<button class="primary" type="button" data-program-action="view">View program</button>' : `<button class="primary" type="button" data-program-action="setup" data-program-id="${escapeHTML(definition.id)}">Set up program</button>`;
    return `<article class="template-card program-template" data-program-id="${escapeHTML(definition.id)}"><div><div class="template-card-heading"><h3>${escapeHTML(definition.name)}</h3><span class="badge">Program</span></div><p>${escapeHTML(typeof definition.summary === 'function' ? definition.summary(weightUnit()) : definition.summary)}</p><p class="program-schedule">${escapeHTML(definition.schedule)}${following ? ` · ${definition.block} ${currentProgram.cycle} in progress` : ''}</p></div><div class="template-actions">${action}</div></article>`;
  }).join('');
}

function dayStatus(entry) {
  if (entry.skipped) return '<span class="program-status skipped">Skipped</span>';
  // A day with no + set (a rep-range program, or a deload week) still says when its main lift fell short.
  if (!entry.amrap) return entry.hit === false ? '<span class="program-status missed">Done (missed reps)</span>' : '<span class="program-status">Done</span>';
  const short = missedAmrap(entry.amrap) ? ` (short of ${escapeHTML(entry.amrap.target)})` : entry.hit === false ? ' (missed a set)' : '';
  return `<span class="program-status${short ? ' missed' : ''}">Done · + set ${escapeHTML(entry.amrap.weight)} × ${escapeHTML(entry.amrap.reps)}${short}</span>`;
}

function programDayRow(program, week, day, next) {
  const entry = program.done[dayKey(week, day)];
  const isNext = Boolean(next) && next.week === week && next.day === day;
  const main = programDefinition(program).workout(program, week, day)[0];
  const label = `${entry ? 'Redo' : 'Start'} ${dayLabel(program, week, day)}`;
  const button = `<button class="${isNext ? 'primary' : 'secondary'}" type="button" data-program-action="start" data-week="${week}" data-day="${day}" aria-label="${escapeHTML(label)}">${entry ? 'Redo' : 'Start'}</button>`;
  return `<li class="program-day${entry ? ' done' : ''}${isNext ? ' next' : ''}"><div><strong>${escapeHTML(programDays(program)[day].name)}</strong><span>${escapeHTML(describeExercisePlan(main))}</span></div><div class="program-day-actions">${entry ? dayStatus(entry) : ''}${button}</div></li>`;
}

function renderProgram() {
  $('programCard').hidden = !currentProgram;
  if (!currentProgram) return;
  const program = currentProgram;
  const definition = programDefinition(program);
  const weeks = programWeeks(program), days = programDays(program);
  const block = capitalize(definition.block);
  const next = nextProgramDay(program);
  const finished = weeks.reduce((count, week, index) => count + doneInWeek(program, index), 0);
  $('programTitle').textContent = definition.name;
  $('programSummary').textContent = `${block} ${program.cycle} · ${finished} of ${weeks.length * days.length} workouts done${next && weeks.length > 1 ? ` · now in week ${next.week + 1} of ${weeks.length}, ${weeks[next.week].name}` : ''}`;
  // Says how the numbers moved at the end of the last block, until the first workout of the new one is done.
  const rollover = program.lastRollover && program.lastRollover.changes.length && !finished ? program.lastRollover : null;
  $('programNotice').hidden = !rollover;
  $('programNotice').textContent = rollover ? `${block} ${rollover.cycle} complete. ${definition.numbersLabel} for ${definition.block} ${program.cycle}: ${describeChanges(program, rollover.changes)}.` : '';
  $('programNext').hidden = !next;
  if (next) {
    const workout = programWorkout(program, next.week, next.day);
    const where = weeks.length > 1 ? ` · week ${next.week + 1}, ${weeks[next.week].name}` : '';
    $('programNext').innerHTML = `<div><span class="program-kicker">Next workout${escapeHTML(where)}</span><strong>${escapeHTML(days[next.day].name)}</strong><ul>${workout.exercises.map(exercise => `<li>${escapeHTML(describeExercisePlan(exercise))}</li>`).join('')}</ul></div><div class="program-next-actions"><button class="primary" type="button" data-program-action="start" data-week="${next.week}" data-day="${next.day}">Start workout</button><button class="secondary" type="button" data-program-action="skip" data-week="${next.week}" data-day="${next.day}">Skip</button></div>`;
  }
  $('programNumbersHeading').textContent = definition.numbersLabel;
  $('programMaxes').innerHTML = definition.lifts.map(lift => {
    const note = definition.numberNote(program, lift);
    return `<li><span>${escapeHTML(lift.name)}</span><strong>${escapeHTML(formatWeight(program.trainingMaxes[lift.key]))} ${weightUnit()}</strong><small${note.warn ? ' class="warn"' : ''}>${escapeHTML(note.text)}</small></li>`;
  }).join('');
  $('programBlockHeading').textContent = `This ${definition.block}`;
  const rows = week => days.map((entry, day) => programDayRow(program, week, day, next)).join('');
  // A block of one week is just its days; longer blocks list each week, the current one open.
  $('programWeeks').innerHTML = weeks.length === 1 ? `<ul class="program-days">${rows(0)}</ul>` : weeks.map((week, index) => `<details class="program-week"${next && next.week === index ? ' open' : ''}><summary><strong>Week ${index + 1} · ${escapeHTML(week.name)}</strong><span>${escapeHTML(week.summary)}</span><span class="program-week-count">${doneInWeek(program, index)} of ${days.length} done</span></summary><ul>${rows(index)}</ul></details>`).join('');
}

// ---- Setting up and editing -----------------------------------------------

// A one-rep max read off the most recent logged sets of an exercise (lastPerformance, kept by script.js), so the lifter
// does not have to work one out; null if the exercise has never been logged with a weight.
function estimatedOneRepMax(name) {
  const previous = lastTime(name);
  const best = previous ? Math.max(0, ...previous.sets.filter(set => set.weight > 0 && set.reps > 0).map(set => estimateOneRepMax(set.weight, set.reps))) : 0;
  return best || null;
}

// The heaviest weight lifted for `reps` or more reps the last time an exercise was done; null if there is none.
function heaviestSetOf(name, reps) {
  const previous = lastTime(name);
  const best = previous ? Math.max(0, ...previous.sets.filter(set => set.reps >= reps).map(set => set.weight)) : 0;
  return best ? prefillWeight(best, previous.converted) : null;
}

function heaviestSetOfFive(name) {
  return heaviestSetOf(name, 5);
}

function optionElementId(option) {
  return `program${capitalize(option.id)}`;
}

function optionField(option, value) {
  const id = optionElementId(option);
  if (option.type === 'check') return `<label class="setting-check" id="${id}Field"><input id="${id}" type="checkbox"${value ? ' checked' : ''} /> ${escapeHTML(option.label)}</label>`;
  const choices = optionChoices(option, weightUnit()).map(choice => `<option value="${escapeHTML(choice.value)}"${String(choice.value) === String(value) ? ' selected' : ''}>${escapeHTML(choice.label)}</option>`).join('');
  const help = option.help || optionChoices(option, weightUnit()).some(choice => choice.help) ? `<p class="subtitle program-help" id="${id}Help"></p>` : '';
  return `<div class="program-option" id="${id}Field"><label for="${id}">${escapeHTML(option.label)}</label><select id="${id}">${choices}</select>${help}</div>`;
}

// What the form says now: whether the numbers are one-rep maxes, and every option's value.
function readProgramForm() {
  const { definition } = programForm;
  const options = Object.fromEntries(definition.options.map(option => {
    const element = $(optionElementId(option));
    return [option.id, option.type === 'check' ? element.checked : optionChoices(option, weightUnit()).find(choice => String(choice.value) === element.value).value];
  }));
  return { oneRepMax:definition.oneRepMaxes && $('programMaxKind').value === '1rm', options, unit:weightUnit() };
}

// Shows what each number entered works out to, and the help for each option as chosen.
function syncProgramForm() {
  const { definition } = programForm;
  const form = readProgramForm();
  $('programMaxKindField').hidden = !definition.oneRepMaxes;
  definition.options.forEach(option => {
    const id = optionElementId(option);
    if (option.oneRepMaxOnly) $(`${id}Field`).hidden = !form.oneRepMax;
    const help = $(`${id}Help`);
    if (help) help.textContent = optionChoices(option, form.unit).find(choice => choice.value === form.options[option.id]).help || option.help || '';
  });
  definition.lifts.forEach(lift => {
    $(`programHint-${lift.key}`).textContent = definition.setup.hint(lift, positiveWeight($(`programMax-${lift.key}`).value), form);
  });
}

// Setting up a program fills the numbers in from history where it can; editing starts from the program's own. Setting
// up a program while following another replaces it.
function openProgramForm(definition) {
  const editing = Boolean(currentProgram) && currentProgram.definition === definition.id;
  const replacing = Boolean(currentProgram) && !editing;
  const options = editing ? currentProgram.options : normalizeOptions(definition, {}, weightUnit());
  programForm = { definition, editing };
  $('programModalTitle').textContent = `${editing ? 'Edit' : 'Start'} ${definition.name}`;
  $('programMaxKind').value = editing ? 'tm' : '1rm';
  $('programOptions').innerHTML = definition.options.map(option => optionField(option, options[option.id])).join('');
  let estimated = 0;
  $('programMaxInputs').innerHTML = definition.lifts.map(lift => {
    const value = editing ? currentProgram.trainingMaxes[lift.key] : definition.setup.estimate(lift);
    if (!editing && value) estimated += 1;
    return `<div class="program-max-row"><label for="programMax-${lift.key}">${escapeHTML(lift.name)} (${weightUnit()})</label><input id="programMax-${lift.key}" type="number" min="0" step="0.5" inputmode="decimal" value="${escapeHTML(value || '')}" /><span class="program-hint" id="programHint-${lift.key}"></span></div>`;
  }).join('');
  const current = replacing ? programDefinition(currentProgram).name : '';
  $('programIntro').textContent = [definition.setup.intro(editing), estimated ? definition.setup.estimated : '',
    replacing ? `This replaces ${current}, which you are following now; its finished workouts stay in your history.` : ''].filter(Boolean).join(' ');
  $('programSubmit').textContent = editing ? 'Save changes' : replacing ? 'Switch program' : 'Start program';
  $('programFormError').hidden = true;
  syncProgramForm();
  $('programModal').hidden = false;
  $(`programMax-${definition.lifts[0].key}`).focus();
}

function closeProgramForm() {
  $('programModal').hidden = true;
}

$('programForm').onsubmit = event => {
  event.preventDefault();
  const { definition, editing } = programForm;
  const form = readProgramForm();
  const trainingMaxes = {};
  let firstInvalid = null;
  definition.lifts.forEach(lift => {
    const input = $(`programMax-${lift.key}`);
    const value = positiveWeight(input.value);
    markInvalid(input, value === null);
    if (value === null) firstInvalid = firstInvalid || input;
    else trainingMaxes[lift.key] = definition.setup.toNumber(value, form, lift);
  });
  if (firstInvalid) {
    $('programFormError').textContent = 'Enter a weight above zero for every lift.';
    $('programFormError').hidden = false;
    firstInvalid.focus();
    return;
  }
  // A number changed by hand starts its run of missed sessions again.
  const stalls = editing ? Object.fromEntries(Object.entries(currentProgram.stalls).filter(([lift]) => trainingMaxes[lift] === currentProgram.trainingMaxes[lift])) : {};
  const base = editing ? currentProgram : { definition:definition.id, unit:weightUnit(), startedAt:Date.now(), cycle:1, done:{}, lastRollover:null };
  const settled = settleProgram(normalizeProgram({ ...base, trainingMaxes, stalls, options:form.options }));
  saveProgram(settled.program);
  closeProgramForm();
  if (settled.rolledOver) showFeedback(nextUpMessage(settled.program, true), 'success');
  else showFeedback(editing ? `${definition.name} updated. The rest of this ${definition.block} uses the new weights.` : `${definition.name} is set up. ${nextUpMessage(settled.program, false)}`, 'success');
  $('programCard').scrollIntoView({ behavior:'smooth', block:'start' });
};
['input', 'change'].forEach(type => $('programForm').addEventListener(type, event => {
  if (event.target.matches('.program-max-row input')) markInvalid(event.target, false);
  syncProgramForm();
}));
$('closeProgram').onclick = closeProgramForm;
$('cancelProgram').onclick = closeProgramForm;
$('programModal').onclick = event => { if (event.target === $('programModal')) closeProgramForm(); };
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('programModal').hidden) closeProgramForm(); });

$('templateList').addEventListener('click', event => {
  const button = event.target.closest('[data-program-action]');
  if (!button) return;
  if (button.dataset.programAction === 'setup') {
    const definition = findProgramDefinition(button.dataset.programId);
    if (definition) openProgramForm(definition);
  }
  if (button.dataset.programAction === 'view') $('programCard').scrollIntoView({ behavior:'smooth', block:'start' });
});
$('programCard').addEventListener('click', event => {
  const button = event.target.closest('[data-program-action]');
  if (!button || !currentProgram) return;
  const week = Number(button.dataset.week), day = Number(button.dataset.day);
  if (!programWeeks(currentProgram)[week] || !programDays(currentProgram)[day]) return;
  if (button.dataset.programAction === 'start') startWorkout(programWorkout(currentProgram, week, day));
  // A skipped day counts as done, so the program moves on, but it changes no weights; Redo on its row still starts it.
  if (button.dataset.programAction === 'skip') {
    const label = dayLabel(currentProgram, week, day);
    showFeedback(`Skipped ${label}. ${recordProgramDay(currentProgram, week, day, { at:Date.now(), skipped:true, amrap:null, hit:null })}`, 'success');
  }
});
$('editProgramBtn').onclick = () => { if (currentProgram) openProgramForm(programDefinition(currentProgram)); };
$('endProgramBtn').onclick = () => {
  if (!currentProgram) return;
  const name = programDefinition(currentProgram).name;
  if (!confirm(`End ${name}? The workouts you have finished stay in your history.`)) return;
  saveProgram(null);
  showFeedback(`${name} ended.`, 'success');
};
// A change of unit in Settings converts the program being followed, which saves it (and shows it) in the new unit.
window.addEventListener('settingschange', () => {
  if (currentProgram && currentProgram.unit !== weightUnit()) saveProgram(programInUnit(currentProgram, weightUnit()));
});
renderProgram();
