# Start the CHEETAAAH server inside WSL and forward the port for the phone.
# Put a shortcut to this in shell:startup, or run it before a meeting.
#   powershell -ExecutionPolicy Bypass -File start.ps1
wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/Imart/Desktop/Issues/CHEETAAAH && (pgrep -f 'python3 server.py' >/dev/null || nohup python3 server.py > /tmp/cheetaaah.log 2>&1 &) ; sleep 1; pgrep -f 'python3 server.py' >/dev/null && echo 'server running on 8787'"
if ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) {
  & "$PSScriptRoot\phone-access.ps1"
} else {
  Write-Host "Not admin: port forward for the phone not refreshed (run phone-access.ps1 as admin once per boot)."
}
Start-Process "http://localhost:8787"
