"""修复 BOM 问题并处理缺失的素材"""

# 1. 修复 BOM 问题
with open('ids_200_samples.txt', 'r', encoding='utf-8-sig') as f:
    ids = [line.strip() for line in f if line.strip()]

with open('ids_200_samples_fixed.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(ids))

print(f'✅ 已创建无BOM的文件: ids_200_samples_fixed.txt')
print(f'   包含 {len(ids)} 个ID')
print(f'   第一个ID: {ids[0]}')

# 2. 检查 401214668 是否已处理
import json
import os

cache_file = 'labeling_200_cache.json'
with open(cache_file, 'r', encoding='utf-8') as f:
    cache = json.load(f)

missing_id = '401214668'
if missing_id in cache:
    print(f'\n✅ 素材 {missing_id} 已在缓存中')
    print(f'   标签: {cache[missing_id]["label"]}')
else:
    print(f'\n⚠️  素材 {missing_id} 不在缓存中，需要打标')
    
    # 检查文件夹
    folder_path = f'downloaded_materials/{missing_id}'
    if os.path.exists(folder_path):
        print(f'✅ 文件夹存在: {folder_path}')
        print(f'\n📋 请使用以下命令单独处理这个素材:')
        print(f'   python minimax_mcp_understand_label_materials.py --id-list ids_200_samples_fixed.txt --mode full')
    else:
        print(f'❌ 文件夹不存在: {folder_path}')
