"""Conservative, model-independent learning of durable user memory.

The model already has explicit ``remember`` / ``forget`` tools.  This module is
for the cases where a model does not support tools or simply fails to call one.
It intentionally recognises only high-confidence statements from the *user*.
A false negative is cheap; a false positive lives across chats and is not.

The returned notes are ordinary memory.md notes.  There is no hidden profile:
the Memory panel remains the single inspectable/editable source of truth.
"""
from __future__ import annotations

import re

GLOBAL = "global"
PROJECT = "project"

_MAX_INPUT = 1400
_MAX_VALUE = 260

# Never persist likely credentials or explicit privacy instructions.  These are
# deliberately broad because remembering a secret by accident is much worse than
# failing to remember a preference that can be stated again.
_SECRET = re.compile(
    r"(?i)(password|passphrase|passwd|api[ _-]?key|access[ _-]?token|auth[ _-]?token|"
    r"secret[ _-]?key|private[ _-]?key|recovery[ _-]?(?:code|phrase)|seed[ _-]?phrase|"
    r"bearer\s+[a-z0-9._~+/=-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bsk-[a-z0-9_-]{12,}|\bgh[pousr]_[a-z0-9]{20,}|"
    r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,})"
)
_DONT_STORE = re.compile(
    r"(?i)\b(?:do\s*not|don't|dont|never)\s+(?:remember|save|store|keep)\b|"
    r"\b(?:forget|ignore)\s+(?:that|this)\b|"
    r"\bне\s+(?:запоминай|сохраняй)\b|\bvergiss\s+(?:das|dies)\b"
)
_TRANSIENT = re.compile(
    r"(?i)\b(?:today|tonight|tomorrow|yesterday|right now|for now|this time|"
    r"this chat|this conversation|temporarily|just this once|for this turn|"
    r"сегодня|сейчас|пока что|в этот раз|завтра|heute|jetzt|vorerst|diesmal|morgen)\b"
)

# Patterns are ordered from most explicit/specific to broadest.  Each captures
# only the value, then renders it into a stable fact rather than storing the
# user's raw sentence as a new instruction.
_GLOBAL_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"(?i)^\s*(?:please\s+)?(?:call|refer to)\s+me\s+(?:as\s+)?(.+?)[.!?]*\s*$"),
     "User prefers to be called {value}."),
    (re.compile(r"(?i)^\s*my\s+(?:name|preferred name)\s+is\s+(.+?)[.!?]*\s*$"),
     "User's preferred name is {value}."),
    (re.compile(r"(?i)^\s*(?:i\s+)?prefer\s+(.+?)[.!?]*\s*$"),
     "User prefers {value}."),
    (re.compile(r"(?i)^\s*i\s+(?:really\s+)?(?:like|love)\s+(.+?)[.!?]*\s*$"),
     "User likes {value}."),
    (re.compile(r"(?i)^\s*i\s+(?:really\s+)?(?:dislike|hate)\s+(.+?)[.!?]*\s*$"),
     "User dislikes {value}."),
    (re.compile(r"(?i)^\s*i\s+use\s+(.+?)[.!?]*\s*$"),
     "User uses {value}."),
    (re.compile(r"(?i)^\s*i(?:'m|\s+am)\s+learning\s+(.+?)[.!?]*\s*$"),
     "User is learning {value}."),
    (re.compile(r"(?i)^\s*i\s+speak\s+(.+?)[.!?]*\s*$"),
     "User speaks {value}."),
    (re.compile(r"(?i)^\s*my\s+main\s+(?:os|operating system)\s+is\s+(.+?)[.!?]*\s*$"),
     "User's main operating system is {value}."),
    (re.compile(r"(?i)^\s*i\s+always\s+want\s+(?:you|wynxq)\s+to\s+(.+?)[.!?]*\s*$"),
     "User prefers the assistant to always {value}."),
    # Russian high-confidence equivalents.
    (re.compile(r"(?i)^\s*(?:называй|зови)\s+меня\s+(.+?)[.!?]*\s*$"),
     "User prefers to be called {value}."),
    (re.compile(r"(?i)^\s*меня\s+зовут\s+(.+?)[.!?]*\s*$"),
     "User's preferred name is {value}."),
    (re.compile(r"(?i)^\s*я\s+предпочитаю\s+(.+?)[.!?]*\s*$"),
     "User prefers {value}."),
    (re.compile(r"(?i)^\s*мне\s+нравится\s+(.+?)[.!?]*\s*$"),
     "User likes {value}."),
    (re.compile(r"(?i)^\s*я\s+использую\s+(.+?)[.!?]*\s*$"),
     "User uses {value}."),
    (re.compile(r"(?i)^\s*я\s+изучаю\s+(.+?)[.!?]*\s*$"),
     "User is learning {value}."),
    (re.compile(r"(?i)^\s*я\s+говорю\s+(?:на\s+)?(.+?)[.!?]*\s*$"),
     "User speaks {value}."),
    # German high-confidence equivalents.
    (re.compile(r"(?i)^\s*nenn\s+mich\s+(.+?)[.!?]*\s*$"),
     "User prefers to be called {value}."),
    (re.compile(r"(?i)^\s*ich\s+hei(?:ß|ss)e\s+(.+?)[.!?]*\s*$"),
     "User's preferred name is {value}."),
    (re.compile(r"(?i)^\s*ich\s+bevorzuge\s+(.+?)[.!?]*\s*$"),
     "User prefers {value}."),
    (re.compile(r"(?i)^\s*ich\s+benutze\s+(.+?)[.!?]*\s*$"),
     "User uses {value}."),
    (re.compile(r"(?i)^\s*ich\s+lerne\s+(.+?)[.!?]*\s*$"),
     "User is learning {value}."),
    (re.compile(r"(?i)^\s*ich\s+spreche\s+(.+?)[.!?]*\s*$"),
     "User speaks {value}."),
)

