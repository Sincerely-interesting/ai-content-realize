@echo off
chcp 65001 >nul
echo ================================================================
echo 🚀 打标200个图片素材文件夹
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
echo [2/3] 检查API Key...
python -c "import os; from dotenv import load_dotenv; load_dotenv(); key=os.getenv('MIN_MAX_API_KEY',''); print('✅ API Key: ' + key[:30] + '...' if key else '❌ 未设置')"

echo.
echo [3/3] 启动打标任务...
echo.
echo ================================================================
echo 📋 任务配置:
echo   - 媒体类型: 图片 (image)
echo   - 处理数量: 200 个
echo   - 分批判定: 每批 4 张图片
echo   - 智能跳过: 已成功的自动跳过
echo ================================================================
echo.
echo 💡 提示:
echo   - 按 Ctrl+C 停止任务
echo   - 日志文件: minimax_mcp_multimodal_labeling.log
echo   - 缓存文件: minimax_mcp_multimodal_cache.json
echo.
echo ================================================================
echo.

python minimax_mcp_multimodal_label_materials_v3.py --media-type image --limit 200

echo.
echo ================================================================
echo 任务完成！
echo ================================================================
pause
