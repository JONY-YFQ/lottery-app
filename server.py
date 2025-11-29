# 文件名: server.py
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from aip import AipOcr
import re
import requests
from bs4 import BeautifulSoup
import uvicorn

# ==========================================
# 1. 百度 OCR 配置
# ==========================================
APP_ID = '121089290'
API_KEY = 'PQUz1id2QoIHLu7OCmSXPyWk'
SECRET_KEY = 'QAriYcjlch2xUFjVhZuqABsJUGERipyZ'
client = AipOcr(APP_ID, API_KEY, SECRET_KEY)

# ==========================================
# 2. 爬虫与计算逻辑
# ==========================================
def get_winning_numbers(issue_code):
    print(f"🌍 正在联网查询第 {issue_code} 期...")
    # 这里使用的是500彩票网的历史数据接口
    url = f"https://datachart.500.com/ssq/history/newinc/history.php?start={issue_code}&end={issue_code}"
    
    try:
        response = requests.get(url, timeout=3)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        t_tr = soup.find('tbody', id='tdata').find('tr')
        if not t_tr:
            print("⚠️ 未查到该期数据")
            return None
            
        tds = t_tr.find_all('td')
        red_balls = [td.text for td in tds[1:7]]
        blue_ball = tds[7].text
        
        print(f"🏆 官方开奖: 红{red_balls} 蓝{blue_ball}")
        return {"red": red_balls, "blue": blue_ball}
        
    except Exception as e:
        print(f"❌ 联网失败: {e}")
        # 【测试兜底】如果联网失败（比如期号太新没开奖），用下面这个号码做演示
        # 你可以随时改这个号码来测试中奖效果
        return {"red": ['05', '08', '12', '17', '23', '30'], "blue": '01'}

def calculate_prize(user_red, user_blue, win_red, win_blue):
    # 简单的比对逻辑
    hit_red = len([n for n in user_red if n in win_red])
    hit_blue = 1 if user_blue == win_blue else 0
    
    prize = 0
    desc = "未中奖"
    
    # 双色球规则简化版
    if hit_red == 6 and hit_blue == 1:
        prize = 10000000; desc = "一等奖"
    elif hit_red == 6:
        prize = 5000000; desc = "二等奖"
    elif hit_red == 5 and hit_blue == 1:
        prize = 3000; desc = "三等奖"
    elif hit_red == 5 or (hit_red == 4 and hit_blue == 1):
        prize = 200; desc = "四等奖"
    elif hit_red == 4 or (hit_red == 3 and hit_blue == 1):
        prize = 10; desc = "五等奖"
    elif hit_blue == 1:
        prize = 5; desc = "六等奖"
        
    return prize, desc

# ==========================================
# 3. Web 服务初始化
# ==========================================
app = FastAPI()

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 核心接口：上传图片 -> 识别 -> 查号 -> 算奖
@app.post("/upload")
async def upload_lottery(file: UploadFile = File(...)):
    print("📥 收到图片上传...")
    image_bytes = await file.read()
    
    # A. OCR 识别
    result = client.basicAccurate(image_bytes)
    if 'words_result' not in result:
        return {"error": "OCR识别失败，请重试"}

    lines = [item['words'] for item in result['words_result']]
    
    # B. 提取期号
    issue = "2025137" # 默认值，防报错
    for line in lines:
        match = re.search(r'202\d{4}', line)
        if match:
            issue = match.group(0)
            break
    
    # C. 获取官方开奖数据
    winning_data = get_winning_numbers(issue)
    
    # D. 处理每一注号码
    tickets = []
    total_money = 0
    
    for line in lines:
        clean = line.replace(" ", "").replace("：", ":")
        # 正则提取：可能是 A:010203... 或者直接 010203...
        match = re.search(r'([A-Z])?[:.]?(\d{12})\+(\d{2})', clean)
        
        if match:
            row_id = match.group(1) if match.group(1) else "?"
            red_raw = match.group(2)
            u_red = [red_raw[i:i+2] for i in range(0, 12, 2)]
            u_blue = match.group(3)
            
            # 默认未中
            is_hit = False
            prize_level = "等待开奖"
            money = 0
            
            # 如果查到了开奖数据，就开始算账
            if winning_data:
                money, prize_level = calculate_prize(u_red, u_blue, winning_data['red'], winning_data['blue'])
                is_hit = (money > 0)
                total_money += money
            
            tickets.append({
                "id": row_id,
                "red": u_red,
                "blue": u_blue,
                "is_hit": is_hit,
                "prize": prize_level,
                "money": money
            })

    return {
        "issue": issue,
        "total_money": total_money,
        "tickets": tickets
    }

# 托管静态文件(HTML)，方便手机直接访问
# 只要把 index.html 放在同级目录下，就能通过 IP 直接访问页面
@app.get("/")
async def read_index():
    with open("index.html", "r", encoding='utf-8') as f:
        return HTMLResponse(content=f.read())

if __name__ == "__main__":
    # host="0.0.0.0" 这一句非常关键，允许局域网访问
    uvicorn.run(app, host="0.0.0.0", port=8000)