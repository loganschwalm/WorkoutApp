"""Tools for the middle of a workout and the end of it: exercise name suggestions, the summary and personal records
when a workout is finished, going straight to any exercise, swapping an exercise (in a saved workout and in a training
program), rest per exercise, and timed exercises."""

import json

from ..harness import ACTIVE, HIDDEN

INTERCEPT = True


def run(t):
    cdp, check, api, token, wait_for, safe_ev = t.cdp, t.check, t.api, t.token, t.wait_for, t.safe_ev
    open_tracker, start, seed, ex = t.open_tracker, t.start, t.seed, t.ex

    def text(idn):
        return cdp.ev(f"document.getElementById('{idn}').textContent")

    def field(idn):
        return cdp.ev(f"document.getElementById('{idn}').value")

    def visible(idn):
        return cdp.ev(f"!document.getElementById('{idn}').hidden")

    def set_field(idn, value):
        cdp.ev(f"(() => {{ const e = document.getElementById('{idn}'); e.value = {json.dumps(str(value))}; e.dispatchEvent(new Event('input', {{ bubbles: true }})); e.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")

    def click(idn):
        cdp.ev(f"document.getElementById('{idn}').click()")

    def log(weight, reps):
        cdp.ev(f"document.getElementById('activeWeight').value = '{weight}'; document.getElementById('completedReps').value = '{reps}'; document.getElementById('completeSetBtn').click();")
        cdp.pause(0.2)

    def rows():
        return cdp.ev("[...document.querySelectorAll('#completedSets li')].map(li => ({ reps: li.querySelector('[data-field=reps]').value, unit: li.querySelectorAll('.set-field span')[1].textContent, label: li.querySelector('[data-field=reps]').getAttribute('aria-label') }))")

    def names():
        return cdp.ev('activeSession.exercises.map(e => e.name)')

    def jump_list():
        return cdp.ev("[...document.querySelectorAll('#exerciseJump button')].map(b => [b.querySelector('.jump-name').textContent, b.querySelector('.jump-sets').textContent, b.hasAttribute('aria-current'), b.classList.contains('done')])")

    def jump(index):
        cdp.ev(f"if (document.getElementById('exerciseJump').hidden) document.getElementById('activeWorkoutProgress').click(); document.querySelector('#exerciseJump [data-jump=\"{index}\"]').click()")
        cdp.pause(0.2)

    def swap(name):
        cdp.ev("if (document.getElementById('swapPanel').hidden) document.getElementById('swapToggle').click()")
        set_field('swapName', name)
        click('swapBtn')
        cdp.pause(0.2)

    def add_exercise(name, reps, timed=False):
        cdp.ev("document.getElementById('addActiveExercise').open = true")
        set_field('activeAddName', name)
        set_field('activeAddReps', reps)
        if timed:
            cdp.ev("document.getElementById('activeAddTimed').click()")
        click('activeAddBtn')
        cdp.pause(0.2)

    def finish():
        for _ in range(10):
            if cdp.ev(HIDDEN):
                break
            click('nextExerciseBtn')
            cdp.pause(0.25)
        cdp.pause(0.6)

    def start_saved(workout_id):
        cdp.goto(f'/index.html?start={workout_id}')
        cdp.wait(ACTIVE)
        cdp.pause(0.5)

    def summary():
        return cdp.ev("""({ shown: !document.getElementById('workoutSummary').hidden, name: document.getElementById('summaryName').textContent,
            stats: [...document.querySelectorAll('#summaryStats li')].map(li => [li.querySelector('strong').textContent, li.querySelector('span').textContent]),
            recordsShown: !document.getElementById('summaryRecords').hidden,
            records: [...document.querySelectorAll('#summaryRecordList li')].map(li => li.textContent) })""")

    def suggestions():
        return cdp.ev("[...document.querySelectorAll('#exerciseNames option')].map(o => o.value)")

    def newest(known):
        fresh = [w for w in t.workouts() if w['id'] not in known]
        return fresh[0] if fresh else None

    def timer():
        return text('timerDisplay')

    # Workouts for the suggestions and records to work from.
    seed('Glutes', 1, [ex('Hip Thrust', 135, 10, [(10, 135)])])
    seed('Glutes', 3, [ex('hip thrust', 145, 10, [(10, 145)])])
    seed('Pull-ups', 1, [ex('Pull-up', 0, 8, [(8, 0), (6, 0)])])
    seed('DB Day', 5, [ex('Dumbbell Bench Press', 50, 10, [(10, 50), (9, 50)])])

    # ------------------------------------------------------------------ D suggestions
    print('D   exercise name suggestions')
    open_tracker()
    # The templates' names are there at once; the logged ones once the saved workouts have loaded.
    cdp.wait('initialLoadDone', 15)
    options = suggestions()
    check('every exercise logged is suggested', {'Bench Press', 'Overhead Press', 'Barbell Row', 'Pull-up', 'Dumbbell Bench Press'} <= set(options), options)
    check('and the templates’ exercises', {'Tricep Pushdown', 'Goblet Squat', 'Plank', 'Lat Pulldown'} <= set(options), options)
    check('each once, spelled as it was most recently logged', options.count('hip thrust') == 1 and 'Hip Thrust' not in options, [o for o in options if 'thrust' in o.lower()])
    check('in alphabetical order', options.index('Back Squat') < options.index('Bench Press') < options.index('hip thrust') < options.index('Plank'), options)
    lists = cdp.ev("['exercise', 'activeAddName', 'swapName'].map(id => document.getElementById(id).getAttribute('list'))")
    check('the workout form, Add an exercise and Swap all offer them', lists == ['exerciseNames'] * 3, lists)
    click('createTemplateBtn')
    check('so does the template editor', cdp.ev("document.getElementById('templateExercise0').getAttribute('list')") == 'exerciseNames')
    click('cancelTemplate')
    click('createWorkoutBtn')
    cdp.ev("document.getElementById('exercise').value = 'Curl'; document.getElementById('reps').value = '10'; document.getElementById('addBtn').click()")
    check('and a written-down workout’s rows', cdp.ev("document.querySelector('#exerciseList .exercise-edit[data-field=name]').getAttribute('list')") == 'exerciseNames')
    click('clearBtn')

    # ------------------------------------------------------------------ P summary and records
    print('P   the summary and personal records')
    known = t.ids()
    start_saved(t.W3)
    check('no summary while a workout is going', not visible('workoutSummary'))
    log(110, 5)
    click('nextExerciseBtn')
    cdp.pause(0.2)
    log(62, 10)
    add_exercise('Pull-up', 8)
    click('nextExerciseBtn')
    cdp.pause(0.2)
    log(0, 10)
    add_exercise('Face Pull', 15)
    click('nextExerciseBtn')
    cdp.pause(0.2)
    log(30, 15)
    finish()
    s = summary()
    check('finishing shows a summary of the workout', s['shown'] and s['name'] == 'Seed Push', s)
    check('how long it took, the exercises, the sets and the volume',
          s['stats'] == [['1 min', 'Time'], ['4', 'Exercises'], ['4', 'Sets'], ['1,620 lbs', 'Volume']], s['stats'])
    check('and the new personal records, one for each kind', s['recordsShown'] and s['records'] == [
        'Bench Press: 110 lbs × 5, your heaviest yet (was 105 lbs)',
        'Overhead Press: 62 lbs × 10, an estimated one-rep max of 83 lbs, your best yet (was 79 lbs)',
        'Pull-up: 10 reps in a set, your most yet (was 8)'], s['records'])
    check('an exercise done for the first time sets no record', not any('Face Pull' in r for r in s['records']), s['records'])
    check('the saved-successfully message still shows', 'saved successfully' in text('formFeedback'), text('formFeedback'))
    check('a new exercise is suggested at once', 'Face Pull' in suggestions())
    check('the workout is saved with how long it took', wait_for(lambda: newest(known) is not None))
    saved = newest(known)
    check('in seconds', isinstance(saved.get('duration'), int) and 0 < saved['duration'] < 600, saved.get('duration'))
    # The list is drawn again once the upload has gone through.
    listed = cdp.wait("document.querySelector('#savedWorkoutList .saved-workout-toggle span').textContent.endsWith(' · 1 min')")
    check('and the Tracker’s list says so', listed, cdp.ev("document.querySelector('#savedWorkoutList .saved-workout-toggle span').textContent"))
    click('summaryDone')
    check('Done puts the summary away', not visible('workoutSummary'))

    start_saved(t.W3)
    log(100, 5)
    finish()
    s = summary()
    check('a workout that beats nothing shows no records', s['shown'] and not s['recordsShown'] and s['records'] == [], s)
    start(0)
    cdp.pause(0.3)
    check('starting the next workout puts the summary away', not visible('workoutSummary'))
    t.end_workout()

    cdp.block_api = True
    cdp.send('Page.reload')
    cdp.pause(0.5)
    cdp.wait("document.readyState === 'complete'")
    cdp.pause(1.5)
    cdp.ev('startWorkout(getAllTemplates()[0])')
    cdp.pause(0.3)
    log(115, 3)
    finish()
    s = summary()
    check('records are told offline too, from what this device remembers',
          s['records'] == ['Bench Press: 115 lbs × 3, your heaviest yet (was 110 lbs)'], s['records'])
    cdp.block_api = False
    cdp.ev('syncNow()')
    check('and the workout uploads afterwards', wait_for(lambda: safe_ev('readPendingWorkouts().length', -1) == 0))

    # ------------------------------------------------------------------ J going to any exercise
    print('J   going straight to any exercise')
    open_tracker()
    start(0)
    cdp.pause(0.4)
    check('the exercise count is a button', cdp.ev("document.getElementById('activeWorkoutProgress').tagName") == 'BUTTON'
          and text('activeWorkoutProgress') == 'Exercise 1 of 3' and cdp.ev("document.getElementById('activeWorkoutProgress').getAttribute('aria-expanded')") == 'false')
    check('its list starts closed', not visible('exerciseJump'))
    click('activeWorkoutProgress')
    check('tapping it lists every exercise, the current one marked', visible('exerciseJump') and jump_list() == [
        ['1. Bench Press', 'No sets yet', True, False], ['2. Overhead Press', 'No sets yet', False, False], ['3. Tricep Pushdown', 'No sets yet', False, False]], jump_list())
    log(115, 5)
    check('and how far each has got', jump_list()[0][1:] == ['1 set', True, True], jump_list())
    cdp.ev("document.querySelector('#exerciseJump [data-jump=\"2\"]').click()")
    cdp.pause(0.2)
    check('tapping one goes straight there', text('activeExerciseName') == 'Tricep Pushdown' and text('activeWorkoutProgress') == 'Exercise 3 of 3', text('activeExerciseName'))
    check('and closes the list', not visible('exerciseJump') and cdp.ev("document.getElementById('activeWorkoutProgress').getAttribute('aria-expanded')") == 'false')
    check('as moving on does, the rest timer is put away', not visible('restPanel'))
    check('the last exercise offers Finish', text('nextExerciseBtn') == 'Finish workout')
    jump(1)
    check('from there any other', text('activeExerciseName') == 'Overhead Press' and not cdp.ev("document.getElementById('prevExerciseBtn').hidden"))
    jump(0)
    check('back to the first with its sets', text('activeExerciseName') == 'Bench Press' and len(rows()) == 1, rows())
    check('where it is reaches the server', wait_for(lambda: (t.active_session() or {}).get('currentIndex') == 0))
    t.end_workout()

    # ------------------------------------------------------------------ S swapping
    print('S   swapping an exercise')
    start_saved(t.W3)
    check('Swap sits by the exercise, closed', visible('swapToggle') and not visible('swapPanel')
          and cdp.ev("document.getElementById('swapToggle').getAttribute('aria-expanded')") == 'false')
    click('swapToggle')
    check('it opens a field for the exercise to do instead', visible('swapPanel') and cdp.ev('document.activeElement.id') == 'swapName')
    check('saying what the new exercise keeps', text('swapHelp') == 'The new exercise keeps the target of 8 reps, with weights of your own.', text('swapHelp'))
    click('swapBtn')
    check('an empty name is not a swap', 'Enter the exercise to do instead' in text('formFeedback') and cdp.ev("document.getElementById('swapName').getAttribute('aria-invalid')") == 'true')
    swap('Dumbbell Bench Press')
    check('Swap renames the exercise', text('activeExerciseName') == 'Dumbbell Bench Press' and names() == ['Dumbbell Bench Press', 'Overhead Press'], names())
    check('keeping its target but not the old weight', text('activeExerciseTarget') == 'Target: 8 reps', text('activeExerciseTarget'))
    check('the new exercise starts from its own last time', '50 lbs × 10, 9' in text('activeExerciseLast') and field('activeWeight') == '50',
          f"{text('activeExerciseLast')} {field('activeWeight')}")
    check('the panel closes and says what happened', not visible('swapPanel') and text('formFeedback') == 'Swapped Bench Press for Dumbbell Bench Press.', text('formFeedback'))
    check('the swap reaches the server', wait_for(lambda: ((t.active_session() or {}).get('exercises') or [{}])[0].get('name') == 'Dumbbell Bench Press'))
    swap('bench press')
    check('swapping back brings the original back, weight and all', text('activeExerciseName') == 'Bench Press' and text('activeExerciseTarget') == 'Target: 8 reps at 105 lbs'
          and cdp.ev('activeSession.exercises[0].swappedFrom') is None, text('activeExerciseTarget'))
    log(105, 8)
    click('swapToggle')
    check('once a set is logged, Swap says it stays', text('swapHelp') == 'The set you logged stays with Bench Press, and the new exercise gets the sets from here on.', text('swapHelp'))
    swap('Machine Chest Press')
    check('the new exercise follows the old one, which keeps its set',
          names() == ['Bench Press', 'Machine Chest Press', 'Overhead Press'] and cdp.ev('activeSession.exercises[0].sets.length') == 1
          and text('activeExerciseName') == 'Machine Chest Press' and text('activeWorkoutProgress') == 'Exercise 2 of 3', names())
    check('and says so', text('formFeedback') == 'Swapped Bench Press for Machine Chest Press. The set you logged stays with Bench Press.', text('formFeedback'))
    known = t.ids()
    log(90, 10)
    finish()
    check('both are saved, each with its own set', wait_for(lambda: newest(known) is not None)
          and [(e['name'], len(e['sets'])) for e in newest(known)['exercises']] == [('Bench Press', 1), ('Machine Chest Press', 1)],
          newest(known) and [(e['name'], len(e['sets'])) for e in newest(known)['exercises']])

    def choose_unit(unit):
        click('settingsButton')
        cdp.ev(f"document.getElementById('unitSetting').value = '{unit}'; document.getElementById('settingsForm').requestSubmit()")
        cdp.pause(0.5)

    start_saved(t.W3)
    swap('Dumbbell Bench Press')
    choose_unit('kg')
    check('changing the unit converts what a swap would go back to', cdp.ev('activeSession.exercises[0].swappedFrom.weight') == 47.63,
          cdp.ev('activeSession.exercises[0].swappedFrom'))
    swap('Bench Press')
    check('so swapping back brings the weight in the new unit', text('activeExerciseTarget') == 'Target: 8 reps at 47.63 kg', text('activeExerciseTarget'))
    choose_unit('lbs')
    t.end_workout()

    # ------------------------------------------------------------------ S2 swapping in a program, and a program's rests
    print('S2  swapping in a training program, and its rests')
    open_tracker()
    cdp.ev("if (document.getElementById('templateArea').hidden) document.getElementById('templatesToggle').click()")
    cdp.ev("document.querySelector('#templateList .program-template[data-program-id=\"apartment-gym\"] [data-program-action=setup]').click()")
    cdp.pause(0.3)
    for lift, value in (('chestPress', 100), ('splitSquat', 30), ('pulldown', 100), ('rdl', 40)):
        set_field(f'programMax-{lift}', value)
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.4)
    check('Apartment Gym’s exercises are suggested', 'Single-Arm Cable Pulldown' in suggestions())
    cdp.ev("document.querySelector('#programNext [data-program-action=start]').click()")
    cdp.pause(0.4)
    rests = cdp.ev('activeSession.exercises.map(e => [e.name, e.rest])')
    check('each exercise has its own rest: two minutes for the main lift, 90 s for compound work, 60 for small muscles', rests == [
        ['Machine Chest Press', 120], ['Incline Dumbbell Press', 90], ['Single-Arm Cable Pulldown', 90], ['Single-Arm Cable Row', 90],
        ['Dumbbell Lateral Raise', 60], ['Single-Arm Cable Pushdown', 60]], rests)
    click('swapToggle')
    check('swapping the main lift warns that the program leaves it alone',
          text('swapHelp') == "The new exercise keeps the 4 planned sets and their reps, with weights of your own. Machine Chest Press is this day's main lift, so while it is swapped out the program leaves its weight alone.",
          text('swapHelp'))
    swap('Dumbbell Bench Press')
    plan = cdp.ev("[...document.querySelectorAll('#activePlan li')].map(li => li.textContent)")
    check('the swap keeps the planned sets and rep range, not the machine’s weight', plan == ['6–10 reps'] * 4 and text('activeExerciseTarget').startswith('Set 1 of 4: 6–10 reps.'),
          f"{plan} {text('activeExerciseTarget')}")
    check('and the rest', cdp.ev('restDuration()') == 120)
    for _ in range(4):
        log(50, 10)
    check('the rest timer counts the exercise’s own two minutes', timer() in ('2:00', '1:59'), timer())
    jump(5)
    finish()
    fb = text('formFeedback')
    check('the day counts as done', "Apartment Gym Upper A" in fb and 'Next in Apartment Gym: Lower A.' in fb, fb)
    check('but a swapped main lift does not move the program', 'Machine Chest Press was swapped out, so this workout does not count toward its progress.' in fb
          and cdp.ev('currentProgram.trainingMaxes.chestPress') == 100 and cdp.ev("currentProgram.done['0-0'].hit") is None, fb)
    cdp.ev("document.querySelector('#programNext [data-program-action=start]').click()")
    cdp.pause(0.4)
    for _ in range(3):
        log(30, 12)
    jump(2)
    swap('Seated Leg Curl')
    log(70, 12)
    jump(5)
    finish()
    fb = text('formFeedback')
    check('swapping any other exercise leaves the main lift’s progress alone', 'Dumbbell Bulgarian Split Squat goes up to 35 lbs next time' in fb
          and cdp.ev('currentProgram.trainingMaxes.splitSquat') == 35 and 'swapped out' not in fb, fb)
    ppl = cdp.ev("redditPpl.workout(normalizeProgram({ definition:'reddit-ppl', unit:'lbs', trainingMaxes:{ deadlift:200, row:100, bench:100, press:60, squat:150 }, options:{} }), 0, 0).map(e => [e.name, e.rest])")
    check('Reddit PPL rests three minutes after its main lift', ppl == [['Deadlift', 180], ['Lat Pulldown', 90], ['Seated Cable Row', 90], ['Face Pull', 60], ['Hammer Curl', 60], ['Dumbbell Curl', 60]], ppl)
    wendler = cdp.ev("wendler531.workout(normalizeProgram({ definition:'wendler-531', unit:'lbs', trainingMaxes:{ press:100, deadlift:300, bench:200, squat:250 }, options:{ assistance:'bbb' } }), 0, 1).map(e => [e.name, e.rest])")
    check('and so does 5/3/1, less after Boring But Big', wendler == [['Deadlift', 180], ['Deadlift (BBB)', 90], ['Hanging Leg Raise', 60]], wendler)
    cdp.ev("document.getElementById('endProgramBtn').click()")
    cdp.pause(0.3)

    # ------------------------------------------------------------------ R rest per exercise in a template
    print('R   rest per exercise in a template')
    click('createTemplateBtn')
    labels = cdp.ev("['templateReps0', 'templateRest0'].map(id => document.querySelector(`label[for=${id}]`).textContent)")
    check('each exercise of a template has a rest, the default until set', labels == ['Reps', 'Rest (s)'] and cdp.ev("document.getElementById('templateRest0').placeholder") == '90', labels)
    set_field('templateName', 'Rest Test')
    set_field('templateExercise0', 'Squat Rest')
    set_field('templateReps0', 5)
    set_field('templateRest0', 150)
    click('addTemplateExercise')
    set_field('templateExercise1', 'Curl Rest')
    set_field('templateReps1', 12)
    cdp.ev("document.getElementById('templateForm').requestSubmit()")
    cdp.pause(0.3)
    stored = cdp.ev("customTemplates.find(item => item.name === 'Rest Test').exercises")
    check('a rest given is kept, and one left blank is not', stored == [{'name': 'Squat Rest', 'reps': '5', 'rest': 150}, {'name': 'Curl Rest', 'reps': '12'}], stored)
    check('the template reaches the server with it', wait_for(lambda: any(e.get('rest') == 150 for tp in api('GET', '/api/state', token=token)[0].get('templates', []) for e in tp['exercises'])))
    known = t.ids()
    cdp.ev("[...document.querySelectorAll('#templateList .template-card')].find(c => c.querySelector('h3').textContent === 'Rest Test').querySelector('[data-template-action=start]').click()")
    cdp.pause(0.4)
    log(200, 5)
    check('after a set, the rest timer counts the exercise’s rest', timer() in ('2:30', '2:29'), timer())
    click('restResetBtn')
    check('Reset goes back to it', timer() == '2:30', timer())
    cdp.ev("document.querySelector('#restAdjust [data-rest-adjust=\"-30\"]').click()")
    check('and taking 30 seconds off works from it', timer() == '2:00', timer())
    click('nextExerciseBtn')
    cdp.pause(0.2)
    log(30, 12)
    check('an exercise with no rest of its own uses the default', timer() in ('1:30', '1:29'), timer())
    finish()
    check('the saved workout keeps each rest, so starting it again does too', wait_for(lambda: newest(known) is not None)
          and [e.get('rest') for e in newest(known)['exercises']] == [150, None], newest(known) and newest(known)['exercises'])
    cdp.ev("[...document.querySelectorAll('#templateList .template-card')].find(c => c.querySelector('h3').textContent === 'Rest Test').querySelector('[data-template-action=edit]').click()")
    cdp.pause(0.2)
    check('editing shows the rest', field('templateRest0') == '150' and field('templateRest1') == '')
    set_field('templateRest1', 700)
    cdp.ev("document.getElementById('templateForm').requestSubmit()")
    cdp.pause(0.3)
    check('a rest past ten minutes is refused, as in Settings', visible('templateModal') and cdp.ev("document.getElementById('templateRest1').validity.rangeOverflow")
          and 'rest' not in cdp.ev("customTemplates.find(item => item.name === 'Rest Test').exercises[1]"))
    set_field('templateRest1', 100)
    cdp.ev("document.getElementById('templateForm').requestSubmit()")
    cdp.pause(0.3)
    check('any whole number of seconds up to it is kept', not visible('templateModal') and cdp.ev("customTemplates.find(item => item.name === 'Rest Test').exercises[1].rest") == 100)

    # ------------------------------------------------------------------ T timed exercises
    print('T   timed exercises')
    card = cdp.ev("[...document.querySelectorAll('#templateList .template-card')].find(c => c.querySelector('h3').textContent === 'Full Body').textContent")
    check('the Full Body template’s plank is held for 30 seconds', 'Plank (30 s)' in card, card)
    cdp.ev('window.__alerts = 0; playRestAlert = () => { window.__alerts += 1; }')
    start(4)
    cdp.pause(0.3)
    check('an exercise that is not timed has no hold timer', not visible('holdTimer') and text('completedRepsLabel') == 'Reps completed')
    jump(3)
    check('a timed exercise asks for seconds', text('activeExerciseName') == 'Plank' and text('completedRepsLabel') == 'Seconds'
          and text('activeExerciseTarget') == 'Target: 30 seconds', text('activeExerciseTarget'))
    check('with a timer, ready at its target', visible('holdTimer') and field('completedReps') == '30' and text('holdDisplay') == '0:30', f"{field('completedReps')} {text('holdDisplay')}")
    set_field('completedReps', 2)
    check('which follows the seconds typed', text('holdDisplay') == '0:02', text('holdDisplay'))
    click('holdBtn')
    check('Start timer counts down', text('holdBtn') == 'Stop' and cdp.ev("document.getElementById('holdTimer').classList.contains('running')"))
    check('the set logs itself when the time is up', cdp.wait("document.querySelectorAll('#completedSets li').length === 1", 5))
    r = rows()
    check('in seconds', r == [{'reps': '2', 'unit': 's', 'label': 'Set 1 seconds'}], r)
    check('with the alert, then the rest', cdp.ev('window.__alerts') == 1 and visible('restPanel') and cdp.ev('restInterval !== null') and text('holdBtn') == 'Start timer')
    set_field('completedReps', 30)
    click('holdBtn')
    cdp.pause(1.3)
    click('holdBtn')
    check('Stop ends it early, filling in the seconds held', field('completedReps') in ('1', '2') and len(rows()) == 1 and text('holdBtn') == 'Start timer',
          f"{field('completedReps')} {rows()}")
    check('starting a hold put the rest away', not visible('restPanel'))
    set_field('completedReps', 30)
    click('holdBtn')
    cdp.pause(1.3)
    click('completeSetBtn')
    cdp.pause(0.2)
    r = rows()
    check('Complete set during a hold logs the seconds held so far', len(r) == 2 and r[1]['reps'] in ('1', '2') and cdp.ev('holdInterval') is None, r)
    set_field('completedReps', 0)
    click('completeSetBtn')
    check('a hold of nothing is refused in seconds', 'seconds held' in text('formFeedback'), text('formFeedback'))
    known = t.ids()
    finish()
    check('a timed exercise is saved as timed', wait_for(lambda: newest(known) is not None))
    plank = newest(known)['exercises'][0]
    check('with its seconds', plank['name'] == 'Plank' and plank.get('timed') is True and plank['sets'][0]['reps'] == 2, plank)
    s = summary()
    check('its seconds are not counted as volume', not any(label == 'Volume' for _, label in s['stats']), s['stats'])
    held = plank['sets'][1]['reps'] if len(plank['sets']) > 1 else None
    start(4)
    cdp.pause(0.3)
    jump(3)
    check('last time is in seconds', text('activeExerciseLast').endswith(f': 2, {held} s'), text('activeExerciseLast'))
    set_field('completedReps', 3)
    click('completeSetBtn')
    cdp.pause(0.2)
    finish()
    check('a longer hold is a record', summary()['records'] == ['Plank: held 3 s, your longest yet (was 2 s)'], summary()['records'])

    start(4)
    cdp.pause(0.3)
    cdp.ev("document.getElementById('addActiveExercise').open = true; document.getElementById('activeAddTimed').click()")
    check('Add an exercise can add a timed one', text('activeAddRepsLabel') == 'Target seconds')
    set_field('activeAddName', 'Wall Sit')
    set_field('activeAddReps', 45)
    click('activeAddBtn')
    cdp.pause(0.2)
    check('and is ready for the next', text('activeAddRepsLabel') == 'Target reps' and not cdp.ev("document.getElementById('activeAddTimed').checked"))
    click('nextExerciseBtn')
    cdp.pause(0.2)
    check('the added exercise is timed', text('activeExerciseName') == 'Wall Sit' and text('activeExerciseTarget') == 'Target: 45 seconds' and visible('holdTimer'))
    t.end_workout()

    click('createTemplateBtn')
    cdp.ev("document.querySelector('#templateExerciseEditor [data-template-field=timed]').click()")
    check('a template exercise can be timed', text('templateReps0Label') == 'Seconds')
    set_field('templateName', 'Hangs')
    set_field('templateExercise0', 'Dead Hang')
    set_field('templateReps0', 20)
    cdp.ev("document.getElementById('templateForm').requestSubmit()")
    cdp.pause(0.3)
    stored = cdp.ev("customTemplates.find(item => item.name === 'Hangs').exercises")
    card = cdp.ev("[...document.querySelectorAll('#templateList .template-card')].find(c => c.querySelector('h3').textContent === 'Hangs').textContent")
    check('and is saved that way', stored == [{'name': 'Dead Hang', 'reps': '20', 'timed': True}] and 'Dead Hang (20 s)' in card, f'{stored} {card}')

    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length > 0")
    lines = cdp.ev("[...document.querySelectorAll('.history-workout .workout-details li')].map(li => li.textContent).filter(line => line.startsWith('Plank'))")
    check('History shows holds in seconds', lines[:2] == ['Plank3 s', f'Plank2, {held} s'], lines)
    meta = cdp.ev("document.querySelector('.history-workout span').textContent")
    check('and how long each workout took', meta.endswith(' · 1 min'), meta)

    seed('Core Day', 30, [{'name': 'Plank', 'timed': True, 'weight': 0, 'reps': 90, 'sets': [{'reps': 90, 'weight': 0}]}, ex('Push-up', 0, 12, [(12, 0)])])
    cdp.goto('/progress.html')
    cdp.wait('chartData && chartData.points.length > 0')
    cdp.pause(0.3)
    series = "Object.fromEntries(chartData.types.map(type => [type.name, [...type.values.values()]]))"
    set_field('exerciseFilter', 'all')
    set_field('metricFilter', 'reps')
    cdp.pause(0.2)
    check('across all exercises, a hold is not counted as reps', cdp.ev(series).get('Core Day') == [12], cdp.ev(series).get('Core Day'))
    set_field('exerciseFilter', 'plank')
    cdp.pause(0.2)
    check('a timed exercise charts its longest hold', text('progressTitle') == 'Longest hold' and sorted(cdp.ev(series).get('Core Day', []) + cdp.ev(series).get('Full Body', [])) == sorted([90, 2, 3]),
          f"{text('progressTitle')} {cdp.ev(series)}")
    set_field('metricFilter', 'volume')
    cdp.pause(0.2)
    check('and its volume is the time held', text('progressTitle') == 'Total time held' and cdp.ev(series).get('Full Body') == [2 + held, 3], cdp.ev(series))

    # ------------------------------------------------------------------ V the server
    print('V   the server checks the new fields')

    def post(body):
        status, _, reply = t.request('POST', '/api/workouts', json.dumps(body).encode(), {'Content-Type': 'application/json'}, token=token)
        return status, reply.get('error')

    base = {'name': 'Check', 'exercises': [{'name': 'Plank', 'reps': 30, 'sets': [{'reps': 30, 'weight': 0}]}]}

    def with_exercise(**extra):
        return {**base, 'exercises': [{**base['exercises'][0], **extra}]}

    check('a rest that is not a number of seconds is refused', post(with_exercise(rest='long')) == (400, 'exercises[0].rest must be a number of seconds, up to an hour.'))
    check('nor none', post(with_exercise(rest=0))[0] == 400)
    check('nor more than an hour', post(with_exercise(rest=3601))[0] == 400)
    check('timed must be true or false', post(with_exercise(timed='yes')) == (400, 'exercises[0].timed must be true or false.'))
    check('a duration must be seconds', post({**base, 'duration': -5}) == (400, 'duration must be a number of seconds.'))
    status, _, reply = t.request('PUT', '/api/state', json.dumps({'templates': [{'name': 'T', 'exercises': [{'name': 'a', 'reps': '5', 'rest': 'x'}]}]}).encode(),
                                 {'Content-Type': 'application/json'}, token=token)
    check('templates are checked the same way', status == 400 and reply.get('error') == 'templates[0].exercises[0].rest must be a number of seconds, up to an hour.', f'{status} {reply}')
    status, error = post({**with_exercise(timed=True, rest=60), 'duration': 1800})
    check('and all of them valid are stored', status in (200, 201) and error is None, f'{status} {error}')
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
