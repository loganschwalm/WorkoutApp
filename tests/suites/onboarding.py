"""The first-login welcome (onboarding.js): shown on the Tracker after Create account and at no other time, its six steps,
the choices it offers and what finishing, skipping and Escape save, the hand-off to a program's setup, the templates or the
Tracker, seeing it again from Settings, never over a workout, and how it fits and reads on a phone, in landscape, at the largest
Text size and in every theme."""

import json

INTERCEPT = False

FLAG = 'workout-tracker-welcome'
STEPS = ['welcome', 'units', 'training', 'week', 'tour', 'ready']
PASSWORD = 'chalk-and-plates-42'

# What the welcome shows now: the step, the focus, the progress, which buttons are there and what the dialog is labelled by.
STATE = """(() => {
  const dialog = document.getElementById('onboarding');
  const there = id => { const element = document.getElementById(id); return !element.hidden && element.getClientRects().length > 0; };
  const dots = [...dialog.querySelectorAll('.onboarding-dot')];
  const labelledBy = document.getElementById(dialog.getAttribute('aria-labelledby'));
  return { current: dialog.dataset.current, shown: [...dialog.querySelectorAll('.onboarding-step')].filter(step => !step.hidden).map(step => step.dataset.step),
    focus: document.activeElement.id, count: document.getElementById('onboardingCount').textContent,
    done: dots.map(dot => dot.classList.contains('done')), dots: dots.map(dot => dot.classList.contains('current')),
    back: there('onboardingBack'), next: there('onboardingNext'), skip: there('onboardingSkip'), start: there('onboardingStart'),
    nextText: there('onboardingNext') ? document.getElementById('onboardingNext').textContent : null,
    labelledby: dialog.getAttribute('aria-labelledby'),
    labelledShown: Boolean(labelledBy) && labelledBy.tagName === 'H2' && !labelledBy.closest('.onboarding-step').hidden };
})()"""

# The controls in the welcome as they stand on the step shown: anything under 44px tall, and anything past either side of the
# screen. A <label for> is the text above the goal's <select>, not a thing to tap (the select is, and is measured), so it is left
# out; a label holding its input (a choice, a day) is the tap target and is measured.
FIT = """(() => {
  const dialog = document.getElementById('onboarding');
  const seen = element => element.getClientRects().length > 0;
  const name = element => element.id || `${element.tagName.toLowerCase()} ${element.textContent.trim().slice(0, 24)}`;
  const controls = [...dialog.querySelectorAll('button, label, summary, select')].filter(seen).filter(element => !(element.tagName === 'LABEL' && element.htmlFor));
  const small = controls.filter(element => element.getBoundingClientRect().height < 43.5).map(element => `${name(element)}: ${Math.round(element.getBoundingClientRect().height)}`);
  const outside = [...dialog.querySelectorAll('*')].filter(seen).filter(element => { const box = element.getBoundingClientRect();
    return box.width > 0 && (box.right > innerWidth + 0.5 || box.left < -0.5); }).map(name);
  const onward = [...['onboardingNext', 'onboardingStart'].map(id => document.getElementById(id))].find(button => !button.hidden);
  return { small, outside: outside.slice(0, 6), page: document.documentElement.scrollWidth <= innerWidth, dialog: dialog.scrollWidth <= dialog.clientWidth,
    measured: controls.length, onward: onward.getBoundingClientRect().bottom <= innerHeight + 0.5 };
})()"""

