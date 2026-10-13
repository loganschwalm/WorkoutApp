// Achievement cards: an achievement drawn as a picture to share, 1080 by 1350 (a portrait post), in the colours of the
// theme in use, so it looks like the app it came from. A gold emblem runs off the card's corner, the one bold thing on it:
// a bumper plate stamped with the milestone, or for a plate achievement the bar loaded with that many plates. Under it the
// achievement's name, set large, what it took, a mark for each tier, and the day it was earned. Loaded after
// achievements.js on the Strength, Cardio and Progress pages.
//
// The picture is made at once, in the tap, so the share sheet still counts as the tap's answer (Safari asks for that). The
// share sheet takes files only over HTTPS; elsewhere, and where it refuses, the picture is saved as a file instead.

const achievementCardGold = { face:'#d9a21b', rim:'#b07d10', light:'#f4cc63', stamp:'#4a3300' };
const achievementCardSteel = { face:'#c9ced8', edge:'#9aa2b1' };
const achievementCardFonts = {
  title:size => `800 ${size}px "Schibsted Grotesk", "Helvetica Neue", Arial, sans-serif`,
  mark:size => `700 ${size}px "Schibsted Grotesk", "Helvetica Neue", Arial, sans-serif`,
  body:(size, weight = 500) => `${weight} ${size}px Figtree, system-ui, -apple-system, "Segoe UI", sans-serif`
};

// The faces are loaded only once a page uses them at these weights, and a card drawn before then would be in Arial.
if (document.fonts && document.fonts.load) {
  [achievementCardFonts.title(120), achievementCardFonts.mark(40), achievementCardFonts.body(44), achievementCardFonts.body(44, 600)]
    .forEach(face => document.fonts.load(face).catch(() => {}));
}

// The theme's own colours, read from the page, with the default light theme's where one is missing.
function achievementCardColours() {
  const style = getComputedStyle(document.documentElement);
  const value = (name, fallback) => style.getPropertyValue(name).trim() || fallback;
  return { ground:value('--bg', '#e8ebf0'), card:value('--card', '#fff'), ink:value('--ink', '#0e131d'), muted:value('--muted', '#586174'),
    accent:value('--accent', '#2a43dc'), line:value('--line', '#dbe0e8') };
}

// What the plate is stamped with: the number, and the word under the hub.
function achievementStamp(item, context) {
  const tier = item.tier;
  const compact = number => number >= 1000000 ? `${number / 1000000}M` : number >= 1000 ? `${number / 1000}k` : String(number);
  return {
    workouts:[String(tier), tier === 1 ? 'workout' : 'workouts'], streak:[String(tier), 'weeks'], records:[String(tier), tier === 1 ? 'record' : 'records'],
    volume:[compact(tier), context.unit], distance:[String(tier), context.distanceUnit], cardioTime:[String(tier / 3600), 'hours'],
    exercises:[String(tier), 'exercises'], bigWeek:[String(tier), 'days'], comeback:['2+', 'weeks off']
  }[item.family] || [String(tier), ''];
}

function achievementCardPath(context, x, y, width, height, radius) {
  context.beginPath();
  context.moveTo(x + radius, y);
  context.arcTo(x + width, y, x + width, y + height, radius);
  context.arcTo(x + width, y + height, x, y + height, radius);
  context.arcTo(x, y + height, x, y, radius);
  context.arcTo(x, y, x + width, y, radius);
  context.closePath();
}

function achievementCardCircle(context, x, y, radius) {
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
}

// Words into lines no wider than `width` in the context's font. A number keeps the word after it ("2 plates"), so a line
// never ends on one.
function wrapAchievementCardText(context, text, width) {
  const lines = [];
  let line = '';
  String(text).replace(/(\d) /g, '$1 ').split(/ +/).filter(Boolean).forEach(word => {
    const next = line ? `${line} ${word}` : word;
    if (line && context.measureText(next).width > width) { lines.push(line); line = word; } else line = next;
  });
  if (line) lines.push(line);
  return lines;
}

// The same lines, as even as they go: the narrowest measure that still takes no more lines, so the last is not one word
// on its own (as text-wrap: balance does on the page).
function balanceAchievementCardText(context, text, width) {
  const count = wrapAchievementCardText(context, text, width).length;
  if (count < 2) return wrapAchievementCardText(context, text, width);
  let low = width / count, high = width;
  while (high - low > 4) {
    const middle = (low + high) / 2;
    if (wrapAchievementCardText(context, text, middle).length > count) low = middle; else high = middle;
  }
  return wrapAchievementCardText(context, text, high);
}

// The largest size, from `start` down to `least`, at which the text takes at most `most` lines that each fit, balanced.
// `fits` is false when even the least size does not.
function fitAchievementCardText(context, text, font, start, least, width, most) {
  for (let size = start; size >= least; size -= 2) {
    context.font = font(size);
    const lines = wrapAchievementCardText(context, text, width);
    if (lines.length <= most && lines.every(line => context.measureText(line).width <= width)) return { size, lines:balanceAchievementCardText(context, text, width), fits:true };
  }
  context.font = font(least);
  return { size:least, lines:wrapAchievementCardText(context, text, width), fits:false };
}

