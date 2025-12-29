"""
Management command to fix PostgreSQL sequence values for primary keys.

This command fixes sequences that are out of sync with actual data,
which can happen after manual data insertion or migrations.

Usage:
    python manage.py fix_sequences
    python manage.py fix_sequences --app gift --model WishList
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django.apps import apps


class Command(BaseCommand):
    help = 'Fix PostgreSQL sequence values for primary keys'

    def add_arguments(self, parser):
        parser.add_argument(
            '--app',
            type=str,
            help='Specific app to fix sequences for (e.g., "gift")',
            default=None,
        )
        parser.add_argument(
            '--model',
            type=str,
            help='Specific model to fix sequence for (e.g., "WishList")',
            default=None,
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without actually fixing',
        )

    def handle(self, *args, **options):
        app_name = options.get('app')
        model_name = options.get('model')
        dry_run = options.get('dry_run', False)

        if app_name and model_name:
            # Fix specific model
            try:
                model = apps.get_model(app_name, model_name)
                self.fix_model_sequence(model, dry_run)
            except LookupError:
                self.stdout.write(
                    self.style.ERROR(f'Model {app_name}.{model_name} not found')
                )
        elif app_name:
            # Fix all models in app
            try:
                app_config = apps.get_app_config(app_name)
                for model in app_config.get_models():
                    self.fix_model_sequence(model, dry_run)
            except LookupError:
                self.stdout.write(
                    self.style.ERROR(f'App {app_name} not found')
                )
        else:
            # Fix all models
            for app_config in apps.get_app_configs():
                # Skip Django's built-in apps
                if app_config.name.startswith('django.'):
                    continue
                for model in app_config.get_models():
                    self.fix_model_sequence(model, dry_run)

    def fix_model_sequence(self, model, dry_run=False):
        """Fix the sequence for a specific model."""
        # Get the primary key field
        pk_field = model._meta.pk
        
        # Only fix sequences for integer primary keys
        if not hasattr(pk_field, 'get_internal_type'):
            return
        
        if pk_field.get_internal_type() not in ('AutoField', 'BigAutoField'):
            return
        
        # Get table name
        table_name = model._meta.db_table
        
        # Get sequence name (PostgreSQL convention)
        sequence_name = f"{table_name}_{pk_field.column}_seq"
        
        with connection.cursor() as cursor:
            # Get current max ID
            cursor.execute(f"SELECT MAX({pk_field.column}) FROM {table_name}")
            max_id_row = cursor.fetchone()
            max_id = max_id_row[0] if max_id_row[0] is not None else 0
            
            # Get current sequence value
            try:
                cursor.execute(
                    f"SELECT last_value FROM {sequence_name}"
                )
                current_seq_value = cursor.fetchone()[0]
            except Exception as e:
                # Sequence might not exist or we don't have permission
                self.stdout.write(
                    self.style.WARNING(
                        f"Could not read sequence {sequence_name} for {model._meta.label}: {e}"
                    )
                )
                return
            
            # Check if sequence needs fixing
            if current_seq_value < max_id:
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[DRY RUN] Would fix {model._meta.label}: "
                            f"sequence at {current_seq_value}, max ID is {max_id}"
                        )
                    )
                else:
                    # Set sequence to max_id + 1
                    new_seq_value = max_id + 1
                    try:
                        cursor.execute(
                            f"SELECT setval('{sequence_name}', {new_seq_value}, false)"
                        )
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Fixed {model._meta.label}: "
                                f"sequence set from {current_seq_value} to {new_seq_value}"
                            )
                        )
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"Error fixing sequence for {model._meta.label}: {e}"
                            )
                        )
            else:
                # Sequence is already correct or ahead
                if current_seq_value > max_id:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"{model._meta.label}: sequence is correct "
                            f"(sequence: {current_seq_value}, max ID: {max_id})"
                        )
                    )

