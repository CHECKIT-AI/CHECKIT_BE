from typing import Literal


ClauseLabel = Literal[
    "임금",
    "근로시간",
    "휴일",
    "휴가",
    "근무 장소·업무",
    "계약기간",
    "계약 종료",
    "손해배상·위약금",
    "기타 근로조건",
    "그 외",
]

CLAUSE_LABELS: tuple[ClauseLabel, ...] = (
    "임금",
    "근로시간",
    "휴일",
    "휴가",
    "근무 장소·업무",
    "계약기간",
    "계약 종료",
    "손해배상·위약금",
    "기타 근로조건",
    "그 외",
)
