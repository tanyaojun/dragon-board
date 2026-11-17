# -*- coding: utf-8 -*-
"""SubRegistry 纯逻辑测试（2026-11-17 P0，全 mock 红线：零网络/零 codec）。

合同来源：docs/kpl-socket/sub-registry-refactor-plan.md §1.2/§3.1
（App qn0 PackManager c/d/e 三列表 + 211 ack 展开 + 402 退订 + 220 选择性重发）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.kpl_sub_registry import (  # noqa: E402
    STATE_ACKED,
    STATE_PENDING,
    STATE_STALE,
    STATE_UNSUB_SENT,
    STATE_UNSUBSCRIBED,
    SubEntry,
    SubRegistry,
)


def _entry(cmd=2203, seq=1, key="600001", lane="zt_reason", req=b"\x0a\x06600001"):
    return SubEntry(cmd=cmd, req=req, ext=bytes([2]) + cmd.to_bytes(2, "big"),
                    seq=seq, lane=lane, key=key)


def _acked(reg, cmd=2203, seq=1, key="600001", sub_id=100, topic=b"t1",
           lane="zt_reason"):
    e = reg.register(_entry(cmd=cmd, seq=seq, key=key, lane=lane))
    reg.on_ack(seq, sub_id=sub_id, topic=topic, now=10.0)
    return e


class TestRegisterAck:
    def test_register_defaults_hint_to_cmd(self):
        reg = SubRegistry()
        e = reg.register(_entry())
        assert e.sub_id_hint == 2203 and e.state == STATE_PENDING

    def test_ack_matches_by_seq_and_fills_sub_id_topic(self):
        reg = SubRegistry()
        reg.register(_entry(seq=5))
        res = reg.on_ack(5, sub_id=77, topic=b"hq|topic", now=12.0)
        assert res["kind"] == "ack" and res["sub_id"] == 77
        e = reg.entries()[0]
        assert e.state == STATE_ACKED and e.sub_id == 77
        assert e.topic == b"hq|topic" and e.ack_at == 12.0

    def test_orphan_ack_counted_fail_visible(self):
        reg = SubRegistry()
        res = reg.on_ack(999, sub_id=1)
        assert res["kind"] == "orphan"
        assert reg.stats()["orphan_ack_n"] == 1

    def test_sub_id_collision_counted_not_merged(self):
        """与 App s() 原位合并的有意差异：per-stock 重发原料必须逐条保留。"""
        reg = SubRegistry()
        _acked(reg, seq=1, key="600001", sub_id=7)
        _acked(reg, seq=2, key="600002", sub_id=7)
        assert reg.stats()["sub_id_collision_n"] == 1
        assert len(reg.entries()) == 2   # 不合并

    def test_has_pending_seq(self):
        reg = SubRegistry()
        reg.register(_entry(seq=3))
        assert reg.has_pending_seq(3)
        reg.on_ack(3, sub_id=1)
        assert not reg.has_pending_seq(3)


class TestBatch211:
    def test_plan_batches_respects_max_items_and_bytes(self):
        reg = SubRegistry()
        entries = [reg.register(_entry(seq=i, key=str(i), req=b"x" * 100))
                   for i in range(1, 8)]
        seq_counter = [100]

        def alloc():
            seq_counter[0] += 1
            return seq_counter[0]

        batches = reg.plan_batches(entries, alloc, max_items=3, max_bytes=10000)
        assert [len(b) for b in batches] == [3, 3, 1]
        # seqId 连续分配、保序、subId hint=cmd
        assert [it["seqId"] for b in batches for it in b] == list(range(101, 108))
        assert all(it["subId"] == 2203 and it["cmd"] == 2203 for b in batches for it in b)
        # max_bytes 约束（100B req + 24 开销 → 每批 ≤8 项@1000B）
        big = reg.plan_batches(entries, alloc, max_items=100, max_bytes=300)
        assert all(len(b) <= 2 for b in big)

    def test_batch_ack_expands_items_by_seq(self):
        """App qn0.o：211 ack 逐项按 item.seqId 更新预登记项 sub_id。"""
        reg = SubRegistry()
        e1 = reg.register(_entry(cmd=2114, seq=11, key=""))
        e2 = reg.register(_entry(cmd=2116, seq=12, key=""))
        reg.bind_batch(10, [e1, e2])
        reg.track_batch(10, 2, now=1.0)
        res = reg.on_ack(10, sub_id=500, topic=b"batch",
                         sub_reqs=[{"seqId": 11, "subId": 501},
                                   {"seqId": 12, "subId": 502}], now=2.0)
        assert res["kind"] == "batch" and res["matched"] == 2 and res["orphan"] == 0
        assert e1.sub_id == 501 and e2.sub_id == 502
        assert e1.state == STATE_PENDING   # 仍待逐项 ack（U5 假说）
        assert reg.timed_out_batches(100.0, 10.0) == []   # 批已 ack

    def test_batch_ack_orphan_items_counted(self):
        reg = SubRegistry()
        reg.track_batch(10, 1, now=1.0)
        res = reg.on_ack(10, sub_reqs=[{"seqId": 99, "subId": 1}])
        assert res["orphan"] == 1 and res["batch_known"] is True

    def test_per_item_ack_after_batch(self):
        reg = SubRegistry()
        e = reg.register(_entry(seq=11))
        reg.bind_batch(10, [e])
        reg.track_batch(10, 1, now=1.0)
        reg.on_ack(10, sub_reqs=[{"seqId": 11, "subId": 501}])
        res = reg.on_ack(11, sub_id=501, topic=b"hq|t", now=3.0)
        assert res["kind"] == "ack" and e.state == STATE_ACKED
        assert e.batch_seq == 10

    def test_batch_item_no_topic_counted(self):
        """2026-11-17 实弹：批内 2103/2203/2013 ack 无 attr3 与 110/2000 拒绝同现。"""
        reg = SubRegistry()
        e = reg.register(_entry(cmd=2203, seq=11))
        reg.bind_batch(10, [e])
        reg.on_ack(11, sub_id=2203, topic=None)
        assert e.state == STATE_ACKED   # ack 确实到达，state 不变
        assert reg.stats()["batch_item_no_topic_n"] == 1
        # 单帧路径无 topic 不计数（语义未定案，只观测批内）
        reg.register(_entry(cmd=2114, seq=12))
        reg.on_ack(12, sub_id=2114, topic=None)
        assert reg.stats()["batch_item_no_topic_n"] == 1

    def test_unacked_and_timed_out_batches(self):
        reg = SubRegistry()
        reg.track_batch(10, 2, now=1.0)
        reg.track_batch(11, 2, now=5.0)
        assert reg.unacked_batches() == [10, 11]
        assert reg.timed_out_batches(12.0, 10.0) == [10]
        assert reg.timed_out_batches(20.0, 10.0) == [10, 11]


class TestPushTopic:
    def test_topic_hit_and_miss(self):
        reg = SubRegistry()
        _acked(reg, topic=b"hq|1:20030/2203-600001/")
        hit = reg.on_push_topic(b"hq|1:20030/2203-600001/")
        assert hit is not None and hit.key == "600001"
        assert reg.on_push_topic(b"unknown") is None
        st = reg.stats()
        assert st["push_topic_hit_n"] == 1 and st["push_topic_miss_n"] == 1


class TestResub220:
    def test_empty_topics_full(self):
        reg = SubRegistry()
        _acked(reg, seq=1, topic=b"a")
        _acked(reg, seq=2, key="600002", topic=b"b")
        picked, mode = reg.on_resub([])
        assert mode == "all" and len(picked) == 2
        assert all(e.state == STATE_STALE and e.resub_n == 1 for e in picked)

    def test_selective_by_topic(self):
        reg = SubRegistry()
        _acked(reg, seq=1, topic=b"a")
        e2 = _acked(reg, seq=2, key="600002", topic=b"b")
        picked, mode = reg.on_resub(["a"])
        assert mode == "selective" and len(picked) == 1 and picked[0].topic == b"a"
        assert e2.state == STATE_ACKED   # 未命中不动
        assert reg.stats()["resub_selective_n"] == 1

    def test_no_match_fallback_all_fail_visible(self):
        reg = SubRegistry()
        _acked(reg, seq=1, topic=b"a")
        picked, mode = reg.on_resub([b"zzz"])
        assert mode == "fallback_all" and len(picked) == 1
        assert reg.stats()["resub_fallback_n"] == 1

    def test_str_topics_normalized(self):
        reg = SubRegistry()
        _acked(reg, seq=1, topic=b"ab")
        picked, mode = reg.on_resub(["ab"])
        assert mode == "selective" and len(picked) == 1

    def test_stale_not_picked_again(self):
        reg = SubRegistry()
        _acked(reg, seq=1, topic=b"a")
        reg.on_resub([])
        picked, mode = reg.on_resub([])
        assert picked == [] and mode == "empty"

    def test_empty_registry(self):
        reg = SubRegistry()
        assert reg.on_resub([]) == ([], "empty")


class TestUnsub402:
    def test_candidates_diff_by_key(self):
        reg = SubRegistry()
        _acked(reg, seq=1, key="600001", sub_id=101)
        _acked(reg, seq=2, key="600002", sub_id=102)
        cands = reg.unsub_candidates("zt_reason", 2203, {"600001"})
        assert [e.sub_id for e in cands] == [102]

    def test_no_sub_id_not_candidate(self):
        reg = SubRegistry()
        e = reg.register(_entry(seq=1))
        reg.on_ack(1, sub_id=None, topic=b"t")   # 服务端未分配 subId
        assert reg.unsub_candidates("zt_reason", 2203, set()) == []

    def test_lane_prefix_isolation(self):
        reg = SubRegistry()
        _acked(reg, seq=1, key="600001", sub_id=101, lane="zt_reason")
        _acked(reg, seq=2, key="600001", sub_id=102, lane="detail:bdo", cmd=2014)
        assert reg.unsub_candidates("zt_reason", 2203, set()) != []
        assert reg.unsub_candidates("detail:", 2014, set()) != []
        assert reg.unsub_candidates("theme", 2013, set()) == []

    def test_unsub_ack_removes_by_sub_id(self):
        reg = SubRegistry()
        e = _acked(reg, seq=1, sub_id=101)
        reg.mark_unsub_sent([e])
        assert e.state == STATE_UNSUB_SENT
        removed = reg.on_unsub_ack([101])
        assert removed == 1 and e.state == STATE_UNSUBSCRIBED
        assert reg.stats()["unsub_ack_removed_n"] == 1

    def test_shared_sub_id_skipped(self):
        """M3：subId 被多条活跃条目共享（U6 sub_id=cmd 回声）→ 跳过退订防误退整族。"""
        reg = SubRegistry()
        _acked(reg, seq=1, key="600001", sub_id=2203)
        _acked(reg, seq=2, key="600002", sub_id=2203)   # 共享 subId
        cands = reg.unsub_candidates("zt_reason", 2203, {"600001"})  # 600002 掉池
        assert cands == []                              # 共享 id 不退
        assert reg.stats()["sub_id_shared_skip_n"] == 1
        _acked(reg, seq=3, key="600003", sub_id=999)    # 唯一 subId 仍可退
        cands2 = reg.unsub_candidates("zt_reason", 2203, {"600001", "600002"})
        assert [e.sub_id for e in cands2] == [999]


class TestLifecycle:
    def test_clear_session(self):
        reg = SubRegistry()
        _acked(reg)
        reg.track_batch(10, 1, now=1.0)
        reg.clear_session()
        assert reg.entries() == [] and reg.unacked_batches() == []
        # 计数器跨会话保留（累计观测口径）
        assert "orphan_ack_n" in reg.stats()

    def test_eviction_cap_fail_visible(self):
        reg = SubRegistry(max_entries=100)
        for i in range(150):
            reg.register(_entry(seq=i, key=str(i)))
        st = reg.stats()
        assert st["total"] == 100 and st["evicted_n"] == 50

    def test_eviction_prefers_terminal_states(self):
        reg = SubRegistry(max_entries=100)
        e_stale = _acked(reg, seq=0, key="old")
        reg.on_resub([])   # → stale
        for i in range(1, 100):
            reg.register(_entry(seq=i, key=str(i)))
        assert e_stale in reg.entries()   # 满员前不淘汰
        reg.register(_entry(seq=999, key="new"))
        assert e_stale not in reg.entries()   # 终态优先淘汰
        assert reg.stats()["evicted_n"] == 1

    def test_stats_shape(self):
        reg = SubRegistry()
        _acked(reg, seq=1, lane="zt_reason")
        reg.register(_entry(seq=2, lane="theme", cmd=2013))
        st = reg.stats()
        assert st["total"] == 2
        assert st["by_state"] == {STATE_ACKED: 1, STATE_PENDING: 1}
        assert st["by_lane"] == {"zt_reason": 1, "theme": 1}
        assert st["by_cmd"] == {"2013": 1, "2203": 1}