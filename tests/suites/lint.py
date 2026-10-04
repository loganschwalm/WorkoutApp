"""The project's consistency checks (tests/lint.py): that the project as it is passes, and that each check notices what it
is for, by putting a fault into a copy of it."""

import contextlib
import os
import shutil
import tempfile

from .. import lint
from ..harness import REPO_ROOT

INTERCEPT = False
BROWSER = False

# What a copy of the project needs for the checks, and no more.
IGNORED = shutil.ignore_patterns('.git', '__pycache__', 'data', 'test-data', 'docs', 'ct', 'media', 'node_modules')


def run(t):
    check = t.check
    clean = lint.problems()
    check('the project as it is hangs together', clean == [], clean)

    root = tempfile.mkdtemp(prefix='workout-lint-')
    copy = os.path.join(root, 'project')
    shutil.copytree(REPO_ROOT, copy, ignore=IGNORED)
    try:
        def path(*parts):
            return os.path.join(copy, *parts)

        @contextlib.contextmanager
        def changed(relative, edit=None, content=None):
            """A file of the copy changed (`edit` of what it had, or `content` for a file that is new) for the length of the block."""
            file = path(*relative.split('/'))
            had = None
            if os.path.exists(file):
                with open(file, encoding='utf-8', newline='') as handle:
                    had = handle.read()
            with open(file, 'w', encoding='utf-8', newline='') as handle:
                handle.write(content if content is not None else edit(had))
            try:
                yield
            finally:
                if had is None:
                    os.remove(file)
                else:
                    with open(file, 'w', encoding='utf-8', newline='') as handle:
                        handle.write(had)

        def replaced(old, new):
            def edit(text):
                assert old in text, old
                return text.replace(old, new, 1)
            return edit

        def found():
            return lint.problems(copy)

        def says(words):
            return any(all(word in problem for word in words) for problem in found())

        check('and so does a copy of it', found() == [], found())

        # -- offline
        with changed('frontend/extra.js', content='// a script a page forgot to precache\n'), changed('frontend/history.html', replaced('<script src="history.js">', '<script src="extra.js"></script>\n  <script src="history.js">')):
            check('a script a page loads that the service worker does not precache is named', says(['history.html', 'extra.js', 'PRECACHE']), found())
        with changed('frontend/history.html', replaced('<script src="history.js">', '<script src="missing.js"></script>\n  <script src="history.js">')):
            check('and one that is not there at all', says(['missing.js', 'not in frontend/']), found())
        with changed('frontend/sw.js', replaced("  '/schedule.js',\n", '')):
            check('and a precache that has lost a script', says(['schedule.js', 'not in PRECACHE']), found())
        with changed('frontend/sw.js', replaced("  '/schedule.js',\n", "  '/schedule.js',\n  '/nothing.js',\n")):
            check('and a precached file that does not exist', says(['nothing.js', 'not in frontend/']), found())
        with changed('frontend/spare.js', content='// loaded by no page\n'), changed('frontend/sw.js', replaced("  '/schedule.js',\n", "  '/schedule.js',\n  '/spare.js',\n")):
            check('and one that no page loads', says(['spare.js', 'no page loads']), found())
        with changed('frontend/history.html', replaced('href="styles.css"', 'href="gone.css"')):
            check('a stylesheet a page needs is held to the same', says(['gone.css']), found())

        # -- names
        with changed('frontend/history.js', lambda text: text + '\nfunction escapeHTML() {}\n'):
            check('a function declared by two scripts is named, with both', says(['escapeHTML', 'common.js', 'history.js']), found())
        with changed('frontend/history.js', lambda text: text + '\nconst weekdayNames = [];\n'):
            check('and so is a const', says(['weekdayNames', 'history.js', 'schedule.js']), found())
        with changed('frontend/history.js', lambda text: text + '\nfunction localOnlyHelper() { const escapeHTML = 1; }\n'):
            check('a name inside a function is not at the top level', found() == [], found())
        with changed('frontend/history.js', lambda text: text + '\nconst VERSION = 1;\n'):
            check('and the service worker, a scope of its own, may share a name with a page', found() == [], found())

        # -- python
        with changed('scripts/newer.py', content='match 1:\n    case 1:\n        pass\n'):
            check('Python newer than 3.9 is named, with its file and a line', says(['scripts/newer.py:', 'not Python 3.9']), found())
        with changed('scripts/older.py', content='print("fine")\n'):
            check('and Python that is not newer is left alone', found() == [], found())

        # -- environment
        with changed('backend/server.py', lambda text: text + "\nNEW_SETTING = os.environ.get('SOMETHING_NEW_AND_UNDOCUMENTED', '')\n"):
            check('an environment variable the reference does not mention is named', says(['SOMETHING_NEW_AND_UNDOCUMENTED']), found())
        with changed('backend/server.py', lambda text: text + "\nNEW_FLAG = env_flag('ANOTHER_UNDOCUMENTED_FLAG', False)\n"):
            check('and so is a flag', says(['ANOTHER_UNDOCUMENTED_FLAG']), found())

        # -- suites
        with changed('tests/suites/orphan.py', content='"""A suite nobody registered."""\n'):
            check('a suite that is not registered, and has no row, is named for both', says(['orphan.py', 'NAMES']) and says(['orphan.py', 'tests/README.md']), found())
        with changed('tests/suites/__init__.py', replaced("'lint', ", '')):
            check('a suite that is left out of NAMES never runs, and the check says so', says(['lint.py', 'NAMES']), found())
        with changed('tests/suites/__init__.py', replaced("'lint', ", "'lint', 'ghost', ")):
            check('a name in NAMES with no file is named', says(['ghost', 'no tests/suites/ghost.py']), found())
        with changed('tests/README.md', lambda text: text.replace('| `lint` |', '| `lintx` |', 1)):
            check('a suite missing from the README’s table, and a row for one that is not there, are both named', says(['lint.py', 'no row']) and says(['lintx', 'does not exist']), found())
        check('the copy was put back as it was after every change', found() == [], found())
    finally:
        shutil.rmtree(root, ignore_errors=True)
