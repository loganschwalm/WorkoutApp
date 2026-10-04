"""What a request may say: BadRequest, which the server answers with its message, and the checks of a workout (and its cardio), which stop
anything but the shape the pages expect from being stored."""

import json
import math
import time
from http import HTTPStatus

from config import MAX_WORKOUTS, MAX_WORKOUT_BYTES


class BadRequest(Exception):
    """A request the client got wrong; answered with its status and message instead of a dropped connection."""

    def __init__(self, message, status=HTTPStatus.BAD_REQUEST, headers=None):
        super().__init__(message)
        self.status = status
        self.headers = headers or {}


# ---- Validation ---------------------------------------------------------------------------------------------
# Generous limits: nothing the app sends comes near them, but a stored value is always the shape the pages expect.

def text(value, field, limit, default=''):
    if value is None:
        return default
    if not isinstance(value, str):
        raise BadRequest(f'{field} must be text.')
    if len(value) > limit:
        raise BadRequest(f'{field} is longer than {limit} characters.')
    return value


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def amount(value, field):
    """A weight or rep count: a number, or the text a number field produces ('' when left empty)."""
    if value is None or value == '' or (is_number(value) and value >= 0):
        return
    if isinstance(value, str) and len(value) <= 32:
        try:
            number = float(value)
        except ValueError:
            number = None
        if number is not None and math.isfinite(number) and number >= 0:
            return
    raise BadRequest(f'{field} must be a number of zero or more.')


def listed(value, field, limit):
    if not isinstance(value, list):
        raise BadRequest(f'{field} must be a list.')
    if len(value) > limit:
        raise BadRequest(f'{field} has more than {limit} entries.')
    for item in value:
        if not isinstance(item, dict):
            raise BadRequest(f'Every entry in {field} must be an object.')
    return value


def validate_exercises(exercises, field='exercises'):
    for index, exercise in enumerate(listed(exercises, field, 1000)):
        where = f'{field}[{index}]'
        text(exercise.get('name'), f'{where}.name', 1000)
        amount(exercise.get('weight'), f'{where}.weight')
        amount(exercise.get('reps'), f'{where}.reps')
        # The rest timer's seconds after each set, when the exercise has its own; and whether it is held for seconds.
        if exercise.get('rest') is not None and not (is_number(exercise['rest']) and 0 < exercise['rest'] <= 3600):
            raise BadRequest(f'{where}.rest must be a number of seconds, up to an hour.')
        if exercise.get('timed') is not None and not isinstance(exercise['timed'], bool):
            raise BadRequest(f'{where}.timed must be true or false.')
        # Exercises next to each other with the same group are a superset.
        text(exercise.get('group'), f'{where}.group', 100)
        # A template exercise can plan its sets, 1 to 20, and a rep range up to repsMax; a workout started from it keeps them.
        if exercise.get('setCount') is not None and not (is_number(exercise['setCount']) and 1 <= exercise['setCount'] <= 20):
            raise BadRequest(f'{where}.setCount must be a number of sets from 1 to 20.')
        amount(exercise.get('repsMax'), f'{where}.repsMax')
        if exercise.get('sets') is not None:
            for number, logged in enumerate(listed(exercise['sets'], f'{where}.sets', 1000)):
                amount(logged.get('weight'), f'{where}.sets[{number}].weight')
                amount(logged.get('reps'), f'{where}.sets[{number}].reps')
                # How many more reps the set had in it, when that was recorded: 0 (none) to 10.
                if logged.get('rir') is not None and not (is_number(logged['rir']) and 0 <= logged['rir'] <= 10):
                    raise BadRequest(f'{where}.sets[{number}].rir must be a number from 0 to 10.')


def weight_unit(value, field='unit'):
    """A record's weight unit: 'lbs' or 'kg', or missing (meaning lbs, for everything saved before kilograms)."""
    if value is not None and value not in ('lbs', 'kg'):
        raise BadRequest(f'{field} must be lbs or kg.')


