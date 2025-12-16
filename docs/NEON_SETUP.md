# Neon Database Setup Guide

This guide explains how to set up and use Neon (serverless PostgreSQL) with the gift-wiki application.

## Why Neon?

Neon is perfect for this application because:
- **Free tier** with generous limits (0.5GB storage, 1 compute hour/day)
- **Serverless** - automatically scales and suspends when not in use
- **Perfect for low-traffic apps** - ideal for ~12 users with seasonal usage
- **Connection pooling** - handles multiple replicas efficiently
- **No infrastructure management** - fully managed PostgreSQL

## Setup Steps

### 1. Create a Neon Account

1. Go to [neon.tech](https://neon.tech)
2. Sign up for a free account
3. Create a new project

### 2. Get Connection Details

After creating your project, Neon will provide:
- **Host**: `your-project.neon.tech` (or similar)
- **Database name**: Usually `neondb` or `main`
- **User**: Your Neon username
- **Password**: Generated password (save it securely!)
- **Port**: `5432`

### 3. Configure Connection Pooling (Important!)

Neon requires connection pooling for serverless workloads. You have two options:

#### Option A: Transaction Pooler (Recommended)
- **Endpoint**: Use the pooler endpoint (usually `your-project-pooler.neon.tech`)
- **Port**: `5432`
- **Mode**: Transaction mode (default)
- **Best for**: Most Django applications

#### Option B: Session Pooler
- **Endpoint**: Use the session pooler endpoint
- **Port**: `6543`
- **Mode**: Session mode
- **Best for**: Applications requiring session-level features

### 4. Update Environment Variables

Set these in your Kubernetes secrets or config:

```bash
DJANGO_DB_HOST=your-project-pooler.neon.tech  # Use pooler endpoint!
DJANGO_DB_NAME=neondb
DJANGO_DB_USER=your-username
DJANGO_DB_PASSWORD=your-password
DJANGO_DB_PORT=5432
DJANGO_DB_POOLER_MODE=transaction  # Optional, for documentation
DJANGO_DB_CONN_MAX_AGE=600  # 10 minutes - good for serverless
```

### 5. Run Migrations

```bash
# Set environment variables first
export DJANGO_DB_HOST=your-project-pooler.neon.tech
export DJANGO_DB_NAME=neondb
export DJANGO_DB_USER=your-username
export DJANGO_DB_PASSWORD=your-password

# Run migrations
python manage.py migrate
```

### 6. Migrate Data from SQLite (if needed)

If you have existing SQLite data:

```bash
python manage.py migrate_sqlite_to_postgres --sqlite-path=db.sqlite3
```

## Caching Strategy

The application includes **in-memory caching** to reduce database queries and stay within Neon's free tier limits:

- **Home page**: Cached for 5 minutes (wishlists don't change frequently)
- **Query results**: Frequently accessed data is cached
- **Cache invalidation**: Automatically clears when data changes

This caching strategy:
- Reduces database connections
- Lowers compute usage
- Improves response times
- Helps stay within free tier limits

## Free Tier Limits

Neon's free tier includes:
- **Storage**: 0.5 GB
- **Compute**: 1 hour/day (auto-suspends after 5 minutes idle)
- **Branches**: 1 project branch
- **Connections**: Unlimited (with pooling)

For ~12 users with seasonal usage, this should be more than sufficient!

## Monitoring Usage

Monitor your Neon usage in the Neon dashboard:
- Check compute hours used
- Monitor storage usage
- View connection metrics

## Troubleshooting

### Connection Timeouts
- Ensure you're using the **pooler endpoint**, not the direct endpoint
- Check that `DJANGO_DB_CONN_MAX_AGE` is set appropriately (600 seconds recommended)

### Auto-suspend Issues
- First request after suspend may be slow (~2-3 seconds)
- This is normal for serverless - subsequent requests are fast
- Consider using a health check endpoint to keep it warm if needed

### Migration Issues
- Ensure all environment variables are set correctly
- Check that the database user has proper permissions
- Verify network connectivity to Neon

## Production Considerations

For production:
1. **Use connection pooling** (already configured)
2. **Enable caching** (already configured)
3. **Monitor usage** in Neon dashboard
4. **Set up alerts** for approaching limits
5. **Consider upgrading** if you exceed free tier (still very affordable)

## References

- [Neon Documentation](https://neon.tech/docs)
- [Neon Connection Pooling](https://neon.tech/docs/connect/connection-pooling)
- [Django PostgreSQL Settings](https://docs.djangoproject.com/en/stable/ref/settings/#databases)

