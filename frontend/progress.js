const colors = ['#5b5ce2', '#e26d5c', '#2a9d8f', '#d9912f', '#c25bd8', '#3c8dcc'];

// The first line is drawn in the theme's accent, so the chart matches the colours chosen in Settings.
function seriesColour(index) {
  const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
  return index % colors.length === 0 && accent ? accent : colors[index % colors.length];
}
let chartData = null;
let allWorkouts = [];
// As loaded; allWorkouts is these in the unit shown, and is worked out again when the unit changes.
let loadedWorkouts = [];
let selectedMetric = 'weight';
// Exercises whose most recent log is timed (a plank): their "reps" are seconds held.
let timedExercises = new Set();
// Where each point was drawn and what it says, so a tap on the chart can find the nearest one.
let drawnPoints = [];
// The cardio activities logged, by cardioKey (cardio-activities.js), each under the latest name it went by.
let cardioLabels = new Map();
// The distance unit the chart was last drawn in, so a change of it in Settings draws it again.
let chartedDistanceUnit = null;

// Whether the chart is of a cardio activity rather than a strength exercise.
function chartingCardio() {
  return isCardioKey(selectedExercise);
}

// A cardio session's value for a metric, in the units shown, or null when the session does not have it. Time is in
// minutes, as are a pace and a split (written as a clock); a speed is distance an hour.
function cardioValue(workout, metric) {
  const cardio = workout.cardio || {};
  if (metric === 'distance') return sessionDistance(workout);
  if (metric === 'duration') return Number(workout.duration) > 0 ? Number(workout.duration) / 60 : null;
  if (metric === 'rate') {
    const rate = sessionRate(workout);
    return rate ? (activityOf(workout).rate === 'speed' ? rate.value : rate.value / 60) : null;
  }
  // What a machine was set to counts at zero too (a flat treadmill), so long as it was entered.
  if (cardioSettings[metric]) return typeof cardio[metric] === 'number' ? cardio[metric] : null;
  return ['calories', 'heartRate', 'floors'].includes(metric) && Number(cardio[metric]) > 0 ? Number(cardio[metric]) : null;
}

// The metrics a chart can show: a strength exercise's, or an activity's (its distance or floors, time, pace, split or
// speed, calories and heart rate).
function metricChoices() {
  if (!chartingCardio()) return [['weight', 'Heaviest weight'], ['oneRepMax', 'Estimated one-rep max'], ['reps', 'Best reps'], ['volume', 'Total volume']];
  const activity = keyActivity(selectedExercise);
  return [...(activity.distance ? [['distance', 'Distance']] : []), ...(activity.floors ? [['floors', 'Floors']] : []), ['duration', 'Time'],
    ...(activity.rate ? [['rate', rateName(activity)]] : []), ['calories', 'Calories'], ['heartRate', 'Average heart rate'],
    ...(activity.settings || []).map(id => [id, cardioSettings[id].label])];
}

// The metric filter offers what the chosen exercise or activity has, keeping the metric chosen where it still applies.
function syncMetricOptions() {
  const choices = metricChoices();
  const select = $('metricFilter');
  const current = select.value;
  const offered = [...select.options].map(option => `${option.value}:${option.textContent}`).join();
  if (offered !== choices.map(([value, label]) => `${value}:${label}`).join()) {
    select.innerHTML = choices.map(([value, label]) => `<option value="${value}">${escapeHTML(label)}</option>`).join('');
  }
  select.value = choices.some(([value]) => value === current) ? current : choices[0][0];
}

// Whether the chart is of a timed exercise, whose best reps are its longest hold and whose volume is its time held.
function chartingTimed() {
  return selectedExercise !== 'all' && timedExercises.has(selectedExercise);
}

// The best estimated one-rep max among an exercise's sets, or 0 when no set can give one (no weight, or too many reps).
function oneRepMaxOf(item) {
  const sets = item.sets && item.sets.length ? item.sets : [{ weight:item.weight, reps:item.reps }];
  return Math.max(0, ...sets.map(set => {
    const weight = Number(set.weight) || 0, reps = Number(set.reps) || 0;
    return weight > 0 && reps >= 1 && reps <= ONE_REP_MAX_REPS ? exactOneRepMax(weight, reps) : 0;
  }));
}

