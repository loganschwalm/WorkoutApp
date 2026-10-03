// Cardio: the activities a session can be, and how a session's numbers read. Shared by the Cardio page (cardio.js),
// History and Progress. A session is saved as a workout with kind 'cardio', no exercises, its time as duration (in
// seconds), and a cardio object: { activity, distance, distanceUnit, calories, heartRate, floors }, each but activity there
// only when it was given. A distance keeps the unit it was entered in and is only converted for showing, as weights are,
// so switching between miles and kilometres never changes what was logged.

// distance: 'road' is in miles or kilometres (Settings), 'meters' in metres, as a rowing machine counts them; the stair
// climber counts floors instead. rate: how fast a session went, as the activity is usually told: 'pace' is time a mile or
// kilometre (lower is faster), 'speed' miles or kilometres an hour, and 'split' time per 500 metres, a rower's pace.
// 'other' is anything else, under a name of your own (Jump rope, Swimming). settings: what a machine (or a treadmill) was
// set to, each optional, from cardioSettings.
const cardioActivities = [
  { id:'walk', name:'Walk', distance:'road', rate:'pace', settings:['incline'] },
  { id:'run', name:'Run', distance:'road', rate:'pace', settings:['incline'] },
  { id:'cycle', name:'Cycling', distance:'road', rate:'speed', settings:['cadence'] },
  { id:'bike', name:'Exercise bike', distance:'road', rate:'speed', settings:['resistance', 'cadence'] },
  { id:'elliptical', name:'Elliptical', distance:'road', rate:'speed', settings:['resistance', 'ramp'] },
  { id:'rower', name:'Rowing machine', distance:'meters', rate:'split', settings:['damper', 'strokeRate'] },
  { id:'stairs', name:'Stair climber', floors:true, settings:['level'] },
  { id:'other', name:'Other', distance:'road', rate:'speed', named:true, settings:['level'] }
];
// The settings a session can keep, each kept under its id in the session's cardio object: what the form calls it, the
// unit after it, its range (the server's too), and how a session's line says it. A treadmill's incline is a percentage
// and can go below zero; an elliptical's is a level on its own scale.
const cardioSettings = {
  incline:{ label:'Incline', unit:'%', min:-10, max:40, step:0.5, help:'Treadmill', says:value => `${value}% incline` },
  resistance:{ label:'Resistance level', min:0, max:100, step:1, says:value => `resistance ${value}` },
  ramp:{ label:'Incline level', min:0, max:100, step:1, says:value => `incline level ${value}` },
  cadence:{ label:'Cadence', unit:'rpm', min:0, max:300, step:1, says:value => `${value} rpm` },
  damper:{ label:'Damper', min:1, max:10, step:1, says:value => `damper ${value}` },
  strokeRate:{ label:'Stroke rate', unit:'spm', min:0, max:100, step:1, says:value => `${value} spm` },
  level:{ label:'Level', min:0, max:100, step:1, says:value => `level ${value}` }
};

// The settings a session has, as [id, value]: those of its activity it was given, in the activity's order.
function sessionSettings(workout) {
  const cardio = workout.cardio || {};
  return (activityOf(workout).settings || []).filter(id => typeof cardio[id] === 'number' && Number.isFinite(cardio[id])).map(id => [id, cardio[id]]);
}
const metresIn = { mi:1609.344, km:1000, m:1 };
// A pace, split or speed only counts as a record from a session of at least this many seconds, so a short burst (or a
// timer started by mistake) does not stand for a whole session.
const cardioRateRecordSeconds = 300;

function cardioActivity(id) {
  return cardioActivities.find(activity => activity.id === id) || cardioActivities[cardioActivities.length - 1];
}

function activityOf(workout) {
  return cardioActivity(workout && workout.cardio ? workout.cardio.activity : null);
}

// The unit a session's distance is shown in: a rower's metres, or Settings' miles or kilometres.
function shownDistanceUnit(activity) {
  return activity.distance === 'meters' ? 'm' : distanceUnitOf();
}

function convertDistance(value, from, to) {
  return from === to || !metresIn[from] || !metresIn[to] ? value : value * metresIn[from] / metresIn[to];
}

