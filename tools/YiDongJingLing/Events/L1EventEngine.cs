using YiDongJingLing.MarketData;

namespace YiDongJingLing.Events;

public sealed class L1EventEngine
{
    private const decimal SharesPerLot = 100m;
    private readonly L1EventRules _rules;
    private readonly Dictionary<string, StockState> _states = new(StringComparer.Ordinal);
    private IReadOnlyDictionary<string, int> _limitUpStreaks = new Dictionary<string, int>(StringComparer.Ordinal);
    private readonly OpeningAuctionStateStore _openingStore;
    private readonly OpeningWeakToStrongDetector _openingDetector;
    private readonly Action<OpeningWeakToStrongTelemetryRecord>? _openingTelemetry;

    public L1EventEngine(
        L1EventRules? rules = null,
        Action<OpeningWeakToStrongTelemetryRecord>? openingTelemetry = null,
        OpeningWeakToStrongRules? openingWeakRules = null)
    {
        _rules = rules ?? new L1EventRules();
        _openingTelemetry = openingTelemetry;
        var openingRules = openingWeakRules ?? DefaultOpeningRules();
        _openingStore = new(openingRules);
        _openingDetector = new(openingRules);
    }

    public static OpeningWeakToStrongRules DefaultOpeningRules()
    {
        return new OpeningWeakToStrongRules(
            "09:20:00",
            "09:20:00",
            "09:20:30",
            "09:24:00",
            "09:24:50",
            "09:25:10",
            "09:30:00",
            "09:35:00",
            1.2m,
            1m,
            0.8m,
            0.35m,
            0.3m,
            0.2m,
            30);
    }

    public void SetLimitUpStreaks(IReadOnlyDictionary<string, int> streaks)
    {
        // 语义：截至上一交易日的连续涨停天数（0 = 昨日未涨停）；由涨停池加载器盘前注入。
        _limitUpStreaks = streaks ?? new Dictionary<string, int>(StringComparer.Ordinal);
    }

    public void UpdateOpeningRules(OpeningWeakToStrongRules rules)
    {
        _openingStore.Clear();
        _openingDetector.Clear();
    }

    public void Clear()
    {
        _states.Clear();
        _openingStore.Clear();
        _openingDetector.Clear();
    }

    public void Prime(QuoteSnapshot quote)
    {
        _openingStore.Capture(ToOpeningQuote(quote, ResolveLimitPct(quote)));
        var state = GetState(quote.Code);
        var isNewStock = IsNewStockWithoutLimit(quote.Name);
        var limitPct = isNewStock ? 0m : ResolveLimitPct(quote);
        var limitUpPrice = isNewStock ? 0m : RoundPrice(quote.PreClose * (1m + limitPct / 100m));
        var limitDownPrice = isNewStock ? 0m : RoundPrice(quote.PreClose * (1m - limitPct / 100m));
        UpdateStateFromQuote(
            state,
            quote,
            !isNewStock && IsLimitUpSealed(quote, limitUpPrice),
            !isNewStock && IsLimitDownSealed(quote, limitDownPrice));
    }

