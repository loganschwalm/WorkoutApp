const colors = ['#5b5ce2', '#e26d5c', '#2a9d8f', '#d9912f', '#c25bd8', '#3c8dcc'];
let chartData = null;
let allWorkouts = [];
// As loaded; allWorkouts is these in the unit shown, and is worked out again when the unit changes.
let loadedWorkouts = [];
let selectedMetric = 'weight';
// Exercises whose most recent log is timed (a plank): their "reps" are seconds held.
let timedExercises = new Set();
// Where each point was drawn and what it says, so a tap on the chart can find the nearest one.
let drawnPoints = [];

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

function buildChartData(workouts) {
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
  const names = [...new Set(workouts.map(workout => workout.name || 'Untitled workout'))].sort();
  $('workoutTypeFilter').innerHTML = '<option value="all">All workout types</option>' + names.map(name => `<option value="${escapeHTML(name)}">${escapeHTML(name)}</option>`).join('');
  $('workoutTypeFilter').value = names.includes(selected) ? selected : 'all';
}

// One option per exercise however its name was typed ("Bench press", "Bench Press "), labelled with the most recent
// spelling. The option's value is the exerciseKey the chart matches on.
function populateExercises(workouts) {
  const selected = $('exerciseFilter').value;
  const labels = new Map();
  timedExercises = new Set();
  [...workouts].sort((a, b) => b.createdAt - a.createdAt).forEach(workout => workout.exercises.forEach(item => {
    const key = exerciseKey(item.name);
    if (!key || labels.has(key)) return;
    labels.set(key, String(item.name).trim());
    if (isTimed(item)) timedExercises.add(key);
  }));
  const options = [...labels].sort(([, a], [, b]) => a.localeCompare(b, undefined, { sensitivity:'base' }));
  $('exerciseFilter').innerHTML = '<option value="all">All exercises</option>' + options.map(([key, label]) => `<option value="${escapeHTML(key)}">${escapeHTML(label)}</option>`).join('');
  $('exerciseFilter').value = labels.has(selected) ? selected : 'all';
}

// The exercise done in the most workouts, which the page opens on: across all exercises, the heaviest lift of each
// workout (a deadlift, usually) would drown out everything else. 'all' until anything has been logged.
function mostLoggedExercise(workouts) {
  const counts = new Map();
  workouts.forEach(workout => new Set(workout.exercises.filter(item => !item.sets || item.sets.length).map(item => exerciseKey(item.name)))
    .forEach(key => { if (key) counts.set(key, (counts.get(key) || 0) + 1); }));
  return [...counts].reduce((best, entry) => !best || entry[1] > best[1] ? entry : best, null)?.[0] ?? 'all';
}

function applyFilters() {
  const type = $('workoutTypeFilter').value;
  selectedMetric = $('metricFilter').value;
  selectedExercise = $('exerciseFilter').value;
  const start = dateFilterTimestamp($('startDateFilter').value);
  const end = dateFilterTimestamp($('endDateFilter').value, true);
  const filtered = allWorkouts.filter(workout => {
    const nameMatches = type === 'all' || (workout.name || 'Untitled workout') === type;
    const dateMatches = (!start || workout.createdAt >= start) && (!end || workout.createdAt <= end);
    return nameMatches && dateMatches;
  });
  renderProgress(filtered);
}

// What the chart measures, for its axis and for each point: [axis label, unit after a value].
function metricLabels() {
  const unit = weightUnit();
  if (selectedMetric === 'weight') return [`Weight (${unit})`, ` ${unit}`];
  if (selectedMetric === 'oneRepMax') return [`Est. one-rep max (${unit})`, ` ${unit}`];
  if (chartingTimed()) return ['Seconds', ' s'];
  return selectedMetric === 'reps' ? ['Reps', ''] : [`Volume (${unit})`, ''];
}

