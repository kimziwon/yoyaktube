import streamlit as st
st.set_page_config(page_title="요약튜브")
st.header("요약튜브 - 유튜브 요약 서비스")
st.text("URL로 유튜브 비디오를 즉시 요약해 보세요! AI 기술로 비디오의 핵심 내용을 몇 초 안에 파악하고, 시간을 절약하세요.")

import pandas as pd
import time
import numpy as np
from openai import OpenAI
from pytube import YouTube
from io import BytesIO
import tempfile
import requests
import boto3
from dateutil import parser

YOUTUBE_VIDEO_5_SEC = "https://www.youtube.com/watch?v=KEUUKA3fuaQ"
YOUTUBE_VIDEO_LOVO_45_MIN = "https://www.youtube.com/watch?v=aHS9x70KEs8"


S3_BUCKET="yoyaktube"
AWS_DEFAULT_REGION = "ap-northeast-2"
s3 = boto3.client('s3',
      aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
      aws_secret_access_key=st.secrets["AWS_ACCESS_KEY_SECRET"],
      region_name=AWS_DEFAULT_REGION,
      config=boto3.session.Config(signature_version='s3v4'),
    )

# st.markdown("# Main Page")
# st.sidebar.markdown("# Main Page")

OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
RUNPOD_API_TOKEN = st.secrets["RUNPOD_API_TOKEN"]
MAX_RETRY_COUNT = 300 # 5 minute
client = OpenAI(api_key=OPENAI_API_KEY)

@st.cache_data
def process_stt(url) -> str:
  runpod_env_id = "faster-whisper"
  data = requests.post(f"https://api.runpod.ai/v2/{runpod_env_id}/run", json={
  # data = requests.post("https://api.runpod.ai/v2/db1wi7vz32idky/run", json={
    "input": {
      "audio": url,  
      "model": "large-v2",
      # "model": "large-v2",
      # "language": "ko",
      "transcription": "vtt",
      "translate": False,
      "temperature": 0,
      "best_of": 1,
      "beam_size": 2,
      "condition_on_previous_text": False,
      "word_timestamps": False,
      "enable_vad": False,
    }
  }, headers={
    "Authorization": f"Bearer {RUNPOD_API_TOKEN}"
  }).json()

  status = data["status"]
  retry_count = 0
  while status not in ["COMPLETED", "FAILED"] and retry_count < MAX_RETRY_COUNT:
    if retry_count != 0: time.sleep(1)
    data = requests.get(f"https://api.runpod.ai/v2/{runpod_env_id}/status/{data['id']}", headers={
      "Authorization": f"Bearer {RUNPOD_API_TOKEN}"
    }).json()
    print(data)

    status = data["status"]
    retry_count += 1
    print(f"Retry Count: {retry_count}/{MAX_RETRY_COUNT}")

  stt_result = data["output"]["transcription"]
  return stt_result

@st.cache_data
def upload_audio_to_s3_and_get_presigned_url(youtube_url: str) -> str:
  def progress_function(chunk, file_handle, bytes_remaining):
    if (bytes_remaining != 0):
      print(f"Remaining: {chunk.filesize/bytes_remaining*100 :.2f}%")

  yt = YouTube(youtube_url)
  yt.register_on_progress_callback(progress_function)

  # audio_stream = yt.streams.filter(adaptive=True, only_audio=True, file_extension='webm', abr="50kbps").first()
  audio_stream = yt.streams.filter(adaptive=True, only_audio=True,).first()

  # print("Starting Audio Download")
  # print(f"audio filename: {audio_stream.default_filename}")
  # download = audio_stream.download(filename=audio_stream.default_filename)

  # Upload audio to S3
  # TODO: Check if already exists.
  # print(f"Video ID: ", yt.video_id)
  buff = BytesIO()
  audio_stream.stream_to_buffer(buff)
  buff.seek(0)
  s3.upload_fileobj(buff, S3_BUCKET, f"audios/{yt.video_id}")
  buff.close()
  url = s3.generate_presigned_url('get_object', Params = {'Bucket': S3_BUCKET, 'Key': f"audios/{yt.video_id}"}, ExpiresIn = 100)
  # return url
  return f"https://yoyaktube.s3.ap-northeast-2.amazonaws.com/audios/{yt.video_id}"

@st.cache_data
def process_chat_gpt(stt) -> str:
  with open("chatGPT_syscommand.txt", "r") as f:
    chatgpt_sys_command = f.read()

  response = client.chat.completions.create(
      # model=st.session_state["openai_model"],
      model="gpt-4-turbo-preview",
      messages=[
          {
            "role": "system",
            "content": chatgpt_sys_command
          },
          {
            "role": "user",
            "content": stt
          }
      ],
      temperature=0.01,
      max_tokens=1024,
      top_p=1,
      frequency_penalty=0,
      presence_penalty=0
  )
  txt_resp = response.choices[0].message.content
  # print(txt_resp)
  return txt_resp

youtube_url = st.text_input("Enter the youtube url")
st.write("Youtube URL: ", youtube_url)
s3_url = None
stt = None
chatgpt_txt_resp = None

if youtube_url:
  s3_url = upload_audio_to_s3_and_get_presigned_url(youtube_url)

if s3_url:
  st.header('Processing STT', divider='blue')
  print(f"S3 URL: {s3_url}")
  stt = process_stt(s3_url)
  expander = st.expander("STT Result")
  expander.write(stt)

if stt:
  st.header('Processing with Chat GPT for Key Scenes', divider='blue')
  chatgpt_txt_resp = process_chat_gpt(stt + ".")

  expander = st.expander("ChatGPT Result")
  expander.write(chatgpt_txt_resp)
