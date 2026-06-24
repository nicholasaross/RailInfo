#Requires -Version 5.1
<#
.SYNOPSIS
    Build, ship, and install the RailInfo Docker image onto a Synology NAS over SSH.

.DESCRIPTION
    Run this on the Windows dev box. It:
      1. builds  railinfo:latest  (linux/amd64 — the DS218+/Celeron arch),
      2. saves it to a tarball,
      3. scp's the tarball to the NAS,
      4. `docker load`s it on the NAS over ssh (via sudo), removing the tarball after.
    With -Start it also writes a prebuilt-image compose + a LF-normalised .env, copies them,
    and runs `docker compose up -d` on the NAS.

.PREREQUISITES
    Dev box : Docker Desktop running; the Windows OpenSSH client (ssh/scp — built in).
    NAS     : SSH enabled (Control Panel > Terminal & SNMP > Enable SSH service);
              Container Manager installed; an *administrator* account (docker runs via sudo).
              For -Start: docker-compose (v1) or `docker compose` (v2) on the NAS - the script
              auto-detects, preferring v1 (the Synology default); override with -ComposeCmd.

.EXAMPLE
    # Build, copy, and load the image (then create/start it yourself in Container Manager):
    .\scripts\deploy-to-nas.ps1 -NasHost 192.168.1.50 -NasUser admin

.EXAMPLE
    # Full one-shot: also copy compose + .env and start the stack:
    .\scripts\deploy-to-nas.ps1 -NasHost 192.168.1.50 -NasUser admin -Start

.EXAMPLE
    # Re-deploy without rebuilding, using an SSH key, on a non-default port:
    .\scripts\deploy-to-nas.ps1 -NasHost nas.local -NasUser admin -SkipBuild -SshKey ~\.ssh\id_ed25519 -SshPort 2222
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $NasHost,                 # NAS IP or hostname
    [Parameter(Mandatory)] [string] $NasUser,                 # a NAS administrator account
    [string] $RemoteDir = "/volume1/docker/railinfo",         # working dir on the NAS
    [string] $ImageTag  = "railinfo:latest",
    [int]    $SshPort   = 22,
    [string] $SshKey,                                         # optional private key path (ssh -i)
    [string] $DockerCmd = "docker",                           # left as "docker" => auto-resolve the path on the NAS; else use this exact path
    [string] $ComposeCmd = "",                                # -Start only: blank => auto-detect docker-compose (v1) / `docker compose` (v2); else this exact command
    [int]    $HostPort = 8000,                                # -Start only: NAS host port to publish (container serves :8000 internally) - use a free one
    [string] $PixooHost = "192.168.1.202",                    # -Start only: PIXOO_HOST in the NAS compose
    [string] $TimeZone  = "Europe/London",                    # -Start only: TZ in the NAS compose
    [switch] $SkipBuild,                                      # reuse the existing local image
    [switch] $Start                                           # also copy compose+.env and `docker compose up -d`
)

$ErrorActionPreference = "Stop"
# Keep our explicit $LASTEXITCODE checks authoritative across PowerShell versions.
Set-Variable -Name PSNativeCommandUseErrorActionPreference -Value $false -Scope Script -ErrorAction SilentlyContinue

$repoRoot  = Split-Path -Parent $PSScriptRoot
$localTar  = Join-Path $env:TEMP "railinfo-image.tar"
$remoteTar = "$RemoteDir/railinfo-image.tar"
$target    = "${NasUser}@${NasHost}"

# ssh uses -p for the port, scp uses -P; -i (key) is optional for both.
# scp -O forces the legacy SCP protocol: Synology's sshd usually omits the SFTP subsystem that
# modern scp defaults to, which otherwise fails with "subsystem request failed on channel 0".
$sshOpts = @("-p", "$SshPort"); $scpOpts = @("-O", "-P", "$SshPort")
if ($SshKey) { $sshOpts += @("-i", $SshKey); $scpOpts += @("-i", $SshKey) }

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Assert-Ok($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)." } }
function Write-LfFile($path, $content) { [IO.File]::WriteAllText($path, ($content -replace "`r`n", "`n")) }

