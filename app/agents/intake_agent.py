from app.schemas.case import CaseIntakeRequest, CaseIntakeResult
from app.services.case_intake_service import assemble_case


def assemble_case_intake(request: CaseIntakeRequest) -> CaseIntakeResult:
    return assemble_case(request)