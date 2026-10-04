"""Same as last set (one tap logs the previous set again) and How to do it (written cues for an exercise, and a link to a
video demonstration)."""

import json

from ..harness import ACTIVE, HIDDEN

INTERCEPT = False

# What an exercise's name is given as, and the guide it should get: a specific lift before the general one it contains.
GUIDES = [
    ('Back Squat', 'Squat'), ('Goblet Squat', 'Goblet Squat'), ('Front Squat', 'Front Squat'),
    ('Dumbbell Bulgarian Split Squat', 'Bulgarian Split Squat'), ('Hack Squat', None), ('Smith Machine Squat', None),
    ('Romanian Deadlift', 'Romanian Deadlift'), ('Single-Leg Dumbbell Romanian Deadlift', 'Single-Leg Romanian Deadlift'), ('Deadlift', 'Deadlift'),
    ('Bench Press', 'Bench Press'), ('Dumbbell Bench Press', 'Dumbbell Bench Press'), ('Incline Dumbbell Press', 'Incline Press'),
    ('Incline Bench Press', 'Incline Press'), ('Machine Chest Press', 'Machine Chest Press'),
    ('Overhead Press', 'Overhead Press'), ('Seated Dumbbell Shoulder Press', 'Dumbbell Shoulder Press'),
    ('Lateral Raise', 'Lateral Raise'), ('Dumbbell Lateral Raise', 'Lateral Raise'), ('Single-Arm Cable Rear Delt Fly', 'Rear Delt Fly'), ('Face Pull', 'Face Pull'),
    ('Barbell Row', 'Barbell Row'), ('Dumbbell Row', 'Dumbbell Row'), ('Chest-Supported Dumbbell Row', 'Chest-Supported Row'),
    ('Seated Cable Row', 'Cable Row'), ('Single-Arm Cable Row', 'Cable Row'), ('Upright Row', None),
    ('Lat Pulldown', 'Lat Pulldown'), ('Single-Arm Cable Pulldown', 'Lat Pulldown'), ('Pull-up', 'Pull-up'), ('Chin-up', 'Pull-up'),
    ('Dip', 'Dip'), ('Push-up', 'Push-up'),
    ('Bicep Curl', 'Curl'), ('Dumbbell Curl', 'Curl'), ('Hammer Curl', 'Hammer Curl'), ('Dumbbell Hammer Curl', 'Hammer Curl'),
    ('Leg Curl', 'Leg Curl'), ('Lying Leg Curl', 'Leg Curl'), ('Wrist Curl', None),
    ('Tricep Pushdown', 'Tricep Pushdown'), ('Single-Arm Cable Pushdown', 'Tricep Pushdown'), ('Overhead Tricep Extension', 'Overhead Tricep Extension'),
    ('Leg Press', 'Leg Press'), ('Leg Extension', 'Leg Extension'), ('Walking Lunge', 'Lunge'), ('Hip Thrust', 'Hip Thrust'),
    ('Calf Raise', 'Calf Raise'), ('Single-Leg Dumbbell Calf Raise', 'Calf Raise'),
    ('Hanging Leg Raise', 'Hanging Leg Raise'), ('Pallof Press', 'Pallof Press'), ('Plank', 'Plank'), ('Landmine Press', None),
]


