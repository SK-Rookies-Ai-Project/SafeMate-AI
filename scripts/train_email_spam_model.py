# ============================================================
# SafeMate AI - 이메일 스팸 분류 모델 학습 스크립트
# 파일 위치: scripts/train_email_spam_model.py
#
# 목적:
# 20260717_email_dataset_9600.csv의 이메일 텍스트를 기반으로
# 단어 TF-IDF + 문자 TF-IDF + Logistic Regression 모델을 학습하고,
# 학습된 Pipeline 모델을 email_spam_model.pkl 파일로 저장한다.
#
# 실행 예시:
# python scripts/train_email_spam_model.py
# python scripts/train_email_spam_model.py --data_path data/raw/20260717_email_dataset_9600.csv --model_path models/email_spam_model.pkl
# ============================================================

import argparse
import os
import pickle

import pandas as pd

from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    classification_report
)


# 1. 기본 경로 설정

DEFAULT_DATA_PATH = 'data/raw/20260717_email_dataset_9600.csv'
DEFAULT_MODEL_PATH = 'models/email_spam_model.pkl'


# 2. 데이터 불러오기 함수
# 입력값 : CSV 파일 경로
# 반환값 : 전체 원본 DataFrame

def load_data(data_path):
    # CSV 파일을 표 형태 데이터로 불러오기(pd.read_csv)
    data = pd.read_csv(
        data_path,
        encoding='utf-8-sig'
    )

    return data


# 3. 이메일 데이터 추출 함수
# 입력값 : 전체 원본 DataFrame
# 반환값 : 이메일 데이터 DataFrame(label, model_text, split)

def extract_email_data(data):
    # channel이 email 또는 이메일인 행만 추출
    channel_value = (
        data['channel']
        .astype(str)
        .str.strip()
        .str.lower()
    )

    email_data = data.loc[
        channel_value.isin(['email', '이메일']),
        ['label', 'model_text', 'split']
    ].copy()

    return email_data


# 4. 이메일 데이터 기본 정보 확인 함수
# 입력값 : 이메일 데이터 DataFrame
# 반환값 : 없음

def print_data_summary(email_data):
    print('[이메일 데이터 기본 정보]')
    print('이메일 데이터 크기:', email_data.shape)
    print('-' * 60)

    # 결측값 개수 확인(isnull, sum)
    print('[결측값 개수]')
    print(email_data.isnull().sum())
    print('-' * 60)

    # 중복값 개수 확인(duplicated, sum)
    print('[중복값 개수]')
    print(
        'model_text 중복 개수:',
        email_data['model_text'].duplicated().sum()
    )
    print(
        'label + model_text 중복 개수:',
        email_data.duplicated(
            subset=['label', 'model_text']
        ).sum()
    )
    print('-' * 60)

    # 정상/스팸 라벨 분포 확인(value_counts)
    print('[전처리 전 라벨 분포]')
    print(
        email_data['label']
        .value_counts()
        .sort_index()
    )
    print('-' * 60)

    # 이메일 문자열 길이 분포 확인(str.len, describe)
    text_length = (
        email_data['model_text']
        .astype(str)
        .str.len()
    )

    print('[이메일 문자열 길이 통계]')
    print(text_length.describe())
    print('-' * 60)


# 5. 이메일 데이터 전처리 함수
# 입력값 : 이메일 데이터 DataFrame
# 반환값 : 전처리된 이메일 데이터 DataFrame

def preprocess_email_data(email_data):
    # label, model_text, split이 없는 행 제거(dropna)
    email_data = email_data.dropna(
        subset=['label', 'model_text', 'split']
    ).copy()

    # URL은 별도 URL 모델에서 처리하므로 [URL] 표시는 이메일 텍스트에서 제거
    email_data['model_text'] = (
        email_data['model_text']
        .astype(str)
        .str.replace('[URL]', ' ', regex=False)
        .str.replace(r'\s+', ' ', regex=True)
        .str.strip()
    )

    # 빈 문자열 제거
    email_data = email_data[
        email_data['model_text'] != ''
    ].copy()

    # label을 정수형으로 변환
    email_data['label'] = (
        email_data['label']
        .astype(int)
    )

    # label과 model_text가 완전히 같은 중복 행 제거(drop_duplicates)
    email_data = (
        email_data
        .drop_duplicates(
            subset=['label', 'model_text']
        )
        .reset_index(drop=True)
    )

    print('[전처리 후 데이터 정보]')
    print('전처리 후 데이터 크기:', email_data.shape)
    print('-' * 60)

    print('[전처리 후 라벨 분포]')
    print(
        email_data['label']
        .value_counts()
        .sort_index()
    )
    print('-' * 60)

    return email_data


# 6. 학습/검증 데이터 분리 함수
# 입력값 : 전처리된 이메일 데이터 DataFrame
# 반환값 : X_train, X_valid, y_train, y_valid

