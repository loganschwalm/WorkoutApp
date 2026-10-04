"""The parts the Progress charts are drawn from (chart-parts.js, and the pure steps of progress.js and bodyweight.js): which labels
there is room to write, where each value is written, and the scale of the bodyweight chart."""

import json

INTERCEPT = False


def run(t):
    cdp, check = t.cdp, t.check

    def ev(expression):
        return cdp.ev(expression)

    cdp.goto('/progress.html')
    cdp.wait("typeof bodyweightScale === 'function' && typeof placeValueLabels === 'function'")

    # ------------------------------------------------------------------ L labels that fit
    print('L   which labels there is room to write')

    def fit(labels, gap=12):
        return ev(f"labelsThatFit({json.dumps([{'x': x, 'width': 20, 'text': text} for text, x in labels])}, {gap}).map(label => label.text)")

    check('labels a gap apart are all written', fit([('a', 0), ('b', 40), ('c', 80)]) == ['a', 'b', 'c'])
    check('one too close to the one before is left out', fit([('a', 0), ('b', 10), ('c', 50)]) == ['a', 'c'])
    check('the last is always written, at the cost of the one before it if they clash', fit([('a', 0), ('b', 40), ('c', 55)]) == ['a', 'c'])
    check('and the one before that if it still does not clear', fit([('a', 0), ('b', 10), ('c', 50), ('d', 60)]) == ['a', 'd'])
    check('one label, or none, is as it was', fit([('a', 5)]) == ['a'] and ev('labelsThatFit([], 12)') == [])
    check('a bigger gap leaves more out', fit([('a', 0), ('b', 40), ('c', 80)], 30) == ['a', 'c'])

    # ------------------------------------------------------------------ V where the values are written
    print('V   where each value is written')

    def place(latest, others=(), width=400):
        def label(spec):
            text, x, y = spec
            return {'text': text, 'colour': 'red', 'x': x, 'y': y, 'width': 20}
        return ev(f"placeValueLabels({json.dumps([label(spec) for spec in latest])}, {json.dumps([label(spec) for spec in others])}, {width}).map(l => [l.text, l.align, l.at])")

    check('a value goes to the right of its point', place([('100', 50, 100)]) == [['100', 'left', 57]])
    check('or to the left, where the chart’s edge would cut it off', place([('100', 395, 100)]) == [['100', 'right', 388]])
    check('one that clashes with a latest value is dropped, and one that does not is kept',
          [label[0] for label in place([('A', 100, 100)], [('B', 104, 105), ('C', 200, 105)])] == ['A', 'C'])
    check('the most recent of the latest values is written before the others, which is who wins a clash',
          [label[0] for label in place([('Older', 100, 100), ('Newer', 104, 105)])] == ['Newer'])
    check('and those that do not clash are written, left to right', [label[0] for label in place([('L1', 100, 50), ('L2', 300, 50)], [('O1', 200, 150)])] == ['L1', 'O1', 'L2'])
    check('a value below another by a line’s height or more does not clash', [label[0] for label in place([('A', 100, 100)], [('B', 100, 113)])] == ['A', 'B'])
    check('and one just above it does', [label[0] for label in place([('A', 100, 100)], [('B', 100, 112)])] == ['A'])
    check('an empty chart has nothing to write', place([]) == [])

    # ------------------------------------------------------------------ S the bodyweight scale
    print('S   the bodyweight chart’s scale')

    def scale(*weights):
        return ev(f"bodyweightScale({json.dumps(list(weights))})")

    check('a few weights get room above and below, on round steps: 180–182 is 178 to 184 in twos',
          scale(180, 182, 181) == {'low': 178, 'high': 184, 'step': 2, 'ticks': [178, 180, 182, 184]}, scale(180, 182, 181))
    check('one weight is a scale of its own, a pound either side', scale(181.4) == {'low': 180, 'high': 183, 'step': 1, 'ticks': [180, 181, 182, 183]}, scale(181.4))
    check('and so is a flat line, which is not drawn along an edge', scale(175, 175, 175) == {'low': 174, 'high': 176, 'step': 1, 'ticks': [174, 175, 176]}, scale(175, 175, 175))
    check('a wide range takes a wide step, as 5s and 2.5s of a power of ten', scale(150, 220) == {'low': 100, 'high': 250, 'step': 50, 'ticks': [100, 150, 200, 250]}, scale(150, 220))
    check('a scale never goes below zero, which no one weighs', scale(0.5, 1)['low'] == 0 and all(tick >= 0 for tick in scale(0.5, 1)['ticks']), scale(0.5, 1))
    check('every weight is inside it, and its lines are a step apart', all(scale(*weights)['low'] <= min(weights) and max(weights) <= scale(*weights)['high']
          and all(round(b - a, 6) == scale(*weights)['step'] for a, b in zip(scale(*weights)['ticks'], scale(*weights)['ticks'][1:]))
          for weights in ([180, 182, 181], [181.4], [175, 175], [150, 220], [60.5, 61.5, 62], [99.9, 100.2])))

    # ------------------------------------------------------------------ C the canvas and the colours
    print('C   the canvas and the colours')
    sized = ev("""(() => { const canvas = document.getElementById('progressChart'); const { context, width, height } = prepareChart(canvas, 123); const ratio = window.devicePixelRatio || 1;
        return [width === canvas.clientWidth, height, canvas.width === canvas.clientWidth * ratio, canvas.height === 123 * ratio, typeof context.fillText]; })()""")
    check('a chart’s canvas is sized to its box, and to the screen’s pixels', sized == [True, 123, True, True, 'function'], sized)
    colours = ev("({ ...chartColours() })")
    check('the colours are the page’s, none empty', all(isinstance(colours[name], str) and colours[name] for name in ('ink', 'line', 'accent')), colours)
    dark = ev("(() => { window.setColorTheme('dark'); const dark = { ...chartColours() }; window.setColorTheme('light'); return dark; })()")
    check('and follow the theme', dark['line'] != colours['line'] or dark['ink'] != colours['ink'], [colours, dark])
    check('no page errors along the way', not [line for line in cdp.console if line.startswith('exceptionThrown')], [line for line in cdp.console if line.startswith('exceptionThrown')][:3])
