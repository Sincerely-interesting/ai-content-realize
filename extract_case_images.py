#!/usr/bin/env python3
"""
从素材文件夹中提取代表性Case图片，更新报告并导出PDF
"""
import json
import shutil
from pathlib import Path
from collections import Counter

# 读取缓存
cache = json.load(open('minicpm_local_archiver_cache.json'))
source_dir = Path('downloaded_materials_smb')
case_images_dir = Path('case_images')

# 创建图片目录
case_images_dir.mkdir(exist_ok=True)

# 清理旧图片
if case_images_dir.exists():
    shutil.rmtree(case_images_dir)
case_images_dir.mkdir()

print("=" * 60)
print("  提取代表性Case图片")
print("=" * 60)
print()

# 标签分布
labels = [info.get('label', '') for info in cache.values()]
label_counter = Counter(labels)

print("标签分布:")
for label, count in label_counter.most_common():
    print(f"  {label}: {count}个")
print()

# 选择代表性Case
# 优秀Case：穿搭精选(核心) - 选择前2个
# 均值Case：单品展示 - 选择中间2个  
# 差劲Case：异常标签 - 选择最后几个

excellent_cases = []  # 优秀
average_cases = []    # 均值
poor_cases = []       # 差劲

# 分类
for mid, info in cache.items():
    label = info.get('label', '')
    
    if '穿搭精选 (核心)' in label:
        excellent_cases.append(mid)
    elif '单品展示' in label and '平铺' not in label:
        average_cases.append(mid)
    elif len(label) > 50 or '根据图片' in label:  # 异常长的标签
        poor_cases.append(mid)

# 选择代表性样本
selected_cases = {
    'excellent': excellent_cases[:2],  # 前2个优秀
    'average': average_cases[5:7],     # 中间2个均值
    'poor': poor_cases[:1] if poor_cases else average_cases[-1:]  # 1个差劲
}

print("选中的代表性Case:")
for tier, cases in selected_cases.items():
    tier_name = {'excellent': '优秀', 'average': '均值', 'poor': '差劲'}[tier]
    print(f"\n{tier_name} Case:")
    for mid in cases:
        info = cache[mid]
        print(f"  {mid}: {info.get('label', 'N/A')[:50]}")
        
        # 复制图片
        material_dir = source_dir / mid
        if material_dir.exists():
            # 创建Case图片目录
            case_dir = case_images_dir / mid
            case_dir.mkdir(exist_ok=True)
            
            # 复制前6张图片
            images = list(material_dir.glob('*.jpg')) + list(material_dir.glob('*.png')) + list(material_dir.glob('*.jpeg'))
            for i, img_path in enumerate(images[:6]):
                dest_path = case_dir / f"{mid}_pic_{i}.jpg"
                shutil.copy2(img_path, dest_path)
                print(f"    ✓ {img_path.name} -> {dest_path.name}")
        else:
            print(f"    ✗ 素材文件夹不存在: {material_dir}")

print("\n" + "=" * 60)
print("图片提取完成！")
print("=" * 60)
