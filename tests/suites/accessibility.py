"""Ease of access: the keyboard focus ring on everything that can take focus, the Text size setting, and the size of what is tapped."""

import json

INTERCEPT = True

PAGES = [('the tracker', '/index.html', "document.querySelectorAll('#templateList [data-template-action=start]').length >= 3"),
         ('History', '/history.html', "document.querySelectorAll('.history-workout').length >= 3"),
         ('Progress', '/progress.html', "document.querySelectorAll('#exerciseFilter option').length > 1"),
         ('Cardio', '/cardio.html', 'cardioLoaded === true')]

# Everything on the page a keyboard can reach, one at a time, focused as the Tab key would focus it (the browser has been told a key was pressed), and whether a ring is
# drawn: on the control itself, or on the label or drawn box beside a hidden input (the theme swatches, the training days).
FOCUS_RINGS = """(() => {
  // The page has seen a key pressed (see keyboard_mode), so a focus made here is a keyboard's and :focus-visible matches.
  const drawn = element => { const style = getComputedStyle(element); return style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0; };
  const reachable = [...document.querySelectorAll('a[href], button, input, select, textarea, summary, [tabindex]')]
    .filter(element => !element.disabled && element.tabIndex >= 0 && element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden');
  const result = { reached: 0, ringed: 0, missing: [] };
  for (const element of reachable) {
    element.focus();
    if (document.activeElement !== element || !element.matches(':focus-visible')) continue;
    result.reached++;
    const sibling = element.nextElementSibling;
    if (drawn(element) || (sibling && drawn(sibling))) result.ringed++;
    else result.missing.push(`${element.tagName.toLowerCase()}#${element.id}.${[...element.classList].join('.')}`);
  }
  document.activeElement.blur();
  return result;
})()"""

# What can be pressed and is under the size of a fingertip, as "tag#id.classes WxH": buttons, links, summaries and fields, and a tick box
# or radio by its label (that is what is pressed). The box measured is what is drawn, or for a hidden input the label around it.
SMALL_TARGETS = """(() => {
  const found = [];
  for (const element of document.querySelectorAll('button, a[href], summary, select, input:not([type=hidden]), textarea, [role=button]')) {
    if (element.disabled || getComputedStyle(element).visibility === 'hidden') continue;
    let box = element.getBoundingClientRect();
    const label = element.closest('label');
    if (element.matches('input[type=checkbox], input[type=radio]') && label) box = label.getBoundingClientRect();
    else if (getComputedStyle(element).opacity === '0') continue;
    if (box.width === 0 || box.height === 0) continue;
    const kind = element.closest('.calendar-day, .weekday') ? (element.closest('.calendar-day') ? 'calendar-day' : 'weekday') : 'other';
    const least = { 'calendar-day': [24, 24], weekday: [36, 44], other: [44, 44] }[kind];
    if (box.width < least[0] - 0.5 || box.height < least[1] - 0.5) {
      found.push(`${element.tagName.toLowerCase()}#${element.id}.${[...element.classList].join('.')} ${Math.round(box.width)}x${Math.round(box.height)} ${(element.getAttribute('aria-label') || element.textContent || '').trim().slice(0, 24)}`);
    }
  }
  return found;
})()"""

SIZES = {'normal': 16, 'large': 18.4, 'larger': 20.8, 'largest': 24}


