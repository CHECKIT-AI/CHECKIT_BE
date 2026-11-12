import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.classifier as classifier_module
from app.access import require_csrf
from app.classifier import LocalClassifier, classifier_actor
from app.config import Settings
from app.errors import APIError
from app.main import create_app


MODEL_ID = "hur03/checkit-contract-classifier-core-synthetic-v1"
REVISION = "7fb6bc333b01919d7e59c1937e9457266d574cbe"


class Pool:
    def open(self):
        pass

    def close(self):
        pass


class Service:
    def predict(self, text):
        assert text == "월 급여는 매월 25일 지급한다."
        return {
            "model_id": MODEL_ID,
            "revision": REVISION,
            "max_length": 256,
            "labels": ["임금"],
            "scores": [{"label": "임금", "score": 0.9077, "threshold": 0.5}],
        }


def make_app(enabled=True):
    app = create_app(Settings(_env_file=None, classifier_enabled=enabled), pool=Pool())
    app.dependency_overrides[require_csrf] = lambda: None
    app.dependency_overrides[classifier_actor] = lambda: SimpleNamespace(kind="MEMBER", id="test")
    return app


def test_predict_response_and_swagger():
    app = make_app()
    app.state.classifier.service = Service()
    with TestClient(app) as client:
        response = client.post(
            "/api/classifier/predict", json={"text": " 월 급여는 매월 25일 지급한다. "},
        )
        assert response.status_code == 200
        assert response.json()["labels"] == ["임금"]
        assert response.json()["revision"] == REVISION
        assert response.headers["cache-control"] == "no-store"
        schema = client.get("/openapi.json").json()
        assert "200" in schema["paths"]["/api/classifier/predict"]["post"]["responses"]


@pytest.mark.parametrize("body", [
    {}, {"text": " "}, {"text": "a" * 2001}, {"text": "test", "labels": ["임금"]},
])
def test_invalid_input(body):
    with TestClient(make_app()) as client:
        assert client.post("/api/classifier/predict", json=body).status_code == 422


def test_csrf_and_session_required():
    app = make_app()
    app.state.classifier.service = Service()
    del app.dependency_overrides[require_csrf]
    with TestClient(app) as client:
        assert client.post("/api/classifier/predict", json={"text": "test"}).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None

    def no_session():
        raise APIError(401, "AUTHENTICATION_REQUIRED", "인증 필요")

    app.dependency_overrides[classifier_actor] = no_session
    with TestClient(app) as client:
        assert client.post("/api/classifier/predict", json={"text": "test"}).status_code == 401


def test_disabled_and_busy():
    classifier = LocalClassifier(Settings(_env_file=None))
    with pytest.raises(APIError) as error:
        classifier.predict("test")
    assert error.value.code == "CLASSIFIER_DISABLED"

    classifier.settings = Settings(_env_file=None, classifier_enabled=True)
    classifier.lock.acquire()
    try:
        with pytest.raises(APIError) as error:
            classifier.predict("test")
        assert error.value.code == "CLASSIFIER_BUSY"
    finally:
        classifier.lock.release()


def test_lazy_initialization_reuses_model_and_recovers(monkeypatch):
    calls = []

    def create(settings):
        calls.append(settings.classifier_revision)
        if len(calls) == 1:
            raise RuntimeError("/private/model/token")
        return Service()

    monkeypatch.setattr(classifier_module, "HuggingFaceClassifier", create)
    classifier = LocalClassifier(Settings(_env_file=None, classifier_enabled=True))
    with pytest.raises(APIError) as error:
        classifier.predict("월 급여는 매월 25일 지급한다.")
    assert error.value.code == "CLASSIFIER_UNAVAILABLE"
    assert "private" not in error.value.message

    classifier.predict("월 급여는 매월 25일 지급한다.")
    classifier.predict("월 급여는 매월 25일 지급한다.")
    assert calls == [REVISION, REVISION]


def test_inference_error_hides_details_and_releases_lock():
    class Broken:
        def predict(self, _):
            raise RuntimeError("/private/model/token")

    classifier = LocalClassifier(Settings(_env_file=None, classifier_enabled=True))
    classifier.service = Broken()
    with pytest.raises(APIError) as error:
        classifier.predict("test")
    assert error.value.code == "CLASSIFIER_UNAVAILABLE"
    assert "private" not in error.value.message
    assert not classifier.lock.locked()


def test_body_and_rate_limits():
    app = make_app()
    app.state.classifier.service = Service()
    with TestClient(app) as client:
        assert client.post("/api/classifier/predict", content=b"x" * 16385).status_code == 413
        for _ in range(30):
            response = client.post(
                "/api/classifier/predict", json={"text": "월 급여는 매월 25일 지급한다."},
            )
            assert response.status_code == 200
        assert client.post(
            "/api/classifier/predict", json={"text": "월 급여는 매월 25일 지급한다."},
        ).status_code == 429


@pytest.mark.skipif(
    os.getenv("CHECKIT_RUN_MODEL_TESTS") != "1",
    reason="set CHECKIT_RUN_MODEL_TESTS=1 to load the pinned public model",
)
def test_pinned_public_model_sample():
    service = classifier_module.HuggingFaceClassifier(
        Settings(_env_file=None, classifier_enabled=True),
    )
    result = service.predict("월 급여는 매월 25일 지급한다.")
    assert result["revision"] == REVISION
    assert result["labels"] == ["임금"]
    assert result["scores"] == [{"label": "임금", "score": 0.9077, "threshold": 0.5}]
