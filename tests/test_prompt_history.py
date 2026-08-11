from herdr_mobile import PROMPT_HISTORY_MAX_ENTRIES, PromptHistoryStore, PromptHistorySuggester


def test_add_persists_to_file_and_loads_back(tmp_path):
    path = tmp_path / "history.json"
    store = PromptHistoryStore(path)
    store.add("do it")
    store.add("hi")

    reloaded = PromptHistoryStore(path)
    assert reloaded.entries == ["hi", "do it"]  # most-recent-first


def test_add_dedupes_consecutive_identical_entries(tmp_path):
    store = PromptHistoryStore(tmp_path / "history.json")
    store.add("run tests")
    store.add("run tests")
    store.add("run tests")
    assert store.entries == ["run tests"]


def test_add_does_not_dedupe_non_consecutive_repeats(tmp_path):
    store = PromptHistoryStore(tmp_path / "history.json")
    store.add("a")
    store.add("b")
    store.add("a")
    assert store.entries == ["a", "b", "a"]


def test_add_ignores_blank_prompts(tmp_path):
    store = PromptHistoryStore(tmp_path / "history.json")
    store.add("   ")
    store.add("")
    assert store.entries == []


def test_add_strips_whitespace(tmp_path):
    store = PromptHistoryStore(tmp_path / "history.json")
    store.add("  hello  ")
    assert store.entries == ["hello"]


def test_cap_at_max_entries(tmp_path):
    store = PromptHistoryStore(tmp_path / "history.json")
    for i in range(PROMPT_HISTORY_MAX_ENTRIES + 10):
        store.add(f"prompt {i}")
    assert len(store.entries) == PROMPT_HISTORY_MAX_ENTRIES
    # Most recent survive, oldest are dropped.
    assert store.entries[0] == f"prompt {PROMPT_HISTORY_MAX_ENTRIES + 9}"
    assert f"prompt 0" not in store.entries


def test_load_from_nonexistent_file_is_empty(tmp_path):
    store = PromptHistoryStore(tmp_path / "does-not-exist.json")
    assert store.entries == []


def test_load_survives_corrupt_json(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("not valid json {{{")
    store = PromptHistoryStore(path)
    assert store.entries == []


def test_load_survives_unexpected_json_shape(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('{"not": "a list"}')
    store = PromptHistoryStore(path)
    assert store.entries == []


def test_add_survives_unwritable_directory(tmp_path):
    # Best-effort: a save failure must not raise or crash the caller.
    path = tmp_path / "no-such-parent" / "sub" / "history.json"
    unwritable_parent = tmp_path / "no-such-parent"
    unwritable_parent.mkdir()
    unwritable_parent.chmod(0o400)  # read-only: mkdir("sub") inside it will fail
    try:
        store = PromptHistoryStore(path)
        store.add("hello")  # must not raise
        assert store.entries == ["hello"]  # in-memory still updated
    finally:
        unwritable_parent.chmod(0o700)  # restore so tmp_path cleanup can remove it


async def test_suggester_returns_most_recent_case_sensitive_match(tmp_path):
    store = PromptHistoryStore(tmp_path / "history.json")
    store.add("run the tests")
    store.add("run the build")
    suggester = PromptHistorySuggester(store)
    assert await suggester.get_suggestion("run the") == "run the build"


async def test_suggester_falls_back_to_case_insensitive_match(tmp_path):
    store = PromptHistoryStore(tmp_path / "history.json")
    store.add("Run The Tests")
    suggester = PromptHistorySuggester(store)
    assert await suggester.get_suggestion("run the") == "Run The Tests"


async def test_suggester_prefers_case_sensitive_over_insensitive(tmp_path):
    store = PromptHistoryStore(tmp_path / "history.json")
    store.add("RUN the tests")  # older, case-insensitive-only match
    store.add("run the build")  # newer, case-sensitive match
    suggester = PromptHistorySuggester(store)
    assert await suggester.get_suggestion("run") == "run the build"


async def test_suggester_returns_none_for_empty_prefix(tmp_path):
    store = PromptHistoryStore(tmp_path / "history.json")
    store.add("anything")
    suggester = PromptHistorySuggester(store)
    assert await suggester.get_suggestion("") is None


async def test_suggester_returns_none_when_no_match(tmp_path):
    store = PromptHistoryStore(tmp_path / "history.json")
    store.add("run the tests")
    suggester = PromptHistorySuggester(store)
    assert await suggester.get_suggestion("fix the bug") is None
