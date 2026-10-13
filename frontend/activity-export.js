// Download a finished workout or cardio session as a .tcx file (Garmin's Training Center XML), from the summary shown when
// one is finished and from History's ⋯ menu. Strava takes the file on its website's upload page, and apps such as HealthFit
// take it to write the session to Apple Health, which cannot read a file itself. It is made on the device from the workout
// as it is, so it works offline and before the workout has reached the server.
//
// The file is one activity of one lap with two trackpoints, at the start and at the end (the format wants a track for a time
// and a distance). There is no route or heart-rate stream because none was recorded: the average heart rate is on the lap
// only. A session's time of day is when it finished, which is what createdAt is for a timed one, so it started its duration
// before that. A workout with no duration (saved from the form without a timer) has no time to give, so it is not offered.

// The characters a XML text may not hold (control characters but tab and line breaks) are dropped; the rest are escaped.
function tcxText(value) {
  return escapeHTML(String(value).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, ''));
}

function canExportActivity(workout) {
  return Boolean(workout) && Number(workout.duration) > 0 && Number(workout.createdAt) > 0;
}

// The format has Running, Biking and Other; Strava lets the lifter change the type when uploading.
function tcxSport(workout) {
  if (!isCardio(workout)) return 'Other';
  return { run:'Running', cycle:'Biking', bike:'Biking' }[activityOf(workout).id] || 'Other';
}

// How far a cardio session went, in metres, from the distance as it was entered (not as shown, which Settings can change).
// Floors and a session with no distance have none: 0.
function tcxMeters(workout) {
  const distance = Number(workout.cardio && workout.cardio.distance);
  if (!isCardio(workout) || !(distance > 0) || !activityOf(workout).distance) return 0;
  return Math.round(convertDistance(distance, enteredDistanceUnit(workout), 'm') * 10) / 10;
}

// The format has no title, so the name leads the notes, then what was done in the units shown, then the workout's own notes.
function tcxNotes(workout) {
  const done = isCardio(workout) ? [describeCardio(workout)]
    : inUnit(workout).exercises.filter(item => !item.sets || item.sets.length).map(item => `${String(item.name).trim()}: ${describeSavedExercise(item)}`);
  return [String(workout.name || 'Workout').trim(), ...done, ...workout.notes ? [String(workout.notes).trim()] : []].join('\n');
}

// A time as the format writes it: UTC, to the second.
function tcxTime(time) {
  return new Date(time).toISOString().replace(/\.\d{3}Z$/, 'Z');
}

// The element order is the schema's (Lap: time, distance, calories, heart rate, intensity, trigger, track), which a strict
// reader holds to. Nothing may come before the XML declaration.
function tcxFile(workout) {
  const seconds = Math.round(Number(workout.duration));
  const start = tcxTime(Number(workout.createdAt) - seconds * 1000), end = tcxTime(workout.createdAt);
  const cardio = workout.cardio || {};
  const meters = tcxMeters(workout);
  const calories = Math.round(Number(cardio.calories)) > 0 ? Math.round(Number(cardio.calories)) : 0;
  const heartRate = Math.round(Number(cardio.heartRate)) > 0 ? Math.round(Number(cardio.heartRate)) : 0;
  const point = (time, distance) => `<Trackpoint><Time>${time}</Time>${meters ? `<DistanceMeters>${distance}</DistanceMeters>` : ''}</Trackpoint>`;
  return ['<?xml version="1.0" encoding="UTF-8"?>',
    '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">',
    '<Activities>',
    `<Activity Sport="${tcxSport(workout)}">`,
    `<Id>${start}</Id>`,
    `<Lap StartTime="${start}">`,
    `<TotalTimeSeconds>${seconds}</TotalTimeSeconds>`,
    `<DistanceMeters>${meters}</DistanceMeters>`,
    `<Calories>${calories}</Calories>`,
    ...heartRate ? [`<AverageHeartRateBpm><Value>${heartRate}</Value></AverageHeartRateBpm>`] : [],
    '<Intensity>Active</Intensity>',
    '<TriggerMethod>Manual</TriggerMethod>',
    `<Track>${point(start, 0)}${point(end, meters)}</Track>`,
    '</Lap>',
    `<Notes>${tcxText(tcxNotes(workout))}</Notes>`,
    '</Activity>',
    '</Activities>',
    '</TrainingCenterDatabase>',
    ''].join('\n');
}

// "run-2026-10-12.tcx": the name and the day it was done.
function tcxFileName(workout) {
  const name = String(workout.name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'workout';
  return `${name}-${calendarDayKey(new Date(workout.createdAt))}.tcx`;
}

// Hands the file to the browser to save, and says what it was called.
function saveActivityFile(workout) {
  const file = tcxFileName(workout);
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([tcxFile(workout)], { type:'application/vnd.garmin.tcx+xml' }));
  link.download = file;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 60000);
  return file;
}

function activitySavedMessage(file) {
  return `Downloaded ${file}. Upload it to Strava on its website, or open it in an app that adds workouts to Apple Health.`;
}

// Makes a summary's button download this workout, or hides it when the workout has no time to export. The workout is held
// by the button, so it is the one just finished whether or not it has reached the server.
function offerActivityExport(button, workout) {
  button.hidden = !canExportActivity(workout);
  button.onclick = () => showFeedback(activitySavedMessage(saveActivityFile(workout)), 'success');
}