    public IReadOnlyList<EventRecord> Evaluate(
        QuoteSnapshot quote,
        QuoteSnapshot? previous,
        IReadOnlyList<QuoteSnapshot> history)
    {
        var state = GetState(quote.Code);
        // 跨日复位：程序跨日连续运行时，昨日收盘帧的封板状态不应让今日首帧误报"打开涨停板"
        // （副作用：跨日一字板会在次日正常报一次封板，符合预期）
        var evalDate = quote.SourceTime.ToLocalTime().ToString("yyyy-MM-dd");
        if (state.SealStateDate != evalDate)
        {
            state.SealStateDate = evalDate;
            state.SealedToday = false;
            state.WasLimitUpSealed = false;
            state.WasLimitDownSealed = false;
        }
        var events = new List<EventRecord>();
        var isNewStock = IsNewStockWithoutLimit(quote.Name);
        var limitPct = isNewStock ? 0m : ResolveLimitPct(quote);
        var limitUpPrice = isNewStock ? 0m : RoundPrice(quote.PreClose * (1m + limitPct / 100m));
        var limitDownPrice = isNewStock ? 0m : RoundPrice(quote.PreClose * (1m - limitPct / 100m));
        var sealedUp = !isNewStock && IsLimitUpSealed(quote, limitUpPrice);
        var sealedDown = !isNewStock && IsLimitDownSealed(quote, limitDownPrice);

        if (isNewStock)
        {
            EvaluateNewStock(events, quote, state);
        }
        else if (sealedUp && !state.WasLimitUpSealed)
        {
            var tradingDate = quote.SourceTime.ToLocalTime().ToString("yyyy-MM-dd");
            if (state.SealStateDate != tradingDate)
            {
                state.SealStateDate = tradingDate;
                state.SealedToday = false;
            }

            var streak = _limitUpStreaks.TryGetValue(quote.Code, out var yesterdayBoards) ? yesterdayBoards : 0;
            var board = streak + 1;
            var boardLabel = board >= 2 ? $"{board}连板" : "首板";
            var sealAmount = FormatMoney(SealAmount(quote, up: true));
            if (state.SealedToday)
            {
                Add(events, quote, L1EventType.LimitUpResealed, "涨停回封", L1EventSeverity.Critical,
                    $"{boardLabel}，回封封单 {sealAmount}");
            }
            else
            {
                var typeName = board >= 2 ? $"{board}连板" : "封涨停板";
                // 连板身份已由 TypeName 表达，Reason 不再重复板数
                Add(events, quote, L1EventType.LimitUpSealed, typeName, L1EventSeverity.Critical,
                    $"买一封单 {sealAmount}");
            }
            state.SealStateDate = tradingDate;
            state.SealedToday = true;
        }
        if (!isNewStock && !sealedUp && state.WasLimitUpSealed)
        {
            Add(events, quote, L1EventType.LimitUpOpened, "打开涨停板", L1EventSeverity.Critical, "最新价低于涨停价或买一不再为涨停价");
        }
        if (!isNewStock && !sealedUp && quote.ChangePct >= limitPct - _rules.NearLimitDistancePct && quote.ChangePct < limitPct)
        {
            Add(events, quote, L1EventType.NearLimitUp, "逼近涨停", L1EventSeverity.Important, $"距涨停约 {Math.Max(0, limitPct - quote.ChangePct):0.00}%");
        }
        if (!isNewStock && sealedDown && !state.WasLimitDownSealed)
        {
            Add(events, quote, L1EventType.LimitDownSealed, "封跌停板", L1EventSeverity.Critical, $"卖一封单 {FormatMoney(SealAmount(quote, up: false))}");
        }
        if (!isNewStock && !sealedDown && state.WasLimitDownSealed)
        {
            Add(events, quote, L1EventType.LimitDownOpened, "打开跌停板", L1EventSeverity.Critical, "最新价高于跌停价或卖一不再为跌停价");
        }
        if (!isNewStock && !sealedDown && quote.ChangePct <= -limitPct + _rules.NearLimitDistancePct && quote.ChangePct > -limitPct)
        {
            Add(events, quote, L1EventType.NearLimitDown, "逼近跌停", L1EventSeverity.Important, $"距跌停约 {Math.Max(0, limitPct + quote.ChangePct):0.00}%");
        }

        EvaluateUpcomingOpen(events, quote, history, state, sealedUp, sealedDown);
        EvaluateSealOrder(events, quote, state, sealedUp, sealedDown);
        EvaluateRiseTiers(events, quote, state);
        EvaluateDropTiers(events, quote, state);
        EvaluateAmountTiers(events, quote, state);
        EvaluateOpenShape(events, quote, state);
        EvaluateOpeningWeakToStrong(events, quote, state, limitUpPrice);
        EvaluateDirectionChanges(events, quote, previous);
        EvaluateIntradayHighLow(events, quote, state);
        EvaluateSpeed(events, quote, history);
        EvaluateVolumeAcceleration(events, quote, history);
        EvaluateLargeOrders(events, quote);
        EvaluatePressure(events, quote);
        EvaluateSpread(events, quote);

        UpdateStateFromQuote(state, quote, sealedUp, sealedDown);
        return events;
    }

    private StockState GetState(string code)
    {
        if (!_states.TryGetValue(code, out var state))
        {
            state = new StockState();
            _states[code] = state;
        }

        return state;
    }

