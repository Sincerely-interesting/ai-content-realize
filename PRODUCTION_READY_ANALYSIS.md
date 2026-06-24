# 🚀 MiniMax 打标脚本 - 生产级解决方案

## 📊 HTTP 529 错误深度分析报告

### 问题现象

```
2026-04-20 16:24:18 [1/718] 正在打标: 440872701
2026-04-20 16:24:18 [ERROR] API 错误 (529): overloaded_error (529)
2026-04-20 16:24:19 [ERROR] API 错误 (529): overloaded_error (529)  
2026-04-20 16:24:21 [ERROR] API 错误 (529): overloaded_error (529)
2026-04-20 16:24:21 [ERROR] API 调用最终失败 (3次尝试)
```

**时间线分析：**
```
16:24:18.507 - 第1次请求 → 529 (等待 2s)
16:24:19.588 - 第2次请求 → 529 (等待 4s)
16:24:20.413 - 第3次请求 → 529 (失败)
```

**总计影响：718 个素材全部失败**

---

## 🔍 根因分析

### 1. HTTP 529 错误本质

**错误含义：**
```json
{
  "type": "error",
  "error": {
    "type": "overloaded_error",
    "message": "overloaded_error (529)"
  }
}
```

**根因：**
- MiniMax API 服务端过载 (Server Overloaded)
- 非标准 HTTP 状态码 (529 不在 RFC 规范中)
- 类似 Cloudflare 的 529 语义：服务器暂时无法处理请求

**触发条件：**
1. ⚠️ **高频连续请求** - 0.5 秒间隔太快
2. ⚠️ **超出服务端容量** - 并发请求数超过服务器处理能力
3. ⚠️ **Token 配额限流** - 账户级别的速率限制
4. ⚠️ **服务端维护/故障** - 基础设施问题

---

### 2. 原脚本的致命缺陷

#### ❌ 缺陷 1: 529 未被识别为可重试错误

**原代码：**
```python
elif resp.status_code in [500, 502, 503, 504]:
    # 只处理这些服务器错误
    wait_time = 2 ** attempt * 2
    logger.warning(f"API 服务器错误 ({resp.status_code})...")
    time.sleep(wait_time)
    continue

else:
    # 529 会进入这个分支！
    logger.error(f"API 错误 ({resp.status_code}): {resp.text[:300]}")
    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
    # 没有 continue，直接退出循环 → 永久失败
```

**问题：**
- 529 不在 `[500, 502, 503, 504]` 列表中
- 进入 `else` 分支后记录错误并退出
- 即使配置了 3 次重试，也不会执行

#### ❌ 缺陷 2: 重试间隔太短

**原退避策略：**
```python
wait_time = 2 ** attempt * 2  # 2s, 4s, 8s
```

**问题：**
- 对于 overloaded 错误，2-4 秒远远不够
- 服务端需要更长时间恢复
- 连续快速重试会加剧服务器负载

#### ❌ 缺陷 3: 缺乏全局速率控制

**原代码：**
```python
time.sleep(0.5)  # 固定 0.5 秒间隔
```

**问题：**
- 718 个素材 × 0.5 秒 = 持续高频请求
- 没有根据 API 响应动态调整
- 容易持续触发 529/429

#### ❌ 缺陷 4: 无熔断保护

**问题：**
- 连续失败时仍然继续请求
- 浪费时间和 API 配额
- 没有给服务端恢复时间

---

## ✅ 生产级解决方案

### 核心改进策略

#### 1️⃣ 将 529 纳入可重试错误

**新代码：**
```python
elif resp.status_code == 529:
    # 服务端过载 - 需要更长退避时间
    wait_time = min(15 * (2 ** attempt), 90)  # 15s, 30s, 60s, 90s, 90s
    logger.warning(f"⚠️ API 服务过载 (529)，等待 {wait_time}s 后重试 [{attempt+1}/{max_retries}]...")
    time.sleep(wait_time)
    continue
```

**退避策略对比：**

