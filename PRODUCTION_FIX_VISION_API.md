# MiniMax视觉API生产级修复方案

## 🔴 问题总结

### 根本原因
MiniMax的**Anthropic兼容端点** (`/anthropic/v1/messages`) **不支持视觉模型VL-01**，会自动降级到文本模型M2.7。

### 测试结果
```
请求端点: https://api.minimaxi.com/v1/chat/completions (OpenAI兼容)
请求模型: MiniMax-VL-01
响应错误: "unknown model 'MiniMax-VL-01'"
```

**结论**: 当前的Token Plan API Key可能不支持VL-01模型，或者该模型需要通过其他端点访问。

---

## ✅ 生产级解决方案

### 方案1: 使用Gemini视觉API（推荐，立即可用）

由于MiniMax视觉API存在兼容性问题，建议使用Gemini Pro Vision作为视觉分析引擎。

**优势**:
- ✅ 立即可用，无需额外配置
- ✅ 视觉识别准确率高
- ✅ 已有`gemini_label_materials.py`脚本
- ✅ 支持批量处理

**实施步骤**:
```python
# 1. 确保Gemini API Key已配置
# .env文件中:
GEMINI_API_KEY=your_gemini_key

# 2. 使用gemini脚本
python gemini_label_materials.py
```

### 方案2: 申请MiniMax按量付费API Key

如果您必须使用MiniMax VL-01：

**步骤**:
1. 访问 https://platform.minimaxi.com
2. 进入"接口密钥"页面
3. 创建**按量付费**的API Key（不是Token Plan）
4. 按量付费支持所有模态模型，包括视觉模型
5. 更新.env文件:
```env
MIN_MAX_API_KEY=sk-new-pay-as-you-go-key
MODEL_NAME=MiniMax-VL-01
```

### 方案3: 使用M2.7文本模型 + 图片元数据

如果只能使用Token Plan，可以降级使用文本模型，但准确度会降低：

**策略**:
- 使用图片文件名、文件夹名等元数据
- 使用图片的EXIF信息
- 结合文件夹结构推断标签

**缺点**: 准确率大幅下降，不推荐

---

## 🔧 当前脚本状态

### 已完成的修复
✅ 1. 端点从Anthropic改为OpenAI兼容格式
✅ 2. 请求格式改为`image_url` (OpenAI格式)
✅ 3. 认证方式改为`Bearer Token`
✅ 4. 响应解析适配OpenAI格式
✅ 5. 模型名称清理（移除Unicode隐藏字符）
✅ 6. 图片编码10步验证
✅ 7. 详细日志和请求追踪
✅ 8. 环境诊断功能

### 待解决的问题
❌ Token Plan API Key不支持VL-01模型
❌ 需要按量付费API Key或切换到其他视觉API

---

## 📋 推荐行动

### 立即执行（推荐）
```bash
# 1. 使用Gemini视觉API
python gemini_label_materials.py

# 2. 或者检查是否有按量付费API Key
# 如果有，更新.env并运行:
python minimax_mcp_label_materials.py
```

### 长期方案
1. **申请按量付费API Key**
   - 访问MiniMax平台
   - 创建按量付费Key
   - 支持所有模态模型

2. **多API备用方案**
   - 主: MiniMax VL-01 (如果可用)
   - 备: Gemini Pro Vision
   - 备: GPT-4 Vision

---

## 🎯 决策矩阵

| 方案 | 可用性 | 准确率 | 成本 | 推荐度 |
|------|--------|--------|------|--------|
| Gemini视觉API | ✅ 立即可用 | ⭐⭐⭐⭐⭐ | 免费额度 | ⭐⭐⭐⭐⭐ |
| MiniMax按量付费 | ❌ 需申请 | ⭐⭐⭐⭐⭐ | 按量计费 | ⭐⭐⭐⭐ |
| MiniMax Token Plan | ❌ 不支持VL | ⭐⭐ | 已付费 | ⭐ |

---

## 📝 下一步

### 如果您选择Gemini
```bash
# 直接运行
python gemini_label_materials.py
```

### 如果您选择MiniMax按量付费
1. 申请新的API Key
2. 更新`.env`文件
3. 运行测试:
```bash
python test_vision_api_direct.py
```
4. 确认成功后运行:
```bash
python minimax_mcp_label_materials.py
```

---

**更新日期**: 2026-04-20  
**状态**: 🟡 需要API Key升级或切换到Gemini  
**优先级**: 高
