// Progress: the achievements earned, the personal records, the stalled lifts and the goals set. Loaded before progress.js, which
// declares the state these read (allWorkouts, selectedExercise) and starts the page; nothing here reads it until the workouts have
// loaded.

// ---- Achievements --------------------------------------------------------------
// A row for each kind (achievements.js): the best tier earned and its day, a mark for each tier, and a bar to the next. From the
// workouts as they were logged (not converted), so a plate counts in the unit it was loaded in.
// The achievements as last drawn, which a row's Share draws its card from.
let shownAchievements = null;

function renderAchievements() {
  shownAchievements = achievementsOf(loadedWorkouts);
  const { families, earned } = shownAchievements;
  const total = families.reduce((sum, family) => sum + family.tiers.length, 0);
  const latest = earned.reduce((newest, item) => !newest || item.at >= newest.at ? item : newest, null);
  $('achievementsState').textContent = earned.length ? `${earned.length} of ${total} earned · latest ${latest.name}` : `0 of ${total} earned`;
  const names = new Map(earned.map(item => [item.id, item]));
  $('achievementList').innerHTML = families.map(family => {
    const top = family.earned.length ? names.get(`${family.id}:${family.tiers[family.earned.length - 1]}`) : null;
    const percent = family.next === null ? 100 : Math.min(100, Math.round(family.value / family.next * 100));
    const marks = family.tiers.map((tier, index) => `<i class="${index < family.earned.length ? 'on' : ''}"></i>`).join('');
    const now = family.reads ? ` · now ${family.reads}` : '';
    const next = family.next === null ? `All ${family.tiers.length} earned${family.reads ? ` · ${family.reads}` : ''}` : `Next: ${family.nextName}${now}`;
    return `<li class="achievement${top ? ' earned' : ''}"><div class="achievement-head"><strong>${escapeHTML(top ? top.name : family.title)}</strong>`
      + `<span class="achievement-marks" role="img" aria-label="${family.earned.length} of ${family.tiers.length} earned">${marks}</span></div>`
      + `<span>${escapeHTML(top ? `Earned ${longDate(top.at)}` : 'Not earned yet')}</span>`
      + `<div class="goal-bar achievement-bar" role="progressbar" aria-label="${escapeHTML(`${family.title}, toward the next`)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span></span></div>`
      + `<span class="achievement-next">${escapeHTML(next)}</span>`
      + (top ? `<button class="link-button achievement-share" type="button" data-share="${escapeHTML(top.id)}" aria-label="Share ${escapeHTML(top.name)} as a picture">Share</button>` : '') + '</li>';
  }).join('');
  // Through the DOM, as the goals' bars are: the Content-Security-Policy refuses style="" written into markup.
  $('achievementList').querySelectorAll('.achievement-bar').forEach(bar => { bar.firstElementChild.style.width = `${bar.getAttribute('aria-valuenow')}%`; });
}

// Share draws the row's best achievement as a card (achievement-card.js), and says so when it was saved rather than shared.
$('achievementList').onclick = event => {
  const button = event.target.closest('[data-share]');
  const item = button && shownAchievements && shownAchievements.earned.find(entry => entry.id === button.dataset.share);
  if (!item) return;
  shareAchievementCard(item, shownAchievements).then(said => { $('achievementFeedback').textContent = said; });
};

// ---- Personal records -----------------------------------------------------
// Each exercise's best, from every saved workout whatever the filters: the heaviest weight (with the most reps done at
// it), the best estimated one-rep max, the most reps in a set without weight, and a timed exercise's longest hold. Each
// record keeps the day it was first reached.