| 错误类型 | 原策略 | 新策略 | 改进 |
|---------|--------|--------|------|
| 429 限流 | 5s, 10s, 20s | **10s, 20s, 40s, 60s** | 3x 更保守 |
| 529 过载 | ❌ 不处理 | **15s, 30s, 60s, 90s** | 新增支持 |
| 500/502/503/504 | 2s, 4s, 8s | **5s, 10s, 20s, 30s** | 2.5x 更长 |

#### 2️⃣ 增加重试次数

**原配置：**
```python
max_retries = 3
```

**新配置：**
```python
max_retries = 5  # 增加至 5 次
```

**效果：**
- 对于临时性过载，更多重试机会
- 配合更长退避时间，成功率显著提升

#### 3️⃣ 全局速率控制

**新机制：**
```python
# 全局请求计数器
global_request_count = 0
last_request_time = time.time()

for idx, mid in enumerate(unprocessed, 1):
    # 检查上次请求时间
    current_time = time.time()
    time_since_last_request = current_time - last_request_time
    
    # 如果间隔小于 2 秒，强制等待
    if time_since_last_request < 2.0:
        wait_time = 2.0 - time_since_last_request
        logger.debug(f"⏱️ 速率控制: 等待 {wait_time:.1f}s")
        time.sleep(wait_time)
    
    last_request_time = time.time()
    global_request_count += 1
```

**优势：**
- 确保请求间隔 ≥ 2 秒
- 避免连续请求触发 529
- 自适应调整 (考虑重试等待时间)

#### 4️⃣ 熔断保护机制

**实现：**
```python
stats = {
    'consecutive_failures': 0,  # 连续失败次数
    'max_consecutive_failures': 0,
    # ...
}

for idx, mid in enumerate(unprocessed, 1):
    # 检查连续失败次数
    if stats['consecutive_failures'] >= 5:
        pause_time = 30  # 暂停 30 秒
        logger.warning(f"🛑 触发熔断保护: 连续 {stats['consecutive_failures']} 次失败，暂停 {pause_time}s...")
        time.sleep(pause_time)
        stats['consecutive_failures'] = 0  # 重置计数器
    
    # 处理素材...
    if success:
        stats['consecutive_failures'] = 0  # 成功时重置
    else:
        stats['consecutive_failures'] += 1
```

**触发条件：**
- 连续 5 次失败 → 暂停 30 秒
- 给服务端充足恢复时间
- 避免浪费 API 配额

#### 5️⃣ 增强统计与可观测性

**新增指标：**
```python
stats = {
    'success': 0,
    'failed': 0,
    'overloaded_529': 0,      # 529 错误计数
    'rate_limited_429': 0,    # 429 错误计数
    'total_api_calls': 0,
    'consecutive_failures': 0,
    'max_consecutive_failures': 0,
    'errors': []
}
```

**进度报告 (每 10 个素材)：**
```
============================================================
📈 进度报告 [10/718]
✅ 成功: 8 | ❌ 失败: 2 | 成功率: 80.0%
⚠️  529错误: 1 | 429错误: 1
🔥 最大连续失败: 3
============================================================
```

**最终统计报告：**
```
============================================================
🎯 打标任务完成 - 最终统计报告
============================================================
📊 总素材数: 774
🔄 本次处理: 718
📞 总 API 调用: 850
✅ 成功: 650
❌ 失败: 68
📈 成功率: 90.5%

⚠️  限流统计:
  - 529 Overloaded: 45 次
  - 429 Rate Limited: 12 次
  - 建议: 增加请求间隔或联系 API 提供商提高配额

🔥 最大连续失败: 7 次

💡 后续建议:
  1. 529 错误较多，建议增加请求间隔至 3-5 秒
  2. 或联系 MiniMax 提高 API 配额
  3. 运行: python retry_failed.py 清理失败记录后重试
============================================================
```

---

## 📈 预期效果对比

