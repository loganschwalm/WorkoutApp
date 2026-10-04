// What the settings are: one entry for each setting, or for each group that is one thing to the person (the bar and plates), under
// the section of the dialog it is in, in the order the dialog shows them. An entry says everything about its setting:
//
//   defaults  the setting's value until one is chosen, {key: value} (a group has several keys; none, for one that follows another)
//   html()    the markup of its controls, which settings-dialog.js puts in the Settings dialog
//   show(s)   puts the settings s into the controls (applySettings, in settings.js, asks each entry)
//   read(c)   what the controls say, as {key: value} (readSettingsForm asks each); c is the settings kept now, for what a
//             control cannot say (a field left empty keeps its setting)
//
// defaultSettings, the dialog, applySettings and readSettingsForm are all made from the sections below, so a new setting is
// one entry here (and whatever uses it), not an edit in each. A setting that is one control is made by checkSetting,
// choiceSetting or rangeSetting; the rest have an entry of their own. Loaded before settings-dialog.js and settings.js.

const getSettingElement = id => document.getElementById(id);
const canVibrate = typeof navigator.vibrate === 'function';
// Safari (iOS 16.4 and later) lets a page choose how the phone treats its sound; see playRestAlert.
const canPlayThroughSilent = 'audioSession' in navigator;

// ---- Settings that are one control ------------------------------------------------

// A tick box. On unless it was turned off; row, if there is one, is the id of its label, which is hidden when available()
// says the browser cannot do what it is for.
function checkSetting(key, id, label, { row, available } = {}) {
  return {
    defaults:{ [key]:true },
    html:() => `<label class="setting-check"${row ? ` id="${row}"` : ''}><input id="${id}" type="checkbox" /> ${label}</label>`,
    show(settings) {
      getSettingElement(id).checked = settings[key] !== false;
      if (row && available) getSettingElement(row).hidden = !available();
    },
    read:() => ({ [key]:getSettingElement(id).checked })
  };
}

// A choice from a list of [value, text]. `normalize` turns whatever is kept, or typed, into one of the values, so a setting
// that is no longer one (from an older version, or a hand-edited import) shows as the default.
function choiceSetting(key, id, label, options, normalize, defaultValue) {
  return {
    defaults:{ [key]:defaultValue },
    html:() => `<label for="${id}">${label}</label><select id="${id}">${options.map(([value, text]) => `<option value="${value}">${text}</option>`).join('')}</select>`,
    show:settings => { getSettingElement(id).value = String(normalize(settings[key])); },
    read:() => ({ [key]:normalize(getSettingElement(id).value) })
  };
}

// A number in a field, kept from `least` to `most`; one that is empty, or not a number, is `blank`. `input` is the field's attributes.
function rangeSetting(key, id, label, input, { least, most, blank, defaultValue }) {
  return {
    defaults:{ [key]:defaultValue },
    html:() => `<label for="${id}">${label}</label><input id="${id}" ${input} />`,
    show:settings => { getSettingElement(id).value = settings[key]; },
    read:() => ({ [key]:Math.min(most, Math.max(least, Number(getSettingElement(id).value) || blank)) })
  };
}

// ---- Appearance ------------------------------------------------------------------------

let legacyTheme = null;
try { legacyTheme = localStorage.getItem('workout-tracker-theme'); } catch (error) { /* no storage: follow the device */ }
// Appearance: 'system' follows the device's light or dark mode; 'light' and 'dark' fix it.
// Match system, or one of the themes theme.js knows. A page without theme.js (an old one, from the cache) has light and dark.
const themeChoices = ['system', ...Object.keys(window.colorThemes || { light:'light', dark:'dark' })];

// Match system, then the light themes, then the dark ones (theme.js says which is which). Each preview is drawn in its theme's
// colours; Match system shows Light and Dark side by side.
const themeNames = { system:'Match system', light:'Light', sunrise:'Sunrise', meadow:'Meadow', blossom:'Blossom',
  dark:'Dark', crimson:'Crimson', emerald:'Emerald', ocean:'Ocean', gold:'Gold', violet:'Violet' };
const themeSwatches = Object.keys(themeNames).map(id => {
  const previews = (id === 'system' ? ['light', 'dark'] : [id]).map(palette => `<span data-palette="${palette}"></span>`).join('');
  return `<label class="theme-swatch"><input type="radio" name="theme" value="${id}" /><span class="theme-preview" aria-hidden="true">${previews}</span><span class="theme-name">${themeNames[id]}</span></label>`;
}).join('');

