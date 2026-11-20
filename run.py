"""Start the Django telecaller: read keys from .env, apply migrations and run the server."""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
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


def main():
    parser = argparse.ArgumentParser(description="Start the AI telecaller dashboard")
    parser.add_argument("--port", type=int, default=8000, help="Dashboard port (default 8000)")
    args = parser.parse_args()

    load_env(ROOT / ".env")
    model = configure_model()
    print(f"AI replies by {model}" if model else "No AI key found: add GEMINI_API_KEY to .env")

    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "telecaller.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(["manage.py", "migrate", "--noinput", "--verbosity", "0"])
    execute_from_command_line(["manage.py", "runserver", f"127.0.0.1:{args.port}", "--noreload"])


if __name__ == "__main__":
    main()
