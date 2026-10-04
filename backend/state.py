"""The account's synced state (settings, templates, program, notes, goals, bodyweight, exercise library): the table that says what
each part is (STATE_PARTS), its checks, what an import takes of it, and how changes to it from several devices are merged."""

import collections
import datetime
import json
import re
import time

from config import DEFAULT_REMINDER_TIME
from validation import BadRequest, is_number, listed, text, validate_exercises, weight_unit


def validate_program(program):
    """The program being followed: null, or an object naming its definition with a number for every training max."""
    if program is None:
        return
    if not isinstance(program, dict):
        raise BadRequest('program must be an object or null.')
    if not text(program.get('definition'), 'program.definition', 100):
        raise BadRequest('program.definition must name the program.')
    weight_unit(program.get('unit'), 'program.unit')
    maxes = program.get('trainingMaxes')
    if not isinstance(maxes, dict) or len(maxes) > 100:
        raise BadRequest('program.trainingMaxes must be an object.')
    if not all(is_number(value) and value >= 0 for value in maxes.values()):
        raise BadRequest('Every training max must be a number of zero or more.')
    for field in ('options', 'done', 'stalls'):
        if program.get(field) is not None and not isinstance(program[field], dict):
            raise BadRequest(f'program.{field} must be an object.')
    # A program the lifter built has a name and up to 7 days, each named and done from a template, by its id.
    text(program.get('name'), 'program.name', 200)
    if program.get('days') is not None:
        for index, day in enumerate(listed(program['days'], 'program.days', 7)):
            text(day.get('name'), f'program.days[{index}].name', 200)
            if not text(day.get('template'), f'program.days[{index}].template', 200):
                raise BadRequest(f'program.days[{index}].template must name the template the day does.')


# The muscle an exercise mostly works, and what it is done with, as exercise-library.js offers them.
MUSCLES = ('chest', 'back', 'shoulders', 'biceps', 'triceps', 'forearms', 'quads', 'hamstrings', 'glutes', 'calves', 'core', 'other')
EQUIPMENT = ('barbell', 'dumbbell', 'machine', 'cable', 'bodyweight', 'kettlebell', 'band', 'other')


