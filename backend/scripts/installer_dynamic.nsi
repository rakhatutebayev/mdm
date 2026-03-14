; NOCKO MDM Agent - Dynamic Installer Template
; Generated per-request with token + server URL baked in
; PS1 agent is included as a binary file (not string)
; Installation is silent - zero config required from user

!define PRODUCT_NAME     "NOCKO MDM Agent"
!define PRODUCT_VERSION  "1.0.0"
!define PRODUCT_PUBLISHER "NOCKO IT"
!define MDM_SERVER       "__MDM_SERVER__"
!define ORG_NAME         "__ORG_NAME__"
!define INSTALL_DIR      "$PROGRAMDATA\NOCKO-MDM"
!define TASK_NAME        "NOCKO-MDM-Agent"
!define UNINSTALL_KEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\NOCKO-MDM"

SetCompressor /SOLID lzma
Unicode true
SilentInstall normal

!include "MUI2.nsh"

Name "${PRODUCT_NAME} - ${ORG_NAME}"
OutFile "__OUT_FILE__"
InstallDir "${INSTALL_DIR}"
RequestExecutionLevel admin
ShowInstDetails show

; Only show progress + finish pages - no config needed
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "NOCKO MDM Agent Installed"
!define MUI_FINISHPAGE_TEXT "The NOCKO MDM Agent has been installed successfully.$\n$\nMDM Server: ${MDM_SERVER}$\nOrganization: ${ORG_NAME}$\n$\nThis device will appear in your NOCKO MDM portal within 60 seconds."
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "Install" SEC01
    SetOutPath "${INSTALL_DIR}"

    ; Install the pre-configured agent script (token + server already baked in)
    File "agent.ps1"

    ; Register scheduled task - runs every 15 min as SYSTEM
    DetailPrint "Registering scheduled task..."
    nsExec::ExecToLog 'powershell.exe -ExecutionPolicy Bypass -NonInteractive -Command "& { try { $$action = New-ScheduledTaskAction -Execute powershell.exe -Argument $''-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File """"$PROGRAMDATA\NOCKO-MDM\agent.ps1"""" -CheckIn''; $$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 15) -Once -At (Get-Date); $$principal = New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest; $$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable; Register-ScheduledTask -TaskName ''NOCKO-MDM-Agent'' -Action $$action -Trigger $$trigger -Principal $$principal -Settings $$settings -Force | Out-Null; Start-ScheduledTask -TaskName ''NOCKO-MDM-Agent''; Write-Host ''OK'' } catch { Write-Host ($$_.Exception.Message) } }"'

    DetailPrint "Creating uninstaller..."
    WriteUninstaller "${INSTALL_DIR}\uninstall.exe"

    ; Programs & Features entry
    WriteRegStr  HKLM "${UNINSTALL_KEY}" "DisplayName"    "${PRODUCT_NAME} (${ORG_NAME})"
    WriteRegStr  HKLM "${UNINSTALL_KEY}" "UninstallString" "${INSTALL_DIR}\uninstall.exe"
    WriteRegStr  HKLM "${UNINSTALL_KEY}" "Publisher"       "${PRODUCT_PUBLISHER}"
    WriteRegStr  HKLM "${UNINSTALL_KEY}" "DisplayVersion"  "${PRODUCT_VERSION}"
    WriteRegStr  HKLM "${UNINSTALL_KEY}" "URLInfoAbout"    "https://nocko.ae"
    WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoModify"       1
    WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoRepair"       1

    DetailPrint "Done! Device will appear in NOCKO MDM within 60 seconds."
SectionEnd

Section "Uninstall"
    nsExec::ExecToLog 'powershell.exe -ExecutionPolicy Bypass -Command "Unregister-ScheduledTask -TaskName ''NOCKO-MDM-Agent'' -Confirm:$$false -ErrorAction SilentlyContinue"'
    Delete "${INSTALL_DIR}\agent.ps1"
    Delete "${INSTALL_DIR}\agent.log"
    Delete "${INSTALL_DIR}\uninstall.exe"
    RMDir  "${INSTALL_DIR}"
    DeleteRegKey HKLM "${UNINSTALL_KEY}"
SectionEnd
