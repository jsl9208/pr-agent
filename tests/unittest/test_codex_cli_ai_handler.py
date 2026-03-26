import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pr_agent.agent.pr_agent import PRAgent
from pr_agent.algo.ai_handlers.codex_cli_ai_handler import CodexCLIHandler
from pr_agent.algo.ai_handlers.factory import get_ai_handler


class FakeSettings:
    def __init__(
        self,
        ai_handler="codex_cli",
        command="codex",
        model="gpt-5.4-2026-03-05",
        codex_model="",
        codex_home="",
        ai_timeout=120,
        reasoning_effort="medium",
    ):
        self.config = type(
            "Config",
            (),
            {
                "ai_handler": ai_handler,
                "model": model,
                "ai_timeout": ai_timeout,
                "reasoning_effort": reasoning_effort,
            },
        )()
        self.codex_cli = type(
            "CodexCLI",
            (),
            {
                "command": command,
                "model": codex_model,
                "codex_home": codex_home,
            },
        )()

    def get(self, key, default=None):
        values = {
            "CONFIG.AI_HANDLER": self.config.ai_handler,
            "CODEX_CLI.COMMAND": self.codex_cli.command,
            "CODEX_CLI.MODEL": self.codex_cli.model,
            "CODEX_CLI.CODEX_HOME": self.codex_cli.codex_home,
        }
        return values.get(key, default)


class FakeProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")
        self.killed = False

    async def communicate(self, _input=None):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


@pytest.mark.asyncio
async def test_codex_cli_handler_runs_exec_with_output_file(monkeypatch):
    settings = FakeSettings()
    monkeypatch.setattr("pr_agent.algo.ai_handlers.codex_cli_ai_handler.get_settings", lambda: settings)

    with patch(
        "pr_agent.algo.ai_handlers.codex_cli_ai_handler.subprocess.run",
        return_value=subprocess.CompletedProcess(["codex", "login", "status"], 0, "ok", ""),
    ):
        recorded = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            output_path = args[args.index("--output-last-message") + 1]
            Path(output_path).write_text("codex reply", encoding="utf-8")
            recorded["args"] = args
            recorded["kwargs"] = kwargs
            return FakeProcess(stdout="ignored stdout")

        with patch(
            "pr_agent.algo.ai_handlers.codex_cli_ai_handler.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=fake_create_subprocess_exec),
        ):
            handler = CodexCLIHandler()
            response, finish_reason = await handler.chat_completion(
                model="gpt-5.4-2026-03-05",
                system="system prompt",
                user="user prompt",
            )

    assert response == "codex reply"
    assert finish_reason == "completed"
    assert recorded["args"][0:2] == ("codex", "exec")
    assert "--skip-git-repo-check" in recorded["args"]
    assert "--sandbox" in recorded["args"]
    assert "read-only" in recorded["args"]
    assert "--ephemeral" in recorded["args"]
    config_index = recorded["args"].index("-c") + 1
    assert recorded["args"][config_index] == 'model_reasoning_effort="medium"'
    assert recorded["args"][-1] == "-"


@pytest.mark.asyncio
async def test_codex_cli_handler_uses_codex_home_and_model_override(monkeypatch):
    settings = FakeSettings(codex_model="gpt-5.4", codex_home="/srv/pr-agent/.codex")
    monkeypatch.setattr("pr_agent.algo.ai_handlers.codex_cli_ai_handler.get_settings", lambda: settings)

    with patch(
        "pr_agent.algo.ai_handlers.codex_cli_ai_handler.subprocess.run",
        return_value=subprocess.CompletedProcess(["codex", "login", "status"], 0, "ok", ""),
    ):
        recorded = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            output_path = args[args.index("--output-last-message") + 1]
            Path(output_path).write_text("override model reply", encoding="utf-8")
            recorded["args"] = args
            recorded["kwargs"] = kwargs
            return FakeProcess()

        with patch(
            "pr_agent.algo.ai_handlers.codex_cli_ai_handler.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=fake_create_subprocess_exec),
        ):
            handler = CodexCLIHandler()
            await handler.chat_completion(model="fallback-model", system="system", user="user")

    model_index = recorded["args"].index("-m") + 1
    assert recorded["args"][model_index] == "gpt-5.4"
    assert recorded["kwargs"]["env"]["CODEX_HOME"] == "/srv/pr-agent/.codex"


def test_codex_cli_handler_requires_login(monkeypatch):
    settings = FakeSettings()
    monkeypatch.setattr("pr_agent.algo.ai_handlers.codex_cli_ai_handler.get_settings", lambda: settings)

    with patch(
        "pr_agent.algo.ai_handlers.codex_cli_ai_handler.subprocess.run",
        return_value=subprocess.CompletedProcess(["codex", "login", "status"], 1, "", "not logged in"),
    ):
        with pytest.raises(ValueError, match="Codex CLI is not authenticated"):
            CodexCLIHandler()


def test_codex_cli_handler_invalid_reasoning_effort_falls_back_to_medium(monkeypatch):
    settings = FakeSettings(reasoning_effort="invalid")
    monkeypatch.setattr("pr_agent.algo.ai_handlers.codex_cli_ai_handler.get_settings", lambda: settings)

    with patch(
        "pr_agent.algo.ai_handlers.codex_cli_ai_handler.subprocess.run",
        return_value=subprocess.CompletedProcess(["codex", "login", "status"], 0, "ok", ""),
    ):
        handler = CodexCLIHandler()

    assert handler.reasoning_effort == "medium"


def test_get_ai_handler_uses_config(monkeypatch):
    settings = FakeSettings(ai_handler="codex_cli")
    monkeypatch.setattr("pr_agent.algo.ai_handlers.factory.get_settings", lambda: settings)

    assert get_ai_handler() is CodexCLIHandler


def test_pr_agent_defaults_to_resolved_ai_handler():
    with patch("pr_agent.agent.pr_agent.get_ai_handler", return_value=CodexCLIHandler):
        agent = PRAgent()

    assert agent.ai_handler is CodexCLIHandler
