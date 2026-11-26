import json

import httpx

from . import config


class LLMError(RuntimeError):
    """Raised when the required Ollama model cannot serve a usable response."""


class LLM:
    """Thin Ollama client; production failures are explicit, mock mode is non-production."""

    def generate_action(self, system: str, prompt: str, tools: list) -> str | dict | None:
        """Request one native Ollama tool call, or a final JSON response."""
        return self.generate_native_action(system, prompt, tools)

    def generate(self, system: str, prompt: str) -> str | None:
        if config.LLM_MODE == "mock":
            return None
        if config.LLM_MODE != "required":
            raise LLMError(f"unsupported LLM_MODE {config.LLM_MODE!r}; use 'required' or 'mock'")
        try:
            r = httpx.post(
                f"{config.OLLAMA_URL}/api/generate",
                json={
                    "model": config.OLLAMA_MODEL,
                    "system": system,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": config.OLLAMA_KEEP_ALIVE,
                    "options": {"temperature": 0.2, "num_predict": config.LLM_MAX_TOKENS},
                },
                timeout=config.LLM_TIMEOUT,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama request failed at {config.OLLAMA_URL}: {e}") from e
        try:
            payload = r.json()
        except ValueError as e:
            raise LLMError("Ollama returned invalid JSON") from e
        if not isinstance(payload, dict):
            raise LLMError("Ollama response must be a JSON object")
        text = (payload.get("response") or "").strip()
        if not text:
            raise LLMError(f"Ollama returned an empty response for model {config.OLLAMA_MODEL}")
        return text

    def generate_native_action(self, system: str, prompt: str, tools: list) -> str | dict | None:
        """Use Ollama's native tool-call API with schemas discovered from the MCP server."""
        if config.LLM_MODE == "mock":
            return None
        if config.LLM_MODE != "required":
            raise LLMError(f"unsupported LLM_MODE {config.LLM_MODE!r}; use 'required' or 'mock'")
        ollama_tools = []
        for tool in tools:
            schema = tool.model_dump(by_alias=True)
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema.get("description", ""),
                    "parameters": schema.get("inputSchema", {}),
                },
            })
        try:
            r = httpx.post(
                f"{config.OLLAMA_URL}/api/chat",
                json={
                    "model": config.OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "tools": ollama_tools,
                    "stream": False,
                    "keep_alive": config.OLLAMA_KEEP_ALIVE,
                    "options": {"temperature": 0.1, "num_predict": config.LLM_MAX_TOKENS},
                },
                timeout=config.LLM_TIMEOUT,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama native tool request failed at {config.OLLAMA_URL}: {e}") from e
        try:
            payload = r.json()
        except ValueError as e:
            raise LLMError("Ollama returned invalid JSON for a native tool request") from e
        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict):
            raise LLMError("Ollama native tool response has no message object")
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list):
            raise LLMError("Ollama native tool response has invalid tool_calls")
        if len(calls) > 1:
            raise LLMError("Ollama returned multiple tool calls; one call per turn is required")
        if calls:
            call = calls[0]
            if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                raise LLMError("Ollama returned a malformed native tool call")
            function = call["function"]
            name, arguments = function.get("name"), function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError as e:
                    raise LLMError("Ollama returned invalid JSON tool arguments") from e
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise LLMError("Ollama returned an invalid native tool call")
            return {"tool": name, "args": arguments}
        content = message.get("content")
        return content if isinstance(content, str) and content.strip() else None
