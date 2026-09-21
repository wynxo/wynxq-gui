"""Model decisions are validated; no regex supplies personal facts or answers."""
import threading

import pytest

from wynxq.memory import Memory
from wynxq.memory_learning import validate_analysis, note_id
from wynxq.memory_service import MemoryService
from wynxq.storage import Store
from wynxq.ollama import Cancelled, OllamaClient, OllamaError


def decision(note, evidence, scope='global', replaces=(), action='save'):
    return {'action': action, 'scope': scope, 'note': note, 'evidence': evidence, 'replaces': list(replaces)}


class Model:
    """Scripted transport, not a pretend validation of actual model intelligence."""
    def __init__(self, changes=(), queries=(), select=None):
        self.changes, self.queries, self.select = list(changes), list(queries), select
        self.requests = []

    def memory_json(self, model, system, data, schema, **kwargs):
        self.requests.append(data)
        if 'latest_user_message' in data and 'existing_memories' in data:
            return {'changes': self.changes, 'queries': self.queries}
        rows = data['candidates']
        return {'ids': self.select(rows) if self.select else [row['id'] for row in rows]}


def service(tmp_path, client, enabled=lambda: True, reference=lambda: True):
    memory = Memory(tmp_path / 'memory.md')
    store = Store(tmp_path / 'history.sqlite3')
    return MemoryService(client, memory, store, 'current', memory_enabled=enabled, history_enabled=reference)


def run(svc, text, **kwargs):
    return svc.prepare([{'role': 'user', 'content': text}], 'local:test', '',
                       kwargs.get('cancel', threading.Event()), kwargs.get('emit', lambda event: None))


def test_arbitrary_model_fact_is_saved_and_reused_after_restart(tmp_path):
    text = 'The humming from fluorescent lights ruins my concentration, so I study by the window.'
    fact = 'User studies by the window because fluorescent-light noise disrupts concentration.'
    client = Model([decision(fact, text)])
    svc = service(tmp_path, client)
    remembered, _ = run(svc, text)
    assert fact in remembered
    svc.store.close()

    # New process/service and new chat, with a paraphrased question.
    other = service(tmp_path, Model(queries=['study environment concentration']))
    remembered, _ = run(other, 'Where should I put my desk?')
    assert fact in remembered
    assert other.memory.notes() == [fact]
    other.store.close()


def test_model_updates_or_deletes_exact_notes_without_subject_specific_rules(tmp_path):
    old = 'User is rehearsing for a stage production.'
    new = 'User has finished the stage production and is training for auditions.'
    source = 'The show ended. Auditions are my focus now.'
    client = Model([decision(new, source, replaces=[note_id('global', old)])])
    svc = service(tmp_path, client)
    svc.memory.remember(old)
    run(svc, source)
    assert svc.memory.notes() == [new]
    client.changes = [decision('', 'forget my theatre plans', replaces=[note_id('global', new)], action='delete')]
    run(svc, 'forget my theatre plans')
    assert svc.memory.notes() == []
    svc.store.close()


def test_ungrounded_unknown_and_wrong_scope_edits_are_rejected():
    existing = [{'id': 'one', 'scope': 'global', 'note': 'Existing fact'}]
    data = {'queries': [], 'changes': [
        decision('invented', 'never said this'),
        decision('invented', 'hello', replaces=['unknown']),
        decision('project fact', 'hello', scope='project', replaces=['one']),
        decision('password: abc', 'hello'),
    ]}
    assert validate_analysis(data, 'hello', existing, '/project')[0] == []


def test_memory_off_does_not_write_or_inject_facts(tmp_path):
    client = Model([decision('A new fact', 'hello')])
    svc = service(tmp_path, client, enabled=lambda: False, reference=lambda: False)
    svc.memory.remember('Existing fact')
    assert run(svc, 'hello') == ('', '')
    assert client.requests == []
    assert svc.memory.notes() == ['Existing fact']
    svc.store.close()


@pytest.mark.parametrize('text', [
    'hi', 'hey bro', 'thanks', 'привет', 'hallo', '👍',
])
def test_small_talk_skips_automatic_memory_work(tmp_path, text):
    client = Model([decision('Should never be written', text)])
    svc = service(tmp_path, client)
    svc.memory.remember('Existing durable fact')
    events = []
    assert run(svc, text, emit=events.append) == ('', '')
    assert client.requests == []
    assert events == []
    assert svc.memory.notes() == ['Existing durable fact']
    svc.store.close()


