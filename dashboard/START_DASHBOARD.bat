@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo  AviMaint-DSS V8.3.2 - Position-Aware Evidence Dashboard
echo  Frozen artifacts profile - no neural model weights required
echo ================================================================

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker is not installed or is not available in PATH.
  echo Install and start Docker Desktop, then run this file again.
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo ERROR: Docker Desktop is not running.
  echo Start Docker Desktop, wait until it is ready, then run this file again.
  exit /b 1
)

if exist "%~dp0frontend\dist" (
  echo Removing stale generated frontend build...
  rmdir /s /q "%~dp0frontend\dist"
  if exist "%~dp0frontend\dist" (
    echo ERROR: Could not remove the stale generated frontend build.
    echo Close programs using dashboard\frontend\dist, then run this file again.
    exit /b 1
  )
)

python scripts\verify_release.py
if errorlevel 1 (
  echo ERROR: Frozen dashboard artifact verification failed.
  exit /b 1
)

echo.
echo Building the dashboard image...
docker build -t avimaint-dss-v832 .
if errorlevel 1 (
  echo ERROR: Docker image build failed.
  exit /b 1
)

echo.
echo Dashboard: http://127.0.0.1:7860
echo Stop it safely with Ctrl+C.
docker run --rm --name avimaint-dss-v832 -p 7860:7860 -v avimaint-feedback-v832:/data avimaint-dss-v832
exit /b %errorlevel%
