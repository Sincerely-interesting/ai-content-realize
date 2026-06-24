# -*- coding: utf-8 -*-
"""
生产级自动重启调度器 - v2.0
功能：
1. 自动重启：调度器退出后自动恢复（最多100次）
2. 智能退避：指数退避策略（1分钟→30分钟）
3. 动态切换：根据任务量自动计算最大切换次数
4. 状态持久化：任何时候崩溃都能恢复
5. 配额预测：提前预测配额耗尽，主动切换
6. 断点续传：从上次中断位置继续
"""

import os
import sys
import time
import json
import math
import random
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict

# Load .env file first
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# ==================== 配置区 ====================

# 标签脚本路径
LABELING_SCRIPT = 'minimax_mcp_understand_label_materials.py'
CACHE_FILE = 'labeling_200_cache.json'
ID_LIST_FILE = 'ids_200_samples.txt'
OUTPUT_FILE = 'labeling_200_results.xlsx'

# API Key 配置
PRIMARY_KEY = os.getenv('MIN_MAX_API_KEY', '')
BACKUP_KEY = os.getenv('MIN_MAX_BACKUP_API_KEY', '')

# 配额配置
QUOTA_LIMIT = 450
QUOTA_WINDOW_HOURS = 5
FRAMES_PER_MATERIAL = 12

# 自动重启配置
MAX_RESTARTS = 100  # 最大重启次数
BACKOFF_BASE = 60  # 退避基数（秒）
BACKOFF_MAX = 1800  # 最大退避时间（30分钟）
SAFETY_MARGIN = 50  # 配额安全边界

# 状态文件
STATE_FILE = 'scheduler_state.json'

# ==================== 日志配置 ====================

LOG_FILE = 'auto_restart_scheduler.log'

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ==================== 状态持久化 ====================

class SchedulerState:
    """调度器状态持久化管理"""
    
    def __init__(self):
        self.state = {
            'version': '2.0',
            'start_time': datetime.now().isoformat(),
            'last_update': datetime.now().isoformat(),
            'total_processed': 0,
            'total_failed': 0,
            'restart_count': 0,
            'switch_count': 0,
            'current_material_id': None,
            'status': 'initializing',  # initializing, running, waiting, completed, error
            'last_error': None,
            'last_error_time': None,
            'cache_file': CACHE_FILE,
            'quota_usage': {
                'primary_key': {
                    'calls': 0,
                    'window_start': datetime.now().isoformat(),
                    'last_switch': None
                },
                'backup_key': {
                    'calls': 0,
                    'window_start': datetime.now().isoformat(),
                    'last_switch': None
                }
            }
        }
    
    def load(self) -> bool:
        """加载状态"""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    loaded_state = json.load(f)
                
                # 合并状态（保留新版本字段）
                self.state.update(loaded_state)
                logger.info(f"✅ 恢复状态: 已处理 {self.state['total_processed']} 个, "
                           f"重启 {self.state['restart_count']} 次")
                return True
            except Exception as e:
                logger.warning(f"⚠️ 状态文件加载失败: {e}")
                return False
        return False
    
    def save(self):
        """保存状态"""
        self.state['last_update'] = datetime.now().isoformat()
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"❌ 状态保存失败: {e}")
    
    def update(self, **kwargs):
        """更新状态"""
        self.state.update(kwargs)
        self.save()
    
    def increment(self, key: str, value: int = 1):
        """递增计数器"""
        if key in self.state:
            self.state[key] += value
            self.save()
    
    def get_status(self) -> Dict:
        """获取状态"""
        return self.state.copy()


# ==================== 配额监控器 ====================

