"""Wynxq — a local AI workbench for Linux."""

from wynxq.commands import run_command
from wynxq.controller import Controller
from wynxq.desktop import DesktopController
from wynxq.dock import DockController
from wynxq.engine import AgentEngine
from wynxq.memory import Memory
from wynxq.ollama import OllamaClient
from wynxq.storage import Store
from wynxq.workspace import WorkspaceController

__all__ = [
    "AgentEngine",
    "Controller",
    "DesktopController",
    "DockController",
    "Memory",
    "OllamaClient",
    "run_command",
    "Store",
    "WorkspaceController",
]

__version__ = "1.0.0"
