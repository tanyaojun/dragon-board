using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using THSBigOrder.Analytics;
using THSBigOrder.Filtering;
using THSBigOrder.Models;
using THSBigOrder.Refresh;

namespace THSBigOrder
{
    public partial class MainForm : Form
    {
        // Windows API for TDX memory reading
        [DllImport("kernel32.dll")]
        static extern IntPtr OpenProcess(int dwDesiredAccess, bool bInheritHandle, int dwProcessId);

        [DllImport("kernel32.dll")]
        static extern bool ReadProcessMemory(IntPtr hProcess, IntPtr lpBaseAddress, byte[] lpBuffer, int dwSize, out int lpNumberOfBytesRead);

        [DllImport("kernel32.dll")]
        static extern bool CloseHandle(IntPtr hObject);

        private const int PROCESS_VM_READ = 0x0010;
        private const int PROCESS_QUERY_INFORMATION = 0x0400;

        // 通达信内存配置
        private static readonly string[] TDX_PROCESS_NAMES = { "tdxw", "TdxW", "new_tdxw", "new_TdxW", "tdx", "TDX" };
        private const string TDX_MODULE_NAME = "Viewthem.dll";
        private const int TDX_BASE_OFFSET = 0x160A64;

        // 数据提供器
        private IMarketSnapshotProvider _dataProvider;
        private List<BigOrderItem> _allData = new List<BigOrderItem>();
        private List<BigOrderItem> _filteredData = new List<BigOrderItem>();
        private StockInfo _stockInfo;
        private MarketSnapshot _snapshot;
        private readonly RefreshCoordinator _refreshCoordinator = new RefreshCoordinator();
        private OrderSide _orderSide = OrderSide.All;
        private readonly Font _gridBoldFont;
        private readonly Font _filterBoldFont;
        private readonly Font _filterUnderlineFont;

        // 当前状态
        private string _currentStockCode = "002963";
        private int _currentMoney = 300000;

        // 定时器
        private System.Windows.Forms.Timer _refreshTimer;
        private System.Windows.Forms.Timer _titleTimer;
        private System.Windows.Forms.Timer _tdxTimer;
        private System.Windows.Forms.Timer _clockTimer;

        // 语音播报
        private VoiceService _voiceService;
        private HashSet<string> _announcedItems = new HashSet<string>();

        // 自定义滚动条
        private Panel _scrollTrack;
        private Panel _scrollThumb;
        private bool _isDragging = false;
        private int _dragStartY;
        private int _dragStartScrollIndex;

        // 颜色定义 - 完全匹配 Slayed03 原始版本
        // 原始代码位置: Slayed03\Decompiled\大单挖掘\MainForm.cs 第891-921行
        private readonly Color ColorMainBuy = Color.Red;           // 主动买 → 红色
        private readonly Color ColorMainSell = Color.Green;        // 主动卖 → 绿色
        private readonly Color ColorIgnite = Color.Violet;         // 点火 → 紫色 + 粗体
        private readonly Color ColorSmash = Color.LightGreen;      // 砸盘 → 浅绿色 + 粗体
        private readonly Color ColorSuperBig = Color.Yellow;       // 超大单(>1000万) → 黄色
        private readonly Color ColorDefault = Color.White;         // 默认 → 白色
        
        // 统计面板颜色（用于统计显示，与表格颜色保持一致）
        private readonly Color ColorBuyActive = Color.Violet;      // 买活跃统计显示 → 紫色（与点火同色系）
        private readonly Color ColorSellActive = Color.LightGreen; // 承接好统计显示 → 浅绿色（与砸盘同色系）

        public MainForm() : this(null, true)
        {
        }

        internal MainForm(IMarketSnapshotProvider dataProvider, bool initializeRuntime)
        {
            InitializeComponent();
            _gridBoldFont = new Font("微软雅黑", 9f, FontStyle.Bold);
            _filterBoldFont = new Font("Microsoft YaHei", 9f, FontStyle.Bold);
            _filterUnderlineFont = new Font("Microsoft YaHei", 9f, FontStyle.Bold | FontStyle.Underline);
            if (initializeRuntime) InitializeCustomComponents();
            else _dataProvider = dataProvider;
        }

        internal SplitContainer MainSplit => mainSplit;
        internal TabControl OrderTabs => orderTabs;
        internal bool ShowsLimitUpReason => ClientSize.Width >= 1100;
        internal bool ShowsSealRate => ClientSize.Width >= 1020;
        internal bool ShowsLastLimitTime => ClientSize.Width >= 1020;
        internal string BoundStockCode => _snapshot?.StockCode;

        internal Task RefreshStockAsync(string stockCode, bool forceForCodeChange)
        {
            _currentStockCode = stockCode;
            if (txtStockCode != null) txtStockCode.Text = stockCode;
            return RefreshDataAsync(forceForCodeChange);
        }

        private void InitializeCustomComponents()
        {
            _dataProvider = new THSBigOrderDataProvider();
            _voiceService = new VoiceService();

            _refreshTimer = new System.Windows.Forms.Timer();
            _refreshTimer.Interval = 6000;
            _refreshTimer.Tick += RefreshTimer_Tick;

            _titleTimer = new System.Windows.Forms.Timer();
            _titleTimer.Interval = 200;
            _titleTimer.Tick += TitleTimer_Tick;

            _tdxTimer = new System.Windows.Forms.Timer();
            _tdxTimer.Interval = 500;
            _tdxTimer.Tick += TdxTimer_Tick;
            _tdxTimer.Start();

            _clockTimer = new System.Windows.Forms.Timer();
            _clockTimer.Interval = 1000;
            _clockTimer.Tick += ClockTimer_Tick;
            _clockTimer.Start();

            SetupDataGridStyle();
            SetupCustomScrollBar();
        }

