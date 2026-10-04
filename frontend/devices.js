// Settings, Account, "Signed-in devices": the browsers and phones signed in to this account, each with when it was last used, and a
// button to sign it out, or every one but this. Loaded after settings.js, whose account panels it joins (accountPanels): opening
// it closes the others, and it closes with them. Signing a device out deletes nothing on it: whatever it had not uploaded stays
// there until it is signed in again.

// "just now", "12 minutes ago", "3 hours ago", "yesterday", "5 days ago", or the date beyond that. Nothing, for a session from
// before the server kept times.
function devicesAgo(when, now = Date.now()) {
  if (!when) return '';
  const minutes = Math.max(0, Math.floor((now - when) / 60000));
  if (minutes < 2) return 'just now';
  if (minutes < 60) return `${minutes} minutes ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? 'an hour ago' : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'yesterday';
  return days < 14 ? `${days} days ago` : new Date(when).toLocaleDateString(undefined, { month:'short', day:'numeric', year:'numeric' });
}

// What a device's row says besides its name: "Last used 12 minutes ago · signed in Oct 1 · 203.0.113.5".
function devicesDetails(device, now = Date.now()) {
  const used = devicesAgo(device.lastUsed, now);
  const parts = [used ? `Last used ${used}` : 'Signed in earlier'];
  if (device.createdAt) parts.push(`signed in ${new Date(device.createdAt).toLocaleDateString(undefined, { month:'short', day:'numeric' })}`);
  if (device.address) parts.push(device.address);
  return parts.join(' · ');
}

function showDevicesFeedback(message) {
  const feedback = getSettingElement('devicesFeedback');
  feedback.textContent = message;
  feedback.hidden = !message;
}

// One row per device, built with text nodes: what the server says of a device is never read as markup.
function renderDevices(devices) {
  const list = getSettingElement('deviceList');
  list.replaceChildren(...devices.map(device => {
    const row = document.createElement('li');
    row.className = 'device';
    const about = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = device.label || 'Browser';
    about.append(name);
    if (device.current) {
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = 'This device';
      about.append(' ', badge);
    }
    const details = document.createElement('span');
    details.className = 'subtitle';
    details.textContent = devicesDetails(device);
    about.append(details);
    row.append(about);
    if (!device.current) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary';
      button.textContent = 'Sign out';
      button.setAttribute('aria-label', `Sign out ${device.label || 'Browser'}, ${devicesDetails(device)}`);
      button.dataset.deviceId = device.id;
      row.append(button);
    }
    return row;
  }));
  getSettingElement('signOutOthers').hidden = devices.filter(device => !device.current).length === 0;
}

async function devicesRequest(path, body) {
  let response;
  try {
    response = await fetch(path, body === undefined ? {} : { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(body) });
  } catch (error) {
    showDevicesFeedback('Could not reach the server. Try again when you are back online.');
    return null;
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    showDevicesFeedback(result.error || 'Something went wrong. Try again.');
    return null;
  }
  return result;
}

async function loadDevices() {
  showDevicesFeedback('');
  getSettingElement('deviceList').replaceChildren();
  getSettingElement('signOutOthers').hidden = true;
  const result = await devicesRequest('/api/account/sessions');
  if (result) renderDevices(result.sessions);
}

async function signOutDevices(path, body, done) {
  const buttons = getSettingElement('devicesEditor').querySelectorAll('button');
  buttons.forEach(button => { button.disabled = true; });
  try {
    const result = await devicesRequest(path, body);
    if (!result) return;
    await loadDevices();
    getSettingElement('accountNotice').textContent = done(result);
    getSettingElement('accountNotice').hidden = false;
  } finally {
    buttons.forEach(button => { button.disabled = false; });
  }
}

accountPanels.devices = { editor:'devicesEditor', open:'devicesButton', cancel:'closeDevices', feedback:'devicesFeedback', focus:'closeDevices', start:loadDevices };
getSettingElement('devicesButton').onclick = () => showAccountPanel('devices');
getSettingElement('closeDevices').onclick = () => { getSettingElement('devicesEditor').hidden = true; };
getSettingElement('deviceList').onclick = event => {
  const button = event.target.closest('button[data-device-id]');
  if (button) signOutDevices('/api/account/sessions/revoke', { id:Number(button.dataset.deviceId) }, () => 'Signed out of that device.');
};
getSettingElement('signOutOthers').onclick = () => signOutDevices('/api/account/sessions/sign-out-others', {}, result =>
  result.signedOut ? `Signed out of ${plural(result.signedOut, 'other device')}.` : 'There was no other device signed in.');
// Like the rest of the account, only when the server has said who is signed in (not while offline).
window.addEventListener('settingsopen', () => { getSettingElement('devicesButton').hidden = !window.localUsername; });
