namespace THSBigOrder
{
    partial class MainForm
    {
    private System.ComponentModel.IContainer components = null;

    protected override void Dispose(bool disposing)
    {
        if (disposing && (components != null))
        {
            components.Dispose();
        }
        base.Dispose(disposing);
    }

    #region Windows Form Designer generated code

    private void InitializeComponent()
    {
        // 主容器
        this.panel1 = new System.Windows.Forms.Panel();
        this.panelTop = new System.Windows.Forms.Panel();
        this.panelStats = new System.Windows.Forms.Panel();
        this.panelFilter = new System.Windows.Forms.Panel();
        this.dataGridView1 = new System.Windows.Forms.DataGridView();

        // 股票信息控件
        this.lblStockName = new System.Windows.Forms.Label();
        this.lblChange = new System.Windows.Forms.Label();
        this.lblTurnover = new System.Windows.Forms.Label();
        this.lblVolumeRatio = new System.Windows.Forms.Label();
        this.lblTotalAmount = new System.Windows.Forms.Label();

        // 统计控件
        this.lblBuyTotal = new System.Windows.Forms.Label();
        this.lblSellTotal = new System.Windows.Forms.Label();
        this.lblNetBuy = new System.Windows.Forms.Label();
        this.lblIgniteCount = new System.Windows.Forms.Label();
        this.lblSmashCount = new System.Windows.Forms.Label();
        this.lblBuyActive = new System.Windows.Forms.Label();
        this.lblSellActive = new System.Windows.Forms.Label();

        // 操作控件
        this.txtStockCode = new System.Windows.Forms.TextBox();
        this.btnRefresh = new System.Windows.Forms.Button();
        this.chkAutoRefresh = new System.Windows.Forms.CheckBox();
        this.chkFollowTdx = new System.Windows.Forms.CheckBox();
        this.chkLockCode = new System.Windows.Forms.CheckBox();
        this.chkTopMost = new System.Windows.Forms.CheckBox();
        this.lblStatus = new System.Windows.Forms.Label();
        this.statusStrip1 = new System.Windows.Forms.StatusStrip();
        this.toolStripStatusLabel1 = new System.Windows.Forms.ToolStripStatusLabel();
        this.toolStripStatusLabel2 = new System.Windows.Forms.ToolStripStatusLabel();
        this.toolStripStatusLabel3 = new System.Windows.Forms.ToolStripStatusLabel();

        // 筛选按钮
        this.btn30W = new System.Windows.Forms.Button();
        this.btn50W = new System.Windows.Forms.Button();
        this.btn100W = new System.Windows.Forms.Button();
        this.btn300W = new System.Windows.Forms.Button();
        this.btn1000W = new System.Windows.Forms.Button();

        // 初始化
        ((System.ComponentModel.ISupportInitialize)(this.dataGridView1)).BeginInit();
        this.SuspendLayout();

        // === Panel 配置（紧凑布局）===

        // panelTop - 顶部信息区（增加高度确保按钮显示）
        this.panelTop.BackColor = System.Drawing.Color.Black;  // 纯黑背景，颜色更鲜明
        this.panelTop.Dock = System.Windows.Forms.DockStyle.Top;
        this.panelTop.Height = 78;

        // panelStats - 统计区（与表格宽度对齐 363px）
        this.panelStats.BackColor = System.Drawing.Color.Black;  // 纯黑背景
        this.panelStats.Dock = System.Windows.Forms.DockStyle.Top;
        this.panelStats.Height = 42;

        // panelFilter - 筛选区
        this.panelFilter.BackColor = System.Drawing.Color.Black;  // 纯黑背景
        this.panelFilter.Dock = System.Windows.Forms.DockStyle.Top;
        this.panelFilter.Height = 50;

        // === 三列布局（与表格宽度对齐）===
        // 表格列宽: 58+55+55+50+50+45+50 ≈ 363px
        // 第一列X=5: 股票名称、输入框 (宽75)
        // 第二列X=85: 涨幅换手、量比成交、刷分+自动刷新
        // 第三列X=300: 窗口置顶、固定代码、跟随通达信

        int col1 = 5;
        int col2 = 85;
        int col3 = 300;
        int row1 = 3;
        int row2 = 25;
        int row3 = 47;

        // === 第一列：股票名称、输入框 ===
        // lblStockName（黄色）
        this.lblStockName.AutoSize = true;
        this.lblStockName.Font = new System.Drawing.Font("Microsoft YaHei", 12F, System.Drawing.FontStyle.Bold);
        this.lblStockName.ForeColor = System.Drawing.Color.FromArgb(255, 215, 0);  // 黄色
        this.lblStockName.Location = new System.Drawing.Point(col1, row1);
        this.lblStockName.Text = "股票名称";

        // txtStockCode (输入框，与股票名称拉开距离)
        this.txtStockCode.BackColor = System.Drawing.Color.FromArgb(40, 40, 50);
        this.txtStockCode.BorderStyle = System.Windows.Forms.BorderStyle.FixedSingle;
        this.txtStockCode.Font = new System.Drawing.Font("Microsoft YaHei", 10F);
        this.txtStockCode.ForeColor = System.Drawing.Color.White;
        this.txtStockCode.Location = new System.Drawing.Point(col1, row2 + 8);
        this.txtStockCode.Size = new System.Drawing.Size(75, 25);
        this.txtStockCode.TextAlign = System.Windows.Forms.HorizontalAlignment.Center;
        this.txtStockCode.KeyPress += new System.Windows.Forms.KeyPressEventHandler(this.txtStockCode_KeyPress);

        // === 第二列：数据信息 + 操作按钮 ===
        // lblChange (涨幅) - 第一行
        this.lblChange.AutoSize = true;
        this.lblChange.Font = new System.Drawing.Font("Microsoft YaHei", 9F, System.Drawing.FontStyle.Bold);
        this.lblChange.ForeColor = System.Drawing.Color.FromArgb(255, 80, 80);
        this.lblChange.Location = new System.Drawing.Point(col2, row1 + 2);
        this.lblChange.Text = "涨幅: --";

        // lblTurnover (换手) - 第一行
        this.lblTurnover.AutoSize = true;
        this.lblTurnover.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.lblTurnover.ForeColor = System.Drawing.Color.Silver;
        this.lblTurnover.Location = new System.Drawing.Point(col2 + 100, row1 + 2);
        this.lblTurnover.Text = "换手: --";

        // lblVolumeRatio (量比) - 第二行
        this.lblVolumeRatio.AutoSize = true;
        this.lblVolumeRatio.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.lblVolumeRatio.ForeColor = System.Drawing.Color.Silver;
        this.lblVolumeRatio.Location = new System.Drawing.Point(col2, row2 + 3);
        this.lblVolumeRatio.Text = "量比: --";

        // lblTotalAmount (成交) - 第二行
        this.lblTotalAmount.AutoSize = true;
        this.lblTotalAmount.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.lblTotalAmount.ForeColor = System.Drawing.Color.Silver;
        this.lblTotalAmount.Location = new System.Drawing.Point(col2 + 100, row2 + 3);
        this.lblTotalAmount.Text = "成交: --";

        // lblRefresh - 第三行（用Label代替Button）
        this.lblRefresh = new System.Windows.Forms.Label();
        this.lblRefresh.AutoSize = true;
        this.lblRefresh.Font = new System.Drawing.Font("Microsoft YaHei", 9F, System.Drawing.FontStyle.Bold);
        this.lblRefresh.ForeColor = System.Drawing.Color.FromArgb(100, 180, 255);
        this.lblRefresh.Location = new System.Drawing.Point(col2, row3 + 3);
        this.lblRefresh.Text = "刷新";
        this.lblRefresh.Cursor = System.Windows.Forms.Cursors.Hand;
        this.lblRefresh.Click += new System.EventHandler(this.btnRefresh_Click);

        // lblAnalysis - 第三行（用Label代替Button）
        this.lblAnalysis = new System.Windows.Forms.Label();
        this.lblAnalysis.AutoSize = true;
        this.lblAnalysis.Font = new System.Drawing.Font("Microsoft YaHei", 9F, System.Drawing.FontStyle.Bold);
        this.lblAnalysis.ForeColor = System.Drawing.Color.FromArgb(255, 180, 100);
        this.lblAnalysis.Location = new System.Drawing.Point(col2 + 38, row3 + 3);
        this.lblAnalysis.Text = "分析";
        this.lblAnalysis.Cursor = System.Windows.Forms.Cursors.Hand;
        this.lblAnalysis.Click += new System.EventHandler(this.btnAnalysis_Click);

        // chkVoice - 语音播报开关（在分析后面）
        this.chkVoice = new System.Windows.Forms.CheckBox();
        this.chkVoice.AutoSize = true;
        this.chkVoice.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.chkVoice.ForeColor = System.Drawing.Color.FromArgb(255, 200, 100);
        this.chkVoice.Location = new System.Drawing.Point(col2 + 75, row3 + 3);
        this.chkVoice.Text = "语音";
        this.chkVoice.Checked = false;
        this.chkVoice.CheckedChanged += new System.EventHandler(this.chkVoice_CheckedChanged);

        // 保留原按钮变量但不使用（保持兼容）
        this.btnRefresh.Visible = false;
        this.btnAnalysis = new System.Windows.Forms.Button();
        this.btnAnalysis.Visible = false;

        // chkAutoRefresh - 第三行（在语音后面）
        this.chkAutoRefresh.AutoSize = true;
        this.chkAutoRefresh.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.chkAutoRefresh.ForeColor = System.Drawing.Color.Silver;
        this.chkAutoRefresh.Location = new System.Drawing.Point(col2 + 145, row3 + 3);
        this.chkAutoRefresh.Text = "自动刷新";
        this.chkAutoRefresh.CheckedChanged += new System.EventHandler(this.chkAutoRefresh_CheckedChanged);

        // === 第三列：复选框（往右移动）===
        int col3Offset = 30;  // 右移偏移量
        
        // chkTopMost (窗口置顶) - 第一行
        this.chkTopMost.AutoSize = true;
        this.chkTopMost.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.chkTopMost.ForeColor = System.Drawing.Color.Silver;
        this.chkTopMost.Location = new System.Drawing.Point(col3 + col3Offset, row1 + 2);
        this.chkTopMost.Text = "窗口置顶";
        this.chkTopMost.CheckedChanged += new System.EventHandler(this.chkTopMost_CheckedChanged);

        // chkLockCode (固定代码) - 第二行
        this.chkLockCode.AutoSize = true;
        this.chkLockCode.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.chkLockCode.ForeColor = System.Drawing.Color.Silver;
        this.chkLockCode.Location = new System.Drawing.Point(col3 + col3Offset, row2 + 3);
        this.chkLockCode.Text = "固定代码";

        // chkFollowTdx - 第三行
        this.chkFollowTdx.AutoSize = true;
        this.chkFollowTdx.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.chkFollowTdx.ForeColor = System.Drawing.Color.Silver;
        this.chkFollowTdx.Location = new System.Drawing.Point(col3 + col3Offset, row3 + 2);
        this.chkFollowTdx.Text = "跟随通达信";
        this.chkFollowTdx.Checked = true;

        // === 统计控件（两行显示，与表格宽度363px对齐）===
        // 表格宽度: 58+55+55+50+50+45+50 = 363px
        // 第一行分3等份: 约120px一份
        // 第二行分4等份: 约90px一份

        // 第一行：买入、卖出、净买入（可点击）
        // lblBuyTotal
        this.lblBuyTotal.AutoSize = true;
        this.lblBuyTotal.Font = new System.Drawing.Font("Microsoft YaHei", 9F, System.Drawing.FontStyle.Bold);
        this.lblBuyTotal.ForeColor = System.Drawing.Color.FromArgb(255, 80, 80);
        this.lblBuyTotal.Location = new System.Drawing.Point(5, 3);
        this.lblBuyTotal.Text = "买入: 0万";
        this.lblBuyTotal.Cursor = System.Windows.Forms.Cursors.Hand;

        // lblSellTotal
        this.lblSellTotal.AutoSize = true;
        this.lblSellTotal.Font = new System.Drawing.Font("Microsoft YaHei", 9F, System.Drawing.FontStyle.Bold);
        this.lblSellTotal.ForeColor = System.Drawing.Color.FromArgb(80, 200, 80);
        this.lblSellTotal.Location = new System.Drawing.Point(125, 3);
        this.lblSellTotal.Text = "卖出: 0万";
        this.lblSellTotal.Cursor = System.Windows.Forms.Cursors.Hand;

        // lblNetBuy
        this.lblNetBuy.AutoSize = true;
        this.lblNetBuy.Font = new System.Drawing.Font("Microsoft YaHei", 9F, System.Drawing.FontStyle.Bold);
        this.lblNetBuy.ForeColor = System.Drawing.Color.FromArgb(255, 80, 80);
        this.lblNetBuy.Location = new System.Drawing.Point(245, 3);
        this.lblNetBuy.Text = "净买: 0万";

        // 第二行：点火、砸盘、买活跃、承接好（可点击筛选）
        // lblIgniteCount
        this.lblIgniteCount.AutoSize = true;
        this.lblIgniteCount.Font = new System.Drawing.Font("Microsoft YaHei", 9F, System.Drawing.FontStyle.Bold);
        this.lblIgniteCount.ForeColor = System.Drawing.Color.FromArgb(255, 215, 0);
        this.lblIgniteCount.Location = new System.Drawing.Point(5, 22);
        this.lblIgniteCount.Text = "点火: 0";
        this.lblIgniteCount.Cursor = System.Windows.Forms.Cursors.Hand;
        this.lblIgniteCount.Click += new System.EventHandler(this.lblIgniteCount_Click);

        // lblSmashCount
        this.lblSmashCount.AutoSize = true;
        this.lblSmashCount.Font = new System.Drawing.Font("Microsoft YaHei", 9F, System.Drawing.FontStyle.Bold);
        this.lblSmashCount.ForeColor = System.Drawing.Color.FromArgb(147, 112, 219);
        this.lblSmashCount.Location = new System.Drawing.Point(90, 22);
        this.lblSmashCount.Text = "砸盘: 0";
        this.lblSmashCount.Cursor = System.Windows.Forms.Cursors.Hand;
        this.lblSmashCount.Click += new System.EventHandler(this.lblSmashCount_Click);

        // lblBuyActive
        this.lblBuyActive.AutoSize = true;
        this.lblBuyActive.Font = new System.Drawing.Font("Microsoft YaHei", 9F, System.Drawing.FontStyle.Bold);
        this.lblBuyActive.ForeColor = System.Drawing.Color.FromArgb(255, 69, 0);
        this.lblBuyActive.Location = new System.Drawing.Point(175, 22);
        this.lblBuyActive.Text = "买活跃: 0";
        this.lblBuyActive.Cursor = System.Windows.Forms.Cursors.Hand;
        this.lblBuyActive.Click += new System.EventHandler(this.lblBuyActive_Click);

        // lblSellActive
        this.lblSellActive.AutoSize = true;
        this.lblSellActive.Font = new System.Drawing.Font("Microsoft YaHei", 9F, System.Drawing.FontStyle.Bold);
        this.lblSellActive.ForeColor = System.Drawing.Color.FromArgb(0, 191, 255);
        this.lblSellActive.Location = new System.Drawing.Point(275, 22);
        this.lblSellActive.Text = "承接好: 0";
        this.lblSellActive.Cursor = System.Windows.Forms.Cursors.Hand;
        this.lblSellActive.Click += new System.EventHandler(this.lblSellActive_Click);

        // === 筛选按钮 ===

        int btnY = 12;
        int btnW = 55;
        int btnH = 26;
        int btnGap = 3;

        // btn30W (默认选中)
        this.btn30W.BackColor = System.Drawing.Color.FromArgb(50, 90, 140);
        this.btn30W.FlatStyle = System.Windows.Forms.FlatStyle.Flat;
        this.btn30W.FlatAppearance.BorderSize = 0;
        this.btn30W.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.btn30W.ForeColor = System.Drawing.Color.White;
        this.btn30W.Location = new System.Drawing.Point(5, btnY);
        this.btn30W.Size = new System.Drawing.Size(btnW, btnH);
        this.btn30W.Text = "30";
        this.btn30W.Cursor = System.Windows.Forms.Cursors.Hand;
        this.btn30W.Click += new System.EventHandler(this.btn30W_Click);

        // btn50W
        this.btn50W.BackColor = System.Drawing.Color.FromArgb(35, 35, 40);
        this.btn50W.FlatStyle = System.Windows.Forms.FlatStyle.Flat;
        this.btn50W.FlatAppearance.BorderSize = 0;
        this.btn50W.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.btn50W.ForeColor = System.Drawing.Color.Silver;
        this.btn50W.Location = new System.Drawing.Point(5 + (btnW + btnGap) * 1, btnY);
        this.btn50W.Size = new System.Drawing.Size(btnW, btnH);
        this.btn50W.Text = "50";
        this.btn50W.Cursor = System.Windows.Forms.Cursors.Hand;
        this.btn50W.Click += new System.EventHandler(this.btn50W_Click);

        // btn100W
        this.btn100W.BackColor = System.Drawing.Color.FromArgb(35, 35, 40);
        this.btn100W.FlatStyle = System.Windows.Forms.FlatStyle.Flat;
        this.btn100W.FlatAppearance.BorderSize = 0;
        this.btn100W.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.btn100W.ForeColor = System.Drawing.Color.Silver;
        this.btn100W.Location = new System.Drawing.Point(5 + (btnW + btnGap) * 2, btnY);
        this.btn100W.Size = new System.Drawing.Size(btnW, btnH);
        this.btn100W.Text = "100万";
        this.btn100W.Cursor = System.Windows.Forms.Cursors.Hand;
        this.btn100W.Click += new System.EventHandler(this.btn100W_Click);

        // btn300W
        this.btn300W.BackColor = System.Drawing.Color.FromArgb(35, 35, 40);
        this.btn300W.FlatStyle = System.Windows.Forms.FlatStyle.Flat;
        this.btn300W.FlatAppearance.BorderSize = 0;
        this.btn300W.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.btn300W.ForeColor = System.Drawing.Color.Silver;
        this.btn300W.Location = new System.Drawing.Point(5 + (btnW + btnGap) * 3, btnY);
        this.btn300W.Size = new System.Drawing.Size(btnW, btnH);
        this.btn300W.Text = "300万";
        this.btn300W.Cursor = System.Windows.Forms.Cursors.Hand;
        this.btn300W.Click += new System.EventHandler(this.btn300W_Click);

        // btn1000W
        this.btn1000W.BackColor = System.Drawing.Color.FromArgb(35, 35, 40);
        this.btn1000W.FlatStyle = System.Windows.Forms.FlatStyle.Flat;
        this.btn1000W.FlatAppearance.BorderSize = 0;
        this.btn1000W.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.btn1000W.ForeColor = System.Drawing.Color.Silver;
        this.btn1000W.Location = new System.Drawing.Point(5 + (btnW + btnGap) * 4, btnY);
        this.btn1000W.Size = new System.Drawing.Size(btnW + 5, btnH);
        this.btn1000W.Text = "1000万";
        this.btn1000W.Cursor = System.Windows.Forms.Cursors.Hand;
        this.btn1000W.Click += new System.EventHandler(this.btn1000W_Click);

        // lblStatus
        this.lblStatus.AutoSize = true;
        this.lblStatus.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.lblStatus.ForeColor = System.Drawing.Color.Gray;
        this.lblStatus.Location = new System.Drawing.Point(300, btnY + 2);
        this.lblStatus.Text = "共 0 条";

        // === DataGridView ===
        this.dataGridView1.Dock = System.Windows.Forms.DockStyle.Fill;
        this.dataGridView1.BackgroundColor = System.Drawing.Color.Black;  // 纯黑背景
        this.dataGridView1.ScrollBars = System.Windows.Forms.ScrollBars.None;  // 隐藏滚动条
        this.dataGridView1.MouseWheel += new System.Windows.Forms.MouseEventHandler(this.dataGridView1_MouseWheel);

        // === 底部状态栏 ===
        this.statusStrip1.BackColor = System.Drawing.Color.Black;  // 纯黑背景
        this.statusStrip1.Dock = System.Windows.Forms.DockStyle.Bottom;
        this.statusStrip1.Font = new System.Drawing.Font("Microsoft YaHei", 9F);
        this.statusStrip1.Items.AddRange(new System.Windows.Forms.ToolStripItem[] {
            this.toolStripStatusLabel1,
            this.toolStripStatusLabel2,
            this.toolStripStatusLabel3
        });

        // toolStripStatusLabel1 - 关联软件
        this.toolStripStatusLabel1.ForeColor = System.Drawing.Color.FromArgb(100, 180, 255);
        this.toolStripStatusLabel1.Text = "未关联交易软件";
        this.toolStripStatusLabel1.AutoSize = false;
        this.toolStripStatusLabel1.Width = 150;
        this.toolStripStatusLabel1.TextAlign = System.Drawing.ContentAlignment.MiddleLeft;

        // toolStripStatusLabel2 - 数据日期
        this.toolStripStatusLabel2.ForeColor = System.Drawing.Color.Silver;
        this.toolStripStatusLabel2.Text = "数据日期: --";
        this.toolStripStatusLabel2.AutoSize = false;
        this.toolStripStatusLabel2.Width = 150;
        this.toolStripStatusLabel2.TextAlign = System.Drawing.ContentAlignment.MiddleCenter;

        // toolStripStatusLabel3 - 当前时间
        this.toolStripStatusLabel3.ForeColor = System.Drawing.Color.LightGreen;
        this.toolStripStatusLabel3.Text = "00:00:00";
        this.toolStripStatusLabel3.Spring = true;
        this.toolStripStatusLabel3.TextAlign = System.Drawing.ContentAlignment.MiddleRight;

        // === 添加控件到面板 ===

        // panelTop 控件
        this.panelTop.Controls.Add(this.lblStockName);
        this.panelTop.Controls.Add(this.lblChange);
        this.panelTop.Controls.Add(this.lblTurnover);
        this.panelTop.Controls.Add(this.lblVolumeRatio);
        this.panelTop.Controls.Add(this.lblTotalAmount);
        this.panelTop.Controls.Add(this.txtStockCode);
        this.panelTop.Controls.Add(this.lblRefresh);
        this.panelTop.Controls.Add(this.lblAnalysis);
        this.panelTop.Controls.Add(this.chkVoice);
        this.panelTop.Controls.Add(this.chkAutoRefresh);
        this.panelTop.Controls.Add(this.chkFollowTdx);
        this.panelTop.Controls.Add(this.chkLockCode);
        this.panelTop.Controls.Add(this.chkTopMost);

        // panelStats 控件
        this.panelStats.Controls.Add(this.lblBuyTotal);
        this.panelStats.Controls.Add(this.lblSellTotal);
        this.panelStats.Controls.Add(this.lblNetBuy);
        this.panelStats.Controls.Add(this.lblIgniteCount);
        this.panelStats.Controls.Add(this.lblSmashCount);
        this.panelStats.Controls.Add(this.lblBuyActive);
        this.panelStats.Controls.Add(this.lblSellActive);

        // panelFilter 控件
        this.panelFilter.Controls.Add(this.btn30W);
        this.panelFilter.Controls.Add(this.btn50W);
        this.panelFilter.Controls.Add(this.btn100W);
        this.panelFilter.Controls.Add(this.btn300W);
        this.panelFilter.Controls.Add(this.btn1000W);
        this.panelFilter.Controls.Add(this.lblStatus);

        // === Form 配置 ===
        // 表格列宽: 58+55+55+50+50+45+50 = 363px，加边距约400px
        this.AutoScaleDimensions = new System.Drawing.SizeF(7F, 15F);
        this.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
        this.BackColor = System.Drawing.Color.Black;  // 纯黑背景
        this.ClientSize = new System.Drawing.Size(400, 550);
        this.MinimumSize = new System.Drawing.Size(400, 400);

        // 添加控件到窗体（注意顺序：后添加的在下面）
        this.Controls.Add(this.dataGridView1);
        this.Controls.Add(this.panelFilter);
        this.Controls.Add(this.panelStats);
        this.Controls.Add(this.panelTop);
        this.Controls.Add(this.statusStrip1);

        this.Name = "MainForm";
        this.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen;
        this.Text = "THS大单监控";
        
        this.Load += new System.EventHandler(this.MainForm_Load);

        ((System.ComponentModel.ISupportInitialize)(this.dataGridView1)).EndInit();
        this.ResumeLayout(false);
    }

