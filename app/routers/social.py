import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import statistics

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.auth import User
from app.models.monitoring import ProviderConnection
from app.models.login_activity import DemoActivityEvent
from app.models.social import OAuthState, ParticipantAuditEvent, PostMetric, SocialParticipant
from app.routers.auth import current_user
from app.schemas.social import (
    DiagnosisResponse,
    OAuthStartResponse,
    ParticipantCreate,
    ParticipantCreateResponse,
    ParticipantResponse,
    PostMetricCreate,
    PostMetricResponse,
    ProviderConnectionSummary,
)
from app.services.providers import MockProvider, sync_connection
from app.time import utcnow

router = APIRouter(prefix="/social", tags=["social accounts"])
settings = get_settings()


def hash_state(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def owned_connection(db: Session, user_id: int, connection_id: int) -> ProviderConnection:
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.id == connection_id,
            ProviderConnection.user_id == user_id,
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connected account not found")
    return connection


def metric_response(metric: PostMetric, connection: ProviderConnection) -> PostMetricResponse:
    interactions = (metric.likes or 0) + (metric.comments or 0)
    denominator = metric.reach or metric.impressions
    rate = round(interactions / denominator * 100, 2) if denominator else None
    return PostMetricResponse(
        id=metric.id,
        provider_connection_id=metric.provider_connection_id,
        external_post_id=metric.external_post_id,
        title=metric.title,
        published_at=metric.published_at,
        likes=metric.likes,
        comments=metric.comments,
        reach=metric.reach,
        impressions=metric.impressions,
        shares=metric.shares,
        saves=metric.saves,
        source=metric.source,
        connection_health=connection.health_status,
        authorization_status=connection.authorization_status,
        engagement_rate=rate,
    )


@router.get("/connections", response_model=list[ProviderConnectionSummary])
def list_social_connections(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[ProviderConnection]:
    return list(
        db.scalars(
            select(ProviderConnection)
            .where(ProviderConnection.user_id == user.id)
            .order_by(ProviderConnection.created_at.desc())
        ).all()
    )


@router.get("/oauth/{provider}/start", response_model=OAuthStartResponse)
def start_oauth(
    provider: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> OAuthStartResponse:
    if provider != "meta":
        raise HTTPException(status_code=400, detail="Only the configured Meta integration is supported")
    raw_state = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(seconds=settings.oauth_state_ttl_seconds)
    db.add(
        OAuthState(
            user_id=user.id,
            provider=provider,
            state_hash=hash_state(raw_state),
            redirect_uri=settings.meta_redirect_uri,
            expires_at=expires_at,
        )
    )
    db.commit()
    if settings.meta_demo_mode or not settings.meta_app_id or not settings.meta_oauth_scopes:
        return OAuthStartResponse(
            provider=provider,
            mode="demo",
            authorization_url=None,
            state=raw_state,
            message="Demo mode: use the returned state with code=demo. No Meta account is accessed.",
        )
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.meta_redirect_uri,
        "state": raw_state,
        "scope": settings.meta_oauth_scopes,
        "response_type": "code",
    }
    return OAuthStartResponse(
        provider=provider,
        mode="live",
        authorization_url=f"{settings.meta_authorization_url}?{urlencode(params)}",
        state=None,
        message="Live authorization requires a Meta app with approved permissions and a matching redirect URI.",
    )


@router.get("/oauth/callback")
def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, str | int]:
    if error:
        raise HTTPException(status_code=400, detail=f"Provider authorization failed: {error}")
    if not state:
        raise HTTPException(status_code=400, detail="OAuth state is required")
    authorization = db.scalar(
        select(OAuthState).where(OAuthState.state_hash == hash_state(state))
    )
    if not authorization or authorization.used_at or authorization.expires_at <= utcnow():
        raise HTTPException(status_code=400, detail="Invalid, expired, or already-used OAuth state")
    if not code:
        raise HTTPException(status_code=400, detail="Provider authorization code is required")
    authorization.used_at = utcnow()
    if code != "demo" or not settings.meta_demo_mode:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Live Meta callback exchange requires configured app credentials, approved permissions, and a token adapter",
        )
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.user_id == authorization.user_id,
            ProviderConnection.provider == "meta",
            ProviderConnection.connection_mode == "demo",
        ).order_by(ProviderConnection.created_at.asc())
    )
    if not connection:
        connection = ProviderConnection(
            user_id=authorization.user_id,
            provider="meta",
            external_account_id=f"demo-meta-{secrets.token_hex(4)}",
            connection_mode="demo",
            authorization_status="authorized",
            health_status="healthy",
            status="healthy",
            scopes=["demo"],
            consent_recorded_at=utcnow(),
        )
        db.add(connection)
    else:
        connection.authorization_status = "authorized"
        connection.health_status = "healthy"
        connection.status = "healthy"
        connection.error_code = None
        connection.error_message = None
    db.commit()
    db.refresh(connection)
    return {
        "connection_id": connection.id,
        "mode": "demo",
        "message": "Synthetic Meta connection ready",
    }


