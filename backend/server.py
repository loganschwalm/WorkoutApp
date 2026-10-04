"""The Workout Tracker server. Run with no arguments to serve; with a command (users, reset-password, set-email, delete-user) to manage
accounts instead. The pieces are the other files in this directory: see readme-for-llm.md, Project structure."""

import argparse
import os
import sys

from admin import AdminError, act_as_database_owner, admin_delete_user, admin_reset_password, admin_set_email, admin_users
from config import DB_PATH
from database import init_database
from webserver import serve


def main(argv):
    parser = argparse.ArgumentParser(
        prog='server.py', description='Runs the Workout Tracker server. The commands manage its accounts instead, '
                                      'in the database WORKOUT_DB names, while the server keeps running.')
    commands = parser.add_subparsers(dest='command', metavar='command')
    commands.add_parser('users', help='list every account and its email')
    reset = commands.add_parser('reset-password', help='set a new password for an account, and sign it out everywhere')
    reset.add_argument('account', help='its username or email')
    email = commands.add_parser('set-email', help="add or change an account's email")
    email.add_argument('account', help='its username or current email')
    email.add_argument('email', help='the new email')
    delete = commands.add_parser('delete-user', help='delete an account and everything in it')
    delete.add_argument('account', help='its username or email')
    delete.add_argument('--yes', action='store_true', help='without asking to confirm, as a script needs')
    args = parser.parse_args(argv)
    if args.command is None:
        serve()
        return 0
    if not os.path.exists(DB_PATH):
        print(f'There is no database at {DB_PATH}. Set WORKOUT_DB to the one the server uses.', file=sys.stderr)
        return 1
    act_as_database_owner()
    init_database()
    try:
        {'users': admin_users, 'reset-password': admin_reset_password, 'set-email': admin_set_email,
         'delete-user': admin_delete_user}[args.command](args)
    except AdminError as error:
        print(error, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\nStopped. Nothing was changed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
