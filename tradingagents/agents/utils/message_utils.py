"""Helpers for normalising LLM message content across providers.

Different chat providers return ``BaseMessage.content`` in incompatible
shapes:

- OpenAI / Anthropic legacy: a flat ``str``.
- Anthropic 3.x and Gemini 3.x: a ``list`` of content blocks like
  ``[{"type": "text", "text": "...", "extras": {"signature": "..."}}]``,
  often interleaved with ``thinking`` / ``tool_use`` / ``tool_result``
  blocks and provider-specific fields (e.g. Gemini's opaque
  ``thought_signature``).

If the raw list is interpolated into an f-string (``f"Bull: {msg.content}"``)
Python falls back to ``repr(list)`` which dumps the entire structure —
including the signatures — into the surface text, polluting reports and
breaking downstream regex / parsers.

``content_to_text`` flattens any of the above into a plain string,
keeping only the visible-text parts.
"""

from __future__ import annotations

from typing import Any


def content_to_text(content: Any) -> str:
    """Flatten ``BaseMessage.content`` into a plain string.

    Drops ``thinking`` / ``tool_use`` / ``tool_result`` blocks and any
    provider-specific extras (e.g. ``extras.signature``). Returns ``""``
    for ``None`` and falls back to ``str(content)`` for unknown shapes.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype in ("thinking", "tool_use", "tool_result"):
                    continue
                if "text" in block and block["text"] is not None:
                    parts.append(str(block["text"]))
                elif "content" in block and block["content"] is not None:
                    parts.append(str(block["content"]))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)
