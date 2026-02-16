import io
import random
import subprocess
import os
from urllib import response
import dotenv
dotenv.load_dotenv()

from google.oauth2.service_account import Credentials as SACreds
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from PIL import Image
import requests

#
# CONFIG
#
DRIVE_SA_FILE = "service_account.json"

# Output temp paths
TMP_IMAGE = "/tmp/short_image.jpg"
TMP_CROPPED = "/tmp/shorts_ready.jpg"
TMP_VIDEO = "/tmp/shorts_video.mp4"
TMP_AUDIO = "/tmp/audio_clip"

TITLE = os.getenv("SHORTS_DESCRIPTION")
UPLOAD_POST_API_KEY = os.getenv("UPLOAD_POST_API_KEY")
USER_ID = os.getenv("UPLOAD_POST_USER_ID")
IMG_FOLDER_ID = os.getenv("IMG_DRIVE")
AUDIO_FOLDER_ID = os.getenv("AUDIO_DRIVE")

#
# STEP 1: Drive helpers
#
def get_drive_service():
    creds = SACreds.from_service_account_file(
        DRIVE_SA_FILE,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)


def list_drive_images(service, folder_id):
    images = []
    page_token = None

    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and mimeType contains 'image/'",
            fields="nextPageToken, files(id, name, createdTime)",
            pageToken=page_token
        ).execute()

        images.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return images


def list_drive_audio(service, folder_id):
    audios = []
    page_token = None

    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and mimeType contains 'audio/'",
            fields="nextPageToken, files(id, name, createdTime)",
            pageToken=page_token
        ).execute()

        audios.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return audios


def download_drive_file(service, file_id, out_path):
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    with open(out_path, "wb") as f:
        f.write(fh.getvalue())


#
# STEP 2: Crop
#
def crop_for_shorts(input_path, output_path):
    img = Image.open(input_path).convert("RGB")
    w, h = img.size

    top_crop = int(h * 0.10)
    bottom_crop = int(h * 0.12)
    img = img.crop((0, top_crop, w, h - bottom_crop))

    w, h = img.size
    target_w, target_h = 1080, 1920
    target_ratio = target_w / target_h
    current_ratio = w / h

    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = int((h - new_h) * 0.35)
        img = img.crop((0, top, w, top + new_h))

    img = img.resize((target_w, target_h), Image.LANCZOS)
    img.save(output_path, quality=95)


#
# STEP 3: FFmpeg video
#
def render_video(image_path, audio_path, output_path):
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-vf", "fade=t=in:st=0:d=2,format=yuv420p",
        "-r", "30",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]
    subprocess.run(cmd, check=True)


def upload_uploadpost(video_path):
    url = "https://api.upload-post.com/api/upload"

    headers = {
        "Authorization": f"{UPLOAD_POST_API_KEY}"
    }

    files = {
        "video": open(video_path, "rb")
    }

    data = {
        "title": TITLE,
        "user": USER_ID,
        "platform[]": [
            "youtube",
            "instagram",
            "tiktok",
        ],
        # IG specific, offset in ms = 2 seconds
        "thumb_offset": 2000,
        # Tiktok thumbail
        "cover_timestamp": 2000
    }

    response = requests.post(
        url,
        headers=headers,
        files=files,
        data=data
    )

    if response.status_code != 200:
        raise RuntimeError(f"Upload failed: {response.text}")


#
# MAIN PIPELINE
#
def main():
    drive = get_drive_service()

    img_files = list_drive_images(drive, IMG_FOLDER_ID)
    audio_files = list_drive_audio(drive, AUDIO_FOLDER_ID)

    if not img_files:
        raise RuntimeError("No images found")
    if not audio_files:
        raise RuntimeError("No audio found")

    img_choice = max(img_files, key=lambda x: x["createdTime"])
    audio_choice = random.choice(audio_files)

    download_drive_file(drive, img_choice["id"], TMP_IMAGE)
    download_drive_file(drive, audio_choice["id"], TMP_AUDIO)

    crop_for_shorts(TMP_IMAGE, TMP_CROPPED)
    render_video(TMP_CROPPED, TMP_AUDIO, TMP_VIDEO)

    upload_uploadpost(TMP_VIDEO)


if __name__ == "__main__":
    main()
