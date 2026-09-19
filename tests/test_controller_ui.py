"""Controller behaviour that the interface depends on."""
import threading
import time
from datetime import datetime

import pytest
from PySide6.QtCore import QCoreApplication

from wynxq import context as ctx
from wynxq.controller import Controller, Messages, derive_title, group_for
from wynxq.engine import AUTO, FULL, MANUAL, SAFE
from wynxq.storage import Store

APP = QCoreApplication.instance() or QCoreApplication([])


class IdleDesktop:
    def __init__(self, connected=False):
        self.connected = connected
        self.captures = []

    def status(self):
        return {"connected": self.connected, "available": True,
                "backend": "test", "detail": "Off"}

    def disconnect(self):
        self.connected = False

    def capture(self, kind="screen", cancel=None):
        self.captures.append(kind)
        return {"ok": True, "image": "AAA", "width": 640, "height": 480, "detail": "Full screen"}

    def active_window(self):
        return {"title": "Firefox", "detail": "X11"}


def controller(tmp_path, **kwargs):
    store = Store(tmp_path / "history.sqlite3")
    return Controller(store=store, desktop=kwargs.pop("desktop", IdleDesktop()),
                      autoconnect=False, **kwargs)


# ------------------------------------------------------------------ sidebar
def test_conversations_group_by_age():
    # Buckets are calendar days, so the reference point is fixed at midday to
    # keep the test independent of when it happens to run.
    now = datetime(2026, 3, 15, 12, 0).timestamp()
    assert group_for(now, now) == "Today"
    assert group_for(now - 2 * 3600, now) == "Today"
    assert group_for(now - 26 * 3600, now) == "Yesterday"
    assert group_for(now - 4 * 86400, now) == "Previous 7 days"
    assert group_for(now - 20 * 86400, now) == "Previous 30 days"
    assert group_for(now - 200 * 86400, now) == "Older"


def test_task_groups_put_pinned_first_and_respect_search(tmp_path):
    bridge = controller(tmp_path)
    alpha = bridge.store.create_conversation("Alpha notes")
    bridge.store.create_conversation("Beta plan")
    bridge.store.set_pinned(alpha["id"], True)
    bridge._refresh_tasks()

    groups = bridge.taskGroups
    assert groups[0]["title"] == "Pinned"
    assert groups[0]["items"][0]["title"] == "Alpha notes"

    bridge.setSearch("beta")
    titles = [item["title"] for group in bridge.taskGroups for item in group["items"]]
    assert titles == ["Beta plan"]

    bridge.setSearch("")
    assert len([i for g in bridge.taskGroups for i in g["items"]]) == 2
    bridge.shutdown()


# -------------------------------------------------------------- attachments
def test_attaching_and_removing_local_context(tmp_path):
    bridge = controller(tmp_path)
    source = tmp_path / "notes.md"
    source.write_text("# Title\ncontent", encoding="utf-8")

    bridge.attachPath(str(source))
    assert bridge.attachmentCount == 1
    assert bridge.attachments[0]["title"] == "notes.md"
    assert bridge.contextUsed > 0

    bridge.removeAttachment(bridge.attachments[0]["id"])
    assert bridge.attachmentCount == 0

    bridge.attachPath(str(source))
    bridge.clearAttachments()
    assert bridge.attachmentCount == 0
    bridge.shutdown()


def test_attaching_a_missing_file_explains_itself_instead_of_raising(tmp_path):
    bridge = controller(tmp_path)
    bridge.attachPath(str(tmp_path / "ghost.txt"))
    assert bridge.attachmentCount == 0
    assert bridge.errorTitle == "That file could not be attached"
    assert "does not exist" in bridge.error
    bridge.shutdown()


def test_file_urls_from_a_drop_are_accepted(tmp_path):
    bridge = controller(tmp_path)
    source = tmp_path / "dropped.txt"
    source.write_text("hi", encoding="utf-8")
    bridge.attachPath("file://" + str(source))
    assert bridge.attachmentCount == 1
    bridge.shutdown()


