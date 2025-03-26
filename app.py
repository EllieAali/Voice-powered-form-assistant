from flask import Flask, render_template, request, send_file
import os
from werkzeug.utils import secure_filename
from main_script import (
    upload_file_to_blob,
    transcribe_audio_from_blob,
    extract_incident_details,
    fill_pdf_form
)

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def upload_audio():
    if request.method == "POST":
        file = request.files["file"]
        if file:
            # 🔒 Secure and save uploaded file locally
            filename = secure_filename(file.filename)
            local_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(local_path)

            container_name = "pva"
            transcript_blob_name = "transcript.json"
            incident_blob_name = "extracted_incident_details.json"
            output_pdf = "completed_police_report.pdf"

            try:
                # ☁️ Upload audio file to blob
                upload_file_to_blob(local_path, container_name, filename)

                # 🎙️ Transcribe audio and store transcript in Blob
                transcribe_audio_from_blob(container_name, filename, transcript_blob_name)

                # 🤖 Extract incident details and store in Blob
                extract_incident_details(transcript_blob_name, incident_blob_name)

                # 📝 Fill PDF with incident details
                fill_pdf_form("SampleFormTemplate5.pdf", output_pdf, incident_blob_name)

                # 📤 Return completed PDF to user
                return send_file(output_pdf, as_attachment=True)

            except Exception as e:
                return f"❌ Error during processing: {str(e)}"

    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)


