<#
.SYNOPSIS
    QWbot 一键启动与保守型守护脚本

.DESCRIPTION
    同时管理 NapCat Desktop、NapCat 账号 Worker 和 QWbot。
    - NapCat Desktop 不存在时启动 Desktop
    - OneBot 端口不可用且没有 Worker 时，调用 NapCat 官方 launcher-user.bat
    - QWbot 进程退出时自动重启
    - 正常退出启动器时停止 QWbot 与 NapCat，避免账号继续在线
    - 不会反复强杀 QQ；需要扫码/手机验证时保持等待并记录日志

    正常使用：双击 start_qwbot.bat
    检查配置：powershell -ExecutionPolicy Bypass -File .\start_qwbot.ps1 -CheckOnly -Once
    保留 NapCat：powershell -ExecutionPolicy Bypass -File .\start_qwbot.ps1 -KeepNapCat
#>

[CmdletBinding()]
param(
    [switch]$Once,
    [switch]$CheckOnly,
    [switch]$KeepNapCat,
    [int]$IntervalSeconds = 10
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BotDir = Join-Path $ProjectRoot 'bot'
$DataDir = Join-Path $ProjectRoot 'data'
$LauncherLog = Join-Path $DataDir 'launcher.log'
$StdoutLog = Join-Path $DataDir 'qwbot_stdout.log'
$StderrLog = Join-Path $DataDir 'qwbot_stderr.log'
$QwbotLock = Join-Path $BotDir 'data\qwbot.lock'

$QqId = if ($env:QWBOT_QQ_ID) { $env:QWBOT_QQ_ID } else { 'YOUR_QQ_ID' }
$OneBotHost = '127.0.0.1'
$OneBotPort = 3001
$OneBotToken = if ($env:QWBOT_ONEBOT_TOKEN) { $env:QWBOT_ONEBOT_TOKEN } else { 'YOUR_ONEBOT_TOKEN' }
$ConfigPath = Join-Path $BotDir 'config.json'
if (-not $env:QWBOT_ONEBOT_TOKEN -and (Test-Path -LiteralPath $ConfigPath)) {
    try {
        $loadedConfig = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($loadedConfig.onebot.access_token) { $OneBotToken = [string]$loadedConfig.onebot.access_token }
    }
    catch { }
}
$NapCatDesktopExe = if ($env:NAPCAT_DESKTOP_EXE) { $env:NAPCAT_DESKTOP_EXE } else { 'C:\Program Files\NapCatQQ Desktop\NapCatQQ-Desktop.exe' }
$NapCatDir = if ($env:NAPCAT_DIR) { $env:NAPCAT_DIR } else { 'C:\ProgramData\NapCatQQ Desktop\components\NapCatQQ' }
$NapCatLauncher = Join-Path $NapCatDir 'launcher-user.bat'
$NapCatOneBotConfig = Join-Path $NapCatDir ("config\onebot11_{0}.json" -f $QqId)

$PythonCandidates = @(
    ($env:QWBOT_PYTHON),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe')
)
$PythonExe = $PythonCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Write-LauncherLog {
    param([string]$Message)
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $LauncherLog -Value $line -Encoding UTF8
    Write-Host $line
}

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutMilliseconds = 1000
    )
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        if (-not $task.Wait($TimeoutMilliseconds)) { return $false }
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Get-QwbotProcess {
    # Prefer the PID captured when this launcher started QWbot.
    if ($script:QwbotPid) {
        $owned = Get-Process -Id $script:QwbotPid -ErrorAction SilentlyContinue
        if ($owned) {
            return @($owned)
        }
        $script:QwbotPid = $null
    }

    $result = @()
    try {
        $items = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop
        $result = @($items | Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match '(?i)app\.py' -and
            $_.CommandLine -match [regex]::Escape($BotDir)
        })
    }
    catch {
        # CommandLine access may be denied by Windows security policy.
        $result = @()
    }
    if ($result.Count -gt 0) {
        return $result
    }

    # Fallback: the QWbot lock is created only by bot\app.py. If a Python
    # process from the configured runtime exists while that lock exists, treat
    # it as the running bot even when WMI command-line access is denied.
    if (Test-Path -LiteralPath $QwbotLock) {
        return @(Get-Process -Name 'python' -ErrorAction SilentlyContinue | Where-Object {
            try { $_.Path -eq $PythonExe } catch { $false }
        })
    }
    return @()
}

