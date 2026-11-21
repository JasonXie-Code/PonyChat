$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = "P:\PonyChat\misc\tools\python\python.exe"
if (!(Test-Path $Python)) { $Python = "python" }
Set-Location (Join-Path $Root "app")
& $Python -m uvicorn main:app --host 127.0.0.1 --port 8777 --reload