// One point a session of the chosen activity, in a line of its own; a session without the metric (no distance, say) has
// nothing to plot rather than a zero.
function buildCardioChartData(workouts) {
  const points = [], values = new Map();
  [...workouts].filter(workout => isCardio(workout) && cardioKey(workout) === selectedExercise).sort((a, b) => a.createdAt - b.createdAt).forEach((workout, index) => {
    const value = cardioValue(workout, selectedMetric);
    if (value === null || !(value > 0 || (cardioSettings[selectedMetric] && Number.isFinite(value)))) return;
    const key = String(workout.id ?? `${workout.createdAt}-${index}`);
    points.push({ key, createdAt:workout.createdAt });
    values.set(key, value);
  });
  return { points, types:points.length ? [{ name:cardioLabels.get(selectedExercise) || keyActivity(selectedExercise).name, values }] : [] };
}

function buildChartData(workouts) {
  if (chartingCardio()) return buildCardioChartData(workouts);
  const types = new Map();
  const points = [];
  const timed = chartingTimed();
  [...workouts].sort((a, b) => a.createdAt - b.createdAt).forEach((workout, index) => {
    const name = workout.name || 'Untitled workout';
    // An exercise saved with an empty set list was skipped, so it has no result to chart. Across all exercises, timed
    // ones are left out: their seconds are not reps, and would count as the best reps or the most volume.
    const matchingExercises = (selectedExercise === 'all' ? workout.exercises.filter(item => !isTimed(item)) : workout.exercises.filter(item => exerciseKey(item.name) === selectedExercise)).filter(item => !item.sets || item.sets.length);
    const values = matchingExercises.map(item => {
      if (selectedMetric === 'oneRepMax') return timed ? 0 : oneRepMaxOf(item);
      if (selectedMetric === 'reps') return Math.max(...(item.sets || []).map(set => Number(set.reps) || 0), Number(item.reps) || 0);
      if (selectedMetric === 'volume' && timed) return item.sets?.length ? item.sets.reduce((total, set) => total + (Number(set.reps) || 0), 0) : Number(item.reps) || 0;
      if (selectedMetric === 'volume') return item.sets?.length ? item.sets.reduce((total, set) => total + (Number(set.weight) || 0) * (Number(set.reps) || 0), 0) : (Number(item.weight) || 0) * (Number(item.reps) || 0);
      return Math.max(...(item.sets || []).map(set => Number(set.weight) || 0), Number(item.weight) || 0);
    });
    const metricValue = selectedMetric === 'volume' ? values.reduce((total, value) => total + value, 0) : Math.max(...values, 0);
    if (!matchingExercises.length) return;
    // A workout with no set that gives a one-rep max (bodyweight, or only long sets) has nothing to plot, not a zero.
    if (selectedMetric === 'oneRepMax' && !(metricValue > 0)) return;
    if (!types.has(name)) types.set(name, new Map());
    const entries = types.get(name);
    const key = String(workout.id ?? `${workout.createdAt}-${index}`);
    points.push({ key, createdAt:workout.createdAt });
    entries.set(key, metricValue);
  });
  return { points, types:[...types].map(([name, values]) => ({ name, values })) };
}

function formatDate(timestamp) {
  return new Date(timestamp).toLocaleDateString(undefined, { month:'short', day:'numeric' });
}

function longDate(timestamp) {
  return new Date(timestamp).toLocaleDateString(undefined, { year:'numeric', month:'short', day:'numeric' });
}

function dateFilterTimestamp(value, endOfDay = false) {
  if (!value) return null;
  return new Date(`${value}T${endOfDay ? '23:59:59.999' : '00:00:00'}`).getTime();
}

function populateWorkoutTypes(workouts) {
  const selected = $('workoutTypeFilter').value;
  const names = [...new Set(workouts.filter(workout => !isCardio(workout)).map(workout => workout.name || 'Untitled workout'))].sort();
  $('workoutTypeFilter').innerHTML = '<option value="all">All workout types</option>' + names.map(name => `<option value="${escapeHTML(name)}">${escapeHTML(name)}</option>`).join('');
  $('workoutTypeFilter').value = names.includes(selected) ? selected : 'all';
}