        private void SetupDataGridStyle()
        {
            // === DataGridView 完全匹配原始版本设置 ===
            // 原始代码: Slayed03\Decompiled\大单挖掘\MainForm.cs 第1846-1865行
            
            // 基础属性
            dataGridView1.AutoGenerateColumns = false;
            dataGridView1.AllowUserToAddRows = false;
            dataGridView1.AllowUserToResizeColumns = false;  // 原始: false
            dataGridView1.AllowUserToResizeRows = false;     // 原始: false
            dataGridView1.ReadOnly = true;                   // 原始: true
            dataGridView1.SelectionMode = DataGridViewSelectionMode.FullRowSelect;  // 原始
            dataGridView1.MultiSelect = false;
            dataGridView1.RowHeadersVisible = false;
            dataGridView1.ScrollBars = ScrollBars.None;      // 原始: None
            dataGridView1.BorderStyle = BorderStyle.None;    // 原始: None
            
            // 行高设置 - 原始版本第1858行: RowTemplate.Height = 20
            dataGridView1.RowTemplate.Height = 14;

            // 单元格样式 - 原始代码第443-461行 MainForm_Load
            dataGridView1.DefaultCellStyle.Font = new Font("微软雅黑", 7f);
            dataGridView1.DefaultCellStyle.ForeColor = Color.White;
            dataGridView1.DefaultCellStyle.BackColor = Color.Black;
            dataGridView1.DefaultCellStyle.SelectionBackColor = Color.Gray;
            dataGridView1.DefaultCellStyle.SelectionForeColor = Color.White;

            // 列头样式
            dataGridView1.ColumnHeadersDefaultCellStyle.Font = new Font("微软雅黑", 7f, FontStyle.Bold);
            dataGridView1.ColumnHeadersDefaultCellStyle.BackColor = Color.DimGray;
            dataGridView1.ColumnHeadersDefaultCellStyle.ForeColor = Color.White;
            dataGridView1.ColumnHeadersDefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleCenter;
            dataGridView1.ColumnHeadersBorderStyle = DataGridViewHeaderBorderStyle.Single;
            dataGridView1.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.AutoSize;  // 原始版本第1850行
            dataGridView1.EnableHeadersVisualStyles = false;
            
            // 背景和网格颜色
            dataGridView1.GridColor = Color.Black;
            dataGridView1.BackgroundColor = Color.Black;

            dataGridView1.Columns.Clear();
            // 完全匹配原始版本列顺序和样式
            // 原始版本使用 AutoSizeMode.AllCells 自动调整列宽
            dataGridView1.Columns.Add(new DataGridViewTextBoxColumn { 
                Name = "Time", 
                HeaderText = "时间", 
                AutoSizeMode = DataGridViewAutoSizeColumnMode.AllCells 
            });
            dataGridView1.Columns.Add(new DataGridViewTextBoxColumn { 
                Name = "Amount", 
                HeaderText = "金额", 
                AutoSizeMode = DataGridViewAutoSizeColumnMode.AllCells 
            });
            dataGridView1.Columns.Add(new DataGridViewTextBoxColumn { 
                Name = "Volume", 
                HeaderText = "手数", 
                AutoSizeMode = DataGridViewAutoSizeColumnMode.AllCells 
            });
            dataGridView1.Columns.Add(new DataGridViewTextBoxColumn { 
                Name = "Price", 
                HeaderText = "均价", 
                AutoSizeMode = DataGridViewAutoSizeColumnMode.AllCells 
            });
            dataGridView1.Columns.Add(new DataGridViewTextBoxColumn { 
                Name = "Type", 
                HeaderText = "买卖", 
                AutoSizeMode = DataGridViewAutoSizeColumnMode.AllCells  // 容纳"主动买"、"主动卖"
            });
            dataGridView1.Columns.Add(new DataGridViewTextBoxColumn { 
                Name = "Fund", 
                HeaderText = "资金", 
                AutoSizeMode = DataGridViewAutoSizeColumnMode.AllCells 
            });
            dataGridView1.Columns.Add(new DataGridViewTextBoxColumn { 
                Name = "Buy", 
                HeaderText = "买盘", 
                AutoSizeMode = DataGridViewAutoSizeColumnMode.AllCells 
            });
            
            // 设置时间列格式（原始版本: HH:mm:ss）
            dataGridView1.Columns["Time"].DefaultCellStyle.Format = "HH:mm:ss";

            foreach (DataGridViewColumn col in dataGridView1.Columns)
            {
                col.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleCenter;
                col.HeaderCell.Style.Alignment = DataGridViewContentAlignment.MiddleCenter;
            }

            dataGridView1.CellFormatting += DataGridView1_CellFormatting;
        }

