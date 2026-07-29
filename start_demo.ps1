<#
.SYNOPSIS
Discovers the Raspberry Pi's IP address and bootstraps it.
#>
param(
    [string]$PiMac = "d8-3a-dd-b4-29-69",
    [string]$HotspotInterface = "Local Area Connection* 10"
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

Write-Host "Discovering Laptop Hotspot IP..." -ForegroundColor Cyan
$LaptopIp = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias $HotspotInterface -ErrorAction SilentlyContinue).IPAddress
if (-not $LaptopIp) {
    Write-Host "ERROR: Could not find hotspot interface '$HotspotInterface'." -ForegroundColor Red
    exit 1
}
Write-Host "Found Laptop Hotspot IP at $LaptopIp" -ForegroundColor Green

Write-Host "`nBootstrapping Pi..." -ForegroundColor Cyan
python deploy/pi_tools/bootstrap_pi.py --pi-ip $PiIp --laptop-ip $LaptopIp

Write-Host "`nStarting SOC Dashboard..." -ForegroundColor Cyan
.\deploy\run_laptop.ps1 -PiHost $PiIp
