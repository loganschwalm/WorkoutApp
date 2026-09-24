function exerciseDetails(exercise) {
  if (exercise.sets && !exercise.sets.length) return 'Skipped';
  if (!exercise.sets || !exercise.sets.length) return `${escapeHTML(exercise.weight || 0)} lbs &middot; ${escapeHTML(exercise.reps)} reps`;
  return exercise.sets.map(set => `${escapeHTML(set.weight || 0)} lbs x ${escapeHTML(set.reps)}`).join(' &middot; ');
}

function renderHistory(workouts) {
  $('historySummary').textContent = `${workouts.length} saved workout${workouts.length === 1 ? '' : 's'}`;
  $('historyList').innerHTML = workouts.length ? workouts.map(workout => `<li class="saved-workout history-workout"><div class="saved-workout-summary"><div><strong>${escapeHTML(workout.name)}</strong><span>${new Date(workout.createdAt).toLocaleDateString(undefined, { year:'numeric', month:'short', day:'numeric' })}${workoutProgramLabel(workout) ? ` &middot; ${escapeHTML(workoutProgramLabel(workout))}` : ''}</span></div><a class="button-link primary" href="index.html?start=${encodeURIComponent(workout.id)}">Start workout</a></div><div class="workout-details">${workout.notes ? `<p class="workout-note">${escapeHTML(workout.notes)}</p>` : ''}<ul>${workout.exercises.map(item => `<li><strong>${escapeHTML(item.name)}</strong><span>${exerciseDetails(item)}</span></li>`).join('')}</ul></div></li>`).join('') : '<li class="empty">No saved workouts yet.</li>';
}

window.localReady.then(flushPendingWorkouts).then(getSavedWorkouts).then(renderHistory).catch(error => {
  $('historySummary').textContent = 'Unable to load workouts.';
  console.error('Unable to load workout history.', error);
});