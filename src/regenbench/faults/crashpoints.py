import os
import sys


class CrashInjector:
    """Injects real OS process hard exits (os._exit) at designated points."""

    @staticmethod
    def maybe_crash(crash_point: str | None, target_point: str) -> None:
        if crash_point and crash_point == target_point:
            sys.stdout.flush()
            sys.stderr.flush()
            # Hard process exit: bypasses Python exception handling and in-memory cleanup
            os._exit(42)
