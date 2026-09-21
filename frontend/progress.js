const $ = id => document.getElementById(id);
const databaseName = 'workout-tracker';
const databaseVersion = 2;
const workoutStore = 'workouts';
const activeWorkoutStore = 'activeWorkout';
const colors = ['#5b5ce2', '#e26d5c', '#2a9d8f', '#d9912f', '#c25bd8', '#3c8dcc'];
let chartData = null;
let allWorkouts = [];
let selectedMetric = 'weight';

$('today').textContent = new Date().toLocaleDateString(undefined, { weekday:'long', month:'short', day:'numeric' });

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, databaseVersion);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(workoutStore)) database.createObjectStore(workoutStore, { keyPath:'id', autoIncrement:true });
      if (!database.objectStoreNames.contains(activeWorkoutStore)) database.createObjectStore(activeWorkoutStore, { keyPath:'id' });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function getSavedWorkouts() {
  return fetch('/api/workouts').then(response => response.ok ? response.json() : Promise.reject(new Error('Unable to load workouts.'))).then(result => result.workouts);
}

function escapeHTML(value) {
  return String(value).replace(/[&<>'"]/g, character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[character]));
}

function buildChartData(workouts) {
  const types = new Map();
  const points = [];
  [...workouts].sort((a, b) => a.createdAt - b.createdAt).forEach((workout, index) => {
    const name = workout.name || 'Untitled workout';
    const matchingExercises = selectedExercise === 'all' ? workout.exercises : workout.exercises.filter(item => item.name === selectedExercise);
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

function populateExercises(workouts) {
  const selected = $('exerciseFilter').value;
  const names = [...new Set(workouts.flatMap(workout => workout.exercises.map(item => item.name)))].sort();
  $('exerciseFilter').innerHTML = '<option value="all">All exercises</option>' + names.map(name => `<option value="${escapeHTML(name)}">${escapeHTML(name)}</option>`).join('');
  $('exerciseFilter').value = names.includes(selected) ? selected : 'all';
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
  chartData.points.forEach((point, index) => context.fillText(formatDate(point.createdAt), x(index), height - 20));

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
  $('legend').innerHTML = chartData.types.map((type, index) => `<div class="legend-item"><span class="legend-swatch" style="background:${colors[index % colors.length]}"></span><span>${escapeHTML(type.name)}</span></div>`).join('');
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
    $('chartEmpty').textContent = 'Progress data is unavailable on this device.';
    console.error('Unable to load progress.', error);
  }
}

let selectedExercise = 'all';
['metricFilter', 'exerciseFilter', 'workoutTypeFilter', 'startDateFilter', 'endDateFilter'].forEach(id => { $(id).onchange = applyFilters; });
$('clearFilters').onclick = () => { $('metricFilter').value = 'weight'; $('exerciseFilter').value = 'all'; $('workoutTypeFilter').value = 'all'; $('startDateFilter').value = ''; $('endDateFilter').value = ''; selectedMetric = 'weight'; selectedExercise = 'all'; renderProgress(allWorkouts); };
window.addEventListener('resize', drawChart);
window.addEventListener('settingschange', drawChart);
loadProgress();