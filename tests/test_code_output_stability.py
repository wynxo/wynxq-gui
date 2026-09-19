"""Code output must stay byte-for-byte stable while the UI changes presentation."""
from pathlib import Path

from wynxq import markdown as md

ROOT = Path(__file__).resolve().parents[1]
CODE_BLOCK = ROOT / "wynxq" / "ui" / "Wynxq" / "CodeBlock.qml"


def test_streamed_fenced_code_keeps_exact_source_text():
    document = md.StreamingDocument()
    chunks = ["Before\n```python\n", "def greet(name):\n    return f\"hi {", "name}\"\n", "```\nAfter"]
    for chunk in chunks:
        document.append(chunk)

    blocks = document.finish()
    code = next(block for block in blocks if block["kind"] == md.CODE)
    assert code["language"] == "python"
    assert code["text"] == 'def greet(name):\n    return f"hi {name}"\n'
    assert blocks[0]["text"] == "Before"
    assert blocks[-1]["text"] == "After"


def test_partial_closing_fence_does_not_leak_into_code():
    document = md.StreamingDocument()
    document.append("```sh\nprintf '%s\\n' hello\n``")
    assert document.tail_kind == md.CODE
    assert document.tail.endswith("``")

    document.append("`\n")
    blocks = document.finish()
    assert len(blocks) == 1
    assert blocks[0]["kind"] == md.CODE
    assert blocks[0]["text"] == "printf '%s\\n' hello\n"


def test_code_ui_uses_separate_streaming_and_final_text_documents():
    text = CODE_BLOCK.read_text(encoding="utf-8")
    assert "sourceComponent: root.streaming ? streamingCode : finalizedCode" in text
    assert "textFormat: TextEdit.PlainText" in text
    assert "textFormat: TextEdit.RichText" in text
    assert "onPaletteChanged" in text
    # Display highlighting must never replace the raw source used by actions.
    assert "bridge.copyText(root.code)" in text
    assert "bridge.saveCode(root.code, root.language)" in text
    assert "bridge.copyAndOpenTerminal(root.code)" in text