    private void EvaluateUpcomingOpen(
        List<EventRecord> events,
        QuoteSnapshot quote,
        IReadOnlyList<QuoteSnapshot> history,
        StockState state,
        bool sealedUp,
        bool sealedDown)
    {
        if (sealedUp && state.WasLimitUpSealed)
        {
            var current = SealAmount(quote, up: true);
            var recentHigh = RecentMaxSealAmount(quote, history, up: true);
            if (IsSealWeakening(current, quote.Bid1Volume, state.LastLimitUpSealAmount, recentHigh))
            {
                Add(events, quote, L1EventType.UpcomingLimitUpOpen, "即将打开涨停", L1EventSeverity.Important, $"买一封单降至 {FormatMoney(current)}");
            }
        }

        if (sealedDown && state.WasLimitDownSealed)
        {
            var current = SealAmount(quote, up: false);
            var recentHigh = RecentMaxSealAmount(quote, history, up: false);
            if (IsSealWeakening(current, quote.Ask1Volume, state.LastLimitDownSealAmount, recentHigh))
            {
                Add(events, quote, L1EventType.UpcomingLimitDownOpen, "即将打开跌停", L1EventSeverity.Important, $"卖一封单降至 {FormatMoney(current)}");
            }
        }
    }

    private void EvaluateSealOrder(List<EventRecord> events, QuoteSnapshot quote, StockState state, bool sealedUp, bool sealedDown)
    {
        if (sealedUp && state.LastLimitUpSealAmount > 0m)
        {
            var current = SealAmount(quote, up: true);
            if (current >= state.LastLimitUpSealAmount * _rules.SealIncreaseRatio)
                Add(events, quote, L1EventType.SealOrderIncreased, "封单增强", L1EventSeverity.Important, $"涨停封单增至 {FormatMoney(current)}");
            else if (current <= state.LastLimitUpSealAmount * _rules.SealWeakRatio)
                Add(events, quote, L1EventType.SealOrderWeakened, "封单变弱", L1EventSeverity.Important, $"涨停封单降至 {FormatMoney(current)}");
        }

        if (sealedDown && state.LastLimitDownSealAmount > 0m)
        {
            var current = SealAmount(quote, up: false);
            if (current >= state.LastLimitDownSealAmount * _rules.SealIncreaseRatio)
                Add(events, quote, L1EventType.SealOrderIncreased, "封单增强", L1EventSeverity.Important, $"跌停封单增至 {FormatMoney(current)}");
            else if (current <= state.LastLimitDownSealAmount * _rules.SealWeakRatio)
                Add(events, quote, L1EventType.SealOrderWeakened, "封单变弱", L1EventSeverity.Important, $"跌停封单降至 {FormatMoney(current)}");
        }
    }

    // 新股（N=首日，C=第2-5日，注册制）无涨跌幅限制：跳过全部涨跌停类事件，改报开板/回封
    private static bool IsNewStockWithoutLimit(string name)
    {
        if (string.IsNullOrEmpty(name)) return false;
        return name.StartsWith("N", StringComparison.Ordinal) ||
               name.StartsWith("C", StringComparison.Ordinal);
    }

    private void EvaluateNewStock(List<EventRecord> events, QuoteSnapshot quote, StockState state)
    {
        if (quote.PreClose <= 0m || quote.High <= 0m || quote.LastPrice <= 0m) return;

        var tradingDate = quote.SourceTime.ToLocalTime().ToString("yyyy-MM-dd");
        if (state.NewStockEventDate != tradingDate)
        {
            state.NewStockEventDate = tradingDate;
            state.NewStockOpened = false;
            state.NewStockResealAnnounced = false;
        }

        var surgePct = (quote.High - quote.PreClose) / quote.PreClose * 100m;
        if (surgePct < _rules.NewStockMinSurgePct) return;

        var drawdownPct = (quote.High - quote.LastPrice) / quote.High * 100m;
        if (!state.NewStockOpened)
        {
            if (drawdownPct >= _rules.NewStockOpenDropPct)
            {
                state.NewStockOpened = true;
                Add(events, quote, L1EventType.NewStockOpened, "新股开板", L1EventSeverity.Critical,
                    $"冲高 {surgePct:0.##}% 后自高点回落 {drawdownPct:0.##}%");
            }
            return;
        }

        if (!state.NewStockResealAnnounced && drawdownPct <= _rules.NewStockResealDrawdownPct)
        {
            state.NewStockResealAnnounced = true;
            Add(events, quote, L1EventType.NewStockReseal, "新股开板回封", L1EventSeverity.Critical,
                $"回升至高点 {quote.High:0.##} 附近，回撤收窄至 {drawdownPct:0.##}%");
        }
    }

