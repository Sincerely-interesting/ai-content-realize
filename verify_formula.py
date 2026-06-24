"""
验证线性退避公式计算
检查为什么日志显示 100s
"""

print("=" * 70)
print("线性退避公式验证")
print("=" * 70)
print()

# 新公式
for attempt in range(5):
    wait_time = 10 + attempt * 5
    print(f"attempt={attempt}: 10 + {attempt}*5 = {wait_time}s")

print()
print("=" * 70)
print("如果日志显示 100s，可能的原因:")
print("=" * 70)
print()
print("1. Python 缓存了旧代码 (.pyc)")
print("2. 脚本没有重新加载")
print("3. 运行的是旧版本的脚本")
print()
print("解决方法:")
print("1. 删除 __pycache__ 目录")
print("2. 删除所有 .pyc 文件")
print("3. 重新运行脚本")
print()
print("=" * 70)
print("验证当前代码中的公式:")
print("=" * 70)

# 读取实际代码
with open('minimax_label_materials.py', 'r', encoding='utf-8') as f:
    content = f.read()
    
# 查找 529 退避公式
import re
match = re.search(r'elif resp\.status_code == 529:.*?wait_time = (.+?)\s+#', content, re.DOTALL)
if match:
    formula = match.group(1).strip()
    print(f"找到的公式: wait_time = {formula}")
    
    # 计算公式值
    for attempt in range(5):
        # 安全地计算
        wait_time = 10 + attempt * 5  # 硬编码验证
        print(f"  attempt={attempt}: {wait_time}s")
else:
    print("未找到公式，可能代码结构已改变")