| 指标 | 原版本 | 改进版 | 提升幅度 |
|------|--------|--------|---------|
| **529 处理** | ❌ 不重试 | ✅ 5次重试 + 长退避 | - |
| **重试次数** | 3 次 | **5 次** | +67% |
| **退避时间** | 2-8 秒 | **15-90 秒** | 10x 更长 |
| **请求间隔** | 固定 0.5s | **动态 ≥2s** | 4x 更保守 |
| **熔断保护** | ❌ 无 | ✅ 连续5次失败暂停30s | - |
| **成功率预期** | 7.2% | **85-95%** | **10x+** |
| **可观测性** | ❌ 简单打印 | ✅ 详细统计+进度报告 | - |

---

## 🚀 使用指南

### 场景 1: 重试 718 个失败的素材

```bash
# 步骤 1: 清理失败记录 (自动备份)
python retry_failed.py

# 输出示例:
# 当前缓存记录数: 774
# 需要重试的记录数: 718
# 失败原因分布:
#   - API 调用失败: 718
#   - 529 服务过载: 718
#   - 429 速率限制: 0
#   - 其他原因: 0
# 
# 💾 已备份原缓存: minimax_label_cache_backup_20260420_162500.json
# ✅ 已清理 718 条失败记录
# 📊 剩余缓存记录数: 56

# 步骤 2: 运行改进版脚本
python minimax_label_materials.py

# 脚本会:
# - 自动以 ≥2 秒间隔请求
# - 529 错误自动重试 5 次 (15s → 30s → 60s → 90s → 90s)
# - 连续失败 5 次自动暂停 30 秒
# - 每 3 个素材自动保存缓存
# - 每 10 个素材输出进度报告
```

### 场景 2: 调整请求间隔 (如果 529 仍然频繁)

编辑 `minimax_label_materials.py`，修改全局速率控制：

```python
# 找到这一行 (约 380 行)
if time_since_last_request < 2.0:
    wait_time = 2.0 - time_since_last_request

# 修改为更保守的间隔 (例如 3 秒或 5 秒)
if time_since_last_request < 3.0:  # 或 5.0
    wait_time = 3.0 - time_since_last_request
```

### 场景 3: 查看处理日志

```powershell
# 实时查看日志
Get-Content minimax_labeling.log -Wait -Tail 50

# 搜索 529 错误
Select-String "529" minimax_labeling.log

# 查看统计报告
Select-String "统计报告" minimax_labeling.log
```

### 场景 4: 验证成功率

```bash
python -c "
import json
cache = json.load(open('minimax_label_cache.json', encoding='utf-8'))
total = len(cache)
success = sum(1 for v in cache.values() if v['label'] != '其他')
failed = total - success
print(f'总记录: {total}')
print(f'成功: {success} ({success/total*100:.1f}%)')
print(f'失败: {failed} ({failed/total*100:.1f}%)')
"
```

---

## ⚙️ 高级配置

### 配置参数说明

```python
# 在 analyze_image 函数中
max_retries: int = 5  # 最大重试次数

# 退避时间配置
elif resp.status_code == 529:
    wait_time = min(15 * (2 ** attempt), 90)  
    # 15 * 2^0 = 15s
    # 15 * 2^1 = 30s
    # 15 * 2^2 = 60s
    # 15 * 2^3 = 120s → 限制为 90s
    # 15 * 2^4 = 240s → 限制为 90s

# 全局速率控制
if time_since_last_request < 2.0:  # 最小请求间隔
    wait_time = 2.0 - time_since_last_request

# 熔断保护
if stats['consecutive_failures'] >= 5:  # 连续失败阈值
    pause_time = 30  # 暂停时间
```

### 根据 API 配额调整

**如果 API 配额充足：**
```python
# 可以加快处理速度
if time_since_last_request < 1.5:  # 减少间隔
max_retries = 3  # 减少重试次数
```

**如果 529 频繁出现：**
```python
# 更保守的策略
if time_since_last_request < 5.0:  # 增加间隔
wait_time = min(20 * (2 ** attempt), 120)  # 更长退避
if stats['consecutive_failures'] >= 3:  # 更早触发熔断
    pause_time = 60  # 更长暂停
```

---

## 🛡️ 容错机制总结

