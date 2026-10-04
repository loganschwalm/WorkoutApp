"""The pieces the Tracker's set logging and exercise screen are made of, each on its own: what the entry fields start a set
with, what is wrong with an entry, and the markup of the plan and the completed sets."""

import json

INTERCEPT = False


def run(t):
    cdp, check = t.cdp, t.check
    t.open_tracker()

    def call(expression):
        return cdp.ev(expression)

    def defaults(exercise, previous='null', timed='false'):
        return call(f"nextSetDefaults({json.dumps(exercise)}, {previous}, {timed})")

    def last_time(weight, reps, converted='false'):
        return f"{{ date: 0, converted: {converted}, sets: [{{ weight: {weight}, reps: {reps} }}] }}"

    # ------------------------------------------------------------------ D what the fields start with
    print('D   what the entry fields start the next set with')
    check('a new exercise with nothing before it starts from its own target weight',
          defaults({'name': 'Row', 'weight': 95, 'reps': 8, 'sets': []}) == {'weight': 95, 'reps': ''}, defaults({'name': 'Row', 'weight': 95, 'reps': 8, 'sets': []}))
    check('last time’s reps are the reps, but the target’s weight is still the weight: it is the lifter’s own plan',
          defaults({'name': 'Row', 'weight': 95, 'reps': 8, 'sets': []}, last_time(100, 6)) == {'weight': 95, 'reps': 6})
    check('with no target weight, last time’s weight is the weight', defaults({'name': 'Row', 'weight': '', 'reps': 8, 'sets': []}, last_time(100, 6)) == {'weight': 100, 'reps': 6})
    check('a set already logged is what the next one repeats, over last time’s',
          defaults({'name': 'Row', 'weight': 95, 'reps': 8, 'sets': [{'weight': 105, 'reps': 7}]}, last_time(100, 6)) == {'weight': 105, 'reps': 7})
    check('a set logged with no weight leaves the weight empty, not 0', defaults({'name': 'Push-up', 'weight': '', 'reps': 10, 'sets': [{'weight': 0, 'reps': 12}]}) == {'weight': '', 'reps': 12})
    check('a timed exercise done for the first time starts from its target seconds, so its timer is ready',
          defaults({'name': 'Plank', 'weight': '', 'reps': 45, 'timed': True, 'sets': []}, timed='true') == {'weight': '', 'reps': 45})
    check('and from its last hold once it has one', defaults({'name': 'Plank', 'weight': '', 'reps': 45, 'timed': True, 'sets': [{'weight': 0, 'reps': 52}]}, timed='true') == {'weight': '', 'reps': 52})
    plan = [{'weight': 135, 'reps': 5}, {'weight': 135, 'reps': 5}, {'weight': 135, 'reps': 5, 'amrap': True}]
    check('a planned set is its planned weight and reps, set by set',
          defaults({'name': 'Bench', 'reps': 5, 'plan': plan, 'sets': []}) == {'weight': 135, 'reps': 5}
          and defaults({'name': 'Bench', 'reps': 5, 'plan': plan, 'sets': [{'weight': 135, 'reps': 5}, {'weight': 135, 'reps': 5}]}) == {'weight': 135, 'reps': 5})
    check('even when the one before was done differently', defaults({'name': 'Bench', 'reps': 5, 'plan': plan, 'sets': [{'weight': 140, 'reps': 3}]}) == {'weight': 135, 'reps': 5})
    accessory = [{'weight': '', 'reps': 8, 'repsMax': 12}, {'weight': '', 'reps': 8, 'repsMax': 12}]
    check('a planned set with no weight (an assistance exercise) takes last time’s, and the bottom of its rep range is where it starts',
          defaults({'name': 'Curl', 'plan': accessory, 'sets': []}, last_time(30, 10)) == {'weight': 30, 'reps': 10})
    check('with nothing before it, no weight and the bottom of the range', defaults({'name': 'Curl', 'plan': accessory, 'sets': []}) == {'weight': '', 'reps': 8})
    check('and after a set, the weight and the reps just done',
          defaults({'name': 'Curl', 'plan': accessory, 'sets': [{'weight': 35, 'reps': 11}]}, last_time(30, 10)) == {'weight': 35, 'reps': 11})
    check('a rep range with no range keeps the plan’s own reps', defaults({'name': 'Squat', 'plan': [{'weight': 200, 'reps': 5}], 'sets': []}, last_time(190, 8)) == {'weight': 200, 'reps': 5})
    check('last time in the other unit is made a weight to load, to the nearest half: 45.359237 is 45.5',
          defaults({'name': 'Row', 'weight': '', 'reps': 8, 'sets': []}, last_time(45.359237, 6, 'true')) == {'weight': 45.5, 'reps': 6})
    check('and one already in this unit is used as it is', defaults({'name': 'Row', 'weight': '', 'reps': 8, 'sets': []}, last_time(46.3, 6)) == {'weight': 46.3, 'reps': 6})

    # ------------------------------------------------------------------ E what is wrong with an entry
    print('E   what is wrong with an entry')

    def problem(weight, reps, timed='false'):
        return call(f"(() => {{ const found = setEntryProblem({{ weightValue: {json.dumps(weight)}, reps: {reps} }}, {timed}); return found && [found[0], found[1].id]; }})()")

    check('no reps asks for them, and looks at that field', problem('100', 0) == ['Enter the reps completed for this set.', 'completedReps'], problem('100', 0))
    check('and no seconds, for a hold, says seconds', problem('', 0, 'true') == ['Enter the seconds held for this set.', 'completedReps'])
    check('reps that are not a number are no reps', problem('100', 'NaN')[1] == 'completedReps')
    check('half a rep is refused, a rep being done or not', problem('100', 5.5) == ['Reps must be a whole number.', 'completedReps'])
    check('but half a second is a hold’s own business', problem('', 30.5, 'true') is None)
    check('a weight below zero is refused, at the weight', problem('-5', 5) == ['Weight cannot be negative.', 'activeWeight'])
    check('reps are looked at before the weight', problem('-5', 0)[1] == 'completedReps')
    check('a good entry, with or without a weight, has nothing wrong', problem('100', 5) is None and problem('', 5) is None and problem('0', 5) is None and problem('52.5', 12) is None)

    # ------------------------------------------------------------------ M the markup
    print('M   the plan and the completed sets')
    chips = call("""(() => { const holder = document.createElement('ol');
      holder.innerHTML = planChipsHtml({ sets: [{ weight: 140, reps: 4 }] }, [{ weight: 135, reps: 5 }, { weight: 135, reps: 5 }, { weight: '', reps: 5 }]);
      return [...holder.children].map(li => [li.className, li.textContent]); })()""")
    check('the plan shows each set done, to do now, and to come', [chip[0] for chip in chips] == ['done', 'current', 'upcoming'], chips)
    check('a set done shows what was lifted, not what was planned', '140' in chips[0][1] and '135' not in chips[0][1], chips[0])
    check('and the rest what is planned', '135' in chips[1][1], chips)
    rows = call("""(() => { const holder = document.createElement('ul');
      holder.innerHTML = completedSetsHtml({ sets: [{ weight: 100, reps: 5, rir: 2 }, { weight: 0, reps: 8 }, { weight: 95, reps: 6, rir: 6 }] }, false);
      return [...holder.children].map(li => ({ label: li.querySelector('.set-number').firstChild.textContent, effort: (li.querySelector('.set-effort') || {}).textContent || '', weight: li.querySelector('[data-field=weight]').value, reps: li.querySelector('[data-field=reps]').value,
        repsLabel: li.querySelector('[data-field=reps]').getAttribute('aria-label'), remove: li.querySelector('[data-remove-set]').dataset.removeSet })); })()""")
    check('each completed set has its number, weight and reps to correct, and a way to remove it',
          [(row['label'], row['effort'], row['weight'], row['reps'], row['remove']) for row in rows]
          == [('Set 1', '2 left', '100', '5', '0'), ('Set 2', '', '', '8', '1'), ('Set 3', '4+ left', '95', '6', '2')], rows)
    check('with the reps described as reps', rows[0]['repsLabel'] == 'Set 1 reps', rows[0])
    timed_rows = call("""(() => { const holder = document.createElement('ul'); holder.innerHTML = completedSetsHtml({ sets: [{ weight: 0, reps: 45 }] }, true);
      return [holder.querySelector('[data-field=reps]').getAttribute('aria-label'), holder.querySelectorAll('.set-field span')[1].textContent]; })()""")
    check('and a hold’s as seconds', timed_rows == ['Set 1 seconds', 's'], timed_rows)
    check('markup in a weight or a number is text, not markup', call("""(() => { const holder = document.createElement('ul');
      holder.innerHTML = completedSetsHtml({ sets: [{ weight: '"><b>x</b>', reps: '<i>1</i>' }] }, false);
      return holder.querySelectorAll('b, i').length === 0 && holder.children.length === 1; })()""") is True)
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
