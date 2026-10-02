"""Your own program: building a weekly split from templates, following it, editing it, and 5/3/1's First Set Last."""

import json
import time

from ..harness import ACTIVE, HIDDEN, TITLE

DAY_MS = 86400000

INTERCEPT = False

CARD = "#templateList .program-template[data-program-id='custom']"


def run(t):
    cdp, check, api = t.cdp, t.check, t.api

    def text(idn):
        return cdp.ev(f"document.getElementById('{idn}').textContent")

    def click(selector):
        cdp.ev(f"document.querySelector({json.dumps(selector)}).click()")
        cdp.pause(0.3)

    def set_value(selector, value):
        cdp.ev(f"""(e => {{ e.value = {json.dumps(value)}; e.dispatchEvent(new Event('input', {{ bubbles: true }}));
            e.dispatchEvent(new Event('change', {{ bubbles: true }})); }})(document.querySelector({json.dumps(selector)}))""")

    def builder_days():
        return cdp.ev("""[...document.querySelectorAll('#builderDays .builder-day')].map(li => ({
            name: li.querySelector('input').value, placeholder: li.querySelector('input').placeholder, template: li.querySelector('select').value }))""")

    def next_up():
        return cdp.ev("""(n => n.hidden ? null : { day: n.querySelector('strong').textContent, plan: [...n.querySelectorAll('li')].map(li => li.textContent),
            start: Boolean(n.querySelector('[data-program-action=start]')) })(document.getElementById('programNext'))""")

    def day_rows():
        return cdp.ev("[...document.querySelectorAll('#programWeeks .program-day')].map(li => li.querySelector('strong').textContent + ' | ' + li.querySelector('span').textContent)")

    def server_program():
        return api('GET', '/api/state', token=lifter)[0].get('program')

    def open_tracker():
        cdp.goto('/index.html')
        cdp.wait(f"document.querySelector({json.dumps(CARD)})")
        cdp.pause(0.6)

    cookie = api('POST', '/api/auth/register', {'username': 'splitter', 'email': 'splitter@example.test', 'password': 'chalk-and-plates-42'})[1]
    lifter = cookie.split('session=')[1].split(';')[0]
    upper = {'id': 'custom-upper', 'name': 'Upper', 'exercises': [{'name': 'Bench Press', 'reps': '8', 'setCount': 3, 'repsMax': 10},
                                                                  {'name': 'Barbell Row', 'reps': '8', 'setCount': 3, 'repsMax': 10}]}
    lower = {'id': 'custom-lower', 'name': 'Lower', 'exercises': [{'name': 'Back Squat', 'reps': '5', 'setCount': 3}]}
    api('PUT', '/api/state', {'templates': [upper, lower]}, lifter)
    # Last time: every bench set at the top of its range, so it goes up; the rows short of it, so they stay.
    api('POST', '/api/workouts', {'name': 'Upper', 'notes': '', 'createdAt': int(time.time() * 1000) - 3 * DAY_MS,
                                  'exercises': [t.ex('Bench Press', 100, 10, [(10, 100)] * 3), t.ex('Barbell Row', 95, 8, [(8, 95)] * 3)]}, lifter)
    t.set_cookie(lifter)

    # ------------------------------------------------------------------ B1 building one
    print('B1  a program is built from templates: a name and its days, in order')
    open_tracker()
    card = cdp.ev(f"document.querySelector({json.dumps(CARD)}).textContent")
    check('Your own program is offered beside the others', 'Your own program' in card and '1 to 7 days a week · built from your templates' in card
          and cdp.ev(f"!!document.querySelector({json.dumps(CARD + ' [data-program-action=build]')})") is True, card)
    click(CARD + ' [data-program-action=build]')
    check('Build program opens the builder', cdp.ev("!document.getElementById('builderModal').hidden") is True
          and text('builderModalTitle') == 'Build your program' and cdp.ev("document.activeElement.id") == 'builderName')
    check('starting from your own templates, in order, each day named after its template until you name it',
          builder_days() == [{'name': '', 'placeholder': 'Upper', 'template': 'custom-upper'}, {'name': '', 'placeholder': 'Lower', 'template': 'custom-lower'}],
          builder_days())
    click('#builderSubmit')
    check('a program needs a name', text('builderError') == 'Give your program a name.' and cdp.ev("document.activeElement.id") == 'builderName'
          and cdp.ev("!document.getElementById('builderModal').hidden") is True, text('builderError'))
    set_value('#builderName', 'Upper/Lower')
    set_value('#builderDayName0', 'Upper A')
    click('#builderAddDay')
    check('Add a day adds one doing a template not used yet', builder_days()[2]['template'] == 'built-in-0' and cdp.ev("document.activeElement.id") == 'builderDayName2',
          builder_days())
    set_value('#builderDayTemplate2', 'custom-upper')
    set_value('#builderDayName2', 'Upper B')
    click('#builderAddDay')
    click("#builderDays [data-builder-action=remove][data-index='3']")
    check('a day can be removed', len(builder_days()) == 3, builder_days())
    for _ in range(4):
        click('#builderAddDay')
    check('up to seven days', len(builder_days()) == 7 and cdp.ev("document.getElementById('builderAddDay').disabled") is True, len(builder_days()))
    for index in (6, 5, 4, 3):
        click(f"#builderDays [data-builder-action=remove][data-index='{index}']")
    click("#builderDays [data-builder-action=down][data-index='1']")
    click("#builderDays [data-builder-action=up][data-index='2']")
    check('and moved, keeping its name and template', [day['name'] or day['placeholder'] for day in builder_days()] == ['Upper A', 'Lower', 'Upper B'], builder_days())
    click('#builderSubmit')
    check('Start program closes the builder and says what is next', cdp.ev("document.getElementById('builderModal').hidden") is True
          and text('formFeedback') == 'Upper/Lower is set up. Next in Upper/Lower: Upper A.', text('formFeedback'))
    kept = t.wait_for(lambda: (server_program() or {}).get('definition') == 'custom') and server_program()
    check('the program is kept with the account: its name, and each day with its template',
          kept and kept['name'] == 'Upper/Lower' and kept['days'] == [{'name': 'Upper A', 'template': 'custom-upper'}, {'name': 'Lower', 'template': 'custom-lower'},
                                                                      {'name': 'Upper B', 'template': 'custom-upper'}], kept)
    check('its card has its name, the week and how much of it is done', text('programTitle') == 'Upper/Lower'
          and text('programSummary') == 'Week 1 · 0 of 3 workouts done', [text('programTitle'), text('programSummary')])
    check('and no numbers per lift, which the templates keep for themselves', cdp.ev("document.getElementById('programNumbersSection').hidden") is True)
    check('the next workout is the first day, its weights from the template\'s progression',
          next_up() == {'day': 'Upper A', 'plan': ['Bench Press 3 × 8–10 at 105 lbs', 'Barbell Row 3 × 8–10 at 95 lbs'], 'start': True}, next_up())
    check('each day says its template and exercises', day_rows() == ['Upper A | Upper: Bench Press, Barbell Row', 'Lower | Lower: Back Squat',
                                                                     'Upper B | Upper: Bench Press, Barbell Row'], day_rows())
    check("the program's card now leads to it", cdp.ev(f"!!document.querySelector({json.dumps(CARD + ' [data-program-action=view]')})") is True)

    # ------------------------------------------------------------------ B2 following it
    print('B2  its days are done in order, named after themselves, and their templates progress')
    click('#programNext [data-program-action=start]')
    cdp.wait(ACTIVE)
    check('Start workout begins the day, planned as its template plans it', cdp.ev(TITLE) == 'Upper A'
          and cdp.ev("document.getElementById('activeWeight').value") == '105', [cdp.ev(TITLE), cdp.ev("document.getElementById('activeWeight').value")])
    for reps in (10, 10, 10):
        t.log_set(reps)
        cdp.pause(0.2)
    click('#nextExerciseBtn')
    for reps in (8, 8, 8):
        t.log_set(reps)
        cdp.pause(0.2)
    click('#nextExerciseBtn')
    cdp.wait(HIDDEN)
    cdp.pause(0.5)
    check('finishing it says what is next', 'Next in Upper/Lower: Lower.' in text('formFeedback'), text('formFeedback'))
    saved = t.wait_for(lambda: len(api('GET', '/api/workouts', token=lifter)[0]['workouts']) == 2) and \
        max(api('GET', '/api/workouts', token=lifter)[0]['workouts'], key=lambda w: w['createdAt'])
    check('it is saved under the day\'s name, and History says which program and week',
          saved and saved['name'] == 'Upper A' and saved['program']['label'] == 'Upper/Lower · Week 1' and saved['program']['name'] == 'Upper/Lower',
          saved and {k: saved[k] for k in ('name', 'program')})
    check('the card moves on', text('programSummary') == 'Week 1 · 1 of 3 workouts done' and next_up()['day'] == 'Lower', [text('programSummary'), next_up()])
    click('#programNext [data-program-action=skip]')
    check('a day can be skipped, and the same template on a later day has gone up once every set reached the top',
          next_up() == {'day': 'Upper B', 'plan': ['Bench Press 3 × 8–10 at 110 lbs', 'Barbell Row 3 × 8–10 at 95 lbs'], 'start': True}, next_up())
    click('#programNext [data-program-action=skip]')
    check('once every day is done, the next week starts', text('programSummary') == 'Week 2 · 0 of 3 workouts done' and next_up()['day'] == 'Upper A',
          [text('programSummary'), next_up()])

    # ------------------------------------------------------------------ B3 editing it
    print('B3  a built program is edited in the builder, keeping what is done where it still applies')
    click('#programNext [data-program-action=skip]')
    cdp.ev("document.getElementById('editProgramBtn').click()")
    cdp.pause(0.3)
    check('Edit program opens the builder with the program as it is', text('builderModalTitle') == 'Edit Upper/Lower'
          and cdp.ev("document.getElementById('builderName').value") == 'Upper/Lower'
          and [day['name'] for day in builder_days()] == ['Upper A', 'Lower', 'Upper B'] and text('builderSubmit') == 'Save changes', builder_days())
    click("#builderDays [data-builder-action=up][data-index='2']")
    click('#builderSubmit')
    check('a day kept in its place with its template stays done; one moved is to do', text('programSummary') == 'Week 2 · 1 of 3 workouts done'
          and next_up()['day'] == 'Upper B' and text('formFeedback') == 'Upper/Lower updated. Next in Upper/Lower: Upper B.',
          [text('programSummary'), next_up(), text('formFeedback')])
    check('and the server has the new order', t.wait_for(lambda: [d['name'] for d in server_program()['days']] == ['Upper A', 'Upper B', 'Lower']))

    # ------------------------------------------------------------------ B4 a template taken away
    print('B4  deleting a template a day does asks first, and the day then asks for another')
    cdp.dialogs.clear()
    cdp.ev("document.querySelector('#templateList [data-template-action=delete][data-template-id=\"custom-lower\"]').click()")
    cdp.pause(0.3)
    check('deleting it says which day of the program does it', cdp.dialogs == ['Delete template “Lower”? Upper/Lower does it on Lower, which will need another template.'],
          cdp.dialogs)
    check('the day then says its template is gone', day_rows()[2] == 'Lower | Its template was deleted. Edit the program to choose another.', day_rows())
    click('#programNext [data-program-action=skip]')
    check('and when it is next, there is nothing to start, only Skip', next_up() == {'day': 'Lower', 'start': False,
                                                                                     'plan': ['Its template was deleted. Edit the program to choose another.']}, next_up())
    cdp.ev("document.getElementById('editProgramBtn').click()")
    cdp.pause(0.3)
    check('in the builder it has no template chosen', builder_days()[2]['template'] == '', builder_days())
    click('#builderSubmit')
    check('and saving asks for one', text('builderError') == 'Choose a template for day 3.' and cdp.ev("document.activeElement.id") == 'builderDayTemplate2',
          text('builderError'))
    set_value('#builderDayTemplate2', 'built-in-2')
    click('#builderSubmit')
    check('given one, the day is ready to start', next_up() and next_up()['day'] == 'Lower' and next_up()['start'] is True
          and next_up()['plan'][0].startswith('Back Squat'), next_up())

    # ------------------------------------------------------------------ B5 kept, replaced and ended
    print('B5  it survives a reload, fits a phone, and ends like any other')
    open_tracker()
    check('after a reload it is all still there', text('programTitle') == 'Upper/Lower' and text('programSummary') == 'Week 2 · 2 of 3 workouts done'
          and next_up()['day'] == 'Lower', [text('programTitle'), text('programSummary')])
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    cdp.ev("document.getElementById('editProgramBtn').click()")
    cdp.pause(0.3)
    fits = cdp.ev("(m => m.scrollWidth <= m.clientWidth && document.documentElement.scrollWidth <= innerWidth)(document.querySelector('.builder-modal'))")
    targets = cdp.ev("Math.min(...[...document.querySelectorAll('#builderDays button, #builderDays select, #builderDays input')].map(e => e.getBoundingClientRect().height))")
    check('on a phone the builder fits, with every control big enough to tap', fits is True and targets >= 44, targets)
    click('#cancelBuilder')
    cdp.send('Emulation.clearDeviceMetricsOverride')
    cdp.answer = True
    cdp.ev("document.getElementById('endProgramBtn').click()")
    cdp.pause(0.3)
    check('End program ends it, and the card offers to build one again', cdp.ev("document.getElementById('programCard').hidden") is True
          and cdp.ev(f"!!document.querySelector({json.dumps(CARD + ' [data-program-action=build]')})") is True)
    check('for good', t.wait_for(lambda: server_program() is None))

    # ------------------------------------------------------------------ B6 First Set Last
    print('B6  5/3/1 offers First Set Last: 5 x 5 at the week\'s first working set')
    choices = cdp.ev("wendler531.options.find(o => o.id === 'assistance').choices.map(c => c.label)")
    check('it is offered beside Boring But Big', choices == ['Boring But Big', 'First Set Last', 'Triumvirate', 'Main lifts only'], choices)
    fsl = cdp.ev("""[0, 1, 2, 3].map(week => wendler531.workout(normalizeProgram({ definition: 'wendler-531', unit: 'lbs',
        trainingMaxes: { press: 100, deadlift: 300, bench: 200, squat: 250 }, options: { assistance: 'fsl' } }), week, 2))
        .map(day => day.slice(1).map(e => describeExercisePlan(e)))""")
    check('weeks 1 to 3 do the first set again at 65%, 70% and 75%, then one assistance exercise',
          fsl[:3] == [['Bench Press (FSL) 5 × 5 at 130 lbs', 'Dumbbell Row 5 × 10'], ['Bench Press (FSL) 5 × 5 at 140 lbs', 'Dumbbell Row 5 × 10'],
                      ['Bench Press (FSL) 5 × 5 at 150 lbs', 'Dumbbell Row 5 × 10']], fsl)
    check('and the deload week is the main lift alone, as with the others', fsl[3] == [], fsl[3])
    t.set_cookie(t.token)
