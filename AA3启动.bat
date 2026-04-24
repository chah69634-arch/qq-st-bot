@echo off
chcp 65001 >nul
if not exist "config.yaml" (
    echo 未找到config.yaml，请先运行"安装并启动.bat"
    pause
    exit
)
python main.py
pause