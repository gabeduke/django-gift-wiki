# /debug — Cloud Run Debugging Guide

Use this skill when investigating errors, slow requests, or unexpected behavior in the giftwiki dev or prod environment.

---

## 1. Check recent logs

```bash
# Tail logs for dev
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="giftwiki-dev"' \
  --project=wikileet --freshness=10m \
  --format='value(timestamp,severity,textPayload)' | head -40

# Filter for errors only
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="giftwiki-dev" AND severity>=ERROR' \
  --project=wikileet --freshness=1h \
  --format='value(timestamp,textPayload)'
```

## 2. Find the trace for a specific request

```bash
# Get trace ID + latency for recent page loads
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="giftwiki-dev" AND httpRequest.requestMethod="GET"' \
  --project=wikileet --limit=5 \
  --format='value(trace,httpRequest.requestUrl,httpRequest.latency,httpRequest.status)'
```

## 3. Pull all logs for a trace (errors + app logs + DB spans)

```bash
TRACE_ID="<id from above, without projects/wikileet/traces/ prefix>"
gcloud logging read \
  "trace=\"projects/wikileet/traces/${TRACE_ID}\"" \
  --project=wikileet \
  --format='table(timestamp,severity,textPayload)'
```

## 4. View the trace waterfall (Django view + DB queries)

```
https://console.cloud.google.com/traces/list?project=wikileet
```

Click a trace to see the full waterfall: Django middleware → view handler → individual SELECT/UPDATE spans with timing.

**Jump to a specific trace:**
```
https://console.cloud.google.com/traces/list?project=wikileet&tid=TRACE_ID_HERE
```

## 5. Check current revision and startup health

```bash
# Latest revisions
gcloud run revisions list --service=giftwiki-dev --project=wikileet --region=us-east1 \
  --format='table(name,status.conditions[0].status,metadata.creationTimestamp)' | head -5

# Startup logs for latest revision
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="giftwiki-dev" AND textPayload=~"Starting|Failed|Error|OpenTelemetry|Cloud Logging"' \
  --project=wikileet --freshness=30m \
  --format='value(timestamp,textPayload)'
```

**Healthy startup looks like:**
```
Starting Gunicorn on 0.0.0.0:8080...
[INFO] Starting gunicorn 23.0.0
```
No `Failed to setup OpenTelemetry` or `Failed to setup Cloud Logging` lines.

## 6. Test the health endpoint

```bash
SERVICE_URL=$(gcloud run services describe giftwiki-dev --region us-east1 --project=wikileet --format='value(status.url)')
curl ${SERVICE_URL}/health/
```

---

## How tracing works

Cloud Run injects `X-Cloud-Trace-Context` on every request. OTel (configured in `giftwiki/wsgi.py`) reads this via `CloudTraceFormatPropagator` and emits child spans for Django view handling and every DB query via psycopg2 instrumentation. `google-cloud-logging` attaches trace context to all structured log entries, enabling trace↔log correlation.

**Only active when:** `DJANGO_ENVIRONMENT=prod` or `dev`.

**"Missing span" at top of waterfall** — normal. It's Cloud Run's internal load balancer span, not exported to Cloud Trace.

---

## Common issues

| Symptom | Check |
|---|---|
| `Failed to setup OpenTelemetry` | OTel packages missing from `requirements.txt` |
| `Failed to setup Cloud Logging` | `google-cloud-logging` missing from `requirements.txt` |
| No DB spans in trace | `opentelemetry-instrumentation-psycopg2` not installed or `DJANGO_ENVIRONMENT` not set |
| Spans not linked to Cloud Run trace | `opentelemetry-propagator-gcp` missing from `requirements.txt` |
| 500 errors | Check `severity>=ERROR` logs; look for DB connection failures or migration errors |
| Container won't start | Check entrypoint logs for migration failure or DB connection test failure |
