#!/bin/bash
# SMB挂载脚本 - 得物平台
# 使用方法: chmod +x mount_smb_dewu.sh && ./mount_smb_dewu.sh

echo "正在挂载SMB共享..."
echo ""

# 创建挂载点
mkdir -p /Volumes/得物平台

# 提示用户手动输入密码（避免特殊字符问题）
echo "请在Finder中输入密码: kyc\$828"
echo ""

# 使用Finder打开SMB连接
open "smb://chengxingyuan@192.168.2.210/得物平台"

echo ""
echo "Finder已打开，请在弹出的对话框中："
echo "1. 选择'注册用户'"
echo "2. 名称: chengxingyuan"  
echo "3. 密码: kyc\$828"
echo "4. 点击'连接'"
echo ""
echo "挂载成功后，运行以下命令开始打标："
echo "  python3 minicpm_dewu_labeler.py --sample 500"
echo ""
