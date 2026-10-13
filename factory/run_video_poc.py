"""Workflow entry point: generate a script, then render a video package."""

import os
from pathlib import Path
import wave

from factory.run_script_poc import main as generate_draft
from factory.video_renderer import VideoRenderError, render_video


def main():
    generate_draft()
    title = os.environ.get("VIDEO_TITLE", "فيديو علمي قصير")
    output_dir = Path("output")
    try:
        video_path = render_video(output_dir / "script-draft.md", title, output_dir)
    except VideoRenderError as error:
        summary_value = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_value:
            summary = Path(summary_value)
            summary.write_text(f"## تعذر إنتاج الفيديو\n\n{error}\n", encoding="utf-8")
        raise SystemExit(f"خطأ إنتاج واضح: {error}") from None

    video_size = video_path.stat().st_size
    with wave.open(str(output_dir / "narration.wav"), "rb") as audio:
        duration = round(audio.getnframes() / audio.getframerate(), 1)
    print(f"المدة التقريبية: {duration} ثانية؛ الحجم: {video_size} بايت.", flush=True)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(
            "## اكتمل إثبات إنتاج الفيديو\n\n"
            f"- الفكرة: {title}\n"
            f"- الملف: `{video_path}`\n"
            "- الأبعاد: 720×1280 (9:16)\n"
            f"- الحجم: {video_size} بايت\n"
            f"- المدة التقريبية: {duration} ثانية\n"
            "- الصوت: eSpeak NG، صوت عربي آلي يحتاج معاينة بشرية.\n"
            "- المسودة والادعاءات تحتاج مراجعة بشرية؛ لم يتم النشر.\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
