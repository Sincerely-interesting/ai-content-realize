"""
生成打标结果对比 HTML 报告
"""
import json
import pandas as pd
from collections import Counter
from datetime import datetime

# ── 数据加载 ─────────────────────────────────────────────────────
df_b = pd.read_excel('minimax_mcp_understand_full_results_before.xlsx')
df_a = pd.read_excel('minimax_mcp_multimodal_results.xlsx')
df_b['id'] = df_b['dynamiclink'].astype(str)
df_a['id'] = df_a['dynamiclink'].astype(str)
df_b200 = df_b.head(200).copy()

lbl_col = '制作组类型（细分标签）'
rsn_b   = '判定依据（结合业务规则判断标准）'
rsn_a   = '判定依据'

cnt_b = Counter(df_b200[lbl_col].str.strip())
cnt_a = Counter(df_a[lbl_col].str.strip())
all_labels = sorted(set(list(cnt_b.keys()) + list(cnt_a.keys())))

merged = df_b200.merge(df_a[['id', lbl_col, rsn_a]], on='id', how='inner', suffixes=('_b', '_a'))
same_mask = merged[lbl_col + '_b'].str.strip() == merged[lbl_col + '_a'].str.strip()
same_n  = int(same_mask.sum())
diff_n  = len(merged) - same_n
total_n = len(merged)

merged['len_b'] = merged[rsn_b].astype(str).str.len()
merged['len_a'] = merged[rsn_a].astype(str).str.len()

mismatch = merged[~same_mask][['id', lbl_col + '_b', lbl_col + '_a']].copy()
mismatch.columns = ['素材ID', 'BEFORE标签', 'AFTER标签']
matrix = mismatch.groupby(['BEFORE标签', 'AFTER标签']).size().reset_index(name='数量')
matrix = matrix.sort_values('数量', ascending=False)

only_in_b = set(cnt_b.keys()) - set(cnt_a.keys())
pending_n = 200 - len(df_a)
ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ── 颜色辅助 ─────────────────────────────────────────────────────
LABEL_COLORS = {
    '明星穿搭':           '#8b5cf6',
    '穿搭精选 (核心)-穿搭种草': '#3b82f6',
    '穿搭精选 (次要)-穿搭种草': '#60a5fa',
    '单品展示 (剔除出穿搭)-上脚': '#f59e0b',
    '创意静物':           '#10b981',
    '静物展示':           '#6ee7b7',
    '性能测试':           '#ef4444',
    '其他':              '#9ca3af',
}
def lbl_badge(lbl):
    color = LABEL_COLORS.get(lbl.strip(), '#6b7280')
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:12px;font-size:12px;white-space:nowrap">{lbl}</span>'

def delta_cell(b, a):
    d = a - b
    if d > 0:
        return f'<span style="color:#ef4444;font-weight:600">+{d} ▲</span>'
    elif d < 0:
        return f'<span style="color:#10b981;font-weight:600">{d} ▼</span>'
    return f'<span style="color:#9ca3af">0</span>'

# ── 分布条形图 data ───────────────────────────────────────────────
max_b = max(cnt_b.values()) if cnt_b else 1
max_a = max(cnt_a.values()) if cnt_a else 1
chart_max = max(max_b, max_a)

def bar(val, mx, color):
    w = max(1, int(val / mx * 200))
    return f'<div style="display:inline-block;width:{w}px;height:14px;background:{color};border-radius:3px;vertical-align:middle"></div> {val}'

# ── HTML 构建 ─────────────────────────────────────────────────────
rows_dist = ''
for lbl in all_labels:
    b = cnt_b.get(lbl, 0)
    a = cnt_a.get(lbl, 0)
    warn = ' ⚠️' if a == 0 and b > 0 else ''
    rows_dist += f'''
    <tr>
      <td>{lbl_badge(lbl)}{warn}</td>
      <td style="text-align:right">{bar(b, chart_max, "#3b82f6")}</td>
      <td style="text-align:right">{bar(a, chart_max, "#8b5cf6")}</td>
      <td style="text-align:right">{delta_cell(b, a)}</td>
    </tr>'''

rows_matrix = ''
for _, row in matrix.iterrows():
    arrow = '→'
    same_lbl = row['BEFORE标签'].strip() == row['AFTER标签'].strip()
    bg = '#f0fdf4' if same_lbl else ('#fef2f2' if row['AFTER标签'].strip() == '其他' else '#fffbeb')
    rows_matrix += f'''
    <tr style="background:{bg}">
      <td>{lbl_badge(row["BEFORE标签"])}</td>
      <td style="text-align:center;font-size:18px;color:#6b7280">{arrow}</td>
      <td>{lbl_badge(row["AFTER标签"])}</td>
      <td style="text-align:center;font-weight:700;color:{"#ef4444" if row["AFTER标签"].strip()=="其他" else "#374151"}">{row["数量"]}</td>
    </tr>'''

