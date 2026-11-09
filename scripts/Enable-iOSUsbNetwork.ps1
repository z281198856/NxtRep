[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this helper as administrator to add the scoped iPhone USB firewall rule.'
}
$usbLinks = @(Get-NetIPConfiguration | Where-Object {
    $_.InterfaceDescription -eq 'Apple Mobile Device Ethernet' -and $_.IPv4DefaultGateway
})
if ($usbLinks.Count -ne 1) { throw 'Expected one connected Apple USB network interface.' }
$usbLink = $usbLinks[0]
$localAddress = [string]$usbLink.IPv4Address.IPAddress
$phoneAddress = [string]$usbLink.IPv4DefaultGateway.NextHop
if ($localAddress -notlike '172.20.10.*' -or $phoneAddress -ne '172.20.10.1') {
    throw 'Unexpected Apple USB subnet. No firewall rule was changed.'
}
$ruleName = 'NxtRep-iPhone-USB-API'
$existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($existing) { Remove-NetFirewallRule -Name $ruleName }
New-NetFirewallRule -Name $ruleName -DisplayName 'NxtRep API from this USB iPhone only' `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 `
    -LocalAddress $localAddress -RemoteAddress $phoneAddress `
    -InterfaceAlias $usbLink.InterfaceAlias -Profile Any | Out-Null
$repoRoot = Split-Path $PSScriptRoot -Parent
@{ rule = $ruleName; localAddress = $localAddress; phoneAddress = $phoneAddress; port = 8000 } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $repoRoot '.local/ios-usb-network.json') -Encoding UTF8
