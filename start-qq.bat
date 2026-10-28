@echo off
chcp 65001 >nul
setlocal

rem ===== 改这里：NapCat 和项目路径 =====
set "NAPCAT_DIR=D:\soft\Napcat\NapCat.52230.Shell"
set "PROJECT_DIR=D:\py_projects\luo"

if not exist "%NAPCAT_DIR%\napcat.quick.bat" (
    echo [错误] 找不到 %NAPCAT_DIR%\napcat.quick.bat
    echo 请检查 NAPCAT_DIR 路径。
    pause
    exit /b 1
)
if not exist "%PROJECT_DIR%\pyproject.toml" (
    echo [错误] 找不到项目目录 %PROJECT_DIR%
    pause
    exit /b 1
)
where uv >nul 2>nul
if errorlevel 1 (
    echo [错误] 找不到 uv，请确认它在 PATH 里。
    pause
    exit /b 1
)

echo [1/2] 启动 NapCat...
echo 如果启动失败，先运行 napcat.kill.qq.bat 清理残留。
start "NapCat" /D "%NAPCAT_DIR%" "%NAPCAT_DIR%\napcat.quick.bat"

echo [2/2] 等待 5 秒后启动洛...
timeout /t 5 /nobreak >nul

cd /d "%PROJECT_DIR%"
uv run luo-qq

echo.
echo 洛已退出。按任意键关闭窗口。
pause
