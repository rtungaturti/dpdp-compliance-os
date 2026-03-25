#Requires -Version 5.1
<#
.SYNOPSIS
    DPDP Compliance OS - Windows Prerequisites Setup
    Run once before first use: .\setup.ps1
    Run as Administrator for auto-install of missing tools.
#>

param(
    [switch]$AutoInstall,   # Pass -AutoInstall to install missing tools via winget
    [switch]$SkipChecks     # Skip version checks (for CI)
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "DPDP Compliance OS - Setup"

# -- Colours ------------------------------------------------------------------
function Write-Ok    { param($m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn  { param($m) Write-Host " [WARN] $m" -ForegroundColor Yellow }
function Write-Fail  { param($m) Write-Host " [FAIL] $m" -ForegroundColor Red }
function Write-Info  { param($m) Write-Host "  [..] $m" -ForegroundColor Cyan }
function Write-Head  { param($m) Write-Host "`n$m" -ForegroundColor White }

Write-Host "DPDP Compliance OS - Windows Setup" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# 1. Windows version
# -----------------------------------------------------------------------------
Write-Head "1. Windows Version"
$winVer = [System.Environment]::OSVersion.Version
if ($winVer.Major -ge 10 -and $winVer.Build -ge 19041) {
    Write-Ok "Windows $($winVer.Major).$($winVer.Minor) build $($winVer.Build) (WSL2 supported)"
} else {
    Write-Fail "Windows 10 build 19041+ required for WSL2. Current: $winVer"
    exit 1
}

# -----------------------------------------------------------------------------
# 2. WSL2
# -----------------------------------------------------------------------------
Write-Head "2. WSL2"
$wslStatus = wsl --status 2>&1
if ($LASTEXITCODE -eq 0) {
    $defaultVersion = (wsl --list --verbose 2>&1) | Select-String "Default"
    Write-Ok "WSL installed. $defaultVersion"
} else {
    Write-Fail "WSL not found or not running."
    if ($AutoInstall) {
        Write-Info "Installing WSL2..."
        wsl --install
        Write-Warn "Restart required after WSL install. Re-run setup.ps1 after restart."
    } else {
        Write-Warn "Run: wsl --install   (then restart)"
    }
}

# -----------------------------------------------------------------------------
# 3. Docker Desktop
# -----------------------------------------------------------------------------
Write-Head "3. Docker Desktop"
try {
    $dockerVersion = docker version --format "{{.Server.Version}}" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Docker Engine $dockerVersion"
    } else {
        throw "Docker not responding"
    }
} catch {
    Write-Fail "Docker Desktop not running or not installed."
    if ($AutoInstall) {
        Write-Info "Installing Docker Desktop via winget..."
        winget install Docker.DockerDesktop --silent --accept-source-agreements
        Write-Warn "Start Docker Desktop manually, then re-run this script."
    } else {
        Write-Warn "Download: https://www.docker.com/products/docker-desktop"
        Write-Warn "Required settings in Docker Desktop:"
        Write-Warn "  Settings > General > Use WSL 2 based engine: ON"
        Write-Warn "  Settings > Resources > WSL Integration: ON"
    }
}

# Check Docker Compose
try {
    $composeVersion = docker compose version --short 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Docker Compose v$composeVersion (plugin)"
    } else {
        throw "Compose not available"
    }
} catch {
    Write-Fail "Docker Compose plugin not found."
    Write-Warn "Ensure Docker Desktop is updated to v4.x+ (includes Compose v2)"
}

# -----------------------------------------------------------------------------
# 4. Docker resources (WSL memory)
# -----------------------------------------------------------------------------
Write-Head "4. Docker Resources"
$wslConfig = "$env:USERPROFILE\.wslconfig"
$needsWslConfig = $false

if (Test-Path $wslConfig) {
    $cfg = Get-Content $wslConfig -Raw
    if ($cfg -match "memory\s*=\s*(\d+)([GgMm])") {
        $mem = [int]$Matches[1]
        $unit = $Matches[2].ToUpper()
        $memGB = if ($unit -eq "G") { $mem } else { [math]::Round($mem / 1024, 1) }
        if ($memGB -ge 8) {
            Write-Ok "WSL memory: ${memGB}GB (sufficient for full stack)"
        } else {
            Write-Warn "WSL memory: ${memGB}GB - recommend 12GB+ for all 63 containers"
            $needsWslConfig = $true
        }
    } else {
        Write-Warn ".wslconfig found but no memory setting - WSL will use 50% of host RAM"
    }
} else {
    Write-Warn "No .wslconfig found - will create recommended config"
    $needsWslConfig = $true
}

if ($needsWslConfig) {
    $totalRamGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    $wslRamGB   = [math]::Max(8, [math]::Min(16, [math]::Round($totalRamGB * 0.6)))
    $wslConfig_content = @"
[wsl2]
memory=${wslRamGB}GB
processors=4
swap=4GB
[experimental]
autoMemoryReclaim=gradual
"@
    Set-Content $wslConfig $wslConfig_content -Encoding UTF8
    Write-Ok "Created $wslConfig  (${wslRamGB}GB RAM, 4 CPUs)"
    Write-Warn "Run: wsl --shutdown   then restart Docker Desktop to apply"
}

# -----------------------------------------------------------------------------
# 5. Git
# -----------------------------------------------------------------------------
Write-Head "5. Git"
try {
    $gitVersion = git --version 2>&1
    Write-Ok $gitVersion

    # Check line-ending config (critical for Python files in containers)
    $autocrlf = git config --global core.autocrlf 2>&1
    if ($autocrlf -eq "false") {
        Write-Ok "core.autocrlf = false (correct for Docker)"
    } else {
        Write-Warn "core.autocrlf = '$autocrlf' - should be 'false' to prevent CRLF in containers"
        Write-Info "Fixing: git config --global core.autocrlf false"
        git config --global core.autocrlf false
        Write-Ok "Fixed core.autocrlf = false"
    }
} catch {
    Write-Fail "Git not found."
    if ($AutoInstall) {
        winget install Git.Git --silent --accept-source-agreements
    } else {
        Write-Warn "Download: https://git-scm.com/download/win"
        Write-Warn "During install: select 'Checkout as-is, commit as-is'"
    }
}

# -----------------------------------------------------------------------------
# 6. PowerShell version
# -----------------------------------------------------------------------------
Write-Head "6. PowerShell"
$psVersion = $PSVersionTable.PSVersion
if ($psVersion.Major -ge 7) {
    Write-Ok "PowerShell $psVersion (recommended)"
} elseif ($psVersion.Major -ge 5) {
    Write-Warn "PowerShell $psVersion - all scripts work, but PS 7+ recommended"
    if ($AutoInstall) {
        Write-Info "Installing PowerShell 7..."
        winget install Microsoft.PowerShell --silent --accept-source-agreements
    } else {
        Write-Info "Optional upgrade: winget install Microsoft.PowerShell"
    }
} else {
    Write-Fail "PowerShell 5.1+ required. Current: $psVersion"
}

# -----------------------------------------------------------------------------
# 7. Port availability
# -----------------------------------------------------------------------------
Write-Head "7. Port Availability"
$ports = @(80, 443, 5432, 5433, 6379, 7233, 7474, 7687, 8080, 9000, 9001, 9092)
$blocked = @()
foreach ($port in $ports) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $proc = Get-Process -Id $listener[0].OwningProcess -ErrorAction SilentlyContinue
        Write-Warn "Port $port in use by: $($proc.Name) (PID $($proc.Id))"
        $blocked += $port
    }
}
if ($blocked.Count -eq 0) {
    Write-Ok "All required ports are free"
} else {
    Write-Warn "$($blocked.Count) port(s) in use. Stop conflicting services before running stack."
}