def test_nonvision_send_keeps_image_locally_for_transcript_but_warns_user(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    bridge._online = True
    bridge._model_capabilities = ["completion"]
    bridge._attachments = [ctx.make(ctx.IMAGE, "shot.png", image="AAA", width=8, height=8),
                           ctx.make(ctx.FILE, "a.py", path="/tmp/a.py", text="print(1)")]
    monkeypatch.setattr(bridge, "_start_run", lambda history: None)
    bridge.send("look at this")

    payloads = [m for m in bridge._history if m.get("images")]
    assert len(payloads) == 1
    assert payloads[0]["images"] == ["AAA"]
    assert bridge.messages.items[-1]["attachments"][0]["title"] == "shot.png"
    # AgentEngine owns the inference boundary; it strips unsupported images
    # immediately before the Ollama request, while local history keeps them.

    assert any("a.py" in str(m.get("content", "")) for m in bridge._history)
    assert bridge.attachmentCount == 0
    bridge.shutdown()


def test_images_reach_a_vision_model(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    bridge._online = True
    bridge._model_capabilities = ["completion", "vision"]
    bridge._attachments = [ctx.make(ctx.IMAGE, "shot.png", image="AAA", width=8, height=8)]
    monkeypatch.setattr(bridge, "_start_run", lambda history: None)
    bridge.send("what is this")
    assert any(m.get("images") == ["AAA"] for m in bridge._history)
    bridge.shutdown()


def test_capture_failures_offer_a_route_to_the_settings(tmp_path):
    class BrokenDesktop(IdleDesktop):
        def capture(self, kind="screen", cancel=None):
            raise RuntimeError("Portal denied the request")

    bridge = controller(tmp_path, desktop=BrokenDesktop())
    bridge._capture_busy = False
    bridge._capture("screen")
    for _ in range(200):
        APP.processEvents()
        if bridge.errorTitle:
            break
        time.sleep(0.01)
    assert bridge.errorTitle == "Screen capture failed"
    assert [action["action"] for action in bridge.errorActions] == ["desktop"]
    bridge.shutdown()


# ------------------------------------------------------- capability warnings
def test_capability_warning_covers_images_tools_vision_and_thinking(tmp_path):
    bridge = controller(tmp_path, desktop=IdleDesktop(connected=True))
    bridge._online = True

    bridge._model_capabilities = ["completion", "tools", "vision"]
    assert bridge.capabilityWarning == ""

    bridge._model_capabilities = ["completion", "tools"]
    assert "cannot click or type" in bridge.capabilityWarning

    bridge._model_capabilities = ["completion"]
    assert "does not advertise tool calling" in bridge.capabilityWarning

    bridge._attachments = [ctx.make(ctx.IMAGE, "a.png", image="AAA")]
    assert "cannot read images" in bridge.capabilityWarning

    bridge._attachments = []
    bridge._model_capabilities = ["completion", "tools", "vision"]
    bridge._think = True
    assert "does not support thinking" in bridge.capabilityWarning
    bridge.shutdown()


def test_capability_warning_is_silent_while_probing(tmp_path):
    bridge = controller(tmp_path)
    bridge._online = True
    bridge._capability_probe_active = True
    bridge._attachments = [ctx.make(ctx.IMAGE, "a.png", image="AAA")]
    assert bridge.capabilityWarning == ""
    bridge.shutdown()


# ------------------------------------------------------------- permissioning
def test_permission_mode_is_validated_and_persisted(tmp_path):
    bridge = controller(tmp_path)
    assert bridge.permissionMode == SAFE
    bridge.setPermissionMode(MANUAL)
    assert bridge.permissionMode == MANUAL
    assert bridge.permissionModeLabel == "Manual"
    assert bridge.store.get_setting("permission_mode") == MANUAL
    bridge.setPermissionMode("nonsense")
    assert bridge.permissionMode == MANUAL
    bridge.shutdown()


def test_the_permission_ladder_is_offered_whole_and_described(tmp_path):
    bridge = controller(tmp_path)
    offered = bridge.permissionModes
    assert [entry["id"] for entry in offered] == [MANUAL, SAFE, AUTO, FULL]
    assert [entry["label"] for entry in offered] == ["Manual", "Auto-approve", "Auto", "Full access"]
    # Every rung says what it does; an unexplained mode is one nobody picks.
    assert all(len(entry["detail"]) > 20 for entry in offered)
    bridge.setPermissionMode(FULL)
    assert bridge.permissionModeDetail == offered[3]["detail"]
    bridge.shutdown()


def test_a_database_written_before_the_ladder_is_migrated_once(tmp_path):
    """"ask" was the old id for what is now Manual. Reading it must not drop the
    user back to the default, and the setting on disk is rewritten to match."""
    store = Store(tmp_path / "history.sqlite3")
    store.set_setting("permission_mode", "ask")
    bridge = Controller(store=store, desktop=IdleDesktop(), autoconnect=False)
    assert bridge.permissionMode == MANUAL
    assert bridge.store.get_setting("permission_mode") == MANUAL
    bridge.shutdown()


def test_a_confirmation_blocks_the_worker_until_the_user_answers(tmp_path):
    bridge = controller(tmp_path)
    answers = []

    def worker():
        answers.append(bridge._confirm_action("type_text", {"text": "hi"}, "sensitive"))

    thread = threading.Thread(target=worker)
    thread.start()
    for _ in range(200):
        APP.processEvents()
        if bridge.permissionPending:
            break
        time.sleep(0.01)
    assert bridge.permissionPending is True
    assert bridge.permissionSummary == "Type “hi”"
    assert bridge.permissionRisk == "sensitive"

    bridge.resolvePermission(True)
    thread.join(3)
    assert answers == [True]
    assert bridge.permissionPending is False
    bridge.shutdown()


def test_declining_is_reported_back_to_the_worker(tmp_path):
    bridge = controller(tmp_path)
    result = []
    thread = threading.Thread(target=lambda: result.append(
        bridge._confirm_action("press_key", {"keys": ["ctrl", "s"]}, "sensitive")))
    thread.start()
    for _ in range(200):
        APP.processEvents()
        if bridge.permissionPending:
            break
        time.sleep(0.01)
    bridge.resolvePermission(False)
    thread.join(3)
    assert result == [False]
    bridge.shutdown()


def test_allow_rest_of_task_stops_prompting_until_the_run_ends(tmp_path):
    bridge = controller(tmp_path)
    first = []
    thread = threading.Thread(target=lambda: first.append(
        bridge._confirm_action("type_text", {"text": "a"}, "sensitive")))
    thread.start()
    for _ in range(200):
        APP.processEvents()
        if bridge.permissionPending:
            break
        time.sleep(0.01)
    bridge.allowRestOfTask()
    thread.join(3)
    assert first == [True]
    # A second action in the same run goes straight through.
    assert bridge._confirm_action("press_key", {"keys": ["a"]}, "sensitive") is True
    assert bridge.permissionPending is False
    bridge.shutdown()


def test_stopping_denies_a_pending_action(tmp_path):
    bridge = controller(tmp_path)
    result = []
    thread = threading.Thread(target=lambda: result.append(
        bridge._confirm_action("click", {"x": 1, "y": 1}, "normal")))
    thread.start()
    for _ in range(200):
        APP.processEvents()
        if bridge.permissionPending:
            break
        time.sleep(0.01)
    bridge.stop()
    thread.join(3)
    assert result == [False]
    bridge.shutdown()


def test_shutdown_releases_a_worker_waiting_on_approval(tmp_path):
    bridge = controller(tmp_path)
    result = []
    thread = threading.Thread(target=lambda: result.append(
        bridge._confirm_action("click", {"x": 1, "y": 1}, "normal")))
    thread.start()
    for _ in range(200):
        APP.processEvents()
        if bridge.permissionPending:
            break
        time.sleep(0.01)
    bridge.shutdown()
    thread.join(3)
    assert result == [False]


# -------------------------------------------------------------- model catalog
def test_catalog_entries_carry_size_and_quantisation(tmp_path):
    bridge = controller(tmp_path)
    entry = Controller._catalog_entry({
        "name": "gemma3:4b", "size": 3_400_000_000,
        "details": {"family": "gemma3", "parameter_size": "4.3B", "quantization_level": "Q4_K_M"},
    })
    assert entry["parameters"] == "4.3B"
    assert entry["quantization"] == "Q4_K_M"
    assert entry["sizeLabel"].endswith("GB")
    bridge.shutdown()


def test_favourite_models_persist_and_sort_first(tmp_path):
    bridge = controller(tmp_path)
    bridge._catalog = [Controller._catalog_entry({"name": name, "size": 1}) for name in ("zeta", "alpha")]
    bridge.toggleFavoriteModel("zeta")
    assert bridge.store.get_setting("favorite_models") == ["zeta"]
    assert bridge.modelCatalog[0]["name"] == "zeta"
    assert bridge.modelCatalog[0]["favorite"] is True
    bridge.toggleFavoriteModel("zeta")
    assert bridge.store.get_setting("favorite_models") == []
    bridge.shutdown()


def test_selecting_a_model_records_it_as_recent(tmp_path):
    bridge = controller(tmp_path)
    bridge.setModel("gemma3:4b")
    bridge.setModel("qwen3:8b")
    assert bridge.store.get_setting("recent_models")[0] == "qwen3:8b"
    assert bridge.store.get_setting("model") == "qwen3:8b"
    bridge.shutdown()


def test_connection_state_reports_what_the_header_needs(tmp_path):
    bridge = controller(tmp_path)
    assert bridge.connectionState == "offline"
    bridge._online = True
    assert bridge.connectionState == "connected"
    bridge._pulling = True
    assert bridge.connectionState == "downloading"
    bridge._pulling = False
    bridge._probe_active = True
    assert bridge.connectionState == "connecting"
    bridge.shutdown()


# ------------------------------------------------------------------ settings
def test_appearance_settings_persist_and_reject_bad_values(tmp_path):
    bridge = controller(tmp_path)
    assert bridge.setTheme("Ion") is True
    assert bridge.accentColor == Controller.THEMES["Ion"]
    assert bridge.setTheme("Nope") is False

    assert bridge.setAccent("#123456") is True
    assert bridge.accentColor == "#123456"
    assert bridge.setAccent("not a colour") is False
    assert "not valid" in bridge.errorTitle

    bridge.setDensity("Compact")
    assert bridge.store.get_setting("density") == "Compact"
    bridge.setDensity("Roomy")
    assert bridge.density == "Compact"

    bridge.setFlag("reduced_motion", True)
    assert bridge.reducedMotion is True
    assert bridge.store.get_setting("reduced_motion") is True
    bridge.setFlag("not_a_setting", True)
    bridge.shutdown()


def test_legacy_theme_names_migrate(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    store.set_setting("theme", "Obsidian")
    bridge = Controller(store=store, desktop=IdleDesktop(), autoconnect=False)
    assert bridge.theme == "Platinum"
    bridge.shutdown()


def test_endpoint_validation_refuses_remote_servers(tmp_path):
    bridge = controller(tmp_path)
    assert bridge.setEndpoint("http://example.com:11434") is False
    assert "not usable" in bridge.errorTitle
    assert bridge.endpoint == "http://127.0.0.1:11434"
    bridge.shutdown()


def test_onboarding_state_round_trips(tmp_path):
    bridge = controller(tmp_path)
    assert bridge.onboarded is False
    bridge.completeOnboarding()
    assert bridge.onboarded is True
    assert bridge.store.get_setting("onboarded") is True
    bridge.resetOnboarding()
    assert bridge.onboarded is False
    bridge.shutdown()


# ------------------------------------------------------------- conversations
def test_branching_forks_history_at_a_message(tmp_path):
    bridge = controller(tmp_path)
    task = bridge.store.create_conversation("Original", "local:test")
    history = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "first"},
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": "second"},
    ]
    bridge.store.set_messages(task["id"], history, "local:test")
    bridge.openTask(task["id"])

    bridge.branchFrom(1)
    assert bridge.taskTitle == "Original branch"
    assert [m["content"] for m in bridge._history] == ["one", "first"]
    # The original is untouched.
    assert len(bridge.store.get_messages(task["id"])) == 4
    bridge.shutdown()


def test_editing_a_message_rewrites_history_and_reruns(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    bridge._online = True
    task = bridge.store.create_conversation("Chat", "local:test")
    bridge.store.set_messages(task["id"], [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
    ], "local:test")
    bridge.openTask(task["id"])

    started = []
    monkeypatch.setattr(bridge, "_start_run", lambda history: started.append(list(history)))
    bridge.editMessage(0, "new question")
    assert started == [[{"role": "user", "content": "new question"}]]
    assert bridge.store.get_messages(task["id"]) == [{"role": "user", "content": "new question"}]
    bridge.shutdown()


def test_renaming_and_duplicating_by_id(tmp_path):
    bridge = controller(tmp_path)
    task = bridge.store.create_conversation("First", "local:test")
    bridge.store.set_messages(task["id"], [{"role": "user", "content": "hey"}], "local:test")

    bridge.renameTaskById(task["id"], "Renamed")
    assert bridge.store.get_conversation(task["id"])["title"] == "Renamed"

    bridge.duplicateTaskById(task["id"])
    assert bridge.taskTitle == "Renamed copy"
    assert bridge.store.get_messages(bridge.taskId) == [{"role": "user", "content": "hey"}]
    bridge.shutdown()


def test_regenerate_is_blocked_while_the_desktop_is_live(tmp_path):
    bridge = controller(tmp_path, desktop=IdleDesktop(connected=True))
    bridge._online = True
    task = bridge.store.create_conversation("Chat", "local:test")
    bridge.store.set_messages(task["id"], [{"role": "user", "content": "hey"}], "local:test")
    bridge.openTask(task["id"])
    assert bridge.canRegenerate is False
    toasts = []
    bridge.toast.connect(toasts.append)
    bridge.regenerate()
    assert toasts and "screen control" in toasts[0].lower()
    bridge.shutdown()


def test_context_usage_counts_history_and_attachments(tmp_path):
    bridge = controller(tmp_path)
    bridge._history = [{"role": "user", "content": "x" * 400}]
    before = bridge.contextUsed
    bridge._attachments = [ctx.make(ctx.FILE, "a.py", text="y" * 400)]
    assert bridge.contextUsed > before
    assert 0 < bridge.contextFraction < 1
    assert "context" in bridge.contextSummary
    bridge.shutdown()


# -------------------------------------------------------------------- errors
def test_errors_carry_a_title_and_recovery_actions(tmp_path):
    bridge = controller(tmp_path)
    bridge.send("hello")  # offline
    assert bridge.errorTitle == "Ollama isn't connected"
    assert [action["action"] for action in bridge.errorActions] == ["retry", "settings"]
    bridge.clearError()
    assert bridge.error == "" and bridge.errorActions == []
    bridge.shutdown()


# ------------------------------------------------------------ message model
def test_message_model_folds_tool_calls_into_activity_groups(tmp_path):
    bridge = controller(tmp_path)
    bridge.messages.replace([
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "working"},
        {"role": "tool", "tool_name": "screenshot", "content": '{"ok": true}'},
        {"role": "tool", "tool_name": "click", "content": '{"ok": false, "error": "missed"}'},
        {"role": "assistant", "content": "done"},
    ])
    kinds = [item["kind"] for item in bridge.messages.items]
    assert kinds == ["user", "assistant", "activity", "assistant"]
    steps = bridge.messages.items[2]["steps"]
    assert [step["state"] for step in steps] == ["done", "failed"]
    assert steps[1]["detail"] == "missed"
    bridge.shutdown()


def test_streaming_assistant_text_produces_blocks_and_a_tail(tmp_path):
    bridge = controller(tmp_path)
    bridge.messages.append_message("assistant", streaming=True)
    for chunk in ["Hello\n", "\n", "```python\n", "x = 1\n"]:
        bridge.messages.stream("body", chunk)
    item = bridge.messages.items[-1]
    assert [block["kind"] for block in item["blocks"]] == ["markdown"]
    assert item["tailKind"] == "code"
    assert item["tailLabel"] == "Python"

    bridge.messages.stream("body", "```\n")
    bridge.messages.finish_stream(2.5)
    item = bridge.messages.items[-1]
    assert [block["kind"] for block in item["blocks"]] == ["markdown", "code"]
    assert item["tail"] == ""
    assert item["streaming"] is False
    assert item["thinkSeconds"] == 2.5
    bridge.shutdown()


def test_activity_steps_append_into_one_group_then_update(tmp_path):
    bridge = controller(tmp_path)
    bridge.messages.append_activity({"name": "screenshot", "icon": "eye", "label": "Inspecting",
                                     "summary": "Capture the screen", "state": "running",
                                     "detail": "", "ms": 0, "output": ""})
    bridge.messages.append_activity({"name": "click", "icon": "cursor", "label": "Clicking",
                                     "summary": "Click at 4, 5", "state": "running",
                                     "detail": "", "ms": 0, "output": ""})
    assert len(bridge.messages.items) == 1
    bridge.messages.update_last_step(state="done", ms=120, output="ok")
    steps = bridge.messages.items[0]["steps"]
    assert len(steps) == 2
    assert steps[0]["state"] == "running"
    assert steps[1]["state"] == "done" and steps[1]["ms"] == 120
    bridge.shutdown()


def test_message_roles_expose_everything_the_delegate_requires(tmp_path):
    bridge = controller(tmp_path)
    names = {value.decode() for value in Messages.ROLES.values()}
    for role in ("kind", "body", "thought", "blocks", "tail", "tailKind",
                 "tailLanguage", "tailLabel", "steps", "attachments", "streaming",
                 "thinkSeconds", "thinkDone", "speaker"):
        assert role in names
    bridge.shutdown()


# -------------------------------------------------------------- highlighting
def test_the_bridge_exposes_theme_aware_rendering(tmp_path):
    bridge = controller(tmp_path)
    bridge.setCodePalette({"keyword": "#ff0000"})
    assert "#ff0000" in bridge.highlight("def f(): pass", "python")
    bridge.setHtmlPalette({"accent": "#00ff00"})
    assert "#00ff00" in bridge.renderMarkdown("a `b` c")
    bridge.shutdown()


def test_reopening_a_chat_keeps_sent_context_on_the_user_turn(tmp_path):
    bridge = controller(tmp_path)
    task = bridge.store.create_conversation("With context", "local:test")
    history = ctx.build_messages([
        ctx.make(ctx.FILE, "main.py", path="/home/me/main.py", text="print(1)\n" * 50),
    ]) + [
        {"role": "user", "content": "What does this do?"},
        {"role": "assistant", "content": "It prints."},
    ]
    bridge.store.set_messages(task["id"], history, "local:test")
    bridge.openTask(task["id"])

    kinds = [item["kind"] for item in bridge.messages.items]
    assert kinds == ["user", "assistant"]
    assert bridge.messages.items[0]["attachments"][0]["title"] == "main.py"
    assert bridge.messages.items[0]["attachments"][0]["kind"] == ctx.FILE
    # The file body must not reappear as something the user typed.
    assert all("print(1)" not in item["body"] for item in bridge.messages.items)
    bridge.shutdown()


def test_branching_maps_view_rows_past_folded_groups(tmp_path):
    bridge = controller(tmp_path)
    task = bridge.store.create_conversation("Folded", "local:test")
    history = ctx.build_messages([ctx.make(ctx.FILE, "a.py", path="/a.py", text="x")]) + [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply one"},
        {"role": "tool", "tool_name": "screenshot", "content": '{"ok": true}'},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "reply two"},
    ]
    bridge.store.set_messages(task["id"], history, "local:test")
    bridge.openTask(task["id"])
    assert [item["kind"] for item in bridge.messages.items] == \
           ["user", "assistant", "activity", "user", "assistant"]

    bridge.branchFrom(1)  # the first assistant reply
    assert [m.get("content") for m in bridge._history][-2:] == ["first", "reply one"]
    bridge.shutdown()


