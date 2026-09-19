"""The QML module must stay consistent: every declared type exists and loads."""
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

UI = Path(__file__).resolve().parents[1] / "wynxq" / "ui"
MODULE = UI / "Wynxq"


def declared_types():
    types = {}
    for line in (MODULE / "qmldir").read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 4 and parts[0] == "singleton":
            types[parts[1]] = parts[3]
        elif len(parts) == 3 and parts[0] != "module":
            types[parts[0]] = parts[2]
    return types


def test_every_declared_type_has_a_file():
    for name, filename in declared_types().items():
        assert (MODULE / filename).is_file(), f"{name} points at a missing {filename}"


# Loaded by URL rather than declared as a module type, because its own imports
# are not available on every installation. Keep this list at one entry unless
# there is the same hard reason.
LAZY_FILES = {"BrowserView.qml"}


def test_every_component_file_is_declared():
    declared = set(declared_types().values())
    for path in MODULE.glob("*.qml"):
        if path.name in LAZY_FILES:
            continue
        assert path.name in declared, f"{path.name} is not listed in qmldir"


def test_the_lazy_files_are_lazy_for_a_reason():
    """A file kept out of qmldir must be loaded by URL and must be the reason
    it is: an import that a machine can legitimately not have. Otherwise it is
    just a component someone forgot to register."""
    for name in LAZY_FILES:
        text = (MODULE / name).read_text(encoding="utf-8")
        assert "import QtWebEngine" in text, f"{name} has no unavailable import to justify itself"
        loaders = [path.name for path in MODULE.glob("*.qml")
                   if f'Qt.resolvedUrl("{name}")' in path.read_text(encoding="utf-8")]
        assert loaders, f"{name} is not loaded by URL from anywhere"


def test_no_component_hard_codes_a_colour():
    """Colour belongs to Theme.qml; scattered hex values are the thing the
    redesign removed, so keep them out."""
    # Only assignments count; a hex string shown to the user (a placeholder in
    # the accent field, say) is content rather than a styling decision.
    hex_colour = re.compile(r'\b(color|ink|tone|tint|activeTint|fill|stroke|'
                            r'accentColor|foreground|background)\s*:\s*"#[0-9a-fA-F]{3,8}"')
    offenders = []
    for path in list(MODULE.glob("*.qml")) + [UI / "Main.qml"]:
        if path.name == "Theme.qml":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if hex_colour.search(line):
                offenders.append(f"{path.name}:{number}")
    assert offenders == [], "hard-coded colours: " + ", ".join(offenders)


def test_fonts_are_bundled_with_their_licences():
    fonts = {path.name for path in (UI / "fonts").glob("*.ttf")}
    assert "Inter-Regular.ttf" in fonts
    assert "JetBrainsMono-Regular.ttf" in fonts
    licences = {path.name for path in (UI / "fonts").glob("*LICENSE*")}
    assert len(licences) >= 2


def test_main_window_stays_usable_at_its_minimum_size():
    text = (UI / "Main.qml").read_text(encoding="utf-8")
    minimum_width = int(re.search(r"minimumWidth:\s*(\d+)", text).group(1))
    minimum_height = int(re.search(r"minimumHeight:\s*(\d+)", text).group(1))
    assert minimum_width <= 600 and minimum_height <= 560


@pytest.mark.skipif(not os.environ.get("WYNXQ_QML_SMOKE"), reason="needs a Qt platform plugin")
def test_the_interface_loads_headless():
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"}
    result = subprocess.run([sys.executable, "-m", "wynxq", "--smoke-test"],
                            capture_output=True, text=True, timeout=120, env=environment)
    assert result.returncode == 0, result.stderr
    assert "failed to load" not in result.stderr


def test_the_theme_follows_the_bridge_by_binding_not_assignment():
    """A one-time assignment silently stops tracking; the preview runner and a
    live accent change both depend on this staying a binding."""
    text = (UI / "Main.qml").read_text(encoding="utf-8")
    assert 'Binding { target: Theme; property: "bridge"; value: bridge }' in text
    assert "Theme.bridge = bridge" not in text


