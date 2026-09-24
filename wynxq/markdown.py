"""Message segmentation and code highlighting.

Assistant text arrives as a token stream, so segmentation is incremental:
``StreamingDocument`` only ever touches the block that is still open, which
keeps rendering cost proportional to the tokens received rather than to the
length of the message. Highlighting runs once, when a code block closes.
"""
from __future__ import annotations

import html
import re

MARKDOWN = "markdown"
CODE = "code"

_FENCE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})\s*([^\s`]*)\s*$")

# Palette keys resolved by the caller so the UI theme stays the single source
# of truth for colour. Highlighting never invents its own hex values.
DEFAULT_PALETTE = {
    "text": "#d8d6d1",
    "keyword": "#c9a5f5",
    "string": "#9fd6ac",
    "number": "#e0b283",
    "comment": "#7b7974",
    "function": "#8fc4f0",
    "builtin": "#7fd0c8",
    "punctuation": "#8d8b87",
}

_KEYWORDS = {
    "python": """False None True and as assert async await break class continue def del elif else
        except finally for from global if import in is lambda nonlocal not or pass raise return try
        while with yield match case self cls""",
    "javascript": """async await break case catch class const continue debugger default delete do else
        export extends finally for from function get if import in instanceof let new of return set
        static super switch this throw try typeof var void while with yield null true false undefined""",
    "typescript": """abstract any as async await boolean break case catch class const continue declare
        default delete do else enum export extends finally for from function if implements import in
        interface let new number of private protected public readonly return static string super switch
        this throw try type typeof var void while yield null true false undefined never unknown""",
    "c": """auto break case char const continue default do double else enum extern float for goto if
        inline int long register restrict return short signed sizeof static struct switch typedef union
        unsigned void volatile while bool true false NULL""",
    "cpp": """alignas alignof auto bool break case catch char class const constexpr continue decltype
        default delete do double else enum explicit export extern false float for friend goto if inline
        int long mutable namespace new noexcept nullptr operator private protected public return short
        signed sizeof static struct switch template this throw true try typedef typename union unsigned
        using virtual void volatile while""",
    "java": """abstract assert boolean break byte case catch char class const continue default do double
        else enum extends final finally float for goto if implements import instanceof int interface long
        native new package private protected public return short static strictfp super switch synchronized
        this throw throws transient try void volatile while true false null var record sealed""",
    "go": """break case chan const continue default defer else fallthrough for func go goto if import
        interface map package range return select struct switch type var nil true false make new len cap
        append copy delete panic recover string int int64 float64 bool byte rune error""",
    "rust": """as async await break const continue crate dyn else enum extern false fn for if impl in let
        loop match mod move mut pub ref return self Self static struct super trait true type unsafe use
        where while Some None Ok Err Vec String Option Result""",
    "shell": """if then else elif fi for while do done case esac function return in select time until
        break continue local export readonly declare shift source alias unset trap set echo cd""",
    "sql": """select from where group by having order limit offset insert into values update set delete
        create table alter drop index view join inner left right outer full on as distinct union all and
        or not null primary key foreign references default constraint with returning case when then end""",
    "css": """important media supports keyframes import font-face charset namespace root
        and not only from to""",
    "yaml": "true false null yes no on off",
    "json": "true false null",
}

_ALIASES = {
    "py": "python", "python3": "python", "js": "javascript", "jsx": "javascript",
    "mjs": "javascript", "node": "javascript", "ts": "typescript", "tsx": "typescript",
    "sh": "shell", "bash": "shell", "zsh": "shell", "console": "shell", "shell-session": "shell",
    "c++": "cpp", "cc": "cpp", "h": "c", "hpp": "cpp", "golang": "go", "rs": "rust",
    "kt": "java", "kotlin": "java", "cs": "java", "csharp": "java", "postgres": "sql",
    "postgresql": "sql", "mysql": "sql", "sqlite": "sql", "yml": "yaml", "htm": "html",
    "xhtml": "html", "svg": "html", "xml": "html", "qml": "javascript", "scss": "css",
    "less": "css", "toml": "yaml", "ini": "yaml", "conf": "yaml", "cfg": "yaml",
    "text": "", "txt": "", "plain": "", "plaintext": "", "output": "", "": "",
}

_LINE_COMMENT = {
    "python": "#", "shell": "#", "yaml": "#", "javascript": "//", "typescript": "//",
    "c": "//", "cpp": "//", "java": "//", "go": "//", "rust": "//", "sql": "--", "css": "",
}

_BLOCK_COMMENT = {
    "javascript": ("/*", "*/"), "typescript": ("/*", "*/"), "c": ("/*", "*/"),
    "cpp": ("/*", "*/"), "java": ("/*", "*/"), "go": ("/*", "*/"), "rust": ("/*", "*/"),
    "css": ("/*", "*/"), "sql": ("/*", "*/"), "html": ("<!--", "-->"),
}

# Language names as shown on a code card; anything unknown keeps the raw tag.
DISPLAY_NAMES = {
    "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
    "shell": "Shell", "c": "C", "cpp": "C++", "java": "Java", "go": "Go", "rust": "Rust",
    "sql": "SQL", "css": "CSS", "html": "HTML", "json": "JSON", "yaml": "YAML",
}

# Shell snippets are the realistic "run this" case; everything else is offered
# as a save, never executed. Wynxq itself never runs code without the user.
RUNNABLE = {"shell"}


def normalise_language(tag: str) -> str:
    tag = str(tag or "").strip().lower()
    tag = tag.split(",")[0].strip()
    if tag in _ALIASES:
        return _ALIASES[tag]
    return tag if tag in _KEYWORDS or tag in ("html", "json") else ""


def display_language(tag: str) -> str:
    normalised = normalise_language(tag)
    if normalised:
        return DISPLAY_NAMES.get(normalised, normalised.title())
    raw = str(tag or "").strip()
    return raw[:24] if raw else "Text"


def _keyword_set(language: str) -> set[str]:
    return set(_KEYWORDS.get(language, "").split())


def _token_pattern(language: str) -> re.Pattern:
    parts = []
    block = _BLOCK_COMMENT.get(language)
    if block:
        parts.append(f"(?P<block>{re.escape(block[0])}.*?(?:{re.escape(block[1])}|$))")
    line = _LINE_COMMENT.get(language)
    if line:
        parts.append(f"(?P<line>{re.escape(line)}[^\\n]*)")
    if language == "python":
        parts.append(r"(?P<tstring>[rRbBfFuU]{0,2}(?:\"\"\"[\s\S]*?(?:\"\"\"|$)|'''[\s\S]*?(?:'''|$)))")
    parts.append(r"(?P<string>\"(?:\\.|[^\"\\\n])*\"?|'(?:\\.|[^'\\\n])*'?|`(?:\\.|[^`\\])*`?)")
    parts.append(r"(?P<number>\b(?:0[xXbBoO][0-9a-fA-F_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)\b)")
    parts.append(r"(?P<name>[A-Za-z_$][\w$]*)")
    parts.append(r"(?P<punct>[^\w\s])")
    return re.compile("|".join(parts), re.MULTILINE)


_PATTERNS: dict[str, re.Pattern] = {}


def highlight(code: str, language: str = "", palette: dict | None = None) -> str:
    """Return HTML for ``code``. Unknown languages fall back to plain escaping."""
    colors = {**DEFAULT_PALETTE, **(palette or {})}
    text = str(code)
    normalised = normalise_language(language)
    if not normalised or normalised == "html":
        escaped = html.escape(text).replace("\n", "<br/>").replace(" ", "&nbsp;")
        return f'<span style="color:{colors["text"]}">{escaped}</span>'
    if normalised not in _PATTERNS:
        _PATTERNS[normalised] = _token_pattern(normalised)
    pattern = _PATTERNS[normalised]
    keywords = _keyword_set(normalised)
    out: list[str] = []
    cursor = 0

    def escape(chunk: str) -> str:
        # Spaces become non-breaking so code keeps its indentation and scrolls
        # horizontally instead of reflowing mid-expression.
        return html.escape(chunk).replace("\n", "<br/>").replace(" ", "&nbsp;")

    def plain(chunk: str) -> None:
        if chunk:
            out.append(escape(chunk))

    def paint(chunk: str, color: str) -> None:
        out.append(f'<span style="color:{color}">{escape(chunk)}</span>')

    for match in pattern.finditer(text):
        plain(text[cursor:match.start()])
        cursor = match.end()
        kind = match.lastgroup
        chunk = match.group()
        if kind in ("block", "line"):
            paint(chunk, colors["comment"])
        elif kind in ("string", "tstring"):
            paint(chunk, colors["string"])
        elif kind == "number":
            paint(chunk, colors["number"])
        elif kind == "punct":
            paint(chunk, colors["punctuation"])
        elif kind == "name":
            if chunk in keywords:
                paint(chunk, colors["keyword"])
            elif text[cursor:cursor + 1] == "(":
                paint(chunk, colors["function"])
            elif chunk[:1].isupper():
                paint(chunk, colors["builtin"])
            else:
                plain(chunk)
        else:
            plain(chunk)
    plain(text[cursor:])
    return f'<span style="color:{colors["text"]}">{"".join(out)}</span>'


def _block(kind: str, text: str, language: str = "") -> dict:
    return {"kind": kind, "text": text, "language": language,
            "label": display_language(language) if kind == CODE else "",
            "runnable": kind == CODE and normalise_language(language) in RUNNABLE}


class StreamingDocument:
    """Split streamed assistant text into markdown and fenced code blocks.

    Only the open block is rewritten as tokens arrive; closed blocks are frozen
    so the view can render them once and leave them alone.
    """

    def __init__(self, text: str = ""):
        self._closed: list[dict] = []
        self._buffer = ""          # text of the block currently open
        self._pending = ""         # partial trailing line, not yet terminated
        self._fence = ""           # active fence marker, empty when in markdown
        self._language = ""
        if text:
            self.append(text)

    @property
    def blocks(self) -> list[dict]:
        return list(self._closed)

    @property
    def tail(self) -> str:
        text = self._buffer + self._pending
        return text if self._fence else text.strip("\n")

    @property
    def tail_kind(self) -> str:
        return CODE if self._fence else MARKDOWN

    @property
    def tail_language(self) -> str:
        return self._language

    @property
    def tail_label(self) -> str:
        return display_language(self._language) if self._fence else ""

    @property
    def tail_runnable(self) -> bool:
        return bool(self._fence) and normalise_language(self._language) in RUNNABLE

    def _close(self, kind: str, language: str = "") -> None:
        text = self._buffer if kind == CODE else self._buffer.strip("\n")
        if text.strip():
            self._closed.append(_block(kind, text, language))
        self._buffer = ""

    def append(self, text: str) -> None:
        if not text:
            return
        self._pending += str(text)
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._consume(line)

    def _consume(self, line: str) -> None:
        match = _FENCE.match(line)
        if self._fence:
            if match and match.group(2)[0] == self._fence[0] and len(match.group(2)) >= len(self._fence):
                self._close(CODE, self._language)
                self._fence, self._language = "", ""
            else:
                self._buffer += line + "\n"
            return
        if match:
            self._close(MARKDOWN)
            self._fence = match.group(2)
            self._language = match.group(3)
            return
        self._buffer += line + "\n"

    def finish(self) -> list[dict]:
        """Flush every open block; used once a message is complete."""
        if self._pending:
            self._consume(self._pending)
            self._pending = ""
        self._close(CODE if self._fence else MARKDOWN, self._language)
        self._fence, self._language = "", ""
        return self.blocks


def segment(text: str) -> list[dict]:
    """Segment a complete message. Equivalent to streaming it in one go."""
    document = StreamingDocument()
    document.append(str(text or ""))
    return document.finish()


def code_blocks(text: str) -> list[dict]:
    return [block for block in segment(text) if block["kind"] == CODE]


# ---------------------------------------------------------------- rendering
# Qt's built-in Markdown reader gives no control over block spacing, table
# borders or heading scale, and its output looks cramped next to the rest of
# the interface. Rendering to the HTML subset Qt's rich text engine supports
# lets typography follow the same design tokens as everything else.

_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)|(?<![_\w])_([^_\n]+)_(?!_)")
_STRIKE = re.compile(r"~~([^~]+)~~")
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_AUTOLINK = re.compile(r"(?<![\"'>=\w])(https?://[^\s<>\"')]+)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_UNORDERED = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")

HTML_PALETTE = {
    "text": "#f4f2ee",
    "muted": "#a5a29b",
    "faint": "#6d6b66",
    "accent": "#e9e3d6",
    "codeBackground": "#0a0a0b",
    "border": "#36363d",
    "rule": "#232326",
}

_HEADING_SIZES = {1: 20, 2: 17, 3: 15, 4: 14, 5: 13, 6: 13}


def _inline(text: str, colors: dict) -> str:
    """Escape a line of Markdown, then reapply the inline constructs."""
    placeholders: list[str] = []

    def stash(html_fragment: str) -> str:
        placeholders.append(html_fragment)
        return f"\x00{len(placeholders) - 1}\x00"

    def code(match):
        body = html.escape(match.group(1))
        return stash(f'<code style="background-color:{colors["codeBackground"]};'
                     f'color:{colors["accent"]}">{body}</code>')

    def link(match):
        label = html.escape(match.group(1)) or html.escape(match.group(2))
        href = html.escape(match.group(2), quote=True)
        return stash(f'<a href="{href}" style="color:{colors["accent"]}">{label}</a>')

    working = _INLINE_CODE.sub(code, text)
    working = _LINK.sub(link, working)
    working = html.escape(working)
    working = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", working)
    working = _ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", working)
    working = _STRIKE.sub(lambda m: f"<s>{m.group(1)}</s>", working)
    working = _AUTOLINK.sub(
        lambda m: f'<a href="{m.group(1)}" style="color:{colors["accent"]}">{m.group(1)}</a>', working)
    for index, fragment in enumerate(placeholders):
        working = working.replace(f"\x00{index}\x00", fragment)
    return working


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def to_html(text: str, palette: dict | None = None) -> str:
    """Render Markdown prose as the HTML subset Qt's rich text engine reads."""
    colors = {**HTML_PALETTE, **(palette or {})}
    lines = str(text or "").split("\n")
    out: list[str] = []
    index = 0
    paragraph: list[str] = []
    list_stack: list[str] = []

    def flush_paragraph():
        if paragraph:
            out.append(f'<p style="margin-top:0px;margin-bottom:10px;line-height:150%">'
                       f'{" ".join(paragraph)}</p>')
            paragraph.clear()

    def close_lists():
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            close_lists()
            index += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            close_lists()
            level = len(heading.group(1))
            size = _HEADING_SIZES[level]
            top = 16 if out else 0
            out.append(f'<p style="margin-top:{top}px;margin-bottom:7px;font-size:{size}px;'
                       f'font-weight:600;color:{colors["text"]}">{_inline(heading.group(2), colors)}</p>')
            index += 1
            continue

        if _RULE.match(line):
            flush_paragraph()
            close_lists()
            out.append(f'<hr style="height:1px;background-color:{colors["rule"]}"/>')
            index += 1
            continue

        # A table needs a header row followed by a divider row.
        if "|" in stripped and index + 1 < len(lines) and _TABLE_DIVIDER.match(lines[index + 1]):
            flush_paragraph()
            close_lists()
            header = _split_row(line)
            index += 2
            rows = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_split_row(lines[index]))
                index += 1
            cells = "".join(
                f'<th style="padding:6px 11px;text-align:left;font-weight:600;'
                f'color:{colors["text"]}">{_inline(cell, colors)}</th>' for cell in header)
            body = ""
            for row in rows:
                body += "<tr>" + "".join(
                    f'<td style="padding:6px 11px;color:{colors["muted"]}">'
                    f'{_inline(cell, colors)}</td>' for cell in row) + "</tr>"
            out.append(f'<table border="1" cellspacing="0" cellpadding="0" width="100%" '
                       f'style="border-color:{colors["border"]};margin-top:2px;margin-bottom:12px">'
                       f'<tr>{cells}</tr>{body}</table>')
            continue

        quote = _QUOTE.match(line)
        if quote:
            flush_paragraph()
            close_lists()
            block = [quote.group(1)]
            index += 1
            while index < len(lines) and _QUOTE.match(lines[index]):
                block.append(_QUOTE.match(lines[index]).group(1))
                index += 1
            joined = _inline(" ".join(part for part in block if part.strip()), colors)
            out.append(f'<table border="0" cellspacing="0" cellpadding="0" width="100%" '
                       f'style="margin-top:2px;margin-bottom:12px"><tr>'
                       f'<td width="2" style="background-color:{colors["border"]}"></td>'
                       f'<td style="padding-left:12px;color:{colors["muted"]}">{joined}</td>'
                       f"</tr></table>")
            continue

        unordered = _UNORDERED.match(line)
        ordered = _ORDERED.match(line)
        if unordered or ordered:
            flush_paragraph()
            tag = "ul" if unordered else "ol"
            if not list_stack:
                out.append(f'<{tag} style="margin-top:0px;margin-bottom:10px;-qt-list-indent:1">')
                list_stack.append(tag)
            elif list_stack[-1] != tag:
                close_lists()
                out.append(f'<{tag} style="margin-top:0px;margin-bottom:10px;-qt-list-indent:1">')
                list_stack.append(tag)
            content = unordered.group(2) if unordered else ordered.group(3)
            out.append(f'<li style="margin-bottom:5px;line-height:145%">{_inline(content, colors)}</li>')
            index += 1
            continue

        close_lists()
        paragraph.append(_inline(stripped, colors))
        index += 1

    flush_paragraph()
    close_lists()
    body = "".join(out) or "&nbsp;"
    return (f'<div style="color:{colors["text"]}">{body}</div>')


__all__ = ['StreamingDocument', 'normalise_language', 'display_language', 'highlight', 'segment', 'code_blocks', 'to_html', 'MARKDOWN', 'CODE', 'DEFAULT_PALETTE', 'DISPLAY_NAMES', 'RUNNABLE', 'HTML_PALETTE']
