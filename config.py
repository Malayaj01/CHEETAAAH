"""Shared settings for CHEETAAAH. Credentials come from the environment
(LLM_BASE_URL / LLM_API_KEY) or from a .env file — never from the command line or source."""
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"                    # meetings/, decisions.db
PROJECTS = HERE / "projects"            # one yaml per project the agent may touch
ENV = pathlib.Path(os.environ.get("CHEETAAAH_ENV", HERE / ".env"))

TRANSCRIBE_MODEL = "google/gemini-3.6-flash"    # takes audio natively, good Hinglish
EXTRACT_MODEL = "anthropic/claude-sonnet-5"      # schema-enforced JSON
JUDGE_MODEL = "anthropic/claude-sonnet-5"        # same / refines / reverses / unrelated


def creds():
    if os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_API_KEY"):
        return os.environ["LLM_BASE_URL"].rstrip("/"), os.environ["LLM_API_KEY"]
    if ENV.exists():
        txt = ENV.read_text(encoding="utf-8", errors="ignore")
        k = re.search(r'LLM_API_KEY\s*=\s*["\']?([^"\'\s]+)', txt)
        b = re.search(r'LLM_BASE_URL\s*=\s*["\']?([^"\'\s]+)', txt)
        if k and b:
            return b.group(1).rstrip("/"), k.group(1)
    sys.exit(f"No credentials: expected LLM_BASE_URL / LLM_API_KEY in {ENV}")