# -----------------------------------------------------------------------------
# 8. Environment file
# -----------------------------------------------------------------------------
Write-Head "8. Environment File"
$envFile = Join-Path $PSScriptRoot ".env"
$envExample = Join-Path $PSScriptRoot ".env.example"

if (Test-Path $envFile) {
    Write-Ok ".env file exists"
} elseif (Test-Path $envExample) {
    Copy-Item $envExample $envFile
    Write-Ok "Created .env from .env.example"
    Write-Warn "Edit .env and change all default passwords before first run"
} else {
    Write-Fail ".env.example not found - is the project directory correct?"
}

# -----------------------------------------------------------------------------
# 9. Line endings in project files (critical!)
# -----------------------------------------------------------------------------
Write-Head "9. Line Endings"
$gitattributes = Join-Path $PSScriptRoot ".gitattributes"
if (Test-Path $gitattributes) {
    Write-Ok ".gitattributes present (controls line endings)"
} else {
    Write-Warn ".gitattributes missing - Python files may get CRLF line endings inside containers"
    Write-Warn "Run: git add --renormalize .   after .gitattributes is created"
}

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
Write-Host "`n" + ("=" * 60) -ForegroundColor White
Write-Host "  Setup complete. Next steps:" -ForegroundColor White
Write-Host ("=" * 60) -ForegroundColor White
Write-Host @"

  1. Edit .env file with your passwords:
     notepad .env

  2. Start infrastructure:
     .\dpdp.ps1 infra

  3. Start Day 1 services:
     .\dpdp.ps1 day1

  4. Smoke test:
     .\dpdp.ps1 test

  5. Open dashboards:
     .\dpdp.ps1 open

  Full help:
     .\dpdp.ps1 help

"@ -ForegroundColor Gray
