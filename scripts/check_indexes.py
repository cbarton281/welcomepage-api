#!/usr/bin/env python3
"""
Database Index Checker Script

This script connects to your database and:
1. Lists all current indexes
2. Identifies missing critical indexes
3. Provides EXPLAIN ANALYZE for sample queries
4. Generates Alembic migration files for missing indexes
5. Detects table scan patterns (fetch all + Python filtering)

Usage:
    python scripts/check_indexes.py [--explain] [--generate-migration] [--detect-scans]
    
Options:
    --explain: Run EXPLAIN ANALYZE on sample queries
    --generate-migration: Generate Alembic migration file for missing indexes
    --detect-scans: Detect potential table scan patterns in codebase
"""

import os
import sys
import argparse
import re
from datetime import datetime
from pathlib import Path
# Optional imports (only needed for database operations)
try:
    from dotenv import load_dotenv
    load_dotenv()
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

try:
    from sqlalchemy import create_engine, text, inspect
    from sqlalchemy.exc import OperationalError
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False

# Critical indexes that should exist (after checking migrations and database)
# Note: Some indexes may be satisfied by unique indexes or composite indexes
REQUIRED_INDEXES = {
    'welcomepage_users': [
        'idx_welcomepage_users_team_id',  # Missing - needed for team_id lookups
        'idx_welcomepage_users_team_draft',  # Missing - composite for team + is_draft queries
        # auth_email - satisfied by ix_welcomepage_users_auth_email_unique (unique)
        # slack_user_id - satisfied by idx_welcomepage_users_team_slack_user_id (composite unique)
        # search_vector - already exists in migration 20250857
    ],
    'page_visits': [
        'idx_page_visits_user_visitor',  # Missing - composite for visit stats queries
        # visited_user_id - already exists in migration 20250802
        # visitor_public_id - already exists in migration 20250802
    ],
    'verification_codes': [
        'idx_verification_codes_email_used',  # Partial index for email + used=false queries
        # email - already exists in migration 20250715
        # email_code - already exists in migration 20250715
    ],
}

def get_db_engine():
    """Create database engine from DATABASE_URL"""
    if not SQLALCHEMY_AVAILABLE:
        print("Error: sqlalchemy is required for database operations")
        sys.exit(1)
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable not set")
        sys.exit(1)
    
    return create_engine(database_url)

def get_indexes_from_migrations():
    """Extract all indexes created in Alembic migration files"""
    migrations_dir = Path(__file__).parent.parent / 'db-migrations' / 'alembic' / 'versions'
    
    if not migrations_dir.exists():
        return {}
    
    import re
    indexes_from_migrations = {}
    
    # Patterns to match index creation
    # op.create_index('index_name', 'table_name', ...)
    # op.execute("CREATE INDEX ...")
    create_index_pattern = re.compile(
        r"op\.create_index\(['\"]([^'\"]+)['\"],\s*['\"]([^'\"]+)['\"]"
    )
    execute_index_pattern = re.compile(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)\s+ON\s+([a-z_][a-z0-9_]*)",
        re.IGNORECASE
    )
    
    for migration_file in migrations_dir.glob('*.py'):
        # Skip the migration we might generate
        if 'add_missing_performance_indexes' in migration_file.name:
            continue
            
        try:
            with open(migration_file, 'r') as f:
                content = f.read()
                
                # Find op.create_index calls
                for match in create_index_pattern.finditer(content):
                    index_name = match.group(1)
                    table_name = match.group(2)
                    
                    if table_name not in indexes_from_migrations:
                        indexes_from_migrations[table_name] = []
                    
                    if index_name not in [idx['name'] for idx in indexes_from_migrations[table_name]]:
                        indexes_from_migrations[table_name].append({
                            'name': index_name,
                            'source': 'migration',
                            'file': migration_file.name
                        })
                
                # Find CREATE INDEX statements in op.execute()
                for match in execute_index_pattern.finditer(content):
                    index_name = match.group(1)
                    table_name = match.group(2)
                    
                    if table_name not in indexes_from_migrations:
                        indexes_from_migrations[table_name] = []
                    
                    if index_name not in [idx['name'] for idx in indexes_from_migrations[table_name]]:
                        indexes_from_migrations[table_name].append({
                            'name': index_name,
                            'source': 'migration',
                            'file': migration_file.name
                        })
        except Exception as e:
            # Skip files that can't be read
            continue
    
    return indexes_from_migrations

