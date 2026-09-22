import sys
from pathlib import Path

import pytest

# Make the project root importable so tests can `from transcriber import ...`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _reset_pending_retry_state():
    """
    The pending failure counts and the backoff schedule are module globals, so
    one test's failed file would otherwise still be "not due yet" in the next
    and silently skip its recovery pass.
    """
    import main

    _clear(main)
    yield
    _clear(main)


def _clear(main):
    main._pending_failures.clear()
    main._pending_next_attempt.clear()
    main._pending_attempt_count.clear()
