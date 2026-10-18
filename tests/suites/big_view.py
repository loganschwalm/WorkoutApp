"""The big view: the set to do and the rest clock in very large type, a mirror of the workout on the Tracker."""

INTERCEPT = False

# A Reddit PPL with its first day done, so the next workout is Push (Bench), whose sets are planned.
PPL = {'definition': 'reddit-ppl', 'startedAt': 1000, 'cycle': 1, 'lastRollover': None,
       'trainingMaxes': {'deadlift': 225, 'row': 115, 'bench': 135, 'press': 85, 'squat': 185}, 'options': {'rounding': 5},
       'done': {'0-0': {'at': 2000, 'skipped': False, 'amrap': None, 'hit': None}}}

# WCAG's contrast ratio of two rgb() strings the browser gives for a colour.
CONTRAST = """((a, b) => {
  const channels = value => value.match(/[\\d.]+/g).slice(0, 3).map(Number);
  const luminance = rgb => { const [r, g, b] = rgb.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const [x, y] = [luminance(channels(a)), luminance(channels(b))];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
})"""


def run(t):
    cdp, check, api, token = t.cdp, t.check, t.api, t.token
    text, field = t.text, t.field

    def view_open():
        return cdp.ev("!document.getElementById('bigView').hidden")

    def open_view():
        cdp.ev("document.getElementById('bigViewBtn').click()")
        cdp.pause(0.4)

    def state():
        return cdp.ev("""({ exercise: document.getElementById('bigViewExercise').textContent, progress: document.getElementById('bigViewProgress').textContent,
          label: document.getElementById('bigViewLabel').hidden ? '' : document.getElementById('bigViewLabel').textContent,
          clock: document.getElementById('bigViewClock').hidden ? '' : document.getElementById('bigViewClock').textContent,
          set: document.getElementById('bigViewSet').textContent,
          numbers: document.getElementById('bigViewNumbers').hidden ? '' : document.getElementById('bigViewNumbers').textContent,
          primary: document.getElementById('bigViewPrimary').textContent, rest: !document.getElementById('bigViewRest').hidden,
          toggle: document.getElementById('bigViewToggle').textContent, go: document.getElementById('bigView').classList.contains('go') })""")

    def seconds(clock):
        minutes, rest = clock.split(':')
        return int(minutes) * 60 + int(rest)

    def clocks_agree(shown, page):
        """The view and the page tick on timers of their own, so their clocks may be a second apart."""
        return bool(shown) and abs(seconds(shown) - seconds(page)) <= 1

    def press(idn):
        cdp.ev(f"document.getElementById('{idn}').click()")
        cdp.pause(0.4)

    # ------------------------------------------------------------------ B1 a template workout: no plan, so just "Set N"
    print('B1  the big view of a workout: the set to do, and the rest clock after it')
    t.open_tracker()
    t.start(0)
    cdp.pause(0.4)
    check('there is a button for it in the workout', cdp.ev("!document.getElementById('bigViewBtn').closest('#activeWorkout').hidden") is True)
    check('and the view is closed to start with', view_open() is False)
    open_view()
    first = state()
    check('it opens as a dialog, with the focus on its big button', view_open() is True
          and cdp.ev("document.getElementById('bigView').getAttribute('role') + document.getElementById('bigView').getAttribute('aria-modal')") == 'dialogtrue'
          and cdp.ev("document.activeElement.id") == 'bigViewPrimary', cdp.ev("document.activeElement.id"))
    check('it names the exercise and where the workout is', first['exercise'] == text('activeExerciseName') and first['progress'] == f"{text('activeWorkoutProgress')} · {text('activeWorkoutTitle')}", first)
    check("it shows the set the entry fields hold, which is what Complete set logs: last time's, for a template",
          first['set'] == 'Set 1' and first['numbers'] == f"{field('activeWeight')} lbs × {field('completedReps')}" and first['numbers'].endswith('× 8'), first)
    check('with no rest to show, only the big button', first['label'] == '' and first['clock'] == '' and first['rest'] is False and first['primary'] == 'Complete set', first)
    sets_before = cdp.ev('activeSession.exercises[0].sets.length')
    press('bigViewPrimary')
    after = state()
    check('its big button logs the set, through the page', cdp.ev('activeSession.exercises[0].sets.length') == sets_before + 1)
    check('and the view turns to the rest, on the page\'s own clock', after['label'] == 'Rest' and clocks_agree(after['clock'], text('timerDisplay')) and after['rest'] is True, after)
    check('with the next set under it', after['set'] == 'Next: Set 2' and after['numbers'] != '', after)
    cdp.pause(1.3)
    check('and the clock runs', clocks_agree(state()['clock'], text('timerDisplay')) and state()['clock'] != after['clock'], [after['clock'], state()['clock']])

    # The rest's own controls are the page's.
    left = cdp.ev('restRemaining')
    cdp.ev("document.querySelector('#bigViewRest [data-big-rest=\"30\"]').click()")
    cdp.pause(0.4)
    check('+30s moves the page\'s timer', cdp.ev('restRemaining') >= left + 28, [left, cdp.ev('restRemaining')])
    cdp.ev("document.getElementById('bigViewToggle').click()")
    cdp.pause(0.4)
    check('Pause stops it, and the view says so and offers Start', cdp.ev('restInterval') is None and state()['label'] == 'Rest · paused' and state()['toggle'] == 'Start rest', state())
    cdp.ev("document.getElementById('bigViewToggle').focus()")
    cdp.pause(0.8)
    check('the focus stays where it was put while the view updates', cdp.ev('document.activeElement.id') == 'bigViewToggle', cdp.ev('document.activeElement.id'))
    cdp.ev("document.getElementById('bigViewSkip').click()")
    cdp.pause(0.4)
    over = state()
    check('Skip rest ends it, and the view goes to "go": the rest is over and the next set is waiting',
          cdp.ev('restRemaining') == 0 and over['label'] == 'Rest over' and over['go'] is True and over['clock'] == '' and over['rest'] is False
          and over['set'] == 'Set 2', over)
    check('which says nothing aloud, the rest having been ended by hand', cdp.ev("document.getElementById('bigViewAnnouncement').textContent + document.getElementById('restAnnouncement').textContent") == '')
    # A rest that runs out while the view is open is told in the view, since the page behind a modal dialog is not read.
    cdp.ev("startRestTimer(); restEndsAt = Date.now() + 400")
    cdp.pause(1.0)
    said = cdp.ev("[document.getElementById('bigViewAnnouncement').textContent, document.getElementById('restAnnouncement').textContent]")
    check('a rest that runs out with the view open is announced inside it, and not twice', said == ['Rest over', ''], said)

    # What it looks like.
    colours = cdp.ev(f"""(() => {{ const contrast = {CONTRAST}; const style = id => getComputedStyle(document.getElementById(id));
      const on = id => contrast(style(id).color, style(id).backgroundColor === 'rgba(0, 0, 0, 0)' ? 'rgb(0, 0, 0)' : style(id).backgroundColor);
      return ['bigViewExercise', 'bigViewProgress', 'bigViewLabel', 'bigViewSet', 'bigViewNumbers', 'bigViewPrimary', 'bigViewClose'].map(id => [id, on(id)]); }})()""")
    check('every piece of text is 7:1 or better against what it sits on, the "go" green too', all(ratio >= 7 for _, ratio in colours), colours)
    check('it is above the tab bar and the page, and under the banner that says what went wrong',
          cdp.ev("Number(getComputedStyle(document.getElementById('bigView')).zIndex)") > 9
          and cdp.ev("Number(getComputedStyle(document.getElementById('formFeedback')).zIndex)") > cdp.ev("Number(getComputedStyle(document.getElementById('bigView')).zIndex)"))
    check('and the page behind does not scroll', cdp.ev("getComputedStyle(document.body).overflow") == 'hidden')
    size = cdp.ev("parseFloat(getComputedStyle(document.getElementById('bigViewNumbers')).fontSize)")
    check('the numbers are big', size >= 38, size)

    for label, width, height, mobile in [('a phone upright', 375, 667, True), ('a phone on its side', 812, 375, True), ('a laptop', 1280, 800, False)]:
        cdp.send('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=mobile)
        cdp.pause(0.3)
        fit = cdp.ev("""(view => ({ across: view.scrollWidth <= view.clientWidth, page: document.documentElement.scrollWidth <= innerWidth,
          button: document.getElementById('bigViewPrimary').getBoundingClientRect().bottom <= innerHeight + 1 }))(document.getElementById('bigView'))""")
        check(f'on {label} it does not scroll across, and its big button is on screen', fit == {'across': True, 'page': True, 'button': True}, fit)
    press('bigViewSkip')
    cdp.ev("saveLocalState('settings', { ...getWorkoutSettings(), textSize: 'largest' }); window.dispatchEvent(new Event('settingschange'))")
    cdp.pause(0.4)
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=667, deviceScaleFactor=1, mobile=True)
    cdp.pause(0.3)
    fit = cdp.ev("""(view => ({ across: view.scrollWidth <= view.clientWidth, page: document.documentElement.scrollWidth <= innerWidth }))(document.getElementById('bigView'))""")
    check('at the largest Text size on a phone, nothing runs off the side', fit == {'across': True, 'page': True}, fit)
    cdp.ev("saveLocalState('settings', { ...getWorkoutSettings(), textSize: 'normal' }); window.dispatchEvent(new Event('settingschange'))")
    cdp.send('Emulation.clearDeviceMetricsOverride')

    # Getting out.
    cdp.ev("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))")
    cdp.pause(0.3)
    check('Escape closes it and the focus goes back to its button', view_open() is False and cdp.ev('document.activeElement.id') == 'bigViewBtn'
          and cdp.ev("document.body.classList.contains('big-view-open')") is False, cdp.ev('document.activeElement.id'))
    open_view()
    cdp.ev("document.getElementById('bigViewClose').click()")
    check('so does its close button', view_open() is False)

    # A set the page will not take is the page's to say, with its field in reach.
    open_view()
    cdp.ev("document.getElementById('completedReps').value = ''")
    cdp.pause(0.4)
    check('with no reps to log, the numbers are not made up', state()['numbers'] == '', state())
    press('bigViewPrimary')
    check('its big button gets out of the way, so the page can say what is wrong', view_open() is False
          and 'reps' in text('formFeedback').lower() and cdp.ev("document.activeElement.id") == 'completedReps', [text('formFeedback'), cdp.ev('document.activeElement.id')])

    # The workout going away takes it with it.
    open_view()
    t.end_workout()
    cdp.pause(0.5)
    check('cancelling the workout closes it', view_open() is False and cdp.ev("document.getElementById('activeWorkout').hidden") is True)

    # ------------------------------------------------------------------ B2 a program's planned sets
    print('B2  a planned workout counts its sets, goes to the next exercise and finishes')
    api('PUT', '/api/state', {'program': PPL}, token)
    t.open_tracker()
    cdp.ev("document.querySelector('#programNext [data-program-action=start]').click()")
    cdp.wait("!document.getElementById('activeWorkout').hidden")
    cdp.pause(0.4)
    planned = cdp.ev('activeSession.exercises[0].plan.length')
    open_view()
    check('the set says how many are planned', state()['set'] == f'Set 1 of {planned}' and state()['primary'] == 'Complete set', state())
    counted = []
    for _ in range(planned - 1):
        press('bigViewPrimary')
        counted.append(state()['set'])
    check('each set logged moves it on, as the rest begins', counted == [f'Next: Set {n} of {planned}' for n in range(2, planned + 1)], counted)
    press('bigViewPrimary')
    done = state()
    check('after the last planned set it says so, and its big button is the page\'s Next', done['set'] == 'All sets done'
          and done['primary'] == text('nextExerciseBtn') == 'Next exercise' and done['numbers'] == '', done)
    first_name = done['exercise']
    press('bigViewPrimary')
    check('which moves on, with the view still open on the next exercise', view_open() is True and state()['exercise'] != first_name
          and state()['set'].startswith('Set 1 of '), state())
    cdp.ev("""(() => { const index = activeSession.exercises.length - 1; goToExercise(index);
      const last = activeSession.exercises[index]; last.sets = last.plan.map(set => ({ weight: Number(set.weight) || 0, reps: Number(set.reps) || 5 }));
      renderActiveWorkout(); })()""")
    cdp.pause(0.5)
    check('on the last exercise its big button finishes the workout', state()['primary'] == 'Finish workout', state())
    press('bigViewPrimary')
    cdp.wait("!document.getElementById('workoutSummary').hidden", timeout=10)
    check('and the view is closed, so the summary is there to see', view_open() is False and cdp.ev("document.getElementById('activeWorkout').hidden") is True)

    # ------------------------------------------------------------------ B3 a timed exercise
    print('B3  a timed exercise: the hold clock, and the big button starts and stops it')
    t.open_tracker()
    t.start(0)
    cdp.pause(0.4)
    cdp.ev("""(() => { activeSession.exercises[0].timed = true; activeSession.exercises[0].reps = 30; renderActiveWorkout(); })()""")
    cdp.ev("document.getElementById('completedReps').value = '30'")
    open_view()
    ready = state()
    check('a timed exercise is shown in seconds, with Start timer as its big button', ready['numbers'] == '30 s' and ready['primary'] == 'Start timer', ready)
    press('bigViewPrimary')
    cdp.pause(0.6)
    held = state()
    check('it starts the hold, and the view shows its clock, as the page does', held['label'] == 'Hold' and clocks_agree(held['clock'], text('holdDisplay'))
          and held['primary'] == 'Stop' and held['numbers'] == '', held)
    press('bigViewPrimary')
    check('and the same button stops it', state()['label'] == '' and state()['primary'] == 'Start timer' and cdp.ev('holdInterval') is None, state())
    t.end_workout()

    # ------------------------------------------------------------------ B4 the setting that opens it
    print('B4  Settings can open the big view by itself when a rest starts')
    t.open_tracker()
    t.start(0)
    cdp.pause(0.4)
    check('it is a setting, off to start with', cdp.ev('getWorkoutSettings().bigViewOnRest') is False)
    cdp.ev("document.getElementById('completedReps').value = '8'; document.getElementById('completeSetBtn').click()")
    cdp.pause(0.5)
    check('and a set logged on the page does not open it', view_open() is False)
    cdp.ev("saveLocalState('settings', { ...getWorkoutSettings(), bigViewOnRest: true }); window.dispatchEvent(new Event('settingschange'))")
    cdp.ev("document.getElementById('completeSetBtn').click()")
    cdp.pause(0.5)
    opened = state()
    check('turned on, a set logged opens it, on the rest', view_open() is True and opened['label'] == 'Rest' and opened['rest'] is True, opened)
    check('with the focus on its big button, so the next set is a tap', cdp.ev('document.activeElement.id') == 'bigViewPrimary')
    cdp.ev("document.getElementById('bigViewClose').click()")
    cdp.pause(0.6)
    check('closed by hand, it stays closed while the rest goes on', view_open() is False)
    cdp.ev("document.getElementById('completeSetBtn').click()")
    cdp.pause(0.5)
    check('and opens again with the next set', view_open() is True)
    press('bigViewPrimary')
    check('a set logged from inside it leaves it open, on the next rest', view_open() is True and state()['label'] == 'Rest', state())
    cdp.ev("saveLocalState('settings', { ...getWorkoutSettings(), bigViewOnRest: false }); window.dispatchEvent(new Event('settingschange'))")
    t.end_workout()
