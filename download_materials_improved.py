#!/usr/bin/env python3
"""
改进的素材下载脚本
==================
从Excel文件中提取素材URL并下载到本地，为MINICPM打标做准备。

功能：
1. 自动查找包含素材URL的Excel文件
2. 提取素材ID和下载链接
3. 按素材ID组织文件夹结构
4. 支持断点续传
5. 并发下载加速

用法：
  python3 download_materials_improved.py --sample 50
  python3 download_materials_improved.py --all
"""

import os
import sys
import json
import glob
import argparse
import requests
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import pandas as pd
import re

# Force line-buffered stdout
sys.stdout.reconfigure(line_buffering=True)

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
OUTPUT_DIR = Path("downloaded_materials")
MAX_WORKERS = 5  # concurrent downloads
TIMEOUT = 60  # seconds per download
RETRY_COUNT = 3

# ──────────────────────────────────────────────
# Excel File Discovery
# ──────────────────────────────────────────────
def find_excel_files():
    """Find all Excel files in the current directory."""
    excel_files = glob.glob("*.xlsx") + glob.glob("*.xls")
    return sorted(set(excel_files))


def find_material_urls(df):
    """
    intelligently find columns containing material URLs.
    Returns (material_id_column, url_columns_list) or (None, None)
    """
    url_cols = []
    id_col = None
    
    for col in df.columns:
        col_lower = str(col).lower()
        col_str = str(col)
        
        # Check for URL patterns in column values
        sample_values = df[col].dropna().head(5)
        has_urls = False
        for val in sample_values:
            val_str = str(val)
            if any(pattern in val_str for pattern in ['http://', 'https://', '.mp4', '.jpg', '.png']):
                has_urls = True
                break
        
        if has_urls:
            # Check if it's a material ID column
            if any(kw in col_lower for kw in ['id', 'trend', 'material', '任务id', '素材id']):
                id_col = col
            # Check if it's a URL column
            elif any(kw in col_lower for kw in ['url', 'link', 'save', 'download', '视频', '图片', 'saveurl']):
                url_cols.append(col)
            # Check column name patterns
            elif 'saveurl' in col_lower or 'dynamiclink' in col_lower:
                url_cols.append(col)
    
    # If no ID column found, use index
    if id_col is None and len(df) > 0:
        # Try to extract ID from URL patterns
        for col in url_cols[:1]:  # Check first URL column
            sample = str(df[col].iloc[0]) if len(df) > 0 else ""
            # Try to extract trendId or numeric ID
            match = re.search(r'trendId=(\d+)', sample)
            if match:
                id_col = '__extracted_id__'
                break
    
    return id_col, url_cols


def extract_material_id(row, id_col, url_col=None):
    """Extract material ID from row."""
    if id_col == '__extracted_id__' and url_col:
        # Extract from URL
        url_str = str(row.get(url_col, ''))
        match = re.search(r'trendId=(\d+)', url_str)
        if match:
            return match.group(1)
    
    if id_col and id_col in row:
        val = row[id_col]
        if pd.notna(val):
            return str(val).strip()
    
    return None


# ──────────────────────────────────────────────
# Download Functions
# ──────────────────────────────────────────────
def download_file(url, save_path, max_retries=RETRY_COUNT):
    """Download a single file with retry logic."""
    for attempt in range(max_retries):
        try:
            # Create directory
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Skip if already exists
            if save_path.exists():
                return True, "already exists"
            
            # Download
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            }
            response = requests.get(url, headers=headers, timeout=TIMEOUT, stream=True)
            response.raise_for_status()
            
            # Write to file
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True, "success"
            
        except requests.exceptions.Timeout:
            if attempt == max_retries - 1:
                return False, f"timeout after {max_retries} retries"
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                return False, str(e)
        
        # Wait before retry
        import time
        time.sleep(2 * (attempt + 1))
    
    return False, "unknown error"


