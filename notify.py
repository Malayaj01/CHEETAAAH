"""Tell the owner a meeting is ready (or failed). Channels, in order of what needs
nothing from you: Windows toast (via PowerShell, works from WSL) -> Slack webhook ->
mail. Set the channel in dispo-analysis/.env:

    NOTIFY=toast                      # default when running under WSL/Windows
    NOTIFY=slack  SLACK_WEBHOOK=https://hooks.slack.com/...
    NOTIFY=off

Mail is deliberately not here: no credentials, and this project never sends mail
from code — drafts only, created on request."""
import os
import re
import shutil
import subprocess

import config

BASE_URL = os.environ.get("CHEETAAAH_URL", "http://localhost:8787")


def _setting(key, default=None):
    if config.ENV.exists():
        m = re.search(rf'^{key}\s*=\s*["\']?([^"\'\s]+)', config.ENV.read_text(errors="ignore"), re.M)
        if m:
            return m.group(1)
    return os.environ.get(key, default)


def _text(meta, st):
    if st.get("state") == "failed":
        return f"{meta['title']} — processing failed", (st.get("error") or "")[-120:]
    if st.get("state") == "executed":
        return (f"{meta['title']} — executed",
                f"{st.get('applied', 0)} applied, {st.get('blocked', 0)} blocked")
    return (f"{meta['title']} — ready for review",
            f"{st.get('decisions', 0)} decisions · {st.get('actionables', 0)} actionables · "
            f"{st.get('reversals', 0)} reversal(s)")


def _toast(title, body, url):
    ps = shutil.which("powershell.exe") or "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = @"
<toast activationType="protocol" launch="{url}">
  <visual><binding template="ToastGeneric"><text>CHEETAAAH</text><text>{title}</text><text>{body}</text></binding></visual>
</toast>
"@
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument; $doc.LoadXml($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("CHEETAAAH").Show($doc)
"""
    subprocess.run([ps, "-NoProfile", "-Command", script], timeout=20,
                   capture_output=True, text=True)


def _slack(title, body, url):
    import requests
    hook = _setting("SLACK_WEBHOOK")
    if hook:
        requests.post(hook, json={"text": f"*{title}*\n{body}\n{url}"}, timeout=15)


def send(meeting_id, meta, st):
    """Never raises: a failed notification must not fail the pipeline."""
    channel = _setting("NOTIFY", "toast")
    if channel == "off":
        return
    title, body = _text(meta, st)
    url = f"{BASE_URL}/m/{meeting_id}"
    try:
        if channel == "slack":
            _slack(title, body, url)
        else:
            _toast(title.replace('"', "'"), body.replace('"', "'"), url)
    except Exception:
        pass