function recordsOf(workouts) {
  const records = new Map();
  [...workouts].sort((a, b) => a.createdAt - b.createdAt).forEach(workout => workout.exercises.forEach(item => {
    // The workout form saves an exercise without sets: its weight and reps are its one set.
    const sets = item.sets || [{ weight:item.weight, reps:item.reps }];
    const key = exerciseKey(item.name);
    if (!sets.length || !key) return;
    const record = records.get(key) || { key, heaviest:null, oneRepMax:null, reps:null, hold:null };
    // Oldest first, so these end up as the most recent spelling, as the exercise list uses.
    record.name = String(item.name).trim();
    const date = workout.createdAt;
    const beats = (current, value) => value > 0 && (!current || value > current.value);
    sets.forEach(set => {
      const weight = Number(set.weight) || 0, reps = Number(set.reps) || 0;
      if (isTimed(item)) {
        if (beats(record.hold, reps)) record.hold = { value:reps, date };
      } else if (weight > 0) {
        if (beats(record.heaviest, weight) || (record.heaviest && weight === record.heaviest.value && reps > record.heaviest.reps)) record.heaviest = { value:weight, reps, date };
        const estimate = reps >= 1 && reps <= ONE_REP_MAX_REPS ? exactOneRepMax(weight, reps) : 0;
        if (beats(record.oneRepMax, estimate)) record.oneRepMax = { value:estimate, weight, reps, date };
      } else if (beats(record.reps, reps)) record.reps = { value:reps, date };
    });
    records.set(key, record);
  }));
  return [...records.values()]
    .map(record => ({ ...record, latest:Math.max(0, ...[record.heaviest, record.oneRepMax, record.reps, record.hold].filter(Boolean).map(best => best.date)) }))
    .filter(record => record.latest > 0)
    .sort((a, b) => b.latest - a.latest);
}

// Each cardio activity's records, as the strength ones are listed: the longest distance, the fastest pace, split or speed
// (and over how far), the longest time and the most floors, each with the day it was set.
function cardioRecordsOf(workouts) {
  return [...cardioBests(workouts).values()].map(best => {
    const unit = shownDistanceUnit(best.activity);
    const lines = [];
    if (best.distance) lines.push(['Longest', formatDistance(best.distance.value, unit), best.distance.at]);
    if (best.rate) lines.push(['Fastest', `${best.rate.text}, over ${formatDistance(best.rate.distance, unit)}`, best.rate.at]);
    if (best.duration) lines.push(['Longest time', formatClock(best.duration.value), best.duration.at]);
    if (best.floors) lines.push(['Most floors', String(best.floors.value), best.floors.at]);
    return { key:best.key, name:best.name, lines, latest:Math.max(0, ...lines.map(line => line[2])) };
  });
}

// A strength exercise's records as [label, value, day] lines, in the unit shown: Personal records lists them, and so does the
// This exercise card.
function strengthRecordLines(record, unit) {
  const lines = [];
  if (record.heaviest) lines.push(['Heaviest', `${formatWeight(record.heaviest.value)} ${unit} × ${record.heaviest.reps}`, record.heaviest.date]);
  if (record.oneRepMax) lines.push(['Est. one-rep max', `${Math.round(record.oneRepMax.value)} ${unit}, from ${formatWeight(record.oneRepMax.weight)} × ${record.oneRepMax.reps}`, record.oneRepMax.date]);
  if (record.reps) lines.push(['Most reps', plural(record.reps.value, 'rep'), record.reps.date]);
  if (record.hold) lines.push(['Longest hold', `${record.hold.value} s`, record.hold.date]);
  return lines;
}

function recordLineHTML([label, value, date]) {
  return `<span><span class="record-label">${escapeHTML(label)}</span> ${escapeHTML(value)} <span class="record-date">· ${escapeHTML(longDate(date))}</span></span>`;
}

function renderRecords() {
  const unit = weightUnit();
  const strength = recordsOf(allWorkouts).map(record => ({ key:record.key, name:record.name, lines:strengthRecordLines(record, unit), latest:record.latest }));
  // The most recent record first, whichever kind it is.
  const records = [...strength, ...cardioRecordsOf(allWorkouts)].filter(record => record.lines.length).sort((a, b) => b.latest - a.latest);
  $('recordsList').innerHTML = records.length ? records.map(record => `<li><button class="record" type="button" data-exercise="${escapeHTML(record.key)}">`
    + `<strong>${escapeHTML(record.name)}</strong>${record.lines.map(recordLineHTML).join('')}</button></li>`).join('')
    : '<li class="empty">Your records appear once you have saved a workout.</li>';
  $('recordsState').textContent = records.length ? `${plural(records.length, 'exercise')} · latest ${records[0].name}` : 'None yet';
}

