@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Mojuan Launcher

rem ==========================================================================
rem  Mojuan launcher: check environment -> install what is missing -> run.
rem
rem    start.bat           check + install missing deps + start servers
rem    start.bat setup     check + install only, do not start anything
rem    start.bat check     print the environment report, change nothing
rem
rem  Two hard rules for this file:
rem    1. ASCII only. "chcp 65001" plus UTF-8 Chinese in a .bat shifts bytes
rem       and cmd starts splitting tokens (PORT -> ORT).
rem    2. CRLF line endings. An LF-only .bat cannot resolve "call :label".
rem ==========================================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "VENV=%ROOT%\.venv"
set "API_PORT=8000"
set "WEB_PORT=5173"
set "MODE=run"
if /i "%~1"=="setup" set "MODE=setup"
if /i "%~1"=="check" set "MODE=check"

echo.
echo   Mojuan - practice trainer
echo   ----------------------------------------
echo   mode: %MODE%
echo.

if not exist "%BACKEND%\app\main.py" goto :no_project
if not exist "%FRONTEND%\package.json" goto :no_project
if not exist "%BACKEND%\requirements.txt" goto :no_project

rem ===== [1/5] python interpreter ==========================================
set "PY="
if exist "%VENV%\Scripts\python.exe" set "PY=%VENV%\Scripts\python.exe"
if defined PY goto :py_found

py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto :py_try_plain
for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)"') do set "PY=%%I"
goto :py_found

:py_try_plain
python -c "import sys" >nul 2>nul
if errorlevel 1 goto :no_python
for /f "delims=" %%I in ('python -c "import sys;print(sys.executable)"') do set "PY=%%I"

:py_found
if not defined PY goto :no_python
"%PY%" -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if errorlevel 1 goto :py_too_old
rem for /f cannot carry a quoted executable path, so round-trip through a temp file
set "PYVER="
"%PY%" -c "import platform;print(platform.python_version())" > "%TEMP%\mojuan_pyver.txt" 2>nul
if exist "%TEMP%\mojuan_pyver.txt" set /p PYVER=<"%TEMP%\mojuan_pyver.txt"
del "%TEMP%\mojuan_pyver.txt" >nul 2>nul
echo   [1/5] python      v%PYVER%  %PY%

rem ===== [2/5] backend dependencies ========================================
rem Import list mirrors backend\requirements.txt:
rem   docx = python-docx, multipart = python-multipart
"%PY%" -c "import fastapi,uvicorn,multipart,httpx,pypdf,docx" >nul 2>nul
if not errorlevel 1 goto :deps_present
if /i "%MODE%"=="check" goto :deps_missing

echo   [2/5] backend     installing requirements (pip install -r) ...
"%PY%" -m pip install --disable-pip-version-check -q -r "%BACKEND%\requirements.txt"
if errorlevel 1 goto :pip_failed
"%PY%" -c "import fastapi,uvicorn,multipart,httpx,pypdf,docx" >nul 2>nul
if errorlevel 1 goto :pip_failed
echo   [2/5] backend     deps installed
goto :deps_done

:deps_present
echo   [2/5] backend     deps ok
goto :deps_done

:deps_missing
set "MISSING=1"
echo   [2/5] backend     deps MISSING - "%PY%" -m pip install -r backend\requirements.txt

:deps_done

rem ===== [3/5] node / npm ==================================================
where node >nul 2>nul
if errorlevel 1 goto :no_node
where npm >nul 2>nul
if errorlevel 1 goto :no_node
set "NODEVER="
for /f "delims=" %%V in ('node -v') do set "NODEVER=%%V"
set "NODEMAJOR="
for /f "delims=" %%V in ('node -p "process.versions.node.split('.')[0]"') do set "NODEMAJOR=%%V"
if not defined NODEMAJOR goto :node_too_old
if %NODEMAJOR% LSS 18 goto :node_too_old
echo   [3/5] node        %NODEVER%

rem ===== [4/5] frontend dependencies ======================================
if exist "%FRONTEND%\node_modules\vite\package.json" goto :web_deps_present
if /i "%MODE%"=="check" goto :web_deps_missing

echo   [4/5] frontend    installing deps (npm install, first run may take a while) ...
pushd "%FRONTEND%"
call npm install --no-audit --no-fund
set "NPM_RC=!errorlevel!"
popd
if not "!NPM_RC!"=="0" goto :npm_failed
if not exist "%FRONTEND%\node_modules\vite\package.json" goto :npm_failed
echo   [4/5] frontend    deps installed
goto :web_deps_done

:web_deps_present
echo   [4/5] frontend    deps ok
goto :web_deps_done

:web_deps_missing
set "MISSING=1"
echo   [4/5] frontend    deps MISSING - cd frontend ^&^& npm install

