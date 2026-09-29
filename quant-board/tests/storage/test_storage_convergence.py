from __future__ import annotations

import json
import sys
from pathlib import Path


from backend.data.ingest.importers import LevelDbIndexedDbImporter
from backend.data.ingest.json_codec import COMPRESSED_TEXT_PREFIX, dumps_json_field, loads_json_field
from backend.core.settings import Settings


def test_json_codec_compresses_large_json_and_reads_plain_or_broken_text() -> None:
    small = {"ok": True}
    assert not dumps_json_field(small).startswith(COMPRESSED_TEXT_PREFIX)
    assert loads_json_field(json.dumps(small), {}) == small

    large = {"items": [{"code": f"{index:06d}", "name": "样本" * 10} for index in range(300)]}
    encoded = dumps_json_field(large)
    assert encoded.startswith(COMPRESSED_TEXT_PREFIX)
    assert len(encoded) < len(json.dumps(large, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    assert loads_json_field(encoded, {}) == large

    broken = f"{COMPRESSED_TEXT_PREFIX}not-base64"
    assert loads_json_field(broken, {"fallback": True}) == {"fallback": True}





def test_leveldb_importer_parses_dfindexeddb_jsonl_projection_stores() -> None:
    snapshot_id = "half_hour:2026-04-30:10:00"

    stdout = "\n".join(
        [
            _dfindexeddb_record(
                5,
                {
                    "id": snapshot_id,
                    "snapshotId": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-04-30",
                    "slotTime": "10:00",
                    "timestamp": 1777524000000,
                    "displayKey": snapshot_id,
                    "stockRowCount": 1,
                    "sectorRowCount": 1,
                },
            ),
            _dfindexeddb_record(
                6,
                {
                    "id": f"{snapshot_id}:600001",
                    "snapshotId": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-04-30",
                    "slotTime": "10:00",
                    "timestamp": 1777524000000,
                    "code": "600001",
                    "name": "sample",
                    "rank": 1,
                    "themeHeat": {"__type__": "Undefined"},
                    "themes": {
                        "__type__": "JSArray",
                        "values": [{"__type__": "Undefined"}],
                        "properties": {"0": "AI"},
                    },
                },
            ),
            _dfindexeddb_record(
                7,
                {
                    "id": f"{snapshot_id}:hot_theme:AI",
                    "snapshotId": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-04-30",
                    "slotTime": "10:00",
                    "timestamp": 1777524000000,
                    "entityType": "hot_theme",
                    "entityKey": "AI",
                    "entityName": "AI",
                    "rank": 1,
                    "metadata": {"__type__": "Null"},
                },
            ),
            _dfindexeddb_record(
                5,
                {
                    "snapshotId": "index-row",
                    "type": 1,
                    "tradingDate": "2026-04-30",
                    "timestamp": 1777524000000,
                },
            ),
        ]
    )

    bundle = LevelDbIndexedDbImporter()._parse_dfindexeddb_output(stdout)

    assert len(bundle.records) == 1
    assert len(bundle.frames) == 1
    assert len(bundle.stock_rows) == 1
    assert len(bundle.sector_rows) == 1
    assert bundle.records[0]["id"] == snapshot_id
    assert bundle.frames[0]["snapshotId"] == snapshot_id
    assert bundle.stock_rows[0]["code"] == "600001"
    assert bundle.stock_rows[0]["themeHeat"] is None
    assert bundle.stock_rows[0]["themes"] == ["AI"]
    assert bundle.sector_rows[0]["entityKey"] == "AI"
    assert bundle.sector_rows[0]["metadata"] is None


def test_leveldb_importer_uses_venv_dfindexeddb_console_script(tmp_path: Path, monkeypatch) -> None:
    script_dir = tmp_path / "Scripts"
    script_dir.mkdir()
    executable = script_dir / "python.exe"
    executable.write_text("", encoding="utf-8")
    (script_dir / "dfindexeddb.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(executable))

    command = LevelDbIndexedDbImporter._dfindexeddb_command(Path("source.leveldb"))

    assert Path(command[0]) == script_dir / "dfindexeddb.exe"
    assert command[1:] == [
        "db",
        "-s",
        "source.leveldb",
        "--format",
        "chrome",
        "--output",
        "jsonl",
        "--use_sequence_number",
        "--load_blobs",
    ]


def test_settings_ignore_legacy_quant_board_database_url(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_BOARD_DATABASE_URL", "sqlite:///data/warehouse/quant_board.db")
    monkeypatch.delenv("QUANT_BOARD_SNAPSHOT_DATABASE_URL", raising=False)
    settings = Settings()
    # 2026-09-29 sqlite 链退役：legacy quant_board.db 被忽略，且未 opt-in 时不回落 warehouse 默认 .db（留空）
    assert settings.snapshot_database_url == ""


def _dfindexeddb_record(object_store_id: int, value: dict) -> str:
    return json.dumps(
        {
            "__type__": "ChromiumIndexedDBRecord",
            "object_store_id": object_store_id,
            "value": {"__type__": "ObjectStoreDataValue", "value": value},
        }
    )


def test_hot_theme_projection_whitelist_includes_heat_level() -> None:
    """hotThemes 读侧投影白名单必须放行 heatLevel 与 metadata（口径标记）。"""
    from backend.data.repositories.mongo_repository import HOT_THEME_FRAME_FIELDS

    assert HOT_THEME_FRAME_FIELDS["heatLevel"] == 1
    assert HOT_THEME_FRAME_FIELDS["heatScore"] == 1
    assert HOT_THEME_FRAME_FIELDS["metadata"] == 1


# ── heatLevel 落库迁移（2026-09 design）：heat_level varchar 列数值写入统一转文本 ──