    private decimal RecentMaxSealAmount(QuoteSnapshot quote, IReadOnlyList<QuoteSnapshot> history, bool up)
    {
        return history
            .Where(item =>
                item.SourceTime < quote.SourceTime &&
                quote.SourceTime - item.SourceTime <= _rules.UpcomingOpenWindow)
            .Select(item => SealAmount(item, up))
            .DefaultIfEmpty(0m)
            .Max();
    }

    private bool IsSealWeakening(decimal currentAmount, decimal currentVolume, decimal lastAmount, decimal recentHighAmount)
    {
        if (currentAmount <= 0m || currentVolume <= 0m) return false;
        var baseline = Math.Max(lastAmount, recentHighAmount);
        return (baseline > 0m && currentAmount <= baseline * _rules.UpcomingOpenSealWeakRatio) ||
            currentAmount <= _rules.UpcomingOpenMinSealAmount ||
            currentVolume <= _rules.UpcomingOpenMinSealVolume;
    }

    private void EvaluateRiseTiers(List<EventRecord> events, QuoteSnapshot quote, StockState state)
    {
        var tier = HighestTriggeredTier(_rules.RiseTiers, quote.ChangePct, state.MaxRiseTierTriggered);
        if (tier > 0m)
        {
            state.MaxRiseTierTriggered = tier;
            Add(events, quote, L1EventType.BigRiseTier, "大幅拉升", L1EventSeverity.Important, $"涨幅突破 {tier:0.##}%");
        }
    }

    private void EvaluateDropTiers(List<EventRecord> events, QuoteSnapshot quote, StockState state)
    {
        var tier = HighestTriggeredTier(_rules.DropTiers, -quote.ChangePct, state.MaxDropTierTriggered);
        if (tier > 0m)
        {
            state.MaxDropTierTriggered = tier;
            Add(events, quote, L1EventType.BigDropTier, "大幅跳水", L1EventSeverity.Important, $"跌幅突破 {tier:0.##}%");
        }
    }

    private void EvaluateAmountTiers(List<EventRecord> events, QuoteSnapshot quote, StockState state)
    {
        var tier = HighestTriggeredTier(_rules.AmountTiers, quote.Amount, state.MaxAmountTierTriggered);
        if (tier > 0m)
        {
            state.MaxAmountTierTriggered = tier;
            Add(events, quote, L1EventType.AmountTier, "成交额跨档", L1EventSeverity.Normal, $"成交额突破 {FormatMoney(tier)}");
        }
    }

    private void EvaluateOpenShape(List<EventRecord> events, QuoteSnapshot quote, StockState state)
    {
        if (quote.Open <= 0m || quote.PreClose <= 0m || quote.LastPrice <= 0m || state.OpenShapeTriggered) return;

        var openGapPct = (quote.Open - quote.PreClose) / quote.PreClose * 100m;
        var bodyPct = (quote.LastPrice - quote.Open) / quote.Open * 100m;
        if (openGapPct <= -_rules.OpenGapPct && bodyPct >= _rules.LongBodyPct)
        {
            state.OpenShapeTriggered = true;
            Add(events, quote, L1EventType.LowOpenLongYang, "低开长阳", L1EventSeverity.Important, $"低开 {Math.Abs(openGapPct):0.00}%，开盘后拉升 {bodyPct:0.00}%");
        }
        else if (openGapPct >= _rules.OpenGapPct && bodyPct <= -_rules.LongBodyPct)
        {
            state.OpenShapeTriggered = true;
            Add(events, quote, L1EventType.HighOpenLongYin, "高开长阴", L1EventSeverity.Important, $"高开 {openGapPct:0.00}%，开盘后回落 {Math.Abs(bodyPct):0.00}%");
        }
    }

    private void EvaluateOpeningWeakToStrong(
        List<EventRecord> events,
        QuoteSnapshot quote,
        StockState state,
        decimal limitUpPrice)
    {
        var tradingDate = quote.SourceTime.ToLocalTime().ToString("yyyy-MM-dd");

        var openingQuote = ToOpeningQuote(quote, limitUpPrice);
        var result = _openingDetector.Evaluate(openingQuote, _openingStore.GetBaseline(quote.Code, quote.SourceTime));
        if (!result.Triggered)
        {
            RecordOpeningTelemetry(state, tradingDate, result, "detector_rejected");
            return;
        }
        if (state.OpeningWeakToStrongTriggeredDate == tradingDate &&
            OpeningStagePriority(result) < state.OpeningWeakToStrongIntradayPriority)
        {
            RecordOpeningTelemetry(state, tradingDate, result, "event_suppressed_duplicate_or_lower_priority");
            return;
        }

        state.OpeningWeakToStrongTriggeredDate = tradingDate;
        state.OpeningWeakToStrongIntradayPriority = OpeningStagePriority(result);
        Add(
            events,
            quote,
            L1EventType.OpeningWeakToStrong,
            OpeningTypeName(result),
            L1EventSeverity.Important,
            OpeningReason(result),
            ToOpeningSignal(result));
    }

