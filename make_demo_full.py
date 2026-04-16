#!/usr/bin/env python3
"""
Full demo GIF (three parts played sequentially):
  Part 1 — Terminal output  (from assets/demo.cast, Stage 1 + Stage 2 start)
  Part 2 — Browser window   (DrissionPage scraping, cropped to Chrome window only)
  Part 3 — Feishu preview   (demo1.png + demo2.png, 4 s each)
Output: assets/demo.gif

Strategy: normalize every segment to identical CFR at GIF_FPS before concat,
then concat with -c copy (guaranteed no timestamp drift), then two-pass palette GIF.
"""
import subprocess, sys, os, time, signal

PROJECT = os.path.dirname(os.path.abspath(__file__))
ASSETS  = os.path.join(PROJECT, "assets")
WOKFLOW = os.path.join(PROJECT, "wokflow.py")

CAST        = os.path.join(ASSETS, "demo.cast")
TERM_GIF    = os.path.join(ASSETS, "_terminal.gif")
TERM_MP4    = os.path.join(ASSETS, "_p1_terminal.mp4")
BROWSER_RAW = os.path.join(ASSETS, "_p2_raw.mp4")
BROWSER_MP4 = os.path.join(ASSETS, "_p2_browser.mp4")
SLIDE1_MP4  = os.path.join(ASSETS, "_p3a_slide.mp4")
SLIDE2_MP4  = os.path.join(ASSETS, "_p3b_slide.mp4")
CONCAT_MP4  = os.path.join(ASSETS, "_full.mp4")
PALETTE     = os.path.join(ASSETS, "_palette.png")
GIF_OUT     = os.path.join(ASSETS, "demo.gif")

BROWSER_SECS = 25   # seconds of browser window recording
SLIDE_SECS   = 4    # seconds per Feishu screenshot
GIF_FPS      = 6
GIF_WIDTH    = 900  # output px width (height auto)

TEMP_FILES = [TERM_GIF, TERM_MP4, BROWSER_RAW, BROWSER_MP4,
              SLIDE1_MP4, SLIDE2_MP4, CONCAT_MP4, PALETTE,
              os.path.join(ASSETS, "_concat.txt")]

os.makedirs(ASSETS, exist_ok=True)

# ── helper ─────────────────────────────────────────────────────────────────
CFR_VF = f"fps={GIF_FPS},scale={GIF_WIDTH}:-2:flags=lanczos,format=yuv420p"

def ff(*args, check=False):
    """Run ffmpeg -y <args>, print command, return CompletedProcess."""
    cmd = ["ffmpeg", "-y", *[str(a) for a in args]]
    print("  $", " ".join(cmd))
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          check=check)

def normalize(src, dst, extra_vf=""):
    """Re-encode src → dst at GIF_FPS CFR, GIF_WIDTH wide."""
    vf = f"{extra_vf},{CFR_VF}" if extra_vf else CFR_VF
    r = ff("-i", src, "-vf", vf,
           "-c:v", "libx264", "-preset", "fast", "-crf", "28", "-vsync", "cfr",
           dst)
    if r.returncode != 0:
        print(f"❌  normalize({src}) failed:", r.stderr.decode()); sys.exit(1)

def probe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True)
    return float(r.stdout.strip())

# ══════════════════════════════════════════════════════════════════════════
# Part 1 — Terminal
# ══════════════════════════════════════════════════════════════════════════
print("\n━━ Part 1: terminal (demo.cast → CFR mp4) ━━")
if not os.path.exists(CAST):
    print(f"❌  {CAST} not found — run make_demo.py first."); sys.exit(1)

r = subprocess.run(
    ["agg", "--cols", "120", "--rows", "35", "--font-size", "13",
     "--speed", "3", "--idle-time-limit", "1", CAST, TERM_GIF],
    capture_output=True, text=True)
if r.returncode != 0:
    print("❌  agg failed:", r.stderr); sys.exit(1)

normalize(TERM_GIF, TERM_MP4)
d = probe_duration(TERM_MP4)
print(f"✅  Terminal: {d:.1f}s  {os.path.getsize(TERM_MP4)//1024} KB")

# ══════════════════════════════════════════════════════════════════════════
# Part 2 — Browser window (DrissionPage)
# ══════════════════════════════════════════════════════════════════════════
print("\n━━ Part 2: browser window ━━")
env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"

