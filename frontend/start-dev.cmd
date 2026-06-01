@echo off
setlocal
cd /d "%~dp0"
set LOG=%CD%\dev-start.log
echo === %date% %time% === > "%LOG%"
echo [cmd] 目录: %CD%>> "%LOG%"

where node >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [错误] 找不到 node >> "%LOG%"
  echo [错误] 找不到 node。请先 conda activate rus-ukr-vis
  type "%LOG%"
  pause
  exit /b 1
)

node -v >> "%LOG%" 2>&1
echo node 版本:>> "%LOG%"
node -v
if errorlevel 1 (
  echo node 无法运行 >> "%LOG%"
  type "%LOG%"
  pause
  exit /b 1
)

if not exist "node_modules\vite\bin\vite.js" (
  echo [提示] 正在 npm install ...>> "%LOG%"
  call npm install >> "%LOG%" 2>&1
)

echo 运行 check-dev.cjs ...>> "%LOG%"
node scripts\check-dev.cjs >> "%LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo [失败] 环境检查未通过，日志:
  type "%LOG%"
  pause
  exit /b 1
)

echo.
echo 启动 Vite，浏览器打开 http://127.0.0.1:5173/
echo 日志: %LOG%
echo.
node scripts\dev.cjs >> "%LOG%" 2>&1
set EC=%ERRORLEVEL%
echo 退出码 %EC%>> "%LOG%"
if %EC% neq 0 (
  echo.
  echo [失败] 见日志:
  type "%LOG%"
  pause
  exit /b %EC%
)
pause