    private void RecordOpeningTelemetry(
        StockState state,
        string tradingDate,
        OpeningWeakToStrongResult result,
        string decision)
    {
        if (result.InvalidReason == "outside_detection_window") return;
        var telemetryKey = $"{tradingDate}:{decision}:{result.InvalidReason ?? result.Stage}";
        if (!state.OpeningTelemetryKeys.Add(telemetryKey)) return;
        _openingTelemetry?.Invoke(OpeningWeakToStrongTelemetryRecord.FromResult(result, decision));
    }

    private static void EvaluateDirectionChanges(List<EventRecord> events, QuoteSnapshot quote, QuoteSnapshot? previous)
    {
        if (previous is null) return;

        if (previous.ChangePct <= 0m && quote.ChangePct > 0m)
            Add(events, quote, L1EventType.TurnRed, "翻红", L1EventSeverity.Normal, "涨跌幅由绿转红");
        if (previous.ChangePct >= 0m && quote.ChangePct < 0m)
            Add(events, quote, L1EventType.TurnGreen, "翻绿", L1EventSeverity.Normal, "涨跌幅由红转绿");
    }

    private void EvaluateIntradayHighLow(List<EventRecord> events, QuoteSnapshot quote, StockState state)
    {
        if (state.IntradayHigh > 0m && quote.LastPrice > state.IntradayHigh)
            Add(events, quote, L1EventType.IntradayHigh, "创日内新高", L1EventSeverity.Normal, $"刷新工具启动后高点 {quote.LastPrice:0.00}");
        if (state.IntradayLow > 0m && quote.LastPrice < state.IntradayLow)
            Add(events, quote, L1EventType.IntradayLow, "创日内新低", L1EventSeverity.Normal, $"刷新工具启动后低点 {quote.LastPrice:0.00}");
    }

    private void EvaluateSpeed(List<EventRecord> events, QuoteSnapshot quote, IReadOnlyList<QuoteSnapshot> history)
    {
        var change30 = ChangeFromWindow(quote, history, TimeSpan.FromSeconds(30));
        var change60 = ChangeFromWindow(quote, history, TimeSpan.FromSeconds(60));
        var change300 = ChangeFromWindow(quote, history, TimeSpan.FromMinutes(5));

        if (change30 >= _rules.FastRise30SecPct || change60 >= _rules.FastRise60SecPct || change300 >= _rules.FastRise300SecPct)
            Add(events, quote, L1EventType.FastRise, "快速拉升", L1EventSeverity.Important, $"30秒 {change30:0.00}%，60秒 {change60:0.00}%，5分钟 {change300:0.00}%");
        if (change30 <= _rules.FastDrop30SecPct || change60 <= _rules.FastDrop60SecPct || change300 <= _rules.FastDrop300SecPct)
            Add(events, quote, L1EventType.FastDrop, "快速跳水", L1EventSeverity.Important, $"30秒 {change30:0.00}%，60秒 {change60:0.00}%，5分钟 {change300:0.00}%");
    }

    private void EvaluateVolumeAcceleration(List<EventRecord> events, QuoteSnapshot quote, IReadOnlyList<QuoteSnapshot> history)
    {
        var recent = history.Where(item => quote.SourceTime - item.SourceTime <= TimeSpan.FromSeconds(30)).ToArray();
        var prior = history.Where(item =>
            quote.SourceTime - item.SourceTime > TimeSpan.FromSeconds(30) &&
            quote.SourceTime - item.SourceTime <= TimeSpan.FromSeconds(60)).ToArray();
        if (recent.Length < 2 || prior.Length < 2) return;

        var recentDelta = Math.Max(0m, recent[^1].Volume - recent[0].Volume);
        var priorDelta = Math.Max(0m, prior[^1].Volume - prior[0].Volume);
        if (priorDelta > 0m && recentDelta >= priorDelta * _rules.VolumeAccelerationRatio)
        {
            Add(events, quote, L1EventType.VolumeAcceleration, "成交增量加速", L1EventSeverity.Normal, $"近30秒成交增量约为前段 {recentDelta / priorDelta:0.0} 倍");
        }
    }

