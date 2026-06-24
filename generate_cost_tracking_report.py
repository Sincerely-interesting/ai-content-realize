"""
生成 MiniMax MCP 打标费用追踪报告
基于 cache 文件分析打标耗时和费用
"""

import json
import os
from datetime import datetime
from collections import Counter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, 
    PageBreak, KeepTogether, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 非交互式后端

# 配置
CACHE_FILE = 'minimax_mcp_understand_full_cache.json'
OUTPUT_PDF = 'minimax_mcp_cost_tracking_report.pdf'

# MiniMax MCP understand_image 定价（请根据实际情况调整）
# 假设：每次 understand_image 调用约消耗 X tokens
# 这里使用占位价格，您需要根据实际 Token Plan 价格调整
PRICE_PER_CALL = 0.05  # 每次调用约 0.05 元（示例价格）

def load_cache():
    """加载缓存文件"""
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def analyze_cache(cache):
    """分析缓存数据"""
    # 解析时间戳
    times = []
    labels = []
    skipped_count = 0
    
    for mid, data in cache.items():
        time_str = data['time']
        # 解析 ISO 格式时间
        if '.' in time_str:
            dt = datetime.fromisoformat(time_str)
        else:
            dt = datetime.fromisoformat(time_str)
        times.append(dt)
        labels.append(data['label'])
        
        if data.get('skipped', False):
            skipped_count += 1
    
    # 排序时间
    times.sort()
    
    # 计算总耗时
    total_duration = times[-1] - times[0]
    total_seconds = total_duration.total_seconds()
    total_minutes = total_seconds / 60
    total_hours = total_minutes / 60
    
    # 统计标签分布
    label_counter = Counter(labels)
    
    # 计算平均耗时
    total_processed = len(cache) - skipped_count
    avg_time_per_material = total_seconds / total_processed if total_processed > 0 else 0
    
    # 计算费用
    total_cost = total_processed * PRICE_PER_CALL
    avg_cost_per_material = PRICE_PER_CALL
    
    return {
        'total_materials': len(cache),
        'total_processed': total_processed,
        'skipped': skipped_count,
        'start_time': times[0],
        'end_time': times[-1],
        'total_duration': total_duration,
        'total_seconds': total_seconds,
        'total_minutes': total_minutes,
        'total_hours': total_hours,
        'avg_time_per_material': avg_time_per_material,
        'label_distribution': dict(label_counter),
        'total_cost': total_cost,
        'avg_cost_per_material': avg_cost_per_material,
        'price_per_call': PRICE_PER_CALL
    }

