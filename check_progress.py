import json
import os

cache_file = 'minimax_mcp_multimodal_cache.json'
log_file = 'minimax_mcp_multimodal_labeling.log'

print("="*80)
print("📊 打标任务进度检查")
print("="*80)

# 检查缓存
if os.path.exists(cache_file):
    with open(cache_file, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    print(f"✅ 缓存文件存在")
    print(f"📝 已处理样本数: {len(cache)} / 200")
    print(f"📈 完成进度: {len(cache)/200*100:.1f}%")
    
    # 统计标签分布
    labels = {}
    for mid, data in cache.items():
        label = data.get('label', '未知')
        labels[label] = labels.get(label, 0) + 1
    
    print(f"\n🏷️  标签分布:")
    for label, count in sorted(labels.items(), key=lambda x: x[1], reverse=True):
        print(f"   {label}: {count}")
else:
    print("❌ 缓存文件不存在")

# 检查日志
if os.path.exists(log_file):
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # 找到最新的进度报告
    for line in reversed(lines):
        if '进度报告' in line:
            print(f"\n📋 最新进度报告:")
            idx = lines.index(line)
            for i in range(idx, min(idx+5, len(lines))):
                print(f"   {lines[i].strip()}")
            break
    
    # 检查是否有错误
    error_count = sum(1 for line in lines if 'ERROR' in line or '余额不足' in line)
    print(f"\n⚠️  错误日志数: {error_count}")
    
    if len(lines) > 0:
        print(f"\n🕐 最新日志时间: {lines[-1][:19]}")

print("="*80)