def get_existing_indexes(engine):
    """Get all indexes from the database"""
    indexes = {}
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                tablename,
                indexname,
                indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN ('welcomepage_users', 'teams', 'page_visits', 
                                'verification_codes', 'slack_state_store', 
                                'slack_pending_installs')
            ORDER BY tablename, indexname;
        """))
        
        for row in result:
            table = row[0]
            index_name = row[1]
            index_def = row[2]
            
            if table not in indexes:
                indexes[table] = []
            
            indexes[table].append({
                'name': index_name,
                'definition': index_def,
                'source': 'database'
            })
    
    return indexes

def merge_index_sources(db_indexes, migration_indexes):
    """Merge indexes from database and migrations, preferring database (actual state)"""
    merged = {}
    
    # Start with database indexes (actual current state)
    for table, indexes in db_indexes.items():
        merged[table] = indexes.copy()
    
    # Add migration indexes that aren't in database yet (might not be applied)
    for table, indexes in migration_indexes.items():
        if table not in merged:
            merged[table] = []
        
        existing_names = [idx['name'] for idx in merged[table]]
        for idx in indexes:
            if idx['name'] not in existing_names:
                merged[table].append(idx)
    
    return merged

def check_missing_indexes(existing_indexes):
    """
    Identify missing critical indexes.
    Also checks if unique indexes or composite indexes satisfy the requirements.
    """
    missing = {}
    
    # Map of alternative indexes that satisfy requirements
    # Format: {required_index: [alternative_index_names]}
    index_alternatives = {
        'idx_welcomepage_users_auth_email': [
            'ix_welcomepage_users_auth_email_unique',  # Unique index satisfies non-unique requirement
            'idx_welcomepage_users_auth_email'
        ],
        'idx_welcomepage_users_slack_user_id': [
            'idx_welcomepage_users_team_slack_user_id',  # Composite unique index satisfies requirement
            'idx_welcomepage_users_slack_user_id'
        ],
    }
    
    for table, required_index_names in REQUIRED_INDEXES.items():
        existing_index_names = [idx['name'] for idx in existing_indexes.get(table, [])]
        missing_for_table = []
        
        for required_name in required_index_names:
            # Direct match
            if required_name in existing_index_names:
                continue
            
            # Check if alternative index exists
            if required_name in index_alternatives:
                found_alternative = False
                for alt_name in index_alternatives[required_name]:
                    if alt_name in existing_index_names:
                        found_alternative = True
                        break
                if found_alternative:
                    continue
            
            # Index is missing
            missing_for_table.append(required_name)
        
        if missing_for_table:
            missing[table] = missing_for_table
    
    return missing

def get_latest_migration_revision():
    """Get the latest Alembic migration revision number"""
    migrations_dir = Path(__file__).parent.parent / 'db-migrations' / 'alembic' / 'versions'
    
    if not migrations_dir.exists():
        return '20250857'  # Default to latest known revision
    
    # Find all migration files and get the highest revision number
    migration_files = list(migrations_dir.glob('*.py'))
    if not migration_files:
        return '20250857'
    
    # Extract revision numbers from filenames (format: YYYYMMDD_description.py)
    revisions = []
    for file in migration_files:
        filename = file.stem
        # Extract the date part (first 8 digits)
        if filename and filename[0:8].isdigit():
            revisions.append(filename[0:8])
    
    if revisions:
        return max(revisions)
    
    return '20250857'

def get_next_revision_number(current_revision):
    """Generate next revision number (increment by 1)"""
    # Current format is YYYYMMDD
    # For simplicity, we'll increment by 1
    try:
        rev_num = int(current_revision)
        next_rev = str(rev_num + 1)
        return next_rev
    except ValueError:
        # If parsing fails, use current date format
        return datetime.now().strftime('%Y%m%d')

def generate_alembic_migration(missing_indexes):
    """Generate an Alembic migration file for missing indexes"""
    if not missing_indexes:
        print("No missing indexes to migrate!")
        return
    
    # Get latest revision
    latest_rev = get_latest_migration_revision()
    next_rev = get_next_revision_number(latest_rev)
    
    # Define index creation operations (only for indexes that are actually missing)
    index_operations = {
        'idx_welcomepage_users_team_id': {
            'table': 'welcomepage_users',
            'columns': ['team_id'],
            'type': 'standard'
        },
        'idx_welcomepage_users_team_draft': {
            'table': 'welcomepage_users',
            'columns': ['team_id', 'is_draft'],
            'type': 'standard'
        },
        'idx_page_visits_user_visitor': {
            'table': 'page_visits',
            'columns': ['visited_user_id', 'visitor_public_id'],
            'type': 'standard'
        },
        'idx_verification_codes_email_used': {
            'table': 'verification_codes',
            'columns': ['email', 'used'],
            'type': 'partial',
            'where': 'used = false'
        },
    }
    
    # Build migration file content
    migration_content = f'''"""add_missing_performance_indexes

