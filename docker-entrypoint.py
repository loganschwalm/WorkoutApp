"""Container entrypoint: hand the data directory to the unprivileged user, then run the server as that user.

Images before this one ran the server as root, so an existing data volume, and the database in it, can be
owned by root. Fixing that needs root, so the container starts as root only for this and then drops to the
`workout` user for good. Started as any other user (docker run --user ...), it changes nothing and just runs.
"""

import os
import pwd
import sys

USER = 'workout'


def main():
    command = sys.argv[1:] or ['python', '/app/server.py']
    if os.getuid() == 0:
        account = pwd.getpwnam(USER)
        data_dir = os.path.dirname(os.path.abspath(os.environ.get('WORKOUT_DB', '/app/data/workouts.db')))
        os.makedirs(data_dir, exist_ok=True)
        for root, _dirs, files in os.walk(data_dir):
            # lchown: a symlink in the volume is re-owned itself, never whatever it points at.
            os.lchown(root, account.pw_uid, account.pw_gid)
            for name in files:
                os.lchown(os.path.join(root, name), account.pw_uid, account.pw_gid)
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
        os.environ['HOME'] = data_dir
    os.execvp(command[0], command)


if __name__ == '__main__':
    main()