// "3.1 mi", "5.02 km", "5,000 m".
function formatDistance(value, unit) {
  return unit === 'm' ? `${Math.round(value).toLocaleString()} m` : `${Math.round(value * 100) / 100} ${unit}`;
}

// A length of time as a clock, to the second: "27:42", "1:05:09".
function formatClock(seconds) {
  const whole = Math.max(0, Math.round(seconds));
  const hours = Math.floor(whole / 3600), minutes = Math.floor(whole % 3600 / 60), rest = whole % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}` : `${minutes}:${String(rest).padStart(2, '0')}`;
}

// The unit a distance was entered in, for one saved before units were kept (never, today) or by hand: the activity's.
function enteredDistanceUnit(workout) {
  const unit = workout.cardio && workout.cardio.distanceUnit;
  return metresIn[unit] ? unit : activityOf(workout).distance === 'meters' ? 'm' : 'mi';
}

// A session's distance in the unit shown, or null when it has none.
function sessionDistance(workout) {
  const distance = Number(workout.cardio && workout.cardio.distance);
  const activity = activityOf(workout);
  if (!(distance > 0) || !activity.distance) return null;
  return convertDistance(distance, enteredDistanceUnit(workout), shownDistanceUnit(activity));
}

function rateName(activity) {
  return { pace:'Pace', speed:'Speed', split:'Split' }[activity.rate] || '';
}

// How fast a session went, from its distance and time, as its activity tells it: { value, text }, or null without a
// distance. A pace or split is seconds (a mile, a kilometre or 500 metres), a speed is distance an hour.
function sessionRate(workout) {
  const activity = activityOf(workout);
  const distance = sessionDistance(workout), seconds = Number(workout.duration);
  if (!activity.rate || !distance || !(seconds > 0)) return null;
  return rateOf(activity, distance, seconds, shownDistanceUnit(activity));
}

function rateOf(activity, distance, seconds, unit) {
  if (activity.rate === 'pace') return { value:seconds / distance, text:`${formatClock(seconds / distance)} /${unit}` };
  if (activity.rate === 'split') return { value:seconds / (distance / 500), text:`${formatClock(seconds / (distance / 500))} /500 m` };
  const speed = distance / (seconds / 3600);
  return { value:speed, text:`${Math.round(speed * 10) / 10} ${unit === 'km' ? 'km/h' : 'mph'}` };
}

// Whether one rate beats another: a faster pace or split is less time, a faster speed more distance.
function fasterRate(activity, value, than) {
  return activity.rate === 'speed' ? value > than : value < than;
}

// Everything a session did, as History, Progress and the Cardio page write it: "3.1 mi in 27:42 · 8:56 /mi · 2% incline ·
// 152 bpm · 320 cal", "20:00 · 60 floors · level 8". Only what was given is there.
function describeCardio(workout) {
  const cardio = workout.cardio || {};
  const activity = activityOf(workout);
  const distance = sessionDistance(workout);
  const time = formatClock(Number(workout.duration) || 0);
  const parts = [distance ? `${formatDistance(distance, shownDistanceUnit(activity))} in ${time}` : time];
  const rate = sessionRate(workout);
  if (rate) parts.push(rate.text);
  if (activity.floors && Number(cardio.floors) > 0) parts.push(plural(Math.round(cardio.floors), 'floor'));
  sessionSettings(workout).forEach(([id, value]) => parts.push(cardioSettings[id].says(value)));
  if (Number(cardio.heartRate) > 0) parts.push(`${Math.round(cardio.heartRate)} bpm`);
  if (Number(cardio.calories) > 0) parts.push(`${Math.round(cardio.calories)} cal`);
  return parts.join(' · ');
}

// The line under a session's name in a list: "Sep 30, 2026 · 27:42 · 3.1 mi".
function describeSessionDate(workout) {
  const activity = activityOf(workout);
  const distance = sessionDistance(workout);
  return [new Date(workout.createdAt).toLocaleDateString(undefined, { year:'numeric', month:'short', day:'numeric' }), formatClock(Number(workout.duration) || 0),
    distance ? formatDistance(distance, shownDistanceUnit(activity)) : ''].filter(Boolean).join(' · ');
}

// What a session's numbers are kept under on Progress (the exercise filter's value) and for its records: the activity,
// or for Other, its own name, so Jump rope and Swimming are two.
function cardioKey(workout) {
  const activity = activityOf(workout);
  return activity.named ? `cardio:other:${exerciseKey(workout.name)}` : `cardio:${activity.id}`;
}

function isCardioKey(key) {
  return typeof key === 'string' && key.startsWith('cardio:');
}

// The activity a key is for.
function keyActivity(key) {
  return cardioActivity(String(key).split(':')[1]);
}

// Each activity's bests, by cardioKey, from the oldest session to the newest: the longest distance and time, the
// fastest pace, split or speed (from a session of at least five minutes), and the most floors. Each keeps when it was
// set, and the latest name the activity went by.
function cardioBests(workouts) {
  const bests = new Map();
  [...workouts].filter(isCardio).sort((a, b) => a.createdAt - b.createdAt).forEach(workout => {
    const key = cardioKey(workout);
    const activity = activityOf(workout);
    const best = bests.get(key) || { key, activity, name:'', distance:null, duration:null, rate:null, floors:null };
    best.name = workout.name;
    const at = workout.createdAt, seconds = Number(workout.duration) || 0;
    const distance = sessionDistance(workout), rate = sessionRate(workout);
    const floors = activity.floors ? Number(workout.cardio && workout.cardio.floors) || 0 : 0;
    if (distance && (!best.distance || distance > best.distance.value)) best.distance = { value:distance, at };
    if (seconds > 0 && (!best.duration || seconds > best.duration.value)) best.duration = { value:seconds, at };
    if (rate && seconds >= cardioRateRecordSeconds && (!best.rate || fasterRate(activity, rate.value, best.rate.value))) best.rate = { ...rate, distance, at };
    if (floors > 0 && (!best.floors || floors > best.floors.value)) best.floors = { value:floors, at };
    bests.set(key, best);
  });
  return bests;
}

// A pace, split or speed half as fast again as the activity's best is more likely a slip (a distance of 30 for 3, a
// time of 3 minutes for 30) than a record, so it is asked about before the session is saved: the question, or ''. The
// first session of an activity has nothing to compare with.
function implausibleRate(workout, earlier) {
  const rate = sessionRate(workout);
  const best = cardioBests(earlier).get(cardioKey(workout))?.rate;
  if (!rate || !best) return '';
  const activity = activityOf(workout);
  const faster = activity.rate === 'speed' ? rate.value / best.value : best.value / rate.value;
  return faster >= 1.5 ? `That's a ${rate.text} ${rateName(activity).toLowerCase()}, far faster than your best (${best.text}). Save it anyway?` : '';
}

