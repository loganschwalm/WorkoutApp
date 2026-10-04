"""Cardio: timing a session and logging one by hand, the sessions so far, History, Progress, and miles or kilometres."""

import json
import time

DAY_MS = 86400000

INTERCEPT = False


def run(t):
    cdp, check, api = t.cdp, t.check, t.api

    def text(idn):
        return cdp.ev(f"document.getElementById('{idn}').textContent")

    def hidden(idn):
        return cdp.ev(f"document.getElementById('{idn}').hidden")

    def click(selector):
        cdp.ev(f"document.querySelector({json.dumps(selector)}).click()")
        cdp.pause(0.3)

    def fill(idn, value):
        cdp.ev(f"""(e => {{ e.value = {json.dumps(str(value))}; e.dispatchEvent(new Event('input', {{ bubbles: true }}));
            e.dispatchEvent(new Event('change', {{ bubbles: true }})); }})(document.getElementById('{idn}'))""")

    def rows():
        return cdp.ev("[...document.querySelectorAll('#cardioList .saved-workout')].map(li => li.querySelector('strong').textContent)")

    def open_cardio(path='/cardio.html'):
        cdp.goto(path)
        cdp.wait("document.querySelectorAll('#cardioList .saved-workout').length > 0 || !!document.querySelector('#cardioList .empty') && cardioLoaded")
        cdp.pause(0.6)

    def sessions():
        return [w for w in api('GET', '/api/workouts', token=runner)[0]['workouts'] if w.get('kind') == 'cardio']

    # Started this many minutes ago, as if the timer had been running that long.
    def backdate(minutes):
        cdp.ev(f"cardioActive.startedAt -= {minutes} * 60000; saveCardioActive(); tickCardio()")

    cookie = api('POST', '/api/auth/register', {'username': 'runner', 'email': 'runner@example.test', 'password': 'chalk-and-plates-42'})[1]
    runner = cookie.split('session=')[1].split(';')[0]
    now = int(time.time() * 1000)
    # Two runs and a row from last month, and a strength workout, so last time, the records and the lists have something.
    seeded = [
        {'kind': 'cardio', 'name': 'Run', 'notes': '', 'createdAt': now - 10 * DAY_MS, 'clientId': 'seed-run-1', 'exercises': [], 'duration': 1680,
         'cardio': {'activity': 'run', 'distance': 3.1, 'distanceUnit': 'mi', 'calories': 300, 'heartRate': 150}},
        {'kind': 'cardio', 'name': 'Run', 'notes': 'Hills', 'createdAt': now - 9 * DAY_MS, 'clientId': 'seed-run-2', 'exercises': [], 'duration': 1890,
         'cardio': {'activity': 'run', 'distance': 3.5, 'distanceUnit': 'mi'}},
        {'kind': 'cardio', 'name': 'Rowing machine', 'notes': '', 'createdAt': now - 8 * DAY_MS, 'clientId': 'seed-row', 'exercises': [], 'duration': 1200,
         'cardio': {'activity': 'rower', 'distance': 5000, 'distanceUnit': 'm'}},
        {'name': 'Push Day', 'notes': '', 'createdAt': now - 8 * DAY_MS + 3600000, 'exercises': [t.ex('Bench Press', 135, 5, [(5, 135)] * 3)]},
    ]
    for workout in seeded:
        api('POST', '/api/workouts', workout, runner)
    t.set_cookie(runner)

    # ------------------------------------------------------------------ C1 the page
    print('C1  Cardio is a tab of its own, with its activities and the sessions so far')
    open_cardio()
    nav = cdp.ev("[...document.querySelectorAll('.site-nav a')].map(a => a.textContent + (a.classList.contains('active') ? '*' : ''))")
    check('the tabs are Strength, Cardio, Progress and History', nav == ['Strength', 'Cardio*', 'Progress', 'History'], nav)
    tiles = cdp.ev("Object.fromEntries([...document.querySelectorAll('#cardioActivityGrid .cardio-activity')].map(b => [b.querySelector('strong').textContent, "
                   "b.querySelector('span').textContent.replace(/\u00a0/g, ' ')]))")
    check('every activity can be started, walking and running and the machines',
          list(tiles) == ['Walk', 'Run', 'Cycling', 'Exercise bike', 'Elliptical', 'Rowing machine', 'Stair climber', 'Other'], list(tiles))
    check('each says when it was last done, and how far', tiles.get('Run', '').endswith('· 3.5 mi') and tiles.get('Rowing machine', '').endswith('· 5,000 m')
          and tiles.get('Walk') == 'Start the timer', tiles)
    check('the sessions are listed, newest first, without the strength workout', rows() == ['Rowing machine', 'Run', 'Run'], rows())
    line = cdp.ev("document.querySelectorAll('#cardioList .saved-workout')[1].querySelector('.saved-workout-toggle span').textContent")
    check('each with its day, time and distance', line.endswith(' · 31:30 · 3.5 mi'), line)
    click("#cardioList .saved-workout:nth-child(2) [data-action=view]")
    details = cdp.ev("document.querySelectorAll('#cardioList .saved-workout')[1].querySelector('.workout-details').textContent")
    check('tapping one shows everything it did, and its note', details == 'HillsRun3.5 mi in 31:30 · 9:00 /mi', details)
    check('this week has nothing yet', text('cardioWeek') == 'Nothing yet this week.', text('cardioWeek'))

    # ------------------------------------------------------------------ C2 timing a session
    print('C2  a session is timed: paused, kept through a reload, cancelled with Undo, and finished')
    click("#cardioActivityGrid [data-activity=walk]")
    check('a tap starts the timer for that activity', not hidden('cardioActive') and text('cardioActiveTitle') == 'Walk' and hidden('cardioStartCard'))
    cdp.pause(1.3)
    check('and the clock runs', text('cardioClock') in ('0:01', '0:02'), text('cardioClock'))
    backdate(25)
    check('timing from when it started', text('cardioClock').startswith('25:0'), text('cardioClock'))
    click('#cardioPauseBtn')
    paused = text('cardioClock')
    cdp.pause(1.2)
    check('Pause stops the clock', text('cardioClock') == paused and text('cardioPauseBtn') == 'Resume'
          and cdp.ev("document.getElementById('cardioActive').classList.contains('paused')") is True, [paused, text('cardioClock')])
    open_cardio()
    check('a reload keeps the session, paused where it was', not hidden('cardioActive') and text('cardioClock') == paused and text('cardioPauseBtn') == 'Resume',
          [text('cardioClock'), paused])
    click('#cardioPauseBtn')
    cdp.pause(1.2)
    check('Resume carries on from there', text('cardioClock') != paused and text('cardioPauseBtn') == 'Pause', text('cardioClock'))
    cdp.dialogs.clear()
    cdp.answer = False
    click('#cardioCancelBtn')
    check('cancelling 25 minutes asks first', cdp.dialogs and cdp.dialogs[0].startswith('Cancel this Walk? Its 25:0') and not hidden('cardioActive'), cdp.dialogs)
    cdp.answer = True
    click('#cardioCancelBtn')
    check('and goes, saving nothing', hidden('cardioActive') and text('formFeedback') == '“Walk” was cancelled. Nothing was saved. Undo'
          and cdp.ev("readLocal(localKey('cardio-active'))") is None, text('formFeedback'))
    click('#formFeedback .feedback-action')
    check('Undo brings it back, its time still counting', not hidden('cardioActive') and text('cardioClock').startswith('25:'), text('cardioClock'))
    click('#cardioFinishBtn')
    check('Finish stops the clock and asks for the rest', hidden('cardioActive') and not hidden('cardioFormCard')
          and text('cardioFormTitle') == 'Finish your walk' and cdp.ev("document.activeElement.id") == 'cardioDistance', text('cardioFormTitle'))
    time_fields = cdp.ev("['cardioHours', 'cardioMinutes', 'cardioSeconds'].map(id => document.getElementById(id).value)")
    check('with the time from the timer', time_fields[0] == '' and time_fields[1] == '25', time_fields)
    click('#cardioFormCancel')
    check('Back to the timer leaves it paused', not hidden('cardioActive') and text('cardioPauseBtn') == 'Resume' and hidden('cardioFormCard'))
    click('#cardioFinishBtn')
    fill('cardioSeconds', '0')
    fill('cardioDistance', '1.5')
    check('the pace is worked out as the distance is typed', text('cardioRate') == 'Pace: 16:40 /mi', text('cardioRate'))
    fill('cardioHeartRate', '118')
    click('#cardioSave')
    cdp.pause(0.6)
    saved = t.wait_for(lambda: any(w['name'] == 'Walk' for w in sessions())) and next(w for w in sessions() if w['name'] == 'Walk')
    check('the session is saved as a workout of its own kind, in the unit it was entered in',
          saved and saved['kind'] == 'cardio' and saved['exercises'] == [] and saved['duration'] == 1500
          and saved['cardio'] == {'activity': 'walk', 'distance': 1.5, 'distanceUnit': 'mi', 'heartRate': 118}, saved)
    stats = cdp.ev("[...document.querySelectorAll('#cardioSummaryStats li')].map(li => li.textContent)")
    check('a summary says what it did', not hidden('cardioSummary') and stats == ['25:00Time', '1.5 miDistance', '16:40 /miPace', '118 bpmHeart rate'], stats)
    check('with no records for a first walk', hidden('cardioSummaryRecords'))
    check('the timer is done with', hidden('cardioActive') and not hidden('cardioStartCard') and cdp.ev("readLocal(localKey('cardio-active'))") is None)
    check('and the week counts it', text('cardioWeek') == 'This week: 1 session · 25 min · 1.5\u00a0mi', text('cardioWeek'))

    # ------------------------------------------------------------------ C3 records
    print('C3  a session that beats the ones before is a record, said in the summary')
    click("#cardioActivityGrid [data-activity=run]")
    check('last time is under the clock', text('cardioLast').startswith('Last time (') and text('cardioLast').endswith('3.5 mi in 31:30 · 9:00 /mi'), text('cardioLast'))
    backdate(25)
    click('#cardioFinishBtn')
    fill('cardioSeconds', '0')
    fill('cardioDistance', '3')
    click('#cardioSave')
    cdp.pause(0.6)
    records = cdp.ev("[...document.querySelectorAll('#cardioSummaryRecordList li')].map(li => li.textContent)")
    check('a faster pace than ever is a record; a shorter, quicker run is no other', records == ['Run: your fastest yet, 8:20 /mi (was 9:00 /mi)'], records)

    # ------------------------------------------------------------------ C4 logging by hand
    print('C4  a session is logged by hand: any activity, any day, with what the machine said and was set to')
    click('#cardioModeManual')
    tile = lambda activity: cdp.ev(f"document.querySelector('#cardioActivityGrid [data-activity={activity}] span').textContent").replace('\u00a0', ' ')
    check('Enter the time, above the activities, makes a tap open the form instead of the timer',
          cdp.ev("document.getElementById('cardioModeManual').getAttribute('aria-pressed')") == 'true' and tile('cycle') == 'Enter its time'
          and text('cardioStartHelp') == 'Tap what you did to enter its time, distance and the rest.', [tile('cycle'), text('cardioStartHelp')])
    open_cardio()
    check('and it is remembered on this device', cdp.ev("document.getElementById('cardioModeManual').getAttribute('aria-pressed')") == 'true')
    click("#cardioActivityGrid [data-activity=bike]")
    check('a tap opens the form for that activity, with no timer', not hidden('cardioFormCard') and text('cardioFormTitle') == 'Log a session'
          and cdp.ev("document.getElementById('cardioActivity').value") == 'bike' and hidden('cardioActive'), cdp.ev("document.getElementById('cardioActivity').value"))
    settings = lambda: cdp.ev("[...document.querySelectorAll('#cardioSettings label')].map(l => l.textContent)")
    check("an exercise bike's settings: resistance and cadence", settings() == ['Resistance level', 'Cadence (rpm)'], settings())
    click('#cardioSave')
    check('it needs a time', text('formFeedback') == 'Enter how long the session took.'
          and cdp.ev("document.getElementById('cardioMinutes').getAttribute('aria-invalid')") == 'true', text('formFeedback'))
    yesterday = cdp.ev("dateInputValue(Date.now() - 86400000)")
    fill('cardioDate', yesterday)
    fill('cardioMinutes', '30')
    fill('cardioDistance', '9')
    check('a bike is told by its speed', text('cardioRate') == 'Speed: 18 mph', text('cardioRate'))
    fill('cardioHeartRate', '300')
    click('#cardioSave')
    check('and a heart rate a heart can have', text('formFeedback').startswith('Enter an average heart rate from 20 to 250'), text('formFeedback'))
    fill('cardioHeartRate', '')
    fill('cardioCalories', '250')
    fill('cardioSetting-resistance', '150')
    click('#cardioSave')
    check('and a setting within its range', text('formFeedback') == 'Enter a resistance level from 0 to 100, or leave it empty.'
          and cdp.ev("document.activeElement.id") == 'cardioSetting-resistance', text('formFeedback'))
    fill('cardioSetting-resistance', '8')
    fill('cardioSetting-cadence', '85')
    tomorrow = cdp.ev("dateInputValue(Date.now() + 86400000)")
    fill('cardioDate', tomorrow)
    click('#cardioSave')
    check('and a day that has been', text('formFeedback') == 'Choose the day of the session, today or before.', text('formFeedback'))
    fill('cardioDate', yesterday)
    click('#cardioSave')
    cdp.pause(0.6)
    bike = t.wait_for(lambda: any(w['name'] == 'Exercise bike' for w in sessions())) and next(w for w in sessions() if w['name'] == 'Exercise bike')
    check('it is saved for that day, at noon, with its settings', bike and cdp.ev(f"dateInputValue({bike['createdAt']})") == yesterday
          and cdp.ev(f"new Date({bike['createdAt']}).getHours()") == 12
          and bike['cardio'] == {'activity': 'bike', 'distance': 9, 'distanceUnit': 'mi', 'calories': 250, 'resistance': 8, 'cadence': 85}, bike)
    stats = cdp.ev("[...document.querySelectorAll('#cardioSummaryStats li')].map(li => li.textContent)")
    check('which the summary says too', '8Resistance level' in stats and '85 rpmCadence' in stats, stats)
    click('#cardioSummaryDone')
    click("#cardioActivityGrid [data-activity=bike]")
    check("the next bike starts from last time's settings", cdp.ev("document.getElementById('cardioSetting-resistance').value") == '8'
          and cdp.ev("document.getElementById('cardioSetting-cadence').value") == '85')
    fill('cardioActivity', 'rower')
    check('another activity has its own: a rower its damper and stroke rate', settings() == ['Damper', 'Stroke rate (spm)'], settings())
    fill('cardioActivity', 'run')
    check('and a treadmill run its incline, which can go below zero', settings() == ['Incline (%)']
          and cdp.ev("document.getElementById('cardioSetting-incline').min") == '-10', settings())
    fill('cardioMinutes', '30')
    fill('cardioDistance', '9')
    cdp.dialogs.clear(); cdp.answer = False
    click('#cardioSave')
    check('a run far faster than your best (9 miles in 30 minutes) asks first', len(cdp.dialogs) == 1
          and cdp.dialogs[0].startswith("That's a 3:20 /mi pace, far faster than your best (") and cdp.dialogs[0].endswith('Save it anyway?'), cdp.dialogs)
    check('and saying no saves nothing, leaving the form open at the distance', not hidden('cardioFormCard') and cdp.ev("document.activeElement.id") == 'cardioDistance'
          and not any(w['name'] == 'Run' and w['cardio'].get('distance') == 9 for w in sessions()))
    cdp.answer = True
    fill('cardioMinutes', '')
    fill('cardioDistance', '')
    fill('cardioActivity', 'stairs')
    check('the stair climber counts floors rather than distance, at a level', hidden('cardioDistanceField') and not hidden('cardioFloorsField')
          and settings() == ['Level'], settings())
    fill('cardioActivity', 'other')
    check('Other asks for a name', not hidden('cardioNameField'))
    fill('cardioName', 'Jump rope')
    fill('cardioMinutes', '10')
    click('#cardioSave')
    cdp.pause(0.6)
    check('and keeps it', t.wait_for(lambda: any(w['name'] == 'Jump rope' and w['cardio']['activity'] == 'other' for w in sessions())))
    click('#cardioSummaryDone')
    click('#cardioModeTimer')
    check('Start the timer goes back to timing', tile('cycle') == 'Start the timer' and cdp.ev("document.getElementById('cardioModeTimer').getAttribute('aria-pressed')") == 'true',
          tile('cycle'))

    # ------------------------------------------------------------------ C5 changing one
    print('C5  a session is edited, copied, started again or deleted from its menu')
    open_cardio()
    check('the newest sessions are listed first', rows()[:4] == ['Jump rope', 'Run', 'Walk', 'Exercise bike'], rows())
    bike_row = f"#cardioList .saved-workout[data-id='{bike['id']}']"
    click(f"{bike_row} [data-action=edit]")
    check('Edit opens it in the form as it was', text('cardioFormTitle') == 'Edit session' and cdp.ev("document.getElementById('cardioDistance').value") == '9'
          and cdp.ev("document.getElementById('cardioMinutes').value") == '30' and text('cardioSave') == 'Save changes')
    fill('cardioCalories', '260')
    click('#cardioSave')
    cdp.pause(0.6)
    edited = t.wait_for(lambda: next(w for w in sessions() if w['id'] == bike['id'])['cardio'].get('calories') == 260) \
        and next(w for w in sessions() if w['id'] == bike['id'])
    check('saving changes it, and nothing else', edited and edited['createdAt'] == bike['createdAt'] and edited['cardio']['distance'] == 9
          and edited['clientId'] == bike['clientId'] and len(sessions()) == 7, edited)
    jump = next(w for w in sessions() if w['name'] == 'Jump rope')
    click(f"#cardioList .saved-workout[data-id='{jump['id']}'] [data-action=copy]")
    check('Copy as new opens it as a new session for today', text('cardioFormTitle') == 'Log a session'
          and cdp.ev("document.getElementById('cardioName').value") == 'Jump rope' and cdp.ev("document.getElementById('cardioDate').value") == cdp.ev("dateInputValue(Date.now())"))
    click('#cardioSave')
    cdp.pause(0.6)
    check('and saves a second one', t.wait_for(lambda: sum(w['name'] == 'Jump rope' for w in sessions()) == 2))
    click('#cardioSummaryDone')
    cdp.answer = True
    click(f"#cardioList .saved-workout[data-id='{jump['id']}'] [data-action=delete]")
    cdp.pause(0.6)
    check('Delete takes one away', t.wait_for(lambda: sum(w['name'] == 'Jump rope' for w in sessions()) == 1))
    click(f"{bike_row} [data-action=start]")
    check('Start does it again, with the timer', not hidden('cardioActive') and text('cardioActiveTitle') == 'Exercise bike')
    cdp.answer = True
    click('#cardioCancelBtn')

    # ------------------------------------------------------------------ C6 miles or kilometres
    print('C6  distances follow Settings: miles or kilometres, as logged until shown')
    check('with nothing chosen, miles go with pounds', cdp.ev('distanceUnitOf()') == 'mi')
    check('and kilometres with kilograms', cdp.ev("distanceUnitOf({ unit: 'kg' })") == 'km' and cdp.ev("distanceUnitOf({ unit: 'kg', distanceUnit: 'mi' })") == 'mi')
    cdp.ev("document.getElementById('settingsButton').click()")
    cdp.pause(0.3)
    fill('distanceUnitSetting', 'km')
    cdp.ev("document.getElementById('doneSettings').click()")
    cdp.pause(0.5)
    kept = t.wait_for(lambda: api('GET', '/api/state', token=runner)[0]['settings'].get('distanceUnit') == 'km')
    check('choosing kilometres is kept with the account', kept)
    run_line = cdp.ev("[...document.querySelectorAll('#cardioList .saved-workout')].find(li => li.querySelector('strong').textContent === 'Run')"
                      ".querySelector('.workout-details').textContent")
    check('and every distance is shown in them', run_line.endswith('4.83 km in 25:00 · 5:11 /km'), run_line)
    check('without changing what was logged', next(w for w in sessions() if w['clientId'] == 'seed-run-2')['cardio']['distance'] == 3.5)
    rower = cdp.ev("document.querySelector('#cardioActivityGrid [data-activity=rower] span').textContent")
    check('a rower keeps its metres', rower.endswith('· 5,000\u00a0m'), rower)
    click("#cardioActivityGrid [data-activity=run]")
    backdate(30)
    click('#cardioFinishBtn')
    check('the form asks in kilometres', text('cardioDistanceUnit') == 'km')
    fill('cardioDistance', '5')
    fill('cardioSeconds', '0')
    click('#cardioSave')
    cdp.pause(0.6)
    check('and keeps the distance in them', t.wait_for(lambda: any(w['cardio'].get('distanceUnit') == 'km' and w['cardio'].get('distance') == 5 for w in sessions())))
    click('#cardioSummaryDone')

    # ------------------------------------------------------------------ C7 History
    print('C7  History lists sessions beside workouts, and the calendar marks a day of cardio only')
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 8")
    cdp.pause(0.6)
    row = "[...document.querySelectorAll('.history-workout')].find(li => li.querySelector('strong').textContent === 'Rowing machine')"
    check('a session shows its time and distance', cdp.ev(f"{row}.querySelector('.saved-workout-toggle span').textContent").endswith(' · 20:00 · 5,000 m'))
    check('and its numbers when opened', cdp.ev(f"{row}.querySelector('.workout-details').textContent") == 'Rowing machine5,000 m in 20:00 · 2:00 /500 m')
    check('Start times it again on the Cardio page', cdp.ev(f"{row}.querySelector('a.button-link').getAttribute('href')").startswith('cardio.html?start='))
    days = cdp.ev("Object.fromEntries([...document.querySelectorAll('.calendar-day.trained')].map(d => [d.dataset.date, d.classList.contains('cardio')]))")
    rowed, lifted = cdp.ev(f"dateInputValue({seeded[2]['createdAt']})"), cdp.ev(f"dateInputValue({seeded[3]['createdAt']})")
    ran = cdp.ev(f"dateInputValue({seeded[1]['createdAt']})")
    check('a day of cardio only is marked apart; one with lifting is not', days.get(ran) is True and (rowed != lifted or days.get(rowed) is False), days)
    check('and sessions count toward the weekly goal', text('calendarSummary').startswith('This week: ') and 'workouts' in text('calendarSummary'), text('calendarSummary'))
    walk = next(w for w in sessions() if w['name'] == 'Walk')
    cdp.ev(f"[...document.querySelectorAll('.history-workout')].find(li => li.dataset.id === '{walk['id']}').querySelector('[data-action=edit]').click()")
    cdp.wait("!document.getElementById('cardioFormCard').hidden && document.getElementById('cardioFormTitle').textContent === 'Edit session'", timeout=10)
    cdp.pause(0.4)
    check('Edit opens the session on the Cardio page', cdp.ev("document.getElementById('cardioActivity').value") == 'walk' and 'edit=' not in cdp.ev('location.search'))
    click('#cardioFormCancel')

    # ------------------------------------------------------------------ C8 Progress
    print('C8  Progress charts an activity with its own measures, lists every session, and its records')
    cdp.goto('/progress.html?exercise=cardio%3Arun')
    cdp.wait("chartData && chartData.points.length > 0")
    cdp.pause(0.6)
    groups = cdp.ev("[...document.querySelectorAll('#exerciseFilter optgroup')].map(g => g.label + ': ' + [...g.querySelectorAll('option')].map(o => o.textContent).join(', '))")
    check('the activities are listed apart from the exercises', groups == ['Strength: All exercises, Bench Press',
                                                                          'Cardio: Exercise bike, Jump rope, Rowing machine, Run, Walk'], groups)
    metrics = cdp.ev("[...document.getElementById('metricFilter').options].map(o => o.textContent)")
    check("a run's measures: distance, time, pace, calories, heart rate and incline", metrics == ['Distance', 'Time', 'Pace', 'Calories', 'Average heart rate', 'Incline'],
          metrics)
    values = cdp.ev('[...chartData.types[0].values.values()].map(v => Math.round(v * 100) / 100)')
    check('every run charted by distance, in the unit shown', values == [4.99, 5.63, 4.83, 5], values)
    check('counted among the sessions, not workouts, with no workout type to filter by', text('progressSummary') == '8 sessions'
          and cdp.ev("document.getElementById('workoutTypeFilter').disabled") is True, text('progressSummary'))
    fill('metricFilter', 'rate')
    cdp.pause(0.3)
    check('the pace is written as a clock', cdp.ev('drawnPoints[drawnPoints.length - 1].text').endswith(': 6:00 /km')
          and text('progressTitle') == 'Pace', cdp.ev('drawnPoints[drawnPoints.length - 1].text'))
    fill('metricFilter', 'heartRate')
    cdp.pause(0.3)
    check('a measure few sessions have charts those', cdp.ev('chartData.points.length') == 1)
    sessions_list = cdp.ev("[...document.querySelectorAll('#sessionList li')].map(li => li.lastElementChild.textContent)")
    check('every session of the run is listed', text('sessionsTitle') == 'Every session of Run' and len(sessions_list) == 4
          and sessions_list[-1] == '4.99 km in 28:00 · 5:37 /km · 150 bpm · 300 cal', sessions_list)
    fill('exerciseFilter', 'cardio:rower')
    cdp.pause(0.3)
    check("a rower's speed is its split", [o for o in cdp.ev("[...document.getElementById('metricFilter').options].map(o => o.textContent)")][2] == 'Split')
    fill('exerciseFilter', 'bench press')
    cdp.pause(0.3)
    check('an exercise goes back to its own measures', cdp.ev("[...document.getElementById('metricFilter').options].map(o => o.value)") == ['weight', 'oneRepMax', 'reps', 'volume']
          and cdp.ev("document.getElementById('workoutTypeFilter').disabled") is False and text('progressSummary') == '1 saved workout', text('progressSummary'))
    records = cdp.ev("Object.fromEntries([...document.querySelectorAll('#recordsList .record')].map(r => [r.querySelector('strong').textContent, [...r.querySelectorAll(':scope > span')].map(s => s.textContent.split(' · ')[0])]))")
    check('the records list each activity\'s bests beside the lifts', records.get('Run') == ['Longest 5.63 km', 'Fastest 5:11 /km, over 4.83 km', 'Longest time 31:30']
          and 'Bench Press' in records, records)

    # ------------------------------------------------------------------ C9 the Strength page, and a phone
    print('C9  the Strength page keeps to strength, and Cardio works on a phone')
    t.open_tracker()
    names = cdp.ev("[...document.querySelectorAll('#savedWorkoutList .saved-workout-toggle strong')].map(s => s.textContent)")
    check('its saved workouts are strength workouts only', names == ['Push Day'], names)
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=800, deviceScaleFactor=1, mobile=True)
    open_cardio()
    click("#cardioActivityGrid [data-activity=elliptical]")
    fits = cdp.ev("document.documentElement.scrollWidth <= innerWidth")
    taps = cdp.ev("Math.min(...['cardioPauseBtn', 'cardioFinishBtn', 'cardioCancelBtn'].map(id => document.getElementById(id).getBoundingClientRect().height))")
    check('on a phone the page fits, and the buttons are big enough to tap', fits is True and taps >= 44, taps)
    click('#cardioFinishBtn')
    check('and so does the form', cdp.ev("document.documentElement.scrollWidth <= innerWidth") is True)
    click('#cardioFormCancel')
    cdp.answer = True
    click('#cardioCancelBtn')
    cdp.send('Emulation.clearDeviceMetricsOverride')
    t.set_cookie(t.token)