def split_train_valid(email_data):
    # 데이터셋에 미리 저장된 train/valid 분할을 그대로 사용
    split_value = (
        email_data['split']
        .astype(str)
        .str.strip()
        .str.lower()
    )

    train_data = email_data[
        split_value == 'train'
    ].copy()

    valid_data = email_data[
        split_value == 'valid'
    ].copy()

    if train_data.empty or valid_data.empty:
        raise ValueError(
            'CSV의 split 컬럼에 train과 valid가 모두 필요합니다.'
        )

    # X는 모델에 입력할 이메일 문자열
    X_train = train_data['model_text']
    X_valid = valid_data['model_text']

    # y는 모델이 맞혀야 하는 정답 라벨
    y_train = train_data['label'].astype(int)
    y_valid = valid_data['label'].astype(int)

    print('[학습/검증 데이터 분리 결과]')
    print('학습 데이터 크기:', X_train.shape)
    print('검증 데이터 크기:', X_valid.shape)
    print('-' * 60)

    print('[학습 데이터 라벨 분포]')
    print(y_train.value_counts().sort_index())
    print('-' * 60)

    print('[검증 데이터 라벨 분포]')
    print(y_valid.value_counts().sort_index())
    print('-' * 60)

    return X_train, X_valid, y_train, y_valid


# 7. 단어 TF-IDF + 문자 TF-IDF + 로지스틱 회귀 Pipeline 생성 함수
# 입력값 : 없음
# 반환값 : Pipeline 모델

def build_model():
    # FeatureUnion
    # -> 단어 단위 TF-IDF와 문자 단위 TF-IDF 결과를 하나로 합친다.
    #
    # Pipeline
    # -> 합쳐진 TF-IDF 특성을 로지스틱 회귀에 전달한다.
    model = Pipeline([
        (
            'tfidf',
            FeatureUnion(
                transformer_list=[
                    (
                        'word_tfidf',
                        TfidfVectorizer(
                            analyzer='word',
                            ngram_range=(1, 2),
                            min_df=2,
                            max_df=0.98,
                            token_pattern=r'(?u)\b\w+\b',
                            max_features=50000,
                            sublinear_tf=True
                        )
                    ),
                    (
                        'char_tfidf',
                        TfidfVectorizer(
                            analyzer='char_wb',
                            ngram_range=(2, 5),
                            min_df=2,
                            max_features=60000,
                            sublinear_tf=True
                        )
                    )
                ],
                transformer_weights={
                    'word_tfidf': 1.0,
                    'char_tfidf': 0.5
                }
            )
        ),
        (
            'model',
            LogisticRegression(
                C=1.0,
                solver='liblinear',
                dual=True,
                max_iter=1000,
                random_state=42
            )
        )
    ])

    return model


# 8. 모델 학습 함수
# 입력값 : Pipeline 모델, 학습용 X, 학습용 y
# 반환값 : 학습된 Pipeline 모델

def train_model(model, X_train, y_train):
    # 학습 데이터로 모델 학습(fit)
    model.fit(
        X_train,
        y_train
    )

    print('[모델 학습 완료]')
    print('-' * 60)

    return model


# 9. 모델 평가 함수
# 입력값 : 학습된 모델, 검증용 X, 검증용 y
# 반환값 : 없음

def evaluate_model(model, X_valid, y_valid):
    # 검증 데이터 예측(predict)
    y_pred = model.predict(
        X_valid
    )

    # 평가 지표 계산
    accuracy = accuracy_score(
        y_valid,
        y_pred
    )
    precision = precision_score(
        y_valid,
        y_pred,
        zero_division=0
    )
    recall = recall_score(
        y_valid,
        y_pred,
        zero_division=0
    )
    f1 = f1_score(
        y_valid,
        y_pred,
        zero_division=0
    )
    cm = confusion_matrix(
        y_valid,
        y_pred,
        labels=[0, 1]
    )

    print('[이메일 스팸 분류 모델 평가 결과]')
    print(f'Accuracy : {accuracy:.4f}')
    print(f'Precision: {precision:.4f}')
    print(f'Recall   : {recall:.4f}')
    print(f'F1-score : {f1:.4f}')
    print('-' * 60)

    print('[Confusion Matrix]')
    print(cm)
    print('-' * 60)

    print('[Classification Report]')
    print(
        classification_report(
            y_valid,
            y_pred,
            labels=[0, 1],
            target_names=['정상', '스팸·사기'],
            digits=4,
            zero_division=0
        )
    )


# 10. 샘플 이메일 예측 함수
# 입력값 : 학습된 모델
# 반환값 : 없음