class QuotaMonitor:
    """API配额监控器（增强版）"""
    
    def __init__(self, api_key: str, key_name: str):
        self.api_key = api_key
        self.key_name = key_name
        self.call_count = 0
        self.window_start = datetime.now()
        self.last_error_time = None
        self.consecutive_2056 = 0
        self.is_exhausted = False
        self.call_history = []  # 记录调用时间
    
    def record_call(self):
        """记录一次API调用"""
        self.call_count += 1
        self.consecutive_2056 = 0
        self.call_history.append(datetime.now())
        
        # 清理5小时前的记录
        cutoff = datetime.now() - timedelta(hours=QUOTA_WINDOW_HOURS)
        self.call_history = [t for t in self.call_history if t > cutoff]
    
    def record_error_2056(self):
        """记录Error 2056"""
        self.consecutive_2056 += 1
        self.last_error_time = datetime.now()
        logger.warning(f"⚠️  {self.key_name} 连续2056错误: {self.consecutive_2056}/3")
    
    def get_remaining_quota(self) -> int:
        """计算剩余配额（基于滚动窗口）"""
        now = datetime.now()
        cutoff = now - timedelta(hours=QUOTA_WINDOW_HOURS)
        
        # 统计窗口内的调用次数
        recent_calls = sum(1 for t in self.call_history if t > cutoff)
        remaining = max(0, QUOTA_LIMIT - recent_calls)
        
        # 如果窗口已完全重置
        if recent_calls == 0 and self.call_count > 0:
            self.window_start = now
            self.call_count = 0
            self.call_history = []
            self.is_exhausted = False
            return QUOTA_LIMIT
        
        return remaining
    
    def predict_exhaustion_time(self, call_rate: float) -> Optional[timedelta]:
        """预测配额耗尽时间
        
        Args:
            call_rate: 调用速率（次/分钟）
        """
        remaining = self.get_remaining_quota()
        if remaining <= 0:
            return timedelta(seconds=0)
        
        if call_rate <= 0:
            return None
        
        minutes_left = remaining / call_rate
        return timedelta(minutes=minutes_left)
    
    def should_prepare_switch(self) -> bool:
        """是否应该准备切换（剩余配额低于安全边界）"""
        return self.get_remaining_quota() <= SAFETY_MARGIN
    
    def time_until_reset(self) -> Optional[timedelta]:
        """计算距离配额重置的时间"""
        if not self.is_exhausted:
            return None
        
        now = datetime.now()
        elapsed = (now - self.window_start).total_seconds()
        window_seconds = QUOTA_WINDOW_HOURS * 3600
        
        if elapsed >= window_seconds:
            return timedelta(seconds=0)
        
        return timedelta(seconds=window_seconds - elapsed)
    
    def get_call_rate(self) -> float:
        """计算最近10分钟的平均调用速率（次/分钟）"""
        now = datetime.now()
        cutoff = now - timedelta(minutes=10)
        
        recent_calls = sum(1 for t in self.call_history if t > cutoff)
        return recent_calls / 10.0
    
    def __str__(self):
        remaining = self.get_remaining_quota()
        rate = self.get_call_rate()
        return f"{self.key_name} [剩余: {remaining}/{QUOTA_LIMIT}, 速率: {rate:.1f}次/分, 错误: {self.consecutive_2056}]"


# ==================== 自动重启调度器 ====================