Revision ID: {next_rev}
Revises: {latest_rev}
Create Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '{next_rev}'
down_revision = '{latest_rev}'
branch_labels = None
depends_on = None


def upgrade():
    # Create indexes for welcomepage_users table
'''
    
    # Add index creation operations
    for table, missing_index_names in missing_indexes.items():
        for index_name in missing_index_names:
            if index_name in index_operations:
                op_def = index_operations[index_name]
                
                if op_def['type'] == 'gin':
                    # GIN index requires raw SQL
                    migration_content += f'''    # GIN index for full-text search
    op.execute("""
        CREATE INDEX IF NOT EXISTS {index_name}
        ON {op_def['table']}
        USING GIN ({op_def['columns'][0]})
    """)
'''
                elif op_def['type'] == 'partial':
                    # Partial index requires raw SQL
                    migration_content += f'''    # Partial index with WHERE clause
    op.execute("""
        CREATE INDEX IF NOT EXISTS {index_name}
        ON {op_def['table']} ({', '.join(op_def['columns'])})
        WHERE {op_def['where']}
    """)
'''
                else:
                    # Standard index using Alembic op
                    migration_content += f'''    op.create_index('{index_name}', '{op_def['table']}', {op_def['columns']}, unique=False)
'''
    
    # Add downgrade function
    migration_content += f'''


def downgrade():
    # Drop indexes in reverse order
'''
    
    # Add index drop operations in reverse order
    for table in reversed(list(missing_indexes.keys())):
        for index_name in reversed(missing_indexes[table]):
            if index_name in index_operations:
                op_def = index_operations[index_name]
                # For GIN and partial indexes, use raw SQL for drop too
                if op_def['type'] in ['gin', 'partial']:
                    migration_content += f'''    op.execute("DROP INDEX IF EXISTS {index_name}")
'''
                else:
                    migration_content += f'''    op.drop_index('{index_name}', table_name='{op_def['table']}')
