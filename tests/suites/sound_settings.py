"""The rest-timer alert settings: tone, volume, vibration, Test alert, and persistence."""

import json

INTERCEPT = True


def run(t):
    cdp, check, api, token = t.cdp, t.check, t.api, t.token
    open_tracker, start, log_set, end_workout = t.open_tracker, t.start, t.log_set, t.end_workout

    # ------------------------------------------------------------------ sound settings
    STUBS = """window.__osc = 0; window.__gains = []; window.__vib = [];
      const co = AudioContext.prototype.createOscillator; AudioContext.prototype.createOscillator = function () { window.__osc++; return co.call(this); };
      const sv = AudioParam.prototype.setValueAtTime; AudioParam.prototype.setValueAtTime = function (v, t) { window.__gains.push(v); return sv.call(this, v, t); };
      navigator.vibrate = p => { window.__vib.push(p); return true; };"""
    RESET = "window.__osc = 0; window.__gains = []; window.__vib = []"

    def counts():
        return cdp.ev('({ osc: window.__osc, vib: window.__vib.length, gain: window.__gains[0] ?? null })')

    def setf(element, value=None, checked=None):
        body = f"e.checked = {str(checked).lower()};" if checked is not None else f"e.value = {json.dumps(str(value))};"
        cdp.ev(f"(() => {{ const e = document.getElementById('{element}'); {body} e.dispatchEvent(new Event('input', {{ bubbles: true }})); e.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()")

    def open_settings(page='/index.html'):
        cdp.goto(page)
        cdp.wait("typeof getWorkoutSettings === 'function'")
        cdp.pause(0.5)
        cdp.ev("document.getElementById('settingsButton').click()")

    def form():
        return cdp.ev("""({ sound: soundEnabledSetting.checked, tone: alertSoundSetting.value, volume: soundVolumeSetting.value, vibrate: vibrateSetting.checked,
          toneOff: alertSoundSetting.disabled, volumeOff: soundVolumeSetting.disabled, testOff: testAlertButton.disabled })""")

    def stored_settings():
        return api('GET', '/api/state', token=token)[0]['settings']

    def test_alert():
        cdp.ev(RESET)
        cdp.ev("document.getElementById('testAlertButton').click()")
        cdp.pause(0.2)
        return counts()

    print('S1  controls and defaults')
    open_settings()
    cdp.ev(STUBS)
    f = form()
    check('sound on, volume 40, double beep, vibrate on by default', f['sound'] and f['volume'] == '40' and f['tone'] == 'beep' and f['vibrate'], str(f))
    check('vibration option is offered where the device supports it', cdp.ev("!document.getElementById('vibrateSettingRow').hidden") is True)

    print('S2  Test alert plays the values in the form (before saving)')
    c = test_alert()
    check('default: double beep at the previous fixed loudness, plus vibration', c['osc'] == 2 and c['vib'] == 1 and abs((c['gain'] or 0) - 0.12) < 1e-6, str(c))
    setf('alertSoundSetting', 'chime')
    c = test_alert()
    check('chime is three notes', c['osc'] == 3, str(c))
    setf('alertSoundSetting', 'long')
    c = test_alert()
    check('long tone is one note', c['osc'] == 1, str(c))
    setf('soundVolumeSetting', 100)
    c = test_alert()
    check('volume 100 is louder than the default', abs((c['gain'] or 0) - 0.3) < 1e-6, str(c))
    setf('soundVolumeSetting', 0)
    c = test_alert()
    check('volume 0 is silent', c['osc'] == 0, str(c))
    setf('soundVolumeSetting', 40)
    setf('vibrateSetting', checked=False)
    c = test_alert()
    check('vibration can be turned off on its own', c['osc'] == 1 and c['vib'] == 0, str(c))
    setf('soundEnabledSetting', checked=False)
    f = form()
    check('with sound off, tone and volume are disabled', f['toneOff'] and f['volumeOff'], str(f))
    check('with sound and vibration off, Test alert is disabled', f['testOff'] is True, str(f))
    setf('vibrateSetting', checked=True)
    c = test_alert()
    check('sound off + vibration on: only vibrates', c['osc'] == 0 and c['vib'] == 1 and form()['testOff'] is False, str(c))
    cdp.ev("document.getElementById('cancelSettings').click(); document.getElementById('settingsButton').click()")
    f = form()
    check('cancelling discards the changes', f['sound'] and f['volume'] == '40' and f['tone'] == 'beep' and f['vibrate'], str(f))
    check('nothing was saved by testing', 'alertSound' not in stored_settings() or stored_settings().get('alertSound') == 'beep', str(stored_settings()))

    print('S3  saving persists across reloads and pages')
    setf('alertSoundSetting', 'chime')
    setf('soundVolumeSetting', 70)
    setf('vibrateSetting', checked=False)
    cdp.ev("document.getElementById('settingsForm').requestSubmit()")
    cdp.pause(0.8)
    s = stored_settings()
    check('server stores the sound settings', s.get('alertSound') == 'chime' and s.get('soundVolume') == 70 and s.get('vibrate') is False and s.get('soundEnabled') is True, str(s))
    for page in ('/index.html', '/history.html', '/progress.html'):
        open_settings(page)
        f = form()
        check(f'{page[1:-5]} page shows the saved values', f['tone'] == 'chime' and f['volume'] == '70' and f['vibrate'] is False and f['sound'] is True, str(f))
    open_settings('/history.html')
    cdp.ev(STUBS)
    c = test_alert()
    check('Test alert works from the History page too', c['osc'] == 3 and abs((c['gain'] or 0) - 0.21) < 1e-6 and c['vib'] == 0, str(c))

    print('S4  the rest timer uses the saved settings')
    def rest_end():
        open_tracker()
        cdp.ev(STUBS)
        cdp.ev("window.__offset = 0; const realNow = Date.now.bind(Date); Date.now = () => realNow() + window.__offset;")
        start(0)
        cdp.pause(0.4)
        log_set(8)
        cdp.pause(0.3)
        cdp.ev("window.__offset = 200000")
        cdp.pause(0.8)
        result = counts()
        end_workout()
        return result
    c = rest_end()
    check('chime at 70% volume, no vibration', c['osc'] == 3 and abs((c['gain'] or 0) - 0.21) < 1e-6 and c['vib'] == 0, str(c))
    api('PUT', '/api/state', {'settings': {**stored_settings(), 'soundEnabled': False, 'vibrate': True}}, token)
    c = rest_end()
    check('sound off + vibration on: vibrates silently', c['osc'] == 0 and c['vib'] == 1, str(c))
    api('PUT', '/api/state', {'settings': {**stored_settings(), 'soundEnabled': False, 'vibrate': False}}, token)
    c = rest_end()
    check('both off: the timer still ends, with no alert', c['osc'] == 0 and c['vib'] == 0, str(c))

    print('S5  settings saved before this feature existed')
    api('PUT', '/api/state', {'settings': {'theme': 'dark', 'restDuration': 120, 'autoRest': True, 'confirmEnd': True}}, token)
    open_settings()
    f = form()
    check('sound settings fall back to the defaults', f['sound'] and f['volume'] == '40' and f['tone'] == 'beep' and f['vibrate'], str(f))
    check('existing settings are kept', cdp.ev("document.documentElement.dataset.theme") == 'dark' and cdp.ev("document.getElementById('restDurationSetting').value") == '120')
    c = rest_end()
    check('rest end plays the default double beep', c['osc'] == 2 and c['vib'] == 1, str(c))
    end_workout()

    print('S6  devices without vibration support')
    ident = cdp.send('Page.addScriptToEvaluateOnNewDocument', source='delete Navigator.prototype.vibrate;')['result']['identifier']
    open_settings()
    row = cdp.ev("({ hidden: vibrateSettingRow.hidden, display: getComputedStyle(vibrateSettingRow).display, testOff: testAlertButton.disabled })")
    check('vibration option is hidden', row['hidden'] is True and row['display'] == 'none', str(row))
    check('Test alert still works for sound', row['testOff'] is False, str(row))
    setf('soundEnabledSetting', checked=False)
    check('and is disabled when sound is off', form()['testOff'] is True)
    cdp.send('Page.removeScriptToEvaluateOnNewDocument', identifier=ident)

    print('S7  modal fits a phone screen')
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=560, deviceScaleFactor=1, mobile=True)
    open_settings()
    cdp.pause(0.3)
    box = cdp.ev("(() => { const m = document.querySelector('#settingsModal .settings-modal'); const r = m.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, vh: innerHeight, scrolls: m.scrollHeight > m.clientHeight, overflowY: getComputedStyle(m).overflowY }; })()")
    check('modal stays inside the viewport', box['top'] >= 0 and box['bottom'] <= box['vh'] + 0.5, str(box))
    check('and scrolls when the content is taller', box['scrolls'] and box['overflowY'] == 'auto', str(box))
    reach = cdp.ev("(() => { const b = document.querySelector('#settingsForm button[type=submit]'); b.scrollIntoView(); const r = b.getBoundingClientRect(); return r.bottom <= innerHeight && r.top >= 0; })()")
    check('Save settings is reachable by scrolling', reach is True)
    slider = cdp.ev("(() => { const s = getComputedStyle(document.getElementById('soundVolumeSetting')); return { border: s.borderTopWidth, pad: s.paddingTop }; })()")
    check('volume slider is not boxed like a text field', slider['border'] == '0px' and slider['pad'] == '0px', str(slider))
    cdp.send('Emulation.clearDeviceMetricsOverride')
