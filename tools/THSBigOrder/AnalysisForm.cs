using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Linq;
using System.Windows.Forms;

namespace THSBigOrder
{
    public class AnalysisForm : Form
    {
        private Panel panelTop;
        private Panel panelChart;
        private DataGridView gridPeriods;
        
        private List<BigOrderItem> _data;
        private string _stockName;
        private string _stockCode;
        private string _filterInfo;

        // 统计数据
        private double _buyAmount, _sellAmount, _netBuy;
        private double _mainBuyAmount, _mainSellAmount;
        private int _igniteCount, _smashCount, _buyActiveCount, _sellActiveCount;

        // 颜色
        private readonly Color ColorBuy = Color.FromArgb(255, 80, 80);
        private readonly Color ColorSell = Color.FromArgb(80, 200, 80);
        private readonly Color ColorIgnite = Color.FromArgb(255, 215, 0);
        private readonly Color ColorSmash = Color.FromArgb(147, 112, 219);
        private readonly Color ColorBuyActive = Color.FromArgb(255, 69, 0);
        private readonly Color ColorSellActive = Color.FromArgb(0, 191, 255);

        public AnalysisForm(string stockCode, string stockName, List<BigOrderItem> data, string filterInfo = "")
        {
            _stockCode = stockCode;
            _stockName = stockName;
            _data = data;
            _filterInfo = filterInfo;
            
            CalculateStatistics();
            InitializeComponent();
        }

        private void CalculateStatistics()
        {
            if (_data == null || _data.Count == 0) return;

            _buyAmount = _data.Where(x => x.IsBuy).Sum(x => x.Amount);
            _sellAmount = _data.Where(x => x.IsSell).Sum(x => x.Amount);
            _netBuy = _buyAmount - _sellAmount;

            _mainBuyAmount = _data.Where(x => x.Type == 2).Sum(x => x.Amount);
            _mainSellAmount = _data.Where(x => x.Type == 4).Sum(x => x.Amount);

            _igniteCount = _data.Count(x => x.FundMarker == "点火");
            _smashCount = _data.Count(x => x.FundMarker == "砸盘");
            _buyActiveCount = _data.Count(x => x.BuyMarker == "买活跃");
            _sellActiveCount = _data.Count(x => x.BuyMarker == "承接好");
        }

        private void InitializeComponent()
        {
            string titleFilter = string.IsNullOrEmpty(_filterInfo) ? "" : " [" + _filterInfo + "]";
            this.Text = _stockName + " (" + _stockCode + ")" + titleFilter + " - 数据统计";
            this.Size = new Size(420, 520);
            this.StartPosition = FormStartPosition.CenterParent;
            this.BackColor = Color.Black;  // 纯黑背景，颜色更鲜明
            this.ForeColor = Color.White;
            this.MinimumSize = new Size(400, 450);
            
            // === 顶部统计面板 ===
            panelTop = new Panel();
            panelTop.BackColor = Color.Black;
            panelTop.Dock = DockStyle.Top;
            panelTop.Height = 95;
            panelTop.Paint += PanelTop_Paint;

            // === 图表面板 ===
            panelChart = new Panel();
            panelChart.BackColor = Color.Black;
            panelChart.Dock = DockStyle.Top;
            panelChart.Height = 110;
            panelChart.Paint += PanelChart_Paint;
            panelChart.Resize += (s, ev) => panelChart.Invalidate();  // 窗口调整时刷新

            // === 分隔线 ===
            var panelSeparator = new Panel();
            panelSeparator.BackColor = Color.DimGray;  // 分隔线保持灰色
            panelSeparator.Dock = DockStyle.Top;
            panelSeparator.Height = 2;

            // === 时段统计表格 ===
            gridPeriods = CreateDataGridView();
            gridPeriods.Dock = DockStyle.Fill;
            gridPeriods.ScrollBars = ScrollBars.None;
            gridPeriods.MouseWheel += GridPeriods_MouseWheel;

            // 添加控件（注意顺序：后添加的在上面）
            this.Controls.Add(gridPeriods);
            this.Controls.Add(panelSeparator);
            this.Controls.Add(panelChart);
            this.Controls.Add(panelTop);

            // 恢复窗口大小
            WindowSettings.ApplyWindowSize(this, "AnalysisForm");

            // 关闭时保存窗口大小
            this.FormClosing += (s, ev) =>
            {
                if (this.WindowState == FormWindowState.Normal)
                {
                    WindowSettings.SaveWindowSize("AnalysisForm", this.Size);
                }
            };

            LoadPeriodData();
        }

