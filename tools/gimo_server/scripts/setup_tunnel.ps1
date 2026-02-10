# Repo Orchestrator Tunnel Setup Helper

Write-Host "--- Repo Orchestrator: Cloudflare Tunnel Setup ---" -ForegroundColor Cyan

# 1. Check cloudflared
if (!(Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: cloudflared not found in PATH." -ForegroundColor Red
    Write-Host "Suggestion: choco install cloudflared" -ForegroundColor Yellow
    exit
}

# 2. Login
Write-Host "Step 1: Authenticating cloudflared..."
# cloudflared tunnel login

# 3. Create Tunnel
Write-Host "Step 2: Creating tunnel 'repo-orchestrator'..."
# cloudflared tunnel create repo-orchestrator

# 4. Route DNS
Write-Host "Step 3: Routing DNS (Replace YOUR-DOMAIN.COM)..."
# cloudflared tunnel route dns repo-orchestrator orch.YOUR-DOMAIN.COM

# 5. Run Tunnel
Write-Host "Step 4: Running tunnel..."
# cloudflared tunnel run --url http://localhost:9325 repo-orchestrator

Write-Host "--- Cloudflare Access Instructions ---" -ForegroundColor Green
Write-Host "1. Go to Cloudflare Zero Trust > Access > Applications."
Write-Host "2. Create/verify app for host 'orch.YOUR-DOMAIN.COM'."
Write-Host "3. Policy: DENY ALL by default. Exceptions: Owner Identity + Service Token (ChatGPT Actions)."
