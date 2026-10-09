#!/usr/bin/env python3
"""Checks that the project hangs together, which no browser is needed for.

    python tests/lint.py            check this repository
    python tests/lint.py --root DIR check a copy of it (the tests do, with faults put in)

What each one guards is a list kept by hand in two places, where leaving one out breaks nothing that shows at once:

  offline      every script and stylesheet a page loads is in the service worker's PRECACHE (a page that is missing one
               works online and breaks the first time it is opened offline), and everything in PRECACHE is there to be
               fetched and is used by some page
  names        no top-level function, const, let or var is declared in two scripts: pages load their scripts into one
               shared scope, so two with a name would stop whichever loads second (or quietly replace the first)
  python       every Python file parses as Python 3.9, the oldest the README claims (Python newer than that, written
               by habit, is caught here and not on someone's server); pyflakes runs beside this in CI, for the rest
  state        the parts of the account's state the server keeps (STATE_PARTS in backend/state.py) and the parts the pages sync
               (accountStateParts in frontend/offline.js) are the same
  defaults     the time of day to remind at, until one is chosen, is the same on the server and on the page
  environment  every environment variable the server reads (in any of backend/*.py) is in the reference's table of server settings
  suites       every test suite is registered in tests/suites/__init__.py and has a row in tests/README.md
  contrast     in every colour theme the text colours the stylesheet sets are readable on what they sit on (WCAG AA, 4.5 to 1), and
               the accent, which draws the keyboard focus ring, stands out from the page (3 to 1)
"""

import argparse
import ast
import glob
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(root, *parts):
    with open(os.path.join(root, *parts), encoding='utf-8') as file:
        return file.read()


def page_assets(root):
    """{page: ([scripts], [stylesheets])} for every HTML page, as the names the page uses."""
    pages = {}
    for path in sorted(glob.glob(os.path.join(root, 'frontend', '*.html'))):
        html = read(root, 'frontend', os.path.basename(path))
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
        styles = re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html)
        pages[os.path.basename(path)] = ([s for s in scripts if '://' not in s], [s for s in styles if '://' not in s])
    return pages


def check_offline(root):
    problems = []
    worker = read(root, 'frontend', 'sw.js')
    listed = re.search(r'const PRECACHE = \[(.*?)\];', worker, re.S)
    if not listed:
        return ['frontend/sw.js: no PRECACHE list found.']
    precache = re.findall(r"'/([^']+)'", listed.group(1))
    used = set()
    for page, (scripts, styles) in page_assets(root).items():
        for asset in scripts + styles:
            used.add(asset)
            if not os.path.exists(os.path.join(root, 'frontend', asset)):
                problems.append(f'frontend/{page} loads {asset}, which is not in frontend/.')
            elif asset not in precache:
                problems.append(f'frontend/{page} loads {asset}, which is not in PRECACHE in frontend/sw.js, so the page fails offline.')
    for asset in precache:
        if not os.path.exists(os.path.join(root, 'frontend', asset)):
            problems.append(f'PRECACHE in frontend/sw.js lists {asset}, which is not in frontend/.')
        elif asset.endswith(('.js', '.css')) and asset not in used and asset != 'sw.js':
            problems.append(f'PRECACHE in frontend/sw.js lists {asset}, which no page loads.')
    pages = re.search(r'const PAGES = \[(.*?)\];', worker, re.S)
    for page in re.findall(r"'/([^']+)'", pages.group(1)) if pages else []:
        if not os.path.exists(os.path.join(root, 'frontend', page)):
            problems.append(f'PAGES in frontend/sw.js lists {page}, which is not in frontend/.')
    return problems


def check_names(root):
    declared = {}
    for path in sorted(glob.glob(os.path.join(root, 'frontend', '*.js'))):
        file = os.path.basename(path)
        if file == 'sw.js':
            continue  # the service worker is a scope of its own
        for name in re.findall(r'^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)|^(?:const|let|var)\s+([A-Za-z_$][\w$]*)', read(root, 'frontend', file), re.M):
            declared.setdefault(name[0] or name[1], set()).add(file)
    return [f'{name} is declared at the top level of {" and ".join(sorted(files))}: pages load scripts into one scope.'
            for name, files in sorted(declared.items()) if len(files) > 1]


def check_python(root):
    problems = []
    for path in sorted(glob.glob(os.path.join(root, '**', '*.py'), recursive=True)):
        relative = os.path.relpath(path, root).replace(os.sep, '/')
        if relative.startswith(('.', 'node_modules')) or '/.' in relative:
            continue
        try:
            ast.parse(read(root, relative), relative, feature_version=(3, 9))
        except SyntaxError as error:
            problems.append(f'{relative}:{error.lineno}: not Python 3.9: {error.msg}.')
    return problems


