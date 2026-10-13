"""Render a narrated, vertically framed video from a generated Arabic script."""

import json
import re
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw


class VideoRenderError(RuntimeError):
    """A clear error that can be shown in a GitHub Actions log."""


INTRO_SECONDS = 1.8
OUTRO_SECONDS = 2.0
PAUSE_SECONDS = 0.28
WIDTH = 720
HEIGHT = 1280
FPS = 30


def extract_narration(markdown):
    """Remove the generated artifact's title, review notice, and sources section."""
    lines = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") or stripped.startswith("> "):
            continue
        if re.match(r"^#{0,6}\s*[«\"']?\s*(مصادر|المراجع|sources)\b", stripped, re.IGNORECASE):
            break
        if stripped.startswith("``` ") or stripped == "```":
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            stripped = stripped[2:].strip()
        if stripped:
            lines.append(stripped)
    narration = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if len(narration) < 20:
        raise VideoRenderError("لم أجد نص إلقاء كافيًا في المسودة. راجع النص وأعد توليده قبل إنتاج الفيديو.")
    return narration


def split_segments(text, max_chars=68):
    """Split the narration into caption-sized phrases without discarding words."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?؟؛،])\s+|\n+", text) if part.strip()]
    segments = []
    for sentence in sentences:
        words = sentence.split()
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > max_chars:
                segments.append(current)
                current = word
            else:
                current = candidate
        if current:
            segments.append(current)
    if not segments:
        raise VideoRenderError("تعذر تقسيم نص الإلقاء إلى مقاطع صوتية.")
    return segments


def _run(command, *, input_text=None, step_name):
    try:
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise VideoRenderError(f"الأداة المطلوبة غير مثبتة لإتمام خطوة {step_name}: {error.filename}") from None
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        detail = "\n".join(detail[-12:])
        raise VideoRenderError(f"فشلت خطوة {step_name} (رمز {result.returncode}).\n{detail}")
    return result


def _read_wave(path):
    with wave.open(str(path), "rb") as source:
        params = source.getparams()
        frames = source.readframes(source.getnframes())
    if params.nchannels != 1 or params.sampwidth != 2:
        raise VideoRenderError("أعاد مولد الصوت تنسيق WAV غير متوقع.")
    return params, frames


def _format_srt_time(seconds):
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _wrap_caption(text, max_chars=38):
    lines = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def _make_background(path):
    """Create a lightweight original science-themed backdrop without stock media."""
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    top = (5, 20, 43)
    bottom = (10, 65, 91)
    for y in range(HEIGHT):
        blend = y / (HEIGHT - 1)
        color = tuple(round(top[c] * (1 - blend) + bottom[c] * blend) for c in range(3))
        for x in range(WIDTH):
            pixels[x, y] = color

    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((116, 190, 604, 678), outline=(110, 210, 235, 70), width=3)
    draw.ellipse((164, 238, 556, 630), outline=(110, 210, 235, 45), width=2)
    draw.ellipse((205, 280, 515, 590), fill=(33, 112, 150, 80), outline=(125, 225, 238, 100), width=3)
    draw.ellipse((278, 340, 442, 504), fill=(81, 176, 192, 45), outline=(195, 244, 242, 100), width=2)
    for x, y, radius, alpha in [
        (92, 155, 4, 150), (615, 230, 5, 125), (95, 770, 3, 130),
        (622, 880, 4, 140), (138, 1015, 3, 120), (570, 1080, 5, 110),
        (500, 145, 3, 140), (205, 870, 4, 90), (548, 720, 3, 120),
    ]:
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=(211, 247, 255, alpha))
    image.save(path, format="PNG", optimize=True)


def render_video(script_path, title, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = Path(script_path)
    if not script_path.is_file():
        raise VideoRenderError(f"ملف المسودة غير موجود: {script_path}")

    narration = extract_narration(script_path.read_text(encoding="utf-8"))
    segments = split_segments(narration)
    print(f"تم استخراج نص الإلقاء وتقسيمه إلى {len(segments)} مقاطع.", flush=True)

    audio_dir = output_dir / "audio_segments"
    audio_dir.mkdir(exist_ok=True)
    audio_parts = []
    captions = []
    cursor = INTRO_SECONDS
    sample_rate = None
    sample_width = None

    for number, segment in enumerate(segments, start=1):
        print(f"توليد الصوت: المقطع {number}/{len(segments)}.", flush=True)
        wav_path = audio_dir / f"segment-{number:03}.wav"
        _run(
            ["espeak-ng", "-v", "ar", "-s", "145", "-w", str(wav_path), "--stdin"],
            input_text=segment,
            step_name=f"توليد الصوت العربي للمقطع {number}",
        )
        params, frames = _read_wave(wav_path)
        sample_rate = sample_rate or params.framerate
        sample_width = sample_width or params.sampwidth
        if params.framerate != sample_rate or params.sampwidth != sample_width:
            raise VideoRenderError("تغيّر تنسيق الصوت بين المقاطع؛ لا يمكن دمجها بأمان.")
        duration = len(frames) / (params.framerate * params.nchannels * params.sampwidth)
        if duration <= 0:
            raise VideoRenderError(f"المقطع الصوتي {number} فارغ.")
        captions.append((cursor, cursor + duration, _wrap_caption(segment)))
        audio_parts.append(frames)
        cursor += duration
        if number < len(segments):
            pause_frames = round(PAUSE_SECONDS * params.framerate)
            audio_parts.append(b"\x00" * pause_frames * params.nchannels * params.sampwidth)
            cursor += PAUSE_SECONDS

    params, _ = _read_wave(audio_dir / "segment-001.wav")
    intro_frames = round(INTRO_SECONDS * params.framerate)
    outro_frames = round(OUTRO_SECONDS * params.framerate)
    full_audio = output_dir / "narration.wav"
    with wave.open(str(full_audio), "wb") as destination:
        destination.setnchannels(params.nchannels)
        destination.setsampwidth(params.sampwidth)
        destination.setframerate(params.framerate)
        destination.writeframes(b"\x00" * intro_frames * params.nchannels * params.sampwidth)
        for frames in audio_parts:
            destination.writeframes(frames)
        destination.writeframes(b"\x00" * outro_frames * params.nchannels * params.sampwidth)

    narration_path = output_dir / "narration.txt"
    narration_path.write_text(narration, encoding="utf-8")

    srt_path = output_dir / "subtitles.srt"
    cues = [(0.15, INTRO_SECONDS - 0.1, _wrap_caption(title))]
    cues.extend((start, end + 0.12, text) for start, end, text in captions)
    outro_start = cursor + 0.15
    cues.append((outro_start, outro_start + OUTRO_SECONDS - 0.25, "حقيقة علمية جديدة في كل فيديو"))
    with srt_path.open("w", encoding="utf-8", newline="\n") as destination:
        for index, (start, end, text) in enumerate(cues, start=1):
            destination.write(
                f"{index}\n{_format_srt_time(start)} --> {_format_srt_time(end)}\n{text}\n\n"
            )

    background = output_dir / "background.png"
    _make_background(background)
    video_path = output_dir / "video.mp4"
    subtitle_filter = (
        f"subtitles={srt_path}:fontsdir=/usr/share/fonts/truetype/noto:"
        "force_style='FontName=Noto Sans Arabic,FontSize=25,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00101A2A,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=128'"
    )
    print("تركيب الخلفية والشرح المكتوب والصوت في فيديو رأسي.", flush=True)
    _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-framerate", str(FPS), "-i", str(background),
            "-i", str(full_audio), "-vf", subtitle_filter,
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
            "-crf", "25", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart", str(video_path),
        ],
        step_name="تركيب الفيديو عبر FFmpeg",
    )
    probe = _run(
        [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_name,codec_type,width,height",
            "-of", "json", str(video_path),
        ],
        step_name="فحص ملف الفيديو الناتج",
    )
    try:
        streams = json.loads(probe.stdout).get("streams", [])
        video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
        audio_stream = next(stream for stream in streams if stream.get("codec_type") == "audio")
    except (ValueError, StopIteration):
        raise VideoRenderError("لم أتمكن من التحقق من مساري الفيديو والصوت في الملف الناتج.") from None
    if (video_stream.get("width"), video_stream.get("height")) != (WIDTH, HEIGHT):
        raise VideoRenderError("أبعاد الفيديو الناتج ليست 9:16 كما هو مطلوب.")
    if video_stream.get("codec_name") != "h264" or audio_stream.get("codec_name") != "aac":
        raise VideoRenderError("ترميز الفيديو أو الصوت الناتج غير متوافق مع إعداد التصدير.")

    print(f"اكتمل الفيديو: {video_path} ({WIDTH}×{HEIGHT}، H.264/AAC).", flush=True)
    return video_path
