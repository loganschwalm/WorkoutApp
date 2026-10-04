"""Accounts in the browser: creating one with an email, signing in with it, resetting a forgotten password with an
emailed code, and adding an email in Settings."""

import json
import sqlite3
import time

from ..harness import load_server

INTERCEPT = False
MAIL = True


def run(t):
    cdp, check, api, mail = t.cdp, t.check, t.api, t.mail

    text = t.text

    def shown(element):
        return cdp.ev(f"getComputedStyle(document.getElementById('{element}')).display !== 'none'")

    def fill(**values):
        for element, value in values.items():
            cdp.ev(f"document.getElementById('{element}').value = {json.dumps(value)}")

    def submit(form):
        cdp.ev(f"document.getElementById('{form}').requestSubmit()")

    def open_login():
        cdp.goto('/login.html')
        cdp.wait("document.readyState === 'complete'")
        cdp.pause(0.5)  # the page asks the server what it offers

    def signed_in_as(username):
        landed = cdp.wait("location.pathname === '/'", timeout=10)
        return landed and cdp.wait(f"window.localUsername === {json.dumps(username)}", timeout=10)

    def shows_error(words):
        cdp.wait("!document.getElementById('authFeedback').hidden")
        return shown('authFeedback') and words in text('authFeedback')

    # ------------------------------------------------------------------ C1 creating an account
    print('C1  creating an account asks for an email')
    open_login()
    check('signing in takes an email or a username in one field', text('usernameLabel') == 'Email or username' and not shown('email'))
    cdp.ev("document.getElementById('registerTab').click()")
    check('Create account adds an email field', shown('email') and shown('emailLabel'))
    check('and asks for a username in the other', text('usernameLabel') == 'Username' and text('authSubmit') == 'Create account')
    check('with the password marked as new, for password managers', cdp.ev("document.getElementById('password').autocomplete") == 'new-password')
    check('and without Forgot password?', not shown('forgotButton'))
    fill(email='newbie@example.test', username='new@bie', password='chalk-and-plates-42')
    submit('authForm')
    check('a username with an @ is refused, saying why', shows_error('cannot contain @'), text('authFeedback'))
    fill(email='Newbie@Example.test', username='newbie')
    submit('authForm')
    check('an account is created and signed in', signed_in_as('newbie'), cdp.ev('location.pathname'))
    check('with its email', cdp.ev('window.localEmail') == 'newbie@example.test', cdp.ev('window.localEmail'))

    # ------------------------------------------------------------------ C2 signing in with an email
    print('C2  signing in with an email')
    open_login()
    check('the email field is gone again', not shown('email') and cdp.ev("document.getElementById('email').disabled") is True)
    fill(username='NEWBIE@example.test', password='wrong-password')
    submit('authForm')
    check('a wrong password is refused', shows_error('Wrong email, username or password'), text('authFeedback'))
    fill(password='chalk-and-plates-42')
    submit('authForm')
    check('the email, in any case, signs in', signed_in_as('newbie'), cdp.ev('location.pathname'))

    # ------------------------------------------------------------------ C2b remember me
    print('C2b "Remember me" is ticked to begin with, and unticked signs in for this visit only')

    def session_cookie():
        cookies = cdp.send('Network.getCookies', urls=[cdp.ev('location.origin')])['result']['cookies']
        return next((cookie for cookie in cookies if cookie['name'] == 'session'), None)

    def sign_in_remembering(remember):
        cdp.send('Network.clearBrowserCookies')
        open_login()
        cdp.ev(f"document.getElementById('remember').checked = {json.dumps(remember)}")
        fill(username='newbie', password='chalk-and-plates-42')
        submit('authForm')
        return signed_in_as('newbie') and session_cookie()

    cdp.send('Network.clearBrowserCookies')
    open_login()
    check('the sign-in form has a Remember me box, ticked', shown('remember') and cdp.ev("document.getElementById('remember').checked") is True)
    check('labelled so, and the label ticks it', 'Remember me' in cdp.ev("document.querySelector('label[for=remember]').textContent")
          and cdp.ev("document.querySelector('label[for=remember]').click(); document.getElementById('remember').checked") is False)
    cdp.ev("document.getElementById('registerTab').click()")
    check('Create account has it too', shown('remember'))
    cdp.ev("document.getElementById('loginTab').click()")
    cookie = sign_in_remembering(True)
    check('signing in with it ticked gives a cookie that outlives the browser',
          cookie and cookie['session'] is False and cookie['expires'] - time.time() > 25 * 86400, cookie)
    cookie = sign_in_remembering(False)
    check('with it unticked, a cookie the browser drops when it closes', cookie and cookie['session'] is True, cookie)
    check('and it is still signed in for the visit', cdp.ev('window.localUsername') == 'newbie', cdp.ev('window.localUsername'))

    # ------------------------------------------------------------------ C3 forgot password
    print('C3  a forgotten password is reset with an emailed code')
    open_login()
    check('the sign-in page offers Forgot password?', shown('forgotButton'))
    fill(username='newbie@example.test')
    cdp.ev("document.getElementById('forgotButton').click()")
    check('it asks for the email, filled in from the sign-in field',
          shown('forgotForm') and cdp.ev("document.getElementById('resetEmail').value") == 'newbie@example.test')
    check('in place of the sign-in form and its tabs', not shown('authForm') and not shown('authTabs'))
    cdp.ev("document.querySelector('#forgotForm [data-back]').click()")
    check('Back to sign in returns to it', shown('authForm') and shown('authTabs') and not shown('forgotForm'))
    cdp.ev("document.getElementById('forgotButton').click()")
    submit('forgotForm')
    check('sending the code moves on to entering it', cdp.wait("!document.getElementById('resetForm').hidden"))
    check('saying where it went', 'newbie@example.test' in text('resetIntro'), text('resetIntro'))
    first = mail.code(mail.wait('newbie@example.test', 1, poll=cdp.pause))
    check('and the email arrives with a code', first is not None)

    cdp.ev("document.getElementById('resendCode').click()")
    check('Send a new code says so', cdp.wait("!document.getElementById('authNotice').hidden") and 'new code' in text('authNotice'), text('authNotice'))
    newest = mail.code(mail.wait('newbie@example.test', 2, poll=cdp.pause))
    check('and a second email arrives', newest is not None and len(mail.to('newbie@example.test')) == 2)
    if first == newest:  # one time in a million the new code repeats the old one; then any other code is wrong
        first = f'{(int(first) + 1) % 10 ** 6:06d}'
    fill(resetCode=first, newPassword='brand-new-password')
    submit('resetForm')
    check('the first code no longer works, and the page says so', shows_error('wrong or has expired'), text('authFeedback'))
    check('leaving the form to try again', shown('resetForm') and not cdp.ev("document.getElementById('resetSubmit').disabled"))
    fill(resetCode=newest)
    submit('resetForm')
    check('the newest code resets the password and signs in', signed_in_as('newbie'), cdp.ev('location.pathname'))
    cookie = api('POST', '/api/auth/login', {'login': 'newbie', 'password': 'brand-new-password'})[1]
    check('the new password is the one that works now', cookie is not None and 'session=' in cookie)

    # ------------------------------------------------------------------ C4 the phone layout
    print('C4  every step fits a phone')
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    fits = "document.documentElement.scrollWidth <= innerWidth"
    open_login()
    check('signing in', cdp.ev(fits) is True)
    cdp.ev("document.getElementById('registerTab').click()")
    check('creating an account', cdp.ev(fits) is True)
    cdp.ev("document.getElementById('loginTab').click(); document.getElementById('forgotButton').click()")
    check('asking for a code', cdp.ev(fits) is True)
    fill(resetEmail='someone.with.a.rather.long.address@example.test')
    submit('forgotForm')
    cdp.wait("!document.getElementById('resetForm').hidden")
    check('entering it, even for a long address', cdp.ev(fits) is True)
    cdp.send('Emulation.clearDeviceMetricsOverride')

    # ------------------------------------------------------------------ C5 Settings
    print('C5  an account without an email adds one in Settings')
    db = sqlite3.connect(t.db_path('test.db'))
    db.execute("UPDATE users SET email = NULL WHERE username = 'tester'")
    db.commit()
    db.close()
    t.set_cookie(t.token)
    t.open_tracker()
    cdp.wait("window.localUsername === 'tester'")
    cdp.ev("document.getElementById('settingsButton').click()")
    check('Settings says there is no email yet, and why to add one', 'reset a forgotten password' in text('accountEmail'), text('accountEmail'))
    check('with an Add email button', text('changeEmailButton') == 'Add email' and not shown('emailEditor'))
    cdp.ev("document.getElementById('changeEmailButton').click()")
    check('which opens the email fields', shown('emailEditor') and cdp.ev("document.activeElement.id") == 'emailSetting')
    cdp.ev("document.getElementById('settingsForm').requestSubmit()")
    check('their being empty does not stop Save settings', cdp.wait("document.getElementById('settingsModal').hidden"))
    cdp.ev("document.getElementById('settingsButton').click(); document.getElementById('changeEmailButton').click()")
    fill(emailSetting='Tester@Example.test', emailPassword='wrong-password')
    submit('emailForm')
    cdp.wait("!document.getElementById('emailFeedback').hidden")
    check('a wrong password is refused, saying so', 'not right' in text('emailFeedback'), text('emailFeedback'))
    check('without the page thinking it was signed out', cdp.ev("!document.getElementById('sessionExpired')") is True)
    fill(emailPassword='chalk-and-plates-42')
    submit('emailForm')
    check('the right password saves it', cdp.wait("document.getElementById('accountEmail').textContent === 'tester@example.test'"), text('accountEmail'))
    check('closing the fields, and offering to change it', not shown('emailEditor') and text('changeEmailButton') == 'Change email')
    check('and the server has it', api('GET', '/api/auth/me', token=t.token)[0]['user']['email'] == 'tester@example.test')
    cdp.ev("document.getElementById('changeEmailButton').click()")
    check('changing it starts from the current email', cdp.ev("document.getElementById('emailSetting').value") == 'tester@example.test')
    cdp.ev("document.getElementById('cancelEmail').click()")
    check('Cancel closes the fields', not shown('emailEditor'))
    cdp.ev("document.getElementById('closeSettings').click()")

    # ------------------------------------------------------------------ C6 no mail server
    print('C6  without a mail server, Forgot password? says who can reset it')
    plain = t.start_server('nomail.db')
    cdp.send('Page.navigate', url=plain.base_url + '/login.html')
    check('the sign-in page still offers Forgot password?',
          cdp.wait("document.readyState === 'complete' && !document.getElementById('forgotButton').hidden"))
    cdp.ev("document.getElementById('forgotButton').click()")
    cdp.wait("!document.getElementById('authNotice').hidden")
    check('which says to ask whoever runs the server', 'Ask whoever runs it' in text('authNotice'), text('authNotice'))
    check('rather than offering to email a code', not shown('forgotForm') and shown('authForm'))

    # ------------------------------------------------------------------ C7 changing the password
    print('C7  the password is changed in Settings')

    def status_of_sign_in(password):
        return t.request('POST', '/api/auth/login', json.dumps({'login': 'tester', 'password': password}).encode(),
                         {'Content-Type': 'application/json'})[0]

    _, cookie = api('POST', '/api/auth/login', {'login': 'tester', 'password': 'chalk-and-plates-42'})
    elsewhere = cookie.split('session=')[1].split(';')[0]
    t.set_cookie(t.token)
    t.open_tracker()
    cdp.wait("window.localUsername === 'tester'")
    cdp.ev("document.getElementById('settingsButton').click()")
    check('Settings offers Change password', shown('changePasswordButton') and not shown('passwordEditor'))
    cdp.ev("document.getElementById('changePasswordButton').click()")
    check('which opens the password fields', shown('passwordEditor') and cdp.ev('document.activeElement.id') == 'currentPassword')
    cdp.ev("document.getElementById('settingsForm').requestSubmit()")
    check('their being empty does not stop Save settings', cdp.wait("document.getElementById('settingsModal').hidden"))
    cdp.ev("document.getElementById('settingsButton').click(); document.getElementById('changePasswordButton').click()")
    fill(currentPassword='wrong-password', newPassword='brand-new-password')
    submit('passwordForm')
    cdp.wait("!document.getElementById('passwordFeedback').hidden")
    check('a wrong current password is refused, saying so', 'not right' in text('passwordFeedback'), text('passwordFeedback'))
    check('without the page thinking it was signed out', cdp.ev("!document.getElementById('sessionExpired')") is True)
    fill(currentPassword='chalk-and-plates-42')
    submit('passwordForm')
    check('the right one changes it, and says other devices were signed out',
          cdp.wait("document.getElementById('accountNotice').textContent.startsWith('Password changed.')")
          and 'signed out' in text('accountNotice'), text('accountNotice'))
    check('closing the fields', not shown('passwordEditor'))
    check('the new password signs in, and the old one does not',
          status_of_sign_in('brand-new-password') == 200 and status_of_sign_in('chalk-and-plates-42') == 401)
    check('this browser stays signed in', api('GET', '/api/auth/me', token=t.token)[0]['user'] is not None)
    check('the other device does not', api('GET', '/api/auth/me', token=elsewhere)[0]['user'] is None)
    cdp.ev("document.getElementById('changeEmailButton').click()")
    check('opening the email fields closes the notice', not shown('accountNotice') and shown('emailEditor'))
    cdp.ev("document.getElementById('closeSettings').click()")

    # ------------------------------------------------------------------ C7b the devices signed in
    print('C7b the devices signed in are listed in Settings, and signed out from there')
    agents = {'phone': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1',
              'laptop': 'Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0'}
    devices = {}
    # Sessions the checks above left behind (the sign-in that tried the new password) are cleared, so the list is just what is made here.
    api('POST', '/api/account/sessions/sign-out-others', {}, t.token)
    for name, agent in agents.items():
        status, headers, _ = t.request('POST', '/api/auth/login', json.dumps({'login': 'tester', 'password': 'brand-new-password'}).encode(),
                                       {'Content-Type': 'application/json', 'User-Agent': agent})
        devices[name] = headers['set-cookie'].split('session=')[1].split(';')[0]

    def device_rows():
        return cdp.ev("[...document.querySelectorAll('#deviceList .device')].map(row => row.textContent.replace(/\\s+/g, ' ').trim())")

    def signed_in(token):
        return api('GET', '/api/auth/me', token=token)[0]['user'] is not None
    cdp.ev("document.getElementById('settingsButton').click()")
    check('Settings offers Signed-in devices, closed to begin with', shown('devicesButton') and not shown('devicesEditor'))
    cdp.ev("document.getElementById('devicesButton').click()")
    check('which lists the three devices', cdp.wait("document.querySelectorAll('#deviceList .device').length === 3"), device_rows())
    rows = device_rows()
    check('this one is marked, and has no button to sign it out',
          cdp.ev("[...document.querySelectorAll('#deviceList .device')].filter(row => row.querySelector('.badge') && !row.querySelector('button')).length") == 1)
    check('the others are named by browser and system, with when they were last used',
          any(row.startswith('Safari on iPhone') and 'Last used just now' in row for row in rows) and any(row.startswith('Firefox on Linux') and 'Last used just now' in row for row in rows), rows)
    check('and the panel offers to sign out all the others', shown('signOutOthers') and cdp.ev('document.activeElement.id') == 'closeDevices')
    cdp.ev("document.querySelector('#deviceList button[aria-label^=\"Sign out Safari on iPhone\"]').click()")
    check('Sign out on the phone ends it, and the list shows two',
          cdp.wait("document.querySelectorAll('#deviceList .device').length === 2") and not signed_in(devices['phone']) and signed_in(devices['laptop']) and signed_in(t.token), device_rows())
    check('and says so', 'Signed out' in text('accountNotice'), text('accountNotice'))
    cdp.ev("document.getElementById('signOutOthers').click()")
    check('Sign out all other devices ends the rest, leaving this one',
          cdp.wait("document.querySelectorAll('#deviceList .device').length === 1") and not signed_in(devices['laptop']) and signed_in(t.token), device_rows())
    check('says how many, and has no one left to offer it for', 'Signed out of 1 other device.' == text('accountNotice') and not shown('signOutOthers'), text('accountNotice'))
    check('Close shuts the panel', cdp.ev("document.getElementById('closeDevices').click(), true") and not shown('devicesEditor'))
    cdp.ev("document.getElementById('devicesButton').click(); document.getElementById('changeEmailButton').click()")
    check('and opening another account panel shuts it too', shown('emailEditor') and not shown('devicesEditor'))
    cdp.ev("document.getElementById('closeSettings').click()")

    # ------------------------------------------------------------------ C8 deleting the account
    print('C8  an account is deleted in Settings')
    _, cookie = api('POST', '/api/auth/register', {'username': 'goodbye', 'email': 'goodbye@example.test', 'password': 'chalk-and-plates-42'})
    goodbye = cookie.split('session=')[1].split(';')[0]
    api('POST', '/api/workouts', {'name': 'Last One', 'exercises': [t.ex('Squat', 100, 5, [(5, 100)])]}, goodbye)
    t.set_cookie(goodbye)
    t.open_tracker()
    cdp.wait("window.localUsername === 'goodbye'")
    goodbye_id = cdp.ev('localUserId')
    kept = f"Object.keys(localStorage).filter(key => key.startsWith('workout-tracker-') && key.endsWith('-{goodbye_id}'))"
    check('this device keeps a copy for the account', len(cdp.ev(kept) or []) > 0, cdp.ev(kept))
    cdp.ev("document.getElementById('settingsButton').click()")
    check('Settings offers Delete account', shown('deleteAccountButton') and not shown('deleteEditor'))
    cdp.ev("document.getElementById('changePasswordButton').click(); document.getElementById('deleteAccountButton').click()")
    check('which asks for the password, says what goes, and closes the password fields',
          shown('deleteEditor') and not shown('passwordEditor') and 'Export first' in text('deleteEditor') and cdp.ev('document.activeElement.id') == 'deletePassword')
    fill(deletePassword='wrong-password')
    submit('deleteForm')
    cdp.wait("!document.getElementById('deleteFeedback').hidden")
    check('a wrong password is refused, and nothing is deleted', 'not right' in text('deleteFeedback')
          and api('GET', '/api/auth/me', token=goodbye)[0]['user'] is not None, text('deleteFeedback'))
    cdp.answer = False
    asked = len(cdp.dialogs)
    fill(deletePassword='chalk-and-plates-42')
    submit('deleteForm')
    cdp.pause(0.5)
    check('it asks once more, and saying no deletes nothing', len(cdp.dialogs) == asked + 1 and 'cannot be undone' in cdp.dialogs[-1]
          and api('GET', '/api/auth/me', token=goodbye)[0]['user'] is not None, cdp.dialogs[asked:])
    cdp.answer = True
    submit('deleteForm')
    check('saying yes deletes it and goes to the sign-in page', cdp.wait("location.pathname === '/login.html'"), cdp.ev('location.href'))
    cdp.wait("!document.getElementById('authNotice').hidden")
    check('which says the account was deleted', 'deleted' in text('authNotice'), text('authNotice'))
    check("and this device's copy of it is gone", cdp.ev(kept) == [], cdp.ev(kept))
    check('the account is gone from the server', api('GET', '/api/auth/me', token=goodbye)[0]['user'] is None
          and t.request('POST', '/api/auth/login', json.dumps({'login': 'goodbye', 'password': 'chalk-and-plates-42'}).encode(),
                        {'Content-Type': 'application/json'})[0] == 401)
    t.set_cookie(t.token)

    # ------------------------------------------------------------------ C9 what a new account's details must be
    print("C9  the forms check a new username, email and password as the server does, before sending")
    # The server's own rules, loaded from its modules, to hold the page's copy of them to.
    server = load_server()

    def server_says(rule, *values):
        try:
            result = getattr(server, rule)(*values)
        except server.BadRequest as error:
            return str(error)
        return result if rule == 'password_problem' and result else ''

    usernames = ['ab', 'abc', 'u' * 32, 'u' * 33, 'new@bie', 'tab\tbed', 'zero​width', 'no break', 'Jo Lifter', '  padded  ', 'émile']
    emails = ['me@example.test', 'Me@Example.TEST', 'short@example.c', 'digits@example.123', 'two..dots@example.test', '.dot@example.test',
              'dot.@example.test', 'hyphen@-example.test', 'hyphen@example-.test', 'under@exa_mple.test', 'com,ma@example.test',
              'josé@example.test', 'l' * 64 + '@example.test', 'l' * 65 + '@example.test', "o'brien@example.test", 'x@xn--bcher-kva.example',
              'first.last+gym@mail.example.co.uk', 'no-at-sign', 'a@localhost', ' spaced@example.test ']
    passwords = [('short', 'lifter', 'lifter@example.test'), ('abababcdcdcd', 'lifter', ''), ('12345678', '', ''), ('hgfedcba', '', ''),
                 ('abcdefgh-' * 14 + 'ab', '', ''), ('abcdefgh-' * 14 + 'abc', '', ''), ('I-am-Lifter-99', 'lifter', ''),
                 ('benchqueen-2026', 'squatter', 'benchqueen@example.test'), ('correct horse battery staple', 'lifter', 'lifter@example.test'),
                 ('Ünïcödé-pässwörd', '', ''), ('ab', 'abcdef', '')]
    open_login()
    page = cdp.ev(f"""({{ usernames: {json.dumps(usernames)}.map(usernameProblem), emails: {json.dumps(emails)}.map(emailProblem),
        passwords: {json.dumps(passwords)}.map(([password, username, email]) => passwordProblem(password, username, email)) }})""")
    for kind, rule, values in [('usernames', 'new_username', [[value] for value in usernames]), ('emails', 'email_address', [[value] for value in emails]),
                               ('passwords', 'password_problem', passwords)]:
        expected = [server_says(rule, *value) for value in values]
        differ = [(value, said, wanted) for value, said, wanted in zip(values, page[kind], expected) if said != wanted]
        check(f'the page judges {len(values)} {kind} as the server does, in its words', not differ, differ)
    check('the server alone refuses the most common passwords', server_says('password_problem', 'password1', '', '')
          and cdp.ev("passwordProblem('password1')") == '')

    cdp.ev("setMode('reset'); resetEmail = 'lifter@example.test'")
    check('resetting a password says what the new one takes', shown('newPasswordAdvice') and '8 to 128 characters' in text('newPasswordAdvice'))
    fill(resetCode='123456', newPassword='lifter-at-dawn')
    submit('resetForm')
    check('and a new one with the name of the email in it is pointed out before anything is sent', shows_error('username or email')
          and cdp.ev("document.getElementById('newPassword').getAttribute('aria-invalid')") == 'true', text('authFeedback'))
    cdp.ev("setMode('login')")

    cdp.ev("document.getElementById('registerTab').click()")
    check('creating an account says what a password takes', shown('passwordAdvice') and '8 to 128 characters' in text('passwordAdvice'))
    check('and holds the username to 32 characters', cdp.ev("document.getElementById('username').maxLength") == 32)
    fill(email='rules@example.c', username='ruleslifter', password='deadlifts-on-monday')
    submit('authForm')
    check('an email that is not a real address is pointed out before anything is sent', shows_error('valid email')
          and cdp.ev("document.getElementById('email').getAttribute('aria-invalid')") == 'true' and cdp.ev('document.activeElement.id') == 'email',
          text('authFeedback'))
    check('so no account was made', t.request('POST', '/api/auth/login', json.dumps({'login': 'ruleslifter', 'password': 'deadlifts-on-monday'}).encode(),
                                              {'Content-Type': 'application/json'})[0] == 401)
    cdp.ev("(e => { e.value = 'rules@example.test'; e.dispatchEvent(new Event('input', { bubbles: true })); })(document.getElementById('email'))")
    check('typing in it takes the mark away', cdp.ev("document.getElementById('email').hasAttribute('aria-invalid')") is False)
    fill(password='87654321')
    submit('authForm')
    check('a run of keys is pointed out at the password', shows_error('too common')
          and cdp.ev("document.getElementById('password').getAttribute('aria-invalid')") == 'true', text('authFeedback'))
    fill(password='iloveyou1')
    submit('authForm')
    cdp.wait("document.getElementById('authFeedback').textContent.includes('too common')")
    check('a common one comes back from the server, in the same words', 'too common' in text('authFeedback'), text('authFeedback'))
    fill(password='deadlifts-on-monday')
    submit('authForm')
    check('one that follows the rules creates the account', signed_in_as('ruleslifter'), cdp.ev('location.pathname'))
    open_login()
    check('signing in shows no advice and sets no limits, for accounts from before them', not shown('passwordAdvice')
          and not cdp.ev("document.getElementById('username').hasAttribute('maxlength')"))

    t.open_tracker()
    cdp.wait("window.localUsername === 'ruleslifter'")
    cdp.ev("document.getElementById('settingsButton').click(); document.getElementById('changePasswordButton').click()")
    check('changing the password says what it takes', shown('newPasswordAdvice') and '8 to 128 characters' in text('newPasswordAdvice'))
    fill(currentPassword='deadlifts-on-monday', newPassword='ruleslifter-2')
    submit('passwordForm')
    cdp.wait("!document.getElementById('passwordFeedback').hidden")
    check('a new password with the username in it is pointed out before anything is sent', 'username or email' in text('passwordFeedback')
          and cdp.ev("document.getElementById('newPassword').getAttribute('aria-invalid')") == 'true', text('passwordFeedback'))
    fill(newPassword='welcome123')
    submit('passwordForm')
    cdp.wait("document.getElementById('passwordFeedback').textContent.includes('too common')")
    check('and a common one is refused by the server', 'too common' in text('passwordFeedback'), text('passwordFeedback'))
    cdp.ev("document.getElementById('changeEmailButton').click()")
    check('opening another panel clears the mark', not cdp.ev("document.querySelector('#settingsModal [aria-invalid]')"))
    fill(emailSetting='rules@example', emailPassword='deadlifts-on-monday')
    submit('emailForm')
    cdp.wait("!document.getElementById('emailFeedback').hidden")
    check('an email that is not a real address is pointed out in Settings too', 'valid email' in text('emailFeedback')
          and cdp.ev("document.getElementById('emailSetting').getAttribute('aria-invalid')") == 'true', text('emailFeedback'))
    check('and the password is still the one it was', t.request('POST', '/api/auth/login', json.dumps({'login': 'ruleslifter', 'password': 'deadlifts-on-monday'}).encode(),
                                                                {'Content-Type': 'application/json'})[0] == 200)
    cdp.ev("document.getElementById('closeSettings').click()")
    t.set_cookie(t.token)
