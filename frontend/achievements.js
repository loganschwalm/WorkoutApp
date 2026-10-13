// Achievements, weekly streaks and the encouraging lines: what makes a workout feel like progress. Loaded on the Strength,
// Cardio, Progress and History pages, after records.js and cardio-activities.js where a page has them, before the page's
// own script.
//
// Achievements are worked out from the workouts every time, never stored: the history is replayed oldest first, and each
// tier is earned by the workout that first took its measure past it. So they follow every device and an import, need no
// migration, and a workout edited or deleted in History takes back what it earned. Two of them depend on a setting: the
// weekly streak is counted against the weekly goal as it is now, and the weight and distance tiers are in the units shown.
// A finished workout is told what it earned by comparing the history before it with the history after it, and only when
// the whole history is in hand: a missed award is better than a false one.

// ---- Sessions and weeks -------------------------------------------------------

// Each session once: one that has uploaded and is still in the queue is the same session, told by its clientId (or id).
// One with neither is its own.
function uniqueSessions(sessions) {
  const seen = new Set();
  return sessions.filter(session => {
    const key = session && (session.clientId ? `c:${session.clientId}` : session.id !== undefined && session.id !== null ? `i:${session.id}` : null);
    if (!key) return true;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// Sessions in each week, by its Monday's day key: strength and cardio alike, as the History calendar counts them.
function weekCountsOf(sessions) {
  const weeks = new Map();
  sessions.forEach(session => {
    const week = calendarDayKey(startOfWeek(new Date(session.createdAt)));
    weeks.set(week, (weeks.get(week) || 0) + 1);
  });
  return weeks;
}

// The current run of weeks at the goal, and the longest. This week counts once it reaches the goal; until then it is
// still in progress, so the run is counted from last week and nothing is lost yet.
function weeklyStreaks(weeks, goal, thisWeek) {
  const reached = monday => (weeks.get(calendarDayKey(monday)) || 0) >= goal;
  let current = reached(thisWeek) ? 1 : 0;
  for (let monday = addDays(thisWeek, -7); reached(monday); monday = addDays(monday, -7)) current += 1;
  const mondays = [...weeks.keys()].sort();
  let best = current, run = 0;
  if (mondays.length) {
    const [year, month, day] = mondays[0].split('-').map(Number);
    for (let monday = new Date(year, month - 1, day); monday <= thisWeek; monday = addDays(monday, 7)) {
      run = reached(monday) ? run + 1 : 0;
      best = Math.max(best, run);
    }
  }
  return { current, best };
}

// The longest run before the current one (`current` weeks, from weeklyStreaks), so a current run past it is a new best:
// weeklyStreaks' best includes the current run, so it cannot say that itself.
function bestStreakBefore(weeks, goal, thisWeek, current) {
  const reached = monday => (weeks.get(calendarDayKey(monday)) || 0) >= goal;
  // The current run ends this week once it has reached the goal, and last week until then.
  const runStart = addDays(reached(thisWeek) ? thisWeek : addDays(thisWeek, -7), -7 * Math.max(0, current - 1));
  const before = current ? runStart : addDays(thisWeek, 7);
  const mondays = [...weeks.keys()].sort();
  let best = 0, run = 0;
  if (mondays.length) {
    const [year, month, day] = mondays[0].split('-').map(Number);
    for (let monday = new Date(year, month - 1, day); monday < before; monday = addDays(monday, 7)) {
      run = reached(monday) ? run + 1 : 0;
      best = Math.max(best, run);
    }
  }
  return best;
}

// ---- The catalogue --------------------------------------------------------------

// The lifts the plate tiers are for, by exerciseKey: these names only, so a dumbbell bench or a front squat is not one.
const plateLifts = {
  bench:['bench press', 'barbell bench press', 'bench', 'flat bench press', 'bb bench press'],
  squat:['squat', 'back squat', 'barbell squat', 'barbell back squat', 'high bar squat', 'low bar squat'],
  deadlift:['deadlift', 'barbell deadlift', 'conventional deadlift', 'sumo deadlift']
};
// Which of plateLifts an exercise is, or null.
function plateLiftOf(name) {
  const key = exerciseKey(name ?? '');
  return Object.keys(plateLifts).find(lift => plateLifts[lift].includes(key)) || null;
}

// A 45 lb or 20 kg bar with one, two, three and four big plates a side, in the unit a set was logged in.
const plateWeights = { lbs:[135, 225, 315, 405], kg:[60, 100, 140, 180] };
const achievementDay = 86400000;

function plateDetail(tier) {
  return `${plateWeights.lbs[tier - 1]} lbs or ${plateWeights.kg[tier - 1]} kg on the bar`;
}

// Each family: what it measures (a metric the replay keeps), its tiers (which may depend on the units shown), a name for
// each tier, a line saying what it took, and how its measure reads on Progress ('' when there is nothing to say yet).
const achievementFamilies = [
  { id:'workouts', title:'Workouts', metric:'workouts', tiers:() => [1, 10, 25, 50, 100, 250, 500, 1000],
    name:tier => tier === 1 ? 'First workout' : `${tier.toLocaleString()} workouts`, detail:() => 'Strength workouts and cardio sessions, all counted',
    reads:value => plural(value, 'workout') },
  { id:'streak', title:'Weekly streak', metric:'streak', tiers:() => [2, 4, 8, 12, 26, 52],
    name:tier => `${tier}-week streak`, detail:(tier, context) => `${tier} weeks in a row at your goal of ${context.goal} a week`,
    reads:value => `best ${plural(value, 'week')}` },
  { id:'records', title:'Personal records', metric:'records', tiers:() => [1, 10, 25, 50, 100],
    name:tier => tier === 1 ? 'First personal record' : `${tier} personal records`, detail:() => 'Records beaten, as each workout told you them',
    reads:value => plural(value, 'record') },
  { id:'bench', title:'Bench press', metric:'bench', tiers:() => [1, 2, 3],
    name:tier => `Bench press: ${plural(tier, 'plate')}`, detail:plateDetail, reads:value => value ? `${plural(value, 'plate')} a side` : '' },
  { id:'squat', title:'Squat', metric:'squat', tiers:() => [1, 2, 3, 4],
    name:tier => `Squat: ${plural(tier, 'plate')}`, detail:plateDetail, reads:value => value ? `${plural(value, 'plate')} a side` : '' },
  { id:'deadlift', title:'Deadlift', metric:'deadlift', tiers:() => [1, 2, 3, 4],
    name:tier => `Deadlift: ${plural(tier, 'plate')}`, detail:plateDetail, reads:value => value ? `${plural(value, 'plate')} a side` : '' },
  { id:'volume', title:'Weight lifted', metric:'volume', tiers:context => context.unit === 'kg' ? [5000, 50000, 250000, 500000] : [10000, 100000, 500000, 1000000],
    name:(tier, context) => `${tier.toLocaleString()} ${context.unit} lifted`, detail:() => 'Every set’s weight times its reps, added up',
    reads:(value, context) => `${Math.round(value).toLocaleString()} ${context.unit}` },
  { id:'distance', title:'Distance covered', metric:'distance', tiers:context => context.distanceUnit === 'km' ? [25, 100, 250, 500, 1000] : [10, 50, 100, 250, 500],
    name:(tier, context) => `${tier.toLocaleString()} ${context.distanceUnit} covered`, detail:() => 'Walks, runs, rides and the machines that count miles',
    reads:(value, context) => `${Math.round(value * 10) / 10} ${context.distanceUnit}` },
  { id:'cardioTime', title:'Cardio time', metric:'cardioSeconds', tiers:() => [5, 25, 50, 100].map(hours => hours * 3600),
    name:tier => `${tier / 3600} hours of cardio`, detail:() => 'Every cardio session’s time, added up',
    reads:value => `${Math.round(value / 360) / 10} h` },
  { id:'exercises', title:'Exercises tried', metric:'exercises', tiers:() => [5, 15, 30],
    name:tier => `${tier} different exercises`, detail:() => 'Each exercise counted once, however often it is done',
    reads:value => plural(value, 'exercise') },
  { id:'bigWeek', title:'Big week', metric:'weekDays', tiers:() => [5, 7],
    name:tier => tier === 7 ? 'Seven days in one week' : 'Five days in one week', detail:tier => `Trained on ${tier} different days, Monday to Sunday`,
    reads:value => `best ${plural(value, 'day')} in a week` },
  { id:'comeback', title:'Back at it', metric:'comeback', tiers:() => [1],
    name:() => 'Back at it', detail:() => 'A workout after two weeks or more off', reads:() => '' }
];

// The units and goal achievements are counted in: those shown, unless said otherwise.
function achievementContext(options = {}) {
  const settings = getWorkoutSettings();
  return { unit:options.unit || weightUnit(), distanceUnit:options.distanceUnit || distanceUnitOf(settings),
    goal:options.goal || weeklyGoalFrom(settings.weeklyGoal) };
}

// Which session earned something, to tell this workout's from the rest.
function achievementSessionKey(session) {
  return session.clientId ? `c:${session.clientId}` : session.id !== undefined && session.id !== null ? `i:${session.id}` : `t:${session.createdAt}`;
}

// Plates a side in a set, by the set's own unit: 225 lbs is two, and so is 100 kg.
function platesIn(weight, unit) {
  return plateWeights[unit === 'kg' ? 'kg' : 'lbs'].filter(threshold => weight >= threshold).length;
}

// Replays the sessions oldest first. Returns { families:[{ id, title, tiers, earned:[{ at, by }], value, ... }], earned:[{ id,
// family, tier, name, detail, at, by }] }, earned tiers in the order they were earned. Records are counted as each workout
// was told them: newRecords (records.js) for a strength workout, against the bests before it, and the cardio records
// (cardio-activities.js) for a session.
function achievementsOf(sessions, options = {}) {
  const context = achievementContext(options);
  const entries = achievementFamilies.map(family => ({ family, tiers:family.tiers(context), earned:[] }));
  const metrics = { workouts:0, streak:0, records:0, bench:0, squat:0, deadlift:0, volume:0, distance:0, cardioSeconds:0, exercises:0, weekDays:0, comeback:0 };
  const weeks = new Map(), weekDays = new Map(), exercises = new Set();
  const cardioBestsSoFar = new Map();
  let bests = {}, previousAt = null;
  [...uniqueSessions(sessions)].sort((a, b) => a.createdAt - b.createdAt).forEach(session => {
    metrics.workouts += 1;
    if (previousAt !== null && session.createdAt - previousAt >= 14 * achievementDay) metrics.comeback = 1;
    previousAt = session.createdAt;
    // The streak: when this session takes its week to the goal, the run of weeks at it that ends here.
    const date = new Date(session.createdAt);
    const week = calendarDayKey(startOfWeek(date));
    weeks.set(week, (weeks.get(week) || 0) + 1);
    if (weeks.get(week) === context.goal) {
      let run = 1;
      for (let monday = addDays(startOfWeek(date), -7); (weeks.get(calendarDayKey(monday)) || 0) >= context.goal; monday = addDays(monday, -7)) run += 1;
      metrics.streak = Math.max(metrics.streak, run);
    }
    const days = weekDays.get(week) || new Set();
    days.add(calendarDayKey(date));
    weekDays.set(week, days);
    metrics.weekDays = Math.max(metrics.weekDays, days.size);
    if (isCardio(session)) {
      const key = cardioKey(session), had = cardioBestsSoFar.get(key);
      if (had) metrics.records += cardioRecordsAgainst(session, had).length;
      addToCardioBests(cardioBestsSoFar, session);
      metrics.cardioSeconds += Number(session.duration) > 0 ? Number(session.duration) : 0;
      const distance = Number(session.cardio && session.cardio.distance);
      if (distance > 0 && activityOf(session).distance === 'road') metrics.distance += convertDistance(distance, enteredDistanceUnit(session), context.distanceUnit);
    } else {
      metrics.records += newRecords(session, bests).length;
      bests = mergeBests(bests, session);
      const from = recordUnit(session);
      (session.exercises || []).forEach(item => {
        const key = exerciseKey(item.name ?? '');
        const sets = item.sets || [{ weight:item.weight, reps:item.reps }];
        if (!key || !sets.length) return;
        exercises.add(key);
        if (isTimed(item)) return;
        const lift = plateLiftOf(key);
        sets.forEach(set => {
          const weight = Number(set.weight) || 0, reps = Number(set.reps) || 0;
          if (!(weight > 0) || reps < 1) return;
          metrics.volume += convertWeight(weight, from, context.unit) * reps;
          if (lift) metrics[lift] = Math.max(metrics[lift], platesIn(weight, from));
        });
      });
      metrics.exercises = exercises.size;
    }
    entries.forEach(entry => {
      while (entry.earned.length < entry.tiers.length && metrics[entry.family.metric] >= entry.tiers[entry.earned.length]) {
        entry.earned.push({ at:session.createdAt, by:achievementSessionKey(session) });
      }
    });
  });
  const families = entries.map(({ family, tiers, earned }) => ({ id:family.id, title:family.title, tiers, earned, value:metrics[family.metric],
    reads:family.reads(metrics[family.metric], context), next:tiers[earned.length] ?? null,
    nextName:earned.length < tiers.length ? family.name(tiers[earned.length], context) : '' }));
  const earned = entries.flatMap(({ family, tiers, earned: got }) => got.map((when, index) => ({ id:`${family.id}:${tiers[index]}`, family:family.id, tier:tiers[index],
    name:family.name(tiers[index], context), detail:family.detail(tiers[index], context), at:when.at, by:when.by })))
    .sort((a, b) => a.at - b.at);
  return { families, earned, context };
}

// What one workout or session earned that the history before it had not: the history after it, less the history before.
function achievementsEarnedBy(history, session, options = {}) {
  const had = new Set(achievementsOf(history, options).earned.map(item => item.id));
  return achievementsOf([...history, session], options).earned.filter(item => !had.has(item.id));
}

// Everything a finished workout or session is rewarded with, against the history before it (null when that is not all in
// hand, which earns nothing): what it earned, whether it took the week to the goal, the streak it leaves, and the
// achievements as they stand after it (`after`, achievementsOf's, null without the history), which a shared card draws on.
function finishRewards(history, session) {
  if (!history) return { earned:[], weekReached:false, streak:0, after:null };
  const before = uniqueSessions(history).filter(other => achievementSessionKey(other) !== achievementSessionKey(session));
  const goal = weeklyGoalFrom(getWorkoutSettings().weeklyGoal);
  const monday = startOfWeek(new Date(session.createdAt));
  const weeks = weekCountsOf([...before, session]);
  const had = new Set(achievementsOf(before).earned.map(item => item.id));
  const after = achievementsOf([...before, session]);
  return { earned:after.earned.filter(item => !had.has(item.id)), weekReached:weeks.get(calendarDayKey(monday)) === goal,
    streak:weeklyStreaks(weeks, goal, startOfWeek(new Date())).current, after };
}

// The line about the week and the streak, after a workout: '' when there is nothing to say.
function rewardStreakLine(rewards) {
  if (rewards.weekReached) return rewards.streak >= 2 ? `Weekly goal reached: that's a ${rewards.streak}-week streak.` : 'Weekly goal reached. A streak starts here.';
  return rewards.streak >= 2 ? `${rewards.streak}-week streak, and counting.` : '';
}

// A summary's list of achievements earned: a name and what it took, each, and a button to share it as a card
// (achievement-card.js) where the page has the cards and the achievements as they stand (`after`, finishRewards').
function renderEarnedAchievements(list, earned, after = null) {
  const sharing = Boolean(after) && typeof shareAchievementCard === 'function';
  list.innerHTML = earned.map((item, index) => `<li><strong>${escapeHTML(item.name)}</strong><span>${escapeHTML(item.detail)}</span>`
    + (sharing ? `<button class="link-button achievement-share" type="button" data-share="${index}" aria-label="Share ${escapeHTML(item.name)} as a picture">Share</button>` : '') + '</li>').join('');
  list.onclick = event => {
    const button = event.target.closest('[data-share]');
    if (!button || !sharing) return;
    shareAchievementCard(earned[Number(button.dataset.share)], after).then(said => { if (said) showFeedback(said, 'success'); });
  };
}

// ---- Encouraging lines --------------------------------------------------------------
// Plain words, picked at random when something happens (never while drawing, which would change them under the eyes), and
// not the same line twice in a row. The last is kept for this tab only, and a browser that will not keep it only repeats.

const splashLines = {
  idle:[
    'Every rep counts, even the ones nobody sees.',
    'Show up today. Future you is keeping score.',
    'Small plates add up to big numbers.',
    'Consistency beats intensity. Today counts.',
    'One good session is all today needs.',
    'Strong is built one ordinary set at a time.',
    'The hardest part is starting. You are nearly there.',
    'Progress hides in the boring weeks. Keep stacking them.',
    'Nobody regrets the workout they finished.',
    'Today is a good day to beat last time.'
  ],
  finish:[
    'That is another one in the bank.',
    'Done. This is how it is built, one session at a time.',
    'Good work. Now eat, sleep and come back stronger.',
    'Another workout logged. Future you says thanks.',
    'You showed up and did the work.',
    'Consistency wins again.'
  ],
  record:[
    'New best. That is what all those sets were for.',
    'Stronger than you have ever been.',
    'A personal record. Remember this one.',
    'Yesterday’s limit is today’s warm-up.'
  ],
  achievement:[
    'Achievement unlocked. You earned that one.',
    'A new milestone. Keep it going.',
    'That one is going on the wall.',
    'Look at you, collecting milestones.'
  ],
  cycle:[
    'A whole block done. The numbers go up from here.',
    'Cycle complete. That is planned, honest progress.',
    'Another block in the books. On to the next one.'
  ],
  streak:[
    'Weekly goal reached. That is how streaks are made.',
    'Another week at your goal. Keep the chain going.',
    'Goal met for the week. Everything from here is extra.'
  ]
};

// A line of a kind, not the last one picked. `random` can be given, to pin it.
function splashLine(kind, random = Math.random) {
  const lines = splashLines[kind] || splashLines.idle;
  let last = null;
  try { last = sessionStorage.getItem('workout-tracker-splash'); } catch (error) { last = null; }
  const choices = lines.length > 1 ? lines.filter(line => line !== last) : lines;
  const line = choices[Math.min(choices.length - 1, Math.floor(random() * choices.length))];
  try { sessionStorage.setItem('workout-tracker-splash', line); } catch (error) { /* only a repeat is risked */ }
  return line;
}

// What a finished workout's line is about: the biggest thing it did. `program` is a program day's outcome (program.js), if any.
function rewardSplashKind(rewards, records, program = null) {
  return rewards.earned.length ? 'achievement' : program && program.completed ? 'cycle' : records.length || (program && program.beat) ? 'record'
    : rewards.weekReached ? 'streak' : 'finish';
}
