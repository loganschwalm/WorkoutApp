"""Training programs: setting up Wendler 5/3/1, its planned sets and weights, moving through a cycle, the next
cycle's training maxes (and a reset after a missed + set), editing and ending it, and keeping it through a network drop."""

import json
import math
import time

from ..harness import ACTIVE, HIDDEN, TITLE

INTERCEPT = True

# The two program cards in the templates list.
WENDLER = '#templateList .program-template[data-program-id="wendler-531"]'
PPL = '#templateList .program-template[data-program-id="reddit-ppl"]'

# Collects every CSP violation on each page from the moment it starts loading.
RECORD_VIOLATIONS = """window.__csp = [];
document.addEventListener('securitypolicyviolation', e => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));"""


def run(t):
    cdp, check, api, token, wait_for = t.cdp, t.check, t.api, t.token, t.wait_for
    open_tracker, safe_ev = t.open_tracker, t.safe_ev
    cdp.send('Page.addScriptToEvaluateOnNewDocument', source=RECORD_VIOLATIONS)

    def text(idn):
        return cdp.ev(f"document.getElementById('{idn}').textContent")

    def visible(idn):
        return cdp.ev(f"!document.getElementById('{idn}').hidden")

    def field(idn):
        return cdp.ev(f"document.getElementById('{idn}').value")

    def set_field(idn, value):
        cdp.ev(f"(() => {{ const e = document.getElementById('{idn}'); e.value = {json.dumps(str(value))}; e.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")

    def click(selector):
        cdp.ev(f"document.querySelector({json.dumps(selector)}).click()")
        cdp.pause(0.2)

    def server_program():
        return api('GET', '/api/state', token=token)[0].get('program')

    def program():
        return cdp.ev('currentProgram')

    def chips():
        return cdp.ev("[...document.querySelectorAll('#activePlan li')].map(li => [li.textContent, li.className])") or []

    def week_rows(week):
        return cdp.ev(f"[...document.querySelectorAll('.program-week')[{week}].querySelectorAll('.program-day')].map(li => li.textContent)") or []

    def complete_set(reps=None):
        if reps is not None:
            cdp.ev(f"document.getElementById('completedReps').value = '{reps}'")
        cdp.ev("document.getElementById('completeSetBtn').click()")
        cdp.pause(0.15)

    def finish_workout():
        for _ in range(8):
            if cdp.ev(HIDDEN):
                break
            cdp.ev("document.getElementById('nextExerciseBtn').click()")
            cdp.pause(0.25)
        cdp.pause(0.8)

    def skip_next():
        click('#programNext [data-program-action=skip]')

    def violations():
        return cdp.ev('window.__csp') or []

    # ------------------------------------------------------------------ P1 offered with the templates
    print('P1  Wendler 5/3/1 is offered with the templates')
    open_tracker()
    check('a Wendler 5/3/1 card is listed', cdp.ev("document.querySelector('#templateList .program-template h3')?.textContent") == 'Wendler 5/3/1')
    check('offering to set it up', cdp.ev("!!document.querySelector('#templateList [data-program-action=setup]')") is True)
    first = cdp.ev("document.querySelector('#templateList [data-template-action=start]').closest('.template-card').querySelector('h3').textContent")
    check('the single-workout templates keep their order', first == 'Push Day', first)
    check('no program card until one is started', visible('programCard') is False)

    # ------------------------------------------------------------------ P2 setting it up
    print('P2  setting it up')
    cdp.wait("document.querySelectorAll('#savedWorkoutList .saved-workout').length >= 3")
    click('#templateList [data-program-action=setup]')
    check('the setup dialog opens', visible('programModal') and text('programModalTitle') == 'Start Wendler 5/3/1', text('programModalTitle'))
    check('asking for one-rep maxes', field('programMaxKind') == '1rm')
    prefilled = {lift: field(f'programMax-{lift}') for lift in ('press', 'deadlift', 'bench', 'squat')}
    check('logged lifts are estimated from their latest sets (105 x 8 and 62 x 8)',
          prefilled == {'press': '79', 'deadlift': '', 'bench': '133', 'squat': ''}, prefilled)
    check('and say what training max that gives', text('programHint-bench') == 'Training max 120 lbs', text('programHint-bench'))
    set_field('programTmPercent', 85)
    check('the hint follows the training-max percentage', text('programHint-bench') == 'Training max 115 lbs', text('programHint-bench'))
    set_field('programTmPercent', 90)
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.3)
    check('a missing lift is refused with a reason', visible('programFormError') and 'every lift' in text('programFormError'), text('programFormError'))
    check('and marked', cdp.ev("document.getElementById('programMax-deadlift').getAttribute('aria-invalid')") == 'true')
    check('nothing is started', visible('programModal') and cdp.ev('currentProgram') is None)
    set_field('programMaxKind', 'tm')
    for lift, value in (('press', 100), ('deadlift', 300), ('bench', 200), ('squat', 250)):
        set_field(f'programMax-{lift}', value)
    check('training maxes are taken as they are', text('programHint-bench') == 'Heaviest set 190 lbs', text('programHint-bench'))
    check('Boring But Big is the default assistance, described', field('programAssistance') == 'bbb' and '50%' in text('programAssistanceHelp'), text('programAssistanceHelp'))
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.5)
    check('the dialog closes', visible('programModal') is False)
    check('the program card appears', visible('programCard') and text('programTitle') == 'Wendler 5/3/1')
    summary = text('programSummary')
    check('at the start of cycle 1', 'Cycle 1' in summary and '0 of 16 workouts done' in summary and 'week 1 of 4, 5s week' in summary, summary)
    check('the user is told what comes first', 'Press Day, week 1' in text('formFeedback'), text('formFeedback'))
    check('its template card now leads to it', cdp.ev(f"!!document.querySelector('{WENDLER} [data-program-action=view]') && !document.querySelector('{WENDLER} [data-program-action=setup]')") is True)
    check('the program reaches the server', wait_for(lambda: (server_program() or {}).get('trainingMaxes', {}).get('bench') == 200), server_program())

    # ------------------------------------------------------------------ P3 the planned cycle
    print('P3  the whole cycle is planned out')
    maxes = cdp.ev("[...document.querySelectorAll('#programMaxes li')].map(li => li.textContent)")
    check('each training max is shown with next cycle’s',
          maxes == ['Overhead Press100 lbsNext cycle: 105', 'Deadlift300 lbsNext cycle: 310', 'Bench Press200 lbsNext cycle: 205', 'Back Squat250 lbsNext cycle: 260'], maxes)
    check('four weeks, the current one open', cdp.ev("[...document.querySelectorAll('.program-week')].map(d => d.open)") == [True, False, False, False])
    rows = week_rows(2)
    check('week 3 works up to 95% (bench 150 x 5, 170 x 3, 190 x 1+)', len(rows) == 4 and 'Bench Press 150 × 5 · 170 × 3 · 190 × 1+' in rows[2], rows)
    rows = week_rows(3)
    check('the deload week is light and has no + set', 'Back Squat 100 × 5 · 125 × 5 · 150 × 5' in rows[3], rows)
    check('and is the main lift only', 'main lift only' in cdp.ev("document.querySelectorAll('.program-week summary')[3].textContent"))
    lines = cdp.ev("[...document.querySelectorAll('#programNext li')].map(li => li.textContent)")
    check('the next workout lists its sets',
          lines == ['Overhead Press 65 × 5 · 75 × 5 · 85 × 5+', 'Overhead Press (BBB) 5 × 10 at 50 lbs', 'Chin-up 5 × 10'], lines)
    check('nothing breaks the Content-Security-Policy', violations() == [], violations())

    # ------------------------------------------------------------------ P4 a planned workout
    print('P4  doing a planned workout')
    known = t.ids()
    click('#programNext [data-program-action=start]')
    check('it starts as the day’s workout', cdp.ev(ACTIVE) and cdp.ev(TITLE) == '5/3/1 Press Day' and text('activeExerciseName') == 'Overhead Press', cdp.ev(TITLE))
    check('with every set planned, warm-ups first',
          [c[0] for c in chips()] == ['40 lbs × 5', '50 lbs × 5', '60 lbs × 3', '65 lbs × 5', '75 lbs × 5', '85 lbs × 5+'], chips())
    check('the first set is the current one', chips()[0][1] == 'current' and chips()[1][1] == 'upcoming', chips())
    check('the target says what to do', text('activeExerciseTarget') == 'Set 1 of 6, warm-up: 40 lbs × 5 (40% of your training max).', text('activeExerciseTarget'))
    check('and its weight and reps are filled in, not last time’s', field('activeWeight') == '40' and field('completedReps') == '5', f"{field('activeWeight')} x {field('completedReps')}")
    for _ in range(3):
        complete_set()
    check('logging moves on to the next planned set', field('activeWeight') == '65' and field('completedReps') == '5', f"{field('activeWeight')} x {field('completedReps')}")
    check('and ticks off the ones done', [c[1] for c in chips()] == ['done', 'done', 'done', 'current', 'upcoming', 'upcoming'], chips())
    complete_set()
    complete_set()
    check('the last set asks for as many reps as possible',
          text('activeExerciseTarget') == 'Set 6 of 6: 85 lbs × 5+ (85% of your training max). As many reps as you can.', text('activeExerciseTarget'))
    complete_set(9)
    target = text('activeExerciseTarget')
    # Epley, rounded as Math.round does: 85 x (1 + 9/30).
    estimate = math.floor(85 * (1 + 9 / 30) + 0.5)
    check('the + set is read as a one-rep max', 'All 6 planned sets done.' in target and '85 lbs × 9' in target and f'near {estimate} lbs' in target, target)
    check('an extra set defaults to the one just logged', field('activeWeight') == '85' and field('completedReps') == '9')
    cdp.pause(0.8)
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    cdp.wait(ACTIVE)
    cdp.pause(0.6)
    check('the plan survives a reload', [c[1] for c in chips()] == ['done'] * 6, chips())
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    check('Boring But Big follows at 50%', text('activeExerciseName') == 'Overhead Press (BBB)' and [c[0] for c in chips()] == ['50 lbs × 10'] * 5, f"{text('activeExerciseName')} {chips()}")
    complete_set()
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    check('an assistance exercise leaves the weight to you', text('activeExerciseName') == 'Chin-up' and [c[0] for c in chips()] == ['10 reps'] * 5 and field('activeWeight') == '', f"{chips()} '{field('activeWeight')}'")
    complete_set(8)
    finish_workout()
    check('the workout is saved', wait_for(lambda: len(t.ids() - known) == 1), '')
    saved = next((w for w in t.workouts() if w['id'] not in known), {})
    check('under the day’s name, with where it was in the program',
          saved.get('name') == '5/3/1 Press Day' and (saved.get('program') or {}).get('label') == 'Cycle 1, week 1 · 5s week', json.dumps({k: saved.get(k) for k in ('name', 'program')}))
    check('with every set logged', [len(e['sets']) for e in saved.get('exercises', [])] == [6, 1, 1], json.dumps(saved.get('exercises')))
    check('the user is told what is next', 'Next in Wendler 5/3/1: Deadlift Day, week 1.' in text('formFeedback'), text('formFeedback'))
    done = (program() or {}).get('done', {})
    check('the day is marked done with its + set', done.get('0-0', {}).get('amrap') == {'weight': 85, 'reps': 9, 'target': 5}, done)
    check('the card shows it', 'Done · + set 85 × 9' in week_rows(0)[0] and '1 of 16 workouts done' in text('programSummary'), week_rows(0))
    check('and the next workout is Deadlift Day', 'Deadlift Day' in text('programNext'), text('programNext'))
    check('the saved list says where it came from', cdp.wait("document.getElementById('savedWorkoutList').textContent.includes('Cycle 1, week 1 · 5s week')"))
    cdp.ev("document.querySelector('#savedWorkoutList .saved-workout [data-action=start]').click()")
    cdp.pause(0.3)
    check('starting the saved workout again is not a day of the program',
          cdp.ev("activeSession.name === '5/3/1 Press Day' && !activeSession.programDay && !activeSession.exercises[0].plan") is True,
          cdp.ev('JSON.stringify(activeSession).slice(0, 300)'))
    t.end_workout()
    check('the server has the progress', wait_for(lambda: '0-0' in (server_program() or {}).get('done', {})), server_program())
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 4")
    check('so does History', 'Cycle 1, week 1 · 5s week' in text('historyList'))

    # ------------------------------------------------------------------ P5 skipping, a missed + set and the next cycle
    print('P5  skipping days, a missed + set, and the next cycle')
    open_tracker()
    skip_next()
    check('a skipped day counts as done', 'Skipped' in week_rows(0)[1] and 'Bench Day' in text('programNext'), week_rows(0))
    check('and says so', 'Skipped Deadlift Day, week 1.' in text('formFeedback'), text('formFeedback'))
    for _ in range(2):
        skip_next()
    check('a finished week moves on to the next', cdp.ev("[...document.querySelectorAll('.program-week')].map(d => d.open)") == [False, True, False, False]
          and 'week 2 of 4, 3s week' in text('programSummary'), text('programSummary'))
    for _ in range(3):
        skip_next()
    check('up to week 2’s squat day', 'Squat Day' in text('programNext') and 'Back Squat 175 × 3 · 200 × 3 · 225 × 3+' in text('programNext'), text('programNext'))
    click('#programNext [data-program-action=start]')
    for _ in range(5):
        complete_set()
    complete_set(2)
    finish_workout()
    done = (program() or {}).get('done', {})
    check('a + set short of its reps is recorded', done.get('1-3', {}).get('amrap') == {'weight': 225, 'reps': 2, 'target': 3}, done.get('1-3'))
    check('and shown as short', 'short of 3' in week_rows(1)[3], week_rows(1))
    maxes = cdp.ev("[...document.querySelectorAll('#programMaxes li')].map(li => li.textContent)")
    check('next cycle resets that lift to 90%', maxes[3] == 'Back Squat250 lbsResets to 225 next cycle', maxes)
    for _ in range(8):
        if (program() or {}).get('cycle') != 1:
            break
        skip_next()
    state = program() or {}
    check('the last day of the cycle starts the next one', state.get('cycle') == 2 and state.get('done') == {}, state)
    check('with the training maxes moved on',
          state.get('trainingMaxes') == {'press': 105, 'deadlift': 310, 'bench': 205, 'squat': 225}, state.get('trainingMaxes'))
    notice = text('programNotice')
    check('the card says how they moved', visible('programNotice') and 'Cycle 1 complete' in notice
          and 'Overhead Press 105 lbs (+5)' in notice and 'Back Squat 225 lbs (reset after a missed + set)' in notice, notice)
    check('so does the message', 'Cycle 1 of Wendler 5/3/1 is complete' in text('formFeedback'), text('formFeedback'))
    check('and every weight follows (70% x 5, 80% x 5, 90% x 5+ of 105, to the nearest 5)',
          'Overhead Press 70 × 5 · 80 × 5 · 90 × 5+' in text('programNext'), text('programNext'))
    check('the server has cycle 2', wait_for(lambda: (server_program() or {}).get('cycle') == 2), server_program())
    open_tracker()
    check('a reload keeps it', (program() or {}).get('cycle') == 2 and 'Cycle 2' in text('programSummary'), text('programSummary'))

    # ------------------------------------------------------------------ P6 editing
    print('P6  editing the program')
    skip_next()
    click('#editProgramBtn')
    check('the dialog edits the training maxes', text('programModalTitle') == 'Edit Wendler 5/3/1' and field('programMaxKind') == 'tm'
          and field('programMax-bench') == '205', f"{text('programModalTitle')} {field('programMaxKind')} {field('programMax-bench')}")
    set_field('programMax-bench', 210)
    set_field('programRounding', 2.5)
    set_field('programAssistance', 'none')
    cdp.ev("const d = document.getElementById('programDeload'); d.checked = false; d.dispatchEvent(new Event('change', { bubbles: true }))")
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.4)
    check('without the deload a cycle is three weeks', cdp.ev("document.querySelectorAll('.program-week').length") == 3)
    check('progress so far is kept', '1 of 12 workouts done' in text('programSummary') and (program() or {}).get('cycle') == 2, text('programSummary'))
    check('weights use the new max and rounding', 'Bench Press 137.5 × 5 · 157.5 × 5 · 177.5 × 5+' in week_rows(0)[2], week_rows(0))
    check('with main lifts only there is no assistance', cdp.ev("document.querySelectorAll('#programNext li').length") == 1, text('programNext'))

    # ------------------------------------------------------------------ P7 through a network drop
    print('P7  a program workout finished offline')
    cdp.block_api = True
    click('#programNext [data-program-action=start]')
    check('it starts offline', cdp.ev(TITLE) == '5/3/1 Deadlift Day', cdp.ev(TITLE))
    complete_set()
    finish_workout()
    check('the day is marked done on this device', '0-1' in (program() or {}).get('done', {}) and cdp.ev("readLocalState('program').dirty") is True)
    cdp.send('Page.reload')
    time.sleep(0.4)
    cdp.wait("document.readyState === 'complete'")
    cdp.pause(1.2)
    check('a reload while offline keeps it', '2 of 12 workouts done' in (safe_ev("document.getElementById('programSummary').textContent") or ''),
          safe_ev("document.getElementById('programSummary').textContent"))
    cdp.block_api = False
    check('and it reaches the server once back online', wait_for(lambda: '0-1' in (server_program() or {}).get('done', {})), server_program())
    check('with the workout itself', wait_for(lambda: any(w['name'] == '5/3/1 Deadlift Day' for w in t.workouts())), '')

    # ------------------------------------------------------------------ P8 the phone layout
    print('P8  the phone layout')
    open_tracker()
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    cdp.pause(0.3)
    check('no sideways scrolling with the program card', cdp.ev('document.documentElement.scrollWidth - innerWidth') <= 0)
    click('#programNext [data-program-action=start]')
    check('nor with a planned workout', cdp.ev('document.documentElement.scrollWidth - innerWidth') <= 0 and len(chips()) == 6)
    cdp.send('Emulation.clearDeviceMetricsOverride')
    t.end_workout()

    # ------------------------------------------------------------------ P9 ending it
    print('P9  ending the program')
    open_tracker()
    cdp.dialogs.clear()
    cdp.answer = False
    click('#endProgramBtn')
    check('asks first', len(cdp.dialogs) == 1 and 'End Wendler 5/3/1?' in cdp.dialogs[0], cdp.dialogs)
    check('and keeps it if declined', visible('programCard') is True)
    cdp.answer = True
    click('#endProgramBtn')
    check('ending it removes the card', visible('programCard') is False and cdp.ev('currentProgram') is None)
    check('and offers to set it up again', cdp.ev(f"!!document.querySelector('{WENDLER} [data-program-action=setup]')") is True)
    check('the server forgets it', wait_for(lambda: server_program() is None), server_program())
    check('its workouts stay in the history', sum(w['name'].startswith('5/3/1') for w in t.workouts()) == 3, [w['name'] for w in t.workouts()])
    check('no Content-Security-Policy violations along the way', violations() == [], violations())

    # ------------------------------------------------------------------ P10 Reddit PPL
    print('P10 a program saved by the previous version, then setting up Reddit PPL')
    # Saved before programs could keep missed sessions or per-day results; it must still load as it was.
    api('PUT', '/api/state', {'program': {
        'definition': 'wendler-531', 'startedAt': 1000, 'cycle': 3, 'lastRollover': None,
        'trainingMaxes': {'press': 110, 'deadlift': 340, 'bench': 210, 'squat': 295},
        'options': {'assistance': 'bbb', 'rounding': 5, 'warmups': True, 'deload': True, 'tmPercent': 90},
        'done': {'0-0': {'at': 2000, 'skipped': False, 'amrap': {'weight': 80, 'reps': 8, 'target': 5}}}}}, token)
    open_tracker()
    check('a 5/3/1 program saved before this version still loads',
          text('programSummary') == 'Cycle 3 · 1 of 16 workouts done · now in week 1 of 4, 5s week' and 'Done · + set 80 × 8' in week_rows(0)[0],
          f"{text('programSummary')} {week_rows(0)[:1]}")
    api('PUT', '/api/state', {'program': None}, token)
    open_tracker()
    cdp.wait("document.querySelectorAll('#savedWorkoutList .saved-workout').length >= 3")
    names = cdp.ev("[...document.querySelectorAll('#templateList .program-template h3')].map(h => h.textContent)")
    check('Reddit PPL is listed after 5/3/1', names[:2] == ['Wendler 5/3/1', 'Reddit PPL'], names)
    click(f'{PPL} [data-program-action=setup]')
    check('its own setup dialog opens', text('programModalTitle') == 'Start Reddit PPL' and 'sets of 5 until the bar slows down' in text('programIntro'), text('programIntro'))
    check('asking for starting weights, not one-rep maxes', visible('programMaxKindField') is False)
    controls = cdp.ev("[...document.querySelectorAll('#programOptions select, #programOptions input')].map(e => e.id)")
    check('with only the options it uses', controls == ['programRounding'], controls)
    prefilled = {lift: field(f'programMax-{lift}') for lift in ('deadlift', 'row', 'bench')}
    check('logged lifts start from their heaviest set of 5 or more last time', prefilled == {'deadlift': '125', 'row': '80', 'bench': '105'}, prefilled)
    check('each lift says how it goes up', text('programHint-deadlift') == '+10 lbs each good session'
          and text('programHint-row') == '+5 lbs each good session', text('programHint-deadlift'))
    for lift, value in (('deadlift', 225), ('row', 115), ('bench', 135), ('press', 85), ('squat', 185)):
        set_field(f'programMax-{lift}', value)
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.5)
    check('the program card shows it', visible('programCard') and text('programTitle') == 'Reddit PPL'
          and text('programSummary') == 'Week 1 · 0 of 6 workouts done', text('programSummary'))
    check('under its own headings', text('programNumbersHeading') == 'Working weights' and text('programBlockHeading') == 'This week')
    numbers = cdp.ev("[...document.querySelectorAll('#programMaxes li')].map(li => li.textContent)")
    check('a working weight for each main lift', numbers == [f'{name}{weight} lbs+{step} lbs after each good session' for name, weight, step in (
        ('Deadlift', 225, 10), ('Barbell Row', 115, 5), ('Bench Press', 135, 5), ('Overhead Press', 85, 5), ('Back Squat', 185, 5))], numbers)
    rows = cdp.ev("[...document.querySelectorAll('#programWeeks .program-day')].map(li => li.querySelector('div').textContent)")
    check('the week is its six days: pull, push and legs twice', rows == [
        'Pull (Deadlift)Deadlift 1 × 5+ at 225 lbs', 'Push (Bench)Bench Press 4 × 5, 1 × 5+ at 135 lbs', 'LegsBack Squat 2 × 5, 1 × 5+ at 185 lbs',
        'Pull (Row)Barbell Row 4 × 5, 1 × 5+ at 115 lbs', 'Push (Overhead Press)Overhead Press 4 × 5, 1 × 5+ at 85 lbs', 'LegsBack Squat 2 × 5, 1 × 5+ at 185 lbs'], rows)
    check('listed without week sections', cdp.ev("document.querySelectorAll('#programWeeks details').length") == 0)
    lines = cdp.ev("[...document.querySelectorAll('#programNext li')].map(li => li.textContent)")
    check('the next workout lists its accessories as rep ranges', lines == [
        'Deadlift 1 × 5+ at 225 lbs', 'Lat Pulldown 3 × 8–12', 'Seated Cable Row 3 × 8–12', 'Face Pull 5 × 15–20', 'Hammer Curl 4 × 8–12', 'Dumbbell Curl 4 × 8–12'], lines)
    check('the 5/3/1 card offers setting that up instead', cdp.ev(f"!!document.querySelector('{WENDLER} [data-program-action=setup]') && !!document.querySelector('{PPL} [data-program-action=view]')") is True)
    check('the program reaches the server', wait_for(lambda: (server_program() or {}).get('definition') == 'reddit-ppl'), server_program())

    # ------------------------------------------------------------------ P11 a session that adds weight
    print('P11 a PPL workout adds weight')
    known = t.ids()
    click('#programNext [data-program-action=start]')
    check('it starts as the day’s workout', cdp.ev(TITLE) == 'PPL Pull (Deadlift)' and [c[0] for c in chips()] == ['225 lbs × 5+'], f'{cdp.ev(TITLE)} {chips()}')
    check('with one + set of deadlifts', text('activeExerciseTarget') == 'Set 1 of 1: 225 lbs × 5+. As many reps as you can.'
          and field('activeWeight') == '225' and field('completedReps') == '5', text('activeExerciseTarget'))
    complete_set(7)
    estimate = math.floor(225 * (1 + 7 / 30) + 0.5)
    check('the + set is read as a one-rep max', text('activeExerciseTarget') == f'The planned set is done. Your + set of 225 lbs × 7 puts your one-rep max near {estimate} lbs.', text('activeExerciseTarget'))
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    check('accessories are planned as rep ranges', text('activeExerciseName') == 'Lat Pulldown' and [c[0] for c in chips()] == ['8–12 reps'] * 3
          and text('activeExerciseTarget') == 'Set 1 of 3: 8–12 reps.', f"{text('activeExerciseName')} {chips()} {text('activeExerciseTarget')}")
    check('starting at the bottom of the range, with the weight up to you', field('activeWeight') == '' and field('completedReps') == '8', f"'{field('activeWeight')}' {field('completedReps')}")
    cdp.ev("document.getElementById('activeWeight').value = '100'")
    complete_set(12)
    check('the next set follows the one just done', field('activeWeight') == '100' and field('completedReps') == '12', f"{field('activeWeight')} {field('completedReps')}")
    complete_set()
    complete_set()
    finish_workout()
    check('the workout is saved', wait_for(lambda: len(t.ids() - known) == 1), '')
    saved = next((w for w in t.workouts() if w['id'] not in known), {})
    check('under the day’s name, labelled with its week', saved.get('name') == 'PPL Pull (Deadlift)' and (saved.get('program') or {}).get('label') == 'Week 1',
          json.dumps({k: saved.get(k) for k in ('name', 'program')}))
    feedback = text('formFeedback')
    check('getting every rep adds weight, and says so', 'Deadlift goes up to 235 lbs next time.' in feedback and 'Next in Reddit PPL: Push (Bench).' in feedback, feedback)
    state = program() or {}
    check('10 lbs for the deadlift', state.get('trainingMaxes', {}).get('deadlift') == 235 and state.get('done', {}).get('0-0', {}).get('hit') is True, state)
    check('the card shows the + set', 'Done · + set 225 × 7' in cdp.ev("document.querySelectorAll('#programWeeks .program-day')[0].textContent"))
    check('the server has the new weight', wait_for(lambda: (server_program() or {}).get('trainingMaxes', {}).get('deadlift') == 235), server_program())

    # ------------------------------------------------------------------ P12 misses and the deload
    print('P12 missed reps, and the 10% drop after three in a row')

    def missed_bench_session(reps):
        for _ in range(4):
            complete_set()
        complete_set(reps)
        finish_workout()

    click('#programNext [data-program-action=start]')
    names = cdp.ev('activeSession.exercises.map(e => e.name)')
    check('push day: the bench, the other press for volume, then accessories', names == [
        'Bench Press', 'Overhead Press (volume)', 'Incline Dumbbell Press', 'Tricep Pushdown', 'Lateral Raise', 'Overhead Tricep Extension', 'Lateral Raise'], names)
    check('the bench is 4 × 5 and a + set', [c[0] for c in chips()] == ['135 lbs × 5'] * 4 + ['135 lbs × 5+'], chips())
    for _ in range(4):
        complete_set()
    complete_set(4)
    for _ in range(3):
        cdp.ev("document.getElementById('nextExerciseBtn').click()")
        cdp.pause(0.2)
    check('a superset says so', text('activeExerciseName') == 'Tricep Pushdown'
          and text('activeExerciseTarget') == 'Set 1 of 3: 8–12 reps. Superset with the lateral raises that follow.', text('activeExerciseTarget'))
    finish_workout()
    check('a short + set keeps the weight and counts the miss', 'Bench Press stays at 135 lbs: 1 missed session in a row. A third drops it 10%.' in text('formFeedback'), text('formFeedback'))
    state = program() or {}
    check('the miss is kept', state.get('trainingMaxes', {}).get('bench') == 135 and state.get('stalls', {}).get('bench') == 1, state)
    note = cdp.ev("(() => { const s = document.querySelectorAll('#programMaxes li small')[2]; return [s.textContent, s.className]; })()")
    check('and shown as a warning', note == ['Missed 1 in a row · 3 drops it to 120', 'warn'], note)
    click('#programWeeks [data-program-action=start][data-day="1"]')
    missed_bench_session(3)
    check('a second miss in a row is counted', '2 missed sessions in a row' in text('formFeedback'), text('formFeedback'))
    click('#programWeeks [data-program-action=start][data-day="1"]')
    missed_bench_session(3)
    check('the third drops the weight 10%', 'Bench Press missed three sessions in a row, so it drops 10% to 120 lbs.' in text('formFeedback'), text('formFeedback'))
    state = program() or {}
    check('and starts counting again', state.get('trainingMaxes', {}).get('bench') == 120 and not state.get('stalls', {}).get('bench'), state)
    check('the day shows the short + set', 'Done · + set 135 × 3 (short of 5)' in cdp.ev("document.querySelectorAll('#programWeeks .program-day')[1].textContent"))

    # ------------------------------------------------------------------ P13 accessories and the next week
    print('P13 accessory progression, and the next week')
    skip_next()
    check('skipping moves on without changing any weight', 'Pull (Row)' in text('programNext') and (program() or {}).get('trainingMaxes', {}).get('squat') == 185, text('programNext'))
    click('#programNext [data-program-action=start]')
    check('the row is 4 × 5 and a + set', [c[0] for c in chips()] == ['115 lbs × 5'] * 4 + ['115 lbs × 5+'], chips())
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    check('an accessory done at the top of its range last time says to go heavier', text('activeExerciseName') == 'Lat Pulldown'
          and 'Last time every set reached 12, so go heavier.' in text('activeExerciseTarget') and field('activeWeight') == '100', text('activeExerciseTarget'))
    t.end_workout()
    for _ in range(3):
        skip_next()
    state = program() or {}
    check('the sixth day starts the next week', state.get('cycle') == 2 and state.get('done') == {} and text('programSummary') == 'Week 2 · 0 of 6 workouts done', text('programSummary'))
    check('and says so', 'Week 1 of Reddit PPL is complete. Next in Reddit PPL: Pull (Deadlift).' in text('formFeedback'), text('formFeedback'))
    check('the working weights carry on', state.get('trainingMaxes') == {'deadlift': 235, 'row': 115, 'bench': 120, 'press': 85, 'squat': 185}
          and visible('programNotice') is False, state.get('trainingMaxes'))
    check('so the next deadlift is heavier', 'Deadlift 1 × 5+ at 235 lbs' in text('programNext'), text('programNext'))
    check('the server has week 2', wait_for(lambda: (server_program() or {}).get('cycle') == 2), server_program())

    # ------------------------------------------------------------------ P14 editing and switching
    print('P14 editing it, and switching programs')
    click('#editProgramBtn')
    check('editing shows the working weights', text('programModalTitle') == 'Edit Reddit PPL' and field('programMax-bench') == '120' and visible('programMaxKindField') is False)
    set_field('programMax-press', 90)
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.4)
    check('a changed weight is used from the next workout', (program() or {}).get('trainingMaxes', {}).get('press') == 90
          and 'Overhead Press 4 × 5, 1 × 5+ at 90 lbs' in cdp.ev("document.querySelectorAll('#programWeeks .program-day')[4].textContent"))
    click(f'{WENDLER} [data-program-action=setup]')
    check('setting up another program says it replaces this one', 'This replaces Reddit PPL' in text('programIntro')
          and text('programSubmit') == 'Switch program' and visible('programMaxKindField') is True, text('programIntro'))
    set_field('programMaxKind', 'tm')
    for lift, value in (('press', 100), ('deadlift', 300), ('bench', 200), ('squat', 250)):
        set_field(f'programMax-{lift}', value)
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.5)
    check('switching replaces it', text('programTitle') == 'Wendler 5/3/1' and text('programSummary').startswith('Cycle 1 · 0 of 16')
          and text('programNumbersHeading') == 'Training maxes', text('programSummary'))
    check('and the PPL card offers setting it up again', cdp.ev(f"!!document.querySelector('{PPL} [data-program-action=setup]')") is True)
    check('the server has the new program', wait_for(lambda: (server_program() or {}).get('definition') == 'wendler-531'), server_program())
    cdp.answer = True
    click('#endProgramBtn')
    check('PPL workouts stay in the history', sum(w['name'].startswith('PPL') for w in t.workouts()) == 4, [w['name'] for w in t.workouts()])
    check('no Content-Security-Policy violations with PPL either', violations() == [], violations())

    run_apartment_gym(t, text, visible, field, set_field, click, server_program, program, chips, complete_set, finish_workout, violations)


