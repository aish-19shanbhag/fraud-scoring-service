"""FastAPI application entry point.

Run locally with:  uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

import fakeredis
import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker
from threadpoolctl import threadpool_limits

from app.config import Settings
from app.database import Base, make_engine
from app.feature_store import FeatureStore
from app.routers import stats, transactions
from app.scoring import FraudModel
from app.websocket import ConnectionManager
from app.websocket import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fraud-api")

API_VERSION = "1.0.0"


def build_redis(url: str | None) -> redis.Redis:
    if url:
        return redis.Redis.from_url(url, decode_responses=True)
    logger.warning("REDIS_URL not set: using in-memory fake Redis (fine for local dev, not production)")
    return fakeredis.FakeRedis(decode_responses=True)


def create_app(settings: Settings | None = None, redis_client: redis.Redis | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Each request scores one row; letting the model spawn its own threads
        # just fights with FastAPI's request threads, so keep it to one.
        threadpool_limits(1)
        engine = make_engine(settings.database_url)
        Base.metadata.create_all(engine)  # simple schema setup; use Alembic for migrations
        client = redis_client or build_redis(settings.redis_url)

        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        app.state.redis = client
        app.state.feature_store = FeatureStore(client)
        app.state.model = FraudModel.load(settings.model_path, settings.amber_threshold, settings.red_threshold)
        app.state.ws_manager = ConnectionManager()
        logger.info(
            "Loaded model %s (amber >= %.3f, red >= %.3f)",
            app.state.model.version,
            app.state.model.amber_threshold,
            app.state.model.red_threshold,
        )
        yield
        engine.dispose()

    app = FastAPI(
        title="Real-Time Transaction Fraud Scoring Service",
        description="Scores card transactions for fraud in milliseconds and streams alerts to analysts.",
        version=API_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(transactions.router)
    app.include_router(stats.router)
    app.include_router(ws_router)
    return app


app = create_app()
