import os
import time
import re
import unicodedata
from flask import Flask, request, send_file, after_this_request, render_template_string
import yt_dlp

app = Flask(__name__)

TEMP_FOLDER = "temp"
os.makedirs(TEMP_FOLDER, exist_ok=True)

STANDARD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
                  '(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
}

# ✨ تنظيف أسماء الملفات لتكون صالحة على أي نظام
def sanitize_filename(filename):
    nfkd_form = unicodedata.normalize('NFKD', filename)
    cleaned = "".join([c for c in nfkd_form if ord(c) < 128])
    cleaned = re.sub(r'[<>:"/\\|?*]', '', cleaned)
    return cleaned

# صفحة HTML بسيطة
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>VidGrab Downloader</title>
</head>
<body>
<h2>VidGrab - تحميل الفيديوهات</h2>
<form action="/download" method="post">
<label>رابط الفيديو:</label><br>
<input type="text" name="url" size="50" required><br><br>
<label>الصيغة:</label><br>
<select name="format">
  <option value="mp3-high">MP3 عالي الجودة</option>
  <option value="mp3-low">MP3 منخفض الجودة</option>
  <option value="mp4-high">MP4 عالي الجودة</option>
  <option value="mp4-low">MP4 منخفض الجودة</option>
  <option value="3gp">3GP</option>
</select><br><br>
<input type="submit" value="تحميل">
</form>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_PAGE)

@app.route("/download", methods=["POST"])
def download():
    url = request.form.get("url")
    format_id = request.form.get("format", "mp4-high")
    unique_name = str(int(time.time()))
    
    # إخراج الملفات
    output = os.path.join(TEMP_FOLDER, sanitize_filename(unique_name) + ".%(ext)s")

    # إعدادات yt-dlp
    ydl_opts = {
        'outtmpl': output,
        'quiet': True,
        'nocheckcertificate': True,
        'http_headers': STANDARD_HEADERS,
        'encoding': 'utf-8',
    }

    if format_id.startswith('mp3-'):
        bitrate = '320' if format_id == 'mp3-high' else '128'
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': bitrate,
            }],
        })
        found_ext = 'mp3'
    elif format_id == '3gp':
        ydl_opts['format'] = 'worstaudio/worst'
        ydl_opts['merge_output_format'] = '3gp'
        found_ext = '3gp'
    else:
        # صيغة فيديو mp4
        ydl_opts['format'] = f"{format_id}+bestaudio/best"
        ydl_opts['merge_output_format'] = 'mp4'
        found_ext = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        final_file = next(
            (os.path.join(TEMP_FOLDER, f) for f in os.listdir(TEMP_FOLDER) if f.startswith(unique_name)),
            None
        )
        if not final_file:
            return "File not found", 500

        @after_this_request
        def clean(response):
            try:
                if os.path.exists(final_file):
                    os.remove(final_file)
            except:
                pass
            return response

        return send_file(
            final_file,
            as_attachment=True,
            download_name=sanitize_filename(f"VidGrab_{int(time.time())}.{found_ext}"),
            mimetype='audio/mpeg' if found_ext == 'mp3' else None
        )

    except Exception as e:
        return f"Download Failed: {e}", 500

if __name__ == "__main__":
    from os import environ
    app.run(host="0.0.0.0", port=int(environ.get("PORT", 5000)))
