# Watchdog Script for v9.5 Bot
# Checks every 60 seconds, restarts if bot dies
# Run: powershell -ExecutionPolicy Bypass -File watchdog.ps1

$botDir = $PSScriptRoot
$lockFile = "$botDir\logs\bot.lock"
$logFile = "$botDir\logs\watchdog.log"
$botScript = "live_trader_v9.5_momentum.py"

function Write-WatchdogLog {
    param($message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp | $message" | Add-Content $logFile
    Write-Host "$timestamp | $message"
}

Write-WatchdogLog "Watchdog started"

while ($true) {
    $running = $false
    
    # Check if lock file exists and process is alive
    if (Test-Path $lockFile) {
        $lockPid = Get-Content $lockFile -ErrorAction SilentlyContinue
        if ($lockPid) {
            try {
                $proc = Get-Process -Id $lockPid -ErrorAction Stop
                $running = $true
            } catch {
                # Process doesn't exist
                $running = $false
            }
        }
    }
    
    if (-not $running) {
        Write-WatchdogLog "Bot not running - restarting..."
        
        # Clean up stale lock
        Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
        
        # Kill any orphaned python processes running our bot
        Get-Process python* -ErrorAction SilentlyContinue | ForEach-Object {
            $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
            if ($cmdline -match $botScript) {
                Write-WatchdogLog "Killing orphaned bot process: $($_.Id)"
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            }
        }
        
        Start-Sleep -Seconds 2
        
        # Start bot
        $startParams = @{
            FilePath = "python"
            ArgumentList = "-u", $botScript
            WorkingDirectory = $botDir
            WindowStyle = "Hidden"
            RedirectStandardOutput = "$botDir\logs\v95_out.log"
            RedirectStandardError = "$botDir\logs\v95_err.log"
        }
        Start-Process @startParams
        
        Write-WatchdogLog "Bot restarted"
        
        # Wait a bit before next check
        Start-Sleep -Seconds 30
    }
    
    # Check every 60 seconds
    Start-Sleep -Seconds 60
}
