#!/bin/bash
# 更新.zshrc中的MINICPM配置

ZSHRC="$HOME/.zshrc"

echo "=== 更新MINICPM配置 ==="

# 备份
cp "$ZSHRC" "${ZSHRC}.backup.$(date +%Y%m%d_%H%M%S)"
echo "✓ 已备份.zshrc"

# 使用sed替换配置
# 注意：macOS的sed需要空字符串参数
sed -i '' 's|^export MINICPM_BASE_URL=.*|export MINICPM_BASE_URL="https://llm-center.ali.modelbest.cn/llm/v1"|' "$ZSHRC"
sed -i '' 's|^export MINICPM_INSTRUCT_MODEL_ID=.*|export MINICPM_INSTRUCT_MODEL_ID="minicpm-v-4"  # 视觉模型使用小写|' "$ZSHRC"

echo "✓ 已更新MINICPM_BASE_URL: https://llm-center.ali.modelbest.cn/llm/v1"
echo "✓ 已更新MINICPM_INSTRUCT_MODEL_ID: minicpm-v-4"
echo ""
echo "请执行: source ~/.zshrc 使配置生效"
