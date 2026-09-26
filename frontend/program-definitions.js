// The training programs the app offers. program.js does everything programs share: saving and syncing the one being
// followed, the program card, the setup form, starting a day as a workout and recording it once it is finished. Each
// definition here supplies the rest:
//
//   id, name, shortName, summary, schedule  how the program is listed; workouts are named "<shortName> <day name>"
//   block                    what one pass through the plan is called ('cycle', 'week'); days are done block by block
//   numbersLabel             what the one number kept per lift is ('Training maxes', 'Working weights')
//   lifts                    [{ key, name, increment }], one number each, asked for at setup
//   oneRepMaxes              true if setup may take one-rep maxes and convert them (see toNumber)
//   options                  settings asked for at setup: { id, type:'select' | 'check', label, choices, default, help, ... }
//   weeks(program)           the weeks of a block, [{ name, summary }]
//   days(program)            the days of each week, [{ name }]
//   workout(program, week, day)  the day's exercises; each has a plan, one entry per set: { weight, reps } plus
//                            repsMax for a rep range, amrap for a + set, warmup, percent. A weight of '' is the lifter's call.
//   afterWorkout(program, day, entry, exercises)  optional: progress made by one session, as { program, note };
//                            exercises are the finished workout's, with each exercise's plan and logged sets
//   nextBlock(program)       optional: what changes when a block is complete, e.g. new training maxes
//   numberNote(program, lift)  { text, warn } under each lift's number on the card
//   setup                    { intro(editing), estimated, estimate(lift), hint(lift, value, form), toNumber(value, form, lift) }
//
// A program's first exercise each day is its main lift. Stored programs keep their numbers in trainingMaxes whatever
// numbersLabel calls them, so programs saved by earlier versions still load.

const roundingOption = { id:'rounding', type:'select', label:'Round weights to', choices:[{ value:5, label:'The nearest 5 lbs' }, { value:2.5, label:'The nearest 2.5 lbs' }] };

function repeatSets(count, set) {
  return Array.from({ length:count }, () => ({ ...set }));
}

// ---- Wendler 5/3/1 --------------------------------------------------------

// In the order the days are trained. Upper-body training maxes go up 5 lbs a cycle, lower-body ones 10.
const wendlerLifts = [
  { key:'press', name:'Overhead Press', day:'Press Day', increment:5 },
  { key:'deadlift', name:'Deadlift', day:'Deadlift Day', increment:10 },
  { key:'bench', name:'Bench Press', day:'Bench Day', increment:5 },
  { key:'squat', name:'Back Squat', day:'Squat Day', increment:10 }
];
// [percent of the training max, reps]. The last set of a working week is a + set: as many reps as possible, at least the number given.
const wendlerWeeks = [
  { name:'5s week', sets:[[65, 5], [75, 5], [85, 5]] },
  { name:'3s week', sets:[[70, 3], [80, 3], [90, 3]] },
  { name:'5/3/1 week', sets:[[75, 5], [85, 3], [95, 1]] },
  { name:'Deload week', sets:[[40, 5], [50, 5], [60, 5]], deload:true }
].map(week => ({ ...week, summary:`${week.sets.map(([percent]) => `${percent}%`).join(' · ')}${week.deload ? ' · main lift only' : ''}` }));
const wendlerWarmups = [[40, 5], [50, 5], [60, 3]];
const wendlerAssistance = [
  { id:'bbb', name:'Boring But Big', description:'5 sets of 10 of the day’s lift at 50% of its training max, then one assistance exercise.',
    supplemental:{ label:'BBB', percent:50, sets:5, reps:10 },
    exercises:{ press:[['Chin-up', 5, 10]], deadlift:[['Hanging Leg Raise', 5, 15]], bench:[['Dumbbell Row', 5, 10]], squat:[['Leg Curl', 5, 10]] } },
  { id:'triumvirate', name:'Triumvirate', description:'Two assistance exercises of 5 sets each after the main lift.',
    exercises:{ press:[['Dip', 5, 15], ['Chin-up', 5, 10]], deadlift:[['Good Morning', 5, 12], ['Hanging Leg Raise', 5, 15]], bench:[['Dumbbell Bench Press', 5, 15], ['Dumbbell Row', 5, 10]], squat:[['Leg Press', 5, 15], ['Leg Curl', 5, 10]] } },
  { id:'none', name:'Main lifts only', description:'Just the day’s main lift.', exercises:{} }
];

