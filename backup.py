import requests
import json
import csv
import os
from datetime import datetime

SUPABASE_URL = 'https://ocikxcyckwigrvtwxsap.supabase.co'
SUPABASE_KEY = 'sb_publishable_f3zLVxnd9ZlV4JiwxFBVPg_UkDDNKVm'

# ALL YOUR TABLES
ALL_TABLES = [
    'hs_accounts', 'hs_users', 'hs_payments', 'hs_submissions',
    'hs_worker_assignments', 'hs_manager_assignments', 'hs_proxies',
    'hs_announcements', 'hs_notifications', 'hs_settings',
    'wf_payroll', 'wf_submissions', 'wf_users', 'wf_workers', 'wf_settings'
]

def get_table_schema(table_name):
    """Get table schema/structure for migration"""
    # This is a simplified schema - you'd get actual schema from Supabase
    # But for migration, we'll use the data structure
    return None

def generate_sql_inserts(table_name, data):
    """Generate SQL INSERT statements for migration"""
    if not data:
        return ""
    
    # Get column names from first record
    columns = list(data[0].keys())
    columns_str = ', '.join([f'"{col}"' for col in columns])
    
    sql_lines = []
    sql_lines.append(f"-- {table_name}")
    sql_lines.append(f"INSERT INTO {table_name} ({columns_str}) VALUES")
    
    values_list = []
    for record in data:
        values = []
        for col in columns:
            val = record.get(col)
            if val is None:
                values.append('NULL')
            elif isinstance(val, str):
                # Escape single quotes
                escaped = val.replace("'", "''")
                values.append(f"'{escaped}'")
            elif isinstance(val, (int, float)):
                values.append(str(val))
            elif isinstance(val, dict):
                values.append(f"'{json.dumps(val).replace("'", "''")}'")
            else:
                values.append(f"'{str(val).replace("'", "''")}'")
        
        values_list.append(f"({', '.join(values)})")
    
    sql_lines.append(',\n'.join(values_list))
    sql_lines.append(';')
    sql_lines.append('')
    
    return '\n'.join(sql_lines)

def backup_for_migration():
    """Backup ALL data in migration-friendly format"""
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_folder = f'migration_backup_{timestamp}'
    os.makedirs(backup_folder, exist_ok=True)
    
    # Create subfolders
    json_folder = f'{backup_folder}/json'
    csv_folder = f'{backup_folder}/csv'
    sql_folder = f'{backup_folder}/sql'
    storage_folder = f'{backup_folder}/storage_files'
    
    os.makedirs(json_folder, exist_ok=True)
    os.makedirs(csv_folder, exist_ok=True)
    os.makedirs(sql_folder, exist_ok=True)
    os.makedirs(storage_folder, exist_ok=True)
    
    print("=" * 70)
    print("🔄 MIGRATION BACKUP - ALL DATA")
    print("=" * 70)
    print(f"📁 Backup folder: {backup_folder}")
    print()
    
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}'
    }
    
    all_data = {}
    total_records = 0
    all_sql = []
    
    # ============================================================
    # PART 1: BACKUP DATABASE TABLES
    # ============================================================
    print("📊 PART 1: Backing up database tables...")
    print("-" * 50)
    
    for table in ALL_TABLES:
        print(f"📥 Fetching {table}...", end=" ")
        try:
            response = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers)
            if response.status_code == 200:
                data = response.json()
                count = len(data)
                total_records += count
                all_data[table] = data
                
                # 1. Save as JSON (for restoration)
                with open(f"{json_folder}/{table}.json", 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, default=str, ensure_ascii=False)
                
                # 2. Save as CSV (for Excel/import)
                if data:
                    keys = list(data[0].keys())
                    with open(f"{csv_folder}/{table}.csv", 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=keys)
                        writer.writeheader()
                        writer.writerows(data)
                
                # 3. Generate SQL INSERT statements
                sql = generate_sql_inserts(table, data)
                with open(f"{sql_folder}/{table}.sql", 'w', encoding='utf-8') as f:
                    f.write(sql)
                
                # Add to master SQL
                all_sql.append(sql)
                
                print(f"✅ {count} records (JSON + CSV + SQL)")
            else:
                print(f"❌ Error {response.status_code}")
                all_data[table] = []
        except Exception as e:
            print(f"❌ {str(e)}")
            all_data[table] = []
    
    # Save master SQL file with ALL tables
    with open(f"{backup_folder}/complete_migration.sql", 'w', encoding='utf-8') as f:
        f.write("-- ============================================================\n")
        f.write("-- COMPLETE DATABASE MIGRATION - ALL TABLES\n")
        f.write(f"-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("-- ============================================================\n\n")
        
        # Add CREATE TABLE statements (simplified - you'd add real schema)
        f.write("-- NOTE: You need to create tables first!\n")
        f.write("-- Use the schema from your Supabase database\n\n")
        
        for sql in all_sql:
            if sql:
                f.write(sql)
                f.write("\n")
    
    # ============================================================
    # PART 2: BACKUP STORAGE FILES
    # ============================================================
    print()
    print("📦 PART 2: Backing up storage files...")
    print("-" * 50)
    
    try:
        response = requests.get(f"{SUPABASE_URL}/storage/v1/object/list/uploads", headers=headers)
        if response.status_code == 200:
            files = response.json()
            print(f"📥 Found {len(files)} files")
            
            # Save file list
            with open(f"{backup_folder}/storage_file_list.json", 'w') as f:
                json.dump(files, f, indent=2)
            
            downloaded = 0
            for file_info in files:
                filename = file_info['name']
                print(f"📥 Downloading {filename[:40]}...", end=" ")
                
                dl_response = requests.get(
                    f"{SUPABASE_URL}/storage/v1/object/uploads/{filename}",
                    headers=headers
                )
                
                if dl_response.status_code == 200:
                    with open(f"{storage_folder}/{filename}", 'wb') as f:
                        f.write(dl_response.content)
                    print(f"✅ {len(dl_response.content):,} bytes")
                    downloaded += 1
                else:
                    print("❌ Failed")
            
            print(f"\n✅ Downloaded {downloaded} files")
        else:
            print(f"❌ Could not get file list: {response.status_code}")
    except Exception as e:
        print(f"❌ Error: {str(e)}")
    
    # ============================================================
    # PART 3: CREATE MIGRATION SUMMARY
    # ============================================================
    
    # Save master JSON with ALL data
    with open(f"{backup_folder}/complete_data.json", 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=2, default=str, ensure_ascii=False)
    
    # Create migration guide
    with open(f"{backup_folder}/README_MIGRATION.txt", 'w') as f:
        f.write("=" * 70 + "\n")
        f.write("MIGRATION BACKUP - HOW TO USE\n")
        f.write("=" * 70 + "\n\n")
        
        f.write("1. JSON FILES (json/ folder):\n")
        f.write("   - For restoration with any database\n")
        f.write("   - Can be imported using: INSERT INTO table SELECT * FROM json_populate...\n\n")
        
        f.write("2. CSV FILES (csv/ folder):\n")
        f.write("   - For Excel/Google Sheets review\n")
        f.write("   - Can be imported using: COPY table FROM 'file.csv' CSV HEADER\n\n")
        
        f.write("3. SQL FILES (sql/ folder):\n")
        f.write("   - Ready-to-run INSERT statements\n")
        f.write("   - Each table has its own .sql file\n")
        f.write("   - complete_migration.sql has ALL tables\n\n")
        
        f.write("4. STORAGE FILES (storage_files/ folder):\n")
        f.write("   - All uploaded files\n")
        f.write("   - Need to be uploaded to new storage bucket\n\n")
        
        f.write("=" * 70 + "\n")
        f.write("TABLES BACKED UP:\n")
        f.write("=" * 70 + "\n\n")
        
        for table in ALL_TABLES:
            count = len(all_data.get(table, []))
            f.write(f"  ✅ {table}: {count} records\n")
        
        f.write("\n" + "=" * 70 + "\n")
        f.write("NEXT STEPS:\n")
        f.write("=" * 70 + "\n\n")
        f.write("1. Create the same tables in your new database\n")
        f.write("2. Import data using:\n")
        f.write("   - SQL: Run complete_migration.sql\n")
        f.write("   - JSON: Use your database's JSON import\n")
        f.write("   - CSV: Use COPY or import tool\n")
        f.write("3. Upload storage files to new bucket\n")
    
    # ============================================================
    # SUMMARY
    # ============================================================
    print()
    print("=" * 70)
    print("📊 MIGRATION BACKUP COMPLETE!")
    print("=" * 70)
    print(f"✅ Tables backed up: {len(ALL_TABLES)}")
    print(f"✅ Total records: {total_records:,}")
    print(f"📁 Saved to: {backup_folder}/")
    print()
    print("📁 What you got:")
    print(f"   ├── json/          - {len(ALL_TABLES)} JSON files")
    print(f"   ├── csv/           - {len(ALL_TABLES)} CSV files")
    print(f"   ├── sql/           - {len(ALL_TABLES)} SQL files")
    print(f"   ├── storage_files/ - All uploaded files")
    print(f"   ├── complete_data.json      - All data in one file")
    print(f"   ├── complete_migration.sql  - All SQL ready to run")
    print(f"   ├── storage_file_list.json  - List of all files")
    print(f"   └── README_MIGRATION.txt    - Migration guide")
    print()
    print("=" * 70)
    print("🚀 READY TO MIGRATE!")
    print("=" * 70)

if __name__ == "__main__":
    backup_for_migration()
