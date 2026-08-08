from __future__ import annotations

from sqlalchemy.orm import Session

from backend.data.models.database import ResearchSessionLocal
from backend.data.backup.supabase_backup import SupabaseBackupClient, get_backup_client
from backend.data.repositories.snapshot_repository import SnapshotRepositoryMixin
from backend.data.repositories.backtest_repository import BacktestRepositoryMixin
from backend.data.repositories.outbox_repository import OutboxRepositoryMixin
from backend.data.repositories.shared import (
    _compute_archive_source,
    _frames_from_backup_rows,
    _maybe_float,
    _maybe_int,
)


class Repository(SnapshotRepositoryMixin, BacktestRepositoryMixin, OutboxRepositoryMixin):
    def __init__(
        self,
        session: Session | None,
        backup_client: SupabaseBackupClient | None = None,
        *,
        enable_backup: bool = True,
    ):
        self.session = session
        self.enable_backup = enable_backup
        self.backup = None if not enable_backup else (backup_client if backup_client is not None else get_backup_client())
        self._research_session: Session | None = None

    @property
    def research_session(self) -> Session:
        if self._research_session is None:
            self._research_session = ResearchSessionLocal()
        return self._research_session

    def close(self) -> None:
        if self._research_session is not None:
            self._research_session.close()
            self._research_session = None