// Labels along a line, first to last, keeping only those with room: each is written only if it clears the one before
// it, and the last is always written, in place of any it would run into.
function labelsThatFit(labels, gap) {
  const kept = [];
  const clears = (a, b) => b.x - a.x >= (a.width + b.width) / 2 + gap;
  labels.forEach(label => { if (!kept.length || clears(kept[kept.length - 1], label)) kept.push(label); });
  const last = labels[labels.length - 1];
  if (last && kept[kept.length - 1] !== last) {
    while (kept.length && !clears(kept[kept.length - 1], last)) kept.pop();
    kept.push(last);
  }
  return kept;
}

function drawChart() {
  drawnPoints = [];
  if (!chartData || !chartData.points.length) return;
  const canvas = $('progressChart');
  const width = canvas.clientWidth;
  const height = 360;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext('2d');
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  const styles = getComputedStyle(document.documentElement);
  const ink = styles.getPropertyValue('--muted').trim();
  const line = styles.getPropertyValue('--line').trim();
  const left = 58, right = 24, top = 22, bottom = 52;
  const chartWidth = Math.max(width - left - right, 1);
  const chartHeight = height - top - bottom;
  const values = chartData.types.flatMap(type => [...type.values.values()]);
  const maximum = Math.max(...values, 1);
  const tickStep = maximum / 4;
  // Across by date, so a month between workouts takes more room than a day, and the slope is the real rate of progress.
  const first = chartData.points[0].createdAt;
  const span = chartData.points[chartData.points.length - 1].createdAt - first;
  const across = chartData.points.map(point => span ? left + (point.createdAt - first) / span * chartWidth : left + chartWidth / 2);
  const y = value => top + chartHeight - value / maximum * chartHeight;
  const [metricLabel, pointUnit] = metricLabels();

  context.font = '12px system-ui, sans-serif';
  context.lineWidth = 1;
  context.strokeStyle = line;
  context.fillStyle = ink;
  context.textAlign = 'right';
  for (let tick = 0; tick <= 4; tick += 1) {
    const value = tick * tickStep;
    const position = y(value);
    context.beginPath(); context.moveTo(left, position); context.lineTo(width - right, position); context.stroke();
    context.fillText(Math.round(value).toLocaleString(), left - 10, position + 4);
  }
  context.save();
  context.translate(15, top + chartHeight / 2);
  context.rotate(-Math.PI / 2);
  context.textAlign = 'center';
  context.fillText(metricLabel, 0, 0);
  context.restore();
  context.textAlign = 'center';
  // A date under every point runs together once there are a few weeks of workouts, so only those with room are written,
  // always including the most recent.
  const dates = chartData.points.map((point, index) => {
    const text = formatDate(point.createdAt);
    return { text, x:across[index], width:context.measureText(text).width };
  });
  labelsThatFit(dates, 12).forEach(label => context.fillText(label.text, label.x, height - 20));

  context.font = '11px system-ui, sans-serif';
  const latest = [], others = [];
  chartData.types.forEach((type, typeIndex) => {
    const colour = colors[typeIndex % colors.length];
    context.strokeStyle = colour;
    context.fillStyle = colour;
    context.lineWidth = 3;
    const own = chartData.points.map((point, index) => ({ point, index, value:type.values.get(point.key) })).filter(entry => entry.value !== undefined);
    context.beginPath();
    own.forEach((entry, position) => {
      if (position === 0) context.moveTo(across[entry.index], y(entry.value)); else context.lineTo(across[entry.index], y(entry.value));
    });
    context.stroke();
    own.forEach(({ point, index, value }, position) => {
      context.beginPath(); context.arc(across[index], y(value), 4, 0, Math.PI * 2); context.fill();
      drawnPoints.push({ x:across[index], y:y(value), text:`${type.name}, ${longDate(point.createdAt)}: ${Math.round(value).toLocaleString()}${pointUnit}` });
      const text = `${Math.round(value).toLocaleString()}${pointUnit}`;
      (position === own.length - 1 ? latest : others).push({ text, colour, x:across[index], y:y(value), width:context.measureText(text).width });
    });
  });
  // A value over every point runs together too, the more so with several workout types on one line. Each series' latest
  // value is written first, the most recent of them before the rest, then the others from left to right, each only where
  // it clears every value already written. A tap on the chart shows any of them.
  const placed = label => {
    // Beside its point on the right, or on the left where the chart's edge would cut it off.
    const onRight = label.x + 7 + label.width <= width - 2;
    return { ...label, left:onRight ? label.x + 7 : label.x - 7 - label.width, align:onRight ? 'left' : 'right', at:onRight ? label.x + 7 : label.x - 7 };
  };
  const clashes = (a, b) => a.left < b.left + b.width + 6 && b.left < a.left + a.width + 6 && Math.abs(a.y - b.y) < 13;
  const written = [];
  [...latest.sort((a, b) => b.x - a.x), ...others.sort((a, b) => a.x - b.x)].map(placed)
    .forEach(label => { if (!written.some(other => clashes(other, label))) written.push(label); });
  written.sort((a, b) => a.left - b.left).forEach(label => {
    context.fillStyle = label.colour;
    context.textAlign = label.align;
    context.fillText(label.text, label.at, label.y - 8);
  });
}

