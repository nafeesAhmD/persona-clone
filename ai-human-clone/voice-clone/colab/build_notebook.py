"""Builds voice_clone_gpu.ipynb: the voice-clone service on a free Google Colab GPU.

The notebook embeds this folder's app.py, model.py and audio.py, so run this script
again after changing them:  python voice-clone/colab/build_notebook.py
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
CODE_FILES = ("app.py", "model.py", "audio.py")


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.strip("\n")}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text.strip("\n")}


INTRO = """
# AI Human Clone: apni aawaz GPU par (muft)

Ye notebook aap ki **apni aawaz** banane wali service Google Colab ke muft GPU par chalata hai.
Laptop ke CPU par 1-2 minute lagte hain, GPU par chand second.

**Har baar:**
1. Upar menu: **Runtime → Change runtime type → T4 GPU → Save** (sirf pehli baar).
2. **Runtime → Run all**.
3. Google Drive ki ijazat maange to de dein.
4. Token maange to laptop wali script (`scripts\\voice-gpu.ps1`) ne jo copy kiya hai wo **Ctrl+V** se paste kar ke Enter.
5. Aakhir mein jo `https://....trycloudflare.com` link aaye, use laptop wali script mein paste karein.

Ye tab khula rehne dein. Band karne par app khud laptop wali (dheemi) aawaz par chali jati hai.

Engine: OmniVoice (asal Urdu, sirf apne istemal ke liye). Pehli dafa har aawaz ki likhai
Whisper se khud banti hai aur Drive mein save ho jati hai (`<id>.txt`, `<id>.omnivoice.pt`).

**Pehli baar:** Google Drive mein `ai-clone-voices` naam ka folder banayein aur laptop ke
`Desktop\\AI-Clone-GPU\\voices` ki saari `.wav` files us mein upload kar dein.
"""

GPU_AND_DRIVE = """
# 1) GPU aur Google Drive
import os, subprocess
gpu = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True).stdout.strip()
if not gpu:
    raise SystemExit("GPU nahi mila! Runtime > Change runtime type > T4 GPU chunein, phir Run all dobara.")
print("GPU:", gpu)

from google.colab import drive
drive.mount("/content/drive")
VOICES = "/content/drive/MyDrive/ai-clone-voices"
os.makedirs(VOICES, exist_ok=True)
voices = sorted(f for f in os.listdir(VOICES) if f.endswith(".wav"))
print(f"Drive voices folder: {VOICES} ({len(voices)} aawaz files)")
if not voices:
    print("Abhi koi .wav nahi: laptop ke Desktop\\\\AI-Clone-GPU\\\\voices ki files is folder mein upload karein,"
          " ya app mein nayi aawaz record karein (wo yahin save hogi).")
"""

INSTALL = """
# 2) Engine aur zaroori packages (2-3 minute). Colab ka apna GPU wala PyTorch istemal hota hai.
# "omnivoice": asal Urdu bolta hai (sirf apne istemal ke liye: CC-BY-NC license).
# "chatterbox": MIT license (bechne ke liye theek), Urdu ko Hindi ke zariye bolta hai.
ENGINE = "omnivoice"

!pip -q install fastapi==0.142.2 uvicorn==0.54.0 python-multipart==0.0.32 soundfile soxr
if ENGINE == "omnivoice":
    !pip -q install omnivoice==0.2.1
else:
    !pip -q install --no-deps chatterbox-tts==0.1.7
    !pip -q install librosa==0.11.0 safetensors s3tokenizer==0.3.0 transformers==5.2.0 diffusers==0.29.0 resemble-perth==1.0.1 conformer==0.3.2 spacy-pkuseg==1.0.1 pykakasi==2.3.0 omegaconf==2.3.1 einops==0.8.2
print("Packages tayyar:", ENGINE)
"""

START = """
# 4) Service chalana + public link (token zaroori: iske baghair koi bhi link use kar sakta hai)
# Khud-mukhtar: Colab ne beech mein session restart kiya ho tab bhi chalta hai.
import getpass, json, os, re, subprocess, time, urllib.request

ENGINE = globals().get("ENGINE", "omnivoice")
VOICES = "/content/drive/MyDrive/ai-clone-voices"
if not os.path.isdir("/content/drive/MyDrive"):
    from google.colab import drive
    drive.mount("/content/drive")
