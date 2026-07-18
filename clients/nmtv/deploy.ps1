# Deploy the RailInfo NM-TV client to a connected board over mpremote.
#
#   pwsh deploy.ps1 -Port COM5              # copy lib + app + config (run with `mpremote run`)
#   pwsh deploy.ps1 -Port COM5 -Autostart  # also install as main.py and reset (runs on boot)
#
# Requires `mpremote` on PATH (uv tool install mpremote) and a config.py (copy config.py.example).

param(
    [string]$Port = "COM5",
    [switch]$Autostart
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path (Join-Path $here "config.py"))) {
    throw "config.py not found - copy config.py.example to config.py and fill it in first."
}

Write-Output "Copying lib modules to ${Port}:/lib ..."
mpremote connect $Port mkdir :lib 2>$null
mpremote connect $Port cp `
    "$here\lib\st7789.py" "$here\lib\writer.py" "$here\lib\dotmatrix19.py" :lib/

Write-Output "Copying app + config ..."
mpremote connect $Port cp "$here\boards.py" "$here\config.py" "$here\railinfo_client.py" :

if ($Autostart) {
    Write-Output "Installing as main.py and resetting (autostart) ..."
    mpremote connect $Port cp "$here\railinfo_client.py" :main.py
    mpremote connect $Port reset
    if ($LASTEXITCODE -ne 0) {
        # A failed/ignored reset leaves the device at the REPL with main.py never started
        # (looks like a frozen board). Fall back to a serial-line hard reset via esptool.
        Write-Warning "mpremote reset failed - the board may sit at the REPL (frozen screen)."
        Write-Warning "Power-cycle it, or run: esptool --port $Port run"
    } else {
        Write-Output "Reset sent. CONFIRM the RailInfo screen comes up and the clock updates."
    }
} else {
    Write-Output "Done. Test with:  mpremote connect $Port run railinfo_client.py"
}
