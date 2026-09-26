"""Settings and custom templates: kept per account, and never undone by a change made offline."""

import json
import re

INTERCEPT = True


def run(t):
    cdp, check, api, token, wait_for = t.cdp, t.check, t.api, t.token, t.wait_for

    def server_state(tok=token):
        return api('GET', '/api/state', token=tok)[0]

    def loaded(path='/index.html'):
        """Open a page and wait until it has settled on this account's settings and templates."""
        cdp.goto(path)
        cdp.wait("typeof getWorkoutSettings === 'function' && !!window.serverStateReady")
        cdp.ev('window.serverStateReady.then(() => true)')
        cdp.pause(0.3)

    def template_names():
        return cdp.ev("[...document.querySelectorAll('#templateList h3')].map(h => h.textContent)") or []

    def rest_duration():
        return cdp.ev('getWorkoutSettings().restDuration')

    def save_settings(**changes):
        cdp.ev("document.getElementById('settingsButton').click()")
        for element, value in changes.items():
            cdp.ev(f"document.getElementById('{element}').value = {json.dumps(str(value))}")
        cdp.ev("document.getElementById('settingsForm').requestSubmit()")
        cdp.pause(0.3)

    def create_template(name, exercise, reps):
        cdp.ev("document.getElementById('createTemplateBtn').click()")
        cdp.ev(f"document.getElementById('templateName').value = {json.dumps(name)};"
               f"const row = document.getElementById('templateExercise0'); row.value = {json.dumps(exercise)}; row.dispatchEvent(new Event('input', {{ bubbles: true }}));"
               f"const reps = document.getElementById('templateReps0'); reps.value = '{reps}'; reps.dispatchEvent(new Event('input', {{ bubbles: true }}));"
               "document.getElementById('templateForm').requestSubmit()")
        cdp.pause(0.3)

    def ui_login(username, query=''):
        cdp.goto('/login.html' + query)
        cdp.ev(f"document.getElementById('username').value = {json.dumps(username)}; document.getElementById('password').value = 'password123';"
               "document.getElementById('authForm').requestSubmit()")
        cdp.wait("location.pathname !== '/login.html'")
        cdp.pause(0.3)

    # ------------------------------------------------------------------ S1 settings
    print('S1  a setting changed offline survives coming back online')
    loaded()
    check('starts from the default rest duration', rest_duration() == 90, rest_duration())
    cdp.block_api = True
    save_settings(restDurationSetting=150)
    check('the change applies straight away offline', rest_duration() == 150, rest_duration())
    cdp.block_api = False
    loaded()  # back online and reloading before the retry fires: the server still has the old value
    check('reloading keeps the offline change instead of the older server copy', rest_duration() == 150, rest_duration())
    check('and it reaches the server', wait_for(lambda: server_state()['settings'].get('restDuration') == 150),
          server_state()['settings'].get('restDuration'))

    # ------------------------------------------------------------------ S2 templates
    print('S2  a template made offline survives coming back online')
    cdp.block_api = True
    create_template('Offline Template', 'Burpee', 12)
    check('it is listed straight away', 'Offline Template' in template_names(), template_names())
    cdp.block_api = False
    loaded()
    check('reloading keeps it', 'Offline Template' in template_names(), template_names())
    check('and it reaches the server',
          wait_for(lambda: any(x.get('name') == 'Offline Template' for x in server_state()['templates'])),
          server_state()['templates'])

    # ------------------------------------------------------------------ S3 the server still wins when nothing is pending
    print('S3  a change made on another device still arrives')
    state = server_state()
    api('PUT', '/api/state', {'settings': {**state['settings'], 'restDuration': 210},
                              'templates': state['templates'] + [{'id': 'custom-server', 'name': 'Server Template',
                                                                  'exercises': [{'name': 'Row', 'reps': '10'}]}]}, token)
    loaded()
    check("the other device's setting replaces this device's clean copy", rest_duration() == 210, rest_duration())
    check("and its template appears", 'Server Template' in template_names(), template_names())
    loaded('/history.html')
    check('the History page reads the same settings', rest_duration() == 210, rest_duration())

    # ------------------------------------------------------------------ S4 another account on this browser
    print('S4  another account on the same browser never sees or inherits these')
    _, cookie = api('POST', '/api/auth/register', {'username': 'second', 'email': 'second@example.test', 'password': 'password123'})
    second = cookie.split('session=')[1].split(';')[0]
    cdp.block_paths = ['/api/state']  # the new account's own copy cannot load
    ui_login('second')
    check('signing in without ?next= lands on /', cdp.ev('location.pathname') == '/', cdp.ev('location.pathname'))
    urls = cdp.ev("performance.getEntriesByType('resource').map(e => new URL(e.name).pathname)") or []
    check('and its scripts load from the site root', urls and not any(u.startswith('/frontend/') for u in urls), str(urls))
    cdp.wait("document.querySelectorAll('#templateList h3').length >= 5")
    cdp.pause(0.5)
    names = template_names()
    check("the first account's templates are not shown", not {'Offline Template', 'Server Template'} & set(names), names)
    check("nor its settings", rest_duration() == 90, rest_duration())
    cdp.ev("document.querySelector('#templateList [data-template-action=duplicate]').click()")
    cdp.pause(0.3)
    cdp.block_paths = []
    check("the new account's template reaches its own account",
          wait_for(lambda: [x.get('name') for x in server_state(second)['templates']] == ['Push Day Copy']),
          [x.get('name') for x in server_state(second)['templates']])
    mine = [x.get('name') for x in server_state()['templates']]
    check("and the first account's templates are unchanged", mine == ['Offline Template', 'Server Template'], mine)

    ui_login('tester')
    cdp.wait("document.querySelectorAll('#templateList h3').length >= 7")
    names = template_names()
    check('signing back in shows the first account its own templates',
          {'Offline Template', 'Server Template'} <= set(names) and 'Push Day Copy' not in names, names)

    # ------------------------------------------------------------------ S5 upgrading from the shared copy
    print('S5  settings kept by the previous version are adopted')
    me = api('GET', '/api/auth/me', token=token)[0]['user']['id']
    loaded()
    cdp.ev(f"localStorage.removeItem('workout-tracker-settings-{me}'); localStorage.removeItem('workout-tracker-templates-{me}');"
           f"localStorage.setItem('workout-tracker-last-user', '{me}');"
           "localStorage.setItem('workout-tracker-settings', JSON.stringify({ theme: 'dark', restDuration: 95 }));"
           "localStorage.setItem('workout-tracker-custom-templates', JSON.stringify([{ id: 'custom-old', name: 'Old Shared', exercises: [{ name: 'Dip', reps: '8' }] }]))")
    cdp.block_paths = ['/api/state']
    loaded()
    check('the old copy is used while the server cannot be reached',
          cdp.ev('document.documentElement.dataset.theme') == 'dark' and rest_duration() == 95 and 'Old Shared' in template_names(),
          f"{cdp.ev('document.documentElement.dataset.theme')} {rest_duration()} {template_names()}")
    check('the shared keys are gone', cdp.ev("localStorage.getItem('workout-tracker-settings') === null && localStorage.getItem('workout-tracker-custom-templates') === null") is True)
    cdp.block_paths = []
    loaded()
    check("once the server answers, its copy replaces the old one (it was never changed here)",
          rest_duration() == 210 and 'Old Shared' not in template_names(), f'{rest_duration()} {template_names()}')
    check('and nothing from the old copy was uploaded', 'Old Shared' not in [x.get('name') for x in server_state()['templates']])

    # ------------------------------------------------------------------ S6 export and import
    print('S6  exporting and importing from Settings')
    loaded()
    # Downloads are caught instead of saved: each one's file name and contents are kept for the checks below.
    cdp.ev("""window.__downloads = [];
      const createURL = URL.createObjectURL;
      URL.createObjectURL = blob => { window.__blob = blob; return createURL(blob); };
      HTMLAnchorElement.prototype.click = function () { if (this.download) window.__downloads.push({ name: this.download, blob: window.__blob }); };""")
    cdp.ev("document.getElementById('settingsButton').click()")
    shown = cdp.ev("['exportButton', 'exportCsvButton', 'importButton'].map(id => document.getElementById(id).offsetParent !== null)")
    check('Settings offers Export, Export sets as CSV and Import', shown == [True, True, True], shown)
    # A finished workout still waiting on this device uploads first, so the file has it.
    cdp.ev("queuePendingWorkout({ name: 'Waiting Workout', notes: '', createdAt: Date.now(), clientId: 'waiting-1', "
           "exercises: [{ name: 'Squat', weight: 100, reps: 5, sets: [{ weight: 100, reps: 5 }] }] })")
    cdp.ev("document.getElementById('exportButton').click()")
    check('Export downloads a file', cdp.wait('window.__downloads.length === 1'), cdp.ev("document.getElementById('dataStatus').textContent"))
    name = cdp.ev('window.__downloads[0] && window.__downloads[0].name') or ''
    check("named with today's date", re.fullmatch(r'workout-tracker-\d{4}-\d{2}-\d{2}\.json', name), name)
    exported = json.loads(cdp.ev('window.__downloads[0].blob.text()') or '{}')
    names = [w.get('name') for w in exported.get('workouts', [])]
    check('with every workout, the one that was waiting on this device too',
          'Waiting Workout' in names and len(names) == len(api('GET', '/api/workouts', token=token)[0]['workouts']), names)
    check('and the templates', 'Offline Template' in [x.get('name') for x in exported.get('templates', [])], exported.get('templates'))
    check('the status says so', cdp.ev("document.getElementById('dataStatus').textContent") == f'Downloaded {name}.',
          cdp.ev("document.getElementById('dataStatus').textContent"))
    cdp.ev("document.getElementById('exportCsvButton').click()")
    check('Export sets as CSV downloads a spreadsheet', cdp.wait("window.__downloads.length === 2 && window.__downloads[1].name.endsWith('.csv')"),
          cdp.ev('window.__downloads.map(d => d.name)'))
    sheet = cdp.ev('window.__downloads[1] ? window.__downloads[1].blob.text() : ""') or ''
    check('of every set, with a header row', 'Date,Workout,Exercise,Set,Weight,Unit,Reps,Seconds' in sheet and 'Waiting Workout,Squat,1,100,lbs,5' in sheet, sheet[:200])
    cdp.block_api = True
    cdp.ev("document.getElementById('exportButton').click()")
    check('offline, Export says it could not reach the server', cdp.wait("document.getElementById('dataStatus').textContent.startsWith('Could not reach')"),
          cdp.ev("document.getElementById('dataStatus').textContent"))
    check('and downloads nothing', cdp.ev('window.__downloads.length') == 2, cdp.ev('window.__downloads.length'))
    cdp.block_api = False

    def choose(text, filename):
        cdp.ev(f"""(() => {{
          const files = new DataTransfer();
          files.items.add(new File([{json.dumps(text)}], {json.dumps(filename)}, {{ type: 'application/json' }}));
          const input = document.getElementById('importFile');
          input.files = files.files;
          input.dispatchEvent(new Event('change'));
        }})()""")

    _, cookie = api('POST', '/api/auth/register', {'username': 'third', 'email': 'third@example.test', 'password': 'password123'})
    third = cookie.split('session=')[1].split(';')[0]
    api('POST', '/api/workouts', {'name': 'From Elsewhere', 'notes': '', 'clientId': 'elsewhere-1',
                                  'exercises': [{'name': 'Row', 'weight': 60, 'reps': 8, 'sets': [{'weight': 60, 'reps': 8}]}]}, third)
    elsewhere = api('GET', '/api/export', token=third)[0]
    asked = len(cdp.dialogs)
    choose(json.dumps(elsewhere), 'elsewhere.json')
    check('Import asks first, saying how many workouts', wait_for(lambda: len(cdp.dialogs) > asked) and len(cdp.dialogs) == asked + 1
          and cdp.dialogs[-1].startswith('Import 1 workout from elsewhere.json?'), cdp.dialogs[asked:])
    check('then says what it added', cdp.wait("document.getElementById('dataStatus').textContent.startsWith('Imported 1 workout.')"),
          cdp.ev("document.getElementById('dataStatus').textContent"))
    check('and the account has it', 'From Elsewhere' in [w['name'] for w in api('GET', '/api/workouts', token=token)[0]['workouts']])
    cdp.ev("document.getElementById('closeSettings').click()")
    check('closing Settings shows it in the list', cdp.wait("[...document.querySelectorAll('#savedWorkoutList strong')].some(s => s.textContent === 'From Elsewhere')", 10))
    cdp.ev("document.getElementById('settingsButton').click()")
    asked = len(cdp.dialogs)
    choose('Date,Workout\n', 'sets.csv')
    check('a file that is not an export is turned away without asking',
          cdp.wait("document.getElementById('dataStatus').textContent.startsWith('sets.csv is not a Workout Tracker export')") and len(cdp.dialogs) == asked,
          cdp.ev("document.getElementById('dataStatus').textContent"))
