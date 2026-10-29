@echo off
chcp 65001 >nul
setlocal
set "MC_DIR=D:\py_projects\luo\mc-server"
set "BOT_DIR=D:\py_projects\luo\bot"

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

echo [1/2] 启动 Minecraft 服务端...
start "Minecraft Server" /D "%MC_DIR%" "%MC_DIR%\start-server.bat"

echo [2/2] 等待 25565 端口...
for /l %%i in (1,1,60) do (
    netstat -ano | findstr /R /C:":25565 .*LISTENING" >nul && goto :ready
    timeout /t 2 /nobreak >nul
)
echo [警告] 等了 120 秒端口还没起来，仍然尝试启动 bot...
:ready

cd /d "%BOT_DIR%"
node index.js

echo.
echo bot 已退出。按任意键关闭窗口。
pause
