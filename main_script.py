# %% Imports
import os
import json
import threading
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk
from azure.storage.blob import BlobServiceClient
from openai import AzureOpenAI
from fillpdf import fillpdfs

# %% Load env variables
load_dotenv()

api_key = os.getenv("api_key")
speech_region = os.getenv("speech_region")
speech_endpoint = os.getenv("speech_endpoint")
openai_endpoint = os.getenv("openai_endpoint")
openai_deployment = os.getenv("openai_deployment")
storage_connection_string = os.getenv("storage_connection_string")
storage_account_name = os.getenv('storage_account_name')

# Check if the credentials are loaded correctly
if not api_key or not speech_region or not openai_endpoint or not openai_deployment or not storage_connection_string or not storage_account_name:
    raise ValueError("Please set the environment variables in the .env file.")

# Create openai client
openai_client = AzureOpenAI(
    azure_endpoint = openai_endpoint,
    api_key = api_key,
    api_version = "2024-05-01-preview"
)

# %% Blob Storage Helper Functions ---------
def upload_text_as_blob(container_name, blob_name, text_data):
    blob_service = BlobServiceClient.from_connection_string(storage_connection_string)
    blob_client = blob_service.get_container_client(container_name).get_blob_client(blob_name)
    blob_client.upload_blob(text_data, overwrite=True)
    print(f"☁️ Uploaded blob '{blob_name}' to container '{container_name}'.")

def download_blob_as_text(container_name, blob_name):
    blob_service = BlobServiceClient.from_connection_string(storage_connection_string)
    blob_client = blob_service.get_container_client(container_name).get_blob_client(blob_name)
    return blob_client.download_blob().readall().decode("utf-8")

def download_blob_to_local(container_name, blob_name, local_filename):
    blob_service = BlobServiceClient.from_connection_string(storage_connection_string)
    blob_client = blob_service.get_container_client(container_name).get_blob_client(blob_name)
    with open(local_filename, "wb") as file:
        file.write(blob_client.download_blob().readall())
    print(f"📥 Downloaded '{blob_name}' to local file: {local_filename}")

def upload_file_to_blob(local_path, container_name, blob_name):
    blob_service = BlobServiceClient.from_connection_string(storage_connection_string)
    blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)
    with open(local_path, "rb") as file:
        blob_client.upload_blob(file, overwrite=True)
    print(f"☁️ Uploaded file '{local_path}' to blob '{blob_name}' in '{container_name}'.")


# %% Transcription Function (Using Azure Blob Storage)
def transcribe_audio_from_blob(audio_container, audio_blob_name, transcript_blob_name):
    local_audio_path = "temp_audio.wav" 
    download_blob_to_local(audio_container, audio_blob_name, local_audio_path)

    # Now pass the local file to Azure Speech
    audio_config = speechsdk.audio.AudioConfig(filename=local_audio_path)
    speech_config = speechsdk.SpeechConfig(subscription=api_key, region=speech_region)
    # Enable automatic silence removal and word-level timestamps
    speech_config.request_word_level_timestamps()

    # Create speech recognizer
    speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    # List to store transcribed text
    transcript_list = []
    # Event to signal when recognition is done
    done_event = threading.Event()

    def handle_result(evt):
        """Appends recognized text to the transcript list."""
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            print(f"Recognized: {evt.result.text}")
            transcript_list.append(evt.result.text)

    def stop_continuous_recognition(evt):
        """Stops recognition when the session ends."""
        print("Session stopped.")
        speech_recognizer.stop_continuous_recognition()
        done_event.set()  # Signal that recognition is complete

    # Connect event handlers
    speech_recognizer.recognized.connect(handle_result)
    speech_recognizer.session_stopped.connect(stop_continuous_recognition)
    speech_recognizer.canceled.connect(stop_continuous_recognition)

    # Start continuous recognition
    print("Starting transcription...")
    speech_recognizer.start_continuous_recognition()
    # Wait until transcription completes
    done_event.wait()

        # ✅ Save transcript as JSON
    final_transcript = "\n".join(transcript_list)
    transcript_data = {"transcript": final_transcript}
    transcript_json_str = json.dumps(transcript_data, indent=4)    

    # Upload the JSON to Blob Storage
    upload_text_as_blob("transcripts", transcript_blob_name, transcript_json_str)
    print(f"✅ Transcript successfully uploaded as JSON: {transcript_blob_name}")
    return transcript_blob_name