// A bumper plate seen face on: gold, its rim, a raised ring, the steel hub with the card showing through, and the stamp.
function drawAchievementPlate(context, x, y, radius, stamp, colours) {
  const gold = achievementCardGold;
  context.save();
  context.shadowColor = 'rgba(14, 19, 29, 0.24)';
  context.shadowBlur = 48;
  context.shadowOffsetY = 18;
  achievementCardCircle(context, x, y, radius);
  context.fillStyle = gold.face;
  context.fill();
  context.restore();
  context.lineWidth = 18;
  context.strokeStyle = gold.rim;
  achievementCardCircle(context, x, y, radius - 9);
  context.stroke();
  // Light on the upper left of the rim.
  context.lineWidth = 7;
  context.strokeStyle = gold.light;
  context.beginPath();
  context.arc(x, y, radius - 26, Math.PI * 1.08, Math.PI * 1.52);
  context.stroke();
  context.lineWidth = 8;
  context.strokeStyle = 'rgba(74, 51, 0, 0.22)';
  achievementCardCircle(context, x, y, radius * 0.64);
  context.stroke();
  achievementCardCircle(context, x, y, radius * 0.19);
  context.fillStyle = achievementCardSteel.face;
  context.fill();
  context.lineWidth = 5;
  context.strokeStyle = achievementCardSteel.edge;
  context.stroke();
  achievementCardCircle(context, x, y, radius * 0.1);
  context.fillStyle = colours.card;
  context.fill();
  context.fillStyle = gold.stamp;
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  // The number in the band between the hub and the raised ring, above; the word below, both clear of the ring.
  const number = fitAchievementCardText(context, stamp[0], achievementCardFonts.title, Math.round(radius * 0.34), 36, radius * 0.86, 1);
  context.font = achievementCardFonts.title(number.size);
  context.fillText(number.lines[0] || '', x, y - radius * 0.4);
  if (stamp[1]) {
    const word = fitAchievementCardText(context, stamp[1], size => achievementCardFonts.body(size, 700), Math.round(radius * 0.16), 24, radius * 0.8, 1);
    context.font = achievementCardFonts.body(word.size, 700);
    context.fillText(word.lines[0] || '', x, y + radius * 0.41);
  }
  context.textAlign = 'left';
  context.textBaseline = 'alphabetic';
}

// The end of a bar seen from the side, loaded with `plates` big plates: the shaft coming in from the left, the collar,
// the plates, and the sleeve past them.
function drawAchievementBarbell(context, plates, card) {
  const gold = achievementCardGold, steel = achievementCardSteel;
  const centre = card.y + 214, plateWidth = 66, gap = 10, plateHeight = 440;
  const end = card.x + card.w - 64;
  const sleeveEnd = end, platesEnd = sleeveEnd - 74;
  const platesStart = platesEnd - plates * (plateWidth + gap) + gap;
  const collar = platesStart - 50;
  context.save();
  context.shadowColor = 'rgba(14, 19, 29, 0.2)';
  context.shadowBlur = 36;
  context.shadowOffsetY = 14;
  context.fillStyle = steel.face;
  achievementCardPath(context, card.x + 80, centre - 14, collar - card.x - 80, 28, 14);
  context.fill();
  achievementCardPath(context, collar, centre - 30, sleeveEnd - collar, 60, 12);
  context.fill();
  achievementCardPath(context, collar, centre - 64, 40, 128, 10);
  context.fill();
  for (let index = 0; index < plates; index += 1) {
    const left = platesStart + index * (plateWidth + gap);
    achievementCardPath(context, left, centre - plateHeight / 2, plateWidth, plateHeight, 14);
    context.fillStyle = gold.face;
    context.fill();
  }
  context.restore();
  for (let index = 0; index < plates; index += 1) {
    const left = platesStart + index * (plateWidth + gap);
    context.fillStyle = gold.rim;
    context.fillRect(left + plateWidth - 14, centre - plateHeight / 2 + 12, 8, plateHeight - 24);
    context.fillStyle = gold.light;
    context.fillRect(left + 10, centre - plateHeight / 2 + 22, 6, plateHeight - 44);
  }
  context.strokeStyle = steel.edge;
  context.lineWidth = 4;
  achievementCardPath(context, collar, centre - 64, 40, 128, 10);
  context.stroke();
}

