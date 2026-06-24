import pandas as pd
from collections import Counter

df_b = pd.read_excel('minimax_mcp_understand_full_results_before.xlsx')
df_a = pd.read_excel('minimax_mcp_multimodal_results.xlsx')

df_b['id'] = df_b['dynamiclink'].astype(str)
df_a['id'] = df_a['dynamiclink'].astype(str)

df_b200 = df_b.head(200).copy()

lbl_col  = '制作组类型（细分标签）'
rsn_b    = '判定依据（结合业务规则判断标准）'
rsn_a    = '判定依据'

# ── 1. 标签分布对比 ──────────────────────────────────────────────
print('\n=== 1. 标签分布对比 (BEFORE前200行 vs AFTER已处理120行) ===')
cnt_b = Counter(df_b200[lbl_col].str.strip())
cnt_a = Counter(df_a[lbl_col].str.strip())
all_labels = sorted(set(list(cnt_b.keys()) + list(cnt_a.keys())))
header = f"{'标签':<32} {'BEFORE':>8} {'AFTER':>8} {'变化':>8}"
print(header)
print('-' * 60)
for lbl in all_labels:
    b = cnt_b.get(lbl, 0)
    a = cnt_a.get(lbl, 0)
    delta = a - b
    sign  = f'+{delta}' if delta > 0 else str(delta)
    print(f'{lbl:<32} {b:>8} {a:>8} {sign:>8}')

# ── 2. 交叉对比：相同ID标签是否一致 ─────────────────────────────
print('\n=== 2. 相同ID标签一致性分析 ===')
merged = df_b200.merge(
    df_a[['id', lbl_col, rsn_a]],
    on='id', how='inner', suffixes=('_b', '_a')
)
print(f'可对比样本数: {len(merged)}')
same_mask = merged[lbl_col + '_b'].str.strip() == merged[lbl_col + '_a'].str.strip()
same  = same_mask.sum()
diff  = len(merged) - same
print(f'标签一致: {same} ({same/len(merged)*100:.1f}%)')
print(f'标签不一致: {diff} ({diff/len(merged)*100:.1f}%)')

# ── 3. 不一致样本明细 ────────────────────────────────────────────
print('\n=== 3. 不一致样本明细 ===')
mismatch = merged[~same_mask][['id', lbl_col + '_b', lbl_col + '_a', rsn_a]].copy()
mismatch.columns = ['素材ID', 'BEFORE标签', 'AFTER标签', 'AFTER判定依据']
print(mismatch[['素材ID', 'BEFORE标签', 'AFTER标签']].to_string(index=False))

# ── 4. 判定依据文本长度对比 ──────────────────────────────────────
print('\n=== 4. 判定依据文本质量对比 ===')
merged['len_b'] = merged[rsn_b].astype(str).str.len()
merged['len_a'] = merged[rsn_a].astype(str).str.len()
print(f'BEFORE 判定依据平均长度: {merged["len_b"].mean():.0f} 字符')
print(f'AFTER  判定依据平均长度: {merged["len_a"].mean():.0f} 字符')
print(f'BEFORE 判定依据最短/最长: {merged["len_b"].min()} / {merged["len_b"].max()}')
print(f'AFTER  判定依据最短/最长: {merged["len_a"].min()} / {merged["len_a"].max()}')

# ── 5. BEFORE独有标签（AFTER中未出现）vs AFTER新增标签 ──────────
print('\n=== 5. 标签覆盖差异 ===')
only_in_b = set(cnt_b.keys()) - set(cnt_a.keys())
only_in_a = set(cnt_a.keys()) - set(cnt_b.keys())
print(f'BEFORE有但AFTER无: {only_in_b if only_in_b else "无"}')
print(f'AFTER有但BEFORE无: {only_in_a if only_in_a else "无"}')

# ── 6. 主要标签转移矩阵 ─────────────────────────────────────────
print('\n=== 6. 标签转移矩阵（不一致样本）===')
if len(mismatch) > 0:
    matrix = mismatch.groupby(['BEFORE标签', 'AFTER标签']).size().reset_index(name='count')
    print(matrix.to_string(index=False))

# ── 7. AFTER特有字段分析 ─────────────────────────────────────────
print('\n=== 7. AFTER新增字段统计 ===')
print(f'含视频素材: {df_a["是否视频"].sum()} 个')
print(f'含音频素材: {df_a["是否有音频"].sum()} 个')
print(f'平均帧数(视频): {df_a[df_a["帧数"]>0]["帧数"].mean():.1f} 帧')
print(f'有语音转录: {(df_a["语音文本长度"]>0).sum()} 个')

# ── 8. BEFORE中有但AFTER未处理（待充值）的ID ─────────────────────
print('\n=== 8. 待处理ID（仅BEFORE有，AFTER缺失）===')
before_ids = set(df_b200['id'].tolist())
after_ids  = set(df_a['id'].tolist())
pending    = before_ids - after_ids
print(f'待处理: {len(pending)} 个 (共200个目标ID中)')

print('\n--- 分析完成 ---')
