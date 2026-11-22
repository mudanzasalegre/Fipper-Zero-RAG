"""Read-only firmware graph APIs, with no Git writes, subprocesses or device access."""
from __future__ import annotations
from importlib.resources import files
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .firmware_graph import FirmwareGraph

router=APIRouter(prefix='/api/firmware', tags=['Firmware Knowledge Graph v0.7'])
pages=APIRouter()
_graph:FirmwareGraph | None=None


def graph() -> FirmwareGraph:
    if _graph is None:raise RuntimeError('Firmware graph not configured')
    return _graph


def _safe(callback):
    try:return callback()
    except ValueError as exc:raise HTTPException(status_code=422, detail=str(exc)) from exc


@pages.get('/firmware',response_class=HTMLResponse)
def firmware_page():
    return files('flipper_rag').joinpath('web/firmware.html').read_text(encoding='utf-8')


@router.get('/snapshots')
def snapshots():
    return {'snapshots':graph().snapshots()}


@router.get('/symbols')
def symbols(ref:str=Query(max_length=100),query:str=Query(default='',max_length=160),
            kind:str=Query(default='',max_length=32),path_prefix:str=Query(default='',max_length=230),
            exported_only:bool=False,limit:int=Query(default=50,ge=1,le=200),offset:int=Query(default=0,ge=0,le=50000)):
    return _safe(lambda:graph().symbols(ref,query=query,kind=kind,path_prefix=path_prefix,
                                        exported_only=exported_only,limit=limit,offset=offset))


@router.get('/symbols/{symbol_id}')
def symbol(symbol_id:str, ref:str=Query(max_length=100)):
    return _safe(lambda:graph().symbol(ref,symbol_id))


@router.get('/references')
def references(ref:str=Query(max_length=100),name:str=Query(max_length=180),
               direction:str=Query(default='both',pattern='^(in|out|both)$'),limit:int=Query(default=80,ge=1,le=200)):
    return _safe(lambda:graph().references(ref,name,direction=direction,limit=limit))


@router.get('/graph')
def neighbors(ref:str=Query(max_length=100),name:str=Query(max_length=160),
              depth:int=Query(default=2,ge=1,le=3),limit:int=Query(default=100,ge=1,le=250)):
    return _safe(lambda:graph().neighbors(ref,name,depth=depth,limit=limit))


@router.get('/exports')
def exports(ref:str=Query(max_length=100),query:str=Query(default='',max_length=160),
            status:str=Query(default='',pattern=r'^[+?\-]?$'),limit:int=Query(default=100,ge=1,le=500)):
    return _safe(lambda:graph().exports(ref,query=query,status=status,limit=limit))


@router.get('/compare')
def compare(before:str=Query(max_length=100),after:str=Query(max_length=100),
            limit:int=Query(default=150,ge=1,le=1000),allow_partial:bool=False):
    return _safe(lambda:graph().compare(before,after,limit=limit,allow_partial=allow_partial))


def attach_firmware(app: FastAPI, db_path) -> None:
    global _graph
    _graph=FirmwareGraph(db_path)
    app.include_router(pages)
    app.include_router(router)
