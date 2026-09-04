@echo off
setlocal
cd /d "%~dp0"

where go >nul 2>&1
if errorlevel 1 (
  echo Go not found in PATH.
  exit /b 1
)

if not exist "..\assets\schedule_manager.ico" (
  echo Icon not found: ..\assets\schedule_manager.ico
  exit /b 1
)

echo Generating Windows resources (icon)...
go run github.com/tc-hib/go-winres@v0.3.3 simply --arch amd64 --icon ..\assets\schedule_manager.ico --manifest cli --product-name "schedule_manager" --file-description "schedule_manager" --original-filename schedule_manager.exe --out rsrc
if errorlevel 1 exit /b 1

if not exist "dist" mkdir dist

echo Building exe...
go build -o dist\schedule_manager.exe .
if errorlevel 1 exit /b 1

echo.
echo Done: %cd%\dist\schedule_manager.exe
exit /b 0
