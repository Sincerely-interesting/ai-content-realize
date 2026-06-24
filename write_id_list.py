import pandas as pd

df = pd.read_excel('minimax_mcp_understand_full_results_before.xlsx')
ids = df['dynamiclink'].head(200).astype(str).tolist()

with open('id_list_before.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(ids))

print(f'Written {len(ids)} IDs to id_list_before.txt')
print('First 5:', ids[:5])
print('Last  5:', ids[-5:])
