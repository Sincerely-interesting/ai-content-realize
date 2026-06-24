# ai-content-realize 生产接口文档

## 1. 文档目的

本文档面向两类使用者：

1. **项目接手者 / 维护者**  
   需要快速理解当前仓库有哪些可用入口、它们的输入输出是什么、生产边界在哪里。

2. **调用方 / 集成方**  
   需要知道如何通过 CLI、环境变量和 HTTP 服务稳定地接入本项目，而不是继续记忆多个历史脚本。

这份文档聚焦“接口”而不是“实现细节”，目标是把项目从“能跑”提升到“可交接、可执行、可约束”。

---

## 2. 当前接口面总览

当前项目已经形成三类接口面：

| 接口面 | 状态 | 作用 | 推荐程度 |
|------|------|------|------|
| CLI 统一入口 | 已收敛 | 下载、打标、归档、同步、诊断 | 高 |
| HTTP 检索服务 | 可用但不自洽 | 相似样本检索、规则搜索、单素材解释 | 中 |
| 环境变量配置面 | 已模板化但未完全统一 | provider 配置、路径与压缩参数 | 高 |

### 当前最重要的判断

- **CLI 是当前生产主入口**
- **HTTP 服务是平台化雏形，不是本仓库的完全独立交付面**
- **环境变量层仍有历史命名分叉，需要调用方显式对齐**

---

## 3. 设计结论与自我辨证

### 3.1 本次收敛做对了什么

1. 用统一 CLI 解决了“多个主脚本边界相近但操作入口分裂”的问题。
2. 用 `requirements.txt` / `pyproject.toml` 解决了“装环境靠口头传承”的问题。
3. 用 `.env.example` 解决了“环境变量靠猜”的问题。

### 3.2 仍然没有彻底解决什么

1. CLI 目前仍然是**编排层**，底层逻辑还在历史脚本里。
2. 各命令的日志风格、错误表现、退出码语义尚未完全统一。
3. 检索服务依赖仓库外模块，因此还不能算完全自洽。

### 3.3 当前最准确的工程定位

> 这是一个已经完成第一阶段工程收敛的生产型工具仓库，但不是最终平台形态。

换言之，它已经足够生产使用，但还没有达到“所有链路共享同一内核”的成熟度。

---

## 4. CLI 接口规范

统一 CLI 入口定义于：

- [ai_content_realize_cli.py](/Users/kaori/Documents/ai-content-realize/ai_content_realize_cli.py:1)

安装完成后入口命令为：

```bash
ai-content-realize
```

### 4.1 顶层命令

```bash
ai-content-realize <command> [options]
```

当前支持：

| 命令 | 作用 | 底层模块 |
|------|------|------|
| `download` | 从本地 Excel 扫描并下载素材 | `download_materials_improved` |
| `label` | 使用 Gemini 进行标签打标 | `gemini_label_materials` |
| `archive` | 使用多 provider 生成归档报告 | `gemma_dewu_archiver` |
| `sync-cache` | 监控缓存并导出 / 同步 SMB | `cache_sync_to_smb` |
| `doctor` | 检查多模态依赖是否齐全 | `check_multimodal_deps` |

### 4.2 退出码约定

当前项目还没有统一错误码标准，但从运行语义上可按以下方式理解：

| 退出码 | 当前语义 |
|------|------|
| `0` | 成功完成命令 |
| 非 `0` | 底层脚本报错、环境缺失、参数错误、依赖异常或运行失败 |

建议后续收敛到明确错误码枚举；在此之前，生产侧应以“非 0 即失败”处理。

---

## 5. `download` 命令接口

### 5.1 作用

从当前目录中的 `.xlsx/.xls` 文件里扫描素材 URL，并将素材下载到统一目录结构。

### 5.2 命令格式

```bash
ai-content-realize download [options]
```

### 5.3 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|------|------|
| `--sample` | `int` | `0` | 限制下载素材数量，`0` 表示不限制 |
| `--all` | flag | `false` | 尽可能下载所有扫描到的素材 |
| `--output` | `str` | `downloaded_materials` | 输出目录 |
| `--workers` | `int` | `5` | 并发下载 worker 数 |

### 5.4 输入约束

- 当前工作目录下至少存在一个 Excel 文件。
- Excel 中能识别出 URL 列。
- URL 支持图片 / 视频链接。

### 5.5 输出约定

目录结构：

