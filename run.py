"""Start the local dashboard with Python or the workspace dependency install."""

import argparse
import os
import sys
from pathlib import Path


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


def main():
    load_env(Path(__file__).resolve().parent / ".env")
    # The first provider with a key in .env is used: OpenAI, then Gemini.
    for name, url, model in (("OPENAI", OPENAI_URL, "gpt-4o-mini"), ("GEMINI", GEMINI_URL, "gemini-flash-lite-latest")):
        key = os.getenv(f"{name}_API_KEY", "").strip()
        if key and not os.getenv("GUIDANCE_LLM_URL"):
            os.environ["GUIDANCE_LLM_URL"] = url
            os.environ["GUIDANCE_LLM_MODEL"] = os.getenv(f"{name}_MODEL", model)
            os.environ["GUIDANCE_LLM_KEY"] = key

    parser = argparse.ArgumentParser(description="Start the local course guidance dashboard")
    parser.add_argument("--gemma", action="store_true", help="Use Gemma 4 31B through Hugging Face")
    parser.add_argument("--port", type=int, default=8000, help="Dashboard port (default 8000)")
    args = parser.parse_args()
    if args.gemma:
        token = os.getenv("HF_TOKEN", "").strip()
        if not token:
            parser.error("--gemma requires HF_TOKEN with Inference Providers permission")
        os.environ["GUIDANCE_LLM_URL"] = "https://router.huggingface.co/v1/chat/completions"
        os.environ["GUIDANCE_LLM_MODEL"] = "google/gemma-4-31B-it"
        os.environ["GUIDANCE_LLM_KEY"] = token

    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    local_packages = root / ".venv-deps"
    if local_packages.is_dir():
        sys.path.append(str(local_packages))

    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
