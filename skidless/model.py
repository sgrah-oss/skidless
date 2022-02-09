import json
import logging.config
import pickle
from datetime import datetime
from pathlib import Path

import pandas as pd
from kafka import KafkaConsumer
from lightgbm import LGBMClassifier
from rich.logging import RichHandler
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder

from config import config
from skidless.features import FeaturePreprocessor

# logger
logging.config.dictConfig(config.logging_config)
logger = logging.getLogger("root")
logger.handlers[0] = RichHandler(markup=True)


def train_preprocessor_and_model() -> None:
    # feature types
    target_name = "income_bracket"
    numerical_features = ["age", "fnlwgt", "capital_gain", "capital_loss", "hours_per_week"]
    categorical_features = [
        "workclass",
        "education",
        "marital_status",
        "occupation",
        "relationship",
        "race",
        "gender",
        "native_country",
    ]
    feature_names = numerical_features + categorical_features

    # dataset
    logger.info("getting dataset...")
    train_path = config.PATH_DATA_RAW / "adult.data.csv"
    test_path = config.PATH_DATA_RAW / "adult.test.csv"
    df_train = pd.read_csv(train_path)
    df_test = pd.read_csv(test_path)
    X_train, y_train = df_train[feature_names], df_train[target_name]
    X_test, y_test = df_test[feature_names], df_test[target_name]

    # preprocessor
    logger.info("creating preprocessors...")
    ## target
    target_preprocessor = LabelEncoder().fit(y_train)
    y_train = target_preprocessor.transform(y_train)
    ## features
    feature_preprocessor = FeaturePreprocessor(
        feature_names, categorical_features, numerical_features
    )
    X_train = feature_preprocessor.fit_transform(X_train)

    # model
    logger.info("creating model...")
    model_params = {
        "learning_rate": 0.1,
        "max_depth": 3,
        "n_estimators": 300,
        "categorical_feature": [feature_names.index(col_name) for col_name in categorical_features],
        "n_jobs": 1,
        "random_state": 1234,
    }
    model = LGBMClassifier(objective="binary", **model_params).fit(X_train, y_train)

    # evaluation
    logger.info("evaluating model...")
    y_test = target_preprocessor.transform(y_test)
    X_test = feature_preprocessor.transform(X_test)
    y_pred = model.predict(X_test)
    logger.info(classification_report(y_test, y_pred))

    # store preprocessor
    logger.info("storing preprocessor...")
    now = datetime.now()
    dt_string = now.strftime("%d-%m-%Y %H:%M:%S")
    pickle.dump(
        target_preprocessor,
        open(Path(config.MODELS_PATH, f"target-preprocessor-{dt_string}"), "wb"),
    )
    pickle.dump(
        target_preprocessor, open(Path(config.MODELS_PATH, "latest-target-preprocessor"), "wb")
    )
    pickle.dump(
        feature_preprocessor,
        open(Path(config.MODELS_PATH, f"feature-preprocessor-{dt_string}"), "wb"),
    )
    pickle.dump(
        feature_preprocessor, open(Path(config.MODELS_PATH, "latest-feature-preprocessor"), "wb")
    )

    # store model
    logger.info("storing model...")
    pickle.dump(model, open(Path(config.MODELS_PATH, f"model-{dt_string}"), "wb"))
    pickle.dump(model, open(Path(config.MODELS_PATH, "latest-model"), "wb"))


def predicting_message():
    feature_preprocessor = pickle.load(
        open(Path(config.MODELS_PATH, "latest-feature-preprocessor"), "rb")
    )
    model = pickle.load(open(Path(config.MODELS_PATH, "latest-model"), "rb"))

    consumer = KafkaConsumer(bootstrap_servers=config.KAFKA_HOST)  # , auto_offset_reset='earliest')
    consumer.subscribe(["app_messages"])

    for msg in consumer:
        message = json.loads(msg.value)
        request_id = message["request_id"]
        x_input = pd.DataFrame(data=message["data"], index=[request_id])
        logger.info(f"Message ID {request_id}")
        logger.info(x_input)
        message_preprocessed = feature_preprocessor.transform(x_input)
        message_prediction = model.predict(message_preprocessed)
        logger.info(f"Prediction of earning more than 50>= : {message_prediction.squeeze()}")
