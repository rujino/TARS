"""Comprehensive test suite for WebSocket 1-Time Ticket Authentication Pattern."""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

# Create isolated temporary sqlite database for tests before imports
temp_dir = tempfile.mkdtemp()
db_path = Path(temp_dir) / "test_ticket.db"
os.environ["TARS_DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

from starlette.testclient import TestClient  # noqa: E402

from tars.api.app import create_app  # noqa: E402
from tars.core.database import get_session_factory, init_db  # noqa: E402
from tars.core.security import (  # noqa: E402
    create_access_token,
    create_ws_ticket,
    get_password_hash,
    validate_and_consume_ws_ticket,
)
from tars.domains.auth.models import User  # noqa: E402
from tars.domains.persona.models import TARSSettings  # noqa: E402


def test_ws_ticket_crypto_and_replay_protection() -> None:
    """Test unit-level ticket generation, consumption, expiration, and replay prevention."""
    user_id = "test-user-uuid-123"

    # 1. Successful creation and single consumption
    ticket = create_ws_ticket(user_id=user_id, expires_in_seconds=30)
    assert ticket is not None
    assert isinstance(ticket, str)

    consumed_uid = validate_and_consume_ws_ticket(ticket)
    assert consumed_uid == user_id, f"Expected {user_id}, got {consumed_uid}"

    # 2. Replay attack: second consumption must fail immediately
    replay_uid = validate_and_consume_ws_ticket(ticket)
    assert replay_uid is None, "Reused ticket must return None (single-use policy)"

    # 3. Expired ticket must fail
    expired_ticket = create_ws_ticket(user_id=user_id, expires_in_seconds=-5)
    assert validate_and_consume_ws_ticket(expired_ticket) is None, "Expired ticket must return None"

    # 4. Access token (type != 'ws_ticket') must fail as ticket
    access_token = create_access_token(data={"sub": user_id})
    assert validate_and_consume_ws_ticket(access_token) is None, "Regular access token must not be accepted as ticket"


async def test_ws_ticket_e2e_flow() -> None:
    """Test full E2E flow with FastAPI app: REST ticket issuance and WebSocket connections."""
    await init_db()
    app = create_app()

    # Create test user in DB
    session_factory = get_session_factory()
    user_id = f"ticket-user-{int(datetime.now(UTC).timestamp())}"
    username = f"user_{int(datetime.now(UTC).timestamp())}"

    async with session_factory() as session:
        user = User(
            id=user_id,
            username=username,
            email=f"{username}@example.com",
            hashed_password=get_password_hash("Secret1234!"),
            is_active=True,
        )
        settings = TARSSettings(
            user_id=user_id,
            mode="attend",
        )
        session.add(user)
        session.add(settings)
        await session.commit()

    access_token = create_access_token(data={"sub": user_id})

    with TestClient(app) as client:
        # A. REST Ticket issuance endpoint
        # 1. Unauthorized request
        unauth_resp = client.post("/api/v1/auth/ws-ticket")
        assert unauth_resp.status_code == 401, f"Expected 401, got {unauth_resp.status_code}"

        # 2. Authorized request
        auth_resp = client.post(
            "/api/v1/auth/ws-ticket",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert auth_resp.status_code == 200, f"Expected 200, got {auth_resp.status_code}"
        ticket_data = auth_resp.json()
        assert "ticket" in ticket_data
        assert ticket_data["expires_in"] == 30
        issued_ticket = ticket_data["ticket"]

        # B. WebSocket Authentication with Ticket
        # 1. Connect with valid ticket -> succeeds
        with client.websocket_connect(f"/api/v1/chat/ws?ticket={issued_ticket}"):
            pass

        # 2. Reconnect with the same ticket -> rejected (4001) due to single-use consumption
        try:
            with client.websocket_connect(f"/api/v1/chat/ws?ticket={issued_ticket}"):
                raise AssertionError("Reused ticket should have been rejected with WebSocketDisconnect")
        except Exception as e:
            assert not isinstance(e, AssertionError), "Reused ticket should have been rejected by server"

        # C. WebSocket Authentication with Legacy Token (?token=...)
        with client.websocket_connect(f"/api/v1/chat/ws?token={access_token}"):
            pass

        # D. WebSocket Authentication with Native Mobile Header (Authorization: Bearer ...)
        with client.websocket_connect(
            "/api/v1/chat/ws",
            headers={"Authorization": f"Bearer {access_token}"},
        ):
            pass

        # E. WebSocket Connection with no credentials -> rejected
        try:
            with client.websocket_connect("/api/v1/chat/ws"):
                raise AssertionError("Empty credentials should have been rejected")
        except Exception as e:
            assert not isinstance(e, AssertionError), "Empty credentials should have been rejected"


if __name__ == "__main__":
    test_ws_ticket_crypto_and_replay_protection()
    print("✓ Unit crypto & replay protection tests passed!")
    asyncio.run(test_ws_ticket_e2e_flow())
    print("✓ Full E2E WebSocket ticket flow passed!")