# %%
def extract_incident_details(transcript_blob_name, output_json="extracted_incident_details.json"):
    transcript_text = download_blob_as_text("transcripts", transcript_blob_name)

    prompt = f"""
    You are an AI assistant structuring police reports. Extract key details from the transcript below.

    Respond **ONLY** in valid JSON format, with no explanations or extra text.

    JSON structure:
    {{
        "aggrieved_name": "<Victim's First Name>",
        "aggrieved_surname": "<Victim's Last Name>",
        "ReasonToContact": "<summary of the incident>",
    }}

    Transcript:
    {transcript_text}
    """

    response = openai_client.chat.completions.create(
        model = openai_deployment,  # Use your Azure GPT-4 deployment
        messages=[{"role": "system", "content": "You are an expert police report assistant."},
                  {"role": "user", "content": prompt}]
    )


    structured_output = response.choices[0].message.content
    extracted_data = json.loads(structured_output)
    extracted_json_str = json.dumps(extracted_data, indent=4)

    upload_text_as_blob("incident-details", output_json, extracted_json_str)
    print(f"✅ Extracted incident details uploaded as JSON: {output_json}")
    return output_json

# %% Fill PDF Form
def fill_pdf_form(input_pdf_blob, output_pdf_blob, incident_details_blob):
    form_fields = list(fillpdfs.get_form_fields(input_pdf_blob).keys())
    details_text = download_blob_as_text("incident-details", incident_details_blob)
    details = json.loads(details_text)

    # ✅ Map extracted data to PDF fields
    data_dict = {
        form_fields[0]: details.get("aggrieved_name", ""),
        form_fields[1]: details.get("aggrieved_surname", ""),
        form_fields[2]: details.get("ReasonToContact", ""),
        # form_fields[3]: details.get("date_time", ""),
        # form_fields[4]: details.get("location", ""),
        # form_fields[5]: ", ".join(details.get("people_involved", [])),
        # form_fields[6]: ", ".join(details.get("weapons_used", [])),
        # form_fields[7]: details.get("casualties", ""),
        # form_fields[8]: details.get("respondent_name", ""),
        # form_fields[9]: details.get("respondent_surname", "")
    }

    fillpdfs.write_fillable_pdf(input_pdf_blob, output_pdf_blob, data_dict)
    print(f"✅ PDF form successfully filled and saved as: {output_pdf_blob}")

# %% Main Pipeline
def main(): 
    audio_container = "pva"
    audio_blob_name = "PVA_sample.wav"
    transcript_blob_name = "transcript.json"

    try:
        # Step 1: Transcribe audio from Blob Storage
        transcript_blob = transcribe_audio_from_blob(audio_container, audio_blob_name, transcript_blob_name)
        if not transcript_blob:
            print("❌ Transcription failed or returned empty.")
            return

        # Step 2: Extract incident details using the transcript
        incident_details_blob = extract_incident_details(transcript_blob, output_json="extracted_incident_details.json")
        if not incident_details_blob:
            print("❌ Incident extraction failed.")
            return

        # Step 3: Fill the PDF form
        download_blob_to_local("pva", "SampleFormTemplate5.pdf", "SampleFormTemplate5.pdf")

        if not os.path.exists("SampleFormTemplate5.pdf"):
            print("❌ PDF form template not found locally.")
            return

        fill_pdf_form("SampleFormTemplate5.pdf", "completed_police_report.pdf", incident_details_blob)
        print("✅ All steps completed successfully.")

        # Step 4: Upload the completed PDF to Blob Storage
        upload_file_to_blob("completed_police_report.pdf", "pva", "completed_police_report.pdf")

    except Exception as e:
        print(f"❌ Error during processing: {e}")


# %%
if __name__ == "__main__":
    main()



