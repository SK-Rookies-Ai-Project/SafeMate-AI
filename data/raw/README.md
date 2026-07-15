# Data Set Notice

본 프로젝트의 학습 및 모델 검증에 사용된 데이터셋 정보와 접근 방법에 대한 안내입니다.

## ⚠️ 데이터셋 업로드 제외 안내

본 프로젝트에서 사용한 `url_binary_dataset.csv` 파일은 **약 900.36 MB**의 대용량 데이터셋입니다. 

GitHub은 파일당 **100MB**의 용량 제한을 두고 있어, 리포지토리의 안정적인 관리와 클론(Clone) 속도 저하를 방지하기 위해 해당 데이터셋을 GitHub 원격 저장소에 직접 푸시하지 않고 원격 클라우드 저장소로 분리하여 관리합니다.

혼란을 방지하기 위해 본 데이터셋 이외에 모든 데이터셋들은 **Google Drive(구글 드라이브)**에 별도로 업로드되었으며, Git 추적 대상(`data/raw/url_binary_dataset.csv`)에서 제외되었습니다.

---

## 💾 데이터셋 다운로드 방법

모델 학습 또는 재현(Replication)을 위해 원본 데이터가 필요하신 분은 아래의 안내를 따라 다운로드해 주시기 바랍니다.

1. **구글 드라이브 링크 접속:** [(https://drive.google.com/drive/folders/1SXsUEF6wtoP1XrukGcvs5c0JcUpLSmoH?usp=drive_link)]
2. **파일 다운로드:** `url_binary_dataset.csv`외 csv 파일들을 다운로드합니다.
3. **디렉토리 배치:** 다운로드한 파일을 프로젝트 내 아래 경로에 위치시켜 주세요.
   ```bash
   # 프로젝트 루트 기준 경로
   data/raw/~
