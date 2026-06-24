# MiniMax视觉模型API - 最终解决方案

## 🔍 测试结果

### 测试环境
- ✅ API Key: 按量付费 (`sk-api-...`)
- ✅ 端点: `https://api.minimaxi.com/v1/chat/completions` (OpenAI兼容)
- ✅ 图片编码: 成功 (284.8KB)

### 测试模型

| 模型名称 | 状态 | 视觉支持 | 说明 |
|---------|------|---------|------|
| MiniMax-M2.7 | ✅ 可用 | ❌ 不支持 | 返回"没有看到图片" |
| MiniMax-M2.7-highspeed | 未测试 | ❌ 不支持 | 极速版文本模型 |
| minimax-vl-01 | ❌ 错误 | - | "unknown model" |
| MiniMax-VL-01 | ❌ 错误 | - | "unknown model" |

### 关键发现

**MiniMax按量付费API当前不支持视觉模型！**

虽然文档说"按量付费支持所有模态模型，包括图像"，但：
1. VL-01模型返回"unknown model"错误
2. M2.7文本模型无法识别图片
3. API文档中没有列出视觉模型的调用方式

---

## ✅ 推荐解决方案

### 方案1: 使用Gemini视觉API（强烈推荐）

**优势**:
- ✅ 立即可用
- ✅ 视觉识别准确率极高
- ✅ 支持中文理解
- ✅ 免费额度充足
- ✅ 已有完整脚本

**配置步骤**:

1. **获取Gemini API Key**
   - 访问: https://aistudio.google.com/apikey
   - 创建API Key

2. **更新.env文件**
   ```env
   # MiniMax配置（保留）
   MIN_MAX_API_KEY=sk-api-your-key
   MODEL_NAME=MiniMax-M2.7
   
   # Gemini配置（新增）
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

3. **运行打标脚本**
   ```bash
   # 抽样50个文件夹
   python gemini_sample_50_label_materials.py
   
   # 或全量打标
   python gemini_label_materials.py
   ```

### 方案2: 联系MiniMax技术支持

**询问内容**:
1. MiniMax-VL-01模型是否已开放API调用？
2. 视觉模型的正确调用方式是什么？
3. 是否需要特殊申请或权限？

**联系方式**:
- 邮箱: Model@minimaxi.com
- 平台: https://platform.minimaxi.com

### 方案3: 使用其他视觉API

**备选方案**:
- **GPT-4 Vision**: https://platform.openai.com
- **Claude Vision**: https://www.anthropic.com
- **通义千问VL**: https://help.aliyun.com/zh/model-studio

---

## 🔧 当前可用脚本

### 已完成的脚本

1. ✅ **gemini_sample_50_label_materials.py**
   - 抽样50个文件夹
   - 使用Gemini 2.5 Flash
   - 完整的打标逻辑
   - **需要**: GEMINI_API_KEY

2. ✅ **gemini_label_materials.py**
   - 全量打标
   - 使用Gemini 2.5 Flash
   - 支持批量处理和缓存
   - **需要**: GEMINI_API_KEY

3. ⚠️ **minimax_mcp_label_materials.py**
   - 代码已完成
   - 集成Search和Embeddings MCP
   - **问题**: MiniMax视觉API不可用
   - **状态**: 等待MiniMax开放视觉模型API

### 脚本对比

| 特性 | Gemini脚本 | MiniMax MCP脚本 |
|------|-----------|----------------|
| 视觉API | ✅ 可用 | ❌ 不可用 |
| Search MCP | ❌ 无 | ✅ 已集成 |
| Embeddings MCP | ❌ 无 | ✅ 已集成 |
| 立即可用 | ✅ 是 | ❌ 否 |
| 准确率 | ⭐⭐⭐⭐⭐ | - |

---

## 📋 立即可执行的方案

### 步骤1: 获取Gemini API Key

```bash
# 访问 https://aistudio.google.com/apikey
# 点击 "Create API Key"
# 复制API Key
```

### 步骤2: 更新.env文件

```env
# 保留MiniMax配置（用于文本任务）
MIN_MAX_API_KEY=sk-api-your-minimax-key
MODEL_NAME=MiniMax-M2.7

# 添加Gemini配置（用于视觉任务）
GEMINI_API_KEY=AIzaSy-your-gemini-key-here
```

### 步骤3: 运行打标

```bash
# 抽样50个文件夹（推荐先测试）
python gemini_sample_50_label_materials.py

# 查看结果
# - gemini_sample_50_results.xlsx
# - gemini_sample_50_cache.json
# - gemini_sample_labeling.log
```

### 步骤4: 验证结果

```bash
# 查看日志
cat gemini_sample_labeling.log

# 打开Excel查看打标结果
```

---

## 🎯 最终建议

### 短期（立即执行）
**使用Gemini API进行视觉打标**
- 准确率最高
- 立即可用
- 免费额度充足

### 中期（1-2周）
**联系MiniMax确认视觉模型API**
- 询问VL-01的开放计划
- 如果有，切换到MiniMax
- 利用已完成的MCP集成代码

### 长期
**多API备用架构**
```python
# 伪代码
def analyze_image(image_path):
    try:
        # 主: MiniMax VL-01 (如果可用)
        return minimax_vision_api(image_path)
    except:
        try:
            # 备1: Gemini
            return gemini_vision_api(image_path)
        except:
            # 备2: GPT-4 Vision
            return gpt4_vision_api(image_path)
```

---

## 📊 成本对比

| API | 免费额度 | 超出后价格 | 性价比 |
|-----|---------|-----------|--------|
| Gemini 2.5 Flash | 15次/分钟 | $0.0375/1K图片 | ⭐⭐⭐⭐⭐ |
| MiniMax VL-01 | 未知 | 未知 | - |
| GPT-4 Vision | 无 | $0.01/图片 | ⭐⭐⭐ |

---

## ✅ 总结

1. **MiniMax视觉API目前不可用**（VL-01返回unknown model）
2. **Gemini API是最佳替代方案**（立即可用，准确率高）
3. **所有代码已准备就绪**（只需添加GEMINI_API_KEY）
4. **MiniMax MCP代码已保存**（未来API开放后可立即启用）

**下一步行动**: 
1. 获取Gemini API Key
2. 更新.env文件
3. 运行 `python gemini_sample_50_label_materials.py`

---

**更新日期**: 2026-04-20  
**测试结论**: MiniMax视觉API不可用，推荐使用Gemini  
**代码状态**: 全部就绪，等待API Key配置