        private void SetupCustomScrollBar()
        {
            // 创建滚动轨道（半透明背景）
            _scrollTrack = new Panel();
            _scrollTrack.Width = 6;
            _scrollTrack.BackColor = Color.FromArgb(30, 255, 255, 255);  // 半透明白色
            _scrollTrack.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Right;

            // 创建滚动滑块
            _scrollThumb = new Panel();
            _scrollThumb.Width = 6;
            _scrollThumb.Height = 50;
            _scrollThumb.BackColor = Color.FromArgb(80, 255, 255, 255);  // 半透明白色
            _scrollThumb.Cursor = Cursors.Hand;

            // 滑块事件
            _scrollThumb.MouseDown += ScrollThumb_MouseDown;
            _scrollThumb.MouseMove += ScrollThumb_MouseMove;
            _scrollThumb.MouseUp += ScrollThumb_MouseUp;
            _scrollThumb.MouseEnter += (s, e) => _scrollThumb.BackColor = Color.FromArgb(150, 255, 255, 255);
            _scrollThumb.MouseLeave += (s, e) => { if (!_isDragging) _scrollThumb.BackColor = Color.FromArgb(80, 255, 255, 255); };

            // 轨道点击事件
            _scrollTrack.MouseClick += ScrollTrack_MouseClick;
            _scrollTrack.MouseEnter += (s, e) => _scrollTrack.BackColor = Color.FromArgb(50, 255, 255, 255);
            _scrollTrack.MouseLeave += (s, e) => _scrollTrack.BackColor = Color.FromArgb(30, 255, 255, 255);

            // 添加到 DataGridView 的父容器
            _scrollTrack.Controls.Add(_scrollThumb);
            
            // 在 DataGridView 加载后定位滚动条
            dataGridView1.VisibleChanged += (s, e) => PositionScrollBar();
            dataGridView1.SizeChanged += (s, e) => PositionScrollBar();
            dataGridView1.RowsAdded += (s, e) => UpdateScrollThumb();
            dataGridView1.RowsRemoved += (s, e) => UpdateScrollThumb();
        }

        private void PositionScrollBar()
        {
            if (dataGridView1.Parent == null) return;
            
            // 将滚动条添加到 DataGridView 的父容器
            if (!dataGridView1.Parent.Controls.Contains(_scrollTrack))
            {
                dataGridView1.Parent.Controls.Add(_scrollTrack);
                _scrollTrack.BringToFront();
            }

            // 定位到 DataGridView 右侧内部
            _scrollTrack.Location = new Point(
                dataGridView1.Right - _scrollTrack.Width - 2,
                dataGridView1.Top + dataGridView1.ColumnHeadersHeight
            );
            _scrollTrack.Height = dataGridView1.Height - dataGridView1.ColumnHeadersHeight;
            
            UpdateScrollThumb();
        }

        private void UpdateScrollThumb()
        {
            if (_scrollTrack == null || _scrollThumb == null) return;
            if (dataGridView1.Rows.Count == 0)
            {
                _scrollThumb.Visible = false;
                return;
            }

            int visibleRows = dataGridView1.DisplayedRowCount(false);
            int totalRows = dataGridView1.Rows.Count;

            if (totalRows <= visibleRows)
            {
                _scrollThumb.Visible = false;
                return;
            }

            _scrollThumb.Visible = true;

            // 计算滑块高度（最小30像素）
            int trackHeight = _scrollTrack.Height;
            int thumbHeight = Math.Max(30, (int)((double)visibleRows / totalRows * trackHeight));
            _scrollThumb.Height = thumbHeight;

            // 计算滑块位置
            int firstRow = dataGridView1.FirstDisplayedScrollingRowIndex;
            int maxScroll = totalRows - visibleRows;
            if (maxScroll > 0)
            {
                int scrollableHeight = trackHeight - thumbHeight;
                int thumbTop = (int)((double)firstRow / maxScroll * scrollableHeight);
                _scrollThumb.Top = Math.Max(0, Math.Min(thumbTop, scrollableHeight));
            }
        }

        private void ScrollThumb_MouseDown(object sender, MouseEventArgs e)
        {
            if (e.Button == MouseButtons.Left)
            {
                _isDragging = true;
                _dragStartY = e.Y;
                _dragStartScrollIndex = dataGridView1.FirstDisplayedScrollingRowIndex;
                _scrollThumb.BackColor = Color.FromArgb(200, 255, 255, 255);
            }
        }

        private void ScrollThumb_MouseMove(object sender, MouseEventArgs e)
        {
            if (_isDragging && dataGridView1.Rows.Count > 0)
            {
                int deltaY = e.Y - _dragStartY + _scrollThumb.Top;
                int trackHeight = _scrollTrack.Height;
                int thumbHeight = _scrollThumb.Height;
                int scrollableHeight = trackHeight - thumbHeight;

                if (scrollableHeight > 0)
                {
                    int visibleRows = dataGridView1.DisplayedRowCount(false);
                    int totalRows = dataGridView1.Rows.Count;
                    int maxScroll = totalRows - visibleRows;

                    double ratio = (double)deltaY / scrollableHeight;
                    int newIndex = (int)(ratio * maxScroll);
                    newIndex = Math.Max(0, Math.Min(newIndex, maxScroll));

                    if (newIndex != dataGridView1.FirstDisplayedScrollingRowIndex)
                    {
                        dataGridView1.FirstDisplayedScrollingRowIndex = newIndex;
                        UpdateScrollThumb();
                    }
                }
            }
        }

        private void ScrollThumb_MouseUp(object sender, MouseEventArgs e)
        {
            _isDragging = false;
            _scrollThumb.BackColor = Color.FromArgb(80, 255, 255, 255);
        }

        private void ScrollTrack_MouseClick(object sender, MouseEventArgs e)
        {
            if (dataGridView1.Rows.Count == 0) return;

            int trackHeight = _scrollTrack.Height;
            int thumbHeight = _scrollThumb.Height;
            int scrollableHeight = trackHeight - thumbHeight;

            if (scrollableHeight > 0)
            {
                int visibleRows = dataGridView1.DisplayedRowCount(false);
                int totalRows = dataGridView1.Rows.Count;
                int maxScroll = totalRows - visibleRows;

                double ratio = (double)e.Y / trackHeight;
                int newIndex = (int)(ratio * maxScroll);
                newIndex = Math.Max(0, Math.Min(newIndex, maxScroll));

                dataGridView1.FirstDisplayedScrollingRowIndex = newIndex;
                UpdateScrollThumb();
            }
        }

