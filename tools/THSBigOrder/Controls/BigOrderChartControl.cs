using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;
using THSBigOrder.Analytics;
using THSBigOrder.Models;

namespace THSBigOrder.Controls
{
    public sealed class ChartAxisTick
    {
        public double Percent { get; set; }
        public double? Price { get; set; }
    }

    public sealed class BigOrderChartControl : Control
    {
        private MarketSnapshot _snapshot;
        private BigOrderSeries _series;
        private readonly List<Rectangle> _layoutBands = new List<Rectangle>();
        private readonly List<float> _hourGridXs = new List<float>();
        private readonly List<float> _halfHourGridXs = new List<float>();
        private readonly List<Rectangle> _halfHourRows = new List<Rectangle>();
        private readonly List<ChartAxisTick> _axisTicks = new List<ChartAxisTick>();
        private double _axisMinimum = -1;
        private double _axisMaximum = 1;

        public BigOrderChartControl()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.ResizeRedraw |
                     ControlStyles.UserPaint, true);
            BackColor = Color.FromArgb(9, 13, 22);
            ForeColor = Color.FromArgb(210, 220, 235);
            RebuildLayout();
        }

        public IReadOnlyList<Rectangle> LayoutBands => _layoutBands;
        public IReadOnlyList<float> HourGridXs => _hourGridXs;
        public IReadOnlyList<float> HalfHourGridXs => _halfHourGridXs;
        public IReadOnlyList<Rectangle> HalfHourRows => _halfHourRows;
        public IReadOnlyList<ChartAxisTick> AxisTicks => _axisTicks;

        public void SetSnapshot(MarketSnapshot snapshot, BigOrderSeries series)
        {
            _snapshot = snapshot;
            _series = series;
            RebuildLayout();
            RebuildAxisTicks();
            Invalidate();
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            RebuildLayout();
        }

        private void RebuildLayout()
        {
            const int leftAxis = 58;
            const int rightAxis = 54;
            const int top = 12;
            const int bottomLabels = 24;
            var bounds = ClientRectangle;
            var usableHeight = Math.Max(3, bounds.Height - top - bottomLabels);
            var priceHeight = (int)(usableHeight * 0.67);
            var volumeHeight = (int)(usableHeight * 0.18);
            var plotWidth = Math.Max(1, bounds.Width - leftAxis - rightAxis);
            _layoutBands.Clear();
            _layoutBands.Add(new Rectangle(leftAxis, top, plotWidth, priceHeight));
            _layoutBands.Add(new Rectangle(leftAxis, top + priceHeight, plotWidth, volumeHeight));
            _layoutBands.Add(new Rectangle(
                leftAxis,
                top + priceHeight + volumeHeight,
                plotWidth,
                Math.Max(2, usableHeight - priceHeight - volumeHeight)));

            _hourGridXs.Clear();
            for (var index = 0; index <= 4; index++)
                _hourGridXs.Add(_layoutBands[0].Left + _layoutBands[0].Width * index / 4f);

            _halfHourGridXs.Clear();
            for (var index = 0; index <= 8; index++)
                _halfHourGridXs.Add(_layoutBands[2].Left + _layoutBands[2].Width * index / 8f);

            _halfHourRows.Clear();
            var firstHeight = _layoutBands[2].Height / 2;
            _halfHourRows.Add(new Rectangle(
                _layoutBands[2].Left, _layoutBands[2].Top,
                _layoutBands[2].Width, firstHeight));
            _halfHourRows.Add(new Rectangle(
                _layoutBands[2].Left, _layoutBands[2].Top + firstHeight,
                _layoutBands[2].Width, _layoutBands[2].Height - firstHeight));
        }

        private void RebuildAxisTicks()
        {
            var values = (_snapshot?.Prices ?? new PricePoint[0])
                .Select(point => point.ChangePercent)
                .Where(value => !double.IsNaN(value) && !double.IsInfinity(value))
                .ToList();
            var minimum = Math.Min(0, values.Count == 0 ? 0 : values.Min());
            var maximum = Math.Max(0, values.Count == 0 ? 0 : values.Max());
            if (maximum - minimum < 2)
            {
                var center = (maximum + minimum) / 2;
                minimum = center - 1;
                maximum = center + 1;
                if (minimum > 0) { minimum = 0; maximum = 2; }
                if (maximum < 0) { minimum = -2; maximum = 0; }
            }
            var padding = (maximum - minimum) * 0.05;
            _axisMinimum = minimum - padding;
            _axisMaximum = maximum + padding;

            double? previousClose = null;
            if (_snapshot?.Stock?.Price != null && _snapshot.Stock.ChangePercent.HasValue)
            {
                var denominator = 1d + _snapshot.Stock.ChangePercent.Value / 100d;
                if (Math.Abs(denominator) > 0.000001)
                    previousClose = _snapshot.Stock.Price.Value / denominator;
            }

            _axisTicks.Clear();
            for (var index = 0; index < 5; index++)
            {
                var percent = _axisMinimum + (_axisMaximum - _axisMinimum) * index / 4d;
                _axisTicks.Add(new ChartAxisTick
                {
                    Percent = percent,
                    Price = previousClose.HasValue
                        ? (double?)(previousClose.Value * (1d + percent / 100d))
                        : null,
                });
            }
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.Clear(BackColor);
            e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            DrawGrid(e.Graphics);
            DrawAxes(e.Graphics);
            if (_snapshot == null || (_snapshot.Prices.Count == 0 && (_series?.Minutes.Count ?? 0) == 0))
            {
                using (var font = new Font("Microsoft YaHei UI", 12, FontStyle.Regular))
                using (var brush = new SolidBrush(Color.FromArgb(105, 120, 145)))
                    e.Graphics.DrawString("等待大单数据", font, brush, new PointF(_layoutBands[0].Left + 12, 32));
                return;
            }
            DrawLines(e.Graphics);
            DrawSignals(e.Graphics);
            DrawVolumes(e.Graphics);
            DrawHalfHourAmounts(e.Graphics);
            if (_snapshot.BigOrderFreshness == DataFreshness.Stale)
            {
                using (var font = new Font("Microsoft YaHei UI", 9, FontStyle.Bold))
                using (var brush = new SolidBrush(Color.FromArgb(255, 184, 77)))
                    e.Graphics.DrawString("数据陈旧", font, brush, Math.Max(4, _layoutBands[0].Right - 72), 16);
            }
        }

        private void DrawGrid(Graphics graphics)
        {
            using (var pen = new Pen(Color.FromArgb(45, 58, 78), 1))
            using (var labelFont = new Font("Consolas", 8))
            using (var labelBrush = new SolidBrush(Color.FromArgb(120, 145, 175)))
            {
                foreach (var band in _layoutBands) graphics.DrawRectangle(pen, band);
                foreach (var x in _hourGridXs)
                    graphics.DrawLine(pen, x, _layoutBands[0].Top, x, _layoutBands[1].Bottom);
                foreach (var x in _halfHourGridXs)
                    graphics.DrawLine(pen, x, _layoutBands[2].Top, x, _layoutBands[2].Bottom);
                graphics.DrawLine(
                    pen, _layoutBands[2].Left, _halfHourRows[1].Top,
                    _layoutBands[2].Right, _halfHourRows[1].Top);

                var labels = new[] { "09:30", "10:30", "11:30/13:00", "14:00", "15:00" };
                for (var index = 0; index < labels.Length; index++)
                {
                    var size = graphics.MeasureString(labels[index], labelFont);
                    var x = Math.Max(0, Math.Min(Width - size.Width, _hourGridXs[index] - size.Width / 2));
                    graphics.DrawString(labels[index], labelFont, labelBrush, x, _layoutBands[2].Bottom + 3);
                }
            }
        }

        private void DrawAxes(Graphics graphics)
        {
            if (_axisTicks.Count == 0) return;
            using (var gridPen = new Pen(Color.FromArgb(38, 51, 71), 1))
            using (var font = new Font("Consolas", 8))
            using (var brush = new SolidBrush(Color.FromArgb(145, 170, 200)))
            {
                for (var index = 0; index < _axisTicks.Count; index++)
                {
                    var y = _layoutBands[0].Bottom - _layoutBands[0].Height * index / 4f;
                    graphics.DrawLine(gridPen, _layoutBands[0].Left, y, _layoutBands[0].Right, y);
                    var leftText = _axisTicks[index].Price.HasValue
                        ? _axisTicks[index].Price.Value.ToString("0.00")
                        : "-";
                    var leftSize = graphics.MeasureString(leftText, font);
                    graphics.DrawString(leftText, font, brush, _layoutBands[0].Left - leftSize.Width - 4, y - 7);
                    var rightText = _axisTicks[index].Percent.ToString("+0.0;-0.0;0.0") + "%";
                    graphics.DrawString(rightText, font, brush, _layoutBands[0].Right + 4, y - 7);
                }
            }
        }

        private void DrawLines(Graphics graphics)
        {
            DrawPercentLine(
                graphics,
                _snapshot.Prices.Select(point => new TimedValue(point.Time, point.ChangePercent)).ToArray(),
                _layoutBands[0], Color.FromArgb(225, 241, 64), 2);
            DrawScaledLine(
                graphics,
                (_series?.NetFlow ?? new NetFlowPoint[0])
                    .Select(point => new TimedValue(point.Time, point.Value)).ToArray(),
                _layoutBands[0], Color.FromArgb(229, 235, 246), 1);
        }

        private void DrawPercentLine(
            Graphics graphics, TimedValue[] values, Rectangle bounds, Color color, float width)
        {
            if (values.Length < 2) return;
            var range = Math.Max(0.0001, _axisMaximum - _axisMinimum);
            var points = values.Select(item => new PointF(
                TimeX(item.Time, bounds),
                bounds.Bottom - (float)((item.Value - _axisMinimum) / range) * bounds.Height)).ToArray();
            using (var pen = new Pen(color, width)) graphics.DrawLines(pen, points);
        }

        private static void DrawScaledLine(
            Graphics graphics, TimedValue[] values, Rectangle bounds, Color color, float width)
        {
            if (values.Length < 2) return;
            var min = values.Min(item => item.Value);
            var max = values.Max(item => item.Value);
            var range = Math.Max(0.0001, max - min);
            var points = values.Select(item => new PointF(
                TimeX(item.Time, bounds),
                bounds.Bottom - 4 - (float)((item.Value - min) / range) * (bounds.Height - 8))).ToArray();
            using (var pen = new Pen(color, width)) graphics.DrawLines(pen, points);
        }

        private void DrawSignals(Graphics graphics)
        {
            if (_snapshot?.Orders == null) return;
            foreach (var order in _snapshot.Orders.Where(item =>
                !string.IsNullOrEmpty(item.FundMarker) || !string.IsNullOrEmpty(item.BuyMarker)))
            {
                var color = order.FundMarker == "点火" || order.BuyMarker == "买活跃"
                    ? Color.FromArgb(255, 91, 111)
                    : Color.FromArgb(35, 218, 154);
                var y = order.IsBuy ? _layoutBands[0].Top + 18 : _layoutBands[0].Bottom - 18;
                using (var brush = new SolidBrush(color))
                    graphics.FillEllipse(brush, TimeX(order.Time, _layoutBands[0]) - 4, y - 4, 8, 8);
            }
        }

        private static float TimeX(DateTime time, Rectangle bounds)
        {
            var minutes = time.Hour < 13
                ? (time.Hour * 60 + time.Minute) - (9 * 60 + 30)
                : 120 + (time.Hour * 60 + time.Minute) - 13 * 60;
            minutes = Math.Max(0, Math.Min(240, minutes));
            return bounds.Left + bounds.Width * minutes / 240f;
        }

        private struct TimedValue
        {
            public TimedValue(DateTime time, double value) { Time = time; Value = value; }
            public DateTime Time;
            public double Value;
        }

        private void DrawVolumes(Graphics graphics)
        {
            var minutes = _series?.Minutes ?? new MinuteFlow[0];
            if (minutes.Count == 0) return;
            var max = Math.Max(1, minutes.Max(value => Math.Max(value.BuyAmount, value.SellAmount)));
            var width = Math.Max(2f, _layoutBands[1].Width / 240f);
            using (var buy = new SolidBrush(Color.FromArgb(225, 66, 92)))
            using (var sell = new SolidBrush(Color.FromArgb(25, 205, 145)))
            {
                for (var index = 0; index < minutes.Count; index++)
                {
                    var x = TimeX(minutes[index].Minute, _layoutBands[1]);
                    var buyHeight = (float)(minutes[index].BuyAmount / max * _layoutBands[1].Height);
                    var sellHeight = (float)(minutes[index].SellAmount / max * _layoutBands[1].Height);
                    graphics.FillRectangle(buy, x, _layoutBands[1].Bottom - buyHeight, width / 2, buyHeight);
                    graphics.FillRectangle(sell, x + width / 2, _layoutBands[1].Bottom - sellHeight, width / 2, sellHeight);
                }
            }
        }

        private void DrawHalfHourAmounts(Graphics graphics)
        {
            var values = _series?.HalfHours ?? new HalfHourAmount[0];
            if (values.Count == 0) return;
            var cellWidth = _layoutBands[2].Width / 8f;
            using (var font = new Font("Consolas", 8, FontStyle.Bold))
            using (var totalBrush = new SolidBrush(Color.FromArgb(205, 216, 232)))
            using (var bigBrush = new SolidBrush(Color.FromArgb(255, 105, 125)))
            using (var totalFill = new SolidBrush(Color.FromArgb(24, 34, 50)))
            using (var bigFill = new SolidBrush(Color.FromArgb(52, 24, 34)))
            {
                for (var index = 0; index < Math.Min(8, values.Count); index++)
                {
                    var x = _layoutBands[2].Left + index * cellWidth;
                    graphics.FillRectangle(totalFill, x + 1, _halfHourRows[0].Top + 1, cellWidth - 2, _halfHourRows[0].Height - 2);
                    graphics.FillRectangle(bigFill, x + 1, _halfHourRows[1].Top + 1, cellWidth - 2, _halfHourRows[1].Height - 2);
                    DrawCentered(
                        graphics,
                        values[index].TotalAmount.HasValue ? FormatAmount(values[index].TotalAmount.Value) : "-",
                        font, totalBrush,
                        new RectangleF(x, _halfHourRows[0].Top, cellWidth, _halfHourRows[0].Height));
                    DrawCentered(
                        graphics, FormatAmount(values[index].BigOrderAmount), font, bigBrush,
                        new RectangleF(x, _halfHourRows[1].Top, cellWidth, _halfHourRows[1].Height));
                }
            }
        }

        private static void DrawCentered(
            Graphics graphics, string text, Font font, Brush brush, RectangleF bounds)
        {
            var size = graphics.MeasureString(text, font);
            graphics.DrawString(
                text, font, brush,
                bounds.Left + Math.Max(1, (bounds.Width - size.Width) / 2),
                bounds.Top + Math.Max(0, (bounds.Height - size.Height) / 2));
        }

        private static string FormatAmount(double value)
        {
            if (Math.Abs(value) >= 100000000) return (value / 100000000d).ToString("0.##") + "亿";
            if (Math.Abs(value) >= 10000) return (value / 10000d).ToString("0.#") + "万";
            return value.ToString("0");
        }
    }
}