:web_deps_done

rem ===== [5/5] database ===================================================
if exist "%ROOT%\data\quiz.db" goto :db_present
if /i "%MODE%"=="check" goto :db_missing

echo   [5/5] database    not found, seeding demo data ...
pushd "%BACKEND%"
"%PY%" seed.py
set "SEED_RC=!errorlevel!"
popd
if not "!SEED_RC!"=="0" goto :seed_failed
echo   [5/5] database    seeded (demo login: admin / mojuan-dev)
goto :db_done

:db_present
echo   [5/5] database    data\quiz.db ok
goto :db_done

:db_missing
set "MISSING=1"
echo   [5/5] database    data\quiz.db MISSING - cd backend ^&^& python seed.py

:db_done

rem ===== report ===========================================================
echo.
if defined MISSING goto :report_missing
if /i "%MODE%"=="check" goto :report_ready
if /i "%MODE%"=="setup" goto :report_ready

rem ===== start backend ====================================================
call :port_busy %API_PORT%
if defined BUSY goto :api_running

echo   start   backend   http://127.0.0.1:%API_PORT%
pushd "%BACKEND%"
start "Mojuan-API :%API_PORT%" cmd /k ""%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT%"
popd
call :wait_port %API_PORT% 40
if errorlevel 1 goto :api_timeout
echo   ready   backend
goto :web

:api_running
echo   skip    backend   port %API_PORT% already listening

rem ===== start frontend ===================================================
:web
call :port_busy %WEB_PORT%
if defined BUSY goto :web_running

echo   start   frontend  http://localhost:%WEB_PORT%
pushd "%FRONTEND%"
start "Mojuan-Web :%WEB_PORT%" cmd /k "npm run dev -- --host"
popd
call :wait_port %WEB_PORT% 40
goto :open

:web_running
echo   skip    frontend  port %WEB_PORT% already listening

:open
start "" "http://localhost:%WEB_PORT%"
echo.
echo   web   http://localhost:%WEB_PORT%
echo   api   http://127.0.0.1:%API_PORT%/docs
echo.
echo   The two server windows ARE the app - closing them stops it.
echo   Demo login: admin / mojuan-dev (change it before any real use)
echo.
exit /b 0

:api_timeout
echo.
echo   [x] backend did not answer on port %API_PORT% within 40s.
echo       Check the "Mojuan-API" window for the traceback.
goto :fail_pause

rem ===== report tails =====================================================
:report_ready
echo   environment is ready.
if /i "%MODE%"=="setup" echo   run start.bat to launch the app.
exit /b 0

:report_missing
echo   [x] something is missing - see the lines marked MISSING above.
goto :fail_pause

rem ===== helpers ==========================================================
:port_busy
set "BUSY="
for /f "tokens=1" %%L in ('netstat -ano ^| findstr /c:":%~1 " ^| findstr /i "LISTENING"') do set "BUSY=1"
exit /b 0

:wait_port
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=%~1;$end=(Get-Date).AddSeconds(%~2);while((Get-Date) -lt $end){try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',$p);$c.Close();exit 0}catch{Start-Sleep -Milliseconds 400}};exit 1"
exit /b %errorlevel%

:fail_pause
if /i "%MODE%"=="check" exit /b 1
echo.
echo   Press any key to close this window.
pause >nul
exit /b 1

rem ===== error exits ======================================================
:no_project
echo   [x] backend\app\main.py, backend\requirements.txt or frontend\package.json not found.
echo       Put start.bat in the project root, next to backend\ and frontend\.
goto :fail_pause

:no_python
echo   [x] no Python found.
echo       Install Python 3.10+ and tick "Add python.exe to PATH":
echo         https://www.python.org/downloads/
goto :fail_pause

:py_too_old
echo   [x] Python %PYVER% is too old, 3.10+ is required.
goto :fail_pause

:pip_failed
echo   [x] pip install failed. Common causes:
echo       - no network / proxy:  set HTTP_PROXY=  and retry
echo       - permission denied:   use a venv instead:
echo           python -m venv .venv
echo           .venv\Scripts\python -m pip install -r backend\requirements.txt
echo           start.bat     (the launcher picks up .venv automatically)
goto :fail_pause

:no_node
echo   [x] node / npm not found. Install Node.js 18+ (LTS):
echo         https://nodejs.org/
goto :fail_pause

:node_too_old
echo   [x] node %NODEVER% is too old, 18+ is required.
goto :fail_pause

:npm_failed
echo   [x] npm install failed. Common causes:
echo       - no network / proxy:  npm config delete proxy
echo       - slow registry:       npm config set registry https://registry.npmmirror.com
goto :fail_pause

:seed_failed
echo   [x] seed.py failed - see the traceback above.
goto :fail_pause
