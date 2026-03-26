import asyncio
import contextlib
import os
import subprocess
from tempfile import TemporaryDirectory

from pr_agent.algo.ai_handlers.base_ai_handler import BaseAiHandler
from pr_agent.config_loader import get_settings
from pr_agent.log import get_logger

CODEX_LOGIN_STATUS_TIMEOUT_SECONDS = 15
VALID_REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}


class CodexCLIHandler(BaseAiHandler):
    """
    AI handler that delegates prompt execution to a locally installed Codex CLI.
    """

    def __init__(self):
        self.command = get_settings().get("CODEX_CLI.COMMAND", "codex") or "codex"
        self.model_override = get_settings().get("CODEX_CLI.MODEL", "") or ""
        self.codex_home = get_settings().get("CODEX_CLI.CODEX_HOME", "") or ""
        self.ai_timeout = get_settings().config.ai_timeout
        self.reasoning_effort = self._get_reasoning_effort()
        self._env = os.environ.copy()
        if self.codex_home:
            self._env["CODEX_HOME"] = self.codex_home
        self._validate_login_status()

    @property
    def deployment_id(self):
        return None

    def _validate_login_status(self) -> None:
        try:
            result = subprocess.run(
                [self.command, "login", "status"],
                capture_output=True,
                text=True,
                timeout=CODEX_LOGIN_STATUS_TIMEOUT_SECONDS,
                env=self._env,
            )
        except FileNotFoundError as e:
            raise ValueError(
                f"Codex CLI command '{self.command}' was not found. Install Codex CLI or set codex_cli.command."
            ) from e
        except subprocess.TimeoutExpired as e:
            raise ValueError(
                f"Codex CLI login status timed out after {CODEX_LOGIN_STATUS_TIMEOUT_SECONDS} seconds."
            ) from e

        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            message = "Codex CLI is not authenticated. Run `codex login` on this deployment node."
            if details:
                message = f"{message} Status output: {details}"
            raise ValueError(message)

    def _build_prompt(self, system: str, user: str) -> str:
        return (
            "You are acting as the model backend for PR-Agent.\n"
            "Treat the provided system prompt and user prompt as the complete task context.\n"
            "Do not inspect the filesystem. Do not run shell commands. Do not rely on repository state.\n"
            "The working directory is intentionally empty.\n"
            "Return only the final answer for the task.\n\n"
            "<SYSTEM_PROMPT>\n"
            f"{system or ''}\n"
            "</SYSTEM_PROMPT>\n\n"
            "<USER_PROMPT>\n"
            f"{user or ''}\n"
            "</USER_PROMPT>\n"
        )

    def _get_reasoning_effort(self) -> str:
        configured_effort = getattr(get_settings().config, "reasoning_effort", "medium")
        if configured_effort in VALID_REASONING_EFFORTS:
            return configured_effort

        get_logger().warning(
            f"Invalid reasoning_effort '{configured_effort}' in config. Using default 'medium' for Codex CLI."
        )
        return "medium"

    def _build_command(self, model: str, output_file: str, workdir: str) -> list[str]:
        selected_model = self.model_override or model
        command = [
            self.command,
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--ephemeral",
            "--output-last-message",
            output_file,
            "-C",
            workdir,
            "-c",
            f'model_reasoning_effort="{self.reasoning_effort}"',
        ]
        if selected_model:
            command.extend(["-m", selected_model])
        command.append("-")
        return command

    async def chat_completion(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.2,
        img_path: str = None,
    ):
        if img_path:
            get_logger().warning(
                f"Image path is not supported for CodexCLIHandler. Ignoring image path: {img_path}"
            )

        prompt = self._build_prompt(system, user)

        with TemporaryDirectory() as tmp_dir:
            output_file = os.path.join(tmp_dir, "codex-last-message.txt")
            command = self._build_command(model=model, output_file=output_file, workdir=tmp_dir)
            get_logger().debug(
                "Running Codex CLI backend",
                artifact={
                    "command": command,
                    "codex_home": self._env.get("CODEX_HOME"),
                    "reasoning_effort": self.reasoning_effort,
                },
            )

            process = None
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    env=self._env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")),
                    timeout=self.ai_timeout,
                )
            except FileNotFoundError as e:
                raise RuntimeError(
                    f"Codex CLI command '{self.command}' was not found. Install Codex CLI or set codex_cli.command."
                ) from e
            except asyncio.TimeoutError as e:
                if process:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    with contextlib.suppress(asyncio.CancelledError, ProcessLookupError):
                        await process.wait()
                raise RuntimeError(f"Codex CLI timed out after {self.ai_timeout} seconds.") from e
            except asyncio.CancelledError:
                if process:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    with contextlib.suppress(asyncio.CancelledError, ProcessLookupError):
                        await process.wait()
                raise

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            if process.returncode != 0:
                error_text = stderr_text or stdout_text or "unknown error"
                raise RuntimeError(f"Codex CLI failed with exit code {process.returncode}: {error_text}")

            response_text = ""
            if os.path.exists(output_file):
                with open(output_file, "r", encoding="utf-8") as file:
                    response_text = file.read().strip()
            if not response_text:
                response_text = stdout_text
            if not response_text:
                raise RuntimeError("Codex CLI returned no output.")

            return response_text, "completed"
