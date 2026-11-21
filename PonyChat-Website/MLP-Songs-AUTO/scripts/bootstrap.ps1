$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Tools = "P:\PonyChat\misc\tools"
$Python = Join-Path $Tools "python\python.exe"
$Jdk = Join-Path $Tools "jdk-17\bin\java.exe"
$AudiverisDir = Join-Path $Tools "audiveris"
$AudiverisDownloads = Join-Path $AudiverisDir "downloads"
$AudiverisExtracted = Join-Path $AudiverisDir "extracted"
$OsmdDir = Join-Path $Tools "opensheetmusicdisplay"

if (!(Test-Path $Python)) {
  throw "Python not found: $Python"
}
if (!(Test-Path $Jdk)) {
  throw "JDK 17 not found: $Jdk"
}

Write-Host "[bootstrap] Using Python: $Python"
Write-Host "[bootstrap] Using JDK: $Jdk"

& $Python -m pip install -q -U pip
& $Python -m pip install -q -r (Join-Path $Root "app\requirements.txt")

New-Item -ItemType Directory -Force $OsmdDir | Out-Null
$osmd = Join-Path $OsmdDir "opensheetmusicdisplay.min.js"
if (!(Test-Path $osmd)) {
  Write-Host "[bootstrap] Downloading OpenSheetMusicDisplay"
  Invoke-WebRequest -Uri "https://cdn.jsdelivr.net/npm/opensheetmusicdisplay@1.9.2/build/opensheetmusicdisplay.min.js" -OutFile $osmd -Headers @{ "User-Agent" = "PonyChat-MLP-Songs-AUTO" }
}
New-Item -ItemType Directory -Force (Join-Path $Root "web\vendor") | Out-Null
Copy-Item -Force $osmd (Join-Path $Root "web\vendor\opensheetmusicdisplay.min.js")

New-Item -ItemType Directory -Force $AudiverisDownloads, $AudiverisExtracted | Out-Null

$existing = Get-ChildItem -Path $AudiverisDir -Recurse -File -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -match "^(Audiveris|audiveris)(\.bat|\.cmd|\.exe)?$" -or $_.Name -match "audiveris.*\.jar$" } |
  Select-Object -First 1

if ($existing) {
  Write-Host "[bootstrap] Audiveris candidate already present: $($existing.FullName)"
  exit 0
}

Write-Host "[bootstrap] Audiveris not found. Querying GitHub latest release..."
$release = Invoke-RestMethod -Uri "https://api.github.com/repos/Audiveris/audiveris/releases/latest" -Headers @{ "User-Agent" = "PonyChat-MLP-Songs-AUTO" }
$asset = $release.assets |
  Where-Object { $_.name -like "*windowsConsole*x86_64.msi" } |
  Select-Object -First 1
if (!$asset) {
  $asset = $release.assets | Where-Object { $_.name -like "*windows*x86_64.msi" } | Select-Object -First 1
}
if (!$asset) {
  throw "No Windows Audiveris MSI asset found in latest release."
}

$msi = Join-Path $AudiverisDownloads $asset.name
if (!(Test-Path $msi)) {
  Write-Host "[bootstrap] Downloading $($asset.name)"
  Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $msi -Headers @{ "User-Agent" = "PonyChat-MLP-Songs-AUTO" }
}

Write-Host "[bootstrap] Extracting MSI to $AudiverisExtracted"
$args = @("/a", $msi, "/qn", "TARGETDIR=$AudiverisExtracted")
$p = Start-Process -FilePath "msiexec.exe" -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
if ($p.ExitCode -ne 0) {
  Write-Warning "msiexec extraction returned $($p.ExitCode). The MSI is still downloaded at $msi."
} else {
  Write-Host "[bootstrap] Audiveris MSI extracted."
}

$found = Get-ChildItem -Path $AudiverisDir -Recurse -File -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -match "^(Audiveris|audiveris)(\.bat|\.cmd|\.exe)?$" -or $_.Name -match "audiveris.*\.jar$" } |
  Select-Object -First 1

if ($found) {
  Write-Host "[bootstrap] Audiveris candidate: $($found.FullName)"
} else {
  Write-Warning "Audiveris was downloaded but no command launcher was found. build_demo.ps1 will report OMR unavailable."
}