// One option per exercise however its name was typed ("Bench press", "Bench Press "), labelled with the most recent
// spelling. The option's value is the exerciseKey the chart matches on. Cardio activities follow, apart, by cardioKey.
function populateExercises(workouts) {
  const selected = $('exerciseFilter').value;
  const labels = new Map();
  cardioLabels = new Map();
  timedExercises = new Set();
  [...workouts].sort((a, b) => b.createdAt - a.createdAt).forEach(workout => {
    if (isCardio(workout)) {
      if (!cardioLabels.has(cardioKey(workout))) cardioLabels.set(cardioKey(workout), workout.name);
      return;
    }
    workout.exercises.forEach(item => {
      const key = exerciseKey(item.name);
      if (!key || labels.has(key)) return;
      labels.set(key, String(item.name).trim());
      if (isTimed(item)) timedExercises.add(key);
    });
  });
  const byLabel = ([, a], [, b]) => a.localeCompare(b, undefined, { sensitivity:'base' });
  const option = ([key, label]) => `<option value="${escapeHTML(key)}">${escapeHTML(label)}</option>`;
  const strength = '<option value="all">All exercises</option>' + [...labels].sort(byLabel).map(option).join('');
  $('exerciseFilter').innerHTML = cardioLabels.size
    ? `<optgroup label="Strength">${strength}</optgroup><optgroup label="Cardio">${[...cardioLabels].sort(byLabel).map(option).join('')}</optgroup>` : strength;
  $('exerciseFilter').value = labels.has(selected) || cardioLabels.has(selected) ? selected : 'all';
}

// The exercise done in the most workouts, which the page opens on: across all exercises, the heaviest lift of each
// workout (a deadlift, usually) would drown out everything else. With no strength workouts, the activity done most;
// 'all' until anything has been logged.
function mostLoggedExercise(workouts) {
  const counts = new Map(), sessions = new Map();
  workouts.forEach(workout => new Set(workout.exercises.filter(item => !item.sets || item.sets.length).map(item => exerciseKey(item.name)))
    .forEach(key => { if (key) counts.set(key, (counts.get(key) || 0) + 1); }));
  workouts.filter(isCardio).forEach(workout => sessions.set(cardioKey(workout), (sessions.get(cardioKey(workout)) || 0) + 1));
  const most = map => [...map].reduce((best, entry) => !best || entry[1] > best[1] ? entry : best, null)?.[0];
  return most(counts) ?? most(sessions) ?? 'all';
}

function applyFilters() {
  selectedExercise = $('exerciseFilter').value;
  syncMetricOptions();
  selectedMetric = $('metricFilter').value;
  // Workout types are the names of strength workouts: an activity's chart is of every session of it.
  $('workoutTypeFilter').disabled = chartingCardio();
  const type = chartingCardio() ? 'all' : $('workoutTypeFilter').value;
  const start = dateFilterTimestamp($('startDateFilter').value);
  const end = dateFilterTimestamp($('endDateFilter').value, true);
  const filtered = allWorkouts.filter(workout => {
    const nameMatches = type === 'all' || (workout.name || 'Untitled workout') === type;
    const dateMatches = (!start || workout.createdAt >= start) && (!end || workout.createdAt <= end);
    return nameMatches && dateMatches;
  });
  renderProgress(filtered);
}

// What the chart measures: its axis label, how a value is written by a point and in words, and how the axis writes one.
// A time (a session's, a pace or split) is a clock; anything else a number and its unit.
function chartFormat() {
  // A tick keeps a step's half (2.5, 7.5) rather than rounding it to a number the line is not on.
  const plain = (axis, unit = '') => ({ axis, value:value => `${Math.round(value).toLocaleString()}${unit}`, tick:value => (Math.round(value * 10) / 10).toLocaleString() });
  if (chartingCardio()) {
    const activity = keyActivity(selectedExercise);
    const unit = shownDistanceUnit(activity);
    const clock = (axis, after = '') => ({ axis, value:value => `${formatClock(value * 60)}${after}`, tick:value => formatClock(value * 60) });
    if (selectedMetric === 'distance') {
      return { axis:`Distance (${unit})`, value:value => formatDistance(value, unit), tick:value => unit === 'm' ? Math.round(value).toLocaleString() : String(Math.round(value * 10) / 10) };
    }
    if (selectedMetric === 'duration') return clock('Time');
    if (selectedMetric === 'rate' && activity.rate === 'pace') return clock(`Pace (min/${unit})`, ` /${unit}`);
    if (selectedMetric === 'rate' && activity.rate === 'split') return clock('Split (min/500 m)', ' /500 m');
    if (selectedMetric === 'rate') {
      const speed = unit === 'km' ? 'km/h' : 'mph';
      return { axis:`Speed (${speed})`, value:value => `${Math.round(value * 10) / 10} ${speed}`, tick:value => String(Math.round(value * 10) / 10) };
    }
    if (cardioSettings[selectedMetric]) {
      const setting = cardioSettings[selectedMetric];
      return { axis:`${setting.label}${setting.unit ? ` (${setting.unit})` : ''}`, value:value => setting.says(Math.round(value * 10) / 10),
        tick:value => String(Math.round(value * 10) / 10) };
    }
    if (selectedMetric === 'calories') return plain('Calories', ' cal');
    if (selectedMetric === 'heartRate') return plain('Heart rate (bpm)', ' bpm');
    return plain('Floors', ' floors');
  }
  const unit = weightUnit();
  if (selectedMetric === 'weight') return plain(`Weight (${unit})`, ` ${unit}`);
  if (selectedMetric === 'oneRepMax') return plain(`Est. one-rep max (${unit})`, ` ${unit}`);
  if (chartingTimed()) return plain('Seconds', ' s');
  return selectedMetric === 'reps' ? plain('Reps') : plain(`Volume (${unit})`);
}

