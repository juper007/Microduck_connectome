"""Linux child shim: terminate on supervisor death, including launch races."""
from __future__ import annotations

import ctypes
import os
import signal
import sys


PR_SET_PDEATHSIG = 1


def main() -> None:
    expected_parent = int(sys.argv[1])
    command = sys.argv[2:]
    if not command or sys.platform != "linux":
        raise SystemExit(64)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGINT, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG)")
    # Parent may have died between fork and prctl. Never exec the trial then.
    if os.getppid() != expected_parent:
        raise SystemExit(75)
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    main()