print("▶  Starting wokflow.py --once …")
wok = subprocess.Popen(
    [sys.executable, "-u", WOKFLOW, "--once"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1, env=env, cwd=PROJECT)

screen_proc  = None
screen_start = None
crop_arg     = None

for line in wok.stdout:
    sys.stdout.write("  | " + line); sys.stdout.flush()

    if screen_proc is None and "Starting to augment" in line:
        print("\n⏳  Waiting 4 s for Chrome to fully open …")
        time.sleep(4)

        # ── detect Chrome window bounds ────────────────────────────────
        r = subprocess.run(["osascript", "-e", '''
            tell application "Google Chrome"
                if (count of windows) > 0 then
                    return bounds of first window
                end if
                return "none"
            end tell'''], capture_output=True, text=True)
        out = r.stdout.strip()
        if out and out != "none":
            lx, ty, rx, by = [int(p.strip()) for p in out.split(",")]
            scale = 2.0          # Retina 2×
            x = int(lx * scale); y = int(ty * scale)
            w = int((rx - lx) * scale) & ~1   # make even
            h = int((by - ty) * scale) & ~1
            crop_arg = f"crop={w}:{h}:{x}:{y}"
            print(f"  Chrome crop (physical): {crop_arg}")
        else:
            print("  ⚠️  Chrome window not detected — recording full screen")
            crop_arg = None

        crop_vf = crop_arg if crop_arg else ""
        print(f"\n🎬  Screen capture started …\n")
        screen_proc = subprocess.Popen([
            "ffmpeg", "-y",
            "-f", "avfoundation",
            "-framerate", "10",
            "-capture_cursor", "1",
            "-i", "4",           # 'Capture screen 0'
            "-t", str(BROWSER_SECS),
            *((["-vf", crop_vf]) if crop_vf else []),
            "-c:v", "libx264", "-preset", "fast", "-crf", "28",
            BROWSER_RAW
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        screen_start = time.time()

    if screen_start and (time.time() - screen_start) >= BROWSER_SECS:
        print("\n⏹  Stopping sync …")
        wok.send_signal(signal.SIGTERM)
        break

wok.wait(timeout=10)

if screen_proc is None:
    print("❌  Stage 2 never started."); sys.exit(1)

print("⏳  Waiting for capture to finish …")
screen_proc.wait(timeout=BROWSER_SECS + 10)

if not os.path.exists(BROWSER_RAW) or os.path.getsize(BROWSER_RAW) < 5000:
    print("❌  Browser capture too small / missing."); sys.exit(1)
print(f"  Raw capture: {os.path.getsize(BROWSER_RAW)//1024} KB")

# Normalize to GIF_FPS CFR (also handles any leftover crop if not applied above)
normalize(BROWSER_RAW, BROWSER_MP4)
d = probe_duration(BROWSER_MP4)
print(f"✅  Browser: {d:.1f}s  {os.path.getsize(BROWSER_MP4)//1024} KB")

# ══════════════════════════════════════════════════════════════════════════
# Part 3 — Feishu slides  (each image held for SLIDE_SECS seconds)
# ══════════════════════════════════════════════════════════════════════════
print("\n━━ Part 3: Feishu slides ━━")
for img, dest in [("demo1.png", SLIDE1_MP4), ("demo2.png", SLIDE2_MP4)]:
    ff("-loop", "1", "-i", os.path.join(ASSETS, img),
       "-t", str(SLIDE_SECS),
       "-vf", CFR_VF,
       "-c:v", "libx264", "-preset", "fast", "-crf", "28", "-vsync", "cfr",
       dest)
print(f"✅  Feishu slides ready")

# ══════════════════════════════════════════════════════════════════════════
# Concat (all parts are identical fps/resolution/format → safe to copy)
# ══════════════════════════════════════════════════════════════════════════
print("\n━━ Concatenating ━━")
concat_list = os.path.join(ASSETS, "_concat.txt")
with open(concat_list, "w") as f:
    for p in [TERM_MP4, BROWSER_MP4, SLIDE1_MP4, SLIDE2_MP4]:
        f.write(f"file '{p}'\n")

r = ff("-f", "concat", "-safe", "0", "-i", concat_list,
       "-c", "copy", CONCAT_MP4)
if r.returncode != 0:
    print("❌  Concat failed:", r.stderr.decode()); sys.exit(1)

d = probe_duration(CONCAT_MP4)
print(f"✅  Concatenated: {d:.1f}s  {os.path.getsize(CONCAT_MP4)//1024} KB")

# ══════════════════════════════════════════════════════════════════════════
# GIF — two-pass palette  (CONCAT_MP4 is already at GIF_FPS, so no fps filter needed)
# ══════════════════════════════════════════════════════════════════════════
print("\n━━ GIF conversion ━━")
# Force a fixed size so all frames are identical dimensions (concat may have
# slight height differences if sources have different aspect ratios).
NORM_VF = f"scale={GIF_WIDTH}:620:flags=lanczos,format=yuv420p"

ff("-i", CONCAT_MP4, "-vf", f"{NORM_VF},palettegen=stats_mode=diff", PALETTE)
if not os.path.exists(PALETTE):
    print("❌  Palette generation failed."); sys.exit(1)

r = ff("-i", CONCAT_MP4, "-i", PALETTE,
       "-filter_complex",
       f"{NORM_VF}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
       GIF_OUT)
if r.returncode != 0:
    print("❌  GIF conversion failed:", r.stderr.decode()); sys.exit(1)

size = os.path.getsize(GIF_OUT) // 1024
print(f"\n✅  GIF saved → {GIF_OUT}  ({size} KB)")

# ── cleanup ────────────────────────────────────────────────────────────────
for f in TEMP_FILES:
    try: os.remove(f)
    except FileNotFoundError: pass

print("🏁  Done!\n")
