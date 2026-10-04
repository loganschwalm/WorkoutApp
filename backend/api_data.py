"""Data endpoints: workouts, the workout in progress, the synced state, export and import (see api_routes.py)."""

import datetime
import json
import threading
import time
from http import HTTPStatus
from urllib.parse import urlparse

from config import EXPORT_FORMAT, MAX_IMPORT, MAX_IMPORTS_AT_ONCE, MAX_STATE_CHANGE
from database import connection, workout_tag
from state import STATE_PARTS, load_state, merge_part, store_state, validate_state
from validation import BadRequest, check_workout_room, listed, validate_workout, weight_unit, workout_payload, workouts_held
from workouts import etag_matches, export_zone, exported_workouts, workout_id, workout_stored, workouts_csv


# One import at a time (see MAX_IMPORTS_AT_ONCE): each reads and parses a body of up to MAX_IMPORT bytes.
import_slots = threading.BoundedSemaphore(MAX_IMPORTS_AT_ONCE)


class DataApi:
    """The endpoints of an account's data: its workouts, the workout in progress, its synced state, and exporting and importing it."""

    def list_workouts(self, user):
        with connection() as database:
            # A page already holding the history is told so, rather than sent it again: every page asks on every load,
            # and the history only grows. Cached by the browser, which checks with the server each time (no-cache), under a
            # tag that changes whenever a workout does. The tag is read first, so workouts changing meanwhile can only
            # leave the browser with newer ones than the tag says, which it then asks for again.
            etag = f'W/"{workout_tag(database, user["id"])}"'
            caching = {'ETag': etag, 'Cache-Control': 'private, no-cache'}
            if etag_matches(self.headers.get('If-None-Match'), etag):
                self.send_response(HTTPStatus.NOT_MODIFIED)
                for name, value in caching.items():
                    self.send_header(name, value)
                self.end_headers()
                return
            rows = database.execute('SELECT id, name, notes, created_at, payload FROM workouts WHERE user_id = ? ORDER BY created_at DESC', (user['id'],)).fetchall()
            workouts = []
            for row in rows:
                item = json.loads(row['payload'])
                item.update(id=row['id'], name=row['name'], notes=row['notes'], createdAt=row['created_at'])
                workouts.append(item)
            self.send_json(HTTPStatus.OK, {'workouts': workouts}, headers=caching)

    def create_workout(self, user):
        data = self.read_json()
        name, notes, created_at = validate_workout(data)
        client_id = data.get('clientId') or None
        payload = workout_payload(data)
        with connection() as database:
            # Held for writing from here, so two requests cannot both take the account's last place.
            database.execute('BEGIN IMMEDIATE')
            # Clients retry uploads after network failures, so a repeated clientId must not create a second workout, and is
            # answered even by an account that has since reached its limit.
            stored = client_id and database.execute('SELECT id FROM workouts WHERE user_id = ? AND client_id = ?', (user['id'], client_id)).fetchone()
            if stored:
                status, stored_id = HTTPStatus.OK, stored['id']
            else:
                check_workout_room(workouts_held(database, user['id']))
                status = HTTPStatus.CREATED
                stored_id = database.execute('INSERT INTO workouts (user_id, name, notes, created_at, payload, client_id) VALUES (?, ?, ?, ?, ?, ?)',
                                             (user['id'], name, notes, created_at, payload, client_id)).lastrowid
        self.send_json(status, {'id': stored_id})

    def update_workout(self, user):
        target = workout_id(self.api_path)
        data = self.read_json()
        name, notes, created_at = validate_workout(data)
        payload = workout_payload(data)
        updated = 0
        if target is not None:
            with connection() as database:
                updated = database.execute('UPDATE workouts SET name=?, notes=?, created_at=?, payload=? WHERE id=? AND user_id=?', (name, notes, created_at, payload, target, user['id'])).rowcount
        if not updated:
            self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Workout not found.'})
            return
        self.send_json(HTTPStatus.OK, {'ok': True})

    def delete_workout(self, user):
        target = workout_id(self.api_path)
        if target is None:
            self.send_json(HTTPStatus.NOT_FOUND, {'error': 'Workout not found.'})
            return
        # Deleting a workout that is already gone (from another tab, say) still leaves what was asked for.
        with connection() as database:
            database.execute('DELETE FROM workouts WHERE id=? AND user_id=?', (target, user['id']))
        self.send_json(HTTPStatus.OK, {'ok': True})

    def get_active_session(self, user):
        with connection() as database:
            row = database.execute('SELECT payload FROM active_sessions WHERE user_id = ?', (user['id'],)).fetchone()
        self.send_json(HTTPStatus.OK, {'session': json.loads(row['payload']) if row else None})

    def save_active_session(self, user):
        data = self.read_json()
        session = data.get('session')
        if session is not None and not isinstance(session, dict):
            raise BadRequest('session must be an object or null.')
        if session is not None:
            weight_unit(session.get('unit'), 'session.unit')
        with connection() as database:
            database.execute('INSERT INTO active_sessions (user_id, payload, updated_at) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at', (user['id'], json.dumps(session), int(time.time() * 1000)))
        self.send_json(HTTPStatus.OK, {'ok': True})

    def clear_active_session(self, user):
        with connection() as database:
            database.execute('DELETE FROM active_sessions WHERE user_id=?', (user['id'],))
        self.send_json(HTTPStatus.OK, {'ok': True})

    def get_state(self, user):
        with connection() as database:
            self.send_json(HTTPStatus.OK, load_state(database, user['id']))

    def replace_state(self, user):
        # Each part sent replaces the stored one whole. Pages from before PATCH (below) send this, so it stays.
        data = self.read_json()
        validate_state(data)
        with connection() as database:
            # Read and written in one locked go, so another request's change cannot land in between and be lost.
            database.execute('BEGIN IMMEDIATE')
            # Only the parts sent change. A missing key keeps the stored part; null is a real value for the program (ended).
            state = {**load_state(database, user['id']), **{name: data[name] for name in STATE_PARTS if name in data}}
            store_state(database, user['id'], state)
        self.send_json(HTTPStatus.OK, state)

    def patch_state(self, user):
        # {part: {value, base, sent}}: each part as this device changed it, the copy it started from, and any copies sent
        # since without an answer, so the change can be merged with any made on another device (see merge_values). A part
        # sent without its base (a change made before this device had loaded the server's copy) replaces the stored one,
        # as PUT does.
        data = self.read_json(MAX_STATE_CHANGE)
        changes = {}
        for part, change in data.items():
            if part not in STATE_PARTS:
                raise BadRequest(f'{part} is not part of the account state.')
            if not isinstance(change, dict) or 'value' not in change:
                raise BadRequest(f'{part} must be an object with its value, and the base it was changed from.')
            if not isinstance(change.get('sent', []), list) or ('sent' in change and 'base' not in change):
                raise BadRequest(f'{part}.sent must be a list of copies sent since its base.')
            changes[part] = change
        validate_state({part: change['value'] for part, change in changes.items()})
        with connection() as database:
            # Read, merged and written in one locked go, so two devices sending at once both have their changes kept.
            database.execute('BEGIN IMMEDIATE')
            state = load_state(database, user['id'])
            for part, change in changes.items():
                mine = change['value']
                merged = merge_part(part, [change['base'], *change.get('sent', [])], mine, state[part]) if 'base' in change else mine
                if merged is not mine:
                    # A merge of two valid copies can still break a limit (more goals than are allowed, say); this
                    # device's own copy, already checked, is kept then, as it would have been without merging.
                    try:
                        validate_state({part: merged})
                    except BadRequest:
                        merged = mine
                state[part] = merged
            store_state(database, user['id'], state)
        self.send_json(HTTPStatus.OK, state)

    def export_json(self, user):
        with connection() as database:
            self.export_account(database, user, as_csv=False)

    def export_csv(self, user):
        with connection() as database:
            self.export_account(database, user, as_csv=True)

    def send_download(self, text, content_type, filename):
        """A file for the browser to save rather than show."""
        body, encoding = self.encoded(text.encode())
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        for name, value in encoding.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def export_account(self, database, user, as_csv):
        zone = export_zone(urlparse(self.path).query)
        today = datetime.datetime.now(zone).strftime('%Y-%m-%d')
        workouts = exported_workouts(database, user['id'])
        if as_csv:
            self.send_download(workouts_csv(workouts, zone), 'text/csv; charset=utf-8', f'workout-tracker-sets-{today}.csv')
            return
        export = {'format': EXPORT_FORMAT, 'version': 1, 'exportedAt': int(time.time() * 1000),
                  'account': {'username': user['username'], 'email': user['email']}, 'workouts': workouts,
                  **load_state(database, user['id'])}
        self.send_download(json.dumps(export, indent=1), 'application/json; charset=utf-8', f'workout-tracker-{today}.json')

    def import_account(self, user):
        # Not waited for: a second import while one is being read is told to come back, rather than held with its body in memory too.
        if not import_slots.acquire(blocking=False):
            raise BadRequest('Another import is running. Try again in a moment.', HTTPStatus.SERVICE_UNAVAILABLE, {'Retry-After': '5'})
        try:
            self.import_from(user, self.read_json(MAX_IMPORT))
        finally:
            import_slots.release()

    def import_from(self, user, data):
        if data.get('format', EXPORT_FORMAT) != EXPORT_FORMAT or not isinstance(data.get('workouts'), list):
            raise BadRequest('That file is not a Workout Tracker export.')
        # Everything is checked before anything is stored, so a file with one bad workout imports nothing.
        prepared = []
        for index, workout in enumerate(listed(data['workouts'], 'workouts', 100_000)):
            # An id belongs to the server the workout came from; this one gives it its own.
            workout = {key: value for key, value in workout.items() if key != 'id'}
            try:
                prepared.append((workout, workout_payload(workout), *validate_workout(workout)))
            except BadRequest as error:
                raise BadRequest(f'Workout {index + 1} in the file cannot be imported: {error}')
        state = {name: data[name] for name in STATE_PARTS if name in data}
        validate_state(state)
        added = 0
        with connection() as database:
            database.execute('BEGIN IMMEDIATE')
            held = workouts_held(database, user['id'])
            for workout, payload, name, notes, created_at in prepared:
                client_id = workout.get('clientId') or None
                if client_id is None and workout_stored(database, user['id'], name, created_at, workout):
                    continue
                # Past the account's limit, the whole file is refused and nothing is stored (the block raises, and is rolled back).
                check_workout_room(held + added)
                added += database.execute('INSERT INTO workouts (user_id, name, notes, created_at, payload, client_id) VALUES (?, ?, ?, ?, ?, ?) '
                                          'ON CONFLICT(user_id, client_id) DO NOTHING',
                                          (user['id'], name, notes, created_at, payload, client_id)).rowcount
            have = load_state(database, user['id'])
            # Each part takes what it will of the file's (and refuses the file, with nothing stored, if that would take it past its limit).
            taken = {name: part.take(have[name], state.get(name)) for name, part in STATE_PARTS.items()}
            if any(count for _, count in taken.values()):
                store_state(database, user['id'], {name: value for name, (value, _) in taken.items()})
        self.send_json(HTTPStatus.OK, {'workouts': added, 'alreadyHere': len(prepared) - added,
                                       **{part.report: taken[name][1] for name, part in STATE_PARTS.items()}})
