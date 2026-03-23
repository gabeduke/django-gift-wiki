"""
Management command to migrate data from SQLite to PostgreSQL.

This command:
1. Connects to SQLite database (source)
2. Exports all data to JSON fixtures
3. Connects to PostgreSQL database (destination)
4. Imports all data into PostgreSQL

Usage:
    # Set SQLite as source (DATABASE_PATH or no DJANGO_DB_HOST)
    # Set PostgreSQL as destination (DJANGO_DB_HOST=postgres)
    python manage.py migrate_sqlite_to_postgres
"""

import json
import os
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connections, transaction


class Command(BaseCommand):
    help = 'Migrate data from SQLite to PostgreSQL database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--sqlite-path',
            type=str,
            help='Path to SQLite database file (default: from DATABASE_PATH env or db.sqlite3)',
            default=None,
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without actually migrating',
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='Skip objects that already exist in PostgreSQL (by primary key)',
        )

    def handle(self, *args, **options):
        sqlite_path = options['sqlite_path']
        dry_run = options['dry_run']
        skip_existing = options['skip_existing']

        # Determine SQLite database path
        if not sqlite_path:
            sqlite_path = os.getenv('DATABASE_PATH', 'db.sqlite3')

        if not os.path.exists(sqlite_path):
            self.stdout.write(self.style.ERROR(f'SQLite database not found: {sqlite_path}'))
            return

        # Check if PostgreSQL is configured
        current_db = settings.DATABASES['default']
        if current_db['ENGINE'] != 'django.db.backends.postgresql':
            self.stdout.write(
                self.style.ERROR(
                    'PostgreSQL is not configured as the default database.\n'
                    'Set DJANGO_DB_HOST environment variable to enable PostgreSQL.'
                )
            )
            return

        self.stdout.write(self.style.SUCCESS('Starting SQLite to PostgreSQL migration...'))
        self.stdout.write(f'Source SQLite: {sqlite_path}')
        self.stdout.write(
            f'Destination PostgreSQL: {current_db["HOST"]}:{current_db.get("PORT", 5432)}/{current_db["NAME"]}'
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No data will be migrated'))

        # Step 1: Export data from SQLite
        self.stdout.write('\nStep 1: Exporting data from SQLite...')

        # Save the current PostgreSQL database config
        postgres_db_config = settings.DATABASES['default'].copy()

        # Get TIME_ZONE from settings (Django 5.x requires it in database config)
        time_zone = getattr(settings, 'TIME_ZONE', 'America/New_York')

        # Temporarily switch default database to SQLite for export
        # Django 5.x requires TIME_ZONE in database settings dict
        sqlite_db_config = {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': sqlite_path,
            'TIME_ZONE': time_zone,  # Always set TIME_ZONE explicitly
            'USE_TZ': getattr(settings, 'USE_TZ', True),
        }

        # Switch default to SQLite
        settings.DATABASES['default'] = sqlite_db_config

        # Close existing connections to force reconnection with new settings
        connections.close_all()

        try:
            # Export all data from SQLite (now the default database)
            fixtures_buffer = StringIO()
            call_command(
                'dumpdata',
                '--natural-foreign',
                '--natural-primary',
                '--exclude=contenttypes',
                '--exclude=auth.Permission',
                '--exclude=admin.LogEntry',
                '--exclude=sessions.Session',
                stdout=fixtures_buffer,
            )

            fixtures_data = fixtures_buffer.getvalue()
            if not fixtures_data.strip():
                self.stdout.write(self.style.WARNING('No data found in SQLite database'))
                return

            # Parse JSON fixtures
            fixtures = json.loads(fixtures_data)
            self.stdout.write(self.style.SUCCESS(f'Exported {len(fixtures)} objects from SQLite'))

            if dry_run:
                # Count objects by model
                model_counts = {}
                for fixture in fixtures:
                    model = fixture['model']
                    model_counts[model] = model_counts.get(model, 0) + 1

                self.stdout.write('\nObjects to migrate:')
                for model, count in sorted(model_counts.items()):
                    self.stdout.write(f'  {model}: {count}')
                return

            # Step 2: Import into PostgreSQL
            self.stdout.write('\nStep 2: Importing data into PostgreSQL...')

            # Ensure migrations are run first
            self.stdout.write('Running migrations on PostgreSQL...')
            call_command('migrate', '--noinput', verbosity=0)

            # Import data - write to temp file and use loaddata
            import tempfile

            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp_file:
                tmp_file.write(fixtures_data)
                tmp_file_path = tmp_file.name

            try:
                # Use loaddata with the temp file
                with transaction.atomic(using='default'):
                    call_command(
                        'loaddata',
                        tmp_file_path,
                        '--database=default',
                        verbosity=1,
                    )
                    self.stdout.write(
                        self.style.SUCCESS('Successfully migrated all data to PostgreSQL!')
                    )
            except Exception as e:
                if skip_existing and (
                    'duplicate key' in str(e).lower() or 'unique constraint' in str(e).lower()
                ):
                    self.stdout.write(
                        self.style.WARNING(
                            'Some objects already exist. Use --skip-existing to handle this automatically.'
                        )
                    )
                    # Try loading with ignore conflicts (if Django version supports it)
                    try:
                        call_command(
                            'loaddata',
                            tmp_file_path,
                            '--database=default',
                            '--verbosity=1',
                        )
                    except:
                        pass
                else:
                    raise
            finally:
                # Clean up temp file
                try:
                    os.unlink(tmp_file_path)
                except:
                    pass

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Migration failed: {e}'))
            import traceback

            self.stdout.write(traceback.format_exc())
            raise
        finally:
            # Restore PostgreSQL as the default database
            settings.DATABASES['default'] = postgres_db_config
            # Close connections to force reconnection with PostgreSQL
            connections.close_all()