def test_renderers_are_told_when_the_palette_changes():
    """Markdown and code are rendered in Python, so a theme change has to
    invalidate what is already on screen."""
    for name in ("Markdown.qml", "CodeBlock.qml"):
        text = (MODULE / name).read_text(encoding="utf-8")
        assert "onPaletteChanged" in text, f"{name} ignores palette changes"
    controller = (Path(__file__).resolve().parents[1] / "wynxq" / "controller.py").read_text()
    assert controller.count("self.paletteChanged.emit()") == 2


def test_interactive_components_carry_accessible_names():
    """A screen reader should not meet a wall of unnamed rectangles."""
    required = {
        "WButton.qml", "IconButton.qml", "Chip.qml", "Toggle.qml", "Segmented.qml",
        "Composer.qml", "WorkspaceSidebar.qml", "TaskRow.qml", "TaskHeader.qml",
        "UserMessage.qml", "AssistantMessage.qml", "RunActivity.qml", "Meter.qml",
        "ModelPicker.qml", "TaskStart.qml",
    }
    for name in sorted(required):
        text = (MODULE / name).read_text(encoding="utf-8")
        assert "Accessible." in text, f"{name} exposes nothing to assistive technology"


def test_status_is_never_carried_by_colour_alone():
    """Activity rows pair colour with an icon, a word and motion."""
    text = (MODULE / "RunActivity.qml").read_text(encoding="utf-8")
    for word in ('"waiting for you"', '"declined"', '"failed"', "modelData.icon", "pulsing:"):
        assert word in text


def test_reduced_motion_gates_every_behaviour_and_looping_animation():
    offenders = []
    for path in list(MODULE.glob("*.qml")) + [UI / "Main.qml"]:
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("Behavior on ") and "enabled:" not in line:
                window = " ".join(lines[number - 1:number + 2])
                if "enabled: !Theme.reducedMotion" not in window:
                    offenders.append(f"{path.name}:{number}")
            if stripped.startswith("SequentialAnimation on ") or stripped.startswith("RotationAnimator on "):
                window = " ".join(lines[number - 1:number + 4])
                if "reducedMotion" not in window and "animate" not in window:
                    offenders.append(f"{path.name}:{number}")
    assert offenders == [], "ungated animation: " + ", ".join(offenders)


# --------------------------------------------------------------- one home each
# The redesign's central claim is that every important action has exactly one
# obvious place. These tests fail when a concept starts leaking back into a
# second surface.

def components_using(needle: str) -> set[str]:
    return {path.name for path in list(MODULE.glob("*.qml")) + [UI / "Main.qml"]
            if needle in path.read_text(encoding="utf-8")}


def test_the_model_is_chosen_in_one_place():
    """Picking the current model belongs to the composer's picker; the manager
    is where you install and delete. Nothing else sets a model."""
    assert components_using("bridge.setModel(") == {"ModelPicker.qml", "ModelManager.qml"}


def test_attachments_have_one_canonical_view():
    """Context used to appear in the composer and again in the inspector. The
    quick bar is a separate window, so it keeps its own compact list."""
    assert components_using("bridge.attachments") == {"Composer.qml", "QuickBarContent.qml"}


def test_screen_control_is_turned_on_in_one_place():
    """The switch lives in Agent settings. The header and composer only report
    that it is on; the palette routes to the same slot."""
    assert components_using("bridge.toggleDesktop(") == {"SettingsSheet.qml", "Main.qml"}


def test_the_runtime_preset_is_not_scattered():
    assert components_using("bridge.applyRuntimePreset(") == {"ModelPicker.qml", "SettingsSheet.qml"}


def test_the_workspace_dock_is_a_tool_column_not_a_status_column():
    """The old inspector was a permanent third column of read-only status, and
    removing it was right. The dock replaces it with tools you work in — so
    each panel must do something, not merely report."""
    interactive = {
        "FileExplorer.qml": "openRequested",
        "FileViewer.qml": "saveFile",
        "TerminalPanel.qml": "sendTerminal",
        "ChangesPanel.qml": "openDiff",
        "ContextPanel.qml": "removeContext",
        "BrowserPanel.qml": "navigate",
    }
    for name, action in interactive.items():
        text = (MODULE / name).read_text(encoding="utf-8")
        assert action in text, f"{name} is read-only; it belongs in a popover, not the dock"