def test_sample_emails(model):
    sample_emails = [
        '제목: 회의 일정 안내 본문: 내일 오후 2시에 회의를 진행합니다. 자료를 확인해 주세요.',
        '제목: 긴급 계정 정지 예정 본문: 비밀번호와 인증번호를 입력하지 않으면 계정이 정지됩니다.'
    ]

    # 샘플 이메일 예측(predict, predict_proba)
    sample_predictions = model.predict(
        sample_emails
    )
    sample_probabilities = (
        model
        .predict_proba(sample_emails)[:, 1]
    )

    print('[샘플 이메일 예측 결과]')

    for text, prediction, probability in zip(
        sample_emails,
        sample_predictions,
        sample_probabilities
    ):
        print('-' * 60)
        print('입력:', text)
        print(
            '예측:',
            '스팸·사기'
            if prediction == 1
            else '정상'
        )
        print(
            '스팸 확률:',
            round(float(probability), 4)
        )

    print('-' * 60)


# 11. 최종 모델 저장 함수
# 입력값 : 전체 X, 전체 y, 저장 경로
# 반환값 : 없음

def train_and_save_final_model(X, y, model_path):
    # 전체 이메일 데이터로 최종 모델 재학습
    final_model = build_model()
    final_model.fit(
        X,
        y
    )

    # 모델 저장 폴더가 없으면 생성(os.makedirs)
    model_dir = os.path.dirname(
        model_path
    )

    if model_dir:
        os.makedirs(
            model_dir,
            exist_ok=True
        )

    # 최종 Pipeline 모델을 pkl 파일로 저장(pickle.dump)
    with open(model_path, 'wb') as file:
        pickle.dump(
            final_model,
            file
        )

    print('[최종 모델 저장 완료]')
    print('저장 경로:', model_path)
    print('-' * 60)


# 12. 저장된 모델 확인 함수
# 입력값 : 저장된 모델 경로
# 반환값 : 없음

def check_saved_model(model_path):
    # 저장된 pkl 모델 불러오기(pickle.load)
    with open(model_path, 'rb') as file:
        loaded_model = pickle.load(file)

    test_email = [
        '제목: 회의 일정 안내 본문: 내일 오후 2시에 회의를 진행합니다.'
    ]

    # 불러온 모델로 예측 확인(predict, predict_proba)
    prediction = loaded_model.predict(
        test_email
    )[0]
    spam_probability = (
        loaded_model
        .predict_proba(test_email)[0][1]
    )

    print('[저장된 모델 예측 확인]')
    print('입력:', test_email[0])
    print(
        '예측 결과:',
        '스팸·사기'
        if prediction == 1
        else '정상'
    )
    print(
        '스팸 확률:',
        round(float(spam_probability), 4)
    )
    print('-' * 60)


# 13. 실행 옵션 설정 함수
# 입력값 : 없음
# 반환값 : argparse 결과 객체

def parse_args():
    parser = argparse.ArgumentParser(
        description='이메일 스팸 분류 모델 학습 스크립트'
    )

    parser.add_argument(
        '--data_path',
        type=str,
        default=DEFAULT_DATA_PATH,
        help='학습에 사용할 CSV 데이터 경로'
    )

    parser.add_argument(
        '--model_path',
        type=str,
        default=DEFAULT_MODEL_PATH,
        help='저장할 pkl 모델 경로'
    )

    return parser.parse_args()


# 14. main 함수
# 입력값 : 없음
# 반환값 : 없음

def main():
    # 1. 실행 옵션 불러오기
    args = parse_args()

    # 2. 데이터셋 불러오기
    data = load_data(
        args.data_path
    )

    # 3. 이메일 데이터만 추출
    email_data = extract_email_data(
        data
    )

    # 4. 전처리 전 데이터 상태 확인
    print_data_summary(
        email_data
    )

    # 5. 이메일 데이터 전처리
    email_data = preprocess_email_data(
        email_data
    )

    # 6. 학습 데이터와 검증 데이터 분리
    X_train, X_valid, y_train, y_valid = split_train_valid(
        email_data
    )

    # 7. 평가용 모델 생성
    model = build_model()

    # 8. 평가용 모델 학습
    model = train_model(
        model,
        X_train,
        y_train
    )

    # 9. 검증 데이터로 모델 평가
    evaluate_model(
        model,
        X_valid,
        y_valid
    )

    # 10. 샘플 이메일 예측 확인
    test_sample_emails(
        model
    )

    # 11. 전체 입력 데이터 X와 정답 y 분리
    X = email_data['model_text']
    y = email_data['label'].astype(int)

    # 12. 전체 이메일 데이터로 최종 모델 재학습 후 저장
    train_and_save_final_model(
        X,
        y,
        args.model_path
    )

    # 13. 저장된 모델이 정상적으로 불러와지는지 확인
    check_saved_model(
        args.model_path
    )


if __name__ == '__main__':
    main()
