from __future__ import annotations

from backend.data.supabase_homomorphic import REQUIRED_TABLES, SupabaseBackupClient


def get_backup_client() -> SupabaseBackupClient | None:
    return SupabaseBackupClient.from_settings()


__all__ = ["REQUIRED_TABLES", "SupabaseBackupClient", "get_backup_client"]
