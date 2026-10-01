from fastapi import APIRouter

from app.api import analysis, audit, cases, documents, findings, health, metrics, notifications, reviews


def build_v1_router() -> APIRouter:
    v1 = APIRouter()
    v1.include_router(health.system_router)
    v1.include_router(metrics.router)
    v1.include_router(cases.router)
    v1.include_router(documents.router)
    v1.include_router(findings.router)
    v1.include_router(analysis.router)
    v1.include_router(reviews.router)
    v1.include_router(audit.router)
    v1.include_router(notifications.router)
    return v1
