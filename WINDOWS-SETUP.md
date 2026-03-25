# Windows Setup Guide — DPDP + AI Compliance OS

Complete guide for running the 63-container compliance platform on Windows with Docker Desktop + WSL2.

---

## System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 21H2 | Windows 11 22H2+ |
| RAM | 16 GB | 32 GB |
| CPU | 4 cores | 8+ cores |
| Disk | 40 GB free (SSD) | 100 GB SSD |
| WSL2 allocation | 8 GB | 16 GB |

---

## Step 1 — Install Prerequisites

Open **PowerShell as Administrator** and run:

```powershell
# 1. Enable WSL2
wsl --install
# Restart Windows when prompted

# 2. Install Docker Desktop (after restart)
winget install Docker.DockerDesktop

# 3. Install Git
winget install Git.Git

# 4. Install PowerShell 7 (optional but recommended)
winget install Microsoft.PowerShell
```

Or run the automated checker:
```powershell
cd C:\path\to\dpdp-compliance-os
.\setup.ps1 -AutoInstall
```

---

## Step 2 — Configure Docker Desktop

Open Docker Desktop → **Settings**:

| Setting | Value |
|---|---|
| General → Use WSL 2 based engine | ✅ ON |
| General → Use containerd for pulling images | ✅ ON |
| Resources → WSL Integration → Enable for your distro | ✅ ON |
| Resources → Advanced → Memory | **12 GB** (min 8 GB) |
| Resources → Advanced → CPUs | 4+ |
| Resources → Advanced → Swap | 4 GB |

Click **Apply & Restart**.

### WSL2 memory config (alternative to Docker Desktop UI)

Create or edit `C:\Users\<YourName>\.wslconfig`:

```ini
[wsl2]
memory=12GB
processors=4
swap=4GB

[experimental]
autoMemoryReclaim=gradual
```

Then restart WSL: `wsl --shutdown`

---

## Step 3 — Fix Line Endings (Critical!)

Python files inside Linux containers **must have LF line endings**, not Windows CRLF. The `.gitattributes` file in this project handles this automatically, but you must configure Git first:

```powershell
# Run ONCE globally
git config --global core.autocrlf false

# If you already cloned the repo, renormalise existing files
git add --renormalize .
git commit -m "Normalise line endings for Docker"
```

**Why this matters:** A Python file with CRLF line endings will throw `SyntaxError` or silently fail when run inside a Linux container. This is the most common Windows-specific Docker problem.

---

## Step 4 — Clone and Configure

```powershell
# Clone the project
git clone <repo-url> dpdp-compliance-os
cd dpdp-compliance-os

# Run setup check
.\setup.ps1

# Create environment file
Copy-Item .env.example .env
notepad .env    # Edit passwords
```

**Required .env values to change:**
```env
DB_PASSWORD=change_me_strong_password
NEO4J_PASSWORD=change_me_strong_password
MINIO_PASSWORD=change_me_strong_password
KAFKA_CLUSTER_ID=dpdp-compliance-cluster-001
```

---

## Step 5 — Start the Stack

The `dpdp.ps1` script is your main control tool (replaces the Linux `Makefile`):

```powershell
# Start infrastructure only (Postgres, Neo4j, Redis, Kafka, etc.)
.\dpdp.ps1 infra

# Wait ~60 seconds, then start Day 1 services
.\dpdp.ps1 day1

# Run smoke tests
.\dpdp.ps1 test

# Add Day 2 services
.\dpdp.ps1 day2

# Open all dashboards
.\dpdp.ps1 open
```

### With Windows-specific overrides

For the most reliable experience on Windows, add the windows override file:

```powershell
docker compose `
  -f docker-compose.day1.yml `
  -f docker-compose.windows.yml `
  --profile infra `
  up -d
```

The `dpdp.ps1` script includes this automatically.

---

## Service Dashboard URLs

After `.\dpdp.ps1 day1`:

| Service | URL |
|---|---|
| **Traefik Dashboard** | http://localhost:8080 |
| Consent Engine API | http://localhost:8003/docs |
| Role Classifier API | http://localhost:8001/docs |
| Rights Portal API | http://localhost:8004/docs |
| **Jaeger Tracing** | http://localhost:16686 |
| **MinIO Console** | http://localhost:9001 |
| Neo4j Browser | http://localhost:7474 |

After `.\dpdp.ps1 day2`:

| Service | URL |
|---|---|
| SDF Determinator | http://localhost:8101/docs |
| DPIA Engine | http://localhost:8102/docs |
| AI Bias Monitor | http://localhost:8103/docs |
| Cross-Border PEP | http://localhost:8104/docs |

After `.\dpdp.ps1 day7`:

| Service | URL |
|---|---|
| PBAC Engine | http://localhost:8606/docs |
| DPO Console | http://localhost:8601/docs |

---

## Common Windows Issues & Fixes

### "Error response from daemon: driver failed programming external connectivity"

Port conflict. Find and stop the process using the port:
```powershell
# Find what's on port 5432 (example)
netstat -ano | findstr :5432

# Kill it (replace 1234 with actual PID)
Stop-Process -Id 1234 -Force
```

### "An error occurred trying to connect" when running `.\dpdp.ps1`

PowerShell execution policy blocked the script. Fix:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Neo4j crashes / OOM

WSL2 memory too low. Increase in `.wslconfig` then restart:
```powershell
# Edit C:\Users\<you>\.wslconfig  — set memory=16GB
wsl --shutdown
# Restart Docker Desktop
```

### Kafka "LEADER_NOT_AVAILABLE" errors

The KRaft cluster ID wasn't formatted properly. Generate a new one:
```powershell
# Generate proper Kafka cluster ID
$id = [System.Guid]::NewGuid().ToString("N").Substring(0, 22)
# Set it in .env:  KAFKA_CLUSTER_ID=<value>
```

### Python `SyntaxError: invalid syntax` in containers

Line endings are CRLF. Fix:
```powershell
git config --global core.autocrlf false
git add --renormalize .
# Rebuild the affected image:
.\dpdp.ps1 build day1
```

### `docker compose` not found (vs `docker-compose`)

Docker Compose v2 is bundled with Docker Desktop 4.x as a plugin (`docker compose`). If you're on Docker Desktop 3.x, update to 4.x:
```powershell
winget upgrade Docker.DockerDesktop
```

### WSL clock drift (tokens expire, weird auth errors)

```powershell
wsl -d Ubuntu --exec sudo hwclock -s
# Or restart WSL:
wsl --shutdown
```

---

## Full Smoke Test

After `.\dpdp.ps1 day1` and `.\dpdp.ps1 day2`:

```powershell
# Test all services that are running
.\dpdp.ps1 test-consent
.\dpdp.ps1 test-classify
.\dpdp.ps1 test-dpia
.\dpdp.ps1 test-bias
.\dpdp.ps1 test-transfer
```

---

## Stopping & Cleanup

```powershell
# Stop all containers (keep data)
.\dpdp.ps1 stop

# Stop and delete ALL data (Postgres, Neo4j, Kafka, MinIO)
.\dpdp.ps1 reset

# Free Docker disk space
docker system prune -f
docker volume prune -f
```

---

## PowerShell Cheat Sheet

| Task | Command |
|---|---|
| Show all commands | `.\dpdp.ps1 help` |
| Start infra | `.\dpdp.ps1 infra` |
| Start Day 1 | `.\dpdp.ps1 day1` |
| Start Day 2 | `.\dpdp.ps1 day2` |
| Show container status | `.\dpdp.ps1 status` |
| Tail logs (all) | `.\dpdp.ps1 logs` |
| Tail logs (specific) | `.\dpdp.ps1 logs consent-engine` |
| Smoke tests | `.\dpdp.ps1 test` |
| Open dashboards | `.\dpdp.ps1 open` |
| Stop everything | `.\dpdp.ps1 stop` |
| Rebuild images | `.\dpdp.ps1 build day1` |
| Nuke and reset | `.\dpdp.ps1 reset` |
