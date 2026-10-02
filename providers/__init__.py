"""Context providers — knowledge the organisation already has, fed to the pipeline
before extraction. Providers ENRICH only: they never create decisions or actionables,
never execute anything, and are read-only against their source.

Each provider implements some of:
    attendees(start_iso, end_iso) -> {"title": str, "attendees": [{"name","email","team"}]}
    person(name_or_email)          -> {"name","email","team"} | None
    repos()                        -> [{"name","path_or_url","owners":[...]}]
    owners(repo, path)             -> [names]
    messages(channel, since_iso)   -> [{"who","when","text"}]

Enable providers in providers/config.yaml:
    calendar: google      # -> providers/calendar_google.py  (to be written)
    directory: null
    repos: null
    chat: null

Profiles: IndiaMART = Google Calendar + Workspace directory + Google Chat + GitHub org.
Generic  = Outlook/Teams or Slack + GitLab. Same interface, different adapters.
"""
import importlib
import pathlib

import yaml

HERE = pathlib.Path(__file__).parent
CONFIG = HERE / "config.yaml"


def _load(kind):
    cfg = yaml.safe_load(CONFIG.read_text()) if CONFIG.exists() else {}
    name = (cfg or {}).get(kind)
    if not name:
        return None
    try:
        return importlib.import_module(f"providers.{kind}_{name}")
    except ModuleNotFoundError:
        return None


def context(meta):
    """Everything the pipeline wants to know before extraction. Missing providers
    simply contribute nothing — the pipeline runs identically without them."""
    out = {}
    cal = _load("calendar")
    if cal and meta.get("start") and meta.get("end"):
        try:
            ev = cal.attendees(meta["start"], meta["end"])
            if ev:
                out.update(ev)
        except Exception as e:          # a provider failing must never fail the meeting
            out["calendar_error"] = str(e)[:200]
    repos = _load("repos")
    if repos:
        try:
            out["repos"] = repos.repos()
        except Exception as e:
            out["repos_error"] = str(e)[:200]
    return out
