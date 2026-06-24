import os
import base64
import requests
import json
import pandas as pd
from PIL import Image
import io
import glob
from datetime import datetime
import time
import logging
import random
import uuid
from typing import Optional, Tuple, Dict

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('minimax_mcp_v2_labeling.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# MiniMax配置
MINIMAX_API_KEY = os.getenv("MIN_MAX_API_KEY", "").strip().replace('\u200c', '').replace('\u200b', '')
MINIMAX_MODEL = "MiniMax-M2.7"  # 使用M2.7作为主控模型
MINIMAX_API_URL = "https://api.minimaxi.com/v1/chat/completions"  # OpenAI兼容端点
SAMPLE_SIZE = 50  # 抽样50个文件夹

if not MINIMAX_API_KEY:
    logger.error("❌ 错误: 请在.env文件中设置MIN_MAX_API_KEY")
    raise ValueError("MIN_MAX_API_KEY not set")


def encode_image_to_base64(image_path: str, max_size: int = 1024, quality: int = 85) -> Optional[str]:
    """
    编码图片为base64 (简化版)
    """
    try:
        if not os.path.exists(image_path):
            return None
        
        file_size = os.path.getsize(image_path)
        if file_size == 0 or file_size < 100:
            return None
        
        img = Image.open(image_path)
        img.verify()
        img = Image.open(image_path)
        img.load()
        
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        
        if max(img.size) > max_size:
            ratio = max_size / float(max(img.size))
            new_size = tuple([int(x * ratio) for x in img.size])
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=quality)
        encoded = base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
        
        return encoded
        
    except Exception as e:
        logger.error(f"图片编码失败 {image_path}: {e}")
        return None


def understand_image_via_mcp(image_path: str, prompt: str) -> Optional[str]:
    """
    通过MCP understand_image工具分析图片
    
    根据MiniMax文档，MCP工具通过Token Plan API调用
    这里使用直接API调用方式（模拟MCP工具调用）
    """
    request_id = str(uuid.uuid4())[:8]
    
    # 编码图片
    encoded = encode_image_to_base64(image_path)
    if not encoded:
        logger.error(f"❌ [REQ-{request_id}] 图片编码失败")
        return None
    
    # 构建MCP工具调用
    # 根据MiniMax MCP文档，understand_image需要prompt和image_url
    # 这里使用base64 data URL格式
    image_data_url = f"data:image/jpeg;base64,{encoded}"
    
    # MCP工具定义
    tools = [
        {
            "type": "function",
            "function": {
                "name": "understand_image",
                "description": "对图片进行理解和分析",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "对图片的提问或分析要求"
                        },
                        "image_url": {
                            "type": "string",
                            "description": "图片来源，支持HTTP/HTTPS URL或本地文件路径或base64 data URL"
                        }
                    },
                    "required": ["prompt", "image_url"]
                }
            }
        }
    ]
    
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MINIMAX_MODEL,
        "max_tokens": 2048,
        "tools": tools,
        "tool_choice": {
            "type": "function",
            "function": {"name": "understand_image"}
        },
        "messages": [
            {
                "role": "user",
                "content": f"请使用understand_image工具分析这张图片：{image_data_url}\n\n分析要求：{prompt}"
            }
        ]
    }
    
    try:
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=120)
        
        if resp.status_code != 200:
            logger.error(f"❌ [REQ-{request_id}] API错误 ({resp.status_code}): {resp.text[:300]}")
            return None
        
        data = resp.json()
        
        # 检查是否有工具调用
        if 'choices' in data and len(data['choices']) > 0:
            message = data['choices'][0].get('message', {})
            
            # 如果模型直接返回了内容（没有调用工具）
            if message.get('content'):
                logger.info(f"✅ [REQ-{request_id}] 模型直接返回结果")
                return message['content']
            
            # 如果有工具调用
            if message.get('tool_calls'):
                logger.info(f"🔧 [REQ-{request_id}] 模型请求调用工具")
                # 这里需要执行工具调用并返回结果
                # 但MiniMax的MCP工具是由服务器端执行的
                # 所以我们只需要返回模型的响应
                return message.get('content', '工具调用已执行')
        
        return None
        
    except Exception as e:
        logger.error(f"💥 [REQ-{request_id}] MCP工具调用异常: {e}", exc_info=True)
        return None