_PROJECT_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"(?i)^\s*(?:in|for)\s+(?:this|the)\s+(?:project|repo|repository|app)\s*[,;:-]?\s*(.+?)[.!?]*\s*$"),
     "In this project, {value}."),
    (re.compile(r"(?i)^\s*(?:this|the)\s+(?:project|repo|repository|app)\s+(?:uses|runs|requires|expects)\s+(.+?)[.!?]*\s*$"),
     "This project uses or expects {value}."),
    (re.compile(r"(?i)^\s*(?:в|для)\s+(?:этом|этого)\s+(?:проекте|проекта|репозитории)\s*[,;:-]?\s*(.+?)[.!?]*\s*$"),
     "In this project, {value}."),
    (re.compile(r"(?i)^\s*(?:этот|данный)\s+(?:проект|репозиторий)\s+(?:использует|требует)\s+(.+?)[.!?]*\s*$"),
     "This project uses or expects {value}."),
    (re.compile(r"(?i)^\s*(?:in|für)\s+(?:diesem|dieses)\s+(?:projekt|repo|repository)\s*[,;:-]?\s*(.+?)[.!?]*\s*$"),
     "In this project, {value}."),
)

# Put the longer forms first: regex alternation is left-biased, so ``remember``
# before ``remember that`` would incorrectly keep the word "that" in the note.
_EXPLICIT = re.compile(
    r"(?i)^\s*(?:please\s+)?(?:remember\s+that|keep\s+in\s+mind|note\s+that|remember)\s*[:,-]?\s*(.+?)\s*$|"
    r"^\s*(?:запомни,?\s+что|запомни)\s*[:,-]?\s*(.+?)\s*$|"
    r"^\s*(?:merk\s+dir|merke\s+dir)\s*[:,-]?\s*(.+?)\s*$"
)
_PROJECT_HINT = re.compile(
    r"(?i)\b(?:this|the)\s+(?:project|repo|repository|codebase|app)\b|"
    r"\b(?:этот|этом|данный)\s+(?:проект|репозиторий|код)\b|"
    r"\b(?:dieses|diesem)\s+(?:projekt|repo|repository)\b"
)


