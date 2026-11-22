# بناء المُثبّت

**المتطلبات (على ويندوز 10/11):** اتصال بالإنترنت، و[Inno Setup 6.3+](https://jrsoftware.org/isinfo.php).

```
installer\build.bat
```

الناتج: `dist\MediaCatcher-Setup-<الإصدار>.exe`

## التخزين المؤقت (لا تنزيل في كل مرة)
- أول بناء ينزّل كل شيء ويحفظ نسخة جاهزة في `build\cache` (Python مع الحزم، ffmpeg، deno).
- البناءات التالية تعمل **بدون إنترنت** وتنتهي خلال ثوانٍ.
- يُعاد بناء بيئة Python تلقائياً فقط إذا تغيّر `requirements.txt`.
- لإصدار جديد بأحدث yt-dlp وdeno: `installer\build.bat -Refresh`
  (التطبيق يحدّث yt-dlp بنفسه عند أول تشغيل على أي حال).

## ما يفعله السكربت
1. ينزّل Python المحمول (embeddable) ويثبّت فيه الحزم من `local_app\requirements.txt`.
2. ينزّل ffmpeg و deno إلى `bin\`.
3. ينسخ `server.py` و`app.py` ومجلد `extension`.
4. يجري اختباراً سريعاً (استيراد الحزم + تشغيل ffmpeg/deno)، ثم يبني `setup.iss`.

## ما يفعله المُثبّت عند المستخدم
- يثبّت في `%LOCALAPPDATA%\Programs\MediaCatcher` بلا صلاحيات مدير.
- يضيف التشغيل مع ويندوز (اختياري) ويشغّل التطبيق: أيقونة في شريط المهام فيها
  فتح مجلد التحميلات، تحديث yt-dlp، التشغيل مع ويندوز، مجلد الإضافة، السجل، خروج.
- يحدّث yt-dlp تلقائياً مرة كل يوم (`pip` داخل مجلد التطبيق)، ثم يعيد التشغيل بعد انتهاء التحميلات.
- التحميلات تُحفظ في `Downloads\MediaCatcher`، ولا يحذفها إلغاء التثبيت.

## إيقاف التطبيق
- من أيقونة شريط المهام ← **خروج** (قد تكون داخل السهم `^`).
- أو من قائمة ابدأ: **Media Catcher - stop**.

## للتأكد أنك تستخدم الملفات الجديدة
- أول سطر عند تشغيل `build.bat`: `Media Catcher build script - revision 0.4.2`.
- اسم المُثبّت: `dist\MediaCatcher-Setup-0.4.2.exe` (المثبّتات القديمة تُنقل إلى `dist\old`).
- بعد التثبيت: `http://127.0.0.1:8765/health` يعرض `"version": "0.4.2"`.

## إن لم تظهر الأيقونة بعد التثبيت
- افتح من قائمة ابدأ: **Media Catcher - debug console**. يعرض أي خطأ في النافذة نفسها.
- أو افتح السجل: `%LOCALAPPDATA%\MediaCatcher\app.log`.
- التطبيق لا ينتظر الإنترنت عند البدء؛ تحديث yt-dlp يجري في الخلفية ويفشل بصمت إن لم يتوفر اتصال.

## تجربة بدون مُثبّت (بعد البناء)
```
build\app\python\python.exe build\app\app.py --no-tray --no-update
```
ثم افتح `http://127.0.0.1:8765/health`. السجل: `%LOCALAPPDATA%\MediaCatcher\app.log`.
