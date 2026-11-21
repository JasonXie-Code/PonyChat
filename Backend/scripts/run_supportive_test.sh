#!/bin/bash
set -e
cd /opt/ponychat/Backend
pkill -9 -f test_supportive_matrix.py 2>/dev/null || true
sleep 1
/opt/ponychat/.venv/bin/python scripts/cleanup_test_users.py
rm -f /tmp/supportive_out.txt
nohup /opt/ponychat/.venv/bin/python -u scripts/test_supportive_matrix.py > /tmp/supportive_out.txt 2>&1 < /dev/null &
sleep 2
echo "PID=$!"
ps aux | grep test_supp | grep -v grep | wc -l
