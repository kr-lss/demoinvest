import os
import uuid
import json
from flask import Flask, render_template, request
# pytube는 제거하고, yt_dlp와 tempfile을 사용합니다.
import yt_dlp
import tempfile
from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig

import logging
from dotenv import load_dotenv

load_dotenv()

# --- 1. 기본 설정 ---

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# GCP 프로젝트 및 GCS 버킷 설정
PROJECT_ID = os.environ.get("PROJECT_ID")
LOCATION = os.environ.get("GOOGLE_CLOUD_REGION", "us-central1")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")

# 환경변수 체크 추가
if not PROJECT_ID or not GCS_BUCKET_NAME:
    logging.error("필수 환경변수가 설정되지 않았습니다. PROJECT_ID와 GCS_BUCKET_NAME을 확인하세요.")

# Gemini 모델 설정
GEMINI_MODEL_ID = "gemini-2.5-pro"  # 최신 버전으로 업데이트

# GCP 클라이언트 초기화
try:
    # Vertex AI SDK 초기화
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    
    # Gemini 모델 로드
    model = GenerativeModel(GEMINI_MODEL_ID)
    logging.info(f"GCS Bucket '{GCS_BUCKET_NAME}' 연결 및 모델 로드 완료.")

except Exception as e:
    logging.error(f"GCP 클라이언트 초기화 실패: {e}")

# --- 2. Gemini 프롬프트 및 스키마 ---

video_extraction_prompt = '''
당신은 당신의 전재산을 투자해야 하는 전문 투자 분석가(Expert Investor)입니다. 
이 주식 방송 영상을 극도로 신중하고 비판적인 시각으로 분석하세요. 
이것은 가벼운 추천이 아니며, 당신의 모든 것을 걸고 투자할지 말지를 결정해야 합니다.

다음 항목에 대해 영상 속 정보만을 기반으로 상세히 분석하세요:

1.  **분석 대상 종목 (Stock Name)**: 
    영상에서 주로 다루는 주식 종목명.
2.  **핵심 투자 논리 (Investment Thesis)**: 
    영상 속 전문가가 '매수' 또는 '매도'를 추천하는 가장 강력한 근거 (예: 실적 개선, 신기술, 차트 패턴, 수급 등).
3.  **주요 리스크 및 반론 (Key Risks & Counter-argument)**: 
    영상에서 언급된 잠재적 위험 요인 또는 투자 논리에 대한 반론. 만약 위험 요인이 전혀 언급되지 않았다면, '언급된 리스크 없음'으로 명시하세요.
4.  **신뢰도 평가 (Credibility Score)**: 
    발표자의 주장이 객관적인 데이터(재무제표, 통계, 공시)에 기반했는지, 아니면 주관적인 예측이나 감정에 치우쳤는지 10점 만점으로 평가하세요. (1점: 매우 주관적, 10점: 매우 객관적)
5.  **최종 결정 (Final Decision)**: 
    당신의 '전재산'을 건다고 가정할 때, 이 종목을 당장 '매수'할지, '매도'할지, 아니면 '관망'(Wait & See)할지 결정하세요.
6.  **결정 사유 (Reason for Decision)**: 
    위 5번 결정에 대한 명확하고 간결한 이유를 3줄 이내로 요약하세요. (예: '리스크 대비 기대수익이 낮아 관망함', '명확한 실적 근거가 제시되어 매수함')

오직 영상 속 정보에만 기반하여 응답해야 하며, 외부 지식을 사용하지 마세요.
'''

video_extraction_response_schema = {
    "type": "OBJECT",
    "properties": {
        "stock_name": {"type": "STRING"},
        "investment_thesis": {"type": "STRING"},
        "mentioned_risk": {"type": "STRING"},
        "credibility_score": {"type": "NUMBER"},
        "final_decision": {"type": "STRING", "enum": ["매수", "매도", "관망"]},
        "decision_reason": {"type": "STRING"},
    },
    "required": ["stock_name", "investment_thesis", "final_decision", "decision_reason"]
}

# GenerationConfig
video_extraction_json_generation_config = GenerationConfig(
    temperature=0.0,
    max_output_tokens=8192,
    response_mime_type="application/json",
    response_schema=video_extraction_response_schema,
)

