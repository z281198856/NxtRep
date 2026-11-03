$ErrorActionPreference = 'Stop'
$script:RepoRoot = Split-Path $PSScriptRoot -Parent
$script:LocalDir = Join-Path $RepoRoot '.local'
$script:Python = Join-Path $RepoRoot 'backend/.venv/Scripts/python.exe'
$script:Helper = Join-Path $PSScriptRoot 'local_runtime.py'
New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null

function Invoke-Helper([string[]]$Arguments) {
    $result = & $Python $Helper @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Local preflight failed: $($Arguments[0])" }
    return ($result -join "`n").Trim()
}

function Read-LocalJson([string]$Path) {
    if (Test-Path -LiteralPath $Path) { return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json }
    return $null
}

function Save-LocalJson([string]$Path, $Value) {
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-LocalFileHash([string]$Path) {
    # Works in Windows PowerShell even when inherited PSModulePath hides Get-FileHash.
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}

function Test-OwnedApi($State) {
    if (-not $State) { return $false }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$State.pid)" -ErrorAction SilentlyContinue
    return ($null -ne $process -and $process.CommandLine -like '*local_runtime.py*' -and
        $process.CommandLine -like "*--run-id $($State.runId)*")
}

function Test-ApiReady {
    try {
        $response = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health/ready' -TimeoutSec 3
        return ($response.status -eq 'ready')
    } catch { return $false }
}

function Get-TestCredential {
    $path = Join-Path $LocalDir 'test-account.xml'
    if (-not (Test-Path -LiteralPath $path)) { throw 'Run scripts/Local-TestAccount.ps1 -Setup first.' }
    try { return Import-Clixml -LiteralPath $path } catch {
        throw 'Windows could not decrypt the test account. Run under the same Windows user that saved it.'
    }
}

function Invoke-Adb([string[]]$Arguments) {
    $result = & $script:Adb @Arguments
    if ($LASTEXITCODE -ne 0) { throw "adb failed: $($Arguments[0])" }
    return ($result -join "`n").Trim()
}

function Get-DeviceUi([string]$Serial) {
    # A failed Android dump can leave an old file behind: never accept stale UI evidence.
    $dumpPath = '/sdcard/nxtrep-launcher-' + [guid]::NewGuid().ToString('N') + '.xml'
    try {
        for ($attempt = 0; $attempt -lt 3; $attempt++) {
            $result = Invoke-Adb @('-s', $Serial, 'shell', 'uiautomator', 'dump', $dumpPath)
            if ($result -match 'dumped to:') {
                return [xml](Invoke-Adb @('-s', $Serial, 'shell', 'cat', $dumpPath))
            }
            Start-Sleep -Seconds 1
        }
        throw 'Android did not return a fresh UI hierarchy. Inspect the emulator.'
    } finally {
        $null = Invoke-Adb @('-s', $Serial, 'shell', 'rm', '-f', $dumpPath)
    }
}

function Tap-Node([string]$Serial, $Node) {
    $coords = [regex]::Matches($Node.bounds, '\d+') | ForEach-Object { [int]$_.Value }
    if ($coords.Count -ne 4) { throw 'Cannot determine control position.' }
    $null = Invoke-Adb @('-s', $Serial, 'shell', 'input', 'tap',
        [string][int](($coords[0]+$coords[2])/2), [string][int](($coords[1]+$coords[3])/2))
}
