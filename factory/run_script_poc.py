"""Workflow entry point: generate a draft and save it as a Markdown artifact."""

import os
from pathlib import Path

from factory.script_generator import generate_script


def main():
    title = os.environ.get("VIDEO_TITLE", "")
    source_notes = os.environ.get("SOURCE_NOTES", "")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")
    draft = generate_script(title, source_notes, model=model)

    output = Path("output") / "script-draft.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"# {title.strip()}\n\n"
        "> مسودة مولدة آليًا؛ راجع الادعاءات والمراجع قبل اعتمادها.\n\n"
        f"{draft}\n",
        encoding="utf-8",
    )
    print("تم إنشاء المسودة. نزّل artifact باسم script-draft لمراجعتها.")


if __name__ == "__main__":
    main()
