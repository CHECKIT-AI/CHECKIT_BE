"""Conservative, versioned employment-contract issue candidate rules."""

import re
from datetime import date

RULE_VERSION = "employment_rules_v1"

# The deployed corpus contains the 2026 notice. Other years require a new,
# reviewed notice snapshot before a numeric minimum-wage comparison is made.
MINIMUM_HOURLY_WAGE = {2026: 10320}
MINIMUM_MONTHLY_209H = {2026: 2156880}

REQUIRED = (
    ("WAGE_COMPONENTS", "임금", (r"기본급|수당|임금.{0,8}구성|급여.{0,8}항목",), "임금 구성 항목"),
    ("WAGE_CALCULATION", "임금", (r"시급|월급|연봉|일급|임금.{0,8}계산|급여.{0,8}산정",), "임금 계산 방법"),
    ("WAGE_PAYMENT", "임금", (r"지급일|매월.{0,12}지급|계좌.{0,12}지급|현금.{0,12}지급|지급.{0,8}방법",), "임금 지급 방법"),
    ("SCHEDULED_HOURS", "근로시간", (r"근로\s*시간|근무\s*시간|소정.*시간|출근.*퇴근|(?:1일|하루|일)\s*\d{1,2}\s*시간",), "소정근로시간"),
    ("HOLIDAY", "휴일", (r"휴일|주휴|공휴일",), "휴일"),
    ("ANNUAL_LEAVE", "휴가", (r"연차|유급휴가",), "연차 유급휴가"),
    ("WORKPLACE", "근무 장소·업무", (r"근무\s*장소|근무지|취업\s*장소",), "근무 장소"),
    ("DUTIES", "근무 장소·업무", (r"업무|직무|담당",), "종사할 업무"),
)


def _candidate(code, clause=None, *, category="LEGAL_RISK", status="CAUTION", explanation="", needed=(), labels=()):
    return {
        "check_code": code, "category": category, "status_hint": status,
        "clause_id": clause["clause_id"] if clause else None,
        "quoted_text": clause["text"] if clause else None,
        "explanation": explanation, "required_information": list(needed),
        "labels": list(labels),
        "source_locations": ([{"clause_id": clause["clause_id"], **(
            {"page": clause["page"], "ordinal_on_page": clause["ordinal_on_page"]}
            if clause.get("page") is not None else {})}] if clause else []),
    }


