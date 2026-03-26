from pr_agent.algo.ai_handlers.base_ai_handler import BaseAiHandler
from pr_agent.algo.ai_handlers.codex_cli_ai_handler import CodexCLIHandler
from pr_agent.algo.ai_handlers.litellm_ai_handler import LiteLLMAIHandler
from pr_agent.config_loader import get_settings

AI_HANDLERS: dict[str, type[BaseAiHandler]] = {
    "litellm": LiteLLMAIHandler,
    "codex_cli": CodexCLIHandler,
}


def get_ai_handler_name() -> str:
    handler_name = get_settings().get("CONFIG.AI_HANDLER", "litellm") or "litellm"
    if handler_name not in AI_HANDLERS:
        supported_handlers = ", ".join(sorted(AI_HANDLERS))
        raise ValueError(
            f"Unsupported config.ai_handler '{handler_name}'. Supported values: {supported_handlers}"
        )
    return handler_name


def get_ai_handler() -> type[BaseAiHandler]:
    return AI_HANDLERS[get_ai_handler_name()]
