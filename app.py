from flask import Flask, render_template, request, send_file, jsonify, after_this_request
import yt_dlp
import os
import uuid
import time 
import subprocess
import json

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

# إعدادات yt-dlp المحسنة للتعامل مع YouTube الجديد
STANDARD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
}

# إعدادات أساسية موثوقة
BASE_YD_OPTS = {
    'quiet': True,
    'no_warnings': True,  # إخفاء التحذيرات
    'nocheckcertificate': True,
    'http_headers': STANDARD_HEADERS,
    'geo_bypass': True,
    'force_ipv4': True,
    'compat_opts': ['no-youtube-unavailable-videos'],
}

@app.route('/')
def home():
    return render_template('index.html')

# 🚀 جلب معلومات الفيديو باستخدام إستراتيجية متعددة
@app.route('/get-info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url: 
        return jsonify({'error': 'Please provide a URL'}), 400

    try:
        # الإستراتيجية 1: استخدام إعدادات بسيطة وموثوقة
        simple_opts = BASE_YD_OPTS.copy()
        simple_opts.update({
            'extract_flat': False,
            'ignoreerrors': True,
        })
        
        with yt_dlp.YoutubeDL(simple_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            video_formats = []
            audio_formats = []
            
            # جمع التنسيقات المتاحة
            for f in info.get('formats', []):
                # التركيز على التنسيقات الأساسية التي تعمل
                if f.get('protocol', '').startswith('http') and f.get('url'):
                    format_item = {
                        'format_id': f['format_id'],
                        'ext': f.get('ext', 'unknown'),
                        'resolution': f.get('resolution', 'N/A'),
                        'height': f.get('height'),
                        'filesize': format_bytes(f.get('filesize') or f.get('filesize_approx')),
                        'format_note': f.get('format_note', ''),
                        'vcodec': f.get('vcodec', 'none'),
                        'acodec': f.get('acodec', 'none'),
                    }
                    
                    # تصنيف التنسيقات
                    if f.get('vcodec') not in ['none', None]:
                        video_formats.append(format_item)
                    elif f.get('acodec') not in ['none', None] and f.get('vcodec') in ['none', None]:
                        audio_formats.append(format_item)
            
            # إذا لم نجد تنسيقات كافية، نستخدم الإستراتيجية 2
            if len(video_formats) < 3:
                print("Few formats found, using alternative strategy...")
                video_formats = get_fallback_formats(info)
            
            # ترتيب وتصفية التنسيقات
            video_formats = sort_and_filter_formats(video_formats)
            audio_formats = sort_and_filter_formats(audio_formats, is_audio=True)
            
            # إضافة خيارات افتراضية مضمونة
            default_formats = [
                {
                    'format_id': 'best[height<=720]',
                    'ext': 'mp4', 
                    'resolution': '720p (Recommended)',
                    'height': 720,
                    'filesize': 'Auto',
                    'format_note': 'Balanced quality & speed'
                },
                {
                    'format_id': 'best[height<=480]', 
                    'ext': 'mp4',
                    'resolution': '480p (Fast)',
                    'height': 480,
                    'filesize': 'Auto',
                    'format_note': 'Faster download'
                },
                {
                    'format_id': 'best[height<=1080]',
                    'ext': 'mp4',
                    'resolution': '1080p (HD)',
                    'height': 1080,
                    'filesize': 'Auto', 
                    'format_note': 'High quality'
                }
            ]
            
            # دمج التنسيقات المكتشفة مع الافتراضية
            final_video_formats = default_formats + video_formats[:10]
            
            return jsonify({
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration_string', 'Unknown'),
                'platform': info.get('extractor_key', 'Unknown'),
                'video_formats': final_video_formats,
                'audio_formats': audio_formats[:5]
            })
            
    except Exception as e:
        return handle_error(e)

def get_fallback_formats(info):
    """الحصول على تنسيقات بديلة إذا فشلت الطريقة الأساسية"""
    fallback_formats = []
    
    # نبحث عن أي تنسيقات متاحة
    for f in info.get('formats', []):
        if f.get('ext') in ['mp4', 'webm'] and f.get('protocol', '').startswith('http'):
            fallback_formats.append({
                'format_id': f['format_id'],
                'ext': f.get('ext', 'mp4'),
                'resolution': f.get('resolution', 'N/A'),
                'height': f.get('height'),
                'filesize': format_bytes(f.get('filesize') or f.get('filesize_approx')),
                'format_note': f.get('format_note', 'Available'),
            })
    
    return fallback_formats

def sort_and_filter_formats(formats, is_audio=False):
    """ترتيب وتصفية التنسيقات"""
    if not formats:
        return []
    
    if is_audio:
        # ترتيب تنسيقات الصوت
        return sorted(formats, key=lambda x: (
            x.get('ext') == 'mp3',
            x.get('ext') == 'm4a', 
            x.get('filesize', '0')
        ), reverse=True)
    else:
        # ترتيب تنسيقات الفيديو
        return sorted(formats, key=lambda x: (
            x.get('height') or 0,
            x.get('ext') == 'mp4',
            x.get('filesize', '0')
        ), reverse=True)

def handle_error(error):
    """معالجة الأخطاء بشكل مركزي"""
    error_message = str(error)
    print(f"Error: {error_message}")
    
    if "confirm you're not a bot" in error_message:
        display_error = "YouTube requires verification. Please try again in a few minutes."
    elif "Private" in error_message:
        display_error = "This video is private or unavailable."
    elif "unavailable" in error_message.lower():
        display_error = "This video is not available."
    elif "age restricted" in error_message.lower():
        display_error = "This video is age-restricted and cannot be downloaded."
    else:
        display_error = "Unable to process this video. Please try a different video or check the URL."
    
    return jsonify({'error': display_error}), 500

# 📥 تحميل الفيديو بإعدادات موثوقة
@app.route('/download', methods=['POST'])
def download_video():
    url = request.form.get('url')
    format_id = request.form.get('format_id')
    convert_to = request.form.get('convert_to')
    
    if not url: 
        return "Invalid URL", 400

    unique_name = str(uuid.uuid4())
    output_template = f'{TEMP_FOLDER}/{unique_name}.%(ext)s'

    ydl_opts = BASE_YD_OPTS.copy()
    ydl_opts.update({
        'outtmpl': output_template,
        'ignoreerrors': True,
        'no_overwrites': True,
    })

    try:
        if convert_to == 'mp3' or format_id == 'mp3':
            # تحويل إلى MP3
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        elif format_id and format_id.startswith('best['):
            # استخدام تنسيقات best المضمونة
            ydl_opts['format'] = format_id
        elif format_id and format_id != 'best':
            # تنسيق محدد
            ydl_opts['format'] = format_id
        else:
            # أفضل جودة مضمونة
            ydl_opts['format'] = 'best[height<=720]/best[ext=mp4]/best'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # البحث عن الملف الذي تم تنزيله
        final_file = find_downloaded_file(unique_name)
        
        if not final_file:
            return "Download completed but file not found. This might be a temporary issue. Please try again.", 500

        @after_this_request
        def cleanup(response):
            try:
                if final_file and os.path.exists(final_file):
                    os.remove(final_file)
            except Exception as e:
                print(f"Cleanup error: {e}")
            return response

        # الحصول على الامتداد الفعلي
        actual_ext = final_file.split('.')[-1]
        
        return send_file(
            final_file, 
            as_attachment=True, 
            download_name=f"download_{int(time.time())}.{actual_ext}"
        )

    except Exception as e:
        return f"Download failed. Please try a different format or video.", 500

def find_downloaded_file(unique_name):
    """الباحث عن الملف الذي تم تنزيله"""
    for f in os.listdir(TEMP_FOLDER):
        if f.startswith(unique_name):
            return os.path.join(TEMP_FOLDER, f)
    
    # إذا لم نجد بالاسم، نبحث عن أحدث ملف
    try:
        files = [f for f in os.listdir(TEMP_FOLDER) if f.endswith(('.mp4', '.mp3', '.webm'))]
        if files:
            latest_file = max(files, key=lambda f: os.path.getctime(os.path.join(TEMP_FOLDER, f)))
            return os.path.join(TEMP_FOLDER, latest_file)
    except:
        pass
    
    return None

# إضافة route لـ favicon
@app.route('/favicon.ico')
def favicon():
    return '', 404

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
