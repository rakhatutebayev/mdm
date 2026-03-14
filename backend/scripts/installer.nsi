; ============================================================
; NOCKO MDM Agent - Windows Installer
; NSIS Script - builds a static .exe installer
; Server URL is baked in; enrollment token entered by IT admin
; ============================================================

!define PRODUCT_NAME     "NOCKO MDM Agent"
!define PRODUCT_VERSION  "1.0.0"
!define PRODUCT_PUBLISHER "NOCKO IT"
!define MDM_SERVER       "https://mdm.it-uae.com"
!define INSTALL_DIR      "$PROGRAMDATA\NOCKO-MDM"
!define TASK_NAME        "NOCKO-MDM-Agent"
!define UNINSTALL_KEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\NOCKO-MDM"
!define AGENT_SCRIPT     "agent.ps1"
!define CONFIG_FILE      "config.json"

SetCompressor /SOLID lzma
Unicode true

; Modern UI 2
!include "MUI2.nsh"
!include "LogicLib.nsh"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "NOCKO-MDM-Agent-Setup.exe"
InstallDir "${INSTALL_DIR}"
RequestExecutionLevel admin
ShowInstDetails show

; -------------------------------------------------------
; Variables
; -------------------------------------------------------
Var EnrollmentToken

; -------------------------------------------------------
; Pages
; -------------------------------------------------------
!insertmacro MUI_PAGE_WELCOME

; Custom page: enter enrollment token
Page custom TokenPageCreate TokenPageLeave

!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; -------------------------------------------------------
; Token entry page
; -------------------------------------------------------
!include "nsDialogs.nsh"

Var Dialog
Var TokenLabel
Var TokenInput
Var HintLabel

Function TokenPageCreate
    nsDialogs::Create 1018
    Pop $Dialog
    ${If} $Dialog == error
        Abort
    ${EndIf}

    ; Title
    ${NSD_CreateLabel} 0 0 100% 20u "Enrollment Token"
    Pop $TokenLabel
    SetCtlColors $TokenLabel "" "transparent"
    CreateFont $0 "Segoe UI" 10 700
    SendMessage $TokenLabel ${WM_SETFONT} $0 0

    ; Token input field
    ${NSD_CreateText} 0 28u 100% 14u ""
    Pop $TokenInput
    ${NSD_SetText} $TokenInput $EnrollmentToken

    ; Hint label
    ${NSD_CreateLabel} 0 50u 100% 40u "Paste the Enrollment Token from the NOCKO MDM portal.$\nGo to Dashboard > Enrollment > Windows tab and copy the token.$\n$\nThe token will be saved to: $PROGRAMDATA\NOCKO-MDM\config.json"
    Pop $HintLabel
    SetCtlColors $HintLabel "666666" "transparent"

    nsDialogs::Show
FunctionEnd

Function TokenPageLeave
    ${NSD_GetText} $TokenInput $EnrollmentToken
    ${If} $EnrollmentToken == ""
        MessageBox MB_OK|MB_ICONEXCLAMATION "Please enter the enrollment token before continuing."
        Abort
    ${EndIf}
FunctionEnd

; -------------------------------------------------------
; Installer Section
; -------------------------------------------------------
Section "Install" SEC01
    SetOutPath "${INSTALL_DIR}"

    ; Write the PowerShell agent script
    File "agent.ps1"

    ; Write config.json with token and server URL
    FileOpen $0 "${INSTALL_DIR}\${CONFIG_FILE}" w
    FileWrite $0 '{$\n'
    FileWrite $0 '  "mdm_server": "${MDM_SERVER}/api/v1",$\n'
    FileWrite $0 '  "enrollment_token": "$EnrollmentToken",$\n'
    FileWrite $0 '  "check_in_minutes": 15$\n'
    FileWrite $0 '}$\n'
    FileClose $0

    ; Register scheduled task (SYSTEM, every 15 min)
    DetailPrint "Registering scheduled task..."
    nsExec::ExecToLog `powershell.exe -ExecutionPolicy Bypass -NonInteractive -Command "& { \
      try { \
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File \"$PROGRAMDATA\NOCKO-MDM\agent.ps1\" -CheckIn -ConfigFile \"$PROGRAMDATA\NOCKO-MDM\config.json\"'; \
        $trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 15) -Once -At (Get-Date); \
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest; \
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable; \
        Register-ScheduledTask -TaskName 'NOCKO-MDM-Agent' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null; \
        Start-ScheduledTask -TaskName 'NOCKO-MDM-Agent'; \
        Write-Host 'Task registered OK'; \
      } catch { Write-Host ('Task error: ' + $_.Exception.Message) } \
    }"`

    ; Write uninstaller
    WriteUninstaller "${INSTALL_DIR}\uninstall.exe"

    ; Add to Programs & Features
    WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayName"     "${PRODUCT_NAME}"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "UninstallString"  "${INSTALL_DIR}\uninstall.exe"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "Publisher"        "${PRODUCT_PUBLISHER}"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayVersion"   "${PRODUCT_VERSION}"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayIcon"      "${INSTALL_DIR}\uninstall.exe"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "URLInfoAbout"     "https://mdm.it-uae.com"
    WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoModify"       1
    WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoRepair"       1

    DetailPrint "Installation complete!"
SectionEnd

; -------------------------------------------------------
; Uninstaller
; -------------------------------------------------------
Section "Uninstall"
    ; Stop and remove scheduled task
    nsExec::ExecToLog `powershell.exe -ExecutionPolicy Bypass -Command "Unregister-ScheduledTask -TaskName 'NOCKO-MDM-Agent' -Confirm:$false -ErrorAction SilentlyContinue"`

    ; Remove files
    Delete "${INSTALL_DIR}\agent.ps1"
    Delete "${INSTALL_DIR}\config.json"
    Delete "${INSTALL_DIR}\agent.log"
    Delete "${INSTALL_DIR}\uninstall.exe"
    RMDir  "${INSTALL_DIR}"

    ; Remove registry
    DeleteRegKey HKLM "${UNINSTALL_KEY}"

    MessageBox MB_OK "${PRODUCT_NAME} has been uninstalled."
SectionEnd
