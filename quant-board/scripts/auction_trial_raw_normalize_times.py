# -*- coding: utf-8 -*-
"""auction_trial_raw 历史档时间格式就地修复（2026-11-14 基率探针发现）。

60 日档中 end_time/start_time 存在上游双格式中的无冒号 HHMMSS 形态（199 行，
4%）：parse 层未归一化时入库。修复 = normalize_trial_time 就地重写（幂等，
已带冒号原样），留痕 doc["timeNormalize"]；回退 = backfill --force 重拉。
零外呼（纯库内字符串重排，§4.0 时间乱序保存打标的补课）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.repositories.repository_factory import (  # noqa: E402
    get_runtime_mongodb_database,
)
from backend.operations.auction_trial_fetch import (  # noqa: E402
    COLLECTION_TRIAL_RAW, normalize_trial_time,
)


def main() -> int:
    db = get_runtime_mongodb_database()
    fixed_rows = fixed_docs = malformed = 0
    for doc in db[COLLECTION_TRIAL_RAW].find({}, {"rows": 1}):
        changed = False
        for r in (doc.get("rows") or {}).values():
            for k in ("start_time", "end_time"):
                v = r.get(k)
                if v is None or ":" in str(v):
                    continue
                nv = normalize_trial_time(v)
                if nv != v:
                    r[k] = nv
                    changed = True
                    fixed_rows += 1
                else:
                    # review finding-7：normalize 契约原样返回 = 不可判（非 5/6 位
                    # 纯数字且无冒号），fail-visible 计数，不猜不丢
                    malformed += 1
        if changed:
            db[COLLECTION_TRIAL_RAW].update_one(
                {"_id": doc["_id"]},
                {"$set": {"rows": doc["rows"], "timeNormalize.at":
                          time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "timeNormalize.reason": "HHMMSS->hh:mm:ss (2026-11-14 fix)"}},
            )
            fixed_docs += 1
    print(f"修复：{fixed_docs} 日档 / {fixed_rows} 行时间字段；不可判残留 {malformed} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