        /// <summary>
        /// 获取整行的颜色 - 完全匹配原始版本的颜色规则
        /// 原始代码位置: Slayed03\Decompiled\大单挖掘\MainForm.cs dataGridView1_RowsAdded 方法
        /// 
        /// 颜色规则（按优先级从高到低）：
        /// 1. 主动卖 + 资金栏为空 → 绿色
        /// 2. 主动买 + 资金栏为空 → 红色
        /// 3. 资金栏为空 + 金额 > 1000万 → 黄色（超大单）
        /// 4. 资金 = "点火" → 紫色 + 粗体
        /// 5. 资金 = "砸盘" → 浅绿色 + 粗体
        /// 6. 其他 → 白色
        /// 
        /// 注意：原始版本中"买活跃"和"承接好"没有特殊颜色，使用默认白色
        /// </summary>
        private void DataGridView1_CellFormatting(object sender, DataGridViewCellFormattingEventArgs e)
        {
            if (e.RowIndex < 0 || e.RowIndex >= _filteredData.Count) return;

            var item = _filteredData[e.RowIndex];
            string fundMarker = item.FundMarker ?? "";
            double amountWan = item.Amount / 10000.0;  // 转换为万

            // 确定整行颜色（完全按照原始版本逻辑）
            Color rowColor = ColorDefault;
            bool isBold = false;

            // 规则1: 主动卖(Type=4) + 资金栏为空 → 绿色
            if (item.Type == 4 && fundMarker == "")
            {
                rowColor = ColorMainSell;  // Color.Green
            }
            // 规则2: 主动买(Type=2) + 资金栏为空 → 红色
            else if (item.Type == 2 && fundMarker == "")
            {
                rowColor = ColorMainBuy;  // Color.Red
            }
            // 规则3: 资金栏为空 + 金额 > 1000万 → 黄色
            else if (fundMarker == "" && amountWan > 1000.0)
            {
                rowColor = ColorSuperBig;  // Color.Yellow
            }
            // 规则4: 资金 = "点火" → 紫色 + 粗体
            else if (fundMarker == "点火")
            {
                rowColor = ColorIgnite;  // Color.Violet
                isBold = true;
            }
            // 规则5: 资金 = "砸盘" → 浅绿色 + 粗体
            else if (fundMarker == "砸盘")
            {
                rowColor = ColorSmash;  // Color.LightGreen
                isBold = true;
            }
            // 规则6: 其他 → 白色
            else
            {
                rowColor = ColorDefault;  // Color.White
            }

            // 设置整行颜色
            e.CellStyle.ForeColor = rowColor;
            
            // 设置粗体（点火和砸盘）
            if (isBold)
            {
                e.CellStyle.Font = _gridBoldFont;
            }
        }

        private async void MainForm_Load(object sender, EventArgs e)
        {
            // 恢复窗口大小
            WindowSettings.ApplyWindowSize(this, "MainForm");
            
            txtStockCode.Text = _currentStockCode;
            UpdateStatusLabel("正在加载数据...");
            await RefreshDataAsync();
            _titleTimer.Start();
        }
        
        private async Task RefreshDataAsync(bool forceForCodeChange = false)
        {
            var request = _refreshCoordinator.Begin(_currentStockCode, forceForCodeChange);
            if (!request.ShouldRun) return;
            try
            {
                lblStatus.Text = "刷新中...";
                lblStatus.ForeColor = Color.Yellow;
                var snapshot = await _dataProvider.LoadSnapshotAsync(request.StockCode, request.CancellationToken);
                if (!_refreshCoordinator.IsLatest(request.Generation, snapshot.StockCode)) return;
                BindSnapshot(snapshot);
            }
            catch (OperationCanceledException) when (request.CancellationToken.IsCancellationRequested) { }
            catch (Exception ex)
            {
                lblStatus.Text = "错误: " + ex.Message;
                lblStatus.ForeColor = Color.Red;
            }
            finally { _refreshCoordinator.Complete(request.Generation); }
        }

        private void BindSnapshot(MarketSnapshot snapshot)
        {
            _snapshot = snapshot;
            _stockInfo = new StockInfo
            {
                Code = snapshot.StockCode,
                Name = snapshot.Stock.Name,
                Price = snapshot.Stock.Price ?? 0,
                Change = snapshot.Stock.ChangePercent ?? 0,
                TurnoverRate = snapshot.Stock.TurnoverRate ?? 0,
                VolumeRatio = snapshot.Stock.VolumeRatio ?? 0,
                TotalAmount = snapshot.Stock.TotalAmount ?? 0,
            };
            _allData = snapshot.Orders.ToList();
            _dataProvider.CalculateMarkers(_allData);
            _allData = _allData.OrderByDescending(item => item.Time).ToList();
            ApplyFilter();
            UpdateDataGrid();
            UpdateStatistics();
            UpdateStockInfo();
            BindSnapshotLabels(snapshot);
            bigOrderChart.SetSnapshot(snapshot, new BigOrderSeriesBuilder().Build(snapshot.Orders));
            CheckAndAnnounce();
            lblStatus.Text = string.Format("共 {0} 条", _filteredData.Count);
            lblStatus.ForeColor = snapshot.BigOrderFreshness == DataFreshness.Fresh ? Color.LightGreen : Color.Orange;
            toolStripStatusLabel2.Text = "数据时间: " + snapshot.BigOrderFetchedAt.ToString("yyyy-MM-dd HH:mm:ss");
        }

