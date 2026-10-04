// What the Progress page's charts are drawn with, which the exercise chart (progress.js) and the bodyweight chart (bodyweight.js) share:
// sizing the canvas, the page's colours, the lines across it with their numbers, the dates under it, a line through points and
// the dots on it. Each takes a canvas context, and sets what it needs of it, so none depends on what another left behind.
// Loaded before both.

// Sizes the canvas to its box, sharp on a dense screen, clears it, and says what to draw with.
function prepareChart(canvas, height) {
  const width = canvas.clientWidth;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext('2d');
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);
  return { context, width, height };
}

// The page's colours for a chart, which change with the theme: its text, its lines and its accent.
function chartColours() {
  const styles = getComputedStyle(document.documentElement);
  return { ink:styles.getPropertyValue('--muted').trim(), line:styles.getPropertyValue('--line').trim(), accent:styles.getPropertyValue('--accent').trim() };
}

// A line across the chart at each tick, `y(tick)` down, with its number (`label(tick)`) to the left of the chart, `gap` away.
function drawGuides(context, { colours, ticks, y, left, right, width, label, gap }) {
  context.font = '12px Inter, system-ui, sans-serif';
  context.lineWidth = 1;
  context.strokeStyle = colours.line;
  context.fillStyle = colours.ink;
  context.textAlign = 'right';
  ticks.forEach(tick => {
    const position = y(tick);
    context.beginPath(); context.moveTo(left, position); context.lineTo(width - right, position); context.stroke();
    context.fillText(label(tick), left - gap, position + 4);
  });
}

// The chart's name for what it measures, turned to read up the left side.
function drawAxisTitle(context, title, x, y) {
  context.save();
  context.translate(x, y);
  context.rotate(-Math.PI / 2);
  context.textAlign = 'center';
  context.fillText(title, 0, 0);
  context.restore();
}

// Which of a row of labels ({ x, width, text }) there is room to write, a gap apart, always including the last.
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

// A date under every point runs together once there are a few weeks of workouts, so only those with room are written, always
// including the most recent. `points` are { time, x }; the dates are written on `baseline`.
function drawDateLabels(context, points, baseline, colours) {
  context.font = '12px Inter, system-ui, sans-serif';
  context.fillStyle = colours.ink;
  context.textAlign = 'center';
  const dates = points.map(point => {
    const text = formatDate(point.time);
    return { text, x:point.x, width:context.measureText(text).width };
  });
  labelsThatFit(dates, 12).forEach(label => context.fillText(label.text, label.x, baseline));
}

// A line of a colour through points ({ x, y }), in order.
function drawLine(context, points, colour) {
  context.strokeStyle = colour;
  context.lineWidth = 3;
  context.beginPath();
  points.forEach((point, position) => { if (position === 0) context.moveTo(point.x, point.y); else context.lineTo(point.x, point.y); });
  context.stroke();
}

function drawDots(context, points, colour) {
  context.fillStyle = colour;
  points.forEach(point => { context.beginPath(); context.arc(point.x, point.y, 4, 0, Math.PI * 2); context.fill(); });
}
