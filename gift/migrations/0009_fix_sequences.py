# Generated manually to fix PostgreSQL sequence values

from django.db import migrations


def fix_sequences(apps, schema_editor):
    """
    Fix PostgreSQL sequence values that may be out of sync with actual data.
    This can happen after manual data insertion or migrations from other databases.
    """
    db_alias = schema_editor.connection.alias
    
    # Only run on PostgreSQL
    if 'postgresql' not in schema_editor.connection.vendor:
        return
    
    # Get models from the historical state
    WishList = apps.get_model('gift', 'WishList')
    Item = apps.get_model('gift', 'Item')
    Category = apps.get_model('gift', 'Category')
    Family = apps.get_model('gift', 'Family')
    Suggestion = apps.get_model('gift', 'Suggestion')
    ScrapedWikiPage = apps.get_model('gift', 'ScrapedWikiPage')
    ScrapedWikiItem = apps.get_model('gift', 'ScrapedWikiItem')
    FeatureFlag = apps.get_model('gift', 'FeatureFlag')
    
    # List of models to fix sequences for
    models_to_fix = [
        WishList,
        Item,
        Category,
        Family,
        Suggestion,
        ScrapedWikiPage,
        ScrapedWikiItem,
        FeatureFlag,
    ]
    
    with schema_editor.connection.cursor() as cursor:
        for model in models_to_fix:
            # Get table name and primary key column from model meta
            table_name = model._meta.db_table
            pk_field = model._meta.pk
            pk_column = pk_field.column
            
            # Only fix sequences for integer primary keys
            if pk_field.get_internal_type() not in ('AutoField', 'BigAutoField'):
                continue
            
            sequence_name = f"{table_name}_{pk_column}_seq"
            
            try:
                # Get current max ID
                cursor.execute(f'SELECT MAX("{pk_column}") FROM "{table_name}"')
                max_id_row = cursor.fetchone()
                max_id = max_id_row[0] if max_id_row[0] is not None else 0
                
                # Check if sequence exists
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_class 
                        WHERE relname = %s
                    )
                """, [sequence_name])
                
                sequence_exists = cursor.fetchone()[0]
                
                if not sequence_exists:
                    # Sequence doesn't exist, skip
                    continue
                
                # Get current sequence value
                cursor.execute(f"SELECT last_value FROM {sequence_name}")
                current_seq_value = cursor.fetchone()[0]
                
                # Fix sequence if it's behind the max ID
                if current_seq_value < max_id:
                    new_seq_value = max_id + 1
                    cursor.execute(
                        f"SELECT setval(%s, %s, false)",
                        [sequence_name, new_seq_value]
                    )
                    print(f"Fixed {table_name}: sequence set from {current_seq_value} to {new_seq_value}")
                else:
                    print(f"{table_name}: sequence is correct (sequence: {current_seq_value}, max ID: {max_id})")
                    
            except Exception as e:
                # Log error but continue with other tables
                print(f"Warning: Could not fix sequence for {table_name}: {e}")
                continue


def reverse_fix_sequences(apps, schema_editor):
    """
    Reverse operation - nothing to do as we're just fixing sequences.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('gift', '0008_add_color_palette_to_user'),
    ]

    operations = [
        migrations.RunPython(fix_sequences, reverse_fix_sequences),
    ]
