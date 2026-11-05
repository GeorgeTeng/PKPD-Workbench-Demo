@echo off
setlocal
set "report=%~dp0report\absorption\index.html"
if exist "%report%" (
    start "" "%report%"
    exit /b 0
)
echo Extract the portable report ZIP into "%~dp0report" first.
echo The extracted folder should contain absorption\index.html.
pause
exit /b 1