# Every exercise of each Apartment Gym day, in order. The equipment is dumbbells, an adjustable bench, a cable stack
# with one handle, and chest press, lat pulldown, leg extension and leg curl machines; nothing else.
APARTMENT_DAYS = [
    ['Machine Chest Press', 'Incline Dumbbell Press', 'Single-Arm Cable Pulldown', 'Single-Arm Cable Row', 'Dumbbell Lateral Raise', 'Single-Arm Cable Pushdown'],
    ['Dumbbell Bulgarian Split Squat', 'Single-Leg Dumbbell Romanian Deadlift', 'Leg Curl', 'Leg Extension', 'Single-Leg Dumbbell Calf Raise', 'Pallof Press'],
    ['Lat Pulldown', 'Dumbbell Bench Press', 'Chest-Supported Dumbbell Row', 'Seated Dumbbell Shoulder Press', 'Single-Arm Cable Rear Delt Fly', 'Dumbbell Hammer Curl'],
    ['Dumbbell Romanian Deadlift', 'Goblet Squat', 'Dumbbell Step-Up', 'Leg Curl', 'Leg Extension', 'Cable Woodchop'],
]
# What each exercise needs, from the list above.
APARTMENT_EQUIPMENT = {
    'dumbbells': ('Dumbbell', 'Goblet Squat'),
    'cable stack': ('Cable', 'Pallof Press'),
    'machines': ('Machine Chest Press', 'Lat Pulldown', 'Leg Curl', 'Leg Extension'),
}
APARTMENT = '#templateList .program-template[data-program-id="apartment-gym"]'


