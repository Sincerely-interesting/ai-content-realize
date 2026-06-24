"""
从打标缓存生成 Excel 结果文件。
仅导出 id_list_before.txt 中指定的素材文件夹 ID。
"""
import json
import os
import pandas as pd
from datetime import datetime

ID_LIST_FILE  = 'id_list_before.txt'
CACHE_FILE    = 'minimax_mcp_multimodal_cache.json'
OUTPUT_EXCEL  = 'minimax_mcp_multimodal_results.xlsx'

# ── 1. 读取指定 ID 集合 ──────────────────────────────────────────
with open(ID_LIST_FILE, 'r', encoding='utf-8') as f:
    target_ids = [line.strip() for line in f if line.strip() and not line.startswith('#')]
print(f'指定 ID 集合: {len(target_ids)} 个')

# ── 2. 读取缓存 ──────────────────────────────────────────────────
with open(CACHE_FILE, 'r', encoding='utf-8') as f:
    cache = json.load(f)
print(f'缓存记录总数: {len(cache)} 条')

# ── 3. 只取目标 ID 中已缓存的 ───────────────────────────────────
today = datetime.now().strftime('%Y-%m-%d')
rows = []
missing = []

for mid in target_ids:
    if mid not in cache:
        missing.append(mid)
        continue
    d    = cache[mid]
    info = d.get('info', {})
    rows.append({
        'daterange':            today,
        'dynamiclink':          mid,
        '制作组类型（细分标签）': d.get('label', ''),
        '判定依据':              d.get('reason', ''),
        '是否视频':              info.get('frames_count', 0) > 0,
        '帧数':                  info.get('frames_count', 0),
        '是否有音频':            info.get('has_audio', False),
        '语音文本长度':          info.get('transcript_length', 0),
        '语音文本预览':          str(info.get('transcript_preview', ''))[:100],
    })

print(f'已缓存: {len(rows)} 条 | 未缓存(待充值后处理): {len(missing)} 条')
if missing:
    print(f'未缓存 ID 示例: {missing[:5]}')

# ── 4. 写入 Excel ────────────────────────────────────────────────
df = pd.DataFrame(rows)
df.to_excel(OUTPUT_EXCEL, index=False)
print(f'\n✅ Excel 已写入: {OUTPUT_EXCEL}  ({len(df)} 行)')

# ── 5. 标签分布统计 ──────────────────────────────────────────────
print('\n标签分布:')
print(df['制作组类型（细分标签）'].value_counts().to_string())
