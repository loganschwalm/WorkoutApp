// The exercise library: the muscle each exercise mostly works and what it is done with, for the Tracker (whose plates and
// warm-ups are for barbell lifts) and Progress (whose sets per muscle count by muscle). An exercise nobody has said
// anything about is guessed from its name; the account's own choices, and exercises of its own, are kept with the
// account by exerciseKey ({ 'landmine press': { name:'Landmine Press', muscle:'shoulders', equipment:'other' } }), on the
// device first and uploaded by offline.js, as notes and goals are. A muscle or equipment left empty is still guessed, so
// a better guess reaches it.

const muscleGroups = [['chest', 'Chest'], ['back', 'Back'], ['shoulders', 'Shoulders'], ['biceps', 'Biceps'], ['triceps', 'Triceps'],
  ['forearms', 'Forearms'], ['quads', 'Quads'], ['hamstrings', 'Hamstrings'], ['glutes', 'Glutes'], ['calves', 'Calves'], ['core', 'Core'], ['other', 'Other']];
const equipmentKinds = [['barbell', 'Barbell'], ['dumbbell', 'Dumbbell'], ['machine', 'Machine'], ['cable', 'Cable'], ['bodyweight', 'Bodyweight'],
  ['kettlebell', 'Kettlebell'], ['band', 'Band'], ['other', 'Other']];

function muscleLabel(muscle) {
  return (muscleGroups.find(([value]) => value === muscle) || [])[1] || '';
}

function equipmentLabel(equipment) {
  return (equipmentKinds.find(([value]) => value === equipment) || [])[1] || '';
}

// A name matches when it has any of these as a whole word (or words), in any case. Not training-tools.js's anyOfWords:
// a top-level const of the same name in two scripts on one page would stop the second (see the note on $ in common.js).
const wordsIn = words => new RegExp(`\\b(${words.join('|')})\\b`, 'i');

// The first group whose words the name has. The order settles names with words of two: a Leg Curl before curls, a
// Romanian Deadlift before deadlifts, an Upright Row before rows, a Chest-Supported Row before the chest, and an Incline
// Curl before the incline bench.
const muscleWords = [
  ['core', wordsIn(['planks?', 'crunch(es)?', 'sit[- ]?ups?', '(leg|knee) raises?', 'ab wheel', 'abs?', 'core', 'rollouts?', 'russian twists?', 'dead ?bugs?',
    'hollow', 'v[- ]?ups?', 'mountain climbers?', 'pallof', 'woodchops?', 'l[- ]sits?', 'side bends?'])],
  ['calves', wordsIn(['calf', 'calves'])],
  ['forearms', wordsIn(['wrist', 'forearms?', "farmer'?s", 'dead hangs?'])],
  ['triceps', wordsIn(['triceps?', 'pushdowns?', 'skull ?crushers?', 'close[- ]grip bench', 'jm press', 'french press'])],
  ['shoulders', wordsIn(['shoulders?', 'delts?', 'deltoids?', 'overhead press', 'ohp', 'military press', 'push press', 'arnold', '(lateral|side|front) raises?',
    'face ?pulls?', 'upright rows?', 'reverse fl(y|ies|yes)'])],
  ['hamstrings', wordsIn(['hamstrings?', '(leg|hamstring|lying|seated|nordic) curls?', 'romanian', 'rdls?', 'stiff[- ]leg(ged)?', 'good ?mornings?', 'glute[- ]ham'])],
  ['glutes', wordsIn(['glutes?', 'hip thrusts?', 'bridges?','abduct(ion|ions|or|ors)'])],
  ['quads', wordsIn(['quads?', 'squats?', 'leg press', 'leg extensions?', 'lunges?', 'step[- ]?ups?', 'hack', 'sissy', 'pistols?', 'wall sits?'])],
  ['back', wordsIn(['back', 'lats?', 'rows?', 'rowing', 'pull[- ]?downs?', 'pull[- ]?ups?', 'chin[- ]?ups?', 'pullovers?', 'shrugs?', 'deadlifts?', 'rack pulls?',
    'hyperextensions?', 'traps?'])],
  ['biceps', wordsIn(['biceps?', 'curls?'])],
  ['chest', wordsIn(['chest', 'pecs?', 'pec deck', 'bench', 'incline', 'decline', 'fl(y|ies|yes)', 'crossovers?', 'push[- ]?ups?', 'dips?'])]
];

