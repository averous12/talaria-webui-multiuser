import pytest

from talaria.artifacts import ArtifactStore


def test_artifacts_survive_store_reopen_and_are_profile_scoped(tmp_path):
    first_store = ArtifactStore(tmp_path / "artifacts.db", profile_id="profile-a")
    second_store = ArtifactStore(tmp_path / "artifacts.db", profile_id="profile-b")
    first = first_store.put(
        "session", 7, "/safe/report.pdf", "report.pdf", "application/pdf", b"PDF data"
    )
    second = second_store.put(
        "session", 7, "/safe/report.pdf", "report.pdf", "application/pdf", b"other"
    )

    reopened = ArtifactStore(tmp_path / "artifacts.db", profile_id="profile-a")
    assert reopened.get(first) == {
        "session_id": "session",
        "message_id": 7,
        "path": "/safe/report.pdf",
        "name": "report.pdf",
        "mime": "application/pdf",
        "data": b"PDF data",
    }
    assert ArtifactStore(tmp_path / "artifacts.db", profile_id="profile-b").get(first) is None
    assert (
        ArtifactStore(tmp_path / "artifacts.db", profile_id="profile-b").get(second)["data"]
        == b"other"
    )
    assert reopened.get_by_source("session", 7, "/safe/report.pdf")["id"] == first


def test_artifact_store_rejects_empty_oversized_or_invalid_records(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts.db", profile_id="p", max_bytes=4)
    with pytest.raises(ValueError):
        store.put("s", 1, "/safe/a.pdf", "a.pdf", "application/pdf", b"")
    with pytest.raises(ValueError):
        store.put("s", 1, "/safe/a.pdf", "a.pdf", "application/pdf", b"12345")
    with pytest.raises(ValueError):
        store.put("s", 0, "/safe/a.pdf", "a.pdf", "application/pdf", b"a")


def test_artifact_store_deletes_session_artifacts(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts.db", profile_id="p")
    artifact = store.put("s", 3, "/safe/a.txt", "a.txt", "text/plain", b"a")
    store.delete_session("s")
    assert store.get(artifact) is None
