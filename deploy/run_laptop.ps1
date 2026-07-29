# ─────────────────────────────────────────────────────────────────────────────
# LogicWard — launch the SOC dashboard on the laptop, reading the REAL Pi.
#
#   .\deploy\run_laptop.ps1                       # Pi at siddhesh-pi.local
#   .\deploy\run_laptop.ps1 -PiHost 192.168.1.42  # or an explicit IP
#
# The dashboard also hosts /api/ingest, so the Pi agent POSTs its events here.
# One-time: allow inbound TCP 8080 through Windows Firewall (run as admin):
#   New-NetFirewallRule -DisplayName LogicWard -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow
# ─────────────────────────────────────────────────────────────────────────────
param(
  [string]$PiHost = "siddhesh.local",
  [string]$Token  = "logicward-dev-token-change-me"
)

$env:LOGICWARD_EMBED_PLANT = "0"        # read the real Pi, not an in-process plant
$env:LOGICWARD_PI_HOST     = $PiHost    # PROGRAM_URL derives from this automatically
$env:LOGICWARD_TOKEN       = $Token     # must match the token on the Pi agent

Write-Host "LogicWard SOC dashboard" -ForegroundColor Cyan
Write-Host "  URL      : http://localhost:8080/   (login soc/soc123)"
Write-Host "  Reading  : PLC at $PiHost  (Modbus :5020, program :8081)"
Write-Host "  Ingest   : POST http://<this-laptop>:8080/api/ingest  (Pi agent -> here)"
Write-Host ""
python -m logicward.dashboard.app
