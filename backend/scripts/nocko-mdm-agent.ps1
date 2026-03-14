#Requires -Version 5.1
<#
.SYNOPSIS
    NOCKO MDM Windows Agent v2
.DESCRIPTION
    Lightweight agent for Windows 10/11 managed by NOCKO MDM.
    - Collects hardware inventory (CPU, RAM, disk, monitors, Entra/domain join status)
    - Checks in every $CHECK_IN_MINUTES via REST
    - Executes remote MDM commands: LOCK, SHUTDOWN, RESTART, MESSAGE, RUN_SCRIPT,
      INSTALL_APP (winget / MSI / MSIX), UNINSTALL_APP, SET_WALLPAPER, COLLECT_INVENTORY

.NOTES
    ── Standalone (no Entra) ──────────────────────────────────────────────────
    1. Set $MDM_SERVER and $ENROLLMENT_TOKEN below (or pass via -Server / -Token)
    2. Run as Administrator:
         powershell -ExecutionPolicy Bypass -File nocko-mdm-agent.ps1 -Install

    ── One-liner (auto-installs via dashboard-generated URL) ─────────────────
         irm 'https://mdm.it-uae.com/api/v1/enrollment/windows/script/<token>' | iex

    ── Commands ──────────────────────────────────────────────────────────────
    -Install    Register as a scheduled task (SYSTEM, runs at startup)
    -Uninstall  Remove the scheduled task
    -CheckIn    Run a single check-in now (called by the task)
    -Status     Show agent task status
#>

param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$CheckIn,
    [switch]$Status,
    [string]$Server = "",
    [string]$Token  = ""
)

# ── Configuration ──────────────────────────────────────────────────────────
$MDM_SERVER       = if ($Server) { $Server } else { "https://mdm.it-uae.com/api/v1" }
$ENROLLMENT_TOKEN = if ($Token)  { $Token  } else { "PASTE_ENROLLMENT_TOKEN_HERE" }
$CHECK_IN_MINUTES = 15
$TASK_NAME        = "NOCKO-MDM-Agent"
$AGENT_DIR        = "$env:ProgramData\NOCKO-MDM"
$AGENT_PATH       = $MyInvocation.MyCommand.Path
$LOG_FILE         = "$AGENT_DIR\agent.log"
# ──────────────────────────────────────────────────────────────────────────

function Write-Log {
    param([string]$Msg, [string]$Level = "INFO")
    if (-not (Test-Path $AGENT_DIR)) { New-Item -ItemType Directory -Path $AGENT_DIR -Force | Out-Null }
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts [$Level] $Msg" | Tee-Object -FilePath $LOG_FILE -Append | Write-Host
}

# ── Hardware inventory ─────────────────────────────────────────────────────
function Get-MonitorInfo {
    $monitors = @()
    try {
        $ids = Get-WmiObject -Namespace "root\wmi" -Class WmiMonitorID -EA SilentlyContinue
        foreach ($m in $ids) {
            $decode = { param($arr) if ($arr) { [System.Text.Encoding]::ASCII.GetString($arr -ne 0).Trim() } else { "" } }
            $model  = & $decode $m.UserFriendlyName
            $serial = & $decode $m.SerialNumberID
            $mfr    = & $decode $m.ManufacturerName
            if ($model -or $serial) {
                $monitors += @{ model = $model; serial = $serial; manufacturer = $mfr }
            }
        }
    } catch {}
    return $monitors
}

function Get-HardwareInfo {
    $bios  = Get-WmiObject Win32_BIOS           -EA SilentlyContinue
    $cs    = Get-WmiObject Win32_ComputerSystem  -EA SilentlyContinue
    $os    = Get-WmiObject Win32_OperatingSystem -EA SilentlyContinue
    $disk  = Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='C:'" -EA SilentlyContinue
    $cpu   = Get-WmiObject Win32_Processor -EA SilentlyContinue | Select-Object -First 1
    $net   = Get-NetAdapter -Physical 2>$null | Where-Object { $_.Status -eq "Up" } | Select-Object -First 1

    $dsreg        = (dsregcmd /status 2>$null) -join "`n"
    $entraJoined  = [bool]($dsreg -match "AzureAdJoined\s*:\s*YES")
    $domainJoined = [bool]($dsreg -match "DomainJoined\s*:\s*YES")
    $ramGB  = if ($cs)   { [math]::Round($cs.TotalPhysicalMemory / 1GB, 1) } else { 0 }
    $diskGB = if ($disk) { [math]::Round($disk.Size / 1GB, 0) } else { 0 }
    $ip     = if ($net)  { ($net | Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Select-Object -First 1).IPAddress } else { "" }

    return @{
        device_token  = $ENROLLMENT_TOKEN
        hostname      = $env:COMPUTERNAME
        serial_number = if ($bios) { $bios.SerialNumber.Trim() } else { "" }
        os_version    = if ($os)   { "$($os.Caption) Build $($os.BuildNumber)" } else { [System.Environment]::OSVersion.Version.ToString() }
        model         = if ($cs)   { "$($cs.Manufacturer) $($cs.Model)".Trim() } else { "" }
        manufacturer  = if ($cs)   { $cs.Manufacturer } else { "" }
        ram_gb        = $ramGB
        disk_gb       = $diskGB
        bios_version  = if ($bios) { $bios.SMBIOSBIOSVersion } else { "" }
        cpu_model     = if ($cpu)  { $cpu.Name.Trim() } else { "" }
        current_user  = "$env:USERDOMAIN\$env:USERNAME"
        ip_address    = "$ip"
        mac_address   = if ($net)  { $net.MacAddress } else { "" }
        domain_joined = $domainJoined
        entra_joined  = $entraJoined
        monitors      = @(Get-MonitorInfo)
    }
}