# --- 0. Preflight ----------------------------------------------------------------------
Step "Checking the local Docker daemon..."
docker version --format 'server {{.Server.Version}} ({{.Server.Os}}/{{.Server.Arch}})'
if ($LASTEXITCODE -ne 0) { throw "Docker daemon not reachable - start Docker Desktop first." }
foreach ($c in 'ssh', 'scp') {
    if (-not (Get-Command $c -ErrorAction SilentlyContinue)) {
        throw "$c not found. Install the Windows OpenSSH client (Settings > Optional features)."
    }
}

# --- 1. Build --------------------------------------------------------------------------
if ($SkipBuild) {
    Step "Skipping build; using the existing $ImageTag."
    docker image inspect $ImageTag *> $null
    if ($LASTEXITCODE -ne 0) { throw "$ImageTag not found locally; run without -SkipBuild." }
}
else {
    Step "Building $ImageTag (linux/amd64)..."
    # --provenance=false => a plain single-arch image, so `docker save`/`load` stays clean on
    # whatever Docker version the NAS runs (attestation manifests can trip older daemons).
    docker build --platform linux/amd64 --provenance=false -t $ImageTag $repoRoot
    Assert-Ok "docker build"
}

# --- 2. Save ---------------------------------------------------------------------------
Step "Saving $ImageTag to a tarball..."
docker save $ImageTag -o $localTar
Assert-Ok "docker save"
$tarMB = [int]((Get-Item $localTar).Length / 1MB)
Write-Host "    tarball: $tarMB MB"

# --- 3. Copy to the NAS ----------------------------------------------------------------
Step "Creating $RemoteDir on $NasHost ..."
ssh @sshOpts $target "mkdir -p '$RemoteDir'"
Assert-Ok "ssh mkdir (check SSH is enabled and the account/credentials)"

Step "Copying the image tarball to $NasHost (~$tarMB MB)..."
scp @scpOpts $localTar "${target}:$remoteTar"
Assert-Ok "scp (image tarball)"

if ($Start) {
    $envFile = Join-Path $repoRoot ".env"
    if (-not (Test-Path $envFile)) { throw ".env not found at $envFile (needed for -Start)." }

    # Compose for the NAS: references the loaded image (no `build:`); host networking reaches
    # the Pixoo and exposes :8000 for the Heltec. Written with LF endings for the Linux host.
    $composeTmp = Join-Path $env:TEMP "railinfo-compose.nas.yml"
    # `version` is kept for Synology's docker-compose v1 (older parsers want it); v2 ignores it.
    Write-LfFile $composeTmp @"
version: "3.8"
services:
  railinfo:
    image: $ImageTag
    container_name: railinfo
    restart: unless-stopped
    # Bridge + explicit publish (deterministic on Synology). Host mode isn't needed: PIXOO_HOST
    # is pinned, and outbound to the Pixoo and LDBWS works fine through the bridge's NAT.
    ports:
      - "${HostPort}:8000"
    env_file: .env
    environment:
      - TZ=$TimeZone
      - PIXOO_HOST=$PixooHost
    command: ["python", "main.py", "--serve", "--pixoo", "--loop", "--port", "8000"]
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
"@

    # Normalise .env to LF so docker compose doesn't leave a stray CR on each value.
    $envTmp = Join-Path $env:TEMP "railinfo.env"
    Write-LfFile $envTmp (Get-Content $envFile -Raw)

    Step "Copying compose + .env to $RemoteDir ..."
    scp @scpOpts $composeTmp "${target}:$RemoteDir/docker-compose.yml"; Assert-Ok "scp (compose)"
    scp @scpOpts $envTmp     "${target}:$RemoteDir/.env";               Assert-Ok "scp (.env)"
    Remove-Item $composeTmp, $envTmp -ErrorAction SilentlyContinue
}

