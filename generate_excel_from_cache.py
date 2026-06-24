import pandas as pd
import json
import os
from datetime import datetime

def generate_excel_from_cache():
    cache_file = 'gemini_label_cache.json'
    output_file = 'gemini_labeled_results.xlsx'
    
    if not os.path.exists(cache_file):
        print(f"Error: {cache_file} not found.")
        return

    with open(cache_file, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(f"Error: {cache_file} is not a valid JSON file.")
            return

    results = []
    # Using the standard columns as defined in the original script
    columns = [
        'daterange', 'saveurl', 'dynamiclink', 'photos', 'videos', 
        'creatupdatedate', 'Unnamed: 6', 'Unnamed: 7', 
        '制作组类型（细分标签）', '判定依据（结合业务规则判断标准）'
    ]

    for mid, info in data.items():
        results.append({
            'daterange': datetime.now().strftime('%Y-%m-%d'),
            'saveurl': f'Folder: {mid}',
            'dynamiclink': mid,
            'photos': '',
            'videos': '',
            'creatupdatedate': '',
            'Unnamed: 6': '',
            'Unnamed: 7': '',
            '制作组类型（细分标签）': info.get('label', '其他'),
            '判定依据（结合业务规则判断标准）': info.get('reason', '')
        })

    if results:
        df = pd.DataFrame(results, columns=columns)
        try:
            df.to_excel(output_file, index=False)
            print(f"Successfully generated {len(results)} records to {os.path.abspath(output_file)}")
        except Exception as e:
            print(f"Error saving Excel file: {e}")
    else:
        print("No results found in cache.")

if __name__ == "__main__":
    generate_excel_from_cache()
