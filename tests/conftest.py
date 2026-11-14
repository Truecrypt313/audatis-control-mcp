"""All automated tests are offline, including future additions."""
import os
import socket

import pytest
import dotenv

# Collection/imports must not load private configuration or production identifiers.
dotenv.load_dotenv = lambda *args, **kwargs: False
os.environ["AUDATIS_ALLOWED_CLIENT_ID"] = "12345"
os.environ.setdefault("AUDATIS_OPENAPI_SPEC_PATH", "")
import task_direct
task_direct.EXPECTED_CLIENT_ID = 12345


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    # Existing tests expect the complete catalog, independent of a developer's profile.
    monkeypatch.setenv("AUDATIS_MCP_MODULES", "all")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    def blocked(*args, **kwargs):
        pytest.fail("Live-Netzwerkzugriffe sind in Offline-Tests verboten")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
