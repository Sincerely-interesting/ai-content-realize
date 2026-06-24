# MiniMax 标签脚本改进说明

## 问题分析报告

### 核心问题
原脚本处理 774 个素材，**718 个失败 (92.8% 失败率)**，仅 6 个成功。

### 根因分析

#### 1. **API 响应处理缺陷** (严重性: 🔴 高)
**现象**: 所有失败都返回 "API 调用失败"，无法区分具体原因

**问题代码**:
```python
# 原代码 - 过于简化
try:
    resp = requests.post(...)
    if resp.status_code == 200:
        return text_content
    else:
        print(f"错误: {resp.text[:500]}")
        return None
except Exception as e:
    print(f"请求异常: {e}")
    return None
```

**影响**:
- 无法区分 401(认证失败)、429(速率限制)、500(服务器错误)、超时等
- 所有错误混为一谈，无法针对性处理
- 没有记录请求参数和响应内容，难以调试

**改进方案**:
```python
# 新增代码 - 详细错误分类
if resp.status_code == 200:
    # 成功处理
elif resp.status_code == 429:
    # 速率限制 - 指数退避重试
    wait_time = min(2 ** attempt * 5, 30)
    time.sleep(wait_time)
    continue
elif resp.status_code in [500, 502, 503, 504]:
    # 服务器错误 - 可重试
    wait_time = 2 ** attempt * 2
    time.sleep(wait_time)
    continue
elif resp.status_code == 401:
    logger.error("API 认证失败")
    return None
elif resp.status_code == 400:
    logger.error(f"请求参数错误: {resp.text[:300]}")
    return None
```

---

#### 2. **缺乏重试机制** (严重性: 🔴 高)
**现象**: 单次请求失败即永久放弃

**问题场景**:
- 网络瞬时抖动 (TCP 连接超时)
- API 服务端短暂不可用 (502/503)
- 速率限制触发 (429 Too Many Requests)
- DNS 解析失败

**影响**: 临时性问题导致永久性失败，成功率大幅降低

**改进方案**:
```python
# 新增指数退避重试逻辑
max_retries = 3
for attempt in range(max_retries):
    try:
        resp = requests.post(..., timeout=60)
        if success:
            return result
        elif retryable_error:
            wait_time = 2 ** attempt * base_delay
            time.sleep(wait_time)
            continue
    except Timeout:
        # 超时也可重试
        wait_time = 2 ** attempt * 2
        time.sleep(wait_time)
        continue
```

**重试策略**:
- 第 1 次失败: 等待 2 秒
- 第 2 次失败: 等待 4 秒
- 第 3 次失败: 等待 8 秒
- 速率限制 (429): 等待 5/10/20 秒 (更保守)

---

#### 3. **Prompt 设计问题** (严重性: 🟡 中)
**现象**: API 经常返回 "未提供图片，无法进行分类" 等自然语言

**根因**:
1. Prompt 约束不够强，模型可以自由选择输出格式
2. 没有提供 JSON 示例
3. 模型可能无法正确解析 base64 图片

**原 Prompt**:
```
请直接输出 JSON 格式（不要包含 markdown 代码块标记）
```

**改进 Prompt**:
```
请直接输出 JSON 格式（不要包含 markdown 代码块标记），包含 'label' 和 'reason' 字段。
示例：{"label": "穿搭精选 (核心)-穿搭种草", "reason": "图片展示了完整的全身穿搭"}
```

**效果**: 通过提供明确示例，提高 JSON 输出合规率

---

#### 4. **JSON 解析过于脆弱** (严重性: 🟡 中)
**现象**: 模型返回 markdown 代码块或自然语言时解析失败

**原代码**:
```python
# 只能处理简单的 { ... } 提取
start = content.find('{')
end = content.rfind('}') + 1
result = json.loads(content[start:end])
```

**问题**:
- 无法处理 markdown 代码块: ```json { ... } ```
- 多个 JSON 对象时会提取错误
- 没有容错机制

**改进方案 - 4 层解析策略**:
```python
def parse_api_response(content: str) -> Tuple[str, str]:
    # 方法1: 直接解析 (最理想)
    try:
        result = json.loads(content)
        return result['label'], result['reason']
    except: pass
    
    # 方法2: 提取文本中的 JSON (次优)
    try:
        start = content.find('{')
        end = content.rfind('}') + 1
        result = json.loads(content[start:end])
        return result['label'], result['reason']
    except: pass
    
    # 方法3: 处理 markdown 代码块
    try:
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', content, re.DOTALL)
        result = json.loads(json_match.group(1))
        return result['label'], result['reason']
    except: pass
    
    # 方法4: 从自然语言中提取标签关键词 (降级方案)
    label_keywords = {
        "性能测试": ["性能测试", "运动场景"],
        "穿搭精选 (核心)-穿搭种草": ["全身图", "全身造型"],
        # ...
    }
    for label, keywords in label_keywords.items():
        if any(kw in content for kw in keywords):
            return label, content[:200]
    
    # 完全无法解析
    return "其他", f"解析失败: {content[:200]}"
```

**优势**: 即使模型不遵循 JSON 格式，也能提取有效信息

---

#### 5. **图片处理缺乏验证** (严重性: 🟡 中)
**现象**: 损坏的图片或空文件会导致 API 调用失败

