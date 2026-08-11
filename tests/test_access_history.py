from herdr_mobile import AccessHistoryStore


def test_record_persists_to_file_and_loads_back(tmp_path):
    path = tmp_path / "access.json"
    store = AccessHistoryStore(path)
    store.record("/dev/proj-a")

    reloaded = AccessHistoryStore(path)
    assert "/dev/proj-a" in reloaded.entries
    assert isinstance(reloaded.entries["/dev/proj-a"], float)


def test_record_updates_timestamp_on_repeated_access(tmp_path, monkeypatch):
    import herdr_mobile as hr

    store = AccessHistoryStore(tmp_path / "access.json")
    times = iter([100.0, 200.0])
    monkeypatch.setattr(hr.time, "time", lambda: next(times))

    store.record("/dev/proj-a")
    assert store.entries["/dev/proj-a"] == 100.0
    store.record("/dev/proj-a")
    assert store.entries["/dev/proj-a"] == 200.0


def test_load_from_nonexistent_file_is_empty(tmp_path):
    store = AccessHistoryStore(tmp_path / "does-not-exist.json")
    assert store.entries == {}


def test_load_survives_corrupt_json(tmp_path):
    path = tmp_path / "access.json"
    path.write_text("not valid json {{{")
    store = AccessHistoryStore(path)
    assert store.entries == {}


def test_load_survives_unexpected_json_shape(tmp_path):
    path = tmp_path / "access.json"
    path.write_text("[1, 2, 3]")  # a list, not a dict
    store = AccessHistoryStore(path)
    assert store.entries == {}


def test_load_ignores_non_string_or_non_numeric_entries(tmp_path):
    path = tmp_path / "access.json"
    path.write_text('{"/dev/ok": 123.0, "42": "not a number", "also_bad": null}')
    store = AccessHistoryStore(path)
    assert store.entries == {"/dev/ok": 123.0}


def test_record_survives_unwritable_directory(tmp_path):
    # Best-effort: a save failure must not raise or crash the caller.
    unwritable_parent = tmp_path / "no-such-parent"
    unwritable_parent.mkdir()
    unwritable_parent.chmod(0o400)  # read-only: mkdir("sub") inside it will fail
    try:
        store = AccessHistoryStore(unwritable_parent / "sub" / "access.json")
        store.record("/dev/proj")  # must not raise
        assert "/dev/proj" in store.entries  # in-memory state still updates
    finally:
        unwritable_parent.chmod(0o700)  # restore so tmp_path cleanup can remove it
