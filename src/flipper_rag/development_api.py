"""Read-only development references and bounded static validation. No HTTP build endpoint."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .development import (get_template, guides, valid_relative_path,
                          validate_project, templates)


class InlineProject(BaseModel):
    kind: str = Field(default="auto", pattern=r"^(auto|fap|mjs)$")
    files: dict[str, str] = Field(min_length=1, max_length=24)


def attach_development(app: FastAPI) -> None:
    @app.get("/development", response_class=HTMLResponse, include_in_schema=False)
    def development_page():
        return files("flipper_rag").joinpath("web/development.html").read_text("utf-8")

    @app.get("/api/development/templates")
    def template_list():
        return {"count": len(templates()), "templates": templates()}

    @app.get("/api/development/templates/{template_id}")
    def template_detail(template_id: str):
        try:
            return get_template(template_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/development/guides")
    def guide_list():
        return {"count": len(guides()), "guides": guides()}

    @app.get("/api/development/guides/{guide_id}")
    def guide_detail(guide_id: str):
        for item in guides():
            if item["id"] == guide_id:
                return item
        raise HTTPException(status_code=404, detail="Unknown development guide")

    @app.post("/api/development/validate")
    def validate_inline(payload: InlineProject):
        if sum(len(s.encode("utf-8")) for s in payload.files.values()) > 64000:
            raise HTTPException(status_code=413, detail="Project exceeds 64 KiB source limit")
        if any(not valid_relative_path(name) or name.endswith(".py") for name in payload.files):
            raise HTTPException(status_code=422, detail="Invalid or unsupported source filename")
        with TemporaryDirectory(prefix="fzr-v08-") as name:
            root = Path(name)
            for filename, content in payload.files.items():
                p = root / filename
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            try:
                return validate_project(root, kind=payload.kind)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