// Steps of 1, 2, 2.5, 5 or 10 of a power of ten, the smallest at least `rough`: what a scale's lines fall on.
function roundStep(rough) {
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  return [1, 2, 2.5, 5, 10].map(multiple => multiple * magnitude).find(size => size >= rough);
}

// Where the chart's axis runs. A strength chart starts at zero, as it always has, up to the round step above its top
// (four of them: 0, 50, 100, 150, 200). A cardio chart spans its sessions with a little room either side, on round steps
// (a clock's for a time), since a pace that moves from 9:10 to 8:20 a mile is a flat line along the top of an axis from
// zero. A pace or split, where less is faster, runs the other way up, so getting faster climbs as getting stronger does.
function chartScale(values) {
  if (!chartingCardio()) {
    const step = roundStep(Math.max(...values, 4) / 4);
    const high = Math.ceil(Math.max(...values, 4) / step) * step;
    const ticks = [];
    for (let value = 0; value <= high + step / 1000; value += step) ticks.push(Math.round(value * 1e6) / 1e6);
    return { low:0, high, invert:false, ticks };
  }
  const slower = selectedMetric === 'rate' && keyActivity(selectedExercise).rate !== 'speed';
  const clock = slower || selectedMetric === 'duration';
  const min = Math.min(...values), max = Math.max(...values);
  // Room either side; one that would be none (every session the same, at zero) is a whole one.
  const pad = Math.max((max - min) * 0.15, clock ? 0.25 : Math.abs(max) * 0.05) || 1;
  const rough = (max - min + 2 * pad) / 4;
  // In minutes: from 5 seconds a step to 4 hours.
  const clockSteps = [5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400].map(seconds => seconds / 60);
  const step = clock ? clockSteps.find(size => size >= rough) || clockSteps[clockSteps.length - 1] : roundStep(rough);
  // Below zero only for what can be: a treadmill set downhill.
  const low = cardioSettings[selectedMetric] ? Math.floor((min - pad) / step) * step : Math.max(0, Math.floor((min - pad) / step) * step);
  const high = Math.ceil((max + pad) / step) * step;
  const ticks = [];
  for (let value = low; value <= high + step / 1000; value += step) ticks.push(Math.round(value * 1e6) / 1e6);
  return { low, high, invert:slower, ticks };
}

// Labels along a line, first to last, keeping only those with room: each is written only if it clears the one before
// it, and the last is always written, in place of any it would run into.
// Where the values written beside the points go. A value over every point runs together, the more so with several workout types
// on one line. Each series' latest value is written first, the most recent of them before the rest, then the others from left
// to right, each only where it clears every value already written. A tap on the chart shows any of them. Each label is
// { text, colour, x, y, width }; those to write are given a place, beside the point on the right, or on the left where the
// chart's edge would cut it off.
function placeValueLabels(latest, others, width) {
  const placed = label => {
    const onRight = label.x + 7 + label.width <= width - 2;
    return { ...label, left:onRight ? label.x + 7 : label.x - 7 - label.width, align:onRight ? 'left' : 'right', at:onRight ? label.x + 7 : label.x - 7 };
  };
  const clashes = (a, b) => a.left < b.left + b.width + 6 && b.left < a.left + a.width + 6 && Math.abs(a.y - b.y) < 13;
  const written = [];
  [...latest.sort((a, b) => b.x - a.x), ...others.sort((a, b) => a.x - b.x)].map(placed)
    .forEach(label => { if (!written.some(other => clashes(other, label))) written.push(label); });
  return written.sort((a, b) => a.left - b.left);
}

