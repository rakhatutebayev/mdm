; NOCKO MDM Agent - Windows Installer
; Built with NSIS (Nullsoft Scriptable Install System)
; Variables __TOKEN__ and __SERVER__ are replaced at build time

!define PRODUCT_NAME "NOCKO MDM Agent"
!define PRODUCT_VERSION "1.0"
!define PRODUCT_PUBLISHER "NOCKO IT"
!define INSTALL_DIR "$PROGRAMDATA\NOCKO-MDM"
!define TASK_NAME "NOCKO-MDM-Agent"
!define AGENT_SCRIPT "agent.ps1"

; Compression
SetCompressor /SOLID lzma

; Modern UI
!include "MUI2.nsh"

Name "${PRODUCT_NAME}"
OutFile "nocko-mdm-installer.exe"
InstallDir "${INSTALL_DIR}"
RequestExecutionLevel admin

; UI Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Uninstall pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; -------------------------------------------------------
; Installer
; -------------------------------------------------------
Section "MainSection" SEC01
    SetOutPath "${INSTALL_DIR}"

    ; Write the agent PS1 script
    FileOpen $0 "${INSTALL_DIR}\${AGENT_SCRIPT}" w
    FileWrite $0 "__PS1_CONTENT__"
    FileClose $0

    ; Register scheduled task (runs every 15 min as SYSTEM)
    DetailPrint "Registering scheduled task..."
    nsExec::ExecToLog 'powershell.exe -ExecutionPolicy Bypass -Command "& { \
        $action = New-ScheduledTaskAction -Execute powershell.exe \
            -Argument \"-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File `\"${INSTALL_DIR}\${AGENT_SCRIPT}`\" -CheckIn\"; \
        $trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 15) -Once -At (Get-Date); \
        $principal = New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest; \
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable; \
        Register-ScheduledTask -TaskName \"${TASK_NAME}\" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null; \
        Start-ScheduledTask -TaskName \"${TASK_NAME}\"; \
        Write-Host \"Task registered and started.\" \
    }"'

    ; Write uninstaller
    WriteUninstaller "${INSTALL_DIR}\uninstall.exe"

    ; Add to Windows Programs list
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NOCKO-MDM" \
        "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NOCKO-MDM" \
        "UninstallString" "${INSTALL_DIR}\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NOCKO-MDM" \
        "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NOCKO-MDM" \
        "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NOCKO-MDM" \
        "DisplayIcon" "${INSTALL_DIR}\uninstall.exe"

    DetailPrint "NOCKO MDM Agent installed successfully."
    MessageBox MB_OK "NOCKO MDM Agent installed successfully!$\n$\nServer: __SERVER__$\nDevice will appear in NOCKO MDM within 60 seconds."
SectionEnd

; -------------------------------------------------------
; Uninstaller
; -------------------------------------------------------
Section "Uninstall"
    ; Remove scheduled task
    nsExec::ExecToLog 'powershell.exe -ExecutionPolicy Bypass -Command "Unregister-ScheduledTask -TaskName \"${TASK_NAME}\" -Confirm:$false"'

    ; Remove files
    Delete "${INSTALL_DIR}\${AGENT_SCRIPT}"
    Delete "${INSTALL_DIR}\uninstall.exe"
    RMDir "${INSTALL_DIR}"

    ; Remove registry entries
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NOCKO-MDM"

    MessageBox MB_OK "NOCKO MDM Agent has been uninstalled."
SectionEnd
