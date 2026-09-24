// Training programs: a whole plan of workouts, each one's weights worked out from the lifter's training maxes, which
// go up every cycle. The program being followed is kept per account beside settings and templates (offline.js saves
// it on this device first and uploads it). Loaded before script.js, whose startWorkout begins the program's workouts.
const programDefinitions = [{
  id:'wendler-531',
  name:'Wendler 5/3/1',
  shortName:'5/3/1',
  summary:'One main lift a day: overhead press, deadlift, bench press and squat. Each week builds to a heavy set of as many reps as you can, and every training max goes up after each cycle.',
  schedule:'4 days a week · 4-week cycles',
  // In the order the days are trained. Upper-body training maxes go up 5 lbs a cycle, lower-body ones 10.
  lifts:[
    { key:'press', name:'Overhead Press', day:'Press Day', increment:5 },
    { key:'deadlift', name:'Deadlift', day:'Deadlift Day', increment:10 },
    { key:'bench', name:'Bench Press', day:'Bench Day', increment:5 },
    { key:'squat', name:'Back Squat', day:'Squat Day', increment:10 }
  ],
  // [percent of the training max, reps]. The last set of a working week is a + set: as many reps as possible, at least the number given.
  weeks:[
    { name:'5s week', sets:[[65, 5], [75, 5], [85, 5]] },
    { name:'3s week', sets:[[70, 3], [80, 3], [90, 3]] },
    { name:'5/3/1 week', sets:[[75, 5], [85, 3], [95, 1]] },
    { name:'Deload week', sets:[[40, 5], [50, 5], [60, 5]], deload:true }
  ],
  warmups:[[40, 5], [50, 5], [60, 3]],
  // Missing the reps on a + set means the training max has got ahead of the lifter, so it drops to this share of itself.
  stallReset:0.9,
  assistance:[
    { id:'bbb', name:'Boring But Big', description:'5 sets of 10 of the day’s lift at 50% of its training max, then one assistance exercise.',
      supplemental:{ label:'BBB', percent:50, sets:5, reps:10 },
      exercises:{ press:[['Chin-up', 5, 10]], deadlift:[['Hanging Leg Raise', 5, 15]], bench:[['Dumbbell Row', 5, 10]], squat:[['Leg Curl', 5, 10]] } },
    { id:'triumvirate', name:'Triumvirate', description:'Two assistance exercises of 5 sets each after the main lift.',
      exercises:{ press:[['Dip', 5, 15], ['Chin-up', 5, 10]], deadlift:[['Good Morning', 5, 12], ['Hanging Leg Raise', 5, 15]], bench:[['Dumbbell Bench Press', 5, 15], ['Dumbbell Row', 5, 10]], squat:[['Leg Press', 5, 15], ['Leg Curl', 5, 10]] } },
    { id:'none', name:'Main lifts only', description:'Just the day’s main lift.', exercises:{} }
  ]
}];
const defaultProgramOptions = { assistance:'bbb', rounding:5, warmups:true, deload:true, tmPercent:90 };
let currentProgram = loadProgram();
let programFormDefinition = null;

function findProgramDefinition(id) {
  return programDefinitions.find(definition => definition.id === id) || null;
}