# ── Command handlers ───────────────────────────────────────────────────────
function Exec-Lock         { rundll32.exe user32.dll,LockWorkStation }
function Exec-Shutdown     { Stop-Computer -Force }
function Exec-Restart      { Restart-Computer -Force }

function Exec-Message($p) {
    $title = if ($p.title)   { $p.title }   else { "NOCKO MDM" }
    $msg   = if ($p.message) { $p.message } else { "Message from IT Administrator" }
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($msg, $title, 'OK', 'Information') | Out-Null
}

function Exec-RunScript($p) {
    $out = Invoke-Expression ($p.script)
    return ($out | Out-String)
}

function Exec-InstallApp($p) {
    if ($p.winget_id) {
        $args = @("install", "--id", $p.winget_id, "--silent", "--accept-source-agreements", "--accept-package-agreements")
        $r = & winget @args
        return ($r | Out-String)
    } elseif ($p.msi_url) {
        $tmp = "$env:TEMP\nocko_install_$([guid]::NewGuid()).msi"
        Invoke-WebRequest -Uri $p.msi_url -OutFile $tmp -UseBasicParsing
        Start-Process msiexec.exe -ArgumentList "/i `"$tmp`" /quiet /norestart" -Wait
        Remove-Item $tmp -Force -EA SilentlyContinue
        return "MSI installed from $($p.msi_url)"
    } elseif ($p.msix_url) {
        $tmp = "$env:TEMP\nocko_install_$([guid]::NewGuid()).msix"
        Invoke-WebRequest -Uri $p.msix_url -OutFile $tmp -UseBasicParsing
        Add-AppxPackage -Path $tmp
        Remove-Item $tmp -Force -EA SilentlyContinue
        return "MSIX installed from $($p.msix_url)"
    }
    throw "No valid install source in payload (winget_id / msi_url / msix_url required)"
}

function Exec-UninstallApp($p) {
    if ($p.winget_id) {
        $r = & winget uninstall --id $p.winget_id --silent
        return ($r | Out-String)
    } elseif ($p.app_name) {
        $pkg = Get-Package -Name $p.app_name -EA SilentlyContinue
        if ($pkg) { $pkg | Uninstall-Package -Force }
        else { throw "Package not found: $($p.app_name)" }
    }
}

function Exec-SetWallpaper($p) {
    $tmp = "$env:TEMP\nocko_wallpaper.jpg"
    Invoke-WebRequest -Uri $p.url -OutFile $tmp -UseBasicParsing
    Add-Type -TypeDefinition @"
        using System.Runtime.InteropServices;
        public class NockoWallpaper {
            [DllImport("user32.dll")] public static extern int SystemParametersInfo(int a,int b,string c,int d);
        }
"@
    [NockoWallpaper]::SystemParametersInfo(20, 0, $tmp, 3) | Out-Null
    return "Wallpaper set from $($p.url)"
}

function Exec-CollectInventory { return (Get-HardwareInfo | ConvertTo-Json -Depth 5) }

function Execute-MDMCommand($command) {
    $type    = $command.command_type
    $payload = if ($command.payload) { $command.payload } else { @{} }
    $output  = ""
    $status  = "success"

    try {
        switch ($type) {
            "LOCK"              { Exec-Lock }
            "LOCK_DEVICE"       { Exec-Lock }
            "SHUTDOWN"          { Exec-Shutdown }
            "REBOOT"            { Exec-Restart }
            "RESTART"           { Exec-Restart }
            "MESSAGE"           { Exec-Message $payload }
            "RUN_SCRIPT"        { $output = Exec-RunScript $payload }
            "INSTALL_APP"       { $output = Exec-InstallApp $payload }
            "ANDROID_INSTALL_APP" { $output = Exec-InstallApp $payload }
            "UNINSTALL_APP"     { Exec-UninstallApp $payload }
            "SET_WALLPAPER"     { $output = Exec-SetWallpaper $payload }
            "COLLECT_INVENTORY" { $output = Exec-CollectInventory }
            "COLLECT_INFO"      { $output = "Hardware info sent on check-in" }
            default             { $output = "Unknown command: $type"; $status = "failed" }
        }
    } catch {
        $output = $_.Exception.Message
        $status = "failed"
        Write-Log "Command $type failed: $output" "ERROR"
    }

    $ackBody = @{ status = $status; output = $output } | ConvertTo-Json -Depth 3
    try {
        Invoke-RestMethod -Uri "$MDM_SERVER/mdm/windows/commands/$($command.id)/ack" `
                          -Method POST -ContentType "application/json" -Body $ackBody -EA SilentlyContinue | Out-Null
    } catch { Write-Log "Failed to ACK command $($command.id): $_" "WARN" }
}