        private void BindSnapshotLabels(MarketSnapshot snapshot)
        {
            lblPrice.Text = "现价 " + FormatNullable(snapshot.Stock.Price, "F2");
            lblMainBuy.Text = "主买 " + FormatAmount(snapshot.MainFunds.MainBuy);
            lblMainSell.Text = "主卖 " + FormatAmount(snapshot.MainFunds.MainSell);
            lblMainNet.Text = "主净 " + FormatAmount(snapshot.MainFunds.NetAmount);
            lblSealAmount.Text = "封单 " + FormatAmount(snapshot.LimitUp.SealAmount);
            lblOpenCount.Text = "开板 " + (snapshot.LimitUp.OpenCount.HasValue ? snapshot.LimitUp.OpenCount.Value.ToString() : "-");
            lblHighDays.Text = "连板 " + (snapshot.LimitUp.HighDays ?? "-");
            lblSealRate.Text = "封板率 " + (snapshot.LimitUp.SuccessRate.HasValue ? (snapshot.LimitUp.SuccessRate.Value * 100).ToString("F1") + "%" : "-");
            lblLimitUpReason.Text = snapshot.LimitUpFreshness == DataFreshness.Failed ? "涨停数据不可用" : snapshot.LimitUpFreshness == DataFreshness.Missing ? "非涨停池" : "涨停原因 " + (snapshot.LimitUp.ReasonType ?? "-");
            lblLastLimitTime.Text = "末封 " + (snapshot.LimitUp.LastLimitTime ?? "-");
            lblFreshness.Text = snapshot.BigOrderFreshness == DataFreshness.Fresh ? "数据实时" : snapshot.BigOrderFreshness == DataFreshness.Stale ? "数据陈旧" : "代理不可用";
            lblFreshness.ForeColor = snapshot.BigOrderFreshness == DataFreshness.Fresh ? Color.LightGreen : Color.Orange;
        }

        private static string FormatNullable(double? value, string format) => value.HasValue ? value.Value.ToString(format) : "-";
        private static string FormatAmount(double? value)
        {
            if (!value.HasValue) return "-";
            return Math.Abs(value.Value) >= 100000000 ? (value.Value / 100000000).ToString("F2") + "亿" : (value.Value / 10000).ToString("F0") + "万";
        }

        private void ApplyFilter()
        {
            _filteredData = OrderFilter.Apply(_allData, _currentMoney, _orderSide, _specialFilter);
        }

        private void UpdateDataGrid()
        {
            dataGridView1.Rows.Clear();
            foreach (var item in _filteredData)
            {
                // 列顺序：时间、金额、手数、均价、买卖、资金、买盘
                dataGridView1.Rows.Add(
                    item.TimeStr,
                    item.AmountStr,
                    item.Volume.ToString("F0"),  // 原始版本不带逗号分隔符
                    item.Price.ToString("F2"),
                    item.TypeName,
                    item.FundMarker,
                    item.BuyMarker
                );
            }
        }

        private void UpdateStatistics()
        {
            if (_filteredData == null || _filteredData.Count == 0)
            {
                lblBuyTotal.Text = "买入: 0万";
                lblSellTotal.Text = "卖出: 0万";
                lblNetBuy.Text = "净买: 0万";
                lblIgniteCount.Text = "点火: 0";
                lblSmashCount.Text = "砸盘: 0";
                lblBuyActive.Text = "买活跃: 0";
                lblSellActive.Text = "承接好: 0";
                return;
            }

            double buyTotal = _filteredData.Where(x => x.IsBuy).Sum(x => x.Amount);
            double sellTotal = _filteredData.Where(x => x.IsSell).Sum(x => x.Amount);
            double netBuy = buyTotal - sellTotal;

            int igniteCount = _filteredData.Count(x => x.FundMarker == "点火");
            int smashCount = _filteredData.Count(x => x.FundMarker == "砸盘");
            int buyActiveCount = _filteredData.Count(x => x.BuyMarker == "买活跃");
            int sellActiveCount = _filteredData.Count(x => x.BuyMarker == "承接好");

            lblBuyTotal.Text = string.Format("买入: {0:F0}万", buyTotal / 10000);
            lblBuyTotal.ForeColor = ColorMainBuy;

            lblSellTotal.Text = string.Format("卖出: {0:F0}万", sellTotal / 10000);
            lblSellTotal.ForeColor = ColorMainSell;

            lblNetBuy.Text = string.Format("净买: {0:F0}万", netBuy / 10000);
            lblNetBuy.ForeColor = netBuy >= 0 ? ColorMainBuy : ColorMainSell;

            lblIgniteCount.Text = "点火: " + igniteCount;
            lblIgniteCount.ForeColor = ColorIgnite;

            lblSmashCount.Text = "砸盘: " + smashCount;
            lblSmashCount.ForeColor = ColorSmash;

            lblBuyActive.Text = "买活跃: " + buyActiveCount;
            lblBuyActive.ForeColor = ColorBuyActive;

            lblSellActive.Text = "承接好: " + sellActiveCount;
            lblSellActive.ForeColor = ColorSellActive;
        }