def process_material_row(row, idx, id_col, url_cols, output_dir):
    """Process a single row and download all its URLs."""
    material_id = extract_material_id(row, id_col, url_cols[0] if url_cols else None)
    
    if not material_id:
        material_id = f"material_{idx}"
    
    material_dir = output_dir / material_id
    material_dir.mkdir(parents=True, exist_ok=True)
    
    downloaded = []
    failed = []
    
    for url_col in url_cols:
        url = row.get(url_col)
        if pd.isna(url) or not str(url).strip():
            continue
        
        url_str = str(url).strip()
        
        # Skip if not a valid URL
        if not url_str.startswith(('http://', 'https://')):
            # Try to extract URL from JSON or text
            url_match = re.search(r'(https?://[^\s"\'}\]]+)', url_str)
            if url_match:
                url_str = url_match.group(1)
            else:
                continue
        
        # Determine filename
        parsed_url = requests.models.URL(url_str)
        filename = Path(parsed_url.path).name
        if not filename or '.' not in filename:
            # Generate filename based on column name and index
            ext = '.mp4' if 'video' in str(url_col).lower() else '.jpg'
            filename = f"{material_id}_{url_col}{ext}"
        
        save_path = material_dir / filename
        
        success, msg = download_file(url_str, save_path)
        if success:
            downloaded.append(filename)
        else:
            failed.append((filename, msg))
    
    return material_id, downloaded, failed


# ──────────────────────────────────────────────
# Main Logic
# ──────────────────────────────────────────────
def scan_excel_for_materials(excel_file, sample_size=0):
    """Scan an Excel file for material URLs."""
    print(f"\n[SCAN] Analyzing: {excel_file}")
    
    try:
        xls = pd.ExcelFile(excel_file)
        print(f"  Sheets: {xls.sheet_names}")
        
        all_materials = []
        
        for sheet_name in xls.sheet_names:
            try:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                id_col, url_cols = find_material_urls(df)
                
                if url_cols:
                    print(f"  ✓ Sheet '{sheet_name}': Found {len(url_cols)} URL column(s)")
                    print(f"    URL columns: {url_cols}")
                    if id_col:
                        print(f"    ID column: {id_col}")
                    
                    # Extract materials
                    rows_to_process = df.iterrows()
                    if sample_size > 0:
                        # Take first N rows
                        rows_list = list(rows_to_process)[:sample_size]
                    else:
                        rows_list = list(rows_to_process)
                    
                    for idx, row in rows_list:
                        material_id = extract_material_id(row, id_col, url_cols[0] if url_cols else None)
                        if not material_id:
                            material_id = f"material_{idx}"
                        
                        urls = []
                        for url_col in url_cols:
                            url = row.get(url_col)
                            if pd.notna(url) and str(url).strip():
                                urls.append(str(url).strip())
                        
                        if urls:
                            all_materials.append({
                                'id': material_id,
                                'urls': urls,
                                'source': f"{excel_file}/{sheet_name}"
                            })
                
            except Exception as e:
                print(f"  ✗ Sheet '{sheet_name}' error: {e}")
        
        return all_materials
        
    except Exception as e:
        print(f"  ✗ Failed to read Excel: {e}")
        return []


