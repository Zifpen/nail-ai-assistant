import sqlite3

conn = sqlite3.connect('salon.db')
cursor = conn.cursor()

print('=' * 70)
print('DATABASE SCHEMA: salon.db')
print('=' * 70)

# Show all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print('\nTables:')
for table in tables:
    print(f'  - {table[0]}')

# Show schema for each table
for table_name in [t[0] for t in tables]:
    print(f'\n{table_name.upper()} TABLE SCHEMA:')
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    for col in columns:
        print(f'  {col[1]:15} {col[2]:10} PK:{col[5]}')

conn.close()