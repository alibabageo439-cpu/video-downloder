from flask import Flask, request, jsonify, send_file, render_template_string
import yt_dlp
import os, uuid, threading, time

app = Flask(__name__)
DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
jobs = {}

def auto_delete(path, delay=600):
    def d():
        time.sleep(delay)
        if os.path.exists(path): os.remove(path)
    threading.Thread(target=d, daemon=True).start()

def get_opts():
    return {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "socket_timeout": 60,
        "retries": 10,
        "fragment_retries": 10,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "android_embedded", "web"],
                "player_skip": ["webpage", "configs"],
            }
        },
    }

def do_download(job_id, url, format_id):
    try:
        output_path = os.path.join(DOWNLOAD_DIR, job_id)

        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                dl = d.get("downloaded_bytes", 0)
                if total > 0:
                    jobs[job_id]["percent"] = int(dl / total * 100)
                    jobs[job_id]["downloaded"] = dl
                    jobs[job_id]["total"] = total
            elif d["status"] == "finished":
                jobs[job_id]["percent"] = 99

        opts = get_opts()
        opts.update({
            "outtmpl": output_path + ".%(ext)s",
            "merge_output_format": "mp4",
            "progress_hooks": [hook],
        })

        if format_id == "audio":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
        elif format_id == "best":
            opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"
        else:
            opts["format"] = f"{format_id}+bestaudio/best"

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")

        for f in os.listdir(DOWNLOAD_DIR):
            if f.startswith(job_id):
                full_path = os.path.join(DOWNLOAD_DIR, f)
                auto_delete(full_path)
                safe = "".join(c for c in title if c.isalnum() or c in " -_")[:50]
                jobs[job_id] = {"status": "done", "file": full_path, "title": safe, "percent": 100}
                return

        jobs[job_id] = {"status": "error", "message": "File not found"}

    except Exception as e:
        err = str(e)
        if "Sign in" in err or "login" in err.lower():
            msg = "Login required — private or age-restricted"
        elif "copyright" in err.lower():
            msg = "Blocked by copyright"
        elif "not available" in err.lower():
            msg = "Video not available"
        elif "Private" in err:
            msg = "Private video"
        elif "Unsupported URL" in err:
            msg = "This website is not supported"
        else:
            msg = err[:200]
        jobs[job_id] = {"status": "error", "message": msg}

HTML = open("index.html", encoding="utf-8").read()

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/info", methods=["POST"])
def get_info():
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "URL required"}), 400

        with yt_dlp.YoutubeDL(get_opts()) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        seen = set()
        for f in info.get("formats", []):
            height = f.get("height")
            vcodec = f.get("vcodec", "none")
            if vcodec == "none" or not height: continue
            if height not in seen:
                seen.add(height)
                formats.append({
                    "format_id": f["format_id"],
                    "quality": f"{height}p",
                    "ext": "mp4",
                    "filesize": f.get("filesize") or f.get("filesize_approx") or 0
                })

        formats.sort(key=lambda x: int(x["quality"].replace("p","")), reverse=True)
        if not formats:
            formats = [{"format_id": "best", "quality": "Best", "ext": "mp4", "filesize": 0}]

        return jsonify({
            "title": info.get("title", "Video"),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader") or info.get("channel", ""),
            "formats": formats[:8],
            "platform": info.get("extractor_key", "").replace("IE","")
        })
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500

@app.route("/download", methods=["POST"])
def download():
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get("url","").strip()
        fmt = data.get("format_id","best")
        if not url: return jsonify({"error": "URL required"}), 400
        jid = str(uuid.uuid4())
        jobs[jid] = {"status": "processing", "percent": 0}
        threading.Thread(target=do_download, args=(jid, url, fmt), daemon=True).start()
        return jsonify({"job_id": jid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/status/<jid>")
def status(jid):
    j = jobs.get(jid)
    if not j: return jsonify({"status": "not_found"}), 404
    return jsonify(j)

@app.route("/file/<jid>")
def get_file(jid):
    j = jobs.get(jid)
    if not j or j.get("status") != "done": return jsonify({"error": "Not ready"}), 404
    return send_file(j["file"], as_attachment=True, download_name=(j.get("title","video")+".mp4"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