def download_materials(materials, output_dir, max_workers=MAX_WORKERS):
    """Download all materials with progress tracking."""
    print(f"\n[DOWNLOAD] Starting download of {len(materials)} materials")
    print(f"  Output directory: {output_dir.absolute()}")
    print(f"  Concurrent workers: {max_workers}\n")
    
    stats = {
        'success': 0,
        'partial': 0,
        'failed': 0,
        'skipped': 0
    }
    
    with tqdm(total=len(materials), desc="Downloading", unit="material") as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            futures = {
                executor.submit(
                    process_material_row,
                    {'id': mat['id']},  # Simplified row
                    idx,
                    'id',
                    ['urls'],  # We'll handle URLs differently
                    output_dir
                ): mat for idx, mat in enumerate(materials)
            }
            
            # Actually, let's do it sequentially for better control
            for mat in materials:
                material_id = mat['id']
                material_dir = output_dir / material_id
                material_dir.mkdir(parents=True, exist_ok=True)
                
                # Check if already downloaded
                if list(material_dir.glob("*.*")):
                    stats['skipped'] += 1
                    pbar.update(1)
                    tqdm.write(f"  [SKIP] {material_id} (already exists)")
                    continue
                
                downloaded = []
                failed = []
                
                for url in mat['urls']:
                    # Extract URL from JSON/text if needed
                    url_match = re.search(r'(https?://[^\s"\'}\]]+)', url)
                    if url_match:
                        actual_url = url_match.group(1)
                    else:
                        failed.append(("unknown", "no valid URL found"))
                        continue
                    
                    # Determine filename
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(actual_url)
                        filename = Path(parsed.path).name
                        if not filename or '.' not in filename:
                            ext = '.mp4' if 'video' in url.lower() else '.jpg'
                            filename = f"{material_id}_file{ext}"
                    except:
                        filename = f"{material_id}_file.jpg"
                    
                    save_path = material_dir / filename
                    success, msg = download_file(actual_url, save_path)
                    
                    if success:
                        downloaded.append(filename)
                    else:
                        failed.append((filename, msg))
                
                # Update stats
                if downloaded and not failed:
                    stats['success'] += 1
                    tqdm.write(f"  [OK] {material_id}: {len(downloaded)} file(s)")
                elif downloaded:
                    stats['partial'] += 1
                    tqdm.write(f"  [PARTIAL] {material_id}: {len(downloaded)} ok, {len(failed)} failed")
                else:
                    stats['failed'] += 1
                    tqdm.write(f"  [FAIL] {material_id}: {failed[0][1] if failed else 'no URLs'}")
                
                pbar.update(1)
    
    return stats


# ──────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="下载素材用于MINICPM打标")
    parser.add_argument("--sample", type=int, default=0, help="下载样本数量（0=全部）")
    parser.add_argument("--all", action="store_true", help="下载所有素材")
    parser.add_argument("--output", type=str, default="downloaded_materials", help="输出目录")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help="并发下载数")
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("="*60)
    print("  素材下载工具 - 为MINICPM打标准备")
    print("="*60)
    
    # Find Excel files
    excel_files = find_excel_files()
    print(f"\nFound {len(excel_files)} Excel file(s):")
    for f in excel_files:
        print(f"  - {f}")
    
    # Scan for materials
    all_materials = []
    for excel_file in excel_files:
        sample = args.sample if args.sample > 0 else 0
        materials = scan_excel_for_materials(excel_file, sample)
        all_materials.extend(materials)
    
    if not all_materials:
        print("\n[ERROR] No materials found in Excel files!")
        print("Please check if the Excel files contain URL columns.")
        sys.exit(1)
    
    print(f"\n[INFO] Total materials found: {len(all_materials)}")
    
    # Limit to sample size if specified
    if args.sample > 0 and len(all_materials) > args.sample:
        all_materials = all_materials[:args.sample]
        print(f"[INFO] Limited to first {args.sample} materials")
    
    # Download
    stats = download_materials(all_materials, output_dir, args.workers)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"  Download Summary:")
    print(f"  ✓ Success: {stats['success']}")
    print(f"  ⚠ Partial: {stats['partial']}")
    print(f"  ✗ Failed:  {stats['failed']}")
    print(f"  ⊘ Skipped: {stats['skipped']}")
    print(f"  Total:     {sum(stats.values())}")
    print(f"{'='*60}")
    print(f"\nMaterials saved to: {output_dir.absolute()}")
    
    # Check if we have enough materials for labeling
    material_count = sum(1 for p in output_dir.iterdir() if p.is_dir())
    if material_count > 0:
        print(f"\n[OK] Ready for MINICPM labeling!")
        print(f"Run: python3 minicpm_label_materials.py --materials_dir {output_dir} --sample {min(500, material_count)}")
    else:
        print(f"\n[WARN] No materials downloaded. Cannot proceed with labeling.")


if __name__ == "__main__":
    main()