function Get-NapCatWorker {
    $workers = @(Get-Process -Name 'NapCatWinBootMain' -ErrorAction SilentlyContinue)
    if ($workers.Count -eq 0) { return @() }
    try {
        $candidates = @(Get-CimInstance Win32_Process -Filter "Name='NapCatWinBootMain.exe'" -ErrorAction Stop | Where-Object {
            $_.CommandLine -and $_.CommandLine -match [regex]::Escape($QqId)
        })
        if ($candidates.Count -gt 0) {
            $ids = @($candidates | ForEach-Object { [int]$_.ProcessId })
            return @($workers | Where-Object { $ids -contains $_.Id })
        }
        return @()
    }
    catch {
        # If command-line inspection is blocked, a single Worker is safe to
        # associate; with multiple accounts, do not guess and do not kill.
        if ($workers.Count -eq 1) { return $workers }
        return @()
    }
}

function Ensure-NapCatWebsocketServer {
    # QWbot is a reverse-WebSocket client, so NapCat must expose a local
    # WebSocket server before the QQ Worker can be used.  Keep this check in
    # the supervisor so a fresh NapCat profile does not require manual UI setup.
    $config = $null
    if (Test-Path -LiteralPath $NapCatOneBotConfig) {
        try {
            $config = Get-Content -LiteralPath $NapCatOneBotConfig -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        catch {
            Write-LauncherLog "WARN NapCat OneBot config could not be parsed: $NapCatOneBotConfig"
            return
        }
    }

    if ($CheckOnly) {
        $existing = @()
        if ($config -and $config.network) {
            $existing = @($config.network.websocketServers | Where-Object {
                $_.host -eq $OneBotHost -and [int]$_.port -eq $OneBotPort -and $_.enable -eq $true
            })
        }
        if ($existing.Count -gt 0) {
            Write-LauncherLog "CHECK NapCat WebSocket server exists at ${OneBotHost}:${OneBotPort}"
        }
        else {
            Write-LauncherLog "CHECK would create NapCat WebSocket server at ${OneBotHost}:${OneBotPort}"
        }
        return
    }

    if (-not $config) {
        $config = [pscustomobject]@{
            network = [pscustomobject]@{
                httpServers = @()
                httpSseServers = @()
                httpClients = @()
                websocketServers = @()
                websocketClients = @()
                plugins = @()
            }
            musicSignUrl = ''
            enableLocalFile2Url = $false
            parseMultMsg = $false
            imageDownloadProxy = ''
            timeout = [pscustomobject]@{
                baseTimeout = 10000
                uploadSpeedKBps = 256
                downloadSpeedKBps = 256
                maxTimeout = 1800000
            }
        }
    }
    if ($null -eq $config.network) {
        $config | Add-Member -NotePropertyName network -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    # An empty array is falsy in PowerShell, so "-not $config.network.websocketServers"
    # is true for a valid "websocketServers": [] entry and Add-Member then fails
    # with "member already exists".  Check the property itself, not its value.
    if ($null -eq $config.network.PSObject.Properties['websocketServers']) {
        $config.network | Add-Member -NotePropertyName websocketServers -NotePropertyValue @() -Force
    }

    $servers = @($config.network.websocketServers)
    $server = $servers | Where-Object {
        $_.host -eq $OneBotHost -and [int]$_.port -eq $OneBotPort
    } | Select-Object -First 1
    $changed = $false
    if (-not $server) {
        $server = [pscustomobject]@{
            enable = $true
            name = 'qwbot'
            host = $OneBotHost
            port = $OneBotPort
            reportSelfMessage = $false
            enableForcePushEvent = $false
            messagePostFormat = 'array'
            token = $OneBotToken
            debug = $false
            heartInterval = 30000
        }
        $config.network.websocketServers = @($servers + $server)
        $changed = $true
    }
    else {
        if ($server.enable -ne $true) { $server.enable = $true; $changed = $true }
        if ([string]$server.host -ne $OneBotHost) { $server.host = $OneBotHost; $changed = $true }
        if ([int]$server.port -ne $OneBotPort) { $server.port = $OneBotPort; $changed = $true }
        if ([string]$server.messagePostFormat -ne 'array') { $server.messagePostFormat = 'array'; $changed = $true }
        if ([string]$server.token -ne $OneBotToken) { $server.token = $OneBotToken; $changed = $true }
    }

    if (-not $changed) { return }
    try {
        $json = $config | ConvertTo-Json -Depth 20
        Set-Content -LiteralPath $NapCatOneBotConfig -Value $json -Encoding UTF8
        Write-LauncherLog "CONFIG NapCat WebSocket server ensured at ${OneBotHost}:${OneBotPort}"
    }
    catch {
        Write-LauncherLog "WARN could not write NapCat OneBot config: $($_.Exception.Message)"
    }
}

function Ensure-NapCatDesktop {
    $desktop = @(Get-Process -Name 'NapCatQQ-Desktop' -ErrorAction SilentlyContinue)
    if ($desktop.Count -gt 0) {
        return
    }
    if (-not (Test-Path -LiteralPath $NapCatDesktopExe)) {
        Write-LauncherLog "ERROR NapCat Desktop not found: $NapCatDesktopExe"
        return
    }
    if ($CheckOnly) {
        Write-LauncherLog 'CHECK NapCat Desktop is not running; would start it'
        return
    }
    $started = Start-Process -FilePath $NapCatDesktopExe -WorkingDirectory (Split-Path -Parent $NapCatDesktopExe) -PassThru
    $script:NapCatDesktopPids = @($started.Id)
    $script:NapCatDesktopStartedByLauncher = $true
    $script:DesktopStartAt = Get-Date
    Write-LauncherLog 'START NapCat Desktop'
}

$script:LastLauncherStart = [datetime]::MinValue
$script:LastWaitingLog = [datetime]::MinValue
$script:DesktopStartAt = [datetime]::MinValue
$script:QwbotPid = $null
$script:NapCatWorkerPids = @()
$script:NapCatDesktopPids = @()
$script:NapCatDesktopStartedByLauncher = $false
$script:Cycle = 0

function Ensure-NapCatWorker {
    $worker = Get-NapCatWorker
    if ($worker.Count -gt 0) {
        $script:NapCatWorkerPids = @($worker | ForEach-Object { $_.Id })
    }

    if (Test-TcpPort -HostName $OneBotHost -Port $OneBotPort) {
        return
    }

    # Give NapCat Desktop time to start its account worker and avoid duplicates.
    if ((Get-Date) - $script:DesktopStartAt -lt [timespan]::FromSeconds(20)) {
        return
    }

    if ($worker.Count -gt 0) {
        # NapCat reads its OneBot config during Worker startup.  If the config
        # was repaired after this Worker started, the Worker is running with the
        # old empty network config and will never open 3001.  Restart it once so
        # it reloads the server entry instead of waiting forever for QR/login.
        try {
            $workerStart = ($worker | Sort-Object StartTime | Select-Object -First 1).StartTime
            $configTime = (Get-Item -LiteralPath $NapCatOneBotConfig -ErrorAction Stop).LastWriteTime
            if ($configTime -gt $workerStart.AddSeconds(2) -and
                ((Get-Date) - $workerStart).TotalSeconds -gt 15) {
                Write-LauncherLog "REPAIR NapCat Worker started before OneBot config; restarting Worker tree"
                foreach ($item in $worker) {
                    & taskkill.exe /PID ([int]$item.Id) /T /F 2>$null | Out-Null
                }
                $script:LastLauncherStart = [datetime]::MinValue
                return
            }
        }
        catch {
            # Process timestamps can be unavailable under restricted process
            # permissions; fall back to the existing wait/QR path below.
        }
        if ((Get-Date) - $script:LastWaitingLog -gt [timespan]::FromSeconds(60)) {
            Write-LauncherLog 'WAIT OneBot port is closed; NapCat Worker exists and may be waiting for QQ login/QR verification'
            $script:LastWaitingLog = Get-Date
        }
        return
    }

    if (-not (Test-Path -LiteralPath $NapCatLauncher)) {
        Write-LauncherLog "ERROR NapCat launcher not found: $NapCatLauncher"
        return
    }
    if ((Get-Date) - $script:LastLauncherStart -lt [timespan]::FromSeconds(120)) {
        return
    }
    if ($CheckOnly) {
        Write-LauncherLog "CHECK NapCat Worker is not running; would run launcher-user.bat $QqId"
        return
    }

    # The official NapCat launcher supplies QQ.exe, Hook DLL, and the account argument.
    $launcherCommand = '/c ""{0}" {1}"' -f $NapCatLauncher, $QqId
    Start-Process -FilePath 'cmd.exe' -ArgumentList $launcherCommand -WorkingDirectory $NapCatDir -WindowStyle Hidden | Out-Null
    $script:LastLauncherStart = Get-Date
    Write-LauncherLog "START NapCat account launcher QQ=$QqId"
}

function Ensure-Qwbot {
    $running = Get-QwbotProcess
    if ($running.Count -gt 0) {
        $candidate = $running | Select-Object -First 1
        $candidatePid = $candidate.Id
        if (-not $candidatePid) { $candidatePid = $candidate.ProcessId }
        if ($candidatePid) { $script:QwbotPid = [int]$candidatePid }
        return
    }
    if (-not $PythonExe) {
        Write-LauncherLog 'ERROR Python runtime not found; set QWBOT_PYTHON or install Python 3.11'
        return
    }
    if (-not (Test-Path -LiteralPath (Join-Path $BotDir 'app.py'))) {
        Write-LauncherLog "ERROR QWbot entrypoint not found: $(Join-Path $BotDir 'app.py')"
        return
    }
    if ($CheckOnly) {
        Write-LauncherLog "CHECK QWbot is not running; would start $PythonExe app.py"
        return
    }

    $started = Start-Process -FilePath $PythonExe `
        -ArgumentList @('app.py', '--config', 'config.json') `
        -WorkingDirectory $BotDir `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -WindowStyle Hidden -PassThru
    $script:QwbotPid = $started.Id
    Write-LauncherLog "START QWbot app.py pid=$($started.Id)"
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    $existing = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $existing) { return }
    try {
        & taskkill.exe /PID $ProcessId /T /F | Out-Null
        Write-LauncherLog "STOP process tree pid=$ProcessId"
    }
    catch {
        Write-LauncherLog "WARN failed to stop process tree pid=${ProcessId}: $($_.Exception.Message)"
    }
}

function Stop-ManagedServices {
    if ($CheckOnly -or $Once -or $KeepNapCat) {
        return
    }

    Write-LauncherLog 'INFO launcher exiting; stopping managed QWbot/NapCat services'

    if ($script:QwbotPid) {
        $bot = Get-Process -Id $script:QwbotPid -ErrorAction SilentlyContinue
        if ($bot) {
            Stop-Process -Id $script:QwbotPid -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            if (Get-Process -Id $script:QwbotPid -ErrorAction SilentlyContinue) {
                Stop-Process -Id $script:QwbotPid -Force -ErrorAction SilentlyContinue
            }
            Write-LauncherLog "STOP QWbot pid=$($script:QwbotPid)"
        }
    }

    foreach ($workerPid in @($script:NapCatWorkerPids)) {
        Stop-ProcessTree -ProcessId ([int]$workerPid)
    }

    if (-not $script:NapCatDesktopStartedByLauncher) {
        return
    }
    foreach ($desktopPid in @($script:NapCatDesktopPids)) {
        if (Get-Process -Id $desktopPid -ErrorAction SilentlyContinue) {
            Stop-Process -Id $desktopPid -Force -ErrorAction SilentlyContinue
            Write-LauncherLog "STOP NapCat Desktop pid=$desktopPid"
        }
    }
}

function Ensure-Stack {
    # Keep the steps independent: a NapCat config problem must not prevent
    # QWbot from starting (and retrying its connection) on the same cycle.
    try { Ensure-NapCatWebsocketServer }
    catch { Write-LauncherLog "ERROR NapCat websocket step failed: $($_.Exception.Message)" }
    try { Ensure-NapCatDesktop }
    catch { Write-LauncherLog "ERROR NapCat Desktop step failed: $($_.Exception.Message)" }
    try { Ensure-NapCatWorker }
    catch { Write-LauncherLog "ERROR NapCat worker step failed: $($_.Exception.Message)" }
    try { Ensure-Qwbot }
    catch { Write-LauncherLog "ERROR QWbot start step failed: $($_.Exception.Message)" }
}

function Write-SupervisorStatus {
    # A healthy cycle is otherwise silent, which makes the console look frozen.
    # Emit one compact status line on the first cycle and then once a minute.
    $bot = @(Get-QwbotProcess)
    $botPid = $null
    if ($bot.Count -gt 0) {
        $botPid = $bot[0].Id
        if (-not $botPid) { $botPid = $bot[0].ProcessId }
    }
    $botState = if ($botPid) { "running(pid=$botPid)" } else { 'stopped' }
    $portState = if (Test-TcpPort -HostName $OneBotHost -Port $OneBotPort) { 'open' } else { 'closed' }
    $desktopCount = @(Get-Process -Name 'NapCatQQ-Desktop' -ErrorAction SilentlyContinue).Count
    Write-LauncherLog "INFO supervisor alive cycle=$script:Cycle qwbot=$botState onebot_port=$portState napcat_desktop=$desktopCount"
}

$script:LauncherMutex = $null
if (-not $CheckOnly) {
    try {
        $script:LauncherMutex = [System.Threading.Mutex]::new($false, 'Local\QWbotLauncher_' + $QqId)
        if (-not $script:LauncherMutex.WaitOne(0)) {
            Write-LauncherLog 'ERROR another QWbot launcher is already running; this window will exit'
            exit 4
        }
    }
    catch {
        Write-LauncherLog "WARN launcher single-instance guard unavailable: $($_.Exception.Message)"
    }
}

if ($IntervalSeconds -lt 3) { $IntervalSeconds = 3 }
Write-LauncherLog "INFO launcher started once=$Once checkOnly=$CheckOnly keepNapCat=$KeepNapCat interval=${IntervalSeconds}s"

try {
    do {
        try {
            Ensure-Stack
        }
        catch {
            Write-LauncherLog "ERROR supervisor cycle failed: $($_.Exception.Message)"
        }

        $script:Cycle++
        if ($script:Cycle -eq 1 -or ($script:Cycle % 6) -eq 0) {
            try { Write-SupervisorStatus }
            catch { Write-LauncherLog "WARN status probe failed: $($_.Exception.Message)" }
        }

        if ($Once) { break }
        Start-Sleep -Seconds $IntervalSeconds
    } while ($true)
}
finally {
    Stop-ManagedServices
    Write-LauncherLog 'INFO launcher stopped'
    if ($script:LauncherMutex) {
        try { $script:LauncherMutex.ReleaseMutex() } catch { }
        $script:LauncherMutex.Dispose()
    }
}