def test_context_estimate_is_cached_rather_than_recomputed_per_token(tmp_path):
    bridge = controller(tmp_path)
    bridge._history = [{"role": "user", "content": "x" * 4000}]
    bridge._recount_history_tokens()
    cached = bridge.contextUsed
    assert cached > 0
    # Streaming emits `changed` constantly; reading the property must not walk
    # the whole conversation again.
    bridge._history.append({"role": "assistant", "content": "y" * 4000})
    assert bridge.contextUsed == cached
    bridge._recount_history_tokens()
    assert bridge.contextUsed > cached
    bridge.shutdown()


def test_a_nearly_full_context_window_is_flagged(tmp_path):
    bridge = controller(tmp_path)
    bridge._online = True
    bridge._model_capabilities = ["completion"]
    bridge._num_ctx = 2048
    bridge._history_tokens = 2000
    assert "nearly fills" in bridge.capabilityWarning
    bridge._history_tokens = 100
    assert "Choose a tool-capable model" in bridge.capabilityWarning
    bridge.shutdown()


def test_adjacent_chat_navigation_follows_the_sidebar_order(tmp_path):
    bridge = controller(tmp_path)
    made = [bridge.store.create_conversation(name) for name in ("First", "Second", "Third")]
    bridge.store.set_pinned(made[2]["id"], True)
    bridge._refresh_tasks()

    order = [item["id"] for group in bridge.taskGroups for item in group["items"]]
    assert order[0] == made[2]["id"]          # pinned first

    bridge.openAdjacentTask(1)                # nothing open yet
    assert bridge.taskId == order[0]
    bridge.openAdjacentTask(1)
    assert bridge.taskId == order[1]
    bridge.openAdjacentTask(-1)
    assert bridge.taskId == order[0]
    bridge.openAdjacentTask(-1)               # already at the top
    assert bridge.taskId == order[0]
    bridge.shutdown()