    private void EvaluatePressure(List<EventRecord> events, QuoteSnapshot quote)
    {
        if (quote.BidVolume5 > 0m && quote.AskVolume5 > 0m)
        {
            if (quote.BidVolume5 >= quote.AskVolume5 * _rules.PressureRatio)
                Add(events, quote, L1EventType.BidPressure, "盘口买压增强", L1EventSeverity.Normal, $"五档买量/卖量 {quote.BidVolume5 / quote.AskVolume5:0.0}");
            if (quote.AskVolume5 >= quote.BidVolume5 * _rules.PressureRatio)
                Add(events, quote, L1EventType.AskPressure, "盘口卖压增强", L1EventSeverity.Normal, $"五档卖量/买量 {quote.AskVolume5 / quote.BidVolume5:0.0}");
        }
    }

    private void EvaluateLargeOrders(List<EventRecord> events, QuoteSnapshot quote)
    {
        if (quote.Bid1Price > 0m && quote.Bid1Volume > 0m)
        {
            var amount = quote.Bid1Price * quote.Bid1Volume * SharesPerLot;
            if (amount >= _rules.LargeOrderAmount)
            {
                Add(events, quote, L1EventType.LargeBidOrder, "出现大买挂盘", L1EventSeverity.Normal, $"买一挂单 {FormatMoney(amount)}");
            }
        }
        if (quote.Ask1Price > 0m && quote.Ask1Volume > 0m)
        {
            var amount = quote.Ask1Price * quote.Ask1Volume * SharesPerLot;
            if (amount >= _rules.LargeOrderAmount)
            {
                Add(events, quote, L1EventType.LargeAskOrder, "出现大卖挂盘", L1EventSeverity.Normal, $"卖一挂单 {FormatMoney(amount)}");
            }
        }
    }

    private void EvaluateSpread(List<EventRecord> events, QuoteSnapshot quote)
    {
        if (quote.Bid1Price <= 0m || quote.Ask1Price <= 0m || quote.LastPrice <= 0m) return;

        var spreadPct = (quote.Ask1Price - quote.Bid1Price) / quote.LastPrice * 100m;
        if (spreadPct >= _rules.SpreadPct)
        {
            Add(events, quote, L1EventType.SpreadWidened, "买卖价差异常", L1EventSeverity.Normal, $"买卖一价差 {spreadPct:0.00}%");
        }
    }

    private decimal ChangeFromWindow(QuoteSnapshot quote, IReadOnlyList<QuoteSnapshot> history, TimeSpan window)
    {
        var baseline = history
            .Where(item => item.SourceTime <= quote.SourceTime - window && item.LastPrice > 0m)
            .OrderByDescending(item => item.SourceTime)
            .FirstOrDefault();
        if (baseline is null || baseline.LastPrice <= 0m) return 0m;
        // 快照断档时基线已过期（超窗口+容忍度），按旧基线算涨速会把断档涨幅误报成瞬时暴涨/暴跌
        if (quote.SourceTime - baseline.SourceTime > window + _rules.SpeedBaselineTolerance) return 0m;
        return (quote.LastPrice - baseline.LastPrice) / baseline.LastPrice * 100m;
    }

    private static decimal ResolveLimitPct(QuoteSnapshot quote)
    {
        var code = quote.Code;
        if (quote.Name.Contains("ST", StringComparison.OrdinalIgnoreCase)) return 5m;
        if (code.StartsWith("30", StringComparison.Ordinal) || code.StartsWith("68", StringComparison.Ordinal)) return 20m;
        if (code.StartsWith("8", StringComparison.Ordinal) || code.StartsWith("4", StringComparison.Ordinal)) return 30m;
        return 10m;
    }

