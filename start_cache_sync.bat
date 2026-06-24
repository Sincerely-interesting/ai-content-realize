@echo off
chcp 65001 >nul
echo ================================================================
echo 🚀 缓存自动导出与SMB同步服务
echo ================================================================
echo.

echo [1/3] 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误: 未找到Python
    pause
    exit /b 1
)
echo ✅ Python环境正常

echo.
echo [2/3] 检查依赖库...
python -c "import pandas; import openpyxl" >nul 2>&1
if errorlevel 1 (
    echo ⚠️  缺少依赖，正在安装...
    pip install pandas openpyxl
)
echo ✅ 依赖库正常

echo.
echo [3/3] 启动同步服务...
echo.
echo ================================================================
echo 📂 缓存文件: minimax_mcp_multimodal_cache.json
echo 📁 本地导出: excel_exports\
echo 🌐 SMB共享: \\192.168.2.242\大数据中心
echo ⏱️  监控间隔: 60秒
echo ================================================================
echo.
echo 💡 提示:
echo   - 确保打标程序正在运行
echo   - 按 Ctrl+C 停止服务
echo   - 日志文件: cache_sync.log
echo.
echo ================================================================
echo.

python cache_sync_to_smb.py

pause