// Draws each workout type's line and dots, and notes where every point is (drawnPoints, for a tap on the chart). Returns the
// value to write at each: each line's latest, and the rest.
function drawSeries(context, { across, y, format }) {
  context.font = '11px Inter, system-ui, sans-serif';
  const latest = [], others = [];
  chartData.types.forEach((type, typeIndex) => {
    const colour = seriesColour(typeIndex);
    const own = chartData.points.map((point, index) => ({ point, index, value:type.values.get(point.key) })).filter(entry => entry.value !== undefined);
    const spots = own.map(entry => ({ x:across[entry.index], y:y(entry.value) }));
    drawLine(context, spots, colour);
    drawDots(context, spots, colour);
    own.forEach(({ point, index, value }, position) => {
      drawnPoints.push({ x:across[index], y:y(value), text:`${type.name}, ${longDate(point.createdAt)}: ${format.value(value)}` });
      const text = format.value(value);
      (position === own.length - 1 ? latest : others).push({ text, colour, x:across[index], y:y(value), width:context.measureText(text).width });
    });
  });
  return { latest, others };
}

function drawChart() {
  drawnPoints = [];
  if (!chartData || !chartData.points.length) return;
  const { context, width, height } = prepareChart($('progressChart'), 360);
  // Set through the DOM: the Content-Security-Policy refuses style="" attributes written into markup. Coloured with the
  // chart, so a change of theme recolours both.
  $('legend').querySelectorAll('.legend-swatch').forEach((swatch, index) => { swatch.style.background = seriesColour(index); });
  const colours = chartColours();
  const left = 58, right = 24, top = 22, bottom = 52;
  const chartWidth = Math.max(width - left - right, 1);
  const chartHeight = height - top - bottom;
  const values = chartData.types.flatMap(type => [...type.values.values()]);
  const scale = chartScale(values);
  // Across by date, so a month between workouts takes more room than a day, and the slope is the real rate of progress.
  const first = chartData.points[0].createdAt;
  const span = chartData.points[chartData.points.length - 1].createdAt - first;
  const across = chartData.points.map(point => span ? left + (point.createdAt - first) / span * chartWidth : left + chartWidth / 2);
  const y = value => {
    const share = (value - scale.low) / (scale.high - scale.low);
    return top + (scale.invert ? share : 1 - share) * chartHeight;
  };
  const format = chartFormat();

  drawGuides(context, { colours, ticks:scale.ticks, y, left, right, width, label:format.tick, gap:10 });
  drawAxisTitle(context, format.axis, 15, top + chartHeight / 2);
  drawDateLabels(context, chartData.points.map((point, index) => ({ time:point.createdAt, x:across[index] })), height - 20, colours);
  const { latest, others } = drawSeries(context, { across, y, format });
  placeValueLabels(latest, others, width).forEach(label => {
    context.fillStyle = label.colour;
    context.textAlign = label.align;
    context.fillText(label.text, label.at, label.y - 8);
  });
}

// The chart in words, for a screen reader, which cannot see the canvas.
function describeChart() {
  if (!chartData.points.length) return 'Nothing to chart.';
  const values = chartData.types.flatMap(type => [...type.values.values()]);
  const amount = chartFormat().value;
  const exercise = selectedExercise === 'all' ? 'all exercises' : $('exerciseFilter').selectedOptions[0]?.textContent || selectedExercise;
  const count = plural(chartData.points.length, 'workout');
  return `${$('progressTitle').textContent} for ${exercise}: ${count} from ${longDate(chartData.points[0].createdAt)} to ${longDate(chartData.points[chartData.points.length - 1].createdAt)}, lowest ${amount(Math.min(...values))}, highest ${amount(Math.max(...values))}.`;
}

