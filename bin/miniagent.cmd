@echo off
setlocal
pushd "%~dp0.."
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
    echo MiniAgent: Python environment missing: .venv\Scripts\python.exe 1>&2
    popd
    exit /b 1
)
".venv\Scripts\python.exe" -u "main.py" %*
set "miniagent_exit_code=%errorlevel%"
popd
exit /b %miniagent_exit_code%
