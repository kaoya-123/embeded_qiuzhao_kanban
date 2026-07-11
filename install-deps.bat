@echo off
chcp 65001 >nul
title 嵌入式校招雷达 - 安装依赖
cd /d D:\AI学习\embedded-job-radar

echo.
echo ========================================
echo   嵌入式校招雷达 - 一键安装依赖
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo [错误] 没有找到 Python 启动器 py。
  echo 请先安装 Python 3.10+，并勾选 Add Python to PATH。
  echo.
  pause
  exit /b 1
)

echo [1/3] 检查 Python 版本...
py --version
if errorlevel 1 goto :fail

echo.
echo [2/3] 安装 Python 依赖 requirements.txt...
py -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo [3/3] 安装 Playwright Chromium 浏览器内核...
py -m playwright install chromium
if errorlevel 1 goto :fail

echo.
echo ========================================
echo   依赖安装完成！
echo ========================================
echo 下一步：双击 start-dashboard.bat 启动看板。
echo 第一次打开网页时，会弹窗引导你填写飞书配置。
echo.
pause
exit /b 0

:fail
echo.
echo ========================================
echo   安装失败，请把上面的错误信息截图发给我
echo ========================================
echo.
pause
exit /b 1
