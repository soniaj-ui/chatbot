"""Read the AI key from .env so both run.py and manage.py use the language model."""

import os

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def load_env(path):
    """Read KEY=value lines from a private .env file; real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if sep and key and not key.startswith("#") and value:
            os.environ.setdefault(key, value)


def configure_model():
    # The first provider with a key in .env writes the replies: OpenAI, then Gemini.
    for name, url, model in (("OPENAI", OPENAI_URL, "gpt-4o-mini"), ("GEMINI", GEMINI_URL, "gemini-flash-lite-latest")):
        key = os.getenv(f"{name}_API_KEY", "").strip()
        if key and not os.getenv("GUIDANCE_LLM_URL"):
            os.environ["GUIDANCE_LLM_URL"] = url
            os.environ["GUIDANCE_LLM_MODEL"] = os.getenv(f"{name}_MODEL", model)
            os.environ["GUIDANCE_LLM_KEY"] = key
    return os.getenv("GUIDANCE_LLM_MODEL")