        private void PanelTop_Paint(object sender, PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;

            var fontTitle = new Font("Microsoft YaHei", 11, FontStyle.Bold);
            var fontNormal = new Font("Microsoft YaHei", 9, FontStyle.Bold);
            var fontSmall = new Font("Microsoft YaHei", 8);
            var buyBrush = new SolidBrush(ColorBuy);
            var sellBrush = new SolidBrush(ColorSell);
            var netBrush = new SolidBrush(_netBuy >= 0 ? ColorBuy : ColorSell);
            var igniteBrush = new SolidBrush(ColorIgnite);
            var smashBrush = new SolidBrush(ColorSmash);
            var buyActiveBrush = new SolidBrush(ColorBuyActive);
            var sellActiveBrush = new SolidBrush(ColorSellActive);

            int y = 5;
            int col1 = 8, col2 = 140, col3 = 280;

            // 第一行：标题
            g.DrawString(string.Format("{0} ({1})", _stockName, _stockCode), fontTitle, Brushes.White, col1, y);
            string filterText = string.IsNullOrEmpty(_filterInfo) ? "" : " " + _filterInfo;
            g.DrawString(string.Format("大单: {0}笔{1}", _data?.Count ?? 0, filterText), fontSmall, Brushes.Yellow, col3 - 20, y + 3);

            y += 22;
            // 第二行：买入、卖出、净买
            g.DrawString(string.Format("买入: {0}", FormatAmount(_buyAmount)), fontNormal, buyBrush, col1, y);
            g.DrawString(string.Format("卖出: {0}", FormatAmount(_sellAmount)), fontNormal, sellBrush, col2, y);
            g.DrawString(string.Format("净买: {0}", FormatAmount(_netBuy)), fontNormal, netBrush, col3, y);

            y += 22;
            // 第三行：主动买、主动卖（与原始版本一致）
            g.DrawString(string.Format("主动买: {0}", FormatAmount(_mainBuyAmount)), fontNormal, buyBrush, col1, y);
            g.DrawString(string.Format("主动卖: {0}", FormatAmount(_mainSellAmount)), fontNormal, sellBrush, col2, y);

            y += 22;
            // 第四行：点火、砸盘、买活跃、承接好
            g.DrawString(string.Format("点火: {0}", _igniteCount), fontNormal, igniteBrush, col1, y);
            g.DrawString(string.Format("砸盘: {0}", _smashCount), fontNormal, smashBrush, col1 + 70, y);
            g.DrawString(string.Format("买活跃: {0}", _buyActiveCount), fontNormal, buyActiveBrush, col2, y);
            g.DrawString(string.Format("承接好: {0}", _sellActiveCount), fontNormal, sellActiveBrush, col3, y);

            fontTitle.Dispose();
            fontNormal.Dispose();
            fontSmall.Dispose();
            buyBrush.Dispose();
            sellBrush.Dispose();
            netBrush.Dispose();
            igniteBrush.Dispose();
            smashBrush.Dispose();
            buyActiveBrush.Dispose();
            sellActiveBrush.Dispose();
        }