def test_memory_preparation_does_not_replace_visible_run_status(tmp_path):
    source = 'I prefer working in a quiet room.'
    client = Model([decision('User prefers working in a quiet room.', source)])
    svc = service(tmp_path, client, reference=lambda: False)
    events = []
    run(svc, source, emit=events.append)
    assert not any(event.get('type') == 'status' for event in events)
    svc.store.close()


def test_toggle_off_or_clear_during_inference_cannot_restore_memory(tmp_path):
    flags = {'enabled': True}
    source = 'I moved my desk beside the window.'
    client = Model([decision('User moved their desk beside the window.', source)])
    svc = service(tmp_path, client, enabled=lambda: flags['enabled'], reference=lambda: False)
    original = client.memory_json
    def disabling(*args, **kwargs):
        flags['enabled'] = False
        return original(*args, **kwargs)
    client.memory_json = disabling
    assert run(svc, source) == ('', '')
    assert svc.memory.notes() == []
    svc.store.close()


def test_cancelled_memory_request_never_writes(tmp_path):
    cancel = threading.Event()
    source = 'I always study with the window open.'
    class Cancelling(Model):
        def memory_json(self, *args, **kwargs):
            cancel.set()
            return super().memory_json(*args, **kwargs)
    svc = service(tmp_path, Cancelling([decision('User studies with the window open.', source)]))
    with pytest.raises(Cancelled):
        run(svc, source, cancel=cancel)
    assert svc.memory.notes() == []
    svc.store.close()


def test_bad_model_json_is_reported_and_existing_memory_is_kept(tmp_path):
    class Broken(Model):
        def memory_json(self, *args, **kwargs):
            raise OllamaError('Invalid JSON')
    svc = service(tmp_path, Broken())
    svc.memory.remember('Previously saved fact')
    events = []
    remembered, _ = run(svc, 'What setup did I tell you I use?', emit=events.append)
    assert 'Previously saved fact' in remembered
    assert any(event['type'] == 'memory_warning' for event in events)
    svc.store.close()


def test_semantic_selection_can_choose_an_excerpt_without_shared_words(tmp_path):
    text = 'The train rattles so much that reading gives me nausea.'
    client = Model(select=lambda rows: [row['id'] for row in rows if text in row['text']])
    svc = service(tmp_path, client)
    old = svc.store.create_conversation('Commute')
    svc.store.set_messages(old['id'], [{'role': 'user', 'content': text}])
    _, recalled = run(svc, 'Why do I prefer audiobooks on journeys?')
    assert text in recalled
    svc.store.close()


def test_model_search_expansion_reaches_old_conversations_and_early_messages(tmp_path):
    client = Model(queries=['orchid greenhouse humidity'])
    svc = service(tmp_path, client)
    old = svc.store.create_conversation('Old gardening')
    fact = 'My orchid greenhouse needs constant humidity.'
    svc.store.set_messages(old['id'], [{'role': 'user', 'content': fact}] +
                           [{'role': 'user', 'content': f'Unrelated item {i}'} for i in range(30)])
    for i in range(85):
        chat = svc.store.create_conversation(f'Later {i}')
        svc.store.set_messages(chat['id'], [{'role': 'user', 'content': 'Other conversation'}])
    _, recalled = run(svc, 'What environment do my tropical flowers require?')
    assert fact in recalled
    svc.store.close()


def test_structured_transport_sends_no_tools_and_validates_json(monkeypatch):
    client = OllamaClient()
    captured = []
    def stream(payload, cancel):
        captured.append(payload)
        yield {'message': {'content': '{"changes": [], "queries": []}'}}
    monkeypatch.setattr(client, 'stream_chat', stream)
    result = client.memory_json('local:test', 'system', {'source': 'text'}, {'type': 'object'})
    assert result == {'changes': [], 'queries': []}
    assert 'tools' not in captured[0]
    assert captured[0]['think'] is False
    assert captured[0]['format'] == {'type': 'object'}


