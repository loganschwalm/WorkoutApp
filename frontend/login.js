const form = document.getElementById('authForm');
const feedback = document.getElementById('authFeedback');
const submit = document.getElementById('authSubmit');
const loginTab = document.getElementById('loginTab');
const registerTab = document.getElementById('registerTab');
let mode = 'login';

// Only same-site paths are followed, so a crafted ?next= link cannot send someone to another site after signing in.
function nextDestination() {
  const next = new URLSearchParams(location.search).get('next');
  return next && next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\') ? next : '/frontend/index.html';
}

function showError(message) {
  feedback.textContent = message;
  feedback.hidden = false;
}

function setMode(nextMode) {
  mode = nextMode;
  loginTab.classList.toggle('active', mode === 'login');
  registerTab.classList.toggle('active', mode === 'register');
  submit.textContent = mode === 'login' ? 'Sign in' : 'Create account';
  feedback.hidden = true;
}

loginTab.onclick = () => setMode('login');
registerTab.onclick = () => setMode('register');
form.onsubmit = async event => {
  event.preventDefault();
  feedback.hidden = true;
  submit.disabled = true;
  try {
    const response = await fetch(`/api/auth/${mode}`, { method:'POST', headers:{ 'Content-Type':'application/json', 'Accept':'application/json' }, body:JSON.stringify({ username:document.getElementById('username').value, password:document.getElementById('password').value }) });
    const responseText = await response.text();
    let result;
    try { result = JSON.parse(responseText); }
    catch (parseError) { throw new Error(`The server returned an unexpected response (${response.status}). Check that the self-hosted server is running the current version.`); }
    if (!response.ok) throw new Error(result.error || 'Unable to authenticate.');
    window.location.href = nextDestination();
  } catch (error) {
    showError(error.message);
    submit.disabled = false;
  }
};
