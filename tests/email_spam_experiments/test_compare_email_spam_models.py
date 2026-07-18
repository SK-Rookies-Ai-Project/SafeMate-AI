# ============================================================
# SafeMate AI - 이메일 스팸 분류 모델 비교 스크립트
# 파일 위치: tests/email_spam_experiments/compare_email_spam_models.py
#
# 목적:
# 동일한 이메일 데이터와 동일한 TF-IDF 특성을 사용하여
# Logistic Regression, LinearSVC, MultinomialNB 모델을 학습하고,
# Accuracy, Precision, Recall, F1-score, Confusion Matrix,
# Classification Report를 비교한다.
#
# 실행 예시:
# python tests/email_spam_experiments/compare_email_spam_models.py
# python tests/email_spam_experiments/compare_email_spam_models.py --data_path data/raw/20260717_email_dataset_9600.csv
# ============================================================

import argparse

import pandas as pd

from sklearn.pipeline import FeatureUnion
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.naive_bayes import MultinomialNB
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
    # 학습에 필요한 컬럼이 있는지 확인
    required_columns = {
        'label',
        'channel',
        'model_text',
        'split'
    }

    missing_columns = (
        required_columns
        - set(data.columns)
    )

    if missing_columns:
        raise ValueError(
            '필수 컬럼이 없습니다: '
            + ', '.join(
                sorted(missing_columns)
            )
        )

    # channel이 email 또는 이메일인 행만 추출
    channel_value = (
        data['channel']
        .astype(str)
        .str.strip()
        .str.lower()
    )

    email_data = data.loc[
        channel_value.isin([
            'email',
            '이메일'
        ]),
        [
            'label',
            'model_text',
            'split'
        ]
    ].copy()

    return email_data


# 4. 이메일 데이터 기본 정보 확인 함수
# 입력값 : 이메일 데이터 DataFrame
# 반환값 : 없음

def print_data_summary(email_data):
    print('[이메일 데이터 기본 정보]')
    print(
        '이메일 데이터 크기:',
        email_data.shape
    )
    print('-' * 60)

    print('[결측값 개수]')
    print(
        email_data.isnull().sum()
    )
    print('-' * 60)

    print('[전처리 전 라벨 분포]')
    print(
        email_data[
            'label'
        ]
        .value_counts()
        .sort_index()
    )
    print('-' * 60)


# 5. 이메일 데이터 전처리 함수
# 입력값 : 이메일 데이터 DataFrame
# 반환값 : 전처리된 이메일 데이터 DataFrame

def preprocess_email_data(email_data):
    # label, model_text, split이 없는 행 제거(dropna)
    email_data = email_data.dropna(
        subset=[
            'label',
            'model_text',
            'split'
        ]
    ).copy()

    # URL은 별도 URL 모델에서 처리하므로
    # 데이터셋의 [URL] 표시만 이메일 텍스트에서 제거
    email_data['model_text'] = (
        email_data[
            'model_text'
        ]
        .astype(str)
        .str.replace(
            '[URL]',
            ' ',
            regex=False
        )
        .str.replace(
            r'\s+',
            ' ',
            regex=True
        )
        .str.strip()
    )

    # 빈 문자열 제거
    email_data = email_data[
        email_data[
            'model_text'
        ] != ''
    ].copy()

    # label을 정수형으로 변환
    email_data['label'] = (
        pd.to_numeric(
            email_data[
                'label'
            ],
            errors='coerce'
        )
    )

    email_data = email_data.dropna(
        subset=['label']
    ).copy()

    email_data['label'] = (
        email_data[
            'label'
        ]
        .astype(int)
    )

    # label은 0 또는 1만 허용
    invalid_label_count = (
        ~email_data[
            'label'
        ].isin([0, 1])
    ).sum()

    if invalid_label_count > 0:
        raise ValueError(
            'label은 0 또는 1만 사용할 수 있습니다.'
        )

    # label과 model_text가 완전히 같은 중복 행 제거
    email_data = (
        email_data
        .drop_duplicates(
            subset=[
                'label',
                'model_text'
            ]
        )
        .reset_index(drop=True)
    )

    print('[전처리 후 데이터 정보]')
    print(
        '전처리 후 데이터 크기:',
        email_data.shape
    )
    print('-' * 60)

    return email_data


# 6. 학습/검증 데이터 분리 함수
# 입력값 : 전처리된 이메일 데이터 DataFrame
# 반환값 : X_train, X_valid, y_train, y_valid

def split_train_valid(email_data):
    # 데이터셋에 미리 저장된 train/valid 분할을 그대로 사용
    split_value = (
        email_data[
            'split'
        ]
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
            'CSV의 split 컬럼에 '
            'train과 valid가 모두 필요합니다.'
        )

    X_train = train_data[
        'model_text'
    ]

    X_valid = valid_data[
        'model_text'
    ]

    y_train = train_data[
        'label'
    ].astype(int)

    y_valid = valid_data[
        'label'
    ].astype(int)

    print('[학습/검증 데이터 분리 결과]')
    print(
        '학습 데이터 크기:',
        X_train.shape
    )
    print(
        '검증 데이터 크기:',
        X_valid.shape
    )
    print('-' * 60)

    print('[학습 데이터 라벨 분포]')
    print(
        y_train
        .value_counts()
        .sort_index()
    )
    print('-' * 60)

    print('[검증 데이터 라벨 분포]')
    print(
        y_valid
        .value_counts()
        .sort_index()
    )
    print('-' * 60)

    return (
        X_train,
        X_valid,
        y_train,
        y_valid
    )


