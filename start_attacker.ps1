<#
.SYNOPSIS
Discovers the Raspberry Pi's IP address and starts the Attacker Dashboard.
#>
param(
    [string]$PiMac = "d8-3a-dd-b4-29-69"
)

Write-Host "Discovering Pi IP on hotspot..." -ForegroundColor Cyan
$arp = arp -a | Select-String $PiMac
if (-not $arp) {
    Write-Host "ERROR: Could not find Pi MAC ($PiMac) in ARP table." -ForegroundColor Red
    Write-Host "Ensure the Pi is turned ON and connected to your Mobile Hotspot." -ForegroundColor Yellow
    exit 1
}

$PiIp = $arp.Line.Trim().Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)[0]
Write-Host "Found Pi at $PiIp" -ForegroundColor Green

Write-Host "`nStarting Attacker Dashboard (Port 9090)..." -ForegroundColor Cyan
python -m logicward.attacker.dashboard --host $PiIp
