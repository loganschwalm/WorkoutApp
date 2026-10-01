"""The exercise library: muscles and equipment guessed from names or chosen on Progress, Sets per muscle, and exercises of your own."""

import json
import time

DAY_MS = 86400000

INTERCEPT = False

# Every exercise in the built-in templates and the training programs, which should all count for some muscle.
BUILT_IN = ['Bench Press', 'Overhead Press', 'Tricep Pushdown', 'Deadlift', 'Barbell Row', 'Lat Pulldown', 'Bicep Curl', 'Back Squat',
            'Romanian Deadlift', 'Leg Press', 'Calf Raise', 'Pull-up', 'Dumbbell Row', 'Lateral Raise', 'Goblet Squat', 'Push-up', 'Plank',
            'Cable Woodchop', 'Chest-Supported Dumbbell Row', 'Chin-up', 'Dip', 'Dumbbell Bench Press', 'Dumbbell Bulgarian Split Squat',
            'Dumbbell Curl', 'Dumbbell Hammer Curl', 'Dumbbell Lateral Raise', 'Dumbbell Romanian Deadlift', 'Dumbbell Step-Up', 'Face Pull',
            'Good Morning', 'Hammer Curl', 'Hanging Leg Raise', 'Incline Dumbbell Press', 'Leg Curl', 'Leg Extension', 'Machine Chest Press',
            'Overhead Tricep Extension', 'Pallof Press', 'Seated Cable Row', 'Seated Dumbbell Shoulder Press', 'Single-Arm Cable Pulldown',
            'Single-Arm Cable Pushdown', 'Single-Arm Cable Rear Delt Fly', 'Single-Arm Cable Row', 'Single-Leg Dumbbell Calf Raise',
            'Single-Leg Dumbbell Romanian Deadlift']


