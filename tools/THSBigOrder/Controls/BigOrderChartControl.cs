using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;
using THSBigOrder.Analytics;
using THSBigOrder.Models;

namespace THSBigOrder.Controls
{
    public sealed class BigOrderChartControl : Control
    {
        private MarketSnapshot _snapshot;
        private BigOrderSeries _series;
        private readonly List<Rectangle> _layoutBands = new List<Rectangle>();

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

        public void SetSnapshot(MarketSnapshot snapshot, BigOrderSeries series)
        {
            _snapshot = snapshot;
            _series = series;
            RebuildLayout();
            Invalidate();
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            RebuildLayout();
        }

        private void RebuildLayout()
        {
            var bounds = ClientRectangle;
            var margin = 36;
            var usableHeight = Math.Max(3, bounds.Height - margin - 24);
            var priceHeight = (int)(usableHeight * 0.67);
            var volumeHeight = (int)(usableHeight * 0.18);
            _layoutBands.Clear();
            _layoutBands.Add(new Rectangle(margin, 12, Math.Max(1, bounds.Width - margin - 12), priceHeight));
            _layoutBands.Add(new Rectangle(margin, 12 + priceHeight, Math.Max(1, bounds.Width - margin - 12), volumeHeight));
            _layoutBands.Add(new Rectangle(margin, 12 + priceHeight + volumeHeight, Math.Max(1, bounds.Width - margin - 12), Math.Max(1, usableHeight - priceHeight - volumeHeight)));
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.Clear(BackColor);
            e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            DrawGrid(e.Graphics);
            if (_snapshot == null || (_snapshot.Prices.Count == 0 && (_series?.Minutes.Count ?? 0) == 0))
            {
                using (var font = new Font("Microsoft YaHei UI", 12, FontStyle.Regular))
                using (var brush = new SolidBrush(Color.FromArgb(105, 120, 145)))
                    e.Graphics.DrawString("等待大单数据", font, brush, new PointF(48, 32));
                return;
            }
            DrawLines(e.Graphics);
            DrawVolumes(e.Graphics);
            DrawThresholds(e.Graphics);
            if (_snapshot.BigOrderFreshness == DataFreshness.Stale)
            {
                using (var font = new Font("Microsoft YaHei UI", 9, FontStyle.Bold))
                using (var brush = new SolidBrush(Color.FromArgb(255, 184, 77)))
                    e.Graphics.DrawString("数据陈旧", font, brush, Math.Max(4, Width - 90), 16);
            }
        }

        private void DrawGrid(Graphics graphics)
        {
            using (var pen = new Pen(Color.FromArgb(38, 51, 71), 1))
            using (var font = new Font("Consolas", 8))
            using (var brush = new SolidBrush(Color.FromArgb(110, 130, 155)))
            {
                foreach (var band in _layoutBands)
                {
                    graphics.DrawRectangle(pen, band);
                    for (var index = 1; index < 4; index++)
                        graphics.DrawLine(pen, band.Left, band.Top + band.Height * index / 4, band.Right, band.Top + band.Height * index / 4);
                }
                graphics.DrawString("09:30", font, brush, _layoutBands[2].Left, _layoutBands[2].Bottom + 3);
                graphics.DrawString("15:00", font, brush, _layoutBands[2].Right - 36, _layoutBands[2].Bottom + 3);
            }
        }

        private void DrawLines(Graphics graphics)
        {
            DrawScaledLine(graphics, _snapshot.Prices.Select(point => point.ChangePercent).ToArray(), _layoutBands[0], Color.FromArgb(225, 241, 64), 2);
            DrawScaledLine(graphics, (_series?.NetFlow ?? new NetFlowPoint[0]).Select(point => point.Value).ToArray(), _layoutBands[0], Color.FromArgb(229, 235, 246), 1);
        }

        private static void DrawScaledLine(Graphics graphics, double[] values, Rectangle bounds, Color color, float width)
        {
            if (values.Length < 2) return;
            var min = values.Min();
            var max = values.Max();
            var range = Math.Max(0.0001, max - min);
            var points = values.Select((value, index) => new PointF(
                bounds.Left + bounds.Width * index / (float)(values.Length - 1),
                bounds.Bottom - 4 - (float)((value - min) / range) * (bounds.Height - 8))).ToArray();
            using (var pen = new Pen(color, width)) graphics.DrawLines(pen, points);
        }

        private void DrawVolumes(Graphics graphics)
        {
            var minutes = _series?.Minutes ?? new MinuteFlow[0];
            if (minutes.Count == 0) return;
            var max = Math.Max(1, minutes.Max(value => Math.Max(value.BuyAmount, value.SellAmount)));
            var width = Math.Max(2f, _layoutBands[1].Width / (float)minutes.Count);
            using (var buy = new SolidBrush(Color.FromArgb(225, 66, 92)))
            using (var sell = new SolidBrush(Color.FromArgb(25, 205, 145)))
            {
                for (var index = 0; index < minutes.Count; index++)
                {
                    var x = _layoutBands[1].Left + index * width;
                    var buyHeight = (float)(minutes[index].BuyAmount / max * _layoutBands[1].Height);
                    var sellHeight = (float)(minutes[index].SellAmount / max * _layoutBands[1].Height);
                    graphics.FillRectangle(buy, x, _layoutBands[1].Bottom - buyHeight, width / 2, buyHeight);
                    graphics.FillRectangle(sell, x + width / 2, _layoutBands[1].Bottom - sellHeight, width / 2, sellHeight);
                }
            }
        }

        private void DrawThresholds(Graphics graphics)
        {
            var values = _series?.Thresholds ?? new ThresholdFlow[0];
            if (values.Count == 0) return;
            var cellWidth = _layoutBands[2].Width / (float)values.Count;
            var max = Math.Max(1, values.Max(value => Math.Abs(value.NetAmount)));
            using (var font = new Font("Consolas", 8, FontStyle.Bold))
            using (var text = new SolidBrush(Color.White))
            {
                for (var index = 0; index < values.Count; index++)
                {
                    var intensity = Math.Min(210, 40 + (int)(Math.Abs(values[index].NetAmount) / max * 170));
                    var color = values[index].NetAmount >= 0 ? Color.FromArgb(intensity, 210, 43, 67) : Color.FromArgb(intensity, 12, 170, 110);
                    using (var brush = new SolidBrush(color))
                        graphics.FillRectangle(brush, _layoutBands[2].Left + index * cellWidth + 1, _layoutBands[2].Top + 1, cellWidth - 2, _layoutBands[2].Height - 2);
                    graphics.DrawString((values[index].Amount / 10000).ToString("0"), font, text, _layoutBands[2].Left + index * cellWidth + 3, _layoutBands[2].Top + 3);
                }
            }
        }
    }
}
