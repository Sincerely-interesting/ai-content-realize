# -*- coding: utf-8 -*-
"""清理失败的打标记录（API Error 2056导致的数据）"""
import json
import shutil
from datetime import datetime
from pathlib import Path

CACHE_FILE = "labeling_200_cache.json"
BACKUP_FILE = f"labeling_200_cache_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def main():
    print("=" * 60)
    print("🧹 清理失败的打标记录")
    print("=" * 60)
    
    # 1. 备份原始缓存
    print(f"\n📦 备份缓存: {BACKUP_FILE}")
    shutil.copy2(CACHE_FILE, BACKUP_FILE)
    print(f"✅ 备份完成")
    
    # 2. 读取缓存
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"\n📊 原始记录数: {len(data)}")
    
    # 3. 分离成功和失败记录
    success_records = {}
    failed_records = {}
    
    for mid, item in data.items():
        label = item.get('label', '')
        reason = item.get('reason', '')
        
        # 判断是否为API错误
        is_api_error = (
            label == '其他' and (
                '2056' in reason or 
                'usage limit' in reason.lower() or
                'Failed to perform' in reason or
                'API Error' in reason or
                '未找到JSON' in reason
            )
        )
        
        if is_api_error:
            failed_records[mid] = item
        else:
            success_records[mid] = item
    
    print(f"✅ 成功记录: {len(success_records)}")
    print(f"❌ 失败记录: {len(failed_records)}")
    
    # 4. 清理失败记录
    if failed_records:
        print(f"\n🗑️  删除 {len(failed_records)} 条失败记录...")
        
        # 写入清理后的缓存
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(success_records, f, ensure_ascii=False, indent=4)
        
        print(f"✅ 清理完成!")
        
        # 5. 显示需要重新打标的素材ID
        print(f"\n📝 需要重新打标的素材:")
        failed_ids = list(failed_records.keys())
        for i, mid in enumerate(failed_ids[:10], 1):
            print(f"  {i}. {mid}")
        if len(failed_ids) > 10:
            print(f"  ... 还有 {len(failed_ids) - 10} 个")
        
        # 6. 保存失败ID列表（用于后续重新打标）
        failed_id_file = "ids_failed_2056.txt"
        with open(failed_id_file, 'w', encoding='utf-8') as f:
            for mid in failed_ids:
                f.write(f"{mid}\n")
        
        print(f"\n💾 已保存失败ID列表: {failed_id_file}")
        print(f"   共 {len(failed_ids)} 个素材需要重新打标")
        
    else:
        print("\n✅ 没有失败记录，无需清理")
    
    # 7. 显示下一步操作
    print(f"\n{'=' * 60}")
    print(f"📋 下一步操作:")
    print(f"{'=' * 60}")
    print(f"1. 登录 MiniMax 平台获取新 API Key")
    print(f"   https://platform.minimaxi.com")
    print(f"")
    print(f"2. 更新 .env 文件中的 MIN_MAX_API_KEY")
    print(f"")
    print(f"3. 从断点继续打标:")
    print(f"   python minimax_mcp_understand_label_materials.py \\")
    print(f"     --id-list ids_200_samples.txt \\")
    print(f"     --cache-file labeling_200_cache.json")
    print(f"")
    print(f"4. 或者先重新打标失败的素材:")
    print(f"   python minimax_mcp_understand_label_materials.py \\")
    print(f"     --id-list ids_failed_2056.txt \\")
    print(f"     --cache-file labeling_200_cache.json")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()
