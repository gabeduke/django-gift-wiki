# Neon Database Setup - Complete ✅

## Project Created

**Project ID**: `polished-bonus-40156660`  
**Project Name**: `gift-wiki`

## Branches Configured

### Production (main)
- **Branch ID**: `br-purple-wildflower-aeqtui8u`
- **Branch Name**: `main`
- **Connection Host**: `ep-falling-morning-ae2u6rxv-pooler.c-2.us-east-2.aws.neon.tech`
- **Database**: `neondb`
- **User**: `neondb_owner`
- **Password**: `npg_7kM0YQBZlmnp` (stored in `deploy/prod/secrets.env`)

### Development (dev)
- **Branch ID**: `br-misty-art-aeswki0g`
- **Branch Name**: `dev`
- **Connection Host**: `ep-floral-paper-aenqf3t7-pooler.c-2.us-east-2.aws.neon.tech`
- **Database**: `neondb`
- **User**: `neondb_owner`
- **Password**: `npg_7kM0YQBZlmnp` (stored in `deploy/dev/secrets.env`)

## Configuration Updated

### Dev Environment (`deploy/dev/`)
- ✅ `config.env` - Updated with Neon dev branch connection
- ✅ `secrets.env` - Updated with Neon credentials

### Prod Environment (`deploy/prod/`)
- ✅ `config.env` - Updated with Neon main branch connection
- ✅ `secrets.env` - Updated with Neon credentials

## Next Steps

### 1. Run Migrations

Migrations will run automatically via the initContainer when you deploy, but you can also run them manually:

**For Dev:**
```bash
export DJANGO_DB_HOST=ep-floral-paper-aenqf3t7-pooler.c-2.us-east-2.aws.neon.tech
export DJANGO_DB_NAME=neondb
export DJANGO_DB_USER=neondb_owner
export DJANGO_DB_PASSWORD=npg_7kM0YQBZlmnp
export DJANGO_DB_PORT=5432

python manage.py migrate
```

**For Prod:**
```bash
export DJANGO_DB_HOST=ep-falling-morning-ae2u6rxv-pooler.c-2.us-east-2.aws.neon.tech
export DJANGO_DB_NAME=neondb
export DJANGO_DB_USER=neondb_owner
export DJANGO_DB_PASSWORD=npg_7kM0YQBZlmnp
export DJANGO_DB_PORT=5432

python manage.py migrate
```

### 2. Migrate Data from SQLite (if needed)

If you have existing SQLite data to migrate:

```bash
# Set the Neon connection variables first (as above)
python manage.py migrate_sqlite_to_postgres --sqlite-path=db.sqlite3
```

### 3. Deploy

The StatefulSet is already configured to:
- ✅ Use Neon connection (via environment variables)
- ✅ Run migrations automatically in initContainer
- ✅ Support multiple replicas (set to 2)
- ✅ Use connection pooling (via pooler endpoints)

Deploy with:
```bash
skaffold run --profile=dev  # or --profile=prod
```

## Connection Details

### Full Connection Strings

**Dev:**
```
postgresql://neondb_owner:npg_7kM0YQBZlmnp@ep-floral-paper-aenqf3t7-pooler.c-2.us-east-2.aws.neon.tech/neondb?channel_binding=require&sslmode=require
```

**Prod:**
```
postgresql://neondb_owner:npg_7kM0YQBZlmnp@ep-falling-morning-ae2u6rxv-pooler.c-2.us-east-2.aws.neon.tech/neondb?channel_binding=require&sslmode=require
```

## Features Enabled

✅ **Connection Pooling** - Using Neon pooler endpoints (transaction mode)  
✅ **In-Memory Caching** - Reduces database queries  
✅ **Multiple Replicas** - Can scale to 2+ instances  
✅ **Auto-Migrations** - Runs via initContainer on deploy  
✅ **Branch Isolation** - Separate dev and prod databases  

## Monitoring

- View your Neon project: https://console.neon.tech/app/projects/polished-bonus-40156660
- Monitor usage, connections, and performance in the Neon dashboard
- Free tier includes: 0.5GB storage, 1 compute hour/day

## Security Notes

⚠️ **Important**: The database password is stored in `secrets.env` files. These should be:
- Added to `.gitignore` if not already
- Managed via Kubernetes secrets in production
- Rotated periodically for security

## Troubleshooting

### Connection Issues
- Verify you're using the **pooler endpoint** (ends with `-pooler`)
- Check that all environment variables are set correctly
- Ensure network connectivity to Neon

### Migration Issues
- Ensure the database user has proper permissions
- Check that the database `neondb` exists (it's created by default)
- Verify connection string format

### Performance
- First request after auto-suspend may be slow (~2-3 seconds)
- Subsequent requests are fast
- Caching helps reduce database load