// The chart in words, for a screen reader, which cannot see the canvas.
function describeChart() {
  if (!chartData.points.length) return 'Nothing to chart.';
  const values = chartData.types.flatMap(type => [...type.values.values()]);
  const [, pointUnit] = metricLabels();
  const amount = value => `${Math.round(value).toLocaleString()}${pointUnit}`;
  const exercise = selectedExercise === 'all' ? 'all exercises' : $('exerciseFilter').selectedOptions[0]?.textContent || selectedExercise;
  const count = plural(chartData.points.length, 'workout');
  return `${$('progressTitle').textContent} for ${exercise}: ${count} from ${longDate(chartData.points[0].createdAt)} to ${longDate(chartData.points[chartData.points.length - 1].createdAt)}, lowest ${amount(Math.min(...values))}, highest ${amount(Math.max(...values))}.`;
}

function renderProgress(workouts) {
  chartData = buildChartData(workouts);
  $('chartEmpty').hidden = Boolean(chartData.points.length);
  $('progressChart').hidden = !chartData.points.length;
  $('progressSummary').textContent = workouts.length === allWorkouts.length ? `${workouts.length} saved workout${workouts.length === 1 ? '' : 's'}` : `${workouts.length} of ${allWorkouts.length} workouts`;
  const labels = chartingTimed()
    ? { weight:['Heaviest weight', 'Track the heaviest weight you have held by workout type and date.'], oneRepMax:['Estimated one-rep max', 'A timed exercise has no one-rep max. Choose Longest hold or Total time held.'], reps:['Longest hold', 'Track your longest hold, in seconds, by workout type and date.'], volume:['Total time held', 'Track the seconds held in each workout, all sets together.'] }
    : { weight:['Heaviest weight', 'Track your heaviest weight by workout type and date.'], oneRepMax:['Estimated one-rep max', 'Your best set in each workout as a one-rep max, from sets of up to 12 reps, so heavier weights and more reps both count.'], reps:['Best reps', 'Track your highest completed reps by workout type and date.'], volume:['Total volume', 'Track total weight moved by workout type and date.'] };
  $('progressTitle').textContent = labels[selectedMetric][0];
  $('progressDescription').textContent = labels[selectedMetric][1];
  if (!chartData.points.length && allWorkouts.length) {
    $('chartEmpty').textContent = selectedMetric === 'oneRepMax'
      ? 'Nothing to chart: a one-rep max needs a set with weight, of 12 reps or fewer.'
      : 'Nothing to chart for these filters.';
  }
  $('legend').innerHTML = chartData.types.map(type => `<div class="legend-item"><span class="legend-swatch"></span><span>${escapeHTML(type.name)}</span></div>`).join('');
  // Set through the DOM: the Content-Security-Policy refuses style="" attributes written into markup.
  $('legend').querySelectorAll('.legend-swatch').forEach((swatch, index) => { swatch.style.background = colors[index % colors.length]; });
  $('progressChart').setAttribute('aria-label', describeChart());
  $('chartDetail').textContent = chartData.points.length ? 'Tap a point to see its value.' : '';
  drawChart();
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

function renderRecords() {
  const unit = weightUnit();
  const records = recordsOf(allWorkouts);
  $('recordsList').innerHTML = records.length ? records.map(record => {
    const lines = [];
    if (record.heaviest) lines.push(['Heaviest', `${formatWeight(record.heaviest.value)} ${unit} × ${record.heaviest.reps}`, record.heaviest.date]);
    if (record.oneRepMax) lines.push(['Est. one-rep max', `${Math.round(record.oneRepMax.value)} ${unit}, from ${formatWeight(record.oneRepMax.weight)} × ${record.oneRepMax.reps}`, record.oneRepMax.date]);
    if (record.reps) lines.push(['Most reps', plural(record.reps.value, 'rep'), record.reps.date]);
    if (record.hold) lines.push(['Longest hold', `${record.hold.value} s`, record.hold.date]);
    return `<li><button class="record" type="button" data-exercise="${escapeHTML(record.key)}"><strong>${escapeHTML(record.name)}</strong>${lines.map(([label, value, date]) =>
      `<span><span class="record-label">${label}</span> ${escapeHTML(value)} <span class="record-date">· ${escapeHTML(longDate(date))}</span></span>`).join('')}</button></li>`;
  }).join('') : '<li class="empty">Your records appear once you have saved a workout.</li>';
}

async function loadProgress() {
  try {
    await window.localReady;
    await flushPendingWorkouts();
    loadedWorkouts = await getSavedWorkouts();
    allWorkouts = loadedWorkouts.map(workout => inUnit(workout));
    populateWorkoutTypes(allWorkouts);
    populateExercises(allWorkouts);
    $('exerciseFilter').value = mostLoggedExercise(allWorkouts);
    selectedMetric = $('metricFilter').value;
    selectedExercise = $('exerciseFilter').value;
    renderProgress(allWorkouts);
    renderRecords();
  } catch (error) {
    $('chartEmpty').hidden = false;
    $('chartEmpty').textContent = 'Progress data could not be loaded.';
    $('recordsList').innerHTML = '<li class="empty">Your records show once your workouts load.</li>';
    console.error('Unable to load progress.', error);
  }
}

let selectedExercise = 'all';
['metricFilter', 'exerciseFilter', 'workoutTypeFilter', 'startDateFilter', 'endDateFilter'].forEach(id => { $(id).onchange = applyFilters; });
// Back to how the page opens: heaviest weight of the exercise done most, over every workout.
$('clearFilters').onclick = () => {
  $('metricFilter').value = 'weight'; $('exerciseFilter').value = mostLoggedExercise(allWorkouts); $('workoutTypeFilter').value = 'all';
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
$('recordsList').onclick = event => {
  const record = event.target.closest('[data-exercise]');
  if (!record) return;
  $('exerciseFilter').value = record.dataset.exercise;
  applyFilters();
  document.querySelector('.progress-card').scrollIntoView({ behavior:'smooth', block:'start' });
};
window.addEventListener('resize', drawChart);
// The theme changes the chart's colours; the unit changes its numbers.
window.addEventListener('settingschange', () => {
  const converted = loadedWorkouts.map(workout => inUnit(workout));
  if (converted.some((workout, index) => workout !== allWorkouts[index])) {
    allWorkouts = converted;
    applyFilters();
    renderRecords();
  } else drawChart();
});
loadProgress();