    private OpeningWeakToStrongQuote ToOpeningQuote(QuoteSnapshot quote, decimal? limitUpPrice = null)
    {
        return new OpeningWeakToStrongQuote(
            quote.Code,
            quote.Name,
            quote.SourceTime,
            quote.LastPrice,
            quote.PreClose,
            quote.Open,
            quote.Amount,
            quote.Volume,
            limitUpPrice ?? 0m,
            quote.CapturedAt,
            quote.BridgeTs,
            quote.OpeningForcedSample,
            quote.RequestedCount,
            quote.ReceivedCount,
            quote.ElapsedMs,
            quote.SlowBatches,
            quote.TruncatedBatches);
    }

    private static string OpeningReason(OpeningWeakToStrongResult result, bool intradayUpdate = false)
    {
        return string.IsNullOrWhiteSpace(result.Reason) ? result.Stage : result.Reason;
    }

    private static string OpeningTypeName(OpeningWeakToStrongResult result)
    {
        return result.Stage switch
        {
            "auctionConditionPassed" or "auctionConditionFailed" => "竞价弱转强候选",
            "gapAlert" => "开盘承接转强",
            "trendConfirm" => "开盘反攻确认",
            "optionalFinalStatus" => "竞价弱转强复盘",
            _ => "竞价弱转强",
        };
    }

    private static int OpeningStagePriority(OpeningWeakToStrongResult result)
    {
        return result.Stage switch
        {
            "auctionConditionPassed" or "auctionConditionFailed" => 1,
            "gapAlert" or "noGap" => 2,
            "trendConfirm" or "trendWeak" => 3,
            "optionalFinalStatus" => 4,
            _ => 0,
        };
    }

    private static OpeningWeakToStrongSignal ToOpeningSignal(OpeningWeakToStrongResult result)
    {
        return new OpeningWeakToStrongSignal(
            result.TriggerAt.ToString("yyyy-MM-dd"),
            result.Code,
            result.Name,
            result.SignalType,
            result.Stage,
            result.Status,
            result.VoiceEligible,
            result.Reason,
            result.Time,
            result.Price,
            result.Pct,
            result.TriggerAt,
            result.AuctionFinalPrice,
            result.AuctionPct,
            result.OfficialOpen,
            result.OfficialOpenPct,
            result.FirstWindowPrice,
            result.FirstWindowPct,
            result.JumpPctPoint,
            result.Amount,
            result.AmountDelta,
            result.InitialBaselineAt,
            result.InitialBaselinePrice,
            result.InitialBaselinePct,
            result.InitialBaselineAmount,
            result.FinalBaselineAt,
            result.FinalBaselinePrice,
            result.FinalBaselinePct,
            result.FinalBaselineAmount,
            result.AuctionPriceLiftPctPoint,
            result.AuctionAmountDelta,
            result.AuctionAmountLiftRatio,
            result.PriceVolumeConfirmed,
            result.BaselineQuality,
            result.AuctionCapturedAt,
            result.BridgeTs,
            result.QuoteCapturedAt,
            result.AuctionSampleCount,
            result.QuoteAgeMs,
            result.LatencyMs,
            result.OpeningForcedSample,
            result.RequestedCount,
            result.ReceivedCount,
            result.ElapsedMs,
            result.SlowBatches,
            result.TruncatedBatches,
            result.RuleVersion,
            result.ConfigHash);
    }

    private static string FormatSignedPct(decimal? value)
    {
        if (!value.HasValue) return "--";
        return $"{(value.Value >= 0m ? "+" : "")}{value.Value:0.00}%";
    }

    private static bool IsLimitUpSealed(QuoteSnapshot quote, decimal limitUpPrice)
    {
        if (quote.PreClose <= 0m || quote.LastPrice <= 0m) return false;
        return quote.LastPrice >= limitUpPrice - 0.01m &&
               quote.Bid1Price >= limitUpPrice - 0.01m &&
               quote.Bid1Volume > 0m;
    }

    private static bool IsLimitDownSealed(QuoteSnapshot quote, decimal limitDownPrice)
    {
        if (quote.PreClose <= 0m || quote.LastPrice <= 0m) return false;
        return quote.LastPrice <= limitDownPrice + 0.01m &&
               quote.Ask1Price <= limitDownPrice + 0.01m &&
               quote.Ask1Volume > 0m;
    }

    private static decimal RoundPrice(decimal value) => Math.Round(value, 2, MidpointRounding.AwayFromZero);

