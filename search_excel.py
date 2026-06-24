import pandas as pd
import os

def search_keyword_in_excel(directory, keyword, output_file="search_results.txt"):
    found_in_files = []
    with open(output_file, 'w', encoding='utf-8') as f_out:
        for filename in os.listdir(directory):
            if filename.endswith(".xlsx") and not filename.startswith("~$"):
                filepath = os.path.join(directory, filename)
                f_out.write(f"Searching in {filename}...\n")
                try:
                    df = pd.read_excel(filepath)
                    for column in df.columns:
                        if df[column].astype(str).str.contains(keyword, na=False).any():
                            found_in_files.append(filename)
                            f_out.write(f"  Found '{keyword}' in column '{column}' of {filename}. Details:\n")
                            f_out.write(df[df[column].astype(str).str.contains(keyword, na=False)].to_string())
                            f_out.write("\n\n")
                            break # Move to next file once found
                except Exception as e:
                    f_out.write(f"  Could not read {filename}: {e}\n")
        
        if found_in_files:
            f_out.write(f"'{keyword}' found in the following Excel files:\n")
            for fn in found_in_files:
                f_out.write(f"- {fn}\n")
        else:
            f_out.write(f"'{keyword}' not found in any Excel files.\n")
    return found_in_files

if __name__ == "__main__":
    current_directory = "."  # Search in the root directory
    keyword_to_search = "明星穿搭"
    search_keyword_in_excel(current_directory, keyword_to_search, "search_results.txt")
    print("Search complete. Results written to search_results.txt")
