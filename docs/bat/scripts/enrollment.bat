@echo off

echo.
	echo *******************************************************************************************
	echo.
	echo		       ManageEngine MDM Windows Enrollment Wizard
	echo.
	echo This script will enroll the device into MDM. Run this batch file and not the exe
	echo.
	echo *******************************************************************************************
	echo.
	echo.

set CURRENT_DIR=%~dp0

set CERT_FILE="%CURRENT_DIR%mdmServer.cer"

set LOG_FILE_PATH="%CURRENT_DIR%logfile.txt"

set EXE_LOG_FILE_PATH="%CURRENT_DIR%mdmregistration.log"

REM set BIN_FOLDER="%CURRENT_DIR%bin\"

FOR /F "usebackq tokens=2,* skip=2" %%L IN (
    `reg query "HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v "PROCESSOR_ARCHITECTURE"`
) DO SET ProcessArch=%%M

SET EXE_NAME=mdmregistrationhandler_64.exe

If "%ProcessArch%" EQU "x86"   SET EXE_NAME=mdmregistrationhandler.exe

set EXE_PATH="%CURRENT_DIR%%EXE_NAME%"


if not exist %CERT_FILE% (
  echo.
	echo THIRD PARTY CERT USER : Certificate is not being installed as it is already trusted
  echo.
	goto callmdmexe
)

certutil.exe -addstore -f "Root" %CERT_FILE% >%LOG_FILE_PATH% 2>&1 && (
  echo.
	echo CERTINSTALL_SUCEESS : Certificate has been installed successfully
  echo.
	goto callmdmexe
) || (
	goto certfailure
)

:callmdmexe
cd %CURRENT_DIR%
echo.
echo Going to enroll device in ManageEngine MDM
echo.
%EXE_PATH% -a "rakhat.utebayev@gmail.com" "38c3720830b639f66d3f01184e7997de" "wSsVR61%%2B%%2FR72CKwpnGD%%2FJuhuyFtXBgujHUgp2VCh6Hf6Sv7Dp8czxRDNBVWgTvBOFTZsRWBE8ep7zBcBhzsIjowpyAkIACiF9mqRe1U4J3x1oLvvlzPDW2Q%%3D" "mdm.manageengine.com" "443" "201993000000118027">%LOG_FILE_PATH% 2>&1 && (
  goto success
) || (
	goto check
)

:success
echo.
echo SUCCESS : MDMRegistration with ManageEngine completed successfully.
echo.
goto exit

:certfailure
echo.
echo Failed to install the certificate
echo.
goto exit

:check
for /f %%C in ('Find /V /C "" ^< %EXE_LOG_FILE_PATH%') do set LINES=%%C
if %LINES% gtr 1 (
	set /a LINES=LINES-1
)
more /E +%LINES% < %EXE_LOG_FILE_PATH% | findstr "8018000A" > nul
if /i %errorlevel% EQU 0 (goto reenroll)
more /E +%LINES% < %EXE_LOG_FILE_PATH% | findstr "8019000A" > nul
if /i %errorlevel% EQU 0 (goto reenroll) else (goto failure)

:reenroll
echo.
echo Device is Already Enrolled in MDM.
echo.
set /p delEnroll=Remove the enrollment and try again? (y/[n]):
if /I "%delEnroll%" NEQ "Y" (
  echo.
  echo Skipped MDM enrollment. Re-Run bat to retry enrollment.
  echo.
  goto exit
)

echo.
echo Removing existing mdm enrollment and enrolling into ManageEngine MDM...
echo.
%EXE_PATH% -f "rakhat.utebayev@gmail.com" "38c3720830b639f66d3f01184e7997de" "wSsVR61%%2B%%2FR72CKwpnGD%%2FJuhuyFtXBgujHUgp2VCh6Hf6Sv7Dp8czxRDNBVWgTvBOFTZsRWBE8ep7zBcBhzsIjowpyAkIACiF9mqRe1U4J3x1oLvvlzPDW2Q%%3D" "mdm.manageengine.com" "443" "201993000000118027" >%LOG_FILE_PATH% 2>&1  && (
	goto success
) || (
	goto failure
)

:failure
echo.
echo Device registration failed due to an error described below
echo.
set LINES=0
for /f %%C in ('Find /V /C "" ^< %EXE_LOG_FILE_PATH%') do set LINES=%%C
if %LINES% gtr 1 (
	set /a LINES=LINES-2
)
for /f "tokens=2* skip=%LINES%" %%l in (mdmregistration.log) do (
  echo %%l %%m
)
echo.
echo Can't resolve? Contact Support with a copy of this folder, including the batch file.
echo.

:exit
if "%1" == "" (
	pause >nul
)
exit