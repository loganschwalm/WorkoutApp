"""What's new: the Tracker's card for someone who was training before a release, until Done, once on every device."""

INTERCEPT = False

DAY_MS = 86400000


def run(t):
    cdp, check, api = t.cdp, t.check, t.api
    ex = t.ex

    def account(name):
        cookie = api('POST', '/api/auth/register', {'username': name, 'email': f'{name}@example.test', 'password': 'chalk-and-plates-42'})[1]
        return cookie.split('session=')[1].split(';')[0]

    def ev(expression):
        return cdp.ev(expression)

    def shown():
        return ev("!document.getElementById('whatsNewCard').hidden")

    def server_settings(token):
        return t.api('GET', '/api/state', token=token)[0].get('settings') or {}

    # ------------------------------------------------------------------ N who sees it
    print("N   someone training before the release sees what is new, once")
    veteran = account('veteran')
    t.set_cookie(veteran)
    # The release's first day, from the page, before anything is logged; then a workout a month before it.
    t.open_tracker()
    release_start = ev("dayStart(whatsNewRelease.from)")
    api('POST', '/api/workouts', {'name': 'Push Day', 'notes': '', 'createdAt': release_start - 30 * DAY_MS, 'exercises': [ex('Bench Press', 135, 5, [(5, 135)])]}, veteran)
    t.open_tracker()
    cdp.wait("!document.getElementById('whatsNewCard').hidden", timeout=10)
    items = ev("[...document.querySelectorAll('#whatsNewList > li strong')].map(e => e.textContent)")
    folded = ev("[...document.querySelectorAll('#whatsNewMoreList > li strong')].map(e => e.textContent)")
    check('an account with a workout from before the release has the card, naming the release', shown() is True
          and ev("document.getElementById('whatsNewRelease').textContent") == ev('whatsNewRelease.name'))
    check('the first three things show, and the rest fold under how many there are',
          items == ev("whatsNewItems.slice(0, 3).map(item => item.title)") and folded == ev("whatsNewItems.slice(3).map(item => item.title)")
          and ev("document.getElementById('whatsNewMoreTitle').textContent") == f'{len(folded)} more' and ev("document.getElementById('whatsNewMore').open") is False,
          [items, folded])
    check('nothing to press is under 44px', ev("""[...document.querySelectorAll('#whatsNewCard button, #whatsNewCard summary, #whatsNewCard a')].every(e => { const box = e.getBoundingClientRect();
        return box.height >= 44 && box.width >= 44; })""") is True)
    check('nothing before the whole history is in hand',
          ev("(() => { savedWorkoutsLoaded = false; renderWhatsNew(); const hidden = document.getElementById('whatsNewCard').hidden; savedWorkoutsLoaded = true; renderWhatsNew(); return hidden; })()") is True)
    t.start(0)
    cdp.pause(0.4)
    check('a workout puts it away with the rest of the Tracker', ev("getComputedStyle(document.getElementById('whatsNewCard')).display") == 'none')
    t.end_workout()
    cdp.pause(0.3)
    check('and it is back after', ev("getComputedStyle(document.getElementById('whatsNewCard')).display") != 'none')

    link = ev("document.querySelector('#whatsNewList a').getAttribute('href')")
    check('Achievements links to them on Progress', link == 'progress.html#achievements', link)
    cdp.goto('/progress.html#achievements')
    cdp.wait("document.querySelectorAll('#achievementList .achievement').length > 0", timeout=10)
    cdp.pause(0.4)
    check('which opens there on its row', ev("document.getElementById('achievementsFold').open") is True)

    t.open_tracker()
    ev("document.getElementById('whatsNewDone').click()")
    cdp.pause(0.2)
    check('Done puts it away, and the keyboard carries on from the templates', shown() is False and ev('document.activeElement.id') == 'templatesToggle',
          ev('document.activeElement.id'))
    check('saving the release as seen, as a setting', ev('getWorkoutSettings().seenWhatsNew') == ev('whatsNewRelease.id'))
    check('which reaches the account', t.wait_for(lambda: server_settings(veteran).get('seenWhatsNew') == ev('whatsNewRelease.id')))
    t.open_tracker()
    cdp.pause(0.4)
    check('so it does not come back here', shown() is False)
    ev("localStorage.removeItem(localKey('settings'))")
    t.open_tracker()
    cdp.pause(0.6)
    check('nor on another device, which has only the account’s copy', shown() is False and ev('getWorkoutSettings().seenWhatsNew') == ev('whatsNewRelease.id'))
    ev("document.getElementById('settingsButton').click()")
    cdp.pause(0.3)
    ev("saveSettings()")
    check('and saving the Settings form keeps it', ev('getWorkoutSettings().seenWhatsNew') == ev('whatsNewRelease.id'))
    ev("closeSettings()")

    # ------------------------------------------------------------------ O who does not
    print('O   an account that began on this release has nothing to catch up on')
    newcomer = account('newcomer')
    api('POST', '/api/workouts', {'name': 'Push Day', 'notes': '', 'createdAt': release_start + DAY_MS, 'exercises': [ex('Bench Press', 135, 5, [(5, 135)])]}, newcomer)
    t.set_cookie(newcomer)
    t.open_tracker()
    cdp.pause(0.5)
    check('workouts only from after the release: no card', shown() is False)
    empty = account('emptyhanded')
    t.set_cookie(empty)
    t.open_tracker()
    cdp.pause(0.5)
    check('nothing logged at all: no card', shown() is False)
    t.set_cookie(t.token)