def run_apartment_gym(t, text, visible, field, set_field, click, server_program, program, chips, complete_set, finish_workout, violations):
    cdp, check, wait_for = t.cdp, t.check, t.wait_for

    def numbers():
        return cdp.ev("[...document.querySelectorAll('#programMaxes li')].map(li => li.textContent)") or []

    def day_rows():
        return cdp.ev("[...document.querySelectorAll('#programWeeks .program-day')].map(li => li.querySelector('div').textContent)") or []

    def maxes():
        return (program() or {}).get('trainingMaxes', {})

    def start_day(day):
        click(f'#programWeeks [data-program-action=start][data-day="{day}"]')

    def main_lift(reps):
        """Log the main lift's sets with these reps each, then finish without the accessories."""
        for count in reps:
            complete_set(count)
        finish_workout()

    # ------------------------------------------------------------------ P15 offered and set up
    print('P15 Apartment Gym is offered, and set up for its equipment')
    t.open_tracker()
    names = cdp.ev("[...document.querySelectorAll('#templateList .program-template h3')].map(h => h.textContent)")
    check('Apartment Gym is listed after the other programs', names == ['Wendler 5/3/1', 'Reddit PPL', 'Apartment Gym'], names)
    card = cdp.ev(f"document.querySelector('{APARTMENT}').textContent")
    check('its card says what it needs and how often', 'dumbbells up to 50 lbs' in card and '4 days a week · upper and lower body twice each' in card, card)
    click(f'{APARTMENT} [data-program-action=setup]')
    check('its setup dialog opens', text('programModalTitle') == 'Start Apartment Gym' and 'Dumbbell weights are per hand.' in text('programIntro'), text('programIntro'))
    check('asking for starting weights, not one-rep maxes', visible('programMaxKindField') is False)
    controls = cdp.ev("[...document.querySelectorAll('#programOptions select, #programOptions input')].map(e => e.id)")
    check('with its equipment as the options', controls == ['programDumbbellMax', 'programMachineStep'], controls)
    check('the heaviest dumbbells default to 50 lbs, the stack to 10-lb plates',
          field('programDumbbellMax') == '50' and field('programMachineStep') == '10', f"{field('programDumbbellMax')} {field('programMachineStep')}")
    prefilled = {lift: field(f'programMax-{lift}') for lift in ('chestPress', 'splitSquat', 'pulldown', 'rdl')}
    check('a logged lift starts from its heaviest set of 8 or more', prefilled == {'chestPress': '', 'splitSquat': '', 'pulldown': '100', 'rdl': ''}, prefilled)
    check('and the intro says so', 'heaviest set of 8 or more' in text('programIntro'), text('programIntro'))
    check('machines go up a plate, dumbbells 5 lbs, at the top of the range',
          text('programHint-chestPress') == '+10 lbs once every set reaches 10' and text('programHint-splitSquat') == '+5 lbs once every set reaches 12',
          f"{text('programHint-chestPress')} / {text('programHint-splitSquat')}")
    set_field('programMax-splitSquat', 60)
    check('a dumbbell weight above the heaviest pair is capped', text('programHint-splitSquat') == 'Capped at 50 lbs, your heaviest dumbbells', text('programHint-splitSquat'))
    set_field('programMachineStep', 5)
    check('the stack step changes the machine hints', text('programHint-chestPress') == '+5 lbs once every set reaches 10', text('programHint-chestPress'))
    set_field('programMachineStep', 10)
    set_field('programMax-chestPress', 100)
    set_field('programMax-rdl', 40)
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.5)
    state = program() or {}
    check('it starts with the split squat capped at 50', maxes() == {'chestPress': 100, 'splitSquat': 50, 'pulldown': 100, 'rdl': 40}, maxes())
    check('and its options stored as numbers', state.get('options') == {'dumbbellMax': 50, 'machineStep': 10}, state.get('options'))
    check('the program card shows it', text('programTitle') == 'Apartment Gym' and text('programSummary') == 'Week 1 · 0 of 4 workouts done', text('programSummary'))
    check('a working weight for each main lift', numbers() == [
        'Machine Chest Press100 lbs+10 lbs once every set reaches 10',
        'Dumbbell Bulgarian Split Squat50 lbsHeaviest dumbbells · progress by slowing the reps',
        'Lat Pulldown100 lbs+10 lbs once every set reaches 10',
        'Dumbbell Romanian Deadlift40 lbs+5 lbs once every set reaches 12'], numbers())
    check('the week is upper and lower body twice', day_rows() == [
        'Upper AMachine Chest Press 4 × 6–10 at 100 lbs', 'Lower ADumbbell Bulgarian Split Squat 3 × 8–12 at 50 lbs',
        'Upper BLat Pulldown 4 × 6–10 at 100 lbs', 'Lower BDumbbell Romanian Deadlift 4 × 8–12 at 40 lbs'], day_rows())
    planned = cdp.ev("[0, 1, 2, 3].map(day => programDefinition(currentProgram).workout(currentProgram, 0, day).map(e => e.name))")
    check('each day is exactly its planned exercises', planned == APARTMENT_DAYS, planned)
    unusable = [name for day in planned or [] for name in day if not any(word in name for words in APARTMENT_EQUIPMENT.values() for word in words)]
    check('every exercise uses only the listed equipment', planned and not unusable, unusable)
    # A deadlift is fine only as a dumbbell Romanian deadlift; there is no barbell to pull from the floor.
    needs_more = [name for day in planned or [] for name in day
                  if any(word in name for word in ('Barbell', 'Back Squat', 'Pull-up', 'Chin-up', 'Dip', 'Leg Press')) or ('Deadlift' in name and 'Dumbbell' not in name)]
    check('nothing needs a barbell, rack, pull-up bar, dip station or leg press', planned and not needs_more, needs_more)
    ranges = cdp.ev("[0, 1, 2, 3].flatMap(day => programDefinition(currentProgram).workout(currentProgram, 0, day).map(e => e.plan.every(s => s.repsMax > s.reps)))")
    check('every set of every exercise is a rep range', ranges and all(ranges), ranges)
    lines = cdp.ev("[...document.querySelectorAll('#programNext li')].map(li => li.textContent)")
    check('the next workout lists the day', lines == ['Machine Chest Press 4 × 6–10 at 100 lbs', 'Incline Dumbbell Press 3 × 8–12', 'Single-Arm Cable Pulldown 3 × 10–12',
                                                   'Single-Arm Cable Row 3 × 10–12', 'Dumbbell Lateral Raise 3 × 12–15', 'Single-Arm Cable Pushdown 3 × 10–15'], lines)
    check('the program reaches the server', wait_for(lambda: (server_program() or {}).get('definition') == 'apartment-gym'), server_program())

    # ------------------------------------------------------------------ P16 top of the range
    print('P16 every set at the top of the range adds weight')
    known = t.ids()
    click('#programNext [data-program-action=start]')
    check('it starts as the day’s workout', cdp.ev("document.getElementById('activeWorkoutTitle').textContent") == 'Apartment Gym Upper A'
          and [c[0] for c in chips()] == ['100 lbs × 6–10'] * 4, chips())
    check('planned as a rep range at the working weight', text('activeExerciseTarget') == 'Set 1 of 4: 100 lbs × 6–10.'
          and field('activeWeight') == '100' and field('completedReps') == '6', text('activeExerciseTarget'))
    for _ in range(4):
        complete_set(10)
    cdp.ev("document.getElementById('nextExerciseBtn').click()")
    cdp.pause(0.3)
    check('accessories come with their setup notes', text('activeExerciseName') == 'Incline Dumbbell Press'
          and text('activeExerciseTarget') == 'Set 1 of 3: 8–12 reps. Bench at 30–45°.' and field('activeWeight') == '', text('activeExerciseTarget'))
    finish_workout()
    check('the workout is saved', wait_for(lambda: len(t.ids() - known) == 1), '')
    saved = next((w for w in t.workouts() if w['id'] not in known), {})
    check('under the day’s name, labelled with its week', saved.get('name') == 'Apartment Gym Upper A' and (saved.get('program') or {}).get('label') == 'Week 1',
          json.dumps({k: saved.get(k) for k in ('name', 'program')}))
    feedback = text('formFeedback')
    check('the machine goes up a plate, and says so', 'Machine Chest Press goes up to 110 lbs next time: every set reached 10 reps.' in feedback
          and 'Next in Apartment Gym: Lower A.' in feedback, feedback)
    check('the new weight is kept, and the day marked done', maxes().get('chestPress') == 110
          and 'Done' in cdp.ev("document.querySelectorAll('#programWeeks .program-day')[0].textContent"), maxes())
    check('and reaches the server', wait_for(lambda: (server_program() or {}).get('trainingMaxes', {}).get('chestPress') == 110), server_program())

    # ------------------------------------------------------------------ P17 the heaviest dumbbells, and within the range
    print('P17 the heaviest dumbbells, and a session inside the range')
    click('#programNext [data-program-action=start]')
    check('the split squat says the weight is per dumbbell and the reps per leg',
          text('activeExerciseTarget') == 'Set 1 of 3: 50 lbs × 8–12. Weight per dumbbell, reps per leg.' and [c[0] for c in chips()] == ['50 lbs × 8–12'] * 3, text('activeExerciseTarget'))
    main_lift([12, 12, 12])
    check('at the heaviest dumbbells the weight stays and the reps get slower', 'Dumbbell Bulgarian Split Squat reached 12 reps on every set with your heaviest dumbbells.'
          in text('formFeedback') and 'lower each rep over 3 seconds' in text('formFeedback'), text('formFeedback'))
    check('the split squat stays at 50', maxes().get('splitSquat') == 50, maxes())
    click('#programNext [data-program-action=start]')
    check('Upper B starts with the pulldown', [c[0] for c in chips()] == ['100 lbs × 6–10'] * 4, chips())
    main_lift([9, 8, 7, 6])
    check('reps inside the range keep the weight until the top', 'Lat Pulldown stays at 100 lbs until every set reaches 10 reps.' in text('formFeedback'), text('formFeedback'))
    check('with no miss counted', maxes().get('pulldown') == 100 and not (program() or {}).get('stalls', {}).get('pulldown'), program())

    # ------------------------------------------------------------------ P18 below the range, and the next week
    print('P18 reps below the range, the next week, and the 10% drop')
    click('#programNext [data-program-action=start]')
    check('Lower B starts with the Romanian deadlift', [c[0] for c in chips()] == ['40 lbs × 8–12'] * 4, chips())
    main_lift([10, 9, 8, 6])
    feedback = text('formFeedback')
    check('a set below the range keeps the weight and counts a miss',
          'Dumbbell Romanian Deadlift stays at 40 lbs: 1 session in a row below 8 reps. A third drops it 10%.' in feedback, feedback)
    check('the fourth day finishes the week', 'Week 1 of Apartment Gym is complete. Next in Apartment Gym: Upper A.' in feedback, feedback)
    state = program() or {}
    check('week 2 starts with the new weights', state.get('cycle') == 2 and state.get('done') == {} and text('programSummary') == 'Week 2 · 0 of 4 workouts done'
          and 'Machine Chest Press 4 × 6–10 at 110 lbs' in text('programNext'), text('programSummary'))
    note = cdp.ev("(() => { const s = document.querySelectorAll('#programMaxes li small')[3]; return [s.textContent, s.className]; })()")
    check('the miss is shown as a warning', note == ['Missed 1 in a row · 3 drops it to 35', 'warn'], note)
    start_day(3)
    main_lift([8, 8, 7, 7])
    check('a second miss in a row is counted', '2 sessions in a row below 8 reps' in text('formFeedback'), text('formFeedback'))
    row = cdp.ev("document.querySelectorAll('#programWeeks .program-day')[3].textContent")
    check('and the day says it missed reps', 'Done (missed reps)' in row, row)
    start_day(3)
    main_lift([7, 7, 7, 7])
    check('the third drops the weight 10%', 'Dumbbell Romanian Deadlift fell below 8 reps three sessions in a row, so it drops 10% to 35 lbs.' in text('formFeedback'), text('formFeedback'))
    check('and clears the misses', maxes().get('rdl') == 35 and not (program() or {}).get('stalls', {}).get('rdl'), program())

    # ------------------------------------------------------------------ P19 changing the equipment
    print('P19 changing the equipment settings')
    click('#editProgramBtn')
    check('editing shows the working weights and equipment', text('programModalTitle') == 'Edit Apartment Gym'
          and field('programMax-chestPress') == '110' and field('programDumbbellMax') == '50', field('programMax-chestPress'))
    set_field('programDumbbellMax', 60)
    set_field('programMachineStep', 5)
    check('heavier dumbbells let the split squat go up again', text('programHint-splitSquat') == '+5 lbs once every set reaches 12', text('programHint-splitSquat'))
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.4)
    check('the new equipment is kept', (program() or {}).get('options') == {'dumbbellMax': 60, 'machineStep': 5}, (program() or {}).get('options'))
    check('and the card says so', numbers()[1] == 'Dumbbell Bulgarian Split Squat50 lbs+5 lbs once every set reaches 12'
          and numbers()[0] == 'Machine Chest Press110 lbs+5 lbs once every set reaches 10', numbers())
    start_day(1)
    main_lift([12, 12, 12])
    check('the split squat now goes up', 'Dumbbell Bulgarian Split Squat goes up to 55 lbs next time' in text('formFeedback') and maxes().get('splitSquat') == 55, text('formFeedback'))
    start_day(0)
    main_lift([10, 10, 10, 10])
    check('the chest press goes up by the smaller step', 'Machine Chest Press goes up to 115 lbs next time' in text('formFeedback') and maxes().get('chestPress') == 115, text('formFeedback'))
    click('#editProgramBtn')
    set_field('programDumbbellMax', 45)
    check('lighter dumbbells cap a heavier working weight', text('programHint-splitSquat') == 'Capped at 45 lbs, your heaviest dumbbells', text('programHint-splitSquat'))
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.4)
    check('and it is lowered to them', maxes() == {'chestPress': 115, 'splitSquat': 45, 'pulldown': 100, 'rdl': 35}, maxes())
    check('the server has it all', wait_for(lambda: (server_program() or {}).get('trainingMaxes') == {'chestPress': 115, 'splitSquat': 45, 'pulldown': 100, 'rdl': 35}), server_program())

    # ------------------------------------------------------------------ P20 history and ending it
    print('P20 the workouts stay in the history')
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length > 0")
    cdp.pause(0.4)
    listed = cdp.ev("document.getElementById('historyList').textContent")
    check('History lists them under their day, with their week', 'Apartment Gym Lower A' in listed and 'Week 2' in listed, listed[:300])
    t.open_tracker()
    t.cdp.answer = True
    click('#endProgramBtn')
    check('ending the program keeps its workouts', sum(w['name'].startswith('Apartment Gym') for w in t.workouts()) == 8, [w['name'] for w in t.workouts()])
    check('no Content-Security-Policy violations with Apartment Gym either', violations() == [], violations())
