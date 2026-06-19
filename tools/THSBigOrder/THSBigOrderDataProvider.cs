using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace THSBigOrder
{
    public class THSBigOrderDataProvider : IDisposable
    {
        private const string KPL_API_BASE = "https://apphwhq.longhuvip.com/w1/api/index.php";
        private const string USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 9; MI 8 MIUI/V11.0.5.0.PEACNXM)";
        private const string DC_API_BASE = "https://push2.eastmoney.com/api/qt/stock/get";

        private readonly HttpClient _httpClient;
        private readonly Random _random = new Random();

        public THSBigOrderDataProvider()
        {
            _httpClient = new HttpClient();
            _httpClient.Timeout = TimeSpan.FromSeconds(15);
            _httpClient.DefaultRequestHeaders.Clear();
            _httpClient.DefaultRequestHeaders.Add("User-Agent", USER_AGENT);
        }

        public async Task<List<BigOrderItem>> GetBigOrderDataAsync(string stockCode, int limit = 100, int money = 0)
        {
            try
            {
                string deviceId = GenerateDeviceId();
                string url = string.Format("{0}?Order=0&st={1}&a=GetMainMonitor_w30&c=StockYiDongKanPan&PhoneOSNew=1&DeviceID={2}&VerSion=5.17.0.4&Index=0&Money={3}&apiv=w36&StockID={4}&IsBS=0&",
                    KPL_API_BASE, limit, deviceId, money, stockCode);

                string json = await _httpClient.GetStringAsync(url);
                var result = new List<BigOrderItem>();
                var jo = JObject.Parse(json);
                var list = jo["List"] as JArray;

                if (list == null || list.Count == 0)
                {
                    return result;
                }

                foreach (var item in list)
                {
                    var order = new BigOrderItem();
                    order.Type = item[0].ToObject<int>();
                    order.Volume = item[2].ToObject<double>();
                    order.Amount = item[3].ToObject<double>();
                    order.Price = item[4].ToObject<double>();
                    order.Time = DateTime.Parse(item[5].ToString());
                    result.Add(order);
                }

                return result;
            }
            catch (Exception ex)
            {
                throw new Exception("获取数据失败: " + ex.Message, ex);
            }
        }

        public async Task<List<BigOrderItem>> GetAllDayDataAsync(string stockCode, int money = 0)
        {
            var allData = new List<BigOrderItem>();
            int pageSize = 500;
            int index = 0;
            string deviceId = GenerateDeviceId();

            while (true)
            {
                try
                {
                    string url = string.Format("{0}?Order=0&st={1}&a=GetMainMonitor_w30&c=StockYiDongKanPan&PhoneOSNew=1&DeviceID={2}&VerSion=5.17.0.4&Index={3}&Money={4}&apiv=w36&StockID={5}&IsBS=0&",
                        KPL_API_BASE, pageSize, deviceId, index, money, stockCode);

                    string json = await _httpClient.GetStringAsync(url);
                    var jo = JObject.Parse(json);
                    var list = jo["List"] as JArray;

                    if (list == null || list.Count == 0)
                    {
                        break;
                    }

                    foreach (var item in list)
                    {
                        var order = new BigOrderItem();
                        order.Type = item[0].ToObject<int>();
                        order.Volume = item[2].ToObject<double>();
                        order.Amount = item[3].ToObject<double>();
                        order.Price = item[4].ToObject<double>();
                        order.Time = DateTime.Parse(item[5].ToString());
                        allData.Add(order);
                    }

                    if (list.Count < pageSize)
                    {
                        break;
                    }

                    index += pageSize;
                    await Task.Delay(100);
                }
                catch
                {
                    break;
                }
            }

            return allData;
        }

        public async Task<StockInfo> GetStockInfoAsync(string stockCode)
        {
            try
            {
                string secid = stockCode.StartsWith("6") ? "1." + stockCode : "0." + stockCode;
                string url = string.Format("{0}?secid={1}&fields=f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f60,f62,f71,f92,f152,f168,f169,f170&ut=fa5fd1943c7b386f172d6893dbfba10b&invt=2&fltt=2&cb=",
                    DC_API_BASE, secid);

                var request = new HttpRequestMessage(HttpMethod.Get, url);
                request.Headers.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36");

                var response = await _httpClient.SendAsync(request);
                string json = await response.Content.ReadAsStringAsync();

                var jo = JObject.Parse(json);
                var data = jo["data"];

                if (data == null || !data.HasValues)
                {
                    return null;
                }

                var info = new StockInfo();
                info.Code = stockCode;
                info.Name = data["f58"] != null ? data["f58"].ToString() : "";
                info.Price = data["f43"] != null ? data["f43"].ToObject<double>() : 0;
                info.Change = data["f170"] != null ? data["f170"].ToObject<double>() : 0;
                info.TurnoverRate = data["f168"] != null ? data["f168"].ToObject<double>() : 0;
                info.VolumeRatio = data["f50"] != null ? data["f50"].ToObject<double>() : 0;
                info.High = data["f44"] != null ? data["f44"].ToObject<double>() : 0;
                info.Low = data["f45"] != null ? data["f45"].ToObject<double>() : 0;
                info.Open = data["f46"] != null ? data["f46"].ToObject<double>() : 0;
                info.PreClose = data["f60"] != null ? data["f60"].ToObject<double>() : 0;
                info.TotalAmount = data["f48"] != null ? data["f48"].ToObject<double>() : 0;
                return info;
            }
            catch (Exception ex)
            {
                Console.WriteLine("获取股票详情失败: " + ex.Message);
                return null;
            }
        }

        /// <summary>
        /// 计算资金标记（点火/砸盘）和买盘标记（买活跃/承接好）
        /// 完全按照 Slayed03 原始版本的逻辑实现
        /// 
        /// 原始代码位置: Slayed03\Decompiled\Units\StatisticsClass.cs
        /// 方法: CCalculateAndAddAverages2(DataTable dataTable, int miaos)
        /// 参数: miaos = 6 (6秒)
        /// </summary>
        public void CalculateMarkers(List<BigOrderItem> data)
        {
            if (data == null || data.Count == 0) return;

            // 1. 按时间升序排列（原始代码: orderby (DateTime)row["时间"]）
            var sortedData = data.OrderBy(x => x.Time).ToList();
            
            // 2. 初始化上一行平均值
            double 上一行主动卖平均价 = 0.0;
            double 上一行主动买平均价 = 0.0;

            // 3. 遍历每一行计算标记
            for (int index = 0; index < sortedData.Count; index++)
            {
                var row = sortedData[index];
                var currentTime = row.Time;
                
                // 重置标记
                row.FundMarker = "";
                row.BuyMarker = "";

                // 只在交易时间内计算（9:30-11:30, 13:00-15:00）
                // 原始代码判断逻辑:
                // (dateTime >= 9:30 && dateTime <= 11:30) || (dateTime >= 13:00 && dateTime <= 15:00)
                var date = currentTime.Date;
                bool isTradeTime = 
                    (currentTime >= date.AddHours(9).AddMinutes(30) && currentTime <= date.AddHours(11).AddMinutes(30)) ||
                    (currentTime >= date.AddHours(13) && currentTime <= date.AddHours(15));
                
                // 非交易时间不计算标记
                if (!isTradeTime) continue;
                
                // 定义时间范围
                DateTime oneMinuteAgo = currentTime.AddSeconds(-50);   // 50秒前
                DateTime oneMinuteAgo6s = currentTime.AddSeconds(-6);  // 6秒前
                DateTime oneMinuteAfter = currentTime.AddSeconds(6);   // 6秒后

                // source = 过去6秒的数据（不包括当前行）- 用于检查是否有点火
                var source = sortedData.Take(index)
                    .Where(x => x.Time >= oneMinuteAgo6s)
                    .ToList();

                // source2 = 过去50秒的数据（不包括当前行）- 用于计算点火/砸盘
                var source2 = sortedData.Take(index)
                    .Where(x => x.Time >= oneMinuteAgo)
                    .ToList();

                // source3 = 未来6秒的数据（包括当前行）- 用于计算买活跃/承接好
                var source3 = sortedData.Skip(index)
                    .Where(x => x.Time <= oneMinuteAfter)
                    .ToList();

                // === 计算点火/砸盘（资金栏）===
                // 原始代码第375-382行
                if (source2.Count > 0)
                {
                    // num = 过去50秒所有数据的平均金额（万）
                    double num = source2.Average(x => x.Amount / 10000.0);
                    
                    // num2 = 当前行金额（如果是主动买Type=2，否则为0）（万）
                    double num2 = (row.Type == 2) ? row.Amount / 10000.0 : 0.0;
                    
                    // num3 = 当前行金额（如果是主动卖Type=4，否则为0）（万）
                    double num3 = (row.Type == 4) ? row.Amount / 10000.0 : 0.0;
                    
                    // 点火条件：金额 >= 300万 且 金额/平均 > 2.0
                    string text = (!(num2 >= 300.0) || num2 / num <= 2.0) ? "" : "点火";
                    
                    // 砸盘条件：金额 >= 300万 且 金额/平均 > 2.0
                    string text2 = (!(num3 >= 300.0) || num3 / num <= 2.0) ? "" : "砸盘";
                    
                    // 赋值：如果同时满足，砸盘优先
                    row.FundMarker = ((text == "") && (text2 == "")) ? "" : ((text2 == "") ? text : text2);
                }

                // === 计算买活跃/承接好（买盘栏）===
                // 原始代码第387-397行
                // Type映射：1=被动卖, 2=主动买, 3=被动买, 4=主动卖
                if (source3.Count > 0)
                {
                    // num4 = 未来6秒内（主动卖 或 被动买）的平均金额
                    // 原始代码: "主动卖" || "被动买" = Type 4 || Type 3
                    // 注意：不匹配的返回0参与平均计算！
                    double num4 = source3.Average(x => 
                        (x.Type == 4 || x.Type == 3) ? x.Amount / 10000.0 : 0.0);
                    
                    // num5 = 未来6秒内（主动买 或 被动卖）的平均金额
                    // 原始代码: "主动买" || "被动卖" = Type 2 || Type 1
                    double num5 = source3.Average(x => 
                        (x.Type == 2 || x.Type == 1) ? x.Amount / 10000.0 : 0.0);
                    
                    // 承接好条件：index > 0 且 当前卖平均 > 上一行卖平均 且 平均 > 300万
                    string text3 = (index <= 0 || !(num4 > 上一行主动卖平均价) || num4 <= 300.0) ? "" : "承接好";
                    
                    // 买活跃条件检查：前6秒(source)内是否有点火
                    bool flag = source.Any(x => x.FundMarker == "点火");
                    
                    // 买活跃条件：index > 0 且 当前买平均 >= 上一行买平均 且 平均 > 100万 且 前6秒有点火
                    // 买活跃优先级高于承接好
                    row.BuyMarker = (index > 0 && num5 >= 上一行主动买平均价 && num5 > 100.0 && flag) ? "买活跃" : text3;
                    
                    // 更新上一行的平均值（用于下一行计算）
                    上一行主动卖平均价 = num4;
                    上一行主动买平均价 = num5;
                }
            }
        }

        private string GenerateDeviceId()
        {
            string input = DateTime.Now.Ticks + _random.Next(0, 9999999).ToString();
            using (var md5 = MD5.Create())
            {
                byte[] hash = md5.ComputeHash(Encoding.ASCII.GetBytes(input));
                return BitConverter.ToString(hash).Replace("-", "").ToLower();
            }
        }

        public void Dispose()
        {
            if (_httpClient != null)
            {
                _httpClient.Dispose();
            }
        }
    }

    public class BigOrderItem
    {
        public int Type { get; set; }
        public double Volume { get; set; }
        public double Amount { get; set; }
        public double Price { get; set; }
        public DateTime Time { get; set; }

        public string FundMarker { get; set; }
        public string BuyMarker { get; set; }

        public BigOrderItem()
        {
            FundMarker = "";
            BuyMarker = "";
        }

        public string TypeName
        {
            get
            {
                // 原始版本使用"主动买"、"主动卖"而不是"主买"、"主卖"
                switch (Type)
                {
                    case 1: return "被动卖";
                    case 2: return "主动买";  // 原始版本
                    case 3: return "被动买";
                    case 4: return "主动卖";  // 原始版本
                    default: return "未知";
                }
            }
        }

        public string AmountStr
        {
            get { return (Amount / 10000).ToString("F0") + "万"; }
        }

        public string TimeStr
        {
            get { return Time.ToString("HH:mm:ss"); }
        }

        public bool IsBuy
        {
            get { return Type == 2 || Type == 3; }
        }

        public bool IsSell
        {
            get { return Type == 1 || Type == 4; }
        }
    }

    public class StockInfo
    {
        public string Code { get; set; }
        public string Name { get; set; }
        public double Price { get; set; }
        public double Change { get; set; }
        public double TurnoverRate { get; set; }
        public double VolumeRatio { get; set; }
        public double High { get; set; }
        public double Low { get; set; }
        public double Open { get; set; }
        public double PreClose { get; set; }
        public double TotalAmount { get; set; }
    }
}
