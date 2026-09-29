// What was done before: each exercise's last performance (shown as "Last time" and used to fill in the next set), the
// personal records a finished workout is compared with, and the summary shown when one is finished.

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

// ---- The summary of a finished workout -------------------------------------
// How long it took, how much was done, and any new personal records; it stays until Done or the next workout starts.
function showWorkoutSummary(workout, records) {
  const shown = inUnit(workout);
  const sets = shown.exercises.reduce((total, item) => total + item.sets.length, 0);
  // Weight × reps of every set with a weight; a hold's seconds are not reps, so timed exercises are left out.
  const setVolume = set => (Number(set.weight) || 0) * (Number(set.reps) || 0);
  const volume = shown.exercises.filter(item => !isTimed(item)).reduce((total, item) => total + item.sets.reduce((sum, set) => sum + setVolume(set), 0), 0);
  const stats = [
    ...(workout.duration ? [[formatDuration(workout.duration), 'Time']] : []),
    [String(shown.exercises.length), shown.exercises.length === 1 ? 'Exercise' : 'Exercises'],
    [String(sets), sets === 1 ? 'Set' : 'Sets'],
    ...(volume ? [[`${Math.round(volume).toLocaleString()} ${weightUnit()}`, 'Volume']] : [])
  ];
  $('summaryName').textContent = workout.name;
  $('summaryStats').innerHTML = stats.map(([value, label]) => `<li><strong>${escapeHTML(value)}</strong><span>${escapeHTML(label)}</span></li>`).join('');
  $('summaryRecords').hidden = !records.length;
  $('summaryRecordList').innerHTML = records.map(record => `<li>${escapeHTML(record)}</li>`).join('');
  $('workoutSummary').hidden = false;
  $('workoutSummary').scrollIntoView({ behavior:'smooth', block:'start' });
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

$('summaryDone').onclick = () => { $('workoutSummary').hidden = true; };

// ---- Celebrating a record -----------------------------------------------------
// The record an exercise has set so far in the workout in progress, as newRecords words it, or ''. It changes when a set
// beats it again (a heavier weight), so logSet compares it before and after a set.
function exerciseRecord(name) {
  const key = exerciseKey(name);
  const exercises = activeSession.exercises.filter(item => exerciseKey(item.name) === key);
  return newRecords({ exercises, unit:recordUnit(activeSession) }, personalBests)[0] || '';
}

// A small firework: sparks flying out of an element, gone after a second. Skipped for anyone who asks for less motion.
const FIREWORK_COLORS = ['#f5b83d', '#ff6b6b', '#5bd6a4', '#8183f4', '#4cc3ff'];

function celebrate(origin) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const box = origin.getBoundingClientRect();
  const burst = document.createElement('div');
  burst.className = 'firework';
  burst.setAttribute('aria-hidden', 'true');
  burst.style.left = `${box.left + box.width / 2}px`;
  burst.style.top = `${box.top + box.height / 2}px`;
  const sparks = 28;
  for (let i = 0; i < sparks; i++) {
    const angle = (i / sparks) * 2 * Math.PI + Math.random() * 0.3;
    const distance = 60 + Math.random() * 70;
    const spark = document.createElement('i');
    spark.style.setProperty('--dx', `${Math.cos(angle) * distance}px`);
    spark.style.setProperty('--dy', `${Math.sin(angle) * distance}px`);
    spark.style.background = FIREWORK_COLORS[i % FIREWORK_COLORS.length];
    burst.appendChild(spark);
  }
  document.body.appendChild(burst);
  setTimeout(() => burst.remove(), 1200);
}
