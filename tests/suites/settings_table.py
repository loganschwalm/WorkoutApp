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
    sections = ev("[...document.querySelectorAll('#settingsForm > .settings-section')].map(h => h.textContent)")
    check('its sections are the table’s, in order, then the two the dialog writes out itself',
          sections == ['General', 'Training schedule', 'During a workout', 'Bar and plates', 'Rest timer', 'Your data', 'Account'], sections)
    check('the table’s are what the code says', ev('settingSections.map(section => section.title)') == sections[:5])
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
    check('the defaults are what they were: every setting there is', sorted(flat) == sorted(ev('Object.keys(defaultSettings)')) and len(flat) == 22, sorted(flat))
    check('and a form showing them reads back as them, apart from the distance unit, which follows the weight unit until it is chosen',
          ev("applySettings(defaultSettings); JSON.stringify(Object.fromEntries(Object.entries(readSettingsForm()).sort()))") == ev("JSON.stringify(Object.fromEntries(Object.entries(defaultSettings).sort()))"))
    chosen = {'unit': 'kg', 'distanceUnit': 'km', 'weeklyGoal': 5, 'restDuration': 120, 'soundVolume': 65, 'alertSound': 'chime', 'autoRest': False, 'confirmEnd': False,
              'trackEffort': False, 'warmupSets': False, 'keepAwakeVideo': False, 'soundEnabled': False, 'vibrate': False, 'playThroughSilent': False,
              'schedule': {'days': [1, 4], 'time': '07:45'}, 'theme': 'ocean', 'barKg': 15, 'platesKg': [25, 10], 'stepKg': 1}
    read = ev(f"applySettings({{ ...defaultSettings, ...{json.dumps(chosen)} }}); (() => {{ const c = readSettingsForm(); return JSON.stringify(Object.fromEntries(Object.entries(c).sort())); }})()")
    expected = {**json.loads(ev('JSON.stringify(defaultSettings)')), **chosen}
    check('what is chosen comes back as chosen', json.loads(read) == expected, [(k, json.loads(read).get(k), expected[k]) for k in expected if json.loads(read).get(k) != expected[k]])
    check('and what is no longer one of the choices comes back as the default', ev("""(() => { applySettings({ ...defaultSettings, unit: 'oz', weeklyGoal: 9, alertSound: 'bogus', restDuration: 5, soundVolume: 500 });
        const read = readSettingsForm(); return [read.unit, read.weeklyGoal, read.alertSound, read.restDuration, read.soundVolume]; })()""") == ['lbs', 3, 'beep', 15, 100])
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
