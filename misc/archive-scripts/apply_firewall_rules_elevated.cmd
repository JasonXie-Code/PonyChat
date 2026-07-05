@echo off
chcp 65001>nul
netsh advfirewall firewall delete rule name="PonyChat Backend (TCP 5000)" >nul 2>nul
netsh advfirewall firewall add rule name="PonyChat Backend (TCP 5000)" dir=in action=allow protocol=TCP localport=5000 profile=private
netsh advfirewall firewall delete rule name="PonyChat LAN HTTPS Proxy (TCP 5001)" >nul 2>nul
netsh advfirewall firewall add rule name="PonyChat LAN HTTPS Proxy (TCP 5001)" dir=in action=allow protocol=TCP localport=5001 profile=private
exit /b %errorlevel%