        private void UpdateStockInfo()
        {
            if (_stockInfo == null || _snapshot == null)
            {
                lblStockName.Text = _currentStockCode;
                lblChange.Text = "涨幅: --";
                lblTurnover.Text = "换手: --";
                lblVolumeRatio.Text = "量比: --";
                lblTotalAmount.Text = "成交: --";
                return;
            }

            // 第一行：股票名称 + 涨幅 + 量比
            lblStockName.Text = _stockInfo.Name;

            if (_snapshot.QuoteFreshness == DataFreshness.Failed || _snapshot.QuoteFreshness == DataFreshness.Missing)
            {
                lblChange.Text = "涨幅: -";
                lblTurnover.Text = "换手: -";
                lblVolumeRatio.Text = "量比: -";
                lblTotalAmount.Text = "成交: -";
                return;
            }

            lblChange.Text = string.Format("涨幅: {0:F1}%", _stockInfo.Change);
            lblChange.ForeColor = _stockInfo.Change >= 0 ? ColorMainBuy : ColorMainSell;

            lblVolumeRatio.Text = string.Format("量比: {0:F2}", _stockInfo.VolumeRatio);

            // 第二行：股票代码 + 换手 + 成交
            lblTurnover.Text = string.Format("换手: {0:F1}%", _stockInfo.TurnoverRate);

            double totalAmount = _stockInfo.TotalAmount;
            string amountStr = totalAmount >= 100000000
                ? string.Format("{0:F2}亿", totalAmount / 100000000)
                : string.Format("{0:F0}万", totalAmount / 10000);
            lblTotalAmount.Text = "成交: " + amountStr;
        }

        private void CheckAndAnnounce()
        {
            if (_filteredData == null || _filteredData.Count == 0) return;
            if (_voiceService == null || !_voiceService.Enabled) return;

            // 只检查最近的数据（最新10条）
            var recentData = _filteredData.Take(10).ToList();

            foreach (var item in recentData)
            {
                // 用时间+金额作为唯一标识，避免重复播报
                string key = _currentStockCode + "_" + item.Time.ToString("HHmmss") + "_" + item.Type + "_" + item.Amount.ToString("F0");
                if (_announcedItems.Contains(key)) continue;

                _announcedItems.Add(key);

                // 限制已播报列表大小
                if (_announcedItems.Count > 1000)
                {
                    _announcedItems.Clear();
                }

                // 播报
                if (item.FundMarker == "点火")
                {
                    _voiceService.AnnounceIgnite(item.Amount);
                    return;  // 每次只播报一条
                }
                else if (item.FundMarker == "砸盘")
                {
                    _voiceService.AnnounceSmash(item.Amount);
                    return;
                }
                else if (item.BuyMarker == "买活跃")
                {
                    _voiceService.AnnounceBuyActive();
                    return;
                }
                else if (item.BuyMarker == "承接好")
                {
                    _voiceService.AnnounceGoodSupport();
                    return;
                }
            }
        }

        private void UpdateScrollText()
        {
            // 滚动标题已禁用
        }

        private void UpdateStatusLabel(string text)
        {
            lblStatus.Text = text;
        }

        private async void RefreshTimer_Tick(object sender, EventArgs e)
        {
            await RefreshDataAsync();
        }

        private void TitleTimer_Tick(object sender, EventArgs e)
        {
            // 标题滚动已禁用，保持固定标题
        }

        private void TdxTimer_Tick(object sender, EventArgs e)
        {
            if (chkLockCode.Checked) return;
            if (!chkFollowTdx.Checked) return;

            try
            {
                var tdxProcess = FindTdxProcess();
                if (tdxProcess == null)
                {
                    toolStripStatusLabel1.Text = "未检测到通达信";
                    toolStripStatusLabel1.ForeColor = Color.Gray;
                    return;
                }

                string stockCode = ReadTdxStockCode();

                if (!string.IsNullOrEmpty(stockCode))
                {
                    toolStripStatusLabel1.Text = string.Format("已连接: {0} (内存)", tdxProcess.ProcessName);
                    toolStripStatusLabel1.ForeColor = Color.LightGreen;

                    if (stockCode != _currentStockCode)
                    {
                        _currentStockCode = stockCode;
                        txtStockCode.Text = stockCode;
                        var _ = RefreshDataAsync();
                    }
                    return;
                }

                toolStripStatusLabel1.Text = string.Format("已连接: {0} (剪贴板)", tdxProcess.ProcessName);
                toolStripStatusLabel1.ForeColor = Color.FromArgb(100, 180, 255);

                if (Clipboard.ContainsText())
                {
                    string clipText = Clipboard.GetText().Trim();
                    if (clipText.Length == 6 && clipText.All(char.IsDigit))
                    {
                        if (clipText != _currentStockCode)
                        {
                            _currentStockCode = clipText;
                            txtStockCode.Text = clipText;
                            var _ = RefreshDataAsync();
                        }
                    }
                }
            }
            catch
            {
            }
        }

        private Process FindTdxProcess()
        {
            foreach (var name in TDX_PROCESS_NAMES)
            {
                var processes = Process.GetProcessesByName(name);
                if (processes.Length > 0)
                    return processes[0];
            }

            var allProcesses = Process.GetProcesses();
            foreach (var p in allProcesses)
            {
                try
                {
                    if (p.MainWindowTitle.Contains("通达信"))
                        return p;
                }
                catch { }
            }

            return null;
        }

