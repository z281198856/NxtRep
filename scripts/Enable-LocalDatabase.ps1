[CmdletBinding()]
param(
    [switch]$Elevated,
    [ValidatePattern('^S-1-5-21-\d+-\d+-\d+-\d+$')][string]$UserSid
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$stateDir = Join-Path $root '.local'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$receipt = Join-Path $stateDir 'database-service-setup.json'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $UserSid) { $UserSid = $identity.User.Value }
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    if ($Elevated) { throw 'Windows administrator elevation was not granted.' }
    Write-Host 'One-time Windows approval: allow your account to start/stop this PostgreSQL service; keep Manual startup.'
    $argsList = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Elevated -UserSid {1}' -f $PSCommandPath, $UserSid
    $child = Start-Process -FilePath 'powershell.exe' -ArgumentList $argsList -Verb RunAs -WindowStyle Hidden -PassThru
    while (-not $child.HasExited) { Start-Sleep -Milliseconds 500; $child.Refresh() }
    if ($child.ExitCode -ne 0) { throw "Database service setup failed. See $receipt" }
    Get-Content -LiteralPath $receipt
    exit 0
}
try {
    $service = Get-Service -Name 'postgresql-x64-17'
    $before = @{ status = [string]$service.Status; startType = [string]$service.StartType }
    $sddl = (& sc.exe sdshow $service.Name | Where-Object { $_ -match '^D:' } | Select-Object -First 1).Trim()
    if (-not $sddl) { throw 'Cannot read the existing service ACL.' }
    $backup = Join-Path $stateDir 'postgresql-service-acl-before.json'
    if (-not (Test-Path -LiteralPath $backup)) {
        @{ service = $service.Name; sddl = $sddl; startup = $before.startType } |
            ConvertTo-Json | Set-Content -LiteralPath $backup -Encoding UTF8
    }
    $descriptor = New-Object Security.AccessControl.RawSecurityDescriptor($sddl)
    $sid = New-Object Security.Principal.SecurityIdentifier($UserSid)
    $granted = 0
    foreach ($ace in $descriptor.DiscretionaryAcl) {
        if ($ace -is [Security.AccessControl.CommonAce] -and
            $ace.SecurityIdentifier -eq $sid -and
            $ace.AceQualifier -eq [Security.AccessControl.AceQualifier]::AccessAllowed) {
            $granted = $granted -bor $ace.AccessMask
        }
    }
    # SERVICE_START (0x10) and SERVICE_STOP (0x20) only. Preserve all existing ACEs.
    if (($granted -band 0x30) -ne 0x30) {
        $ace = New-Object Security.AccessControl.CommonAce(
            [Security.AccessControl.AceFlags]::None,
            [Security.AccessControl.AceQualifier]::AccessAllowed, 0x30, $sid, $false, $null)
        $descriptor.DiscretionaryAcl.InsertAce($descriptor.DiscretionaryAcl.Count, $ace)
        $newSddl = $descriptor.GetSddlForm([Security.AccessControl.AccessControlSections]::Access)
        $result = & sc.exe sdset $service.Name $newSddl
        if ($LASTEXITCODE -ne 0) { throw "Cannot grant start/stop access: $result" }
    }
    if ($service.Status -ne 'Running') {
        if (Get-NetTCPConnection -LocalPort 5432 -State Listen -ErrorAction SilentlyContinue) {
            throw 'Port 5432 is already used while the PostgreSQL service is stopped. Stop the known temporary instance first; no process was stopped automatically.'
        }
        Start-Service -Name $service.Name
        $service.WaitForStatus('Running', [TimeSpan]::FromSeconds(45))
    }
    Set-Service -Name $service.Name -StartupType Manual
    @{ success = $true; service = $service.Name; before = $before; status = 'Running'; startType = 'Manual'; userSid = $UserSid; grantedRights = 'SERVICE_START, SERVICE_STOP' } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receipt -Encoding UTF8
} catch {
    @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json |
        Set-Content -LiteralPath $receipt -Encoding UTF8
    exit 1
}