os.makedirs(VOICES, exist_ok=True)
if not os.path.isfile("/content/vc/app.py"):
    raise SystemExit("Code nahi mila: pehle cell 3 chalayen (ya Runtime > Run all).")

token = getpass.getpass("Token paste karein (Ctrl+V, phir Enter): ").strip()
if len(token) < 16:
    raise SystemExit("Token khaali ya ghalat hai. Laptop par scripts\\\\voice-gpu.ps1 dobara chalayen, wo token copy karti hai.")

env = dict(os.environ, VOICE_CLONE_SERVICE_TOKEN=token, VOICE_DATA_DIR=VOICES, VOICE_CLONE_DEVICE="cuda",
           VOICE_CLONE_ENGINE=ENGINE, OMNIVOICE_STEPS="32",
           SYNTH_TIMEOUT_SECONDS="240", MODEL_WAIT_SECONDS="120", HF_HUB_DISABLE_TELEMETRY="1")
for name in ("server", "tunnel"):
    if name in globals():
        globals()[name].terminate()  # "Run all" again: stop the old ones first
server = subprocess.Popen(
    ["python", "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8100", "--workers", "1", "--no-access-log"],
    cwd="/content/vc", env=env, stdout=open("/content/vc/server.log", "w"), stderr=subprocess.STDOUT)

print("Model load ho raha hai (pehli baar ~3 GB download: 2-5 minute)...", flush=True)
for _ in range(180):
    time.sleep(10)
    if server.poll() is not None:
        print(open("/content/vc/server.log").read()[-4000:])
        raise SystemExit("Service band ho gayi (upar log dekhein).")
    try:
        health = json.load(urllib.request.urlopen("http://127.0.0.1:8100/health", timeout=5))
    except Exception:
        continue
    if health["model_loaded"]:
        print("Model tayyar:", health)
        break
else:
    raise SystemExit("30 minute mein model load nahi hua.")

if not os.path.exists("/content/cloudflared"):
    urllib.request.urlretrieve(
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64", "/content/cloudflared")
    os.chmod("/content/cloudflared", 0o755)
tunnel = subprocess.Popen(["/content/cloudflared", "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8100"],
                          stdout=open("/content/tunnel.log", "w"), stderr=subprocess.STDOUT)
url = None
for _ in range(90):
    time.sleep(2)
    found = re.search(r"https://[a-z0-9-]+\\.trycloudflare\\.com", open("/content/tunnel.log").read())
    if found:
        url = found.group(0)
        break
if not url:
    print(open("/content/tunnel.log").read()[-3000:])
    raise SystemExit("Public link nahi bana (upar log dekhein). Run all dobara karein.")
print("\\n" + "=" * 70)
print("YE LINK COPY KAR KE LAPTOP WALI SCRIPT MEIN PASTE KAREIN:\\n")
print("   ", url)
print("=" * 70)
"""

KEEP_ALIVE = """
# 5) Chalta rehne dein: har minute halat dikhata hai (Colab isse jaga rehta hai). Rokna ho to Stop dabayein.
import time
while True:
    time.sleep(60)
    alive = server.poll() is None and tunnel.poll() is None
    lines = [l for l in open("/content/vc/server.log").read().splitlines() if "synthesized" in l or "Error" in l]
    print(time.strftime("%H:%M"), "chal raha hai" if alive else "BAND HO GAYA: Run all dobara karein", "|", (lines[-1][-110:] if lines else ""))
    if not alive:
        break
"""


def write_code_cell() -> dict:
    lines = ["# 3) Voice service ka code (laptop wala hi code, build_notebook.py ne yahan daala hai)",
             "import os", 'os.makedirs("/content/vc", exist_ok=True)', "FILES = {"]
    for name in CODE_FILES:
        lines.append(f"    {name!r}: {(SERVICE / name).read_text(encoding='utf-8')!r},")
    lines += ["}", "for name, text in FILES.items():",
              '    with open(f"/content/vc/{name}", "w", encoding="utf-8") as fh:', "        fh.write(text)",
              'print("Code likh diya:", ", ".join(FILES))']
    return code("\n".join(lines))


def build() -> dict:
    cells = [md(INTRO), code(GPU_AND_DRIVE), code(INSTALL), write_code_cell(), code(START), code(KEEP_ALIVE)]
    for cell in cells:  # notebooks store source as a list of lines
        cell["source"] = cell["source"].splitlines(keepends=True)
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


if __name__ == "__main__":
    out = HERE / "voice_clone_gpu.ipynb"
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", out)
