"""Read the AI keys from .env so both run.py and manage.py use the language model."""

import os

# OpenAI-compatible chat-completions endpoints, in order of preference, with their default models.
PROVIDERS = (
    ("OPENAI", "https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
    ("GEMINI", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "gemini-flash-lite-latest"),
    ("GROQ", "https://api.groq.com/openai/v1/chat/completions", "qwen/qwen3.8-27b"),
)


def load_env(path):
    """Read KEY=value lines from a private .env file; real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if sep and key and not key.startswith("#") and value:
            os.environ.setdefault(key, value)


def configured_models():
    """Every provider with a key: the first writes the replies, the next is the backup."""
    return [{"name": name.title(), "url": url, "model": os.getenv(f"{name}_MODEL", model),
             "key": os.getenv(f"{name}_API_KEY", "").strip()}
            for name, url, model in PROVIDERS if os.getenv(f"{name}_API_KEY", "").strip()]
