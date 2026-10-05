// What was done before: each exercise's last performance (shown as "Last time" and used to fill in the next set), the
// personal records a finished workout is compared with (its summary, shown when one is finished, is summary.js).

let lastPerformance = {};
let personalBests = {};

function normalizeSets(sets) {
  return sets.map(set => ({
    weight:Number(set.weight) || 0, reps:Number(set.reps) || 0, ...(set.rir !== undefined && set.rir !== null ? { rir:Number(set.rir) } : {})
  }));
}

// The most recent real performance of each exercise (skipped exercises are ignored); shown and used to prefill the next session.
function buildLastPerformance(workouts) {
  const latest = {};
  [...workouts].sort((a, b) => b.createdAt - a.createdAt).forEach(workout => workout.exercises.forEach(item => {
    const key = exerciseKey(item.name);
    if (latest[key]) return;
    // The name as it was typed, for suggesting it (the key is lowercased).
    const entry = { name:String(item.name).trim(), date:workout.createdAt, unit:recordUnit(workout) };
    if (item.sets && item.sets.length) latest[key] = { ...entry, sets:normalizeSets(item.sets) };
    else if (!item.sets) latest[key] = { ...entry, sets:normalizeSets([{ weight:item.weight, reps:item.reps }]) };
  }));
  return latest;
}

function saveLastPerformance() {
  writeLocal(localKey('lastperf'), lastPerformance);
}

// Updated as soon as a workout is finished, so the next session shows it even if the upload is still waiting.
function rememberLastPerformance(workout) {
  workout.exercises.forEach(item => {
    lastPerformance[exerciseKey(item.name)] = {
      name:String(item.name).trim(), date:workout.createdAt, unit:recordUnit(workout), sets:normalizeSets(item.sets)
    };
  });
  saveLastPerformance();
  renderExerciseSuggestions();
}

// ---- Personal records -----------------------------------------------------
// The best each exercise has done in every saved workout (and any still uploading), kept on this device so a finished
// workout can be told its records at once, online or not. Weights are kept in pounds whatever they were logged in, so
// workouts in either unit compare. Per exercise: the heaviest weight, the best estimated one-rep max, the most reps in
// a set without weight, and for a timed exercise the longest hold. One-rep maxes come from exactOneRepMax in common.js.
function bestsOf(workouts) {
  const bests = {};
  workouts.forEach(workout => workout.exercises.forEach(item => {
    // The workout form saves an exercise without sets: its weight and reps are its one set.
    const sets = item.sets || [{ weight:item.weight, reps:item.reps }];
    if (!sets.length) return;
    const key = exerciseKey(item.name);
    const best = bests[key] || (bests[key] = { weight:0, oneRepMax:0, reps:0, seconds:0 });
    sets.forEach(set => {
      const reps = Number(set.reps) || 0;
      const weight = convertWeight(Number(set.weight) || 0, recordUnit(workout), 'lbs');
      if (isTimed(item)) best.seconds = Math.max(best.seconds, reps);
      else if (weight > 0) {
        best.weight = Math.max(best.weight, weight);
        if (reps >= 1 && reps <= ONE_REP_MAX_REPS) best.oneRepMax = Math.max(best.oneRepMax, exactOneRepMax(weight, reps));
      } else best.reps = Math.max(best.reps, reps);
    });
  }));
  return bests;
}

// ---- Values that look like a slip ----------------------------------------
// A set far past anything done before is more likely a slip of the thumb (1355 for 135, 500 reps for 50) than a record,
// so it is asked about before it is logged. Far past is three times the exercise's best and a good step beyond it, so a
// light first session (a 45 lb press, then 95) is never questioned. With nothing logged yet, only a weight past what
// almost anyone lifts, or over a hundred reps in a set. Sets already logged this workout (`others`) count as bests too.
const implausibleWeight = { lbs:1000, kg:450 };
const implausibleStep = { lbs:50, kg:25 };
const implausibleReps = 100;

