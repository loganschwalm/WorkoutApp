"""Deleting a saved workout, a cardio session or a template asks nothing first and offers Undo: a workout comes back as a new one (the
server keeps the clientId of everything deleted, so the old one could not be sent again), also when there is no connection to send it on,
and a template comes back in its place with its own id."""

import json
import time

INTERCEPT = True


def run(t):
    cdp, check, api, token = t.cdp, t.check, t.api, t.token
    safe_ev, wait_for = t.safe_ev, t.wait_for

    def stored():
        return api('GET', '/api/workouts', token=token)[0]['workouts']

    def named(name):
        return [w for w in stored() if w['name'] == name]

    def banner():
        return cdp.ev("document.getElementById('formFeedback').textContent")

    def make(name, client_id, **extra):
        body = {'name': name, 'notes': 'kept notes', 'createdAt': int(time.time() * 1000) - 3600_000, 'clientId': client_id,
                'exercises': [t.ex('Squat', 100, 5, [(5, 100), (5, 100)])], **extra}
        return api('POST', '/api/workouts', body, token)[0]['id'], body

    def delete_in(selector):
        cdp.dialogs.clear()
        cdp.ev(f"document.querySelector({json.dumps(selector)} + ' [data-action=delete]').click()")

    def undo():
        cdp.ev("document.querySelector('#formFeedback .feedback-action').click()")

    # ------------------------------------------------------------------ U1 the Tracker's list
    print('U1  a saved workout deleted from the Tracker comes back as a new one')
    workout_id, original = make('Undo Me', 'undo-me')
    t.open_tracker()
    row = f".saved-workout[data-id='{workout_id}']"
    cdp.wait(f"!!document.querySelector({json.dumps(row)})")
    delete_in(row)
    check('it is deleted with no question first', wait_for(lambda: not named('Undo Me')) and cdp.dialogs == [], cdp.dialogs)
    check('and the banner offers Undo', cdp.wait("document.getElementById('formFeedback').textContent === 'Deleted “Undo Me”. Undo'"), banner())
    check('with the keyboard on it, since the button that was pressed has gone', cdp.ev("document.activeElement.classList.contains('feedback-action')") is True)
    undo()
    check('Undo puts it back on the server', wait_for(lambda: len(named('Undo Me')) == 1), named('Undo Me'))
    back = named('Undo Me')[0]
    check('with the same name, notes, day and sets', (back['notes'], back['createdAt'], back['exercises']) == (original['notes'], original['createdAt'], original['exercises']), back)
    check('as a new workout, since the server will not take the deleted one again', back['id'] != workout_id and back.get('clientId') != 'undo-me', back)
    check('and the banner says so, with the list showing it', cdp.wait("document.getElementById('formFeedback').textContent === '“Undo Me” is back.'")
          and cdp.wait("[...document.querySelectorAll('#savedWorkoutList .saved-workout strong')].some(e => e.textContent === 'Undo Me')"), banner())

    # ------------------------------------------------------------------ U2 with no connection
    print('U2  Undo with no connection keeps it on the device and sends it when there is one')
    workout_id, original = make('Undo Offline', 'undo-offline')
    t.open_tracker()
    row = f".saved-workout[data-id='{workout_id}']"
    cdp.wait(f"!!document.querySelector({json.dumps(row)})")
    delete_in(row)
    cdp.wait("document.getElementById('formFeedback').textContent === 'Deleted “Undo Offline”. Undo'")
    cdp.block_api = True
    undo()
    check('it says it is on the device', cdp.wait("document.getElementById('formFeedback').textContent.includes('is back on this device and will sync')"), banner())
    check('queued to go up', safe_ev("readPendingWorkouts().filter(w => w.name === 'Undo Offline').length", -1) == 1)
    cdp.block_api = False
    cdp.ev('flushPendingWorkouts()')
    check('and it does when the server is back', wait_for(lambda: len(named('Undo Offline')) == 1), named('Undo Offline'))

    # ------------------------------------------------------------------ U3 History
    print('U3  the same from History')
    workout_id, original = make('Undo History', 'undo-history')
    cdp.goto('/history.html')
    row = f".history-workout[data-id='{workout_id}']"
    cdp.wait(f"!!document.querySelector({json.dumps(row)})")
    delete_in(row)
    check('deleted, with Undo', wait_for(lambda: not named('Undo History')) and cdp.wait("document.getElementById('formFeedback').textContent === 'Deleted “Undo History”. Undo'")
          and cdp.dialogs == [], banner())
    undo()
    check('Undo brings it back, and into the list', wait_for(lambda: len(named('Undo History')) == 1)
          and cdp.wait("[...document.querySelectorAll('.history-workout strong')].some(e => e.textContent === 'Undo History')"), named('Undo History'))

    # ------------------------------------------------------------------ U4 Cardio
    print('U4  and a cardio session from Cardio')
    session = {'kind': 'cardio', 'duration': 1680, 'cardio': {'activity': 'run', 'distance': 3.1, 'distanceUnit': 'mi'}}
    workout_id = api('POST', '/api/workouts', {'name': 'Undo Run', 'notes': '', 'createdAt': int(time.time() * 1000) - 7200_000,
                                               'clientId': 'undo-run', 'exercises': [], **session}, token)[0]['id']
    cdp.goto('/cardio.html')
    row = f"#cardioList .saved-workout[data-id='{workout_id}']"
    cdp.wait(f"!!document.querySelector({json.dumps(row)})")
    delete_in(row)
    check('deleted, with Undo', wait_for(lambda: not named('Undo Run')) and cdp.wait("document.getElementById('formFeedback').textContent.startsWith('Deleted “Undo Run” of ')"), banner())
    undo()
    check('Undo brings it back, as a cardio session with the same numbers', wait_for(lambda: len(named('Undo Run')) == 1)
          and named('Undo Run')[0].get('kind') == 'cardio' and named('Undo Run')[0]['cardio'] == session['cardio'] and named('Undo Run')[0]['duration'] == 1680, named('Undo Run'))

    # ------------------------------------------------------------------ U5 templates
    print('U5  a template comes back in its place, with its id')
    t.open_tracker()
    cdp.ev("""customTemplates.push({ id: 'custom-first', name: 'Undo First', exercises: [{ name: 'Row', reps: '8' }] },
        { id: 'custom-second', name: 'Undo Second', exercises: [{ name: 'Curl', reps: '10' }] }); saveCustomTemplates(); renderTemplates();""")
    ids = lambda: cdp.ev("customTemplates.map(item => item.id)")
    before = ids()
    cdp.dialogs.clear()
    cdp.ev("document.querySelector('#templateList [data-template-action=delete][data-template-id=\"custom-first\"]').click()")
    check('it is deleted with no question first, and Undo is offered', 'custom-first' not in ids() and cdp.dialogs == []
          and banner() == 'Deleted template “Undo First”. Undo', [ids(), banner()])
    undo()
    check('Undo puts it back where it was, under the same id', ids() == before and banner() == 'Put template “Undo First” back.', [ids(), before, banner()])
    check('and the list shows it', cdp.ev("!!document.querySelector('#templateList [data-template-id=\"custom-first\"]')") is True)
    check('and the account has it', wait_for(lambda: 'custom-first' in [item.get('id') for item in api('GET', '/api/state', token=token)[0]['templates']]))
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
