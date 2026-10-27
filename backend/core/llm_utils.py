"""LLM response helpers shared by Anthropic-compatible providers."""
from typing import Any, Iterable, List


def extract_text_content(content: Iterable[Any]) -> str:
    """Return text blocks from Anthropic-style response content."""
    texts: List[str] = []
    for block in content or []:
        if isinstance(block, str):
            texts.append(block)
            continue

        block_type = getattr(block, "type", None)
        text = getattr(block, "text", None)
        if isinstance(block, dict):
            block_type = block.get("type", block_type)
            text = block.get("text", text)

        if isinstance(text, str) and (block_type in (None, "text")):
            texts.append(text)

    return "\n".join(t for t in texts if t)


def generation_options(client) -> dict:
    """Short structured calls need their token budget for output, not reasoning."""
    from urllib.parse import urlsplit
    if urlsplit(str(client.base_url)).hostname == "api.deepseek.com":
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}
