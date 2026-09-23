# -*- coding: utf-8 -*-
"""卖点扫描隔离 trial runner（与 CLI cmd_run_ranktrend 完全同构，payload 任意 trade_config）。

背景（2026-09-23 事故）：通过 8000 API 连续跑批时，uvicorn 进程内每 trial 全量装载
frames + result 大 JSON 不断累积（16 trial 后 RSS 8.4GB，全系统换页冻结行情链）。
本 runner 在**独立 python 进程**内执行回测（CLI 同链路：runtime_session +
BacktestService.run_ranktrend），进程退出即释放全部内存。

用法：
    单 trial：exit-scan-trial-runner.py <payload.json> <runid-out.txt> [--local-frames <frames.json.gz>] [--dry-run]
    批量模式（同进程串行多 trial，进程内共享信号缓存——同 strategy_config 的 trial
    只算一次信号，trade 参数档位只重跑撮合；cProfile 实测信号计算占单 trial 60-75%）：
        exit-scan-trial-runner.py --batch <payloads.json> <outdir> [--local-frames <frames.json.gz>] [--dry-run]
        payloads.json = payload 数组；outdir 下每个 trial 写 <index>-runid.txt（1 起）
        + runids.json（顺序数组）。
    --local-frames：读本地导出的 frames（exit-frames-export.py 产物），扫描全程
    零 MongoDB 大读——仅 monkeypatch repo.load_frames（harness 侧），quality gate、
    引擎与结果落库链路不变；小表（a_share_codes）与结果写入仍走正常链路。
    首次加载后自动写同名 .pkl 缓存（源 gzip 变更自动失效，异常降级直读）。
    --dry-run（2026-09-23 引擎提速立项层 2）：payload 注入 dryRun=true，跳过五表
    落库与 result_json 大序列化；runId 仅为响应标识，全量 trades/equityCurve 随
    响应返回，runner 把摘要落盘为 <runid-out 同目录>/<名字>-summary.json（单 trial）
    或 <outdir>/<index>-summary.json（批量），供扫描分析脚本归因。
输出：runId 写入 runid-out.txt，stdout 打印。
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

QB_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(QB_ROOT))

from backend.cli import runtime_session  # noqa: E402
from backend.services.backtest_service import BacktestService  # noqa: E402


def _load_local_frames(local_path: Path) -> list[dict]:
    """读本地 frames；同名 .pkl 缓存命中则跳过 gzip json 解析（省 ~50s/进程）。

    缓存守卫：记录源 gzip 的 mtime_ns/size，源文件更新自动失效重建；缓存读/写任何
    异常都降级回 gzip json 直读（fail-visible 打印原因，不阻断扫描）。
    pickle 只读本 runner 写出的本机缓存文件，勿指向不可信路径。
    pickle 与 json 路径产出同一份 json.load 对象的精确还原（值与类型逐位一致）。
    """
    import pickle

    pkl_path = local_path.with_suffix(".pkl")
    source_stat = local_path.stat()
    if pkl_path.exists():
        try:
            with pkl_path.open("rb") as fh:
                cached = pickle.load(fh)
            if (
                isinstance(cached, dict)
                and cached.get("sourceMtimeNs") == source_stat.st_mtime_ns
                and cached.get("sourceSize") == source_stat.st_size
                and isinstance(cached.get("frames"), list)
            ):
                print(f"local frames from pickle cache: {len(cached['frames'])} frames ({pkl_path.name})")
                return cached["frames"]
            print("pickle cache stale (source changed); reloading gzip json")
        except Exception as exc:
            print(f"pickle cache unreadable ({exc!r}); falling back to gzip json")

    with gzip.open(local_path, "rt", encoding="utf-8") as fh:
        frames = json.load(fh)

    try:
        with pkl_path.open("wb") as fh:
            pickle.dump(
                {"sourceMtimeNs": source_stat.st_mtime_ns, "sourceSize": source_stat.st_size, "frames": frames},
                fh,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        print(f"pickle cache written: {pkl_path.name} ({pkl_path.stat().st_size / 1_000_000:.0f} MB)")
    except Exception as exc:
        print(f"pickle cache write skipped ({exc!r}); scans still use gzip json")
    return frames


def _install_local_frames_loader(local_path: Path) -> None:
    """monkeypatch MongoRepository.load_frames 读本地导出（runner 进程内，不进生产链）。"""
    from backend.data.repositories import mongo_repository

    local_frames = _load_local_frames(local_path)

    def _load_frames_local(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        include_payload: bool = True,
        fields: list[str] | None = None,
    ) -> list[dict]:
        def _in_range(frame: dict) -> bool:
            d = str(frame.get("tradingDate") or "")
            return (not start_date or d >= start_date) and (not end_date or d <= end_date)

        return [f for f in local_frames if _in_range(f)]

    mongo_repository.MongoRepository.load_frames = _load_frames_local
    print(f"local frames loaded: {len(local_frames)} frames from {local_path}")


def _install_signal_cache() -> None:
    """进程内信号缓存：同 RankTrendConfig（strategy_config 恒定的批次内恒命中）只 replay 一次。

    依据（2026-09-23 cProfile，小窗口）：RankTrend _build_signal 链占单 trial 60-75%，
    批次内 strategy_config 恒定 → 信号输出恒定；下游（TradeSimulator/efficacy）对
    signal dict 只读（grep 核实无 signal["x"]= 写点），共享引用安全。
    缓存键 = RankTrendConfig repr（字段全量指纹），config 不同自动失效，不污染 golden。
    """
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    cache: dict[str, list[dict]] = {}
    original_replay = RankTrendPythonEngine.replay

    def _cached_replay(self, frames, *, meta=None):
        key = repr(self.config)
        if key not in cache:
            cache[key] = original_replay(self, frames, meta=meta)
            print(f"[signal-cache] miss -> computed ({len(cache[key])} signals)")
        else:
            print("[signal-cache] hit")
        return cache[key]

    RankTrendPythonEngine.replay = _cached_replay


def _run_one(payload: dict, session, dry_run: bool = False) -> tuple[str, dict | None]:
    if dry_run:
        payload = {**payload, "dryRun": True}
    result = BacktestService(session).run_ranktrend(payload)
    run_id = str(result.get("runId") or result.get("id") or "")
    print(f"runId: {run_id}{' (dry-run, 未落库)' if dry_run else ''}")
    return run_id, (result if dry_run else None)


def main() -> None:
    args = sys.argv[1:]
    local_frames_index = args.index("--local-frames") if "--local-frames" in args else -1
    local_path = Path(args[local_frames_index + 1]) if local_frames_index >= 0 else None
    if local_frames_index >= 0:
        del args[local_frames_index : local_frames_index + 2]
    dry_run = "--dry-run" in args
    if dry_run:
        args.remove("--dry-run")

    if args and args[0] == "--batch":
        if len(args) < 3:
            raise SystemExit("usage: --batch <payloads.json> <outdir> [--local-frames <frames.json.gz>] [--dry-run]")
        if not isinstance(payloads := json.loads(Path(args[1]).read_text(encoding="utf-8")), list):
            raise SystemExit("payloads.json must be a JSON array of payload objects")
        outdir = Path(args[2])

        def _batch_identity(p: dict) -> tuple:
            # 信号缓存键只含 RankTrendConfig——窗口/数据集/策略/种子不同的 payload
            # 混入同批会静默拿到第一个窗口的信号（fail-visible：批首校验，不一致拒跑）
            return (
                p.get("dataset_id"),
                p.get("snapshot_type"),
                p.get("start_date"),
                p.get("end_date"),
                p.get("strategy_name"),
                p.get("random_seed"),
                json.dumps(p.get("strategy_config") or {}, sort_keys=True),
            )

        identities = {_batch_identity(p) for p in payloads}
        if len(identities) != 1:
            raise SystemExit(
                "batch payloads vary in dataset/window/strategy_config/seed: "
                f"{identities} —— 信号缓存要求批次同源，请拆批"
            )
        outdir.mkdir(parents=True, exist_ok=True)
        if local_path is not None:
            _install_local_frames_loader(local_path)
        _install_signal_cache()
        run_ids: list[str] = []
        with runtime_session() as session:
            for index, payload in enumerate(payloads, start=1):
                run_id, summary = _run_one(payload, session, dry_run)
                run_ids.append(run_id)
                (outdir / f"{index}-runid.txt").write_text(run_id, encoding="utf-8")
                if dry_run and summary is not None:
                    (outdir / f"{index}-summary.json").write_text(
                        json.dumps(summary, ensure_ascii=False, allow_nan=False), encoding="utf-8"
                    )
        (outdir / "runids.json").write_text(json.dumps(run_ids), encoding="utf-8")
        print(f"batch done: {len(run_ids)} trials{' (dry-run)' if dry_run else ''} -> {outdir}")
        return

    if len(args) < 2:
        raise SystemExit("usage: exit-scan-trial-runner.py <payload.json> <runid-out.txt> [--local-frames ...] [--dry-run]")
    payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    if local_path is not None:
        _install_local_frames_loader(local_path)
    with runtime_session() as session:
        run_id, summary = _run_one(payload, session, dry_run)
    Path(args[1]).write_text(run_id, encoding="utf-8")
    if dry_run and summary is not None:
        summary_path = Path(args[1]).with_name(Path(args[1]).stem + "-summary.json")
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        print(f"dry-run summary: {summary_path}")


if __name__ == "__main__":
    main()