def validate_schedule(schedule):
    """The days of the week the lifter trains, as the browser numbers them (Sunday is 0), and the time of day to remind them."""
    if not isinstance(schedule, dict):
        raise BadRequest('settings.schedule must be an object.')
    days = schedule.get('days', [])
    if (not isinstance(days, list) or not all(isinstance(day, int) and not isinstance(day, bool) and 0 <= day <= 6 for day in days)
            or len(set(days)) != len(days)):
        raise BadRequest('settings.schedule.days must be a list of different days of the week, 0 (Sunday) to 6 (Saturday).')
    at = schedule.get('time', DEFAULT_REMINDER_TIME)
    if not (isinstance(at, str) and re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', at)):
        raise BadRequest('settings.schedule.time must be a time of day as HH:MM.')


# How many of each an account may keep, for the validators below and for what an import may add.
MAX_TEMPLATES = 1000
MAX_NOTES = 5000
MAX_GOALS = 500
MAX_WEIGH_INS = 40_000
MAX_LIBRARY = 5000


def validate_settings(settings):
    if not isinstance(settings, dict):
        raise BadRequest('settings must be an object.')
    if 'schedule' in settings:
        validate_schedule(settings['schedule'])


def validate_templates(templates):
    for index, template in enumerate(listed(templates, 'templates', MAX_TEMPLATES)):
        text(template.get('name'), f'templates[{index}].name', 1000)
        validate_exercises(template.get('exercises'), f'templates[{index}].exercises')


def keyed_collection(name, limit, things, check_entry, check_key=None):
    """The validator of a part that is an object of up to `limit` entries by key: the keys are checked by `check_key` (by
    default, as text) and each entry by `check_entry(key, entry)`, which raise BadRequest."""
    def validate(entries):
        if not isinstance(entries, dict) or len(entries) > limit:
            raise BadRequest(f'{name} must be an object of up to {limit} {things}.')
        for key, entry in entries.items():
            (check_key or (lambda key: text(key, f'{name} key', 1000)))(key)
            check_entry(key, entry)
    return validate


def check_note(key, note):
    text(note, f'exerciseNotes[{key!r}]', 2000)


def check_goal(key, goal):
    if not isinstance(goal, dict):
        raise BadRequest(f'goals[{key!r}] must be an object.')
    if not text(goal.get('name'), f'goals[{key!r}].name', 1000).strip():
        raise BadRequest(f'goals[{key!r}].name must name the exercise.')
    if not is_number(goal.get('target')) or not 0 < goal['target'] <= 100_000:
        raise BadRequest(f'goals[{key!r}].target must be a weight above zero.')
    weight_unit(goal.get('unit'), f'goals[{key!r}].unit')
    by = goal.get('by')
    if by not in (None, '') and not (isinstance(by, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', by)):
        raise BadRequest(f'goals[{key!r}].by must be a date as YYYY-MM-DD, or empty.')


def check_weigh_in_day(day):
    try:
        datetime.date.fromisoformat(day if re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) else '')
    except ValueError:
        raise BadRequest(f'bodyweight key {day!r} must be a date as YYYY-MM-DD.')


def check_weigh_in(day, entry):
    if not isinstance(entry, dict) or not is_number(entry.get('weight')) or not 0 < entry['weight'] <= 2000:
        raise BadRequest(f'bodyweight[{day!r}].weight must be a weight above zero.')
    weight_unit(entry.get('unit'), f'bodyweight[{day!r}].unit')


def check_library_entry(key, entry):
    if not isinstance(entry, dict):
        raise BadRequest(f'exerciseLibrary[{key!r}] must be an object.')
    if not text(entry.get('name'), f'exerciseLibrary[{key!r}].name', 1000).strip():
        raise BadRequest(f'exerciseLibrary[{key!r}].name must name the exercise.')
    # Empty, or missing, leaves it to the app's guess from the name.
    if entry.get('muscle') not in (None, '', *MUSCLES):
        raise BadRequest(f'exerciseLibrary[{key!r}].muscle must be one of {", ".join(MUSCLES)}, or empty.')
    if entry.get('equipment') not in (None, '', *EQUIPMENT):
        raise BadRequest(f'exerciseLibrary[{key!r}].equipment must be one of {", ".join(EQUIPMENT)}, or empty.')


def validate_state(data):
    """Checks each part of the state that `data` has (see STATE_PARTS), in their order; a part it does not name is not looked at."""
    for name, part in STATE_PARTS.items():
        if name in data:
            part.validate(data[name])


# ---- Export and import --------------------------------------------------------------------------------------
# An export is the whole account in one JSON file: every workout, plus every part of its state (STATE_PARTS). Importing one only
# ever adds. Workouts already here (by clientId, or else by name, time and exercises) are skipped, and what a part adds is its
# `take`: templates not already here, an entry for a key that has none, and settings and a program only for an account that has
# none of its own.

# The account's state: what the pages keep and sync with the server, which is everything an account has but its workouts. One entry
# in STATE_PARTS says all the server needs to know about a part, so a new one is an entry here, a column (below), and its name
# in accountStateParts in frontend/offline.js, and not a change in each place that has to know the parts. (tests/lint.py checks
# that the server's list and the page's agree, and the api suite that every part has its column.) Each part has:
#   column    the column of user_state that keeps it, as JSON
#   empty     what the column holds for an account that has not set it, as JSON: also the column's DEFAULT
#   merge     how changes to it from several devices are merged (see merge_values)
#   validate  checks a value, raising BadRequest if it will not do
#   take      what an import does with it: from what the account has and what the file has, what the account has after (an
#             import only ever adds) and what that added, a count or whether the file's was taken
#   report    the name an import's answer gives that: templates, settings, program, notes, goals, bodyweights, exercises
StatePart = collections.namedtuple('StatePart', 'column empty merge validate take report')


def take_whole(have, incoming):
    """Import rule for a part that is one thing: the file's is taken only by an account that has none of its own."""
    return (incoming, True) if incoming and not have else (have, False)


def add_missing(noun, limit, unit='', wanted=lambda entry: True):
    """Import rule for a part that is entries by key: the file's for a key the account has none for; one already here is the
    account's own and stays."""
    def take(have, incoming):
        new = {key: entry for key, entry in (incoming or {}).items() if key not in have and wanted(entry)}
        if len(have) + len(new) > limit:
            raise BadRequest(f'Importing these {noun} would take the account past {limit}{unit}.')
        return {**have, **new}, len(new)
    return take


def add_new_templates(have, incoming):
    """Import rule for the templates: those the account has not already got (see same_template)."""
    new = []
    for template in incoming or []:
        if not any(same_template(template, kept) for kept in have + new):
            new.append(template)
    if len(have) + len(new) > MAX_TEMPLATES:
        raise BadRequest(f'Importing these templates would take the account past {MAX_TEMPLATES}.')
    return have + new, len(new)


STATE_PARTS = {
    'settings': StatePart('settings_json', '{}', {'depth': 1}, validate_settings, take_whole, 'settings'),
    'templates': StatePart('templates_json', '[]', {'depth': 1, 'by_id': True}, validate_templates, add_new_templates, 'templates'),
    'program': StatePart('program_json', 'null', {'depth': 2, 'identity': ('definition', 'startedAt', 'cycle', 'unit')}, validate_program, take_whole, 'program'),
    'exerciseNotes': StatePart('notes_json', '{}', {'depth': 1}, keyed_collection('exerciseNotes', MAX_NOTES, 'notes', check_note),
                               add_missing('notes', MAX_NOTES, wanted=bool), 'notes'),
    'goals': StatePart('goals_json', '{}', {'depth': 1}, keyed_collection('goals', MAX_GOALS, 'goals', check_goal), add_missing('goals', MAX_GOALS), 'goals'),
    # One weight a day, by the day it was weighed; a lifetime of daily weigh-ins fits.
    'bodyweight': StatePart('bodyweight_json', '{}', {'depth': 1}, keyed_collection('bodyweight', MAX_WEIGH_INS, 'days', check_weigh_in, check_weigh_in_day),
                            add_missing('bodyweights', MAX_WEIGH_INS, ' days'), 'bodyweights'),
    'exerciseLibrary': StatePart('library_json', '{}', {'depth': 1}, keyed_collection('exerciseLibrary', MAX_LIBRARY, 'exercises', check_library_entry),
                                 add_missing('exercises', MAX_LIBRARY), 'exercises'),
}


def load_state(database, user_id):
    columns = ', '.join(part.column for part in STATE_PARTS.values())
    row = database.execute(f'SELECT {columns} FROM user_state WHERE user_id = ?', (user_id,)).fetchone()
    return {name: json.loads(row[part.column] if row else part.empty) for name, part in STATE_PARTS.items()}


def store_state(database, user_id, state):
    columns = [part.column for part in STATE_PARTS.values()]
    database.execute(f"INSERT INTO user_state (user_id, {', '.join(columns)}, updated_at) VALUES (?, {', '.join('?' for _ in columns)}, ?) "
                     f"ON CONFLICT(user_id) DO UPDATE SET {', '.join(f'{column}=excluded.{column}' for column in columns)}, updated_at=excluded.updated_at",
                     (user_id, *(json.dumps(state[name]) for name in STATE_PARTS), int(time.time() * 1000)))


# ---- Merging changes from several devices ---------------------------------------------------------------------
# A device that changed part of the state sends the part as it changed it, and the copy it started from (PATCH
# /api/state). Another device may have changed the part on the server since; merging keeps both devices' changes, and
# where both changed the same thing, the change arriving now wins. How finely each part is merged is its `merge` in STATE_PARTS:
#   depth     how many levels of objects below the part are merged key by key; a value deeper than that is one value,
#             so a bodyweight's weight and unit, or a goal's target and unit, always travel together
#   by_id     a list of objects told apart by their id, merged as if keyed by it (templates)
#   identity  keys that say which run of a program the rest belongs to: its days are a cycle's, its weights a unit's,
#             so changes to two different runs are never mixed (see merge_values)
# A key one side has and the other does not.
MISSING = object()


def merge_values(bases, mine, theirs, depth, identity=()):
    """`mine` (this device's copy) merged with `theirs` (the server's). `bases` are the copies this device's change may
    have started from: the one the server last confirmed having, and any sent since whose answer never came back (the
    page closed, the connection dropped), which the server may have stored. What only one side changed is kept; where
    both changed the same thing, `mine` wins, as the later. A value is this device's change if it differs from any base,
    so a value changed and then changed back, before an answer that never came, still counts; and the server's is
    unchanged if it matches any. Objects are merged key by key `depth` levels down. Copies whose `identity` keys differ
    are different runs of a program, which are not mixed: the side that moved to another run wins whole."""
    if all(mine == base for base in bases):
        return theirs
    if mine == theirs or any(theirs == base for base in bases):
        return mine
    if depth <= 0 or not isinstance(mine, dict) or not isinstance(theirs, dict):
        return mine
    bases = [base if isinstance(base, dict) else {} for base in bases]
    if any(mine.get(key, MISSING) != theirs.get(key, MISSING) for key in identity):
        moved = any(mine.get(key, MISSING) != base.get(key, MISSING) for base in bases for key in identity)
        return mine if moved else theirs
    merged = {}
    # The server's order, then what this device added.
    for key in [*theirs, *(key for key in mine if key not in theirs)]:
        value = merge_values([base.get(key, MISSING) for base in bases], mine.get(key, MISSING), theirs.get(key, MISSING), depth - 1)
        if value is not MISSING:
            merged[key] = value
    return merged


def keyed_by_id(items):
    """A list of objects with distinct text ids as {id: object}, or None when it is not one."""
    if not isinstance(items, list):
        return None
    keyed = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or item['id'] in keyed:
            return None
        keyed[item['id']] = item
    return keyed


def merge_part(part, bases, mine, theirs):
    spec = STATE_PARTS[part].merge
    if spec.get('by_id'):
        keyed = [keyed_by_id(value) for value in (*bases, mine, theirs)]
        # A list with an item that has no id (from before templates had them) cannot be told apart item by item.
        if None in keyed:
            return merge_values(bases, mine, theirs, 0)
        return list(merge_values(keyed[:-2], keyed[-2], keyed[-1], spec['depth']).values())
    return merge_values(bases, mine, theirs, spec['depth'], spec.get('identity', ()))


def same_template(a, b):
    if a.get('id') and b.get('id'):
        return a['id'] == b['id']
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