// What a new session beats, against the sessions before it, in the words of the strength records: "Run: your longest
// yet, 4.2 mi (was 3.1 mi)". The first session of an activity has nothing to beat, so it sets no records.
function newCardioRecords(workout, earlier) {
  const before = cardioBests(earlier).get(cardioKey(workout));
  if (!before) return [];
  const now = cardioBests([workout]).get(cardioKey(workout));
  const activity = activityOf(workout), unit = shownDistanceUnit(activity), name = workout.name;
  const records = [];
  if (now.distance && before.distance && now.distance.value > before.distance.value) {
    records.push(`${name}: your longest yet, ${formatDistance(now.distance.value, unit)} (was ${formatDistance(before.distance.value, unit)})`);
  }
  if (now.rate && before.rate && fasterRate(activity, now.rate.value, before.rate.value)) {
    records.push(`${name}: your fastest yet, ${now.rate.text} (was ${before.rate.text})`);
  }
  if (now.duration && before.duration && now.duration.value > before.duration.value) {
    records.push(`${name}: your longest time yet, ${formatClock(now.duration.value)} (was ${formatClock(before.duration.value)})`);
  }
  if (now.floors && before.floors && now.floors.value > before.floors.value) {
    records.push(`${name}: the most floors yet, ${now.floors.value} (was ${before.floors.value})`);
  }
  return records;
}
