"""The table the settings come from (settings-fields.js): the dialog, the defaults, and what is shown and read back all made
from it, and a setting added to it needing nothing else."""

import json

INTERCEPT = False


def run(t):
    cdp, check = t.cdp, t.check

    def ev(expression):
        return cdp.ev(expression)

    t.open_tracker()
    ev("document.getElementById('settingsButton').click()")
    cdp.pause(0.4)

    # ------------------------------------------------------------------ T the dialog
    print('T   the dialog is made from the table')
    sections = ev("[...document.querySelectorAll('#settingsForm > .settings-fold > .fold-summary > .settings-section')].map(h => h.textContent)")
    check('its sections are the table’s, in order, then the two the dialog writes out itself',
          sections == ['General', 'Training schedule', 'During a workout', 'Bar and plates', 'Rest timer', 'Your data', 'Account'], sections)
    check('the table’s are what the code says', ev('settingSections.map(section => section.title)') == sections[:5])
    # Each section is a row that folds open: General is open with the dialog (it is what is changed most, and where the focus goes),
    # and each says in a line what it holds, from the table's summary.
    folds = ev("[...document.querySelectorAll('#settingsForm > .settings-fold')].map(d => [d.id, d.open, d.querySelector('.fold-state').textContent])")
    check('each section is a row that folds, General open and the rest folded, each saying what it holds',
          [f[0] for f in folds] == ['settings-general', 'settings-schedule', 'settings-workout', 'settings-equipment', 'settings-rest', 'settings-data', 'settings-account']
          and [f[1] for f in folds] == [True] + [False] * 6 and all(f[2] for f in folds[:6]), folds)
    check('and every section of the table has an id and a summary', ev("settingSections.every(s => typeof s.id === 'string' && typeof s.summary === 'function')") is True)
    states = ev("""(() => { applySettings({ ...defaultSettings, theme: 'ocean', unit: 'kg', distanceUnit: 'km', weeklyGoal: 5, textSize: 'large',
        schedule: { days: [4, 1], time: '07:45' }, confirmEnd: false, restDuration: 120, soundEnabled: false });
      return Object.fromEntries(settingSections.map(s => [s.id, document.getElementById('settings-' + s.id + '-state').textContent])); })()""")
    check('the lines are the settings: the theme, units and goal; the days; the options on; the bar; the rest',
          states['general'] == 'Ocean · kg · km · 5 a week · Large text' and states['schedule'].startswith('Mon, Thu · ')
          and states['workout'].startswith('2 of ') and states['equipment'] == '20 kg bar · 7 plates · 2.5 kg step'
          and states['rest'] == '120 s · starts itself · no sound', states)
    ev("applySettings(defaultSettings)")
    ids = ev("[...document.querySelectorAll('[id]')].map(el => el.id)")
    check('no id is used twice on the page', len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1}))
    check('every control the table makes is in the dialog', ev("""settingFields.every(field => { const holder = document.createElement('div'); holder.innerHTML = field.html();
        return [...holder.querySelectorAll('[id]')].every(el => document.getElementById(el.id)); })""") is True)
    check('and the Test alert button is last in its section', ev("document.getElementById('testAlertButton').previousElementSibling.id") == 'silentSettingRow')

    # ------------------------------------------------------------------ D the defaults
    print('D   the defaults, and what comes back')
    entry_keys = ev("settingFields.map(field => Object.keys(field.defaults))")
    flat = [key for keys in entry_keys for key in keys]
    check('every entry has a default for each setting it owns, and no two entries own the same one', len(flat) == len(set(flat)) and all(isinstance(keys, list) for keys in entry_keys), flat)
    check('the defaults are what they were: every setting there is', sorted(flat) == sorted(ev('Object.keys(defaultSettings)')) and len(flat) == 23, sorted(flat))
    check('and a form showing them reads back as them, apart from the distance unit, which follows the weight unit until it is chosen',
          ev("applySettings(defaultSettings); JSON.stringify(Object.fromEntries(Object.entries(readSettingsForm()).sort()))") == ev("JSON.stringify(Object.fromEntries(Object.entries(defaultSettings).sort()))"))
    chosen = {'unit': 'kg', 'distanceUnit': 'km', 'weeklyGoal': 5, 'restDuration': 120, 'soundVolume': 65, 'alertSound': 'chime', 'autoRest': False, 'confirmEnd': False,
              'trackEffort': False, 'warmupSets': False, 'bigViewOnRest': True, 'keepAwakeVideo': False, 'soundEnabled': False, 'vibrate': False, 'playThroughSilent': False,
              'schedule': {'days': [1, 4], 'time': '07:45'}, 'theme': 'ocean', 'barKg': 15, 'platesKg': [25, 10], 'stepKg': 1}
    read = ev(f"applySettings({{ ...defaultSettings, ...{json.dumps(chosen)} }}); (() => {{ const c = readSettingsForm(); return JSON.stringify(Object.fromEntries(Object.entries(c).sort())); }})()")
    expected = {**json.loads(ev('JSON.stringify(defaultSettings)')), **chosen}
    check('what is chosen comes back as chosen', json.loads(read) == expected, [(k, json.loads(read).get(k), expected[k]) for k in expected if json.loads(read).get(k) != expected[k]])
    check('and what is no longer one of the choices comes back as the default', ev("""(() => { applySettings({ ...defaultSettings, unit: 'oz', weeklyGoal: 9, alertSound: 'bogus', restDuration: 5, soundVolume: 500 });
        const read = readSettingsForm(); return [read.unit, read.weeklyGoal, read.alertSound, read.restDuration, read.soundVolume]; })()""") == ['lbs', 3, 'beep', 15, 100])
    # A tick box that is off unless turned on (the big view opening itself is not for everyone), where the rest are on unless turned off.
    check('the big view opening itself is off to start with, and its tick box is clear', ev("defaultSettings.bigViewOnRest") is False
          and ev("applySettings(defaultSettings); document.getElementById('bigViewSetting').checked") is False)
    check('a setting never chosen (an account from before it, or one imported) is off too, not on',
          ev("(() => { const { bigViewOnRest, ...older } = defaultSettings; applySettings(older); return document.getElementById('bigViewSetting').checked; })()") is False)
    summary_off = ev("applySettings(defaultSettings); document.getElementById('settings-workout-state').textContent")
    summary_on = ev("applySettings({ ...defaultSettings, bigViewOnRest: true }); document.getElementById('settings-workout-state').textContent")
    on, total = (int(part) for part in summary_off.replace(' on', '').split(' of '))
    check('the row counts it only when it is on', summary_on == f'{on + 1} of {total} on' and on == total - 1, [summary_off, summary_on])
    ev("applySettings(defaultSettings)")
    check('the alert sounds in the table have tones to play, and no tone is left out',
          sorted(ev('alertSoundOptions.map(([name]) => name)')) == sorted(ev('Object.keys(alertTones)')), ev('Object.keys(alertTones)'))
    check('a control left to a browser that cannot do it is hidden, and the rest are shown', ev("""settingFields.every(field => true)
        && document.getElementById('keepAwakeSettingRow').hidden === ('wakeLock' in navigator)
        && document.getElementById('vibrateSettingRow').hidden === !canVibrate && document.getElementById('silentSettingRow').hidden === !canPlayThroughSilent""") is True)

    # ------------------------------------------------------------------ O one entry
    print('O   a setting is one entry')
    # A new setting, written as the table has them and added to it: nothing else is told, and it is shown, read, defaulted and
    # kept like the rest.
    ev("""(() => {
      window.__entry = checkSetting('demoFlag', 'demoFlagSetting', 'A setting added later');
      settingFields.push(window.__entry);
      document.getElementById('settingsForm').querySelector('#testAlertButton').insertAdjacentHTML('afterend', window.__entry.html());
    })()""")
    check('its control is made by the entry', ev("document.getElementById('demoFlagSetting').type") == 'checkbox'
          and ev("document.getElementById('demoFlagSetting').parentElement.textContent.trim()") == 'A setting added later')
    ev("applySettings({ ...defaultSettings, demoFlag: false })")
    check('applySettings shows it from the settings', ev("document.getElementById('demoFlagSetting').checked") is False)
    ev("applySettings({ ...defaultSettings })")
    check('on by default, as a tick box is', ev("document.getElementById('demoFlagSetting').checked") is True)
    ev("document.getElementById('demoFlagSetting').checked = false")
    check('and readSettingsForm reads it back, with the others', ev("readSettingsForm().demoFlag") is False and ev("Object.keys(readSettingsForm()).length") >= 22)
    ev("settingFields.pop(); document.getElementById('demoFlagSetting').closest('label').remove(); applySettings(defaultSettings)")
    check('(and it is taken out again)', ev("!document.getElementById('demoFlagSetting') && !('demoFlag' in readSettingsForm())") is True)
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
