from flask import Flask, request, send_file, render_template, after_this_request
import os
import subprocess
from faster_whisper import WhisperModel

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Load whisper model
model = WhisperModel("base", device="cpu")

# Offset in seconds to reduce slight delay
CAPTION_OFFSET = -0.1  # 100ms earlier

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["video"]
    mode = request.form.get("mode", "sentence")  # "sentence" or "word"
    caption_type = request.form.get("caption_type", "normal")  # "normal" or "reels"
    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    # Set alignment based on caption type
    if caption_type == "reels":
        alignment = 5  # middle-center
        margin_v = 0
    else:
        alignment = 2  # bottom-center
        margin_v = 100

    # Transcribe video
    segments, info = model.transcribe(filepath)

    # Create .ass subtitles
    ass_path = os.path.join(OUTPUT_FOLDER, f"{os.path.splitext(file.filename)[0]}.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("[Script Info]\n")
        f.write("ScriptType: v4.00+\n")
        f.write("Collisions: Normal\n")
        f.write("PlayResX: 1920\n")
        f.write("PlayResY: 1080\n\n")

        f.write("[V4+ Styles]\n")
        f.write("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding\n")
        f.write(f"Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
                f"0,0,0,0,100,100,0,0,1,2,0,{alignment},0,0,{margin_v},1\n\n")

        f.write("[Events]\n")
        f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

        prev_end = None
        for seg in segments:
            if mode == "sentence":
                start = max(0, seg.start + CAPTION_OFFSET)
                end = seg.end
                if prev_end and start < prev_end:
                    start = prev_end
                text = seg.text.replace("\n", " ").strip()
                f.write(f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(end)},Default,,0,0,0,,{text}\n")
                prev_end = end
            else:  # word mode
                words = seg.text.strip().split()
                if not words:
                    continue
                duration = seg.end - seg.start
                per_word = duration / len(words)
                for i, word in enumerate(words):
                    word_start = seg.start + i * per_word + CAPTION_OFFSET
                    word_end = word_start + per_word
                    if prev_end and word_start < prev_end:
                        word_start = prev_end
                    f.write(f"Dialogue: 0,{format_ass_time(word_start)},{format_ass_time(word_end)},Default,,0,0,0,,{word}\n")
                    prev_end = word_end

    # Burn subtitles
    output_path = os.path.join(OUTPUT_FOLDER, f"final-{file.filename}")
    ass_path_ffmpeg = ass_path.replace("\\", "/")
    filepath_ffmpeg = filepath.replace("\\", "/")
    output_path_ffmpeg = output_path.replace("\\", "/")

    cmd = [
        "ffmpeg",
        "-i", filepath_ffmpeg,
        "-vf", f"ass='{ass_path_ffmpeg}',format=yuv420p",
        "-c:a", "copy",
        output_path_ffmpeg,
        "-y"
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        return f"FFmpeg failed:<br><pre>{e.stderr}</pre>"

    @after_this_request
    def cleanup(response):
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
            if os.path.exists(ass_path):
                os.remove(ass_path)
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception as e:
            print("Cleanup error:", e)
        return response

    return send_file(output_path, as_attachment=True)

def format_ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int((seconds % 1) * 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"

if __name__ == "__main__":
    app.run(port=5000, debug=True)