function wendlerWeekPlans(program) {
  return program.options.deload ? wendlerWeeks : wendlerWeeks.filter(week => !week.deload);
}

// Next cycle's training maxes: each goes up by its lift's increment, unless one of its + sets this cycle fell short,
// which means the training max has got ahead of the lifter, so it drops to 90% of itself.
function wendlerNextMaxes(program) {
  const weeks = wendlerWeekPlans(program);
  return wendlerLifts.map((lift, day) => {
    const from = program.trainingMaxes[lift.key];
    const reset = weeks.some((week, index) => missedAmrap(program.done[dayKey(index, day)]?.amrap));
    return { lift:lift.key, from, to:reset ? roundToStep(from * 0.9, program.options.rounding) : from + lift.increment, reset };
  });
}

const wendler531 = {
  id:'wendler-531',
  name:'Wendler 5/3/1',
  shortName:'5/3/1',
  summary:'One main lift a day: overhead press, deadlift, bench press and squat. Each week builds to a heavy set of as many reps as you can, and every training max goes up after each cycle.',
  schedule:'4 days a week · 4-week cycles',
  block:'cycle',
  numbersLabel:'Training maxes',
  lifts:wendlerLifts,
  oneRepMaxes:true,
  options:[
    { id:'tmPercent', type:'select', label:'Training max', oneRepMaxOnly:true,
      choices:[{ value:90, label:'90% of your one-rep max (the original program)' }, { value:85, label:'85% of your one-rep max (5/3/1 Forever)' }] },
    { id:'assistance', type:'select', label:'Assistance work', choices:wendlerAssistance.map(item => ({ value:item.id, label:item.name, help:item.description })) },
    roundingOption,
    { id:'warmups', type:'check', label:'Warm up with 40%, 50% and 60% of the training max before the work sets', default:true },
    { id:'deload', type:'check', label:'End each cycle with a deload week', default:true }
  ],
  // Without the deload week each cycle is three weeks long.
  weeks:wendlerWeekPlans,
  days:() => wendlerLifts.map(lift => ({ name:lift.day })),
  workout(program, week, day) {
    const lift = wendlerLifts[day];
    const weekPlan = wendlerWeekPlans(program)[week];
    const trainingMax = program.trainingMaxes[lift.key];
    const set = ([percent, reps], extra = {}) => ({ percent, weight:roundToStep(trainingMax * percent / 100, program.options.rounding), reps, ...extra });
    // Warm-ups, except in the deload week, whose sets are that light already; then the week's sets, the last a + set.
    const warmups = program.options.warmups && !weekPlan.deload ? wendlerWarmups.map(entry => set(entry, { warmup:true })) : [];
    const main = [...warmups, ...weekPlan.sets.map((entry, index) => set(entry, !weekPlan.deload && index === weekPlan.sets.length - 1 ? { amrap:true } : {}))];
    const top = main[main.length - 1];
    const exercises = [{ name:lift.name, weight:top.weight, reps:String(top.reps), plan:main }];
    // The deload week is the main lift alone, to recover.
    if (weekPlan.deload) return exercises;
    const assistance = wendlerAssistance.find(item => item.id === program.options.assistance);
    const extra = assistance.supplemental;
    if (extra) {
      const weight = roundToStep(trainingMax * extra.percent / 100, program.options.rounding);
      exercises.push({ name:`${lift.name} (${extra.label})`, weight, reps:String(extra.reps), plan:repeatSets(extra.sets, { percent:extra.percent, weight, reps:extra.reps }) });
    }
    (assistance.exercises[lift.key] || []).forEach(([name, sets, reps]) => exercises.push({ name, weight:'', reps:String(reps), plan:repeatSets(sets, { weight:'', reps }) }));
    return exercises;
  },
  nextBlock(program) {
    const changes = wendlerNextMaxes(program);
    return { trainingMaxes:Object.fromEntries(changes.map(change => [change.lift, change.to])), lastRollover:{ cycle:program.cycle, changes } };
  },
  numberNote(program, lift) {
    const next = wendlerNextMaxes(program).find(change => change.lift === lift.key);
    return next.reset ? { text:`Resets to ${next.to} next cycle`, warn:true } : { text:`Next cycle: ${next.to}`, warn:false };
  },
  setup:{
    intro:editing => editing
      ? 'Change a training max when the weights feel too heavy or too light. The rest of this cycle uses the new numbers, and later cycles build on them.'
      : 'Enter a recent one-rep max for each lift, or switch to training maxes if you already know yours. Every weight in the program is worked out from these.',
    estimated:'Lifts you have logged are filled in with an estimate from your latest sets.',
    estimate:lift => estimatedOneRepMax(lift.name),
    // What a number works out to: the training max from a one-rep max, or the cycle's heaviest set from a training max.
    hint(lift, value, form) {
      const trainingMax = value && wendler531.setup.toNumber(value, form);
      if (!trainingMax) return '';
      return form.oneRepMax ? `Training max ${trainingMax} lbs` : `Heaviest set ${roundToStep(trainingMax * 0.95, form.options.rounding)} lbs`;
    },
    toNumber:(value, form) => form.oneRepMax ? roundToStep(value * form.options.tmPercent / 100, form.options.rounding) : value
  }
};

