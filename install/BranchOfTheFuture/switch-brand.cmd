@echo off
REM Switch demo brand. Supports legacy and industry-pack paths.
REM Usage: switch-brand.cmd flagstar | zava | zava-health

if "%~1"=="" (
    echo Usage: switch-brand.cmd ^<brand^>
    echo   Legacy: zava, flagstar, bofa
    echo   Industry packs: zava-financial, zava-health, zava-insurance, etc.
    exit /b 1
)

if exist "configs\brands\%~1\demo_config.yaml" (
    copy /y "configs\brands\%~1\demo_config.yaml" "demo_config.yaml" >/dev/null
    echo Copied demo_config.yaml from configs\brands\%~1
    if exist "configs\brands\%~1\product_catalog.yaml" (
        copy /y "configs\brands\%~1\product_catalog.yaml" "product_catalog.yaml" >/dev/null
        echo Copied product_catalog.yaml
    )
    echo.>>"demo_config.yaml"
    echo use_industry_packs: true>>"demo_config.yaml"
    echo active_brand: "%~1">>"demo_config.yaml"
    echo Industry packs activated for %~1
    goto done
)

if exist "configs\%~1\demo_config.yaml" (
    copy /y "configs\%~1\demo_config.yaml" "demo_config.yaml" >/dev/null
    echo Copied demo_config.yaml from configs\%~1
    if exist "configs\%~1\product_catalog.yaml" (
        copy /y "configs\%~1\product_catalog.yaml" "product_catalog.yaml" >/dev/null
        echo Copied product_catalog.yaml
    )
    goto done
)

echo Error: No config found for "%~1"
exit /b 1

:done
echo.
echo Brand switched to: %~1
echo Restart the Flask app to apply changes.
