@echo off

rem ------------------------------------
rem Checking for Administrator permission
rem ------------------------------------
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"

rem -----------------------------------------------------------------------------------
rem Throws error if not in admin session,catching and re-directing the same accordingly
rem -----------------------------------------------------------------------------------
if '%errorlevel%' NEQ '0' (
    echo Requesting administrative privileges...
    goto UACPrompt
) else ( goto AdminPrompt )


rem -----------------------------------------------------------------------------------
rem Invokes UACPrompt by creating a VBScript, as native escalation is not supported
rem -----------------------------------------------------------------------------------
:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "%windir%\system32\cmd.exe", "/c ""%~s0""", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    del "%temp%\getadmin.vbs"
    exit /b

rem -----------------------------------------------------------------------------------
rem Called when in admin session so invoking the bat
rem -----------------------------------------------------------------------------------
:AdminPrompt
    echo Administrative permissions confirmed.
    echo.
    set CUR_DIR=%~dp0
    call "%CUR_DIR%scripts\enrollmentIntermediate.bat"
exit /b 0
