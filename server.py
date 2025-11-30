# 文件名: server.py
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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
# 2. 爬虫与计算逻辑 (升级：支持大乐透初步逻辑 + 强力防屏蔽)
# ==========================================
def get_winning_numbers(issue_code, lottery_type="ssq"):
    print(f"🌍 正在联网查询 {lottery_type} 第 {issue_code} 期...")
    
    # 500彩票网的接口地址
    if lottery_type == "dlt": # 大乐透
        url = f"https://datachart.500.com/dlt/history/newinc/history.php?start={issue_code}&end={issue_code}"
    else: # 默认双色球
        url = f"https://datachart.500.com/ssq/history/newinc/history.php?start={issue_code}&end={issue_code}"
    
    # 【关键修改】加上 User-Agent 伪装成浏览器，防止被网站屏蔽
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        t_tr = soup.find('tbody', id='tdata').find('tr')
        
        if not t_tr:
            print("⚠️ 真实数据未查到 (可能期号太新或网站未更新)")
            return None # 【诚实模式】查不到就返回空，绝不瞎编
            
        tds = t_tr.find_all('td')
        
        if lottery_type == "dlt":
            # 大乐透：前5个红，后2个蓝
            red_balls = [td.text for td in tds[1:6]]
            blue_balls = [td.text for td in tds[6:8]]
            print(f"🏆 真实开奖(大乐透): 红{red_balls} 蓝{blue_balls}")
            return {"red": red_balls, "blue": blue_balls, "type": "dlt"}
        else:
            # 双色球：前6个红，第7个是蓝
            red_balls = [td.text for td in tds[1:7]]
            blue_ball = [tds[7].text] # 统一转成列表格式方便处理
            print(f"🏆 真实开奖(双色球): 红{red_balls} 蓝{blue_ball}")
            return {"red": red_balls, "blue": blue_ball, "type": "ssq"}
        
    except Exception as e:
        print(f"❌ 联网错误: {e}")
        return None

def calculate_prize(user_red, user_blue, win_data):
    if not win_data:
        return 0, "暂无数据"

    win_red = win_data['red']
    win_blue = win_data['blue']
    l_type = win_data.get('type', 'ssq')
    
    # 计算红球命中
    hit_red = len([n for n in user_red if n in win_red])
    # 计算蓝球命中
    hit_blue = len([n for n in user_blue if n in win_blue])
    
    prize = 0
    desc = "未中奖"
    
    # --- 双色球规则 ---
    if l_type == 'ssq':
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
            
    # --- 大乐透规则 (简单版) ---
    elif l_type == 'dlt':
        if hit_red == 5 and hit_blue == 2:
            prize = 10000000; desc = "一等奖"
        elif hit_red == 5 and hit_blue == 1:
            prize = 800000; desc = "二等奖"
        elif (hit_red == 5) or (hit_red == 4 and hit_blue == 2):
            prize = 10000; desc = "三等奖" # 简化金额
        elif (hit_red == 4 and hit_blue == 1) or (hit_red == 3 and hit_blue == 2):
            prize = 3000; desc = "四等奖" # 简化金额
        elif (hit_red == 4) or (hit_red == 3 and hit_blue == 1) or (hit_red == 2 and hit_blue == 2):
            prize = 300; desc = "五等奖" # 简化金额
        elif hit_blue >= 0: # 大乐透末等奖规则复杂，这里只做演示，实际需要更细
             if (hit_red==3) or (hit_red==1 and hit_blue==2) or (hit_red==2 and hit_blue==1) or (hit_blue==2):
                 prize = 5; desc = "九等奖"

    return prize, desc

# ==========================================
# 3. Web 服务初始化
# ==========================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/upload")
async def upload_lottery(file: UploadFile = File(...)):
    print("📥 收到图片上传...")
    image_bytes = await file.read()
    
    # A. OCR 识别
    result = client.basicAccurate(image_bytes)
    if 'words_result' not in result:
        return {"error": "OCR识别失败"}

    lines = [item['words'] for item in result['words_result']]
    all_text = "".join(lines)
    
    # --- 智能判断是双色球还是大乐透 ---
    lottery_type = "ssq" # 默认双色球
    if "大乐透" in all_text or "乐透" in all_text:
        lottery_type = "dlt"
    
    # B. 提取期号
    issue = "2025137" # 默认值，防止没识别到报错
    for line in lines:
        match = re.search(r'202\d{4}', line)
        if match:
            issue = match.group(0)
            break
    
    # C. 获取真实数据 (如果被屏蔽或没开奖，这里就是 None)
    winning_data = get_winning_numbers(issue, lottery_type)
    
    # D. 提取号码
    tickets = []
    total_money = 0
    
    for line in lines:
        clean = line.replace(" ", "").replace("：", ":")
        
        # 正则适配：双色球(12+2位) 或 大乐透(10+4位)
        # 这是一个通用正则，尝试匹配 "红球区域 + 蓝球区域"
        match = re.search(r'([A-Z])?[:.]?(\d{10,12})\+(\d{2,4})', clean)
        
        if match:
            row_id = match.group(1) if match.group(1) else "?"
            red_raw = match.group(2)
            blue_raw = match.group(3)
            
            # 切割红球 (2位一组)
            u_red = [red_raw[i:i+2] for i in range(0, len(red_raw), 2)]
            # 切割蓝球 (2位一组)
            u_blue = [blue_raw[i:i+2] for i in range(0, len(blue_raw), 2)]
            
            is_hit = False
            prize_level = "等待开奖"
            money = 0
            
            if winning_data:
                money, prize_level = calculate_prize(u_red, u_blue, winning_data)
                is_hit = (money > 0)
                total_money += money
            elif not winning_data:
                 prize_level = "暂无数据"
            
            # 兼容前端显示 (把蓝球列表拼回字符串给前端显示)
            tickets.append({
                "id": row_id,
                "red": u_red,
                "blue": " ".join(u_blue), # 变成 "01" 或 "05 12"
                "is_hit": is_hit,
                "prize": prize_level,
                "money": money
            })

    return {
        "issue": issue,
        "total_money": total_money,
        "tickets": tickets
    }

@app.get("/")
async def read_index():
    with open("index.html", "r", encoding='utf-8') as f:
        return HTMLResponse(content=f.read())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
