import pandas as pd
import json
import os

excel_file = 'gemini_labeled_results.xlsx'
cache_file = 'gemini_label_cache.json'

if os.path.exists(excel_file):
    try:
        df = pd.read_excel(excel_file)
        cache = {}
        for _, row in df.iterrows():
            mid = str(row['dynamiclink'])
            # Only keep valid labels (if any)
            label = row.get('制作组类型（细分标签）', '其他')
            reason = row.get('判定依据（结合业务规则判断标准）', '从 Excel 恢复')
            if pd.isna(label): label = "其他"
            if pd.isna(reason): reason = "从 Excel 恢复"
            
            # Skip entries that represent previous failures
            if any(x in str(reason) for x in ['未能从 Gemini API', 'Error calling', 'HTTP']):
                continue
                
            cache[mid] = {
                'label': label,
                'reason': reason,
                'timestamp': '2026-04-16T10:00:00'
            }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)
        print(f"Successfully recovered {len(cache)} valid entries from Excel to cache.")
    except Exception as e:
        print(f"Error during recovery: {e}")
else:
    print("Excel file not found. Creating empty cache.")
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump({}, f)