# 7. 단어 TF-IDF + 문자 TF-IDF 생성 함수
# 입력값 : 없음
# 반환값 : FeatureUnion 객체

def build_tfidf():
    # 세 모델이 완전히 같은 특성을 사용하도록
    # TF-IDF는 한 번만 학습한다.
    tfidf = FeatureUnion(
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

    return tfidf


# 8. 비교할 분류 모델 생성 함수
# 입력값 : 없음
# 반환값 : 모델 이름과 모델 객체 dictionary

def build_models():
    models = {
        'Logistic Regression': LogisticRegression(
            C=1.0,
            solver='liblinear',
            dual=True,
            max_iter=1000,
            random_state=42
        ),

        'LinearSVC': LinearSVC(
            C=1.0,
            max_iter=5000,
            random_state=42
        ),

        'MultinomialNB': MultinomialNB(
            alpha=1.0
        )
    }

    return models


# 9. TF-IDF 변환 함수
# 입력값 : TF-IDF 객체, 학습용 X, 검증용 X
# 반환값 : 변환된 X_train, X_valid

def transform_text(
    tfidf,
    X_train,
    X_valid
):
    print('[TF-IDF 학습 및 변환 시작]')

    X_train_tfidf = tfidf.fit_transform(
        X_train
    )

    X_valid_tfidf = tfidf.transform(
        X_valid
    )

    print(
        '학습 TF-IDF 크기:',
        X_train_tfidf.shape
    )
    print(
        '검증 TF-IDF 크기:',
        X_valid_tfidf.shape
    )
    print('-' * 60)

    return (
        X_train_tfidf,
        X_valid_tfidf
    )


# 10. 단일 모델 평가 함수
# 입력값 : 모델 이름, 모델, 학습/검증 데이터
# 반환값 : 평가 지표 dictionary

def train_and_evaluate_model(
    model_name,
    model,
    X_train,
    X_valid,
    y_train,
    y_valid
):
    print('=' * 70)
    print(
        f'[{model_name} 학습 시작]'
    )

    # 모델 학습
    model.fit(
        X_train,
        y_train
    )

    # 검증 데이터 예측
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

    print(
        f'[{model_name} 평가 결과]'
    )
    print(
        f'Accuracy : {accuracy:.4f}'
    )
    print(
        f'Precision: {precision:.4f}'
    )
    print(
        f'Recall   : {recall:.4f}'
    )
    print(
        f'F1-score : {f1:.4f}'
    )
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
            target_names=[
                '정상',
                '스팸·사기'
            ],
            digits=4,
            zero_division=0
        )
    )

    return {
        'Model': model_name,
        'Accuracy': accuracy,
        'Precision': precision,
        'Recall': recall,
        'F1-score': f1
    }


# 11. 전체 모델 비교 함수
# 입력값 : 모델 dictionary, 학습/검증 데이터
# 반환값 : 비교 결과 DataFrame

def compare_models(
    models,
    X_train,
    X_valid,
    y_train,
    y_valid
):
    results = []

    for model_name, model in models.items():
        result = train_and_evaluate_model(
            model_name,
            model,
            X_train,
            X_valid,
            y_train,
            y_valid
        )

        results.append(
            result
        )

    result_data = pd.DataFrame(
        results
    )

    result_data = (
        result_data
        .sort_values(
            by='F1-score',
            ascending=False
        )
        .reset_index(drop=True)
    )

    return result_data


# 12. 최종 비교 결과 출력 함수
# 입력값 : 비교 결과 DataFrame
# 반환값 : 없음

def print_comparison_result(
    result_data
):
    print('=' * 70)
    print('[모델별 최종 비교 결과]')

    print(
        result_data.to_string(
            index=False,
            float_format=lambda value: (
                f'{value:.4f}'
            )
        )
    )

    print('-' * 70)

    best_model_name = result_data.loc[
        0,
        'Model'
    ]

    best_f1 = result_data.loc[
        0,
        'F1-score'
    ]

    print(
        'F1-score 기준 가장 높은 모델:',
        best_model_name
    )
    print(
        'F1-score:',
        round(
            float(best_f1),
            4
        )
    )
    print('=' * 70)


# 13. 실행 옵션 설정 함수
# 입력값 : 없음
# 반환값 : argparse 결과 객체

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            '이메일 스팸 분류 모델 비교 스크립트'
        )
    )

    parser.add_argument(
        '--data_path',
        type=str,
        default=DEFAULT_DATA_PATH,
        help=(
            '비교에 사용할 CSV 데이터 경로'
        )
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
    (
        X_train,
        X_valid,
        y_train,
        y_valid
    ) = split_train_valid(
        email_data
    )

    # 7. TF-IDF 객체 생성
    tfidf = build_tfidf()

    # 8. 동일한 TF-IDF 특성으로 변환
    (
        X_train_tfidf,
        X_valid_tfidf
    ) = transform_text(
        tfidf,
        X_train,
        X_valid
    )

    # 9. 비교할 모델 생성
    models = build_models()

    # 10. 세 모델 학습 및 평가
    result_data = compare_models(
        models,
        X_train_tfidf,
        X_valid_tfidf,
        y_train,
        y_valid
    )

    # 11. 최종 비교 결과 출력
    print_comparison_result(
        result_data
    )


if __name__ == '__main__':
    main()
