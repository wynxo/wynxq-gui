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
    for label in ("TODAY", "THIS WEEK", "THIS MONTH", "ALL TIME"):
        assert label in page
    assert "cached input is already part of input and is never counted twice" in page


def test_composer_does_not_send_while_ime_is_composing():
    composer = (MODULE / "Composer.qml").read_text(encoding="utf-8")
    assert composer.count("input.inputMethodComposing") >= 2
    assert composer.index("input.inputMethodComposing") < composer.index("root.send(); event.accepted = true;")