@router.delete("/connections/{connection_id}", status_code=204)
def disconnect_connection(
    connection_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    connection = owned_connection(db, user.id, connection_id)
    connection.authorization_status = "revoked"
    connection.health_status = "unknown"
    connection.status = "revoked"
    connection.error_code = "disconnected_by_user"
    connection.error_message = "Disconnected by the owning user"
    db.commit()


@router.post("/participants", response_model=ParticipantCreateResponse, status_code=201)
def create_participant(
    payload: ParticipantCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ParticipantCreateResponse:
    connection = (
        owned_connection(db, user.id, payload.provider_connection_id)
        if payload.provider_connection_id
        else None
    )
    consent_token = secrets.token_urlsafe(32)
    participant = SocialParticipant(
        user_id=user.id,
        provider_connection_id=connection.id if connection else None,
        display_name=payload.display_name,
        is_demo=payload.is_demo,
        provider_account_id=connection.external_account_id if connection else None,
        provider=connection.provider if connection else "unconnected",
        consent_status="pending",
        consent_token_hash=hash_state(consent_token),
        consent_expires_at=utcnow() + timedelta(days=7),
        participation_status="paused",
        connection_health=connection.health_status if connection else "unknown",
    )
    db.add(participant)
    db.flush()
    db.add(
        ParticipantAuditEvent(
            participant_id=participant.id,
            user_id=user.id,
            action="created",
            details={"consent_status": "pending"},
        )
    )
    db.commit()
    db.refresh(participant)
    return ParticipantCreateResponse(participant=participant, consent_token=consent_token)


@router.get("/participants", response_model=list[ParticipantResponse])
def list_participants(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[SocialParticipant]:
    return list(
        db.scalars(
            select(SocialParticipant)
            .where(SocialParticipant.user_id == user.id)
            .order_by(SocialParticipant.created_at.desc())
        ).all()
    )


@router.post("/participants/{participant_id}/consent", response_model=ParticipantResponse)
def confirm_participant_consent(
    participant_id: int,
    token: str = Query(..., min_length=20),
    db: Session = Depends(get_db),
) -> SocialParticipant:
    participant = db.scalar(
        select(SocialParticipant).where(
            SocialParticipant.id == participant_id,
            SocialParticipant.consent_token_hash == hash_state(token),
        )
    )
    if not participant or participant.consent_status != "pending":
        raise HTTPException(status_code=400, detail="Invalid or already-used consent invitation")
    if participant.consent_expires_at and participant.consent_expires_at <= utcnow():
        raise HTTPException(status_code=400, detail="Consent invitation has expired")
    participant.consent_status = "consented"
    participant.consent_confirmed_at = utcnow()
    participant.consent_token_hash = None
    participant.consent_expires_at = None
    participant.participation_status = "active"
    participant.joined_at = utcnow()
    db.add(
        ParticipantAuditEvent(
            participant_id=participant.id,
            user_id=participant.user_id,
            action="consent_confirmed",
            details={"actor": "participant"},
        )
    )
    db.commit()
    db.refresh(participant)
    return participant


@router.post("/participants/{participant_id}/{action}", response_model=ParticipantResponse)
def participant_action(
    participant_id: int,
    action: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SocialParticipant:
    participant = db.scalar(
        select(SocialParticipant).where(
            SocialParticipant.id == participant_id,
            SocialParticipant.user_id == user.id,
        )
    )
    if not participant:
        raise HTTPException(status_code=404, detail="Participant not found")
    if action not in {"pause", "join", "withdraw", "disconnect"}:
        raise HTTPException(status_code=400, detail="Unsupported participant action")
    if action == "join":
        if participant.consent_status != "consented":
            raise HTTPException(status_code=409, detail="Explicit participant consent is required")
        participant.participation_status = "active"
        participant.joined_at = participant.joined_at or utcnow()
    elif action == "pause":
        participant.participation_status = "paused"
    else:
        participant.participation_status = "withdrawn"
        participant.withdrawn_at = utcnow()
        if action == "disconnect":
            participant.provider_connection_id = None
            participant.provider_account_id = None
            participant.connection_health = "disconnected"
    db.add(ParticipantAuditEvent(participant_id=participant.id, user_id=user.id, action=action))
    db.commit()
    db.refresh(participant)
    return participant


@router.post("/analytics/demo", response_model=list[PostMetricResponse], status_code=201)
def create_demo_analytics(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[PostMetricResponse]:
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.user_id == user.id,
            ProviderConnection.connection_mode == "demo",
        )
    )
    if not connection:
        connection = ProviderConnection(
            user_id=user.id,
            provider="meta",
            external_account_id=f"demo-meta-{secrets.token_hex(4)}",
            connection_mode="demo",
            authorization_status="authorized",
            health_status="healthy",
            status="healthy",
            scopes=["demo"],
            consent_recorded_at=utcnow(),
        )
        db.add(connection)
        db.flush()
    now = utcnow()
    values = [
        ("demo-post-1", "Strong community post", 180, 24, 2100, 4800),
        ("demo-post-2", "Product education", 90, 12, 1600, 3500),
        ("demo-post-3", "Needs a new hook", 30, 5, 1400, 3100),
    ]
    metrics = []
    for offset, (post_id, title, likes, comments, reach, impressions) in enumerate(values):
        metric = db.scalar(
            select(PostMetric).where(
                PostMetric.user_id == user.id,
                PostMetric.provider_connection_id == connection.id,
                PostMetric.external_post_id == post_id,
                PostMetric.source == "demo",
            )
        )
        if not metric:
            metric = PostMetric(
                user_id=user.id, provider_connection_id=connection.id, external_post_id=post_id,
                title=title, published_at=now - timedelta(days=offset),
                likes=likes, comments=comments, reach=reach, impressions=impressions, source="demo",
            )
            db.add(metric)
        metrics.append(metric)
    db.commit()
    for metric in metrics:
        db.refresh(metric)
    return [metric_response(metric, connection) for metric in metrics]


@router.delete("/demo-data")
def reset_demo_data(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, int]:
    demo_connections = list(
        db.scalars(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user.id,
                ProviderConnection.connection_mode == "demo",
            )
        ).all()
    )
    connection_ids = [connection.id for connection in demo_connections]
    participant_ids = list(
        db.scalars(
            select(SocialParticipant.id).where(
                SocialParticipant.user_id == user.id,
                SocialParticipant.is_demo.is_(True),
            )
        ).all()
    )
    metrics_deleted = db.query(PostMetric).filter(
        PostMetric.user_id == user.id,
        PostMetric.source == "demo",
    ).delete(synchronize_session=False)
    activity_deleted = db.query(DemoActivityEvent).filter(
        DemoActivityEvent.user_id == user.id,
        DemoActivityEvent.is_demo.is_(True),
    ).delete(synchronize_session=False)
    if participant_ids:
        db.query(ParticipantAuditEvent).filter(
            ParticipantAuditEvent.user_id == user.id,
            ParticipantAuditEvent.participant_id.in_(participant_ids),
        ).delete(synchronize_session=False)
        db.query(SocialParticipant).filter(
            SocialParticipant.user_id == user.id,
            SocialParticipant.is_demo.is_(True),
        ).delete(synchronize_session=False)
    connections_deleted = 0
    for connection in demo_connections:
        has_real_participants = db.scalar(
            select(SocialParticipant.id).where(
                SocialParticipant.provider_connection_id == connection.id,
                SocialParticipant.is_demo.is_(False),
            ).limit(1)
        )
        if not has_real_participants:
            db.delete(connection)
            connections_deleted += 1
    db.commit()
    return {
        "participants_deleted": len(participant_ids),
        "metrics_deleted": metrics_deleted,
        "activity_deleted": activity_deleted,
        "connections_deleted": connections_deleted,
    }


@router.post("/analytics/posts", response_model=PostMetricResponse, status_code=201)
def add_post_metric(
    payload: PostMetricCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> PostMetricResponse:
    connection = owned_connection(db, user.id, payload.provider_connection_id)
    metric = PostMetric(user_id=user.id, **payload.model_dump())
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return metric_response(metric, connection)


@router.get("/analytics/diagnosis", response_model=DiagnosisResponse)
def diagnosis(
    connection_id: int | None = Query(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DiagnosisResponse:
    connection = (
        owned_connection(db, user.id, connection_id)
        if connection_id
        else db.scalar(
            select(ProviderConnection)
            .where(ProviderConnection.user_id == user.id)
            .order_by(ProviderConnection.created_at.desc())
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connect an account before requesting diagnosis")
    metrics = list(
        db.scalars(
            select(PostMetric)
            .where(
                PostMetric.user_id == user.id,
                PostMetric.provider_connection_id == connection.id,
            )
            .order_by(PostMetric.published_at.asc())
        ).all()
    )
    posts = [metric_response(metric, connection) for metric in metrics]
    rates = [post.engagement_rate for post in posts if post.engagement_rate is not None]
    trend = "insufficient_data"
    findings = ["At least two posts with reach or impressions are needed for a trend."]
    recommendations = ["Connect an approved account or add available post metrics."]
    if len(rates) >= 2:
        trend = "increasing" if rates[-1] > rates[0] else "declining" if rates[-1] < rates[0] else "stable"
        findings = [f"Engagement rate is {trend} across the available posts."]
        recommendations = (
            ["Review the strongest post and repeat its content pattern."]
            if trend == "increasing"
            else ["Test a stronger opening and review posting timing."]
        )
    notes = []
    if connection.authorization_status != "authorized":
        notes.append("Provider authorization is not currently authorized.")
    if any(post.engagement_rate is None for post in posts):
        notes.append("Some posts lack reach and impressions; engagement rate is unavailable for them.")
    if not metrics:
        notes.append("No post metrics are available for this account.")
    best = sorted(posts, key=lambda post: post.engagement_rate or -1, reverse=True)[:3]

    # Calculate account-specific baseline using median and IQR
    latest_metric = metrics[-1] if metrics else None
    historical_reach_posts = [
        metric for metric in metrics
        if metric is not latest_metric and metric.reach is not None
    ]
    baseline_median_reach: int | None = None
    baseline_difference_reach: int | None = None
    baseline_difference_percentage: float | None = None
    baseline_comparable_count: int | None = None
    status: str | None = None

    if len(historical_reach_posts) >= 2:
        historical_reaches = [metric.reach for metric in historical_reach_posts]
        import statistics as stats_module
        quartiles = stats_module.quantiles(historical_reaches, n=4)
        q25 = quartiles[0]
        q75 = quartiles[2]
        iqr = q75 - q25

        if iqr == 0:
            comparable_posts = [
                metric for metric in historical_reach_posts if metric.reach == q25
            ]
        else:
            comparable_posts = [
                metric for metric in historical_reach_posts
                if q25 - 1.5 * iqr <= metric.reach <= q75 + 1.5 * iqr
            ]

        baseline_comparable_count = len(comparable_posts)

        if baseline_comparable_count >= 2:
            comparable_reaches = [metric.reach for metric in comparable_posts]
            baseline_median_reach = round(stats_module.median(comparable_reaches))

            current_reach = latest_metric.reach if latest_metric else None
            if current_reach is not None and baseline_median_reach != 0:
                baseline_difference_reach = current_reach - baseline_median_reach
                baseline_difference_percentage = round(
                    baseline_difference_reach / baseline_median_reach * 100, 2
                )
                if current_reach > baseline_median_reach:
                    status = "Above baseline"
                elif current_reach >= baseline_median_reach:
                    status = "Near baseline"
                else:
                    status = "Below baseline"

    return DiagnosisResponse(
        connection_id=connection.id,
        source="synthetic_demo" if any(metric.source == "demo" for metric in metrics) else "authorised_provider_data",
        metric_notes=notes,
        trend=trend,
        findings=findings,
        recommendations=recommendations,
        best_posts=best,
        posts=posts,
        baseline_median_reach=baseline_median_reach,
        baseline_difference_reach=baseline_difference_reach,
        baseline_difference_percentage=baseline_difference_percentage,
        baseline_comparable_count=baseline_comparable_count,
        status=status,
    )