def generate_charts(stats, cache):
    """生成图表"""
    # 1. 标签分布饼图
    fig, ax = plt.subplots(figsize=(10, 8))
    labels = list(stats['label_distribution'].keys())
    sizes = list(stats['label_distribution'].values())
    
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
    
    colors_list = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', 
                   '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E2']
    
    wedges, texts, autotexts = ax.pie(sizes, labels=None, autopct='%1.1f%%',
                                       colors=colors_list, startangle=90,
                                       textprops={'fontsize': 10})
    
    ax.legend(wedges, labels,
              title="标签分类",
              loc="center left",
              bbox_to_anchor=(1, 0, 0.5, 1),
              fontsize=9)
    
    ax.set_title('素材标签分布\n(总计 {} 个)'.format(stats['total_processed']), 
                 fontsize=14, fontweight='bold', pad=20)
    
    plt.tight_layout()
    plt.savefig('chart_label_distribution.png', dpi=150, bbox_inches='tight')
    plt.close()
    
    # 2. 处理时间线图（采样显示）
    fig, ax = plt.subplots(figsize=(14, 6))
    
    # 采样显示（每10个显示一个点，避免过于密集）
    times_list = []
    cache_items = sorted(cache.items(), key=lambda x: x[1]['time'])
    
    for i, (mid, data) in enumerate(cache_items):
        if i % 10 == 0:  # 每10个采样一次
            dt = datetime.fromisoformat(data['time'])
            times_list.append((i, dt))
    
    if times_list:
        start_time = times_list[0][1]
        x_vals = [t[0] for t in times_list]
        y_vals = [(t[1] - start_time).total_seconds() / 60 for t in times_list]
        
        ax.plot(x_vals, y_vals, 'b-', linewidth=1, alpha=0.7)
        ax.scatter(x_vals, y_vals, c='blue', s=10, alpha=0.5)
        
        ax.set_xlabel('处理序号（每10个采样一次）', fontsize=12)
        ax.set_ylabel('累计时间（分钟）', fontsize=12)
        ax.set_title('打标处理时间线\n(总耗时: {:.1f} 分钟)'.format(stats['total_minutes']), 
                     fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('chart_timeline.png', dpi=150, bbox_inches='tight')
        plt.close()
    
    # 3. 标签Top5柱状图
    fig, ax = plt.subplots(figsize=(10, 6))
    
    sorted_labels = sorted(stats['label_distribution'].items(), 
                          key=lambda x: x[1], reverse=True)[:5]
    
    if sorted_labels:
        label_names = [l[0] for l in sorted_labels]
        label_counts = [l[1] for l in sorted_labels]
        
        bars = ax.barh(range(len(label_names)), label_counts, color=colors_list[:5])
        ax.set_yticks(range(len(label_names)))
        ax.set_yticklabels(label_names, fontsize=9)
        ax.invert_yaxis()
        
        # 在柱子上显示数值
        for bar, count in zip(bars, label_counts):
            ax.text(bar.get_width() + 5, bar.get_y() + bar.get_height()/2,
                   str(count), va='center', fontsize=10, fontweight='bold')
        
        ax.set_xlabel('素材数量', fontsize=12)
        ax.set_title('Top 5 标签分布', fontsize=14, fontweight='bold')
        ax.grid(axis='x', alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('chart_top5_labels.png', dpi=150, bbox_inches='tight')
        plt.close()

def create_pdf(stats):
    """创建PDF报告"""
    # 注册中文字体
    font_paths = [
        'C:/Windows/Fonts/msyh.ttc',  # Microsoft YaHei
        'C:/Windows/Fonts/simhei.ttf',  # SimHei
        'C:/Windows/Fonts/msjh.ttc',  # Microsoft JhengHei
    ]
    
    registered = False
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont('ChineseFont', font_path))
                registered = True
                print(f"✅ 成功注册字体: {font_path}")
                break
            except Exception as e:
                print(f"⚠️ 字体注册失败 {font_path}: {e}")
                continue
    
    if not registered:
        print("⚠️ 未找到中文字体，使用默认字体")
    
    # 创建文档
    doc = SimpleDocTemplate(
        OUTPUT_PDF,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    
    # 样式
    styles = getSampleStyleSheet()
    
    if registered:
        font_name = 'ChineseFont'
    else:
        font_name = 'Helvetica'
    
    styles.add(ParagraphStyle(
        name='ChineseTitle',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=24,
        leading=32,
        spaceAfter=20,
        alignment=TA_CENTER
    ))
    
    styles.add(ParagraphStyle(
        name='ChineseHeading1',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=18,
        leading=24,
        spaceBefore=20,
        spaceAfter=10
    ))
    
    styles.add(ParagraphStyle(
        name='ChineseHeading2',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=14,
        leading=18,
        spaceBefore=15,
        spaceAfter=8
    ))
    
    styles.add(ParagraphStyle(
        name='ChineseBody',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=11,
        leading=16,
        spaceAfter=6
    ))
    
    styles.add(ParagraphStyle(
        name='ChineseSmall',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        leading=13
    ))
    
    # 构建内容
    story = []
    
    # 标题
    story.append(Paragraph('MiniMax MCP 打标费用追踪报告', styles['ChineseTitle']))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f'生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        styles['ChineseSmall']
    ))
    story.append(Spacer(1, 20))
    
    # 执行概览
    story.append(Paragraph('一、执行概览', styles['ChineseHeading1']))
    
    overview_data = [
        ['指标', '数值'],
        ['总素材数量', f"{stats['total_materials']} 个"],
        ['成功打标', f"{stats['total_processed']} 个"],
        ['跳过（无图片）', f"{stats['skipped']} 个"],
        ['成功率', f"{stats['total_processed']/stats['total_materials']*100:.1f}%"],
        ['开始时间', stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')],
        ['结束时间', stats['end_time'].strftime('%Y-%m-%d %H:%M:%S')],
        ['总耗时', f"{stats['total_hours']:.2f} 小时 ({stats['total_minutes']:.1f} 分钟)"],
    ]
    
    overview_table = Table(overview_data, colWidths=[2*inch, 3*inch])
    overview_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A90E2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), font_name),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F5F5')),
        ('FONTNAME', (0, 1), (-1, -1), font_name),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#DDDDDD')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9F9F9')]),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    
    story.append(overview_table)
    story.append(Spacer(1, 20))
    
    # 费用分析
    story.append(Paragraph('二、费用分析', styles['ChineseHeading1']))
    
    cost_data = [
        ['费用项', '金额'],
        ['单次调用费用', f"¥{stats['price_per_call']:.4f}"],
        ['总调用次数', f"{stats['total_processed']} 次"],
        ['总费用', f"¥{stats['total_cost']:.2f}"],
        ['平均每个素材费用', f"¥{stats['avg_cost_per_material']:.4f}"],
    ]
    
    cost_table = Table(cost_data, colWidths=[2.5*inch, 2.5*inch])
    cost_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27AE60')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), font_name),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#E8F8F5')),
        ('FONTNAME', (0, 1), (-1, -1), font_name),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#DDDDDD')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0FFF0')]),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#FFF3CD')),
        ('FONTNAME', (0, -1), (-1, -1), font_name),
        ('FONTSIZE', (0, -1), (-1, -1), 12),
    ]))
    
    story.append(cost_table)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        '注：以上费用为估算值，实际费用请以 MiniMax 平台账单为准。',
        styles['ChineseSmall']
    ))
    story.append(Spacer(1, 20))
    
    # 性能分析
    story.append(Paragraph('三、性能分析', styles['ChineseHeading1']))
    
    perf_data = [
        ['性能指标', '数值'],
        ['平均每个素材处理时间', f"{stats['avg_time_per_material']:.2f} 秒"],
        ['平均每分钟处理素材', f"{60/stats['avg_time_per_material']:.2f} 个"],
        ['平均每小时处理素材', f"{3600/stats['avg_time_per_material']:.2f} 个"],
        ['最快处理速度', '~9 秒/素材"],
    ]
    
    perf_table = Table(perf_data, colWidths=[2.5*inch, 2.5*inch])
    perf_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8E44AD')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), font_name),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5EEF8')),
        ('FONTNAME', (0, 1), (-1, -1), font_name),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#DDDDDD')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FAF5FF')]),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    
    story.append(perf_table)
    story.append(Spacer(1, 20))
    
    # 标签分布
    story.append(Paragraph('四、标签分布统计', styles['ChineseHeading1']))
    
    label_data = [['标签', '数量', '占比']]
    sorted_labels = sorted(stats['label_distribution'].items(), 
                          key=lambda x: x[1], reverse=True)
    
    for label, count in sorted_labels:
        percentage = count / stats['total_processed'] * 100
        label_data.append([label, str(count), f'{percentage:.1f}%'])
    
    # 总计行
    label_data.append([
        '总计',
        str(stats['total_processed']),
        '100.0%'
    ])
    
    label_table = Table(label_data, colWidths=[2.5*inch, 1*inch, 1*inch])
    label_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E67E22')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), font_name),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('FONTNAME', (0, 1), (-1, -2), font_name),
        ('FONTSIZE', (0, 1), (-1, -2), 10),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#DDDDDD')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#FFF5E6')]),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#FFF3CD')),
        ('FONTNAME', (0, -1), (-1, -1), font_name),
        ('FONTSIZE', (0, -1), (-1, -1), 11),
    ]))
    
    story.append(label_table)
    story.append(Spacer(1, 20))
    
    # 图表页面
    story.append(PageBreak())
    story.append(Paragraph('五、可视化图表', styles['ChineseHeading1']))
    story.append(Spacer(1, 15))
    
    # 添加图表图片
    chart_files = [
        ('chart_label_distribution.png', '5.1 标签分布饼图'),
        ('chart_top5_labels.png', '5.2 Top 5 标签柱状图'),
        ('chart_timeline.png', '5.3 处理时间线图'),
    ]
    
    for chart_file, title in chart_files:
        if os.path.exists(chart_file):
            story.append(Paragraph(title, styles['ChineseHeading2']))
            story.append(Spacer(1, 10))
            from reportlab.platypus import Image
            img = Image(chart_file, width=6.5*inch, height=4.5*inch)
            story.append(img)
            story.append(Spacer(1, 15))
    
    # 总结
    story.append(PageBreak())
    story.append(Paragraph('六、总结与建议', styles['ChineseHeading1']))
    
    summary_text = f"""
    <b>本次打标任务总结：</b><br/><br/>
    • 共处理 <b>{stats['total_materials']}</b> 个素材文件夹，成功打标 <b>{stats['total_processed']}</b> 个<br/>
    • 总耗时 <b>{stats['total_hours']:.2f}</b> 小时，成功率 <b>{stats['total_processed']/stats['total_materials']*100:.1f}%</b><br/>
    • 平均每个素材处理时间 <b>{stats['avg_time_per_material']:.2f}</b> 秒<br/>
    • 预估总费用 <b>¥{stats['total_cost']:.2f}</b>，平均每个素材 <b>¥{stats['avg_cost_per_material']:.4f}</b><br/><br/>
    
    <b>优化建议：</b><br/><br/>
    1. <b>批量处理</b>：当前为串行处理，可考虑并发处理提升效率<br/>
    2. <b>缓存复用</b>：已实现断点续传，避免重复调用浪费资源<br/>
    3. <b>图片采样</b>：对于图片较多的文件夹，可只分析首张图片<br/>
    4. <b>Token监控</b>：建议定期检查 MiniMax 平台 Token 余额，避免中断<br/>
    5. <b>质量验证</b>：建议抽样验证打标准确性，持续优化 prompt
    """
    
    story.append(Paragraph(summary_text, styles['ChineseBody']))
    
    # 构建PDF
    doc.build(story)
    print(f"\n✅ PDF报告已生成: {OUTPUT_PDF}")

def main():
    print("=" * 60)
    print("📊 MiniMax MCP 打标费用追踪报告生成器")
    print("=" * 60)
    
    # 加载缓存
    print("\n📂 加载缓存文件...")
    cache = load_cache()
    print(f"✅ 加载 {len(cache)} 条记录")
    
    # 分析数据
    print("\n🔍 分析数据...")
    stats = analyze_cache(cache)
    
    print(f"\n📈 统计结果:")
    print(f"  • 总素材: {stats['total_materials']}")
    print(f"  • 成功打标: {stats['total_processed']}")
    print(f"  • 跳过: {stats['skipped']}")
    print(f"  • 总耗时: {stats['total_hours']:.2f} 小时")
    print(f"  • 平均每个素材: {stats['avg_time_per_material']:.2f} 秒")
    print(f"  • 预估总费用: ¥{stats['total_cost']:.2f}")
    
    # 生成图表
    print("\n📊 生成图表...")
    generate_charts(stats, cache)
    print("✅ 图表生成完成")
    
    # 生成PDF
    print("\n📝 生成PDF报告...")
    create_pdf(stats)
    
    print("\n" + "=" * 60)
    print("✅ 报告生成完成！")
    print("=" * 60)

if __name__ == "__main__":
    main()
