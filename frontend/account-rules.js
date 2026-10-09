// What a new username, email and password must be, checked in the browser so a mistake shows before anything is sent.
// The same rules as the server's (new_username, email_address and password_problem in server.py), in the same words.
// The server checks again, and it alone keeps the list of common passwords it also refuses. Used by the sign-in page
// (creating an account, resetting a password) and by Settings (changing the email or password).

const USERNAME_MAX = 32;
const PASSWORD_MAX = 128;
const EMAIL_SHAPE = /^([a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*)@((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59}))$/;

// Invisible and control characters: anything Python's isprintable() refuses, which is every space but the plain one, and the
// characters that print as nothing which it lets through (BLANK_CHARACTERS and the variation selectors in accounts.py).
function hasInvisible(value) {
  return /[\p{C}\p{Z}]/u.test(value.replace(/ /g, ''))
    || /[\u034f\u115f\u1160\u17b4\u17b5\u2800\u3164\uffa0\u180b-\u180d\u180f\ufe00-\ufe0f\u{e0100}-\u{e01ef}]/u.test(value);
}

// Each returns what is wrong, or '' when nothing is.
function usernameProblem(value) {
  // Composed first, as the server stores it, so one name typed two ways is one name.
  const username = value.normalize('NFKC').trim();
  const length = [...username].length;
  if (length < 3) return 'Username must be 3+ characters.';
  if (length > USERNAME_MAX) return `Username must be ${USERNAME_MAX} characters or fewer.`;
  if (username.includes('@')) return 'Username cannot contain @. Your email goes in its own field.';
  if (hasInvisible(username)) return 'Username cannot contain invisible or control characters.';
  return '';
}

function emailProblem(value) {
  const email = value.trim().toLowerCase();
  const shape = email.length <= 254 ? EMAIL_SHAPE.exec(email) : null;
  return shape && shape[1].length <= 64 ? '' : 'Enter a valid email address, like name@example.com.';
}

function passwordProblem(password, username = '', email = '') {
  const characters = [...password];
  if (characters.length < 8) return 'Password must be 8+ characters.';
  if (characters.length > PASSWORD_MAX) return `Password must be ${PASSWORD_MAX} characters or fewer.`;
  const lowered = [...password.toLowerCase()];
  if (new Set(lowered).size < 5) return 'Use at least 5 different characters in your password.';
  // A run of keys, each one up (or each one down) from the last: 12345678, abcdefgh, 98765432.
  const steps = new Set(lowered.slice(1).map((character, index) => character.codePointAt(0) - lowered[index].codePointAt(0)));
  if (steps.size === 1 && (steps.has(1) || steps.has(-1))) return 'That password is too common and easy to guess. Choose another.';
  const joined = lowered.join('');
  if ([username.toLowerCase(), email.toLowerCase().split('@')[0]].some(name => [...name].length >= 3 && joined.includes(name))) {
    return 'Your password cannot contain your username or email.';
  }
  return '';
}

// Under a new password's field: what it takes.
const PASSWORD_ADVICE = `8 to ${PASSWORD_MAX} characters. A few words together work well; avoid common passwords, runs like 12345678, and your username.`;