```txt
downloaded_materials/<material_id>/
```

每个素材一个子目录，内部为下载后的图片或视频。

### 5.6 失败语义

常见失败包括：

- 没有找到 Excel 文件
- Excel 可读但无法识别 URL 列
- 某个素材下载超时 / 网络失败
- URL 内容异常

### 5.7 生产建议

- 先 `--sample 10` 验证列识别是否正确
- 再放大到批量下载
- 对下载目录做外部容量监控

---

## 6. `label` 命令接口

### 6.1 作用

对素材目录执行 Gemini 标签打标，产出：

- 标签
- 判定依据
- cache
- Excel 结果

### 6.2 命令格式

```bash
ai-content-realize label [options]
```

### 6.3 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|------|------|
| `--materials-dir` | `str` | `downloaded_materials` | 素材目录 |
| `--output-file` | `str` | `gemini_labeled_results.xlsx` | Excel 输出文件 |
| `--delay` | `float` | `1.0` | API 调用间隔 |
| `--batch-size` | `int` | `5` | 每批处理素材数 |
| `--batch-delay` | `float` | `20.0` | 批次间隔 |

### 6.4 环境依赖

必须至少配置一个：

- `YESCODE_API_KEY`
- `GEMINI_API_KEY`

可选：

- `YESCODE_GEMINI_PROXY_BASE_URL`

### 6.5 输入约束

- 素材目录内每个素材应是单独文件夹
- 每个文件夹内至少有一张图片，或至少有一个视频文件

### 6.6 输出约定

| 产物 | 说明 |
|------|------|
| `gemini_label_cache.json` | 中间缓存 |
| Excel 文件 | 汇总标签结果 |
| `gemini_frames/` | 视频素材抽帧中间产物 |

### 6.7 标签返回语义

当前标签集来自提示词定义，至少包括：

- 性能测试 / 性能测评
- 明星穿搭
- 穿搭精选（核心）
- 穿搭精选（次要）
- 单品展示（上脚）
- 创意静物
- 静物展示
- 其他

### 6.8 失败语义

常见失败包括：

- API key 缺失
- 网络请求失败
- 模型返回非 JSON
- 视频抽帧后无可分析帧
- 素材目录不存在

### 6.9 生产建议

- 把 `delay` 与 `batch-delay` 当成限流保护手段，而不是可省略参数
- 保留 cache，用作断点续跑
- 对视频素材目录定期清理抽帧中间产物

---

## 7. `archive` 命令接口

### 7.1 作用

按 provider 生成素材归档报告，而不仅仅是标签判定。  
输出面向策划 / 运营使用的 Markdown 报告。

### 7.2 命令格式

```bash
ai-content-realize archive [options]
```

### 7.3 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|------|------|
| `--provider` | enum | `custom_minmax` | 视觉 provider |
| `--media-type` | enum | `image` | 处理 `image` / `video` / `all` |
| `--sample` | `int` | `1000` | 处理素材文件夹数量 |
| `--concurrency` | `int` | `1` | 并发 API 调用数 |
| `--test` | flag | `false` | 测试模式，仅跑少量样本 |

provider 枚举：

- `custom_minmax`
- `minmax`
- `minmax_mcp`
- `kimi`
- `kimi_coding`
- `paddle`
- `minicpm`

### 7.4 输入约束

- 对图片模式：素材目录下应存在图片
- 对视频模式：素材目录下应存在 `mp4`
- 某些 provider 需要额外环境变量
- 视频场景通常要求 `ffmpeg`

### 7.5 输出约定

| 产物 | 说明 |
|------|------|
| `*_report.md` | 成功的归档报告 |
| `*_error.txt` | 失败记录 |

### 7.6 失败语义

常见失败包括：

- provider key 缺失
- 共享盘未挂载
- `ffmpeg` 不可用
- provider API 超时 / 限流 / 鉴权失败

### 7.7 生产建议

- 并发保持低值
- 先用 `--test`
- 不同 provider 的成本、稳定性、时延差异很大，不能直接混用同一阈值

---

## 8. `sync-cache` 命令接口

### 8.1 作用

持续监控一个 JSON cache 文件：

1. 检测变化
2. 安全读取
3. 导出本地 Excel
4. 同步到 SMB

### 8.2 命令格式

```bash
ai-content-realize sync-cache [options]
```

