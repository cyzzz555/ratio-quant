@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONPATH=%CD%\backend
where uv >nul 2>nul
if errorlevel 1 (
  echo Install uv first: https://docs.astral.sh/uv/getting-started/installation/
  goto failed
)
where node >nul 2>nul
if errorlevel 1 (
  echo Install Node.js 24 LTS first: https://nodejs.org/
  goto failed
)
if not exist ".venv\Scripts\python.exe" (
  uv sync --frozen
  if errorlevel 1 goto failed
)
if not exist "frontend\node_modules\vite\bin\vite.js" (
  where pnpm >nul 2>nul
  if errorlevel 1 (
    echo Install pnpm first: npm install -g pnpm@11.25.0
    goto failed
  )
  pushd frontend
  call pnpm install --frozen-lockfile
  if errorlevel 1 (
    popd
    goto failed
  )
  popd
)
set "MODE=--file-only"
if defined DATABASE_URL set "MODE="
if exist "config\local_runtime.json" set "MODE="
echo Starting local research workspace. Live trading is disabled.
".venv\Scripts\python.exe" -m app.local_workspace %MODE%
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. Keep the error message above for diagnosis.
pause
exit /b 1