def test_recently_used_models_rank_above_the_rest(tmp_path):
    bridge = controller(tmp_path)
    bridge._catalog = [Controller._catalog_entry({"name": name, "size": 1})
                       for name in ("alpha", "beta", "gamma")]
    bridge._models = ["alpha", "beta", "gamma"]
    bridge.setModel("gamma")
    assert [entry["name"] for entry in bridge.modelCatalog][0] == "gamma"
    assert bridge.modelCatalog[0]["recent"] is True
    assert bridge.modelCatalog[1]["recent"] is False
    bridge.shutdown()


@pytest.mark.parametrize("text,expected", [
    ("Fix the retry loop", "Fix the retry loop"),
    ("What's wrong here?", "What's wrong here"),
    ("   spaced   out   words  ", "spaced out words"),
    ("", "New task"),
])
def test_short_prompts_become_their_own_title(text, expected):
    assert derive_title(text) == expected


def test_long_prompts_are_cut_on_a_word_boundary():
    title = derive_title("The daemon drops its connection after about 30 seconds and the CPU spikes")
    assert title.endswith("…")
    assert len(title) <= 53
    assert not title[:-1].endswith(" ")
    # Never mid-word.
    assert title[:-1].split()[-1] in "The daemon drops its connection after about 30 seconds and the".split()