// ---- Reddit PPL -----------------------------------------------------------
// /u/Metallicadpa's "A Linear Progression Based PPL Program for Beginners" (r/Fitness, 2015).

// Weight goes on every session the lift's sets are all done: 5 lbs, or 10 for the deadlift.
const pplLifts = [
  { key:'deadlift', name:'Deadlift', increment:10 },
  { key:'row', name:'Barbell Row', increment:5 },
  { key:'bench', name:'Bench Press', increment:5 },
  { key:'press', name:'Overhead Press', increment:5 },
  { key:'squat', name:'Back Squat', increment:5 }
];
// Sets of 5 before the last set, a + set of at least 5: deadlifts 1x5+, squats 2x5, 1x5+, the rest 4x5, 1x5+.
const pplStraightSets = { deadlift:0, row:4, bench:4, press:4, squat:2 };
// [name, sets, fewest reps, most reps, note]. Accessories go up in weight once every set reaches the top of the range.
const pplPull = [['Lat Pulldown', 3, 8, 12], ['Seated Cable Row', 3, 8, 12], ['Face Pull', 5, 15, 20], ['Hammer Curl', 4, 8, 12], ['Dumbbell Curl', 4, 8, 12]];
// Push days finish with the other press for volume, then triceps work supersetted with lateral raises.
const pplPush = otherPress => [
  [`${otherPress} (volume)`, 3, 8, 12], ['Incline Dumbbell Press', 3, 8, 12],
  ['Tricep Pushdown', 3, 8, 12, 'Superset with the lateral raises that follow'], ['Lateral Raise', 3, 15, 20],
  ['Overhead Tricep Extension', 3, 8, 12, 'Superset with the lateral raises that follow'], ['Lateral Raise', 3, 15, 20]
];
const pplLegs = [['Romanian Deadlift', 3, 8, 12], ['Leg Press', 3, 8, 12], ['Leg Curl', 3, 8, 12], ['Calf Raise', 5, 8, 12]];
// Pull, push and legs twice a week. The pull days alternate deadlifts and rows, the push days bench and overhead press.
const pplDays = [
  { name:'Pull (Deadlift)', lift:'deadlift', accessories:pplPull },
  { name:'Push (Bench)', lift:'bench', accessories:pplPush('Overhead Press') },
  { name:'Legs', lift:'squat', accessories:pplLegs },
  { name:'Pull (Row)', lift:'row', accessories:pplPull },
  { name:'Push (Overhead Press)', lift:'press', accessories:pplPush('Bench Press') },
  { name:'Legs', lift:'squat', accessories:pplLegs }
];

// Three failed sessions in a row at one weight mean it is time to take 10% off and work back up.
function pplDeload(program, lift) {
  return roundToStep(program.trainingMaxes[lift.key] * 0.9, program.options.rounding);
}

