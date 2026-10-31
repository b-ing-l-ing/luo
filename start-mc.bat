@echo off
chcp 65001 >nul
setlocal
set "MC_DIR=D:\py_projects\luo\mc-server"
set "BOT_DIR=D:\py_projects\luo\bot"
set "PROJECT_DIR=D:\py_projects\luo"

if not exist "%MC_DIR%\start-server.bat" (
    echo [错误] 找不到 %MC_DIR%\start-server.bat
    pause
    exit /b 1
)
if not exist "%BOT_DIR%\index.js" (
    echo [错误] 找不到 %BOT_DIR%\index.js
    pause
    exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
    echo [错误] 找不到 node
    pause
    exit /b 1
)
where uv >nul 2>nul
if errorlevel 1 (
    echo [错误] 找不到 uv
    pause
    exit /b 1
)

set "MC_RUNNING="
netstat -ano | findstr /R /C:":25565 .*LISTENING" >nul && set "MC_RUNNING=1"
if defined MC_RUNNING (
    echo [1/3] 服务端已在运行，跳过启动。
) else (
    echo [1/3] 启动 Minecraft 服务端...
    start "Minecraft Server" /D "%MC_DIR%" "%MC_DIR%\start-server.bat"
    echo [2/3] 等待 25565 端口...
    for /l %%i in (1,1,60) do (
        netstat -ano | findstr /R /C:":25565 .*LISTENING" >nul && goto :ready
        timeout /t 2 /nobreak >nul
    )
    echo [警告] 等了 120 秒端口还没起来，仍然继续...
)
:ready

set "BOT_RUNNING="
netstat -ano | findstr /R /C:":3002 .*LISTENING" >nul && set "BOT_RUNNING=1"
if defined BOT_RUNNING (
    echo [3/3] Mineflayer 已在运行，跳过启动。
) else (
    echo [3/3] 启动 Mineflayer...
    start "Mineflayer" /D "%BOT_DIR%" cmd /c "node index.js"
    timeout /t 5 /nobreak >nul
)

cd /d "%PROJECT_DIR%"
uv run luo-mc

echo.
echo AI 已退出。按任意键关闭窗口。
pause
