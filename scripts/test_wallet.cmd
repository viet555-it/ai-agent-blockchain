@echo off
setlocal
cd /d "%~dp0.."
set "ATI_PYTHON=%CD%\.venv-phase3\Scripts\python.exe"
if not exist "%ATI_PYTHON%" (
  echo Missing .venv-phase3. Follow docs\WALLET_HISTORY_RUNBOOK.md first.
  exit /b 1
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo npm.cmd was not found. Install Node.js or reopen the terminal.
  exit /b 1
)
echo [1/5] Backend unit and persistence tests
"%ATI_PYTHON%" -m scripts.run_phase3 --suite unit
if errorlevel 1 exit /b %errorlevel%
echo [2/5] Local Hardhat integration tests
"%ATI_PYTHON%" -m scripts.run_phase3 --suite local_evm
if errorlevel 1 exit /b %errorlevel%
echo [3/5] Frontend unit tests
call npm.cmd --prefix frontend test
if errorlevel 1 exit /b %errorlevel%
echo [4/5] Frontend build
call npm.cmd --prefix frontend run build
if errorlevel 1 exit /b %errorlevel%
echo [5/5] Chromium wallet E2E tests
"%ATI_PYTHON%" -m scripts.run_wallet_e2e
if errorlevel 1 exit /b %errorlevel%
echo PASS: all wallet test stages completed. Results: .phase3\wallet-e2e\results.json
exit /b 0