        private void PanelChart_Paint(object sender, PaintEventArgs e)
        {
            if (_data == null || _data.Count == 0) return;

            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;

            int margin = 10;
            int barHeight = 18;
            int maxWidth = panelChart.Width - margin * 2 - 80;
            int y = 8;

            var fontSmall = new Font("Microsoft YaHei", 8);
            var buyBrush = new SolidBrush(ColorBuy);
            var sellBrush = new SolidBrush(ColorSell);
            var mainBuyBrush = new SolidBrush(Color.FromArgb(200, 60, 60));
            var mainSellBrush = new SolidBrush(Color.FromArgb(60, 160, 60));
            var igniteBrush = new SolidBrush(ColorIgnite);
            var smashBrush = new SolidBrush(ColorSmash);
            var buyActiveBrush = new SolidBrush(ColorBuyActive);
            var sellActiveBrush = new SolidBrush(ColorSellActive);

            // 买卖对比条
            double total = _buyAmount + _sellAmount;
            if (total > 0)
            {
                int buyWidth = (int)((_buyAmount / total) * maxWidth);
                int sellWidth = maxWidth - buyWidth;

                g.DrawString("买卖比", fontSmall, Brushes.Gray, margin, y);
                g.FillRectangle(buyBrush, margin + 45, y, buyWidth, barHeight);
                g.FillRectangle(sellBrush, margin + 45 + buyWidth, y, sellWidth, barHeight);
                
                double buyPct = _buyAmount / total * 100;
                g.DrawString(string.Format("{0:F0}%", buyPct), fontSmall, Brushes.White, margin + 45 + buyWidth / 2 - 12, y + 2);
            }

            y += barHeight + 8;

            // 主动买主动卖对比条
            double mainTotal = _mainBuyAmount + _mainSellAmount;
            if (mainTotal > 0)
            {
                int mainBuyWidth = (int)((_mainBuyAmount / mainTotal) * maxWidth);
                int mainSellWidth = maxWidth - mainBuyWidth;

                g.DrawString("主动比", fontSmall, Brushes.Gray, margin, y);
                g.FillRectangle(mainBuyBrush, margin + 45, y, mainBuyWidth, barHeight);
                g.FillRectangle(mainSellBrush, margin + 45 + mainBuyWidth, y, mainSellWidth, barHeight);
                
                double mainBuyPct = _mainBuyAmount / mainTotal * 100;
                g.DrawString(string.Format("{0:F0}%", mainBuyPct), fontSmall, Brushes.White, margin + 45 + mainBuyWidth / 2 - 12, y + 2);
            }

            y += barHeight + 8;

            // 点火砸盘对比条
            int actionTotal = _igniteCount + _smashCount;
            if (actionTotal > 0)
            {
                int igniteWidth = (int)(((double)_igniteCount / actionTotal) * maxWidth);
                int smashWidth = maxWidth - igniteWidth;

                g.DrawString("资金动", fontSmall, Brushes.Gray, margin, y);
                g.FillRectangle(igniteBrush, margin + 45, y, igniteWidth, barHeight);
                g.FillRectangle(smashBrush, margin + 45 + igniteWidth, y, smashWidth, barHeight);
                
                g.DrawString(string.Format("{0}", _igniteCount), fontSmall, Brushes.Black, margin + 45 + igniteWidth / 2 - 8, y + 2);
            }

            y += barHeight + 8;

            // 活跃度对比条
            int activeTotal = _buyActiveCount + _sellActiveCount;
            if (activeTotal > 0)
            {
                int buyActWidth = (int)(((double)_buyActiveCount / activeTotal) * maxWidth);
                int sellActWidth = maxWidth - buyActWidth;

                g.DrawString("活跃度", fontSmall, Brushes.Gray, margin, y);
                g.FillRectangle(buyActiveBrush, margin + 45, y, buyActWidth, barHeight);
                g.FillRectangle(sellActiveBrush, margin + 45 + buyActWidth, y, sellActWidth, barHeight);
                
                g.DrawString(string.Format("{0}", _buyActiveCount), fontSmall, Brushes.White, margin + 45 + buyActWidth / 2 - 8, y + 2);
            }

            fontSmall.Dispose();
            buyBrush.Dispose();
            sellBrush.Dispose();
            mainBuyBrush.Dispose();
            mainSellBrush.Dispose();
            igniteBrush.Dispose();
            smashBrush.Dispose();
            buyActiveBrush.Dispose();
            sellActiveBrush.Dispose();
        }

        private DataGridView CreateDataGridView()
        {
            var grid = new DataGridView();
            grid.BackgroundColor = Color.Black;
            grid.ForeColor = Color.White;
            grid.GridColor = Color.Black;
            grid.BorderStyle = BorderStyle.None;
            grid.RowHeadersVisible = false;
            grid.AllowUserToAddRows = false;
            grid.ReadOnly = true;
            grid.AutoGenerateColumns = false;
            grid.EnableHeadersVisualStyles = false;
            grid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(30, 60, 100);
            grid.ColumnHeadersDefaultCellStyle.ForeColor = Color.White;
            grid.ColumnHeadersDefaultCellStyle.Font = new Font("Microsoft YaHei", 9, FontStyle.Bold);
            grid.ColumnHeadersHeight = 24;
            grid.DefaultCellStyle.BackColor = Color.Black;
            grid.DefaultCellStyle.ForeColor = Color.White;
            grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(50, 60, 80);
            grid.DefaultCellStyle.Font = new Font("Microsoft YaHei", 9);
            grid.RowTemplate.Height = 22;
            return grid;
        }

