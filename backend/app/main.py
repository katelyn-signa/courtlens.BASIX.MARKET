"""ASGI application exposing the existing reasoning subsystem API."""

from fastapi import FastAPI

from backend.app.api.reasoning import router as reasoning_router


app = FastAPI(
	title="CourtLens Reasoning Subsystem",
	description=(
		"Deterministic evidence reasoning and explanation. This app does not include "
		"the future CourtLens case lifecycle or upstream agents."
	),
	version="1.0.0",
)
app.include_router(reasoning_router)