def run(t):
    cdp, check = t.cdp, t.check

    def settle(path, ready):
        cdp.goto(path)
        cdp.wait(ready, timeout=10)
        cdp.pause(0.5)

    def account(name):
        cookie = t.api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'})[1]
        return cookie.split('session=')[1].split(';')[0]

    def field(idn):
        return cdp.ev(f"document.getElementById('{idn}').textContent")

    # ------------------------------------------------------------------ L1 guesses from the name
    print('L1  an exercise\'s muscle and equipment are guessed from its name')
    settle('/progress.html', "typeof guessMuscle === 'function'")
    guessed = cdp.ev(f"{json.dumps(BUILT_IN)}.filter(name => !guessMuscle(name))")
    check('every exercise in the templates and programs counts for a muscle', guessed == [], guessed)
    cases = {'Leg Curl': 'hamstrings', 'Romanian Deadlift': 'hamstrings', 'Bicep Curl': 'biceps', 'Incline Dumbbell Curl': 'biceps',
             'Incline Dumbbell Press': 'chest', 'Chest-Supported Dumbbell Row': 'back', 'Upright Row': 'shoulders', 'Barbell Row': 'back',
             'Close-Grip Bench Press': 'triceps', 'Bench Press': 'chest', 'Single-Arm Cable Rear Delt Fly': 'shoulders', 'Cable Fly': 'chest',
             'Back Squat': 'quads', 'Hanging Leg Raise': 'core', 'Single-Leg Dumbbell Calf Raise': 'calves', 'Hip Thrust': 'glutes',
             'Glute-Ham Raise': 'hamstrings', 'Pallof Press': 'core', 'Thruster': ''}
    muscles = cdp.ev(f"Object.fromEntries({json.dumps(list(cases))}.map(name => [name, guessMuscle(name)]))")
    check('a name with words of two muscles goes to the one it works most', muscles == cases,
          {name: muscle for name, muscle in (muscles or {}).items() if cases.get(name) != muscle})
    kinds = {'Bench Press': 'barbell', 'Dumbbell Bench Press': 'dumbbell', 'Goblet Squat': 'dumbbell', 'Lat Pulldown': 'machine', 'Leg Press': 'machine',
             'Single-Arm Cable Pulldown': 'cable', 'Tricep Pushdown': 'cable', 'Pull-up': 'bodyweight', 'Bench Dips': 'bodyweight',
             'Kettlebell Swing': 'kettlebell', 'Romanian Deadlift': 'barbell', 'Calf Raise': ''}
    equipment = cdp.ev(f"Object.fromEntries({json.dumps(list(kinds))}.map(name => [name, guessEquipment(name)]))")
    check('and the equipment, a barbell only where the plates have always said so', equipment == kinds,
          {name: kind for name, kind in (equipment or {}).items() if kinds.get(name) != kind})

    # ------------------------------------------------------------------ L2 sets per muscle, a week at a time
    print('L2  Sets per muscle counts a week\'s sets by muscle, beside the average of the weeks before')
    counter = account('counter')
    now = int(time.time() * 1000)
    ex = t.ex

    def lift(name, when, *exercises):
        t.api('POST', '/api/workouts', {'name': name, 'notes': '', 'createdAt': when, 'exercises': list(exercises)}, counter)

    lift('Push', now, ex('Bench Press', 135, 5, [(5, 135)] * 3), ex('Incline Dumbbell Press', 50, 10, [(10, 50)] * 2),
         ex('Barbell Row', 95, 8, [(8, 95)] * 4), ex('Thruster', 65, 10, [(10, 65)] * 2), ex('Leg Curl', 70, 12, []))
    # Saved from the workout form, without sets: its weight and reps are its one set.
    lift('Form', now, {'name': 'Squat', 'weight': '185', 'reps': '5'})
    lift('Push', now - 7 * DAY_MS, ex('Bench Press', 135, 5, [(5, 135)] * 3))
    lift('Push', now - 14 * DAY_MS, ex('Bench Press', 135, 5, [(5, 135)] * 3))
    lift('Legs', now - 21 * DAY_MS, ex('Squat', 185, 5, [(5, 185)] * 5))
    # Five weeks back: the first workout, before the four weeks this week is measured against.
    lift('Push', now - 35 * DAY_MS, ex('Bench Press', 135, 5, [(5, 135)] * 10))
    t.set_cookie(counter)
    rows = ("[...document.querySelectorAll('#muscleList [data-muscle]')].map(row => [row.querySelector('.muscle-name').textContent, "
            "row.querySelector('.muscle-count').textContent])")
    settle('/progress.html', "document.querySelectorAll('#muscleList [data-muscle]').length > 0")
    check("this week's sets, a muscle a line in the same order every week, with the average of the four weeks before",
          cdp.ev(rows) == [['Chest', '5 sets · avg 1.5'], ['Back', '4 sets · avg 0'], ['Quads', '1 set · avg 1.3']], cdp.ev(rows))
    check('the summary says which week, and how many sets were counted', field('musclesSummary').startswith('This week, ')
          and field('musclesSummary').endswith(' · 10 sets'), field('musclesSummary'))
    check('a skipped exercise counts nothing, and one saved without sets counts as one', 'Hamstrings' not in str(cdp.ev(rows)))
    bars = cdp.ev("Object.fromEntries([...document.querySelectorAll('#muscleList [data-muscle]')].map(row => [row.dataset.muscle, "
                  "[row.querySelector('.muscle-fill').getBoundingClientRect().width / row.querySelector('.muscle-bar').clientWidth, "
                  "row.querySelector('.muscle-average').offsetLeft / row.querySelector('.muscle-bar').clientWidth]]))")
    near = lambda value, expected: value is not None and abs(value - expected) < 0.02
    check('each bar is drawn to its sets, the most the whole width', bars and near(bars['chest'][0], 1) and near(bars['back'][0], 0.8)
          and near(bars['quads'][0], 0.2), bars)
    check('with a mark at the average', bars and near(bars['chest'][1], 0.3) and near(bars['quads'][1], 0.25), bars)
    check('which is explained under them', not cdp.ev("document.getElementById('musclesKey').hidden")
          and 'over the 4 weeks before' in field('musclesKey'), field('musclesKey'))
    check('an exercise with no muscle is named as not counted, with a way to give it one',
          not cdp.ev("document.getElementById('musclesUncounted').hidden") and field('musclesUncountedNames') == 'Not counted, with no muscle yet: Thruster.',
          field('musclesUncountedNames'))
    check('there is no week after this one', cdp.ev("document.getElementById('musclesLater').disabled") is True
          and cdp.ev("document.getElementById('musclesEarlier').disabled") is False)

    cdp.ev("document.getElementById('musclesEarlier').click()")
    cdp.pause(0.2)
    check('the week before is measured against the four before it', field('musclesSummary').startswith('Last week, ')
          and cdp.ev(rows) == [['Chest', '3 sets · avg 3.3'], ['Quads', '0 sets · avg 1.3']], [field('musclesSummary'), cdp.ev(rows)])
    for _ in range(4):
        cdp.ev("document.getElementById('musclesEarlier').click()")
    cdp.pause(0.2)
    check('the first week trained has nothing before it to average, and no week before it to go to',
          cdp.ev(rows) == [['Chest', '10 sets']] and cdp.ev("document.getElementById('musclesKey').hidden") is True
          and cdp.ev("document.getElementById('musclesEarlier').disabled") is True, cdp.ev(rows))
    cdp.ev("document.getElementById('musclesLater').click()")
    cdp.pause(0.2)
    check('a week with nothing logged still shows what the week before had', cdp.ev(rows) == [['Chest', '0 sets · avg 10']]
          and field('musclesKey') == 'The mark on each bar, and avg, is the sets a week over the week before.', [cdp.ev(rows), field('musclesKey')])

    # ------------------------------------------------------------------ L3 the Exercises card
    print('L3  Exercises chooses the muscle and equipment of each exercise, and adds exercises of your own')
    settle('/progress.html', "document.querySelectorAll('#muscleList [data-muscle]').length > 0")
    library_rows = "[...document.querySelectorAll('#libraryList li[data-key]')].map(li => li.dataset.name)"
    check('every exercise logged is listed, A to Z, folded away under how many there are and how many have no muscle',
          cdp.ev(library_rows) == ['Barbell Row', 'Bench Press', 'Incline Dumbbell Press', 'Leg Curl', 'Squat', 'Thruster']
          and field('librarySummary') == 'Show your 6 exercises · 1 with no muscle' and cdp.ev("document.getElementById('libraryDetails').open") is False,
          [cdp.ev(library_rows), field('librarySummary')])

    def row(name):
        return cdp.ev(f"""(li => li && {{ note: li.querySelector('.library-name span')?.textContent || '',
            muscle: li.querySelector('[data-field=muscle]').value, equipment: li.querySelector('[data-field=equipment]').value,
            remove: Boolean(li.querySelector('[data-library-remove]')) }})
            ([...document.querySelectorAll('#libraryList li[data-key]')].find(li => li.dataset.name === {json.dumps(name)}))""")

    check('a guess says it is one', row('Bench Press') == {'note': 'Guessed from its name', 'muscle': 'chest', 'equipment': 'barbell', 'remove': False},
          row('Bench Press'))
    check('and an exercise the name says nothing of says its sets are not counted',
          row('Thruster') == {'note': 'Its sets are not counted until it has a muscle', 'muscle': '', 'equipment': '', 'remove': False}, row('Thruster'))

    def choose(name, which, value):
        cdp.ev(f"""(li => {{ const select = li.querySelector('[data-field={which}]'); select.value = {json.dumps(value)};
            select.dispatchEvent(new Event('change', {{ bubbles: true }})); }})
            ([...document.querySelectorAll('#libraryList li[data-key]')].find(li => li.dataset.name === {json.dumps(name)}))""")
        cdp.pause(0.2)

    cdp.ev("document.getElementById('musclesUncountedLink').click()")
    cdp.pause(0.4)
    check('Give them a muscle opens the list at the first exercise with none', cdp.ev("document.getElementById('libraryDetails').open") is True
          and cdp.ev("document.activeElement.closest('li')?.dataset.name") == 'Thruster', cdp.ev("document.activeElement.outerHTML"))
    choose('Thruster', 'muscle', 'quads')
    check('choosing a muscle counts its sets for it at once', cdp.ev(rows) == [['Chest', '5 sets · avg 1.5'], ['Back', '4 sets · avg 0'],
                                                                              ['Quads', '3 sets · avg 1.3']]
          and cdp.ev("document.getElementById('musclesUncounted').hidden") is True, cdp.ev(rows))
    check('and says so, keeping the keyboard on the same choice', field('libraryFeedback') == 'Thruster counts for Quads.'
          and cdp.ev("document.activeElement.dataset.field + ' ' + document.activeElement.closest('li').dataset.name") == 'muscle Thruster',
          field('libraryFeedback'))
    check('the equipment still to be guessed', row('Thruster')['note'] == '' and row('Thruster')['equipment'] == '', row('Thruster'))
    choose('Incline Dumbbell Press', 'muscle', 'shoulders')
    check('a guess can be changed', cdp.ev(rows)[:3] == [['Chest', '3 sets · avg 1.5'], ['Back', '4 sets · avg 0'], ['Shoulders', '2 sets · avg 0']]
          and row('Incline Dumbbell Press')['note'] == 'Equipment guessed from its name', [cdp.ev(rows), row('Incline Dumbbell Press')])
    choose('Squat', 'equipment', 'machine')
    kept = t.wait_for(lambda: len(t.api('GET', '/api/state', token=counter)[0].get('exerciseLibrary', {})) == 3) \
        and t.api('GET', '/api/state', token=counter)[0]['exerciseLibrary']
    check('the choices are kept with the account, by exercise, leaving the rest to the guess',
          kept == {'thruster': {'name': 'Thruster', 'muscle': 'quads', 'equipment': ''},
                   'incline dumbbell press': {'name': 'Incline Dumbbell Press', 'muscle': 'shoulders', 'equipment': ''},
                   'squat': {'name': 'Squat', 'muscle': '', 'equipment': 'machine'}}, kept)
    settle('/progress.html', "document.querySelectorAll('#muscleList [data-muscle]').length > 0 && document.querySelectorAll('#libraryList li[data-key]').length > 0")
    check('and are there when the page opens again', row('Thruster')['muscle'] == 'quads' and 'Shoulders' in str(cdp.ev(rows)), cdp.ev(rows))

    cdp.ev("document.getElementById('libraryDetails').open = true")

    def search(words):
        cdp.ev(f"(i => {{ i.value = {json.dumps(words)}; i.dispatchEvent(new Event('input')); }})(document.getElementById('librarySearch'))")
        cdp.pause(0.2)

    search('press ben')
    check('the list can be searched, every word in the name', cdp.ev(library_rows) == ['Bench Press'], cdp.ev(library_rows))
    search('zzz')
    check('and says when nothing matches', cdp.ev("document.querySelector('#libraryList .empty')?.textContent") == 'No exercise has those words in its name.')
    search('')

    def add(name, muscle='', equipment=''):
        cdp.ev(f"(n => {{ n.value = {json.dumps(name)}; n.dispatchEvent(new Event('input')); }})(document.getElementById('libraryName'))")
        cdp.ev(f"document.getElementById('libraryMuscle').value = {json.dumps(muscle)}; document.getElementById('libraryEquipment').value = {json.dumps(equipment)};"
               "document.querySelector('#libraryForm button[type=submit]').click()")
        cdp.pause(0.3)

    add('')
    check('a new exercise needs a name', field('libraryFeedback') == "Enter the new exercise's name." and len(cdp.ev(library_rows)) == 6, field('libraryFeedback'))
    cdp.ev("(n => { n.value = 'Cable Fly'; n.dispatchEvent(new Event('input')); })(document.getElementById('libraryName'))")
    hints = cdp.ev("[document.getElementById('libraryMuscle').options[0].textContent, document.getElementById('libraryEquipment').options[0].textContent]")
    check('its choices say what would be guessed as the name is typed', hints == ['Guess: Chest', 'Guess: Cable'], hints)
    add('Landmine Press', 'shoulders', 'other')
    check('a new exercise is added with its muscle', field('libraryFeedback') == 'Added Landmine Press, for Shoulders. It is suggested wherever you type an exercise.'
          and row('Landmine Press') == {'note': 'Your own, not logged yet', 'muscle': 'shoulders', 'equipment': 'other', 'remove': True},
          [field('libraryFeedback'), row('Landmine Press')])
    check('and the form is cleared for the next', cdp.ev("document.getElementById('libraryName').value") == ''
          and cdp.ev("document.getElementById('libraryMuscle').value") == '')
    add('thruster', '', 'barbell')
    check("adding one already there changes only what was chosen, under the exercise's own spelling",
          field('libraryFeedback') == 'Updated Thruster.' and row('Thruster')['muscle'] == 'quads' and row('Thruster')['equipment'] == 'barbell',
          [field('libraryFeedback'), row('Thruster')])
    add('Sled Push')
    check('one whose name says nothing is added with no muscle', row('Sled Push') and row('Sled Push')['muscle'] == ''
          and field('libraryFeedback').startswith('Added Sled Push. '), [field('libraryFeedback'), row('Sled Push')])
    cdp.ev("[...document.querySelectorAll('#libraryList li[data-key]')].find(li => li.dataset.name === 'Sled Push').querySelector('[data-library-remove]').click()")
    cdp.pause(0.3)
    check('an exercise of your own can be removed until it is logged', row('Sled Push') is None and field('libraryFeedback') == 'Removed Sled Push.')
    check('for good', t.wait_for(lambda: 'sled push' not in t.api('GET', '/api/state', token=counter)[0]['exerciseLibrary']
                                 and 'landmine press' in t.api('GET', '/api/state', token=counter)[0]['exerciseLibrary']))

    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    settle('/progress.html', "document.querySelectorAll('#muscleList [data-muscle]').length > 0")
    cdp.ev("document.getElementById('libraryDetails').open = true")
    cdp.pause(0.2)
    fits = cdp.ev("""['musclesCard', 'exercisesCard'].map(id => document.getElementById(id))
        .every(card => card.scrollWidth <= card.clientWidth) && document.documentElement.scrollWidth <= innerWidth""")
    check('on a phone both cards fit, with no sideways scrolling', fits is True)
    bar = cdp.ev("document.querySelector('#muscleList .muscle-bar').clientWidth")
    check('and the bars still have room to tell muscles apart', bar >= 60, bar)
    cdp.send('Emulation.clearDeviceMetricsOverride')

    # ------------------------------------------------------------------ L4 the Tracker
    print('L4  on the Tracker, your exercises are suggested and their equipment decides the plates')
    t.open_tracker()
    suggested = cdp.ev("[...document.querySelectorAll('#exerciseNames option')].map(o => o.value)")
    check('an exercise of your own is suggested before it is ever logged', 'Landmine Press' in suggested, suggested)
    t.start(0)
    cdp.wait("!document.getElementById('activeWorkout').hidden")
    cdp.ev("(i => { i.value = '135'; i.dispatchEvent(new Event('input', { bubbles: true })); })(document.getElementById('activeWeight'))")
    cdp.pause(0.2)
    plates = lambda: None if cdp.ev("document.getElementById('plateHint').hidden") else field('plateHint')
    check('a Bench Press is a barbell lift by its name, so it gets plates', cdp.ev("document.getElementById('activeExerciseName').textContent") == 'Bench Press'
          and plates() is not None, plates())
    cdp.ev("setExerciseDetails('Bench Press', { equipment: 'machine' }); showPlates()")
    check('marked as done on a machine, it gets none', plates() is None and cdp.ev("document.getElementById('warmupHint').hidden") is True, plates())
    cdp.ev("setExerciseDetails('Bench Press', { equipment: '' }); showPlates()")
    check('and back to the guess, they return', plates() is not None, plates())
    t.end_workout()
    t.set_cookie(t.token)
