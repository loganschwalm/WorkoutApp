// What's new, on the Tracker: once a release, a card telling someone who was already training what the app has learned since,
// a line for each thing, until Done. It is for those who started before the release: a newer account learned the app as it
// is (the welcome, onboarding.js, shows it), so it never sees the card for a release it began on. Done is kept as a setting,
// `seenWhatsNew` (settings-fields.js), so it is seen once on every device. Loaded on the Tracker after recap.js; script.js
// draws it once the saved workouts have loaded, and again when the settings change.
//
// A new release adds its own list here and moves `whatsNewRelease` on; the card then shows to everyone who trained before it.

const whatsNewRelease = { id:'2026-10', from:'2026-10-12', name:'October 2026' };

// What is new, the most useful first; the first three show, and the rest fold under them. A link goes to where it lives.
const whatsNewItems = [
  { title:'Achievements', text:'Milestones worked out from your own workouts: plates on the bar, weekly streaks, records beaten and more, each with the day you earned it. Share one as a picture.',
    link:['progress.html#achievements', 'See yours on Progress'] },
  { title:'Within reach', text:'During a workout, the app says what the next set would be a record of, and what finishing the workout earns.' },
  { title:'Big view', text:'A button in a workout shows the set and the rest clock in large type, to read from the bench. Settings can open it for every rest.' },
  { title:'Last week', text:'Each new week starts with a look back at the last: your goal, your streak, your records and achievements.' },
  { title:'Program moments', text:'A + set past its plan, every planned rep made, and a finished cycle are celebrated, with fireworks across the screen.' },
  { title:'One exercise at a time', text:'Choose an exercise on Progress for its records, the heaviest weight it has done for 1 to 10 reps, its goal, and whether it has stalled.' },
  { title:'Strava export', text:'Download a finished workout or cardio session as a .tcx file for Strava, from its summary or from History.' }
];

// Someone who was training before the release: a workout of theirs is older than it. A newer account, or one with nothing
// logged, has nothing to catch up on.
function whatsNewOwed() {
  if (!savedWorkoutsLoaded || getWorkoutSettings().seenWhatsNew === whatsNewRelease.id) return false;
  const release = dayStart(whatsNewRelease.from);
  return [...savedSessions, ...readPendingWorkouts()].some(session => Number(session.createdAt) < release);
}

function whatsNewItemHTML(item) {
  return `<li><strong>${escapeHTML(item.title)}</strong><span>${escapeHTML(item.text)}</span>`
    + (item.link ? `<a class="past-sessions-link" href="${escapeHTML(item.link[0])}">${escapeHTML(item.link[1])}</a>` : '') + '</li>';
}

function renderWhatsNew() {
  const owed = whatsNewOwed();
  $('whatsNewCard').hidden = !owed;
  if (!owed) return;
  $('whatsNewRelease').textContent = whatsNewRelease.name;
  $('whatsNewList').innerHTML = whatsNewItems.slice(0, 3).map(whatsNewItemHTML).join('');
  const more = whatsNewItems.slice(3);
  $('whatsNewMore').hidden = !more.length;
  $('whatsNewMoreTitle').textContent = `${more.length} more`;
  $('whatsNewMoreList').innerHTML = more.map(whatsNewItemHTML).join('');
}

// Done marks this release seen, for the account, and the keyboard carries on from the templates under it.
$('whatsNewDone').onclick = () => {
  saveLocalState('settings', { ...getWorkoutSettings(), seenWhatsNew:whatsNewRelease.id });
  window.dispatchEvent(new Event('settingschange'));
  $('whatsNewCard').hidden = true;
  $('templatesToggle')?.focus();
};
