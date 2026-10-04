@echo off
cd /d "%~dp0"
set ALEXANDRIA_HOST=0.0.0.0
set ALEXANDRIA_PORT=4200
app\env\Scripts\python.exe app\app.py
pause