def test_the_first_message_names_the_chat(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    bridge._online = True
    monkeypatch.setattr(bridge, "_start_run", lambda history: None)
    bridge.send("The daemon drops its connection after about 30 seconds and the CPU spikes")
    assert bridge.taskTitle.endswith("…")
    assert "and the C" not in bridge.taskTitle
    bridge.shutdown()


def _png(width, height, colour=(20, 20, 24)):
    import base64
    import io
    Image = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_region_capture_crops_an_image_wynxq_already_holds(tmp_path):
    desktop = IdleDesktop()
    bridge = controller(tmp_path, desktop=desktop)
    try:
        bridge.attachRegion()
        assert pump_until(lambda: bridge.regionActive)
        assert desktop.captures == ["screen"]
        assert bridge.regionWidth == 640 and bridge.regionHeight == 480

        # The capture is a stub without pixels, so give it real ones to crop.
        bridge._region = {"image": _png(200, 120), "width": 200, "height": 120}
        bridge.cropRegion(20, 10, 80, 60)
        assert bridge.attachmentCount == 1
        attachment = bridge.attachments[0]
        assert attachment["kind"] == "screenshot"
        assert (attachment["width"], attachment["height"]) == (80, 60)
        # Cropping consumes the capture: no stale screen image is kept around.
        assert bridge.regionActive is False
    finally:
        bridge.shutdown()


def test_a_tiny_or_cancelled_region_attaches_nothing(tmp_path):
    bridge = controller(tmp_path)
    try:
        bridge._region = {"image": _png(200, 120), "width": 200, "height": 120}
        bridge.cropRegion(0, 0, 2, 2)
        assert bridge.attachmentCount == 0
        assert bridge.regionActive is False

        bridge._region = {"image": _png(200, 120), "width": 200, "height": 120}
        bridge.cancelRegion()
        assert bridge.regionActive is False
        assert bridge.attachmentCount == 0
    finally:
        bridge.shutdown()


def test_a_region_outside_the_image_is_clamped(tmp_path):
    bridge = controller(tmp_path)
    try:
        bridge._region = {"image": _png(100, 100), "width": 100, "height": 100}
        bridge.cropRegion(60, 60, 400, 400)
        assert bridge.attachments[0]["width"] == 40
        assert bridge.attachments[0]["height"] == 40
    finally:
        bridge.shutdown()


def pump_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_search_looks_inside_messages_once_the_query_is_long_enough(tmp_path):
    bridge = controller(tmp_path)
    try:
        notes = bridge.store.create_conversation("Notes")
        other = bridge.store.create_conversation("Other")
        bridge.store.set_messages(notes["id"], [
            {"role": "user", "content": "remember the kubernetes migration"},
            {"role": "assistant", "content": "noted"},
        ])
        bridge.store.set_messages(other["id"], [{"role": "user", "content": "unrelated"}])
        bridge._refresh_tasks()

        # A word that appears only in an older message still finds the chat.
        bridge.setSearch("kubernetes")
        found = [item["id"] for group in bridge.taskGroups for item in group["items"]]
        assert found == [notes["id"]]

        # Below the threshold the search stays local to titles and previews.
        bridge.setSearch("ku")
        assert [item["id"] for group in bridge.taskGroups for item in group["items"]] == []

        bridge.setSearch("")
        assert len([i for g in bridge.taskGroups for i in g["items"]]) == 2
    finally:
        bridge.shutdown()


# ------------------------------------------------------------------- project
# The working folder was buried in the inspector; it is now the first thing the
# interface states, so it needs a name, a place and a way back.

def test_the_project_exposes_a_name_a_path_and_its_parent(tmp_path):
    bridge = controller(tmp_path)
    try:
        project = tmp_path / "code" / "wynxq-gui-ai-agent"
        project.mkdir(parents=True)
        bridge._set_project(str(project))

        assert bridge.projectName == "wynxq-gui-ai-agent"
        assert bridge.projectPath == str(project)
        assert bridge.projectLabel.endswith("code/wynxq-gui-ai-agent")
        # The parent line must not repeat the name shown above it.
        assert bridge.projectParentLabel.endswith("/code")
        assert "wynxq-gui-ai-agent" not in bridge.projectParentLabel

        bridge.clearProject()
        assert bridge.projectName == "" and bridge.projectLabel == ""
        assert bridge.projectParentLabel == ""
    finally:
        bridge.shutdown()


def test_recent_projects_are_remembered_most_recent_first(tmp_path):
    bridge = controller(tmp_path)
    try:
        first, second = tmp_path / "one", tmp_path / "two"
        first.mkdir()
        second.mkdir()
        bridge._set_project(str(first))
        bridge._set_project(str(second))

        # The folder you are in is not offered as somewhere to go.
        assert [entry["path"] for entry in bridge.recentProjects] == [str(first)]
        assert bridge.store.get_setting("recent_projects") == [str(second), str(first)]

        bridge.openProject(str(first))
        assert bridge.projectPath == str(first)
        assert [entry["name"] for entry in bridge.recentProjects] == ["two"]
    finally:
        bridge.shutdown()


def test_a_recent_project_that_moved_is_dropped_rather_than_opened(tmp_path):
    bridge = controller(tmp_path)
    try:
        gone = tmp_path / "gone"
        gone.mkdir()
        bridge._set_project(str(gone))
        bridge.clearProject()
        gone.rmdir()

        toasts = []
        bridge.toast.connect(toasts.append)
        bridge.openProject(str(gone))

        assert bridge.projectPath == ""
        assert bridge.store.get_setting("recent_projects") == []
        assert toasts and "no longer there" in toasts[0]
    finally:
        bridge.shutdown()


def test_the_recent_project_list_is_bounded(tmp_path):
    bridge = controller(tmp_path)
    try:
        for index in range(bridge.RECENT_PROJECT_LIMIT + 4):
            folder = tmp_path / f"p{index}"
            folder.mkdir()
            bridge._set_project(str(folder))
        assert len(bridge.store.get_setting("recent_projects")) == bridge.RECENT_PROJECT_LIMIT
    finally:
        bridge.shutdown()


# -------------------------------------------------------------- shell layout
def test_the_shell_remembers_how_it_was_left(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    bridge = Controller(store=store, desktop=IdleDesktop(), autoconnect=False)
    try:
        bridge.setSidebarWidth(320)
        bridge.setSidebarCollapsed(True)
        assert store.get_setting("sidebar_width") == 320
        assert store.get_setting("sidebar_collapsed") is True
    finally:
        bridge.shutdown()

    reopened = Controller(store=store, desktop=IdleDesktop(), autoconnect=False)
    try:
        assert reopened.sidebarWidth == 320
        assert reopened.sidebarCollapsed is True
    finally:
        reopened.shutdown()


def test_a_sidebar_width_outside_the_usable_range_is_clamped(tmp_path):
    bridge = controller(tmp_path)
    try:
        bridge.setSidebarWidth(10_000)
        assert bridge.sidebarWidth == 400
        bridge.setSidebarWidth(20)
        assert bridge.sidebarWidth == 200
        bridge.setSidebarWidth("not a number")
        assert bridge.sidebarWidth == 200
    finally:
        bridge.shutdown()


def test_embedding_only_models_are_flagged_out_of_the_quick_picker(tmp_path):
    """The composer's picker shows models you can talk to; the manager still
    lists everything Ollama has on disk."""
    bridge = controller(tmp_path)
    try:
        bridge._catalog = [Controller._catalog_entry({"name": name, "size": 1})
                           for name in ("chatty", "embedder")]
        bridge._catalog[1]["capabilities"] = ["embedding"]
        bridge._decorate_catalog()
        by_name = {entry["name"]: entry for entry in bridge.modelCatalog}
        assert by_name["chatty"]["chat"] is True
        assert by_name["embedder"]["chat"] is False
    finally:
        bridge.shutdown()


# ----------------------------------------------------------- wayland session
# Screen control is only usable day to day if the desktop stops asking, and
# only safe if it can be stopped from whatever window has focus.

def test_the_portal_restore_token_is_kept_with_the_other_settings(tmp_path):
    from wynxq.controller import _StoredTokens
    store = Store(tmp_path / "history.sqlite3")
    tokens = _StoredTokens(store)

    assert tokens.load() == ""
    tokens.save("first-token")
    assert store.get_setting("desktop_restore_token") == "first-token"
    # Single use: the next session's token replaces it rather than adding to it.
    tokens.save("second-token")
    assert tokens.load() == "second-token"
    tokens.clear()
    assert tokens.load() == ""


def test_a_global_stop_shortcut_reaches_the_running_task(tmp_path):
    """The shortcut fires on the portal's thread; the run may only be touched
    from the GUI thread, so it travels as a signal."""
    handlers = []

    class ShortcutDesktop(IdleDesktop):
        def set_stop_handler(self, handler):
            handlers.append(handler)

    bridge = controller(tmp_path, desktop=ShortcutDesktop(connected=True))
    try:
        assert handlers, "no stop handler was registered with the desktop"
        stopped = []
        bridge.stopRequested.connect(lambda: stopped.append(True))

        handlers[0]()          # As the portal would, from its own thread.
        APP.processEvents()
        assert stopped == [True]
    finally:
        bridge.shutdown()


def test_the_interface_reports_what_the_desktop_decided(tmp_path):
    class WaylandDesktop(IdleDesktop):
        def status(self):
            return {"connected": True, "available": True, "backend": "Wayland / Desktop portal",
                    "detail": "Connected", "remembered": True,
                    "stopShortcut": "Meta+Shift+X", "stopDetail": ""}

    bridge = controller(tmp_path, desktop=WaylandDesktop(connected=True))
    try:
        assert bridge.desktopRemembered is True
        # Whatever key the compositor chose, not the one Wynxq asked for.
        assert bridge.desktopStopShortcut == "Meta+Shift+X"
    finally:
        bridge.shutdown()


def test_a_desktop_without_those_features_reports_nothing_rather_than_guessing(tmp_path):
    bridge = controller(tmp_path, desktop=IdleDesktop(connected=True))
    try:
        assert bridge.desktopRemembered is False
        assert bridge.desktopStopShortcut == ""
    finally:
        bridge.shutdown()


def test_regenerate_cannot_repeat_a_local_command(tmp_path):
    bridge = controller(tmp_path)
    bridge._online = True
    task = bridge.store.create_conversation("Command", bridge.model)
    bridge._task_id = task["id"]
    bridge._history = [
        {"role": "user", "content": "Run a command"},
        {"role": "assistant", "tool_calls": [{"function": {"name": "run_command", "arguments": {"command": "echo hi"}}}]},
        {"role": "tool", "tool_name": "run_command", "content": "ok"},
        {"role": "assistant", "content": "Done"},
    ]
    assert bridge.canRegenerate is False
    before = list(bridge._history)
    bridge.regenerate()
    assert bridge._history == before and not bridge.busy
    bridge.shutdown()


def test_reopening_chat_keeps_command_output():
    from wynxq.controller import Messages
    import json
    model = Messages()
    model.replace([{"role": "tool", "tool_name": "run_command", "content": json.dumps({
        "ok": True, "command": "printf hello", "exit_code": 0, "output": "hello"})}])
    step = model.items[0]["steps"][0]
    assert step["summary"] == "Run printf hello"
    assert step["output"] == "hello"


def test_sent_image_context_stays_with_user_message_after_reload(tmp_path):
    bridge = controller(tmp_path)
    task = bridge.store.create_conversation("Image context", "local:test")
    history = ctx.build_messages([
        ctx.make(ctx.IMAGE, "clipboard.png", image="QUJD", width=32, height=24,
                 subtitle="32 × 24"),
    ]) + [{"role": "user", "content": "what is this?"}]
    bridge.store.set_messages(task["id"], history, "local:test")
    bridge.openTask(task["id"])
    assert [item["kind"] for item in bridge.messages.items] == ["user"]
    attached = bridge.messages.items[0]["attachments"]
    assert len(attached) == 1
    assert attached[0]["title"] == "clipboard.png"
    assert attached[0]["image"] == "QUJD"
    bridge.shutdown()


def test_builtin_browser_tool_routes_to_dock_without_system_browser(tmp_path):
    bridge = controller(tmp_path)
    routed = []
    bridge.browserNavigateRequested.disconnect()
    bridge.browserNavigateRequested.connect(routed.append)
    bridge.dock._browser_error = ""
    result = bridge._request_builtin_browser("youtube.com")
    if bridge.dock.browserAvailable:
        assert result["ok"] is True
        assert result["url"] == "https://youtube.com"
        assert routed == ["https://youtube.com"]
    else:
        assert result["ok"] is False
    bridge.shutdown()


def test_paste_image_returns_false_for_text_and_true_for_an_image(tmp_path, monkeypatch):
    import wynxq.controller as controller_module

    bridge = controller(tmp_path)

    class FakeImage:
        def __init__(self, empty):
            self.empty = empty

        def isNull(self):
            return self.empty

        def save(self, buffer, _format):
            buffer.write(b"\x89PNG fake clipboard image")
            return True

    class FakeClipboard:
        def __init__(self):
            self.image_value = FakeImage(True)

        def image(self):
            return self.image_value

    clipboard = FakeClipboard()

    class FakeGuiApplication:
        @staticmethod
        def clipboard():
            return clipboard

    monkeypatch.setattr(controller_module, "QGuiApplication", FakeGuiApplication)
    assert bridge.pasteImage() is False
    assert bridge.attachmentCount == 0

    clipboard.image_value = FakeImage(False)
    assert bridge.pasteImage() is True
    assert bridge.attachmentCount == 1
    assert bridge.attachments[0]["kind"] == ctx.IMAGE
    assert bridge.attachments[0]["image"]
    bridge.shutdown()
