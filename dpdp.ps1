#Requires -Version 5.1
<#
.SYNOPSIS
    DPDP Compliance OS - Main control script (Windows PowerShell replacement for Makefile)

.EXAMPLE
    .\dpdp.ps1 help          # Show all commands
    .\dpdp.ps1 infra         # Start infrastructure
    .\dpdp.ps1 day1          # Build and start Day 1 services
    .\dpdp.ps1 day2          # Add Day 2 services
    .\dpdp.ps1 all           # Start everything
    .\dpdp.ps1 status        # Show service health
    .\dpdp.ps1 logs consent-engine   # Tail logs
    .\dpdp.ps1 test          # Run smoke tests
    .\dpdp.ps1 open          # Open all dashboards in browser
    .\dpdp.ps1 stop          # Stop all containers
    .\dpdp.ps1 reset         # Stop + delete volumes (DESTRUCTIVE)
#>

param(
    [Parameter(Position=0)]
    [string]$Command = "help",

    [Parameter(Position=1, ValueFromRemainingArguments)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# -- Compose files -------------------------------------------------------------
$C1  = "docker-compose.day1.yml"
$C28 = "docker-compose.day2-8.yml"

# Base compose invocation (always include day1 for infra definitions)
function dc {
    param([string[]]$dcArgs)
    $cmd = @("docker", "compose",
             "-f", $C1,
             "-f", $C28,
             "--project-name", "dpdp-compliance-os") + $dcArgs
    Write-Verbose "Running: $($cmd -join ' ')"
    & $cmd[0] $cmd[1..($cmd.Length-1)]
    if ($LASTEXITCODE -ne 0) { throw "docker compose exited $LASTEXITCODE" }
}

# -- Colours ------------------------------------------------------------------
function info  { param($m) Write-Host "  >> $m" -ForegroundColor Cyan }
function ok    { param($m) Write-Host "  OK $m" -ForegroundColor Green }
function warn  { param($m) Write-Host "WARN $m" -ForegroundColor Yellow }
function head  { param($m) Write-Host "`n=== $m ===" -ForegroundColor White }

# -----------------------------------------------------------------------------
# Command handlers
# -----------------------------------------------------------------------------

function Cmd-Help {
    Write-Host @"

  DPDP Compliance OS - PowerShell Control Script
  -----------------------------------------------------------------
  .\dpdp.ps1 <command> [options]

  SETUP
    setup           Run prerequisites check (calls setup.ps1)

  INFRASTRUCTURE
    infra           Start all 9 infrastructure services
                    (Postgres, Neo4j, Redis, Kafka, Temporal,
                     MinIO, TimescaleDB, OTel, Traefik)

  SERVICES (incremental - always include previous days)
    day1            Build + start Day 1 services
    day2            Add Day 2 services (requires day1 running)
    day3            Add Day 3 services
    day4            Add Day 4 services
    day5            Add Day 5 services
    day6            Add Day 6 services
    day7            Add Day 7 services
    day8            Add Day 8 services + frontends
    all             Start everything (infra + all days)

  OPERATIONS
    status          Show health of all running containers
    logs [service]  Tail logs (all services or named service)
    ps              List containers with status
    stop            Stop all containers (keep volumes)
    reset           Stop + DELETE all volumes (DESTRUCTIVE)
    build [day]     Rebuild images (e.g., build day1)
    pull            Pull latest base images

  TESTING
    test            Run smoke tests against Day 1 services
    test-consent    Test Consent Engine API
    test-classify   Test Role Classifier API
    test-dpia       Test DPIA Engine API
    test-bias       Test AI Bias Monitor API
    test-transfer   Test Cross-Border PEP API
    test-pbac       Test PBAC Engine API
    test-shadow     Test Shadow AI Discovery

  BROWSER
    open            Open all service dashboards in browser

  -----------------------------------------------------------------
"@
}

function Cmd-Setup {
    & "$PSScriptRoot\setup.ps1"
}

function Cmd-Infra {
    head "Starting Infrastructure"
    info "Starting: Postgres, Neo4j, Redis, Kafka (KRaft), Temporal, MinIO, TimescaleDB, OTel, Traefik"
    dc @("--profile", "infra", "up", "-d", "--wait")
    Start-Sleep -Seconds 5
    info "Waiting for health checks..."
    $timeout = 120
    $elapsed = 0
    while ($elapsed -lt $timeout) {
        $unhealthy = docker ps --filter "health=starting" --format "{{.Names}}" 2>&1
        if (-not $unhealthy) { break }
        Start-Sleep -Seconds 5
        $elapsed += 5
        Write-Host "  Waiting... ($elapsed/${timeout}s)" -ForegroundColor Gray
    }
    ok "Infrastructure ready"
    Cmd-Urls -InfraOnly
}

function Cmd-Day {
    param([string]$Day)
    head "Starting $Day services"
    dc @("--profile", $Day, "up", "-d", "--build", "--wait")
    ok "$Day services started"
    Cmd-Urls -Day $Day
}

function Cmd-All {
    head "Starting full stack (all 63 containers)"
    warn "This requires 12GB+ RAM allocated to Docker/WSL2"
    $confirm = Read-Host "Continue? [y/N]"
    if ($confirm -ne "y") { return }
    dc @("--profile", "all", "up", "-d", "--build")
    ok "Full stack started"
    Cmd-Open
}

function Cmd-Status {
    head "Service Status"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" `
        --filter "label=com.docker.compose.project=dpdp-compliance-os" 2>&1
}

function Cmd-Logs {
    param([string]$Service = "")
    if ($Service) {
        dc @("logs", "-f", "--tail=100", $Service)
    } else {
        dc @("logs", "-f", "--tail=50",
             "consent-engine", "role-classifier", "rights-portal",
             "sdf-determinator", "hitl-service")
    }
}

function Cmd-PS {
    dc @("ps")
}

function Cmd-Stop {
    head "Stopping all services"
    dc @("down")
    ok "Stopped"
}

function Cmd-Reset {
    head "Reset - DELETE all volumes"
    warn "This will destroy ALL data: Postgres, Neo4j, Redis, MinIO, Kafka"
    $confirm = Read-Host "Type 'yes' to confirm"
    if ($confirm -ne "yes") { warn "Cancelled"; return }
    dc @("down", "-v", "--remove-orphans")
    ok "Reset complete - all volumes deleted"
}

function Cmd-Build {
    param([string]$Day = "")
    if ($Day) {
        head "Rebuilding $Day images"
        dc @("--profile", $Day, "build", "--no-cache")
    } else {
        head "Rebuilding all images"
        dc @("build", "--no-cache")
    }
}

function Cmd-Pull {
    head "Pulling base images"
    docker pull pgvector/pgvector:pg15
    docker pull neo4j:5-enterprise
    docker pull redis:7-alpine
    docker pull confluentinc/cp-kafka:7.6.0
    docker pull temporalio/auto-setup:1.24.2
    docker pull minio/minio:latest
    docker pull timescale/timescaledb:latest-pg15
    docker pull ghcr.io/mlflow/mlflow:v2.13.0
    docker pull otel/opentelemetry-collector-contrib:0.100.0
    docker pull jaegertracing/all-in-one:1.57
    docker pull traefik:v3.0
    ok "All base images pulled"
}

# -- Smoke tests ---------------------------------------------------------------
function Invoke-API {
    param([string]$Url, [string]$Method = "GET", [hashtable]$Body = $null, [string]$Label = "")
    try {
        $params = @{ Uri = $Url; Method = $Method; TimeoutSec = 10; ErrorAction = "Stop" }
        if ($Body) {
            $params.Body = ($Body | ConvertTo-Json -Depth 10)
            $params.ContentType = "application/json"
        }
        $resp = Invoke-RestMethod @params
        ok "$Label"
        return $resp
    } catch {
        warn "$Label - FAILED: $_"
        return $null
    }
}

function Cmd-TestConsent {
    head "Testing Consent Engine (:8003)"
    Invoke-API "http://localhost:8003/health" -Label "Health check"
    Invoke-API "http://localhost:8003/consent/grant" -Method POST -Label "Grant consent" -Body @{
        principal_id     = "test-user-001"
        data_fiduciary_id = "org-acme"
        purpose_ids      = @("marketing", "analytics")
        data_categories  = @("email", "name")
        retention_days   = 365
    }
    Invoke-API "http://localhost:8003/consent/check" -Method POST -Label "Check consent" -Body @{
        principal_id     = "test-user-001"
        data_fiduciary_id = "org-acme"
        purpose_id       = "marketing"
    }
}

function Cmd-TestClassify {
    head "Testing Role Classifier (:8001)"
    Invoke-API "http://localhost:8001/health" -Label "Health check"
    $result = Invoke-API "http://localhost:8001/classify" -Method POST -Label "Classify SDF entity" -Body @{
        entity_id            = "org-bigtech"
        entity_name          = "BigTech India Pvt Ltd"
        sector               = "social_media"
        user_count           = 15000000
        processes_child_data = $false
        ai_ml_profiling      = $true
        annual_turnover_crore = 600
    }
    if ($result) { info "Risk score: $($result.risk_score) | Role: $($result.role) | SDF: $($result.is_sdf)" }
}

function Cmd-TestDPIA {
    head "Testing DPIA Engine (:8102)"
    Invoke-API "http://localhost:8102/health" -Label "Health check"
    $result = Invoke-API "http://localhost:8102/dpia/initiate" -Method POST -Label "Initiate DPIA" -Body @{
        project_id                      = "proj-ml-credit"
        project_name                    = "ML Credit Scoring v3"
        data_controller_id              = "org-finco"
        processing_description          = "ML model for credit scoring using transaction history"
        data_categories                 = @("financial", "transaction_history")
        data_subjects_count             = 500000
        includes_children               = $false
        includes_sensitive_data         = $true
        uses_automated_decision_making  = $true
        involves_cross_border_transfer  = $false
        new_technology_involved         = $true
        requested_by                    = "product-team"
        business_justification          = "Improve loan approval accuracy"
    }
    if ($result) { info "Risk level: $($result.risk_level) | Score: $($result.overall_score) | Status: $($result.status)" }
}

function Cmd-TestBias {
    head "Testing AI Bias Monitor (:8103)"
    Invoke-API "http://localhost:8103/health" -Label "Health check"
    $result = Invoke-API "http://localhost:8103/bias/evaluate" -Method POST -Label "Evaluate model bias" -Body @{
        model_id             = "loan-model-v3"
        model_name           = "Loan Approval Model"
        model_version        = "3.0.1"
        evaluation_dataset_id = "eval-2024-q1"
        reference_group      = "general_population"
        use_case             = "credit_scoring"
        evaluated_by         = "mlops-team"
        group_metrics        = @(
            @{ group_name = "general_population"; protected_attribute = "gender"; group_size = 50000; positive_rate = 0.72; true_positive_rate = 0.75; false_positive_rate = 0.15; false_negative_rate = 0.25 },
            @{ group_name = "women"             ; protected_attribute = "gender"; group_size = 22000; positive_rate = 0.55; true_positive_rate = 0.58; false_positive_rate = 0.20; false_negative_rate = 0.42 }
        )
    }
    if ($result) { info "Bias level: $($result.bias_level) | Fairness score: $($result.overall_fairness_score)" }
}

function Cmd-TestTransfer {
    head "Testing Cross-Border PEP (:8104)"
    Invoke-API "http://localhost:8104/health" -Label "Health check"
    $allowed = Invoke-API "http://localhost:8104/transfer/check" -Method POST -Label "Transfer to US (whitelisted)" -Body @{
        destination_country = "US"
        destination_entity  = "Acme US LLC"
        data_categories     = @("general")
        principal_count     = 1000
        data_volume_mb      = 50
        purpose             = "analytics"
        legal_basis         = "consent"
        requestor_id        = "data-team"
    }
    $blocked = Invoke-API "http://localhost:8104/transfer/check" -Method POST -Label "Transfer to CN (blocked)" -Body @{
        destination_country = "CN"
        destination_entity  = "Unknown Entity"
        data_categories     = @("general")
        principal_count     = 100
        data_volume_mb      = 5
        purpose             = "analytics"
        legal_basis         = "consent"
        requestor_id        = "data-team"
    }
    if ($allowed) { info "US transfer: $($allowed.decision)" }
    if ($blocked) { info "CN transfer: $($blocked.decision)" }
}

function Cmd-TestPBAC {
    head "Testing PBAC Engine (:8606)"
    Invoke-API "http://localhost:8606/health" -Label "Health check"
    # Assign URL to variable first - PowerShell 5.1 cannot parse & inside
    # a string literal when used as a direct function argument
    $mockUrl = "http://localhost:8606/pbac/consent/mock" +
               "?principal_id=user-123" +
               "&fiduciary_id=org-abc" +
               "&purpose=marketing" +
               "&active=true"
    Invoke-API $mockUrl -Method POST -Label "Set mock consent"
    $result = Invoke-API "http://localhost:8606/pbac/authorize" -Method POST -Label "Authorize access" -Body @{
        principal_id       = "user-123"
        requestor_id       = "analyst-456"
        requestor_role     = "analyst"
        data_fiduciary_id  = "org-abc"
        requested_purpose  = "marketing"
        data_categories    = @("email", "name")
        data_fields        = @("email", "name", "dob")
        record_count       = 100
    }
    if ($result) { info "Decision: $($result.decision) | Allowed fields: $($result.allowed_fields -join ', ')" }
}

function Cmd-TestShadow {
    head "Testing Shadow AI Discovery (:8701)"
    Invoke-API "http://localhost:8701/health" -Label "Health check"
    $result = Invoke-API "http://localhost:8701/shadow-ai/scan" -Method POST -Label "Scan network events" -Body @{
        network_events = @(
            @{
                source_service  = "customer-service-api"
                source_ip       = "10.0.1.50"
                destination_url = "https://api.openai.com/v1/chat/completions"
                http_method     = "POST"
                payload_sample  = "Summarise this customer complaint about order 12345"
                bytes_sent      = 2048
            },
            @{
                source_service  = "hr-portal"
                source_ip       = "10.0.2.100"
                destination_url = "https://api.anthropic.com/v1/messages"
                http_method     = "POST"
                payload_sample  = "Employee Rajesh Kumar, PAN: ABCDE1234F, salary review"
                bytes_sent      = 1024
            }
        )
        sanctioned_ai_ids = @()
    }
    if ($result) { info "Events: $($result.events_processed) | Alerts: $($result.alerts_raised)" }
}

function Cmd-Test {
    Cmd-TestConsent
    Cmd-TestClassify
}

function Cmd-Open {
    head "Opening dashboards"
    $urls = @{
        "Traefik Dashboard"    = "http://localhost:8080"
        "Consent Engine API"   = "http://localhost:8003/docs"
        "Role Classifier API"  = "http://localhost:8001/docs"
        "DPIA Engine API"      = "http://localhost:8102/docs"
        "AI Bias Monitor API"  = "http://localhost:8103/docs"
        "HITL Service API"     = "http://localhost:8303/docs"
        "PBAC Engine API"      = "http://localhost:8606/docs"
        "Shadow AI API"        = "http://localhost:8701/docs"
        "Compliance Score API" = "http://localhost:8506/docs"
        "Jaeger Tracing"       = "http://localhost:16686"
        "MinIO Console"        = "http://localhost:9001"
        "Neo4j Browser"        = "http://localhost:7474"
    }
    foreach ($entry in $urls.GetEnumerator()) {
        info "Opening $($entry.Key): $($entry.Value)"
        Start-Process $entry.Value
        Start-Sleep -Milliseconds 300
    }
}

function Cmd-Urls {
    param([switch]$InfraOnly, [string]$Day = "")
    Write-Host ""
    if ($InfraOnly) {
        Write-Host "  Infrastructure URLs:" -ForegroundColor White
        Write-Host "    Traefik Dashboard  http://localhost:8080" -ForegroundColor Gray
        Write-Host "    Jaeger UI          http://localhost:16686" -ForegroundColor Gray
        Write-Host "    MinIO Console      http://localhost:9001" -ForegroundColor Gray
        Write-Host "    Neo4j Browser      http://localhost:7474" -ForegroundColor Gray
        return
    }
    $dayUrls = @{
        day1 = @(
            "Consent Engine     http://localhost:8003/docs",
            "Role Classifier    http://localhost:8001/docs",
            "Lifecycle Mapper   http://localhost:8002/docs",
            "Rights Portal      http://localhost:8004/docs"
        )
        day2 = @(
            "SDF Determinator   http://localhost:8101/docs",
            "DPIA Engine        http://localhost:8102/docs",
            "AI Bias Monitor    http://localhost:8103/docs",
            "Cross-Border PEP   http://localhost:8104/docs"
        )
        day4 = @("HITL Service       http://localhost:8303/docs")
        day6 = @("Compliance Score   http://localhost:8506/docs")
        day7 = @("PBAC Engine        http://localhost:8606/docs")
        day8 = @("Shadow AI          http://localhost:8701/docs", "RAG Privacy        http://localhost:8702/docs")
    }
    if ($Day -and $dayUrls[$Day]) {
        Write-Host "  $Day Service URLs:" -ForegroundColor White
        foreach ($u in $dayUrls[$Day]) { Write-Host "    $u" -ForegroundColor Gray }
    }
    Write-Host ""
}

# -----------------------------------------------------------------------------
# Dispatch
# -----------------------------------------------------------------------------
switch ($Command.ToLower()) {
    "help"          { Cmd-Help }
    "setup"         { Cmd-Setup }
    "infra"         { Cmd-Infra }
    "day1"          { Cmd-Day "day1" }
    "day2"          { Cmd-Day "day2" }
    "day3"          { Cmd-Day "day3" }
    "day4"          { Cmd-Day "day4" }
    "day5"          { Cmd-Day "day5" }
    "day6"          { Cmd-Day "day6" }
    "day7"          { Cmd-Day "day7" }
    "day8"          { Cmd-Day "day8" }
    "all"           { Cmd-All }
    "status"        { Cmd-Status }
    "logs"          { Cmd-Logs ($Args -join " ") }
    "ps"            { Cmd-PS }
    "stop"          { Cmd-Stop }
    "reset"         { Cmd-Reset }
    "build"         { Cmd-Build ($Args -join " ") }
    "pull"          { Cmd-Pull }
    "test"          { Cmd-Test }
    "test-consent"  { Cmd-TestConsent }
    "test-classify" { Cmd-TestClassify }
    "test-dpia"     { Cmd-TestDPIA }
    "test-bias"     { Cmd-TestBias }
    "test-transfer" { Cmd-TestTransfer }
    "test-pbac"     { Cmd-TestPBAC }
    "test-shadow"   { Cmd-TestShadow }
    "open"          { Cmd-Open }
    default {
        warn "Unknown command: '$Command'"
        Cmd-Help
    }
}