def candidates(clauses: list[dict], classifications: list[dict], context: dict) -> list[dict]:
    """Find review candidates; never turn a label alone into a legal verdict."""
    output = []
    labels = set().union(*(set(row["labels"]) for row in classifications)) if classifications else set()
    whole_text = "\n".join(clause["text"] for clause in clauses)
    for code, label, patterns, name in REQUIRED:
        lexical = any(re.search(pattern, whole_text) for pattern in patterns)
        if label not in labels or not lexical:
            output.append(_candidate(
                f"MISSING_{code}", category="MISSING", status="MISSING_SUSPECTED" if not lexical and label not in labels
                else "NEEDS_CONFIRMATION", explanation=f"{name}의 명시 여부를 확인해야 합니다.",
                needed=(name,), labels=(label,),
            ))

    year = date.fromisoformat(context["effective_date"]).year if context.get("effective_date") else None
    headcount = context.get("employee_count")
    for clause in clauses:
        text = clause["text"]
        if re.search(r"(?:회사|사용자).{0,30}(?:필요에\s*따라|임의로|일방적으로).{0,35}(?:근무지|근무\s*장소|업무|직무|임금).{0,15}변경", text, re.S):
            output.append(_candidate("UNILATERAL_CHANGE", clause, category="DISADVANTAGE",
                                     explanation="회사가 주요 근로조건을 일방적으로 바꿀 수 있는 문구 후보입니다.",
                                     labels=("기타 근로조건",)))
        if re.search(r"(?:모든|일체의|전액).{0,30}(?:손해|손실).{0,30}(?:배상|책임)", text, re.S):
            output.append(_candidate("BROAD_LIABILITY", clause, category="DISADVANTAGE",
                                     explanation="근로자에게 손해 책임을 넓게 지우는 문구 후보입니다.",
                                     labels=("손해배상·위약금",)))
        if re.search(r"(?:퇴사|퇴직).{0,40}(?:경쟁업체|동종업계|동종\s*업체).{0,30}(?:취업|근무).{0,10}(?:금지|제한)", text, re.S):
            output.append(_candidate("POST_EMPLOYMENT_RESTRICTION", clause, category="DISADVANTAGE",
                                     explanation="퇴사 후 취업을 제한하는 문구 후보입니다.",
                                     labels=("기타 근로조건",)))
        penalty = re.search(r"(퇴사|퇴직|계약\s*불이행|중도\s*해지).{0,45}(위약금|벌금|배상액|손해배상액).{0,25}(원|지급|배상)", text, re.S)
        penalty = penalty or re.search(r"(퇴사|퇴직|계약\s*불이행|중도\s*해지).{0,35}[\d,]+\s*만?원.{0,20}(위약금|벌금|배상)", text, re.S)
        if penalty and not re.search(r"위약금\s*(?:없음|없다|미부과)", text):
            output.append(_candidate("PRESET_PENALTY", clause,
                                     explanation="근로계약 불이행에 대한 위약금·손해배상액 예정 문구 후보입니다.",
                                     labels=("손해배상·위약금",)))

        wage = re.search(r"(?:시급|시간급)\s*(?:은|:|=)?\s*([\d,]+)\s*원", text)
        if wage:
            amount = int(wage.group(1).replace(",", ""))
            if year in MINIMUM_HOURLY_WAGE and amount < MINIMUM_HOURLY_WAGE[year]:
                output.append(_candidate("MINIMUM_WAGE", clause,
                    explanation=f"명시된 시급 {amount}원이 {year}년 기준액보다 낮습니다.",
                    needed=("최저임금 산입 임금 및 적용 예외",), labels=("임금",)))
            elif year not in MINIMUM_HOURLY_WAGE:
                output.append(_candidate("MINIMUM_WAGE", clause, status="NEEDS_CONFIRMATION",
                    explanation="기준일에 해당하는 검증된 최저임금 고시가 없습니다.",
                    needed=("적용 연도의 최저임금 고시",), labels=("임금",)))

        monthly = re.search(r"월급\s*(?:은|:|=)?\s*([\d,]+)\s*원", text)
        if monthly and context.get("weekly_hours") == 40 and year in MINIMUM_MONTHLY_209H:
            amount = int(monthly.group(1).replace(",", ""))
            if amount < MINIMUM_MONTHLY_209H[year]:
                output.append(_candidate("MINIMUM_WAGE_MONTHLY", clause, status="NEEDS_CONFIRMATION",
                    explanation="주 40시간·월 209시간 환산 기준보다 명시 월급이 낮을 가능성이 있습니다.",
                    needed=("주휴 포함 월 소정근로시간", "최저임금 산입 임금"), labels=("임금",)))

        if re.search(r"(연장|야간|휴일).{0,35}(수당|가산).{0,20}(없음|없다|지급하지\s*않|미지급|포함하지\s*않)", text, re.S):
            output.append(_candidate("OVERTIME_PREMIUM", clause,
                status="CAUTION" if headcount is not None and headcount >= 5 else "NEEDS_CONFIRMATION",
                explanation="연장·야간·휴일근로 가산수당을 배제하는 문구 후보입니다.",
                needed=() if headcount is not None and headcount >= 5 else ("상시 근로자 수",),
                labels=("임금", "근로시간")))
        premium = re.search(r"(연장|야간|휴일).{0,35}(\d{1,3})\s*%\s*가산", text, re.S)
        if premium and int(premium.group(2)) < 50:
            output.append(_candidate("OVERTIME_PREMIUM", clause,
                status="CAUTION" if headcount is not None and headcount >= 5 else "NEEDS_CONFIRMATION",
                explanation="명시된 연장·야간·휴일근로 가산율이 50%보다 낮습니다.",
                needed=() if headcount is not None and headcount >= 5 else ("상시 근로자 수",),
                labels=("임금", "근로시간")))

        hours = re.search(r"(?:1일|하루|일)\s*(\d{1,2})\s*시간\s*(?:근로|근무)", text)
        break_time = re.search(r"휴게\s*(?:시간)?\s*(?:은|:|=)?\s*(\d{1,3})\s*분", text)
        if hours and break_time:
            h, minutes = int(hours.group(1)), int(break_time.group(1))
            required = 60 if h >= 8 else 30 if h >= 4 else 0
            if required and minutes < required:
                output.append(_candidate("INSUFFICIENT_BREAK", clause,
                    explanation=f"1일 {h}시간 근로에 휴게 {minutes}분으로 명시되어 있습니다.",
                    needed=("휴게시간의 실제 부여 방식",), labels=("근로시간",)))
    return output
