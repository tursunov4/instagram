"""Ovoz (o'zbekcha TTS), fon musiqasi (o'zimiz sintez qilamiz — mualliflik muammosi yo'q)
va effektlarni birlashtirish."""
import asyncio
import os
import subprocess
from xml.sax.saxutils import escape

import numpy as np
import requests
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

SR = 44100


# ------------------------------------------------------------------ TTS
def tts(text, path, voice, rate="+6%"):
    """Matnni mp3 ga aylantiradi. Azure kaliti bo'lsa Azure, aks holda edge-tts.
    Qaytaradi: ishlatilgan xizmat nomi."""
    key, region = os.environ.get("AZURE_SPEECH_KEY"), os.environ.get("AZURE_SPEECH_REGION")
    if key and region:
        ssml = (f"<speak version='1.0' xml:lang='uz-UZ'><voice name='{voice}'>"
                f"<prosody rate='{rate}'>{escape(text)}</prosody></voice></speak>")
        r = requests.post(
            f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={"Ocp-Apim-Subscription-Key": key,
                     "Content-Type": "application/ssml+xml",
                     "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3",
                     "User-Agent": "arzoni-reels"},
            data=ssml.encode("utf-8"), timeout=60)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        return "azure"

    import edge_tts

    async def _go():
        await edge_tts.Communicate(text, voice, rate=rate).save(path)

    asyncio.run(_go())
    return "edge"


def load(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return trim(np.frombuffer(raw, np.float32).astype(np.float64))


def trim(x, thr=0.008, keep=0.03):
    idx = np.flatnonzero(np.abs(x) > thr)
    if not len(idx):
        return x
    k = int(keep * SR)
    return x[max(0, idx[0] - k): idx[-1] + k]


# ------------------------------------------------------------------ musiqa
def _midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def _lp(x, hz, order=2):
    return sosfilt(butter(order, hz, "low", fs=SR, output="sos"), x)


def _hp(x, hz, order=2):
    return sosfilt(butter(order, hz, "high", fs=SR, output="sos"), x)


def music(T, bpm=104, seed=1):
    """Yengil, quvnoq fon: Am–F–C–G, pad + arpejio + bas + yengil barabanlar."""
    rng = np.random.default_rng(seed)
    n = int((T + 1) * SR)
    beat = 60 / bpm
    bar = 4 * beat
    prog = [(45, [57, 60, 64]), (41, [53, 57, 60]), (48, [55, 60, 64]), (43, [55, 59, 62])]
    pad, arp, bass, drums = (np.zeros(n) for _ in range(4))

    for b in range(int(T / bar) + 2):
        root, chord = prog[b % 4]
        s0 = int(b * bar * SR)
        if s0 >= n:
            break
        L = min(n - s0, int((bar + 0.5) * SR))
        tt = np.arange(L) / SR
        env = np.minimum(1, tt / 0.35) * np.clip((bar + 0.5 - tt) / 0.5, 0, 1)
        for note in chord:
            f = _midi(note)
            for det in (-0.0025, 0.0025):
                for k in range(1, 6):
                    pad[s0:s0 + L] += env * np.sin(2 * np.pi * f * (1 + det) * k * tt) / (k * 1.6)
        # bas: 1- va 3-zarbda
        for q in (0, 2):
            s = s0 + int(q * beat * SR)
            Lb = min(n - s, int(beat * 1.9 * SR))
            if Lb <= 0:
                continue
            tb = np.arange(Lb) / SR
            fb = _midi(root)
            bass[s:s + Lb] += np.tanh(1.6 * np.sin(2 * np.pi * fb * tb)) * np.exp(-tb * 2.2)
        # arpejio: 8-taliklar
        tones = [c + 12 for c in chord] + [chord[0] + 24]
        for i in range(8):
            s = s0 + int(i * beat / 2 * SR)
            La = min(n - s, int(0.45 * SR))
            if La <= 0:
                continue
            ta = np.arange(La) / SR
            fa = _midi(tones[(i * 3 + b) % len(tones)])
            arp[s:s + La] += (np.sin(2 * np.pi * fa * ta) + 0.3 * np.sin(4 * np.pi * fa * ta)) * np.exp(-ta * 9)
        # barabanlar (birinchi taktdan keyin)
        if b == 0:
            continue
        for q in range(4):
            s = s0 + int(q * beat * SR)
            Lk = min(n - s, int(0.25 * SR))
            if Lk <= 0:
                continue
            tk = np.arange(Lk) / SR
            if q in (0, 2):  # kick
                ph = 2 * np.pi * np.cumsum(45 + 90 * np.exp(-tk * 30)) / SR
                drums[s:s + Lk] += 0.9 * np.sin(ph) * np.exp(-tk * 14)
            else:  # chapak
                nz = _hp(rng.standard_normal(Lk), 1200)
                drums[s:s + Lk] += 0.28 * nz * np.exp(-tk * 22)
            sh = s + int(beat / 2 * SR)  # hi-hat
            Lh = min(n - sh, int(0.06 * SR))
            if Lh > 0:
                th = np.arange(Lh) / SR
                drums[sh:sh + Lh] += 0.12 * _hp(rng.standard_normal(Lh), 7000) * np.exp(-th * 70)

    mix = (0.20 * _lp(pad, 1600) / (np.abs(pad).max() + 1e-9)
           + 0.16 * arp / (np.abs(arp).max() + 1e-9)
           + 0.30 * _lp(bass, 400) / (np.abs(bass).max() + 1e-9)
           + 0.34 * drums / (np.abs(drums).max() + 1e-9))
    mix = mix[: int(T * SR)]
    fade = int(1.2 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)
    return mix / (np.abs(mix).max() + 1e-9)


# ------------------------------------------------------------------ effektlar
def whoosh(d=0.4, seed=0):
    rng = np.random.default_rng(seed)
    L = int(d * SR)
    t = np.arange(L) / SR
    env = np.sin(np.pi * t / d) ** 2
    return 0.5 * _lp(_hp(rng.standard_normal(L), 400), 3500) * env


def pop():
    t = np.arange(int(0.09 * SR)) / SR
    f = 700 + 500 * np.exp(-t * 40)
    return 0.45 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 38)


