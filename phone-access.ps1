# Run once in an ADMIN PowerShell after each reboot (WSL's address changes).
# Forwards port 8787 from Windows to WSL so the phone can open http://<laptop-ip>:8787
$wsl = (wsl hostname -I).Trim().Split(" ")[0]
netsh interface portproxy delete v4tov4 listenport=8787 listenaddress=0.0.0.0 2>$null | Out-Null
netsh interface portproxy add v4tov4 listenport=8787 listenaddress=0.0.0.0 connectport=8787 connectaddress=$wsl
netsh advfirewall firewall delete rule name="CHEETAAAH 8787" 2>$null | Out-Null
netsh advfirewall firewall add rule name="CHEETAAAH 8787" dir=in action=allow protocol=TCP localport=8787
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.InterfaceAlias -match 'Wi-Fi|Ethernet' -and $_.IPAddress -notlike '169.*'} | Select-Object -First 1).IPAddress
Write-Host "Forwarding 8787 -> WSL $wsl.  On the phone open:  http://$ip:8787"
