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

# رؤوس HTTP لتقليد متصفح حقيقي
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
    }
    
    # Bypassات ضد YouTube bot detection
    ydl_opts["extractor_args"] = {
        "youtube": {
            "player_client": ["ios", "android", "web_embedded"],
            "skip_captcha": ["yes"],
            "max_comments": ["0"]
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # process=False لتقليل فرصة الـ bot check
            info = ydl.extract_info(url, download=False, process=False)
            
            video_formats = []
            audio_formats = []
            seen_resolutions = set()
            
            # 1. جمع وتصنيف الصيغ
            for f in info.get('formats', []):
                size = f.get('filesize') or f.get('filesize_approx')
                
                # A. صيغ الفيديو (مع دمج الصوت التلقائي إذا كانت بدون صوت)
                if f.get('vcodec') != 'none' and f.get('ext') in ['mp4', 'webm', '3gp', 'flv']:
                    res = f.get('resolution')
                    # نضيف فقط صيغ الفيديو التي لها دقة محددة
                    if res and res != 'none' and res not in seen_resolutions: 
                        video_formats.append({
                            'format_id': f['format_id'],
                            'ext': f['ext'],
                            'resolution': res,
                            'filesize': format_bytes(size),
                            'note': f.get('format_note', 'Video')
                        })
                        seen_resolutions.add(res)
                        
                # B. صيغ الصوت النقي
                elif f.get('acodec') != 'none' and f.get('vcodec') == 'none' and f.get('ext') in ['m4a', 'webm', 'ogg']:
                    audio_formats.append({
                        'format_id': f['format_id'],
                        'ext': f['ext'],
                        'resolution': f'{f.get("abr", "Unknown")} kbps', # Audio Bitrate
                        'filesize': format_bytes(size),
                        'note': f.get('format_note', 'Audio')
                    })
            
            # 2. إضافة خيارات تحويل MP3 (لتحديد الجودة مع الحجم المقدر)
            if info.get('duration') and info.get('duration') > 0:
                duration_sec = info.get('duration')
                
                # تقدير الحجم لـ 320 kbps (جودة عالية)
                size_high = (duration_sec * 320000) / 8 
                audio_formats.insert(0, {
                    'format_id': 'mp3-high',
                    'ext': 'mp3',
                    'resolution': '320 kbps (High Quality)',
                    'filesize': format_bytes(size_high),
                    'note': 'Convert to MP3'
                })
                
                # تقدير الحجم لـ 128 kbps (جودة قياسية)
                size_low = (duration_sec * 128000) / 8 
                audio_formats.insert(0, {
                    'format_id': 'mp3-low',
                    'ext': 'mp3',
                    'resolution': '128 kbps (Standard)',
                    'filesize': format_bytes(size_low),
                    'note': 'Convert to MP3'
                })

            # 3. الفرز وتجهيز الخرج
            # الفرز بناءً على الدقة (الأعلى أولاً)
            video_formats.sort(key=lambda x: int(x.get('resolution').split('x')[0]) if 'x' in x.get('resolution', '0') else 0, reverse=True)
            audio_formats.sort(key=lambda x: x.get('resolution', 'Z'), reverse=True)

            return jsonify({
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration_string'),
                'platform': info.get('extractor_key'),
                'video_formats': video_formats,
                'audio_formats': audio_formats
            })

    except Exception as e:
        error_message = str(e)

        if ("confirm you're not a bot" in error_message or
            "Sign in to" in error_message or
            "login required" in error_message):

            return jsonify({
                # رسالة خطأ واضحة للمستخدم
                'error': "⚠️ الفيديو مقيّد بشدة ويحتاج تسجيل دخول أو YouTube قام بحظر الطلب. يُرجى تجربة رابط آخر."
            }), 500

        return jsonify({'error': f"Failed: {error_message}"}), 500


# 📥 تحميل الفيديو
# -------------------------------------------------------------------

@app.route('/download', methods=['POST'])
def download_video():
    url = request.form.get('url')
    format_id = request.form.get('format_id')
    
    if not url or not format_id:
        return "Invalid URL or format selection", 400

    unique_name = str(uuid.uuid4())
    output_template = f'{TEMP_FOLDER}/{unique_name}.%(ext)s'
    
    # تحديد اللاحقة الافتراضية، ستتغير لاحقاً
    found_ext = 'mp4' 

    ydl_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'nocheckcertificate': True,
        'http_headers': STANDARD_HEADERS,
    }

    # Bypassات
    ydl_opts["extractor_args"] = {
        "youtube": {
            "player_client": ["ios", "android", "web_embedded"],
            "skip_captcha": ["yes"],
        }
    }

    # --- معالجة خيارات التحميل الجديدة ---
    if format_id.startswith('mp3-'):
        # 1. تحويل MP3
        bitrate = '320K' if format_id == 'mp3-high' else '128K'
        
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': bitrate # استخدام الجودة المحددة
            }],
        })
        found_ext = 'mp3'
        
    else:
        # 2. صيغ الفيديو أو الصوت النقي المحددة
        
        # دائماً حاول دمج الفيديو مع أفضل صوت متاح
        ydl_opts['format'] = f"{format_id}+bestaudio/best"
        
        # دمج النتيجة النهائية إلى mp4 (للفيديو)
        ydl_opts['merge_output_format'] = 'mp4'
        
        # استثناء: إذا كان Format ID هو لصيغة صوت نقي، يجب ألا ندمج الفيديو/الصوت
        # هذا الجزء معقد ويجب أن يتطلب الوصول إلى بيانات info مرة أخرى، لكن لتجنب الاتصال مرتين
        # سنعتمد على أن yt-dlp سيتجاهل الدمج إذا كان format_id هو لصيغة صوت صافية.
        # مع yt-dlp، الدمج لا يتم إلا إذا كان هناك حاجة لذلك.
        
        # لضمان اللاحقة الصحيحة:
        if 'audio' in format_id or 'm4a' in format_id or 'webm' in format_id:
            if format_id != 'bestaudio':
                 ydl_opts['format'] = format_id # حمل الصوت فقط
                 ydl_opts['merge_output_format'] = None # لا تدمج
                 found_ext = 'm4a' # قد يكون webm أو m4a

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        final_file = None
        
        # البحث عن الملف الناتج (تحديد اللاحقة الحقيقية)
        for f in os.listdir(TEMP_FOLDER):
            if f.startswith(unique_name):
                final_file = os.path.join(TEMP_FOLDER, f)
                found_ext = f.split('.')[-1] # اللاحقة الحقيقية للملف
                break

        if not final_file:
            return "Error: File not found after processing. Check ffmpeg logs.", 500

        @after_this_request
        def cleanup(response):
            try:
                if os.path.exists(final_file):
                    os.remove(final_file)
            except:
                pass
            return response

        return send_file(
            final_file,
            as_attachment=True,
            download_name=f"VidGrab_{int(time.time())}.{found_ext}"
        )

    except Exception as e:
        return f"Download Failed: {str(e)}", 500


if __name__ == '__main__':
    pass
