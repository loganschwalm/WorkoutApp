"""Download a finished workout or cardio session as a .tcx file, from the summary shown when one is finished and from History's menu."""

import datetime
import json

INTERCEPT = False

METRES_PER_MILE = 1609.344


def run(t):
    cdp, check, api = t.cdp, t.check, t.api
    ex = t.ex

    cookie = api('POST', '/api/auth/register', {'username': 'exporter', 'email': 'exporter@example.test', 'password': 'chalk-and-plates-42'})[1]
    lifter = cookie.split('session=')[1].split(';')[0]

    def utc_ms(*when):
        return int(datetime.datetime(*when, tzinfo=datetime.timezone.utc).timestamp() * 1000)

    def iso(ms):
        return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    def save(workout):
        return api('POST', '/api/workouts', workout, lifter)[0]['id']

    def cardio(name, activity, duration, createdAt, notes='', **numbers):
        return save({'kind': 'cardio', 'name': name, 'notes': notes, 'createdAt': createdAt, 'exercises': [], 'duration': duration,
                     'cardio': {'activity': activity, **numbers}})

    finished = utc_ms(2026, 4, 2, 10)
    ids = {
        'run': cardio('Run', 'run', 1680, finished, 'Hills & <sprints>', distance=3.1, distanceUnit='mi', calories=310, heartRate=152),
        'ride': cardio('Cycling', 'cycle', 3600, finished + 86400000, distance=20, distanceUnit='km'),
        'row': cardio('Rowing machine', 'rower', 600, finished + 2 * 86400000, distance=2000, distanceUnit='m'),
        'stairs': cardio('Stair climber', 'stairs', 900, finished + 3 * 86400000, floors=40),
        'lift': save({'name': 'Push & Pull', 'notes': 'Felt strong', 'createdAt': finished + 4 * 86400000, 'duration': 3000,
                      'exercises': [ex('Bench Press', 135, 5, [(5, 135)] * 3), ex('Squat', 185, 5, [])]}),
        'untimed': save({'name': 'Quick', 'notes': '', 'createdAt': finished + 5 * 86400000, 'exercises': [ex('Curl', 30, 10, [(10, 30)])]}),
    }
    times = {'run': finished, 'ride': finished + 86400000, 'row': finished + 2 * 86400000, 'stairs': finished + 3 * 86400000, 'lift': finished + 4 * 86400000}
    t.set_cookie(lifter)

    def catch_downloads():
        """Keep what the page would save, with its text, rather than letting the browser save it."""
        cdp.ev("""(() => {
          window.saved = [];
          window.contents = [];
          const create = URL.createObjectURL.bind(URL);
          URL.createObjectURL = blob => { blob.text().then(content => { window.contents.push(content); }); return create(blob); };
          HTMLAnchorElement.prototype.click = function () { window.saved.push(this.download); };
        })()""")

    def saved_file():
        cdp.pause(0.4)
        names = cdp.ev('window.saved') or []
        contents = cdp.ev('window.contents') or []
        cdp.ev('window.saved = []; window.contents = []')
        return {'name': names[0], 'content': contents[0]} if len(names) == 1 and len(contents) == 1 else None

    def read(content):
        """What the file says, read as an XML parser does."""
        return cdp.ev(f"""(text => {{
          const doc = new DOMParser().parseFromString(text, 'application/xml');
          const one = tag => doc.getElementsByTagName(tag)[0];
          const text_of = tag => one(tag) ? one(tag).textContent : null;
          const heart = one('AverageHeartRateBpm');
          return {{ broken: doc.getElementsByTagName('parsererror').length > 0, namespace: doc.documentElement.namespaceURI,
            sport: one('Activity').getAttribute('Sport'), id: text_of('Id'), start: one('Lap').getAttribute('StartTime'),
            seconds: text_of('TotalTimeSeconds'), metres: text_of('DistanceMeters'), calories: text_of('Calories'),
            heart: heart ? heart.firstElementChild.textContent : null, intensity: text_of('Intensity'), trigger: text_of('TriggerMethod'),
            lap: [...one('Lap').children].map(child => child.tagName),
            points: [...doc.getElementsByTagName('Trackpoint')].map(point => [point.getElementsByTagName('Time')[0].textContent,
              point.getElementsByTagName('DistanceMeters')[0] ? point.getElementsByTagName('DistanceMeters')[0].textContent : null]),
            notes: text_of('Notes') }};
        }})({json.dumps(content)})""")

    def from_history(key):
        """Choose Download .tcx in a History row's menu and return { name, content } of what it saved, or None."""
        cdp.ev('window.saved = []; window.contents = []')
        cdp.ev(f"""(() => {{ const button = document.querySelector('.history-workout[data-id="{ids[key]}"] [data-action=export]');
          if (button) button.click(); }})()""")
        return saved_file()

    # ------------------------------------------------------------------ A1 History's menu
    print("A1  a session's file, from the three dots in History's menu")
    cdp.goto('/history.html')
    cdp.wait("document.querySelectorAll('.history-workout').length >= 6")
    cdp.pause(0.5)
    catch_downloads()
    menu = lambda key: cdp.ev(f"[...document.querySelectorAll('.history-workout[data-id=\"{ids[key]}\"] .row-menu-items button')].map(b => b.textContent)")
    check('the menu offers Download .tcx between Edit and Delete', menu('run') == ['Copy as new', 'Edit', 'Download .tcx', 'Delete'], menu('run'))
    check('but not for a workout saved with no time', menu('untimed') == ['Copy as new', 'Edit', 'Delete'], menu('untimed'))

    file = from_history('run')
    day = cdp.ev(f'calendarDayKey(new Date({times["run"]}))')
    check('the file is named for the session and its day', file is not None and file['name'] == f'run-{day}.tcx', file and file['name'])
    content = file['content']
    check('it starts with the XML declaration, with nothing before it', content.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<TrainingCenterDatabase'), content[:80])
    run_file = read(content)
    check('and parses as XML in the TrainingCenter namespace', run_file['broken'] is False
          and run_file['namespace'] == 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2', run_file['namespace'])
    check('a run is Running', run_file['sport'] == 'Running', run_file['sport'])
    check('it started its time before it finished: the session is saved at its end', run_file['start'] == iso(times['run'] - 1680 * 1000)
          and run_file['id'] == run_file['start'], run_file)
    check('the lap has its time, distance in metres from miles, calories and average heart rate',
          run_file['seconds'] == '1680' and abs(float(run_file['metres']) - round(3.1 * METRES_PER_MILE, 1)) < 0.05
          and run_file['calories'] == '310' and run_file['heart'] == '152', run_file)
    check("in the schema's order, with a track", run_file['lap'] == ['TotalTimeSeconds', 'DistanceMeters', 'Calories', 'AverageHeartRateBpm',
                                                                  'Intensity', 'TriggerMethod', 'Track'], run_file['lap'])
    check('the track is two points, the start with none of the way and the end with all of it', len(run_file['points']) == 2
          and run_file['points'][0] == [run_file['start'], '0'] and run_file['points'][1][0] == iso(times['run'])
          and abs(float(run_file['points'][1][1]) - float(run_file['metres'])) < 0.001, run_file['points'])
    check('the name, what it did and its notes are the notes, escaped and read back whole',
          run_file['notes'].split('\n')[0] == 'Run' and '3.1 mi in 28:00' in run_file['notes'] and run_file['notes'].endswith('Hills & <sprints>'), run_file['notes'])
    check('the markup itself carries them escaped', 'Hills &amp; &lt;sprints&gt;' in content)

    ride = read(from_history('ride')['content'])
    check('a ride is Biking, and its kilometres are metres whatever the unit shown', ride['sport'] == 'Biking' and float(ride['metres']) == 20000.0, ride)
    row = read(from_history('row')['content'])
    check('a rower is Other, and its metres are its metres', row['sport'] == 'Other' and float(row['metres']) == 2000.0, row)
    stairs = read(from_history('stairs')['content'])
    check('stairs have no distance: none in the lap or on the track, and no heart rate or calories made up',
          stairs['sport'] == 'Other' and stairs['metres'] == '0' and all(point[1] is None for point in stairs['points'])
          and stairs['heart'] is None and stairs['calories'] == '0' and stairs['seconds'] == '900', stairs)

    lift = from_history('lift')
    lifted = read(lift['content'])
    check('a strength workout is Other, with its time and no distance', lifted['sport'] == 'Other' and lifted['seconds'] == '3000'
          and lifted['metres'] == '0' and lifted['start'] == iso(times['lift'] - 3000 * 1000), lifted)
    check('its sets are in the notes, a skipped exercise is not, and a name with & is escaped',
          lifted['notes'].split('\n') == ['Push & Pull', 'Bench Press: 3 × 5 at 135 lbs', 'Felt strong'] and 'Push &amp; Pull' in lift['content'], lifted['notes'])
    check('and its file is named for it', lift['name'].startswith('push-pull-2026-'), lift['name'])
    check('the page says what it saved and where it goes', cdp.ev("document.getElementById('historyFeedback').textContent").startswith('Downloaded push-pull-')
          and 'Strava' in cdp.ev("document.getElementById('historyFeedback').textContent")
          and 'Apple Health' in cdp.ev("document.getElementById('historyFeedback').textContent"))
    check('control characters are dropped and the rest escaped', cdp.ev("tcxText('a\\u0001b & c\\td')") == 'ab &amp; c\td')

    # ------------------------------------------------------------------ A2 the summaries
    print('A2  the button on the summary of a finished session and workout')
    cdp.goto('/cardio.html')
    cdp.wait('cardioLoaded === true')
    cdp.pause(0.4)
    catch_downloads()
    done = {'kind': 'cardio', 'name': 'Run', 'notes': '', 'createdAt': finished, 'exercises': [], 'duration': 1680,
            'cardio': {'activity': 'run', 'distance': 5, 'distanceUnit': 'km', 'heartRate': 150}}
    cdp.ev(f'showCardioSummary({json.dumps(done)}, [])')
    check('a finished session offers its file', cdp.ev("document.getElementById('cardioSummaryExport').hidden") is False)
    cdp.ev("document.getElementById('cardioSummaryExport').click()")
    first = saved_file()
    check('which is the session just finished, held in memory before it reaches the server',
          first is not None and read(first['content'])['metres'] == '5000' and read(first['content'])['heart'] == '150', first and first['name'])
    check('and says so', cdp.ev("document.getElementById('formFeedback').textContent").startswith('Downloaded run-'),
          cdp.ev("document.getElementById('formFeedback').textContent"))
    cdp.ev(f'showCardioSummary({json.dumps({**done, "duration": 0})}, [])')
    check('a session with no time offers nothing', cdp.ev("document.getElementById('cardioSummaryExport').hidden") is True)

    t.open_tracker()
    catch_downloads()
    workout = {'name': 'Upper', 'notes': '', 'createdAt': finished, 'duration': 2400, 'unit': 'lbs', 'exercises': [ex('Overhead Press', 85, 5, [(5, 85)] * 3)]}
    cdp.ev(f'showWorkoutSummary({json.dumps(workout)}, [], {{}})')
    check('a finished workout offers its file', cdp.ev("document.getElementById('summaryExport').hidden") is False)
    cdp.ev("document.getElementById('summaryExport').click()")
    second = saved_file()
    check('with its sets', second is not None and read(second['content'])['notes'].split('\n') == ['Upper', 'Overhead Press: 3 × 5 at 85 lbs'], second and second['content'])
    cdp.ev(f'showWorkoutSummary({json.dumps({k: v for k, v in workout.items() if k != "duration"})}, [], {{}})')
    check('and one saved with no time offers nothing', cdp.ev("document.getElementById('summaryExport').hidden") is True)