const redditPpl = {
  id:'reddit-ppl',
  name:'Reddit PPL',
  shortName:'PPL',
  summary:'Pull, push and legs, twice a week each. Every day starts with a heavy barbell lift that goes up each session you get all its reps, then higher-rep accessory work.',
  schedule:'6 days a week · weight added every session',
  block:'week',
  numbersLabel:'Working weights',
  lifts:pplLifts,
  oneRepMaxes:false,
  options:[{ ...roundingOption, help:'Used when a lift drops 10% after three missed sessions.' }],
  weeks:() => [{ name:'Week', summary:'' }],
  days:() => pplDays,
  workout(program, week, day) {
    const plan = pplDays[day];
    const lift = pplLifts.find(item => item.key === plan.lift);
    const weight = program.trainingMaxes[lift.key];
    const main = [...repeatSets(pplStraightSets[lift.key], { weight, reps:5 }), { weight, reps:5, amrap:true }];
    return [{ name:lift.name, weight, reps:'5', plan:main },
      ...plan.accessories.map(([name, sets, reps, repsMax, note]) => ({ name, weight:'', reps:String(reps), ...(note ? { note } : {}), plan:repeatSets(sets, { weight:'', reps, repsMax }) }))];
  },
  // The main lift moves after every session: up when every set got its reps, down 10% after a third miss in a row.
  // A session where the main lift was not attempted changes nothing.
  afterWorkout(program, day, entry) {
    const lift = pplLifts.find(item => item.key === pplDays[day].lift);
    const weight = program.trainingMaxes[lift.key];
    const set = (to, misses) => ({ ...program, trainingMaxes:{ ...program.trainingMaxes, [lift.key]:to }, stalls:{ ...program.stalls, [lift.key]:misses } });
    if (entry.hit === null) return { program, note:'' };
    if (entry.hit) return { program:set(weight + lift.increment, 0), note:`${lift.name} goes up to ${weight + lift.increment} lbs next time.` };
    const misses = (program.stalls[lift.key] || 0) + 1;
    if (misses < 3) return { program:set(weight, misses), note:`${lift.name} stays at ${weight} lbs: ${misses} missed session${misses === 1 ? '' : 's'} in a row. A third drops it 10%.` };
    const lowered = pplDeload(program, lift);
    return { program:set(lowered, 0), note:`${lift.name} missed three sessions in a row, so it drops 10% to ${lowered} lbs.` };
  },
  numberNote(program, lift) {
    const misses = program.stalls[lift.key] || 0;
    return misses ? { text:`Missed ${misses} in a row · 3 drops it to ${pplDeload(program, lift)}`, warn:true } : { text:`+${lift.increment} lbs after each good session`, warn:false };
  },
  setup:{
    intro:editing => editing
      ? 'Change a working weight when it is too heavy or too light. Changing one also clears its run of missed sessions.'
      : 'Enter a starting weight for each main lift. The program’s advice: work up in sets of 5 until the bar slows down, then take off 5 lbs.',
    estimated:'Lifts you have logged are filled in with your heaviest set of 5 or more last time.',
    estimate:lift => heaviestSetOfFive(lift.name),
    hint:lift => `+${lift.increment} lbs each good session`,
    toNumber:value => value
  }
};

// ---- Apartment Gym --------------------------------------------------------
// Strength training on the equipment of a typical apartment gym: dumbbells up to about 50 lbs, an adjustable bench, a
// cable stack with a single handle, and chest press, lat pulldown, leg extension and leg curl machines. No barbell.