function renderProgress(workouts) {
  chartData = buildChartData(workouts);
  $('chartEmpty').hidden = Boolean(chartData.points.length);
  $('progressChart').hidden = !chartData.points.length;
  // Counted among their own kind: strength workouts for an exercise's chart, sessions for an activity's.
  const ofKind = list => list.filter(workout => isCardio(workout) === chartingCardio());
  const shown = ofKind(workouts).length, total = ofKind(allWorkouts).length;
  const noun = chartingCardio() ? 'session' : 'saved workout';
  $('progressSummary').textContent = shown === total ? plural(total, noun) : `${shown} of ${total} ${chartingCardio() ? 'sessions' : 'workouts'}`;
  const activity = chartingCardio() ? keyActivity(selectedExercise) : null;
  const per = activity && shownDistanceUnit(activity) === 'km' ? 'kilometre' : 'mile';
  const labels = activity ? {
    distance:['Distance', 'How far each session went.'],
    floors:['Floors', 'The floors climbed in each session.'],
    duration:['Time', 'How long each session took.'],
    rate:activity.rate === 'speed' ? ['Speed', 'The average speed of each session, from its distance and time.']
      : activity.rate === 'split' ? ['Split', 'Time per 500 metres in each session. Faster is higher up.']
        : ['Pace', `Time per ${per} in each session. Faster is higher up.`],
    calories:['Calories', 'The calories of each session, where you entered them.'],
    heartRate:['Average heart rate', 'The average heart rate of each session, where you entered it.'],
    ...Object.fromEntries((activity.settings || []).map(id => [id, [cardioSettings[id].label, `The ${cardioSettings[id].label.toLowerCase()} of each session, where you entered it.`]]))
  } : chartingTimed()
    ? { weight:['Heaviest weight', 'Track the heaviest weight you have held by workout type and date.'], oneRepMax:['Estimated one-rep max', 'A timed exercise has no one-rep max. Choose Longest hold or Total time held.'], reps:['Longest hold', 'Track your longest hold, in seconds, by workout type and date.'], volume:['Total time held', 'Track the seconds held in each workout, all sets together.'] }
    : { weight:['Heaviest weight', 'Track your heaviest weight by workout type and date.'], oneRepMax:['Estimated one-rep max', 'Your best set in each workout as a one-rep max, from sets of up to 12 reps, so heavier weights and more reps both count.'], reps:['Best reps', 'Track your highest completed reps by workout type and date.'], volume:['Total volume', 'Track total weight moved by workout type and date.'] };
  $('progressTitle').textContent = labels[selectedMetric][0];
  $('progressDescription').textContent = labels[selectedMetric][1];
  if (!chartData.points.length && allWorkouts.length && activity) {
    const missing = { distance:'a distance', floors:'floors', rate:'a distance to work it out from', calories:'calories', heartRate:'a heart rate' }[selectedMetric]
      || (cardioSettings[selectedMetric] ? `a ${cardioSettings[selectedMetric].label.toLowerCase()}` : '');
    $('chartEmpty').textContent = missing && ofKind(workouts).some(workout => cardioKey(workout) === selectedExercise)
      ? `Nothing to chart: none of these sessions has ${missing} entered.` : 'Nothing to chart for these filters.';
  } else if (!chartData.points.length && allWorkouts.length) {
    $('chartEmpty').textContent = selectedMetric === 'oneRepMax'
      ? 'Nothing to chart: a one-rep max needs a set with weight, of 12 reps or fewer.'
      : 'Nothing to chart for these filters.';
  }
  $('legend').innerHTML = chartData.types.map(type => `<div class="legend-item"><span class="legend-swatch"></span><span>${escapeHTML(type.name)}</span></div>`).join('');
  $('progressChart').setAttribute('aria-label', describeChart());
  $('chartDetail').textContent = chartData.points.length ? 'Tap a point to see its value.' : '';
  drawChart();
  renderSessions(workouts);
}

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
    $('sessionList').innerHTML = sessions.map(workout => `<li><div><strong>${escapeHTML(longDate(workout.createdAt))}</strong><span>${escapeHTML(workout.name)}</span></div>`
      + `<span>${escapeHTML(describeCardio(workout))}</span></li>`).join('');
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
  $('sessionList').innerHTML = sessions.map(({ workout, items }) => {
    const efforts = describeEfforts(items.flatMap(item => item.sets || []));
    return `<li><div><strong>${escapeHTML(longDate(workout.createdAt))}</strong><span>${escapeHTML(workout.name || 'Untitled workout')}</span></div>`
      + `<span>${escapeHTML(items.map(describeSavedExercise).join(' · '))}${efforts ? ` · ${escapeHTML(efforts)}` : ''}</span></li>`;
  }).join('');
}

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

