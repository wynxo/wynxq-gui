"""Compatibility facade for platform desktop backends.

Platform implementations live in focused modules. Keep these re-exports so
existing imports, tests, and embedders do not need to change when backend
internals evolve independently.
"""
from .desktop_portal import _PortalBackend
from .desktop_stop import GlobalStop, X11GlobalStop
from .desktop_x11 import _X11Backend

__all__ = ["GlobalStop", "X11GlobalStop", "_PortalBackend", "_X11Backend"]