// Double progression: a main lift stays at its weight until every set reaches the top of its rep range, then goes up.
// Machines go up by one plate of their stack; dumbbells by 5 lbs a hand, until they reach the heaviest pair there is.
const apartmentLifts = [
  { key:'chestPress', name:'Machine Chest Press', sets:4, reps:6, repsMax:10 },
  { key:'splitSquat', name:'Dumbbell Bulgarian Split Squat', sets:3, reps:8, repsMax:12, dumbbell:true, note:'Weight per dumbbell, reps per leg' },
  { key:'pulldown', name:'Lat Pulldown', sets:4, reps:6, repsMax:10 },
  { key:'rdl', name:'Dumbbell Romanian Deadlift', sets:4, reps:8, repsMax:12, dumbbell:true, note:'Weight per dumbbell' }
];
const apartmentDumbbellStep = 5;
// [name, sets, fewest reps, most reps, note]. The weight is the lifter's call; the app says to go heavier once every
// set reached the top of the range.
const apartmentDays = [
  { name:'Upper A', lift:'chestPress', accessories:[
    ['Incline Dumbbell Press', 3, 8, 12, 'Bench at 30–45°'], ['Single-Arm Cable Pulldown', 3, 10, 12, 'Half-kneeling, one handle, reps per arm'],
    ['Single-Arm Cable Row', 3, 10, 12, 'One handle, reps per arm'], ['Dumbbell Lateral Raise', 3, 12, 15],
    ['Single-Arm Cable Pushdown', 3, 10, 15, 'One handle, reps per arm']] },
  { name:'Lower A', lift:'splitSquat', accessories:[
    ['Single-Leg Dumbbell Romanian Deadlift', 3, 8, 12, 'Reps per leg'], ['Leg Curl', 3, 10, 15], ['Leg Extension', 3, 10, 15],
    ['Single-Leg Dumbbell Calf Raise', 3, 12, 20, 'Reps per leg'], ['Pallof Press', 3, 10, 12, 'Cable at chest height, reps per side']] },
  { name:'Upper B', lift:'pulldown', accessories:[
    ['Dumbbell Bench Press', 3, 8, 12], ['Chest-Supported Dumbbell Row', 3, 8, 12, 'Face down on the bench at 30–45°'],
    ['Seated Dumbbell Shoulder Press', 3, 8, 12, 'Bench upright'], ['Single-Arm Cable Rear Delt Fly', 3, 12, 15, 'One handle, reps per arm'],
    ['Dumbbell Hammer Curl', 3, 10, 12]] },
  { name:'Lower B', lift:'rdl', accessories:[
    ['Goblet Squat', 3, 10, 15, 'One dumbbell held at the chest'], ['Dumbbell Step-Up', 3, 8, 12, 'Onto a sturdy flat bench, reps per leg'],
    ['Leg Curl', 3, 8, 12], ['Leg Extension', 3, 12, 15], ['Cable Woodchop', 3, 10, 12, 'One handle, reps per side']] }
];

function apartmentLift(key) {
  return apartmentLifts.find(lift => lift.key === key);
}

function apartmentStep(options, lift) {
  return lift.dumbbell ? apartmentDumbbellStep : options.machineStep;
}

// At or past the heaviest dumbbells there is no heavier weight to move to.
function apartmentCapped(program, lift) {
  return Boolean(lift.dumbbell) && program.trainingMaxes[lift.key] >= program.options.dumbbellMax;
}

// Three sessions in a row below the rep range mean the weight has got ahead of the lifter: take off 10%.
function apartmentDeload(program, lift) {
  return roundToStep(program.trainingMaxes[lift.key] * 0.9, apartmentStep(program.options, lift));
}

// Whether every planned set of the day's main lift (its first exercise) was logged at the top of its rep range.
function reachedTopOfRange(exercises) {
  const main = exercises[0];
  if (!main || !Array.isArray(main.plan) || !(main.sets || []).length) return false;
  return main.plan.every((set, index) => set.warmup || (Boolean(main.sets[index]) && storedNumber(main.sets[index].reps) >= storedNumber(set.repsMax || set.reps)));
}