    private void UpdateStateFromQuote(StockState state, QuoteSnapshot quote, bool sealedUp, bool sealedDown)
    {
        state.WasLimitUpSealed = sealedUp;
        state.WasLimitDownSealed = sealedDown;
        var sealDate = quote.SourceTime.ToLocalTime().ToString("yyyy-MM-dd");
        if (state.SealStateDate != sealDate)
        {
            state.SealStateDate = sealDate;
            state.SealedToday = false;
        }
        if (sealedUp)
        {
            state.SealedToday = true;
        }
        state.LastLimitUpSealAmount = sealedUp ? SealAmount(quote, up: true) : 0m;
        state.LastLimitDownSealAmount = sealedDown ? SealAmount(quote, up: false) : 0m;
        state.MaxRiseTierTriggered = Math.Max(
            state.MaxRiseTierTriggered,
            HighestTriggeredTier(_rules.RiseTiers, quote.ChangePct, 0m));
        state.MaxDropTierTriggered = Math.Max(
            state.MaxDropTierTriggered,
            HighestTriggeredTier(_rules.DropTiers, -quote.ChangePct, 0m));
        state.MaxAmountTierTriggered = Math.Max(
            state.MaxAmountTierTriggered,
            HighestTriggeredTier(_rules.AmountTiers, quote.Amount, 0m));
        state.IntradayHigh = Math.Max(state.IntradayHigh, quote.LastPrice);
        state.IntradayLow = state.IntradayLow == 0m ? quote.LastPrice : Math.Min(state.IntradayLow, quote.LastPrice);
        state.OpenShapeTriggered = state.OpenShapeTriggered || IsOpenShapeTriggered(quote);
    }

    private bool IsOpenShapeTriggered(QuoteSnapshot quote)
    {
        if (quote.Open <= 0m || quote.PreClose <= 0m || quote.LastPrice <= 0m) return false;

        var openGapPct = (quote.Open - quote.PreClose) / quote.PreClose * 100m;
        var bodyPct = (quote.LastPrice - quote.Open) / quote.Open * 100m;
        return openGapPct <= -_rules.OpenGapPct && bodyPct >= _rules.LongBodyPct ||
            openGapPct >= _rules.OpenGapPct && bodyPct <= -_rules.LongBodyPct;
    }

    private static decimal HighestTriggeredTier(IEnumerable<decimal> tiers, decimal value, decimal current)
    {
        return tiers
            .Where(item => value >= item && current < item)
            .DefaultIfEmpty(0m)
            .Max();
    }

    private static void Add(
        List<EventRecord> events,
        QuoteSnapshot quote,
        L1EventType type,
        string typeName,
        L1EventSeverity severity,
        string reason,
        OpeningWeakToStrongSignal? openingSignal = null)
    {
        events.Add(new EventRecord(
            type,
            typeName,
            quote.Code,
            quote.Name,
            quote.LastPrice,
            quote.ChangePct,
            quote.Volume,
            quote.Amount,
            quote.SourceTime,
            severity,
            reason,
            openingSignal));
    }

    private static string FormatMoney(decimal value)
    {
        if (value >= 100_000_000m) return $"{value / 100_000_000m:0.##}亿";
        if (value >= 10_000m) return $"{value / 10_000m:0.##}万";
        return $"{value:0}";
    }

    private static decimal SealAmount(QuoteSnapshot quote, bool up)
    {
        return up
            ? quote.Bid1Price * quote.Bid1Volume * SharesPerLot
            : quote.Ask1Price * quote.Ask1Volume * SharesPerLot;
    }

    private sealed class StockState
    {
        public bool WasLimitUpSealed { get; set; }
        public bool WasLimitDownSealed { get; set; }
        public decimal LastLimitUpSealAmount { get; set; }
        public decimal LastLimitDownSealAmount { get; set; }
        public decimal MaxRiseTierTriggered { get; set; }
        public decimal MaxDropTierTriggered { get; set; }
        public decimal MaxAmountTierTriggered { get; set; }
        public decimal IntradayHigh { get; set; }
        public decimal IntradayLow { get; set; }
        public bool OpenShapeTriggered { get; set; }
        public string OpeningWeakToStrongTriggeredDate { get; set; } = "";
        public int OpeningWeakToStrongIntradayPriority { get; set; }
        public string NewStockEventDate { get; set; } = "";
        public string SealStateDate { get; set; } = "";
        public bool SealedToday { get; set; }
        public bool NewStockOpened { get; set; }
        public bool NewStockResealAnnounced { get; set; }
        public HashSet<string> OpeningTelemetryKeys { get; } = new(StringComparer.Ordinal);
    }
}