def test_the_dock_never_moves_the_panel_the_user_chose():
    """State changes must never move the UI the user chose. The old inspector
    picked its own tab from `bridge.busy`; nothing in QML may do that again —
    the visible tab comes from the dock, and only a user action sets it."""
    for path in MODULE.glob("*.qml"):
        text = path.read_text(encoding="utf-8")
        assert "autoTab" not in text and "chosenTab" not in text, path.name
    # `suggest` is the only path that may change the tab on the app's behalf,
    # it is not reachable from QML, and it refuses once the user has chosen.
    dock = (Path(__file__).resolve().parents[1] / "wynxq" / "dock.py").read_text(encoding="utf-8")
    assert "def suggest(self" in dock
    assert "if name not in TABS or self._tab_pinned:" in dock
    assert "@Slot" not in dock.split("def suggest(self")[0].rsplit("\n", 3)[-2]
    for path in list(MODULE.glob("*.qml")) + [UI / "Main.qml"]:
        assert ".suggest(" not in path.read_text(encoding="utf-8"), path.name


def test_the_dock_remembers_what_the_user_left_open():
    """Width, tab and visibility are the user's, so they survive a restart."""
    dock = (Path(__file__).resolve().parents[1] / "wynxq" / "dock.py").read_text(encoding="utf-8")
    for key in ("dock_visible", "dock_width", "dock_tab", "dock_tab_pinned"):
        assert f'"{key}"' in dock


def test_anchored_overlays_position_themselves_repeatably():
    """A popover that adjusts its own `x` drifts a little further off-screen
    every time it is opened; both surfaces derive it from `anchorX` instead."""
    for name in ("WMenu.qml", "Popover.qml"):
        text = (MODULE / name).read_text(encoding="utf-8")
        assert "property real anchorX" in text
        assert "var wanted = anchorX;" in text
    for name in ("TaskHeader.qml", "TaskRow.qml", "ModelPicker.qml"):
        text = (MODULE / name).read_text(encoding="utf-8")
        assert "anchorX:" in text, f"{name} positions an overlay without anchorX"


def test_explicitly_sized_popovers_place_using_their_rendered_height():
    """An explicit `height` may be much larger than implicitHeight. Edge
    placement must move the complete rendered popup, not only its implicit
    content estimate, or bottom-anchored detail surfaces get clipped."""
    text = (MODULE / "Popover.qml").read_text(encoding="utf-8")
    assert "var popupHeight = Math.max(Number(height) || 0, Number(implicitHeight) || 0);" in text
    assert "-popupHeight - gap" in text
    assert "below.y + popupHeight" in text


def test_the_composer_keeps_drag_and_drop_and_keyboard_send():
    text = (MODULE / "Composer.qml").read_text(encoding="utf-8")
    for feature in ("DropArea", "attachPath", "Keys.priority: Keys.BeforeItem",
                    "Keys.onReturnPressed", "Keys.onEnterPressed", "ShiftModifier", "pasteImage",
                    'sequence: "Return"', 'sequence: "Enter"', "root.keyboardSend()"):
        assert feature in text


def test_permanent_navigation_surfaces_stay_opaque():
    """Permanent shell chrome should be stable; material effects belong to transient UI."""
    sidebar = (MODULE / "WorkspaceSidebar.qml").read_text(encoding="utf-8")
    dock = (MODULE / "WorkspaceDock.qml").read_text(encoding="utf-8")
    assert "Permanent navigation is deliberately opaque" in sidebar
    assert "color: Theme.backgroundSoft" in sidebar
    assert "fillOpacity: 0.82" not in sidebar
    assert "permanent productivity surface" in dock
    assert "color: Theme.background" in dock