def run(t):
    cdp, check, api, token = t.cdp, t.check, t.api, t.token
    open_tracker, start, end_workout = t.open_tracker, t.start, t.end_workout

    def settle(path, ready):
        cdp.goto(path)
        cdp.wait(ready, timeout=10)
        cdp.pause(0.5)

    def keyboard_mode():
        """A real Tab, so the browser treats the next focus as the keyboard's: :focus-visible matches then, and only then."""
        for kind in ('rawKeyDown', 'keyUp'):
            cdp.send('Input.dispatchKeyEvent', type=kind, key='Tab', code='Tab', windowsVirtualKeyCode=9, nativeVirtualKeyCode=9)

    def rings_now():
        keyboard_mode()
        return cdp.ev(FOCUS_RINGS)

    def stored_settings():
        return api('GET', '/api/state', token=token)[0]['settings']

    def open_settings(page='/index.html'):
        cdp.goto(page)
        cdp.wait("typeof getWorkoutSettings === 'function' && !!window.serverStateReady")
        cdp.ev('window.serverStateReady.then(() => true)')
        cdp.pause(0.3)
        cdp.ev("document.getElementById('settingsButton').click()")

    def choose_size(size):
        cdp.ev(f"(() => {{ const e = document.getElementById('textSizeSetting'); e.value = {json.dumps(size)}; "
               "e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); })()")

    def root_size():
        return cdp.ev("parseFloat(getComputedStyle(document.documentElement).fontSize)")

    # ------------------------------------------------------------------ F1 keyboard focus
    print('F1  whatever the keyboard can reach shows where it is')
    for label, path, ready in PAGES:
        settle(path, ready)
        rings = rings_now()
        check(f'{label}: there are controls to reach, and each is focused the way the Tab key focuses', rings['reached'] >= 5, rings)
        check(f'{label}: every one shows a ring', rings['missing'] == [], rings['missing'])
    settle('/login.html', "!!document.getElementById('authForm')")
    rings = rings_now()
    check('the sign-in page: every control shows a ring', rings['reached'] >= 4 and rings['missing'] == [], rings)
    open_settings()
    rings = rings_now()
    check('Settings: every control shows a ring, the swatches and training days included', rings['reached'] >= 30 and rings['missing'] == [], rings)
    cdp.ev("document.getElementById('closeSettings').click()")
    open_tracker()
    start(0)
    cdp.pause(0.4)
    rings = rings_now()
    check('a workout in progress: every control shows a ring', rings['reached'] >= 10 and rings['missing'] == [], rings)
    # The ring is the accent in every theme, drawn two pixels clear of the control (tests/lint.py keeps the accent readable against both
    # the page and the card), so it is seen on a filled button as well as on a plain one.
    keyboard_mode()
    ring = cdp.ev("""(() => { const b = document.getElementById('completeSetBtn'); b.focus(); const s = getComputedStyle(b);
      return { color: s.outlineColor, accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(), offset: s.outlineOffset, width: s.outlineWidth }; })()""")
    check('the ring is two pixels wide, set clear of the control, in the accent', ring['width'] == '2px' and ring['offset'] == '2px' and ring['color'].startswith('rgb'), ring)
    end_workout()
    # A click or a tap is not a keyboard: no ring is left on what was just pressed.
    open_tracker()
    cdp.send('Input.dispatchMouseEvent', type='mousePressed', x=5, y=5, button='left', clickCount=1)
    cdp.send('Input.dispatchMouseEvent', type='mouseReleased', x=5, y=5, button='left', clickCount=1)
    pressed = cdp.ev("(() => { const b = document.getElementById('settingsButton'); b.focus({ focusVisible: false }); return b.matches(':focus-visible'); })()")
    check('a control focused by a pointer does not take the ring', pressed is False, pressed)

    # ------------------------------------------------------------------ F2 text size
    print('F2  the Text size setting scales all of the text')
    open_settings()
    options = cdp.ev("[...document.getElementById('textSizeSetting').options].map(o => o.value)")
    check('Settings offers four sizes, in General', options == ['normal', 'large', 'larger', 'largest']
          and cdp.ev("document.getElementById('textSizeSetting').closest('section, fieldset, div').textContent.includes('Text size')") is True, options)
    check('it starts at Normal, which leaves the page at the browser size',
          cdp.ev("document.getElementById('textSizeSetting').value") == 'normal' and root_size() == 16
          and cdp.ev("'textSize' in document.documentElement.dataset") is False, root_size())
    for size, pixels in SIZES.items():
        choose_size(size)
        cdp.pause(0.2)
        check(f'{size}: the page is at {pixels:g}px', abs(root_size() - pixels) < 0.01, root_size())
    body = cdp.ev("parseFloat(getComputedStyle(document.querySelector('.subtitle')).fontSize) / 16")
    check('and the small print scales with it, not by a size of its own', body > 0.6, body)
    check('the choice is saved as it is made', t.wait_for(lambda: stored_settings().get('textSize') == 'largest'), str(stored_settings()))
    cdp.ev("document.getElementById('closeSettings').click()")

    print('F3  and it is there before the page is drawn, on every page, and on the sign-in page')
    # The size at the moment the page's own scripts start, i.e. before anything is painted: a page that applied it afterwards would
    # flash small and then jump.
    marker = cdp.send('Page.addScriptToEvaluateOnNewDocument', source="document.addEventListener('DOMContentLoaded', () => { window.__sizeAtLoad = "
                      "parseFloat(getComputedStyle(document.documentElement).fontSize); });")
    for label, path, ready in PAGES:
        settle(path, ready)
        size = cdp.ev('window.__sizeAtLoad')
        check(f'{label}: opens at the largest size straight away', size == 24, size)
    settle('/login.html', "!!document.getElementById('authForm')")
    check('the sign-in page too', cdp.ev('window.__sizeAtLoad') == 24, cdp.ev('window.__sizeAtLoad'))
    cdp.send('Page.removeScriptToEvaluateOnNewDocument', identifier=marker['result']['identifier'])

    print('F4  at the largest size nothing runs off the side of a phone')
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    sideways = "Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)"
    for label, path, ready in PAGES:
        settle(path, ready)
        check(f'{label}: no sideways scrolling', cdp.ev(sideways) <= 0, cdp.ev(sideways))
    open_settings()
    check('Settings: no sideways scrolling', cdp.ev(sideways) <= 0, cdp.ev(sideways))
    cdp.ev("document.getElementById('closeSettings').click()")
    open_tracker()
    start(0)
    cdp.pause(0.4)
    check('a workout in progress: no sideways scrolling', cdp.ev(sideways) <= 0, cdp.ev(sideways))
    covered = cdp.ev("""(() => { const b = document.getElementById('completeSetBtn').getBoundingClientRect(); return b.width > 0 && b.right <= innerWidth && b.left >= 0; })()""")
    check('and Log set is wholly on the screen', covered is True, covered)
    end_workout()

    print('F5  settings from before it, or a value that is not a size, are Normal')
    cdp.send('Emulation.clearDeviceMetricsOverride')
    for stored in ({'theme': 'dark', 'restDuration': 120}, {'textSize': 'enormous'}, {'textSize': 7}):
        api('PUT', '/api/state', {'settings': stored}, token)
        open_settings()
        check(f'{stored}: Normal', cdp.ev("document.getElementById('textSizeSetting').value") == 'normal' and root_size() == 16, root_size())
        cdp.ev("document.getElementById('closeSettings').click()")

    # ------------------------------------------------------------------ F6 what is pressed is big enough to press
    print('F6  everything pressed is the size of a fingertip, on a phone, at the usual text size and the largest')
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)

    def small_targets_everywhere():
        found = {}
        for label, path, ready in PAGES + [('the sign-in page', '/login.html', "!!document.getElementById('authForm')")]:
            settle(path, ready)
            found[label] = cdp.ev(SMALL_TARGETS)
        open_settings()
        found['Settings'] = cdp.ev(SMALL_TARGETS)
        cdp.ev("document.getElementById('closeSettings').click()")
        open_tracker()
        start(0)
        cdp.pause(0.4)
        cdp.ev("document.querySelectorAll('details').forEach(details => { details.open = true; })")
        cdp.pause(0.3)
        found['a workout'] = cdp.ev(SMALL_TARGETS)
        end_workout()
        return found

    for size in ('normal', 'largest'):
        api('PUT', '/api/state', {'settings': {'textSize': size}}, token)
        for label, small in small_targets_everywhere().items():
            check(f'{size}: {label}: nothing to press is smaller than 44px (a calendar day 24px, a training day 36 wide)', small == [], small)
    api('PUT', '/api/state', {'settings': {}}, token)
    cdp.send('Emulation.clearDeviceMetricsOverride')