def check_state(root):
    tree = ast.parse(read(root, 'backend', 'state.py'))
    on_server = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(target, 'id', None) == 'STATE_PARTS' for target in node.targets) and isinstance(node.value, ast.Dict):
            on_server = [key.value for key in node.value.keys if isinstance(key, ast.Constant)]
    listed = re.search(r'const accountStateParts = \[(.*?)\];', read(root, 'frontend', 'offline.js'), re.S)
    if on_server is None or not listed:
        return ['backend/state.py has no STATE_PARTS dict, or frontend/offline.js no accountStateParts list.']
    on_pages = re.findall(r"'([^']+)'", listed.group(1))
    return ([f'backend/state.py keeps the state part {name}, which accountStateParts in frontend/offline.js does not sync.' for name in on_server if name not in on_pages]
            + [f'accountStateParts in frontend/offline.js syncs {name}, which STATE_PARTS in backend/state.py does not keep.' for name in on_pages if name not in on_server])


def check_defaults(root):
    server = re.search(r"DEFAULT_REMINDER_TIME = '([^']*)'", read(root, 'backend', 'config.py'))
    page = re.search(r"schedule:\{ days:\[\], time:'([^']*)' \}", read(root, 'frontend', 'settings-fields.js'))
    if not server or not page:
        return ['DEFAULT_REMINDER_TIME in backend/config.py, or the schedule default in frontend/settings-fields.js, was not found.']
    if server.group(1) != page.group(1):
        return [f'The default reminder time is {server.group(1)} on the server (DEFAULT_REMINDER_TIME) and {page.group(1)} on the page (settings-fields.js).']
    return []


def check_environment(root):
    reference = read(root, 'readme-for-llm.md')
    found = {}
    for path in sorted(glob.glob(os.path.join(root, 'backend', '*.py'))):
        module = os.path.basename(path)
        source = read(root, 'backend', module)
        for name in set(re.findall(r"os\.environ\.get\('([A-Z][A-Z0-9_]*)'", source)) | set(re.findall(r"env_flag\('([A-Z][A-Z0-9_]*)'", source)):
            found.setdefault(name, module)
    return [f'backend/{module} reads {name}, which readme-for-llm.md does not mention.' for name, module in sorted(found.items()) if name not in reference]


def check_suites(root):
    problems = []
    suites = {os.path.basename(path)[:-3] for path in glob.glob(os.path.join(root, 'tests', 'suites', '*.py')) if not path.endswith('__init__.py')}
    registered = set(re.findall(r"'([a-z_0-9]+)'", re.search(r'NAMES = \[(.*?)\]', read(root, 'tests', 'suites', '__init__.py'), re.S).group(1)))
    documented = set(re.findall(r'^\| `([a-z_0-9]+)` \|', read(root, 'tests', 'README.md'), re.M))
    for name in sorted(suites - registered):
        problems.append(f'tests/suites/{name}.py is not in NAMES in tests/suites/__init__.py, so it never runs.')
    for name in sorted(registered - suites):
        problems.append(f'{name} is in NAMES in tests/suites/__init__.py but has no tests/suites/{name}.py.')
    for name in sorted(suites - documented):
        problems.append(f'tests/suites/{name}.py has no row in the table in tests/README.md.')
    for name in sorted(documented - suites):
        problems.append(f'tests/README.md describes a suite called {name}, which does not exist.')
    return problems


# ---- Colour contrast ------------------------------------------------------------------------------------------------------------
# WCAG's ratio between two colours: the lighter one's relative luminance plus .05, over the darker one's. 4.5 is AA for text, 3 for
# what is not text (a focus ring).
TEXT_CONTRAST = 4.5
RING_CONTRAST = 3.0


