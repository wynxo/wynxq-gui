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
 │                    ├─ workspace_*_ops.py         ← task/session/run product behavior
 │                    └─ dock_*_ops.py              ← workspace-panel behavior slices
 │
 ├─ planning.py / endpoint_policy.py / workspace_checkpoint.py
 │                                                   ← product policy, Qt-free
 ├─ agent_prompt.py / engine_support.py / tool_execution.py
 │                                                   ← run policy/helpers, Qt-free
 ├─ engine.py                                        ← bounded agent coordinator, Qt-free
 │    └─ ollama.py                                   ← HTTP/model transport, Qt-free
 └─ storage / context / commands / desktop / project services
```

## Boundaries

- `controller.py` is the public QML bridge. It owns Qt signals, exposed properties,
  construction, and shared state. Operational methods are bound from focused
  `controller_*_ops.py` modules so the public API stays stable without a god-file.
- `workspace.py` is the stable Chat/Work Qt facade. Session/draft/plan persistence,
  usage/project policy, task lifecycle, and run orchestration live in focused
  `workspace_*_ops.py` slices. Filesystem checkpointing, planning, and endpoint
  validation remain separate pure-policy modules.
- `engine.py` coordinates capabilities, tool exposure, model turns, cancellation, and
  the bounded action budget. It does not own prompt policy, concrete tool execution,
  transcript plumbing, HTTP transport, or Qt.
- `agent_prompt.py` owns Chat/Work system-prompt construction from already-resolved
  runtime capabilities.
- `engine_support.py` owns model-bound transcript shaping, screenshot-context retention,
  and reasoning-channel parsing.
- `tool_execution.py` owns validation, approval checks, concrete tool dispatch, and the
  evidence events produced by an executed action.
- `ollama.py` owns Ollama HTTP, model management, streaming, and endpoint validation.
  Endpoint policy is injectable through the client class instead of monkey-patching
  engine globals.
- `dock.py` owns QML-facing workspace state/properties. Files, Terminal, Git,
  Context/Activity, Browser/Preview, and layout operations live in separate slices.
- `SettingsSheet.qml` is only the settings navigation/shell. Each settings domain
  lives in a focused `Settings*Page.qml` component so unrelated settings do not
  share one giant declarative file.
- `desktop_backends.py` is a compatibility facade only. X11 lives in
  `desktop_x11.py`, portal control in `desktop_portal.py`, and emergency-stop
  bindings in `desktop_stop.py`.
- `endpoint_policy.py`, `workspace_checkpoint.py`, `planning.py`, `ollama.py`,
  `agent_prompt.py`, `engine_support.py`, and `tool_execution.py` must remain Qt-free.

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
- The engine, prompt policy, transcript helpers, tool executor, and Ollama transport
  are Qt-free and receive cancellation/events as normal Python objects/callbacks.
- Dock shell IO uses the socket notifier; Git/file work uses dock workers.
- Per-task agent runs keep their own session state so switching conversations does
  not redirect an in-flight run into another task.
- Active task IDs are journaled while runs are live. A hard restart never resumes
  tools automatically; it only repairs every persisted in-progress plan step back
  to pending and clears the stale journal.

## Safety ownership

- Endpoint syntax/host policy: `ollama.py` + `endpoint_policy.py`.
- Tool schema/risk policy: `agent_tools.py`.
- Per-call validation, approval enforcement, and dispatch: `tool_execution.py`.
- Permission UI/session decisions: controller permission operations.
- Desktop backend authorization/input: `desktop.py` and backend modules.
- Project path containment: project/file service modules.
- Work-mode undo/checkpoint conflict detection: `workspace_checkpoint.py`.

These boundaries are intentional security boundaries as well as maintainability
boundaries; moving them should require corresponding architecture tests.
