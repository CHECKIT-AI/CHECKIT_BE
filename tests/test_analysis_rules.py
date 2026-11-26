from app.analysis_rules import REQUIRED, candidates
from app.analysis import stored_clauses
from uuid import UUID


def clause(text, number=1):
    return {"clause_id": f"c{number}", "page": None, "text": text}


def test_all_required_fields_are_reviewed_even_when_labels_and_words_exist():
    rows = [clause("기본급 월급 250만원은 매월 25일 계좌 지급한다."),
            clause("1일 8시간 근무한다. 근무지는 서울, 담당 업무는 개발이다."),
            clause("주휴일과 연차 유급휴가를 준다.")]
    found = candidates(rows, {"effective_date": "2026-11-09"})
    required = [x for x in found if x["check_code"].startswith("MISSING_")]
    assert {x["check_code"] for x in required} == {f"MISSING_{code}" for code, _, _ in REQUIRED}
    assert len(required) == 8
    assert all(x["category"] == "MISSING" and x["status_hint"] == "NEEDS_CONFIRMATION"
               for x in required)


def test_payment_wording_does_not_gate_whole_document_review():
    rows = [clause("임금: 월 기본급 2,480,000원. 매월 25일 본인 계좌로\n지급한다."),
            clause("시간급 12,000원이다.", 2)]
    found = candidates(rows, {})
    codes = {item["check_code"] for item in found}
    assert {"MISSING_WAGE_CALCULATION", "MISSING_WAGE_PAYMENT"} <= codes


def test_missing_terms_have_neutral_review_hints():
    rows = [clause("근무지는 서울이고 담당 업무는 개발이다.")]
    found = candidates(rows, {})
    by_code = {x["check_code"]: x for x in found}
    assert by_code["MISSING_SCHEDULED_HOURS"]["status_hint"] == "NEEDS_CONFIRMATION"
    assert by_code["MISSING_WORKPLACE"]["status_hint"] == "NEEDS_CONFIRMATION"
    assert by_code["MISSING_WAGE_COMPONENTS"]["quoted_text"] is None


def test_explicit_problem_rules_and_application_conditions():
    rows = [clause("근로자가 중도 퇴사하면 위약금 100만원을 지급한다."),
            clause("시급 9,000원으로 한다.", 2),
            clause("연장 근로 수당은 지급하지 않는다.", 3),
            clause("1일 8시간 근무하며 휴게시간 30분이다.", 4)]
    found = candidates(rows, {"effective_date": "2026-11-09", "employee_count": 5})
    codes = {x["check_code"] for x in found}
    assert {"PRESET_PENALTY", "MINIMUM_WAGE", "OVERTIME_PREMIUM", "INSUFFICIENT_BREAK"} <= codes
    assert next(x for x in found if x["check_code"] == "OVERTIME_PREMIUM")["status_hint"] == "CAUTION"


def test_demo_penalty_and_retirement_waiver_create_separate_candidates():
    rows = [clause("8. 위약금: 근로자가 계약기간 만료 전에 퇴사하는 경우, 교육비 및 채용 비용 명목으로 50만 원을 사업주에게 배상한다."),
            clause("9. 퇴직금: 근로자는 퇴직금을 청구하지 않기로 하며, 퇴직금은 월 임금에 포함된 것으로 본다.", 2)]
    found = candidates(rows, {"effective_date": "2026-11-01"})
    assert {(item["check_code"], item["clause_id"]) for item in found} >= {
        ("PRESET_PENALTY", "c1"), ("RETIREMENT_PAY_WAIVER", "c2")}


def test_paged_stored_clauses_supply_source_ordinal_for_rule_candidates():
    first = "시급 9,800원으로 한다."
    content = first + "\n두 번째 조항"
    rows = stored_clauses(UUID(int=1), content, [
        {"page": 1, "start": 0, "end": len(first)},
        {"page": 2, "start": len(first) + 1, "end": len(content)},
    ])
    found = candidates(rows, {"effective_date": "2026-11-16"})
    wage = next(item for item in found if item["check_code"] == "MINIMUM_WAGE")
    assert wage["source_locations"] == [{"clause_id": rows[0]["clause_id"],
                                          "page": 1, "ordinal_on_page": 1}]
    assert rows[1]["ordinal_on_page"] == 1


def test_unknown_year_and_small_workplace_do_not_create_definite_numeric_candidate():
    rows = [clause("시급 9,000원. 연장 근로 수당은 지급하지 않는다.")]
    found = candidates(rows, {"effective_date": "2027-01-01", "employee_count": 4})
    assert next(x for x in found if x["check_code"] == "MINIMUM_WAGE")["status_hint"] == "NEEDS_CONFIRMATION"
    assert next(x for x in found if x["check_code"] == "OVERTIME_PREMIUM")["status_hint"] == "NEEDS_CONFIRMATION"


def test_monthly_wage_and_low_premium_are_review_candidates():
    rows = [clause("월급 2,000,000원. 연장근로 20% 가산한다.")]
    found = candidates(rows, {"effective_date": "2026-11-09", "employee_count": 5, "weekly_hours": 40})
    assert next(x for x in found if x["check_code"] == "MINIMUM_WAGE_MONTHLY")["status_hint"] == "NEEDS_CONFIRMATION"
    assert next(x for x in found if x["check_code"] == "OVERTIME_PREMIUM")["status_hint"] == "CAUTION"


def test_contractual_disadvantages_are_separate_from_legal_candidates():
    rows = [clause("회사는 필요에 따라 근무지를 변경할 수 있다."),
            clause("근로자는 모든 손해를 전액 배상할 책임이 있다.", 2)]
    found = candidates(rows, {})
    by_code = {item["check_code"]: item for item in found}
    assert by_code["UNILATERAL_CHANGE"]["category"] == "DISADVANTAGE"
    assert by_code["BROAD_LIABILITY"]["category"] == "DISADVANTAGE"
    assert by_code["MISSING_WAGE_PAYMENT"]["category"] == "MISSING"