def ding():
    t = np.arange(int(1.3 * SR)) / SR
    return 0.32 * (np.sin(2 * np.pi * 1318.5 * t) + 0.6 * np.sin(2 * np.pi * 1975.5 * t)) * np.exp(-t * 4)


SFX = {"whoosh": whoosh, "pop": pop, "ding": ding}


# ------------------------------------------------------------------ yig'ish
def _smooth(x, sec):
    k = max(1, int(sec * SR))
    c = np.cumsum(np.concatenate([np.zeros(k), x]))
    return (c[k:] - c[:-k]) / k


def mix(T, voices, sfx, path, music_on=True):
    """voices: [(boshlanish_sekund, signal)], sfx: [(sekund, nomi)]."""
    n = int(T * SR)
    v = np.zeros(n)
    gate = np.zeros(n)
    for t0, sig in voices:
        s = int(t0 * SR)
        e = min(n, s + len(sig))
        if s < n:
            v[s:e] += sig[: e - s]
            gate[max(0, s - int(0.1 * SR)): e + int(0.15 * SR)] = 1
    out = v / (np.abs(v).max() + 1e-9) * 0.9 if voices else v
    if music_on:
        duck = 0.42 - 0.30 * np.clip(_smooth(gate, 0.15), 0, 1)
        out = out + music(T) * duck
    for t0, name in sfx:
        sig = SFX[name]()
        s = int(t0 * SR)
        e = min(n, s + len(sig))
        if s < n:
            out[s:e] += 0.55 * sig[: e - s]
    out = np.tanh(out * 1.1) / np.tanh(1.1)
    out = out / (np.abs(out).max() + 1e-9) * 0.95
    wavfile.write(path, SR, (out * 32767).astype(np.int16))