rows_mismatch = ''
for _, row in mismatch.head(30).iterrows():
    rows_mismatch += f'''
    <tr>
      <td style="font-family:monospace;color:#6b7280">{row["素材ID"]}</td>
      <td>{lbl_badge(row["BEFORE标签"])}</td>
      <td>{lbl_badge(row["AFTER标签"])}</td>
    </tr>'''
if len(mismatch) > 30:
    rows_mismatch += f'<tr><td colspan="3" style="text-align:center;color:#9ca3af;padding:12px">... 还有 {len(mismatch)-30} 条不一致记录（共 {len(mismatch)} 条）</td></tr>'

pct_same = same_n / total_n * 100
pct_diff = diff_n / total_n * 100
consistency_color = '#ef4444' if pct_same < 30 else ('#f59e0b' if pct_same < 60 else '#10b981')

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>打标结果对比报告</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f8fafc; color: #1e293b; font-size: 14px; }}
  .page {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px; }}
  h1 {{ font-size: 24px; font-weight: 700; color: #0f172a; }}
  h2 {{ font-size: 17px; font-weight: 600; color: #1e293b; margin: 28px 0 12px;
        padding-left: 10px; border-left: 4px solid #3b82f6; }}
  .meta {{ color: #64748b; font-size: 13px; margin-top: 6px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 24px 0; }}
  .kpi {{ background: #fff; border-radius: 12px; padding: 20px 16px;
          box-shadow: 0 1px 4px rgba(0,0,0,.07); text-align: center; }}
  .kpi .val {{ font-size: 32px; font-weight: 800; line-height: 1.1; }}
  .kpi .sub {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
  .kpi.red   .val {{ color: #ef4444; }}
  .kpi.green .val {{ color: #10b981; }}
  .kpi.blue  .val {{ color: #3b82f6; }}
  .kpi.gray  .val {{ color: #6b7280; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 12px; overflow: hidden;
           box-shadow: 0 1px 4px rgba(0,0,0,.07); }}
  th {{ background: #f1f5f9; padding: 10px 14px; text-align: left;
        font-size: 13px; font-weight: 600; color: #475569; }}
  td {{ padding: 9px 14px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f8fafc; }}
  .progress-wrap {{ background: #e2e8f0; border-radius: 999px; height: 10px; overflow: hidden; margin: 4px 0; }}
  .progress-bar  {{ height: 10px; border-radius: 999px; }}
  .badge-warn {{ background: #fef9c3; color: #92400e; padding: 3px 10px;
                 border-radius: 8px; font-size: 12px; font-weight: 600; display: inline-block; margin: 2px; }}
  .section {{ background: #fff; border-radius: 12px; padding: 20px;
              box-shadow: 0 1px 4px rgba(0,0,0,.07); margin-bottom: 20px; }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .issue-list li {{ padding: 6px 0; border-bottom: 1px dashed #e2e8f0; line-height: 1.6; }}
  .issue-list li:last-child {{ border-bottom: none; }}
  .tag {{ display: inline-block; padding: 1px 7px; border-radius: 6px;
          font-size: 11px; font-weight: 700; margin-right: 4px; }}
  .p0 {{ background: #fee2e2; color: #b91c1c; }}
  .p1 {{ background: #fef9c3; color: #92400e; }}
  .p2 {{ background: #dcfce7; color: #166534; }}
  .footer {{ text-align: center; color: #94a3b8; font-size: 12px; margin-top: 40px; }}
  @media (max-width: 700px) {{
    .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .two-col  {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <h1>📊 打标结果对比分析报告</h1>
  <div class="meta">
    生成时间: {ts} &nbsp;|&nbsp;
    BEFORE: <code>minimax_mcp_understand_full_results_before.xlsx</code> &nbsp;|&nbsp;
    AFTER: <code>minimax_mcp_multimodal_results.xlsx</code>
  </div>

  <!-- KPI -->
  <div class="kpi-grid">
    <div class="kpi {'red' if pct_same < 40 else 'blue'}">
      <div class="val">{pct_same:.1f}%</div>
      <div class="sub">标签一致率（{same_n}/{total_n}）</div>
    </div>
    <div class="kpi red">
      <div class="val">{pct_diff:.1f}%</div>
      <div class="sub">标签不一致率（{diff_n} 条）</div>
    </div>
    <div class="kpi gray">
      <div class="val">{pending_n}</div>
      <div class="sub">待处理样本（API余额不足）</div>
    </div>
    <div class="kpi green">
      <div class="val">{len(df_a)}</div>
      <div class="sub">已完成打标（目标200）</div>
    </div>
  </div>

  <!-- 进度条 -->
  <div class="section">
    <h2>📈 整体一致性</h2>
    <div style="margin: 12px 0 4px;font-size:13px;color:#475569">标签一致率</div>
    <div class="progress-wrap">
      <div class="progress-bar" style="width:{pct_same:.1f}%;background:{consistency_color}"></div>
    </div>
    <div style="font-size:12px;color:#64748b;margin-top:4px">
      一致 {same_n} 条 &nbsp;/&nbsp; 不一致 {diff_n} 条 &nbsp;(共 {total_n} 条可对比样本)
    </div>

    <div style="margin: 16px 0 4px;font-size:13px;color:#475569">任务完成率</div>
    <div class="progress-wrap">
      <div class="progress-bar" style="width:{len(df_a)/200*100:.1f}%;background:#3b82f6"></div>
    </div>
    <div style="font-size:12px;color:#64748b;margin-top:4px">
      已完成 {len(df_a)} / 200 ({len(df_a)/200*100:.1f}%) &nbsp;—&nbsp;
      剩余 {pending_n} 条待 API 充值后续跑
    </div>
  </div>

  <!-- 标签分布对比 -->
  <h2>🏷️ 标签分布对比（BEFORE前200行 vs AFTER已处理{len(df_a)}行）</h2>
  <table>
    <thead><tr>
      <th>标签</th>
      <th>BEFORE（蓝）</th>
      <th>AFTER（紫）</th>
      <th>变化</th>
    </tr></thead>
    <tbody>{rows_dist}</tbody>
  </table>
  <div style="margin-top:10px;font-size:12px;color:#64748b">
    ⚠️ 标注项 = BEFORE有、AFTER完全消失的标签
  </div>

  <!-- 判定依据质量 -->
  <div class="two-col" style="margin-top:20px">
    <div class="section">
      <h2 style="margin-top:0">📝 判定依据文本质量</h2>
      <table>
        <thead><tr><th>指标</th><th>BEFORE</th><th>AFTER</th></tr></thead>
        <tbody>
          <tr><td>平均字符数</td>
              <td style="color:#10b981;font-weight:700">{merged["len_b"].mean():.0f}</td>
              <td style="color:#ef4444;font-weight:700">{merged["len_a"].mean():.0f}</td></tr>
          <tr><td>最短</td>
              <td>{int(merged["len_b"].min())}</td>
              <td>{int(merged["len_a"].min())}</td></tr>
          <tr><td>最长</td>
              <td>{int(merged["len_b"].max())}</td>
              <td>{int(merged["len_a"].max())}</td></tr>
          <tr><td>结构化程度</td>
              <td>✅ 三段式（场景→内容→排除）</td>
              <td>⚠️ 简单结论句</td></tr>
        </tbody>
      </table>
    </div>
    <div class="section">
      <h2 style="margin-top:0">🎬 AFTER 新增字段</h2>
      <table>
        <thead><tr><th>字段</th><th>统计</th><th>状态</th></tr></thead>
        <tbody>
          <tr><td>是否视频</td>
              <td>{df_a["是否视频"].sum()}/120 = 100%</td>
              <td style="color:#ef4444">⚠️ 数据错误</td></tr>
          <tr><td>帧数</td>
              <td>均值 {df_a[df_a["帧数"]>0]["帧数"].mean():.1f}</td>
              <td style="color:#f59e0b">⚠️ 实为图片数</td></tr>
          <tr><td>是否有音频</td>
              <td>{df_a["是否有音频"].sum()} 个</td>
              <td style="color:#f59e0b">⚠️ 图片不应有</td></tr>
          <tr><td>语音文本长度</td>
              <td>{(df_a["语音文本长度"]>0).sum()} 个 > 0</td>
              <td style="color:#f59e0b">⚠️ 存疑</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 标签转移矩阵 -->
  <h2>🔄 标签转移矩阵（不一致样本流向分析）</h2>
  <table>
    <thead><tr>
      <th>BEFORE 标签</th>
      <th style="text-align:center">方向</th>
      <th>AFTER 标签</th>
      <th style="text-align:center">数量</th>
    </tr></thead>
    <tbody>{rows_matrix}</tbody>
  </table>
  <div style="margin-top:8px;font-size:12px;color:#64748b">
    🔴 红色背景 = 退化为"其他"（核心问题）&nbsp;|&nbsp;
    🟡 黄色背景 = 标签边界漂移&nbsp;|&nbsp;
    🟢 绿色背景 = 可能正确的优先级升级
  </div>

  <!-- 不一致样本明细 -->
  <h2>📋 不一致样本明细（前30条，共{len(mismatch)}条）</h2>
  <table>
    <thead><tr><th>素材ID</th><th>BEFORE 标签</th><th>AFTER 标签</th></tr></thead>
    <tbody>{rows_mismatch}</tbody>
  </table>

  <!-- 根因分析 -->
  <h2>🔍 根因分析</h2>
  <div class="section">
    <ul class="issue-list">
      <li>
        <strong>🔴 "其他"大量涌现（34→98，+64）</strong><br>
        综合判定 prompt 合并 12~18 张图片描述，生成 3000+ 字符的 meta_prompt，其中含大量明星姓名（文俊辉、权顺荣、王一博等），触发 MiniMax <strong>Error 1026</strong> 内容安全拦截 → 返回 None → fallback 到"其他"。
      </li>
      <li>
        <strong>🔴 性能测试 / 穿搭精选(次要) 完全消失</strong><br>
        综合判定阶段被 1026 中断后未保留分批结果，这两个边界标签在逐张图片的单次 prompt 中权重不足，未能被识别。
      </li>
      <li>
        <strong>🔴 判定依据退化（171→30字符）</strong><br>
        AFTER 取的是 MCP 原始返回文本截断，缺乏"场景→内容→排除法"三段式结构化输出，推理链条不可追溯。
      </li>
      <li>
        <strong>🟡 "是否视频"字段语义错误</strong><br>
        <code>export_cache_to_excel.py</code> 中 <code>frames_count > 0</code> 条件下将图片素材的"图片数量"误判为视频帧数，导致 100% 的记录被标为视频。
      </li>
      <li>
        <strong>🟡 80个样本未完成</strong><br>
        API 余额不足（Error 1008），非脚本逻辑问题，充值后可续跑。
      </li>
    </ul>
  </div>

  <!-- 提升点 -->
  <h2>✅ 可辩证肯定的提升点</h2>
  <div class="section">
    <ul class="issue-list">
      <li><strong>明星穿搭优先级正确提升</strong>：7个 BEFORE 标为"穿搭精选(核心)"的素材，AFTER 正确识别为"明星穿搭"（识别到明星应优先），属于真实准确率提升。</li>
      <li><strong>技术架构升级</strong>：MCP Server 架构支持 Token Plan Key，避免了 Pay-as-you-go 限制，扩展了可用性。</li>
      <li><strong>媒体预分类</strong>：新增 scan_and_classify_materials 机制，支持 image/video 按类型过滤，提升批量运营效率。</li>
      <li><strong>多模态字段扩展</strong>：帧数、音频、语音转录字段为视频素材深度分析奠定基础（需修复字段逻辑后生效）。</li>
      <li><strong>智能续跑机制</strong>：缓存 + 自动跳过已处理样本，支持断点续跑，不丢失历史结果。</li>
    </ul>
  </div>

  <!-- 改进优先级 -->
  <h2>🛠️ 改进优先级清单</h2>
  <div class="section">
    <ul class="issue-list">
      <li><span class="tag p0">P0</span> <strong>"其他"过度占比（82%）</strong>：启用 v3.0 分批综合判定（BATCH_SIZE=4），每批 ≤4 张，prompt ≤1000 字，规避 Error 1026。</li>
      <li><span class="tag p0">P0</span> <strong>性能测试 / 穿搭精选(次要) 消失</strong>：在 prompt 中显式加入两者的判定条件与示例，提升边界标签覆盖率。</li>
      <li><span class="tag p0">P0</span> <strong>判定依据文本退化</strong>：改造 prompt 要求模型按"场景→内容→排除法"格式输出，并在 export 时保留完整推理文本。</li>
      <li><span class="tag p1">P1</span> <strong>"是否视频"字段错误</strong>：修复为 <code>media_types.get(mid) == 'video'</code>，使用已有的 media_type_cache 判断。</li>
      <li><span class="tag p1">P1</span> <strong>80个样本未完成</strong>：API 充值后运行 <code>python minimax_mcp_multimodal_label_materials.py --id-list id_list_before.txt</code></li>
      <li><span class="tag p2">P2</span> <strong>一致性提升验收</strong>：P0 修复后，预期一致率可从 18.3% 提升至 60%+，届时重新运行对比报告验收。</li>
    </ul>
  </div>

  <!-- 消失标签 -->
  {'<h2>⚠️ 消失标签预警</h2><div class="section"><p style="margin-bottom:10px;color:#64748b">以下标签在 BEFORE 中存在，但在 AFTER 中完全未出现，需重点关注：</p>' + ''.join([f'<span class="badge-warn">{lbl}</span>' for lbl in only_in_b]) + '</div>' if only_in_b else ''}

  <div class="footer">
    报告由 compare_results_html.py 自动生成 &nbsp;·&nbsp; {ts}
  </div>
</div>
</body>
</html>'''

# ── 写文件 ────────────────────────────────────────────────────────
out = 'labeling_comparison_report.html'
with open(out, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'✅ HTML 报告已生成: {out}')
