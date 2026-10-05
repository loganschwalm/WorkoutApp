// The summary shown when a workout is finished: how long it took and how much was done, the personal records it set (records.js
// words them), and how it compares with before: its volume against the last time the same workout was done, each exercise's
// top set against its last time, the goals it reached, and where it leaves the week. Whatever it is compared with is taken
// before the workout joins the history (summaryBefore), after which "last time" would be this workout.

// The top set of some sets: the heaviest weight, then the most reps at it. With no weight (bodyweight, or a hold held for
// seconds) it is the most reps, or seconds. Null for no sets.
function topSet(sets) {
  return sets.reduce((top, set) => {
    const weight = Number(set.weight) || 0, reps = Number(set.reps) || 0;
    return !top || weight > top.weight || (weight === top.weight && reps > top.reps) ? { weight, reps } : top;
  }, null);
}

function describeTopSet(top, timed, unit) {
  if (timed) return `${top.reps} s`;
  return top.weight > 0 ? `${formatWeight(top.weight)} ${unit} × ${top.reps}` : plural(top.reps, 'rep');
}

// How a top set compares with the one before it: { kind: 'up' | 'down' | 'same' | 'first', text }. The weight is compared first,
// then the reps (or seconds) at it, so a heavier weight is up whatever the reps.
function topSetChange(top, before, timed, unit) {
  if (!before) return { kind:'first', text:'First time' };
  const weightChange = timed ? 0 : Math.round((top.weight - before.weight) * 100) / 100;
  const repsChange = top.reps - before.reps;
  const change = weightChange || repsChange;
  if (!change) return { kind:'same', text:'Same as last time' };
  const amount = weightChange ? `${formatWeight(Math.abs(weightChange))} ${unit}` : timed ? `${Math.abs(repsChange)} s` : plural(Math.abs(repsChange), 'rep');
  return { kind:change > 0 ? 'up' : 'down', text:`${change > 0 ? '+' : '−'}${amount}` };
}

// One row for each exercise done: its sets, its top set, and that against its last time (`last`, by exerciseKey, in the unit shown).
function summaryExercises(shown, last) {
  const unit = recordUnit(shown);
  return shown.exercises.filter(item => item.sets && item.sets.length).map(item => {
    const timed = isTimed(item);
    const lastSets = last[exerciseKey(item.name)]?.sets;
    const top = topSet(item.sets);
    return { name:String(item.name).trim(), sets:item.sets.length, top:describeTopSet(top, timed, unit),
      change:topSetChange(top, lastSets && lastSets.length ? topSet(lastSets) : null, timed, unit) };
  });
}

// Weight × reps of every set with a weight; a hold's seconds are not reps, so timed exercises are left out.
function workoutVolume(shown) {
  const setVolume = set => (Number(set.weight) || 0) * (Number(set.reps) || 0);
  return shown.exercises.filter(item => !isTimed(item)).reduce((total, item) => total + (item.sets || []).reduce((sum, set) => sum + setVolume(set), 0), 0);
}

// "6% more volume than last time (Oct 1)", or '' with nothing to compare (`before` is { volume, date }).
function volumeLine(volume, before) {
  if (!before || !before.volume || !volume) return '';
  const percent = Math.round((volume - before.volume) / before.volume * 100);
  const when = new Date(before.date).toLocaleDateString(undefined, { month:'short', day:'numeric' });
  return percent ? `${Math.abs(percent)}% ${percent > 0 ? 'more' : 'less'} volume than last time (${when})` : `The same volume as last time (${when})`;
}

// The goals (see Progress) this workout reached for the first time, a line each: an exercise whose heaviest set met its goal's
// weight when `bests` (what was done before it) had not.
function goalsReached(workout, bests) {
  const stored = readLocalState('goals');
  const goals = stored && stored.value && typeof stored.value === 'object' ? stored.value : {};
  const from = recordUnit(workout);
  const reached = [];
  new Set(workout.exercises.map(item => exerciseKey(item.name))).forEach(key => {
    const goal = goals[key];
    if (!goal || !(goal.target > 0)) return;
    const unit = goal.unit || 'lbs';
    const done = workout.exercises.filter(item => exerciseKey(item.name) === key);
    const lifted = Math.max(0, ...done.flatMap(item => (item.sets || []).map(set => convertWeight(Number(set.weight) || 0, from, unit))));
    const had = convertWeight(bests[key]?.weight || 0, 'lbs', unit);
    if (lifted >= goal.target && had < goal.target) reached.push(`${String(done[0].name).trim()}: ${formatWeight(goal.target)} ${unit}, goal reached`);
  });
  return reached;
}