const themeSetting = {
  defaults:{ theme:themeChoices.includes(legacyTheme) ? legacyTheme : 'system' },
  html:() => `<fieldset class="theme-picker" id="themeSetting"><legend>Appearance</legend>${themeSwatches}</fieldset>`,
  show(settings) {
    // theme.js, in <head>, applies it and follows the device. A page from before theme.js existed (served from the
    // cache for one load after an update) lacks it, and just gets light or dark.
    if (window.setColorTheme) window.setColorTheme(settings.theme);
    else document.documentElement.dataset.theme = settings.theme === 'dark' ? 'dark' : 'light';
    const theme = themeChoices.includes(settings.theme) ? settings.theme : 'system';
    getSettingElement('themeSetting').querySelectorAll('input[name=theme]').forEach(input => { input.checked = input.value === theme; });
  },
  read:() => ({ theme:getSettingElement('themeSetting').querySelector('input[name=theme]:checked')?.value || 'system' })
};

// ---- Units and the weekly goal ---------------------------------------------------------

// Miles or kilometres, for cardio: the one chosen in Settings, or until one is, the one that goes with the weight unit.
function distanceUnitOf(settings = getWorkoutSettings()) {
  if (settings.distanceUnit === 'mi' || settings.distanceUnit === 'km') return settings.distanceUnit;
  return settings.unit === 'kg' ? 'km' : 'mi';
}

// The distance unit is only kept once it has been chosen (settings.js marks it so); until then it follows the weight unit.
const distanceSetting = {
  defaults:{},
  html:() => '<label for="distanceUnitSetting">Distance unit, for cardio</label>'
    + '<select id="distanceUnitSetting"><option value="mi">Miles (mi)</option><option value="km">Kilometres (km)</option></select>',
  show(settings) {
    getSettingElement('distanceUnitSetting').value = distanceUnitOf(settings);
    getSettingElement('distanceUnitSetting').dataset.chosen = String(settings.distanceUnit === 'mi' || settings.distanceUnit === 'km');
  },
  read() {
    const distance = getSettingElement('distanceUnitSetting');
    return distance.dataset.chosen === 'true' ? { distanceUnit:distance.value === 'km' ? 'km' : 'mi' } : {};
  }
};

// Workouts a week the training calendar on the History page counts a week as done at: a whole number from 1 to 7.
function weeklyGoalFrom(value) {
  const goal = Math.round(Number(value));
  return goal >= 1 && goal <= 7 ? goal : defaultSettings.weeklyGoal;
}

// ---- The training schedule ---------------------------------------------------------------

// Training days, Monday first as the calendar has them, by the number the browser gives each (Sunday is 0).
const trainingDayChoices = [[1, 'Mon', 'Monday'], [2, 'Tue', 'Tuesday'], [3, 'Wed', 'Wednesday'], [4, 'Thu', 'Thursday'], [5, 'Fri', 'Friday'], [6, 'Sat', 'Saturday'], [0, 'Sun', 'Sunday']]
  .map(([value, short, name]) => `<label class="weekday"><input type="checkbox" value="${value}" aria-label="${name}" /><span aria-hidden="true">${short}</span></label>`).join('');

// The days of the week the lifter trains (as the browser numbers them, Sunday 0) and the time of day to remind them, from
// the settings; a setting from before the schedule, or a hand-edited one, is no days and the default time.
const scheduleTimePattern = /^([01]\d|2[0-3]):[0-5]\d$/;

function scheduleFrom(settings = getWorkoutSettings()) {
  const stored = settings.schedule && typeof settings.schedule === 'object' ? settings.schedule : {};
  const days = Array.isArray(stored.days) ? [...new Set(stored.days.filter(day => Number.isInteger(day) && day >= 0 && day <= 6))].sort((a, b) => a - b) : [];
  return { days, time:scheduleTimePattern.test(stored.time) ? stored.time : defaultSettings.schedule.time };
}

// The reminders' own controls (reminders.js) are part of this section: whether they are on belongs to the browser, not the account.
const scheduleSetting = {
  defaults:{ schedule:{ days:[], time:'17:00' } },
  html:() => `<fieldset class="weekday-choices" id="scheduleDays"><legend>Days you train</legend>${trainingDayChoices}</fieldset>
      <span class="subtitle schedule-help">The Tracker says what is planned for today and the next training day, and History marks them on the calendar. A program moves on when you finish a workout, not when a day passes.</span>
      <label for="reminderTimeSetting">Remind me at</label>
      <input id="reminderTimeSetting" type="time" />
      <label class="setting-check"><input id="remindSetting" type="checkbox" /> Remind me on training days, on this device</label>
      <p class="subtitle" id="remindStatus" role="status"></p>
      <button class="secondary test-alert" id="testReminderButton" type="button" hidden>Send a test notification</button>`,
  show(settings) {
    const schedule = scheduleFrom(settings);
    getSettingElement('scheduleDays').querySelectorAll('input').forEach(input => { input.checked = schedule.days.includes(Number(input.value)); });
    getSettingElement('reminderTimeSetting').value = schedule.time;
  },
  // A time cleared or half-typed keeps the one there was.
  read(current) {
    const days = [...getSettingElement('scheduleDays').querySelectorAll('input:checked')].map(input => Number(input.value)).sort((a, b) => a - b);
    const typed = getSettingElement('reminderTimeSetting').value;
    return { schedule:{ days, time:scheduleTimePattern.test(typed) ? typed : scheduleFrom(current).time } };
  }
};

