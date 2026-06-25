@echo off
chcp 65001 >nul
echo ====================================================
echo VirtuMate 一键启动脚本
echo ====================================================
echo.

REM 设置 HuggingFace 镜像（国内加速）
set HF_ENDPOINT=https://hf-mirror.com

REM 设置模型缓存目录（项目本地）
set HF_HOME=%~dp0.models\huggingface
set HF_HUB_CACHE=%~dp0.models\huggingface\hub

echo [INFO] HuggingFace 镜像: %HF_ENDPOINT%
echo [INFO] 模型缓存目录: %HF_HOME%
echo.

REM 运行主程序
echo 正在启动 VirtuMate...
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] 程序运行出错！
    echo 请检查日志文件: logs\run.log
    pause
)
