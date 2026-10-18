"""The finished workouts the server refuses: kept on the device, listed in Settings (Your data) with what the server said, and tried
once more, saved to a file that imports, or discarded from there."""

import json
import time

INTERCEPT = True
# An account that already has three workouts (the suite seeds them) is at its limit, so any more are refused until there is room.
SERVER_ENV = {'MAX_WORKOUTS': '3'}


def run(t):
    cdp, check, api = t.cdp, t.check, t.api
    safe_ev = t.safe_ev

    def made(name, client_id=None, bad=False):
        workout = {'name': name, 'notes': '', 'createdAt': int(time.time() * 1000), 'exercises': 'not a list' if bad
                   else [{'name': 'Squat', 'weight': 100, 'reps': 5, 'sets': [{'weight': 100, 'reps': 5}]}]}
        if client_id:
            workout['clientId'] = client_id
        return workout

    def rows():
        return cdp.ev("""[...document.querySelectorAll('#refusedList li')].map(li => ({ name: li.querySelector('strong').textContent,
            why: li.querySelector('.subtitle').textContent, buttons: [...li.querySelectorAll('button')].map(b => b.textContent) }))""")

    def feedback():
        return cdp.ev("document.getElementById('refusedFeedback').textContent")

    def press(action, name):
        cdp.ev(f"""[...document.querySelectorAll('#refusedList li')].find(li => li.querySelector('strong').textContent === {json.dumps(name)})
            .querySelector('[data-refused-action={action}]').click()""")
        cdp.pause(0.6)

    def on_the_server():
        return [w['name'] for w in api('GET', '/api/workouts', token=t.token)[0]['workouts']]

    # ------------------------------------------------------------------ R1 the list
    print('R1  the workouts the server refused are listed in Settings, with why')
    t.open_tracker()
    queued = [made('Over The Limit', 'over-1'), made('Broken', 'broken-1', bad=True), made('Old Build', bad=True), made('Download Me', 'dl-1')]
    cdp.ev(';'.join(f'queuePendingWorkout({json.dumps(workout)})' for workout in queued))
    check('the flush finishes, every one refused', cdp.ev('flushPendingWorkouts()') is True and safe_ev('readRejectedWorkouts().length', -1) == 4)
    check('and nothing is left in the upload queue', safe_ev('readPendingWorkouts().length', -1) == 0)
    check('the Tracker says where to look', 'see Settings, Your data' in cdp.ev("document.getElementById('storageStatus').textContent"),
          cdp.ev("document.getElementById('storageStatus').textContent"))
    cdp.ev("document.getElementById('settingsButton').click()")
    cdp.pause(0.4)
    check('Your data says how many are refused, folded or not', cdp.ev("document.getElementById('settings-data-state').textContent") == '4 refused')
    cdp.ev("document.getElementById('settings-data').open = true")
    listed = rows()
    check('each is listed with its name', [row['name'] for row in listed] == ['Over The Limit', 'Broken', 'Old Build', 'Download Me'], listed)
    check('and what the server said of it', 'at most 3' in listed[0]['why'] and 'exercises' in listed[1]['why'] and listed[2]['why'].endswith('The server will not accept it.'), listed)
    check('each can be retried, downloaded or discarded', all(row['buttons'] == ['Retry', 'Download', 'Discard'] for row in listed), listed)
    named = cdp.ev("[...document.querySelectorAll('#refusedList li')][0].querySelector('button').getAttribute('aria-label')")
    check('with buttons named for the workout', named.startswith('Retry Over The Limit'), named)

    # ------------------------------------------------------------------ R2 retry
    print('R2  Retry tries once, and keeps the workout unless the server takes it')
    press('retry', 'Over The Limit')
    check('refused again, it says so and why', feedback().startswith('The server still refuses “Over The Limit”: ') and 'at most 3' in feedback(), feedback())
    check('it is still on the device, and not put back in the queue', len(rows()) == 4 and safe_ev('readPendingWorkouts().length', -1) == 0)
    cdp.block_api = True
    press('retry', 'Over The Limit')
    cdp.block_api = False
    check('with no connection it says so, and nothing changes', feedback() == 'Could not reach the server. Try again when you are back online.' and len(rows()) == 4, feedback())
    check('and the buttons work again', cdp.ev("document.querySelectorAll('#refusedList button:disabled').length") == 0)

    # ------------------------------------------------------------------ R3 download
    print('R3  Download makes a file that imports')
    cdp.ev("""window.__saved = null; const real = URL.createObjectURL.bind(URL);
        URL.createObjectURL = blob => { window.__saved = blob; return real(blob); }""")
    press('download', 'Download Me')
    check('it says what it saved', feedback().startswith('Downloaded Download-Me-') and feedback().endswith('.json.'), feedback())
    saved = json.loads(cdp.ev("window.__saved.text()"))
    check('in the export format, without the clientId the server tells it apart by',
          saved['format'] == 'workout-tracker-export' and len(saved['workouts']) == 1 and saved['workouts'][0]['name'] == 'Download Me'
          and 'clientId' not in saved['workouts'][0] and 'id' not in saved['workouts'][0], saved)
    for workout in api('GET', '/api/workouts', token=t.token)[0]['workouts'][:2]:
        api('DELETE', f"/api/workouts/{workout['id']}", token=t.token)
    status, _, reply = t.request('POST', '/api/import', json.dumps(saved).encode(), {'Content-Type': 'application/json'}, token=t.token)
    check('and Import takes it, once there is room', status == 200 and reply.get('workouts') == 1, f'{status} {reply}')
    check('it is on the server', 'Download Me' in on_the_server(), on_the_server())

    # ------------------------------------------------------------------ R4 retry that works
    print('R4  Retry saves it once the server will have it, and it leaves the device')
    check('with one place left', len(on_the_server()) == 2, on_the_server())
    press('retry', 'Over The Limit')
    check('it is saved, and says so', feedback() == 'Saved “Over The Limit” to your account.' and 'Over The Limit' in on_the_server(), feedback())
    check('gone from the list', [row['name'] for row in rows()] == ['Broken', 'Old Build', 'Download Me'] and safe_ev('readRejectedWorkouts().length', -1) == 3, rows())
    check('and the reason with it', 'over-1' not in safe_ev('Object.keys(readRefusals())', []), safe_ev('Object.keys(readRefusals())', []))
    check('the state line follows', cdp.ev("document.getElementById('settings-data-state').textContent") == '3 refused')

    # ------------------------------------------------------------------ R5 discard
    print('R5  Discard asks first, and then the workout is gone from the device for good')
    cdp.answer = False
    cdp.dialogs.clear()
    press('discard', 'Old Build')
    check('declining keeps it', len(rows()) == 3 and 'Discard “Old Build”?' in (cdp.dialogs[0] if cdp.dialogs else ''), cdp.dialogs)
    cdp.answer = True
    press('discard', 'Old Build')
    check('accepting removes it', [row['name'] for row in rows()] == ['Broken', 'Download Me'] and feedback() == 'Discarded “Old Build”.', [rows(), feedback()])
    check('and nothing of it is left to upload', safe_ev('readPendingWorkouts().length', -1) == 0
          and safe_ev('readRejectedWorkouts().map(w => w.name)', []) == ['Broken', 'Download Me'])
    check('it survives a reload', (cdp.send('Page.reload') or True) and cdp.wait("document.readyState === 'complete'")
          and safe_ev('readRejectedWorkouts().length', -1) == 2)

    # ------------------------------------------------------------------ R6 what the server said is text
    print('R6  a name that looks like markup is shown as text')
    t.open_tracker()
    cdp.ev(f"queuePendingWorkout({json.dumps(made('<img src=x onerror=alert(1)>', 'markup-1', bad=True))}); flushPendingWorkouts()")
    cdp.pause(0.6)
    cdp.ev("document.getElementById('settingsButton').click()")
    cdp.pause(0.3)
    check('as text, not markup', cdp.ev("document.querySelectorAll('#refusedList img').length") == 0
          and '<img src=x onerror=alert(1)>' in [row['name'] for row in rows()], [row['name'] for row in rows()])
    for name in [row['name'] for row in rows()]:
        press('discard', name)
    check('once all are discarded, the list goes and the state line is as it was', cdp.ev("document.getElementById('refusedWorkouts').hidden") is True
          and cdp.ev("document.getElementById('settings-data-state').textContent") == 'Export or import')
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