def test_hover_actions_remain_keyboard_reachable_without_layout_jitter():
    context = (MODULE / "ContextPanel.qml").read_text(encoding="utf-8")
    assert "id: removeButton" in context
    assert "visible: !!entry.modelData.removable" in context
    assert "opacity: hover.hovered || visualFocus ? 1 : 0" in context
    assert "removeButton.visualFocus" in context

    changes = (MODULE / "ChangesPanel.qml").read_text(encoding="utf-8")
    assert "opacity: change.hovered || more.visualFocus || changeMenu.opened ? 1 : 0" in changes
    assert "opacity: change.hovered || more.visualFocus || changeMenu.opened ? 0 : 1" in changes

    user = (MODULE / "UserMessage.qml").read_text(encoding="utf-8")
    assert "editAction.visualFocus" in user
    assert "copyAction.visualFocus" in user


def test_transient_quick_bar_uses_shared_material_and_scrollbar():
    text = (MODULE / "QuickBarContent.qml").read_text(encoding="utf-8")
    assert "GlassSurface {\n        id: shell" in text
    assert "font.pixelSize: Theme.title" in text
    assert "ScrollBar.vertical: WScrollBar {}" in text
    assert "sendButton.visualFocus" in text


def test_composer_image_actions_have_real_hit_targets_and_icons():
    text = (MODULE / "Composer.qml").read_text(encoding="utf-8")
    assert text.count("width: Theme.controlSmall; height: Theme.controlSmall") >= 2
    assert 'name: "close"' in text
    assert "imagePreviewHit.containsMouse || hovered || visualFocus" in text
    assert 'text: "×"' not in text


def test_activity_details_are_keyboard_expandable():
    text = (MODULE / "ActivityPanel.qml").read_text(encoding="utf-8")
    assert "activeFocusOnTab: event.hasDetail && !event.isTurn" in text
    assert "Keys.onReturnPressed" in text
    assert "Keys.onSpacePressed" in text
    assert "visible: event.activeFocus" in text


def test_composer_send_is_plain_circular_not_glass():
    text = (MODULE / "Composer.qml").read_text(encoding="utf-8")
    send = text.split("id: sendButton", 1)[1].split("DropArea", 1)[0]
    assert "background: Rectangle" in send
    assert "radius: width / 2" in send
    assert "GlassSurface" not in send


def test_fresh_task_shows_thirty_day_usage_grid():
    task = (MODULE / "TaskStart.qml").read_text(encoding="utf-8")
    heatmap = (MODULE / "UsageHeatmap.qml").read_text(encoding="utf-8")
    assert "UsageHeatmap {" in task
    assert "30-day activity" in heatmap
    assert "Theme.success" in heatmap
    assert "bridge.tokenUsageDays" in heatmap


def test_dock_rail_is_flat_and_hides_unused_plan():
    text = (MODULE / "DockTabBar.qml").read_text(encoding="utf-8")
    assert "background: GlassSurface" not in text
    assert "bridge.planSteps.length > 0" in text
    assert "Theme.surfaceSelected" in text


def test_ctrl_v_attaches_images_without_breaking_text_paste():
    text = (MODULE / "Composer.qml").read_text(encoding="utf-8")
    assert "Normal Ctrl+V remains normal text paste" in text
    assert "event.accepted = !!(bridge && bridge.pasteImage())" in text
    controller = (Path(__file__).resolve().parents[1] / "wynxq" / "controller.py").read_text()
    assert "@Slot(result=bool)\n    def pasteImage" in controller
    assert "if image.isNull():\n            return False" in controller
    assert "return self._attach_clipboard_png(image_png)" in controller
    assert "def _attach_clipboard_png" in controller


def test_sent_attachments_render_inside_the_user_turn():
    message = (MODULE / "UserMessage.qml").read_text(encoding="utf-8")
    listing = (MODULE / "MessageList.qml").read_text(encoding="utf-8")
    assert 'objectName: "sentAttachments"' in message
    assert "data:image/png;base64," in message
    assert "ContextKinds.icon(modelData.kind)" in message
    assert "attachments: rowItem.attachments" in listing


def test_activity_and_message_spacing_stays_compact():
    listing = (MODULE / "MessageList.qml").read_text(encoding="utf-8")
    activity = (MODULE / "RunActivity.qml").read_text(encoding="utf-8")
    assistant = (MODULE / "AssistantMessage.qml").read_text(encoding="utf-8")
    assert "spacing: Theme.s4" in listing
    assert "root.steps.length > 3 ? 24 : 0" in activity
    assert "stepColumn.implicitHeight + Theme.s1" in activity
    assert "height: 22" in assistant


