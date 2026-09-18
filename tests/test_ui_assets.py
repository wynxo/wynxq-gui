"""The QML module must stay consistent: every declared type exists and loads."""
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

UI = Path(__file__).resolve().parents[1] / "wynxo" / "ui"
MODULE = UI / "Wynxo"


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


@pytest.mark.skipif(not os.environ.get("WYNXO_QML_SMOKE"), reason="needs a Qt platform plugin")
def test_the_interface_loads_headless():
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"}
    result = subprocess.run([sys.executable, "-m", "wynxo", "--smoke-test"],
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
    controller = (Path(__file__).resolve().parents[1] / "wynxo" / "controller.py").read_text()
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
    dock = (Path(__file__).resolve().parents[1] / "wynxo" / "dock.py").read_text(encoding="utf-8")
    assert "def suggest(self" in dock
    assert "if name not in TABS or self._tab_pinned:" in dock
    assert "@Slot" not in dock.split("def suggest(self")[0].rsplit("\n", 3)[-2]
    for path in list(MODULE.glob("*.qml")) + [UI / "Main.qml"]:
        assert ".suggest(" not in path.read_text(encoding="utf-8"), path.name


def test_the_dock_remembers_what_the_user_left_open():
    """Width, tab and visibility are the user's, so they survive a restart."""
    dock = (Path(__file__).resolve().parents[1] / "wynxo" / "dock.py").read_text(encoding="utf-8")
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
    for feature in ("DropArea", "attachPath", "Keys.onReturnPressed",
                    "Keys.onEnterPressed", "ShiftModifier", "pasteImage"):
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