# WCAG's contrast for every piece of text the welcome shows on the step shown, against what is really under it: the first
# background behind it that is not transparent, with the layers between laid over it, and for the overlay's own ground its
# page colour with the glow its radial gradient lays over the top of it (strongest at the top centre, gone by 70% of the way
# out). The step's fade-in is finished first. Text is blended with that by its own alpha and its opacity and its ancestors' (the summary's labels are at 75%).
CONTRAST = """window.onboardingContrastCheck = () => {
  // A step fades in as it opens; measured part way through, its text would be as faint as the fade.
  document.getAnimations().forEach(animation => animation.finish());
  const parse = value => {
    const numbers = (value.match(/-?[\\d.]+(e-?\\d+)?/g) || []).map(Number);
    const scale = value.startsWith('color(') ? 255 : 1;
    return [numbers[0] * scale, numbers[1] * scale, numbers[2] * scale, numbers.length > 3 ? numbers[3] : 1];
  };
  const luminance = rgb => { const [r, g, b] = rgb.slice(0, 3).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const ratio = (a, b) => { const [x, y] = [luminance(a), luminance(b)]; return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const over = (top, under, alpha) => [0, 1, 2].map(i => top[i] * alpha + under[i] * (1 - alpha));
  const dialog = document.getElementById('onboarding');
  const probe = document.createElement('span');
  probe.style.setProperty('color', 'var(--glow)');
  dialog.append(probe);
  const glow = parse(getComputedStyle(probe).color);
  probe.remove();
  const frame = dialog.getBoundingClientRect();
  const ground = element => {
    const box = element.getBoundingClientRect();
    const centre = frame.left + frame.width / 2;
    const x = Math.min(Math.max(centre, box.left), box.right), y = Math.min(Math.max(frame.top, box.top), box.bottom);
    const distance = Math.hypot((x - centre) / (1.2 * frame.width), (y - frame.top) / (0.6 * frame.height));
    return over(glow, parse(getComputedStyle(dialog).backgroundColor), Math.max(0, 1 - distance / 0.7));
  };
  const behind = element => {
    const layers = [];
    for (let node = element; node && node !== dialog; node = node.parentElement) {
      const colour = parse(getComputedStyle(node).backgroundColor);
      if (colour[3] > 0) layers.push(colour);
      if (colour[3] >= 1) break;
    }
    let base = layers.length && layers[layers.length - 1][3] >= 1 ? layers.pop() : ground(element);
    while (layers.length) { const layer = layers.pop(); base = over(layer, base, layer[3]); }
    return base;
  };
  const faded = element => { let opacity = 1; for (let node = element; node && node !== dialog.parentElement; node = node.parentElement) opacity *= Number(getComputedStyle(node).opacity); return opacity; };
  const texts = [...dialog.querySelectorAll('*')].filter(element => element.getClientRects().length > 0 && getComputedStyle(element).visibility === 'visible'
    && [...element.childNodes].some(node => node.nodeType === 3 && node.textContent.trim()));
  const measured = texts.map(element => { const colour = parse(getComputedStyle(element).color); const under = behind(element);
    return [element.id || `${element.tagName.toLowerCase()} ${element.textContent.trim().slice(0, 24)}`, Math.round(ratio(over(colour, under, colour[3] * faded(element)), under) * 100) / 100]; });
  return { measured: measured.length, low: measured.filter(([, value]) => value < 4.5) };
};
true"""


