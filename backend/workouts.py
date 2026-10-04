"""Helpers for the workouts themselves: the tag that tells a browser it has them all (etag_matches), the export of them as CSV, and the
check for one already stored, which an import uses."""

import csv
import datetime
import io
import json
from urllib.parse import parse_qs


def workout_id(path):
    """The id in /api/workouts/<id>, or None if it is not a plain number (answered as not found)."""
    tail = path[len('/api/workouts/'):]
    return int(tail) if tail.isdigit() and len(tail) < 19 else None


def etag_matches(header, etag):
    """Whether an If-None-Match header names this ETag (or anything: *). Compared weakly, as it is for a GET, so W/"x" is "x"."""
    if not header:
        return False
    plain = lambda tag: tag.strip().removeprefix('W/')
    return header.strip() == '*' or plain(etag) in {plain(tag) for tag in header.split(',')}


def exported_workouts(database, user_id):
    """Every workout, oldest first, as the pages know them but without this server's ids."""
    workouts = []
    for row in database.execute('SELECT name, notes, created_at, payload FROM workouts WHERE user_id = ? ORDER BY created_at, id', (user_id,)):
        item = json.loads(row['payload'])
        item.pop('id', None)
        item.update(name=row['name'], notes=row['notes'], createdAt=row['created_at'])
        workouts.append(item)
    return workouts


def export_zone(query):
    """The time zone an export's dates are written in: the browser's, which sends ?offset= in minutes east of UTC."""
    try:
        minutes = int(parse_qs(query).get('offset', ['0'])[0])
    except ValueError:
        minutes = 0
    return datetime.timezone(datetime.timedelta(minutes=max(-840, min(840, minutes))))


def local_date(milliseconds, zone):
    # Added on rather than fromtimestamp(), which some platforms refuse for dates far in the future.
    moment = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(milliseconds=milliseconds)
    return moment.astimezone(zone).strftime('%Y-%m-%d')


def spreadsheet_text(value):
    """Text a spreadsheet keeps as text. One starting like a formula (=, +, -, @) would otherwise be run as one."""
    value = str(value)
    return "'" + value if value[:1] in ('=', '+', '-', '@', '\t', '\r') else value


def workouts_csv(workouts, zone):
    """One row per logged set, oldest first, for a spreadsheet. A skipped exercise has no rows, and one saved without
    sets (from the workout form) has one row of its weight and reps. A timed exercise's count goes under Seconds. A cardio
    session is one row: its time under Seconds, then its distance (in the unit it was entered in), calories, average heart
    rate and floors, then what the machine was set to, where it has them."""
    out = io.StringIO()
    writer = csv.writer(out)
    settings = {'incline': 'Incline (%)', 'resistance': 'Resistance level', 'ramp': 'Incline level', 'cadence': 'Cadence (rpm)', 'damper': 'Damper',
                'strokeRate': 'Stroke rate (spm)', 'level': 'Level'}
    writer.writerow(['Date', 'Workout', 'Exercise', 'Set', 'Weight', 'Unit', 'Reps', 'Seconds', 'Distance', 'Distance unit', 'Calories',
                     'Average heart rate', 'Floors', *settings.values()])
    for workout in workouts:
        date = local_date(workout['createdAt'], zone)
        unit = workout.get('unit') or 'lbs'
        if workout.get('kind') == 'cardio':
            cardio = workout.get('cardio') or {}
            given = lambda field: '' if cardio.get(field) is None else cardio[field]
            name = spreadsheet_text(workout['name'])
            writer.writerow([date, name, name, '', '', '', '', workout.get('duration', ''), given('distance'),
                             cardio.get('distanceUnit', '') if cardio.get('distance') is not None else '', given('calories'), given('heartRate'),
                             given('floors'), *(given(field) for field in settings)])
            continue
        for exercise in workout.get('exercises') or []:
            sets = exercise.get('sets')
            rows = [(index + 1, logged) for index, logged in enumerate(sets)] if sets is not None else [('', exercise)]
            timed = exercise.get('timed') is True
            for number, logged in rows:
                weight, count = logged.get('weight'), logged.get('reps')
                count = '' if count is None else count
                writer.writerow([date, spreadsheet_text(workout['name']), spreadsheet_text(exercise.get('name') or ''), number,
                                 '' if weight is None else weight, unit, '' if timed else count, count if timed else '', '', '', '', '', '',
                                 *('' for _ in settings)])
    # A byte-order mark, or Excel reads the file in its own code page and mangles anything beyond plain English.
    return '﻿' + out.getvalue()


def workout_stored(database, user_id, name, created_at, workout):
    """Whether the account has a workout like this one, which has no clientId: the same name, time and exercises."""
    exercises = json.dumps(workout.get('exercises'), sort_keys=True)
    rows = database.execute('SELECT payload FROM workouts WHERE user_id = ? AND created_at = ? AND name = ?', (user_id, created_at, name))
    return any(json.dumps(json.loads(row['payload']).get('exercises'), sort_keys=True) == exercises for row in rows)