def test_actual_chat_controller_runs_memory_inference_and_passes_it_to_next_chat(tmp_path, monkeypatch):
    import time
    from PySide6.QtCore import QCoreApplication
    from wynxq.product import ProductController
    from test_multi_runtime import IdleDesktop

    app = QCoreApplication.instance() or QCoreApplication([])
    text = 'The downstairs workshop is shared with my cousin, so evening noise is a problem.'
    note = 'User shares a downstairs workshop with their cousin and needs quiet evenings.'

    class Client(Model):
        endpoint = 'http://127.0.0.1:11434'
        def capabilities(self, model):
            return ['completion']
        def stream_chat(self, payload, cancel):
            self.answers.append(payload)
            yield {'message': {'content': 'Acknowledged.'}, 'done': True}

    client = Client([decision(note, text)])
    client.answers = []
    bridge = ProductController(store=Store(tmp_path / 'history.sqlite3'),
                               memory=Memory(tmp_path / 'memory.md'),
                               desktop=IdleDesktop(), autoconnect=False)
    monkeypatch.setattr(bridge, '_ollama_client', lambda endpoint: client)
    monkeypatch.setattr(bridge, '_maybe_generate_task_title', lambda *args: None)
    bridge._online = True
    bridge._model_capabilities = ['completion']

    def settle():
        deadline = time.monotonic() + 4
        while bridge.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert not bridge.busy

    bridge.send(text)
    settle()
    assert bridge.taskMode == 'chat'
    assert note in bridge.memory.notes()
    assert client.requests[0]['latest_user_message'] == text
    client.changes = []
    bridge.newTaskMode('chat')
    bridge.send('When would it be considerate to use my noisy tools?')
    settle()
    assert note in client.answers[-1]['messages'][0]['content']
    assert not client.answers[-1].get('tools')
    bridge.shutdown()


def test_clearing_memory_during_model_analysis_discards_stale_write(tmp_path):
    client = Model([decision('New detail', 'a new detail')])
    svc = service(tmp_path, client, reference=lambda: False)
    svc.memory.remember('Existing detail')
    original = client.memory_json
    def clear(*args, **kwargs):
        svc.memory.clear()
        return original(*args, **kwargs)
    client.memory_json = clear
    events = []
    run(svc, 'a new detail', emit=events.append)
    assert svc.memory.notes() == []
    assert any(event['type'] == 'memory_warning' for event in events)
    svc.store.close()


def test_project_memory_is_not_sent_to_other_projects(tmp_path):
    client = Model()
    svc = service(tmp_path, client, reference=lambda: False)
    svc.memory.remember('Project A private convention', 'project', '/a')
    svc.prepare([{'role': 'user', 'content': 'How do we build this?'}], 'local:test', '/b',
                threading.Event(), lambda event: None)
    assert 'Project A private convention' not in str(client.requests)
    svc.store.close()


def test_opt_out_is_decided_by_model_without_falling_back_to_phrase_rules(tmp_path):
    svc = service(tmp_path, Model())
    run(svc, 'Keep this out of your long-term notes: I have moved to Vienna.')
    assert svc.memory.notes() == []
    assert svc.client.requests  # The request reached the model; no regex extracted it.
    svc.store.close()


def test_reference_resolution_uses_immediately_preceding_dialogue(tmp_path):
    svc = service(tmp_path, Model())
    history = [
        {'role': 'user', 'content': 'An earlier topic'},
        {'role': 'assistant', 'content': 'An earlier answer'},
        {'role': 'user', 'content': 'I want to learn woodworking'},
        {'role': 'assistant', 'content': 'Would a weekend workshop suit you?'},
        {'role': 'user', 'content': 'Yes, that is my plan'},
    ]
    svc.prepare(history, 'local:test', '', threading.Event(), lambda event: None)
    assert svc.client.requests[0]['recent_dialogue'] == history[2:4]
    svc.store.close()


def test_history_edited_during_selection_is_not_recalled(tmp_path):
    client = Model()
    svc = service(tmp_path, client)
    chat = svc.store.create_conversation('Travel plans')
    svc.store.set_messages(chat['id'], [{'role': 'user', 'content': 'I am travelling to Prague'}])
    original = client.memory_json
    def editing(model, system, data, schema, **kwargs):
        response = original(model, system, data, schema, **kwargs)
        if 'candidates' in data:
            svc.store.set_messages(chat['id'], [{'role': 'user', 'content': 'Plans removed'}])
        return response
    client.memory_json = editing
    _, recalled = run(svc, 'Where am I travelling?')
    assert not recalled
    svc.store.close()


def test_conflicting_model_edits_to_the_same_saved_fact_fail_closed():
    old = "User works from a standing desk."
    ident = note_id("global", old)
    existing = [{"id": ident, "scope": "global", "note": old}]
    source = "I changed my desk setup today."
    data = {
        "queries": [],
        "changes": [
            decision("User now works from a sitting desk.", source, replaces=[ident]),
            decision("User now works from a treadmill desk.", source, replaces=[ident]),
        ],
    }

    changes, _ = validate_analysis(data, source, existing, "")

    assert changes == []
