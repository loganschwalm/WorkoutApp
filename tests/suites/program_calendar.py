"""Add to calendar: the program's remaining workouts as an .ics file on the training schedule, from the program card's ⋯ menu."""

import json

INTERCEPT = False

DAY_MS = 86400000
# A Reddit PPL with its first day done, so what is left is Push (Bench), Legs, Pull (Row), Push (Overhead Press), Legs.
PPL = {'definition': 'reddit-ppl', 'startedAt': 1000, 'cycle': 1, 'lastRollover': None,
       'trainingMaxes': {'deadlift': 225, 'row': 115, 'bench': 135, 'press': 85, 'squat': 185}, 'options': {'rounding': 5},
       'done': {'0-0': {'at': 2000, 'skipped': False, 'amrap': None, 'hit': None}}}
LEFT = ['Push (Bench)', 'Legs', 'Pull (Row)', 'Push (Overhead Press)', 'Legs']
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]


def run(t):
    cdp, check, api, token = t.cdp, t.check, t.api, t.token
    text, click = t.text, t.click

    def set_schedule(days, at='17:00'):
        cdp.ev(f"saveLocalState('settings', {{ ...getWorkoutSettings(), schedule: {{ days: {json.dumps(days)}, time: '{at}' }} }}); window.dispatchEvent(new Event('settingschange'))")

    def catch_downloads():
        """Keep what the page would save, rather than letting the browser save it."""
        cdp.ev("""(() => {
          window.saved = [];
          const create = URL.createObjectURL.bind(URL);
          URL.createObjectURL = blob => { blob.text().then(content => { window.saved.push({ content, type:blob.type }); }); return create(blob); };
          HTMLAnchorElement.prototype.click = function () { window.saved.push({ name:this.download }); };
        })()""")

    def download():
        """Choose Add to calendar and return { name, content, type } of what it saved, or None."""
        cdp.ev('window.saved = []')
        click('calendarProgramBtn')
        cdp.pause(0.4)
        saved = cdp.ev('window.saved')
        return {**saved[0], **saved[1]} if saved and len(saved) == 2 else None

    def events(content):
        """Each event's properties, with folded lines joined as a calendar app reads them."""
        return [dict(line.split(':', 1) for line in block.split('\r\n') if ':' in line) for block in content.replace('\r\n ', '').split('BEGIN:VEVENT\r\n')[1:]]

    # ------------------------------------------------------------------ the file
    print('F   the calendar file')
    api('PUT', '/api/state', {'program': PPL}, token)
    t.open_tracker()
    catch_downloads()
    check('Add to calendar is in the program card’s menu', cdp.ev("document.getElementById('programCard').contains(document.getElementById('calendarProgramBtn'))") is True)

    set_schedule([])
    check('with no days chosen, nothing is saved', download() is None)
    check('and it says to choose them', 'Choose the days you train' in text('formFeedback'), text('formFeedback'))

    set_schedule(EVERY_DAY)
    saved = download()
    check('with days chosen, a file is saved', saved is not None and saved['name'] == 'reddit-ppl.ics', saved and saved['name'])
    content = saved['content']
    check('it is a calendar', saved['type'] == 'text/calendar;charset=utf-8' and content.startswith('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n') and content.endswith('END:VCALENDAR\r\n'), content[:60])
    check('every line ends CRLF and none is over 75 octets', '\n' not in content.replace('\r\n', '') and all(len(line.encode()) <= 75 for line in content.split('\r\n')))
    found = events(content)
    check('one event for each workout left in the block, and none from the next', [e['SUMMARY'] for e in found] == [f'Reddit PPL: {name}' for name in LEFT], [e['SUMMARY'] for e in found])
    check('each starts at the schedule’s time and lasts an hour', all(e['DTSTART'].endswith('T170000') and e['DTEND'][:8] == e['DTSTART'][:8] and e['DTEND'].endswith('T180000') for e in found), found[0])
    check('on consecutive days, as every day is a training day', all(int(b['DTSTART'][6:8]) != int(a['DTSTART'][6:8]) for a, b in zip(found, found[1:])) and len({e['DTSTART'] for e in found}) == 5)
    check('each is stamped in UTC and has a UID of its own, from this run of the program', all(e['DTSTAMP'].endswith('Z') and e['UID'].startswith('1000-1-') for e in found) and len({e['UID'] for e in found}) == 5, [e['UID'] for e in found])
    description = found[0]['DESCRIPTION']
    check('the description lists the day’s exercises as planned', description.startswith('Bench Press ') and '\\n' in description and 'weights move as you train' in description, description[:80])
    again = download()
    check('saving again gives the same UIDs, so a calendar updates rather than doubles', [e['UID'] for e in events(again['content'])] == [e['UID'] for e in found])

    # ------------------------------------------------------------------ the schedule
    print('S   on the training schedule')
    set_schedule([1, 4], '06:30')
    found = events(download()['content'])
    days = cdp.ev(f"{json.dumps([e['DTSTART'] for e in found])}.map(start => new Date(+start.slice(0, 4), +start.slice(4, 6) - 1, +start.slice(6, 8)).getDay())")
    check('only the days chosen are used, at the time chosen', set(days) <= {1, 4} and all(e['DTSTART'].endswith('T063000') for e in found), days)
    check('and still every workout left, once each, in order', [e['SUMMARY'] for e in found] == [f'Reddit PPL: {name}' for name in LEFT])
    set_schedule([2], '17:00')
    starts = [e['DTSTART'] for e in events(download()['content'])]
    gaps = cdp.ev(f"{json.dumps(starts)}.map(start => Date.UTC(+start.slice(0, 4), +start.slice(4, 6) - 1, +start.slice(6, 8)))")
    check('one day a week is a workout a week', [b - a for a, b in zip(gaps, gaps[1:])] == [7 * DAY_MS] * 4, gaps)

    # ------------------------------------------------------------------ the text
    print('T   the format')
    check('commas, semicolons, backslashes and line breaks are escaped', cdp.ev("icsEscape('a,b;c\\\\d\\ne')") == 'a\\,b\\;c\\\\d\\ne')
    folded = cdp.ev("icsFold('SUMMARY:' + 'Überschrift, ünïcode — 💪 '.repeat(12))")
    lines = folded.split('\r\n')
    check('a long line is folded within 75 octets, a space starting each continuation', len(lines) > 1 and all(len(line.encode()) <= 75 for line in lines) and all(line.startswith(' ') for line in lines[1:]))
    check('and unfolds to what it was', ''.join([lines[0]] + [line[1:] for line in lines[1:]]) == 'SUMMARY:' + 'Überschrift, ünïcode — 💪 ' * 12)
