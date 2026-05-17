"""Text metrics helpers — words and token estimates."""

import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")


def tokens(text: str) -> int:
    """Token count using cl100k_base (GPT-4 / Claude tokenizer)."""
    return len(_enc.encode(text))


def words(text: str) -> int:
    return len(text.split())


def text_stats(text: str) -> dict[str, int]:
    """Return both metrics as a dict for use in log calls."""
    return {"tokens": tokens(text), "words": words(text)}
