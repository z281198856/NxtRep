[CmdletBinding()]
param([switch]$Database, [switch]$Emulator)
. "$PSScriptRoot/Local.Common.ps1"
$mutex = New-Object Threading.Mutex($false, 'Local\NxtRep-Local-Launch')
if (-not $mutex.WaitOne(0)) { $mutex.Dispose(); throw 'Another NxtRep start/stop is in progress.' }
try {
$api = Read-LocalJson (Join-Path $LocalDir 'api.json')
if (Test-OwnedApi $api) {
    Stop-Process -Id $api.pid
    Wait-Process -Id $api.pid -Timeout 15 -ErrorAction SilentlyContinue
    Write-Host 'Stopped the NxtRep API.'
}
$sessionPath = Join-Path $LocalDir 'session.json'
$session = Read-LocalJson $sessionPath
if ($Database -or ($session -and $session.databaseStarted)) {
    $listener = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    if ($listener.Count -gt 0) { throw 'An unmanaged API is still listening on port 8000; database was left running.' }
    Stop-Service -Name 'postgresql-x64-17'
    (Get-Service 'postgresql-x64-17').WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
    Write-Host 'Stopped PostgreSQL; database files are retained. Startup remains Manual.'
    if ($session) { $session.databaseStarted = $false }
}
if ($session -and $session.serial -and ($Emulator -or $session.emulatorStarted)) {
    $script:Adb = (Get-Command adb).Source
    $devices = Invoke-Adb @('devices')
    if ($devices -match "(?m)^$([regex]::Escape($session.serial))\s+device") {
        $null = Invoke-Adb @('-s', $session.serial, 'emu', 'kill')
        $closed = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            $devices = Invoke-Adb @('devices')
            if ($devices -notmatch "(?m)^$([regex]::Escape($session.serial))\s+") { $closed = $true; break }
            Start-Sleep -Seconds 1
        }
        if (-not $closed) { throw 'Emulator shutdown was requested but it is still connected.' }
        Write-Host 'Closed the Android emulator.'
    }
    $session.emulatorStarted = $false
}
if ($session) { Save-LocalJson $sessionPath $session }
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
