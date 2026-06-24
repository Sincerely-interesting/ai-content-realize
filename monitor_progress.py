# -*- coding: utf-8 -*-
"""监控打标进度并在完成后自动导出Excel"""
import json
import time
import pandas as pd
from pathlib import Path
from datetime import datetime

CACHE_FILE = Path("d:/gitrepo/material-process/revalidation_cache.json")
TARGET_COUNT = 26
CHECK_INTERVAL = 30  # 每30秒检查一次

def export_to_excel(cache_data):
    """导出缓存到Excel"""
    rows = []
    for material_id, data in cache_data.items():
        rows.append({
            "素材ID": material_id,
            "打标结果": data.get("label", "未知"),
            "判定理由": data.get("reason", ""),
            "打标时间": data.get("time", ""),
            "状态": "失败" if "失败" in data.get("label", "") else "成功"
        })
    
    df = pd.DataFrame(rows)
    
    # 统计
    print(f"\n{'='*60}")
    print(f"共 {len(df)} 条记录")
    print(f"\n标签分布:")
    print(df["打标结果"].value_counts())
    print(f"\n成功/失败:")
    print(df["状态"].value_counts())
    
    # 导出Excel
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"d:/gitrepo/material-process/revalidation_results_26_{timestamp}.xlsx"
    df.to_excel(output_file, index=False, engine="openpyxl")
    print(f"\n✅ 已导出: {output_file}")
    return output_file

def main():
    print("🔍 开始监控打标进度...")
    print(f"📁 缓存文件: {CACHE_FILE}")
    print(f"🎯 目标数量: {TARGET_COUNT}")
    print(f"⏱️  检查间隔: {CHECK_INTERVAL}秒")
    print("="*60)
    
    last_count = 0
    
    while True:
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                
                current_count = len(cache)
                
                if current_count != last_count:
                    print(f"\n📊 [{datetime.now().strftime('%H:%M:%S')}] 进度: {current_count}/{TARGET_COUNT}")
                    
                    # 显示最新处理的素材
                    if current_count > 0:
                        last_id = list(cache.keys())[-1]
                        last_label = cache[last_id].get("label", "未知")
                        print(f"   最新: {last_id} -> {last_label}")
                    
                    last_count = current_count
                
                if current_count >= TARGET_COUNT:
                    print(f"\n✅ 打标完成! 共处理 {current_count} 个素材")
                    export_to_excel(cache)
                    break
                
            except Exception as e:
                print(f"⚠️  读取缓存失败: {e}")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