def run(t):
    cdp, check, api = t.cdp, t.check, t.api

    # ---- helpers ----------------------------------------------------------

    def account(name):
        cookie = api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': PASSWORD})[1]
        return cookie.split('session=')[1].split(';')[0]

    def browser_token():
        cookies = cdp.send('Network.getCookies', urls=[t.base_url])['result']['cookies']
        return next(cookie['value'] for cookie in cookies if cookie['name'] == 'session')

    def server_state(token):
        return api('GET', '/api/state', token=token)[0] or {}

    def server_settings(token):
        return server_state(token).get('settings') or {}

    def flag():
        return cdp.ev(f"sessionStorage.getItem('{FLAG}')")

    def flag_gone():
        # Asked as a comparison, so a protocol error (which reads as None) cannot pass for the flag being gone.
        return cdp.ev(f"sessionStorage.getItem('{FLAG}') === null") is True

    def set_flag():
        cdp.ev(f"sessionStorage.setItem('{FLAG}', '1')")

    def is_open():
        return cdp.ev("(() => { const dialog = document.getElementById('onboarding'); return Boolean(dialog) && !dialog.hidden "
                      "&& document.body.classList.contains('onboarding-open'); })()")

    def is_closed():
        return cdp.ev("(() => { const dialog = document.getElementById('onboarding'); return (!dialog || dialog.hidden) "
                      "&& !document.body.classList.contains('onboarding-open'); })()")

    def settled():
        # The welcome is asked for once the page has started and the account's settings are in; this waits until that has
        # happened, so "not shown" means it was decided against, not that it had yet to be asked.
        cdp.wait('initialLoadDone === true', timeout=12)
        cdp.ev("window.serverStateReady.then(() => new Promise(done => setTimeout(done, 150))).then(() => true)")

    def reload_tracker():
        cdp.goto('/index.html')
        settled()

    def open_welcomed(token):
        """A new account opened on the Tracker as if just created on the sign-in page (the flag login.js leaves)."""
        t.set_cookie(token)
        set_flag()
        t.open_tracker()
        settled()
        return cdp.wait("document.body.classList.contains('onboarding-open')", timeout=8)

    def state():
        return cdp.ev(STATE)

    def step_index():
        return STEPS.index(cdp.ev("document.getElementById('onboarding').dataset.current"))

    def go(index):
        for _ in range(12):
            now = step_index()
            if now == index:
                return
            t.click('onboardingNext' if index > now else 'onboardingBack')

    def pick(name, value):
        # A tap: the radio or box's own click, which the page hears as a change (setting .checked would not be).
        cdp.ev(f"document.querySelector('#onboarding input[name={name}][value=\"{value}\"]').click()")

    def picked(name):
        return cdp.ev(f"[...document.querySelectorAll('#onboarding input[name={name}]:checked')].map(input => input.value)")

    def settings():
        return cdp.ev('getWorkoutSettings()')

    def escape():
        cdp.ev("(document.activeElement || document.body).dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))")
        cdp.pause(0.2)

    def synced():
        return cdp.wait("readLocalState('settings') && readLocalState('settings').dirty === false", timeout=10)

    def fold_templates():
        cdp.ev("if (!document.getElementById('templateArea').hidden) document.getElementById('templatesToggle').click()")
        return cdp.ev("document.getElementById('templateArea').hidden") is True

    def expected_state(index):
        name = STEPS[index]
        last = index == len(STEPS) - 1
        return {'current': name, 'shown': [name], 'focus': f'onboardingTitle-{name}', 'labelledby': f'onboardingTitle-{name}', 'labelledShown': True,
                'count': f'Step {index + 1} of 6', 'done': [j < index for j in range(6)], 'dots': [j == index for j in range(6)],
                'back': index > 0, 'next': not last, 'skip': not last, 'start': last, 'nextText': None if last else ('Get started' if index == 0 else 'Next')}

    def differences(visited, keys):
        return [(index, key, seen[key], expected_state(index)[key]) for index, seen in visited for key in keys if seen[key] != expected_state(index)[key]]

    # ------------------------------------------------------------------ O1 creating an account in the browser
    print('O1  Create account lands on the Tracker with the welcome open, on its first step')
    cdp.goto('/login.html')
    cdp.pause(0.5)
    cdp.ev("document.getElementById('registerTab').click()")
    for element, value in {'email': 'firstlifter@example.test', 'username': 'firstlifter', 'password': PASSWORD}.items():
        cdp.ev(f"document.getElementById('{element}').value = {json.dumps(value)}")
    cdp.ev("document.getElementById('authForm').requestSubmit()")
    landed = cdp.wait("location.pathname === '/'", timeout=10)
    check('creating an account goes to the Tracker', landed, cdp.ev('location.pathname'))
    check('where the welcome opens over it', cdp.wait("document.body.classList.contains('onboarding-open')", timeout=15)
          and is_open() is True, cdp.ev("document.body.className"))
    first = state()
    check('on its first step, Welcome, with only that step shown', first['current'] == 'welcome' and first['shown'] == ['welcome'], first)
    check('with the focus on its heading', first['focus'] == 'onboardingTitle-welcome', first['focus'])
    check('saying Step 1 of 6', first['count'] == 'Step 1 of 6', first['count'])
    check('with Get started and Skip, and no Back', first['nextText'] == 'Get started' and first['skip'] and not first['back']
          and t.text('onboardingSkip') == 'Skip', first)
    first_token = browser_token()
    first_before = settings()
    check('a new account has not been welcomed yet', first_before.get('welcomed') is False, first_before.get('welcomed'))

    # ------------------------------------------------------------------ O10 what a screen reader is told
    print('O10 it is a modal dialog, named by the heading of the step shown')
    check('role="dialog" and aria-modal="true"', cdp.ev("document.getElementById('onboarding').getAttribute('role')") == 'dialog'
          and cdp.ev("document.getElementById('onboarding').getAttribute('aria-modal')") == 'true')
    check('aria-labelledby is the heading of the step shown', first['labelledby'] == 'onboardingTitle-welcome' and first['labelledShown'] is True, first)
    check('every step has an h2 that can take the focus', cdp.ev("""[...document.querySelectorAll('#onboarding .onboarding-step')]
        .map(step => step.querySelector('h2') && step.querySelector('h2').getAttribute('tabindex'))""") == ['-1'] * 6)
    check('the steps are the contract\'s six, in order', cdp.ev("[...document.querySelectorAll('#onboarding .onboarding-step')].map(step => step.dataset.step)") == STEPS)
    check('and the progress is a polite live region', cdp.ev("document.getElementById('onboardingProgress').getAttribute('aria-live')") == 'polite'
          and cdp.ev("document.getElementById('onboardingProgress').contains(document.getElementById('onboardingCount'))") is True)
    check('the page behind does not scroll', cdp.ev('getComputedStyle(document.body).overflow') == 'hidden')

    # ------------------------------------------------------------------ O3 moving through the steps
    print('O3  Next and Back move through the six steps')
    visited = [(0, first)]
    for index in range(1, 6):
        t.click('onboardingNext')
        visited.append((index, state()))
    for index in range(4, -1, -1):
        t.click('onboardingBack')
        visited.append((index, state()))
    check('each press shows the step it should, and only that one', not differences(visited, ['current', 'shown']), differences(visited, ['current', 'shown']))
    check('the focus moves to the heading of each step', not differences(visited, ['focus']), differences(visited, ['focus']))
    check('the progress says Step N of 6 for each', not differences(visited, ['count']), differences(visited, ['count']))
    check('and its dots follow: those before done, this one current', not differences(visited, ['done', 'dots']), differences(visited, ['done', 'dots']))
    check('Back is hidden on step 1 only', not differences(visited, ['back']), differences(visited, ['back']))
    check('Skip and Next are on every step but the last, which has Start', not differences(visited, ['skip', 'next', 'start', 'nextText']),
          differences(visited, ['skip', 'next', 'start', 'nextText']))
    check('aria-labelledby follows the step shown', not differences(visited, ['labelledby', 'labelledShown']), differences(visited, ['labelledby', 'labelledShown']))
    go(5)
    cdp.ev("document.getElementById('onboardingStart').focus()")
    cdp.ev("document.getElementById('onboardingStart').dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))")
    wrapped = cdp.ev('document.activeElement.id')
    cdp.ev("document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }))")
    check('Tab from the last control goes round to the first, and Shift+Tab back, inside the welcome', wrapped == 'onboardingBack'
          and cdp.ev('document.activeElement.id') == 'onboardingStart', [wrapped, cdp.ev('document.activeElement.id')])

    # ------------------------------------------------------------------ O4 the choices
    print('O4  the choices: units, a way to train, a goal and days, and the Start button saying what it will do')
    go(1)
    check('units start from the settings: pounds and miles for a new account', picked('onboardingUnit') == ['lbs'] and picked('onboardingDistance') == ['mi'],
          [picked('onboardingUnit'), picked('onboardingDistance')])
    pick('onboardingUnit', 'kg')
    check('choosing kilograms moves distance to kilometres', picked('onboardingDistance') == ['km'], picked('onboardingDistance'))
    pick('onboardingUnit', 'lbs')
    check('and pounds back to miles', picked('onboardingDistance') == ['mi'], picked('onboardingDistance'))
    # Kilometres chosen with pounds, then kilograms and back to pounds: had the distance still followed, pounds would take it to miles.
    pick('onboardingDistance', 'km')
    pick('onboardingUnit', 'kg')
    pick('onboardingUnit', 'lbs')
    check('but once a distance is chosen, the weight unit leaves it alone', picked('onboardingUnit') == ['lbs'] and picked('onboardingDistance') == ['km'],
          [picked('onboardingUnit'), picked('onboardingDistance')])
    pick('onboardingUnit', 'kg')
    go(2)
    paths = cdp.ev("[...document.querySelectorAll('#onboarding input[name=onboardingPath]')].map(input => input.value)")
    check('the ways to train are the three programs, templates and logging as you go',
          paths == ['program:wendler-531', 'program:reddit-ppl', 'program:apartment-gym', 'templates', 'log'], paths)
    check('with templates chosen to start with', picked('onboardingPath') == ['templates'], picked('onboardingPath'))
    go(3)
    check('the weekly goal is 1 to 7, starting from the setting (3)', cdp.ev("[...document.getElementById('onboardingGoal').options].map(option => option.value)")
          == [str(n) for n in range(1, 8)] and t.field('onboardingGoal') == '3', t.field('onboardingGoal'))
    days = cdp.ev("[...document.querySelectorAll('#onboarding input[name=onboardingDay]')].map(input => input.value)")
    check('the training days are shown Monday first, Sunday as 0, none ticked', days == ['1', '2', '3', '4', '5', '6', '0'] and picked('onboardingDay') == [], days)
    labels = {}
    for path in paths:
        go(2)
        pick('onboardingPath', path)
        go(5)
        labels[path] = t.text('onboardingStart')
    names = {pid: cdp.ev(f"findProgramDefinition('{pid}').name") for pid in ['wendler-531', 'reddit-ppl', 'apartment-gym']}
    wanted = {**{f'program:{pid}': f'Set up {name}' for pid, name in names.items()}, 'templates': 'Choose a template', 'log': 'Go to the Tracker'}
    check("the Start button says what it will do for each way: Set up <program>, Choose a template, Go to the Tracker", labels == wanted, [labels, wanted])

    # ------------------------------------------------------------------ O6a Escape
    print('O6a Escape skips: it saves having been welcomed and nothing else')
    go(3)
    t.set_field('onboardingGoal', 6)
    pick('onboardingDay', 2)
    check('(the choices on screen differ from the settings before Escape)', picked('onboardingUnit') == ['kg'] and t.field('onboardingGoal') == '6')
    escape()
    after = settings()
    check('Escape closes the welcome', is_closed() is True)
    check('saving welcomed: true and changing nothing else', after == {**first_before, 'welcomed': True},
          {key: (first_before.get(key), after.get(key)) for key in set(first_before) | set(after) if first_before.get(key) != after.get(key)})
    check('the flag is gone from the tab', flag_gone(), flag())
    check('and the keyboard is left on the Tracker', cdp.ev('document.activeElement.id') in ('templatesToggle', 'settingsButton'), cdp.ev('document.activeElement.id'))
    check('the server has welcomed: true, and kept pounds', synced() and t.wait_for(lambda: server_settings(first_token).get('welcomed') is True)
          and server_settings(first_token).get('unit') != 'kg', server_settings(first_token))
    set_flag()
    reload_tracker()
    check('a reload, even with the flag set again, does not show it', is_closed() is True)

    # ------------------------------------------------------------------ O5 finishing, one way to train at a time
    print('O5  Start saves the choices and hands over to what was chosen')
    time_default = cdp.ev('scheduleFrom().time')
    cases = [
        ('a program', 'program:wendler-531', 'kg', None, 4, [1, 3, 5]),
        ('templates', 'templates', 'lbs', 'km', 2, []),
        ('logging as you go', 'log', 'kg', 'mi', 7, [0, 6]),
    ]
    tokens = {}
    for label, path, unit, distance, goal, chosen_days in cases:
        token = tokens[path] = account(f"finish{path.split(':')[-1].replace('-', '')}")
        check(f'[{label}] a new account sees the welcome', open_welcomed(token) is True)
        before = settings()
        check(f'[{label}] (the templates are folded first, to see what Start opens)', fold_templates())
        go(1)
        pick('onboardingUnit', unit)
        if distance:
            pick('onboardingDistance', distance)
        go(2)
        pick('onboardingPath', path)
        go(3)
        t.set_field('onboardingGoal', goal)
        for day in chosen_days:
            pick('onboardingDay', day)
        go(5)
        distance_unit = distance or ('km' if unit == 'kg' else 'mi')
        expected = {**before, 'unit': unit, 'distanceUnit': distance_unit, 'weeklyGoal': goal,
                    'schedule': {'days': sorted(chosen_days), 'time': time_default}, 'welcomed': True}
        t.click('onboardingStart')
        cdp.pause(0.4)
        after = settings()
        check(f'[{label}] Start saves exactly the units, goal, days and welcomed', after == expected,
              {key: (expected.get(key), after.get(key)) for key in set(expected) | set(after) if expected.get(key) != after.get(key)})
        check(f'[{label}] closes the welcome and removes the flag', is_closed() is True and flag_gone(), flag())
        # Once this device's copy is uploaded (offline.js marks it clean), what the server keeps.
        synced()
        t.wait_for(lambda: server_settings(token).get('welcomed') is True)
        # The server is sent the settings with the defaults filled in on both sides (accountStateFill), so a choice that is the
        # default (pounds, no days) is not a change and is not stored: it reads back as the default, as the page reads it.
        stored = {**cdp.ev('defaultSettings'), **server_settings(token)}
        check(f'[{label}] and the server has the same', {key: stored.get(key) for key in ('unit', 'distanceUnit', 'weeklyGoal', 'schedule', 'welcomed')}
              == {key: expected[key] for key in ('unit', 'distanceUnit', 'weeklyGoal', 'schedule', 'welcomed')}, stored)
        modal = cdp.ev("!document.getElementById('programModal').hidden")
        folded = cdp.ev("document.getElementById('templateArea').hidden")
        if path.startswith('program:'):
            name = cdp.ev(f"findProgramDefinition('{path[8:]}').name")
            check(f'[{label}] its own setup form opens, to ask for the starting weights', modal is True
                  and t.text('programModalTitle') == f'Start {name}', [modal, t.text('programModalTitle')])
            check(f'[{label}] with the focus in it, and the weights in the unit just chosen', cdp.ev("document.getElementById('programModal').contains(document.activeElement)") is True
                  and '(kg)' in cdp.ev("document.querySelector('#programMaxInputs label').textContent"), cdp.ev("document.querySelector('#programMaxInputs label').textContent"))
            check(f'[{label}] but the welcome made no program itself', cdp.ev('currentProgram === null') is True and server_state(token).get('program') is None,
                  [cdp.ev('currentProgram'), server_state(token).get('program')])
            t.click('cancelProgram')
            cdp.pause(0.2)
        elif path == 'templates':
            cdp.pause(0.8)  # a smooth scroll to the templates
            check(f'[{label}] the template list opens, and nothing else', folded is False and modal is False
                  and cdp.ev("document.getElementById('templatesToggle').getAttribute('aria-expanded')") == 'true', [folded, modal])
            check(f'[{label}] scrolled into view', cdp.ev("(box => box.top < innerHeight && box.bottom > 0)(document.getElementById('templateArea').closest('section').getBoundingClientRect())") is True)
        else:
            check(f'[{label}] nothing more opens: no program form, the templates still folded', modal is False and folded is True, [modal, folded])
            check(f'[{label}] and the keyboard is on the Tracker', cdp.ev('document.activeElement.id') in ('templatesToggle', 'settingsButton'), cdp.ev('document.activeElement.id'))

    # ------------------------------------------------------------------ O6b Skip
    print('O6b Skip saves having been welcomed and nothing else, and the account is not welcomed again')
    skipper = account('skipper')
    check('a new account sees the welcome', open_welcomed(skipper) is True)
    before = settings()
    go(1)
    pick('onboardingUnit', 'kg')
    go(3)
    t.set_field('onboardingGoal', 5)
    pick('onboardingDay', 4)
    t.click('onboardingSkip')
    cdp.pause(0.3)
    after = settings()
    check('Skip closes it and removes the flag', is_closed() is True and flag_gone(), flag())
    check('saving welcomed: true and changing nothing else', after == {**before, 'welcomed': True},
          {key: (before.get(key), after.get(key)) for key in set(before) | set(after) if before.get(key) != after.get(key)})
    check('the server has welcomed: true and none of the choices', synced() and t.wait_for(lambda: server_settings(skipper).get('welcomed') is True)
          and server_settings(skipper).get('unit') != 'kg' and server_settings(skipper).get('weeklyGoal') != 5, server_settings(skipper))
    reload_tracker()
    check('a reload does not show it', is_closed() is True)
    set_flag()
    reload_tracker()
    check('nor with the flag set again in the tab', is_closed() is True)
    # As another browser would be: nothing of the account kept here, only what the server says.
    cdp.ev("Object.keys(localStorage).filter(key => key.startsWith('workout-tracker-')).forEach(key => localStorage.removeItem(key))")
    set_flag()
    reload_tracker()
    check('nor with this device\'s copy gone, since the account itself has been welcomed', is_closed() is True
          and cdp.ev('getWorkoutSettings().welcomed') is True, cdp.ev('getWorkoutSettings().welcomed'))
    cdp.ev(f"sessionStorage.removeItem('{FLAG}')")

    # ------------------------------------------------------------------ O7 seeing it again
    print('O7  Settings shows it again, from the Tracker and from another page')
    program_token = tokens['program:wendler-531']
    t.set_cookie(program_token)
    t.open_tracker()
    settled()
    check('(an account already welcomed, with no flag, opens without it)', is_closed() is True)
    kept = settings()
    t.click('settingsButton')
    check('Settings has Show the welcome tour again', cdp.wait("!document.getElementById('settingsModal').hidden")
          and t.text('welcomeAgainButton') == 'Show the welcome tour again')
    t.click('welcomeAgainButton')
    cdp.pause(0.2)
    replay = state()
    check('which closes Settings and opens the welcome on its first step', cdp.ev("document.getElementById('settingsModal').hidden") is True and is_open() is True
          and replay['current'] == 'welcome' and replay['focus'] == 'onboardingTitle-welcome', replay)
    check('marked as a replay', cdp.ev("document.getElementById('onboarding').dataset.replay") == 'true')
    go(1)
    units = [picked('onboardingUnit'), picked('onboardingDistance')]
    go(2)
    path_now = picked('onboardingPath')
    go(3)
    week = [t.field('onboardingGoal'), picked('onboardingDay')]
    check('with the choices made since filled in: kilograms, kilometres, 4 a week, Monday, Wednesday and Friday',
          units == [['kg'], ['km']] and week == ['4', ['1', '3', '5']] and path_now == ['templates'], [units, week, path_now])
    escape()
    check('Escape closes it again, changing nothing', is_closed() is True and settings() == {**kept, 'welcomed': True}, settings())

    cdp.goto('/progress.html')
    cdp.wait("document.getElementById('settingsButton') && typeof openSettings === 'function'")
    cdp.pause(0.3)
    t.click('settingsButton')
    cdp.wait("!document.getElementById('settingsModal').hidden")
    t.click('welcomeAgainButton')
    went = cdp.wait("location.pathname === '/index.html' && document.readyState === 'complete'", timeout=10)
    settled()
    check('from Progress it goes to the Tracker and opens there', went and cdp.wait("document.body.classList.contains('onboarding-open')", timeout=8) and is_open() is True,
          cdp.ev('location.href'))
    check("taking 'welcome' off the address", cdp.ev('location.search') == '' and 'welcome' not in cdp.ev('location.href'), cdp.ev('location.href'))
    check('marked as a replay, on its first step, Settings closed', cdp.ev("document.getElementById('onboarding').dataset.replay") == 'true'
          and state()['current'] == 'welcome' and cdp.ev("!document.getElementById('settingsModal') || document.getElementById('settingsModal').hidden") is True)

    # ------------------------------------------------------------------ O9 how it fits and reads
    print('O9  it fits a phone, landscape and the largest Text size, and reads in every theme')
    check('it is above the header, tab bar and big view, with the feedback banner above it while open',
          cdp.ev("Number(getComputedStyle(document.getElementById('onboarding')).zIndex)") == 70
          and cdp.ev("Number(getComputedStyle(document.getElementById('formFeedback')).zIndex)") > 70, [
              cdp.ev("getComputedStyle(document.getElementById('onboarding')).zIndex"), cdp.ev("getComputedStyle(document.getElementById('formFeedback')).zIndex")])
    # The ready step's summary and the week's days are worth seeing chosen, so some are.
    for label, width, height, size in [('a phone upright (375x667)', 375, 667, 'normal'), ('a phone on its side (812x375)', 812, 375, 'normal'),
                                       ('a phone at the largest Text size', 375, 667, 'largest')]:
        cdp.send('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=True)
        cdp.ev(f"window.setTextSize('{size}')")
        cdp.pause(0.3)
        fits = []
        for index in range(6):
            go(index)
            cdp.pause(0.1)
            fits.append((STEPS[index], cdp.ev(FIT)))
        check(f'on {label}, nothing scrolls sideways, on any step', all(fit['page'] and fit['dialog'] and not fit['outside'] for _, fit in fits),
              [(step, fit) for step, fit in fits if not (fit['page'] and fit['dialog'] and not fit['outside'])])
        check(f'on {label}, every button, choice, day and the goal is 44px tall or more', all(fit['measured'] and not fit['small'] for _, fit in fits),
              [(step, fit['small']) for step, fit in fits if fit['small'] or not fit['measured']])
        check(f'on {label}, Next or Start is on screen on every step', all(fit['onward'] for _, fit in fits), [step for step, fit in fits if not fit['onward']])
    cdp.ev("window.setTextSize('normal')")
    cdp.send('Emulation.clearDeviceMetricsOverride')
    cdp.pause(0.2)

    cdp.ev(CONTRAST)
    themes = cdp.ev('window.colorThemes')
    low = {'dark': [], 'light': []}
    measured = 0
    for theme, kind in themes.items():
        cdp.ev(f"window.setColorTheme('{theme}')")
        for index in range(6):
            go(index)
            cdp.pause(0.05)
            result = cdp.ev('window.onboardingContrastCheck()')
            measured += result['measured']
            low[kind] += [(theme, STEPS[index], name, ratio) for name, ratio in result['low']]
    check(f"in the dark themes ({', '.join(theme for theme, kind in themes.items() if kind == 'dark')}) every piece of text is 4.5:1 or better",
          measured > 0 and not low['dark'], low['dark'][:12])
    check('and in the light themes too', not low['light'], low['light'][:12])
    cdp.ev("window.setColorTheme(getWorkoutSettings().theme)")
    escape()
    reload_tracker()
    check('a reload after a replay does not show it again', is_closed() is True)

    # ------------------------------------------------------------------ O2 signing in, and accounts made elsewhere
    print('O2  signing in, and an account made through the API, show no welcome')
    account('returning')
    cdp.goto('/login.html')
    cdp.pause(0.5)
    set_flag()  # as an account made in this tab and not yet welcomed would leave it
    cdp.ev(f"document.getElementById('username').value = 'returning'; document.getElementById('password').value = {json.dumps(PASSWORD)}")
    cdp.ev("document.getElementById('authForm').requestSubmit()")
    check('signing in to an account goes to the Tracker', cdp.wait("location.pathname === '/'", timeout=10), cdp.ev('location.pathname'))
    settled()
    check('with no welcome, though the account has never been welcomed', is_closed() is True and cdp.ev('getWorkoutSettings().welcomed') is False)
    check('signing in clears a flag left in the tab', flag_gone(), flag())
    t.set_cookie(t.token)
    t.open_tracker()
    settled()
    check('an account made through the API, opened on the Tracker, sees none', is_closed() is True
          and cdp.ev("document.getElementById('onboarding') === null") is True)

    # ------------------------------------------------------------------ O8 never over a workout
    print('O8  it never shows while a workout is under way')
    t.start(0)
    cdp.wait("!document.getElementById('activeWorkout').hidden")
    cdp.pause(0.4)
    set_flag()
    cdp.goto('/index.html')
    settled()
    check('with a workout in progress and the flag set, a reload shows the workout and no welcome',
          cdp.ev('Boolean(activeSession)') is True and is_closed() is True, [cdp.ev('Boolean(activeSession)'), is_closed()])
    check('needsOnboarding() says no while it is under way', cdp.ev('needsOnboarding()') is False)
    t.end_workout()
    cdp.wait("document.getElementById('activeWorkout').hidden")
    reload_tracker()
    check('once the workout is over, the same flag shows it: the workout was what kept it away',
          cdp.wait("document.body.classList.contains('onboarding-open')", timeout=8) and is_open() is True)
    t.click('onboardingSkip')
    cdp.pause(0.2)
    check('(and Skip puts it away)', is_closed() is True)
    t.set_cookie(t.token)