        private string ReadTdxStockCode()
        {
            try
            {
                var process = FindTdxProcess();
                if (process == null) return null;

                IntPtr hProcess = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, false, process.Id);
                if (hProcess == IntPtr.Zero) return null;

                try
                {
                    ProcessModule targetModule = null;
                    try
                    {
                        foreach (ProcessModule module in process.Modules)
                        {
                            if (module.ModuleName.Equals(TDX_MODULE_NAME, StringComparison.OrdinalIgnoreCase))
                            {
                                targetModule = module;
                                break;
                            }
                        }
                    }
                    catch { }

                    if (targetModule != null)
                    {
                        IntPtr targetAddress = IntPtr.Add(targetModule.BaseAddress, TDX_BASE_OFFSET);
                        string code = ReadMemoryAsStockCode(hProcess, targetAddress);
                        if (!string.IsNullOrEmpty(code)) return code;
                    }

                    if (process.MainModule != null)
                    {
                        int[] offsets = { 0x160A64, 0x15FA64, 0x161A64, 0x160000 };
                        foreach (var offset in offsets)
                        {
                            IntPtr targetAddress = IntPtr.Add(process.MainModule.BaseAddress, offset);
                            string code = ReadMemoryAsStockCode(hProcess, targetAddress);
                            if (!string.IsNullOrEmpty(code)) return code;
                        }
                    }
                }
                finally
                {
                    CloseHandle(hProcess);
                }
            }
            catch
            {
            }

            return null;
        }

        private string ReadMemoryAsStockCode(IntPtr hProcess, IntPtr address)
        {
            byte[] buffer = new byte[16];
            int bytesRead;

            if (ReadProcessMemory(hProcess, address, buffer, buffer.Length, out bytesRead) && bytesRead > 0)
            {
                string result = Encoding.ASCII.GetString(buffer).TrimEnd('\0');
                string code = new string(result.TakeWhile(c => char.IsDigit(c) || char.IsLetter(c)).Take(6).ToArray());

                if (code.Length == 6 && code.All(char.IsDigit))
                {
                    return code;
                }
            }

            return null;
        }

        private void ClockTimer_Tick(object sender, EventArgs e)
        {
            toolStripStatusLabel3.Text = DateTime.Now.ToString("HH:mm:ss");
        }

        private void dataGridView1_MouseWheel(object sender, MouseEventArgs e)
        {
            // 原始版本: 每次滚动2行（第874-888行）
            if (dataGridView1.Rows.Count <= 0) return;
            
            if (e.Delta > 0)
            {
                // 向上滚动
                if (dataGridView1.FirstDisplayedScrollingRowIndex - 2 < 0)
                    dataGridView1.FirstDisplayedScrollingRowIndex = 0;
                else
                    dataGridView1.FirstDisplayedScrollingRowIndex -= 2;
            }
            else
            {
                // 向下滚动
                dataGridView1.FirstDisplayedScrollingRowIndex += 2;
            }
            
            // 同步更新自定义滚动条
            UpdateScrollThumb();
        }

        private void chkTopMost_CheckedChanged(object sender, EventArgs e)
        {
            this.TopMost = chkTopMost.Checked;
        }

        private void chkVoice_CheckedChanged(object sender, EventArgs e)
        {
            if (_voiceService != null)
            {
                _voiceService.Enabled = chkVoice.Checked;
                
                // 勾选时播报测试
                if (chkVoice.Checked)
                {
                    _voiceService.AnnounceIgnite(5000000);  // 测试：点火500万
                }
            }
        }

        private async void btnRefresh_Click(object sender, EventArgs e)
        {
            var stockCode = txtStockCode.Text.Trim();
            var changed = stockCode != _currentStockCode;
            _specialFilter = "";
            await RefreshStockAsync(stockCode, changed);
        }

        private void OrderTabs_SelectedIndexChanged(object sender, EventArgs e)
        {
            _orderSide = orderTabs.SelectedIndex == 1 ? OrderSide.Buy : orderTabs.SelectedIndex == 2 ? OrderSide.Sell : OrderSide.All;
            var page = orderTabs.SelectedTab;
            if (page != null && dataGridView1.Parent != page) page.Controls.Add(dataGridView1);
            ApplyFilterAndRefreshUI();
        }

        protected override void OnClientSizeChanged(EventArgs e)
        {
            base.OnClientSizeChanged(e);
            if (mainSplit == null || ClientSize.Width <= 0) return;
            var desired = Math.Max(mainSplit.Panel1MinSize, Math.Min((int)(ClientSize.Width * 0.72), ClientSize.Width - mainSplit.Panel2MinSize - mainSplit.SplitterWidth));
            if (desired > 0) mainSplit.SplitterDistance = desired;
            if (lblLimitUpReason != null) lblLimitUpReason.Visible = ClientSize.Width >= 1100;
            if (lblSealRate != null) lblSealRate.Visible = ClientSize.Width >= 1020;
            if (lblLastLimitTime != null) lblLastLimitTime.Visible = ClientSize.Width >= 1020;
            if (lblReasonHint != null) lblReasonHint.Visible = ClientSize.Width < 1100;
        }

