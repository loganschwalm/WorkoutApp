"""Container entrypoint: hand the data directory to the unprivileged user, then run the server as that user.

Images before this one ran the server as root, so an existing data volume, and the database in it, can be
owned by root. Fixing that needs root, so the container starts as root only for this and then drops to the
`workout` user for good. Started as any other user (docker run --user ...), it changes nothing and just runs.
"""

import os
import pwd
import sys

USER = 'workout'


def hand_over(data_dir, uid, gid):
    """Gives everything in the data directory to the workout user. What it owns already is left alone, so a start after the
    first walks the volume without writing to it. A path that cannot be given (a volume on NFS that squashes root, or one
    mounted read-only) is said and left, rather than stopping the container: the server says plainly enough if it then
    cannot write the database, and a container that stops here only starts again, and stops, for ever."""
    if os.path.realpath(data_dir) == '/':
        print(f'WORKOUT_DB is a file in /, so the whole filesystem is not handed to the {USER} user. Put the database in a '
              'directory of its own, such as /app/data.', file=sys.stderr, flush=True)
        return
    for root, _dirs, files in os.walk(data_dir):
        for path in [root, *(os.path.join(root, name) for name in files)]:
            try:
                status = os.lstat(path)
                if (status.st_uid, status.st_gid) != (uid, gid):
                    # lchown: a symlink in the volume is re-owned itself, never whatever it points at.
                    os.lchown(path, uid, gid)
            except OSError as error:
                print(f'Could not give {path} to the {USER} user ({error.strerror}). The server may not be able to write it.',
                      file=sys.stderr, flush=True)


def main():
    command = sys.argv[1:] or ['python', '/app/server.py']
    if os.getuid() == 0:
        account = pwd.getpwnam(USER)
        data_dir = os.path.dirname(os.path.abspath(os.environ.get('WORKOUT_DB', '/app/data/workouts.db')))
        os.makedirs(data_dir, exist_ok=True)
        hand_over(data_dir, account.pw_uid, account.pw_gid)
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
        os.environ['HOME'] = data_dir
    os.execvp(command[0], command)


if __name__ == '__main__':
    main()
