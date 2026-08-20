<div dir="rtl">

# سير عمل GitHub Actions لإصدار Windows

سير العمل الفعّال موجود الآن في [`.github/workflows/windows-release.yml`](../.github/workflows/windows-release.yml) تحت اسم **Windows Release**. يعمل على بيئة `windows-latest`، وينشئ مثبت NSIS لنظام Windows x64.

## ما الذي يتحقق منه السير؟

| المرحلة | النتيجة المتوقعة |
| --- | --- |
| إعداد بيئة Windows | تجهيز Python وpnpm وNode.js وRust لهدف `x86_64-pc-windows-msvc`. |
| جودة المحرك الخلفي | تشغيل `ruff check app tests` و`pytest -q`. |
| العملية الجانبية | بناء Python/FastAPI عبر PyInstaller ثم تشغيلها وفحص نقطة `/health`. |
| جودة الواجهة | تثبيت تبعيات الواجهة ثم تشغيل `pnpm lint`. |
| الحزمة | بناء Tauri مع هدف Windows x64 ثم إنتاج ملف NSIS `.exe`. |
| الإخراج | رفع المثبت Artifact؛ وعند دفع وسم يبدأ بـ `v`، نشره أيضًا في GitHub Release. |

## تشغيله يدويًا

من صفحة **Actions** في المستودع، افتح **Windows Release** ثم اختر **Run workflow** على الفرع `main`. سيظهر ملف المثبت بعد نجاح المهمة داخل قسم Artifacts في التنفيذ.

## نشر إصدار جديد

أنشئ وسمًا يبدأ بحرف `v` مثل `v0.2.0` وادفعه إلى GitHub. يشغل الوسم السير تلقائيًا، وبعد نجاح الفحوصات ينشر ملف `.exe` في صفحة الإصدار المطابقة.

> لا تضع مفاتيح API أو أي بيانات سرية في متغيرات السير أو ملفات المستودع. ملف المثبت لا يتضمن Ollama ولا نموذجًا لغويًا؛ يظل تنزيلهما قرارًا محليًا للمستخدم.

</div>
