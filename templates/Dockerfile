FROM python:3.9-slim

WORKDIR /app

# تثبيت FFmpeg
RUN apt-get update && apt-get install -y ffmpeg

# نسخ الملفات
COPY . .

# تثبيت المتطلبات
RUN pip install --no-cache-dir -r requirements.txt

# فتح المنفذ
EXPOSE 5000

# تشغيل التطبيق
CMD ["python", "app.py"]