// ---- Stalled lifts ------------------------------------------------------------
// Each lift whose best has not moved in three weeks or more (stalls.js), the longest stalled first, with the deload to try.
function renderStalls() {
  const unit = weightUnit();
  const stalls = stalledLifts(allWorkouts);
  $('stallList').innerHTML = stalls.length ? stalls.map(({ key, name, stall }) => `<li><button class="record" type="button" data-exercise="${escapeHTML(key)}">`
    + `<strong>${escapeHTML(name)}</strong><span>${escapeHTML(describeStall(stall))}</span>`
    + `<span><span class="record-label">Best</span> est. one-rep max ${Math.round(stall.best)} ${unit} <span class="record-date">· ${escapeHTML(longDate(stall.bestAt))}</span></span>`
    + `<span><span class="record-label">Try</span> a week at ${escapeHTML(formatWeight(stall.deload))} ${unit}, 10% off last time's ${escapeHTML(formatWeight(stall.heaviest))}</span>`
      + `</button></li>`).join('')
    : '<li class="empty">Nothing has stalled: every lift you have trained lately has set a best within three weeks, or is still early on.</li>';
  const named = stalls.slice(0, 2).map(({ name }) => name).join(', ');
  $('stallsState').textContent = stalls.length ? `${plural(stalls.length, 'lift')} stalled: ${named}${stalls.length > 2 ? ` and ${stalls.length - 2} more` : ''}` : 'None stalled';
}

// ---- Goals ------------------------------------------------------------------
// One goal per exercise (by exerciseKey): a weight to reach, and optionally a day to reach it by. It is kept with the account
// like a note, in the unit it was set in, and measured against the heaviest weight in any saved workout.
let goals = {};

function loadGoals() {
  const stored = readLocalState('goals');
  goals = stored && stored.value && typeof stored.value === 'object' && !Array.isArray(stored.value) ? stored.value : {};
}

function saveGoals() {
  saveLocalState('goals', goals);
}

