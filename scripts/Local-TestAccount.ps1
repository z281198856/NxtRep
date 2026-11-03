[CmdletBinding()]
param([switch]$Setup, [switch]$Show)
. "$PSScriptRoot/Local.Common.ps1"
$path = Join-Path $LocalDir 'test-account.xml'
$bindingPath = Join-Path $LocalDir 'test-account-database.json'
if ($Setup) {
    $database = (Invoke-Helper @('inspect')) | ConvertFrom-Json
    $binding = Read-LocalJson $bindingPath
    if ($binding -and $binding.binding -ne $database.binding) {
        throw 'The saved test account belongs to another database. No account or password was changed.'
    }
    if (-not (Test-Path -LiteralPath $path)) {
        if ($binding) { throw 'Credential file is missing. Restore it or choose a new dedicated test account explicitly.' }
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $digits = ''
            while ($digits.Length -lt 30) {
                $bytes = New-Object byte[] 64
                $rng.GetBytes($bytes)
                foreach ($b in $bytes) { if ($b -lt 250) { $digits += [string]($b % 10) } }
            }
        } finally { $rng.Dispose() }
        $username = '90' + $digits.Substring(0, 8)
        $secure = ConvertTo-SecureString $digits.Substring(8, 20) -AsPlainText -Force
        $credential = New-Object Management.Automation.PSCredential($username, $secure)
        # Export-Clixml uses DPAPI for PSCredential on Windows (same machine/user only).
        $credential | Export-Clixml -LiteralPath $path
        Save-LocalJson $bindingPath $database
        $digits = $null
    } elseif (-not $binding) { throw 'Missing database binding for the saved credential.' }
    $credential = Get-TestCredential
    $payload = @{ username = $credential.UserName; password = $credential.GetNetworkCredential().Password } | ConvertTo-Json
    $result = $payload | & $Python $Helper account
    $payload = $null
    if ($LASTEXITCODE -ne 0) { throw 'Test-account setup failed; the saved password was not reset.' }
    Write-Host "Test account ready: $($credential.UserName). Credential is encrypted in .local/test-account.xml."
}
if ($Show) {
    $credential = Get-TestCredential
    Write-Host "Username: $($credential.UserName)"
    Write-Host "Password: $($credential.GetNetworkCredential().Password)"
}
if (-not $Setup -and -not $Show) { Write-Host 'Use -Setup once, or -Show to view the credential locally.' }