        private void LoadPeriodData()
        {
            if (_data == null || _data.Count == 0) return;

            gridPeriods.Columns.Clear();
            gridPeriods.Columns.Add(new DataGridViewTextBoxColumn { Name = "Period", HeaderText = "时段", Width = 75 });
            gridPeriods.Columns.Add(new DataGridViewTextBoxColumn { Name = "Count", HeaderText = "笔", Width = 35 });
            gridPeriods.Columns.Add(new DataGridViewTextBoxColumn { Name = "Buy", HeaderText = "买入", Width = 60 });
            gridPeriods.Columns.Add(new DataGridViewTextBoxColumn { Name = "Sell", HeaderText = "卖出", Width = 60 });
            gridPeriods.Columns.Add(new DataGridViewTextBoxColumn { Name = "Net", HeaderText = "净买", Width = 60 });
            gridPeriods.Columns.Add(new DataGridViewTextBoxColumn { Name = "Ignite", HeaderText = "点", Width = 30 });
            gridPeriods.Columns.Add(new DataGridViewTextBoxColumn { Name = "Smash", HeaderText = "砸", Width = 30 });
            gridPeriods.Columns.Add(new DataGridViewTextBoxColumn { Name = "BuyAct", HeaderText = "买活", Width = 38 });
            gridPeriods.Columns.Add(new DataGridViewTextBoxColumn { Name = "SellAct", HeaderText = "卖活", Width = 38 });

            foreach (DataGridViewColumn col in gridPeriods.Columns)
            {
                col.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleCenter;
                col.HeaderCell.Style.Alignment = DataGridViewContentAlignment.MiddleCenter;
            }

            var periods = new[]
            {
                new { Name = "09:30-10:00", Start = new TimeSpan(9, 30, 0), End = new TimeSpan(10, 0, 0) },
                new { Name = "10:00-10:30", Start = new TimeSpan(10, 0, 0), End = new TimeSpan(10, 30, 0) },
                new { Name = "10:30-11:00", Start = new TimeSpan(10, 30, 0), End = new TimeSpan(11, 0, 0) },
                new { Name = "11:00-11:30", Start = new TimeSpan(11, 0, 0), End = new TimeSpan(11, 30, 0) },
                new { Name = "13:00-13:30", Start = new TimeSpan(13, 0, 0), End = new TimeSpan(13, 30, 0) },
                new { Name = "13:30-14:00", Start = new TimeSpan(13, 30, 0), End = new TimeSpan(14, 0, 0) },
                new { Name = "14:00-14:30", Start = new TimeSpan(14, 0, 0), End = new TimeSpan(14, 30, 0) },
                new { Name = "14:30-15:00", Start = new TimeSpan(14, 30, 0), End = new TimeSpan(15, 0, 0) }
            };

            foreach (var period in periods)
            {
                var periodData = _data.Where(x =>
                    x.Time.TimeOfDay >= period.Start &&
                    (x.Time.TimeOfDay < period.End ||
                     (IsSessionClose(period.End) && x.Time.TimeOfDay == period.End))).ToList();

                double buy = periodData.Where(x => x.IsBuy).Sum(x => x.Amount);
                double sell = periodData.Where(x => x.IsSell).Sum(x => x.Amount);
                double net = buy - sell;

                int rowIndex = gridPeriods.Rows.Add(
                    period.Name,
                    periodData.Count,
                    FormatAmountShort(buy),
                    FormatAmountShort(sell),
                    FormatAmountShort(net),
                    periodData.Count(x => x.FundMarker == "点火"),
                    periodData.Count(x => x.FundMarker == "砸盘"),
                    periodData.Count(x => x.BuyMarker == "买活跃"),
                    periodData.Count(x => x.BuyMarker == "承接好")
                );

                // 净买入颜色
                gridPeriods.Rows[rowIndex].Cells["Net"].Style.ForeColor =
                    net >= 0 ? ColorBuy : ColorSell;
                
                // 买入颜色
                gridPeriods.Rows[rowIndex].Cells["Buy"].Style.ForeColor = ColorBuy;
                // 卖出颜色
                gridPeriods.Rows[rowIndex].Cells["Sell"].Style.ForeColor = ColorSell;
            }
        }

        private static bool IsSessionClose(TimeSpan value)
        {
            return value == new TimeSpan(11, 30, 0) || value == new TimeSpan(15, 0, 0);
        }

        private void GridPeriods_MouseWheel(object sender, MouseEventArgs e)
        {
            int rowsToScroll = e.Delta > 0 ? -2 : 2;
            int newIndex = gridPeriods.FirstDisplayedScrollingRowIndex + rowsToScroll;

            if (newIndex < 0) newIndex = 0;
            if (newIndex >= gridPeriods.RowCount) newIndex = gridPeriods.RowCount - 1;

            if (gridPeriods.RowCount > 0 && newIndex >= 0)
            {
                gridPeriods.FirstDisplayedScrollingRowIndex = newIndex;
            }
        }

        private string FormatAmount(double amount)
        {
            if (Math.Abs(amount) >= 100000000)
                return string.Format("{0:F1}亿", amount / 100000000);
            return string.Format("{0:F0}万", amount / 10000);
        }

        private string FormatAmountShort(double amount)
        {
            if (Math.Abs(amount) >= 100000000)
                return string.Format("{0:F0}亿", amount / 100000000);
            if (Math.Abs(amount) >= 10000)
                return string.Format("{0:F0}万", amount / 10000);
            return "0";
        }
        
    }
}