def run(t):
    cdp, check = t.cdp, t.check
    open_tracker, start = t.open_tracker, t.start

    def text(idn):
        return cdp.ev(f"document.getElementById('{idn}').textContent")

    def field(idn):
        return cdp.ev(f"document.getElementById('{idn}').value")

    def visible(idn):
        return cdp.ev(f"!document.getElementById('{idn}').hidden")

    def click(idn):
        cdp.ev(f"document.getElementById('{idn}').click()")

    def fill(weight, reps):
        cdp.ev(f"document.getElementById('activeWeight').value = '{weight}'; document.getElementById('completedReps').value = '{reps}';")

    def sets():
        return cdp.ev("activeSession.exercises[activeSession.currentIndex].sets.map(s => [s.weight, s.reps, s.rir ?? null])")

    def log(weight, reps):
        fill(weight, reps)
        click('completeSetBtn')
        cdp.pause(0.2)

    def add_exercise(name, reps, timed=False):
        cdp.ev("document.getElementById('addActiveExercise').open = true")
        cdp.ev(f"document.getElementById('activeAddName').value = {json.dumps(name)}; document.getElementById('activeAddReps').value = '{reps}'")
        if timed:
            click('activeAddTimed')
        click('activeAddBtn')
        cdp.pause(0.2)

    def go_to(name):
        cdp.ev(f"goToExercise(activeSession.exercises.findIndex(e => e.name === {json.dumps(name)}))")
        cdp.pause(0.2)

    # ------------------------------------------------------------------ R same as last set
    print('R   same as last set')
    open_tracker()
    start(0)
    cdp.wait(ACTIVE)
    cdp.pause(0.4)
    check('the first exercise is Bench Press', text('activeExerciseName') == 'Bench Press', text('activeExerciseName'))
    check('with no set logged there is nothing to repeat, so no button', not visible('repeatSetBtn'))
    log(135, 5)
    check('after a set, the button says what it would log', visible('repeatSetBtn') and text('repeatSetBtn') == 'Same as last set: 135 lbs × 5', text('repeatSetBtn'))
    check('the fields already hold that set, as before', (field('activeWeight'), field('completedReps')) == ('135', '5'))
    # What was typed for the next set is not what the button logs.
    fill(200, 3)
    click('repeatSetBtn')
    cdp.pause(0.3)
    check('one tap logs the last set again, not what the fields were changed to', sets() == [[135, 5, None], [135, 5, None]], sets())
    check('the rest timer starts, as for Complete set', visible('restPanel'))
    check('and the completed sets say two', 'Completed sets (2)' in text('completedSetsSummary'), text('completedSetsSummary'))
    click('repeatSetBtn')
    click('repeatSetBtn')
    cdp.pause(0.3)
    check('each tap is one more set', len(sets()) == 4 and all(s[:2] == [135, 5] for s in sets()), sets())

    # A set heavier than the one before is repeated at that weight.
    log(140, 4)
    click('repeatSetBtn')
    cdp.pause(0.3)
    check('after a change in weight, it repeats the new one', sets()[-2:] == [[140, 4, None], [140, 4, None]], sets())

    # How hard a set was is the new set's own: the one chosen now, not the one before.
    cdp.ev("document.querySelector('#effortChoices [data-effort=\"2\"]').click()")
    log(145, 3)
    check('the reps left are recorded on a set as always', sets()[-1] == [145, 3, 2], sets())
    click('repeatSetBtn')
    cdp.pause(0.3)
    check('a repeated set takes none from the one before', sets()[-1] == [145, 3, None], sets())
    cdp.ev("document.querySelector('#effortChoices [data-effort=\"1\"]').click()")
    click('repeatSetBtn')
    cdp.pause(0.3)
    check('unless one is chosen first', sets()[-1] == [145, 3, 1], sets())

    # The button goes with the exercise's own sets.
    click('nextExerciseBtn')
    cdp.pause(0.3)
    check('the next exercise, with none logged, has none to repeat', text('activeExerciseName') == 'Overhead Press' and not visible('repeatSetBtn'))
    click('prevExerciseBtn')
    cdp.pause(0.3)
    check('and coming back, the last of Bench Press’s sets', visible('repeatSetBtn') and text('repeatSetBtn') == 'Same as last set: 145 lbs × 3', text('repeatSetBtn'))

    # The sets survive a reload, with the button.
    cdp.pause(0.6)
    cdp.goto('/index.html')
    cdp.wait(ACTIVE)
    cdp.pause(0.6)
    check('a reload keeps the repeated sets and the button', len(sets()) == 9 and visible('repeatSetBtn'), sets())

    # A timed exercise repeats its seconds, even with its hold running.
    add_exercise('Plank', 30, timed=True)
    go_to('Plank')
    check('a timed exercise is next', cdp.ev('isTimed(activeSession.exercises[activeSession.currentIndex])') is True)
    log('', 30)
    check('its button names the seconds', text('repeatSetBtn') == 'Same as last set: 30 s', text('repeatSetBtn'))
    fill('', 45)
    click('holdBtn')
    cdp.pause(0.4)
    check('a hold is running', cdp.ev('holdInterval !== null') is True)
    click('repeatSetBtn')
    cdp.pause(0.3)
    check('repeating stops the hold and logs the 30 seconds, not those held so far', sets() == [[0, 30, None], [0, 30, None]] and cdp.ev('holdInterval === null') is True, sets())

    # A bodyweight exercise repeats its reps with no weight, and is not asked about one.
    add_exercise('Push-up', 12)
    go_to('Push-up')
    log('', 12)
    check('a bodyweight set is written as reps', text('repeatSetBtn') == 'Same as last set: 12 reps', text('repeatSetBtn'))
    click('repeatSetBtn')
    cdp.pause(0.3)
    check('and repeated as reps', sets() == [[0, 12, None], [0, 12, None]], sets())

    # The workout saves with all of them.
    known = t.ids()
    for _ in range(10):
        if cdp.ev(HIDDEN):
            break
        click('nextExerciseBtn')
        cdp.pause(0.3)
    check('the workout finishes', cdp.ev(HIDDEN) is True)
    check('and is saved with every set, repeated ones included', t.wait_for(lambda: len(t.ids() - known) == 1))
    saved = next((w for w in t.workouts() if w['id'] in t.ids() - known), None)
    bench = next((e for e in (saved or {}).get('exercises', []) if e['name'] == 'Bench Press'), {})
    check('Bench Press has the sets that were logged and repeated', [(s['weight'], s['reps']) for s in bench.get('sets', [])] == [(135, 5)] * 4 + [(140, 4)] * 2 + [(145, 3)] * 3, bench.get('sets'))

    # ------------------------------------------------------------------ G how to do it
    print('G   how to do it')
    open_tracker()
    start(0)
    cdp.wait(ACTIVE)
    cdp.pause(0.4)
    menu = "[...document.querySelectorAll('#exerciseMenu .row-menu-items button')].map(b => b.textContent)"
    check('the exercise’s menu offers it', cdp.ev(menu) == ['Swap exercise', 'How to do it', 'Add note', 'Superset with next'], cdp.ev(menu))
    check('the cues are out of the way until asked for', not visible('guidePanel') and cdp.ev("document.getElementById('guideToggle').getAttribute('aria-expanded')") == 'false')
    cdp.ev("document.getElementById('exerciseMenu').open = true")
    click('guideToggle')
    cdp.pause(0.2)
    check('choosing it opens them, and closes the menu', visible('guidePanel') and cdp.ev("document.getElementById('exerciseMenu').open") is False)
    check('as expanded to a screen reader', cdp.ev("document.getElementById('guideToggle').getAttribute('aria-expanded')") == 'true')
    check('headed with the exercise', text('guideTitle') == 'Bench Press', text('guideTitle'))
    steps = cdp.ev("[...document.querySelectorAll('#guideSteps li')].map(li => li.textContent)")
    check('with its steps in order', 3 <= len(steps) <= 5 and all(len(step) > 20 for step in steps), steps)
    check('and the usual mistake', visible('guideMistake') and text('guideMistake').startswith('Common mistake: '), text('guideMistake'))
    check('with no “no cues” message', not visible('guideNone'))
    link = cdp.ev("({ href: document.getElementById('guideVideo').href, target: document.getElementById('guideVideo').target, rel: document.getElementById('guideVideo').rel, label: document.getElementById('guideVideo').getAttribute('aria-label') })")
    check('a video search for it, opening in a new tab that cannot reach back',
          link['href'] == 'https://www.youtube.com/results?search_query=Bench%20Press%20exercise%20form' and link['target'] == '_blank' and 'noopener' in link['rel'], link)
    check('described as opening in a new tab', 'new tab' in link['label'], link)
    click('guideClose')
    check('Close puts it away', not visible('guidePanel') and cdp.ev("document.getElementById('guideToggle').getAttribute('aria-expanded')") == 'false')
    click('guideToggle')
    click('guideToggle')
    check('and the menu item toggles it', not visible('guidePanel'))
    click('guideToggle')
    click('nextExerciseBtn')
    cdp.pause(0.3)
    check('moving to the next exercise closes it', not visible('guidePanel') and text('activeExerciseName') == 'Overhead Press')
    click('guideToggle')
    check('and what it opens is that exercise’s own', text('guideTitle') == 'Overhead Press' and 'leaning back' in text('guideMistake').lower(), text('guideMistake'))

    # An exercise nothing matches still gets the video search.
    add_exercise('Sandbag Carry Thing', 10)
    go_to('Sandbag Carry Thing')
    click('guideToggle')
    check('an exercise with no cues says so', visible('guideNone') and 'no written cues for Sandbag Carry Thing' in text('guideNone') and not visible('guideMistake')
          and cdp.ev("document.querySelectorAll('#guideSteps li').length") == 0, text('guideNone'))
    check('and still links to a video search for it', 'search_query=Sandbag%20Carry%20Thing%20exercise%20form' in cdp.ev("document.getElementById('guideVideo').href"))
    add_exercise('<b>x</b> & "y"', 10)
    go_to('<b>x</b> & "y"')
    click('guideToggle')
    check('a name that looks like markup stays text', text('guideTitle') == '<b>x</b> & "y"' and cdp.ev("document.getElementById('guideTitle').children.length") == 0, text('guideTitle'))
    t.end_workout()
    cdp.pause(0.4)

    # Which guide each name gets.
    got = cdp.ev("(names => names.map(name => { const guide = guideFor(name); return guide ? guide.title : null; }))(%s)" % json.dumps([name for name, _ in GUIDES]))
    wrong = [(name, want, have) for (name, want), have in zip(GUIDES, got) if want != have]
    check('each exercise’s name gets the right guide, a specific lift before the general one', not wrong, wrong)
    check('the exercises in the programs and templates all have one', cdp.ev("""['Back Squat', 'Bench Press', 'Overhead Press', 'Deadlift', 'Barbell Row', 'Lat Pulldown', 'Dumbbell Romanian Deadlift',
        'Dumbbell Bulgarian Split Squat', 'Machine Chest Press', 'Chest-Supported Dumbbell Row', 'Seated Cable Row', 'Dumbbell Lateral Raise', 'Hanging Leg Raise', 'Pallof Press', 'Leg Press', 'Leg Curl',
        'Leg Extension', 'Calf Raise', 'Tricep Pushdown', 'Hammer Curl', 'Goblet Squat', 'Plank', 'Push-up', 'Pull-up'].filter(name => !guideFor(name))""") == [])
    check('every guide has its own title, steps and a mistake', cdp.ev("""exerciseGuides.every(g => g.title && g.steps.length >= 3 && g.steps.every(s => s.length > 20) && g.mistake.length > 10)
        && new Set(exerciseGuides.map(g => g.title)).size === exerciseGuides.length"""))
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])

    # ------------------------------------------------------------------ L on a phone
    print('L   on a phone')
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    open_tracker()
    start(0)
    cdp.wait(ACTIVE)
    cdp.pause(0.4)
    log(135, 5)
    click('guideToggle')
    cdp.pause(0.3)
    box = cdp.ev("""(() => { const r = id => document.getElementById(id).getBoundingClientRect(); const b = r('repeatSetBtn'), v = r('guideVideo'), c = r('guideClose');
        return { overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, repeatHeight: b.height, repeatWidth: b.width, videoHeight: v.height, closeHeight: c.height,
                 repeatInside: b.left >= 0 && b.right <= innerWidth, panelInside: r('guidePanel').right <= innerWidth }; })()""")
    check('the page does not scroll sideways', box['overflow'] <= 0, box)
    check('Same as last set is as wide as the card and tall enough to tap', box['repeatInside'] and box['repeatWidth'] > 250 and box['repeatHeight'] >= 44, box)
    check('the cues fit, and their link and Close are tall enough to tap', box['panelInside'] and box['videoHeight'] >= 44 and box['closeHeight'] >= 40, box)
    cdp.send('Emulation.clearDeviceMetricsOverride')
