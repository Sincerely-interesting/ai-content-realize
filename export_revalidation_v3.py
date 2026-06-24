# -*- coding: utf-8 -*-
"""导出打标结果到Excel - 用于revalidation_results_v3.xlsx"""
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

# 读取缓存
cache_file = Path("d:/gitrepo/material-process/revalidation_cache.json")
output_file = Path("d:/gitrepo/material-process/revalidation_results_v3.xlsx")

if not cache_file.exists():
    print(f"❌ 缓存文件不存在: {cache_file}")
    exit(1)

with open(cache_file, "r", encoding="utf-8") as f:
    cache = json.load(f)

print(f"📊 共 {len(cache)} 条记录")

# 构建数据
rows = []
for material_id, data in sorted(cache.items()):
    rows.append({
        "素材ID": material_id,
        "打标结果": data["label"],
        "判定理由": data["reason"],
        "打标时间": data.get("time", "")
    })

# 创建DataFrame
df = pd.DataFrame(rows)

# 统计
print("\n📈 标签分布:")
print(df["打标结果"].value_counts())

# 导出Excel
df.to_excel(output_file, index=False, engine="openpyxl")
print(f"\n✅ 已导出: {output_file}")

# 显示详细结果
print("\n📋 详细结果:")
for _, row in df.iterrows():
    print(f"  {row['素材ID']}: {row['打标结果']}")