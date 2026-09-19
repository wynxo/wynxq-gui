"""Network policy for the desktop workspace."""
import pytest

from wynxq.workspace import endpoint_scope, validate_workspace_endpoint


@pytest.mark.parametrize("value,expected", [
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("http://localhost:11434/", "http://localhost:11434"),
    ("http://192.168.1.42:11434", "http://192.168.1.42:11434"),
    ("http://10.0.0.8:11434", "http://10.0.0.8:11434"),
    ("http://172.20.5.9:11434", "http://172.20.5.9:11434"),
    ("https://ollama.home.arpa", "https://ollama.home.arpa"),
    ("https://ollama.example.net:443", "https://ollama.example.net:443"),
    ("http://[fd00::5]:11434", "http://[fd00::5]:11434"),
])
def test_workspace_accepts_explicit_ollama_origins(value, expected):
    assert validate_workspace_endpoint(value) == expected


@pytest.mark.parametrize("value", [
    "192.168.1.42:11434",
    "ftp://192.168.1.42:11434",
    "http://user:pass@192.168.1.42:11434",
    "http://192.168.1.42:11434/api/chat",
    "http://192.168.1.42:11434/?x=1",
    "http://192.168.1.42:11434/#fragment",
    "http://exa mple.test:11434",
])
def test_workspace_rejects_ambiguous_or_unsafe_endpoint_forms(value):
    with pytest.raises(ValueError):
        validate_workspace_endpoint(value)


def test_endpoint_scope_distinguishes_local_lan_and_remote():
    assert endpoint_scope("http://127.0.0.1:11434") == "local"
    assert endpoint_scope("http://192.168.1.20:11434") == "lan"
    assert endpoint_scope("http://ollama.home.arpa:11434") == "lan"
    assert endpoint_scope("https://ollama.example.net") == "remote"
