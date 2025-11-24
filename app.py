from flask import Flask, render_template, request, send_file, jsonify, after_this_request, redirect, Response, stream_with_context
import yt_dlp
import os
import uuid
import time
import ssl
import certifi
import subprocess
import json
from flask import abort
from functools import wraps

app = Flask(__name__)

# Rate limiting decorator
def limit_content_length(max_length):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if request.content_length and request.content_length > max_length:
                abort(413)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# إصلاح مشكلة SSL في Termux
ssl._create_default_https_context = ssl._create_unverified_context

# التحقق من وجود FFmpeg
def check_ffmpeg():
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        return result.returncode == 0
    except:
        return False

HAS_FFMPEG = check_ffmpeg()
print(f"FFmpeg available: {HAS_FFMPEG}")

# إعداد مجلد التحميل المؤقت
TEMP_FOLDER = "temp_downloads"
if not os.path.exists(TEMP_FOLDER):
    os.makedirs(TEMP_FOLDER)

def format_bytes(size):
    if not size: return "Unknown"
    power = 2**10
    n = 0
    power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f}{power_labels[n]}B"

# إعدادات yt-dlp المحسنة
STANDARD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
}

BASE_YD_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'http_headers': STANDARD_HEADERS,
    'geo_bypass': True,
    'force_ipv4': True,
    'compat_opts': ['no-youtube-unavailable-videos'],
}

class DownloadProgress:
    def __init__(self):
        self.progress = 0
        self.status = "Preparing..."
        self.file_path = ""

download_progress = DownloadProgress()

def progress_hook(d):
    global download_progress
    if d['status'] == 'downloading':
        total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
        downloaded_bytes = d.get('downloaded_bytes', 0)
        if total_bytes and total_bytes > 0:
            download_progress.progress = int((downloaded_bytes / total_bytes) * 100)
            download_progress.status = f"Downloading... {download_progress.progress}%"
    elif d['status'] == 'finished':
        download_progress.progress = 100
        download_progress.status = "Processing..."
        download_progress.file_path = d.get('filename', '')

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/dmca')
def dmca():
    return render_template('dmca.html')

@app.route('/fair-use')
def fair_use():
    return render_template('fair_use.html')

