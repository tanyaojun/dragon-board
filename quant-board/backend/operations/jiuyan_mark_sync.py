"""韭研板块名 → 通达信 mark.dat 每日同步（merge，字体黄）。

数据源：MongoDB `jiuyan_action` final 文档（`_id="<date>:final"`），由 8001 采集器
每个交易日盘后自动落库（设计见 docs/hotlist-jev/jiuyan-collector-design.md）。
  fields[].name    = 板块名称（写入 [TIP]/[TIPWORD]）
  fields[].stocks  = 成分股，code 形如 "sz000504"/"sh601318"

目标：通达信 mark.dat（默认 D:\\APP_SOFT\\TDX\\T0002\\mark.dat），5 段 GBK：
  [MARK] 代码=标记色 | [TIP] 代码=板块名 | [TIPWORD] 代码=板块名
  [TIPCOLOR] 代码=文字色(RGB整数) | [TIME] 代码=YYYYMMDD
代码 8 位：2 位市场(00 深/01 沪/02 北) + 6 位证券代码。

安全（对齐 AGENTS.md fail-visible / 单一事实源）：
  * 默认 dry-run，--apply 才落盘；落盘前备份 *.bak-<时间戳>。
  * final 缺失/无成分 → 中止，绝不写空或半成品（不清除既有标记）。
  * 坏代码跳过并告警，仍写其余；往返序列化与源文件字节一致，只改目标条目。
  * 读库走 get_runtime_mongodb_database()（pytest 库护栏在内），禁真调用由测试 mock。

用法：
  python -m backend.operations.jiuyan_mark_sync                 # dry-run，取最新 final
  python -m backend.operations.jiuyan_mark_sync --date 2026-10-15
  python -m backend.operations.jiuyan_mark_sync --apply         # 落盘(先备份)
  python -m backend.operations.jiuyan_mark_sync --dump-sections # 看当前各段条数
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DEFAULT_MARK = r"D:\APP_SOFT\TDX\T0002\mark.dat"
SECTION_ORDER = ["MARK", "TIP", "TIPWORD", "TIPCOLOR", "TIME"]


# ---------- mark.dat 解析 / 序列化（往返字节一致） ----------
def parse_mark(text: str) -> tuple[dict[str, dict], list[str]]:
    sections: dict[str, dict] = {s: {} for s in SECTION_ORDER}
    order: list[str] = []
    cur = None
    for raw in text.split("\r\n"):
        m = re.fullmatch(r"\[([A-Z]+)\]", raw)
        if m:
            cur = m.group(1)
            sections.setdefault(cur, {})
            if cur not in order:
                order.append(cur)
            continue
        if cur is None or raw == "":
            continue
        if "=" in raw:
            code, val = raw.split("=", 1)
            sections[cur][code] = val
        else:  # 非 code=value 的非空行：保留，避免静默丢弃
            sections[cur].setdefault("__RAW__", []).append(raw)
    return sections, (order or SECTION_ORDER)


def serialize_mark(sections: dict[str, dict], order: list[str]) -> str:
    out: list[str] = []
    for sec in order:
        out.append("[%s]\r\n" % sec)
        table = sections.get(sec, {})
        raws = table.pop("__RAW__", None)
        for code, val in table.items():
            out.append("%s=%s\r\n" % (code, val))
        if raws:
            out.extend("%s\r\n" % r for r in raws)
            table["__RAW__"] = raws
    return "".join(out)


# ---------- 代码规范化：sz000504/shd/6/7/8 位 → 8 位(2 市场+6 代码) ----------
_MARKET_PREFIX = {"sz": "00", "sh": "01", "bj": "02"}


def normalize_code(code) -> str | None:
    c = str(code or "").strip().lower()
    prefix = ""
    m = re.match(r"^(sz|sh|bj)", c)
    if m:
        prefix = _MARKET_PREFIX[m.group(1)]
        c = c[m.end():]
    digits = re.sub(r"\D", "", c)
    if prefix:
        return (prefix + digits)[-8:].rjust(8, "0") if len(digits) == 6 else None
    if len(digits) == 8:
        return digits
    if len(digits) == 7:  # 1 位市场 + 6 位
        return "0" + digits
    if len(digits) == 6:
        if digits[:2] in ("60", "68", "90", "91"):
            return "01" + digits
        if digits[0] in ("4", "8") or digits[:3] == "920":
            return "02" + digits
        if digits[:2] in ("00", "30", "15", "16", "12", "20", "39"):
            return "00" + digits
        return None
    return None


# ---------- 韭研文档 → {code8: [板块名,...]} ----------
def boards_from_doc(doc: dict | None, warnings: list[str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    if not doc:
        return mapping
    for field in doc.get("fields") or []:
        name = str(field.get("name") or "").strip()
        stocks = field.get("stocks") or []
        if not name:
            warnings.append("存在无名称板块，已跳过(count=%s)" % field.get("count"))
            continue
        for s in stocks:
            raw_code = s.get("code")
            c8 = normalize_code(raw_code)
            if not c8:
                warnings.append("板块[%s] 代码无法识别: %r" % (name, raw_code))
                continue
            mapping.setdefault(c8, [])
            if name not in mapping[c8]:
                mapping[c8].append(name)
    return mapping


def latest_final_date(db) -> str | None:
    doc = db["jiuyan_action"].find_one(
        {"kind": "jiuyan_action", "updateKind": "final"},
        sort=[("tradingDate", -1)])
    return str(doc["tradingDate"]) if doc and doc.get("tradingDate") else None


# ---------- 合并（merge：只动韭研股，保留其余） ----------
def apply_merge(sections: dict[str, dict], mapping: dict[str, list[str]],
                mark_color: str, tip_color: str, time_val: str) -> dict:
    stats = {"stocks": len(mapping), "new_mark": 0, "set_tip": 0,
             "set_color": 0, "set_time": 0}
    for code, names in mapping.items():
        tip = "/".join(names)
        if code not in sections["MARK"]:
            stats["new_mark"] += 1
        sections["MARK"][code] = str(mark_color)
        if sections["TIP"].get(code) != tip:
            stats["set_tip"] += 1
        sections["TIP"][code] = tip
        sections["TIPWORD"][code] = tip
        if sections["TIPCOLOR"].get(code) != str(tip_color):
            stats["set_color"] += 1
        sections["TIPCOLOR"][code] = str(tip_color)
        if sections["TIME"].get(code) != time_val:
            stats["set_time"] += 1
        sections["TIME"][code] = time_val
    return stats


# ---------- 文件 IO ----------
def read_mark(path: str) -> str:
    with open(path, "rb") as f:
        return f.read().decode("gbk", errors="replace")


def write_mark(path: str, text: str) -> None:
    try:
        raw = text.encode("gbk")
    except UnicodeEncodeError as e:  # fail-visible：非 GBK 字符替换并告警
        sys.stderr.write("[告警] 非 GBK 字符已用 ? 替换: %s\n" % e)
        raw = text.encode("gbk", errors="replace")
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def backup_mark(path: str) -> str:
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = "%s.bak-%s" % (path, ts)
    with open(path, "rb") as r, open(dst, "wb") as w:
        w.write(r.read())
    return dst


# ---------- 编排 ----------
def sync(db, *, date: str | None, mark_path: str, mark_color: str,
         tip_color: str, apply: bool, backup: bool) -> dict:
    if not os.path.isfile(mark_path):
        return {"ok": False, "error": "mark.dat 不存在: %s" % mark_path}

    resolved = date or latest_final_date(db)
    if not resolved:
        return {"ok": False, "error": "未找到任何 jiuyan_action final 文档"}

    doc = db["jiuyan_action"].find_one({"_id": f"{resolved}:final"})
    warnings: list[str] = []
    mapping = boards_from_doc(doc, warnings)
    if not mapping:
        return {"ok": False, "error": "final[%s] 无有效成分股，按 fail-visible 不写入" % resolved,
                "warnings": warnings}

    time_val = resolved.replace("-", "")  # YYYYMMDD
    text = read_mark(mark_path)
    sections, order = parse_mark(text)
    before = {s: len([k for k in sections.get(s, {}) if k != "__RAW__"]) for s in order}
    stats = apply_merge(sections, mapping, mark_color, tip_color, time_val)
    new_text = serialize_mark(sections, order)
    new_raw = new_text.encode("gbk", errors="replace")
    after = {s: len([k for k in sections.get(s, {}) if k != "__RAW__"]) for s in order}

    report = {"ok": True, "date": resolved, "apply": apply, "warnings": warnings,
              "stats": stats, "bytes": len(new_raw),
              "sections_before": before, "sections_after": after,
              "backup": None, "written": False}

    if not apply:
        return report

    if backup:
        report["backup"] = backup_mark(mark_path)
    write_mark(mark_path, new_text)
    report["written"] = True
    return report


def maybe_sync_after_collect(db, date: str, kind: str) -> dict:
    """韭研 final 入库后自动同步 mark.dat（采集进程 after-collect 钩子，单一触发点）。

    仅 kind=="final" 触发；pytest 进程跳过（禁真写）；未启用或 mark 文件缺失则跳过；
    任何异常只记录不外抛，绝不影响采集主链（fail-visible）。
    """
    log = logging.getLogger(__name__)
    if kind != "final":
        return {"skipped": "not_final"}
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"skipped": "pytest"}
    from backend.core.settings import get_settings
    s = get_settings()
    if not s.jiuyan_mark_sync_enabled:
        return {"skipped": "disabled"}
    path = s.jiuyan_mark_path
    if not path or not os.path.isfile(path):
        log.debug("jiuyan mark sync 跳过：mark.dat 不存在 %s", path)
        return {"skipped": "mark_missing", "path": path}
    try:
        r = sync(db, date=date, mark_path=path,
                 mark_color=s.jiuyan_mark_mark_color,
                 tip_color=s.jiuyan_mark_tip_color, apply=True, backup=True)
    except Exception as exc:  # 双保险：钩子异常绝不波及采集主链
        log.exception("jiuyan mark sync 失败")
        return {"ok": False, "error": str(exc)}
    if r.get("ok"):
        log.info("jiuyan mark sync ok date=%s stocks=%s bytes=%s sections=%s backup=%s",
                 r.get("date"), r["stats"]["stocks"], r.get("bytes"),
                 r.get("sections_after"), r.get("backup"))
    else:
        log.warning("jiuyan mark sync 中止：%s", r.get("error"))
    return r


def _print_report(r: dict) -> None:
    if not r.get("ok"):
        sys.stderr.write("[中止] %s\n" % r.get("error"))
        for w in (r.get("warnings") or [])[:50]:
            sys.stderr.write("  ! %s\n" % w)
        return
    st = r["stats"]
    print("=== 韭研 → mark.dat (date=%s, apply=%s) ===" % (r["date"], r["apply"]))
    print("韭研个股: %d | 新增标记: %d | 置TIP板块名: %d | 置TIPCOLOR: %d | 置TIME: %d"
          % (st["stocks"], st["new_mark"], st["set_tip"], st["set_color"], st["set_time"]))
    print("字节: %d" % r["bytes"])
    for s in r["sections_after"]:
        print("  [%-8s] %d -> %d" % (s, r["sections_before"].get(s, 0), r["sections_after"][s]))
    for w in (r.get("warnings") or [])[:50]:
        print("  ! " + w)
    if r["backup"]:
        print("[备份] %s" % r["backup"])
    if r["written"]:
        print("[完成] 已写入")
    else:
        print("[dry-run] 未写入，加 --apply 才落盘")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="韭研板块名写入通达信 mark.dat（merge）")
    ap.add_argument("--date", default=None, help="数据日期 YYYY-MM-DD（默认取最新 final）")
    ap.add_argument("--mark", default=DEFAULT_MARK, help="mark.dat 路径")
    ap.add_argument("--mark-color", default="7", help="[MARK] 标记色（默认 7）")
    ap.add_argument("--tip-color", default="65535", help="[TIPCOLOR] 文字色（默认 65535 黄）")
    ap.add_argument("--apply", action="store_true", help="真正落盘（默认 dry-run）")
    ap.add_argument("--no-backup", action="store_true", help="落盘不备份（不推荐）")
    ap.add_argument("--dump-sections", action="store_true", help="只打印当前各段条数后退出")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.mark):
        sys.stderr.write("[错误] mark.dat 不存在: %s\n" % args.mark)
        return 2

    if args.dump_sections:
        text = read_mark(args.mark)
        sections, order = parse_mark(text)
        print("mark.dat: %s (%d bytes)" % (args.mark, len(text.encode("gbk", "replace"))))
        for s in order:
            print("  [%-8s] %d 条" % (s, len([k for k in sections.get(s, {}) if k != "__RAW__"])))
        return 0

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    r = sync(db, date=args.date, mark_path=args.mark, mark_color=args.mark_color,
             tip_color=args.tip_color, apply=args.apply, backup=not args.no_backup)
    _print_report(r)
    return 0 if r.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
