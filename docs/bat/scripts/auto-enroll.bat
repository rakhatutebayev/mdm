@echo off
setlocal enabledelayedexpansion

set CURRENT_DIR=%~dp0
set CERT_FILE="%CURRENT_DIR%mdmServer.cer"

REM Default email - can be overridden by -u flag
set USER_EMAIL=rakhat.utebayev@gmail.com

REM Parse command line flags - support multiple arguments
set FLAG_DISPLAY=STANDARD
set FORCE_FLAG=
set SAFE_FLAG=
set AUTO_USER_FLAG=

REM Loop through all arguments
:parse_args
if "%1" == "" goto :done_parsing
if "%1" == "-f" (
    set FORCE_FLAG=-f
    set FLAG_DISPLAY=%FLAG_DISPLAY%+FORCE
) else if "%1" == "-s" (
    set SAFE_FLAG=-s
    set FLAG_DISPLAY=%FLAG_DISPLAY%+SAFE
) else if "%1" == "-u" (
    set AUTO_USER_FLAG=-u
    set FLAG_DISPLAY=%FLAG_DISPLAY%+AUTO_USER
    REM Call get-user-email.bat and capture the returned email
    for /f "delims=" %%i in ('"%CURRENT_DIR%get-user-upn.bat"') do set USER_EMAIL=%%i
)
shift
goto :parse_args

:done_parsing
REM Clean up flag display
if "%FLAG_DISPLAY%" == "STANDARD+FORCE" set FLAG_DISPLAY=FORCE
if "%FLAG_DISPLAY%" == "STANDARD+SAFE" set FLAG_DISPLAY=SAFE
if "%FLAG_DISPLAY%" == "STANDARD+AUTO_USER" set FLAG_DISPLAY=AUTO_USER
if "%FLAG_DISPLAY%" == "STANDARD+FORCE+AUTO_USER" set FLAG_DISPLAY=FORCE+AUTO_USER
if "%FLAG_DISPLAY%" == "STANDARD+SAFE+AUTO_USER" set FLAG_DISPLAY=SAFE+AUTO_USER

REM Determine architecture and executable
FOR /F "usebackq tokens=2,* skip=2" %%L IN (
    `reg query "HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v "PROCESSOR_ARCHITECTURE"`
) DO SET ProcessArch=%%M

SET EXE_NAME=mdmregistrationhandler_64.exe
If "%ProcessArch%" EQU "x86" SET EXE_NAME=mdmregistrationhandler.exe
set EXE_PATH="%CURRENT_DIR%%EXE_NAME%"

REM Check certificate status
if not exist %CERT_FILE% (
    set CERT_STATUS=SKIPPED
) else (
    certutil.exe -addstore -f "Root" %CERT_FILE% >nul 2>&1
    if !errorlevel! equ 0 (
        set CERT_STATUS=INSTALLED
    ) else (
        set CERT_STATUS=FAILED
        goto :print_summary
    )
)

REM Check current enrollment status
%EXE_PATH% --check >nul 2>&1
set CHECK_RESULT=!errorlevel!

if !CHECK_RESULT! == 0 (
    set CURRENT_STATUS=ENROLLED
) else if !CHECK_RESULT! == 1 (
    set CURRENT_STATUS=NOT_ENROLLED
) else (
    set CURRENT_STATUS=
)

REM Check if safe mode and already enrolled
if "%SAFE_FLAG%" == "-s" if "!CURRENT_STATUS!" == "ENROLLED" (
    set ENROLLMENT_RESULT=SKIPPED_SAFE_MODE
    set EXE_RESULT=0
    goto :print_summary
)

REM Perform enrollment
cd %CURRENT_DIR%


if "!CURRENT_STATUS!" == "ENROLLED" (
    if "%FORCE_FLAG%" == "-f" (
        %EXE_PATH% -f "%USER_EMAIL%" "38c3720830b639f66d3f01184e7997de" "wSsVR61%%2B%%2FR72CKwpnGD%%2FJuhuyFtXBgujHUgp2VCh6Hf6Sv7Dp8czxRDNBVWgTvBOFTZsRWBE8ep7zBcBhzsIjowpyAkIACiF9mqRe1U4J3x1oLvvlzPDW2Q%%3D" "mdm.manageengine.com" "443" "201993000000118027"
    ) else (
        %EXE_PATH% -a "%USER_EMAIL%" "38c3720830b639f66d3f01184e7997de" "wSsVR61%%2B%%2FR72CKwpnGD%%2FJuhuyFtXBgujHUgp2VCh6Hf6Sv7Dp8czxRDNBVWgTvBOFTZsRWBE8ep7zBcBhzsIjowpyAkIACiF9mqRe1U4J3x1oLvvlzPDW2Q%%3D" "mdm.manageengine.com" "443" "201993000000118027"
    )
) else (
    %EXE_PATH% -a "%USER_EMAIL%" "38c3720830b639f66d3f01184e7997de" "wSsVR61%%2B%%2FR72CKwpnGD%%2FJuhuyFtXBgujHUgp2VCh6Hf6Sv7Dp8czxRDNBVWgTvBOFTZsRWBE8ep7zBcBhzsIjowpyAkIACiF9mqRe1U4J3x1oLvvlzPDW2Q%%3D" "mdm.manageengine.com" "443" "201993000000118027"
)

set EXE_RESULT=!errorlevel!

if !EXE_RESULT! equ 0 (
    set ENROLLMENT_RESULT=SUCCESS
) else (
    set ENROLLMENT_RESULT=FAILED
)

:print_summary

echo.
echo   Certificate Status    : %CERT_STATUS%
echo   Execution Flag        : %FLAG_DISPLAY%
echo   User Email            : %USER_EMAIL%
echo   Current Enrollment    : %CURRENT_STATUS%
echo   Enrollment Result     : %ENROLLMENT_RESULT%
echo   EXE Exit Code         : %EXE_RESULT%
echo.

if !EXE_RESULT! equ 0 (
    exit /b 0
) else (
    exit /b 1
)
