from flask import Flask, request, jsonify, send_file, render_template_string
import yt_dlp
import os
import uuid
import threading
import time

app = Flask(__name__)
DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Auto delete files after 10 min
def auto_delete(path, delay=600):
    def delete():
        time.sleep(delay)
        if os.path.exists(path):
            os.remove(path)
    threading.Thread(target=delete, daemon=True).start()

HTML = open("index.html", encoding="utf-8").read()

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/info", methods=["POST"])
def get_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400
    try:
        ydl_opts = {"quiet": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            seen = set()
            for f in info.get("formats", []):
                height = f.get("height")
                ext = f.get("ext")
                if height and ext in ["mp4", "webm"] and height not in seen:
                    seen.add(height)
                    formats.append({
                        "format_id": f["format_id"],
                        "quality": f"{height}p",
                        "ext": ext,
                        "filesize": f.get("filesize") or 0
                    })
            formats.sort(key=lambda x: int(x["quality"].replace("p","")), reverse=True)
            return jsonify({
                "title": info.get("title", "Video"),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", ""),
                "formats": formats[:6]
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/download", methods=["POST"])
def download():
    data = request.json
    url = data.get("url", "").strip()
    format_id = data.get("format_id", "best")
    if not url:
        return jsonify({"error": "URL required"}), 400
    try:
        filename = str(uuid.uuid4())
        output_path = os.path.join(DOWNLOAD_DIR, filename)
        ydl_opts = {
            "format": f"{format_id}+bestaudio/best" if format_id != "best" else "best[ext=mp4]/best",
            "outtmpl": output_path + ".%(ext)s",
            "quiet": True,
            "merge_output_format": "mp4",
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")
        # Find downloaded file
        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(filename):
                full_path = os.path.join(DOWNLOAD_DIR, f)
                auto_delete(full_path)
                safe_title = "".join(c for c in title if c.isalnum() or c in " -_")[:50]
                return send_file(
                    full_path,
                    as_attachment=True,
                    download_name=f"{safe_title}.mp4"
                )
        return jsonify({"error": "Download failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
