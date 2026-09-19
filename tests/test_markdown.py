"""Message segmentation, highlighting, and Markdown rendering."""
import pytest

from wynxq import markdown as md


def test_segment_splits_prose_and_fenced_code():
    blocks = md.segment("Intro line\n\n```python\nprint(1)\n```\n\nOutro")
    assert [block["kind"] for block in blocks] == [md.MARKDOWN, md.CODE, md.MARKDOWN]
    assert blocks[0]["text"] == "Intro line"
    assert blocks[1]["text"] == "print(1)\n"
    assert blocks[1]["language"] == "python"
    assert blocks[1]["label"] == "Python"
    assert blocks[2]["text"] == "Outro"


def test_streaming_matches_a_single_pass():
    text = "One\n\n```sh\nls -la\necho hi\n```\n\nTwo\n\n```\nplain\n```\n"
    document = md.StreamingDocument()
    for index in range(0, len(text), 3):
        document.append(text[index:index + 3])
    assert document.finish() == md.segment(text)


def test_closed_blocks_are_frozen_while_the_tail_streams():
    document = md.StreamingDocument()
    document.append("Hello\n\n```python\ndef f():\n")
    assert [block["kind"] for block in document.blocks] == [md.MARKDOWN]
    assert document.tail_kind == md.CODE
    assert document.tail_language == "python"
    frozen = document.blocks
    document.append("    return 1\n")
    # Appending inside an open block must not disturb what is already closed.
    assert document.blocks == frozen
    assert "return 1" in document.tail


def test_unterminated_fence_still_yields_a_code_block():
    blocks = md.segment("Before\n\n```js\nconst a = 1;")
    assert [block["kind"] for block in blocks] == [md.MARKDOWN, md.CODE]
    assert blocks[1]["language"] == "js"
    assert blocks[1]["label"] == "JavaScript"


def test_tilde_fences_and_longer_markers():
    blocks = md.segment("~~~python\nx = 1\n~~~\n")
    assert blocks[0]["kind"] == md.CODE
    inner = md.segment("````\n```\nnested\n```\n````\n")
    assert inner[0]["kind"] == md.CODE
    assert "nested" in inner[0]["text"]


@pytest.mark.parametrize("tag,expected", [
    ("py", "python"), ("PYTHON", "python"), ("bash", "shell"), ("c++", "cpp"),
    ("ts", "typescript"), ("txt", ""), ("", ""), ("brainfuck", ""),
])
def test_language_normalisation(tag, expected):
    assert md.normalise_language(tag) == expected


def test_shell_blocks_are_the_only_ones_offered_to_a_terminal():
    assert md.segment("```bash\nls\n```")[0]["runnable"] is True
    assert md.segment("```python\nimport os\n```")[0]["runnable"] is False


def test_highlight_escapes_markup_and_colours_tokens():
    out = md.highlight('x = "<script>"  # note', "python")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert md.DEFAULT_PALETTE["comment"] in out
    assert md.DEFAULT_PALETTE["string"] in out


def test_highlight_uses_the_supplied_palette_and_preserves_indentation():
    out = md.highlight("def f():\n    return 1", "python", {"keyword": "#ff0000"})
    assert "#ff0000" in out
    assert out.count("&nbsp;") >= 4
    assert "<br/>" in out


def test_highlight_of_an_unknown_language_is_plain_but_safe():
    out = md.highlight("<b>hi</b>", "unknownlang")
    assert "&lt;b&gt;" in out


def test_to_html_renders_headings_lists_tables_and_quotes():
    html = md.to_html("# Title\n\n- one\n- two\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n> quoted\n")
    assert "font-size:20px" in html
    assert "<ul" in html and html.count("<li") == 2
    assert "<table" in html and "<th" in html
    assert "quoted" in html


def test_to_html_escapes_untrusted_content():
    html = md.to_html("<img src=x onerror=alert(1)>")
    assert "onerror" not in html or "&lt;img" in html
    assert "<img" not in html


def test_to_html_marks_up_inline_constructs():
    html = md.to_html("A **bold** and `code` and [link](https://example.test).")
    assert "<b>bold</b>" in html
    assert "<code" in html
    assert 'href="https://example.test"' in html


def test_to_html_never_returns_an_empty_document():
    assert md.to_html("") .endswith("</div>")
    assert "&nbsp;" in md.to_html("")


def test_code_blocks_helper_returns_only_code():
    blocks = md.code_blocks("text\n```py\na=1\n```\nmore\n```sh\nls\n```")
    assert [block["language"] for block in blocks] == ["py", "sh"]