| 机制 | 触发条件 | 动作 | 目的 |
|------|---------|------|------|
| **指数退避** | 429/529/500 错误 | 15s → 30s → 60s → 90s | 给服务端恢复时间 |
| **全局速率控制** | 请求间隔 < 2s | 强制等待至 2s | 避免连续高频请求 |
| **熔断保护** | 连续 5 次失败 | 暂停 30s | 防止雪崩效应 |
| **定期缓存** | 每 3 个素材 | 保存进度 | 中断恢复 |
| **智能重试** | 区分错误类型 | 可重试 vs 不可重试 | 避免无效重试 |

---

## 📝 最佳实践

### ✅ 推荐做法

1. **首次运行** - 使用默认配置 (2s 间隔, 5 次重试)
2. **监控日志** - 观察 529/429 错误频率
3. **动态调整** - 根据错误率调整间隔
4. **分批处理** - 如果素材很多，可以分批运行
5. **定期备份** - 脚本已自动备份，但建议手动备份重要数据

### ❌ 避免做法

1. ❌ 不要将间隔设置为 < 1 秒 (容易触发 529)
2. ❌ 不要禁用重试机制 (临时错误会永久失败)
3. ❌ 不要忽略日志 (包含关键诊断信息)
4. ❌ 不要手动删除缓存文件 (会导致重复处理)
5. ❌ 不要在 529 频繁时继续快速重试 (会加剧问题)

---

## 🔧 故障排查

### 问题 1: 529 错误仍然很多

**症状：**
```
⚠️ API 服务过载 (529)，等待 15s 后重试 [1/5]...
⚠️ API 服务过载 (529)，等待 30s 后重试 [2/5]...
```

**解决方案：**
1. 增加全局请求间隔至 3-5 秒
2. 联系 MiniMax 提高 API 配额
3. 分批次处理 (每次 100-200 个素材)
4. 错峰运行 (避开高峰期)

### 问题 2: 处理速度太慢

**症状：**
```
平均每个素材需要 30-60 秒
```

**解决方案：**
1. 如果 529 很少，可以减少间隔至 1.5 秒
2. 减少重试次数至 3 次
3. 考虑使用更便宜的模型 (如果可用)

### 问题 3: 程序意外中断

**恢复方法：**
```bash
# 直接重新运行，会自动从断点继续
python minimax_label_materials.py

# 脚本会:
# 1. 加载缓存 (已处理的 56 个)
# 2. 跳过已处理的素材
# 3. 继续处理剩余的 662 个
```

---

## 📚 技术亮点

1. **自适应退避算法** - 根据错误类型动态调整等待时间
2. **多层容错机制** - 重试 + 速率控制 + 熔断保护
3. **智能错误分类** - 区分 429/529/500/超时等，针对性处理
4. **实时可观测性** - 进度报告、统计指标、错误分布
5. **断点续传** - 定期保存缓存，支持中断恢复
6. **防御性编程** - 假设一切都会出错，提前准备
7. **渐进式降级** - 4 层 JSON 解析策略，最大化成功率

---

## 🎯 总结

**核心改进：**
- ✅ 529 错误现在会被正确识别并重试
- ✅ 重试次数从 3 次增加到 5 次
- ✅ 退避时间从 2-8 秒增加到 15-90 秒
- ✅ 全局请求间隔从 0.5 秒增加到 ≥2 秒
- ✅ 新增熔断保护 (连续 5 次失败暂停 30 秒)
- ✅ 增强统计报告和可观测性

**预期效果：**
- 成功率从 7.2% 提升至 **85-95%**
- 718 个失败素材大部分可以成功处理
- 自动适应 API 限流，无需人工干预

**下一步：**
```bash
# 1. 清理失败记录
python retry_failed.py

# 2. 运行改进版脚本
python minimax_label_materials.py

# 3. 监控日志
Get-Content minimax_labeling.log -Wait

# 4. 验证结果
python analyze_cache.py
```

---

**版本信息：**
- 脚本版本: v2.0 (生产级)
- 更新日期: 2026-04-20
- 改进内容: 529 错误处理、自适应退避、熔断保护、增强统计

**作者：** AI Assistant  
**许可证：** Internal Use Only
