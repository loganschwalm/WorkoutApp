// Bodyweight, on the Progress page: one weight a day, logged here and kept with the account (offline.js keeps it on the
// device first and uploads it, as it does goals), charted over time with how it has moved lately. Each weight keeps the
// unit it was logged in and is only converted for showing, so switching units never changes what was logged. Loaded
// after progress.js, whose date helpers and chart style it shares.

// { 'YYYY-MM-DD': { weight, unit } }: the day weighed, by the calendar of whoever logged it.
let bodyweights = {};
// Where each weigh-in was drawn, so a tap can say which one it was.
let bodyweightPoints = [];
// The newest few are listed under the chart, to see what was logged and take one away.
const bodyweightListed = 5;

function loadBodyweights() {
  const stored = readLocalState('bodyweight');
  bodyweights = stored && stored.value && typeof stored.value === 'object' && !Array.isArray(stored.value) ? stored.value : {};
}

function saveBodyweights() {
  saveLocalState('bodyweight', bodyweights);
}

function dayKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

// Midnight at the start of a day, where this device is.
function dayStart(key) {
  const [year, month, day] = key.split('-').map(Number);
  return new Date(year, month - 1, day).getTime();
}

// "181.4": bodyweight to a tenth, which is as fine as a scale shows.
function formatBodyweight(weight) {
  return formatWeight(Math.round(weight * 10) / 10);
}

// Every weigh-in in the unit shown, oldest first. Anything malformed (a hand-edited import) is left out.
function bodyweightEntries() {
  const unit = weightUnit();
  return Object.entries(bodyweights)
    .filter(([day, entry]) => /^\d{4}-\d{2}-\d{2}$/.test(day) && entry && Number(entry.weight) > 0)
    .map(([day, entry]) => ({ day, time:dayStart(day), weight:Number(convertWeight(Number(entry.weight), entry.unit === 'kg' ? 'kg' : 'lbs', unit)) }))
    .sort((a, b) => a.time - b.time);
}

// How the weight has moved: over the last 30 days, measured from the last weigh-in at least that long before the latest;
// with none that old, since the first. "Down 2.4 lbs in 30 days", "Up 0.8 kg since Sep 12".
function bodyweightTrend(entries) {
  if (entries.length < 2) return '';
  const latest = entries[entries.length - 1];
  const monthAgo = latest.time - 30 * 24 * 60 * 60 * 1000;
  const earlier = [...entries].reverse().find(entry => entry.time <= monthAgo);
  const from = earlier || entries[0];
  const change = Math.round((latest.weight - from.weight) * 10) / 10;
  const when = earlier ? `in ${Math.round((latest.time - from.time) / (24 * 60 * 60 * 1000))} days` : `since ${formatDate(from.time)}`;
  if (!change) return `No change ${when}`;
  return `${change < 0 ? 'Down' : 'Up'} ${formatBodyweight(Math.abs(change))} ${weightUnit()} ${when}`;
}

function drawBodyweight() {
  bodyweightPoints = [];
  const entries = bodyweightEntries();
  const canvas = $('bodyweightChart');
  if (!entries.length || canvas.hidden) return;
  const width = canvas.clientWidth;
  const height = 220;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext('2d');
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  const styles = getComputedStyle(document.documentElement);
  const ink = styles.getPropertyValue('--muted').trim();
  const line = styles.getPropertyValue('--line').trim();
  const accent = styles.getPropertyValue('--accent').trim();
  const left = 52, right = 20, top = 18, bottom = 40;
  const chartWidth = Math.max(width - left - right, 1);
  const chartHeight = height - top - bottom;
  // A little room above and below, so a flat stretch is not drawn along an edge, and the scale widened to round steps
  // (1, 2, 2.5 or 5 of a power of ten) so its lines fall on numbers a scale would show: 180, 182, 184.
  const weights = entries.map(entry => entry.weight);
  const padding = Math.max(1, (Math.max(...weights) - Math.min(...weights)) * 0.15);
  const rough = (Math.max(...weights) - Math.min(...weights) + 2 * padding) / 3;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map(multiple => multiple * magnitude).find(size => size >= rough);
  const low = Math.floor((Math.min(...weights) - padding) / step) * step;
  const high = Math.ceil((Math.max(...weights) + padding) / step) * step;
  const first = entries[0].time, span = entries[entries.length - 1].time - first;
  const x = entry => span ? left + (entry.time - first) / span * chartWidth : left + chartWidth / 2;
  const y = weight => top + chartHeight - (weight - low) / (high - low) * chartHeight;

  context.font = '12px Inter, system-ui, sans-serif';
  context.lineWidth = 1;
  context.strokeStyle = line;
  context.fillStyle = ink;
  context.textAlign = 'right';
  for (let tick = 0; low + tick * step <= high + step / 1000; tick += 1) {
    const weight = low + tick * step;
    context.beginPath(); context.moveTo(left, y(weight)); context.lineTo(width - right, y(weight)); context.stroke();
    context.fillText(formatBodyweight(weight), left - 8, y(weight) + 4);
  }
  context.textAlign = 'center';
  const dates = entries.map(entry => { const text = formatDate(entry.time); return { text, x:x(entry), width:context.measureText(text).width }; });
  labelsThatFit(dates, 12).forEach(label => context.fillText(label.text, label.x, height - 14));

  context.strokeStyle = accent;
  context.fillStyle = accent;
  context.lineWidth = 3;
  context.beginPath();
  entries.forEach((entry, index) => { if (index) context.lineTo(x(entry), y(entry.weight)); else context.moveTo(x(entry), y(entry.weight)); });
  context.stroke();
  // Dots while they have room; months of daily weigh-ins read better as the line alone, with the latest marked.
  const dots = entries.length <= chartWidth / 8 ? entries : [entries[entries.length - 1]];
  dots.forEach(entry => { context.beginPath(); context.arc(x(entry), y(entry.weight), 4, 0, Math.PI * 2); context.fill(); });
  entries.forEach(entry => bodyweightPoints.push({ x:x(entry), y:y(entry.weight), text:`${longDate(entry.time)}: ${formatBodyweight(entry.weight)} ${weightUnit()}` }));
  // The latest value is written on the side of its point away from the line coming into it: under it when the weight
  // came down, over it when it went up, so the line never runs through the number.
  const latest = entries[entries.length - 1];
  const before = entries[entries.length - 2];
  const text = formatBodyweight(latest.weight);
  context.font = '12px Inter, system-ui, sans-serif';
  const onRight = x(latest) + 8 + context.measureText(text).width <= width - 2;
  context.textAlign = onRight ? 'left' : 'right';
  context.fillText(text, x(latest) + (onRight ? 8 : -8), y(latest.weight) + (before && before.weight > latest.weight ? 18 : -9));
}