# --- 3. Flask 라우트 (웹 로직) ---

@app.route('/')
def index():
    """메인 페이지를 렌더링합니다."""
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    """/analyze 엔드포인트로 POST 요청이 오면 분석을 수행합니다."""
    
    youtube_url = request.form.get('youtube_url')
    if not youtube_url:
        return render_template('index.html', error="YouTube URL을 입력해주세요.")

    local_video_path = None
    gcs_blob_name = None
    gcs_uri = None

    try:
        # --- 2. 유튜브 영상 다운로드 (pytube -> yt-dlp로 교체됨) ---
        logging.info(f"Analyzing URL: {youtube_url}")

        # Windows/Mac/Linux 호환을 위해 OS의 임시 폴더를 사용합니다.
        # (pytube의 /tmp 경로 버그 수정)
        temp_dir = tempfile.gettempdir()
        unique_filename = f"{uuid.uuid4()}.mp4"
        local_video_path = os.path.join(temp_dir, unique_filename)

        # yt-dlp 옵션 설정
        ydl_opts = {
            'format': 'bestvideo[ext=mp4][progressive=True][height=720]/best[ext=mp4][progressive=True]/best[ext=mp4]',
            'outtmpl': local_video_path,  # 파일 저장 경로를 정확히 지정
            'quiet': False, # 다운로드 로그를 보기 위해 False로 설정
        }

        logging.info(f"Downloading video with yt-dlp to: {local_video_path}")
        try:
            # yt-dlp 실행
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])
        except Exception as e:
            logging.error(f"yt-dlp download failed: {e}")
            raise Exception(f"yt-dlp 다운로드 실패: {e}")

        # 파일이 실제로 생성되었는지 확인
        if not os.path.exists(local_video_path):
            raise Exception("yt-dlp: 다운로드에 실패했습니다 (파일이 생성되지 않음).")
        
        logging.info("Download complete.")


        # --- 3. GCS에 업로드 ---
        gcs_blob_name = f"video-uploads/{unique_filename}"
        blob = bucket.blob(gcs_blob_name)
        
        logging.info(f"Uploading to GCS: gs://{GCS_BUCKET_NAME}/{gcs_blob_name}")
        blob.upload_from_filename(local_video_path)
        gcs_uri = f"gs://{GCS_BUCKET_NAME}/{gcs_blob_name}"
        logging.info("Upload to GCS complete.")

        # --- 4. Gemini API 호출 (수정: file_uri → uri) ---
        logging.info(f"Calling Gemini API with URI: {gcs_uri}")
        video_part = Part.from_uri(
            uri=gcs_uri,  # file_uri 대신 uri 사용
            mime_type="video/mp4"
        )
        
        video_extraction_response = model.generate_content(
            [
                video_extraction_prompt,
                video_part,
            ],
            generation_config=video_extraction_json_generation_config,
        )
        logging.info("Gemini analysis complete.")
        
        # --- 5. 결과 반환 ---
        results_text = video_extraction_response.text
        results_data = json.loads(results_text)
        
        # 누락된 필드 기본값 설정
        if 'mentioned_risk' not in results_data:
            results_data['mentioned_risk'] = "언급된 리스크 없음"
        if 'credibility_score' not in results_data:
            results_data['credibility_score'] = 5
        
        return render_template('index.html', results=results_data, youtube_url=youtube_url)

    except Exception as e:
        logging.error(f"An error occurred: {e}")
        return render_template('index.html', error=str(e), youtube_url=youtube_url)

    finally:
        # --- 6. 임시 파일 정리 (중요!) ---
        try:
            if local_video_path and os.path.exists(local_video_path):
                os.remove(local_video_path)
                logging.info(f"Cleaned up local file: {local_video_path}")
            
            if gcs_blob_name:
                blob = bucket.blob(gcs_blob_name)
                if blob.exists():
                    blob.delete()
                    logging.info(f"Cleaned up GCS file: {gcs_blob_name}")
        except Exception as e:
            logging.warning(f"Failed to clean up files: {e}")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
