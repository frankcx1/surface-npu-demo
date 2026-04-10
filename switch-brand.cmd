@echo off
REM Switch demo brand by copying config files from configs/<brand>/
REM Usage: switch-brand.cmd flagstar
REM        switch-brand.cmd zava

if "%~1"=="" (
    echo Usage: switch-brand.cmd ^<brand^>
    echo Available brands:
    for /d %%d in (configs\*) do echo   %%~nxd
    exit /b 1
)

if not exist "configs\%~1\demo_config.yaml" (
    echo Error: configs\%~1\demo_config.yaml not found
    exit /b 1
)

copy /y "configs\%~1\demo_config.yaml" "demo_config.yaml" >nul
echo Copied demo_config.yaml from %~1

if exist "configs\%~1\product_catalog.yaml" (
    copy /y "configs\%~1\product_catalog.yaml" "product_catalog.yaml" >nul
    echo Copied product_catalog.yaml from %~1
)

echo.
echo Brand switched to: %~1
echo Restart the Flask app to apply changes.
