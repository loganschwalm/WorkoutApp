"""Putting the exercises of a workout in progress in another order: the arrows in the list of exercises, "Do this one last" with Undo, a
superset moving as one, the lift a program day is about staying first, and a rest on show surviving the move."""

INTERCEPT = False


def run(t):
    cdp, check = t.cdp, t.check
    start, log_set, end_workout = t.start, t.log_set, t.end_workout
    text, wait_for, safe_ev = t.text, t.wait_for, t.safe_ev

    def names():
        return cdp.ev('activeSession.exercises.map(e => e.name)')

    def kept_names():
        return safe_ev('readLocalActive().session.exercises.map(e => e.name)', [])

    def button(direction, index):
        return f"document.querySelector('#exerciseJump [data-move=\"{direction}\"][data-index=\"{index}\"]')"

    def move(direction, index):
        cdp.ev(f"{button(direction, index)}.click()")
        cdp.pause(0.2)

    def disabled(direction, index):
        return cdp.ev(f"{button(direction, index)}.disabled")

    # ------------------------------------------------------------------ M1 the arrows
    print('M1  the arrows beside each exercise in the list')
    t.open_tracker()
    start(0)
    cdp.pause(0.4)
    first = names()
    check('a workout of three', len(first) == 3, first)
    cdp.ev("document.getElementById('activeWorkoutProgress').click()")
    check('each exercise has an arrow up and an arrow down, named for it',
          cdp.ev("[...document.querySelectorAll('#exerciseJump [data-move]')].map(b => b.getAttribute('aria-label'))")
          == [f'Move {first[0]} earlier', f'Move {first[0]} later', f'Move {first[1]} earlier', f'Move {first[1]} later', f'Move {first[2]} earlier', f'Move {first[2]} later'])
    check('the first cannot go earlier, nor the last later', disabled(-1, 0) is True and disabled(1, 2) is True and disabled(1, 0) is False and disabled(-1, 2) is False)
    move(1, 0)
    check('down moves it one place later', names() == [first[1], first[0], first[2]], names())
    check('the exercise on show is still the one on show, now second of three', text('activeExerciseName') == first[0] and text('activeWorkoutProgress') == 'Exercise 2 of 3',
          f"{text('activeExerciseName')} {text('activeWorkoutProgress')}")
    check('the keyboard is on the same arrow of the same exercise', cdp.ev("document.activeElement.dataset.move + document.activeElement.dataset.index") == '11')
    check('it is kept on this device', wait_for(lambda: kept_names() == [first[1], first[0], first[2]]), kept_names())
    check('and reaches the server', wait_for(lambda: [e['name'] for e in (t.active_session() or {}).get('exercises', [])] == [first[1], first[0], first[2]]))
    move(-1, 1)
    check('up puts it back', names() == first, names())

    # ------------------------------------------------------------------ M2 do this one last
    print('M2  "Do this one last", and Undo')
    check('the menu offers it for an exercise that is not last', cdp.ev("document.getElementById('lastToggle').hidden") is False)
    cdp.ev("document.getElementById('exerciseMenu').open = true; document.getElementById('lastToggle').click()")
    cdp.pause(0.2)
    check('it goes to the end, and is still the one on show', names() == [first[1], first[2], first[0]] and text('activeExerciseName') == first[0]
          and text('activeWorkoutProgress') == 'Exercise 3 of 3', f"{names()} {text('activeExerciseName')}")
    check('the banner says so, with Undo', text('formFeedback') == f'{first[0]} is now the last exercise. Undo', text('formFeedback'))
    check('and the menu no longer offers it, for the last one', cdp.ev("document.getElementById('lastToggle').hidden") is True)
    cdp.ev("document.querySelector('#formFeedback .feedback-action').click()")
    cdp.pause(0.2)
    check('Undo puts the order back', names() == first and text('activeExerciseName') == first[0], names())

    # ------------------------------------------------------------------ M3 supersets
    print('M3  a superset moves as one')
    cdp.ev("activeSession.exercises[0].group = 'sx'; activeSession.exercises[1].group = 'sx'; renderActiveProgress()")
    move(-1, 2)
    check('the exercise after a superset moves in front of both', names() == [first[2], first[0], first[1]], names())
    check('the two are still together', cdp.ev("activeSession.exercises[1].group === 'sx' && activeSession.exercises[2].group === 'sx'") is True)
    move(-1, 2)
    check('moving one of them moves both', names() == first, names())
    check('and arrows on either say which they move', cdp.ev(f"{button(-1, 1)}.getAttribute('aria-label')") == f'Move {first[0]} and {first[1]} earlier',
          cdp.ev(f"{button(-1, 1)}.getAttribute('aria-label')"))
    cdp.ev("activeSession.exercises.forEach(item => { delete item.group; }); renderActiveProgress()")

    # ------------------------------------------------------------------ M4 a program day keeps its lift first
    print('M4  the lift a program day is about stays first')
    # The program reads its main lift by place (the first exercise), so a workout of a program day cannot move it, or put another before it.
    cdp.ev("activeSession.programDay = { day: 0 }; renderActiveProgress()")
    check('its first exercise has no arrows to use, and the second cannot go in front of it', disabled(1, 0) is True and disabled(-1, 0) is True and disabled(-1, 1) is True
          and disabled(1, 1) is False)
    check('and moving it any other way does nothing', cdp.ev('moveExercise(0, 1)') == -1 and cdp.ev('moveExercise(1, -1)') == -1 and names() == first)
    check('the others move among themselves', cdp.ev('moveExercise(1, 1)') == 2 and names() == [first[0], first[2], first[1]], names())
    cdp.ev("delete activeSession.programDay; renderActiveProgress()")

    # ------------------------------------------------------------------ M5 a rest on show
    print('M5  a rest on show follows the exercise it was for')
    cdp.ev('moveExercise(2, -1)')
    cdp.ev('goToExercise(1)')
    cdp.pause(0.3)
    log_set(8)
    cdp.pause(0.4)
    check('a rest is on show after a set', not cdp.ev("document.getElementById('restPanel').hidden"))
    index_before = cdp.ev('activeSession.currentIndex')
    cdp.ev(f'moveExercise({index_before}, -1)')
    index_after = cdp.ev('activeSession.currentIndex')
    kept = safe_ev("readLocal(localKey('rest'))", None)
    check('it moved', index_after == index_before - 1, f'{index_before} then {index_after}')
    check('and the rest kept for a reload is for the exercise where it now is', kept is not None and kept.get('index') == index_after, kept)
    cdp.send('Page.reload')
    cdp.wait("document.readyState === 'complete'")
    cdp.wait("typeof activeSession !== 'undefined' && activeSession !== null")
    cdp.pause(0.6)
    check('so after a reload the rest is still there', not cdp.ev("document.getElementById('restPanel').hidden") and text('timerDisplay') != '', text('timerDisplay'))
    end_workout()
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
