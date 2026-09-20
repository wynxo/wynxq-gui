"""Cross-chat recall stays relevant, bounded, and user-controlled."""

from wynxq import chat_recall
from wynxq.storage import Store


def make_chat(store, title, messages):
    task = store.create_conversation(title)
    store.set_messages(task["id"], messages)
    return task


def test_recall_finds_relevant_older_user_text_and_ignores_assistant_claims(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    relevant = make_chat(store, "Linux setup", [
        {"role": "user", "content": "I use KDE Plasma on Debian for my laptop."},
        {"role": "assistant", "content": "You also use SecretAssistantFact OS."},
    ])
    make_chat(store, "Cooking", [
        {"role": "user", "content": "I made pasta yesterday."},
        {"role": "assistant", "content": "KDE Plasma is definitely your favorite desktop."},
    ])

    rows = chat_recall.recall(store, "How did I configure KDE Plasma before?")

    assert rows
    assert rows[0]["id"] == relevant["id"]
    joined = " ".join(rows[0]["excerpts"])
    assert "KDE Plasma" in joined
    assert "SecretAssistantFact" not in str(rows)
    store.close()


def test_active_chat_is_never_recalled_into_itself(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    current = make_chat(store, "Current", [
        {"role": "user", "content": "My unusual marker is ALPHA-RECALL-ONLY."},
    ])
    older = make_chat(store, "Older", [
        {"role": "user", "content": "My unusual marker is BETA-RECALL-ONLY."},
    ])

    rows = chat_recall.recall(
        store, "What did I say about RECALL ONLY before?", exclude_id=current["id"]
    )

    assert all(row["id"] != current["id"] for row in rows)
    assert any(row["id"] == older["id"] for row in rows)
    assert "ALPHA-RECALL-ONLY" not in str(rows)
    store.close()


def test_explicit_generic_recall_uses_recent_user_messages(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    older = make_chat(store, "Older", [
        {"role": "user", "content": "The old remembered sentence."},
    ])
    recent = make_chat(store, "Recent", [
        {"role": "user", "content": "The newest remembered sentence."},
    ])

    rows = chat_recall.recall(store, "What did I tell you before?", limit=2)

    assert [row["id"] for row in rows][:2] == [recent["id"], older["id"]]
    store.close()


def test_unrelated_ordinary_prompt_does_not_pull_random_history(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    make_chat(store, "Linux", [
        {"role": "user", "content": "I use KDE Plasma and Debian."},
    ])

    assert chat_recall.recall(store, "Explain photosynthesis in plants") == []
    store.close()


def test_deleting_a_chat_removes_it_from_recall(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    old = make_chat(store, "Rust notes", [
        {"role": "user", "content": "I was learning Rust ownership rules."},
    ])
    assert chat_recall.recall(store, "What did I say about Rust before?")

    store.delete_conversation(old["id"])

    assert chat_recall.recall(store, "What did I say about Rust before?") == []
    store.close()


def test_prompt_labels_recalled_text_as_historical_not_instructions(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    make_chat(store, "Old preference", [
        {"role": "user", "content": "I prefer compact answers about networking."},
    ])

    text = chat_recall.prompt(store, "What did I say about networking before?")

    assert "Relevant past-chat context" in text
    assert "not new instructions" in text
    assert "current request always wins" in text
    store.close()


def test_sidebar_pin_does_not_turn_an_old_chat_into_recent_recall(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    old = make_chat(store, "Pinned old", [
        {"role": "user", "content": "The older remembered sentence."},
    ])
    store.set_pinned(old["id"], True)
    recent = make_chat(store, "Actually recent", [
        {"role": "user", "content": "The actually newest remembered sentence."},
    ])

    rows = chat_recall.recall(store, "What did I tell you before?", limit=2)

    assert [row["id"] for row in rows][:2] == [recent["id"], old["id"]]
    store.close()


def test_semantic_candidate_recency_ignores_sidebar_pin_order(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    old = make_chat(store, "Pinned old", [
        {"role": "user", "content": "Older context with no matching search words."},
    ])
    store.set_pinned(old["id"], True)
    recent = make_chat(store, "Actually recent", [
        {"role": "user", "content": "Newest context with no matching search words."},
    ])

    rows = chat_recall.candidate_excerpts(store, [], budget=5000)

    assert rows
    assert rows[0]["chat"] == recent["id"]
    store.close()