const apartmentGym = {
  id:'apartment-gym',
  name:'Apartment Gym',
  shortName:'Apartment Gym',
  summary:'Strength training with dumbbells up to 50 lbs, an adjustable bench, a cable stack with one handle, and chest press, lat pulldown, leg extension and leg curl machines. Upper and lower body twice a week each; a main lift goes up once every set reaches the top of its rep range.',
  schedule:'4 days a week · upper and lower body twice each',
  block:'week',
  numbersLabel:'Working weights',
  lifts:apartmentLifts,
  oneRepMaxes:false,
  options:[
    { id:'dumbbellMax', type:'select', label:'Heaviest dumbbells', default:50,
      choices:[20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100].map(value => ({ value, label:`${value} lbs each` })),
      help:'The dumbbell lifts go up to this and no further. After that the program makes them harder by slowing them down instead.' },
    { id:'machineStep', type:'select', label:'Weight stack steps',
      choices:[{ value:10, label:'10 lbs a plate (most stacks)' }, { value:5, label:'5 lbs (half plates or add-on weights)' }, { value:15, label:'15 lbs a plate' }],
      help:'How much the chest press and lat pulldown go up at a time.' }
  ],
  weeks:() => [{ name:'Week', summary:'' }],
  days:() => apartmentDays,
  workout(program, week, day) {
    const plan = apartmentDays[day];
    const lift = apartmentLift(plan.lift);
    const weight = program.trainingMaxes[lift.key];
    return [{ name:lift.name, weight, reps:String(lift.reps), ...(lift.note ? { note:lift.note } : {}), plan:repeatSets(lift.sets, { weight, reps:lift.reps, repsMax:lift.repsMax }) },
      ...plan.accessories.map(([name, sets, reps, repsMax, note]) => ({ name, weight:'', reps:String(reps), ...(note ? { note } : {}), plan:repeatSets(sets, { weight:'', reps, repsMax }) }))];
  },
  // Every set at the top of the range: up a step next time (or, at the heaviest dumbbells, slower reps instead).
  // A set below the bottom of the range counts a miss; the third in a row takes 10% off. Anything between keeps the
  // weight and clears the misses. A session where the main lift was not attempted changes nothing.
  afterWorkout(program, day, entry, exercises) {
    const lift = apartmentLift(apartmentDays[day].lift);
    const weight = program.trainingMaxes[lift.key];
    const set = (to, misses) => ({ ...program, trainingMaxes:{ ...program.trainingMaxes, [lift.key]:to }, stalls:{ ...program.stalls, [lift.key]:misses } });
    if (entry.hit === null) return { program, note:'' };
    if (reachedTopOfRange(exercises)) {
      if (apartmentCapped(program, lift)) {
        return { program:set(weight, 0), note:`${lift.name} reached ${lift.repsMax} reps on every set with your heaviest dumbbells. Keep them, and make it harder: lower each rep over 3 seconds and pause at the bottom.` };
      }
      const to = lift.dumbbell ? Math.min(weight + apartmentDumbbellStep, program.options.dumbbellMax) : weight + program.options.machineStep;
      return { program:set(to, 0), note:`${lift.name} goes up to ${to} lbs next time: every set reached ${lift.repsMax} reps.` };
    }
    if (entry.hit) return { program:set(weight, 0), note:`${lift.name} stays at ${weight} lbs until every set reaches ${lift.repsMax} reps.` };
    const misses = (program.stalls[lift.key] || 0) + 1;
    if (misses < 3) return { program:set(weight, misses), note:`${lift.name} stays at ${weight} lbs: ${misses} session${misses === 1 ? '' : 's'} in a row below ${lift.reps} reps. A third drops it 10%.` };
    const lowered = apartmentDeload(program, lift);
    return { program:set(lowered, 0), note:`${lift.name} fell below ${lift.reps} reps three sessions in a row, so it drops 10% to ${lowered} lbs.` };
  },
  numberNote(program, lift) {
    const misses = program.stalls[lift.key] || 0;
    if (misses) return { text:`Missed ${misses} in a row · 3 drops it to ${apartmentDeload(program, lift)}`, warn:true };
    if (apartmentCapped(program, lift)) return { text:'Heaviest dumbbells · progress by slowing the reps', warn:false };
    return { text:`+${apartmentStep(program.options, lift)} lbs once every set reaches ${lift.repsMax}`, warn:false };
  },
  setup:{
    intro:editing => editing
      ? 'Change a working weight when it is too heavy or too light. Changing one also clears its run of missed sessions.'
      : 'Enter a starting weight for each main lift: one you could lift for the bottom of its rep range with two reps to spare. Dumbbell weights are per hand.',
    estimated:'Lifts you have logged are filled in with your heaviest set of 8 or more last time.',
    estimate:lift => heaviestSetOf(lift.name, 8),
    hint(lift, value, form) {
      if (lift.dumbbell && value > form.options.dumbbellMax) return `Capped at ${form.options.dumbbellMax} lbs, your heaviest dumbbells`;
      return `+${apartmentStep(form.options, lift)} lbs once every set reaches ${lift.repsMax}`;
    },
    // A dumbbell lift cannot start heavier than the heaviest dumbbells.
    toNumber:(value, form, lift) => lift.dumbbell ? Math.min(value, form.options.dumbbellMax) : value
  }
};

const programDefinitions = [wendler531, redditPpl, apartmentGym];