function programDefinition(program) {
  return findProgramDefinition(program.definition);
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
  const given = value.options && typeof value.options === 'object' ? value.options : {};
  const options = {
    assistance:definition.assistance.some(item => item.id === given.assistance) ? given.assistance : defaultProgramOptions.assistance,
    rounding:[2.5, 5].includes(Number(given.rounding)) ? Number(given.rounding) : defaultProgramOptions.rounding,
    warmups:typeof given.warmups === 'boolean' ? given.warmups : defaultProgramOptions.warmups,
    deload:typeof given.deload === 'boolean' ? given.deload : defaultProgramOptions.deload,
    tmPercent:[85, 90].includes(Number(given.tmPercent)) ? Number(given.tmPercent) : defaultProgramOptions.tmPercent
  };
  const done = {};
  Object.entries(value.done && typeof value.done === 'object' ? value.done : {}).forEach(([key, entry]) => {
    if (!/^\d+-\d+$/.test(key) || !entry || typeof entry !== 'object') return;
    const amrap = entry.amrap && typeof entry.amrap === 'object' ? { weight:storedNumber(entry.amrap.weight), reps:storedNumber(entry.amrap.reps), target:storedNumber(entry.amrap.target) } : null;
    done[key] = { at:storedNumber(entry.at), skipped:entry.skipped === true, amrap };
  });
  const rollover = value.lastRollover && typeof value.lastRollover === 'object' && Array.isArray(value.lastRollover.changes) ? {
    cycle:storedNumber(value.lastRollover.cycle),
    changes:value.lastRollover.changes.filter(change => change && definition.lifts.some(lift => lift.key === change.lift)).map(change => ({ lift:change.lift, from:storedNumber(change.from), to:storedNumber(change.to), reset:change.reset === true }))
  } : null;
  return { definition:definition.id, startedAt:storedNumber(value.startedAt), cycle:Math.max(1, Math.floor(storedNumber(value.cycle))), trainingMaxes, options, done, lastRollover:rollover };
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
  const settled = settleProgram(loadProgram());
  if (settled.rolledOver) saveProgram(settled.program);
  else {
    currentProgram = settled.program;
    renderProgram();
  }
}

// ---- The plan -------------------------------------------------------------

// Without the deload week each cycle is three weeks long.
function programWeeks(program) {
  const weeks = programDefinition(program).weeks;
  return program.options.deload ? weeks : weeks.filter(week => !week.deload);
}

// One day a week for each lift, in the definition's order.
function programDays(program) {
  return programDefinition(program).lifts;
}

function dayKey(week, day) {
  return `${week}-${day}`;
}

function nextProgramDay(program) {
  const weeks = programWeeks(program), days = programDays(program);
  for (let week = 0; week < weeks.length; week += 1) {
    for (let day = 0; day < days.length; day += 1) if (!program.done[dayKey(week, day)]) return { week, day };
  }
  return null;
}

function doneInWeek(program, week) {
  return programDays(program).filter((lift, day) => program.done[dayKey(week, day)]).length;
}

// Every set of the day's main lift: warm-ups (except in the deload week, whose sets are that light already), then
// the week's three sets, the last of them a + set in the working weeks.
function mainLiftPlan(program, week, lift) {
  const trainingMax = program.trainingMaxes[lift.key];
  const weekPlan = programWeeks(program)[week];
  const set = ([percent, reps], extra = {}) => ({ percent, weight:roundToStep(trainingMax * percent / 100, program.options.rounding), reps, ...extra });
  const warmups = program.options.warmups && !weekPlan.deload ? programDefinition(program).warmups.map(entry => set(entry, { warmup:true })) : [];
  return [...warmups, ...weekPlan.sets.map((entry, index) => set(entry, !weekPlan.deload && index === weekPlan.sets.length - 1 ? { amrap:true } : {}))];
}

