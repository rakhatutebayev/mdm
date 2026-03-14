@echo off

rem -----------------------------
rem This intermediate file is for 
rem allowing enrollment.bat to print 
rem output lines in command prompt
rem -----------------------------

call start "MDM Enrollment" "%CUR_DIR%scripts\enrollment.bat"
