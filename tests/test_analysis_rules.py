from app.analysis_rules import candidates


def clause(text, number=1):
    return {"clause_id": f"c{number}", "page": None, "text": text}


def classification(labels):
    return {"labels": labels}


def test_required_fields_are_document_wide_and_classifier_is_only_a_hint():
    rows = [clause("기본급 월급 250만원은 매월 25일 계좌 지급한다."),
            clause("1일 8시간 근무한다. 근무지는 서울, 담당 업무는 개발이다."),
            clause("주휴일과 연차 유급휴가를 준다.")]
    found = candidates(rows, [classification(["임금"]), classification(["근로시간", "근무 장소·업무"]),
                              classification(["휴일", "휴가"])], {"effective_date": "2026-11-09"})
    assert not [x for x in found if x["check_code"].startswith("MISSING_")]


def test_missing_and_mismatched_label_remain_candidates():
    rows = [clause("근무지는 서울이고 담당 업무는 개발이다.")]
    found = candidates(rows, [classification(["임금"])], {})
    by_code = {x["check_code"]: x for x in found}
    assert by_code["MISSING_SCHEDULED_HOURS"]["status_hint"] == "MISSING_SUSPECTED"
    assert by_code["MISSING_WORKPLACE"]["status_hint"] == "NEEDS_CONFIRMATION"
    assert by_code["MISSING_WAGE_COMPONENTS"]["quoted_text"] is None


def test_explicit_problem_rules_and_application_conditions():
    rows = [clause("근로자가 중도 퇴사하면 위약금 100만원을 지급한다."),
            clause("시급 9,000원으로 한다.", 2),
            clause("연장 근로 수당은 지급하지 않는다.", 3),
            clause("1일 8시간 근무하며 휴게시간 30분이다.", 4)]
    found = candidates(rows, [classification([]) for _ in rows],
                       {"effective_date": "2026-11-09", "employee_count": 5})
    codes = {x["check_code"] for x in found}
    assert {"PRESET_PENALTY", "MINIMUM_WAGE", "OVERTIME_PREMIUM", "INSUFFICIENT_BREAK"} <= codes
    assert next(x for x in found if x["check_code"] == "OVERTIME_PREMIUM")["status_hint"] == "CAUTION"


def test_unknown_year_and_small_workplace_do_not_create_definite_numeric_candidate():
    rows = [clause("시급 9,000원. 연장 근로 수당은 지급하지 않는다.")]
    found = candidates(rows, [classification(["임금"])],
                       {"effective_date": "2027-01-01", "employee_count": 4})
    assert next(x for x in found if x["check_code"] == "MINIMUM_WAGE")["status_hint"] == "NEEDS_CONFIRMATION"
    assert next(x for x in found if x["check_code"] == "OVERTIME_PREMIUM")["status_hint"] == "NEEDS_CONFIRMATION"


def test_monthly_wage_and_low_premium_are_review_candidates():
    rows = [clause("월급 2,000,000원. 연장근로 20% 가산한다.")]
    found = candidates(rows, [classification(["임금", "근로시간"])],
                       {"effective_date": "2026-11-09", "employee_count": 5, "weekly_hours": 40})
    assert next(x for x in found if x["check_code"] == "MINIMUM_WAGE_MONTHLY")["status_hint"] == "NEEDS_CONFIRMATION"
    assert next(x for x in found if x["check_code"] == "OVERTIME_PREMIUM")["status_hint"] == "CAUTION"


def test_contractual_disadvantages_are_separate_from_legal_candidates():
    rows = [clause("회사는 필요에 따라 근무지를 변경할 수 있다."),
            clause("근로자는 모든 손해를 전액 배상할 책임이 있다.", 2)]
    found = candidates(rows, [classification([]) for _ in rows], {})
    by_code = {item["check_code"]: item for item in found}
    assert by_code["UNILATERAL_CHANGE"]["category"] == "DISADVANTAGE"
    assert by_code["BROAD_LIABILITY"]["category"] == "DISADVANTAGE"
    assert by_code["MISSING_WAGE_PAYMENT"]["category"] == "MISSING"