def understand_image_direct(image_path: str, prompt: str) -> Optional[str]:
    """
    直接调用MiniMax视觉理解API（不通过MCP）
    
    根据最新文档，MiniMax的understand_image是MCP工具
    但我们可以通过M2.7模型的多模态能力直接分析图片
    """
    request_id = str(uuid.uuid4())[:8]
    
    # 编码图片
    encoded = encode_image_to_base64(image_path)
    if not encoded:
        logger.error(f"❌ [REQ-{request_id}] 图片编码失败")
        return None
    
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 使用OpenAI兼容格式直接传入图片
    payload = {
        "model": MINIMAX_MODEL,
        "max_tokens": 2048,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded}",
                            "detail": "high"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    }
    
    try:
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=120)
        
        if resp.status_code != 200:
            logger.error(f"❌ [REQ-{request_id}] API错误 ({resp.status_code}): {resp.text[:300]}")
            return None
        
        data = resp.json()
        
        # 解析响应
        if 'choices' in data and len(data['choices']) > 0:
            content = data['choices'][0].get('message', {}).get('content', '')
            logger.info(f"✅ [REQ-{request_id}] 视觉分析成功")
            return content
        
        return None
        
    except Exception as e:
        logger.error(f"💥 [REQ-{request_id}] API调用异常: {e}", exc_info=True)
        return None


def get_label_and_reason(media_path: str) -> Tuple[str, str]:
    """
    获取图片标签和原因
    """
    prompt = """
    你是一位专业的时尚与运动产品分析师。请分析以下图片，并将其归类为以下精准标签之一。
    
    ### 标签分类及判定标准：

    1. **性能测试**
       - 人物在实际运动场景中穿着产品，并有明显的运动行为
       - 包含对产品"科技点"的讲解
       - 排除：单纯行走展示

    2. **明星穿搭**
       - 识别到知名明星出镜
       - 专业资讯扒图、街拍、活动现场
       - 明星同款分享

    3. **穿搭精选 (核心)-穿搭种草**
       - 全身图：头部 + 躯干 + 脚部都清晰识别
       - 人物占比 > 50%
       - 整体服装搭配风格展示

    4. **穿搭精选 (次要)-穿搭种草**
       - 半身图：头部 + 躯干，未识别到脚部
       - 中近景构图

    5. **单品展示 (剔除出穿搭)-上脚**
       - 局部图：仅膝盖以下及脚部
       - 画面中心集中在鞋部

    6. **创意静物**
       - 无人物出镜
       - 艺术置景、氛围灯光或AI渲染

    7. **静物展示**
       - 纯底拍摄、平铺展示
       - 无人物交互

    8. **其他**
       - 不属于以上任何分类

    ### 输出格式要求：
    请输出一个 JSON 格式的结果，包含 'label' 和 'reason' 两个字段。
    'reason' 必须包含三部分（用换行符分隔）：
    1. 场景与行为符合标准
    2. 核心内容符合定义
    3. 排除法分析

    示例：
    {
        "label": "穿搭精选 (核心)-穿搭种草",
        "reason": "场景与行为符合标准：户外街景，达人全身出镜。\\n核心内容符合定义：展示运动鞋与休闲装搭配。\\n排除法分析：无运动测试行为，排除性能测试。"
    }
    """
    
    # 尝试直接调用
    result = understand_image_direct(media_path, prompt)
    
    if not result:
        return "其他", "视觉分析API调用失败"
    
    # 解析JSON
    try:
        # 查找JSON
        json_start = result.find('{')
        json_end = result.rfind('}') + 1
        
        if json_start != -1 and json_end > json_start:
            json_str = result[json_start:json_end]
            data = json.loads(json_str)
            
            label = data.get("label", "其他")
            reason = data.get("reason", "未提供判断理由")
            
            return label, reason
        else:
            return "其他", f"未找到JSON: {result[:200]}"
            
    except json.JSONDecodeError:
        return "其他", f"JSON解析失败: {result[:200]}"
    except Exception as e:
        return "其他", f"解析异常: {str(e)}"


def sample_folders(all_folders: list, sample_size: int) -> list:
    """随机抽样文件夹"""
    if len(all_folders) <= sample_size:
        return all_folders
    
    random.seed(42)  # 可复现
    return random.sample(all_folders, sample_size)


