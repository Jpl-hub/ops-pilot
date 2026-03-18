from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opspilot.infra.auth_store import AuthStore


class AuthStoreTestCase(unittest.TestCase):
    def test_register_login_and_revoke_session(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "auth.db"
            store = AuthStore(f"sqlite+pysqlite:///{db_path}")
            store.initialize()

            user, register_token = store.register_user(
                username="tester",
                display_name="测试用户",
                password="secret123",
                role="investor",
            )
            self.assertEqual(user.username, "tester")
            self.assertEqual(user.role, "investor")
            self.assertIsNotNone(store.get_user_by_token(register_token))

            logged_in_user, login_token = store.login(username="tester", password="secret123")
            self.assertEqual(logged_in_user.display_name, "测试用户")
            self.assertIsNotNone(store.get_user_by_token(login_token))

            store.revoke_session(login_token)
            self.assertIsNone(store.get_user_by_token(login_token))
            store.close()

    def test_register_rejects_duplicate_username(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "auth.db"
            store = AuthStore(f"sqlite+pysqlite:///{db_path}")
            store.initialize()
            store.register_user(
                username="tester",
                display_name="测试用户",
                password="secret123",
                role="investor",
            )

            with self.assertRaises(ValueError):
                store.register_user(
                    username="tester",
                    display_name="另一个用户",
                    password="secret123",
                    role="management",
                )
            store.close()


if __name__ == "__main__":
    unittest.main()