function renderRecords() {
  const unit = weightUnit();
  const strength = recordsOf(allWorkouts).map(record => {
    const lines = [];
    if (record.heaviest) lines.push(['Heaviest', `${formatWeight(record.heaviest.value)} ${unit} × ${record.heaviest.reps}`, record.heaviest.date]);
    if (record.oneRepMax) lines.push(['Est. one-rep max', `${Math.round(record.oneRepMax.value)} ${unit}, from ${formatWeight(record.oneRepMax.weight)} × ${record.oneRepMax.reps}`, record.oneRepMax.date]);
    if (record.reps) lines.push(['Most reps', plural(record.reps.value, 'rep'), record.reps.date]);
    if (record.hold) lines.push(['Longest hold', `${record.hold.value} s`, record.hold.date]);
    return { key:record.key, name:record.name, lines, latest:record.latest };
  });
  // The most recent record first, whichever kind it is.
  const records = [...strength, ...cardioRecordsOf(allWorkouts)].filter(record => record.lines.length).sort((a, b) => b.latest - a.latest);
  $('recordsList').innerHTML = records.length ? records.map(record => `<li><button class="record" type="button" data-exercise="${escapeHTML(record.key)}">`
    + `<strong>${escapeHTML(record.name)}</strong>${record.lines.map(([label, value, date]) =>
      `<span><span class="record-label">${label}</span> ${escapeHTML(value)} <span class="record-date">· ${escapeHTML(longDate(date))}</span></span>`).join('')}</button></li>`).join('')
    : '<li class="empty">Your records appear once you have saved a workout.</li>';
}