### 8.3 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|------|------|
| `--cache-file` | `str` | `labeling_200_cache.json` | 监控的 JSON 缓存文件 |
| `--smb-path` | `str` | `\\192.168.2.242\大数据中心` | SMB 共享目录 |
| `--smb-filename` | `str` | `minimax_mcp_multimodal_results_latest.xlsx` | 共享盘文件名 |
| `--local-excel-dir` | `str` | `excel_exports` | 本地 Excel 导出目录 |
| `--poll-interval` | `int` | `60` | 轮询间隔（秒） |
| `--log-file` | `str` | `cache_sync.log` | 日志文件路径 |

### 8.4 输入约束

- cache 文件为 JSON object
- SMB 共享路径对当前机器可访问
- 当前进程有本地写权限

### 8.5 输出约定

- 本地 Excel 文件
- SMB 共享盘目标文件
- 日志文件

### 8.6 失败语义

常见失败包括：

- cache 文件不存在
- JSON 被写坏 / 正在写入
- SMB 不可达
- Excel 导出失败

### 8.7 生产建议

- 单独作为守护进程运行
- 与打标主任务解耦
- 对 SMB 健康状态做外部监控

---

## 9. `doctor` 命令接口

### 9.1 作用

检查多模态相关依赖是否满足运行要求。

### 9.2 命令格式

```bash
ai-content-realize doctor
```

### 9.3 输出语义

- 终端打印依赖检查结果
- 用于安装后健康检查，不直接修改任何业务数据

### 9.4 适用场景

- 新机器初始化
- 生产排障前的快速确认
- provider 切换前的环境预检

---

## 10. HTTP 服务接口

HTTP 服务入口位于：

- [multimodal_label_service/app.py](/Users/kaori/Documents/ai-content-realize/multimodal_label_service/app.py:1)

### 10.1 服务定位

它不是素材打标主入口，而是**知识检索与解释服务**。

### 10.2 边界说明

当前 HTTP 服务依赖以下外部模块：

- `multimodal_label_store`
- `multimodal_label_eval`
- `multimodal_label_knowledge`
- `minimax_mcp_client`

因此：

- **接口定义是清晰的**
- **服务实现不是单仓库自洽的**

### 10.3 健康检查

#### `GET /healthz`

作用：进程级存活检查

响应示例：

```json
{
  "status": "ok"
}
```

#### `GET /readyz`

作用：服务就绪检查，返回 embedding / table 状态摘要

响应示例：

```json
{
  "status": "ready",
  "provider": {
    "name": "hash-ngram",
    "version": "hash-ngram_v1_dim1536_c24",
    "dim": 1536
  },
  "tables": {
    "assets": {
      "row_count": 0,
      "embedding_ready": true,
      "embedding_applicable": false
    }
  }
}
```

### 10.4 相似样本搜索

#### `POST /api/v1/search/similar-samples`

请求体：

```json
{
  "query_text": "全身穿搭，街拍风格，非明星",
  "filters": {
    "media_type": "image",
    "label_id": "outfit_core",
    "has_person": true
  },
  "top_k": 5
}
```