def workout_payload(data):
    """The JSON a workout is stored as, if it is a size a workout can be (413 otherwise)."""
    payload = json.dumps(data)
    if len(payload) > MAX_WORKOUT_BYTES:
        raise BadRequest(f'A workout can be at most {MAX_WORKOUT_BYTES // 1024} KB.', HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    return payload


def workouts_held(database, user_id):
    return database.execute('SELECT COUNT(*) FROM workouts WHERE user_id = ?', (user_id,)).fetchone()[0]


def check_workout_room(held, adding=1):
    """Raises if an account holding `held` workouts cannot take `adding` more (MAX_WORKOUTS)."""
    if MAX_WORKOUTS and held + adding > MAX_WORKOUTS:
        raise BadRequest(f'An account can keep at most {MAX_WORKOUTS:,} workouts. Export and delete some before adding more.')


def validate_workout(data):
    """(name, notes, created_at) for storing, after checking the whole workout is a shape the pages can show."""
    name = text(data.get('name', 'Untitled workout'), 'name', 1000)
    notes = text(data.get('notes'), 'notes', 100_000)
    created_at = data.get('createdAt', int(time.time() * 1000))
    if not is_number(created_at) or not 0 <= created_at < 10 ** 14:
        raise BadRequest('createdAt must be a time in milliseconds.')
    validate_exercises(data.get('exercises'))
    weight_unit(data.get('unit'))
    # How long the workout took, in seconds, when it was timed from start to finish.
    if data.get('duration') is not None and not (is_number(data['duration']) and 0 <= data['duration'] < 10 ** 9):
        raise BadRequest('duration must be a number of seconds.')
    if data.get('clientId') is not None:
        text(data['clientId'], 'clientId', 200)
    # A workout from a training program says where in the program it was, for History to show.
    if data.get('program') is not None:
        if not isinstance(data['program'], dict):
            raise BadRequest('program must be an object.')
        text(data['program'].get('name'), 'program.name', 1000)
        text(data['program'].get('label'), 'program.label', 1000)
    validate_cardio(data)
    return name, notes, int(created_at)


# The most a cardio session's numbers can be; nothing the app sends comes near them.
CARDIO_LIMITS = {'distance': 1_000_000, 'calories': 100_000, 'heartRate': 400, 'floors': 100_000}
# What a machine (or a treadmill) was set to, each optional, as cardioSettings in cardio-activities.js has them: (least,
# most). A treadmill's incline can go below zero.
CARDIO_SETTINGS = {'incline': (-10, 40), 'resistance': (0, 100), 'ramp': (0, 100), 'cadence': (0, 300), 'damper': (1, 10),
                   'strokeRate': (0, 100), 'level': (0, 100)}


def validate_cardio(data):
    """A cardio session (the Cardio page) is a workout with kind 'cardio', no exercises, its time as duration, and what it
    did as cardio: {activity, distance, distanceUnit, calories, heartRate, floors}, all but the activity optional."""
    kind = data.get('kind')
    if kind is None:
        return
    if kind != 'cardio':
        raise BadRequest('kind must be cardio, or left out for a strength workout.')
    cardio = data.get('cardio')
    if not isinstance(cardio, dict):
        raise BadRequest('cardio must be an object.')
    if not text(cardio.get('activity'), 'cardio.activity', 50).strip():
        raise BadRequest('cardio.activity must name the activity.')
    if not (is_number(data.get('duration')) and 0 < data['duration'] < 10 ** 6):
        raise BadRequest('A cardio session needs its time, as duration in seconds.')
    for field, most in CARDIO_LIMITS.items():
        value = cardio.get(field)
        if value is not None and not (is_number(value) and 0 <= value <= most):
            raise BadRequest(f'cardio.{field} must be a number from 0 to {most}.')
    if cardio.get('distanceUnit') not in (None, 'mi', 'km', 'm'):
        raise BadRequest('cardio.distanceUnit must be mi, km or m.')
    for field, (least, most) in CARDIO_SETTINGS.items():
        value = cardio.get(field)
        if value is not None and not (is_number(value) and least <= value <= most):
            raise BadRequest(f'cardio.{field} must be a number from {least} to {most}.')
