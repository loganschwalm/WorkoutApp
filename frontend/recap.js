// Last week, on the Tracker: a card from the first visit of a new week, until Done, saying how the week before went (its
// workouts against the weekly goal and the streak, how it compares with the week before, its totals, the records it set and
// the achievements it earned). Worked out from the history (weekRecapOf, achievements.js), and only once all of it has
// loaded. A week with nothing in it has no card: a recap is a look back at what was done, never a reminder of what was not.
// Done is kept on this device, by the week's Monday, so the next week's card comes by itself. Loaded on the Tracker after
// achievements.js; saved-workouts.js draws it once the saved workouts have loaded, and again when the settings change.

// Last week and What's new are a line each until opened: the Tracker's first screen is for starting a workout, and these are
// news. The toggle is the card's heading, which opens its body; the line under the heading says what is inside and gives way to
// the body when it opens. Whether it is open is not kept, so each visit begins with the one line.
function wireBanner(toggle, body, line) {
  $(toggle).onclick = () => {
    const open = $(toggle).getAttribute('aria-expanded') !== 'true';
    $(toggle).setAttribute('aria-expanded', String(open));
    $(body).hidden = !open;
    $(line).hidden = open;
  };
}

// Monday of last week, as the History calendar counts weeks.
function recapMonday() {
  return addDays(startOfWeek(new Date()), -7);
}

// "4 workouts, your goal of 3 reached: a 5-week streak."
function recapHeadline(recap) {
  const done = plural(recap.sessions, 'workout');
  if (!recap.reached) return `${done}. A new streak can start this week.`;
  return recap.streak >= 2 ? `${done}, your goal of ${recap.goal} reached: a ${recap.streak}-week streak.` : `${done}, your goal of ${recap.goal} reached.`;
}

// "1 more workout than the week before, and 12% more volume.", or '' after a week with nothing to compare with.
function recapComparison(recap) {
  const { sessions, volume } = recap.previous;
  if (!sessions) return '';
  const difference = recap.sessions - sessions;
  const count = difference > 0 ? `${plural(difference, 'workout')} more than the week before`
    : difference < 0 ? `${plural(-difference, 'workout')} fewer than the week before` : 'As many workouts as the week before';
  const percent = volume > 0 && recap.volume > 0 ? Math.round((recap.volume - volume) / volume * 100) : null;
  const lifted = percent === null ? '' : percent ? `, and ${Math.abs(percent)}% ${percent > 0 ? 'more' : 'less'} volume` : ', and the same volume';
  return `${count.charAt(0).toUpperCase()}${count.slice(1)}${lifted}.`;
}

function renderRecap() {
  const card = $('recapCard');
  const monday = recapMonday();
  const recap = savedWorkoutsLoaded && readLocal(localKey('recap-dismissed')) !== calendarDayKey(monday)
    ? weekRecapOf([...savedSessions, ...readPendingWorkouts()], monday) : null;
  card.hidden = !recap;
  if (!recap) return;
  const day = date => date.toLocaleDateString(undefined, { month:'short', day:'numeric' });
  $('recapRange').textContent = `${day(monday)} – ${day(addDays(monday, 6))}`;
  $('recapHeadline').textContent = recapHeadline(recap);
  $('recapLine').textContent = recap.biggest ? `Your biggest week of lifting yet. ${recapHeadline(recap)}` : recapHeadline(recap);
  $('recapBest').hidden = !recap.biggest;
  const comparison = recapComparison(recap);
  $('recapCompare').textContent = comparison;
  $('recapCompare').hidden = !comparison;
  const { unit, distanceUnit } = recap.context;
  const stats = [[String(recap.sessions), recap.sessions === 1 ? 'Workout' : 'Workouts'],
    ...(recap.seconds ? [[formatDuration(recap.seconds), 'Time']] : []),
    ...(recap.sets ? [[String(recap.sets), recap.sets === 1 ? 'Set' : 'Sets']] : []),
    ...(recap.volume ? [[`${Math.round(recap.volume).toLocaleString()} ${unit}`, 'Volume']] : []),
    ...(recap.distance ? [[`${Math.round(recap.distance * 10) / 10} ${distanceUnit}`, 'Distance']] : [])];
  $('recapStats').innerHTML = stats.map(([value, label]) => `<li><strong>${escapeHTML(value)}</strong><span>${escapeHTML(label)}</span></li>`).join('');
  // Up to three records, each exercise's latest, and how many more there were.
  const shown = recap.records.slice(0, 3);
  const more = recap.recordCount - shown.length;
  $('recapRecords').hidden = !recap.recordCount;
  $('recapRecordsTitle').textContent = recap.recordCount === 1 ? '1 personal record' : `${recap.recordCount} personal records`;
  $('recapRecordList').innerHTML = shown.map(line => `<li>${escapeHTML(line)}</li>`).join('')
    + (more > 0 ? `<li class="recap-more">and ${more} more</li>` : '');
  $('recapAchievements').hidden = !recap.earned.length;
  renderEarnedAchievements($('recapAchievementList'), recap.earned, recap.achievements);
}

wireBanner('recapToggle', 'recapBody', 'recapLine');

// Dismiss puts the card away until next week, and the keyboard carries on from the templates under it.
$('recapDone').onclick = () => {
  writeLocal(localKey('recap-dismissed'), calendarDayKey(recapMonday()));
  $('recapCard').hidden = true;
  $('templatesToggle')?.focus();
};
