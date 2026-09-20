#!/bin/sh
set -eu

# The Fly volume is mounted at /data and can initially be owned by root.
mkdir -p /data/scans /data/models /data/jobs
chown spatial:spatial /data/scans /data/models /data/jobs

gosu spatial python /worker/container_worker.py &
worker_pid=$!
gosu spatial uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 &
api_pid=$!

shutdown() {
  kill "$api_pid" "$worker_pid" 2>/dev/null || true
  wait "$api_pid" "$worker_pid" 2>/dev/null || true
}
trap shutdown TERM INT

# Exit if either required process stops; Fly can then restart the Machine.
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null; do
  sleep 2 &
  wait $!
done
shutdown
exit 1
