@echo off
REM Create a Desktop + Start-Menu icon for the dashboard, so you can launch it with a
REM single double-click (no need to open this folder each time). Safe to run again.
setlocal
cd /d "%~dp0"
set "NAME=Rainfall Verification"
set "TARGET=%~dp0Rainfall Verification.vbs"
set "ICON=%~dp0app_icon.ico"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws=New-Object -ComObject WScript.Shell;" ^
  "$dt=[Environment]::GetFolderPath('Desktop');" ^
  "$sm=Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs';" ^
  "foreach($d in @($dt,$sm)){ if($d -and (Test-Path $d)){ $lnk=Join-Path $d '%NAME%.lnk'; $s=$ws.CreateShortcut($lnk); $s.TargetPath='%TARGET%'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%ICON%'; $s.Description='Rainfall Verification Dashboard'; $s.Save() } }"
echo Created "%NAME%" icon on your Desktop and Start Menu.
echo Double-click that icon any time to open the dashboard.