**原代码**:
```python
img = Image.open(path)
img.thumbnail(...)
return base64.encode(...)
```

**问题**:
- 没有检查文件是否存在
- 没有验证图片完整性
- 空文件会生成无效的 base64

**改进方案**:
```python
def encode_image(path: str) -> Optional[str]:
    # 1. 检查文件存在性
    if not os.path.exists(path):
        logger.error(f"文件不存在: {path}")
        return None
    
    # 2. 检查文件大小
    file_size = os.path.getsize(path)
    if file_size == 0:
        logger.warning(f"文件为空: {path}")
        return None
    
    # 3. 验证图片完整性
    img = Image.open(path)
    try:
        img.verify()  # 验证文件是否损坏
    except Exception as e:
        logger.warning(f"图片损坏: {path}, {e}")
        return None
    
    # 4. 重新打开 (verify 后需要重新 open)
    img = Image.open(path)
    # ... 继续处理
```

---

#### 6. **日志和可观测性不足** (严重性: 🟢 低)
**现象**: 无法追踪处理进度、性能指标、失败原因分布

**原代码**:
```python
print(f"正在打标: {mid}")
print(f"结果: {label}")
```

**问题**:
- 没有记录时间戳
- 没有记录请求耗时
- 没有记录详细的错误信息
- 无法生成统计报告

**改进方案**:
```python
# 结构化日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('minimax_labeling.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# 详细记录
logger.info(f"[{idx}/{total}] 正在打标: {mid}")
logger.debug(f"API 请求尝试 {attempt + 1}/{max_retries}")
logger.debug(f"API 响应: status={resp.status_code}, 耗时={elapsed:.2f}s")
logger.info(f"结果: {label} - {reason[:100]}")

# 统计信息
stats = {'success': 0, 'failed': 0, 'errors': []}
# ... 处理完成后打印
logger.info(f"成功率: {stats['success']/total*100:.1f}%")
```

---

#### 7. **缓存保存策略不当** (严重性: 🟢 低)
**现象**: 只在所有处理完成后保存一次缓存

**风险**:
- 程序意外中断会丢失所有进度
- 长时间运行后需要从头开始

**改进方案**:
```python
# 每处理 5 个素材保存一次缓存
if idx % 5 == 0:
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=4)
    logger.debug(f"缓存已保存 ({len(cache)} 条记录)")

# 最终再保存一次
with open(CACHE_FILE, 'w', encoding='utf-8') as f:
    json.dump(cache, f, ensure_ascii=False, indent=4)
```

---

## 改进效果预期

| 指标 | 原版本 | 改进版 | 提升 |
|------|--------|--------|------|
| 成功率 | 7.2% (56/774) | **预计 85-95%** | **10x+** |
| 错误可追溯性 | ❌ 无法定位 | ✅ 详细日志 | - |
| 容错能力 | ❌ 无重试 | ✅ 3次重试+指数退避 | - |
| 解析成功率 | ❌ 单一策略 | ✅ 4层降级策略 | - |
| 中断恢复 | ❌ 丢失进度 | ✅ 定期保存缓存 | - |
| 可观测性 | ❌ 简单打印 | ✅ 结构化日志+统计 | - |

---

## 使用建议

### 1. 清理旧缓存重试
```bash
# 删除旧缓存（如果想重新处理所有素材）
rm minimax_label_cache.json

# 运行改进版脚本
python minimax_label_materials.py
```

### 2. 查看日志
```bash
# 实时查看日志
tail -f minimax_labeling.log

# 查看错误统计
grep "ERROR" minimax_labeling.log | wc -l
```

### 3. 调整重试参数
如果 API 限流严重，可以在代码中调整:
```python
# 增加重试次数
max_retries = 5  # 原为 3

# 增加请求间隔
time.sleep(1.0)  # 原为 0.5
```

### 4. 批量重试失败记录
```python
# 筛选失败的记录
import json
cache = json.load(open('minimax_label_cache.json'))
failed = {k: v for k, v in cache.items() if 'API 调用失败' in v['reason']}
print(f"需要重试: {len(failed)} 个")

# 删除失败记录，重新运行脚本
for k in failed.keys():
    del cache[k]
json.dump(cache, open('minimax_label_cache.json', 'w'), ensure_ascii=False, indent=4)
```

---

## 技术亮点

1. **指数退避重试**: 避免雪崩效应，优雅处理瞬时故障
2. **4层 JSON 解析**: 最大化提取有效信息，提高容错率
3. **详细分类错误**: 区分 401/400/429/500/超时等，针对性处理
4. **图片完整性验证**: 提前发现损坏文件，避免无效 API 调用
5. **定期缓存保存**: 支持中断恢复，避免进度丢失
6. **结构化日志**: 便于问题排查和性能分析
7. **类型注解**: 提高代码可读性和 IDE 支持
8. **统计报告**: 处理完成后自动输出成功率、失败详情

---

## 后续优化建议

1. **并发处理**: 使用 `asyncio` + `aiohttp` 实现并发请求 (需注意 API 限流)
2. **图片选择策略**: 不是只用第一张图，可以评估图片质量后选择最佳
3. **缓存优化**: 使用 SQLite 替代 JSON，支持更复杂的查询
4. **监控告警**: 集成 Prometheus/Grafana 监控成功率
5. **成本优化**: 对低分辨率图片使用更便宜的模型
