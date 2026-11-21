$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = "P:\PonyChat\misc\tools\python\python.exe"
if (!(Test-Path $Python)) { throw "Python not found: $Python" }
& $Python (Join-Path $Root "scripts\build_demo.py")