def test_collapsed_side_surfaces_leave_only_restore_affordances():
    main = (UI / "Main.qml").read_text(encoding="utf-8")
    sidebar = (MODULE / "WorkspaceSidebar.qml").read_text(encoding="utf-8")
    dock = (MODULE / "WorkspaceDock.qml").read_text(encoding="utf-8")
    header = (MODULE / "TaskHeader.qml").read_text(encoding="utf-8")
    assert "sidebarCollapsed ? 0" in main
    assert 'objectName: "sidebarRestoreButton"' in main
    assert 'objectName: "dockRestoreButton"' in main
    assert "Collapsed state intentionally renders nothing" in sidebar
    assert "implicitWidth: panelOpen ? Theme.railWidth + panelWidth + 5 : 0" in dock
    assert "visible: root.panelOpen" in dock
    assert "visible: false // Collapsed navigation is restored" in header
    assert "visible: root.dockAvailable && root.dockOpen" in header


def test_motion_language_is_restrained_and_reduced_motion_aware():
    glyph = (MODULE / "ActivityGlyph.qml").read_text(encoding="utf-8")
    composer = (MODULE / "Composer.qml").read_text(encoding="utf-8")
    task = (MODULE / "TaskStart.qml").read_text(encoding="utf-8")
    messages = (MODULE / "MessageList.qml").read_text(encoding="utf-8")
    assert "Theme.success" in glyph
    assert "running: root.running && root.visible && !Theme.reducedMotion" in glyph
    assert "scale: down ? 0.90" in composer
    assert "function playEntrance()" in task
    assert "from: 0.985; to: 1" in task
    assert 'property: "scale"; from: 0.985; to: 1' in messages


def test_usage_activity_is_a_real_seven_row_contribution_grid():
    heatmap = (MODULE / "UsageHeatmap.qml").read_text(encoding="utf-8")
    assert "rows: 7" in heatmap
    assert "flow: Grid.TopToBottom" in heatmap
    assert 'text: "Less"' in heatmap
    assert 'text: "More"' in heatmap
    assert "Theme.success" in heatmap


def test_live_assistant_uses_the_activity_glyph():
    assistant = (MODULE / "AssistantMessage.qml").read_text(encoding="utf-8")
    header = (MODULE / "TaskHeader.qml").read_text(encoding="utf-8")
    assert "ActivityGlyph {" in assistant
    assert "Thinking through the task" in assistant
    assert "ActivityGlyph {" in header


def test_model_picker_pairs_server_and_model_per_chat():
    picker = (MODULE / "ModelPicker.qml").read_text(encoding="utf-8")
    assert 'SectionLabel { text: "Server" }' in picker
    assert "bridge.endpointProfiles" in picker
    assert "bridge.selectEndpoint(modelData.url)" in picker
    assert 'SectionLabel { text: "Model · " + (bridge ? bridge.endpointProfileName : "") }' in picker


def test_settings_manages_named_ollama_servers_without_reintroducing_global_only_runtime():
    settings = (MODULE / "SettingsSheet.qml").read_text(encoding="utf-8")
    assert 'title: "Ollama servers"' in settings
    assert "bridge.endpointProfiles" in settings
    assert "bridge.addEndpointProfile" in settings
    assert "bridge.setDefaultEndpoint" in settings
    assert "bridge.removeEndpointProfile" in settings
    assert "each existing chat remembers its own server and model" in settings


def test_sidebar_surfaces_background_generation_without_a_spinner():
    row = (MODULE / "TaskRow.qml").read_text(encoding="utf-8")
    assert "row.entry.running" in row
    assert "ActivityGlyph {" in row
    assert "row.entry.runStatus" in row


def test_contribution_grid_aligns_real_dates_to_weekday_rows():
    heatmap = (MODULE / "UsageHeatmap.qml").read_text(encoding="utf-8")
    assert "leadingBlanks" in heatmap
    assert "(day + 6) % 7" in heatmap
    assert "root.leadingBlanks + root.days.length" in heatmap
