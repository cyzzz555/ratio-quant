"""Exclusive process locks; closing the file releases ownership on both platforms."""

import errno
import os
import sys
import time
from typing import IO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

LOCK_EX = 2
LOCK_NB = 4
LOCK_UN = 8


def flock(stream: IO[str], operation: int) -> None:
    if sys.platform == "win32":
        # Every handle locks the same byte, independent of append position or file size.
        descriptor = stream.fileno()
        while True:
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                mode = msvcrt.LK_UNLCK if operation == LOCK_UN else msvcrt.LK_NBLCK
                msvcrt.locking(descriptor, mode, 1)
                return
            except OSError as exc:
                if operation == LOCK_UN or exc.errno not in (errno.EACCES, errno.EDEADLK):
                    raise
                if operation & LOCK_NB:
                    raise BlockingIOError(exc.errno, "File is locked") from exc
                time.sleep(0.05)
    else:
        fcntl.flock(stream, operation)