// One day of the current cycle, in the shape startWorkout takes. Each exercise carries its plan: one entry per set
// with the weight and reps to do, where a weight of '' leaves the weight to the lifter (assistance exercises).
// programDay says which day of which run of the program it is, so finishing it can mark that day done.
function programWorkout(program, week, day) {
  const definition = programDefinition(program);
  const lift = programDays(program)[day];
  const weekPlan = programWeeks(program)[week];
  const main = mainLiftPlan(program, week, lift);
  const top = main[main.length - 1];
  const exercises = [{ name:lift.name, weight:top.weight, reps:String(top.reps), plan:main }];
  // The deload week is the main lift alone, to recover.
  if (!weekPlan.deload) {
    const assistance = definition.assistance.find(item => item.id === program.options.assistance);
    const extra = assistance.supplemental;
    if (extra) {
      const weight = roundToStep(program.trainingMaxes[lift.key] * extra.percent / 100, program.options.rounding);
      exercises.push({ name:`${lift.name} (${extra.label})`, weight, reps:String(extra.reps), plan:Array.from({ length:extra.sets }, () => ({ percent:extra.percent, weight, reps:extra.reps })) });
    }
    (assistance.exercises[lift.key] || []).forEach(([name, sets, reps]) => exercises.push({ name, weight:'', reps:String(reps), plan:Array.from({ length:sets }, () => ({ weight:'', reps })) }));
  }
  return {
    name:`${definition.shortName} ${lift.day}`,
    notes:'',
    exercises,
    programDay:{ definition:definition.id, startedAt:program.startedAt, cycle:program.cycle, week, day, label:`Cycle ${program.cycle}, week ${week + 1} · ${weekPlan.name}` }
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

// Next cycle's training maxes: each goes up by its lift's increment, unless one of its + sets this cycle fell short.
function nextTrainingMaxes(program) {
  const definition = programDefinition(program);
  const weeks = programWeeks(program);
  return programDays(program).map((lift, day) => {
    const from = program.trainingMaxes[lift.key];
    const reset = weeks.some((week, index) => missedAmrap(program.done[dayKey(index, day)]?.amrap));
    return { lift:lift.key, from, to:reset ? roundToStep(from * definition.stallReset, program.options.rounding) : from + lift.increment, reset };
  });
}

function rollOver(program) {
  const changes = nextTrainingMaxes(program);
  return { ...program, cycle:program.cycle + 1, trainingMaxes:Object.fromEntries(changes.map(change => [change.lift, change.to])), done:{}, lastRollover:{ cycle:program.cycle, changes } };
}

// A cycle with every day done moves on to the next. That normally happens as its last day is saved, but dropping the
// deload week, or a copy from another device, can also leave one finished.
function settleProgram(program) {
  return program && !nextProgramDay(program) ? { program:rollOver(program), rolledOver:true } : { program, rolledOver:false };
}

function describeChanges(program, changes) {
  return changes.map(change => {
    const lift = programDays(program).find(item => item.key === change.lift);
    return `${lift.name} ${change.to} lbs (${change.reset ? 'reset after a missed + set' : `+${Math.round((change.to - change.from) * 100) / 100}`})`;
  }).join(', ');
}

function nextUpMessage(program, rolledOver) {
  const definition = programDefinition(program);
  if (rolledOver) return `Cycle ${program.lastRollover.cycle} of ${definition.name} is complete. New training maxes: ${describeChanges(program, program.lastRollover.changes)}.`;
  const next = nextProgramDay(program);
  return `Next in ${definition.name}: ${programDays(program)[next.day].day}, week ${next.week + 1}.`;
}

// Saves a day as done, starting the next cycle once every day of this one is. Returns a sentence saying what comes next.
function recordProgramDay(program, week, day, entry) {
  const settled = settleProgram({ ...program, done:{ ...program.done, [dayKey(week, day)]:entry } });
  saveProgram(settled.program);
  return nextUpMessage(settled.program, settled.rolledOver);
}

// Called by finishWorkout for a workout started from the program with at least one set logged. A workout from a
// program that has since been ended, restarted or moved on to its next cycle is saved, but marks nothing done.
function completeProgramWorkout(session) {
  const { programDay } = session;
  const program = currentProgram;
  if (!programDay || !program || program.startedAt !== programDay.startedAt || program.cycle !== programDay.cycle || !programWeeks(program)[programDay.week] || !programDays(program)[programDay.day]) return '';
  return recordProgramDay(program, programDay.week, programDay.day, { at:Date.now(), skipped:false, amrap:amrapResult(session.exercises) });
}

// ---- Formatting -----------------------------------------------------------

// "85 lbs × 5+", or "10 reps" when the plan leaves the weight to the lifter.
function formatPlannedSet(set) {
  const reps = `${set.reps}${set.amrap ? '+' : ''}`;
  return set.weight === '' || set.weight === undefined || set.weight === null ? `${reps} reps` : `${set.weight} lbs × ${reps}`;
}

// The line under an exercise with a plan during a workout: what the next set is, or how the + set went.
function plannedTarget(exercise) {
  const plan = exercise.plan;
  const next = plan[exercise.sets.length];
  if (next) {
    const share = next.percent ? ` (${next.percent}% of your training max)` : '';
    return `Set ${exercise.sets.length + 1} of ${plan.length}${next.warmup ? ', warm-up' : ''}: ${formatPlannedSet(next)}${share}.${next.amrap ? ' As many reps as you can.' : ''}`;
  }
  const result = amrapResult([exercise]);
  const done = `All ${plan.length} planned sets done.`;
  return result && result.weight && result.reps ? `${done} Your + set of ${result.weight} lbs × ${result.reps} puts your one-rep max near ${estimateOneRepMax(result.weight, result.reps)} lbs.` : done;
}

function formatWorkSets(sets) {
  return sets.map(set => `${set.weight} × ${set.reps}${set.amrap ? '+' : ''}`).join(' · ');
}

// One line per exercise for the next-workout panel, work sets only: "Bench Press 115 × 3 · 130 × 3 · 145 × 3+".
function describeExercisePlan(exercise) {
  const work = exercise.plan.filter(set => !set.warmup);
  const uniform = work.every(set => set.weight === work[0].weight && set.reps === work[0].reps && !set.amrap);
  if (!uniform) return `${exercise.name} ${formatWorkSets(work)}`;
  return `${exercise.name} ${work.length} × ${work[0].reps}${work[0].weight === '' ? '' : ` at ${work[0].weight} lbs`}`;
}

// ---- The program card -----------------------------------------------------

function programTemplateCards() {
  return programDefinitions.map(definition => {
    const following = Boolean(currentProgram) && currentProgram.definition === definition.id;
    const action = following ? '<button class="primary" type="button" data-program-action="view">View program</button>' : `<button class="primary" type="button" data-program-action="setup" data-program-id="${escapeHTML(definition.id)}">Set up program</button>`;
    return `<article class="template-card program-template"><div><div class="template-card-heading"><h3>${escapeHTML(definition.name)}</h3><span class="badge">Program</span></div><p>${escapeHTML(definition.summary)}</p><p class="program-schedule">${escapeHTML(definition.schedule)}${following ? ` · cycle ${currentProgram.cycle} in progress` : ''}</p></div><div class="template-actions">${action}</div></article>`;
  }).join('');
}

function amrapStatus(entry) {
  if (entry.skipped) return '<span class="program-status skipped">Skipped</span>';
  if (!entry.amrap) return '<span class="program-status">Done</span>';
  const missed = missedAmrap(entry.amrap);
  return `<span class="program-status${missed ? ' missed' : ''}">Done · + set ${escapeHTML(entry.amrap.weight)} × ${escapeHTML(entry.amrap.reps)}${missed ? ` (short of ${escapeHTML(entry.amrap.target)})` : ''}</span>`;
}

function programDayRow(program, week, day, next) {
  const lift = programDays(program)[day];
  const entry = program.done[dayKey(week, day)];
  const isNext = Boolean(next) && next.week === week && next.day === day;
  const work = mainLiftPlan(program, week, lift).filter(set => !set.warmup);
  const label = `${entry ? 'Redo' : 'Start'} ${lift.day}, week ${week + 1}`;
  const button = `<button class="${isNext ? 'primary' : 'secondary'}" type="button" data-program-action="start" data-week="${week}" data-day="${day}" aria-label="${escapeHTML(label)}">${entry ? 'Redo' : 'Start'}</button>`;
  return `<li class="program-day${entry ? ' done' : ''}${isNext ? ' next' : ''}"><div><strong>${escapeHTML(lift.day)}</strong><span>${escapeHTML(`${lift.name} ${formatWorkSets(work)}`)}</span></div><div class="program-day-actions">${entry ? amrapStatus(entry) : ''}${button}</div></li>`;
}

function renderProgram() {
  $('programCard').hidden = !currentProgram;
  if (!currentProgram) return;
  const program = currentProgram;
  const weeks = programWeeks(program), days = programDays(program);
  const next = nextProgramDay(program);
  const finished = weeks.reduce((count, week, index) => count + doneInWeek(program, index), 0);
  $('programTitle').textContent = programDefinition(program).name;
  $('programSummary').textContent = `Cycle ${program.cycle} · ${finished} of ${weeks.length * days.length} workouts done${next ? ` · now in week ${next.week + 1} of ${weeks.length}, ${weeks[next.week].name}` : ''}`;
  // Says how the training maxes moved, until the first workout of the new cycle is done.
  const rollover = program.lastRollover && !finished ? program.lastRollover : null;
  $('programNotice').hidden = !rollover;
  $('programNotice').textContent = rollover ? `Cycle ${rollover.cycle} complete. Training maxes for cycle ${program.cycle}: ${describeChanges(program, rollover.changes)}.` : '';
  $('programNext').hidden = !next;
  if (next) {
    const workout = programWorkout(program, next.week, next.day);
    $('programNext').innerHTML = `<div><span class="program-kicker">Next workout · week ${next.week + 1}, ${escapeHTML(weeks[next.week].name)}</span><strong>${escapeHTML(days[next.day].day)}</strong><ul>${workout.exercises.map(exercise => `<li>${escapeHTML(describeExercisePlan(exercise))}</li>`).join('')}</ul></div><div class="program-next-actions"><button class="primary" type="button" data-program-action="start" data-week="${next.week}" data-day="${next.day}">Start workout</button><button class="secondary" type="button" data-program-action="skip" data-week="${next.week}" data-day="${next.day}">Skip</button></div>`;
  }
  const projected = nextTrainingMaxes(program);
  $('programMaxes').innerHTML = days.map((lift, index) => `<li><span>${escapeHTML(lift.name)}</span><strong>${escapeHTML(program.trainingMaxes[lift.key])} lbs</strong><small${projected[index].reset ? ' class="reset"' : ''}>${projected[index].reset ? `Resets to ${escapeHTML(projected[index].to)} next cycle` : `Next cycle: ${escapeHTML(projected[index].to)}`}</small></li>`).join('');
  $('programWeeks').innerHTML = weeks.map((week, index) => `<details class="program-week"${next && next.week === index ? ' open' : ''}><summary><strong>Week ${index + 1} · ${escapeHTML(week.name)}</strong><span>${week.sets.map(([percent]) => `${percent}%`).join(' · ')}${week.deload ? ' · main lift only' : ''}</span><span class="program-week-count">${doneInWeek(program, index)} of ${days.length} done</span></summary><ul>${days.map((lift, day) => programDayRow(program, index, day, next)).join('')}</ul></details>`).join('');
}

// ---- Setting up and editing -----------------------------------------------

// A one-rep max read off the most recent logged sets of an exercise (lastPerformance, kept by script.js), so the lifter
// does not have to work one out; null if the exercise has never been logged with a weight.
function estimatedOneRepMax(name) {
  const previous = lastPerformance[exerciseKey(name)];
  const best = previous ? Math.max(0, ...previous.sets.filter(set => set.weight > 0 && set.reps > 0).map(set => estimateOneRepMax(set.weight, set.reps))) : 0;
  return best || null;
}

function programFormNumbers() {
  return { oneRepMax:$('programMaxKind').value === '1rm', percent:Number($('programTmPercent').value) === 85 ? 85 : 90, rounding:Number($('programRounding').value) === 2.5 ? 2.5 : 5 };
}

// Shows what each number entered works out to (the training max from a one-rep max, or the cycle's heaviest set
// from a training max), and the chosen assistance's description.
function syncProgramForm() {
  const { oneRepMax, percent, rounding } = programFormNumbers();
  $('programTmPercentField').hidden = !oneRepMax;
  programFormDefinition.lifts.forEach(lift => {
    const value = positiveWeight($(`programMax-${lift.key}`).value);
    const trainingMax = value && (oneRepMax ? roundToStep(value * percent / 100, rounding) : value);
    $(`programHint-${lift.key}`).textContent = !trainingMax ? '' : oneRepMax ? `Training max ${trainingMax} lbs` : `Heaviest set ${roundToStep(trainingMax * 0.95, rounding)} lbs`;
  });
  const assistance = programFormDefinition.assistance.find(item => item.id === $('programAssistance').value);
  $('programAssistanceHelp').textContent = assistance ? assistance.description : '';
}

// Setting up asks for one-rep maxes, filled in from history where it can be; editing starts from the training maxes.
function openProgramForm(definition) {
  const editing = Boolean(currentProgram);
  const options = editing ? currentProgram.options : defaultProgramOptions;
  programFormDefinition = definition;
  $('programModalTitle').textContent = `${editing ? 'Edit' : 'Start'} ${definition.name}`;
  $('programMaxKind').value = editing ? 'tm' : '1rm';
  $('programTmPercent').value = String(options.tmPercent);
  $('programAssistance').innerHTML = definition.assistance.map(item => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)}</option>`).join('');
  $('programAssistance').value = options.assistance;
  $('programRounding').value = String(options.rounding);
  $('programWarmups').checked = options.warmups;
  $('programDeload').checked = options.deload;
  let estimated = 0;
  $('programMaxInputs').innerHTML = definition.lifts.map(lift => {
    const value = editing ? currentProgram.trainingMaxes[lift.key] : estimatedOneRepMax(lift.name);
    if (!editing && value) estimated += 1;
    return `<div class="program-max-row"><label for="programMax-${lift.key}">${escapeHTML(lift.name)} (lbs)</label><input id="programMax-${lift.key}" type="number" min="0" step="0.5" inputmode="decimal" value="${escapeHTML(value || '')}" /><span class="program-hint" id="programHint-${lift.key}"></span></div>`;
  }).join('');
  $('programIntro').textContent = editing
    ? 'Change a training max when the weights feel too heavy or too light. The rest of this cycle uses the new numbers, and later cycles build on them.'
    : `Enter a recent one-rep max for each lift, or switch to training maxes if you already know yours. Every weight in the program is worked out from these.${estimated ? ' Lifts you have logged are filled in with an estimate from your latest sets.' : ''}`;
  $('programSubmit').textContent = editing ? 'Save changes' : 'Start program';
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
  const definition = programFormDefinition;
  const { oneRepMax, percent, rounding } = programFormNumbers();
  const trainingMaxes = {};
  let firstInvalid = null;
  definition.lifts.forEach(lift => {
    const input = $(`programMax-${lift.key}`);
    const value = positiveWeight(input.value);
    markInvalid(input, value === null);
    if (value === null) firstInvalid = firstInvalid || input;
    else trainingMaxes[lift.key] = oneRepMax ? roundToStep(value * percent / 100, rounding) : value;
  });
  if (firstInvalid) {
    $('programFormError').textContent = 'Enter a weight above zero for every lift.';
    $('programFormError').hidden = false;
    firstInvalid.focus();
    return;
  }
  const editing = Boolean(currentProgram);
  const options = { assistance:$('programAssistance').value, rounding, warmups:$('programWarmups').checked, deload:$('programDeload').checked, tmPercent:percent };
  const base = editing ? currentProgram : { definition:definition.id, startedAt:Date.now(), cycle:1, done:{}, lastRollover:null };
  const settled = settleProgram(normalizeProgram({ ...base, trainingMaxes, options }));
  saveProgram(settled.program);
  closeProgramForm();
  if (settled.rolledOver) showFeedback(nextUpMessage(settled.program, true), 'success');
  else showFeedback(editing ? `${definition.name} updated. The rest of this cycle uses the new weights.` : `${definition.name} is set up. ${nextUpMessage(settled.program, false)}`, 'success');
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
  // A skipped day counts as done, so the program moves on; Redo on its row still starts it later.
  if (button.dataset.programAction === 'skip') {
    const name = programDays(currentProgram)[day].day;
    showFeedback(`Skipped ${name}, week ${week + 1}. ${recordProgramDay(currentProgram, week, day, { at:Date.now(), skipped:true, amrap:null })}`, 'success');
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
renderProgram();