// { message, field } to ask with, field being the one to fix ('weight' or 'reps'); null when the set looks like a set.
function implausibleSet(exercise, set, others = []) {
  const unit = weightUnit(), weight = Number(set.weight) || 0, reps = Number(set.reps) || 0;
  const name = String(exercise.name).trim();
  const best = personalBests[exerciseKey(name)] || {};
  const done = others.map(other => ({ weight:Number(other.weight) || 0, reps:Number(other.reps) || 0 }));
  const times = (value, than) => `${Math.floor(value / than)}×`;
  if (isTimed(exercise)) {
    const longest = Math.max(best.seconds || 0, ...done.map(other => other.reps));
    return longest > 0 && reps >= 3 * longest && reps - longest >= 60
      ? { message:`That's ${times(reps, longest)} your longest ${name} (${longest} s). Log ${reps} s anyway?`, field:'reps' } : null;
  }
  if (weight > 0) {
    const heaviest = Math.max(convertWeight(best.weight || 0, 'lbs', unit), ...done.map(other => other.weight));
    if (heaviest > 0 && weight >= 3 * heaviest && weight - heaviest >= implausibleStep[unit]) {
      return { message:`That's ${times(weight, heaviest)} your heaviest ${name} (${formatWeight(heaviest)} ${unit}). Log ${formatWeight(weight)} ${unit} anyway?`, field:'weight' };
    }
    if (weight > implausibleWeight[unit] && weight > heaviest) return { message:`${formatWeight(weight)} ${unit} is more than almost anyone lifts. Log it anyway?`, field:'weight' };
    return reps > implausibleReps ? { message:`${reps} reps in one set? Log it anyway?`, field:'reps' } : null;
  }
  const most = Math.max(best.reps || 0, ...done.filter(other => !other.weight).map(other => other.reps));
  if (most > 0 && reps >= 3 * most && reps - most >= 20) return { message:`That's ${times(reps, most)} your most ${name} reps (${most}). Log ${reps} anyway?`, field:'reps' };
  return reps > implausibleReps && reps > most ? { message:`${reps} reps in one set? Log it anyway?`, field:'reps' } : null;
}

function rememberBests(workout) {
  Object.entries(bestsOf([workout])).forEach(([key, best]) => {
    const had = personalBests[key];
    personalBests[key] = had ? Object.fromEntries(Object.keys(best).map(field => [field, Math.max(had[field] || 0, best[field])])) : best;
  });
  writeLocal(localKey('bests'), personalBests);
}