function renderBodyweight() {
  applyUnitLabels();
  const entries = bodyweightEntries();
  const unit = weightUnit();
  const latest = entries[entries.length - 1];
  $('bodyweightSummary').textContent = latest
    ? [`${formatBodyweight(latest.weight)} ${unit} on ${formatDate(latest.time)}`, bodyweightTrend(entries) || 'Log it again to see how it moves'].join(' · ')
    : 'Log your weight to see how it changes alongside your lifts.';
  $('bodyweightChart').hidden = !entries.length;
  $('bodyweightChart').setAttribute('aria-label', entries.length
    ? `Bodyweight: ${plural(entries.length, 'weigh-in')} from ${longDate(entries[0].time)} to ${longDate(latest.time)}, lowest ${formatBodyweight(Math.min(...entries.map(entry => entry.weight)))} ${unit}, `
      + `highest ${formatBodyweight(Math.max(...entries.map(entry => entry.weight)))} ${unit}, latest ${formatBodyweight(latest.weight)} ${unit}.`
    : 'No bodyweight logged yet.');
  $('bodyweightDetail').textContent = entries.length > 1 ? 'Tap a point to see its value.' : '';
  $('bodyweightList').innerHTML = [...entries].reverse().slice(0, bodyweightListed).map(entry => '<li>'
    + `<span>${escapeHTML(longDate(entry.time))}</span><strong>${escapeHTML(formatBodyweight(entry.weight))} ${unit}</strong>`
    + `<button class="link-button" type="button" data-bodyweight-remove="${escapeHTML(entry.day)}" aria-label="Remove the weight for ${escapeHTML(longDate(entry.time))}">Remove</button></li>`).join('');
  $('bodyweightDate').max = dayKey(new Date());
  if (!$('bodyweightDate').value) $('bodyweightDate').value = dayKey(new Date());
  drawBodyweight();
}

function showBodyweightFeedback(message, isError = false) {
  $('bodyweightFeedback').textContent = message;
  $('bodyweightFeedback').classList.toggle('error', isError);
}

$('bodyweightForm').onsubmit = event => {
  event.preventDefault();
  const weight = Number($('bodyweightValue').value);
  const day = $('bodyweightDate').value;
  if (!($('bodyweightValue').value !== '' && weight > 0 && weight <= 2000)) {
    showBodyweightFeedback('Enter your weight, above zero.', true);
    $('bodyweightValue').focus();
    return;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || day > dayKey(new Date())) {
    showBodyweightFeedback('Choose the day you weighed in, today or before.', true);
    $('bodyweightDate').focus();
    return;
  }
  const replaced = day in bodyweights;
  // One a day: weighing in again that day replaces it.
  bodyweights = { ...bodyweights, [day]:{ weight:Math.round(weight * 100) / 100, unit:weightUnit() } };
  saveBodyweights();
  $('bodyweightValue').value = '';
  $('bodyweightDate').value = dayKey(new Date());
  renderBodyweight();
  const when = day === dayKey(new Date()) ? 'today' : longDate(dayStart(day));
  showBodyweightFeedback(`${replaced ? 'Updated' : 'Logged'} ${formatBodyweight(weight)} ${weightUnit()} for ${when}.`);
};

$('bodyweightList').onclick = event => {
  const button = event.target.closest('[data-bodyweight-remove]');
  if (!button || !(button.dataset.bodyweightRemove in bodyweights)) return;
  const day = button.dataset.bodyweightRemove;
  bodyweights = { ...bodyweights };
  delete bodyweights[day];
  saveBodyweights();
  renderBodyweight();
  showBodyweightFeedback(`Removed the weight for ${longDate(dayStart(day))}.`);
};

// A tap on the chart says which weigh-in is nearest, since only the latest has its value written.
$('bodyweightChart').addEventListener('click', event => {
  const bounds = $('bodyweightChart').getBoundingClientRect();
  const tapX = event.clientX - bounds.left, tapY = event.clientY - bounds.top;
  const distance = point => Math.hypot(point.x - tapX, point.y - tapY);
  const nearest = bodyweightPoints.reduce((best, point) => !best || distance(point) < distance(best) ? point : best, null);
  if (nearest && distance(nearest) <= 40) $('bodyweightDetail').textContent = nearest.text;
});

loadBodyweights();
renderBodyweight();
window.addEventListener('resize', drawBodyweight);
document.fonts.ready.then(drawBodyweight);
// The server's copy replaces this device's once it answers, unless a weight logged here is still uploading.
window.serverStateReady.then(() => { loadBodyweights(); renderBodyweight(); });
// The unit changes the numbers; the theme, the colours.
window.addEventListener('settingschange', renderBodyweight);