'''
    
    # Write migration file
    migrations_dir = Path(__file__).parent.parent / 'db-migrations' / 'alembic' / 'versions'
    migrations_dir.mkdir(parents=True, exist_ok=True)
    
    migration_filename = f'{next_rev}_add_missing_performance_indexes.py'
    migration_path = migrations_dir / migration_filename
    
    with open(migration_path, 'w') as f:
        f.write(migration_content)
    
    print(f"\n✓ Generated Alembic migration: {migration_path}")
    print(f"  Revision: {next_rev}")
    print(f"  Down revision: {latest_rev}")
    print(f"\nTo apply the migration, run:")
    print(f"  alembic upgrade head")
    print(f"\nOr from the db-migrations directory:")
    print(f"  alembic -c alembic.ini upgrade head")

def create_indexes(engine, missing_indexes):
    """Create missing indexes directly (DEPRECATED - use --generate-migration instead)"""
    print("WARNING: Direct index creation bypasses Alembic version control!")
    print("Consider using --generate-migration instead.")
    
    index_sql = {
        'idx_welcomepage_users_auth_email': """
            CREATE INDEX IF NOT EXISTS idx_welcomepage_users_auth_email 
            ON welcomepage_users(auth_email);
        """,
        'idx_welcomepage_users_team_id': """
            CREATE INDEX IF NOT EXISTS idx_welcomepage_users_team_id 
            ON welcomepage_users(team_id);
        """,
        'idx_welcomepage_users_slack_user_id': """
            CREATE INDEX IF NOT EXISTS idx_welcomepage_users_slack_user_id 
            ON welcomepage_users(slack_user_id) 
            WHERE slack_user_id IS NOT NULL;
        """,
        'idx_welcomepage_users_team_draft': """
            CREATE INDEX IF NOT EXISTS idx_welcomepage_users_team_draft 
            ON welcomepage_users(team_id, is_draft);
        """,
        'idx_welcomepage_users_search_vector': """
            CREATE INDEX IF NOT EXISTS idx_welcomepage_users_search_vector 
            ON welcomepage_users USING GIN(search_vector);
        """,
        'idx_page_visits_visited_user_id': """
            CREATE INDEX IF NOT EXISTS idx_page_visits_visited_user_id 
            ON page_visits(visited_user_id);
        """,
        'idx_page_visits_visitor_public_id': """
            CREATE INDEX IF NOT EXISTS idx_page_visits_visitor_public_id 
            ON page_visits(visitor_public_id);
        """,
        'idx_page_visits_user_visitor': """
            CREATE INDEX IF NOT EXISTS idx_page_visits_user_visitor 
            ON page_visits(visited_user_id, visitor_public_id);
        """,
        'idx_verification_codes_email_used': """
            CREATE INDEX IF NOT EXISTS idx_verification_codes_email_used 
            ON verification_codes(email, used) 
            WHERE used = false;
        """,
    }
    
    with engine.begin() as conn:
        for table, missing_index_names in missing_indexes.items():
            for index_name in missing_index_names:
                if index_name in index_sql:
                    print(f"Creating index: {index_name}")
                    try:
                        conn.execute(text(index_sql[index_name]))
                        print(f"  ✓ Created {index_name}")
                    except Exception as e:
                        print(f"  ✗ Failed to create {index_name}: {e}")

def explain_query(engine, query, description):
    """Run EXPLAIN ANALYZE on a query"""
    print(f"\n{'='*60}")
    print(f"EXPLAIN ANALYZE: {description}")
    print(f"{'='*60}")
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"EXPLAIN ANALYZE {query}"))
            for row in result:
                print(row[0])
    except Exception as e:
        print(f"Error: {e}")

def detect_table_scan_patterns():
    """
    Detect potential table scan patterns in the codebase.
    Looks for patterns where code fetches all rows and filters in Python.
    """
    base_dir = Path(__file__).parent.parent
    patterns_found = []
    
    # Patterns to detect
    scan_patterns = [
        {
            'name': 'JSONB fetch all + Python filter',
            'pattern': r'\.filter\([^)]*\.(?:sharing_settings|slack_settings)\.isnot\(None\)\)\.all\(\)',
            'followup': r'for\s+\w+\s+in\s+\w+.*:\s*\n\s*[^\n]*\.get\(.*\)\s*==|\s*if\s+[^\n]*\.get\(.*\)\s*==',
            'severity': 'HIGH',
            'description': 'Fetches all rows with JSONB field, then filters in Python'
        },
        {
            'name': 'Query fetch all + loop with JSONB/dict access',
            'pattern': r'\.query\([^)]+\)\.(?:filter\([^)]*\))*\.all\(\)',
            'followup': r'for\s+\w+\s+in\s+\w+.*:\s*\n\s*[^\n]*\.(?:get\(|sharing_settings|slack_settings)',
            'severity': 'HIGH',
            'description': 'Fetches all rows from query, then loops and accesses JSONB/dict fields in Python'
        },
        {
            'name': 'Fetch all when first() would work',
            'pattern': r'\.query\([^)]+\)\.(?:filter\([^)]*\))*\.all\(\)',
            'followup': r'for\s+\w+\s+in\s+\w+.*:\s*\n\s*if\s+[^\n]*:\s*\n\s*(?:return\s+\w+|break)',
            'severity': 'MEDIUM',
            'description': 'Fetches all rows when only one result is needed (use .first() instead)'
        }
    ]
    
    # Directories to scan
    scan_dirs = [
        base_dir / 'api',
        base_dir / 'services',
    ]
    
    # Files to scan
    files_to_scan = []
    for scan_dir in scan_dirs:
        if scan_dir.exists():
            files_to_scan.extend(scan_dir.glob('*.py'))
    
    for file_path in files_to_scan:
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                lines = content.split('\n')
            
            # Check each pattern
            for pattern_def in scan_patterns:
                # Find all matches of the main pattern
                for match in re.finditer(pattern_def['pattern'], content, re.MULTILINE):
                    line_num = content[:match.start()].count('\n') + 1
                    
                    # Check if there's a followup pattern (Python-side filtering)
                    is_table_scan = False
                    if pattern_def['followup']:
                        # Look ahead in the code for the followup pattern (within next 20 lines)
                        remaining_lines = lines[line_num:line_num + 20]
                        remaining_content = '\n'.join(remaining_lines)
                        if re.search(pattern_def['followup'], remaining_content, re.MULTILINE | re.DOTALL):
                            is_table_scan = True
                    else:
                        # Pattern itself indicates a scan
                        is_table_scan = True
                    
                    if is_table_scan:
                        # Get context around the match
                        start_line = max(0, line_num - 3)
                        end_line = min(len(lines), line_num + 15)
                        context = '\n'.join(lines[start_line:end_line])
                        
                        # Check if this is a false positive
                        context_lower = context.lower()
                        
                        # Skip pagination patterns
                        if any(keyword in context_lower for keyword in ['offset', 'limit', 'paginate', 'page_size']):
                            continue
                        
                        # Skip if it's in a comment
                        if '#' in lines[line_num - 1] and match.group(0) in lines[line_num - 1].split('#')[1]:
                            continue
                        
                        # Skip if it's not a database query (no .query() or .filter())
                        if 'db.query' not in context and 'self.db.query' not in context:
                            # Check if it's a list comprehension or other non-db pattern
                            if 'for ' in context and '.query' not in context:
                                # Might be iterating over a list, not a DB result
                                if not any(keyword in context for keyword in ['.all()', '.filter(', '.query(']):
                                    continue
                        
                        patterns_found.append({
                            'pattern': pattern_def['name'],
                            'file': str(file_path.relative_to(base_dir)),
                            'line': line_num,
                            'severity': pattern_def['severity'],
                            'description': pattern_def['description'],
                            'code': context,
                            'match': match.group(0)
                        })
        except Exception as e:
            # Skip files that can't be read
            continue
    
    # Remove duplicates (same file, same line)
    seen = set()
    unique_patterns = []
    for pattern in patterns_found:
        key = (pattern['file'], pattern['line'])
        if key not in seen:
            seen.add(key)
            unique_patterns.append(pattern)
    
    return unique_patterns

def run_sample_explains(engine):
    """Run EXPLAIN ANALYZE on sample queries"""
    # Get sample data
    with engine.connect() as conn:
        # Get a sample user
        user_result = conn.execute(text("""
            SELECT public_id, auth_email, team_id 
            FROM welcomepage.welcomepage_users 
            LIMIT 1;
        """))
        user_row = user_result.fetchone()
        
        if not user_row:
            print("No users found in database. Cannot run EXPLAIN ANALYZE.")
            return
        
        user_public_id = user_row[0]
        user_email = user_row[1]
        team_id = user_row[2]
        
        # Sample queries
        queries = [
            (
                f"SELECT * FROM welcomepage.welcomepage_users WHERE public_id = '{user_public_id}';",
                "User lookup by public_id"
            ),
            (
                f"SELECT * FROM welcomepage.welcomepage_users WHERE auth_email = '{user_email}';",
                "User lookup by auth_email"
            ),
        ]
        
        if team_id:
            queries.extend([
                (
                    f"SELECT * FROM welcomepage.welcomepage_users WHERE team_id = {team_id};",
                    "Users by team_id"
                ),
                (
                    f"SELECT COUNT(*) FROM welcomepage.welcomepage_users WHERE team_id = {team_id} AND is_draft = false;",
                    "Published count by team"
                ),
            ])
        
        for query, description in queries:
            explain_query(engine, query, description)

def main():
    parser = argparse.ArgumentParser(
        description='Check database indexes and generate Alembic migrations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Check indexes and see what's missing
  python scripts/check_indexes.py
  
  # Generate Alembic migration for missing indexes (recommended)
  python scripts/check_indexes.py --generate-migration
  
  # Run EXPLAIN ANALYZE on sample queries
  python scripts/check_indexes.py --explain
  
  # Detect table scan patterns (fetch all + Python filtering)
  python scripts/check_indexes.py --detect-scans
        '''
    )
    parser.add_argument('--create', action='store_true', 
                       help='[DEPRECATED] Create missing indexes directly (use --generate-migration instead)')
    parser.add_argument('--generate-migration', action='store_true',
                       help='Generate Alembic migration file for missing indexes (recommended)')
    parser.add_argument('--explain', action='store_true',
                       help='Run EXPLAIN ANALYZE on sample queries')
    parser.add_argument('--detect-scans', action='store_true',
                       help='Detect potential table scan patterns (fetch all + Python filtering)')
    
    args = parser.parse_args()
    
    # If only detecting scans, do that and exit
    if args.detect_scans:
        print("Table Scan Pattern Detector")
        print("=" * 60)
        print("\nScanning codebase for potential table scan patterns...")
        print("(Fetch all rows + Python-side filtering)\n")
        
        patterns = detect_table_scan_patterns()
        
        if patterns:
            print(f"⚠ Found {len(patterns)} potential table scan pattern(s):\n")
            for i, pattern in enumerate(patterns, 1):
                print(f"{'='*60}")
                print(f"Pattern {i}: {pattern['pattern']}")
                print(f"File: {pattern['file']}")
                print(f"Line: {pattern['line']}")
                print(f"Severity: {pattern['severity']}")
                print(f"\nCode context:")
                print("-" * 60)
                code_lines = pattern['code'].split('\n')
                start_line = pattern['line'] - 3  # We show 3 lines before
                for i, line in enumerate(code_lines):
                    actual_line = start_line + i + 1
                    marker = " >>> " if actual_line == pattern['line'] else "     "
                    print(f"{actual_line:4d}{marker}{line}")
                print("-" * 60)
                print()
            
            print("\n💡 Recommendations:")
            print("  - Replace Python-side filtering with PostgreSQL WHERE clauses")
            print("  - Use JSONB operators (->, ->>, @>) in SQL WHERE clauses")
            print("  - Add GIN indexes on JSONB columns for efficient lookups")
            print("  - Consider using .first() instead of .all() + loop if only one result needed")
        else:
            print("✓ No table scan patterns detected!")
        
        return
    
    print("Database Index Checker")
    print("=" * 60)
    
    engine = get_db_engine()
    
    # Get existing indexes from database
    print("\n1. Checking existing indexes in database...")
    db_indexes = get_existing_indexes(engine)
    
    # Get indexes from migration files
    print("2. Checking indexes in migration files...")
    migration_indexes = get_indexes_from_migrations()
    
    # Merge both sources
    existing_indexes = merge_index_sources(db_indexes, migration_indexes)
    
    print("\n3. Existing indexes (database + migrations):")
    for table, indexes in existing_indexes.items():
        print(f"\n{table}:")
        for idx in indexes:
            source = idx.get('source', 'unknown')
            print(f"  ✓ {idx['name']} ({source})")
    
    # Check for missing indexes
    print("\n4. Checking for missing critical indexes...")
    missing_indexes = check_missing_indexes(existing_indexes)
    
    if missing_indexes:
        print("\n⚠ Missing indexes:")
        for table, missing_index_names in missing_indexes.items():
            print(f"\n{table}:")
            for index_name in missing_index_names:
                print(f"  ✗ {index_name}")
    else:
        print("\n✓ All critical indexes exist!")
    
    # Run EXPLAIN ANALYZE if requested (regardless of missing indexes)
    if args.explain:
        print("\n5. Running EXPLAIN ANALYZE on sample queries...")
        run_sample_explains(engine)
        return  # Exit after explain, no need to continue
    
    # If no missing indexes and no explain requested, exit early
    if not missing_indexes and not args.explain:
        return
    
    # Generate Alembic migration if requested (recommended)
    if args.generate_migration:
        print("\n5. Generating Alembic migration file...")
        generate_alembic_migration(missing_indexes)
        return
    
    # Create indexes directly if requested (deprecated)
    if args.create and missing_indexes:
        print("\n5. Creating missing indexes directly...")
        create_indexes(engine, missing_indexes)
        
        # Update statistics
        print("\n6. Updating statistics...")
        with engine.begin() as conn:
            conn.execute(text("ANALYZE welcomepage_users;"))
            conn.execute(text("ANALYZE page_visits;"))
            conn.execute(text("ANALYZE verification_codes;"))
        print("✓ Statistics updated")
    
    # If no action taken, suggest generating migration
    if not args.create and not args.explain and missing_indexes:
        print("\n💡 Tip: Run with --generate-migration to create an Alembic migration file")
        print("   This ensures indexes are applied consistently across all environments.")

if __name__ == '__main__':
    main()

