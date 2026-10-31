@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "JAVA=C:\Users\34667\AppData\Roaming\.minecraft\runtime\java-runtime-delta\bin\java.exe"
if not exist "%JAVA%" (
    echo [错误] 找不到 Java 21: %JAVA%
    pause
    exit /b 1
)
"%JAVA%" -Xms1G -Xmx2G -jar paper.jar nogui
pause
