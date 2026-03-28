"""
Database configuration for SQLite with WAL mode for concurrent access.
"""

from django.db.backends.sqlite3.base import DatabaseWrapper


def enable_wal_mode(connection):
    """
    Enable Write-Ahead Logging (WAL) mode for SQLite.
    This allows multiple readers and a single writer, improving concurrency.
    """
    # Check if this is a Django DatabaseWrapper (has vendor attribute) or raw connection
    # If it's a DatabaseWrapper, use it directly. If it's a raw connection, we need the wrapper.
    if hasattr(connection, 'vendor') and connection.vendor == 'sqlite3':
        with connection.cursor() as cursor:
            # Enable WAL mode
            cursor.execute('PRAGMA journal_mode=WAL;')
            # Set busy timeout to handle lock contention (30 seconds)
            cursor.execute('PRAGMA busy_timeout=30000;')
            # Optimize for concurrent access
            cursor.execute('PRAGMA synchronous=NORMAL;')
            # Increase cache size for better performance
            cursor.execute('PRAGMA cache_size=-64000;')  # 64MB cache


# Monkey patch the database connection to enable WAL mode
original_get_new_connection = DatabaseWrapper.get_new_connection


def get_new_connection_with_wal(self, conn_params):
    """Wrapper to enable WAL mode on new connections."""
    conn = original_get_new_connection(self, conn_params)
    enable_wal_mode(self)  # Pass self (DatabaseWrapper) not conn (raw connection)
    return conn


DatabaseWrapper.get_new_connection = get_new_connection_with_wal
