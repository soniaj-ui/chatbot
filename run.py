"""Start the Django telecaller: read keys from .env, apply migrations and run the server."""

import argparse
import os
import sys
from pathlib import Path

from telecaller.env import configure_model, load_env

ROOT = Path(__file__).resolve().parent


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
