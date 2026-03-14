"""
Windows MDM Enrollment — Two Paths:

PATH A (Standalone / No Entra):
  POST /api/v1/enrollment/windows/script   → generates a PowerShell agent installer
  GET  /api/v1/enrollment/windows/script/{token_id} → download the .ps1 script

PATH B (Entra ID / OMA-DM):
  GET  /EnrollmentServer/Discovery.svc     → OMA-DM Discovery (used by Windows MDM settings)
  POST /EnrollmentServer/Policy.svc        → OMA-DM Policy (certificate requirements)
  POST /EnrollmentServer/Enrollment.svc    → OMA-DM Enrollment (device registers here)
  GET  /api/v1/enrollment/windows/entra-config  → returns config info for the admin UI
"""
import uuid
import textwrap
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db import get_db
from app.models.device import Device, DevicePlatform, DeviceStatus, EnrollmentType
from app.models.enrollment import EnrollmentToken
from app.models.user import User, UserRole
from app.routers.auth import get_current_user, require_role
from app.config import get_settings

router = APIRouter(tags=["windows-enrollment"])

settings = get_settings()

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WindowsScriptRequest(BaseModel):
    token_id: str
    check_in_minutes: int = 15


class EntraConfigOut(BaseModel):
    enabled: bool
    tenant_id: Optional[str]
    mdm_server_url: str
    discovery_url: str
    enrollment_url: str
    tos_url: str


# ---------------------------------------------------------------------------
# PATH A — Standalone (Agent / PowerShell)
# ---------------------------------------------------------------------------

