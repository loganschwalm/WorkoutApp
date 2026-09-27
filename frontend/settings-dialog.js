// The Settings dialog, one copy for every page that has the gear button. Loaded just before settings.js, which gives it
// its behaviour, so the dialog is on the page before anything looks for it. Whitespace between these tags only ever
// falls between items of a grid or flex box, or between a select's options, where the browser ignores it.

// The account panels (email, password, deleting the account) sit inside the settings form but submit their own forms,
// named by form="…" on their fields and buttons, since forms cannot nest.
function accountEditor(id, fields, actions, lead = '') {
  return `<div class="account-editor" id="${id}" hidden>${lead}${fields}<div class="account-editor-actions">${actions}</div></div>`;
}

const weeklyGoals = [1, 2, 3, 4, 5, 6, 7].map(goal => `<option value="${goal}">${goal} workout${goal === 1 ? '' : 's'} a week</option>`).join('');

document.body.insertAdjacentHTML('beforeend', `
<div class="modal-backdrop" id="settingsModal" hidden>
  <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
    <div class="settings-heading">
      <h2 id="settingsTitle">Settings</h2>
      <button class="modal-close" id="closeSettings" type="button" aria-label="Close settings">&times;</button>
    </div>
    <form id="settingsForm">
      <h3 class="settings-section">General</h3>
      <label for="themeSetting">Appearance</label>
      <select id="themeSetting">
        <option value="system">Match system</option><option value="light">Light mode</option><option value="dark">Dark mode</option>
      </select>
      <label for="unitSetting">Weight unit</label>
      <select id="unitSetting"><option value="lbs">Pounds (lbs)</option><option value="kg">Kilograms (kg)</option></select>
      <label for="weeklyGoalSetting">Weekly goal</label>
      <select id="weeklyGoalSetting">${weeklyGoals}</select>
      <h3 class="settings-section">During a workout</h3>
      <label class="setting-check"><input id="confirmEndSetting" type="checkbox" /> Confirm before ending an active workout</label>
      <label class="setting-check"><input id="effortSetting" type="checkbox" /> Ask how many reps each set had left (effort)</label>
      <label class="setting-check"><input id="warmupSetting" type="checkbox" /> Suggest warm-up sets for barbell lifts</label>
      <h3 class="settings-section">Rest timer</h3>
      <label for="restDurationSetting">Default rest duration (seconds)</label>
      <input id="restDurationSetting" type="number" inputmode="numeric" min="15" max="600" step="15" />
      <label class="setting-check"><input id="autoRestSetting" type="checkbox" /> Start the rest timer automatically after each set</label>
      <label class="setting-check"><input id="soundEnabledSetting" type="checkbox" /> Play a sound when rest ends</label>
      <label for="alertSoundSetting">Alert sound</label>
      <select id="alertSoundSetting">
        <option value="beep">Double beep</option><option value="chime">Chime</option><option value="long">Long tone</option>
      </select>
      <label for="soundVolumeSetting">Volume</label>
      <input id="soundVolumeSetting" type="range" min="0" max="100" step="5" />
      <label class="setting-check" id="vibrateSettingRow"><input id="vibrateSetting" type="checkbox" /> Vibrate when rest ends</label>
      <label class="setting-check" id="silentSettingRow"><input id="silentSetting" type="checkbox" /> Play the alert when the ringer is silent, at your media volume (pauses your music while it plays)</label>
      <button class="secondary test-alert" id="testAlertButton" type="button">Test alert</button>
      <h3 class="settings-section">Your data</h3>
      <div class="data-section">
        <div class="account-details">
          <span class="subtitle">Save every workout to a file, with your templates, program and settings, or bring in one saved from any Workout Tracker.</span>
        </div>
        <div class="data-actions">
          <button class="secondary" id="exportButton" type="button">Export</button>
          <button class="secondary" id="exportCsvButton" type="button">Export sets as CSV</button>
          <button class="secondary" id="importButton" type="button">Import</button>
        </div>
        <input id="importFile" type="file" accept=".json,application/json" hidden />
        <p class="subtitle data-status" id="dataStatus" role="status" hidden></p>
      </div>
      <h3 class="settings-section">Account</h3>
      <div class="account-row">
        <div class="account-details">
          <span class="subtitle" id="accountName"></span>
          <span class="subtitle" id="accountEmail"></span>
          <span class="subtitle" id="accountNotice" role="status" hidden></span>
          <button class="link-button" id="changeEmailButton" type="button">Change email</button>
          <button class="link-button" id="changePasswordButton" type="button">Change password</button>
          <button class="link-button danger-link" id="deleteAccountButton" type="button">Delete account</button>
        </div>
        <button class="secondary" id="signOutButton" type="button">Sign out</button>
      </div>
      ${accountEditor('emailEditor',
        '<label for="emailSetting">Email</label><input id="emailSetting" type="email" form="emailForm" autocomplete="email" maxlength="254" required />'
        + '<label for="emailPassword">Current password</label><input id="emailPassword" type="password" form="emailForm" autocomplete="current-password" required />'
        + '<p class="auth-feedback" id="emailFeedback" role="alert" hidden></p>',
        '<button class="secondary" id="cancelEmail" type="button">Cancel</button><button class="primary" id="saveEmail" type="submit" form="emailForm">Save email</button>')}
      ${accountEditor('passwordEditor',
        '<label for="currentPassword">Current password</label>'
        + '<input id="currentPassword" type="password" form="passwordForm" autocomplete="current-password" required />'
        + '<label for="newPassword">New password</label>'
        + '<input id="newPassword" type="password" form="passwordForm" autocomplete="new-password" minlength="8" required />'
        + '<p class="auth-feedback" id="passwordFeedback" role="alert" hidden></p>',
        '<button class="secondary" id="cancelPassword" type="button">Cancel</button>'
        + '<button class="primary" id="savePassword" type="submit" form="passwordForm">Save password</button>')}
      ${accountEditor('deleteEditor',
        '<label for="deletePassword">Current password</label>'
        + '<input id="deletePassword" type="password" form="deleteForm" autocomplete="current-password" required />'
        + '<p class="auth-feedback" id="deleteFeedback" role="alert" hidden></p>',
        '<button class="secondary" id="cancelDelete" type="button">Cancel</button>'
        + '<button class="danger" id="confirmDelete" type="submit" form="deleteForm">Delete account</button>',
        '<p class="subtitle delete-warning">This deletes your account from this server for good: every workout, template and setting in it, and your '
        + 'training program. Export first to keep a copy.</p>')}
      <div class="settings-actions">
        <p class="subtitle settings-saved" id="settingsSaved" role="status">Changes are saved as you make them.</p>
        <button class="primary" id="doneSettings" type="submit">Done</button>
      </div>
    </form>
    <form id="emailForm" hidden></form>
    <form id="passwordForm" hidden></form>
    <form id="deleteForm" hidden></form>
  </section>
</div>`);