    #endregion

    // 面板
    private System.Windows.Forms.Panel panel1;
    private System.Windows.Forms.Panel panelTop;
    private System.Windows.Forms.Panel panelStats;
    private System.Windows.Forms.Panel panelFilter;
    private System.Windows.Forms.DataGridView dataGridView1;

    // 股票信息
    private System.Windows.Forms.Label lblStockName;
    private System.Windows.Forms.Label lblChange;
    private System.Windows.Forms.Label lblTurnover;
    private System.Windows.Forms.Label lblVolumeRatio;
    private System.Windows.Forms.Label lblTotalAmount;

    // 统计信息
    private System.Windows.Forms.Label lblBuyTotal;
    private System.Windows.Forms.Label lblSellTotal;
    private System.Windows.Forms.Label lblNetBuy;
    private System.Windows.Forms.Label lblIgniteCount;
    private System.Windows.Forms.Label lblSmashCount;
    private System.Windows.Forms.Label lblBuyActive;
    private System.Windows.Forms.Label lblSellActive;

    // 操作控件
    private System.Windows.Forms.TextBox txtStockCode;
    private System.Windows.Forms.Button btnRefresh;
    private System.Windows.Forms.Button btnAnalysis;
    private System.Windows.Forms.Label lblRefresh;
    private System.Windows.Forms.Label lblAnalysis;
    private System.Windows.Forms.CheckBox chkVoice;
    private System.Windows.Forms.CheckBox chkAutoRefresh;
    private System.Windows.Forms.CheckBox chkFollowTdx;
    private System.Windows.Forms.CheckBox chkLockCode;
    private System.Windows.Forms.CheckBox chkTopMost;
    private System.Windows.Forms.Label lblStatus;

    // 底部状态栏
    private System.Windows.Forms.StatusStrip statusStrip1;
    private System.Windows.Forms.ToolStripStatusLabel toolStripStatusLabel1;
    private System.Windows.Forms.ToolStripStatusLabel toolStripStatusLabel2;
    private System.Windows.Forms.ToolStripStatusLabel toolStripStatusLabel3;

    // 筛选按钮
    private System.Windows.Forms.Button btn30W;
    private System.Windows.Forms.Button btn50W;
    private System.Windows.Forms.Button btn100W;
    private System.Windows.Forms.Button btn300W;
    private System.Windows.Forms.Button btn1000W;
    }
}
