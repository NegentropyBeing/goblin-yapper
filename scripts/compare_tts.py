"""Compare voice models: has the running TTS server read a fixed set of pt-BR chat lines with each profile,
then saves the audio for listening and the timings for comparing.

Run it once per model (switch the model in the Voice tab, wait for "ready", run again), then listen to
compare/<model>/<profile>/*.wav side by side and look at compare/results.csv.

  python scripts/compare_tts.py [--url http://127.0.0.1:8766] [--profile ID ...] [--seed 42] [--out compare]

Only the standard library: it runs with any Python, not only the server's. The first line of a run is
spoken once more beforehand and not counted: it warms the model up (and builds missing profile voices).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Twitch chat as it comes: short and long, slang, laughter, numbers, English mixed in, shouting, typos
LINES = [
    "oi chat",
    "kkkkkkkkk",
    "boa noite galera, tudo certo com vocês?",
    "mano que jogada absurda, não acredito que ele fez isso",
    "o time azul tá muito roubado, nerfa eles pelo amor de Deus",
    "eu tenho 27 anos e jogo isso desde 2012, ou seja, há mais de 13 anos",
    "isso custou R$ 49,90 na promoção, com 50% de desconto",
    "GG WP, that was a clutch play, sem condições",
    "vou dar um rush no B e vocês fazem o flank pelo mid, beleza?",
    "CALMA GENTE, NÃO PRECISA GRITAR",
    "vc viu q ele errou o pulo? tlgd",
    "Sabe, eu sempre achei que esse jogo fosse fácil, mas depois de passar três horas tentando derrotar esse "
    "chefe, eu comecei a repensar todas as minhas escolhas de vida, inclusive a de ter comprado esse teclado.",
    "Qual é a capital da Austrália? Não vale olhar no Google!",
    "hmm... sei não, hein",
]


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def speak(url: str, text: str, profile: str, params: dict) -> tuple[bytes, float, float]:
    body = json.dumps({"text": text, "profile": profile, "params": params}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{url}/synthesize", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.read(), float(r.headers["X-Gen-Seconds"]), float(r.headers["X-Audio-Seconds"])
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode("utf-8", "replace") or f"HTTP {e.code}") from None


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", s.lower()).strip("-")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--url", default="http://127.0.0.1:8766", help="the TTS server (not the app)")
    p.add_argument("--profile", action="append", help="profile id (repeatable; default: every profile)")
    p.add_argument("--seed", help="fixed seed, for engines that take one (Qwen3-TTS)")
    p.add_argument("--out", default="compare", help="output folder")
    args = p.parse_args()
    url = args.url.rstrip("/")

    try:
        status = get(f"{url}/status")
    except OSError as e:
        print(f"no TTS server at {url} ({e}); start the app (or the server) first", file=sys.stderr)
        return 1
    if status["state"] != "ready":
        print(f"the server is not ready yet ({status['state']}); wait for it in the Voice tab", file=sys.stderr)
        return 1
    model = status["label"]
    profiles = [m for m in get(f"{url}/profiles") if not args.profile or m["id"] in args.profile]
    if not profiles:
        print("no profiles to read with", file=sys.stderr)
        return 1
    params = {"seed": args.seed} if args.seed else {}

    out = Path(args.out)
    (out / slug(model)).mkdir(parents=True, exist_ok=True)
    (out / "lines.txt").write_text("\n".join(f"{i:02d}  {t}" for i, t in enumerate(LINES, 1)) + "\n", encoding="utf-8")
    results = out / "results.csv"
    new_file = not results.exists()
    print(f"{model} on {status.get('gpu') or status.get('device')}: {len(profiles)} profile(s) x {len(LINES)} lines")

    with open(results, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["when", "model", "profile", "line", "chars", "gen_seconds", "audio_seconds", "rtf",
                        "vram_model_gb", "seed", "error"])
        when = time.strftime("%Y-%m-%d %H:%M")
        for prof in profiles:
            folder = out / slug(model) / prof["id"]
            folder.mkdir(exist_ok=True)
            try:
                speak(url, LINES[0], prof["id"], params)  # warm-up, not counted
            except RuntimeError as e:
                print(f"  {prof['name']}: skipped ({e})")
                continue
            for i, text in enumerate(LINES, 1):
                try:
                    wav, gen, dur = speak(url, text, prof["id"], params)
                except RuntimeError as e:
                    w.writerow([when, model, prof["id"], i, len(text), "", "", "", "", args.seed or "", str(e)[:200]])
                    print(f"  {prof['name']} {i:02d}: error: {e}")
                    continue
                (folder / f"{i:02d}.wav").write_bytes(wav)
                vram = get(f"{url}/status").get("vram_model_gb", "")
                rtf = gen / dur if dur else 0
                w.writerow([when, model, prof["id"], i, len(text), f"{gen:.2f}", f"{dur:.2f}", f"{rtf:.3f}", vram,
                            args.seed or "", ""])
                print(f"  {prof['name']} {i:02d}: {dur:5.2f}s of audio in {gen:5.2f}s (RTF {rtf:.2f})")
            f.flush()
    print(f"audio in {out / slug(model)}, timings in {results}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
