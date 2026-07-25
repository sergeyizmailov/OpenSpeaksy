import fcntl

import main


def test_instance_lock_rejects_second_owner(tmp_path):
    lock_path = tmp_path / "instance.lock"
    first = main._open_instance_lock(lock_path)
    assert first is not None

    second = main._open_instance_lock(lock_path)
    assert second is None

    fcntl.flock(first.fileno(), fcntl.LOCK_UN)
    first.close()

    third = main._open_instance_lock(lock_path)
    assert third is not None
    third.close()
