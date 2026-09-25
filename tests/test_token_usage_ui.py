"""Composer usage stays compact; detailed accounting lives in Settings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "wynxq" / "ui" / "Wynxq"


def test_composer_keeps_usage_summary_next_to_run_controls():
    composer = (MODULE / "Composer.qml").read_text(encoding="utf-8")
    assert "TokenUsage {" in composer
    assert composer.index("TokenUsage {") < composer.index("ModelPicker {")
    assert "compact: root.tight" in composer


def test_composer_usage_is_informational_not_a_dashboard_or_button():
    qml = (MODULE / "TokenUsage.qml").read_text(encoding="utf-8")
    assert "bridge.liveTokenRate" in qml
    assert "bridge.liveTokenRateExact" in qml
    assert "bridge.conversationTokens" in qml
    assert "Accessible.StaticText" in qml
    assert "Popover {" not in qml
    assert "AbstractButton {" not in qml
    assert "bridge.tokenUsage" not in qml
    for period in ('"today"', '"week"', '"month"', '"allTime"'):
        assert period not in qml


def test_settings_owns_exact_period_usage():
    shell = (MODULE / "SettingsSheet.qml").read_text(encoding="utf-8")
    page = (MODULE / "SettingsUsagePage.qml").read_text(encoding="utf-8")
    assert "readonly property int usagePage" in shell
    assert 'label: "Usage", icon: "bolt"' in shell
    assert "bridge.refreshTokenUsage()" in shell
    assert "bridge.tokenUsage" in shell
    assert "bridge.conversationTokens" in page
    for label in ("Today usage", "Weekly", "Monthly", "Yearly", "All time"):
        assert label in page
    assert "Cached input is already part of input and is never counted twice" in page


def test_composer_does_not_send_while_real_ime_preedit_exists():
    composer = (MODULE / "Composer.qml").read_text(encoding="utf-8")
    guard = "input.preeditText.length > 0"
    assert guard in composer
    assert composer.index(guard) < composer.index("else root.send();")
    assert composer.index("else root.send();") < composer.index("event.accepted = true;")
    # Qt can leave inputMethodComposing true after real preedit has ended on
    # some Linux IME stacks; using it here would regress normal Enter-to-send.
    assert "input.inputMethodComposing" not in composer