class AutoRestartScheduler:
    """生产级自动重启调度器"""
    
    def __init__(self):
        self.state = SchedulerState()
        self.primary_monitor = QuotaMonitor(PRIMARY_KEY, "MIN_MAX_API_KEY")
        self.backup_monitor = QuotaMonitor(BACKUP_KEY, "MIN_MAX_BACKUP_API_KEY")
        self.current_key = BACKUP_KEY
        self.current_monitor = self.backup_monitor
        self.process = None
        self.max_switches = 50  # 会被动态计算覆盖
        
        # 加载之前的状态
        self.state.load()
    
    def calculate_dynamic_max_switches(self) -> int:
        """动态计算最大切换次数"""
        try:
            # 读取缓存获取已处理数量
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                processed = len(cache)
            else:
                processed = 0
            
            # 读取ID列表获取总数
            with open(ID_LIST_FILE, 'r', encoding='utf-8') as f:
                total_ids = len([line for line in f.read().splitlines() if line.strip()])
            
            remaining = total_ids - processed
            if remaining <= 0:
                return 10  # 已经完成，只需少量切换
            
            # 计算需要的切换次数
            total_calls_needed = remaining * FRAMES_PER_MATERIAL
            calls_per_cycle = QUOTA_LIMIT * 2  # 两个Key
            cycles_needed = math.ceil(total_calls_needed / calls_per_cycle)
            
            # 每个周期2次切换 + 20%缓冲
            max_switches = cycles_needed * 2 + max(10, int(cycles_needed * 0.2))
            
            logger.info(f"📊 动态计算切换上限:")
            logger.info(f"   总数: {total_ids}, 已处理: {processed}, 剩余: {remaining}")
            logger.info(f"   预计API调用: {total_calls_needed}")
            logger.info(f"   需要周期: {cycles_needed}")
            logger.info(f"   最大切换: {max_switches}")
            
            return max_switches
            
        except Exception as e:
            logger.warning(f"⚠️ 计算切换上限失败，使用默认值: {e}")
            return 50
    
    def update_env_file(self, api_key: str):
        """更新.env文件"""
        env_file = Path('.env')
        if not env_file.exists():
            logger.error("❌ .env 文件不存在")
            return False
        
        with open(env_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('MIN_MAX_API_KEY='):
                lines[i] = f"MIN_MAX_API_KEY={api_key}\n"
                updated = True
                break
        
        if not updated:
            logger.error("❌ 未找到 MIN_MAX_API_KEY 配置行")
            return False
        
        with open(env_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        
        logger.info(f"✅ .env 文件已更新")
        return True
    
    def start_labeling(self) -> Optional[subprocess.Popen]:
        """启动打标进程"""
        self.state.update(status='running')
        
        logger.info("=" * 80)
        logger.info(f"🚀 启动打标任务 (重启#{self.state.state['restart_count']})")
        logger.info(f"🔑 当前使用: {self.current_monitor.key_name}")
        logger.info(f"📊 配额状态: {self.current_monitor}")
        logger.info("=" * 80)
        
        cmd = [
            sys.executable,
            LABELING_SCRIPT,
            '--id-list', ID_LIST_FILE,
            '--cache-file', CACHE_FILE,
            '--output-file', OUTPUT_FILE
        ]
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                bufsize=1
            )
            return self.process
        except Exception as e:
            logger.error(f"❌ 启动打标进程失败: {e}")
            return None
    
    def monitor_labeling_output(self, process: subprocess.Popen) -> str:
        """监控打标进程输出"""
        processed_count = 0
        
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            
            logger.info(line)
            
            # 记录成功调用
            if '✅' in line and '帧' in line and '其他' not in line:
                self.current_monitor.record_call()
            
            # 更新进度
            elif '正在打标' in line:
                processed_count += 1
                self.state.update(current_material_id=line.split(':')[-1].strip())
        
        # 等待进程结束
        return_code = process.wait()
        
        if return_code == 0:
            logger.info("✅ 打标进程正常结束")
            return 'completed'
        elif return_code == 2:
            logger.error("🚫 打标进程因Error 2056退出（配额耗尽）")
            return 'need_switch'
        else:
            logger.error(f"❌ 打标进程异常退出 (code={return_code})")
            return 'error'
    
    def switch_api_key(self):
        """切换API Key"""
        logger.info("=" * 80)
        logger.info("🔄 开始切换API Key...")
        logger.info("=" * 80)
        
        # 停止当前进程
        if self.process:
            logger.info("⏸️  停止当前打标进程...")
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except:
                self.process.kill()
            logger.info("✅ 打标进程已停止")
        
        # 切换到另一个Key
        if self.current_key == BACKUP_KEY:
            logger.info("🔑 切换到 MIN_MAX_API_KEY")
            self.wait_for_quota_reset(self.primary_monitor)
            self.current_key = PRIMARY_KEY
            self.current_monitor = self.primary_monitor
        else:
            logger.info("🔑 切换到 MIN_MAX_BACKUP_API_KEY")
            self.wait_for_quota_reset(self.backup_monitor)
            self.current_key = BACKUP_KEY
            self.current_monitor = self.backup_monitor
        
        # 更新.env
        self.update_env_file(self.current_key)
        
        # 更新状态
        self.state.increment('switch_count')
        self.state.update(last_switch_time=datetime.now().isoformat())
        
        logger.info(f"✅ Key切换完成: {self.current_monitor}")
        logger.info("=" * 80)
    
    def wait_for_quota_reset(self, monitor: QuotaMonitor):
        """等待配额重置"""
        while True:
            remaining = monitor.get_remaining_quota()
            
            if remaining > 0:
                logger.info(f"✅ {monitor.key_name} 配额已重置 (剩余: {remaining})")
                monitor.is_exhausted = False
                break
            
            reset_time = monitor.time_until_reset()
            if reset_time and reset_time.total_seconds() <= 0:
                logger.info(f"✅ {monitor.key_name} 配额已重置!")
                monitor.is_exhausted = False
                break
            
            # 显示倒计时
            hours, remainder = divmod(int(reset_time.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.info(f"⏳ 等待配额重置: {hours}小时 {minutes}分钟 {seconds}秒")
            
            # 更新状态
            self.state.update(status='waiting')
            
            time.sleep(60)  # 每分钟检查一次
    
    def calculate_backoff(self) -> int:
        """计算指数退避时间"""
        restart_count = self.state.state['restart_count']
        backoff = min(BACKOFF_BASE * (2 ** restart_count), BACKOFF_MAX)
        jitter = random.uniform(0, backoff * 0.1)
        return int(backoff + jitter)
    
    def run_scheduler_once(self) -> str:
        """运行一次调度器（可能多次切换Key）"""
        max_switches = self.calculate_dynamic_max_switches()
        switch_count = 0
        
        while switch_count < max_switches:
            # 启动打标
            process = self.start_labeling()
            if not process:
                return 'error'
            
            # 监控输出
            status = self.monitor_labeling_output(process)
            
            if status == 'completed':
                return 'completed'
            elif status == 'need_switch':
                switch_count += 1
                self.switch_api_key()
                continue
            elif status == 'error':
                return 'error'
        
        logger.warning(f"⚠️ 达到最大切换次数 {max_switches}")
        return 'quota_exhausted_both'
    
    def run_with_auto_restart(self):
        """带自动重启的主循环"""
        logger.info("=" * 80)
        logger.info("🎯 生产级自动重启调度器 v2.0 启动")
        logger.info("=" * 80)
        logger.info(f"📦 标签脚本: {LABELING_SCRIPT}")
        logger.info(f"📋 ID列表: {ID_LIST_FILE}")
        logger.info(f"💾 缓存文件: {CACHE_FILE}")
        logger.info(f"🔄 最大重启次数: {MAX_RESTARTS}")
        logger.info(f"⚡ 退避策略: {BACKOFF_BASE}秒 → {BACKOFF_MAX}秒")
        logger.info("=" * 80)
        
        # 初始状态
        logger.info(f"\n📊 初始配额状态:")
        logger.info(f"   {self.primary_monitor}")
        logger.info(f"   {self.backup_monitor}")
        
        while self.state.state['restart_count'] < MAX_RESTARTS:
            try:
                restart_count = self.state.state['restart_count']
                self.state.increment('restart_count')
                
                logger.info(f"\n{'='*80}")
                logger.info(f"🔄 第 {restart_count + 1} 次启动 (最大{MAX_RESTARTS})")
                logger.info(f"{'='*80}")
                
                # 运行调度器
                status = self.run_scheduler_once()
                
                if status == 'completed':
                    logger.info("\n🎉 任务完成！")
                    self.state.update(status='completed')
                    self.generate_final_report()
                    return
                
                elif status == 'quota_exhausted_both':
                    logger.warning("⚠️ 两个Key配额都已耗尽，等待重置...")
                    self.state.update(status='waiting')
                    
                    # 等待任意一个Key重置
                    wait_time = self.wait_for_any_key_reset()
                    logger.info(f"💤 等待{wait_time}秒后重启...")
                    time.sleep(wait_time)
                    continue
                
                elif status == 'error':
                    logger.error("❌ 调度器异常，准备重启...")
                    self.state.update(
                        status='error',
                        last_error='Process exited with error code',
                        last_error_time=datetime.now().isoformat()
                    )
                    
                    # 指数退避
                    backoff = self.calculate_backoff()
                    hours, remainder = divmod(backoff, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    logger.warning(f"⏳ {hours}小时{minutes}分钟{seconds}秒后重启...")
                    
                    self.state.update(status='waiting')
                    time.sleep(backoff)
                    continue
            
            except KeyboardInterrupt:
                logger.info("\n⏸️  收到用户中断信号")
                self.state.update(status='stopped_by_user')
                logger.info("✅ 状态已保存，可以稍后继续")
                return
            
            except Exception as e:
                logger.error(f"❌ 未预期异常: {e}", exc_info=True)
                self.state.update(
                    status='error',
                    last_error=str(e),
                    last_error_time=datetime.now().isoformat()
                )
                
                backoff = self.calculate_backoff()
                logger.info(f"💤 {backoff}秒后重启...")
                time.sleep(backoff)
                continue
        
        logger.error(f"\n❌ 达到最大重启次数 {MAX_RESTARTS}，停止调度")
        self.state.update(status='max_restarts_reached')
    
    def wait_for_any_key_reset(self) -> int:
        """等待任意一个Key的配额重置，返回等待时间（秒）"""
        while True:
            primary_remaining = self.primary_monitor.get_remaining_quota()
            backup_remaining = self.backup_monitor.get_remaining_quota()
            
            if primary_remaining > 50:
                logger.info(f"✅ MIN_MAX_API_KEY 已重置 (剩余: {primary_remaining})")
                self.current_key = PRIMARY_KEY
                self.current_monitor = self.primary_monitor
                return 0
            
            if backup_remaining > 50:
                logger.info(f"✅ MIN_MAX_BACKUP_API_KEY 已重置 (剩余: {backup_remaining})")
                self.current_key = BACKUP_KEY
                self.current_monitor = self.backup_monitor
                return 0
            
            # 计算最近的重置时间
            primary_reset = self.primary_monitor.time_until_reset()
            backup_reset = self.backup_monitor.time_until_reset()
            
            wait_times = []
            if primary_reset:
                wait_times.append(primary_reset.total_seconds())
            if backup_reset:
                wait_times.append(backup_reset.total_seconds())
            
            if not wait_times:
                return 300  # 默认等待5分钟
            
            min_wait = min(wait_times)
            hours, remainder = divmod(int(min_wait), 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.info(f"⏳ 等待Key重置: {hours}h {minutes}m {seconds}s")
            
            time.sleep(60)  # 每分钟检查一次
    
    def generate_final_report(self):
        """生成最终报告"""
        logger.info("=" * 80)
        logger.info("📊 最终报告")
        logger.info("=" * 80)
        
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            
            logger.info(f"✅ 总处理素材: {len(cache)}")
            logger.info(f"🔄 重启次数: {self.state.state['restart_count']}")
            logger.info(f"🔑 切换次数: {self.state.state['switch_count']}")
            logger.info(f"⏱️  运行时间: {self.state.state['start_time']} → {datetime.now().isoformat()}")
            logger.info(f"💾 缓存文件: {CACHE_FILE}")
            logger.info(f"📄 输出文件: {OUTPUT_FILE}")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"❌ 生成报告失败: {e}")


def main():
    """主函数"""
    # 检查API Key
    if not PRIMARY_KEY:
        logger.error("❌ 未设置 MIN_MAX_API_KEY 环境变量")
        sys.exit(1)
    
    if not BACKUP_KEY:
        logger.error("❌ 未设置 MIN_MAX_BACKUP_API_KEY 环境变量")
        sys.exit(1)
    
    # 检查标签脚本
    if not os.path.exists(LABELING_SCRIPT):
        logger.error(f"❌ 标签脚本不存在: {LABELING_SCRIPT}")
        sys.exit(1)
    
    # 检查ID列表
    if not os.path.exists(ID_LIST_FILE):
        logger.error(f"❌ ID列表文件不存在: {ID_LIST_FILE}")
        sys.exit(1)
    
    # 运行自动重启调度器
    scheduler = AutoRestartScheduler()
    
    try:
        scheduler.run_with_auto_restart()
    except KeyboardInterrupt:
        logger.info("\n⏸️  用户手动停止")
        scheduler.state.update(status='stopped_by_user')
    except Exception as e:
        logger.error(f"❌ 调度器异常: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