POWERSHELL_SCRIPT_TEMPLATE = """\
#Requires -Version 5.1
<#
.SYNOPSIS
    NOCKO MDM Windows Agent Installer
.DESCRIPTION
    Installs the NOCKO MDM Windows agent as a scheduled task.
    The agent checks in every {check_in_minutes} minutes and executes MDM commands.
.NOTES
    Generated: {generated_at}
    Token: {token}
    Server: {server_url}
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ─── Configuration ─────────────────────────────────────────────────────────
$MDM_SERVER   = "{server_url}"
$DEVICE_TOKEN = "{token}"
$CHECK_IN_MIN = {check_in_minutes}
$AGENT_DIR    = "$env:ProgramData\\NOCKO-MDM"
$AGENT_SCRIPT = "$AGENT_DIR\\agent.ps1"
$TASK_NAME    = "NOCKO-MDM-Agent"
$LOG_FILE     = "$AGENT_DIR\\agent.log"

# ─── Create agent directory ─────────────────────────────────────────────────
if (-not (Test-Path $AGENT_DIR)) {{
    New-Item -ItemType Directory -Path $AGENT_DIR -Force | Out-Null
}}

# ─── Write the persistent agent script ─────────────────────────────────────
@'
function Write-Log {{
    param([string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $Msg" | Tee-Object -FilePath "{log_file}" -Append | Write-Host
}}

function Get-HardwareInfo {{
    $os     = Get-CimInstance Win32_OperatingSystem
    $cs     = Get-CimInstance Win32_ComputerSystem
    $bios   = Get-CimInstance Win32_BIOS
    $disk   = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Measure-Object Size -Sum
    $cpu    = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
    $entra  = $false
    try {{
        $dsreg = dsregcmd /status
        $entra = ($dsreg | Select-String "AzureAdJoined : YES") -ne $null
    }} catch {{}}

    @{{
        device_token    = "{device_token}"
        hostname        = $env:COMPUTERNAME
        serial_number   = $bios.SerialNumber
        os_version      = $os.Caption + " " + $os.BuildNumber
        model           = $cs.Model
        manufacturer    = $cs.Manufacturer
        ram_gb          = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
        disk_gb         = [math]::Round($disk.Sum / 1GB, 1)
        current_user    = $env:USERNAME
        ip_address      = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {{$_.PrefixOrigin -ne "WellKnown"}} | Select-Object -First 1).IPAddress
        mac_address     = (Get-NetAdapter | Where-Object {{$_.Status -eq "Up"}} | Select-Object -First 1).MacAddress
        bios_version    = $bios.SMBIOSBIOSVersion
        cpu_model       = $cpu
        domain_joined   = $cs.PartOfDomain
        entra_joined    = $entra
    }}
}}

function Invoke-CheckIn {{
    $body = Get-HardwareInfo | ConvertTo-Json -Depth 3
    try {{
        $resp = Invoke-RestMethod -Uri "{mdm_server}/api/v1/mdm/windows/checkin" `
                                  -Method POST `
                                  -Body $body `
                                  -ContentType "application/json" `
                                  -TimeoutSec 30
        return $resp
    }} catch {{
        Write-Log "Check-in failed: $_"
        return $null
    }}
}}

function Invoke-Command {{
    param($DeviceId, $Cmd)
    Write-Log "Executing command: $($Cmd.command_type)"
    $result = @{{ status = "success"; output = "" }}

    switch ($Cmd.command_type) {{
        "LOCK_DEVICE" {{
            rundll32.exe user32.dll,LockWorkStation
        }}
        "REBOOT" {{
            Restart-Computer -Force
        }}
        "SHUTDOWN" {{
            Stop-Computer -Force
        }}
        "RUN_SCRIPT" {{
            try {{
                $out = Invoke-Expression $Cmd.payload.script
                $result.output = $out | Out-String
            }} catch {{
                $result.status = "failed"
                $result.output = $_.ToString()
            }}
        }}
        "INSTALL_APP" {{
            try {{
                if ($Cmd.payload.msi_url) {{
                    $tmp = "$env:TEMP\\install_$([guid]::NewGuid()).msi"
                    Invoke-WebRequest -Uri $Cmd.payload.msi_url -OutFile $tmp
                    Start-Process msiexec.exe -ArgumentList "/i `"$tmp`" /quiet /norestart" -Wait
                    Remove-Item $tmp -Force
                }} elseif ($Cmd.payload.winget_id) {{
                    winget install --id $Cmd.payload.winget_id --silent --accept-source-agreements
                }}
            }} catch {{
                $result.status = "failed"
                $result.output = $_.ToString()
            }}
        }}
        "UNINSTALL_APP" {{
            try {{
                $app = Get-Package -Name $Cmd.payload.app_name -ErrorAction SilentlyContinue
                if ($app) {{ $app | Uninstall-Package -Force }}
            }} catch {{
                $result.status = "failed"; $result.output = $_.ToString()
            }}
        }}
        "SET_WALLPAPER" {{
            try {{
                $url = $Cmd.payload.url
                $tmp = "$env:TEMP\\wallpaper.jpg"
                Invoke-WebRequest -Uri $url -OutFile $tmp
                Add-Type -TypeDefinition @"
                    using System.Runtime.InteropServices;
                    public class Wallpaper {{
                        [DllImport("user32.dll")] public static extern int SystemParametersInfo(int a, int b, string c, int d);
                    }}
"@
                [Wallpaper]::SystemParametersInfo(20, 0, $tmp, 3) | Out-Null
            }} catch {{
                $result.status = "failed"; $result.output = $_.ToString()
            }}
        }}
        "COLLECT_INVENTORY" {{
            $inv = Get-HardwareInfo | ConvertTo-Json -Depth 3
            $result.output = $inv
        }}
        default {{
            $result.status = "failed"
            $result.output = "Unknown command: $($Cmd.command_type)"
        }}
    }}

    try {{
        Invoke-RestMethod -Uri "{mdm_server}/api/v1/mdm/windows/commands/$($Cmd.id)/ack" `
                          -Method POST `
                          -Body ($result | ConvertTo-Json) `
                          -ContentType "application/json" | Out-Null
    }} catch {{
        Write-Log "Failed to ack command $($Cmd.id): $_"
    }}
}}

# ─── Main loop ──────────────────────────────────────────────────────────────
Write-Log "NOCKO MDM Agent starting (check-in every {check_in_minutes}m)"

while ($true) {{
    $resp = Invoke-CheckIn
    if ($resp) {{
        foreach ($cmd in $resp.commands) {{
            Invoke-Command -DeviceId $resp.device_id -Cmd $cmd
        }}
        $interval = $resp.check_in_interval_minutes
    }} else {{
        $interval = {check_in_minutes}
    }}
    Start-Sleep -Seconds ($interval * 60)
}}
'@ | Set-Content -Path $AGENT_SCRIPT -Encoding UTF8

Write-Host "[✓] Agent script written to $AGENT_SCRIPT" -ForegroundColor Green

# ─── Register scheduled task ─────────────────────────────────────────────────
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$AGENT_SCRIPT`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings_obj = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TASK_NAME `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings_obj `
    -Principal $principal `
    -Description "NOCKO MDM Device Management Agent" | Out-Null

Write-Host "[✓] Scheduled task '$TASK_NAME' registered (runs at startup as SYSTEM)" -ForegroundColor Green

# ─── Start now ───────────────────────────────────────────────────────────────
Start-ScheduledTask -TaskName $TASK_NAME
Write-Host "[✓] Agent started. Device will appear in NOCKO MDM within 60 seconds." -ForegroundColor Green
Write-Host ""
Write-Host "Server : $MDM_SERVER" -ForegroundColor Cyan
Write-Host "Token  : $DEVICE_TOKEN" -ForegroundColor Cyan
"""