# ── Check-in ───────────────────────────────────────────────────────────────
function Do-CheckIn {
    Write-Log "Check-in starting..."
    $hw   = Get-HardwareInfo
    $body = $hw | ConvertTo-Json -Depth 5

    try {
        $resp = Invoke-RestMethod -Uri "$MDM_SERVER/mdm/windows/checkin" `
                                  -Method POST -ContentType "application/json" -Body $body `
                                  -TimeoutSec 30 -EA Stop

        Write-Log "Check-in OK — Device: $($resp.device_id) | Commands: $($resp.commands.Count)"
        foreach ($cmd in $resp.commands) {
            Write-Log "Executing: $($cmd.command_type)"
            Execute-MDMCommand $cmd
        }
    } catch {
        Write-Log "Check-in failed: $($_.Exception.Message)" "WARNING"
    }
}

# ── Install / Uninstall ────────────────────────────────────────────────────
function Install-Agent {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Error "Run as Administrator to install the agent."
        exit 1
    }

    if (-not (Test-Path $AGENT_DIR)) { New-Item -ItemType Directory -Path $AGENT_DIR -Force | Out-Null }

    # Copy script to persistent location
    $dest = "$AGENT_DIR\agent.ps1"
    Copy-Item $AGENT_PATH $dest -Force

    # Patch the copy with the real server/token values
    (Get-Content $dest) `
        -replace 'PASTE_ENROLLMENT_TOKEN_HERE', $ENROLLMENT_TOKEN `
        -replace 'https://mdm.it-uae.com/api/v1', $MDM_SERVER `
        | Set-Content $dest -Encoding UTF8

    $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
                -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dest`" -CheckIn"
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $repeat  = New-ScheduledTaskTrigger -Once -At (Get-Date) `
                -RepetitionInterval (New-TimeSpan -Minutes $CHECK_IN_MINUTES)
    $settings = New-ScheduledTaskSettingsSet `
                    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
                    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -EA SilentlyContinue
    Register-ScheduledTask -TaskName $TASK_NAME `
        -Action $action -Trigger @($trigger, $repeat) `
        -Settings $settings -Principal $principal `
        -Description "NOCKO MDM Device Management Agent" | Out-Null

    Write-Host ""
    Write-Host "  [OK] NOCKO MDM Agent installed successfully" -ForegroundColor Green
    Write-Host "  [>]  Server : $MDM_SERVER"                   -ForegroundColor Cyan
    Write-Host "  [>]  Token  : $ENROLLMENT_TOKEN"             -ForegroundColor Cyan
    Write-Host "  [>]  Check-in every $CHECK_IN_MINUTES minutes (SYSTEM account)" -ForegroundColor Cyan
    Write-Host ""

    Start-ScheduledTask -TaskName $TASK_NAME
    Write-Host "  [>>] Agent started. Device will appear in NOCKO MDM within 60 seconds." -ForegroundColor Green
}

function Uninstall-Agent {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -EA SilentlyContinue
    Write-Host "✅ NOCKO MDM Agent removed." -ForegroundColor Yellow
}

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TASK_NAME -EA SilentlyContinue
    if ($task) {
        Write-Host "Agent task '$TASK_NAME': $($task.State)"
        if (Test-Path $LOG_FILE) {
            Write-Host "`nLast 10 log lines:"
            Get-Content $LOG_FILE -Tail 10
        }
    } else {
        Write-Host "Agent is NOT installed (task '$TASK_NAME' not found)."
    }
}

# ── Entry point ────────────────────────────────────────────────────────────
if     ($Install)   { Install-Agent }
elseif ($Uninstall) { Uninstall-Agent }
elseif ($CheckIn)   { Do-CheckIn }
elseif ($Status)    { Show-Status }
else {
    Write-Host ""
    Write-Host "NOCKO MDM Windows Agent v2" -ForegroundColor Cyan
    Write-Host "===========================" -ForegroundColor Cyan
    Write-Host "  -Install      Install as scheduled task (requires Admin)"
    Write-Host "  -Uninstall    Remove scheduled task"
    Write-Host "  -CheckIn      Run one check-in now"
    Write-Host "  -Status       Show task status + last log lines"
    Write-Host "  -Server URL   Override MDM server URL"
    Write-Host "  -Token  TOK   Override enrollment token"
    Write-Host ""
    Write-Host "Edit the top of this file to set permanent values"
    Write-Host "for MDM_SERVER and ENROLLMENT_TOKEN before distributing."
    Write-Host ""
}
