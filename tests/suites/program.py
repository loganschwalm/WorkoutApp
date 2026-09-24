"""Training programs: setting up Wendler 5/3/1, its planned sets and weights, moving through a cycle, the next
cycle's training maxes (and a reset after a missed + set), editing and ending it, and keeping it through a network drop."""

import json
import math
import time

from ..harness import ACTIVE, HIDDEN, TITLE

INTERCEPT = True

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
    check('its template card now leads to it', cdp.ev("!!document.querySelector('#templateList [data-program-action=view]') && !document.querySelector('#templateList [data-program-action=setup]')") is True)
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
    check('and offers to set it up again', cdp.ev("!!document.querySelector('#templateList [data-program-action=setup]')") is True)
    check('the server forgets it', wait_for(lambda: server_program() is None), server_program())
    check('its workouts stay in the history', sum(w['name'].startswith('5/3/1') for w in t.workouts()) == 3, [w['name'] for w in t.workouts()])
    check('no Content-Security-Policy violations along the way', violations() == [], violations())
