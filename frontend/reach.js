// Within reach: during a workout, what the next set or the finish is a step away from, said while there is still time to go
// for it. A line under the exercise (the reps at this weight that would be a record, a goal the weight reaches, a plate tier
// close by or reached for the first time), mirrored in the big view, and a line for the workout (what finishing it earns:
// the weekly goal, the streak, an achievement). Loaded on the Tracker after records.js and achievements.js; script.js,
// whose workout it reads, draws it.
//
// The exercise line never guesses: a record is said only when trying the next set through newRecords, as logging it would,
// gives a different record from the workout's so far, so "8 reps at 185 lbs would be a record" means a set of 8 sets off
// the fireworks. The workout line and the plates need the whole history, so they wait for the saved workouts to load.

// What the workout's line and the plate tiers start from, worked out once a workout (and again when anything it depends on
// changes, such as the saved workouts loading): { key, line, lifts:{ bench:{ plates, heaviest }, ... } or null }.
let reachBase = null;

// "“50 workouts”", "“A” and “B”", "“A”, “B” and “C”".
function quotedList(names) {
  const quoted = names.map(name => `“${name}”`);
  return quoted.length > 1 ? `${quoted.slice(0, -1).join(', ')} and ${quoted[quoted.length - 1]}` : quoted.join('');
}

function reachBaseFor(session) {
  const pending = readPendingWorkouts();
  const key = [session.clientId || session.startedAt, savedWorkoutsLoaded, savedSessions.length, pending.length, recordUnit(session),
    weeklyGoalFrom(getWorkoutSettings().weeklyGoal)].join('|');
  if (reachBase && reachBase.key === key) return reachBase;
  if (!savedWorkoutsLoaded) return (reachBase = { key, line:'', lifts:null });
  const history = uniqueSessions([...savedSessions, ...pending]);
  // Finishing now, with nothing more logged: what the count alone earns (a workout milestone, the week, the streak).
  const finish = finishRewards(history, { name:session.name, createdAt:Date.now(), exercises:[], clientId:'within-reach' });
  const parts = [];
  if (finish.weekReached) parts.push(finish.streak >= 2 ? `reaches your weekly goal (a ${finish.streak}-week streak)` : 'reaches your weekly goal');
  const earned = finish.earned.filter(item => !(finish.weekReached && item.family === 'streak')).map(item => item.name);
  if (earned.length) parts.push(`earns ${quotedList(earned)}`);
  // Each plate lift: its plates a side so far (as the achievements count them) and its heaviest set, in this workout's unit.
  const unit = recordUnit(session);
  const lifts = Object.fromEntries(Object.keys(plateLifts).map(lift => [lift, { plates:finish.after.families.find(family => family.id === lift).value, heaviest:0 }]));
  history.filter(workout => !isCardio(workout)).forEach(workout => (workout.exercises || []).forEach(item => {
    const lift = plateLiftOf(item.name);
    if (!lift || isTimed(item)) return;
    (item.sets || [{ weight:item.weight, reps:item.reps }]).forEach(set => {
      if (Number(set.weight) > 0 && Number(set.reps) >= 1) lifts[lift].heaviest = Math.max(lifts[lift].heaviest, convertWeight(Number(set.weight), recordUnit(workout), unit));
    });
  }));
  return (reachBase = { key, line:parts.length ? `Finishing this workout ${parts.join(' and ')}.` : '', lifts });
}

// The fewest reps at `weight` (in the workout's unit) that would set off a record on the next set: newRecords over the
// workout's sets of the exercise and that one, against the bests before the workout, saying something new. 0 for none (up
// to 15 reps), or for an exercise done for the first time, which has nothing to beat.
function recordReps(exercise, weight) {
  const key = exerciseKey(exercise.name);
  if (!personalBests[key]) return 0;
  const now = exerciseRecord(exercise.name);
  const unit = recordUnit(activeSession);
  const items = activeSession.exercises.filter(item => exerciseKey(item.name) === key);
  for (let reps = 1; reps <= 15; reps += 1) {
    const exercises = items.map(item => item === exercise ? { ...item, sets:[...(item.sets || []), { weight, reps }] } : item);
    const line = newRecords({ exercises, unit }, personalBests)[0] || '';
    if (line && line !== now) return reps;
  }
  return 0;
}

