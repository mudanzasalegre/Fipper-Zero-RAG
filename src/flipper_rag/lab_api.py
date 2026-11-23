"""Bounded local-only Protocol Lab API: no files opened, no subprocess/network calls."""
from __future__ import annotations

from importlib.resources import files
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Literal

from .protocol_lab import FORMATS, MAX_BYTES, analyze_text, render_report


class LabInput(BaseModel):
    filename: str = Field(default="sample.sub", max_length=120)
    content: str = Field(max_length=MAX_BYTES)
    file_format: str | None = Field(default=None, max_length=12)


class ReportInput(LabInput):
    output: Literal["json", "markdown", "html"] = "markdown"


def attach_lab(app: FastAPI) -> None:
    @app.get("/lab", response_class=HTMLResponse, tags=["protocol-lab"])
    def lab_home():
        return files("flipper_rag").joinpath("web/lab.html").read_text(encoding="utf-8")

    @app.get("/api/lab/formats", tags=["protocol-lab"])
    def lab_formats():
        return {"formats":FORMATS,"offline":True,"hardware_control":False,"data_retention":False}

    @app.post("/api/lab/analyze", tags=["protocol-lab"])
    def lab_analyze(req: LabInput):
        try:
            return analyze_text(req.content,filename=req.filename,file_format=req.file_format)
        except (ValueError,TypeError) as exc:
            raise HTTPException(status_code=422,detail="Unsupported, oversized or invalid text input") from exc

    @app.post("/api/lab/report", tags=["protocol-lab"])
    def lab_report(req: ReportInput):
        try:
            result=analyze_text(req.content,filename=req.filename,file_format=req.file_format)
            content=render_report(result,output=req.output)
            return {"report":content,"mime_type":{"json":"application/json","markdown":"text/markdown",
                       "html":"text/html"}[req.output], "redacted":True}
        except (ValueError,TypeError) as exc:
            raise HTTPException(status_code=422,detail="Unsupported, oversized or invalid text input") from exc
