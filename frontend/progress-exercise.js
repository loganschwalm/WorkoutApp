// Progress, for the exercise chosen: every session of it (newest first, in years and months that fold), and the card of its
// records, rep maxes, goal, stall and muscle. Loaded before progress.js, which declares the state these read (allWorkouts,
// selectedExercise) and starts the page; nothing here reads it until the workouts have loaded.

// ---- Every session of one exercise ------------------------------------------
// With one exercise chosen, each workout it was done in, newest first, with its sets and how many reps they had left,
// and the note kept with the exercise. Other pages link here with ?exercise= to open on it.
function renderSessions(workouts) {
  const single = selectedExercise !== 'all';
  $('sessionsCard').hidden = !single;
  if (!single) return;
  const label = $('exerciseFilter').selectedOptions[0]?.textContent || selectedExercise;
  if (chartingCardio()) {
    const sessions = workouts.filter(workout => isCardio(workout) && cardioKey(workout) === selectedExercise).sort((a, b) => b.createdAt - a.createdAt);
    $('sessionsTitle').textContent = `Every session of ${label}`;
    $('sessionsSummary').textContent = sessions.length ? `${plural(sessions.length, 'session')}, the most recent first.` : 'None for these filters.';
    $('sessionsNote').hidden = true;
    $('sessionList').innerHTML = sessionGroups(sessions, workout => workout.createdAt, workout => `<li class="session"><div><strong>${escapeHTML(longDate(workout.createdAt))}</strong>`
      + `<span>${escapeHTML(workout.name)}</span></div><span>${escapeHTML(describeCardio(workout))}</span></li>`);
    return;
  }
  const sessions = [...workouts].sort((a, b) => b.createdAt - a.createdAt).map(workout => ({
    workout, items:workout.exercises.filter(item => exerciseKey(item.name) === selectedExercise && (!item.sets || item.sets.length))
  })).filter(session => session.items.length);
  $('sessionsTitle').textContent = `Every session of ${label}`;
  $('sessionsSummary').textContent = sessions.length ? `${plural(sessions.length, 'session')}, the most recent first.` : 'None for these filters.';
  const notes = readLocalState('exerciseNotes')?.value;
  const note = notes && typeof notes === 'object' ? notes[selectedExercise] : '';
  $('sessionsNote').hidden = !note;
  $('sessionsNote').textContent = note ? `Your note: ${note}` : '';
  $('sessionList').innerHTML = sessionGroups(sessions, session => session.workout.createdAt, ({ workout, items }) => {
    const efforts = describeEfforts(items.flatMap(item => item.sets || []));
    return `<li class="session"><div><strong>${escapeHTML(longDate(workout.createdAt))}</strong><span>${escapeHTML(workout.name || 'Untitled workout')}</span></div>`
      + `<span>${escapeHTML(items.map(describeSavedExercise).join(' · '))}${efforts ? ` · ${escapeHTML(efforts)}` : ''}</span></li>`;
  });
}

// The sessions as years holding months, each folded or open on its heading, the latest year and month open and the rest folded, so
// an exercise done for years is not one long column. These are the folding groups of History's list, and use its classes.
// What was opened or closed by hand is kept, for the exercise it was done on, when the list is drawn again.
const sessionGroupOpened = new Map();

function sessionGroups(sessions, timeOf, rowOf) {
  const years = new Map();
  sessions.forEach(session => {
    const date = new Date(timeOf(session));
    const months = years.get(date.getFullYear()) || new Map();
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
    months.set(key, [...(months.get(key) || []), session]);
    years.set(date.getFullYear(), months);
  });
  const isOpen = (group, latest) => sessionGroupOpened.has(`${selectedExercise}|${group}`) ? sessionGroupOpened.get(`${selectedExercise}|${group}`) : latest;
  const fold = (className, group, open, name, total, inner) => `<li class="${className.split(' ')[0]}" data-group="${group}">`
    + `<details class="history-group ${className.split(' ')[1]}"${open ? ' open' : ''}><summary class="history-group-summary">`
    + `<h3 class="history-group-name">${escapeHTML(name)}</h3><span class="history-group-total">${escapeHTML(total)}</span></summary>${inner}</details></li>`;
  return [...years].map(([year, months], yearIndex) => {
    const monthItems = [...months].map(([key, inMonth], monthIndex) => {
      const name = new Date(Number(key.slice(0, 4)), Number(key.slice(5)) - 1, 1).toLocaleDateString(undefined, { month:'long' });
      return fold('history-month history-month-group', `month:${key}`, isOpen(`month:${key}`, yearIndex === 0 && monthIndex === 0), name,
        plural(inMonth.length, 'session'), `<ul class="history-month-list">${inMonth.map(rowOf).join('')}</ul>`);
    }).join('');
    const inYear = [...months.values()].flat();
    return fold('history-year history-year-group', `year:${year}`, isOpen(`year:${year}`, yearIndex === 0), String(year),
      plural(inYear.length, 'session'), `<ul class="history-year-list">${monthItems}</ul>`);
  }).join('');
}

