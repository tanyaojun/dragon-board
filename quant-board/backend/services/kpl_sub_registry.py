# -*- coding: utf-8 -*-
"""KPL 订阅注册表（2026-11-17 P0/P1，App qn0 PackManager 注册表语义同款）。

RE 合同唯一来源：docs/kpl-socket/sub-registry-refactor-plan.md §1.2/§3.1。
App 模型（.tmp_review main_src/c2_src qn0.java 逐字对照）：
- c=已发待 ack（按 seq 匹配回复）；e=已订阅注册表（**权威 key=ack 帧 attr2
  服务端分配 subId**，topic=ack attr3 原始字节）；推送按 topic 路由（非按 cmd）；
- 220 ResubNt：topics 空→全量重发、非空→按 topic 选择性重发，重发项移出注册表
  待再 ack（qn0.j）；断线清空 c/d/e（qn0.f）；
- 402/pkg 0x50 UnsubIdReq 退订，kind5 ack 按 subIds 移除（qn0.q）；
- 211 SubReqs 批 ack 逐项展开（seq=item.seqId、attr2=item.subId 预置待回复，
  qn0.o）——请求侧语义未验证（探针 U1-U8），本模块只做结构跟踪。

与 App 的有意差异（fail-visible 不静默）：
- subId 冲突不原位合并（App s() 合并）：本注册表同时承担 220 重发原料库，
  per-stock 同 cmd 订阅必须逐条保留 req；冲突只计数观测。
- 未匹配 ack 不丢弃静默：orphan 计数进 stats。

本模块纯逻辑、无 I/O、无网络——pytest 全 mock（红线 README §六）。
线程合同：状态变更（register/on_ack/on_resub/unsub 等）仅采集线程调用，无锁；
stats() 供 FastAPI 线程跨线程读，为**尽力快照**（GIL 下列表迭代+预初始化计数键
无崩溃风险，可能读到撕裂中间态，仅作观测不作判据——review m7）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

STATE_PENDING = "pending"        # 已发待 ack（App c/d）
STATE_ACKED = "acked"            # 订阅成功（App e）
STATE_STALE = "stale"            # 220 失效移出，待重发再 ack（App j 移出 e）
STATE_UNSUB_SENT = "unsub_sent"  # 402 已发待退订 ack
STATE_UNSUBSCRIBED = "unsubscribed"  # 退订 ack 确认（终态，等待清理）


@dataclass
class SubEntry:
    cmd: int
    req: bytes                  # 内层 req pb 原料（220 重发/批量复用，单一事实源）
    ext: bytes                  # 外层 ext 路由头（02 <cmd 2BE>）
    seq: int                    # 发送帧 seq（direct）或 item.seqId（211 批内项）
    lane: str = "setup"         # setup|zt_reason|theme|detail:<lane>|dynamic
    key: str = ""               # 业务 key（stock_id/页标识），退订 diff 用
    priority: bool = False      # setup pid=8 前插标志（220 重发保序）
    sub_id_hint: int = 0        # 客户端 hint（App 观测口径=cmd）
    sub_id: Optional[int] = None   # ack attr2 回填（服务端分配，权威 key）
    topic: Optional[bytes] = None  # ack attr3 原始字节（推送/220 匹配 key）
    state: str = STATE_PENDING
    batch_seq: Optional[int] = None  # 所属 211 批帧 seq（None=单帧）
    sent_at: float = 0.0
    ack_at: float = 0.0
    resub_n: int = 0


class SubRegistry:
    """订阅注册表（会话级生命周期：clear_session=App qn0.f 断线清空同款）。"""

    def __init__(self, max_entries: int = 2000):
        self._max_entries = max(100, int(max_entries))
        self._entries: List[SubEntry] = []
        # 211 批帧跟踪：batch_seq → {sent_at, acked, n_items}（熔断超时判定用）
        self._batches: Dict[int, Dict[str, Any]] = {}
        self._counters: Dict[str, int] = {
            "orphan_ack_n": 0,        # seq 无匹配的订阅 ack（fail-visible）
            "ext_parse_err_n": 0,     # ack ext 属性解析失败
            "sub_id_collision_n": 0,  # 服务端 subId 重复（不合并，只计数）
            "push_topic_hit_n": 0,    # 推送 topic 命中注册表（观测，不改路由）
            "push_topic_miss_n": 0,
            "resub_selective_n": 0,   # 220 选择性重发条目累计
            "resub_fallback_n": 0,    # 220 topic 无匹配降级全量次数
            "evicted_n": 0,           # 超上限淘汰（终态优先）
            "unsub_ack_removed_n": 0,
            "batch_item_no_topic_n": 0,  # 批内项 ack 无 attr3（2026-11-17 实弹：与 110/2000
                                         # 拒绝通知同时出现，疑似被拒项观测位）
            "sub_id_shared_skip_n": 0,   # M3：subId 被多条活跃条目共享→跳过退订（防误退整族）
        }

    # ---- 发送登记 ----

    def register(self, entry: SubEntry) -> SubEntry:
        """已发订阅登记（drain/inline 发送成功后调用）。超上限先淘汰终态条目，
        仍超限淘汰最旧 pending（fail-visible 计数，不静默丢）。"""
        if len(self._entries) >= self._max_entries:
            terminal = [e for e in self._entries
                        if e.state in (STATE_STALE, STATE_UNSUBSCRIBED)]
            if terminal:
                self._entries.remove(terminal[0])
                self._counters["evicted_n"] += 1
            else:
                self._entries.pop(0)
                self._counters["evicted_n"] += 1
        if not entry.sub_id_hint:
            entry.sub_id_hint = entry.cmd
        self._entries.append(entry)
        return entry

    def track_batch(self, batch_seq: int, n_items: int, now: float) -> None:
        """211 批帧发送登记（熔断超时判定原料）。"""
        self._batches[batch_seq] = {"sent_at": now, "acked": False, "n_items": n_items}

    def bind_batch(self, batch_seq: int, entries: List[SubEntry]) -> None:
        for e in entries:
            e.batch_seq = batch_seq

    # ---- ack 处理 ----

    def has_pending_seq(self, seq: int) -> bool:
        return any(e.seq == seq and e.state == STATE_PENDING for e in self._entries)

    def on_ack(self, seq: int, *, sub_id: Optional[int] = None,
               topic: Optional[bytes] = None,
               sub_reqs: Optional[List[Dict[str, Any]]] = None,
               now: float = 0.0) -> Dict[str, Any]:
        """订阅 ack 入口（App qn0.o 同款语义）。

        - sub_reqs 非 None = 211 批 ack：逐项按 item.seqId 更新预登记项的
          sub_id（服务端分配值），批帧标记 acked；未预登记的项计 orphan。
        - 普通 ack：按 seq 匹配 pending 项 → acked + sub_id/topic 回填。
        - 无匹配：orphan 计数（fail-visible）。
        返回结构化结果供 collector 发事件。"""
        if sub_reqs is not None:
            batch = self._batches.get(seq)
            if batch is not None:
                batch["acked"] = True
            matched, orphan = 0, 0
            for it in sub_reqs:
                iseq = int(it.get("seqId", 0))
                entry = next((e for e in self._entries
                              if e.seq == iseq and e.state == STATE_PENDING), None)
                if entry is None:
                    orphan += 1
                    self._counters["orphan_ack_n"] += 1
                    continue
                entry.sub_id = int(it.get("subId", 0)) or entry.sub_id
                matched += 1
            return {"kind": "batch", "seq": seq, "expanded": len(sub_reqs),
                    "matched": matched, "orphan": orphan,
                    "batch_known": batch is not None}
        entry = next((e for e in self._entries
                      if e.seq == seq and e.state == STATE_PENDING), None)
        if entry is None:
            self._counters["orphan_ack_n"] += 1
            return {"kind": "orphan", "seq": seq}
        if sub_id is not None:
            if any(e.sub_id == sub_id and e is not entry
                   for e in self._entries if e.state == STATE_ACKED):
                self._counters["sub_id_collision_n"] += 1
            entry.sub_id = sub_id
        if topic is not None:
            entry.topic = topic
        elif entry.batch_seq is not None:
            # 批内项 ack 无 topic：实弹观察与 110/2000 拒绝通知一一对应（2103/2203/2013
            # 在批内被拒）；只计数不改 state（ack 确实到达，语义待后续探针钉死）
            self._counters["batch_item_no_topic_n"] += 1
        entry.state = STATE_ACKED
        entry.ack_at = now
        return {"kind": "ack", "seq": seq, "cmd": entry.cmd, "lane": entry.lane,
                "sub_id": entry.sub_id, "topic": entry.topic}

    def mark_ext_parse_error(self) -> None:
        self._counters["ext_parse_err_n"] += 1

    # ---- 推送路由观测（P1 只记录，dispatch 仍按 cmd）----

    def on_push_topic(self, ext_raw: bytes) -> Optional[SubEntry]:
        hit = next((e for e in self._entries
                    if e.state == STATE_ACKED and e.topic is not None
                    and e.topic == ext_raw), None)
        if hit is not None:
            self._counters["push_topic_hit_n"] += 1
        else:
            self._counters["push_topic_miss_n"] += 1
        return hit

    # ---- 220 ResubNt（App qn0.j）----

    def on_resub(self, topics: List[Any]) -> Tuple[List[SubEntry], str]:
        """返回 (待重发条目, mode)。topics 空→全量；非空→topic 精确匹配；
        匹配不到任何条目→降级全量（mode=fallback_all，fail-visible 计数）。
        返回条目置 stale（移出活跃注册表，App j 同款；重发后重新 register）。"""
        candidates = [e for e in self._entries if e.state == STATE_ACKED]
        if not candidates:
            return [], "empty"
        norm: List[bytes] = []
        for t in topics or []:
            if isinstance(t, str):
                norm.append(t.encode("utf-8"))
            elif isinstance(t, (bytes, bytearray)):
                norm.append(bytes(t))
        if not norm:
            picked, mode = list(candidates), "all"
        else:
            tset = set(norm)
            picked = [e for e in candidates if e.topic is not None and e.topic in tset]
            if picked:
                mode = "selective"
                self._counters["resub_selective_n"] += len(picked)
            else:
                picked, mode = list(candidates), "fallback_all"
                self._counters["resub_fallback_n"] += 1
        for e in picked:
            e.state = STATE_STALE
            e.resub_n += 1
        return picked, mode

    # ---- 402 退订（App SocketRepository.n / qn0.q）----

    def unsub_candidates(self, lane_prefix: str, cmd: int,
                         keep_keys: set) -> List[SubEntry]:
        """指定 lane/cmd 下业务 key 已不在保留面的已 ack 条目（退订 diff）。
        只取 sub_id 已回填者（服务端未分配 subId 的条目无法按 id 退订，
        留待会话重建自然失效——fail-visible 由 stats 承载）。

        M3 冲突护栏（U6 实弹：sub_id=cmd 回声，per-stock 多股共享 subId）：
        subId 被 >1 条活跃条目共享时跳过——402 按 id 退订会误退整族，
        on_unsub_ack 亦会把全部同 id 条目置 unsubscribed。只退唯一 id，
        共享 id 计数披露（sub_id_shared_skip_n）。per-stock 精准退订需唯一
        subId/topic 退订设计（方案 §12），在此之前本护栏使 per-stock 退订安全空操作。"""
        active_counts: Dict[int, int] = {}
        for e in self._entries:
            if e.sub_id is not None and e.state in (
                    STATE_PENDING, STATE_ACKED, STATE_UNSUB_SENT):
                active_counts[e.sub_id] = active_counts.get(e.sub_id, 0) + 1
        out: List[SubEntry] = []
        for e in self._entries:
            if not (e.state == STATE_ACKED and e.cmd == cmd
                    and e.lane.startswith(lane_prefix)
                    and e.key and e.key not in keep_keys and e.sub_id is not None):
                continue
            if active_counts.get(e.sub_id, 0) > 1:
                self._counters["sub_id_shared_skip_n"] += 1
                continue
            out.append(e)
        return out

    def mark_unsub_sent(self, entries: List[SubEntry]) -> None:
        for e in entries:
            e.state = STATE_UNSUB_SENT

    def on_unsub_ack(self, sub_ids: List[int]) -> int:
        """kind5 ack（UnsubIdReq 回声）：按 subId 移除注册表条目（App qn0.q）。"""
        idset = set(int(s) for s in sub_ids)
        removed = 0
        for e in self._entries:
            if e.sub_id is not None and e.sub_id in idset \
                    and e.state in (STATE_UNSUB_SENT, STATE_ACKED, STATE_PENDING):
                e.state = STATE_UNSUBSCRIBED
                removed += 1
        self._counters["unsub_ack_removed_n"] += removed
        return removed

    # ---- 211 批计划与熔断 ----

    def plan_batches(self, entries: List[SubEntry], alloc_seq: Callable[[], int],
                     max_items: int = 10, max_bytes: int = 65536
                     ) -> List[List[Dict[str, Any]]]:
        """把待登记条目打包成 SubReqs 批计划（纯结构，不加密——data 编码由
        collector 按 sub_batch_codec flag 处理）。seqId 从 alloc_seq 分配
        （与帧 seq 共用计数器，App t31 单计数器同款；号空间语义待探针 U4）。
        每批 ≤max_items 项且 Σdata ≤max_bytes；保序。返回 item dict 列表，
        每项附 `_entry` 引用供发送后 bind_batch。"""
        batches: List[List[Dict[str, Any]]] = []
        cur: List[Dict[str, Any]] = []
        cur_bytes = 0
        for e in entries:
            size = len(e.req) + 24   # item pb 开销估算（六字段 tag+varint 余量）
            if cur and (len(cur) >= max_items or cur_bytes + size > max_bytes):
                batches.append(cur)
                cur, cur_bytes = [], 0
            cur.append({"seqId": alloc_seq(), "cmd": e.cmd, "version": 0,
                        "codec": 0, "subId": e.sub_id_hint or e.cmd,
                        "data": e.req, "_entry": e})
            cur_bytes += size
        if cur:
            batches.append(cur)
        return batches

    def unacked_batches(self) -> List[int]:
        return [s for s, b in self._batches.items() if not b["acked"]]

    def timed_out_batches(self, now: float, timeout_s: float) -> List[int]:
        return [s for s, b in self._batches.items()
                if not b["acked"] and now - b["sent_at"] > timeout_s]

    # ---- 会话生命周期 ----

    def clear_session(self) -> None:
        """断线/新会话清空（App qn0.f：c/d/e 全清；重发原料由 collector
        订阅面重建流程重新 register）。"""
        self._entries.clear()
        self._batches.clear()

    def entries(self) -> List[SubEntry]:
        return list(self._entries)

    def stats(self) -> Dict[str, Any]:
        by_state: Dict[str, int] = {}
        by_lane: Dict[str, int] = {}
        by_cmd: Dict[int, int] = {}
        for e in self._entries:
            by_state[e.state] = by_state.get(e.state, 0) + 1
            by_lane[e.lane] = by_lane.get(e.lane, 0) + 1
            by_cmd[e.cmd] = by_cmd.get(e.cmd, 0) + 1
        return {
            "total": len(self._entries),
            "by_state": by_state,
            "by_lane": by_lane,
            "by_cmd": {str(k): v for k, v in sorted(by_cmd.items())},
            "batches_sent": len(self._batches),
            "batches_acked": sum(1 for b in self._batches.values() if b["acked"]),
            **self._counters,
        }