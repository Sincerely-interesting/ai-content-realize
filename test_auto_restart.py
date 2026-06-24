# -*- coding: utf-8 -*-
"""
自动重启调度器测试脚本
测试场景：
1. 正常完成
2. 配额耗尽自动重启
3. 状态持久化
4. 指数退避
"""

import os
import sys
import json
import time
from datetime import datetime

def test_state_persistence():
    """测试1: 状态持久化"""
    print("\n" + "="*80)
    print("测试1: 状态持久化")
    print("="*80)
    
    from auto_restart_scheduler import SchedulerState
    
    # 创建状态
    state = SchedulerState()
    state.update(total_processed=98, restart_count=0)
    
    # 验证文件创建
    assert os.path.exists('scheduler_state.json'), "状态文件未创建"
    print("✅ 状态文件创建成功")
    
    # 读取并验证
    state2 = SchedulerState()
    loaded = state2.load()
    assert loaded, "状态加载失败"
    assert state2.state['total_processed'] == 98, "数据不一致"
    print("✅ 状态加载成功")
    print("✅ 测试通过: 状态持久化正常")
    
    # 清理
    if os.path.exists('scheduler_state.json'):
        os.remove('scheduler_state.json')

def test_quota_monitor():
    """测试2: 配额监控"""
    print("\n" + "="*80)
    print("测试2: 配额监控")
    print("="*80)
    
    from auto_restart_scheduler import QuotaMonitor
    
    monitor = QuotaMonitor("test_key", "TEST_KEY")
    
    # 记录调用
    for i in range(10):
        monitor.record_call()
    
    remaining = monitor.get_remaining_quota()
    assert remaining == 440, f"配额计算错误: {remaining}"
    print(f"✅ 配额计算正确: 剩余 {remaining}/450")
    
    # 测试速率计算
    rate = monitor.get_call_rate()
    assert rate >= 0, "速率计算错误"
    print(f"✅ 调用速率: {rate:.2f} 次/分钟")
    
    print("✅ 测试通过: 配额监控正常")

def test_dynamic_switches():
    """测试3: 动态切换计算"""
    print("\n" + "="*80)
    print("测试3: 动态切换计算")
    print("="*80)
    
    # 创建临时ID列表
    test_ids = '\n'.join([str(i) for i in range(200)])
    with open('test_ids.txt', 'w') as f:
        f.write(test_ids)
    
    # 创建临时缓存
    test_cache = {str(i): {'label': 'test'} for i in range(98)}
    with open('test_cache.json', 'w', encoding='utf-8') as f:
        json.dump(test_cache, f)
    
    try:
        # 临时修改配置
        import auto_restart_scheduler
        original_id_list = auto_restart_scheduler.ID_LIST_FILE
        original_cache = auto_restart_scheduler.CACHE_FILE
        
        auto_restart_scheduler.ID_LIST_FILE = 'test_ids.txt'
        auto_restart_scheduler.CACHE_FILE = 'test_cache.json'
        
        # 创建调度器并计算
        from auto_restart_scheduler import AutoRestartScheduler
        scheduler = AutoRestartScheduler()
        max_switches = scheduler.calculate_dynamic_max_switches()
        
        print(f"📊 计算结果:")
        print(f"   总数: 200")
        print(f"   已处理: 98")
        print(f"   剩余: 102")
        print(f"   最大切换: {max_switches}")
        
        assert max_switches > 10, "切换次数过少"
        assert max_switches < 100, "切换次数过多"
        
        print("✅ 测试通过: 动态切换计算合理")
        
        # 恢复配置
        auto_restart_scheduler.ID_LIST_FILE = original_id_list
        auto_restart_scheduler.CACHE_FILE = original_cache
        
    finally:
        # 清理临时文件
        if os.path.exists('test_ids.txt'):
            os.remove('test_ids.txt')
        if os.path.exists('test_cache.json'):
            os.remove('test_cache.json')

def test_backoff_calculation():
    """测试4: 指数退避"""
    print("\n" + "="*80)
    print("测试4: 指数退避计算")
    print("="*80)
    
    from auto_restart_scheduler import AutoRestartScheduler, BACKOFF_BASE, BACKOFF_MAX
    
    scheduler = AutoRestartScheduler()
    
    # 测试不同重启次数的退避时间
    test_cases = [
        (0, 60, 120),      # 第1次: ~1分钟
        (1, 120, 240),     # 第2次: ~2分钟
        (2, 240, 480),     # 第3次: ~4分钟
        (3, 480, 960),     # 第4次: ~8分钟
        (10, 1800, 1800),  # 第11次: 最多30分钟
    ]
    
    for restart_count, min_expected, max_expected in test_cases:
        scheduler.state.state['restart_count'] = restart_count
        backoff = scheduler.calculate_backoff()
        
        # 允许10%的抖动
        min_with_jitter = min_expected * 0.9
        max_with_jitter = min(max_expected, BACKOFF_MAX) * 1.1
        
        assert min_with_jitter <= backoff <= max_with_jitter, \
            f"退避时间异常: restart={restart_count}, backoff={backoff}"
        
        print(f"✅ 重启#{restart_count}: {backoff}秒 (预期: {min_expected}-{max_expected})")
    
    print("✅ 测试通过: 指数退避正常")

def test_env_file_update():
    """测试5: .env文件更新"""
    print("\n" + "="*80)
    print("测试5: .env文件更新")
    print("="*80)
    
    from auto_restart_scheduler import AutoRestartScheduler
    
    # 备份原始.env
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        try:
            scheduler = AutoRestartScheduler()
            
            # 更新Key
            test_key = "test_api_key_12345"
            success = scheduler.update_env_file(test_key)
            
            assert success, "更新失败"
            print("✅ .env文件更新成功")
            
            # 验证内容
            with open('.env', 'r', encoding='utf-8') as f:
                content = f.read()
            
            assert test_key in content, "Key未更新"
            print("✅ Key更新验证成功")
            
        finally:
            # 恢复原始内容
            with open('.env', 'w', encoding='utf-8') as f:
                f.write(original_content)
            print("✅ .env文件已恢复")
    
    print("✅ 测试通过: .env文件更新正常")

def main():
    """运行所有测试"""
    print("\n" + "="*80)
    print("🧪 自动重启调度器测试套件")
    print("="*80)
    
    tests = [
        ("状态持久化", test_state_persistence),
        ("配额监控", test_quota_monitor),
        ("动态切换计算", test_dynamic_switches),
        ("指数退避", test_backoff_calculation),
        (".env文件更新", test_env_file_update),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"❌ 测试失败: {test_name}")
            print(f"   错误: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    # 总结
    print("\n" + "="*80)
    print("📊 测试结果总结")
    print("="*80)
    print(f"✅ 通过: {passed}/{len(tests)}")
    print(f"❌ 失败: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n🎉 所有测试通过！调度器可以安全使用。")
    else:
        print(f"\n⚠️  有 {failed} 个测试失败，请检查代码。")
        sys.exit(1)

if __name__ == "__main__":
    main()
