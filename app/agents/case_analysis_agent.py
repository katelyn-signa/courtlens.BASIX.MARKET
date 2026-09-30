from app.schemas.analysis import CaseAnalysisRequest, CaseAnalysisResult
from app.services.case_analysis_service import analyze_case


def analyze(request: CaseAnalysisRequest) -> CaseAnalysisResult:
    return analyze_case(request)