// ---- Stalled lifts ------------------------------------------------------------
// Each lift whose best has not moved in three weeks or more (stalls.js), the longest stalled first, with the deload to try.
function renderStalls() {
  const unit = weightUnit();
  const stalls = stalledLifts(allWorkouts);
  $('stallList').innerHTML = stalls.length ? stalls.map(({ key, name, stall }) => `<li><button class="record" type="button" data-exercise="${escapeHTML(key)}">`
    + `<strong>${escapeHTML(name)}</strong><span>${escapeHTML(describeStall(stall))}</span>`
    + `<span><span class="record-label">Best</span> est. one-rep max ${Math.round(stall.best)} ${unit} <span class="record-date">· ${escapeHTML(longDate(stall.bestAt))}</span></span>`
    + `<span><span class="record-label">Try</span> a week at ${escapeHTML(formatWeight(stall.deload))} ${unit}, 10% off last time's ${escapeHTML(formatWeight(stall.heaviest))}</span></button></li>`).join('')
    : '<li class="empty">Nothing has stalled: every lift you have trained lately has set a best within three weeks, or is still early on.</li>';
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

function renderGoals() {
  applyUnitLabels();
  const unit = weightUnit();
  const records = recordsOf(allWorkouts);
  const heaviest = new Map(records.map(record => [record.key, record.heaviest ? record.heaviest.value : 0]));
  $('goalExercises').innerHTML = records.filter(record => record.heaviest).map(record => `<option value="${escapeHTML(record.name)}"></option>`).join('');
  const items = Object.entries(goals).map(([key, goal]) => {
    const target = convertWeight(goal.target, goal.unit || 'lbs', unit);
    const best = heaviest.get(key) || 0;
    return { key, goal, target, best, reached:best >= target };
  // Goals still to reach first, the nearest deadline first, then the ones reached.
  }).sort((a, b) => a.reached - b.reached || (a.goal.by || '9999').localeCompare(b.goal.by || '9999') || a.goal.name.localeCompare(b.goal.name));
  $('goalList').innerHTML = items.length ? items.map(({ key, goal, target, best, reached }) => {
    const percent = Math.min(100, Math.round(best / target * 100));
    const status = reached ? 'Reached' : `${formatWeight(Math.round((target - best) * 100) / 100)} ${unit} to go`;
    const deadline = goal.by && !reached ? ` · ${goalDeadline(goal.by)}` : '';
    return `<li class="goal${reached ? ' reached' : ''}"><div class="goal-head"><strong>${escapeHTML(goal.name)}</strong>`
      + `<span>${formatWeight(best)} of ${formatWeight(target)} ${unit}</span></div>`
      + `<div class="goal-bar" role="progressbar" aria-label="${escapeHTML(goal.name)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><span></span></div>`
      + `<div class="goal-foot"><span>${escapeHTML(status + deadline)}</span>`
      + `<button class="link-button" type="button" data-goal-remove="${escapeHTML(key)}" aria-label="Remove the goal for ${escapeHTML(goal.name)}">Remove</button></div></li>`;
  }).join('') : '<li class="empty">No goals yet. Set one below.</li>';
  // Set through the DOM: the Content-Security-Policy refuses style="" attributes written into markup, which left every
  // bar full whatever the goal's progress.
  $('goalList').querySelectorAll('.goal-bar').forEach(bar => { bar.firstElementChild.style.width = `${bar.getAttribute('aria-valuenow')}%`; });
}

function showGoalFeedback(message, isError = false) {
  $('goalFeedback').textContent = message;
  $('goalFeedback').classList.toggle('error', isError);
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

async function loadProgress() {
  try {
    await window.localReady;
    await flushPendingWorkouts();
    loadedWorkouts = await getSavedWorkouts();
    allWorkouts = loadedWorkouts.map(workout => inUnit(workout));
    populateWorkoutTypes(allWorkouts);
    populateExercises(allWorkouts);
    // A link from another page (History, a workout's past sessions) can name the exercise to open on.
    const asked = new URLSearchParams(location.search).get('exercise');
    $('exerciseFilter').value = asked && [...$('exerciseFilter').options].some(option => option.value === asked) ? asked : mostLoggedExercise(allWorkouts);
    selectedExercise = $('exerciseFilter').value;
    syncMetricOptions();
    selectedMetric = $('metricFilter').value;
    $('workoutTypeFilter').disabled = chartingCardio();
    chartedDistanceUnit = distanceUnitOf();
    renderProgress(allWorkouts);
    renderRecords();
    renderStalls();
    loadGoals();
    renderGoals();
    // muscles.js, loaded after this, counts the same workouts.
    renderMuscles();
    renderLibrary();
  } catch (error) {
    $('chartEmpty').hidden = false;
    $('chartEmpty').textContent = 'Progress data could not be loaded.';
    $('recordsList').innerHTML = '<li class="empty">Your records show once your workouts load.</li>';
    $('muscleList').innerHTML = '<li class="empty">Your sets show once your workouts load.</li>';
    console.error('Unable to load progress.', error);
  }
}

let selectedExercise = 'all';
['metricFilter', 'exerciseFilter', 'workoutTypeFilter', 'startDateFilter', 'endDateFilter'].forEach(id => { $(id).onchange = applyFilters; });
// Back to how the page opens: heaviest weight of the exercise done most, over every workout.
$('clearFilters').onclick = () => {
  $('exerciseFilter').value = mostLoggedExercise(allWorkouts);
  selectedExercise = $('exerciseFilter').value;
  syncMetricOptions();
  $('metricFilter').value = metricChoices()[0][0];
  $('workoutTypeFilter').value = 'all';
  $('startDateFilter').value = ''; $('endDateFilter').value = '';
  applyFilters();
};
// A tap on the chart says what the nearest point is, since not every point has room for its value.
$('progressChart').addEventListener('click', event => {
  const bounds = $('progressChart').getBoundingClientRect();
  const tapX = event.clientX - bounds.left, tapY = event.clientY - bounds.top;
  const distance = point => Math.hypot(point.x - tapX, point.y - tapY);
  const nearest = drawnPoints.reduce((best, point) => !best || distance(point) < distance(best) ? point : best, null);
  if (nearest && distance(nearest) <= 40) $('chartDetail').textContent = nearest.text;
});
$('stallList').onclick = event => $('recordsList').onclick(event);
$('recordsList').onclick = event => {
  const record = event.target.closest('[data-exercise]');
  if (!record) return;
  $('exerciseFilter').value = record.dataset.exercise;
  applyFilters();
  document.querySelector('.progress-card').scrollIntoView({ behavior:'smooth', block:'start' });
};
window.addEventListener('resize', drawChart);
// A canvas only draws in Inter once it has loaded, and the labels' spacing is measured in it.
document.fonts.ready.then(drawChart);
// The note kept with an exercise may only arrive from the server once the page has drawn.
window.serverStateReady.then(() => {
  loadGoals();
  if (allWorkouts.length) { renderSessions(allWorkouts); renderGoals(); }
});
// The theme changes the chart's colours; the weight unit changes its numbers, and the distance unit a cardio chart's and
// the cardio records.
window.addEventListener('settingschange', () => {
  const converted = loadedWorkouts.map(workout => inUnit(workout));
  if (converted.some((workout, index) => workout !== allWorkouts[index])) {
    allWorkouts = converted;
    applyFilters();
    renderRecords();
    renderStalls();
    renderGoals();
  } else if (chartedDistanceUnit !== null && chartedDistanceUnit !== distanceUnitOf()) {
    chartedDistanceUnit = distanceUnitOf();
    applyFilters();
    renderRecords();
  } else drawChart();
});
loadProgress();
