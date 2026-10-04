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
        cdp.wait("typeof getWorkoutSettings === 'function' && !!window.serverStateReady")
        # Opened once the account's settings have loaded, so the form shows them rather than this device's older copy.
        cdp.ev('window.serverStateReady.then(() => true)')
        cdp.pause(0.3)
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
    check('each change is saved as it is made, and says so', t.wait_for(lambda: stored_settings().get('soundEnabled') is False)
          and cdp.ev("document.getElementById('settingsSaved').textContent") == 'Saved.', str(stored_settings()))
    # Put back as they were, and closed with the ×, which keeps them too.
    setf('soundEnabledSetting', checked=True)
    setf('alertSoundSetting', 'beep')
    cdp.ev("document.getElementById('settingsButton').focus()")
    cdp.ev("document.getElementById('closeSettings').click()")
    check('closing Settings gives the focus back to its button', cdp.ev('document.activeElement.id') == 'settingsButton', cdp.ev('document.activeElement.id'))
    cdp.ev("document.getElementById('settingsButton').focus(); document.getElementById('settingsButton').click()")
    cdp.ev("document.getElementById('restDurationSetting').value = '120'")
    cdp.ev("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))")
    check('a rest duration still being typed is kept when Escape closes it', t.wait_for(lambda: stored_settings().get('restDuration') == 120), str(stored_settings()))
    check('and focus goes back to the button', cdp.ev('document.activeElement.id') == 'settingsButton', cdp.ev('document.activeElement.id'))
    cdp.ev("document.getElementById('settingsButton').click()")
    setf('restDurationSetting', 90)
    f = form()
    check('opening it again shows what was kept', f['sound'] and f['volume'] == '40' and f['tone'] == 'beep' and f['vibrate'], str(f))

    print('S3  saving persists across reloads and pages')
    setf('alertSoundSetting', 'chime')
    setf('soundVolumeSetting', 70)
    setf('vibrateSetting', checked=False)
    cdp.ev("document.getElementById('settingsForm').requestSubmit()")
    stored = lambda s: s.get('alertSound') == 'chime' and s.get('soundVolume') == 70 and s.get('vibrate') is False and s.get('soundEnabled') is True
    check('server stores the sound settings', t.wait_for(lambda: stored(stored_settings())), str(stored_settings()))
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
    # That was kept as soon as it changed, so sound goes back on for what follows.
    setf('soundEnabledSetting', checked=True)
    cdp.send('Page.removeScriptToEvaluateOnNewDocument', identifier=ident)

    print('S7  modal fits a phone screen')
    cdp.send('Emulation.setDeviceMetricsOverride', width=375, height=560, deviceScaleFactor=1, mobile=True)
    open_settings()
    cdp.pause(0.3)
    box = cdp.ev("(() => { const m = document.querySelector('#settingsModal .settings-modal'); const r = m.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, vh: innerHeight, scrolls: m.scrollHeight > m.clientHeight, overflowY: getComputedStyle(m).overflowY }; })()")
    check('modal stays inside the viewport', box['top'] >= 0 and box['bottom'] <= box['vh'] + 0.5, str(box))
    check('and scrolls when the content is taller', box['scrolls'] and box['overflowY'] == 'auto', str(box))
    reach = cdp.ev("(() => { const b = document.querySelector('#settingsForm button[type=submit]'); b.scrollIntoView(); const r = b.getBoundingClientRect(); return r.bottom <= innerHeight && r.top >= 0; })()")
    check('Done is reachable by scrolling', reach is True)
    slider = cdp.ev("(() => { const s = getComputedStyle(document.getElementById('soundVolumeSetting')); return { border: s.borderTopWidth, pad: s.paddingTop }; })()")
    check('volume slider is not boxed like a text field', slider['border'] == '0px' and slider['pad'] == '0px', str(slider))
    cdp.send('Emulation.clearDeviceMetricsOverride')

    print('S8  on an iPhone, the alert plays with the ringer silent, taking the audio only while it sounds')
    open_settings()
    check('a browser that cannot choose how its sound is treated is not offered the option',
          cdp.ev("document.getElementById('silentSettingRow').hidden") is True)
    # Safari's Audio Session API, as an iPhone has it: every type the page asks for is recorded.
    session = cdp.send('Page.addScriptToEvaluateOnNewDocument', source="""(() => {
      let type = 'auto'; window.__sessionTypes = [];
      Object.defineProperty(navigator, 'audioSession', { configurable: true,
        value: { get type() { return type; }, set type(value) { type = value; window.__sessionTypes.push(value); } } });
    })();""")['result']['identifier']
    open_settings()
    cdp.ev(STUBS)
    # Headless Chrome only runs sound after a real tap, so what is checked is that the page lets go of it and asks for it back.
    cdp.ev("""window.__suspends = 0; window.__resumes = 0;
      const suspend = AudioContext.prototype.suspend; AudioContext.prototype.suspend = function () { window.__suspends++; return suspend.call(this); };
      const resume = AudioContext.prototype.resume; AudioContext.prototype.resume = function () { window.__resumes++; return resume.call(this); };""")
    check('Safari is offered it, on by default', cdp.ev("!document.getElementById('silentSettingRow').hidden && document.getElementById('silentSetting').checked") is True)
    c = test_alert()
    check('the alert is played as playback audio, which follows the volume buttons', cdp.ev('window.__sessionTypes') == ['playback'] and c['osc'] == 2,
          f"{cdp.ev('window.__sessionTypes')} {c}")
    cdp.pause(1.2)
    check('once it has sounded, the audio is let go so music can carry on', cdp.ev('window.__sessionTypes') == ['playback', 'auto']
          and cdp.ev('window.__suspends') == 1, f"{cdp.ev('window.__sessionTypes')} {cdp.ev('window.__suspends')}")
    cdp.ev(RESET)
    cdp.ev("window.__sessionTypes.length = 0; window.__resumes = 0; document.getElementById('testAlertButton').click()")
    cdp.pause(0.5)
    check('the next alert takes it again and still sounds', cdp.ev('window.__sessionTypes') == ['playback'] and counts()['osc'] == 2
          and cdp.ev('window.__resumes') >= 1, f"{cdp.ev('window.__sessionTypes')} {counts()} {cdp.ev('window.__resumes')}")
    cdp.pause(1.2)
    setf('silentSetting', checked=False)
    cdp.ev('window.__sessionTypes.length = 0')
    c = test_alert()
    cdp.pause(0.4)
    check('turned off, the alert stays ambient audio, as before', cdp.ev('window.__sessionTypes') == [] and counts()['osc'] == 2,
          f"{cdp.ev('window.__sessionTypes')} {counts()}")
    setf('soundEnabledSetting', checked=False)
    check('with sound off it has nothing to do, so it is greyed out', cdp.ev("document.getElementById('silentSetting').disabled") is True)
    setf('soundEnabledSetting', checked=True)
    cdp.ev("document.getElementById('settingsForm').requestSubmit()")
    check('turning it off is saved to the account', t.wait_for(lambda: stored_settings().get('playThroughSilent') is False), stored_settings())
    open_settings()
    check('and kept when the page opens again', cdp.ev("document.getElementById('silentSetting').checked") is False)
    cdp.send('Page.removeScriptToEvaluateOnNewDocument', identifier=session)

    print('S9  sound an iPhone interrupted (a locked screen, a call) is woken, not left silent')
    open_settings()
    cdp.ev(STUBS)
    cdp.ev("""window.__resumes = 0;
      const resume = AudioContext.prototype.resume; AudioContext.prototype.resume = function () { window.__resumes++; return resume.call(this); };""")
    test_alert()
    # Safari's own state: Chrome never reports it, so the context is made to.
    cdp.ev("Object.defineProperty(audioContext, 'state', { configurable: true, get: () => 'interrupted' }); window.__resumes = 0")
    c = test_alert()
    check('an alert while interrupted asks for the sound back, and still plays its tones', cdp.ev('window.__resumes') >= 1 and c['osc'] == 2,
          f"{cdp.ev('window.__resumes')} {c}")
    cdp.ev("window.__resumes = 0; document.dispatchEvent(new Event('visibilitychange'))")
    check('so does coming back to the page, before any alert', cdp.ev('window.__resumes') >= 1, cdp.ev('window.__resumes'))
    cdp.ev("window.__closed = audioContext; Object.defineProperty(audioContext, 'state', { configurable: true, get: () => 'closed' })")
    c = test_alert()
    check('sound the browser has closed is started afresh', cdp.ev('audioContext !== window.__closed') is True and c['osc'] == 2, str(c))
