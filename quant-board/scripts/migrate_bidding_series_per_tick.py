# -*- coding: utf-8 -*-
"""kpl_bidding_series 旧嵌入形态 → 逐 tick 文档化迁移（2026-11-19，红线 1/4）。

方案唯一来源：docs/hotlist-jev/auction-trial-density-storage-fix-plan-20261119.md §2。
旧形态=单日单文档嵌入 ticks（16MB BSON 饱和，11-19 午后 bid_series_fail=749）；
新形态=日 meta（_id=date，不含 ticks）+ 逐 tick 文档（{date, ts, n, it}，索引
{date:1, ts:1}）。消费合同经 load_bidding_series 同形，迁移有界。

纪律：
- 归档先行（红线 4）：逐档 mongoexport 到 data/backups/（gitignore），失败即停该档；
- 逐档显式操作、幂等可重跑：重跑先清该日已迁 tick 文档（归档已在，单集合显式
  delete_many，非批量文件删除），再全量重插，最后 $unset ticks + $set tick_n；
- 计数核对：tick 文档数 == 旧 ticks 长度 == meta.tick_n，任一不符该档记失败；
- meta 加字段（prev_pct/open_pct/*_state）零触碰（$unset 只删 ticks）；
- 单写者=collector：生产库迁移前必须停 :8002（预检探测，--force 显式绕过留痕）；
- 先在 dragon_board_test 干跑/实跑验证，再生产（--database 显式指定）。

用法：
  .venv python -m scripts.migrate_bidding_series_per_tick --database dragon_board_test --dry-run
  .venv python -m scripts.migrate_bidding_series_per_tick --database dragon_board_test
  .venv python -m scripts.migrate_bidding_series_per_tick            # 生产（:8002 已停）
回退 = mongoimport data/backups/ 归档重导入（git + 归档双保险）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COLLECTION = "kpl_bidding_series"


def _collector_alive() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8002/api/kpl/status", timeout=3) as r:
            return bool(json.loads(r.read().decode("utf-8")).get("ok"))
    except Exception:  # noqa: BLE001 — 探测失败视为不在位（迁移预检只拦活写者）
        return False


def _count_lines(p: Path) -> int:
    with open(p, "r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _export_legacy(tools_bin: Path, uri: str, database: str, date: str,
                   out_dir: Path, *, expect_lines: int) -> Path:
    """mongoexport 单档归档（红线 4：备份只走 mongoexport/mongodump）。

    完整性（2026-11-19 review S2）：已存在归档必须行数==expect_lines 才可复用
    （否则删除重导，防上一轮失败残留被误当完整回退保险）；本轮导出失败也删
    残留，不留给下一轮。"""
    out = out_dir / f"kpl_bidding_series_legacy_{database}_{date}.json"
    if out.exists():
        if _count_lines(out) == expect_lines:
            return out   # 幂等重跑：首次完整归档已在，不覆盖
        out.unlink()   # 残留/不完整归档不复用
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(tools_bin / "mongoexport.exe"), "--uri", uri, "--db", database,
           "--collection", COLLECTION,
           "--query", json.dumps({"_id": date}),
           "--out", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not out.exists():
        if out.exists():
            out.unlink()   # 失败残留不进下一轮幂等复用
            # （部分文件 ≠ 完整归档，否则重跑会把唯一完整副本改写掉，红线 4）
        raise RuntimeError(f"mongoexport failed rc={r.returncode}: {r.stderr.strip()[:300]}")
    n = _count_lines(out)
    if n != expect_lines:
        out.unlink()
        raise RuntimeError(f"mongoexport incomplete: lines={n} expect={expect_lines}")
    return out


def migrate_one(db, tools_bin: Path, uri: str, database: str, doc: dict,
                out_dir: Path, *, dry_run: bool = False) -> dict:
    date = doc["_id"]
    ticks = doc.get("ticks") or []
    rep: dict = {"date": date, "legacy_ticks": len(ticks)}
    if dry_run:
        rep["state"] = "dry_run"
        return rep
    col = db[COLLECTION]
    try:
        archive = _export_legacy(tools_bin, uri, database, date, out_dir,
                                 expect_lines=len(ticks))
        rep["archive"] = str(archive)
        # 归档完整性校验（2026-11-19 review S2，红线 4）：导出行数必须等于
        # 嵌入 ticks 数，否则该档记失败、绝不改写唯一完整副本（_export_legacy
        # 已自检，此处对替身/异路径二次防守）
        with open(archive, "r", encoding="utf-8") as fh:
            n_export = sum(1 for line in fh if line.strip())
        if n_export != len(ticks):
            rep["state"] = "failed"
            rep["error"] = (f"archive_line_mismatch: export={n_export} "
                            f"legacy_ticks={len(ticks)}")
            return rep
        # 幂等：清该日已迁 tick 文档（部分失败重跑不产生重复；归档先行已在）
        cleared = col.delete_many({"date": date, "it": {"$exists": True}}).deleted_count
        rep["cleared_partial"] = cleared
        new_docs = [{"date": date, "ts": t.get("ts"),
                     "n": t.get("n") if t.get("n") is not None else len(t.get("it") or []),
                     "it": t.get("it") or []} for t in ticks]
        if new_docs:
            col.insert_many(new_docs)
        col.update_one({"_id": date},
                       {"$unset": {"ticks": ""}, "$set": {"tick_n": len(ticks)}})
        n_docs = col.count_documents({"date": date, "it": {"$exists": True}})
        meta = col.find_one({"_id": date}) or {}
        rep["tick_docs"] = n_docs
        rep["meta_tick_n"] = meta.get("tick_n")
        if n_docs != len(ticks) or meta.get("tick_n") != len(ticks) or "ticks" in meta:
            rep["state"] = "count_mismatch"
        else:
            rep["state"] = "ok"
    except Exception as exc:  # noqa: BLE001 — 逐档隔离，一日失败不中断整轮
        rep["state"] = f"failed:{type(exc).__name__}"
        rep["error"] = str(exc)[:300]
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", default=None, help="目标库（默认生产 settings；干跑用 dragon_board_test）")
    ap.add_argument("--uri", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dates", nargs="*", default=None)
    ap.add_argument("--force", action="store_true",
                    help="生产库且 :8002 在位时显式绕过预检（单写者竞态自负，留痕）")
    args = ap.parse_args()

    from backend.core.settings import get_settings
    s = get_settings()
    database = args.database or s.mongodb_database
    uri = args.uri or s.mongodb_uri
    tools_bin = Path(s.mongodb_tools_bin)

    if database == "dragon_board_quant" and _collector_alive() and not args.force:
        print("❌ 预检：:8002 collector 在位（单写者=collector）。先停 :8002 再迁移；"
              "确需带写者迁移用 --force（竞态自负）。")
        return 2

    from pymongo import MongoClient
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client[database]
    col = db[COLLECTION]
    q: dict = {"ticks": {"$exists": True}}
    if args.dates:
        q["_id"] = {"$in": args.dates}
    legacy = list(col.find(q))
    print(f"=== kpl_bidding_series 迁移 database={database} dry_run={args.dry_run} "
          f"legacy_docs={len(legacy)} ===")
    if not args.dry_run:
        col.create_index([("date", 1), ("ts", 1)])
    out_dir = Path(__file__).resolve().parents[1] / "data" / "backups"
    reports = []
    for doc in sorted(legacy, key=lambda d: d["_id"]):
        rep = migrate_one(db, tools_bin, uri, database, doc, out_dir,
                          dry_run=args.dry_run)
        reports.append(rep)
        print(json.dumps(rep, ensure_ascii=False))
    bad = [r for r in reports if r["state"] not in ("ok", "dry_run")]
    already = col.count_documents({"it": {"$exists": True}})
    metas = col.count_documents({"it": {"$exists": False}})
    print(f"=== 汇总：ok={sum(r['state'] == 'ok' for r in reports)} "
          f"dry_run={sum(r['state'] == 'dry_run' for r in reports)} failed={len(bad)} "
          f"tick_docs_total={already} meta_docs={metas} ===")
    if bad:
        print("失败档可幂等重跑（归档已在，清部分重插）；回退=mongoimport 归档。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