// A plate tier this lift is close to (within a tenth of it), or one `weight` reaches for the first time: { first, text }, or
// null. Every alias of the lift counts, from the history and this workout.
function plateReach(exercise, weight) {
  const lift = plateLiftOf(exercise.name);
  const base = reachBase && reachBase.lifts;
  if (!lift || !base) return null;
  const unit = recordUnit(activeSession);
  const done = activeSession.exercises.filter(item => plateLiftOf(item.name) === lift && !isTimed(item)).flatMap(item => item.sets || [])
    .filter(set => Number(set.weight) > 0 && Number(set.reps) >= 1).map(set => Number(set.weight));
  const tiers = achievementFamilies.find(family => family.id === lift).tiers({}).length;
  const have = Math.max(base[lift].plates, ...done.map(set => Math.min(tiers, platesIn(set, unit))), 0);
  if (have >= tiers) return null;
  const target = plateWeights[unit === 'kg' ? 'kg' : 'lbs'][have];
  if (weight >= target) {
    const plates = Math.min(tiers, platesIn(weight, unit));
    return { first:true, text:`${formatWeight(weight)} ${unit} puts ${plural(plates, 'plate')} a side on the bar for the first time. It is yours when you finish.` };
  }
  const heaviest = Math.max(base[lift].heaviest, ...done, 0);
  const gap = Math.round((target - heaviest) * 100) / 100;
  return heaviest > 0 && gap > 0 && gap <= target * 0.1
    ? { first:false, text:`${formatWeight(gap)} ${unit} from ${plural(have + 1, 'plate')} a side (${formatWeight(target)} ${unit}).` } : null;
}

// The line under the exercise, or ''. Quiet for a timed exercise, a warm-up set, and while the stall hint suggests a
// lighter week, which a nudge to go heavier would argue with. A goal outranks a record, as it does when the set is logged.
function exerciseReach(exercise) {
  if (!exercise || isTimed(exercise)) return '';
  const planned = Array.isArray(exercise.plan) ? exercise.plan[(exercise.sets || []).length] : null;
  if (planned && planned.warmup) return '';
  if (!$('progressionHint').hidden && $('progressionHint').classList.contains('stalled')) return '';
  const typed = $('activeWeight').value.trim();
  const weight = Number(typed) || 0;
  if (typed !== '' && !(Number(typed) >= 0)) return '';
  const unit = recordUnit(activeSession);
  const at = `${formatWeight(weight)} ${unit}`;
  if (weight > 0) {
    const goal = goalReachedBy(exercise, weight);
    if (goal) return `A set at ${at} reaches your goal of ${formatWeight(goal.target)} ${goal.unit || 'lbs'}.`;
  }
  const plate = plateReach(exercise, weight);
  if (plate && plate.first) return plate.text;
  const reps = recordReps(exercise, weight);
  if (reps) {
    if (!(weight > 0)) return `${plural(reps, 'rep')} would be a record.`;
    return reps === 1 ? `Any set at ${at} would be a record.` : `${plural(reps, 'rep')} at ${at} would be a record.`;
  }
  return plate ? plate.text : '';
}

// Draws both lines, from the workout as it stands and the weight in the field.
function renderReach() {
  if (!activeSession) return;
  const base = reachBaseFor(activeSession);
  $('workoutReach').textContent = base.line;
  $('workoutReach').hidden = !base.line;
  const line = exerciseReach(activeSession.exercises[activeSession.currentIndex]);
  $('reachHint').textContent = line;
  $('reachHint').hidden = !line;
}
