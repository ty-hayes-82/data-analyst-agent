# VPS Web App Troubleshooting Plan

## Problem
Uvicorn starts successfully inside the `swoop-agent` Docker container (host networking mode) on VPS 2 (`187.124.147.182`), logs "Application startup complete", and `ss -tlnp` shows port 8080 listening — but all HTTP connections (curl, wget, Python urllib) time out. No connection attempts appear in server logs.

## Environment
- **VPS:** `root@187.124.147.182`
- **Container:** `swoop-agent` (host network mode)
- **Python:** 3.13.5
- **Uvicorn:** 0.42.0
- **App:** FastAPI (`web.app:app`)
- **Port:** 8080

## What We Know
1. `list_datasets()` and `from web.app import app` both work fine when called directly
2. Basic Python socket server (bind/listen/accept) works inside the container
3. Uvicorn starts, binds, and logs "running" — but never logs incoming connections
4. `curl` from both inside and outside the container times out (exit 28)
5. `connect_ex()` returns errno 11 (EAGAIN) — socket exists but won't accept
6. No firewall rules active (`iptables` policy ACCEPT, `ufw` inactive)
7. Container uses `--network host` — shares host network namespace

## Hypotheses (ordered by likelihood)

### H1: Async event loop dies after `nohup &` / `docker exec -d`
**Why:** `docker exec -d` detaches stdin/stdout. Uvicorn's asyncio event loop may stop polling after the parent shell exits. The socket stays bound (kernel-level) but `accept()` never runs.
**Test:**
```bash
# Run interactively (don't background) and test from another SSH session
ssh root@187.124.147.182
docker exec -it swoop-agent bash -c 'cd /data/data-analyst-agent && python3 -m uvicorn web.app:app --host 0.0.0.0 --port 8080'
# In a second terminal:
ssh root@187.124.147.182 "curl -s http://127.0.0.1:8080/health"
```
**Fix if confirmed:** Install `tmux` or `screen` in the container, or use a proper process manager (supervisord).

### H2: Python 3.13 asyncio regression with uvicorn 0.42
**Why:** Python 3.13 changed asyncio internals. Uvicorn 0.42 may have an incompatibility when backgrounded.
**Test:**
```bash
# Check if uvloop is installed (faster event loop, different codepath)
docker exec swoop-agent python3 -c "import uvloop; print(uvloop.__version__)"
# Try forcing asyncio loop
docker exec swoop-agent bash -c 'cd /data/data-analyst-agent && python3 -m uvicorn web.app:app --host 0.0.0.0 --port 8080 --loop asyncio'
# Try downgrading uvicorn
docker exec swoop-agent pip install uvicorn==0.30.0
```

### H3: Stale socket / zombie process holding the port
**Why:** Previous uvicorn processes weren't cleanly killed. The kernel keeps the socket in LISTEN state even after the process event loop is dead.
**Test:**
```bash
# Kill everything, wait for TIME_WAIT to clear
docker exec swoop-agent bash -c 'pkill -9 -f uvicorn; pkill -9 -f "python3.*web"'
sleep 5
ss -tlnp | grep 8080  # Should be empty
# Then start fresh
```

### H4: Container resource limits (cgroups / ulimits)
**Why:** Container may have restrictive ulimits on open files or connections.
**Test:**
```bash
docker exec swoop-agent bash -c 'ulimit -a'
docker inspect swoop-agent --format '{{json .HostConfig.Ulimits}}'
```

### H5: Import-time side effect blocking the event loop
**Why:** `from . import run_manager` or another import may start a background thread or acquire a lock that conflicts with asyncio.
**Test:**
```bash
# Create a minimal app and test
docker exec swoop-agent bash -c 'cat > /tmp/test_app.py << EOF
from fastapi import FastAPI
app = FastAPI()
@app.get("/health")
async def health():
    return {"status": "ok"}
EOF
cd /data/data-analyst-agent && python3 -m uvicorn test_app:app --host 0.0.0.0 --port 8081 --app-dir /tmp'
# Test from another terminal
curl http://127.0.0.1:8081/health
```

## Resolution Steps

### Step 1: Confirm H1 (interactive test)
Run uvicorn interactively in one SSH session, curl from another. If this works, the problem is backgrounding.

### Step 2: Install a process manager
```bash
docker exec swoop-agent pip install supervisor
# Or simpler: install tmux
docker exec swoop-agent apt-get update && apt-get install -y tmux
```

### Step 3: Create a proper startup script
```bash
# /data/data-analyst-agent/scripts/start_web.sh
#!/bin/bash
cd /data/data-analyst-agent
exec python3 -m uvicorn web.app:app --host 0.0.0.0 --port 8080 --log-level info
```
Run via tmux:
```bash
docker exec swoop-agent bash -c 'tmux new-session -d -s webapp "bash /data/data-analyst-agent/scripts/start_web.sh"'
```

### Step 4: Verify from outside
```bash
curl http://187.124.147.182:8080/health
curl http://187.124.147.182:8080/api/datasets
```

### Step 5: Fix dedup bug
The `ops_metrics_weekly` Tableau dataset is hidden because `csv/ops_metrics_weekly_validation` has the same `name` field and gets listed first. Fix: rename the CSV validation dataset's `name` field to something distinct.

## Pending After Web App Is Running
1. Re-run weekly brief with corrected KPIs (Rev/Order, Loaded % replacing truck_count-based ones)
2. Re-run monthly brief and validate
3. Confirm new derived KPIs appear correctly in briefs
4. Data quality: zero-value fields (truck_count, exprncd_drvr_cnt) need source-level fix
