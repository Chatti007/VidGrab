#!/bin/bash

# تحديث قائمة الحزم
apt update

# تثبيت FFmpeg (يحتوي على ffprobe و ffmpeg)
apt install -y ffmpeg