# 🚀 Get video info
@app.route('/get-info', methods=['POST'])
@limit_content_length(10 * 1024 * 1024)  # 10MB limit
def get_info():
    url = request.json.get('url')
    if not url: 
        return jsonify({'error': 'Please enter a video URL'}), 400

    try:
        # Clean URL
        url = url.strip()
        
        if 'youtube.com/shorts/' in url:
            url = url.replace('youtube.com/shorts/', 'youtube.com/watch?v=')
        
        if '?si=' in url:
            url = url.split('?si=')[0]
            
        # Block Facebook
        if 'facebook.com' in url.lower():
            return jsonify({
                'error': 'Facebook videos are not supported. Please use YouTube or TikTok.'
            }), 400
        
        print(f"Processing URL: {url}")
        
        ydl_opts = BASE_YD_OPTS.copy()
        ydl_opts.update({
            'ignoreerrors': True,
            'no_overwrites': True,
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        video_formats = []
        audio_formats = []
        
        # Collect formats
        for f in info.get('formats', []):
            if f.get('protocol', '').startswith('http') and f.get('url'):
                format_item = {
                    'format_id': f.get('format_id', 'unknown'),
                    'ext': f.get('ext', 'unknown'),
                    'resolution': f.get('resolution', 'N/A'),
                    'height': f.get('height', 0),
                    'filesize': format_bytes(f.get('filesize') or f.get('filesize_approx')),
                    'format_note': f.get('format_note', ''),
                }
                
                if f.get('vcodec') not in ['none', None]:
                    video_formats.append(format_item)
                elif f.get('acodec') not in ['none', None]:
                    audio_formats.append(format_item)
        
        # Sort formats
        video_formats.sort(key=lambda x: x.get('height') or 0, reverse=True)
        audio_formats.sort(key=lambda x: x.get('filesize', '0'), reverse=True)
        
        # Add default options
        default_formats = [
            {
                'format_id': 'best[height<=720]',
                'ext': 'mp4', 
                'resolution': '720p (Recommended)',
                'height': 720,
                'filesize': 'Auto',
                'format_note': 'Balanced quality'
            },
            {
                'format_id': 'best[height<=480]', 
                'ext': 'mp4',
                'resolution': '480p (Fast)',
                'height': 480,
                'filesize': 'Auto',
                'format_note': 'Faster download'
            }
        ]
        
        # Add MP3 option if FFmpeg available
        if HAS_FFMPEG:
            audio_formats.insert(0, {
                'format_id': 'mp3',
                'ext': 'mp3',
                'resolution': 'MP3',
                'height': 0,
                'filesize': 'Auto',
                'format_note': 'High quality audio'
            })
        else:
            audio_formats.insert(0, {
                'format_id': 'bestaudio',
                'ext': 'm4a',
                'resolution': 'Audio',
                'height': 0,
                'filesize': 'Auto',
                'format_note': 'Audio (No MP3)'
            })
        
        final_video_formats = default_formats + video_formats[:8]
        
        return jsonify({
            'title': info.get('title', 'Unknown title'),
            'thumbnail': info.get('thumbnail', ''),
            'duration': info.get('duration_string', 'Unknown'),
            'platform': info.get('extractor_key', 'Unknown'),
            'has_ffmpeg': HAS_FFMPEG,
            'video_formats': final_video_formats,
            'audio_formats': audio_formats[:4]
        })
        
    except Exception as e:
        print(f"Error in get-info: {str(e)}")
        return handle_error(e)

def handle_error(error):
    """Error handling"""
    error_message = str(error)
    print(f"Detailed error: {error_message}")
    
    if "Video not available" in error_message:
        display_error = "Video not available. Please try another video."
    elif "Private" in error_message:
        display_error = "This video is private or unavailable."
    elif "unavailable" in error_message.lower():
        display_error = "This video is unavailable."
    else:
        display_error = "Could not process the video. Please check the URL."
    
    return jsonify({'error': display_error}), 500

# 📥 Download progress endpoint
@app.route('/progress')
def progress():
    def generate():
        while True:
            yield f"data: {json.dumps({'progress': download_progress.progress, 'status': download_progress.status})}\n\n"
            time.sleep(1)
    
    return Response(generate(), mimetype='text/event-stream')

# 📥 Download video with enhanced MP3 support
@app.route('/download', methods=['POST'])
@limit_content_length(10 * 1024 * 1024)  # 10MB limit
def download_video():
    global download_progress
    
    url = request.form.get('url')
    format_id = request.form.get('format_id')
    
    if not url: 
        return "Invalid URL", 400

    # Reset progress
    download_progress.progress = 0
    download_progress.status = "Starting download..."
    download_progress.file_path = ""

    unique_name = str(uuid.uuid4())
    output_template = f'{TEMP_FOLDER}/{unique_name}.%(ext)s'

    ydl_opts = BASE_YD_OPTS.copy()
    ydl_opts.update({
        'outtmpl': output_template,
        'ignoreerrors': True,
        'no_overwrites': True,
        'progress_hooks': [progress_hook],
    })

    try:
        # Determine settings based on selection
        if format_id == 'mp3':
            if not HAS_FFMPEG:
                return "MP3 conversion not available. Please install FFmpeg.", 500
                
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        elif format_id and format_id != 'best':
            ydl_opts['format'] = format_id
        else:
            ydl_opts['format'] = 'best[height<=720]/best[ext=mp4]/best'

        print(f"Downloading video: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        final_file = find_downloaded_file(unique_name)
        
        if not final_file:
            return "Download completed but file not found.", 500

        download_progress.status = "Download complete! Starting file transfer..."

        @after_this_request
        def cleanup(response):
            try:
                if final_file and os.path.exists(final_file):
                    os.remove(final_file)
            except Exception as e:
                print(f"Cleanup error: {e}")
            return response

        actual_ext = final_file.split('.')[-1]
        
        return send_file(
            final_file, 
            as_attachment=True, 
            download_name=f"download_{int(time.time())}.{actual_ext}"
        )

    except Exception as e:
        print(f"Download error: {str(e)}")
        download_progress.status = f"Download failed: {str(e)}"
        return f"Download failed. Please try again.", 500

def find_downloaded_file(unique_name):
    """Find the downloaded file"""
    for f in os.listdir(TEMP_FOLDER):
        if f.startswith(unique_name):
            return os.path.join(TEMP_FOLDER, f)
    
    try:
        files = [f for f in os.listdir(TEMP_FOLDER) if f.endswith(('.mp4', '.mp3', '.webm', '.m4a'))]
        if files:
            latest_file = max(files, key=lambda f: os.path.getctime(os.path.join(TEMP_FOLDER, f)))
            return os.path.join(TEMP_FOLDER, latest_file)
    except:
        pass
    
    return None

@app.route('/download', methods=['GET'])
def handle_get_download():
    return redirect('/')

@app.route('/favicon.ico')
def favicon():
    return '', 404

@app.route('/install-ffmpeg')
def install_ffmpeg_guide():
    return '''
    <html>
    <head><title>Install FFmpeg</title></head>
    <body style="font-family: Arial; background: #0f1117; color: white; padding: 20px;">
        <h1>🎵 Install FFmpeg for MP3 Support</h1>
        <p>To enable video to MP3 conversion, run these commands in Termux:</p>
        <div style="background: #1e212b; padding: 15px; border-radius: 10px; margin: 10px 0;">
            <code style="color: #6C63FF;">
            pkg update && pkg upgrade<br>
            pkg install ffmpeg<br>
            # Then restart the application
            </code>
        </div>
        <a href="/" style="color: #6C63FF;">← Back to Home</a>
    </body>
    </html>
    '''

# Error handler for 413
@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'Request too large'}), 413

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

