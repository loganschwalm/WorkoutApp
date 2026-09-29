"""Help while training: notes kept with an exercise, going heavier when every set reached its target, warm-up sets for
barbell lifts, how many reps each set had left, the past sessions of an exercise (in a workout and on Progress), and
supersets, made mid-workout or in a template."""

import json

from ..harness import ACTIVE, HIDDEN

INTERCEPT = True


def run(t):
    cdp, check, api, token, wait_for = t.cdp, t.check, t.api, t.token, t.wait_for
    open_tracker, seed, ex = t.open_tracker, t.seed, t.ex

    def text(idn):
        return cdp.ev(f"document.getElementById('{idn}').textContent")

    def visible(idn):
        return cdp.ev(f"!document.getElementById('{idn}').hidden")

    def set_field(idn, value):
        cdp.ev(f"(() => {{ const e = document.getElementById('{idn}'); e.value = {json.dumps(str(value))}; e.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()")

    def click(idn):
        cdp.ev(f"document.getElementById('{idn}').click()")
        cdp.pause(0.2)

    def log(weight, reps):
        cdp.ev(f"document.getElementById('activeWeight').value = '{weight}'; document.getElementById('completedReps').value = '{reps}'; document.getElementById('completeSetBtn').click();")
        cdp.pause(0.2)

    def start_saved(workout_id):
        cdp.goto(f'/index.html?start={workout_id}')
        cdp.wait(ACTIVE)
        cdp.pause(0.5)

    def end():
        t.end_workout()

    def finish():
        for _ in range(10):
            if cdp.ev(HIDDEN):
                break
            click('nextExerciseBtn')
        cdp.pause(0.6)

    def current():
        return text('activeExerciseName')

    def settings(**checks):
        cdp.ev("document.getElementById('settingsButton').click()")
        for element, value in checks.items():
            cdp.ev(f"document.getElementById('{element}').checked = {str(value).lower()}")
        cdp.ev("document.getElementById('settingsForm').requestSubmit()")
        cdp.pause(0.3)

    lift_day = seed('Lift Day', 5, [ex('Bench Press', 100, 8, [(8, 100), (8, 100), (8, 100)]), ex('Barbell Row', 80, 8, [(8, 80), (8, 80)]),
                                    ex('Curl', 30, 10, [(10, 30)])])
    heavy_day = seed('Heavy Day', 6, [ex('Back Squat', 200, 5, [(5, 200), (5, 200), (5, 200)])])
    fade_day = seed('Fade Day', 7, [ex('Deadlift', 300, 5, [(5, 300), (5, 300), (3, 300)])])
    t.api('POST', '/api/workouts', {'name': 'Grind Day', 'notes': '', 'createdAt': t.t0 + 8 * 86400000,
                                    'exercises': [{'name': 'Pendlay Row', 'weight': 150, 'reps': 8,
                                                   'sets': [{'weight': 150, 'reps': 8, 'rir': 1}, {'weight': 150, 'reps': 8, 'rir': 0}]}]}, token)
    grind_day = [w for w in t.workouts() if w['name'] == 'Grind Day'][0]['id']

    # ------------------------------------------------------------------ N notes kept with an exercise
    print('N   a note kept with an exercise shows whenever it comes up')
    start_saved(lift_day)
    check('no note yet, and a button to add one', not visible('exerciseNote') and text('noteToggle') == 'Add note')
    click('noteToggle')
    check('which opens a place to write it', visible('notePanel') and cdp.ev('document.activeElement.id') == 'noteText')
    set_field('noteText', 'Grip on the rings\nFeet flat')
    click('noteSave')
    check('the note shows under the exercise', visible('exerciseNote') and text('exerciseNote') == 'Grip on the rings\nFeet flat' and not visible('notePanel'), text('exerciseNote'))
    check('and the button offers to edit it', text('noteToggle') == 'Edit note')
    check('it reaches the account', wait_for(lambda: api('GET', '/api/state', token=token)[0].get('exerciseNotes') == {'bench press': 'Grip on the rings\nFeet flat'}),
          api('GET', '/api/state', token=token)[0].get('exerciseNotes'))
    click('nextExerciseBtn')
    check('another exercise does not show it', current() == 'Barbell Row' and not visible('exerciseNote'))
    end()
    open_tracker()
    t.start(0)  # Push Day: Bench Press first
    cdp.pause(0.4)
    check('another workout with the same exercise shows it too', current() == 'Bench Press' and text('exerciseNote') == 'Grip on the rings\nFeet flat')
    cdp.send('Page.reload')
    cdp.wait(ACTIVE)
    cdp.pause(0.6)
    check('and so does the page after a reload', text('exerciseNote') == 'Grip on the rings\nFeet flat')
    click('noteToggle')
    check('editing starts from the note as it is', cdp.ev("document.getElementById('noteText').value") == 'Grip on the rings\nFeet flat')
    set_field('noteText', '   ')
    click('noteSave')
    check('saving it empty removes it', not visible('exerciseNote') and text('noteToggle') == 'Add note'
          and wait_for(lambda: api('GET', '/api/state', token=token)[0].get('exerciseNotes') == {}))
    click('noteToggle')
    set_field('noteText', 'Grip on the rings')
    click('noteSave')
    end()

    # ------------------------------------------------------------------ H going heavier
    print('H   going heavier once every set reached its target')
    start_saved(heavy_day)
    check('every set at 200 × 5 last time: go heavier', visible('progressionHint')
          and text('progressionText') == 'Last time every set at 200 lbs reached 5 reps: time to go heavier.' and text('progressionUse') == 'Use 205 lbs',
          f"{visible('progressionHint')} {text('progressionText')} {text('progressionUse')}")
    click('progressionUse')
    check('one tap fills in the heavier weight', cdp.ev("document.getElementById('activeWeight').value") == '205')
    log(205, 5)
    check('and once a set is logged the hint has done its job', not visible('progressionHint'))
    end()
    start_saved(fade_day)
    check('a set that fell short (5, 5, 3) means staying at the weight', not visible('progressionHint'))
    end()
    start_saved(grind_day)
    check('so does a set with no reps left, even at the target', not visible('progressionHint'))
    end()

    # ------------------------------------------------------------------ W warm-up sets
    print('W   warm-up sets for a barbell lift')
    start_saved(heavy_day)
    check('the ramp to 200 lbs: the bar, then about 40%, 60% and 80%', visible('warmupHint')
          and text('warmupHint') == 'Warm up first: 45 × 10, 80 × 5, 120 × 3, 160 × 2 (lbs)', text('warmupHint'))
    click('progressionUse')
    check('it follows the weight to lift', text('warmupHint') == 'Warm up first: 45 × 10, 80 × 5, 125 × 3, 165 × 2 (lbs)', text('warmupHint'))
    log(205, 5)
    check('and goes once the first working set is done', not visible('warmupHint'))
    end()
    start_saved(lift_day)
    jump = "if (document.getElementById('exerciseJump').hidden) document.getElementById('activeWorkoutProgress').click(); document.querySelector('#exerciseJump [data-jump=\"2\"]').click()"
    cdp.ev(jump)
    cdp.pause(0.2)
    check('not for a lift without a barbell', current() == 'Curl' and not visible('warmupHint'))
    end()
    settings(warmupSetting=False)
    start_saved(heavy_day)
    check('and not at all with warm-ups turned off in Settings', not visible('warmupHint'))
    end()
    settings(warmupSetting=True)

    # ------------------------------------------------------------------ E effort
    print('E   how many reps each set had left')
    start_saved(lift_day)
    check('asked, but optional: nothing chosen yet', visible('effortChoices')
          and cdp.ev("[...document.querySelectorAll('#effortChoices [aria-pressed=true]')].length") == 0)
    cdp.ev("document.querySelector('#effortChoices [data-effort=\"2\"]').click()")
    check('tapping one chooses it', cdp.ev("document.querySelector('#effortChoices [data-effort=\"2\"]').getAttribute('aria-pressed')") == 'true')
    log(100, 8)
    check('the set keeps it, and says so', cdp.ev('activeSession.exercises[0].sets[0].rir') == 2
          and cdp.ev("document.querySelector('#completedSets .set-effort').textContent") == '2 left', cdp.ev('activeSession.exercises[0].sets[0]'))
    check('the next set starts with nothing chosen', cdp.ev("[...document.querySelectorAll('#effortChoices [aria-pressed=true]')].length") == 0)
    cdp.ev("document.querySelector('#effortChoices [data-effort=\"4\"]').click(); document.querySelector('#effortChoices [data-effort=\"4\"]').click()")
    check('tapping the chosen one again takes it back', cdp.ev("[...document.querySelectorAll('#effortChoices [aria-pressed=true]')].length") == 0)
    cdp.ev("document.querySelector('#effortChoices [data-effort=\"0\"]').click()")
    log(100, 8)
    log(100, 7)
    check('each set has its own, or none', cdp.ev('activeSession.exercises[0].sets.map(s => s.rir ?? null)') == [2, 0, None])
    known = {w['id'] for w in t.workouts()}
    finish()
    saved = [w for w in t.workouts() if w['id'] not in known]
    check('the saved workout keeps them', saved and [s.get('rir') for s in saved[0]['exercises'][0]['sets']] == [2, 0, None],
          saved[0]['exercises'][0]['sets'] if saved else 'none')
    settings(effortSetting=False)
    start_saved(lift_day)
    check('turned off in Settings, it is not asked', not visible('effortChoices'))
    log(100, 8)
    check('and nothing is recorded', cdp.ev("'rir' in activeSession.exercises[0].sets[0]") is False)
    end()
    settings(effortSetting=True)

    # ------------------------------------------------------------------ P past sessions
    print('P   the past sessions of an exercise')
    start_saved(lift_day)
    sessions = cdp.ev("[...document.querySelectorAll('#pastSessionList li')].map(li => [...li.querySelectorAll('span')].map(s => s.textContent))") or []
    check('in a workout, the last few times it was done, newest first', visible('pastSessions') and 1 < len(sessions) <= 5
          and sessions[0][1] == '100 lbs × 8, 8, 7 · reps left 2, 0' and 'Lift Day' in sessions[0][0], sessions)
    check('with older workouts too', any(line[1] == '105 lbs × 8' and 'Seed Push' in line[0] for line in sessions), sessions)
    link = cdp.ev("document.getElementById('exerciseHistoryLink').getAttribute('href')")
    check('and a link to every session', link == 'progress.html?exercise=bench%20press', link)
    end()
    cdp.goto('/' + link)
    cdp.wait("!document.getElementById('sessionsCard').hidden && document.querySelectorAll('#sessionList li').length > 0")
    cdp.pause(0.3)
    all_sessions = cdp.ev("[...document.querySelectorAll('#sessionList li')].map(li => li.textContent)") or []
    bench_workouts = [w for w in t.workouts() if any(e['name'] == 'Bench Press' and e.get('sets') for e in w['exercises'])]
    check('Progress opens on that exercise', cdp.ev("document.getElementById('exerciseFilter').value") == 'bench press'
          and text('sessionsTitle') == 'Every session of Bench Press')
    check('and lists every session of it, newest first', len(all_sessions) == len(bench_workouts) and all_sessions[0].endswith('100 lbs × 8, 8, 7 · reps left 2, 0'),
          (len(all_sessions), len(bench_workouts), all_sessions[:2]))
    check('with the note kept with it', visible('sessionsNote') and text('sessionsNote') == 'Your note: Grip on the rings', text('sessionsNote'))
    cdp.ev("(e => { e.value = 'all'; e.dispatchEvent(new Event('change')); })(document.getElementById('exerciseFilter'))")
    cdp.pause(0.2)
    check('across all exercises there is no such list', not visible('sessionsCard'))
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length > 0")
    href = cdp.ev("[...document.querySelectorAll('.workout-details li strong a')].find(a => a.textContent === 'Barbell Row').getAttribute('href')")
    check('History links each exercise to it', href == 'progress.html?exercise=barbell%20row', href)

    # ------------------------------------------------------------------ S supersets
    print('S   supersets made mid-workout and in a template')
    start_saved(lift_day)
    check('an exercise can be paired with the next', visible('supersetToggle') and text('supersetToggle') == 'Superset with next')
    click('supersetToggle')
    check('which makes them a superset', visible('supersetLine') and text('supersetLine') == 'Superset with Barbell Row: a set of each in turn, then rest.'
          and text('supersetToggle') == 'Leave superset', text('supersetLine'))
    log(100, 8)
    check('a set goes straight on to the other, with no rest', current() == 'Barbell Row' and not visible('restPanel'))
    log(80, 8)
    check('which ends the round: rest, and back to the first', current() == 'Bench Press' and visible('restPanel'))
    cdp.ev("document.getElementById('addActiveExercise').open = true")
    set_field('activeAddName', 'Face Pull')
    set_field('activeAddReps', 15)
    click('activeAddBtn')
    check('an exercise added mid-superset goes after it, not into it', cdp.ev('activeSession.exercises.map(e => e.name)') == ['Bench Press', 'Barbell Row', 'Face Pull', 'Curl'],
          cdp.ev('activeSession.exercises.map(e => e.name)'))
    click('supersetToggle')
    check('leaving it undoes the superset for both', cdp.ev('activeSession.exercises.map(e => e.group || null)') == [None, None, None, None] and not visible('supersetLine'))
    end()

    open_tracker()
    click('templatesToggle')
    click('createTemplateBtn')
    cdp.ev("""(() => {
      document.getElementById('templateName').value = 'Arms';
      const rows = [['Curl', 10], ['Tricep Pushdown', 12], ['Plank', 30]];
      rows.slice(1).forEach(() => document.getElementById('addTemplateExercise').click());
      rows.forEach(([name, reps], index) => {
        const nameField = document.getElementById(`templateExercise${index}`); nameField.value = name; nameField.dispatchEvent(new Event('input', { bubbles: true }));
        const repsField = document.getElementById(`templateReps${index}`); repsField.value = String(reps); repsField.dispatchEvent(new Event('input', { bubbles: true }));
      });
    })()""")
    boxes = cdp.ev("document.querySelectorAll('#templateExerciseEditor [data-template-field=superset]').length")
    check('the template editor offers a superset with the next on all but the last', boxes == 2, boxes)
    cdp.ev("(b => { b.checked = true; b.dispatchEvent(new Event('input', { bubbles: true })); })(document.querySelector('#templateExerciseEditor [data-template-field=superset][data-index=\"0\"]'))")
    cdp.ev("document.getElementById('templateForm').requestSubmit()")
    cdp.pause(0.4)
    arms = [x for x in api('GET', '/api/state', token=token)[0]['templates'] if x['name'] == 'Arms'] if wait_for(
        lambda: any(x['name'] == 'Arms' for x in api('GET', '/api/state', token=token)[0]['templates'])) else []
    groups = [e.get('group') for e in arms[0]['exercises']] if arms else []
    check('the template keeps the first two as a superset', len(groups) == 3 and groups[0] and groups[0] == groups[1] and groups[2] is None, groups)
    cdp.ev("[...document.querySelectorAll('#templateList [data-template-action=edit]')].find(b => b.closest('.template-card').textContent.includes('Arms')).click()")
    cdp.pause(0.2)
    ticks = cdp.ev("[...document.querySelectorAll('#templateExerciseEditor [data-template-field=superset]')].map(b => b.checked)")
    check('editing it again shows the superset ticked', ticks == [True, False], ticks)
    click('cancelTemplate')
    cdp.ev("[...document.querySelectorAll('#templateList [data-template-action=start]')].find(b => b.closest('.template-card').textContent.includes('Arms')).click()")
    cdp.pause(0.4)
    check('and starting it does them as a superset', current() == 'Curl' and text('supersetLine') == 'Superset with Tricep Pushdown: a set of each in turn, then rest.',
          text('supersetLine'))
    end()
    # ------------------------------------------------------------------ a new personal record sets off a firework
    print('F   a set that beats your best sets off a firework, once per new record')
    open_tracker()
    cdp.ev("personalBests = { [exerciseKey('Bench Press')]: { weight: 100, oneRepMax: 115, reps: 0, seconds: 0 } }")
    t.start(0)
    cdp.pause(0.4)
    fireworks = "document.querySelectorAll('.firework').length"
    log(95, 5)
    check('a set short of the best sets off nothing', cdp.ev(fireworks) == 0, cdp.ev(fireworks))
    log(105, 5)
    check('a heavier weight than ever does', cdp.ev(fireworks) == 1, cdp.ev(fireworks))
    check('with sparks that carry their own direction', cdp.ev("document.querySelectorAll('.firework i').length") == 28
          and cdp.ev("!!document.querySelector('.firework i').style.getPropertyValue('--dx')"), cdp.ev("document.querySelectorAll('.firework i').length"))
    check('never in the way of a tap', cdp.ev("getComputedStyle(document.querySelector('.firework')).pointerEvents") == 'none')
    cdp.pause(1.4)
    check('and clears itself away', cdp.ev(fireworks) == 0, cdp.ev(fireworks))
    log(105, 5)
    check('repeating the same record sets off nothing new', cdp.ev(fireworks) == 0, cdp.ev(fireworks))
    log(110, 5)
    check('beating it again does', cdp.ev(fireworks) == 1, cdp.ev(fireworks))
    cdp.pause(1.4)
    cdp.ev("saveLocalState('goals', { 'bench press': { name: 'Bench Press', target: 120, unit: 'lbs', by: '' }, 'squat': { name: 'Squat', target: 100, unit: 'kg', by: '' } })")
    log(115, 5)
    check('a set short of a goal is only a record', cdp.ev(fireworks) == 1 and cdp.ev("document.querySelectorAll('.firework i').length") == 28
          and 'Goal reached' not in text('formFeedback'), text('formFeedback'))
    cdp.pause(1.4)
    log(120, 5)
    check('a set that reaches a goal sets off a bigger firework, once', cdp.ev(fireworks) == 1 and cdp.ev("document.querySelectorAll('.firework i').length") == 64,
          cdp.ev("document.querySelectorAll('.firework i').length"))
    check('and says which goal', text('formFeedback') == 'Goal reached: Bench Press, 120 lbs!', text('formFeedback'))
    cdp.pause(1.4)
    log(125, 5)
    check('going past it is a record again, not the goal', cdp.ev(fireworks) == 1 and cdp.ev("document.querySelectorAll('.firework i').length") == 28
          and 'Goal reached' not in text('formFeedback'), text('formFeedback'))
    end()

    # ------------------------------------------------------------------ progression in your own templates
    print('P   a template exercise with sets and a rep range progresses on its own')
    seed('Rows Before', 9, [ex('Cable Row', 100, 8, [(12, 100), (12, 100), (12, 100)]), ex('Leg Curl', 60, 8, [(12, 60), (10, 60), (9, 60)])])
    open_tracker()
    click('templatesToggle')
    click('createTemplateBtn')

    def fill_template(name, rows):
        cdp.ev(f"""(() => {{
          document.getElementById('templateName').value = {json.dumps(name)};
          const rows = {json.dumps(rows)};
          rows.slice(1).forEach(() => document.getElementById('addTemplateExercise').click());
          const put = (id, value) => {{ const e = document.getElementById(id); e.value = String(value); e.dispatchEvent(new Event('input', {{ bubbles: true }})); }};
          rows.forEach(([name, sets, reps, top], index) => {{
            put(`templateExercise${{index}}`, name); put(`templateSets${{index}}`, sets); put(`templateReps${{index}}`, reps); put(`templateRepsMax${{index}}`, top);
          }});
        }})()""")

    labels = cdp.ev("['templateSets0', 'templateReps0', 'templateRepsMax0'].map(id => document.querySelector(`label[for=${id}]`).textContent)")
    check('the template editor asks for sets and the top of a rep range', labels == ['Sets', 'Reps', 'Up to'], labels)
    fill_template('Pull Accessories', [['Cable Row', 3, 8, 12], ['Leg Curl', 3, 8, 6]])
    cdp.ev("document.getElementById('templateForm').requestSubmit()")
    cdp.pause(0.3)
    check('a range that goes down is turned back', visible('templateModal') and text('formFeedback') == 'A rep range goes up: Leg Curl is 8 up to 6.',
          text('formFeedback'))
    click('cancelTemplate')
    click('createTemplateBtn')
    fill_template('Pull Accessories', [['Cable Row', 3, 8, 12], ['Leg Curl', 3, 8, 12], ['Hammer Curl', 2, 10, '']])
    cdp.ev("document.getElementById('templateForm').requestSubmit()")
    cdp.pause(0.4)
    card = cdp.ev("[...document.querySelectorAll('#templateList .template-card')].find(c => c.textContent.includes('Pull Accessories')).querySelector('p').textContent")
    check('its card says the sets and ranges', card == 'Cable Row (3 × 8–12 reps) · Leg Curl (3 × 8–12 reps) · Hammer Curl (2 × 10 reps)', card)
    kept = [x for x in api('GET', '/api/state', token=token)[0]['templates'] if x['name'] == 'Pull Accessories'] if wait_for(
        lambda: any(x['name'] == 'Pull Accessories' for x in api('GET', '/api/state', token=token)[0]['templates'])) else []
    shapes = [(e.get('setCount'), e.get('reps'), e.get('repsMax')) for e in kept[0]['exercises']] if kept else []
    check('and the account keeps them', shapes == [(3, '8', 12), (3, '8', 12), (2, '10', None)], shapes)

    cdp.ev("[...document.querySelectorAll('#templateList [data-template-action=start]')].find(b => b.closest('.template-card').textContent.includes('Pull Accessories')).click()")
    cdp.pause(0.4)
    target = text('activeExerciseTarget')
    check('every set reached 12 last time, so it goes up a weight step',
          target == 'Set 1 of 3: 105 lbs × 8–12. Up from 100 lbs: last time every set reached 12 reps.'
          and cdp.ev("document.getElementById('activeWeight').value") == '105', target)
    check('planned set by set', cdp.ev("[...document.querySelectorAll('#activePlan li')].map(li => li.textContent)") == ['105 lbs × 8–12'] * 3)
    log(105, 12)
    log(105, 12)
    log(105, 11)
    click('nextExerciseBtn')
    target = text('activeExerciseTarget')
    check('one that fell short stays at its weight until every set reaches the top',
          target == 'Set 1 of 3: 60 lbs × 8–12. The same as last time until every set reaches 12 reps.'
          and cdp.ev("document.getElementById('activeWeight').value") == '60', target)
    log(60, 12)
    click('nextExerciseBtn')
    target = text('activeExerciseTarget')
    check('never done before, the weight is yours to choose', target == 'Set 1 of 2: 10 reps.' and cdp.ev("document.getElementById('activeWeight').value") == '', target)
    log(25, 10)
    log(25, 10)
    finish()
    again = [w for w in t.workouts() if w['name'] == 'Pull Accessories']
    check('the workout is saved with its set counts', again and [e.get('setCount') for e in again[0]['exercises']] == [3, 3, 2],
          again and [e.get('setCount') for e in again[0]['exercises']])
    start_saved(again[0]['id'])
    target = text('activeExerciseTarget')
    check('starting it again, a set short of 12 keeps the weight', target == 'Set 1 of 3: 105 lbs × 8–12. The same as last time until every set reaches 12 reps.', target)
    cdp.ev(jump)
    cdp.pause(0.2)
    target = text('activeExerciseTarget')
    check('and without a range, reaching the reps goes up', current() == 'Hammer Curl'
          and target == 'Set 1 of 2: 30 lbs × 10. Up from 25 lbs: last time every set reached 10 reps.', target)
    end()
    status, _, reply = t.request('PUT', '/api/state', json.dumps({'templates': [{'name': 'Too Many', 'exercises': [
        {'name': 'Curl', 'reps': '10', 'setCount': 50}]}]}).encode(), {'Content-Type': 'application/json'}, token=token)
    check('the server turns away a set count it could not plan', status == 400 and 'setCount' in str(reply), (status, reply))

    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')],
          [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