$('sessionList').onclick = event => {
  const heading = event.target.closest('.history-group-summary');
  if (!heading) return;
  // Drawn by hand, so what was said is kept when the list is drawn again.
  event.preventDefault();
  const details = heading.parentElement;
  details.open = !details.open;
  sessionGroupOpened.set(`${selectedExercise}|${details.parentElement.dataset.group}`, details.open);
};

// ---- This exercise ------------------------------------------------------------
// With one strength exercise chosen, what there is to know about it in one place, over every saved workout whatever the
// filters (as Personal records are): its records, the heaviest weight it has done for 1, 3, 5, 8 and 10 reps, its goal and
// whether it has stalled, under its muscle and equipment. These are the same figures as the rows below the chart, which
// are for every exercise at once and fold away.

// The rep counts the table is kept for.
const repMaxTargets = [1, 3, 5, 8, 10];

// The heaviest weight done for at least each of repMaxTargets' reps, each with the day it was first reached, as
// { reps, weight, date } for those that have one. At least, so a set of 8 counts for 5 and the table never gets heavier as
// the reps rise. A timed exercise and sets without weight have none. An exercise saved without sets is one set of its own
// weight and reps, as recordsOf takes it, and one saved with an empty set list was skipped.
function repMaxesOf(workouts, key) {
  const best = new Map();
  [...workouts].sort((a, b) => a.createdAt - b.createdAt).forEach(workout => (workout.exercises || []).forEach(item => {
    if (exerciseKey(item.name ?? '') !== key || isTimed(item)) return;
    bestSets(item.sets || [{ weight:item.weight, reps:item.reps }]).forEach(set => {
      const weight = Number(set.weight) || 0, reps = Number(set.reps) || 0;
      if (!(weight > 0)) return;
      repMaxTargets.forEach(target => {
        // Oldest first and strictly heavier, so the day is the one the weight was first done for that many.
        if (reps >= target && (!best.has(target) || weight > best.get(target).weight)) best.set(target, { reps:target, weight, date:workout.createdAt });
      });
    });
  }));
  return repMaxTargets.filter(target => best.has(target)).map(target => best.get(target));
}

// Which of an exercise's muscle and equipment were guessed from its name, as the Exercises list says it.
function describeExerciseDetails(details) {
  const parts = [muscleLabel(details.muscle), equipmentLabel(details.equipment)].filter(Boolean);
  if (details.muscleGuessed && details.equipmentGuessed) parts.push('guessed from its name');
  else if (details.muscleGuessed) parts.push('muscle guessed from its name');
  else if (details.equipmentGuessed) parts.push('equipment guessed from its name');
  if (!details.muscle) parts.push('its sets are not counted until it has a muscle');
  return parts.join(' · ');
}

// Hidden across all exercises and for a cardio activity, whose records and sessions are listed with its chart.
function renderExerciseCard() {
  const single = selectedExercise !== 'all' && !chartingCardio() && allWorkouts.length > 0;
  $('exerciseCard').hidden = !single;
  if (!single) return;
  const unit = weightUnit();
  const record = recordsOf(allWorkouts).find(own => own.key === selectedExercise);
  const name = record ? record.name : $('exerciseFilter').selectedOptions[0]?.textContent || selectedExercise;
  $('exerciseTitle').textContent = name;
  $('exerciseDetails').textContent = describeExerciseDetails(exerciseDetails(name));
  const tile = (title, lines) => `<li class="record fact"><strong>${escapeHTML(title)}</strong>${lines.join('')}</li>`;
  const tiles = [];
  const recordLines = record ? strengthRecordLines(record, unit) : [];
  if (recordLines.length) tiles.push(tile('Records', recordLines.map(recordLineHTML)));
  const repMaxes = repMaxesOf(allWorkouts, selectedExercise);
  if (repMaxes.length) {
    tiles.push(tile('Heaviest weight for reps', repMaxes.map(({ reps, weight, date }) =>
      recordLineHTML([reps === 1 ? '1 rep' : `${reps}+ reps`, `${formatWeight(weight)} ${unit}`, date]))));
  }
  const goal = goals[selectedExercise];
  if (goal && goal.target > 0) {
    const best = record && record.heaviest ? record.heaviest.value : 0;
    const standing = goalStanding(goal, best, unit);
    tiles.push(tile('Goal', [`<span>${escapeHTML(`${formatWeight(best)} of ${formatWeight(standing.target)} ${unit}`)}</span>`,
      `<span>${escapeHTML(standing.text)}</span>`]));
  }
  const stall = stallOf(allWorkouts, selectedExercise);
  if (stall) {
    tiles.push(tile('Stalled', [`<span>${escapeHTML(describeStall(stall))}</span>`,
      `<span><span class="record-label">Try</span> ${escapeHTML(`a week at ${formatWeight(stall.deload)} ${unit}, 10% off last time's ${formatWeight(stall.heaviest)}`)}</span>`]));
  }
  $('exerciseFacts').innerHTML = tiles.join('') || '<li class="empty">Nothing is logged for it yet.</li>';
}