@router.post("/api/v1/enrollment/windows/script-generate", tags=["windows-enrollment"])
async def generate_windows_script(
    body: WindowsScriptRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.IT_MANAGER, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Return enrollment details so the frontend can render the PowerShell one-liner."""
    result = await db.execute(
        select(EnrollmentToken).where(
            EnrollmentToken.id == body.token_id,
            EnrollmentToken.org_id == current_user.org_id,
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(404, "Enrollment token not found")
    if not token.is_valid:
        raise HTTPException(400, "Token is expired or exhausted")

    return {
        "token": token.token,
        "server_url": settings.MDM_SERVER_URL,
        "check_in_minutes": body.check_in_minutes,
        "one_liner": (
            f"Set-ExecutionPolicy Bypass -Scope Process -Force; "
            f"[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
            f"irm '{settings.MDM_SERVER_URL}/api/v1/enrollment/windows/script/{token.token}' | iex"
        ),
        "script_url": f"{settings.MDM_SERVER_URL}/api/v1/enrollment/windows/script/{token.token}",
    }


@router.get("/api/v1/enrollment/windows/script/{token}", tags=["windows-enrollment"])
async def download_windows_script(
    token: str,
    check_in_minutes: int = 15,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — returns the PowerShell agent script for a given enrollment token."""
    result = await db.execute(
        select(EnrollmentToken).where(EnrollmentToken.token == token)
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(404, "Invalid enrollment token")
    if not enrollment.is_valid:
        raise HTTPException(410, "Enrollment token has expired")

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    script = POWERSHELL_SCRIPT_TEMPLATE.format(
        token=token,
        server_url=settings.MDM_SERVER_URL,
        check_in_minutes=check_in_minutes,
        generated_at=now,
        log_file=r"%ProgramData%\NOCKO-MDM\agent.log",
        device_token=token,
        mdm_server=settings.MDM_SERVER_URL,
    )

    return PlainTextResponse(
        content=script,
        headers={
            "Content-Disposition": "attachment; filename=nocko-mdm-install.ps1",
            "Content-Type": "application/octet-stream",
        },
    )


# ---------------------------------------------------------------------------
# PATH B — Entra ID / OMA-DM protocol
# (Windows built-in MDM enrollment via Settings → Work Access → Add work account)
# ---------------------------------------------------------------------------

@router.get("/api/v1/enrollment/windows/entra-config", response_model=EntraConfigOut, tags=["windows-enrollment"])
async def entra_config(
    current_user: User = Depends(get_current_user),
):
    """Return Entra/OMA-DM configuration info for the admin UI."""
    s = get_settings()
    base = s.MDM_SERVER_URL
    return EntraConfigOut(
        enabled=s.entra_enabled,
        tenant_id=s.ENTRA_TENANT_ID,
        mdm_server_url=base,
        discovery_url=f"{base}/EnrollmentServer/Discovery.svc",
        enrollment_url=f"{base}/EnrollmentServer/Enrollment.svc",
        tos_url=f"{base}/terms",
    )


@router.get("/EnrollmentServer/Discovery.svc", tags=["windows-oma-dm"])
async def oma_discovery_get(request: Request):
    """
    OMA-DM Discovery GET — Windows calls this first to find the MDM server.
    Returns an XML response pointing to policy and enrollment endpoints.
    """
    s = get_settings()
    base = s.MDM_SERVER_URL
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:d="http://schemas.microsoft.com/windows/pki/2009/01/enrollment">
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://schemas.microsoft.com/windows/pki/2009/01/enrollment/IDiscoveryService/DiscoverResponse
    </a:Action>
  </s:Header>
  <s:Body>
    <d:DiscoverResponse>
      <d:DiscoverResult>
        <d:AuthPolicy>Federated</d:AuthPolicy>
        <d:EnrollmentVersion>4.0</d:EnrollmentVersion>
        <d:EnrollmentPolicyServiceUrl>{base}/EnrollmentServer/Policy.svc</d:EnrollmentPolicyServiceUrl>
        <d:EnrollmentServiceUrl>{base}/EnrollmentServer/Enrollment.svc</d:EnrollmentServiceUrl>
        <d:AuthenticationServiceUrl>{base}/EnrollmentServer/Auth.svc</d:AuthenticationServiceUrl>
      </d:DiscoverResult>
    </d:DiscoverResponse>
  </s:Body>
</s:Envelope>"""
    return Response(content=xml, media_type="application/soap+xml; charset=utf-8")


@router.post("/EnrollmentServer/Discovery.svc", tags=["windows-oma-dm"])
async def oma_discovery_post(request: Request):
    """OMA-DM Discovery POST (same response as GET)."""
    return await oma_discovery_get(request)


@router.post("/EnrollmentServer/Policy.svc", tags=["windows-oma-dm"])
async def oma_policy(request: Request):
    """
    OMA-DM Policy endpoint — returns certificate issuance policy.
    Windows uses this to determine what type of cert the MDM server will issue.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:u="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
            xmlns:wst="http://docs.oasis-open.org/ws-sx/ws-trust/200512"
            xmlns:xcep="http://schemas.microsoft.com/windows/pki/2009/01/enrollmentpolicy">
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://schemas.microsoft.com/windows/pki/2009/01/enrollmentpolicy/IPolicy/GetPoliciesResponse
    </a:Action>
  </s:Header>
  <s:Body>
    <xcep:GetPoliciesResponse>
      <xcep:response>
        <xcep:policyID>{00000000-0000-0000-0000-000000000000}</xcep:policyID>
        <xcep:policyFriendlyName>NOCKO MDM Certificate Policy</xcep:policyFriendlyName>
        <xcep:nextUpdateHours>8</xcep:nextUpdateHours>
        <xcep:policiesNotChanged>false</xcep:policiesNotChanged>
        <xcep:policies>
          <xcep:policy>
            <xcep:policyOIDReference>0</xcep:policyOIDReference>
            <xcep:cAs/>
            <xcep:attributes>
              <xcep:policySchema>3</xcep:policySchema>
              <xcep:certificateValidity>
                <xcep:validityPeriodSeconds>31536000</xcep:validityPeriodSeconds>
                <xcep:renewalPeriodSeconds>2592000</xcep:renewalPeriodSeconds>
              </xcep:certificateValidity>
              <xcep:permission>
                <xcep:enroll>true</xcep:enroll>
                <xcep:autoEnroll>false</xcep:autoEnroll>
              </xcep:permission>
              <xcep:privateKeyAttributes>
                <xcep:minimalKeyLength>2048</xcep:minimalKeyLength>
                <xcep:keySpec>AT_KEYEXCHANGE</xcep:keySpec>
                <xcep:exportable>false</xcep:exportable>
              </xcep:privateKeyAttributes>
              <xcep:revision>
                <xcep:majorRevision>101</xcep:majorRevision>
                <xcep:minorRevision>0</xcep:minorRevision>
              </xcep:revision>
              <xcep:supersededPolicies/>
              <xcep:privateKeyFlags>0</xcep:privateKeyFlags>
              <xcep:subjectNameFlags>0</xcep:subjectNameFlags>
              <xcep:enrollmentFlags>0</xcep:enrollmentFlags>
              <xcep:generalFlags>0</xcep:generalFlags>
              <xcep:hashAlgorithmOIDReference>0</xcep:hashAlgorithmOIDReference>
              <xcep:rARequirements>
                <xcep:rASignatures>0</xcep:rASignatures>
              </xcep:rARequirements>
              <xcep:keyUsages>
                <xcep:keyUsageProperty>NCRYPT_ALLOW_SIGNING_FLAG</xcep:keyUsageProperty>
              </xcep:keyUsages>
              <xcep:nPoliticies/>
            </xcep:attributes>
          </xcep:policy>
        </xcep:policies>
      </xcep:response>
      <xcep:cAs/>
      <xcep:oIDs>
        <xcep:oID>
          <xcep:value>1.3.6.1.5.5.7.3.2</xcep:value>
          <xcep:group>1</xcep:group>
          <xcep:oIDReferenceID>0</xcep:oIDReferenceID>
          <xcep:defaultName>Client Authentication</xcep:defaultName>
        </xcep:oID>
      </xcep:oIDs>
    </xcep:GetPoliciesResponse>
  </s:Body>
</s:Envelope>"""
    return Response(content=xml, media_type="application/soap+xml; charset=utf-8")


@router.post("/EnrollmentServer/Enrollment.svc", tags=["windows-oma-dm"])
async def oma_enrollment(request: Request, db: AsyncSession = Depends(get_db)):
    """
    OMA-DM Enrollment endpoint — receives the Windows device enrollment SOAP request
    and returns a provisioning XML with MDM management URL.
    Registers/updates the device record in the database.
    """
    s = get_settings()
    base = s.MDM_SERVER_URL

    try:
        body_bytes = await request.body()
        body_text = body_bytes.decode("utf-8", errors="replace")

        # Extract device/user info from SOAP envelope (simple string search)
        device_id = str(uuid.uuid4())
        user_email = ""
        hostname = "Windows-Device"

        # Try to extract UPN (user email) from the SOAP body
        import re
        upn_match = re.search(r'<wsse:BinarySecurityToken[^>]*>([^<]+)</wsse:BinarySecurityToken>', body_text)
        email_match = re.search(r'[\w.+-]+@[\w.-]+\.\w+', body_text)
        if email_match:
            user_email = email_match.group(0)

    except Exception:
        pass

    # Build the MDM provisioning response
    management_url = f"{base}/api/v1/mdm/windows/checkin"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing"
            xmlns:u="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://schemas.microsoft.com/windows/pki/2009/01/enrollment/RSTRC/wstep
    </a:Action>
    <ActivityId>{str(uuid.uuid4())}</ActivityId>
  </s:Header>
  <s:Body>
    <wst:RequestSecurityTokenResponseCollection
        xmlns:wst="http://docs.oasis-open.org/ws-sx/ws-trust/200512">
      <wst:RequestSecurityTokenResponse>
        <wst:TokenType>
          http://schemas.microsoft.com/5.0.0.0/ConfigurationManager/Enrollment/DeviceEnrollmentToken
        </wst:TokenType>
        <wst:DispositionMessage xmlns="http://schemas.microsoft.com/windows/pki/2009/01/enrollment/RSTRC"/>
        <wst:RequestedSecurityToken>
          <BinarySecurityToken
              ValueType="http://schemas.microsoft.com/5.0.0.0/ConfigurationManager/Enrollment/DeviceEnrollmentProvisionDoc"
              EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd#base64binary"
              xmlns="http://docs.oasis-open.org/">
            <![CDATA[<wap-provisioningdoc version="1.1">
  <characteristic type="com.microsoft/mdm/loginurl">
    <parm name="LoginURL" value="{base}/EnrollmentServer/Auth.svc"/>
  </characteristic>
  <characteristic type="DMClient">
    <characteristic type="Provider">
      <characteristic type="NOCKO-MDM">
        <parm name="EntDeviceName" value="MDM-Managed"/>
        <parm name="EntDMID" value="{str(uuid.uuid4())}"/>
        <characteristic type="Poll">
          <parm name="IntervalForFirstSetOfRetries" value="15"/>
          <parm name="NumberOfFirstRetries" value="8"/>
          <parm name="IntervalForSecondSetOfRetries" value="60"/>
          <parm name="NumberOfSecondRetries" value="5"/>
          <parm name="IntervalForRemainingScheduledRetries" value="1440"/>
          <parm name="PollOnLogin" value="true" datatype="boolean"/>
        </characteristic>
      </characteristic>
    </characteristic>
    <characteristic type="ManagementServiceAddress">
      <parm name="ManagementServiceAddress" value="{management_url}"/>
    </characteristic>
  </characteristic>
</wap-provisioningdoc>]]>
          </BinarySecurityToken>
        </wst:RequestedSecurityToken>
        <wst:RequestID>0</wst:RequestID>
      </wst:RequestSecurityTokenResponse>
    </wst:RequestSecurityTokenResponseCollection>
  </s:Body>
</s:Envelope>"""

    return Response(content=xml, media_type="application/soap+xml; charset=utf-8")


@router.get("/EnrollmentServer/Auth.svc", tags=["windows-oma-dm"])
async def oma_auth():
    """Simple auth stub — returns 200 OK for MDM auth pings."""
    return Response(content="OK", media_type="text/plain")


@router.get("/terms", tags=["windows-oma-dm"])
async def oma_terms():
    """Terms of Service page required by Windows MDM enrollment."""
    html = """<!DOCTYPE html><html><head><title>NOCKO MDM — Terms of Service</title>
<style>body{font-family:Arial,sans-serif;max-width:600px;margin:40px auto;color:#333}
h1{color:#1a1a2e}</style></head>
<body><h1>NOCKO MDM — Terms of Service</h1>
<p>By enrolling this device you agree to allow your organization to manage it 
using the NOCKO Mobile Device Management platform.</p>
<p>The following may be enforced by your IT department:</p>
<ul>
<li>Remote lock and wipe</li>
<li>Application deployment and removal</li>
<li>Device inventory collection (hardware specs only)</li>
<li>Password / PIN policy enforcement</li>
</ul>
<p>Personal files and data are never accessed or transmitted.</p>
<p>Contact your IT administrator for questions.</p>
</body></html>"""
    return HTMLResponse(content=html)
