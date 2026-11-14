import pytest

from talaria.auth import hash_password
from talaria.users import UserStore


def test_first_start_migrates_legacy_password_to_admin(tmp_path):
    store = UserStore(tmp_path / "users.db", hash_password("secret"))
    admin = store.authenticate("admin", "secret")
    assert admin["username"] == "admin"
    assert admin["role"] == "admin"
    assert store.list_public()[0]["username"] == "admin"


def test_admin_can_create_user_and_user_password_isolated(tmp_path):
    store = UserStore(tmp_path / "users.db", hash_password("secret"))
    user = store.create("alice", "alice-password", "user")
    assert store.authenticate("alice", "alice-password")["id"] == user["id"]
    assert store.authenticate("alice", "secret") is None
    with pytest.raises(ValueError, match="role"):
        store.create("bob", "password", "owner")


def test_user_store_disables_user_but_keeps_admin(tmp_path):
    store = UserStore(tmp_path / "users.db", hash_password("secret"))
    user = store.create("alice", "alice-password", "user")
    store.set_enabled(user["id"], False)
    assert store.authenticate("alice", "alice-password") is None
    assert store.authenticate("admin", "secret")["role"] == "admin"
