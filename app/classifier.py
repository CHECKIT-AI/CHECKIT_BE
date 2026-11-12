"""Authenticated contract-clause classification backed by a pinned Hugging Face model."""

import json
import logging
from threading import Lock

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.access import current_actor, require_csrf
from app.ai_contracts import CLAUSE_LABELS, ClauseLabel
from app.api_docs import error_response
from app.errors import APIError

router = APIRouter(prefix="/api/classifier", tags=["classifier"])
logger = logging.getLogger(__name__)


class ClassificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000, description="분류할 계약 조항 원문")

    @field_validator("text")
    @classmethod
    def strip_text(cls, value):
        if not value.strip():
            raise ValueError("분류할 문장을 입력하세요.")
        return value.strip()


class LabelScore(BaseModel):
    label: ClauseLabel
    score: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)


class ClassificationOutput(BaseModel):
    model_id: str
    revision: str
    max_length: int
    labels: list[ClauseLabel]
    scores: list[LabelScore]


class HuggingFaceClassifier:
    def __init__(self, settings):
        import torch
        from huggingface_hub import hf_hub_download
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.model_id = settings.classifier_model_id
        self.revision = settings.classifier_revision
        self.max_length = settings.classifier_max_length

        labels_path = hf_hub_download(
            repo_id=self.model_id, filename="labels.json", revision=self.revision,
        )
        with open(labels_path, encoding="utf-8") as file:
            label_data = json.load(file)
        labels = label_data.get("labels")
        thresholds = label_data.get("thresholds")
        if labels != list(CLAUSE_LABELS) or not isinstance(thresholds, dict):
            raise ValueError("classifier label contract mismatch")
        try:
            self.thresholds = [float(thresholds[label]) for label in CLAUSE_LABELS]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid classifier thresholds") from exc
        if any(value < 0 or value > 1 for value in self.thresholds):
            raise ValueError("invalid classifier thresholds")

        self.device = self._device(settings.classifier_device)
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_id, revision=self.revision, trust_remote_code=False,
        )
        self.model = AutoModelForSequenceClassification.from_pretrained(
            self.model_id, revision=self.revision, trust_remote_code=False,
        )
        if self.model.config.num_labels != len(CLAUSE_LABELS):
            raise ValueError("classifier output size mismatch")
        self.model.to(self.device)
        self.model.eval()

    def _device(self, configured):
        if configured == "auto":
            if self.torch.cuda.is_available():
                return self.torch.device("cuda")
            mps = getattr(self.torch.backends, "mps", None)
            if mps is not None and mps.is_available():
                return self.torch.device("mps")
            return self.torch.device("cpu")
        if configured == "cuda" and not self.torch.cuda.is_available():
            raise ValueError("CUDA is unavailable")
        if configured == "mps":
            mps = getattr(self.torch.backends, "mps", None)
            if mps is None or not mps.is_available():
                raise ValueError("MPS is unavailable")
        return self.torch.device(configured)

    def predict(self, text):
        inputs = self.tokenizer(
            text, truncation=True, max_length=self.max_length,
            padding="max_length", return_tensors="pt",
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.no_grad():
            probabilities = self.torch.sigmoid(self.model(**inputs).logits)[0]
        values = probabilities.detach().cpu().tolist()
        scores = [
            {"label": label, "score": round(float(score), 4), "threshold": threshold}
            for label, score, threshold in zip(CLAUSE_LABELS, values, self.thresholds)
            if score >= threshold
        ]
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "max_length": self.max_length,
            "labels": [item["label"] for item in scores],
            "scores": scores,
        }


class LocalClassifier:
    """Load one classifier per process and reject concurrent inference."""

    def __init__(self, settings):
        self.settings = settings
        self.service = None
        self.lock = Lock()

    def predict(self, text):
        if not self.settings.classifier_enabled:
            logger.warning("Classifier unavailable: reason=disabled")
            raise APIError(503, "CLASSIFIER_DISABLED", "분류 기능을 활성화해야 합니다.")
        if not self.lock.acquire(blocking=False):
            logger.warning("Classifier unavailable: reason=busy")
            raise APIError(503, "CLASSIFIER_BUSY", "분류 처리 중입니다. 잠시 후 다시 시도하세요.", retryable=True)
        try:
            if self.service is None:
                try:
                    logger.info("Classifier model loading started")
                    self.service = HuggingFaceClassifier(self.settings)
                    logger.info("Classifier model loading completed")
                except Exception as exc:
                    logger.error("Classifier model loading failed: error_type=%s", type(exc).__name__)
                    raise APIError(
                        503, "CLASSIFIER_UNAVAILABLE", "분류 모델 준비 상태를 확인하세요."
                    ) from None
            try:
                return self.service.predict(text)
            except APIError:
                raise
            except Exception as exc:
                logger.error("Classifier inference failed: error_type=%s", type(exc).__name__)
                raise APIError(
                    503, "CLASSIFIER_UNAVAILABLE", "분류 요청을 처리할 수 없습니다.", retryable=True
                ) from None
        finally:
            self.lock.release()


def classifier_actor(request: Request):
    with request.app.state.database_pool.connection() as conn:
        return current_actor(request, conn)


@router.post(
    "/predict", response_model=ClassificationOutput, dependencies=[Depends(require_csrf)],
    summary="계약 조항 분류",
    description="회원 세션과 CSRF 헤더 필요. 조항 원문을 고정 버전 멀티라벨 모델로 분류합니다.",
    responses={
        401: error_response("AUTHENTICATION_REQUIRED", "회원 세션 필요", "인증이 필요합니다.", "LOGIN"),
        403: error_response("CSRF_FAILED", "CSRF 토큰 또는 Origin 오류", "보안 토큰을 확인하세요."),
        413: error_response("REQUEST_TOO_LARGE", "본문 16,384바이트 초과", "요청 크기가 너무 큽니다."),
        422: error_response("INVALID_INPUT", "입력 형식 또는 길이 오류", "입력 형식을 확인하세요."),
        429: error_response("RATE_LIMITED", "세션당 분당 30회 초과", "잠시 후 다시 시도하세요.", retryable=True),
        503: error_response("CLASSIFIER_UNAVAILABLE", "분류 비활성화·준비 실패 또는 동시 처리 중", "분류 모델 준비 상태를 확인하세요."),
    },
)
def predict(body: ClassificationInput, request: Request, actor=Depends(classifier_actor)):
    request.app.state.auth_limiter.check(f"classifier:{actor.kind}:{actor.id}", limit=30)
    return request.app.state.classifier.predict(body.text)