// What a finished workout did better than every workout before it, a sentence each. An exercise done for the first
// time has nothing to beat, so it sets no record, and each exercise names its best record only: a heavier weight, else
// a better estimated one-rep max (more reps at a weight), else more reps without weight; or a timed exercise's longer hold.
function newRecords(workout, before) {
  const from = recordUnit(workout), unit = weightUnit();
  const fromPounds = pounds => `${formatWeight(convertWeight(pounds, 'lbs', unit))} ${unit}`;
  const exercises = new Map();
  workout.exercises.forEach(item => {
    const key = exerciseKey(item.name);
    if (!exercises.has(key)) exercises.set(key, { name:String(item.name).trim(), timed:isTimed(item), sets:[] });
    // Sets as done, with each weight in pounds too, to compare.
    exercises.get(key).sets.push(...(item.sets || []).map(set => ({
      reps:Number(set.reps) || 0, weight:Number(set.weight) || 0, pounds:convertWeight(Number(set.weight) || 0, from, 'lbs')
    })));
  });
  const records = [];
  exercises.forEach(({ name, timed, sets }, key) => {
    const best = before[key];
    if (!best || !sets.length) return;
    const top = score => sets.reduce((a, b) => score(b) > score(a) ? b : a);
    const done = set => `${formatWeight(convertWeight(set.weight, from, unit))} ${unit} × ${set.reps}`;
    if (timed) {
      const longest = top(set => set.reps);
      if (best.seconds && longest.reps > best.seconds) records.push(`${name}: held ${longest.reps} s, your longest yet (was ${best.seconds} s)`);
      return;
    }
    const heaviest = top(set => set.pounds);
    if (best.weight && heaviest.pounds > best.weight) {
      records.push(`${name}: ${done(heaviest)}, your heaviest yet (was ${fromPounds(best.weight)})`);
      return;
    }
    const counted = sets.filter(set => set.pounds > 0 && set.reps >= 1 && set.reps <= ONE_REP_MAX_REPS);
    const strongest = counted.length ? counted.reduce((a, b) => exactOneRepMax(b.pounds, b.reps) > exactOneRepMax(a.pounds, a.reps) ? b : a) : null;
    if (strongest && best.oneRepMax && exactOneRepMax(strongest.pounds, strongest.reps) > best.oneRepMax) {
      const estimate = value => `${Math.round(convertWeight(value, 'lbs', unit))} ${unit}`;
      const estimated = estimate(exactOneRepMax(strongest.pounds, strongest.reps));
      records.push(`${name}: ${done(strongest)}, an estimated one-rep max of ${estimated}, your best yet (was ${estimate(best.oneRepMax)})`);
      return;
    }
    const most = top(set => set.pounds > 0 ? 0 : set.reps);
    if (best.reps && most.pounds === 0 && most.reps > best.reps) records.push(`${name}: ${most.reps} reps in a set, your most yet (was ${best.reps})`);
  });
  return records;
}

// Last time's performance of an exercise in the unit shown, or null. `converted` says it was logged in the other unit,
// so its weights are exact conversions (102.06 kg) rather than weights anyone loads; see prefillWeight.
function lastTime(name) {
  const entry = lastPerformance[exerciseKey(name)];
  if (!entry) return null;
  const from = recordUnit(entry), to = weightUnit();
  return from === to ? entry : { ...entry, unit:to, converted:true, sets:entry.sets.map(set => ({ ...set, weight:convertWeight(set.weight, from, to) })) };
}

// A weight to fill in for the next set. One converted from the other unit is rounded to the nearest half, which the
// weight buttons then step from; one logged in this unit is used as it is.
function prefillWeight(weight, converted) {
  const number = Number(weight);
  return converted && weight !== '' && Number.isFinite(number) ? Math.round(number * 2) / 2 : weight;
}

// ---- Celebrating a record -----------------------------------------------------
// The record an exercise has set so far in the workout in progress, as newRecords words it, or ''. It changes when a set
// beats it again (a heavier weight), so logSet compares it before and after a set.
function exerciseRecord(name) {
  const key = exerciseKey(name);
  const exercises = activeSession.exercises.filter(item => exerciseKey(item.name) === key);
  return newRecords({ exercises, unit:recordUnit(activeSession) }, personalBests)[0] || '';
}

// The goal (see Progress) that a set of this weight reaches for the first time, or null: one for this exercise, met by this set
// and by nothing before it, in this workout or any saved one. Call it before the set is added.
function goalReachedBy(exercise, weight) {
  const key = exerciseKey(exercise.name);
  const stored = readLocalState('goals');
  const goal = stored && stored.value && typeof stored.value === 'object' ? stored.value[key] : null;
  if (!goal || !(goal.target > 0)) return null;
  const unit = goal.unit || 'lbs', from = recordUnit(activeSession);
  if (!(convertWeight(Number(weight) || 0, from, unit) >= goal.target)) return null;
  const earlier = [convertWeight(personalBests[key]?.weight || 0, 'lbs', unit)];
  activeSession.exercises.filter(item => exerciseKey(item.name) === key).forEach(item => (item.sets || []).forEach(set => {
    earlier.push(convertWeight(Number(set.weight) || 0, from, unit));
  }));
  return Math.max(...earlier) < goal.target ? goal : null;
}

// The firework a record sets off (celebrate) is common.js's, shared with the Cardio page.
