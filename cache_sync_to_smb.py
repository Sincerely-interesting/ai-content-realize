"""
缓存自动导出与SMB同步脚本 v1.0
功能：
1. 监控JSON缓存文件变化（基于修改时间戳）
2. 安全读取（处理读写冲突）
3. 转换为Excel格式
4. 通过SMB协议同步到共享盘

设计原则：
- 原子性：临时文件 + 原子重命名
- 容错性：重试机制 + 异常隔离
- 安全性：文件锁 + 数据校验
- 可观测性：详细日志 + 状态报告
"""

import os
import sys
import json
import time
import shutil
import hashlib
import logging
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import tempfile

# Windows文件锁支持
if os.name == 'nt':
    import msvcrt
else:
    import fcntl  # Unix文件锁

# ==================== 配置区 ====================

# 缓存文件路径
CACHE_FILE = 'labeling_200_cache.json'

# Excel输出路径（本地临时）
LOCAL_EXCEL_DIR = 'excel_exports'

# SMB共享盘配置
SMB_SHARE_PATH = r'\\192.168.2.242\大数据中心'
SMB_FILENAME = 'minimax_mcp_multimodal_results_latest.xlsx'

# 监控间隔（秒）
POLL_INTERVAL = 60  # 1分钟

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒

# 日志配置
LOG_FILE = 'cache_sync.log'

# ==================== 日志配置 ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class FileLock:
    """
    跨平台文件锁实现
    
    Windows: 使用 msvcrt.locking
    Unix/Linux: 使用 fcntl.flock
    """
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.lockfile = f"{filepath}.lock"
        self.fd = None
    
    def acquire(self, timeout: int = 10) -> bool:
        """
        获取文件锁
        
        Args:
            timeout: 超时时间（秒）
        
        Returns:
            bool: 是否成功获取锁
        """
        try:
            self.fd = open(self.lockfile, 'w')
            
            if os.name == 'nt':
                # Windows: 使用 msvcrt
                start_time = time.time()
                while True:
                    try:
                        # 锁定整个文件
                        msvcrt.locking(self.fd.fileno(), msvcrt.LK_NBLCK, 1)
                        return True
                    except OSError:
                        if time.time() - start_time > timeout:
                            logger.warning(f"⚠️  获取文件锁超时: {self.lockfile}")
                            return False
                        time.sleep(0.1)
            else:
                # Unix: 使用 fcntl
                fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX)
                return True
                
        except Exception as e:
            logger.error(f"❌ 获取文件锁失败: {e}")
            return False
    
    def release(self):
        """释放文件锁"""
        try:
            if self.fd:
                if os.name == 'nt':
                    try:
                        msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)
                    except:
                        pass
                else:
                    fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
                self.fd.close()
                
                # 删除锁文件
                if os.path.exists(self.lockfile):
                    try:
                        os.remove(self.lockfile)
                    except:
                        pass
        except Exception as e:
            logger.error(f"❌ 释放文件锁失败: {e}")
        finally:
            self.fd = None


