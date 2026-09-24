const colors = ['#5b5ce2', '#e26d5c', '#2a9d8f', '#d9912f', '#c25bd8', '#3c8dcc'];
let chartData = null;
let allWorkouts = [];
let selectedMetric = 'weight';

function buildChartData(workouts) {
  const types = new Map();
  const points = [];
  [...workouts].sort((a, b) => a.createdAt - b.createdAt).forEach((workout, index) => {
    const name = workout.name || 'Untitled workout';
    // An exercise saved with an empty set list was skipped, so it has no result to chart.
    const matchingExercises = (selectedExercise === 'all' ? workout.exercises : workout.exercises.filter(item => exerciseKey(item.name) === selectedExercise)).filter(item => !item.sets || item.sets.length);
    const values = matchingExercises.map(item => {
      if (selectedMetric === 'reps') return Math.max(...(item.sets || []).map(set => Number(set.reps) || 0), Number(item.reps) || 0);
      if (selectedMetric === 'volume') return item.sets?.length ? item.sets.reduce((total, set) => total + (Number(set.weight) || 0) * (Number(set.reps) || 0), 0) : (Number(item.weight) || 0) * (Number(item.reps) || 0);
      return Math.max(...(item.sets || []).map(set => Number(set.weight) || 0), Number(item.weight) || 0);
    });
    const metricValue = selectedMetric === 'volume' ? values.reduce((total, value) => total + value, 0) : Math.max(...values, 0);
    if (!matchingExercises.length) return;
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
  [...workouts].sort((a, b) => b.createdAt - a.createdAt).forEach(workout => workout.exercises.forEach(item => {
    const key = exerciseKey(item.name);
    if (key && !labels.has(key)) labels.set(key, String(item.name).trim());
  }));
  const options = [...labels].sort(([, a], [, b]) => a.localeCompare(b, undefined, { sensitivity:'base' }));
  $('exerciseFilter').innerHTML = '<option value="all">All exercises</option>' + options.map(([key, label]) => `<option value="${escapeHTML(key)}">${escapeHTML(label)}</option>`).join('');
  $('exerciseFilter').value = labels.has(selected) ? selected : 'all';
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

function drawChart() {
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
  const x = index => chartData.points.length === 1 ? left + chartWidth / 2 : left + index / (chartData.points.length - 1) * chartWidth;
  const y = value => top + chartHeight - value / maximum * chartHeight;
  const metricLabel = selectedMetric === 'weight' ? 'Weight (lbs)' : selectedMetric === 'reps' ? 'Reps' : 'Volume';

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
  // A date under every point runs together once there are a few weeks of workouts, so only as many as fit are written,
  // evenly spaced and always including the most recent.
  const last = chartData.points.length - 1;
  const labelWidth = Math.max(...chartData.points.map(point => context.measureText(formatDate(point.createdAt)).width)) + 12;
  const every = last ? Math.max(1, Math.ceil(labelWidth / (chartWidth / last))) : 1;
  chartData.points.forEach((point, index) => {
    if (index === last || (index % every === 0 && last - index >= every)) context.fillText(formatDate(point.createdAt), x(index), height - 20);
  });

  chartData.types.forEach((type, typeIndex) => {
    context.strokeStyle = colors[typeIndex % colors.length];
    context.fillStyle = colors[typeIndex % colors.length];
    context.lineWidth = 3;
    const own = chartData.points.map((point, index) => ({ index, value:type.values.get(point.key) })).filter(entry => entry.value !== undefined);
    context.beginPath();
    own.forEach((entry, position) => {
      if (position === 0) context.moveTo(x(entry.index), y(entry.value)); else context.lineTo(x(entry.index), y(entry.value));
    });
    context.stroke();
    own.forEach(({ index, value }) => {
      context.beginPath(); context.arc(x(index), y(value), 4, 0, Math.PI * 2); context.fill();
      context.textAlign = 'left';
      context.font = '11px system-ui, sans-serif';
      context.fillText(`${Math.round(value).toLocaleString()}${selectedMetric === 'weight' ? ' lbs' : ''}`, x(index) + 7, y(value) - 8);
    });
  });
}

function renderProgress(workouts) {
  chartData = buildChartData(workouts);
  $('chartEmpty').hidden = Boolean(chartData.points.length);
  $('progressChart').hidden = !chartData.points.length;
  $('progressSummary').textContent = workouts.length === allWorkouts.length ? `${workouts.length} saved workout${workouts.length === 1 ? '' : 's'}` : `${workouts.length} of ${allWorkouts.length} workouts`;
  const labels = { weight:['Heaviest weight', 'Track your heaviest weight by workout type and date.', 'Weight (lbs)'], reps:['Best reps', 'Track your highest completed reps by workout type and date.', 'Reps'], volume:['Total volume', 'Track total weight moved by workout type and date.', 'Volume'] };
  $('progressTitle').textContent = labels[selectedMetric][0];
  $('progressDescription').textContent = labels[selectedMetric][1];
  $('legend').innerHTML = chartData.types.map(type => `<div class="legend-item"><span class="legend-swatch"></span><span>${escapeHTML(type.name)}</span></div>`).join('');
  // Set through the DOM: the Content-Security-Policy refuses style="" attributes written into markup.
  $('legend').querySelectorAll('.legend-swatch').forEach((swatch, index) => { swatch.style.background = colors[index % colors.length]; });
  drawChart();
}

async function loadProgress() {
  try {
    await window.localReady;
    await flushPendingWorkouts();
    allWorkouts = await getSavedWorkouts();
    populateWorkoutTypes(allWorkouts);
    populateExercises(allWorkouts);
    selectedMetric = $('metricFilter').value;
    selectedExercise = $('exerciseFilter').value;
    renderProgress(allWorkouts);
  } catch (error) {
    $('chartEmpty').hidden = false;
    $('chartEmpty').textContent = 'Progress data could not be loaded.';
    console.error('Unable to load progress.', error);
  }
}

let selectedExercise = 'all';
['metricFilter', 'exerciseFilter', 'workoutTypeFilter', 'startDateFilter', 'endDateFilter'].forEach(id => { $(id).onchange = applyFilters; });
$('clearFilters').onclick = () => { $('metricFilter').value = 'weight'; $('exerciseFilter').value = 'all'; $('workoutTypeFilter').value = 'all'; $('startDateFilter').value = ''; $('endDateFilter').value = ''; selectedMetric = 'weight'; selectedExercise = 'all'; renderProgress(allWorkouts); };
window.addEventListener('resize', drawChart);
window.addEventListener('settingschange', drawChart);
loadProgress();