@echo off
REM Encoding: CP932 for Japanese cmd.exe
setlocal
cd /d "%~dp0"

where pyinstaller >nul 2>&1
if errorlevel 1 goto install_pyinstaller
goto build

:install_pyinstaller
echo PyInstaller をインストールします...
pip install "pyinstaller>=6.0"
if errorlevel 1 exit /b 1

:build
echo exe をビルドしています...
pyinstaller --noconfirm schedule_manager.spec
if errorlevel 1 exit /b 1

if not exist "dist\schedule_manager.exe" goto failed

echo.
echo 完了: %cd%\dist\schedule_manager.exe
echo この exe を任意のフォルダにコピーして実行できます。
echo 同じフォルダの schedule.db が使われます（無ければ新規作成）。
exit /b 0

:failed
echo ビルドに失敗しました。
exit /b 1