// Whole days from today to a YYYY-MM-DD date: 0 is today, negative is past.
function daysUntil(by) {
  const [year, month, day] = by.split('-').map(Number);
  const now = new Date();
  return Math.round((new Date(year, month - 1, day) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
}

function goalDeadline(by) {
  const days = daysUntil(by);
  const [year, month, day] = by.split('-').map(Number);
  const date = new Date(year, month - 1, day).toLocaleDateString(undefined, { year:'numeric', month:'short', day:'numeric' });
  const left = days === 0 ? 'today' : days > 0 ? `${plural(days, 'day')} left` : `${plural(-days, 'day')} overdue`;
  return `by ${date}, ${left}`;
}

// Where a goal stands against the heaviest weight lifted (in the unit shown): its target in that unit, whether it is reached,
// how full its bar is, and how it reads ("50 lbs to go · by Dec 1, 50 days left"). The goal list and the This exercise card say it alike.
function goalStanding(goal, best, unit) {
  const target = convertWeight(goal.target, goal.unit || 'lbs', unit);
  const reached = best >= target;
  const status = reached ? 'Reached' : `${formatWeight(Math.round((target - best) * 100) / 100)} ${unit} to go`;
  const deadline = goal.by && !reached ? ` · ${goalDeadline(goal.by)}` : '';
  return { target, reached, percent:Math.min(100, Math.round(best / target * 100)), text:status + deadline };
}

function renderGoals() {
  applyUnitLabels();
  const unit = weightUnit();
  const records = recordsOf(allWorkouts);
  const heaviest = new Map(records.map(record => [record.key, record.heaviest ? record.heaviest.value : 0]));
  $('goalExercises').innerHTML = records.filter(record => record.heaviest).map(record => `<option value="${escapeHTML(record.name)}"></option>`).join('');
  const items = Object.entries(goals).map(([key, goal]) => {
    const best = heaviest.get(key) || 0;
    return { key, goal, best, ...goalStanding(goal, best, unit) };
  // Goals still to reach first, the nearest deadline first, then the ones reached.
  }).sort((a, b) => a.reached - b.reached || (a.goal.by || '9999').localeCompare(b.goal.by || '9999') || a.goal.name.localeCompare(b.goal.name));
  $('goalList').innerHTML = items.length ? items.map(({ key, goal, target, best, reached, percent, text }) =>
    `<li class="goal${reached ? ' reached' : ''}"><div class="goal-head"><strong>${escapeHTML(goal.name)}</strong>`
      + `<span>${formatWeight(best)} of ${formatWeight(target)} ${unit}</span></div>`
      + `<div class="goal-bar" role="progressbar" aria-label="${escapeHTML(goal.name)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span></span></div>`
      + `<div class="goal-foot"><span>${escapeHTML(text)}</span>`
      + `<button class="link-button" type="button" data-goal-remove="${escapeHTML(key)}" aria-label="Remove the goal for ${escapeHTML(goal.name)}">Remove</button></div></li>`
  ).join('') : '<li class="empty">No goals yet. Set one below.</li>';
  // Set through the DOM: the Content-Security-Policy refuses style="" attributes written into markup, which left every
  // bar full whatever the goal's progress.
  $('goalList').querySelectorAll('.goal-bar').forEach(bar => { bar.firstElementChild.style.width = `${bar.getAttribute('aria-valuenow')}%`; });
  $('goalsState').textContent = items.length ? `${plural(items.length, 'goal')} · ${items.filter(item => item.reached).length} reached` : 'None yet';
  // The exercise being looked at shows its own goal, so a goal set or removed here changes it.
  renderExerciseCard();
}

function showGoalFeedback(message, isError = false) {
  setStatusLine($('goalFeedback'), message, { error:isError });
}

$('goalForm').onsubmit = event => {
  event.preventDefault();
  const typed = $('goalExercise').value.trim();
  const target = Number($('goalTarget').value);
  const key = exerciseKey(typed);
  if (!key) { showGoalFeedback('Enter the exercise for the goal.', true); $('goalExercise').focus(); return; }
  if (!($('goalTarget').value !== '' && target > 0 && target <= 100000)) { showGoalFeedback('Enter a target weight above zero.', true); $('goalTarget').focus(); return; }
  // The exercise's own spelling when it has been done, so "bench press" and "Bench Press" are one goal.
  const known = recordsOf(allWorkouts).find(record => record.key === key);
  const name = known ? known.name : typed;
  // A target already lifted is reached the moment it is set, which is seldom what a goal is for; asked first, since it
  // can be meant (getting back to a weight after time off). Saying no asks for one above the best.
  const best = known && known.heaviest ? known.heaviest.value : 0, unit = weightUnit();
  const reached = best >= target;
  if (reached && !confirm(`You've already lifted ${formatWeight(best)} ${unit} on ${name}, so ${formatWeight(target)} ${unit} is reached already. Set it anyway?`)) {
    showGoalFeedback(`Choose a target above ${formatWeight(best)} ${unit} to aim for.`, true);
    $('goalTarget').focus();
    return;
  }
  const replaced = key in goals;
  goals = { ...goals, [key]:{ name, target, unit, by:$('goalBy').value } };
  saveGoals();
  $('goalForm').reset();
  renderGoals();
  showGoalFeedback(`${replaced ? 'Goal updated' : 'Goal set'} for ${name}${reached ? ', reached already' : ''}.`);
};

$('goalList').onclick = event => {
  const button = event.target.closest('[data-goal-remove]');
  if (!button || !(button.dataset.goalRemove in goals)) return;
  const { name } = goals[button.dataset.goalRemove];
  goals = { ...goals };
  delete goals[button.dataset.goalRemove];
  saveGoals();
  renderGoals();
  showGoalFeedback(`Goal removed for ${name}.`);
};
