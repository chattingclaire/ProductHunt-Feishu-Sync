#!/usr/bin/env python3
"""
Record a full demo GIF:
  Part 1 — Screen capture while DrissionPage scrapes PH product pages (real browser visible)
  Part 2 — Feishu Bitable preview (demo1.png + demo2.png, 4s each)
Output: assets/demo.gif
"""
import subprocess, sys, os, time, signal, shutil, json

PROJECT = os.path.dirname(os.path.abspath(__file__))
ASSETS  = os.path.join(PROJECT, "assets")
WOKFLOW = os.path.join(PROJECT, "wokflow.py")

SCREEN_MP4 = os.path.join(ASSETS, "_screen.mp4")
SLIDE_MP4  = os.path.join(ASSETS, "_slides.mp4")
CONCAT_MP4 = os.path.join(ASSETS, "_full.mp4")
GIF_OUT    = os.path.join(ASSETS, "demo.gif")
PALETTE    = os.path.join(ASSETS, "_palette.png")

SCREEN_SECS   = 35   # how long to record the browser
SLIDE_SECS    = 4    # seconds per Feishu screenshot
GIF_FPS       = 6
GIF_WIDTH     = 900   # px

os.makedirs(ASSETS, exist_ok=True)

# ── helpers ────────────────────────────────────────────────────────────────
def run(args, **kw):
    print("  $", " ".join(str(a) for a in args))
    return subprocess.run(args, **kw)

def ffmpeg(*args, **kw):
    return run(["ffmpeg", "-y", *args],
               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kw)

# ── Step 1: launch wokflow, wait for Stage 2 ───────────────────────────────
env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"

print("▶  Starting wokflow.py --once …")
wok = subprocess.Popen(
    [sys.executable, "-u", WOKFLOW, "--once"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1, env=env, cwd=PROJECT
)

screen_proc   = None
screen_start  = None
lines_seen    = 0

print("   Waiting for DrissionPage Stage 2 …")

for line in wok.stdout:
    sys.stdout.write("  | " + line); sys.stdout.flush()
    lines_seen += 1

    # DrissionPage is about to open the browser
    if screen_proc is None and "Starting to augment" in line:
        print("\n🎬  DrissionPage started — beginning screen capture …\n")
        screen_proc = subprocess.Popen([
            "ffmpeg", "-y",
            "-f", "avfoundation",
            "-framerate", "10",
            "-capture_cursor", "1",
            "-i", "4",          # 'Capture screen 0'
            "-t", str(SCREEN_SECS),
            "-vf", f"scale={GIF_WIDTH}:-2",
            "-c:v", "libx264", "-preset", "fast", "-crf", "28",
            SCREEN_MP4
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        screen_start = time.time()

    # Stop after SCREEN_SECS of browser recording
    if screen_start and (time.time() - screen_start) >= SCREEN_SECS:
        print("\n⏹  Screen recording window done — stopping sync …")
        wok.send_signal(signal.SIGTERM)
        break

wok.wait(timeout=10)

if screen_proc is None:
    print("❌  Never reached Stage 2 — check wokflow output above.")
    sys.exit(1)

print("⏳  Waiting for ffmpeg screen capture to finish …")
screen_proc.wait(timeout=SCREEN_SECS + 10)

if not os.path.exists(SCREEN_MP4) or os.path.getsize(SCREEN_MP4) < 10_000:
    print("❌  Screen capture file missing or too small.")
    print("    Make sure Terminal has Screen Recording permission in")
    print("    System Settings → Privacy & Security → Screen Recording")
    sys.exit(1)

print(f"✅  Screen capture: {os.path.getsize(SCREEN_MP4)//1024} KB")

# ── Step 2: build Feishu slideshow ─────────────────────────────────────────
slide_inputs = []
for i, img in enumerate(["demo1.png", "demo2.png"]):
    src  = os.path.join(ASSETS, img)
    dest = os.path.join(ASSETS, f"_slide{i}.mp4")
    r = ffmpeg(
        "-loop", "1", "-i", src,
        "-t", str(SLIDE_SECS),
        "-vf", f"scale={GIF_WIDTH}:-2,format=yuv420p",
        "-c:v", "libx264", "-preset", "fast", "-crf", "28",
        dest
    )
    if r.returncode != 0:
        print(f"❌  Failed to create slide from {img}:", r.stderr.decode())
        sys.exit(1)
    slide_inputs.append(dest)

# ── Step 3: concatenate screen + slides ────────────────────────────────────
concat_list = os.path.join(ASSETS, "_concat.txt")
with open(concat_list, "w") as f:
    f.write(f"file '{SCREEN_MP4}'\n")
    for s in slide_inputs:
        f.write(f"file '{s}'\n")

r = ffmpeg(
    "-f", "concat", "-safe", "0", "-i", concat_list,
    "-c", "copy",
    CONCAT_MP4
)
if r.returncode != 0:
    # concat copy can fail if pixel formats differ — re-encode
    r = ffmpeg(
        "-f", "concat", "-safe", "0", "-i", concat_list,
        "-vf", f"scale={GIF_WIDTH}:-2,format=yuv420p",
        "-c:v", "libx264", "-preset", "fast", "-crf", "28",
        CONCAT_MP4
    )
    if r.returncode != 0:
        print("❌  Concatenation failed:", r.stderr.decode())
        sys.exit(1)

print(f"✅  Concatenated: {os.path.getsize(CONCAT_MP4)//1024} KB")

# ── Step 4: video → GIF (two-pass palette for quality) ─────────────────────
print("🎨  Converting to GIF …")

# Re-encode to yuv420p first (screen capture may be yuv422p)
CONV_MP4 = os.path.join(ASSETS, "_conv.mp4")
ffmpeg("-i", CONCAT_MP4,
       "-vf", f"fps={GIF_FPS},scale={GIF_WIDTH}:-2:flags=lanczos,format=yuv420p",
       "-c:v", "libx264", "-preset", "fast", "-crf", "28", CONV_MP4)

vf_gen = f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos,palettegen=stats_mode=diff"
vf_use = f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5"

ffmpeg("-i", CONV_MP4, "-vf", vf_gen, PALETTE)

if not os.path.exists(PALETTE):
    print("❌  Palette generation failed.")
    sys.exit(1)

r = ffmpeg("-i", CONV_MP4, "-i", PALETTE,
           "-filter_complex", vf_use, GIF_OUT)
if r.returncode != 0:
    print("❌  GIF conversion failed:", r.stderr.decode())
    sys.exit(1)

size = os.path.getsize(GIF_OUT) // 1024
print(f"✅  GIF saved → {GIF_OUT}  ({size} KB)")

# ── cleanup temp files ──────────────────────────────────────────────────────
for f in [SCREEN_MP4, SLIDE_MP4, CONCAT_MP4, CONV_MP4, PALETTE, concat_list,
          os.path.join(ASSETS, "_slide0.mp4"),
          os.path.join(ASSETS, "_slide1.mp4")]:
    try: os.remove(f)
    except FileNotFoundError: pass

print("🏁  Done!")
