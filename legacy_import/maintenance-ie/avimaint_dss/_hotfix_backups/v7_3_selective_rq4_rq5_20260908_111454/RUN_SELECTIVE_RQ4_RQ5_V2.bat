@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PIPELINE=%~dp0selective_rq4_rq5_v2.py"

if not exist "%PIPELINE%" (
  echo ERROR: %PIPELINE% is missing.
  exit /b 1
)
where conda >nul 2>&1
if errorlevel 1 (
  echo ERROR: conda is not available in this terminal.
  echo Open Anaconda Prompt and run this file again.
  exit /b 1
)

if "%~1"=="" goto :help
if /i "%~1"=="help" goto :help
if /i "%~1"=="status" goto :status
if /i "%~1"=="preflight" goto :preflight
if /i "%~1"=="prepare" goto :prepare
if /i "%~1"=="precompute" goto :precompute
if /i "%~1"=="precompute-gpu" goto :precompute_gpu
if /i "%~1"=="dev" goto :dev
if /i "%~1"=="safe" goto :safe
if /i "%~1"=="test" goto :test
if /i "%~1"=="rq5" goto :rq5
if /i "%~1"=="manual" goto :manual
if /i "%~1"=="report" goto :report
if /i "%~1"=="freeze" goto :freeze
if /i "%~1"=="verify" goto :verify
if /i "%~1"=="self-test" goto :self_test
echo ERROR: Unknown command "%~1".
goto :help_error

:dash
call conda run --no-capture-output -n avimaint-dash python -u "%PIPELINE%" %*
exit /b %errorlevel%

:spert
call conda run --no-capture-output -n spert python -u "%PIPELINE%" %*
exit /b %errorlevel%

:status
call :dash status
exit /b %errorlevel%

:preflight
call :dash preflight
exit /b %errorlevel%

:prepare
call :dash prepare
exit /b %errorlevel%

:precompute
call :spert precompute --cpu
exit /b %errorlevel%

:precompute_gpu
call :spert precompute
exit /b %errorlevel%

:dev
call :dash evaluate --partition dev
exit /b %errorlevel%

:safe
echo ================================================================
echo  SAFE SELECTIVE RQ4/RQ5 STAGES: PREFLIGHT - PREPARE - SPERT - DEV
echo  The Selective TEST partition will NOT be opened by this command.
echo ================================================================
call :dash preflight
if errorlevel 1 exit /b %errorlevel%
call :dash prepare
if errorlevel 1 exit /b %errorlevel%
call :spert precompute --cpu
if errorlevel 1 exit /b %errorlevel%
call :dash evaluate --partition dev
if errorlevel 1 exit /b %errorlevel%
echo.
echo SAFE STAGES COMPLETE. Review RQ4_DEV_SELECTION.json before TEST.
exit /b 0

:test
if /i not "%~2"=="OPEN-TEST-ONCE" (
  echo TEST IS LOCKED BY DESIGN.
  echo Review DEV first, then run exactly:
  echo RUN_SELECTIVE_RQ4_RQ5_V2.bat test OPEN-TEST-ONCE
  exit /b 2
)
call :dash evaluate --partition test --confirm-final-test
exit /b %errorlevel%

:rq5
call :dash rq5
exit /b %errorlevel%

:manual
call :dash manual-next
exit /b %errorlevel%

:report
call :dash report
exit /b %errorlevel%

:freeze
call :dash freeze
exit /b %errorlevel%

:verify
call :dash verify
exit /b %errorlevel%

:self_test
call conda run --no-capture-output -n avimaint-dash python -u "%~dp0check_selective_rq4_rq5_v2.py"
exit /b %errorlevel%

:help
echo AviMaint-DSS Selective-ByT5 RQ4/RQ5 V2 - single controller
echo.
echo   RUN_SELECTIVE_RQ4_RQ5_V2.bat safe
echo       Run preflight, prepare, problem-only Selective SpERT and DEV.
echo       This cannot open TEST.
echo.
echo   RUN_SELECTIVE_RQ4_RQ5_V2.bat test OPEN-TEST-ONCE
echo       Open and permanently lock Selective TEST after DEV review.
echo.
echo   RUN_SELECTIVE_RQ4_RQ5_V2.bat rq5
echo       Fit on DEV and evaluate the RQ5 historical-agreement calibrator.
echo.
echo   RUN_SELECTIVE_RQ4_RQ5_V2.bat manual
echo       Create/advance/score the blinded manual-review workflow.
echo       Run again after filling each generated review CSV.
echo.
echo   RUN_SELECTIVE_RQ4_RQ5_V2.bat report
echo       Build the thesis-ready Selective results summary after RQ5.
echo.
echo   RUN_SELECTIVE_RQ4_RQ5_V2.bat freeze
echo       Freeze only after the manual review is complete.
echo.
echo   RUN_SELECTIVE_RQ4_RQ5_V2.bat verify
echo   RUN_SELECTIVE_RQ4_RQ5_V2.bat status
echo   RUN_SELECTIVE_RQ4_RQ5_V2.bat self-test
echo.
echo The normal dashboard launcher remains FINAL_12_START_DASHBOARD.bat.
exit /b 0

:help_error
call :help
exit /b 1