字段约束：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query_text` | `string` | 是 | 检索文本 |
| `filters` | `object` | 否 | 检索过滤条件 |
| `top_k` | `int` | 否 | 返回条数，`1-100` |

响应体：

```json
[
  {
    "asset_id": "445123456",
    "label_id": "outfit_core",
    "label_display_name": "穿搭精选 (核心)-穿搭种草",
    "score": 0.78,
    "text": "reason=达人全身出镜，街拍场景，非明星",
    "source": "sample_memories",
    "metadata": {
      "media_type": "image",
      "retrieval_channels": ["fts", "vector:sample_embedding"]
    }
  }
]
```

### 10.5 规则搜索

#### `POST /api/v1/search/rules`

请求体：

```json
{
  "query_text": "全身图，头部躯干脚部同时出现",
  "media_type": "image",
  "label_target": "outfit_core",
  "top_k": 5
}
```

响应体：

```json
[
  {
    "rule_id": "rule_outfit_core_full_body",
    "label_id": "outfit_core",
    "label_display_name": "穿搭精选 (核心)-穿搭种草",
    "score": 0.81,
    "text": "需要识别到头部、躯干和脚部",
    "source": "rule_cards",
    "metadata": {
      "rule_type": "positive",
      "priority": 10
    }
  }
]
```

### 10.6 单素材解释

#### `POST /api/v1/search/explain`

请求体：

```json
{
  "asset_id": "445123456"
}
```

响应体：

```json
{
  "asset": {
    "asset_id": "445123456"
  },
  "observation": {
    "media_type": "image",
    "has_person": true
  },
  "sample_memory": {
    "label_id": "outfit_core",
    "label_display_name": "穿搭精选 (核心)-穿搭种草"
  },
  "decision_trace": {
    "trace_text": "命中 full body 规则"
  },
  "analysis_failure": null,
  "related_rules": []
}
```

错误行为：

- 资产不存在时返回 `404`

---

## 11. 环境变量接口

配置模板位于：

- [.env.example](/Users/kaori/Documents/ai-content-realize/.env.example:1)

### 11.1 Gemini / 代理链路

| 变量 | 必填 | 说明 |
|------|------|------|
| `YESCODE_API_KEY` | 条件必填 | YesCode / Gemini 代理 key |
| `GEMINI_API_KEY` | 条件必填 | Gemini key，和上者二选一 |
| `YESCODE_GEMINI_PROXY_BASE_URL` | 否 | Gemini 代理 base URL |

### 11.2 MiniMax 链路

| 变量 | 必填 | 说明 |
|------|------|------|
| `MIN_MAX_API_KEY` | 条件必填 | 历史命名 |
| `MINMAX_API_KEY` | 条件必填 | 另一历史命名 |
| `MODEL_NAME` | 否 | MiniMax 模型名 |

### 11.3 自定义 provider

| 变量 | 必填 | 说明 |
|------|------|------|
| `CUSTOM_MINMAX_API_KEY` | 按需 | 自定义服务鉴权 |
| `CUSTOM_MINMAX_URL` | 按需 | 自定义服务 base URL |

### 11.4 MINICPM

| 变量 | 必填 | 说明 |
|------|------|------|
| `MINICPM_API_KEY` | 按需 | MINICPM API key |
| `MINICPM_BASE_URL` | 否 | 默认已给出 |
| `MINICPM_INSTRUCT_MODEL_ID` | 否 | 默认 `minicpm-v-4` |

### 11.5 其他 provider

| 变量 | 必填 | 说明 |
|------|------|------|
| `KIMI_API_KEY` | 按需 | Kimi provider |
| `PADDLE_API_KEY` | 按需 | Paddle provider |

### 11.6 图像压缩

| 变量 | 必填 | 说明 |
|------|------|------|
| `IMAGE_MAX_SIZE` | 否 | 图片最大边长 |
| `IMAGE_QUALITY` | 否 | JPEG 质量 |

---

## 12. 输入输出契约

### 12.1 标准素材目录契约

推荐目录：

```txt
downloaded_materials/
  <material_id>/
    *.jpg / *.png / *.mp4
```

### 12.2 结果契约

| 类型 | 典型产物 |
|------|------|
| 缓存 | `*_cache.json` |
| 标签结果 | `*.xlsx` |
| 归档结果 | `*_report.md` |
| 中间产物 | `*_frames/` |
| 日志 | `*.log` |

### 12.3 调用方责任

调用方应保证：

1. provider 所需环境变量已配置
2. 素材目录结构稳定
3. 共享盘路径已挂载
4. `ffmpeg` 在需要视频链路时可用

---

## 13. 生产风险与反思

### 13.1 当前生产最强项

- 流程闭环完整
- 异常现实感强
- 已具备统一安装与统一入口

### 13.2 当前生产最大风险

- 内部仍是脚本编排，不是统一内核
- 服务层不完全自洽
- 配置命名历史包袱仍在

### 13.3 自我反思

这类项目最容易陷入两个极端：

1. 继续堆脚本，导致“只有原作者会跑”
2. 过早大重构，导致业务链断裂

本次收敛选择的是中间路线：

- 先统一入口
- 再统一安装
- 再暴露明确接口
- 最后才继续收敛内部实现

这是更符合生产迁移风险控制的路径。

---

## 14. 后续收敛建议

### 第一阶段之后的下一步

1. CLI 下沉为共享内核
2. 统一日志、错误码、配置对象
3. 将 provider 接口正式抽象
4. 为 HTTP 服务补齐依赖闭包

### 不建议现在就做的事

1. 一次性删除所有历史脚本
2. 未做回归基线就直接重写打标逻辑
3. 把 CLI 和服务层混成单一入口

正确顺序应当是：**统一入口 -> 统一配置 -> 统一内核 -> 统一服务层**。