        private void btnAnalysis_Click(object sender, EventArgs e)
        {
            if (_filteredData == null || _filteredData.Count == 0)
            {
                MessageBox.Show("请先获取数据", "提示", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            string stockName = _stockInfo != null ? _stockInfo.Name : _currentStockCode;
            // 传递筛选后的数据和筛选条件
            string filterInfo = _currentMoney > 0 ? string.Format(">{0}万", _currentMoney / 10000) : "";
            var form = new AnalysisForm(_currentStockCode, stockName, _filteredData, filterInfo);
            form.ShowDialog(this);
        }

        private void txtStockCode_KeyPress(object sender, KeyPressEventArgs e)
        {
            if (e.KeyChar == (char)Keys.Enter)
            {
                e.Handled = true;
                btnRefresh.PerformClick();
            }
        }

        private void chkAutoRefresh_CheckedChanged(object sender, EventArgs e)
        {
            if (chkAutoRefresh.Checked)
            {
                _refreshTimer.Start();
            }
            else
            {
                _refreshTimer.Stop();
            }
        }

        private void btn30W_Click(object sender, EventArgs e)
        {
            _currentMoney = 300000;
            UpdateFilterButtons((Button)sender);
            ApplyFilterAndRefreshUI();
        }

        private void btn50W_Click(object sender, EventArgs e)
        {
            _currentMoney = 500000;
            UpdateFilterButtons((Button)sender);
            ApplyFilterAndRefreshUI();
        }

        private void btn100W_Click(object sender, EventArgs e)
        {
            _currentMoney = 1000000;
            UpdateFilterButtons((Button)sender);
            ApplyFilterAndRefreshUI();
        }

        private void btn300W_Click(object sender, EventArgs e)
        {
            _currentMoney = 3000000;
            UpdateFilterButtons((Button)sender);
            ApplyFilterAndRefreshUI();
        }

        private void btn1000W_Click(object sender, EventArgs e)
        {
            _currentMoney = 10000000;
            UpdateFilterButtons((Button)sender);
            ApplyFilterAndRefreshUI();
        }

        private void btn500W_Click(object sender, EventArgs e)
        {
            _currentMoney = 5000000;
            UpdateFilterButtons((Button)sender);
            ApplyFilterAndRefreshUI();
        }

        private void btn700W_Click(object sender, EventArgs e)
        {
            _currentMoney = 7000000;
            UpdateFilterButtons((Button)sender);
            ApplyFilterAndRefreshUI();
        }

        // 特殊筛选类型
        private string _specialFilter = "";

        private void lblIgniteCount_Click(object sender, EventArgs e)
        {
            if (_specialFilter == "点火")
            {
                _specialFilter = "";
                lblIgniteCount.Font = _filterBoldFont;
            }
            else
            {
                _specialFilter = "点火";
                ResetSpecialFilterLabels();
                lblIgniteCount.Font = _filterUnderlineFont;
            }
            ApplyFilterAndRefreshUI();
        }

        private void lblSmashCount_Click(object sender, EventArgs e)
        {
            if (_specialFilter == "砸盘")
            {
                _specialFilter = "";
                lblSmashCount.Font = _filterBoldFont;
            }
            else
            {
                _specialFilter = "砸盘";
                ResetSpecialFilterLabels();
                lblSmashCount.Font = _filterUnderlineFont;
            }
            ApplyFilterAndRefreshUI();
        }

        private void lblBuyActive_Click(object sender, EventArgs e)
        {
            if (_specialFilter == "买活跃")
            {
                _specialFilter = "";
                lblBuyActive.Font = _filterBoldFont;
            }
            else
            {
                _specialFilter = "买活跃";
                ResetSpecialFilterLabels();
                lblBuyActive.Font = _filterUnderlineFont;
            }
            ApplyFilterAndRefreshUI();
        }

        private void lblSellActive_Click(object sender, EventArgs e)
        {
            if (_specialFilter == "承接好")
            {
                _specialFilter = "";
                lblSellActive.Font = _filterBoldFont;
            }
            else
            {
                _specialFilter = "承接好";
                ResetSpecialFilterLabels();
                lblSellActive.Font = _filterUnderlineFont;
            }
            ApplyFilterAndRefreshUI();
        }

        private void ResetSpecialFilterLabels()
        {
            lblIgniteCount.Font = _filterBoldFont;
            lblSmashCount.Font = _filterBoldFont;
            lblBuyActive.Font = _filterBoldFont;
            lblSellActive.Font = _filterBoldFont;
        }

        private void ApplyFilterAndRefreshUI()
        {
            ApplyFilter();
            UpdateDataGrid();
            UpdateStatistics();
            UpdateScrollText();
            lblStatus.Text = string.Format("共 {0} 条", _filteredData.Count);
        }

        private void UpdateFilterButtons(Button activeBtn)
        {
            // 清除特殊筛选
            _specialFilter = "";
            ResetSpecialFilterLabels();

            var filterButtons = new Button[] { btn30W, btn50W, btn100W, btn300W, btn500W, btn700W, btn1000W };
            foreach (var btn in filterButtons)
            {
                if (btn == activeBtn)
                {
                    btn.BackColor = Color.FromArgb(50, 90, 140);
                    btn.ForeColor = Color.White;
                }
                else
                {
                    btn.BackColor = Color.FromArgb(35, 35, 40);
                    btn.ForeColor = Color.Silver;
                }
            }
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            // 保存窗口大小
            if (this.WindowState == FormWindowState.Normal)
            {
                WindowSettings.SaveWindowSize("MainForm", this.Size);
            }

            if (_refreshTimer != null) { _refreshTimer.Stop(); _refreshTimer.Dispose(); }
            if (_titleTimer != null) { _titleTimer.Stop(); _titleTimer.Dispose(); }
            if (_tdxTimer != null) { _tdxTimer.Stop(); _tdxTimer.Dispose(); }
            if (_clockTimer != null) { _clockTimer.Stop(); _clockTimer.Dispose(); }
            var disposableProvider = _dataProvider as IDisposable;
            if (disposableProvider != null) { disposableProvider.Dispose(); }
            if (_voiceService != null) { _voiceService.Dispose(); }
            _refreshCoordinator.Dispose();
            _gridBoldFont.Dispose();
            _filterBoldFont.Dispose();
            _filterUnderlineFont.Dispose();
            base.OnFormClosing(e);
        }
    }
}
