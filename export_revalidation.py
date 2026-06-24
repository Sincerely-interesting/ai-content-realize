# -*- coding: utf-8 -*-
"""导出重验证结果到Excel"""
import json
import pandas as pd
from pathlib import Path

# 读取缓存
cache_file = Path("d:/gitrepo/material-process/revalidation_cache.json")
with open(cache_file, "r", encoding="utf-8") as f:
    cache = json.load(f)

# 构建数据
rows = []
for material_id, data in cache.items():
    rows.append({
        "素材ID": material_id,
        "打标结果": data["label"],
        "判定理由": data["reason"],
        "打标时间": data["time"]
    })

# 创建DataFrame
df = pd.DataFrame(rows)

# 统计
print(f"共 {len(df)} 条记录")
print("\n标签分布:")
print(df["打标结果"].value_counts())

# 导出Excel
output_file = "d:/gitrepo/material-process/revalidation_results_v2.xlsx"
df.to_excel(output_file, index=False, engine="openpyxl")
print(f"\n已导出: {output_file}")
