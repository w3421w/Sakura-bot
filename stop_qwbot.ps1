<#
Stop the QWbot stack for the configured QQ account.
Only a NapCat Worker whose command line contains that QQ number is targeted.
Set QWBOT_QQ_ID and QWBOT_PYTHON, or edit the defaults below.
#>

$ErrorActionPreference = 'SilentlyContinue'
$QqId = if ($env:QWBOT_QQ_ID) { $env:QWBOT_QQ_ID } else { 'YOUR_QQ_ID' }
$PythonExe = if ($env:QWBOT_PYTHON) { $env:QWBOT_PYTHON } else { 'python' }
$LockPath = Join-Path $PSScriptRoot 'bot\data\qwbot.lock'

if (Test-Path -LiteralPath $LockPath) {
    $targets = @()
    try {
        $targets = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop |
            Where-Object {
                $_.CommandLine -and
                $_.CommandLine -match 'app\.py' -and
                $_.CommandLine -match [regex]::Escape($PSScriptRoot)
            })
    }
    catch {
        if ($PythonExe -ne 'python') {
            $targets = @(Get-Process -Name python -ErrorAction SilentlyContinue |
                Where-Object { try { $_.Path -eq $PythonExe } catch { $false } })
        }
    }
    foreach ($target in $targets) {
        $targetId = if ($target.ProcessId) { $target.ProcessId } else { $target.Id }
        if (-not $targetId) { continue }
        Stop-Process -Id $targetId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped QWbot PID $targetId"
    }
}

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
    & taskkill.exe /PID $workerId /T /F | Out-Null
    Write-Host "Stopped NapCat Worker tree PID $workerId (QQ $QqId)"
}

Write-Host 'QWbot stop requested. NapCat Desktop was left running.'
