const form = document.getElementById('authForm');
const feedback = document.getElementById('authFeedback');
const notice = document.getElementById('authNotice');
const submit = document.getElementById('authSubmit');
const loginTab = document.getElementById('loginTab');
const registerTab = document.getElementById('registerTab');
const emailInput = document.getElementById('email');
const loginInput = document.getElementById('username');
const passwordInput = document.getElementById('password');
const forgotButton = document.getElementById('forgotButton');
const forgotForm = document.getElementById('forgotForm');
const resetForm = document.getElementById('resetForm');
const resetEmailInput = document.getElementById('resetEmail');
// 'login', 'register', 'forgot' (asking for a code) or 'reset' (entering it).
let mode = 'login';
let resetAvailable = false;
let resetEmail = '';

// Only same-site paths are followed, so a crafted ?next= link cannot send someone to another site after signing in.
function nextDestination() {
  const next = new URLSearchParams(location.search).get('next');
  return next && next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\') ? next : '/';
}

// The app keys what it keeps on this device by account and, until the server answers, assumes the last account seen.
// Recording who just signed in means the first page load already uses this account's copy, not the previous one's.
function rememberAccount(user) {
  try { localStorage.setItem('workout-tracker-last-user', JSON.stringify(user.id)); }
  catch (error) { /* no storage: the app identifies the account from the server instead */ }
}

function showError(message) {
  notice.hidden = true;
  feedback.textContent = message;
  feedback.hidden = false;
}

function showNotice(message) {
  feedback.hidden = true;
  notice.textContent = message;
  notice.hidden = false;
}

function setMode(nextMode) {
  mode = nextMode;
  const signingIn = mode === 'login';
  const registering = mode === 'register';
  document.getElementById('authTabs').hidden = !signingIn && !registering;
  form.hidden = !signingIn && !registering;
  forgotForm.hidden = mode !== 'forgot';
  resetForm.hidden = mode !== 'reset';
  loginTab.classList.toggle('active', signingIn);
  registerTab.classList.toggle('active', registering);
  // Signing in takes an email or a username in the one field; only a new account asks for the email on its own.
  // Disabled as well as hidden, or its being empty and required would stop the form from submitting.
  document.getElementById('emailLabel').hidden = emailInput.hidden = emailInput.disabled = !registering;
  document.getElementById('usernameLabel').textContent = registering ? 'Username' : 'Email or username';
  passwordInput.autocomplete = registering ? 'new-password' : 'current-password';
  submit.textContent = registering ? 'Create account' : 'Sign in';
  forgotButton.hidden = !signingIn || !resetAvailable;
  feedback.hidden = notice.hidden = true;
}

async function post(path, body) {
  const response = await fetch(path, { method:'POST', headers:{ 'Content-Type':'application/json', 'Accept':'application/json' }, body:JSON.stringify(body) });
  const responseText = await response.text();
  let result;
  try { result = JSON.parse(responseText); }
  catch (parseError) { throw new Error(`The server returned an unexpected response (${response.status}). Check that the self-hosted server is running the current version.`); }
  if (!response.ok) throw new Error(result.error || 'Something went wrong. Try again.');
  return result;
}

// Runs one request for a button. A task that returns true is leaving the page, so its button stays disabled.
async function submitWith(button, task) {
  feedback.hidden = notice.hidden = true;
  button.disabled = true;
  try {
    if (await task()) return;
  } catch (error) {
    showError(error.message);
  }
  button.disabled = false;
}

function signedIn(result) {
  if (result.user) rememberAccount(result.user);
  window.location.href = nextDestination();
  return true;
}

// A server with registration turned off only offers signing in, and one with no mail server cannot send reset codes.
fetch('/api/auth/me').then(response => response.json()).then(info => {
  resetAvailable = info.passwordReset === true;
  forgotButton.hidden = mode !== 'login' || !resetAvailable;
  if (info.registrationOpen !== false) return;
  registerTab.hidden = true;
  if (mode === 'register') setMode('login');
}).catch(() => {});

loginTab.onclick = () => setMode('login');
registerTab.onclick = () => setMode('register');
document.querySelectorAll('[data-back]').forEach(button => { button.onclick = () => setMode('login'); });

form.onsubmit = event => {
  event.preventDefault();
  const body = mode === 'register'
    ? { email:emailInput.value, username:loginInput.value, password:passwordInput.value }
    : { login:loginInput.value, password:passwordInput.value };
  submitWith(submit, async () => signedIn(await post(`/api/auth/${mode}`, body)));
};

forgotButton.onclick = () => {
  const typed = loginInput.value.trim();
  resetEmailInput.value = typed.includes('@') ? typed : '';
  setMode('forgot');
  resetEmailInput.focus();
};

forgotForm.onsubmit = event => {
  event.preventDefault();
  submitWith(document.getElementById('sendCodeButton'), async () => {
    await post('/api/auth/forgot-password', { email:resetEmailInput.value });
    resetEmail = resetEmailInput.value.trim();
    // The server answers the same whether or not the address has an account, so this cannot say which.
    document.getElementById('resetIntro').textContent = `If ${resetEmail} belongs to an account, a code is on its way to it. It works for 15 minutes. Check your spam folder if it does not arrive.`;
    document.getElementById('resetCode').value = '';
    setMode('reset');
    document.getElementById('resetCode').focus();
  });
};

document.getElementById('resendCode').onclick = event => {
  submitWith(event.currentTarget, async () => {
    await post('/api/auth/forgot-password', { email:resetEmail });
    showNotice('A new code is on its way. Only the newest code works.');
  });
};

resetForm.onsubmit = event => {
  event.preventDefault();
  submitWith(document.getElementById('resetSubmit'), async () => signedIn(await post('/api/auth/reset-password', {
    email:resetEmail,
    code:document.getElementById('resetCode').value.replace(/\s/g, ''),
    password:document.getElementById('newPassword').value
  })));
};
