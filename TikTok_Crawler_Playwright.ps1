# TikTok Crawler - Playwright Version
# Enhanced script for longer execution time (30-40 minutes)

$baseUrl = "https://tiktok-crawler-2-production.up.railway.app"

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "  TIKTOK CRAWLER - PLAYWRIGHT MODE  " -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Health Check
Write-Host "[1/4] Checking Railway service health..." -ForegroundColor Yellow
try {
    $healthResponse = Invoke-RestMethod -Uri "$baseUrl/health" -Method Get -TimeoutSec 30
    
    if ($healthResponse.status -eq "healthy") {
        Write-Host "  ✅ Service is HEALTHY" -ForegroundColor Green
        Write-Host "     - Lark connected: $($healthResponse.lark_connected)" -ForegroundColor Gray
        Write-Host "     - Sheets connected: $($healthResponse.sheets_connected)" -ForegroundColor Gray
        Write-Host "     - Crawler ready: $($healthResponse.crawler_ready)" -ForegroundColor Gray
    } else {
        Write-Host "  ⚠️  Service status: $($healthResponse.status)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ❌ Health check FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please check:" -ForegroundColor Yellow
    Write-Host "  1. Railway service is running" -ForegroundColor Gray
    Write-Host "  2. URL is correct: $baseUrl" -ForegroundColor Gray
    Write-Host "  3. Internet connection is stable" -ForegroundColor Gray
    exit 1
}

Write-Host ""

# Step 2: Trigger Crawl Job
Write-Host "[2/4] Triggering daily crawl job..." -ForegroundColor Yellow
try {
    $triggerResponse = Invoke-RestMethod -Uri "$baseUrl/jobs/daily" -Method Post -TimeoutSec 30
    
    if ($triggerResponse.success -eq $true) {
        Write-Host "  ✅ Crawl job STARTED successfully" -ForegroundColor Green
        Write-Host "     Status: $($triggerResponse.status)" -ForegroundColor Gray
        Write-Host "     Message: $($triggerResponse.message)" -ForegroundColor Gray
        Write-Host "     Started at: $($triggerResponse.timestamp)" -ForegroundColor Gray
    } else {
        Write-Host "  ❌ Failed to start job" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "  ❌ Trigger FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Step 3: Wait for completion
Write-Host "[3/4] Waiting for crawl to complete..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  ⏱️  ESTIMATED TIME: 30-40 minutes (227 videos)" -ForegroundColor Cyan
Write-Host "  📊 ~7-10 seconds per video with Playwright" -ForegroundColor Gray
Write-Host ""
Write-Host "  What's happening now:" -ForegroundColor Yellow
Write-Host "     1. Fetching records from Lark Bitable" -ForegroundColor Gray
Write-Host "     2. Launching Playwright browser" -ForegroundColor Gray
Write-Host "     3. Crawling each TikTok video" -ForegroundColor Gray
Write-Host "     4. Extracting view counts" -ForegroundColor Gray
Write-Host "     5. Updating Google Sheets" -ForegroundColor Gray
Write-Host "     6. Removing duplicates" -ForegroundColor Gray
Write-Host ""

# Progress indicators
$totalMinutes = 35
$checkInterval = 120  # Check every 2 minutes

Write-Host "  Progress updates every 2 minutes:" -ForegroundColor Yellow
Write-Host ""

for ($i = 1; $i -le [Math]::Ceiling($totalMinutes / 2); $i++) {
    $elapsed = $i * 2
    $remaining = $totalMinutes - $elapsed
    
    if ($remaining -lt 0) { $remaining = 0 }
    
    $percentage = [Math]::Min([Math]::Round(($elapsed / $totalMinutes) * 100), 100)
    
    # Progress bar
    $barLength = 30
    $filled = [Math]::Floor($barLength * $percentage / 100)
    $empty = $barLength - $filled
    $bar = "█" * $filled + "░" * $empty
    
    Write-Host "  [$bar] $percentage% " -NoNewline -ForegroundColor Cyan
    Write-Host "($elapsed/$totalMinutes min, ~$remaining min remaining)" -ForegroundColor Gray
    
    # Check health periodically
    if ($i % 3 -eq 0) {
        try {
            $statusCheck = Invoke-RestMethod -Uri "$baseUrl/health" -Method Get -TimeoutSec 10 -ErrorAction SilentlyContinue
            Write-Host "     ✓ Service still running" -ForegroundColor DarkGreen
        } catch {
            Write-Host "     ⚠️  Could not verify service status" -ForegroundColor DarkYellow
        }
    }
    
    # Don't sleep on last iteration
    if ($i -lt [Math]::Ceiling($totalMinutes / 2)) {
        Start-Sleep -Seconds $checkInterval
    }
}

Write-Host ""
Write-Host "  ✅ Expected completion time reached" -ForegroundColor Green
Write-Host ""

# Step 4: Final check
Write-Host "[4/4] Verifying results..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  📋 Please check your Google Sheets:" -ForegroundColor Cyan
Write-Host "     - New 'Last Check Timestamp' values" -ForegroundColor Gray
Write-Host "     - Updated view counts in 'Current Views' column" -ForegroundColor Gray
Write-Host "     - Status column showing 'success' or 'partial'" -ForegroundColor Gray
Write-Host "     - No duplicate Record IDs" -ForegroundColor Gray
Write-Host ""

# Try to get status
try {
    $statusResponse = Invoke-RestMethod -Uri "$baseUrl/status" -Method Get -TimeoutSec 30 -ErrorAction SilentlyContinue
    
    Write-Host "  📊 System Status:" -ForegroundColor Cyan
    Write-Host "     Overall: $($statusResponse.status)" -ForegroundColor Gray
    if ($statusResponse.services) {
        Write-Host "     Services:" -ForegroundColor Gray
        $statusResponse.services.PSObject.Properties | ForEach-Object {
            $icon = if ($_.Value -eq "healthy") { "✅" } else { "⚠️" }
            Write-Host "       $icon $($_.Name): $($_.Value)" -ForegroundColor Gray
        }
    }
} catch {
    Write-Host "  ℹ️  Could not fetch detailed status" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "          JOB COMPLETE              " -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "📌 NEXT STEPS:" -ForegroundColor Yellow
Write-Host "   1. Open your Google Sheets" -ForegroundColor Gray
Write-Host "   2. Verify data has been updated" -ForegroundColor Gray
Write-Host "   3. Check Railway logs for any errors:" -ForegroundColor Gray
Write-Host "      https://railway.app/dashboard" -ForegroundColor DarkCyan
Write-Host ""

Write-Host "💡 TIPS:" -ForegroundColor Yellow
Write-Host "   - Success rate should be > 80%" -ForegroundColor Gray
Write-Host "   - 'partial' status means crawl failed, used Lark data" -ForegroundColor Gray
Write-Host "   - If many failures, check Railway logs" -ForegroundColor Gray
Write-Host ""

Write-Host "Press any key to exit..." -ForegroundColor DarkGray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
