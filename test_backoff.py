"""
测试退避时间计算公式
"""

# 当前的公式
def calculate_wait_time_529(attempt):
    """529 错误退避时间"""
    return min(15 * (2 ** attempt), 90)

def calculate_wait_time_429(attempt):
    """429 错误退避时间"""
    return min(10 * (2 ** attempt), 60)

def calculate_wait_time_500(attempt):
    """500 错误退避时间"""
    return min(5 * (2 ** attempt), 30)

print("=" * 60)
print("529 Overloaded 退避时间 (当前公式)")
print("=" * 60)
for attempt in range(5):
    wait = calculate_wait_time_529(attempt)
    print(f"Attempt {attempt+1}/5: 15 * 2^{attempt} = {15 * (2 ** attempt):3d}s → min(..., 90) = {wait:3d}s")

print()
print("=" * 60)
print("429 Rate Limit 退避时间 (当前公式)")
print("=" * 60)
for attempt in range(5):
    wait = calculate_wait_time_429(attempt)
    print(f"Attempt {attempt+1}/5: 10 * 2^{attempt} = {10 * (2 ** attempt):3d}s → min(..., 60) = {wait:3d}s")

print()
print("=" * 60)
print("问题分析")
print("=" * 60)
print()
print("如果日志显示 '等待 155s'，可能原因：")
print("1. 日志字符串拼接错误")
print("2. attempt 变量值不正确")
print("3. 公式被其他代码修改")
print()
print("验证日志格式字符串：")
attempt = 0
wait_time = 15
log_msg = f"⚠️ API 服务过载 (529)，等待 {wait_time}s 后重试 [{attempt+1}/5]..."
print(f"Attempt 0: {log_msg}")

attempt = 1
wait_time = 30
log_msg = f"⚠️ API 服务过载 (529)，等待 {wait_time}s 后重试 [{attempt+1}/5]..."
print(f"Attempt 1: {log_msg}")