def main():
    logger.info("=" * 60)
    logger.info("🚀 启动 MiniMax MCP 抽样打标任务 (50个文件夹)")
    logger.info(f"📦 模型: {MINIMAX_MODEL}")
    logger.info(f"📊 抽样数量: {SAMPLE_SIZE}")
    logger.info("=" * 60)

    materials_dir = 'downloaded_materials'
    output_file = 'minimax_mcp_sample_50_results.xlsx'
    cache_file = 'minimax_mcp_sample_50_cache.json'

    if not os.path.exists(materials_dir):
        logger.error(f"❌ 素材目录不存在: {materials_dir}")
        return

    # 加载缓存
    cache = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            logger.info(f"✅ 加载缓存: {len(cache)} 条记录")
        except:
            cache = {}

    # 获取所有文件夹
    all_ids = sorted([d for d in os.listdir(materials_dir) if os.path.isdir(os.path.join(materials_dir, d))])
    logger.info(f"📁 总计 {len(all_ids)} 个素材文件夹")
    
    # 抽样
    sampled_ids = sample_folders(all_ids, SAMPLE_SIZE)
    unprocessed = [mid for mid in sampled_ids if mid not in cache]
    
    logger.info(f"📊 抽样 {len(sampled_ids)} 个，已处理 {len(sampled_ids) - len(unprocessed)} 个，待处理 {len(unprocessed)} 个")
    
    if not unprocessed:
        logger.info("✅ 所有抽样素材已处理完成")
        return

    # 统计
    stats = {'success': 0, 'failed': 0, 'total_api_calls': 0, 'errors': []}

    for idx, mid in enumerate(unprocessed, 1):
        path = os.path.join(materials_dir, mid)
        logger.info(f"\n{'='*60}")
        logger.info(f"📝 [{idx}/{len(unprocessed)}] 正在打标: {mid}")
        
        # 查找媒体文件
        imgs = (glob.glob(os.path.join(path, '*.jpg')) + 
                glob.glob(os.path.join(path, '*.jpeg')) + 
                glob.glob(os.path.join(path, '*.png')))
        
        label, reason = "其他", "无有效媒体"
        
        try:
            if imgs:
                logger.info(f"🖼️  找到 {len(imgs)} 张图片，使用: {os.path.basename(imgs[0])}")
                label, reason = get_label_and_reason(imgs[0])
                stats['total_api_calls'] += 1
                
                if label != "其他" or "成功" in reason or "识别" in reason:
                    stats['success'] += 1
                    logger.info(f"✅ 打标成功: {label}")
                else:
                    stats['failed'] += 1
                    stats['errors'].append({'id': mid, 'label': label, 'reason': reason[:200]})
                    logger.warning(f"❌ 打标失败: {reason[:100]}")
            else:
                logger.warning(f"⚠️ 未找到图片")
                
        except Exception as e:
            logger.error(f"💥 处理异常: {e}", exc_info=True)
            label, reason = "其他", f"处理异常: {str(e)}"
            stats['failed'] += 1

        # 保存缓存
        cache[mid] = {
            'label': label, 
            'reason': reason, 
            'time': datetime.now().isoformat()
        }
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.warning(f"⚠️ 缓存保存失败: {e}")
        
        # API间隔
        if idx < len(unprocessed):
            time.sleep(1.5)
        
        # 进度报告
        if idx % 10 == 0:
            success_rate = stats['success'] / idx * 100
            logger.info(f"\n{'='*60}")
            logger.info(f"📈 进度报告 [{idx}/{len(unprocessed)}]")
            logger.info(f"✅ 成功: {stats['success']} | ❌ 失败: {stats['failed']} | 成功率: {success_rate:.1f}%")
            logger.info(f"{'='*60}")

    # 导出结果
    results = []
    for mid, data in cache.items():
        results.append({
            'daterange': datetime.now().strftime('%Y-%m-%d'),
            'dynamiclink': mid,
            '制作组类型（细分标签）': data['label'],
            '判定依据（结合业务规则判断标准）': data['reason']
        })
    
    if results:
        try:
            df = pd.DataFrame(results)
            df.to_excel(output_file, index=False)
            logger.info(f"\n✅ 导出成功: {output_file} ({len(results)} 条记录)")
        except Exception as e:
            logger.error(f"❌ 导出 Excel 失败: {e}")
    
    # 最终统计
    logger.info("\n" + "=" * 60)
    logger.info("🎯 抽样打标任务完成 - 最终统计报告")
    logger.info("=" * 60)
    logger.info(f"📊 总素材数: {len(all_ids)}")
    logger.info(f"🎲 抽样数量: {len(sampled_ids)}")
    logger.info(f"🔄 本次处理: {len(unprocessed)}")
    logger.info(f"📞 总 API 调用: {stats['total_api_calls']}")
    logger.info(f"✅ 成功: {stats['success']}")
    logger.info(f"❌ 失败: {stats['failed']}")
    
    if unprocessed:
        success_rate = stats['success'] / len(unprocessed) * 100
        logger.info(f"📈 成功率: {success_rate:.1f}%")
    
    if stats['errors']:
        logger.info(f"\n❌ 失败详情 (前10个):")
        for i, err in enumerate(stats['errors'][:10], 1):
            logger.info(f"  {i}. {err['id']}: {err['reason'][:100]}")
    
    logger.info("\n" + "=" * 60)


if __name__ == "__main__":
    main()
