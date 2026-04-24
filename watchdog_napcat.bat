@echo off
chcp 65001 >nul
echo [watchdog] NapCat 守护进程已启动
:loop
tasklist | findstr "NapCatWinBootMain" >nul
if errorlevel 1 (
    echo [%time%] NapCat 已掉线，正在重启...
    start "" "D:\NapCat\launcher_auto.bat" 1043484516
    timeout /t 20 /nobreak >nul
    echo [%time%] NapCat 已重启
) else (
    echo [%time%] NapCat 运行正常
)
timeout /t 60 /nobreak >nul
goto loop