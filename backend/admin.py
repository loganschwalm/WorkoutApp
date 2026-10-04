"""Account administration from the server's own command line: `server.py users`, `reset-password <account>`, `set-email <account> <email>` and
`delete-user <account>`, which manage accounts while the server runs, so a forgotten password can be reset without a mail server."""

import getpass
import os
import sys

from accounts import email_address, find_account, password_hash, password_problem
from config import DB_PATH, LOGIN_WINDOW
from database import connection, delete_account_rows
from validation import BadRequest


# ---- Account administration ---------------------------------------------------------------------------------
# `server.py users`, `server.py reset-password <account>` and `server.py set-email <account> <email>` manage accounts
# from the server's own command line, so a forgotten password can be reset without a mail server.

class AdminError(Exception):
    """A command that cannot be carried out; its message is printed and the command exits with status 1."""


def act_as_database_owner():
    """Run as root, switch to the user who owns the database (the service's user), so that the journal files SQLite
    creates beside it stay writable by the server. Anyone else stays who they are."""
    if not hasattr(os, 'getuid') or os.getuid() != 0:
        return
    owner = os.stat(DB_PATH)
    if owner.st_uid != 0:
        os.setgroups([])
        os.setgid(owner.st_gid)
        os.setuid(owner.st_uid)


def admin_account(database, login):
    row = find_account(database, login)
    if not row:
        raise AdminError(f'No account has the username or email {login!r}. `users` lists them.')
    return row


def read_new_password(username, email):
    """Asked twice, unseen, at a terminal; read from the first line of input otherwise, so it can be piped in. It has to
    pass the same rules as one set on the sign-in page."""
    if sys.stdin.isatty():
        password = getpass.getpass('New password: ')
        if getpass.getpass('Same again: ') != password:
            raise AdminError('The passwords did not match. Nothing was changed.')
    else:
        password = sys.stdin.readline().rstrip('\r\n')
    problem = password_problem(password, username, email or '')
    if problem:
        raise AdminError(f'{problem} Nothing was changed.')
    return password


def admin_users(args):
    with connection() as database:
        rows = database.execute('SELECT username, email FROM users ORDER BY username COLLATE NOCASE').fetchall()
    if not rows:
        print('No accounts yet.')
    width = max((len(row['username']) for row in rows), default=0)
    for row in rows:
        print(f"{row['username']:<{width}}  {row['email'] or '(no email)'}")


def admin_reset_password(args):
    with connection() as database:
        account = admin_account(database, args.account)
    username = account['username']
    stored_hash = password_hash(read_new_password(username, account['email']))
    with connection() as database:
        user_id = admin_account(database, username)['id']
        database.execute('UPDATE users SET password_hash = ? WHERE id = ?', (stored_hash, user_id))
        database.execute('DELETE FROM password_resets WHERE user_id = ?', (user_id,))
        database.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
    print(f'Set a new password for {username}, and signed the account out everywhere.')
    # The sign-in limit lives in the running server's memory, which this command cannot reach.
    print(f'If failed sign-ins had made it wait, that wait still runs out on its own (up to {LOGIN_WINDOW // 60} minutes), '
          'or restart the server to end it now.')


def admin_set_email(args):
    try:
        email = email_address(args.email)
    except BadRequest as error:
        raise AdminError(f'{error} Nothing was changed.')
    with connection() as database:
        row = admin_account(database, args.account)
        if database.execute('SELECT 1 FROM users WHERE email = ? AND id != ?', (email, row['id'])).fetchone():
            raise AdminError(f'Another account already uses {email}. Nothing was changed.')
        database.execute('UPDATE users SET email = ? WHERE id = ?', (email, row['id']))
        # A code already sent went to the old address.
        database.execute('DELETE FROM password_resets WHERE user_id = ?', (row['id'],))
    print(f"Set the email of {row['username']} to {email}.")


def admin_delete_user(args):
    with connection() as database:
        row = admin_account(database, args.account)
        count = database.execute('SELECT COUNT(*) FROM workouts WHERE user_id = ?', (row['id'],)).fetchone()[0]
    username, workouts = row['username'], f"{count} workout{'' if count == 1 else 's'}"
    if not args.yes:
        # Nothing to undo it with, so it is asked for by name; without a terminal to ask at, --yes says it instead.
        if not sys.stdin.isatty():
            raise AdminError(f'Deleting {username} and their {workouts} cannot be undone. Add --yes to go ahead. Nothing was changed.')
        if input(f'This deletes {username} and their {workouts}, and cannot be undone. Type the username to go ahead: ').strip() != username:
            raise AdminError('That is not the username. Nothing was changed.')
    with connection() as database:
        delete_account_rows(database, admin_account(database, username)['id'])
    print(f'Deleted {username} and their {workouts}.')
