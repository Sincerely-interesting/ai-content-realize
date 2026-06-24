#!/bin/bash
# 快速启动脚本 - 使用ls快速扫描SMB
cd /Users/kaori/Documents/gitrepo/ai-content-realize-master
source ~/.zshrc

echo "快速扫描SMB素材文件夹..."
MATERIALS_DIR="/Volumes/得物平台/引力任务素材"

# 使用ls快速获取有内容的文件夹
echo "正在扫描..."
FOLDER_LIST=$(ls "$MATERIALS_DIR" 2>/dev/null | head -500)

if [ -z "$FOLDER_LIST" ]; then
    echo "错误: 无法访问SMB共享"
    exit 1
fi

echo "找到素材文件夹，开始打标..."
echo "$FOLDER_LIST" > /tmp/material_ids.txt

# 运行打标脚本（会跳过空文件夹）
python3 minicpm_dewu_labeler.py --sample 500
