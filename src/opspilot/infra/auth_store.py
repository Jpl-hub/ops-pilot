from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from secrets import token_hex
from typing import Literal
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


UserRole = Literal["investor", "management", "regulator"]


class Base(DeclarativeBase):
    pass


class UserAccount(Base):
    __tablename__ = "user_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(24))
    password_hash: Mapped[str] = mapped_column(String(256))
    password_salt: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    token: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user: Mapped[UserAccount] = relationship(back_populates="sessions")


@dataclass(slots=True)
class AuthUser:
    user_id: str
    username: str
    display_name: str
    role: UserRole
    created_at: str
    last_login_at: str | None


class AuthStore:
    def __init__(self, dsn: str, *, session_days: int = 7) -> None:
        self.engine = create_engine(dsn, future=True)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, future=True)
        self.session_days = session_days

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    def register_user(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        role: UserRole,
    ) -> tuple[AuthUser, str]:
        normalized_username = username.strip().lower()
        normalized_display_name = display_name.strip()
        if not normalized_username or not normalized_display_name:
            raise ValueError("用户名和显示名不能为空。")
        salt = token_hex(16)
        password_hash = _hash_password(password, salt)
        with self.session_factory() as session:
            account = UserAccount(
                username=normalized_username,
                display_name=normalized_display_name,
                role=role,
                password_hash=password_hash,
                password_salt=salt,
            )
            session.add(account)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError("用户名已存在。") from exc
            token = self._issue_session(session, account)
            session.commit()
            return _to_auth_user(account), token

    def login(self, *, username: str, password: str) -> tuple[AuthUser, str]:
        normalized_username = username.strip().lower()
        with self.session_factory() as session:
            account = session.scalar(select(UserAccount).where(UserAccount.username == normalized_username))
            if account is None or not _verify_password(password, account.password_salt, account.password_hash):
                raise ValueError("用户名或密码错误。")
            account.last_login_at = datetime.now(UTC)
            token = self._issue_session(session, account)
            session.commit()
            return _to_auth_user(account), token

    def get_user_by_token(self, token: str) -> AuthUser | None:
        with self.session_factory() as session:
            stmt = (
                select(UserSession)
                .join(UserAccount)
                .where(UserSession.token == token)
            )
            user_session = session.scalar(stmt)
            if user_session is None:
                return None
            expires_at = user_session.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= datetime.now(UTC):
                session.delete(user_session)
                session.commit()
                return None
            return _to_auth_user(user_session.user)

    def revoke_session(self, token: str) -> None:
        with self.session_factory() as session:
            user_session = session.scalar(select(UserSession).where(UserSession.token == token))
            if user_session is None:
                return
            session.delete(user_session)
            session.commit()

    def _issue_session(self, session: Session, account: UserAccount) -> str:
        token = token_hex(32)
        expires_at = datetime.now(UTC) + timedelta(days=self.session_days)
        session.add(
            UserSession(
                token=token,
                user=account,
                expires_at=expires_at,
            )
        )
        return token


def _hash_password(password: str, salt: str) -> str:
    password_bytes = password.encode("utf-8")
    salt_bytes = salt.encode("utf-8")
    digest = pbkdf2_hmac("sha256", password_bytes, salt_bytes, 310000)
    return digest.hex()


def _verify_password(password: str, salt: str, expected_hash: str) -> bool:
    actual_hash = _hash_password(password, salt)
    return compare_digest(actual_hash, expected_hash)


def _to_auth_user(account: UserAccount) -> AuthUser:
    return AuthUser(
        user_id=account.id,
        username=account.username,
        display_name=account.display_name,
        role=account.role,  # type: ignore[return-value]
        created_at=account.created_at.isoformat(),
        last_login_at=account.last_login_at.isoformat() if account.last_login_at else None,
    )