def luminance(colour):
    digits = colour.lstrip('#')
    if len(digits) in (3, 4):
        digits = ''.join(digit * 2 for digit in digits)
    channels = [int(digits[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    red, green, blue = [channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one, other):
    lighter, darker = sorted((luminance(one), luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def theme_palettes(root):
    """({theme: {variable: colour}}, {theme: 'light' or 'dark'}): the colours each theme gives in styles.css, and whether theme.js
    says it is a light or a dark one."""
    css = read(root, 'frontend', 'styles.css')
    palettes = {}
    for selector, body in re.findall(r'^((?::root, )?\[data-(?:palette|theme)[^{]*)\{([^}]*)\}', css, re.M):
        colours = re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{3,8})', body)
        for name in re.findall(r'data-palette="(\w+)"', selector) if colours else []:
            palettes.setdefault(name, {}).update(colours)
    listed = re.search(r'window\.colorThemes = \{(.*?)\};', read(root, 'frontend', 'theme.js'), re.S)
    return palettes, dict(re.findall(r"(\w+):'(light|dark)'", listed.group(1))) if listed else {}


def colour_rules(css):
    """{selector: {'light': {property: value}, 'dark': {property: value}}} for every rule in styles.css that sets a text colour or a
    background, with the dark theme's changes (a selector under html[data-theme="dark"]) in their own layer, later ones over earlier."""
    rules = {}
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        if 'data-palette' in selector or ':root' in selector or '@' in selector:
            continue
        found = {}
        for name, pattern in (('color', r'(?<![\w-])color:\s*([^;]+)'), ('background', r'(?<![\w-])background(?:-color)?:\s*([^;]+)')):
            match = re.search(pattern, body)
            if match:
                found[name] = match.group(1).strip()
        for part in selector.split(','):
            part = ' '.join(part.split())
            dark = part.startswith('html[data-theme="dark"] ')
            layer = rules.setdefault(part[len('html[data-theme="dark"] '):] if dark else part, {'light': {}, 'dark': {}})
            layer['dark' if dark else 'light'].update(found)
    return rules


def check_contrast(root):
    palettes, kinds = theme_palettes(root)
    if not palettes or not kinds:
        return ['frontend/styles.css or frontend/theme.js: no colour themes found.']
    problems = []

    def fail(theme, what, one, other, wanted):
        problems.append(f'{theme} theme: {what} is {contrast(one, other):.2f} to 1 ({one} on {other}); it needs {wanted:g}.')

    for theme, colours in sorted(palettes.items()):
        for text in ('ink', 'muted', 'accent'):
            for ground in ('bg', 'card', 'sunk', 'accent-soft'):
                if text in colours and ground in colours and contrast(colours[text], colours[ground]) < TEXT_CONTRAST:
                    fail(theme, f'{text} text on {ground}', colours[text], colours[ground], TEXT_CONTRAST)
        if contrast(colours['on-accent'], colours['accent']) < TEXT_CONTRAST:
            fail(theme, 'the text on the accent', colours['on-accent'], colours['accent'], TEXT_CONTRAST)
        # The focus ring is the accent, drawn against the page and the card it is on.
        for ground in ('bg', 'card'):
            if contrast(colours['accent'], colours[ground]) < RING_CONTRAST:
                fail(theme, f'the accent (the focus ring) against {ground}', colours['accent'], colours[ground], RING_CONTRAST)

    # Every rule that sets a colour in the stylesheet, read as the colours it gives: a colour written out, or a theme variable. Text
    # with no background of its own is on the card or the page.
    def resolve(value, colours):
        match = re.fullmatch(r'var\(--([\w-]+)\)', value or '')
        if match:
            return colours.get(match.group(1))
        return value if re.fullmatch(r'#[0-9a-fA-F]{3,8}', value or '') else None

    for selector, layers in sorted(colour_rules(read(root, 'frontend', 'styles.css')).items()):
        for theme, colours in sorted(palettes.items()):
            properties = {**layers['light'], **layers['dark']} if kinds.get(theme) == 'dark' else layers['light']
            text = resolve(properties.get('color'), colours)
            grounds = [resolve(properties.get('background'), colours)] if resolve(properties.get('background'), colours) else [colours['card'], colours['bg']]
            if text is None or (not properties.get('background') and properties.get('color') == 'var(--on-accent)'):
                continue
            for ground in grounds:
                if len(text) in (4, 5, 7, 9) and contrast(text, ground) < TEXT_CONTRAST:
                    problems.append(f'{theme} theme: {selector} has text of {contrast(text, ground):.2f} to 1 ({text} on {ground}); it needs {TEXT_CONTRAST:g}.')
    return problems


CHECKS = [check_offline, check_names, check_python, check_state, check_defaults, check_environment, check_suites, check_contrast]


def problems(root=REPO_ROOT):
    """Everything wrong with the project at `root`, as sentences; none when it is as it should be."""
    return [problem for check in CHECKS for problem in check(root)]


def main():
    parser = argparse.ArgumentParser(description='Check that the project hangs together.')
    parser.add_argument('--root', default=REPO_ROOT, help='the project to check (default: this one)')
    found = problems(parser.parse_args().root)
    for problem in found:
        print(f'  [FAIL] {problem}')
    print(f'{len(found)} problem{"" if len(found) == 1 else "s"} found.' if found else 'The project hangs together.')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
