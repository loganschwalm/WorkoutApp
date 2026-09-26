"""Kilograms: the unit setting, showing pound workouts in kilograms and back, logging in kilograms, a unit change in the
middle of a workout, Progress, and training programs in kilograms."""

import json

INTERCEPT = True

LBS_TO_KG = 0.45359237


def kg(lbs):
    """Pounds as the app converts them: to 2 decimals."""
    return round(lbs * LBS_TO_KG, 2)


def run(t):
    cdp, check, api, token, wait_for = t.cdp, t.check, t.api, t.token, t.wait_for
    open_tracker, safe_ev = t.open_tracker, t.safe_ev

    def text(idn):
        return cdp.ev(f"document.getElementById('{idn}').textContent")

    def field(idn):
        return cdp.ev(f"document.getElementById('{idn}').value")

    def set_field(idn, value):
        cdp.ev(f"(() => {{ const e = document.getElementById('{idn}'); e.value = {json.dumps(str(value))}; e.dispatchEvent(new Event('input', {{ bubbles: true }})); e.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")

    def choose_unit(unit):
        cdp.ev("document.getElementById('settingsButton').click()")
        cdp.ev(f"document.getElementById('unitSetting').value = '{unit}'; document.getElementById('settingsForm').requestSubmit()")
        cdp.pause(0.5)

    def server_settings():
        return api('GET', '/api/state', token=token)[0]['settings']

    def details(name):
        """The exercise lines of the first saved workout with this name on the Tracker, opened."""
        return cdp.ev(f"""(() => {{ const row = [...document.querySelectorAll('#savedWorkoutList .saved-workout')].find(li => li.querySelector('strong').textContent === {json.dumps(name)});
          return [...row.querySelectorAll('.workout-details li')].map(li => li.textContent); }})()""")

    def complete_set(weight, reps):
        set_field('activeWeight', weight)
        cdp.ev(f"document.getElementById('completedReps').value = '{reps}'; document.getElementById('completeSetBtn').click()")
        cdp.pause(0.2)

    def finish():
        for _ in range(8):
            if cdp.ev("document.getElementById('activeWorkout').hidden"):
                break
            cdp.ev("document.getElementById('nextExerciseBtn').click()")
            cdp.pause(0.25)
        cdp.pause(0.6)

    # ------------------------------------------------------------------ K1 the setting
    print('K1  the weight unit is a setting')
    open_tracker()
    cdp.ev("document.getElementById('settingsButton').click()")
    check('Settings offers pounds and kilograms, pounds to start', cdp.ev("[...document.getElementById('unitSetting').options].map(o => o.value)") == ['lbs', 'kg']
          and field('unitSetting') == 'lbs')
    cdp.ev("document.getElementById('cancelSettings').click()")
    choose_unit('kg')
    check('choosing kilograms is saved to the account', wait_for(lambda: server_settings().get('unit') == 'kg'), server_settings())

    # ------------------------------------------------------------------ K2 the tracker in kilograms
    print('K2  the Tracker in kilograms')
    labels = cdp.ev("[...document.querySelectorAll('.unit-label')].map(l => l.textContent)")
    check('weight labels say kg', labels == ['kg', 'kg'], labels)
    steppers = cdp.ev("[...document.querySelectorAll('#weightStepper [data-weight-step]')].map(b => [b.textContent, b.dataset.weightStep, b.getAttribute('aria-label')])")
    check('the weight buttons step 2.5 kg', steppers == [['−2.5', '-2.5', '2.5 kg lighter'], ['+2.5', '2.5', '2.5 kg heavier']], steppers)
    cdp.ev("document.querySelector('#savedWorkoutList [data-action=view]').click()")
    check('saved pound workouts are shown in kilograms', details('Seed Push') == ['Bench Press' + f'{kg(105)} kg × 8', 'Overhead Press' + f'{kg(62)} kg × 8'], details('Seed Push'))
    stored = t.workout(t.W1)
    check('while the stored workout is untouched, in pounds', stored.get('unit') is None and stored['exercises'][0]['sets'][0]['weight'] == 100, stored)

    # ------------------------------------------------------------------ K3 a workout in kilograms
    print('K3  logging a workout in kilograms')
    known = t.ids()
    cdp.ev("document.querySelector('#savedWorkoutList [data-action=start]').click()")
    cdp.pause(0.5)
    check('last time is shown in kilograms', text('activeExerciseLast').endswith(f'{kg(105)} kg × 8'), text('activeExerciseLast'))
    check('the weight to lift is rounded to the nearest half kilo', text('activeExerciseTarget') == 'Target: 8 reps at 47.5 kg'
          and field('activeWeight') == '47.5', f"{text('activeExerciseTarget')} {field('activeWeight')}")
    check('with plates for a 20 kg bar', text('plateHint') == 'Each side of a 20 kg bar: 10 + 2.5 + 1.25', text('plateHint'))
    cdp.ev("document.querySelector('#weightStepper [data-weight-step=\"2.5\"]').click()")
    check('+2.5 adds 2.5 kg', field('activeWeight') == '50' and text('plateHint') == 'Each side of a 20 kg bar: 15', f"{field('activeWeight')} {text('plateHint')}")
    complete_set(60, 5)
    row = cdp.ev("(() => { const li = document.querySelector('#completedSets li'); return [li.querySelector('[data-field=weight]').value, li.querySelector('.set-field span').textContent, li.querySelector('[data-field=weight]').getAttribute('aria-label')]; })()")
    check('the logged set says kg', row == ['60', 'kg', 'Set 1 weight in kg'], row)
    check('the workout in progress is in kilograms', safe_ev('readLocalActive().session.unit') == 'kg')
    finish()
    check('it is saved', wait_for(lambda: len(t.ids() - known) == 1))
    saved = next(w for w in t.workouts() if w['id'] not in known)
    check('in kilograms, as logged', saved.get('unit') == 'kg' and saved['exercises'][0]['sets'] == [{'reps': 5, 'weight': 60}], json.dumps(saved)[:300])

    # ------------------------------------------------------------------ K4 back to pounds
    print('K4  back to pounds')
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 4")
    choose_unit('lbs')
    lines = cdp.ev("[...document.querySelectorAll('.history-workout')].map(li => li.querySelector('.workout-details li').textContent)")
    kg_in_lbs = round(60 / LBS_TO_KG, 2)
    check('History shows the kilogram workout in pounds', lines[0] == f'Bench Press{kg_in_lbs} lbs × 5', lines[0])
    check('and the pound workouts exactly as logged', lines[1:] == ['Bench Press105 lbs × 8', 'Barbell Row80 lbs × 8', 'Bench Press2 × 8 at 100 lbs'], lines[1:])
    open_tracker()
    cdp.ev("document.querySelector('#templateList [data-template-action=start]')?.click() || document.getElementById('templatesToggle').click()")
    cdp.pause(0.2)
    cdp.ev("document.querySelector('#templateList [data-template-action=start]').click()")
    cdp.pause(0.5)
    check('last time, logged in kilograms, is shown in pounds', text('activeExerciseLast').endswith(f'{kg_in_lbs} lbs × 5'), text('activeExerciseLast'))
    check('and filled in rounded to the nearest half pound', field('activeWeight') == '132.5', field('activeWeight'))
    check('the weight buttons are back to 5 lbs', cdp.ev("document.querySelector('#weightStepper [data-weight-step]').textContent") == '−5')

    # ------------------------------------------------------------------ K5 changing unit mid-workout
    print('K5  changing the unit in the middle of a workout')
    complete_set(100, 5)
    choose_unit('kg')
    row = cdp.ev("(() => { const li = document.querySelector('#completedSets li'); return [li.querySelector('[data-field=weight]').value, li.querySelector('.set-field span').textContent]; })()")
    check('the logged set is converted', row == [str(kg(100)), 'kg'], row)
    check('and the workout in progress is saved in kilograms', safe_ev('readLocalActive().session.unit') == 'kg'
          and wait_for(lambda: (t.active_session() or {}).get('unit') == 'kg'), t.active_session())
    known = t.ids()
    finish()
    check('finishing saves it in kilograms', wait_for(lambda: len(t.ids() - known) == 1))
    saved = next(w for w in t.workouts() if w['id'] not in known)
    check('with the converted weight', saved.get('unit') == 'kg' and saved['exercises'][0]['sets'][0]['weight'] == kg(100), json.dumps(saved)[:300])

    # ------------------------------------------------------------------ K6 Progress
    print('K6  Progress in kilograms')
    cdp.goto('/progress.html')
    cdp.wait('chartData && chartData.points.length > 0')
    cdp.pause(0.3)
    set_field('exerciseFilter', 'bench press')
    cdp.pause(0.3)
    values = cdp.ev("chartData.types.flatMap(type => [...type.values.values()]).sort((a, b) => a - b)")
    check('the chart plots every workout in kilograms', values == sorted([kg(100), kg(105), 60, kg(100)]), values)
    choose_unit('lbs')
    values = cdp.ev("chartData.types.flatMap(type => [...type.values.values()]).sort((a, b) => a - b)")
    check('and redraws in pounds when the unit changes', values == sorted([100, 105, kg_in_lbs, round(kg(100) / LBS_TO_KG, 2)]), values)

    # ------------------------------------------------------------------ K7 programs in kilograms
    print('K7  a training program in kilograms')
    open_tracker()
    choose_unit('kg')
    cdp.ev("if (document.getElementById('templateArea').hidden) document.getElementById('templatesToggle').click()")
    cdp.ev("document.querySelector('#templateList .program-template[data-program-id=\"reddit-ppl\"] [data-program-action=setup]').click()")
    cdp.pause(0.3)
    rounding = cdp.ev("[...document.getElementById('programRounding').options].map(o => o.textContent)")
    check('rounding is offered in kilograms', rounding == ['The nearest 2.5 kg', 'The nearest 1.25 kg'], rounding)
    check('the lifts ask for kilograms', cdp.ev("document.querySelector('label[for=programMax-deadlift]').textContent") == 'Deadlift (kg)')
    check('and go up 5 kg for the deadlift, 2.5 for the rest', text('programHint-deadlift') == '+5 kg each good session' and text('programHint-bench') == '+2.5 kg each good session',
          text('programHint-deadlift'))
    check('the setup advice is in kilograms', 'take off 2.5 kg' in text('programIntro'), text('programIntro'))
    for lift, value in (('deadlift', 100), ('row', 50), ('bench', 60), ('press', 40), ('squat', 80)):
        set_field(f'programMax-{lift}', value)
    cdp.ev("document.getElementById('programForm').requestSubmit()")
    cdp.pause(0.5)
    numbers = cdp.ev("[...document.querySelectorAll('#programMaxes li')].map(li => li.textContent)")
    check('the working weights are in kilograms', numbers[0] == 'Deadlift100 kg+5 kg after each good session', numbers)
    check('and the plan too', 'Deadlift 1 × 5+ at 100 kg' in text('programNext'), text('programNext'))
    check('the program is saved in kilograms', wait_for(lambda: (api('GET', '/api/state', token=token)[0].get('program') or {}).get('unit') == 'kg'))
    cdp.ev("document.querySelector('#programNext [data-program-action=start]').click()")
    cdp.pause(0.4)
    complete_set(100, 7)
    finish()
    check('a good session adds 5 kg', 'Deadlift goes up to 105 kg next time.' in text('formFeedback'), text('formFeedback'))

    # ------------------------------------------------------------------ K8 converting a program
    print('K8  switching units converts the program')
    choose_unit('lbs')
    program = cdp.ev('currentProgram')
    check('its numbers land on pound steps', program['unit'] == 'lbs' and program['trainingMaxes'] == {'deadlift': 230, 'row': 110, 'bench': 130, 'press': 90, 'squat': 175},
          program['trainingMaxes'])
    check('and its rounding moves to the nearest pound choice', program['options'] == {'rounding': 5}, program['options'])
    numbers = cdp.ev("[...document.querySelectorAll('#programMaxes li')].map(li => li.textContent)")
    check('the card shows pounds', numbers[0] == 'Deadlift230 lbs+10 lbs after each good session', numbers)
    check('the converted program reaches the server', wait_for(lambda: (api('GET', '/api/state', token=token)[0].get('program') or {}).get('unit') == 'lbs'))
    choose_unit('kg')
    cdp.ev("document.querySelector('#templateList .program-template[data-program-id=\"apartment-gym\"] [data-program-action=setup]').click()")
    cdp.pause(0.3)
    check('Apartment Gym starts from 22.5 kg dumbbells and 5 kg stack plates', field('programDumbbellMax') == '22.5' and field('programMachineStep') == '5'
          and cdp.ev("document.getElementById('programDumbbellMax').selectedOptions[0].textContent") == '22.5 kg each', f"{field('programDumbbellMax')} {field('programMachineStep')}")
    card = cdp.ev("document.querySelector('#templateList .program-template[data-program-id=\"apartment-gym\"] p').textContent")
    check('and its card says so', 'dumbbells up to about 22.5 kg' in card, card)
    cdp.ev("document.getElementById('cancelProgram').click()")

    # ------------------------------------------------------------------ K8b a unit changed elsewhere
    print('K8b a unit changed on another device')
    api('PUT', '/api/state', {'settings': {**server_settings(), 'unit': 'lbs'}}, token)
    for attempt in range(3):
        # The page starts from this device's copy (kilograms) and learns of pounds from the server as it loads.
        open_tracker()
        cdp.wait("initialLoadDone")
        cdp.pause(0.3)
        cdp.ev("document.querySelector('#savedWorkoutList [data-action=view]').click()")
        shown = details('Seed Push')
        # The newest Seed Push is the one logged in kilograms in K3.
        if shown != [f'Bench Press{kg_in_lbs} lbs × 5']:
            break
    check('the saved workouts follow it, however the page load goes', shown == [f'Bench Press{kg_in_lbs} lbs × 5']
          and cdp.ev("document.querySelector('.unit-label').textContent") == 'lbs', shown)
    choose_unit('kg')

    # ------------------------------------------------------------------ K9 the server
    print('K9  the server keeps units honest')
    status, _, reply = t.request('POST', '/api/workouts', json.dumps({'name': 'Stones', 'unit': 'stone', 'exercises': []}).encode(), {'Content-Type': 'application/json'}, token=token)
    check('a workout in any other unit is refused', status == 400 and reply.get('error') == 'unit must be lbs or kg.', f'{status} {reply}')
    status, _, reply = t.request('PUT', '/api/state', json.dumps({'program': {'definition': 'reddit-ppl', 'unit': 'st', 'trainingMaxes': {}}}).encode(), {'Content-Type': 'application/json'}, token=token)
    check('and so is a program', status == 400 and reply.get('error') == 'program.unit must be lbs or kg.', f'{status} {reply}')
    stored = t.workout(t.W1)
    check('after all that, the pound workouts on the server are still exactly as logged',
          stored.get('unit') is None and [s['weight'] for s in stored['exercises'][0]['sets']] == [100, 100], stored)
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
