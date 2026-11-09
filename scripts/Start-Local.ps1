[CmdletBinding()]
param(
    [switch]$BackendOnly,
    [switch]$Lan,
    [switch]$Rebuild,
    [switch]$RestartBackend,
    [switch]$LoginTestAccount,
    [string]$Device,
    [ValidatePattern('^[a-zA-Z0-9_.-]+$')][string]$Avd = 'Pixel_8'
)
. "$PSScriptRoot/Local.Common.ps1"
$mutex = New-Object Threading.Mutex($false, 'Local\NxtRep-Local-Launch')
if (-not $mutex.WaitOne(0)) { $mutex.Dispose(); throw 'Another NxtRep launch is already in progress.' }
try {
    Write-Host '[1/4] Checking the configured PostgreSQL service...'
    $sessionPath = Join-Path $LocalDir 'session.json'
    $previous = Read-LocalJson $sessionPath
    $session = @{ databaseStarted = $false; emulatorStarted = $false; serial = $null }
    if ($previous) {
        $session.databaseStarted = [bool]$previous.databaseStarted
        $session.emulatorStarted = [bool]$previous.emulatorStarted
        $session.serial = $previous.serial
    }
    $service = Get-Service 'postgresql-x64-17'
    if ($service.StartType -ne 'Manual') {
        throw 'PostgreSQL must use Manual startup. Run scripts/Enable-LocalDatabase.ps1 once.'
    }
    if ($service.Status -ne 'Running') {
        if (Get-NetTCPConnection -LocalPort 5432 -State Listen -ErrorAction SilentlyContinue) {
            throw 'Port 5432 is occupied by a different database instance. No automatic database switch was made.'
        }
        try { Start-Service $service.Name } catch {
            throw 'Cannot start PostgreSQL. Run scripts/Enable-LocalDatabase.ps1 once under your normal Windows account.'
        }
        $service.WaitForStatus('Running', [TimeSpan]::FromSeconds(45))
        $session.databaseStarted = $true
        Save-LocalJson $sessionPath $session
    }
    $database = (Invoke-Helper @('inspect')) | ConvertFrom-Json
    Write-Host "Database: $($database.host):$($database.port)/$($database.database) (from backend/.env)"

    Write-Host '[2/4] Checking local API...'
    $apiPath = Join-Path $LocalDir 'api.json'
    $apiState = Read-LocalJson $apiPath
    $listener = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    $signature = Invoke-Helper @('fingerprint', '--area', 'backend')
    $apiHost = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
    if ($listener.Count -gt 0) {
        if (-not (Test-OwnedApi $apiState) -or $listener[0].OwningProcess -ne $apiState.pid) {
            throw 'Port 8000 belongs to an unmanaged process. Stop that API explicitly before using this launcher.'
        }
        if ($RestartBackend) {
            Stop-Process -Id $apiState.pid
            Wait-Process -Id $apiState.pid -Timeout 15 -ErrorAction SilentlyContinue
            $listener = @()
        } elseif (($apiState.host -and $apiState.host -ne $apiHost) -or (-not $apiState.host -and $Lan)) {
            throw 'API binding changed. Add -RestartBackend to explicitly restart with the requested -Lan setting.'
        } elseif ($apiState.signature -ne $signature) {
            throw 'Backend code/config changed. Run Start-NxtRep.cmd -RestartBackend to reload it.'
        } elseif (-not (Test-ApiReady)) {
            throw 'The existing managed API is not ready. Inspect .local/api.err.log or use -RestartBackend.'
        } else { Write-Host 'Reusing the running API.' }
    }
    if ($listener.Count -eq 0) {
        $runId = [guid]::NewGuid().ToString('N')
        $arguments = '"{0}" serve --run-id {1} --host {2}' -f $Helper, $runId, $apiHost
        $api = Start-Process -FilePath $Python -ArgumentList $arguments -WorkingDirectory (Join-Path $RepoRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $LocalDir 'api.out.log') -RedirectStandardError (Join-Path $LocalDir 'api.err.log')
        $ready = $false
        for ($attempt = 0; $attempt -lt 45; $attempt++) {
            $apiState = Read-LocalJson $apiPath
            if ($apiState -and $apiState.runId -eq $runId -and (Test-ApiReady)) {
                $active = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
                if ($active.Count -gt 0 -and $active[0].OwningProcess -eq $apiState.pid) { $ready = $true; break }
            }
            if ($api.HasExited) { break }
            Start-Sleep -Seconds 1
        }
        if (-not $ready) { throw 'API did not become ready. Inspect .local/api.err.log.' }
    }
    Write-Host 'API ready: http://127.0.0.1:8000/api/v1/health/ready'
    if ($Lan) { Write-Host 'LAN mode: API listens on local network interfaces. Database settings are unchanged; firewall access must be scoped separately.' }
    if ($LoginTestAccount) { & "$PSScriptRoot/Local-TestAccount.ps1" -Setup }
    if ($BackendOnly) { return }

    Write-Host '[3/4] Reusing or starting the Android emulator...'
    $script:Adb = (Get-Command adb -ErrorAction Stop).Source
    $sdk = Split-Path (Split-Path $Adb -Parent) -Parent
    $null = Invoke-Adb @('start-server')
    $devices = Invoke-Adb @('devices')
    $online = @([regex]::Matches($devices, '(?m)^(emulator-\d+)\s+device\s*$') | ForEach-Object { $_.Groups[1].Value })
    if ($Device) {
        if ($Device -notin $online) { throw "Requested emulator $Device is not online." }
        $serial = $Device
    } elseif ($online.Count -gt 0) { $serial = $online[0] } else {
        $emulator = Join-Path $sdk 'emulator/emulator.exe'
        if (-not (Test-Path -LiteralPath $emulator)) { throw 'Cannot find emulator.exe beside the adb SDK.' }
        $available = & $emulator -list-avds
        if ($Avd -notin $available) { throw "AVD $Avd does not exist. Available: $available" }
        # Visible because this is the interactive emulator the user asked to use.
        $emulatorProcess = Start-Process -FilePath $emulator -ArgumentList @('-avd', $Avd) -WindowStyle Normal -PassThru
        $serial = $null
        for ($attempt = 0; $attempt -lt 90; $attempt++) {
            $devices = Invoke-Adb @('devices')
            $matches = [regex]::Matches($devices, '(?m)^(emulator-\d+)\s+device\s*$')
            foreach ($match in $matches) {
                $candidate = $match.Groups[1].Value
                if ((Invoke-Adb @('-s', $candidate, 'emu', 'avd', 'name')) -match "(?m)^$([regex]::Escape($Avd))\r?$") { $serial = $candidate; break }
            }
            if ($serial) { break }
            if ($attempt % 10 -eq 0) { Write-Host 'Waiting for emulator startup...' }
            Start-Sleep -Seconds 2
        }
        if (-not $serial) { throw 'Emulator did not connect within 180 seconds.' }
        $session.emulatorStarted = $true
    }
    $session.serial = $serial
    Save-LocalJson $sessionPath $session
    $booted = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ((Invoke-Adb @('-s', $serial, 'shell', 'getprop', 'sys.boot_completed')) -eq '1') { $booted = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $booted) { throw 'Emulator is connected but Android has not finished booting.' }

    Write-Host '[4/4] Checking the app build...'
    $apk = Join-Path $LocalDir 'nxtrep-main-debug.apk'
    $buildStatePath = Join-Path $LocalDir 'android-build.json'
    $buildState = Read-LocalJson $buildStatePath
    $sourceHash = Invoke-Helper @('fingerprint', '--area', 'frontend')
    $cached = $false
    if ($buildState -and (Test-Path -LiteralPath $apk)) {
        $cached = ($buildState.sourceHash -eq $sourceHash -and (Get-LocalFileHash $apk) -eq $buildState.apkHash)
    }
    if ($Rebuild -or -not $cached) {
        Write-Host 'Building the normal app entrypoint. Later unchanged launches reuse this APK.'
        $priorJava = $env:JAVA_TOOL_OPTIONS
        $env:JAVA_TOOL_OPTIONS = ($priorJava + ' -Djdk.net.unixdomain.tmpdir=C:\Windows\Temp').Trim()
        Push-Location (Join-Path $RepoRoot 'frontend')
        try {
            & flutter build apk --debug --target lib/main.dart --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1
            if ($LASTEXITCODE -ne 0) { throw 'Flutter build failed.' }
        } finally { Pop-Location; $env:JAVA_TOOL_OPTIONS = $priorJava }
        Copy-Item -LiteralPath (Join-Path $RepoRoot 'frontend/build/app/outputs/flutter-apk/app-debug.apk') -Destination $apk -Force
        $buildState = @{ sourceHash = (Invoke-Helper @('fingerprint', '--area', 'frontend')); apkHash = (Get-LocalFileHash $apk) }
        Save-LocalJson $buildStatePath $buildState
    } else { Write-Host 'Source unchanged; skipping Flutter build.' }
    # pm path returns exit 1 when absent (also after Flutter integration tests).
    # Listing packages succeeds for an empty result, allowing the first install.
    $packages = Invoke-Adb @('-s', $serial, 'shell', 'pm', 'list', 'packages', 'com.zengsiqi.nxtrep')
    $packagePath = ''
    if ($packages -match '(?m)^package:com\.zengsiqi\.nxtrep\s*$') {
        $packagePath = Invoke-Adb @('-s', $serial, 'shell', 'pm', 'path', 'com.zengsiqi.nxtrep')
    }
    $installedHash = ''
    if ($packagePath -match 'package:([^\r\n]+base\.apk)') {
        $installedHash = ((Invoke-Adb @('-s', $serial, 'shell', 'sha256sum', $Matches[1])) -split '\s+')[0]
    }
    if ($installedHash -ne $buildState.apkHash) {
        $null = Invoke-Adb @('-s', $serial, 'install', '-r', $apk)
    } else { Write-Host 'Current APK is already installed; preserving the app session.' }
    $null = Invoke-Adb @('-s', $serial, 'shell', 'am', 'start', '-W', '-n', 'com.zengsiqi.nxtrep/.MainActivity')

    if ($LoginTestAccount) {
        $loginLabel = [string][char]0x767B + [char]0x5F55
        $ui = $null
        for ($attempt = 0; $attempt -lt 10; $attempt++) {
            $ui = Get-DeviceUi $serial
            if ($ui.SelectSingleNode("//node[@content-desc='$loginLabel']") -or
                $ui.SelectSingleNode("//node[contains(@content-desc,'Tab 1 of 6')]")) { break }
            Start-Sleep -Seconds 1
        }
        if ($ui.SelectSingleNode("//node[@content-desc='$loginLabel']")) {
            $credential = Get-TestCredential
            foreach ($passwordField in @($false, $true)) {
                $ui = Get-DeviceUi $serial
                $field = $ui.SelectSingleNode("//node[@class='android.widget.EditText' and @password='$($passwordField.ToString().ToLower())']")
                if (-not $field) { throw 'Login field unavailable. The app is open for manual login.' }
                Tap-Node $serial $field
                $null = Invoke-Adb @('-s', $serial, 'shell', 'input', 'keyevent', '123')
                $erase = @('-s', $serial, 'shell', 'input', 'keyevent', '--delay', '1') + @(1..128 | ForEach-Object { '67' })
                $null = Invoke-Adb $erase
                $value = if ($passwordField) { $credential.GetNetworkCredential().Password } else { $credential.UserName }
                $null = Invoke-Adb @('-s', $serial, 'shell', 'input', 'text', $value)
                $value = $null
            }
            $ui = Get-DeviceUi $serial
            # mInputShown can remain true with a hardware keyboard although no
            # IME is visible. Back would then leave the app and clear the form.
            if ($ui.SelectSingleNode("//node[contains(@package,'inputmethod')]")) {
                $null = Invoke-Adb @('-s', $serial, 'shell', 'input', 'keyevent', '4')
                $ui = Get-DeviceUi $serial
            }
            Tap-Node $serial ($ui.SelectSingleNode("//node[@content-desc='$loginLabel']"))
            $loggedIn = $false
            for ($attempt = 0; $attempt -lt 10; $attempt++) {
                $ui = Get-DeviceUi $serial
                if ($ui.SelectSingleNode("//node[contains(@content-desc,'Tab 1 of 6')]")) { $loggedIn = $true; break }
                Start-Sleep -Seconds 1
            }
            if (-not $loggedIn) { throw 'App is open, but automatic test login did not reach home. Inspect the screen; no retry loop or password reset was performed.' }
            Write-Host 'Dedicated test account logged in successfully.'
        } elseif ($ui.SelectSingleNode("//node[contains(@content-desc,'Tab 1 of 6')]")) {
            Write-Host 'Existing app session preserved.'
        } else { throw 'App opened but neither login nor home became visible. Inspect the emulator.' }
    }
    Write-Host "NxtRep is open on $serial. Run Stop-NxtRep.cmd when finished."
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
