setlocal enabledelayedexpansion

if "%~1"=="" (
    echo ui ^| dev ^| build ^| linux
    goto :end
)

if "%~1"=="ui" (
    echo ========== UI ===========
    pushd "%~dp0"
    where pyside6-uic >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] pyside6-uic not found in PATH, run: micromamba activate qtt
        popd
        goto :end
    )
    for /d %%i in (ui\*) do (
        set folder_name=%%~nxi
        if exist "%%i\_view.ui" (
            pyside6-uic "%%i\_view.ui" -o "%%i\_view.py.tmp"
            if exist "%%i\_view.py.tmp" (
                move /y "%%i\_view.py.tmp" "%%i\_view.py" >nul
                echo Generated: %%i\_view.py
            ) else (
                echo [ERROR] uic failed, keep old file: %%i\_view.py
            )
        )
    )
    popd
)

if "%~1"=="dev" (
    echo ========== Build ===========
    uv run src\main.py
)

if "%~1"=="build" (
    echo ========== Build ==========
    pushd "%~dp0"

    if exist "_build" rmdir /s /q "_build"
    if exist "_dist" rmdir /s /q "_dist"

    uv run pyinstaller --noconfirm ^
        --clean ^
        --onefile ^
        --name main ^
        --hidden-import="_elementtree" ^
        --hidden-import="xml.etree.cElementTree" ^
        --paths . ^
        --paths libs ^
        --collect-submodules ui ^
        --collect-submodules broker ^
        --collect-submodules plc ^
        --collect-submodules vsp ^
        --collect-submodules wf ^
        --collect-submodules pdf ^
        --hidden-import PySide6.QtWebEngineCore ^
        --hidden-import PySide6.QtWebEngineWidgets ^
        --distpath _dist ^
        --workpath _build ^
        --specpath _build ^
        main.py
    if errorlevel 1 (
        popd
        exit /b 1
    )

    echo Copying runtime and configuration files...
    xcopy "runtime" "_dist\runtime\" /E /I /Y >nul
    copy /Y "app.ini" "_dist\app.ini" >nul
    popd

    echo Build complete!
)


if "%~1"=="zip" (
    echo ========== Push to Vmware ===========
    for /f "delims=" %%i in ('powershell -Command "Get-Date -Format 'yyyy-MMdd-HH-mm'"') do set TS=%%i
    if not exist "..\.bak" mkdir "..\.bak"
    powershell -Command "Get-ChildItem -Path 'main' -Recurse | Where-Object { $_.FullName -notmatch '\__pycache__' } | Compress-Archive -DestinationPath 'main-!TS!.zip' -Force"
    move "main-!TS!.zip" "..\.bak\"
)

:end
exit /b
echo off