// ---- Bar and plates --------------------------------------------------------------------
// The bar, the plates there are to load on it, and the step the weight buttons and Go heavier go up by. Each unit keeps
// its own, since a gym's pound plates are not its kilogram ones, and switching units never turns one into the other.
// Plates come in quarters of a pound or kilogram at the finest, which the plate calculator (training-tools.js) relies on.
const plateChoices = { lbs:[55, 45, 35, 25, 15, 10, 5, 2.5, 1.25, 0.5], kg:[25, 20, 15, 10, 5, 2.5, 2, 1.25, 1, 0.5] };
const stepChoices = { lbs:[1, 2.5, 5, 10], kg:[0.5, 1, 1.25, 2.5, 5] };
const barLimits = { lbs:[5, 100], kg:[2.5, 50] };
const equipmentKeys = { lbs:{ bar:'barLbs', plates:'platesLbs', step:'stepLbs' }, kg:{ bar:'barKg', plates:'platesKg', step:'stepKg' } };

// The bar, plates (heaviest first) and step for a unit, with anything missing or not one of the choices (a setting from
// an older version, or a hand-edited import) taken from the defaults.
function gymEquipment(settings = getWorkoutSettings(), unit = settings.unit === 'kg' ? 'kg' : 'lbs') {
  const keys = equipmentKeys[unit];
  const bar = Number(settings[keys.bar]);
  const [lightest, heaviest] = barLimits[unit];
  const plates = Array.isArray(settings[keys.plates]) ? plateChoices[unit].filter(plate => settings[keys.plates].includes(plate)) : [];
  const step = Number(settings[keys.step]);
  return {
    unit,
    bar:bar >= lightest && bar <= heaviest ? bar : defaultSettings[keys.bar],
    plates:plates.length ? plates : defaultSettings[keys.plates],
    step:stepChoices[unit].includes(step) ? step : defaultSettings[keys.step]
  };
}

// The fields show one unit's equipment, the unit that was chosen when they were filled: see `read`. A bar outside its limits
// (or a field left empty) keeps the bar there was.
const equipmentSetting = {
  defaults:{ barLbs:45, barKg:20, platesLbs:[45, 35, 25, 10, 5, 2.5, 1.25], platesKg:[25, 20, 15, 10, 5, 2.5, 1.25], stepLbs:5, stepKg:2.5 },
  html:() => `<div class="equipment-fields" id="equipmentFields">
        <span class="subtitle">What your gym has, for the plates to load on a barbell lift, its warm-ups, the weight buttons and Go heavier. Each unit keeps its own.</span>
        <label for="barSetting">Bar weight (<span data-equipment-unit>lbs</span>)</label>
        <input id="barSetting" type="number" inputmode="decimal" step="0.5" />
        <fieldset class="plate-choices"><legend>Plates you have (<span data-equipment-unit>lbs</span>)</legend><div id="plateSetting"></div></fieldset>
        <label for="stepSetting">Weight step</label>
        <select id="stepSetting"></select>
      </div>`,
  show(settings) {
    const unit = settings.unit === 'kg' ? 'kg' : 'lbs';
    const equipment = gymEquipment(settings, unit);
    getSettingElement('equipmentFields').dataset.unit = unit;
    document.querySelectorAll('[data-equipment-unit]').forEach(label => { label.textContent = unit; });
    getSettingElement('barSetting').value = formatWeight(equipment.bar);
    [getSettingElement('barSetting').min, getSettingElement('barSetting').max] = barLimits[unit];
    getSettingElement('plateSetting').innerHTML = plateChoices[unit].map(plate => '<label class="setting-check">'
      + `<input type="checkbox" value="${plate}"${equipment.plates.includes(plate) ? ' checked' : ''} /> ${formatWeight(plate)}</label>`).join('');
    getSettingElement('stepSetting').innerHTML = stepChoices[unit]
      .map(step => `<option value="${step}"${step === equipment.step ? ' selected' : ''}>${formatWeight(step)} ${unit}</option>`).join('');
  },
  // What the fields say, for the unit they show; the other unit's is kept as it is.
  read(current) {
    const unit = getSettingElement('equipmentFields').dataset.unit === 'kg' ? 'kg' : 'lbs';
    const keys = equipmentKeys[unit];
    const had = gymEquipment(current, unit);
    const bar = Number(getSettingElement('barSetting').value);
    const [lightest, heaviest] = barLimits[unit];
    const plates = [...getSettingElement('plateSetting').querySelectorAll('input:checked')].map(input => Number(input.value));
    const other = equipmentKeys[unit === 'kg' ? 'lbs' : 'kg'];
    return {
      [keys.bar]:getSettingElement('barSetting').value !== '' && bar >= lightest && bar <= heaviest ? bar : had.bar,
      [keys.plates]:plates.length ? plates : had.plates,
      [keys.step]:Number(getSettingElement('stepSetting').value) || had.step,
      [other.bar]:current[other.bar], [other.plates]:current[other.plates], [other.step]:current[other.step]
    };
  }
};

