@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo BioCatalyst Intelligence - 本地浏览器服务
start "BioCatalyst" http://localhost:8000/
py -3 -m http.server 8000
pause