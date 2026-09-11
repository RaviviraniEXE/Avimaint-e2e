@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "MODE=SAFE"
if not "%~1"=="" set "MODE=%~1"

if /I not "%MODE%"=="SAFE" if /I not "%MODE%"=="CONFIRM_TEST" if /I not "%MODE%"=="VERIFY_ONLY" (
  echo.
  echo ERROR: Unknown mode "%MODE%".
  echo Use one of:
  echo   PHASE2_RUN_AND_FREEZE.bat
  echo   PHASE2_RUN_AND_FREEZE.bat CONFIRM_TEST
  echo   PHASE2_RUN_AND_FREEZE.bat VERIFY_ONLY
  exit /b 2
)

echo ================================================================
echo  AviMaint thesis Phase 2 - one-click evidence completion
echo  Mode: %MODE%
echo  Policy: inference/evaluation only; no training or retuning
echo ================================================================
echo.

where conda >nul 2>nul
if errorlevel 1 (
  echo ERROR: conda was not found. Run this file from Anaconda Prompt.
  exit /b 3
)

if not exist "scripts\thesis_phase2\phase2_normalization.py" (
  echo ERROR: Phase 2 files are incomplete. Extract the hotfix into the repository root.
  exit /b 4
)

echo [1/5] Running hotfix self-tests...
call conda run --no-capture-output -n avimaint-normalization python -u -m unittest scripts.thesis_phase2.test_phase2_hotfix
if errorlevel 1 goto :failed

echo.
echo [2/5] Checking the frozen validation selection and normalization TEST evidence...
call conda run --no-capture-output -n avimaint-normalization python -u scripts\thesis_phase2\phase2_normalization.py --mode %MODE%
set "NORMALIZATION_RESULT=%ERRORLEVEL%"
if "%NORMALIZATION_RESULT%"=="20" goto :confirmation_required
if not "%NORMALIZATION_RESULT%"=="0" goto :failed

if /I "%MODE%"=="VERIFY_ONLY" goto :verify_only

echo.
echo [3/5] Running the supplementary fixed-protocol robustness study...
call conda run --no-capture-output -n avimaint-dash python -u scripts\thesis_phase2\final_protocol_robustness.py
if errorlevel 1 goto :failed

echo.
echo [4/5] Creating the immutable Phase 2 freeze and thesis-ready report...
call conda run --no-capture-output -n avimaint-normalization python -u scripts\thesis_phase2\phase2_freeze.py
if errorlevel 1 goto :failed

:verify_only
echo.
echo [5/5] Verifying the complete Phase 2 freeze...
call conda run --no-capture-output -n avimaint-normalization python -u scripts\thesis_phase2\phase2_freeze.py --verify-only
if errorlevel 1 goto :failed

echo.
echo ================================================================
echo  PHASE 2 COMPLETE AND VERIFIED
echo  Results: outputs\frozen\phase2_missing_evidence_final
echo  Thesis values: outputs\frozen\phase2_missing_evidence_final\PHASE2_THESIS_RESULTS.md
echo ================================================================
exit /b 0

:confirmation_required
echo.
echo SAFE MODE STOPPED BEFORE OPENING THE NORMALIZATION TEST.
echo Review the missing-output list above. To run the locked test once, use:
echo.
echo   PHASE2_RUN_AND_FREEZE.bat CONFIRM_TEST
echo.
exit /b 20

:failed
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" set "RESULT=1"
echo.
echo PHASE 2 FAILED. No existing frozen RQ4/RQ5 result was modified.
echo Review the first ERROR above. Exit code: %RESULT%
exit /b %RESULT%
