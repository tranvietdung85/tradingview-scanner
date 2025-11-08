@echo off
REM Batch file to run AB_W + Volume spike scanner with preset parameters.
REM Adjust parameters below as needed.

SET TOP=500
SET VOL_MULT=5
SET ABW_LT=1.2
SET PYTHON=python

REM Activate virtual environment if it exists
IF EXIST .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) ELSE (
    echo [WARN] .venv not found. Using system Python.
)

REM Run scanner
%PYTHON% -m src.scan_abw_volume --top %TOP% --vol-mult %VOL_MULT% --abw-lt %ABW_LT%

REM Keep window open if double-clicked
IF "%1"=="/nopause" GOTO :EOF
pause
