# src > api.py // @toblobs // 31.10.26
# for (rankington)

## intended use: uvicorn badminton.api:app --host 127.0.0.1 --port 8000

import hmac
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, Depends, File, Header, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .charts import history_chart
from .core import Store, DomainError
from .scheduling import schedule

from .__init__ import __version__

## pydantic models

class PlayerInput(BaseModel): name: str = Field(min_length = 1, max_length = 100)
     
class RerateInput(BaseModel):
    preview: bool = False    

class ScheduleInput(BaseModel):
    player_ids: list[str] = Field(min_length=4, max_length=24)
    mode: Literal["balanced", "matchmaking", "round-robin"] = "balanced"
    rounds: int = Field(default=7, ge=1, le=30)
    seed: int = 0

## fastAPI app

def create_app(db_path = None, admin_key = None):
    
    path = db_path or "data/badminton.sqlite3"
    key = admin_key if admin_key is not None else os.getenv("BADMINTON_ADMIN_KEY", "")
    
    @asynccontextmanager
    async def lifespan(app):
        
        app.state.store = Store(path)
        yield
        
    app = FastAPI(title = "Rankington", version = __version__, lifespan = lifespan,
                  description = "An ELO-like engine tasked with ranking, analysing and generating for my badminton group.") 
    
    def store(request: Request): return request.app.state.store
    
    def admin(x_api_key: str | None = Header(default = None)):
        
        if not key: raise DomainError("Set an admin key before enabling writes", 503)
        if not x_api_key or not hmac.compare_digest(x_api_key.encode(), key.encode()): raise DomainError("Invalid or missing X-API-KEY", 401)
        
    @app.exception_handler(DomainError)
    async def domain_error(request, exc): return JSONResponse(status_code = exc.status, content = {"detail": str(exc)})

    @app.exception_handler(sqlite3.OperationalError)
    async def db_error(request, exc):
        if "locked" in str(exc).lower() or "busy" in str(exc).lower(): return JSONResponse(status_code = 503, content = {"detail": "Database busy - retry the same request safely"}, headers = {"Retry-After": "2"})
        raise exc # server logging retains traceback
    
    @app.get("/health")
    def health(db: Store = Depends(store)):
        with db.connection() as conn: conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/players")
    def players(db: Store = Depends(store)): return db.players()

    @app.post("/players", dependencies = [Depends(admin)], status_code = 201)
    def create_player(body: PlayerInput, db: Store = Depends(store)): return db.create_player(body.name)

    @app.get("/weeks")
    def weeks(db: Store = Depends(store)): return db.weeks()

    @app.get("/leaderboard")
    def leaderboard(week: str | None = None, db: Store = Depends(store)): return db.leaderboard(week)

    @app.get("/players/{player_id}/history")
    def history(player_id: str, db: Store = Depends(store)): return db.history(player_id)

    @app.get("/matches")
    def matches(week: str | None = None, limit: int = Query(100, ge = 1, le = 1000), offset: int = Query(0, ge = 0), db: Store = Depends(store)): return db.matches(week, limit, offset)

    @app.get("/weeks/{week}/insights")
    def insights(week: str, db: Store = Depends(store)): return db.insights(week)
    
    async def upload(week, file, db, preview, replace):
        
        try:
            
            raw = await file.read(2_000_001)
            if len(raw) > 2_000_000: raise DomainError("CSV exceeds 2 MiB")
            
            try: text = raw.decode("utf-8-sig")
            except UnicodeDecodeError: raise DomainError("CSV must be UTF-8")
            
            return await run_in_threadpool(db.import_week, week, text, preview = preview, replace = replace)
        
        finally: await file.close()
    
    @app.post("/weeks/{week}/import", dependencies = [Depends(admin)])
    async def import_week(week: str, file: UploadFile = File(...), preview: bool = False, db: Store = Depends(store)): return await upload(week, file, db, preview, False)

    @app.put("/weeks/{week}/import", dependencies = [Depends(admin)])
    async def replace_week(week: str, file: UploadFile = File(...), preview: bool = False, db: Store = Depends(store)): return await upload(week, file, db, preview, True)

    @app.post("/ratings/recalculate", dependencies = [Depends(admin)])
    def rerate(body: RerateInput, db: Store = Depends(store)): return db.rerate(preview = body.preview)

    @app.post("/schedule", dependencies = [Depends(admin)])
    def make_schedule(body: ScheduleInput, db: Store = Depends(store)): return schedule(db, body.player_ids, body.mode, body.rounds, body.seed)

    @app.get("/charts/ratings.{image_format}")
    def chart(image_format: Literal["svg", "png"], player_ids: list[str] = Query(...), db: Store = Depends(store)):
        data = history_chart(db, player_ids, image_format)
        return Response(data, media_type = "image/svg+xml" if image_format == "svg" else "image/png")

    return app

app = create_app()
