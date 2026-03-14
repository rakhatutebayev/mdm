@echo off
setlocal enabledelayedexpansion

REM ========================================
REM Get User Email for MDM Enrollment
REM ========================================
REM Usage: get-user-email.bat [directory_type]
REM directory_type: onprem (default) | azure | okta
REM ========================================

set DIRECTORY_TYPE=%1
if "%DIRECTORY_TYPE%"=="" set DIRECTORY_TYPE=onprem

REM Check directory type and handle accordingly
if /i "%DIRECTORY_TYPE%"=="okta" (
    REM Okta not supported yet
    exit /b 2
)

if /i "%DIRECTORY_TYPE%"=="onprem" goto :get_upn
if /i "%DIRECTORY_TYPE%"=="azure" goto :get_upn

REM Unknown directory type
exit /b 3

:get_upn
REM Try to get UPN using whoami /upn
for /f "delims=" %%i in ('whoami /upn 2^>nul') do set USER_EMAIL=%%i

REM If whoami /upn succeeded, output the email
if not "!USER_EMAIL!"=="" (
    echo !USER_EMAIL!
    exit /b 0
)

REM If whoami /upn failed, return error code
REM auto-enroll.bat will handle this and use default email
exit /b 1
