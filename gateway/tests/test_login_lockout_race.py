"""The lockout counter must not lose concurrent failures (gateway/users.py)."""

import threading
import time

from gateway import users
from gateway.tests.test_gateway_app import env  # noqa: F401


def test_ten_concurrent_wrong_passwords_lock_the_account(env, monkeypatch):
    _, _, db = env
    email = "race@example.com"
    users.create_user(db, email, "correct horse 42", name="Race", role="approver",
                      kitchen_id="demo-kitchen")
    real = users._password_ok

    def slow(user, password):
        time.sleep(0.05)
        return real(user, password)

    monkeypatch.setattr(users, "_password_ok", slow)
    barrier = threading.Barrier(10)
    unexpected = []

    def attempt():
        barrier.wait()
        try:
            users.login(db, email, "wrong password 99")
        except users.AuthError:
            pass
        except Exception as exc:  # a broken count must fail the test, not the thread
            unexpected.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not unexpected
    stored = db.users.find_one({"_id": email})
    assert stored["locked_until"] is not None
