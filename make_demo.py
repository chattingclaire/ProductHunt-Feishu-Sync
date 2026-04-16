#!/usr/bin/env python3
"""Quick demo: run wokflow.py --once for ~45s, save cast + GIF."""
import subprocess, sys, time, json, os, signal

PROJECT = os.path.dirname(os.path.abspath(__file__))
CAST    = os.path.join(PROJECT, "assets", "demo.cast")
GIF     = os.path.join(PROJECT, "assets", "demo.gif")
SCRIPT  = os.path.join(PROJECT, "wokflow.py")
TIMEOUT = 45  # seconds — captures Stage 1 + first few Stage 2 products

os.makedirs(os.path.join(PROJECT, "assets"), exist_ok=True)

header = {
    "version": 2, "width": 120, "height": 35,
    "title": "ProductHunt Leaderboard → Feishu Bitable",
    "timestamp": int(time.time())
}
events = []
start  = time.time()

print(f"▶  Recording {TIMEOUT}s demo…\n")

proc = subprocess.Popen(
    [sys.executable, SCRIPT, "--once"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1, cwd=PROJECT
)

try:
    for line in proc.stdout:
        t = round(time.time() - start, 3)
        sys.stdout.write(line); sys.stdout.flush()
        events.append([t, "o", line.rstrip("\n") + "\r\n"])
        if t >= TIMEOUT:
            proc.send_signal(signal.SIGTERM)
            events.append([t + 0.2, "o", "\r\n… (truncated for demo)\r\n"])
            break
    proc.wait(timeout=5)
except Exception:
    proc.kill()

with open(CAST, "w") as f:
    f.write(json.dumps(header) + "\n")
    for e in events:
        f.write(json.dumps(e) + "\n")

print(f"\n✅  {len(events)} lines → {CAST}")
print("🎨  Converting to GIF…")

r = subprocess.run(
    ["agg", "--cols", "120", "--rows", "35", "--font-size", "13",
     "--speed", "3", "--idle-time-limit", "2", CAST, GIF],
    capture_output=True, text=True
)
if r.returncode == 0:
    size = os.path.getsize(GIF) // 1024
    print(f"✅  GIF saved → {GIF}  ({size} KB)")
else:
    print("❌  agg error:", r.stderr)
    sys.exit(1)
