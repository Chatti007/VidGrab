from flask import Flask, render_template, request, send_file, jsonify, after_this_request
import yt_dlp
import os
import uuid
import time
import tempfile

app = Flask(__name__)

# 📌 مجلد مؤقت (ضروري ل Railway و Heroku)
TEMP_FOLDER = tempfile.gettempdir()
print("⚠ TEMP FOLDER =", TEMP_FOLDER)

def format_bytes(size):
    if not size: return "Unknown"
    power = 2**10
    n = 0
    labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f}{labels[n]}B"

STANDARD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, مثل Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

@app.route('/')
def home():
    return render_template('index.html')  # لأن عندك HTML من قبل

@app.route('/get-info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url: return jsonify({'error': 'Please provide a URL'}), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'http_headers': STANDARD_HEADERS,
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "android", "web_embedded"],
                "skip_captcha": ["yes"],
                "max_comments": ["0"]
            }
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)

            video_formats, audio_formats, seen_res = [], [], set()

            for f in info.get('formats', []):
                size = f.get('filesize') or f.get('filesize_approx')

                if f.get('vcodec') != 'none':
                    res = f.get('resolution')
                    if res and res != 'none' and res not in seen_res:
                        video_formats.append({
                            'format_id': f['format_id'],
                            'ext': f['ext'],
                            'resolution': res,
                            'filesize': format_bytes(size),
                            'note': f.get('format_note', 'Video')
                        })
                        seen_res.add(res)

                elif f.get('acodec') != 'none':
                    audio_formats.append({
                        'format_id': f['format_id'],
                        'ext': f['ext'],
                        'resolution': f'{f.get("abr", "Unknown")} kbps',
                        'filesize': format_bytes(size),
                        'note': f.get('format_note', 'Audio')
                    })

            # خيارات MP3
            if info.get('duration'):
                d = info['duration']
                audio_formats.insert(0, {
                    'format_id': 'mp3-high',
                    'ext': 'mp3',
                    'resolution': '320 kbps',
                    'filesize': format_bytes(d * 320000 / 8),
                    'note': 'Convert to MP3'
                })
                audio_formats.insert(0, {
                    'format_id': 'mp3-low',
                    'ext': 'mp3',
                    'resolution': '128 kbps',
                    'filesize': format_bytes(d * 128000 / 8),
                    'note': 'Convert to MP3'
                })

            video_formats.sort(key=lambda x: int(x['resolution'].split('x')[0]) if 'x' in x['resolution'] else 0, reverse=True)
            audio_formats.sort(key=lambda x: x.get('resolution', ''), reverse=True)

            return jsonify({
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration_string'),
                'platform': info.get('extractor_key'),
                'video_formats': video_formats,
                'audio_formats': audio_formats
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download_video():
    url = request.form.get('url')
    format_id = request.form.get('format_id')
    if not url or not format_id: return "Invalid URL or format selection", 400

    unique_name = str(uuid.uuid4())
    output = f"{TEMP_FOLDER}/{unique_name}.%(ext)s"
    found_ext = "mp4"

    ydl_opts = {
        'outtmpl': output,
        'quiet': True,
        'nocheckcertificate': True,
        'http_headers': STANDARD_HEADERS,
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
    else:
        ydl_opts['format'] = f"{format_id}+bestaudio/best"
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        final_file = next(
            (os.path.join(TEMP_FOLDER, f) for f in os.listdir(TEMP_FOLDER) if f.startswith(unique_name)),
            None
        )
        if not final_file: return "File not found", 500
        found_ext = final_file.split('.')[-1]

        @after_this_request
        def clean(r):
            try:
                if os.path.exists(final_file): os.remove(final_file)
            except: pass
            return r

        return send_file(
            final_file,
            as_attachment=True,
            download_name=f"VidGrab_{int(time.time())}.{found_ext}",
            mimetype='audio/mpeg' if found_ext == 'mp3' else None
        )
    except Exception as e:
        return f"Download Failed: {e}", 500

# تشغيل على Railway
if __name__ == "__main__":
    from os import environ
    app.run(host="0.0.0.0", port=int(environ.get("PORT", 5000)))
