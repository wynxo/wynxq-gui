from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "wynxq" / "ui" / "Wynxq"


def source(name: str) -> str:
    return (QML / name).read_text(encoding="utf-8")


def test_plan_components_are_registered():
    qmldir = source("qmldir")
    assert "PlanPanel 1.0 PlanPanel.qml" in qmldir
    assert "PlanTaskRow 1.0 PlanTaskRow.qml" in qmldir


def test_plan_is_agent_authored_and_persisted_workspace_state():
    plan = source("PlanPanel.qml")
    workspace = (ROOT / "wynxq" / "workspace.py").read_text(encoding="utf-8")
    session = (ROOT / "wynxq" / "workspace_session_ops.py").read_text(encoding="utf-8")
    run_ops = (ROOT / "wynxq" / "workspace_run_ops.py").read_text(encoding="utf-8")
    combined = workspace + session + run_ops
    assert "bridge.planSteps" in plan
    assert '"update_plan"' in combined
    assert "task_plan:" in session
    assert "_saved_plan" in session
    assert "_persist_plan" in session
    assert "derive_title" not in plan
    assert "bridge.messageModel" not in plan


def test_plan_tool_is_low_risk_and_not_desktop_activity():
    session = (ROOT / "wynxq" / "workspace_session_ops.py").read_text(encoding="utf-8")
    run_ops = (ROOT / "wynxq" / "workspace_run_ops.py").read_text(encoding="utf-8")
    planning = (ROOT / "wynxq" / "planning.py").read_text(encoding="utf-8")
    assert 'engine_module._NONVISUAL.add("update_plan")' in planning
    assert 'engine_module.LOW_RISK.add("update_plan")' in planning
    assert 'event.get("name") == "update_plan"' in run_ops
    assert "_strip_plan_history" in session


def test_plan_row_exposes_agent_plan_states():
    row = source("PlanTaskRow.qml")
    for label in ("Completed", "Running", "Failed", "Skipped", "Pending"):
        assert label in row
    for state in ("completed", "in_progress", "failed", "skipped", "pending"):
        assert state in row
    assert "Theme.stateColor" in row
    assert "StatusDot" in row


def test_workspace_auto_opens_from_an_explicit_multistep_plan():
    dock = source("WorkspaceDock.qml")
    assert "userSelectedWorkspaceTab" in dock
    assert "onPlanChanged" in dock
    assert "bridge.planSteps" in dock
    assert "steps.length >= 2" in dock
    assert "root.planSelected = true" in dock
    assert "root.dock.setVisible(true)" in dock
    assert "if (!bridge || !root.dock || root.userSelectedWorkspaceTab)" in dock


def test_manual_workspace_choice_resets_when_task_changes():
    dock = source("WorkspaceDock.qml")
    assert "observedTaskId" in dock
    assert "taskId !== root.observedTaskId" in dock
    assert "root.userSelectedWorkspaceTab = false" in dock
    assert "root.planSelected = false" in dock


def test_plan_rail_indicator_uses_plan_state_not_activity_count():
    rail = source("DockTabBar.qml")
    assert "bridge.planSteps.length >= 2" in rail
    assert "bridge.activity.length >= 2" not in rail


def test_shortcuts_and_header_respect_manual_workspace_choice():
    main = (ROOT / "wynxq" / "ui" / "Main.qml").read_text(encoding="utf-8")
    assert "dock.userSelectedWorkspaceTab = true" in main
    assert "drawerDock.userSelectedWorkspaceTab = true" in main
    assert "dock.pickWorkspaceTab(tab)" in main
    assert "drawerDock.planSelected = false" in main


def test_plan_and_activity_remain_separate_surfaces():
    dock = source("WorkspaceDock.qml")
    rail = source("DockTabBar.qml")
    assert "sourceComponent: PlanPanel {}" in dock
    assert "sourceComponent: ActivityPanel {}" in dock
    assert 'Accessible.name: "Plan"' in rail
    assert 'modelData.id === "activity"' in rail
