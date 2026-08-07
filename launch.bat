@echo off
REM ============================================================================
REM  Open Utility Manager in a clean browser window with NO address bar.
REM
REM  The address bar cannot be hidden by the web app itself - it belongs to the
REM  browser. This launcher opens the app in Chrome/Edge "app mode", which shows
REM  the page in its own window with no URL bar, tabs, or navigation buttons.
REM
REM  Requires the app to already be running (e.g. via run.py or a production
REM  server) and reachable at the URL below.
REM ============================================================================

set URL=http://127.0.0.1:5000/

REM --- App mode: normal window, no address bar (recommended) --------------------
start "" chrome --app=%URL% --window-size=1440,900 2>nul
if %errorlevel%==0 goto :eof

REM --- Fall back to Microsoft Edge if Chrome is not installed -------------------
start "" msedge --app=%URL% --window-size=1440,900 2>nul
if %errorlevel%==0 goto :eof

echo Could not find Chrome or Edge. Open %URL% manually, then press F11 for fullscreen.
pause

REM ----------------------------------------------------------------------------
REM  For a fully locked-down, fullscreen terminal (no way out but Alt+F4),
REM  replace the --app line above with:
REM      start "" chrome --kiosk %URL%
REM ----------------------------------------------------------------------------
