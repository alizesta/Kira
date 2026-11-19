"""Compare installed Piper ONNX voices by synthesis real-time factor.

Example:
  python scripts/benchmark_piper_voices.py --models path/to/medium.onnx path/to/low.onnx
"""
import argparse
import io
import json
import statistics
import time
import wave

from kira.local_voice import synthesize_persian

SAMPLE = (
    "سلام، این یک متن آزمایشی برای مقایسه سرعت و کیفیت تولید گفتار فارسی است. "
    "کیرا باید واضح، طبیعی و بدون مکث‌های غیرعادی صحبت کند."
)


def benchmark(model_path, runs):
    durations = []
    audio_seconds = 0.0
    for index in range(runs + 1):
        started = time.perf_counter()
        payload = synthesize_persian(SAMPLE, model_path=model_path)
        elapsed = time.perf_counter() - started
        with wave.open(io.BytesIO(payload), "rb") as audio:
            spoken_seconds = audio.getnframes() / audio.getframerate()
        if not spoken_seconds:
            raise RuntimeError(f"Model produced empty audio: {model_path}")
        if index > 0:
            durations.append(elapsed)
            audio_seconds = spoken_seconds
    median = statistics.median(durations)
    return {
        "model": model_path,
        "runs": runs,
        "median_synthesis_seconds": round(median, 3),
        "audio_seconds": round(audio_seconds, 3),
        "real_time_factor": round(median / audio_seconds, 3),
        "faster_than_realtime": median < audio_seconds,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", required=True, help="Paths to installed Piper ONNX models")
    parser.add_argument("--runs", type=int, default=3, help="Timed runs per model (default: 3)")
    args = parser.parse_args()
    if args.runs < 1 or args.runs > 10:
        parser.error("--runs must be between 1 and 10")
    print(json.dumps([benchmark(path, args.runs) for path in args.models], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
