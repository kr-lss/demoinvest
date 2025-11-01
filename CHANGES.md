# 주요 수정사항

## 🔧 수정된 오류들

### 1. **Vertex AI API 호출 오류 수정**
- `Part.from_uri()`에서 `file_uri` → `uri`로 파라미터 이름 변경
- 최신 API 사양에 맞게 수정

### 2. **누락된 패키지 추가**
- `requirements.txt`에 `google-cloud-storage` 추가
- 원본에서 누락되어 GCS 연결 시 오류 발생했던 문제 해결

### 3. **환경변수 체크 추가**
- PROJECT_ID와 GCS_BUCKET_NAME 필수 체크
- 설정되지 않은 경우 경고 로그 출력

### 4. **pytube 다운로드 개선**
- 360p 스트림이 없을 경우 대체 스트림 시도
- 프로그레시브가 아닌 스트림도 시도하도록 개선

### 5. **Gemini 모델 버전 업데이트**
- `gemini-1.5-flash-001` → `gemini-1.5-flash-002`

### 6. **결과 데이터 검증 추가**
- 응답에 필수 필드가 없을 경우 기본값 설정
- JSON 파싱 오류 처리

## 📋 파일 구조
```
demoinvest/
├── app.py                 # 메인 애플리케이션 (수정됨)
├── requirements.txt       # 패키지 의존성 (수정됨)
├── templates/
│   └── index.html        # UI 템플릿
├── .env.example          # 환경변수 예시
└── .gitignore           # Git 제외 설정
```

## 🚀 실행 방법

1. 환경변수 설정
```bash
cp .env.example .env
# .env 파일 편집하여 PROJECT_ID, GCS_BUCKET_NAME 설정
```

2. 패키지 설치
```bash
pip install -r requirements.txt
```

3. 실행
```bash
python app.py
```
