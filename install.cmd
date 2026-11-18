@echo off
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 goto error
where npm >nul 2>&1
if errorlevel 1 goto error
python -m pip install -r requirements.txt
if errorlevel 1 goto error
call npm ci --no-audit --no-fund
if errorlevel 1 goto error
if not exist "data\seed.sqlite" python scripts\generate_seed.py --output data\seed.sqlite
if errorlevel 1 goto error
python scripts\prepare_map.py
if errorlevel 1 goto error
call npm run build
if errorlevel 1 goto error
echo Setup complete. Run start.cmd.
pause
exit /b 0
:error
echo Setup failed. Check Python, Node.js, network and the messages above.
pause
exit /b 1