// A barbell lift, as the plates and warm-ups have always told one: Bench Press yes, Dumbbell Bench Press or Leg Press no.
const barbellWords = wordsIn(['barbell', 'bench', 'squat', 'deadlift', 'rdl', 'overhead press', 'military press', 'push press', 'ohp', 'pendlay',
  'bent[- ]over row', 'power clean', 'hang clean', 'good morning', 'hip thrust']);
const notBarbellWords = wordsIn(['dumbbells?', 'db', 'kettlebells?', 'machine', 'cable', 'smith', 'leg press', 'hack', 'goblet', 'split', 'bulgarian',
  'trap bar', 'hex bar', 'landmine', 'band', 'dips?', 'pistol']);
// The others, checked first, in this order.
const equipmentWords = [
  ['dumbbell', wordsIn(['dumbbells?', 'db', 'goblet'])],
  ['kettlebell', wordsIn(['kettlebells?', 'kb'])],
  ['band', wordsIn(['bands?'])],
  ['cable', wordsIn(['cables?', 'pushdowns?', 'face ?pulls?', 'crossovers?', 'pallof', 'woodchops?'])],
  ['machine', wordsIn(['machine', 'smith', 'leg press', 'leg extensions?', '(leg|lying|seated) curls?', 'pec deck', 'hack', 'lat pull[- ]?downs?'])]
];
const bodyweightWords = wordsIn(['bodyweight', 'push[- ]?ups?', 'pull[- ]?ups?', 'chin[- ]?ups?', 'dips?', 'planks?', 'crunch(es)?', 'sit[- ]?ups?',
  '(leg|knee) raises?', 'pistols?', 'burpees?', 'dead hangs?', 'hangs?', 'l[- ]sits?']);

// '' when the name gives nothing away.
function guessMuscle(name) {
  return (muscleWords.find(([, words]) => words.test(name)) || [''])[0];
}

function guessEquipment(name) {
  const kind = equipmentWords.find(([, words]) => words.test(name));
  if (kind) return kind[0];
  if (barbellWords.test(name) && !notBarbellWords.test(name)) return 'barbell';
  return bodyweightWords.test(name) ? 'bodyweight' : '';
}

let exerciseLibrary = loadExerciseLibrary();

function loadExerciseLibrary() {
  const stored = readLocalState('exerciseLibrary');
  return stored && stored.value && typeof stored.value === 'object' && !Array.isArray(stored.value) ? stored.value : {};
}

// What an exercise works and is done with: the account's choice, else the guess (either may be ''), and which were guessed.
function exerciseDetails(name) {
  const entry = exerciseLibrary[exerciseKey(name)] || {};
  const muscle = entry.muscle || guessMuscle(String(name)), equipment = entry.equipment || guessEquipment(String(name));
  return { muscle, equipment, muscleGuessed:!entry.muscle && Boolean(muscle), equipmentGuessed:!entry.equipment && Boolean(equipment) };
}

// Changes an exercise's muscle or equipment (or both), adding it to the library if it is not there; '' goes back to the guess.
function setExerciseDetails(name, changes) {
  const key = exerciseKey(name);
  const kept = exerciseLibrary[key] || {};
  exerciseLibrary = { ...exerciseLibrary, [key]:{ muscle:'', equipment:'', ...kept, name:kept.name || String(name).trim(), ...changes } };
  saveLocalState('exerciseLibrary', exerciseLibrary);
}

function removeFromLibrary(name) {
  exerciseLibrary = { ...exerciseLibrary };
  delete exerciseLibrary[exerciseKey(name)];
  saveLocalState('exerciseLibrary', exerciseLibrary);
}
