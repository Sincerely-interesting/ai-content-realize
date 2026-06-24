#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
重试失败记录的辅助脚本
用于清理缓存中的失败记录，以便重新处理
"""

import json
import os
from datetime import datetime

CACHE_FILE = 'minimax_label_cache.json'

def retry_failed(only_api_errors=True):
    """
    重试失败的记录
    
    Args:
        only_api_errors: 如果为 True，只重试 API 调用失败的记录
                        如果为 False，重试所有标记为 "其他" 的记录
    """
    if not os.path.exists(CACHE_FILE):
        print("缓存文件不存在")
        return
    
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    
    print(f"当前缓存记录数: {len(cache)}")
    
    # 找出失败的记录
    failed_ids = []
    failure_reasons = {
        'api_call_failed': 0,
        'overloaded_529': 0,
        'rate_limited_429': 0,
        'other': 0
    }
    
    for mid, data in cache.items():
        label = data.get('label', '')
        reason = data.get('reason', '')
        
        if only_api_errors:
            # 只重试 API 调用失败的
            if 'API 调用失败' in reason:
                failed_ids.append(mid)
                if '529' in reason:
                    failure_reasons['overloaded_529'] += 1
                elif '429' in reason:
                    failure_reasons['rate_limited_429'] += 1
                else:
                    failure_reasons['api_call_failed'] += 1
            elif 'API 未返回有效内容' in reason:
                failed_ids.append(mid)
                failure_reasons['api_call_failed'] += 1
        else:
            # 重试所有 "其他" 标签
            if label == '其他' or label is None:
                failed_ids.append(mid)
                if 'API' in reason:
                    failure_reasons['api_call_failed'] += 1
                else:
                    failure_reasons['other'] += 1
    
    print(f"\n需要重试的记录数: {len(failed_ids)}")
    print(f"\n失败原因分布:")
    print(f"  - API 调用失败: {failure_reasons['api_call_failed']}")
    print(f"  - 529 服务过载: {failure_reasons['overloaded_529']}")
    print(f"  - 429 速率限制: {failure_reasons['rate_limited_429']}")
    print(f"  - 其他原因: {failure_reasons['other']}")
    
    if not failed_ids:
        print("\n✅ 没有需要重试的记录")
        return
    
    # 备份原缓存
    backup_file = f'minimax_label_cache_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=4)
    print(f"\n💾 已备份原缓存: {backup_file}")
    
    # 删除失败记录
    for mid in failed_ids:
        del cache[mid]
    
    # 保存清理后的缓存
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=4)
    
    print(f"\n✅ 已清理 {len(failed_ids)} 条失败记录")
    print(f"📊 剩余缓存记录数: {len(cache)}")
    print(f"\n🚀 现在可以运行 python minimax_label_materials.py 重新处理这些素材")
    print(f"💡 建议: 如果 529 错误较多，可以在脚本中增加请求间隔")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='重试失败的打标记录')
    parser.add_argument('--all', action='store_true', 
                       help='重试所有标记为"其他"的记录（不仅是 API 错误）')
    
    args = parser.parse_args()
    
    retry_failed(only_api_errors=not args.all)