// Everything the summary compares a workout with, taken before it is added to the history: the last time of each exercise
// (in the unit shown), the volume of the last workout of the same name, the records so far (for goals), and how many workouts
// this week has had, this one included.
function summaryBefore(workout) {
  const named = String(workout.name).trim().toLowerCase();
  const previous = [...savedWorkouts, ...readPendingWorkouts()]
    .filter(other => !isCardio(other) && String(other.name).trim().toLowerCase() === named && other.createdAt < workout.createdAt)
    .sort((a, b) => b.createdAt - a.createdAt)[0];
  const last = {};
  workout.exercises.forEach(item => {
    const entry = lastTime(item.name);
    if (entry) last[exerciseKey(item.name)] = entry;
  });
  const week = calendarDayKey(startOfWeek(new Date(workout.createdAt)));
  const thisWeek = [...savedSessions, ...readPendingWorkouts()].filter(other => calendarDayKey(startOfWeek(new Date(other.createdAt))) === week).length;
  return { last, bests:JSON.parse(JSON.stringify(personalBests)), week:thisWeek + 1,
    previous:previous ? { volume:workoutVolume(inUnit(previous)), date:previous.createdAt } : null };
}

// How long it took, how much was done, how that compares, and any new personal records; it stays until Done or the next
// workout starts. `before` is summaryBefore's, from before the workout was added to the history.
function showWorkoutSummary(workout, records, before = {}) {
  const shown = inUnit(workout);
  const rows = summaryExercises(shown, before.last || {});
  const sets = rows.reduce((total, row) => total + row.sets, 0);
  const volume = workoutVolume(shown);
  const stats = [
    ...(workout.duration ? [[formatDuration(workout.duration), 'Time']] : []),
    [String(shown.exercises.length), shown.exercises.length === 1 ? 'Exercise' : 'Exercises'],
    [String(sets), sets === 1 ? 'Set' : 'Sets'],
    ...(volume ? [[`${Math.round(volume).toLocaleString()} ${weightUnit()}`, 'Volume']] : [])
  ];
  const compared = volumeLine(volume, before.previous);
  const goals = goalsReached(workout, before.bests || {});
  const symbols = { up:'▲', down:'▼', same:'', first:'' };
  $('summaryName').textContent = workout.name;
  $('summaryStats').innerHTML = stats.map(([value, label]) => `<li><strong>${escapeHTML(value)}</strong><span>${escapeHTML(label)}</span></li>`).join('');
  $('summaryCompare').textContent = compared;
  $('summaryCompare').hidden = !compared;
  $('summaryWeek').textContent = before.week ? weekGoalLine(before.week, weeklyGoalFrom(getWorkoutSettings().weeklyGoal)) : '';
  $('summaryWeek').hidden = !before.week;
  $('summaryGoals').hidden = !goals.length;
  $('summaryGoalList').innerHTML = goals.map(goal => `<li>${escapeHTML(goal)}</li>`).join('');
  $('summaryRecords').hidden = !records.length;
  $('summaryRecordList').innerHTML = records.map(record => `<li>${escapeHTML(record)}</li>`).join('');
  $('summaryExercises').hidden = !rows.length;
  $('summaryExerciseList').innerHTML = rows.map(row => `<li><div><strong>${escapeHTML(row.name)}</strong><span>${escapeHTML(`${plural(row.sets, 'set')} · top ${row.top}`)}</span></div>`
    + `<span class="summary-change ${row.change.kind}">${symbols[row.change.kind] ? `<span aria-hidden="true">${symbols[row.change.kind]}</span> ` : ''}${escapeHTML(row.change.text)}</span></li>`).join('');
  $('workoutSummary').hidden = false;
  $('workoutSummary').scrollIntoView({ behavior:'smooth', block:'start' });
}

$('summaryDone').onclick = () => { $('workoutSummary').hidden = true; };