class CacheSyncMonitor:
    """
    缓存同步监控器
    
    核心特性：
    1. 基于时间戳的变化检测
    2. 安全的文件读取（避免读写冲突）
    3. 原子性Excel导出
    4. SMB同步重试机制
    """
    
    def __init__(self, cache_file: str, smb_path: str):
        self.cache_file = cache_file
        self.smb_path = smb_path
        self.last_mtime = 0.0
        self.last_hash = ""
        self.sync_count = 0
        self.error_count = 0
        
        # 创建本地导出目录
        os.makedirs(LOCAL_EXCEL_DIR, exist_ok=True)
        
        # 验证SMB路径
        self._verify_smb_path()
    
    def _verify_smb_path(self):
        """验证SMB共享路径是否可访问"""
        try:
            if not os.path.exists(self.smb_path):
                logger.warning(f"⚠️  SMB共享路径不存在: {self.smb_path}")
                logger.warning("   请确保网络连接正常且共享盘已挂载")
                return False
            
            # 测试写入权限
            test_file = os.path.join(self.smb_path, '.sync_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            
            logger.info(f"✅ SMB共享路径验证成功: {self.smb_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ SMB共享路径不可用: {e}")
            logger.error("   脚本将继续运行，但SMB同步会失败")
            return False
    
    def _calculate_file_hash(self, filepath: str) -> str:
        """
        计算文件MD5哈希值（用于检测真实内容变化）
        
        Args:
            filepath: 文件路径
        
        Returns:
            str: MD5哈希值
        """
        try:
            md5 = hashlib.md5()
            with open(filepath, 'rb') as f:
                # 只读取前1KB用于快速校验
                chunk = f.read(1024)
                md5.update(chunk)
            return md5.hexdigest()
        except Exception as e:
            logger.error(f"❌ 计算文件哈希失败: {e}")
            return ""
    
    def _safe_read_json(self, filepath: str) -> Optional[Dict]:
        """
        安全读取JSON文件（处理读写冲突）
        
        策略：
        1. 获取文件锁
        2. 读取到内存
        3. 立即释放锁
        4. 数据校验
        
        Args:
            filepath: JSON文件路径
        
        Returns:
            Optional[Dict]: 解析后的数据，失败返回None
        """
        lock = FileLock(filepath)
        
        for attempt in range(MAX_RETRIES):
            try:
                # 尝试获取锁
                if not lock.acquire(timeout=5):
                    logger.warning(f"⚠️  读取JSON文件超时 (尝试 {attempt + 1}/{MAX_RETRIES})")
                    time.sleep(RETRY_DELAY)
                    continue
                
                # 读取文件
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 立即释放锁
                lock.release()
                
                # 数据校验
                if not isinstance(data, dict):
                    logger.error(f"❌ JSON数据格式错误: 期望dict，实际{type(data)}")
                    return None
                
                logger.info(f"✅ 安全读取JSON成功: {len(data)} 条记录")
                return data
                
            except json.JSONDecodeError as e:
                lock.release()
                logger.error(f"❌ JSON解析失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
                logger.warning("   可能文件正在写入中，稍后重试...")
                time.sleep(RETRY_DELAY)
                
            except Exception as e:
                lock.release()
                logger.error(f"❌ 读取JSON失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
                time.sleep(RETRY_DELAY)
        
        logger.error(f"❌ 读取JSON失败，已达最大重试次数")
        return None
    
    def _export_to_excel(self, data: Dict, output_path: str) -> bool:
        """
        将JSON缓存导出为Excel格式
        
        Excel格式：
        - daterange: 导出日期
        - dynamiclink: 素材ID
        - 制作组类型（细分标签）: 标签
        - 判定依据: 判定理由
        - 是否视频: 布尔值
        - 帧数: 整数
        - 是否有音频: 布尔值
        - 语音文本长度: 整数
        - 语音文本预览: 字符串
        
        Args:
            data: JSON缓存数据
            output_path: Excel输出路径
        
        Returns:
            bool: 是否成功
        """
        try:
            # 转换为DataFrame
            results = []
            for mid, item_data in data.items():
                info = item_data.get('info', {})
                label = item_data.get('label', '未知')
                reason = item_data.get('reason', '')
                time_str = item_data.get('time', '')
                skipped = item_data.get('skipped', False)
                
                # 判断是否为失败记录
                is_failed = (
                    '失败' in label or 
                    '异常' in label or 
                    '处理异常' in reason or 
                    '解析异常' in reason or
                    label == '其他' and ('错误' in reason or '异常' in reason)
                )
                
                status = '跳过' if skipped else ('失败' if is_failed else '成功')
                
                # 提取打标时间（从缓存的time字段）
                label_date = '未知'
                if time_str:
                    try:
                        # 2026-04-24T17:46:45.078734 -> 2026-04-24
                        label_date = time_str.split('T')[0]
                    except:
                        label_date = time_str[:10] if len(time_str) >= 10 else time_str
                
                results.append({
                    'daterange': label_date,  # 使用打标时间，而非导出时间
                    'dynamiclink': mid,
                    '制作组类型（细分标签）': label,
                    '判定依据（结合业务规则判断标准）': reason,
                    '状态': status,
                    '是否视频': info.get('frames_count', 0) > 0,
                    '帧数': info.get('frames_count', 0),
                    '是否有音频': info.get('has_audio', False),
                    '语音文本长度': info.get('transcript_length', 0),
                    '语音文本预览': str(info.get('transcript_preview', ''))[:100]
                })
            
            if not results:
                logger.warning("⚠️  无数据可导出")
                return False
            
            df = pd.DataFrame(results)
            
            # 原子性写入：先在临时目录创建.xlsx文件，再移动到目标位置
            # 使用 tempfile 确保原子性
            dir_name = os.path.dirname(output_path) or '.'
            fd, temp_path = tempfile.mkstemp(suffix='.xlsx', dir=dir_name)
            os.close(fd)  # 立即关闭文件描述符
            
            try:
                df.to_excel(temp_path, index=False, engine='openpyxl')
                
                # 原子重命名
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(temp_path, output_path)
            except Exception:
                # 清理临时文件
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
            
            logger.info(f"✅ Excel导出成功: {output_path} ({len(results)} 条)")
            return True
            
        except Exception as e:
            logger.error(f"❌ Excel导出失败: {e}")
            return False
    
    def _copy_to_smb(self, source_path: str) -> bool:
        """
        复制文件到SMB共享盘（带重试机制）
        
        Args:
            source_path: 源文件路径
        
        Returns:
            bool: 是否成功
        """
        smb_file = os.path.join(self.smb_path, SMB_FILENAME)
        
        for attempt in range(MAX_RETRIES):
            try:
                # 检查SMB路径
                if not os.path.exists(self.smb_path):
                    logger.warning(f"⚠️  SMB路径不可达 (尝试 {attempt + 1}/{MAX_RETRIES})")
                    time.sleep(RETRY_DELAY * (attempt + 1))  # 指数退避
                    continue
                
                # 复制到SMB
                shutil.copy2(source_path, smb_file)
                
                # 验证复制
                if os.path.exists(smb_file):
                    src_size = os.path.getsize(source_path)
                    dst_size = os.path.getsize(smb_file)
                    
                    if src_size == dst_size:
                        logger.info(f"✅ SMB同步成功: {smb_file} ({src_size} bytes)")
                        return True
                    else:
                        logger.warning(f"⚠️  文件大小不匹配: 源={src_size}, 目标={dst_size}")
                
                time.sleep(RETRY_DELAY)
                
            except Exception as e:
                logger.error(f"❌ SMB同步失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
                time.sleep(RETRY_DELAY * (attempt + 1))  # 指数退避
        
        logger.error(f"❌ SMB同步失败，已达最大重试次数")
        return False
    
    def check_and_sync(self) -> bool:
        """
        检查缓存文件变化并同步
        
        Returns:
            bool: 是否执行了同步
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(self.cache_file):
                logger.debug(f"⏸️  缓存文件不存在: {self.cache_file}")
                return False
            
            # 获取文件修改时间
            current_mtime = os.path.getmtime(self.cache_file)
            
            # 快速检查：修改时间是否变化
            if current_mtime == self.last_mtime:
                return False
            
            # 深度检查：计算哈希值（避免误判）
            current_hash = self._calculate_file_hash(self.cache_file)
            
            if current_hash == self.last_hash and self.last_hash != "":
                logger.debug("⏸️  文件修改时间变化但内容未变")
                self.last_mtime = current_mtime
                return False
            
            # 文件确实发生变化，执行同步
            logger.info("=" * 80)
            logger.info(f"🔄 检测到缓存文件更新")
            logger.info(f"   修改时间: {datetime.fromtimestamp(current_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"   文件哈希: {current_hash}")
            
            # 1. 安全读取JSON
            data = self._safe_read_json(self.cache_file)
            if data is None:
                logger.error("❌ 跳过同步：JSON读取失败")
                self.error_count += 1
                return False
            
            # 2. 导出到本地Excel
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            local_excel = os.path.join(LOCAL_EXCEL_DIR, f'minimax_results_{timestamp}.xlsx')
            
            if not self._export_to_excel(data, local_excel):
                logger.error("❌ 跳过同步：Excel导出失败")
                self.error_count += 1
                return False
            
            # 3. 同步到SMB
            if not self._copy_to_smb(local_excel):
                logger.warning("⚠️  SMB同步失败，但本地Excel已保存")
                self.error_count += 1
            else:
                self.sync_count += 1
            
            # 更新状态
            self.last_mtime = current_mtime
            self.last_hash = current_hash
            
            logger.info(f"✅ 同步完成 (累计成功: {self.sync_count}, 失败: {self.error_count})")
            logger.info("=" * 80)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 检查同步失败: {e}")
            self.error_count += 1
            return False
    
    def run(self):
        """运行监控循环"""
        logger.info("=" * 80)
        logger.info("🚀 缓存自动导出与SMB同步服务启动")
        logger.info("=" * 80)
        logger.info(f"📂 缓存文件: {os.path.abspath(self.cache_file)}")
        logger.info(f"📁 本地导出: {os.path.abspath(LOCAL_EXCEL_DIR)}")
        logger.info(f"🌐 SMB共享: {self.smb_path}")
        logger.info(f"⏱️  监控间隔: {POLL_INTERVAL} 秒")
        logger.info("=" * 80)
        
        # 初始状态
        if os.path.exists(self.cache_file):
            self.last_mtime = os.path.getmtime(self.cache_file)
            self.last_hash = self._calculate_file_hash(self.cache_file)
            logger.info(f"✅ 初始缓存文件已加载: {len(self.last_hash)} 字符哈希")
        else:
            logger.warning(f"⚠️  缓存文件不存在，等待创建...")
        
        # 监控循环
        try:
            while True:
                self.check_and_sync()
                time.sleep(POLL_INTERVAL)
                
        except KeyboardInterrupt:
            logger.info("\n⏸️  收到停止信号，正在退出...")
        except Exception as e:
            logger.error(f"❌ 监控循环异常: {e}")
            raise
        finally:
            logger.info("=" * 80)
            logger.info("🛑 缓存同步服务已停止")
            logger.info(f"📊 统计: 成功 {self.sync_count} 次, 失败 {self.error_count} 次")
            logger.info("=" * 80)


def main():
    """主函数"""
    # 检查依赖
    try:
        import pandas
        import openpyxl
    except ImportError as e:
        logger.error(f"❌ 缺少依赖: {e}")
        logger.error("   请运行: pip install pandas openpyxl")
        sys.exit(1)
    
    # 创建监控器
    monitor = CacheSyncMonitor(
        cache_file=CACHE_FILE,
        smb_path=SMB_SHARE_PATH
    )
    
    # 运行监控
    monitor.run()


if __name__ == "__main__":
    main()
