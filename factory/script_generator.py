"""Generate a sourced Arabic short-video draft with a local Ollama model."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ScriptGenerationError(RuntimeError):
    """An actionable error suitable for a workflow summary."""


def generate_script(title, source_notes, *, model="qwen2.5:1.5b", base_url="http://127.0.0.1:11434",
                    timeout=240, opener=urlopen):
    title = title.strip() if isinstance(title, str) else ""
    source_notes = source_notes.strip() if isinstance(source_notes, str) else ""
    if not title:
        raise ScriptGenerationError("عنوان الفكرة مطلوب.")
    if not source_notes:
        raise ScriptGenerationError("أضف ملاحظات أو روابط المصادر قبل توليد المسودة.")

    prompt = f"""اكتب نص إلقاء لفيديو قصير مدته 45 إلى 60 ثانية بالعربية الفصحى المبسطة.
الفكرة: {title}
المعلومات والمصادر المقدمة:
{source_notes}

قواعد التحرير:
- اجعل نص الإلقاء نفسه بين 80 و100 كلمة عربية، ولا تتجاوز 100 كلمة قبل قسم المصادر.
- اختصر إلى الفكرة الأهم فقط؛ جمل قصيرة ومباشرة تناسب ريلز مدته دقيقة.
- ابنِ النص على المعلومات المقدمة فقط، ولا تخترع حقائق أو أرقامًا أو مراجع.
- ابدأ بخطاف موجز، ثم اشرح الفكرة بوضوح، واختم بسؤال أو خلاصة.
- إذا لم تدعم المصادر ادعاءً ما، اكتب بجواره [يحتاج تحققًا] بدل صياغته كحقيقة.
- أضف في النهاية قسمًا بعنوان «مصادر المراجعة» وانقل الروابط التي زودك بها المستخدم كما هي.
- أخرج مسودة قابلة للمراجعة، ولا تدّعِ أن الحقائق تحققت آليًا."""

    request = Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 320},
        }, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 404:
            raise ScriptGenerationError(f"لم يتمكن Ollama من العثور على النموذج {model}.") from None
        raise ScriptGenerationError(f"فشل النموذج المحلي برمز HTTP {error.code}.") from None
    except (URLError, TimeoutError, OSError):
        raise ScriptGenerationError("تعذر الاتصال بخدمة Ollama داخل عامل GitHub.") from None
    except (ValueError, TypeError):
        raise ScriptGenerationError("استجابة Ollama غير صالحة.") from None

    result = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(result, str) or not result.strip():
        raise ScriptGenerationError("أعاد النموذج نصًا فارغًا.")
    return result.strip()