// The card for an achievement, `item` being one of achievementsOf's earned and `result` the achievements it came from.
function drawAchievementCard(item, result) {
  const canvas = document.createElement('canvas');
  canvas.width = 1080;
  canvas.height = 1350;
  const context = canvas.getContext('2d');
  const colours = achievementCardColours();
  const card = { x:64, y:64, w:952, h:1130 };
  context.fillStyle = colours.ground;
  context.fillRect(0, 0, canvas.width, canvas.height);
  achievementCardPath(context, card.x, card.y, card.w, card.h, 56);
  context.fillStyle = colours.card;
  context.fill();

  // The emblem over the card's top right, past its corner but inside the picture.
  if (plateLifts[item.family]) drawAchievementBarbell(context, item.tier, card);
  else drawAchievementPlate(context, card.x + card.w - 200, card.y + 196, 232, achievementStamp(item, result.context), colours);

  // The name, what it took and the tier marks share the room between the emblem and the footer: the name as large as
  // fits there, up to three lines.
  const left = card.x + 80, width = card.w - 160;
  const footer = card.y + card.h - 214;
  const top = card.y + 478, room = footer - 56 - top;
  const family = result.families.find(entry => entry.id === item.family);
  const marks = family && family.tiers.length > 1 ? 32 + 40 : 0;
  const detail = fitAchievementCardText(context, item.detail, size => achievementCardFonts.body(size), 42, 30, width, 3);
  const detailHeight = detail.lines.length * detail.size * 1.32;
  let title = null;
  for (let size = 150; size >= 64; size -= 2) {
    title = fitAchievementCardText(context, item.name, achievementCardFonts.title, size, size, width, 3);
    if (title.fits && title.lines.length * size + 30 + detailHeight + marks <= room) break;
  }
  // Set against the bottom of the room, so a short name sits on the footer rather than under the emblem.
  let y = footer - 56 - (title.lines.length * title.size + 30 + detailHeight + marks);
  context.fillStyle = colours.ink;
  context.font = achievementCardFonts.title(title.size);
  if ('letterSpacing' in context) context.letterSpacing = `${-Math.round(title.size * 0.025)}px`;
  title.lines.forEach((line, index) => context.fillText(line, left, y + title.size * 0.84 + index * title.size));
  if ('letterSpacing' in context) context.letterSpacing = '0px';
  y += title.lines.length * title.size + 30;
  context.fillStyle = colours.muted;
  context.font = achievementCardFonts.body(detail.size);
  detail.lines.forEach((line, index) => context.fillText(line, left, y + detail.size + index * detail.size * 1.32));
  y += detailHeight + 40;

  // A mark for each tier of the kind: gold up to this one, open after it.
  const reached = family ? family.tiers.indexOf(item.tier) : -1;
  if (marks) {
    family.tiers.forEach((tier, index) => {
      achievementCardCircle(context, left + 16 + index * 46, y + 16, 15);
      if (index <= reached) {
        context.fillStyle = achievementCardGold.face;
        context.fill();
      } else {
        context.lineWidth = 4;
        context.strokeStyle = colours.line;
        context.stroke();
      }
    });
  }

  context.fillStyle = colours.line;
  context.fillRect(left, footer, width, 3);
  context.fillStyle = colours.ink;
  context.font = achievementCardFonts.body(46, 600);
  context.fillText(`Earned ${new Date(item.at).toLocaleDateString(undefined, { year:'numeric', month:'long', day:'numeric' })}`, left, footer + 86);
  const workouts = result.families.find(entry => entry.id === 'workouts');
  const first = result.earned.find(entry => entry.id === 'workouts:1');
  const support = item.family === 'workouts' && first
    ? `Training since ${new Date(first.at).toLocaleDateString(undefined, { year:'numeric', month:'long' })}`
    : workouts ? `${plural(workouts.value, 'workout')} logged so far` : '';
  context.fillStyle = colours.muted;
  context.font = achievementCardFonts.body(38);
  context.fillText(support, left, footer + 146);

  // The app's name on the ground under the card, after a square of the theme's accent.
  const base = card.y + card.h + 96;
  achievementCardPath(context, card.x + 8, base - 30, 32, 32, 9);
  context.fillStyle = colours.accent;
  context.fill();
  context.fillStyle = colours.ink;
  context.font = achievementCardFonts.mark(40);
  context.fillText('Workout Tracker', card.x + 58, base);
  return canvas;
}

// The picture as a file's bytes, made without waiting, so the tap still counts when the share sheet opens.
function achievementCardBlob(canvas) {
  const data = atob(canvas.toDataURL('image/png').split(',')[1]);
  const bytes = new Uint8Array(data.length);
  for (let index = 0; index < data.length; index += 1) bytes[index] = data.charCodeAt(index);
  return new Blob([bytes], { type:'image/png' });
}

function saveAchievementCard(blob, name) {
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 60000);
  return `Saved ${name}. Post it wherever you like.`;
}

// Shares the card through the phone's share sheet where it takes a picture, or saves it. Resolves to what to tell the
// lifter: '' once shared or when the share sheet was closed without sharing, or that it was saved.
function shareAchievementCard(item, result) {
  const blob = achievementCardBlob(drawAchievementCard(item, result));
  const name = `${String(item.name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'achievement'}.png`;
  const file = typeof File === 'function' ? new File([blob], name, { type:'image/png' }) : null;
  if (file && navigator.share && navigator.canShare && navigator.canShare({ files:[file] })) {
    return navigator.share({ files:[file], title:item.name, text:`${item.name}: ${item.detail}.` })
      .then(() => '', error => error && error.name === 'AbortError' ? '' : saveAchievementCard(blob, name));
  }
  return Promise.resolve(saveAchievementCard(blob, name));
}
