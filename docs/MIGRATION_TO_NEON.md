# Migration from SQLite to Neon - Step by Step Guide

This guide walks you through the safe migration from SQLite (StatefulSet) to Neon PostgreSQL (Deployment).

## Architecture Overview

- **StatefulSet** (`wikileet`): Scaled to 0, kept for rollback. Uses SQLite on PVC `wikileet-db`
- **Deployment** (`wikileet`): Active deployment using Neon PostgreSQL. Supports multiple replicas
- **Service** (`wikileet`): Routes to both (but StatefulSet is scaled to 0, so only Deployment receives traffic)
- **Migration Job**: Migrates data from SQLite PVC to Neon

## Migration Steps

### 1. Verify Current State

Check that StatefulSet is running and has data:
```bash
# Check StatefulSet status
kubectl get statefulset wikileet -n <namespace>

# Check if there's data in SQLite
kubectl exec -it wikileet-0 -n <namespace> -- ls -lh /app/db/db.sqlite3
```

### 2. Scale Down StatefulSet

The StatefulSet is already configured to scale to 0, but verify:
```bash
kubectl scale statefulset wikileet --replicas=0 -n <namespace>
```

Or apply the updated manifest:
```bash
kubectl apply -k deploy/dev  # or deploy/prod
```

### 3. Run Migration Job

The migration job will:
1. Wait for Neon to be ready
2. Run Django migrations on Neon (create schema)
3. Migrate all data from SQLite to Neon

**For Dev:**
```bash
# Ensure config.env and secrets.env are updated with Neon dev branch details
kubectl apply -f deploy/base/migrate-sqlite-to-postgres-job.yaml -n wikileet-dev

# Watch the job
kubectl logs -f job/migrate-sqlite-to-postgres -n wikileet-dev
```

**For Prod:**
```bash
# Ensure config.env and secrets.env are updated with Neon main branch details
kubectl apply -f deploy/base/migrate-sqlite-to-postgres-job.yaml -n wikileet

# Watch the job
kubectl logs -f job/migrate-sqlite-to-postgres -n wikileet
```

### 4. Verify Migration

Check that data was migrated:
```bash
# Connect to Neon and verify tables
# Use the connection string from Neon dashboard or:
kubectl run -it --rm postgres-client --image=postgres:16-alpine --restart=Never -- \
  psql "postgresql://neondb_owner:<password>@<neon-host>/neondb?sslmode=require"

# In psql:
\dt  # List tables
SELECT COUNT(*) FROM gift_wishlist;
SELECT COUNT(*) FROM gift_item;
```

### 5. Deploy New Deployment

Deploy the new Deployment that uses Neon:
```bash
skaffold run --profile=dev   # or --profile=prod
```

Or manually:
```bash
kubectl apply -k deploy/dev  # or deploy/prod
```

### 6. Verify Deployment

Check that the Deployment is running and healthy:
```bash
# Check Deployment status
kubectl get deployment wikileet -n <namespace>

# Check pods
kubectl get pods -l app=wikileet -n <namespace>

# Check logs
kubectl logs -l app=wikileet -n <namespace> --tail=50

# Test the application
curl https://giftwiki-dev.leetserve.com/health/  # or prod URL
```

### 7. Monitor and Test

- Test all application features
- Verify data is accessible
- Check performance metrics
- Monitor Neon dashboard for connection/usage

## Rollback Procedure

If you need to rollback to SQLite:

### Quick Rollback

1. **Scale down Deployment:**
   ```bash
   kubectl scale deployment wikileet --replicas=0 -n <namespace>
   ```

2. **Scale up StatefulSet:**
   ```bash
   kubectl scale statefulset wikileet --replicas=1 -n <namespace>
   ```

3. **Verify StatefulSet is running:**
   ```bash
   kubectl get pods -l app=wikileet -n <namespace>
   kubectl logs -l app=wikileet -n <namespace>
   ```

### Full Rollback (if data needs to be restored)

If you need to restore SQLite data from backup:
1. Scale down Deployment
2. Scale up StatefulSet
3. Restore SQLite database from backup to PVC
4. Verify application works

## Cleanup (After Successful Migration)

Once you're confident the migration is successful and stable:

1. **Keep StatefulSet scaled to 0** (for emergency rollback)
2. **Keep PVC** (contains original SQLite data as backup)
3. **Optional: Delete StatefulSet** (only after extended period of stability):
   ```bash
   kubectl delete statefulset wikileet -n <namespace>
   # Keep PVC for backup: kubectl delete pvc wikileet-db -n <namespace>
   ```

## Troubleshooting

### Migration Job Fails

1. **Check Neon connection:**
   ```bash
   kubectl logs job/migrate-sqlite-to-postgres -n <namespace>
   ```

2. **Verify environment variables:**
   ```bash
   kubectl get configmap django-app-config -n <namespace> -o yaml
   kubectl get secret django-app-secrets -n <namespace> -o yaml
   ```

3. **Check SQLite PVC:**
   ```bash
   kubectl get pvc wikileet-db -n <namespace>
   ```

### Deployment Won't Start

1. **Check initContainer logs:**
   ```bash
   kubectl describe pod <pod-name> -n <namespace>
   kubectl logs <pod-name> -c migrate -n <namespace>
   ```

2. **Verify Neon connection:**
   - Check connection string in config
   - Test connection from pod
   - Check Neon dashboard for connection issues

### Data Missing After Migration

1. **Check migration job logs** for errors
2. **Verify data in Neon:**
   ```bash
   # Connect to Neon and query tables
   ```
3. **If needed, re-run migration** (may need to clear Neon first)

## Post-Migration Checklist

- [ ] Migration job completed successfully
- [ ] Deployment running with 2+ replicas
- [ ] Application accessible and functional
- [ ] All data visible in application
- [ ] Performance acceptable
- [ ] Monitoring/alerting configured
- [ ] StatefulSet scaled to 0 (kept for rollback)
- [ ] Team notified of migration completion
- [ ] Documentation updated

## Benefits After Migration

✅ **Multiple replicas** - High availability  
✅ **Connection pooling** - Efficient database usage  
✅ **Auto-scaling** - Neon handles load automatically  
✅ **No PVC dependency** - Stateless pods  
✅ **Better performance** - PostgreSQL optimizations  
✅ **Free tier friendly** - Caching reduces queries  