# --- 4. Install (and optionally start) on the NAS --------------------------------------
# sudo on Synology resets PATH (secure_path) and can't see `docker`/`docker-compose`, so we
# resolve their full paths in the remote shell and call `sudo <full-path>`. Synology also
# usually has docker-compose v1 (hyphenated), NOT the `docker compose` v2 plugin, so compose
# is resolved separately (v1 first, v2 fallback). One ssh -t session: -t gives sudo a TTY and
# caches its credentials across the &&-chained commands (prompted at most once).

# Resolve the docker binary into $D (or set it to the caller-supplied -DockerCmd).
if ($DockerCmd -eq 'docker') {
    $resolveD = 'D=$(for p in /usr/local/bin/docker ' +
        '/var/packages/ContainerManager/target/usr/bin/docker ' +
        '/var/packages/Docker/target/usr/bin/docker; do [ -x "$p" ] && { echo "$p"; break; }; done); ' +
        '[ -z "$D" ] && D=$(command -v docker); ' +
        '[ -z "$D" ] && { echo "docker not found on the NAS - re-run with -DockerCmd <path>" >&2; exit 127; }; ' +
        'echo "using docker at $D"; '
}
else {
    $resolveD = "D='$DockerCmd'; "
}
$dk = '"$D"'             # literal; the remote shell expands $D
$imageRepo = $ImageTag.Split(':')[0]

if ($Start) {
    Step "Loading the image and starting the stack on the NAS (enter the sudo password if prompted)..."
    # Resolve the compose command into $C: docker-compose (v1) first, then `docker compose` (v2).
    if ($ComposeCmd) {
        $resolveC = "C='$ComposeCmd'; "
    }
    else {
        $resolveC = 'if [ -x /usr/local/bin/docker-compose ]; then C=/usr/local/bin/docker-compose; ' +
            'elif command -v docker-compose >/dev/null 2>&1; then C=$(command -v docker-compose); ' +
            'elif "$D" compose version >/dev/null 2>&1; then C="$D compose"; ' +
            'else echo "no docker-compose (v1) or docker compose (v2) on the NAS - re-run with -ComposeCmd <cmd>" >&2; exit 127; fi; ' +
            'echo "using compose: $C"; '
    }
    $ck = '$C'          # unquoted reference, so a `<docker> compose` (v2) value word-splits
    # `down` first so a prior/half-created container can't leave its port "already allocated"
    # ( || true: down is a no-op the first time, when there's nothing to remove ).
    $remote = $resolveD + $resolveC +
        "sudo $dk load -i '$remoteTar' && sudo rm -f '$remoteTar' && cd '$RemoteDir' && " +
        "{ sudo $ck down || true; } && sudo $ck up -d && sudo $ck ps"
}
else {
    Step "Loading the image on the NAS (enter the sudo password if prompted)..."
    $remote = $resolveD +
        "sudo $dk load -i '$remoteTar' && sudo rm -f '$remoteTar' && sudo $dk images $imageRepo"
}
ssh -t @sshOpts $target $remote
Assert-Ok "remote docker step"

# --- 5. Cleanup + next steps -----------------------------------------------------------
Remove-Item $localTar -ErrorAction SilentlyContinue
Step "Done."
if ($Start) {
    Write-Host @"

Started. Verify:  http://${NasHost}:${HostPort}/healthz   then  /board?view=departures
Cutover:
  - Point clients/heltec/config.py SERVER_URL at  http://<NAS-IP>:${HostPort}  and redeploy.
  - Stop the dev-box process so both don't push the Pixoo.
"@ -ForegroundColor Green
}
else {
    Write-Host @"

Image '$ImageTag' is now loaded on $NasHost.
Next, re-run with -Start (add -HostPort if :8000 is taken), or create the Project in Container
Manager using a compose that publishes  ports: ["${HostPort}:8000"]  with
command --serve --pixoo --loop --port 8000.
Then point the Heltec's config.py SERVER_URL at  http://<NAS-IP>:${HostPort}  and stop the dev-box process.
"@ -ForegroundColor Green
}
