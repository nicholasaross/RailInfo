# Deploy the RailInfo CYD client to a connected board over mpremote.
#
#   pwsh deploy.ps1 -Port COM4              # copy lib + app + config (run with `mpremote run`)
#   pwsh deploy.ps1 -Port COM4 -Autostart  # also install as main.py and reset (runs on boot)
#
# Requires `mpremote` on PATH (uv tool install mpremote) and a config.py (copy config.py.example).
# Fonts must be generated first (tools/gen_fonts.ps1 -> lib/dotmatrix17.py, dotmatrix27.py).

param(
    [string]$Port = "COM4",
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
    "$here\lib\ili9341.py" "$here\lib\writer.py" "$here\lib\dotmatrix19.py" :lib/

Write-Output "Copying app + config ..."
mpremote connect $Port cp "$here\boards.py" "$here\config.py" "$here\railinfo_client.py" :

if ($Autostart) {
    Write-Output "Installing as main.py and resetting (autostart) ..."
    mpremote connect $Port cp "$here\railinfo_client.py" :main.py
    mpremote connect $Port reset
} else {
    Write-Output "Done. Test with:  mpremote connect $Port run railinfo_client.py"
}
