"""
从VLM归档的Markdown报告中提取标签并生成Excel
基于新的性能测评判定标准：
- 性能测评 = 人物半身出现拿着鞋子并讲解 + 是视频素材文件夹类型
"""
import os
import re
import json
import pandas as pd
import glob
from datetime import datetime
from typing import Optional, Tuple
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('md_label_extraction.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def extract_label_from_markdown(md_content: str, material_id: str, is_video_folder: bool = False) -> Tuple[str, str]:
    """
    从markdown报告中提取标签和判定依据
    
    Args:
        md_content: markdown文件内容
        material_id: 素材ID
        is_video_folder: 是否为视频素材文件夹
    
    Returns:
        (label, reason) 元组
    """
    label = "其他"
    reason = ""
    
    # 查找标签分类建议（格式：## 4. 标签分类建议\n- **明星穿搭**（首选））
    label_match = re.search(r'## [\d]+\.\s*标签分类建议\s*\n-\s*\*\*(.*?)\*\*（', md_content)
    
    if label_match:
        label = label_match.group(1).strip()
        
        # 提取判断依据（## 5. 判断依据 到 ## 6. 内容摘要之间）
        reason_match = re.search(r'## [\d]+\.\s*判断依据\s*\n(.*?)\n## [\d]+\.\s*内容摘要', md_content, re.DOTALL)
        if reason_match:
            reason = reason_match.group(1).strip()
        
        # 提取内容摘要
        summary_match = re.search(r'## [\d]+\.\s*内容摘要\s*\n(.*?)(?=\n##|$)', md_content, re.DOTALL)
        if summary_match:
            summary = summary_match.group(1).strip()
            reason += f"\n\n内容摘要：{summary}"
    else:
        # 如果没找到标签，尝试从各帧分析中提取最常见的标签
        frame_labels = re.findall(r'判断：\*\*(.*?)\*\*', md_content)
        if frame_labels:
            from collections import Counter
            most_common = Counter(frame_labels).most_common(1)[0][0]
            label = most_common
            reason = f"从{len(frame_labels)}帧分析中提取的最常见标签"
    
    # 应用新的性能测评判定标准（二次校验）
    if is_video_folder:
        # 检查是否符合性能测评新标准
        has_person_half_body = bool(re.search(r'人物.*半身|上半身.*可见|人物出镜', md_content))
        has_hold_shoe_explain = bool(re.search(r'手持.*鞋|拿着.*鞋|讲解|口播|产品展示', md_content))
        
        # 如果VLM判定为性能测评，但素材不符合新标准，则降级
        if label == "性能测评" and not (has_person_half_body and has_hold_shoe_explain):
            logger.warning(f"⚠️  {material_id}: VLM判定为性能测评，但不符合新标准（人物半身+持鞋讲解），降级为穿搭/静物")
            # 根据内容重新判定
            if has_person_half_body:
                label = "穿搭精选 (次要)-穿搭种草"
                reason += "\n\n【系统校正】原判定为性能测评，但缺少持鞋讲解特征，校正为穿搭精选。"
            else:
                label = "静物展示"
                reason += "\n\n【系统校正】原判定为性能测评，但无人物出镜，校正为静物展示。"
    else:
        # 图片素材文件夹，不可能是性能测评
        if label == "性能测评":
            logger.warning(f"⚠️  {material_id}: 图片素材文件夹，排除性能测评，降级为其他标签")
            label = "其他"
            reason += "\n\n【系统校正】图片素材文件夹，不可能是性能测评，校正为其他。"
    
    return label, reason


def check_is_video_folder(material_id: str, materials_dir: str = "downloaded_materials") -> bool:
    """检查素材文件夹是否包含视频"""
    folder_path = os.path.join(materials_dir, material_id)
    if not os.path.exists(folder_path):
        return False
    
    # 检查是否有.mp4文件
    mp4_files = glob.glob(os.path.join(folder_path, "*.mp4"))
    return len(mp4_files) > 0


def main():
    """主函数：从markdown报告提取标签并生成Excel"""
    
    # 配置
    md_dir = "material_archives_test"  # markdown报告目录
    materials_dir = "downloaded_materials"  # 素材目录
    output_excel = f"vlm_md_labels_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    # 检查markdown目录
    if not os.path.exists(md_dir):
        logger.error(f"❌ Markdown目录不存在: {md_dir}")
        return
    
    # 获取所有markdown文件
    md_files = sorted(glob.glob(os.path.join(md_dir, "*_report.md")))
    logger.info(f"📁 找到 {len(md_files)} 个markdown报告")
    
    if not md_files:
        logger.warning("⚠️  未找到任何markdown报告，请先运行 vlm_material_archiver.py")
        return
    
    # 提取标签
    results = []
    success_count = 0
    fail_count = 0
    
    for md_file in md_files:
        # 提取素材ID
        filename = os.path.basename(md_file)
        material_id = filename.replace("_report.md", "")
        
        logger.info(f"\n📝 处理: {material_id}")
        
        # 读取markdown
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                md_content = f.read()
        except Exception as e:
            logger.error(f"❌ 读取失败: {e}")
            fail_count += 1
            continue
        
        # 检查是否为视频素材
        is_video = check_is_video_folder(material_id, materials_dir)
        
        # 提取标签
        label, reason = extract_label_from_markdown(md_content, material_id, is_video)
        
        logger.info(f"   ✅ 标签: {label}")
        logger.info(f"   📹 视频素材: {is_video}")
        
        # 添加到结果
        results.append({
            '素材ID': material_id,
            '打标结果': label,
            '判定依据': reason,
            '素材类型': '视频' if is_video else '图片',
            'markdown报告': md_file
        })
        
        success_count += 1
    
    # 生成Excel
    if results:
        df = pd.DataFrame(results)
        
        # 保存到Excel
        df.to_excel(output_excel, index=False, engine='openpyxl')
        logger.info(f"\n✅ Excel已生成: {output_excel}")
        logger.info(f"📊 共 {len(df)} 条记录")
        
        # 标签分布统计
        logger.info(f"\n📊 标签分布统计:")
        label_counts = df['打标结果'].value_counts()
        for lbl, count in label_counts.items():
            percentage = count / len(df) * 100
            logger.info(f"  {lbl}: {count} ({percentage:.1f}%)")
        
        # 视频/图片分布
        logger.info(f"\n📹 素材类型分布:")
        type_counts = df['素材类型'].value_counts()
        for typ, count in type_counts.items():
            percentage = count / len(df) * 100
            logger.info(f"  {typ}: {count} ({percentage:.1f}%)")
        
        # 同步到缓存（可选）
        cache_file = 'vlm_md_label_cache.json'
        cache = {}
        for row in results:
            cache[row['素材ID']] = {
                'label': row['打标结果'],
                'reason': row['判定依据'],
                'time': datetime.now().isoformat(),
                'is_video': row['素材类型'] == '视频'
            }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.info(f"\n💾 缓存已保存: {cache_file}")
        
    else:
        logger.error("❌ 未提取到任何标签")
    
    # 最终统计
    logger.info(f"\n{'='*60}")
    logger.info(f"🎯 标签提取完成")
    logger.info(f"{'='*60}")
    logger.info(f"✅ 成功: {success_count}")
    logger.info(f"❌ 失败: {fail_count}")
    logger.info(f"📁 输出文件: {output_excel}")
    logger.info(f"{'='*60}")


if __name__ == '__main__':
    main()