def _clean_value(value: str) -> str:
    value = " ".join(str(value or "").split()).strip(" \t\r\n\"'`.,;:!?—–-")
    return value[:_MAX_VALUE].strip()


def _safe_candidate(text: str) -> bool:
    if not text or len(text) > _MAX_INPUT:
        return False
    if _SECRET.search(text) or _DONT_STORE.search(text):
        return False
    return True


def _note(patterns, sentence: str) -> str:
    for pattern, template in patterns:
        match = pattern.match(sentence)
        if not match:
            continue
        value = _clean_value(match.group(1))
        if 1 <= len(value) <= _MAX_VALUE and not _SECRET.search(value):
            return template.format(value=value)
    return ""


_FORGET = re.compile(
    r"(?i)^\s*(?:please\s+)?(?:forget|remove\s+from\s+memory|stop\s+remembering)"
    r"(?:\s+that)?\s*[:,-]?\s*(.+?)\s*[.!?]*\s*$|"
    r"^\s*(?:забудь|удали\s+из\s+памяти)(?:,?\s+что)?\s*[:,-]?\s*(.+?)\s*[.!?]*\s*$|"
    r"^\s*(?:vergiss|aus\s+dem\s+gedächtnis\s+löschen)(?:\s+dass)?"
    r"\s*[:,-]?\s*(.+?)\s*[.!?]*\s*$"
)


def forget_memory_queries(text: str) -> list[str]:
    """Extract explicit requests to forget durable memory.

    Chat mode has no tools by design, so forgetting cannot depend on a model
    deciding to call a tool. Only direct imperative phrasing is accepted.
    """
    raw = str(text or "").strip()
    if not raw or len(raw) > _MAX_INPUT:
        return []
    queries = []
    for line in (item.strip() for item in raw.splitlines() if item.strip()):
        match = _FORGET.match(line)
        if not match:
            continue
        value = _clean_value(next((group for group in match.groups() if group), ""))
        if not value or value.casefold() in {
            "that", "this", "it", "everything", "all", "это", "всё", "все", "das", "dies",
        }:
            continue
        queries.append(value)
    return queries[:4]


def learnable_memories(text: str, project: str = "") -> list[dict]:
    """Return high-confidence durable notes found in one user message.

    Each item is ``{"note": ..., "scope": "global"|"project"}``.  Nothing is
    written here; callers decide whether memory is enabled and persist through
    :class:`wynxq.memory.Memory`, preserving its dedupe and size limits.
    """
    raw = str(text or "").strip()
    if not _safe_candidate(raw):
        return []

    # An explicitly temporary statement should not become durable even when it
    # happens to look like a preference ("for now I prefer …").
    transient = bool(_TRANSIENT.search(raw))
    candidates: list[dict] = []

    # Split only on line boundaries.  Sentence tokenisation is deliberately not
    # attempted: it creates false memories from examples and quoted prose.
    for sentence in (line.strip() for line in raw.splitlines() if line.strip()):
        if len(sentence) > 600 or not _safe_candidate(sentence):
            continue

        explicit = _EXPLICIT.match(sentence)
        if explicit:
            value = _clean_value(next((group for group in explicit.groups() if group), ""))
            if value and not _TRANSIENT.search(value) and not _SECRET.search(value):
                scope = PROJECT if project and _PROJECT_HINT.search(value) else GLOBAL
                candidates.append({"note": value, "scope": scope})
            continue

        if transient:
            continue
        if project:
            note = _note(_PROJECT_PATTERNS, sentence)
            if note:
                candidates.append({"note": note, "scope": PROJECT})
                continue
        note = _note(_GLOBAL_PATTERNS, sentence)
        if note:
            candidates.append({"note": note, "scope": GLOBAL})

    # Preserve order while suppressing duplicates produced by overlapping
    # patterns.  Memory.remember does the authoritative cross-turn dedupe.
    seen, unique = set(), []
    for item in candidates[:6]:
        key = (item["scope"], " ".join(item["note"].split()).casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
