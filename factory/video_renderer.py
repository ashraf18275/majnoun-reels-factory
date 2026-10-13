"""Create a narrated Arabic explainer with neural speech and animated scenes."""

import json
import re
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class VideoRenderError(RuntimeError):
    """A clear error that can be shown in a GitHub Actions log."""


INTRO_SECONDS = 1.8
OUTRO_SECONDS = 2.0
PAUSE_SECONDS = 0.18
WIDTH = 720
HEIGHT = 1280
FPS = 30
SCENE_COUNT = 5


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
        if stripped.startswith(("- ", "* ")):
            stripped = stripped[2:].strip()
        if stripped:
            lines.append(stripped)
    narration = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if len(narration) < 20:
        raise VideoRenderError("لم أجد نص إلقاء كافيًا في المسودة. راجع النص وأعد توليده قبل إنتاج الفيديو.")
    return narration


def split_segments(text, max_chars=115):
    """Split narration into sentence-sized chunks to preserve natural prosody."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?؟؛])\s+|\n+", text) if part.strip()]
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
        result = subprocess.run(command, input=input_text, text=True, capture_output=True, check=False)
    except FileNotFoundError as error:
        raise VideoRenderError(f"الأداة المطلوبة غير مثبتة لإتمام خطوة {step_name}: {error.filename}") from None
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise VideoRenderError(f"فشلت خطوة {step_name} (رمز {result.returncode}).\n" + "\n".join(detail[-12:]))
    return result


def _read_wave(path):
    with wave.open(str(path), "rb") as source:
        params, frames = source.getparams(), source.readframes(source.getnframes())
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
    lines, current = [], ""
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


def _font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _topic_title(text, index):
    patterns = [
        (r"الشمس|ضوء|الضوء", "رحلة الضوء"),
        (r"موج|طول موجي|الأطوال الموجية", "ألوان بأطوال مختلفة"),
        (r"جزيئ|جزيئات|ذرات|غلاف جوي|الهواء", "ما يحدث في الغلاف الجوي"),
        (r"تبعثر|تشتت|ينتشر|يتشتت", "لماذا يتبعثر الضوء؟"),
        (r"سماء|أزرق|السماء", "سر زرقة السماء"),
    ]
    for pattern, heading in patterns:
        if re.search(pattern, text):
            return heading
    return ["السؤال العلمي", "الفكرة الأساسية", "كيف يحدث ذلك؟", "ما الذي تكشفه الأدلة؟", "الخلاصة العلمية"][index]


def _draw_scene(path, title, index, topic):
    """Paint a distinct infographic scene; FFmpeg then animates its camera move."""
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    top, bottom = (7, 17, 43), (13, 57, 83)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = tuple(round(top[c] * (1 - t) + bottom[c] * t) for c in range(3))
        for x in range(WIDTH):
            pixels[x, y] = color
    draw = ImageDraw.Draw(image, "RGBA")
    accent = [(255, 190, 74), (72, 206, 255), (143, 255, 203), (255, 114, 149), (184, 154, 255)][index]
    draw.rounded_rectangle((42, 82, 678, 132), radius=22, fill=(255, 255, 255, 18), outline=(*accent, 180), width=2)
    draw.text((360, 107), f"مجنون علم  •  {index + 1:02}", font=_font(23, True), fill=(229, 244, 255), anchor="mm", direction="rtl")
    draw.text((360, 250), title, font=_font(39, True), fill=(255, 255, 255), anchor="mm", direction="rtl", stroke_width=1, stroke_fill=(2, 11, 30))
    # A layered illustrated centerpiece makes each chapter visually distinct.
    cx, cy = 360, 605
    if re.search(r"شمس|ضوء|السماء|أزرق|موج|غلاف جوي|هواء", topic):
        if index == 0:
            for radius in (190, 150, 112):
                draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), outline=(*accent, 65), width=4)
            draw.ellipse((cx-78, cy-78, cx+78, cy+78), fill=(255, 191, 66, 235))
            for angle in range(0, 360, 30):
                import math
                a = math.radians(angle)
                draw.line((cx+92*math.cos(a), cy+92*math.sin(a), cx+142*math.cos(a), cy+142*math.sin(a)), fill=(255, 214, 115, 210), width=7)
        elif index == 1:
            for j, color in enumerate(((255, 85, 90), (255, 161, 80), (255, 224, 89), (113, 236, 152), (82, 188, 255), (119, 120, 255))):
                y = cy - 150 + j * 58
                points = [(80, y)]
                for x in range(80, 660, 8):
                    import math
                    points.append((x, y + 19 * math.sin((x - 80) / (45 + j * 12))))
                draw.line(points, fill=(*color, 220), width=5)
        elif index in (2, 3):
            for x, y, r in ((235, 530, 45), (460, 500, 35), (335, 700, 50), (500, 740, 26), (205, 760, 24), (360, 570, 17)):
                draw.ellipse((x-r, y-r, x+r, y+r), fill=(*accent, 38), outline=(*accent, 215), width=4)
            draw.line((235,530,360,570,460,500,500,740,335,700,205,760), fill=(211, 242, 255, 125), width=4)
            for j in range(5):
                y = 450 + j * 72
                draw.line((80, y, 640, y-75), fill=(96, 202, 255, 85), width=3)
        else:
            draw.rectangle((70, 680, 650, 900), fill=(13, 111, 164, 130))
            draw.ellipse((75, 320, 645, 890), outline=(98, 207, 255, 190), width=10)
            draw.ellipse((280, 375, 440, 535), fill=(255, 196, 76, 240))
            for j, x in enumerate((180, 270, 390, 510)):
                draw.ellipse((x-15, 650-j*35, x+15, 680-j*35), fill=(148, 224, 255, 220))
    else:
        for r in (205, 160, 110):
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=(*accent, 90 + r//4), width=5)
        draw.ellipse((cx-54, cy-54, cx+54, cy+54), fill=(*accent, 205))
        for x, y in ((205, 510), (490, 550), (245, 730), (460, 750), (360, 385)):
            draw.ellipse((x-17, y-17, x+17, y+17), fill=(227, 249, 255, 240))
            draw.line((cx, cy, x, y), fill=(*accent, 150), width=3)
    draw.rounded_rectangle((48, 1010, 672, 1125), radius=26, fill=(1, 12, 30, 130), outline=(*accent, 110), width=2)
    draw.text((360, 1068), "معلومة • دليل • تفسير", font=_font(27, True), fill=(232, 246, 255), anchor="mm", direction="rtl")
    image.save(path, "PNG", optimize=True)


def _make_storyboard(output_dir, narration):
    segments = split_segments(narration)
    groups = [[] for _ in range(SCENE_COUNT)]
    for index, segment in enumerate(segments):
        groups[min(SCENE_COUNT - 1, index * SCENE_COUNT // len(segments))].append(segment)
    scenes = []
    for index, group in enumerate(groups):
        source = " ".join(group) or narration
        image_path = output_dir / f"scene-{index + 1:02}.png"
        _draw_scene(image_path, _topic_title(source, index), index, narration)
        scenes.append((image_path, sum(len(part.split()) for part in group)))
    return scenes


def render_video(script_path, title, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = Path(script_path)
    if not script_path.is_file():
        raise VideoRenderError(f"ملف المسودة غير موجود: {script_path}")
    narration = extract_narration(script_path.read_text(encoding="utf-8"))
    segments = split_segments(narration)
    model_path = Path(__import__("os").environ.get("PIPER_MODEL", "models/ar_JO-kareem-medium.onnx"))
    if not model_path.is_file():
        raise VideoRenderError(f"نموذج الصوت العربي Piper غير موجود: {model_path}")
    try:
        from piper import PiperVoice
        voice = PiperVoice.load(str(model_path))
    except Exception as error:
        raise VideoRenderError(f"تعذر تحميل الصوت العصبي العربي Piper: {error}") from None
    print(f"حُمّل الصوت العصبي العربي؛ سيتم توليد {len(segments)} مقاطع صوتية.", flush=True)

    audio_parts, captions = [], []
    cursor = INTRO_SECONDS
    sample_rate = voice.config.sample_rate
    silence = b"\x00" * round(PAUSE_SECONDS * sample_rate) * 2
    for number, segment in enumerate(segments, start=1):
        print(f"توليد الصوت العصبي: المقطع {number}/{len(segments)}.", flush=True)
        wav_path = output_dir / f"speech-{number:03}.wav"
        try:
            with wave.open(str(wav_path), "wb") as wav_file:
                voice.synthesize_wav(segment, wav_file)
        except Exception as error:
            raise VideoRenderError(f"فشل توليد الصوت العربي للمقطع {number}: {error}") from None
        params, frames = _read_wave(wav_path)
        if params.framerate != sample_rate:
            raise VideoRenderError("تغير معدل أخذ العينات في الصوت العربي بين المقاطع.")
        duration = len(frames) / (sample_rate * params.nchannels * params.sampwidth)
        if duration <= 0:
            raise VideoRenderError(f"المقطع الصوتي {number} فارغ.")
        captions.append((cursor, cursor + duration, _wrap_caption(segment)))
        audio_parts.append(frames)
        cursor += duration
        if number < len(segments):
            audio_parts.append(silence)
            cursor += PAUSE_SECONDS

    full_audio = output_dir / "narration.wav"
    with wave.open(str(full_audio), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00" * round(INTRO_SECONDS * sample_rate) * 2)
        for frames in audio_parts:
            wav_file.writeframes(frames)
        wav_file.writeframes(b"\x00" * round(OUTRO_SECONDS * sample_rate) * 2)
    (output_dir / "narration.txt").write_text(narration, encoding="utf-8")

    srt_path = output_dir / "subtitles.srt"
    cues = [(0.15, INTRO_SECONDS - 0.1, _wrap_caption(title))]
    cues.extend((start, end + 0.12, text) for start, end, text in captions)
    cues.append((cursor + 0.15, cursor + OUTRO_SECONDS - 0.1, "حقيقة علمية جديدة في كل فيديو"))
    with srt_path.open("w", encoding="utf-8", newline="\n") as destination:
        for index, (start, end, text) in enumerate(cues, start=1):
            destination.write(f"{index}\n{_format_srt_time(start)} --> {_format_srt_time(end)}\n{text}\n\n")

    print("رسم خمس مشاهد علمية مختلفة وتحريك انتقال الكاميرا بينها.", flush=True)
    scenes = _make_storyboard(output_dir, narration)
    total_words = sum(count for _, count in scenes) or 1
    spoken_duration = max(1.0, cursor - INTRO_SECONDS)
    clip_paths = []
    for index, (image_path, word_count) in enumerate(scenes):
        duration = spoken_duration * word_count / total_words if word_count else spoken_duration / SCENE_COUNT
        duration = max(1.5, duration)
        clip_path = output_dir / f"scene-video-{index + 1:02}.mp4"
        zoom = "min(zoom+0.00035,1.07)" if index % 2 == 0 else "max(zoom-0.00025,1.0)"
        animated_filter = (
            f"zoompan=z='{zoom}':d=1:s={WIDTH}x{HEIGHT}:fps={FPS},trim=duration={duration:.3f},setpts=PTS-STARTPTS,"
            "drawbox=x='mod(70+t*85,680)':y='475+70*sin(t*1.8)':w=16:h=16:color=0x57D9FF@0.95:t=fill,"
            "drawbox=x='mod(640-t*62,680)':y='620+85*cos(t*1.4)':w=12:h=12:color=0xFFC45B@0.95:t=fill,"
            "drawbox=x='mod(220+t*48,680)':y='770+55*sin(t*2.2)':w=10:h=10:color=0x9BFFD0@0.95:t=fill"
        )
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(FPS),
            "-i", str(image_path), "-vf", animated_filter,
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-crf", "24", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-movflags", "+faststart", str(clip_path),
        ], step_name=f"تحريك المشهد {index + 1}")
        clip_paths.append(clip_path)
    concat_file = output_dir / "scenes.txt"
    concat_file.write_text("".join(f"file '{path.resolve().as_posix()}'\n" for path in clip_paths), encoding="utf-8")
    joined = output_dir / "storyboard.mp4"
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(joined)], step_name="دمج المشاهد المتحركة")

    video_path = output_dir / "video.mp4"
    subtitle_filter = (
        f"subtitles={srt_path}:fontsdir=/usr/share/fonts/truetype/noto:"
        "force_style='FontName=Noto Sans Arabic,FontSize=25,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00101A2A,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV=128'"
    )
    print("إضافة الترجمة والصوت إلى تسلسل المشاهد.", flush=True)
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(joined), "-i", str(full_audio),
          "-vf", subtitle_filter, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "libx264", "-preset", "ultrafast",
          "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(video_path)],
         step_name="تركيب الفيديو والصوت")
    probe = _run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,codec_type,width,height", "-of", "json", str(video_path)], step_name="فحص ملف الفيديو الناتج")
    try:
        streams = json.loads(probe.stdout).get("streams", [])
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        audio = next(stream for stream in streams if stream.get("codec_type") == "audio")
    except (ValueError, StopIteration):
        raise VideoRenderError("لم أتمكن من التحقق من مساري الفيديو والصوت في الملف الناتج.") from None
    if (video.get("width"), video.get("height"), video.get("codec_name"), audio.get("codec_name")) != (WIDTH, HEIGHT, "h264", "aac"):
        raise VideoRenderError("الأبعاد أو ترميز الصوت والفيديو الناتج لا يطابق إعداد التصدير.")
    print(f"اكتمل الفيديو: {video_path} ({WIDTH}×{HEIGHT}، خمسة مشاهد، H.264/AAC).", flush=True)
    return video_path

