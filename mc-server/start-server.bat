@echo off
chcp 65001 >nul
cd /d "%~dp0"
java -Xms1G -Xmx2G -jar paper.jar nogui
pause
