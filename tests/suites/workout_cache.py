"""Reading an account's workouts: the ETag that lets a page that already has them be told so (GET /api/workouts answering 304),
the triggers and the index behind it, and a repeat load in the browser being revalidated rather than downloaded again."""

import http.client
import json
import secrets
import sqlite3
import time

INTERCEPT = False

DAY_MS = 86400000
PASSWORD = 'chalk-and-plates-42'


def run(t):
    cdp, check, api, token, request = t.cdp, t.check, t.api, t.token, t.request
    database = t.db_path('test.db')

    def conditional(path, tag=None, who=None):
        """A GET with an If-None-Match, as a browser holding the answer sends it: (status, every header, body)."""
        connection = http.client.HTTPConnection('127.0.0.1', t.port, timeout=10)
        headers = {'Cookie': f'session={who or token}'}
        if tag is not None:
            headers['If-None-Match'] = tag
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        headers = response.getheaders()
        connection.close()
        return response.status, headers, body

    def etag(who=None):
        return dict((name.lower(), value) for name, value in conditional('/api/workouts', who=who)[1])['etag']

    def post(body, who=None):
        return request('POST', '/api/workouts', json.dumps(body).encode(), {'Content-Type': 'application/json'}, token=who or token)

    def sql(statement, *args):
        db = sqlite3.connect(database)
        try:
            rows = db.execute(statement, args).fetchall()
            db.commit()
            return rows
        finally:
            db.close()

    def made(name, days_ago=0, client_id=None):
        return {'name': name, 'notes': '', 'createdAt': int(time.time() * 1000) - days_ago * DAY_MS, 'exercises': [t.ex('Bench Press', 100, 5, [(5, 100)])],
                **({'clientId': client_id} if client_id else {})}

    # ------------------------------------------------------------------ E the ETag
    print('E   a page that has the workouts is told they are current')
    status, headers, body = conditional('/api/workouts')
    named = [name for name, _ in headers]
    sent = {name.lower(): value for name, value in headers}
    tag = sent['etag']
    check('the workouts come with a weak ETag the browser may keep them under', status == 200 and tag.startswith('W/"') and len(json.loads(body)['workouts']) == 3, f'{status} {tag}')
    check('which it must check with the server each time, and keep to itself', sent['cache-control'] == 'private, no-cache' and named.count('Cache-Control') == 1, headers)
    status, headers, body = conditional('/api/workouts', tag)
    sent = {name.lower(): value for name, value in headers}
    check('asking again with that tag is answered 304, with no body', status == 304 and body == b'' and 'content-type' not in sent, f'{status} {body[:40]!r}')
    check('which repeats the tag and how to keep it', sent.get('etag') == tag and sent.get('cache-control') == 'private, no-cache', sent)
    check('the same tag written strong, or among others, or as *, is just as good', all(conditional('/api/workouts', value)[0] == 304 for value in (tag[2:], f'"other", {tag}', f'{tag} , "x"', '*')))
    check('another tag, or none, is a whole answer', conditional('/api/workouts', 'W/"abc"')[0] == 200 and conditional('/api/workouts', '')[0] == 200 and conditional('/api/workouts', 'garbage')[0] == 200)
    check('signed out there is no 304 for anyone: the answer is 401', request('GET', '/api/workouts', None, {'If-None-Match': tag})[0] == 401)
    status, headers, _ = conditional('/api/state')
    check('the rest of the API is still not kept', {name.lower(): value for name, value in headers}['cache-control'] == 'no-store' and [n for n, _ in headers].count('Cache-Control') == 1, headers)

    # ------------------------------------------------------------------ C what changes it
    print('C   every change to the workouts changes the tag, and nothing else does')
    status, _, reply = post(made('Cache One', client_id='cache-one'))
    added = etag()
    check('saving a workout changes it', status == 201 and added != tag, f'{status} {tag} {added}')
    check('and the new answer has the workout', conditional('/api/workouts', tag)[0] == 200 and 'Cache One' in [w['name'] for w in json.loads(conditional('/api/workouts', tag)[2])['workouts']])
    status, _, _ = post(made('Cache One', client_id='cache-one'))
    check('an upload sent twice (a retry) changes nothing, the second being refused as the first', status == 200 and etag() == added, status)
    workout_id = reply['id']
    request('PUT', f'/api/workouts/{workout_id}', json.dumps({**made('Cache One'), 'notes': 'a'}).encode(), {'Content-Type': 'application/json'}, token=token)
    edited = etag()
    check('editing one changes it', edited != added)
    request('PUT', f'/api/workouts/{workout_id}', json.dumps({**made('Cache One'), 'notes': 'b'}).encode(), {'Content-Type': 'application/json'}, token=token)
    check('even an edit that leaves it the same size', etag() not in (added, edited))
    before = etag()
    api('PUT', '/api/state', {'settings': {'restDuration': 120}}, token)
    api('POST', '/api/active-session', {'session': None}, token)
    check('settings and the workout in progress are not workouts, and leave it alone', etag() == before)
    request('DELETE', f'/api/workouts/{workout_id}', None, None, token=token)
    check('deleting one changes it', etag() != before)
    before = etag()
    request('DELETE', f'/api/workouts/{workout_id}', None, None, token=token)
    check('deleting one that is gone does not', etag() == before)
    sql('UPDATE workouts SET notes = ? WHERE user_id = (SELECT id FROM users WHERE username = ?) AND name = ?', 'edited behind the server’s back', 'tester', 'Seed Pull')
    check('and a change made to the database by anything else changes it too, the tag being kept by the database', etag() != before)

    # ------------------------------------------------------------------ A accounts
    print('A   each account has its own')
    other_token = api('POST', '/api/auth/register', {'username': 'cachier', 'email': 'cachier@example.test', 'password': PASSWORD})[1].split('session=')[1].split(';')[0]
    mine, theirs = etag(), etag(other_token)
    check('another account has a tag of its own, with no workouts yet', theirs != mine and json.loads(conditional('/api/workouts', who=other_token)[2])['workouts'] == [], f'{mine} {theirs}')
    check('and the first one’s tag is no use to it', conditional('/api/workouts', mine, other_token)[0] == 200)
    check('nor does either’s workouts change the other’s tag', etag(other_token) == theirs and etag() == mine)
    post(made('Theirs'), other_token)
    check('a workout of its own changes its own tag, and not the first’s', etag(other_token) != theirs and etag() == mine)
    exported = api('GET', '/api/export', token=token)[0]
    third_token = api('POST', '/api/auth/register', {'username': 'importer', 'email': 'importer@example.test', 'password': PASSWORD})[1].split('session=')[1].split(';')[0]
    empty = etag(third_token)
    status, _, _ = request('POST', '/api/import', json.dumps(exported).encode(), {'Content-Type': 'application/json'}, token=third_token)
    check('importing workouts changes the tag, however many it adds', status == 200 and etag(third_token) != empty and len(json.loads(conditional('/api/workouts', who=third_token)[2])['workouts']) >= 3, status)
    # An account from before the tags has workouts and none: the first read gives it one, and it holds.
    sql('DELETE FROM workout_versions')
    first = etag()
    check('an account with workouts from before the tags is given one on its first read, which then holds', conditional('/api/workouts', first)[0] == 304 and etag() == first)
    leaver_token = api('POST', '/api/auth/register', {'username': 'leaver', 'email': 'leaver@example.test', 'password': PASSWORD})[1].split('session=')[1].split(';')[0]
    post(made('Gone soon'), leaver_token)
    leaver_id = sql('SELECT id FROM users WHERE username = ?', 'leaver')[0][0]
    check('it is kept in the database', sql('SELECT COUNT(*) FROM workout_versions WHERE user_id = ?', leaver_id)[0][0] == 1)
    status, _, _ = request('POST', '/api/account/delete', json.dumps({'password': PASSWORD}).encode(), {'Content-Type': 'application/json'}, token=leaver_token)
    check('and goes with the account', status == 200 and sql('SELECT COUNT(*) FROM workout_versions WHERE user_id = ?', leaver_id)[0][0] == 0, status)

    # ------------------------------------------------------------------ I the index
    print('I   the workouts are read in the order they are kept')
    plan = ' '.join(row[3] for row in sql("EXPLAIN QUERY PLAN SELECT id, name, notes, created_at, payload FROM workouts WHERE user_id = 1 ORDER BY created_at DESC"))
    check('by an index on the account and the time, with no sorting afterwards', 'workouts_user_created' in plan and 'TEMP B-TREE' not in plan, plan)
    check('which is there in the database', sql("SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = 'workouts_user_created'")[0][0] == 1)
    triggers = sorted(row[0] for row in sql("SELECT name FROM sqlite_master WHERE type = 'trigger' AND name NOT LIKE 'workouts_bytes_%'"))
    check('as are the three triggers that keep the tags', triggers == ['workouts_deleted', 'workouts_inserted', 'workouts_updated'], triggers)

    # ------------------------------------------------------------------ S signing out
    print('S   signing out clears what the browser kept')
    login_token = api('POST', '/api/auth/login', {'login': 'importer', 'password': PASSWORD})[1].split('session=')[1].split(';')[0]
    status, headers, _ = request('POST', '/api/auth/logout', b'{}', {'Content-Type': 'application/json'}, token=login_token)
    check('the answer to signing out says so', status == 200 and headers.get('clear-site-data') == '"cache"', headers)
    check('and none of the other answers do', 'clear-site-data' not in request('GET', '/api/auth/me')[1])

    # ------------------------------------------------------------------ B in the browser
    print('B   a repeat visit is checked rather than downloaded')
    # Notes that do not compress, so the whole history is a big download and a check on it a small one.
    for index in range(150):
        post({**made(f'Older {index:03d}', days_ago=20 + index), 'notes': secrets.token_hex(50)}, token)

    def workouts_request():
        """The page's own request for the workouts, as the browser timed it: how much came over the wire, and what it was."""
        return cdp.ev("(() => { const entry = performance.getEntriesByType('resource').filter(item => new URL(item.name).pathname === '/api/workouts').pop(); "
                      "return entry ? { sent: entry.transferSize, body: entry.decodedBodySize } : null; })()")

    def open_history():
        cdp.goto('/history.html')
        cdp.wait("document.querySelectorAll('.history-workout').length >= 3")
        cdp.pause(0.5)
        return cdp.ev("document.getElementById('historySummary').textContent")

    t.open_tracker()
    first = workouts_request()
    check('the first page to ask downloads them all', first and first['sent'] > 10000 and first['body'] > 30000, first)
    summary = open_history()
    next_page = workouts_request()
    check('the next page only checks: a few hundred bytes, for the same workouts', next_page and next_page['sent'] < 1000 and next_page['body'] == first['body'], [first, next_page])
    check('and shows them all', 'Older 000' in cdp.ev("document.getElementById('historyList').textContent") or summary != '', summary)
    t.open_tracker()
    check('as does the page after it, and a reload', workouts_request()['sent'] < 1000, workouts_request())

    post(made('Fresh from the gym'), token)
    open_history()
    fresh = workouts_request()
    check('a workout saved since is downloaded with the rest', fresh and fresh['sent'] > 10000, fresh)
    check('and shown', cdp.wait("document.getElementById('historyList').textContent.includes('Fresh from the gym')"))
    t.open_tracker()
    check('and the next page checks again', workouts_request()['sent'] < 1000, workouts_request())

    cdp.ev("document.getElementById('settingsButton').click()")
    cdp.pause(0.4)
    cdp.ev("document.getElementById('signOutButton').click()")
    cdp.wait("location.pathname.endsWith('login.html')", timeout=10)
    t.set_cookie(api('POST', '/api/auth/login', {'login': 'tester', 'password': PASSWORD})[1].split('session=')[1].split(';')[0])
    open_history()
    after = workouts_request()
    check('after signing out, what the browser kept is gone: the next visit downloads them again', after and after['sent'] > 10000, after)
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
