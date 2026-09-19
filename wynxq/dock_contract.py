"""Stable workspace-dock tabs, metadata, and sizing contract."""

TABS = ("files", "terminal", "changes", "context", "memory", "activity", "browser", "preview")

TAB_META = {
    "files":    {"label": "Files",    "icon": "folder",   "shortcut": "Ctrl+Shift+E"},
    "terminal": {"label": "Terminal", "icon": "terminal", "shortcut": "Ctrl+`"},
    "changes":  {"label": "Changes",  "icon": "branch",   "shortcut": "Ctrl+Shift+G"},
    "context":  {"label": "Context",  "icon": "layers",   "shortcut": "Ctrl+Shift+K"},
    "memory":   {"label": "Memory",   "icon": "memory",   "shortcut": "Ctrl+Shift+M"},
    "activity": {"label": "Activity", "icon": "bolt",     "shortcut": "Ctrl+Shift+A"},
    "browser":  {"label": "Browser",  "icon": "globe",    "shortcut": "Ctrl+Shift+W"},
    "preview":  {"label": "Preview",  "icon": "image",    "shortcut": "Ctrl+Shift+U"},
}

MIN_WIDTH = 280
MAX_WIDTH = 900
DEFAULT_WIDTH = 380
