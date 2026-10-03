// Stalls: a lift whose estimated one-rep max has stopped going up, and the deload that usually gets it moving again.
// The Strength page says so before the first set of a stalled lift, with the lighter weight a tap away, and Progress
// lists every stalled lift. The training programs deload on their own (a missed + set, three missed sessions), so a
// lift a program plans is left to it.
//
// A lift has stalled when its best estimated one-rep max (Epley, sets of up to 12 reps) is at least three weeks old and
// it has been done at least three times since without beating it, the latest within the last three weeks (one not
// trained lately has not stalled, it has stopped). A deload restarts the count: a session at no more than 92% of the
// weight before it is taken as one, and only the sessions from then on are weighed, so a lift working back up from a
// deload is not called stalled again straight away.

const stallWeeks = 3;
const stallSessions = 3;
const stallDay = 86400000;
// What a deload takes off, and how light a session has to be to count as one.
const deloadShare = 0.9;
const deloadSpotted = 0.92;

// Each session of a lift, oldest first: when, its best estimated one-rep max and its heaviest weight. Workouts must be
// in the unit shown (inUnit). A session with no set that gives an estimate (bodyweight, or only long sets) is left out.
function liftSessions(workouts, key) {
  const sessions = [];
  [...workouts].filter(workout => !isCardio(workout)).sort((a, b) => a.createdAt - b.createdAt).forEach(workout => {
    const items = (workout.exercises || []).filter(item => exerciseKey(item.name ?? '') === key && !isTimed(item));
    const sets = items.flatMap(item => item.sets && item.sets.length ? item.sets : item.sets ? [] : [{ weight:item.weight, reps:item.reps }]);
    const scored = sets.map(set => ({ weight:Number(set.weight) || 0, reps:Number(set.reps) || 0 })).filter(set => set.weight > 0 && set.reps >= 1);
    const estimates = scored.filter(set => set.reps <= ONE_REP_MAX_REPS).map(set => exactOneRepMax(set.weight, set.reps));
    if (!estimates.length) return;
    sessions.push({ at:workout.createdAt, best:Math.max(...estimates), heaviest:Math.max(...scored.map(set => set.weight)) });
  });
  return sessions;
}

// The stall of a lift, or null: { best, bestAt, since (sessions since the best), heaviest (last time's), deload (that,
// less a tenth, on the weight step from Settings) }.
function stallOf(workouts, key, now = Date.now()) {
  const sessions = liftSessions(workouts, key);
  // From the latest deload on.
  let start = 0;
  sessions.forEach((session, index) => { if (index && session.heaviest <= sessions[index - 1].heaviest * deloadSpotted) start = index; });
  const weighed = sessions.slice(start);
  if (weighed.length < stallSessions + 1) return null;
  const bestIndex = weighed.reduce((best, session, index) => session.best > weighed[best].best ? index : best, 0);
  const best = weighed[bestIndex], last = weighed[weighed.length - 1];
  const since = weighed.length - 1 - bestIndex;
  if (since < stallSessions || now - best.at < stallWeeks * 7 * stallDay || now - last.at > stallWeeks * 7 * stallDay) return null;
  const step = gymEquipment().step;
  return { best:best.best, bestAt:best.at, since, heaviest:last.heaviest, deload:Math.max(step, Math.round(last.heaviest * deloadShare / step) * step) };
}

// Every stalled lift in the workouts, by exerciseKey, under its latest spelling, the longest stalled first.
function stalledLifts(workouts, now = Date.now()) {
  const names = new Map();
  [...workouts].filter(workout => !isCardio(workout)).sort((a, b) => b.createdAt - a.createdAt)
    .forEach(workout => (workout.exercises || []).forEach(item => {
      const key = exerciseKey(item.name ?? '');
      if (key && !names.has(key)) names.set(key, String(item.name).trim());
    }));
  return [...names].map(([key, name]) => ({ key, name, stall:stallOf(workouts, key, now) })).filter(lift => lift.stall)
    .sort((a, b) => a.stall.bestAt - b.stall.bestAt);
}

// "No new best since Sep 3, over 4 sessions."
function describeStall(stall) {
  const day = new Date(stall.bestAt).toLocaleDateString(undefined, { month:'short', day:'numeric' });
  return `No new best since ${day}, over ${plural(stall.since, 'session')}.`;
}
