# Architecture

Wynxq keeps one stable Qt/QML facade while pushing implementation into focused,
testable layers. The rule is simple: **UI facades coordinate; policy and services
do the work.**

## Dependency direction

```text
QML
 │
 ▼
WorkspaceController / Controller / DockController   ← Qt-facing facades
 │                    │
 │                    ├─ controller_*_ops.py        ← conversation/app behavior slices
 │                    └─ dock_*_ops.py              ← workspace-panel behavior slices
 │
 ├─ planning.py / endpoint_policy.py / workspace_checkpoint.py
 │                                                   ← product policy, Qt-free
 ├─ engine.py                                        ← agent/tool loop, Qt-free
 │    └─ ollama.py                                   ← HTTP/model transport, Qt-free
 └─ storage / context / commands / desktop / project services
```

## Boundaries

- `controller.py` is the public QML bridge. It owns Qt signals, exposed properties,
  construction, and shared state. Operational methods are bound from focused
  `controller_*_ops.py` modules so the public API stays stable without a god-file.
- `workspace.py` adds Chat/Work product state. Filesystem checkpointing, planning,
  and endpoint validation live outside it.
- `engine.py` owns the bounded tool loop only. It does not own HTTP transport or Qt.
- `ollama.py` owns Ollama HTTP, model management, streaming, and endpoint validation.
  Endpoint policy is injectable through the client class instead of monkey-patching
  engine globals.
- `dock.py` owns QML-facing workspace state/properties. Files, Terminal, Git,
  Context/Activity, Browser/Preview, and layout operations live in separate slices.
- `endpoint_policy.py`, `workspace_checkpoint.py`, `planning.py`, and `ollama.py`
  must remain Qt-free.

## Compatibility strategy

The facades deliberately keep their historic public names. Existing Python callers
and QML continue to call `bridge.send()`, `bridge.newTask()`, `bridge.dock.openFile()`,
and the same properties as before. Refactors move implementations, not contracts.

Likewise, `engine.py` re-exports its Ollama transport names and the coordinator
modules re-export selected legacy helpers where tests or external callers already
rely on them.

## Growth rules

Architecture tests enforce line budgets for coordinator modules and behavior slices.
When a budget is reached, add a focused module instead of raising the limit unless
there is a strong structural reason. New policy modules should prefer pure Python
and explicit dependency injection. Avoid runtime monkey-patching, cross-facade
imports, and hidden global state.

A useful test for placement is: **could this code run without Qt?** If yes, it
usually does not belong in a Qt controller.

## Concurrency ownership

- GUI state is mutated on the Qt thread.
- Controller background work uses `Job` and returns through signals.
- The engine and Ollama transport are Qt-free and receive cancellation/events as
  normal Python objects/callbacks.
- Dock shell IO uses the socket notifier; Git/file work uses dock workers.
- Per-task agent runs keep their own session state so switching conversations does
  not redirect an in-flight run into another task.

## Safety ownership

- Endpoint syntax/host policy: `ollama.py` + `endpoint_policy.py`.
- Tool schema/risk policy: `agent_tools.py`.
- Permission UI/session decisions: controller permission operations.
- Desktop backend authorization/input: `desktop.py` and backend modules.
- Project path containment: project/file service modules.
- Work-mode undo/checkpoint conflict detection: `workspace_checkpoint.py`.

These boundaries are intentional security boundaries as well as maintainability
boundaries; moving them should require corresponding architecture tests.
