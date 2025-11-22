from flask import Flask, render_template, request, send_file, jsonify, after_this_request
import yt_dlp
import os
import uuid
import time 

app = Flask(__name__)

# إعداد مجلد التحميل المؤقت
TEMP_FOLDER = "temp_downloads"
if not os.path.exists(TEMP_FOLDER):
    os.makedirs(TEMP_FOLDER)

# دالة لتحويل حجم الملف إلى نص مقروء
def format_bytes(size):
    if not size: return "Unknown"
    power = 2**10
    n = 0
    power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f}{power_labels[n]}B"

# إعدادات الرأس لتقليد متصفح حقيقي (لمنع الحظر)
STANDARD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

@app.route('/')
def home():
    return render_template('index.html')

# 🚀 جلب معلومات الفيديو
# -------------------------------------------------------------------

@app.route('/get-info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url: return jsonify({'error': 'Please provide a URL'}), 400

    ydl_opts = {
        'quiet': True, 
        'no_warnings': True, 
        'nocheckcertificate': True,
        'http_headers': STANDARD_HEADERS,
        'geo_bypass': True,  # ✨ التعديل الأول: لتجاوز القيود الجغرافية
        'force_ipv4': True,  # ✨ التعديل الثاني: لإجبار الاتصال على IPv4 (يساعد في بعض مشاكل الاتصال)
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats_list = []
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none' and f.get('resolution') != 'audio only':
                    size = f.get('filesize') or f.get('filesize_approx')
                    formats_list.append({
                        'format_id': f['format_id'],
                        'ext': f['ext'],
                        'resolution': f.get('resolution') or f.get('height'),
                        'filesize': format_bytes(size),
                        'note': f.get('format_note', '')
                    })
            
            formats_list.reverse() 

            return jsonify({
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration_string'),
                'platform': info.get('extractor_key'),
                'formats': formats_list[:15]
            })
    except Exception as e:
        # إرجاع خطأ أو رسالة عامة لتجنب تفاصيل yt-dlp المعقدة
        error_message = str(e)
        if "confirm you're not a bot" in error_message:
            display_error = "Error: This video requires login or is restricted. Please try another video."
        else:
            display_error = f"Failed to fetch video details: {error_message}"
            
        return jsonify({'error': display_error}), 500

# 📥 تحميل الفيديو
# -------------------------------------------------------------------

@app.route('/download', methods=['POST'])
def download_video():
    url = request.form.get('url')
    format_id = request.form.get('format_id')
    convert_to = request.form.get('convert_to')
    
    if not url: return "Invalid URL", 400

    unique_name = str(uuid.uuid4())
    output_template = f'{TEMP_FOLDER}/{unique_name}.%(ext)s'

    ydl_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'nocheckcertificate': True,
        'http_headers': STANDARD_HEADERS,
        'geo_bypass': True,  # ✨ التعديل الثالث
        'force_ipv4': True,  # ✨ التعديل الرابع
    }

    if convert_to == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        })
    else:
        ydl_opts['merge_output_format'] = convert_to
        if format_id and format_id != 'best':
            ydl_opts['format'] = f"{format_id}+bestaudio/best"
        else:
            ydl_opts['format'] = "bestvideo+bestaudio/best"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        final_file = None
        found_ext = convert_to
        for f in os.listdir(TEMP_FOLDER):
            if f.startswith(unique_name):
                final_file = os.path.join(TEMP_FOLDER, f)
                found_ext = f.split('.')[-1]
                break
        
        if not final_file: return "Error: File not found after processing. Check Termux logs for ffmpeg errors.", 500

        @after_this_request
        def cleanup(response):
            try:
                if os.path.exists(final_file): os.remove(final_file)
            except: pass
            return response

        return send_file(
            final_file, 
            as_attachment=True, 
            download_name=f"VidGrab_{int(time.time())}.{found_ext}"
        )

    except Exception as e:
        return f"Download Failed: {str(e)}", 500

if __name__ == '__main__':
    # لا داعي لتشغيله محليًا إذا كنت تستخدم Render
    # app.run(debug=True, host='0.0.0.0', port=5000)
    pass
