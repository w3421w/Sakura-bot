<#
Stop the complete QWbot stack for the configured QQ account.

Stops:
  1. the QWbot supervisor (so it cannot restart anything)
  2. the QWbot Python app
  3. the NapCat account Worker and its injected QQ process
  4. NapCat Desktop itself
  5. leftover launcher-user.bat cmd processes

Set QWBOT_QQ_ID, QWBOT_PYTHON and optionally NAPCAT_DIR, or edit the defaults.
The user's normal standalone QQ client is not targeted.
#>

$ErrorActionPreference = 'SilentlyContinue'
$QqId = if ($env:QWBOT_QQ_ID) { $env:QWBOT_QQ_ID } else { 'YOUR_QQ_ID' }
$PythonExe = if ($env:QWBOT_PYTHON) { $env:QWBOT_PYTHON } else { 'python' }
$LockPath = Join-Path $PSScriptRoot 'bot\data\qwbot.lock'

function Stop-Tree {
    param([int]$ProcessId, [string]$Label)
    if ($ProcessId -le 0) { return }
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Stopped $Label PID $ProcessId"
}

function Get-CommandLineProcesses {
    param([string]$Pattern)
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $Pattern })
}

# 1. Supervisor first: it monitors ports and would otherwise restart QWbot.
foreach ($process in (Get-CommandLineProcesses 'start_qwbot\.ps1')) {
    Stop-Tree -ProcessId ([int]$process.ProcessId) -Label 'QWbot supervisor'
}
foreach ($process in (Get-CommandLineProcesses 'start_qwbot\.bat')) {
    Stop-Tree -ProcessId ([int]$process.ProcessId) -Label 'QWbot launcher cmd'
}

# 2. QWbot app. Prefer the configured Python executable when it is a full path.
$appProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match '^python' -and
        $_.CommandLine -and
        $_.CommandLine -match 'app\.py\s+--config\s+config\.json' -and
        (
            $PythonExe -eq 'python' -or
            $_.ExecutablePath -eq $PythonExe -or
            $_.CommandLine -match [regex]::Escape($PythonExe)
        )
    })
foreach ($process in $appProcesses) {
    Stop-Tree -ProcessId ([int]$process.ProcessId) -Label 'QWbot app'
}

# 3. NapCat account Worker (and the QQ process it injected).
$workerIds = @()
try {
    $workerIds = @(Get-CimInstance Win32_Process -Filter "Name='NapCatWinBootMain.exe'" -ErrorAction Stop |
        Where-Object { $_.CommandLine -and $_.CommandLine -match [regex]::Escape($QqId) } |
        ForEach-Object { [int]$_.ProcessId })
}
catch {
    $workers = @(Get-Process -Name NapCatWinBootMain -ErrorAction SilentlyContinue)
    if ($workers.Count -eq 1) { $workerIds = @([int]$workers[0].Id) }
}
foreach ($workerId in $workerIds) {
    Stop-Tree -ProcessId $workerId -Label "NapCat Worker tree (QQ $QqId)"
}

# 4. NapCat Desktop.
foreach ($desktop in @(Get-Process -Name 'NapCatQQ-Desktop' -ErrorAction SilentlyContinue)) {
    Stop-Tree -ProcessId ([int]$desktop.Id) -Label 'NapCat Desktop'
}

# 5. Leftover official launcher cmd processes.
foreach ($process in (Get-CommandLineProcesses 'launcher-user\.bat')) {
    Stop-Tree -ProcessId ([int]$process.ProcessId) -Label 'NapCat launcher cmd'
}

# Final safety net for a stray QWbot app after the supervisor is gone.
if (Test-Path -LiteralPath $LockPath) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match '^python' -and
            $_.CommandLine -and
            $_.CommandLine -match 'app\.py\s+--config'
        } |
        ForEach-Object { Stop-Tree -ProcessId ([int]$_.ProcessId) -Label 'leftover QWbot app' }
}

Start-Sleep -Milliseconds 500
$left = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.CommandLine -and $_.CommandLine -match 'start_qwbot\.ps1|app\.py\s+--config\s+config\.json|launcher-user\.bat') -or
        ($_.Name -eq 'NapCatWinBootMain.exe' -and $_.CommandLine -and $_.CommandLine -match [regex]::Escape($QqId)) -or
        ($_.Name -eq 'NapCatQQ-Desktop.exe')
    })
if ($left.Count -gt 0) {
    Write-Host ''
    Write-Host 'Warning: these processes are still running:'
    $left | Select-Object ProcessId, Name, CommandLine | Format-Table -Wrap | Out-String | Write-Host
    Write-Host 'You can retry stop_qwbot, or close the remaining window manually.'
} else {
    Write-Host ''
    Write-Host 'All QWbot / NapCat processes stopped. Normal QQ was not touched.'
    Write-Host 'OneBot port 3001 should now be closed.'
}
