"""Accounts in the browser: creating one with an email, signing in with it, resetting a forgotten password with an
emailed code, and adding an email in Settings."""

import json
import sqlite3

INTERCEPT = False
MAIL = True


def run(t):
    cdp, check, api, mail = t.cdp, t.check, t.api, t.mail

    def text(element):
        return cdp.ev(f"document.getElementById('{element}').textContent")

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
    fill(email='newbie@example.test', username='new@bie', password='password123')
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
    fill(password='password123')
    submit('authForm')
    check('the email, in any case, signs in', signed_in_as('newbie'), cdp.ev('location.pathname'))

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
    fill(emailPassword='password123')
    submit('emailForm')
    check('the right password saves it', cdp.wait("document.getElementById('accountEmail').textContent === 'tester@example.test'"), text('accountEmail'))
    check('closing the fields, and offering to change it', not shown('emailEditor') and text('changeEmailButton') == 'Change email')
    check('and the server has it', api('GET', '/api/auth/me', token=t.token)[0]['user']['email'] == 'tester@example.test')
    cdp.ev("document.getElementById('changeEmailButton').click()")
    check('changing it starts from the current email', cdp.ev("document.getElementById('emailSetting').value") == 'tester@example.test')
    cdp.ev("document.getElementById('cancelEmail').click()")
    check('Cancel closes the fields', not shown('emailEditor'))
    cdp.ev("document.getElementById('cancelSettings').click()")

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