// ---- The sections --------------------------------------------------------------------

// The alert sounds and their names. Each needs tones of the same name in alertTones (settings.js), which makes them.
const alertSoundOptions = [['beep', 'Double beep'], ['chime', 'Chime'], ['long', 'Long tone']];

const settingSections = [
  { title:'General', fields:[
    themeSetting,
    choiceSetting('unit', 'unitSetting', 'Weight unit', [['lbs', 'Pounds (lbs)'], ['kg', 'Kilograms (kg)']], value => value === 'kg' ? 'kg' : 'lbs', 'lbs'),
    distanceSetting,
    choiceSetting('weeklyGoal', 'weeklyGoalSetting', 'Weekly goal', [1, 2, 3, 4, 5, 6, 7].map(goal => [goal, `${goal} workout${goal === 1 ? '' : 's'} a week`]), weeklyGoalFrom, 3)
  ] },
  { title:'Training schedule', fields:[scheduleSetting] },
  { title:'During a workout', fields:[
    checkSetting('confirmEnd', 'confirmEndSetting', 'Ask before cancelling a workout with sets logged'),
    checkSetting('trackEffort', 'effortSetting', 'Ask how many reps each set had left (effort)'),
    checkSetting('warmupSets', 'warmupSetting', 'Suggest warm-up sets for barbell lifts'),
    // Only where the browser has no Wake Lock of its own (a plain http:// address): elsewhere the screen stays on anyway.
    checkSetting('keepAwakeVideo', 'keepAwakeSetting', 'Keep the screen on with a silent video, as this browser will not do it itself',
      { row:'keepAwakeSettingRow', available:() => !('wakeLock' in navigator) })
  ] },
  { title:'Bar and plates', fields:[equipmentSetting] },
  { title:'Rest timer', fields:[
    rangeSetting('restDuration', 'restDurationSetting', 'Default rest duration (seconds)', 'type="number" inputmode="numeric" min="15" max="600" step="15"',
      { least:15, most:600, blank:90, defaultValue:90 }),
    checkSetting('autoRest', 'autoRestSetting', 'Start the rest timer automatically after each set'),
    checkSetting('soundEnabled', 'soundEnabledSetting', 'Play a sound when rest ends'),
    choiceSetting('alertSound', 'alertSoundSetting', 'Alert sound', alertSoundOptions, value => alertSoundOptions.some(([name]) => name === value) ? value : 'beep', 'beep'),
    rangeSetting('soundVolume', 'soundVolumeSetting', 'Volume', 'type="range" min="0" max="100" step="5"', { least:0, most:100, blank:0, defaultValue:40 }),
    checkSetting('vibrate', 'vibrateSetting', 'Vibrate when rest ends', { row:'vibrateSettingRow', available:() => canVibrate }),
    // Only Safari on an iPhone or iPad can choose; everywhere else the alert already follows the media volume.
    checkSetting('playThroughSilent', 'silentSetting', 'Play the alert when the ringer is silent, at your media volume (pauses your music while it plays)',
      { row:'silentSettingRow', available:() => canPlayThroughSilent })
  ], after:'<button class="secondary test-alert" id="testAlertButton" type="button">Test alert</button>' }
];

const settingFields = settingSections.flatMap(section => section.fields);

// Settings never chosen are the defaults, on every page; the server is told so (see accountStateFill in offline.js), or
// saving the form, which writes every setting, would look like choosing each default over another device's choice.
const defaultSettings = Object.assign({}, ...settingFields.map(field => field.defaults));
