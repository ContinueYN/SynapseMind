# -*- coding: utf-8 -*-
"""Generate SynapseMind design diagrams with Pillow (no external graph tools)."""
import os, math
from PIL import Image, ImageDraw, ImageFont

OUT = r"D:\File\Work-program\Project_try\assets"
os.makedirs(OUT, exist_ok=True)

FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_B = r"C:\Windows\Fonts\msyhbd.ttc"

def f(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size, index=0)

def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if draw.textlength(cur + ch, font=font) <= max_w:
            cur += ch
        else:
            lines.append(cur); cur = ch
    if cur: lines.append(cur)
    return lines

def text(draw, xy, s, font, fill, anchor="la", max_w=None, spacing=6, align="left"):
    if max_w:
        lines = wrap(draw, s, font, max_w)
    else:
        lines = s.split("\n")
    x, y = xy
    for i, line in enumerate(lines):
        draw.text((x, y + i*(font.size+spacing)), line, font=font, fill=fill, anchor=anchor)
    return y + len(lines)*(font.size+spacing)

def rrect(draw, box, r, fill, outline=None, width=2):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)

def shadow(draw, box, r=24, off=6, color=(0,0,0,22)):
    x1,y1,x2,y2 = box
    draw.rounded_rectangle((x1+off,y1+off,x2+off,y2+off), radius=r, fill=color)

def arrow(draw, p1, p2, color, width=4, head=16, dashed=False):
    x1,y1 = p1; x2,y2 = p2
    if dashed:
        dist = math.hypot(x2-x1, y2-y1); n = max(1, int(dist//24))
        for i in range(n):
            t0 = i/n; t1 = min(1, (i+0.55)/n)
            draw.line((x1+(x2-x1)*t0, y1+(y2-y1)*t0, x1+(x2-x1)*t1, y1+(y2-y1)*t1), fill=color, width=width)
    else:
        draw.line((x1,y1,x2,y2), fill=color, width=width)
    ang = math.atan2(y2-y1, x2-x1)
    for s in (-1, 1):
        draw.polygon([
            (x2, y2),
            (x2 - head*math.cos(ang - s*0.5), y2 - head*math.sin(ang - s*0.5)),
            (x2 - head*0.55*math.cos(ang), y2 - head*0.55*math.sin(ang)),
        ], fill=color)

def badge(draw, cx, cy, r, label, fill, fg="#FFFFFF", fs=28):
    draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=fill)
    draw.text((cx, cy), label, font=f(fs, True), fill=fg, anchor="mm")

# ---------- palette ----------
BG      = "#F6F3EC"
INK     = "#1F2A2E"
MUTED   = "#5D6B70"
TEAL    = "#0F6B63"
TEAL_L  = "#DCEFEA"
AMBER   = "#C77A16"
AMBER_L = "#FAEBD3"
CORAL   = "#B6493A"
CORAL_L = "#F7DDD8"
BLUE    = "#2D5F8B"
BLUE_L  = "#DDE9F3"
LINE    = "#C9C2B4"
WHITE   = "#FFFFFF"

# =====================================================================
# Diagram 1: core loop
# =====================================================================
W, H = 2400, 1380
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img, "RGBA")

# subtle dots
for x in range(60, W, 48):
    for y in range(60, H, 48):
        d.ellipse((x, y, x+2, y+2), fill=(31,42,46,14))

d.text((90, 62), "SynapseMind 核心闭环", font=f(66, True), fill=INK)
d.text((92, 148), "12 分钟诊断  →  15 分钟处方  →  7 天复测；每一环都留下证据，每一张卡都能被推翻",
       font=f(30), fill=MUTED)

cards = [
    # (x, y, w, h, num, title, body, accent, light)
    (90,  250, 660, 300, "01", "轻诊断", "24 题 / 12 分钟；第 6 题先给一张\n“暂定卡点卡”，不让人等到最后", TEAL, TEAL_L),
    (870, 250, 660, 300, "02", "能力需求向量", "题 × 学生的七维需求\nV · Gv · Gf · WM · Gs · LTS · M", TEAL, TEAL_L),
    (1650,250, 660, 300, "03", "瓶颈假设", "先过“知识缺口”闸门\n再比 d_effective 与 θ 的缺口", TEAL, TEAL_L),
    (1650,700, 660, 300, "04", "学习处方", "P0/P1/P2/P4/P5…\n剂量 + 成功标准 + 停止规则", AMBER, AMBER_L),
    (870, 700, 660, 300, "05", "训练与验证", "学习模式 / 考试模式\n7 天同型题、30 天迁移题", CORAL, CORAL_L),
    (90,  700, 660, 300, "06", "证据反馈", "证据链 + 置信度 + 反证条件\n“我不同意”回流标注队列", BLUE, BLUE_L),
]
for (x,y,w,h,num,title,body,accent,light) in cards:
    shadow(d, (x,y,x+w,y+h), 26, 7)
    rrect(d, (x,y,x+w,y+h), 26, WHITE, (0,0,0,12), 2)
    rrect(d, (x,y,x+w,y+12), 6, accent)
    d.text((x+36, y+38), num, font=f(34, True), fill=accent)
    d.text((x+104, y+32), title, font=f(44, True), fill=INK)
    text(d, (x+38, y+118), body, f(28), MUTED, max_w=w-76, spacing=10)

# arrows: 1->2->3, 3->4, 4->5->6, 6->1 loop
arrow(d, (750, 400), (860, 400), LINE, 5)
arrow(d, (1530,400), (1640,400), LINE, 5)
arrow(d, (1980,550), (1980,690), LINE, 5)
arrow(d, (1640,850), (1540,850), LINE, 5)
arrow(d, (860, 850), (760, 850), LINE, 5)
# loop 6 -> 1 up left
arrow(d, (420, 700), (420, 560), BLUE, 4, dashed=True)
arrow(d, (420, 560), (420, 560), BLUE, 4, dashed=True)
d.line((420,560, 420, 560), fill=BLUE, width=4)
d.text((300, 610), "每周校准", font=f(24), fill=BLUE)
d.text((300, 642), "规则权重", font=f(24), fill=BLUE)

# bottom band
rrect(d, (90, 1110, 2310, 1260), 20, (255,255,255,210), (0,0,0,10), 2)
d.text((120, 1136), "一条不能破的纪律", font=f(30, True), fill=CORAL)
d.text((120, 1186), "LLM 不产生分数，只产生偏移；分数来自规则与 IRT。任何结论都要能回到“哪道题、哪条规则、什么时间”。",
       font=f(28), fill=INK)
d.text((90, 1300), "SynapseMind · 项目设计方案 v0.1", font=f(22), fill=MUTED)

img.save(os.path.join(OUT, "01-core-loop.png"), quality=95)
print("saved 01")

# =====================================================================
# Diagram 2: architecture 4 -> 9
# =====================================================================
W, H = 2600, 1560
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img, "RGBA")
for x in range(60, W, 48):
    for y in range(60, H, 48):
        d.ellipse((x, y, x+2, y+2), fill=(31,42,46,12))

d.text((90, 58), "从 10 周到 10 万 DAU：4 个部署单元 → 9 个服务", font=f(58, True), fill=INK)
d.text((92, 136), "边界先立，进程后拆；拆分有触发条件，不为了微服务而微服务", font=f(28), fill=MUTED)

# left panel
rrect(d, (90, 210, 1120, 1370), 28, (255,255,255,215), (0,0,0,12), 2)
d.text((130, 246), "MVP · 10 周", font=f(38, True), fill=TEAL)
d.text((130, 300), "4 个部署单元 / 1 套流水线", font=f(26), fill=MUTED)

units = [
    ("synapse-gateway", "JWT · 路由 · 限流 · 灰度 · Trace", TEAL),
    ("synapse-core", "auth + learner + assessment + plan + notify", TEAL),
    ("synapse-content", "题库 · 知识点树 · 检索 · 版本", TEAL),
    ("synapse-ai", "RAG · Agent · MCP · 护栏", AMBER),
]
y = 360
for name, desc, col in units:
    shadow(d, (130, y, 1080, y+150), 18, 5)
    rrect(d, (130, y, 1080, y+150), 18, WHITE, (0,0,0,12), 2)
    d.rectangle((130, y, 142, y+150), fill=col)
    d.text((170, y+26), name, font=f(30, True), fill=INK)
    d.text((172, y+78), desc, font=f(24), fill=MUTED)
    y += 180

# data layer
rrect(d, (130, 1100, 1080, 1320), 18, TEAL_L, (15,107,99,60), 2)
d.text((160, 1124), "数据层（MVP 单库 + 月分区）", font=f(25, True), fill=TEAL)
for i, (nm, sub) in enumerate([("MySQL 8.0", "业务主数据"), ("Redis 7.2", "缓存/锁/限流"), ("PGvector", "知识库检索"), ("RocketMQ", "异步事件")]):
    x = 160 + (i % 2) * 450
    yy = 1170 + (i // 2) * 68
    d.text((x, yy), nm, font=f(24, True), fill=INK)
    d.text((x+150, yy+2), sub, font=f(20), fill=MUTED)

# arrow between panels
arrow(d, (1130, 760), (1280, 760), AMBER, 6, 22)
d.text((1138, 700), "按触发条件", font=f(24, True), fill=AMBER)
d.text((1138, 790), "逐步拆分", font=f(24, True), fill=AMBER)

# right panel
rrect(d, (1290, 210, 2510, 1370), 28, (255,255,255,215), (0,0,0,12), 2)
d.text((1330, 246), "目标 · 10 万 DAU", font=f(38, True), fill=AMBER)
d.text((1330, 300), "9 个服务 / 独立数据所有权 / 独立扩缩容", font=f(26), fill=MUTED)

svcs = [
    ("gateway", "入口/灰度"), ("auth", "登录/RBAC"), ("learner", "画像/掌握"),
    ("assessment", "诊断/判分"), ("content", "题库/知识点"), ("plan", "处方/调度"),
    ("ai-orchestrator", "RAG/Agent"), ("analytics", "聚合/周报"), ("notification", "推送/审核"),
]
for i, (nm, sub) in enumerate(svcs):
    col = i % 3; row = i // 3
    x = 1330 + col * 380
    yy = 370 + row * 170
    shadow(d, (x, yy, x+350, yy+130), 16, 5)
    rrect(d, (x, yy, x+350, yy+130), 16, WHITE, (0,0,0,12), 2)
    d.text((x+22, yy+24), nm, font=f(26, True), fill=INK)
    d.text((x+22, yy+74), sub, font=f(22), fill=MUTED)

# triggers band
rrect(d, (1290, 930, 2510, 1080), 18, AMBER_L, (199,122,22,70), 2)
d.text((1320, 952), "拆分触发（任一满足）", font=f(26, True), fill=AMBER)
d.text((1320, 1000), "日均调用 > 200 万   ·   周发布 > 2 次   ·   资源画像差 > 3×   ·   故障域需隔离",
       font=f(23), fill=INK)
d.text((1320, 1040), "先触发：assessment / content / ai-orchestrator", font=f(22), fill=MUTED)

# principles band
rrect(d, (1290, 1110, 2510, 1320), 18, BLUE_L, (45,95,139,70), 2)
d.text((1320, 1130), "三条不能破的纪律", font=f(26, True), fill=BLUE)
d.text((1320, 1176), "① 每张表只有一个写 owner；跨服务不直连他人库", font=f(22), fill=INK)
d.text((1320, 1212), "② 模块只暴露 api 包，ArchUnit 强制依赖方向", font=f(22), fill=INK)
d.text((1320, 1248), "③ AI 只走 ai-orchestrator，模型挂了业务仍能跑", font=f(22), fill=INK)

d.text((90, 1470), "SynapseMind · 项目设计方案 v0.1", font=f(22), fill=MUTED)
img.save(os.path.join(OUT, "02-architecture.png"), quality=95)
print("saved 02")

# =====================================================================
# Diagram 3: multi-agent
# =====================================================================
W, H = 2600, 1560
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img, "RGBA")
for x in range(60, W, 48):
    for y in range(60, H, 48):
        d.ellipse((x, y, x+2, y+2), fill=(31,42,46,12))

d.text((90, 58), "多 Agent：确定性状态机，不是自由聊天室", font=f(60, True), fill=INK)
d.text((92, 138), "7 个角色；只有教练与复盘允许局部 ReAct（≤4 步）；跨 Agent 只传 typed state",
       font=f(28), fill=MUTED)

# center
cx, cy = 1300, 760
rrect(d, (cx-330, cy-150, cx+330, cy+150), 28, INK, None, 0)
d.text((cx, cy-92), "确定性状态机", font=f(44, True), fill=WHITE, anchor="mm")
d.text((cx, cy-30), "Shared State JSON", font=f(28), fill="#D9E6E3", anchor="mm")
d.text((cx, cy+30), "schema_version · stage · evidence_refs", font=f(20), fill="#A9C4BF", anchor="mm")
d.text((cx, cy+78), "budget · trace_id · degraded", font=f(20), fill="#A9C4BF", anchor="mm")

# agent cards: 4 top, 3 bottom
agents_top = [
    ("诊断师", "24 题 → 六维 + 置信度", "MVP", TEAL),
    ("规划师", "2–4 周处方与剂量", "MVP", TEAL),
    ("教练", "L1–L3 提示阶梯", "MVP", AMBER),
    ("内容守护者", "入库审核 / 课标对齐", "MVP", TEAL),
]
agents_bottom = [
    ("复盘师", "错因归因 + 反证据", "半 Agent", CORAL),
    ("出题官", "变式 / 间隔 / 交错", "Phase 2", MUTED),
    ("元认知教练", "预测—实际校准", "Phase 2", MUTED),
]
wcard, hcard = 390, 160
for i, (nm, sub, tag, col) in enumerate(agents_top):
    x = 170 + i*570
    y = 250
    shadow(d, (x, y, x+wcard, y+hcard), 18, 6)
    rrect(d, (x, y, x+wcard, y+hcard), 18, WHITE, (0,0,0,12), 2)
    d.rectangle((x, y, x+10, y+hcard), fill=col)
    d.text((x+28, y+24), nm, font=f(30, True), fill=INK)
    d.text((x+28, y+76), sub, font=f(22), fill=MUTED)
    d.text((x+wcard-24, y+24), tag, font=f(18, True), fill=col, anchor="ra")
    arrow(d, (x+wcard//2, y+hcard), (cx-120+i*80, cy-160), col, 3, 14, dashed=(tag!="MVP"))

for i, (nm, sub, tag, col) in enumerate(agents_bottom):
    x = 360 + i*700
    y = 1120
    shadow(d, (x, y, x+wcard, y+hcard), 18, 6)
    rrect(d, (x, y, x+wcard, y+hcard), 18, WHITE, (0,0,0,12), 2)
    d.rectangle((x, y, x+10, y+hcard), fill=col)
    d.text((x+28, y+24), nm, font=f(30, True), fill=INK)
    d.text((x+28, y+76), sub, font=f(22), fill=MUTED)
    d.text((x+wcard-24, y+24), tag, font=f(18, True), fill=col, anchor="ra")
    arrow(d, (cx-120+i*120, cy+160), (x+wcard//2, y), col, 3, 14, dashed=(tag!="半 Agent"))

# side MCP
rrect(d, (90, 640, 480, 900), 22, BLUE_L, (45,95,139,70), 2)
d.text((120, 668), "MCP Server", font=f(30, True), fill=BLUE)
d.text((120, 716), "8 tools（MVP 5）", font=f(22), fill=INK)
d.text((120, 756), "profile / vector / search", font=f(20), fill=MUTED)
d.text((120, 790), "create_practice / attempt", font=f(20), fill=MUTED)
d.text((120, 824), "OAuth 2.1 · 审计 · 限流", font=f(20), fill=MUTED)
arrow(d, (480, 770), (cx-335, 770), BLUE, 4, 16)

# side guardrail
rrect(d, (2120, 640, 2510, 900), 22, CORAL_L, (182,73,58,70), 2)
d.text((2150, 668), "护栏", font=f(30, True), fill=CORAL)
d.text((2150, 716), "答案单向阀（4 道）", font=f(22), fill=INK)
d.text((2150, 756), "引用校验 / 标签词", font=f(20), fill=MUTED)
d.text((2150, 790), "置信 < 0.55 → 人工", font=f(20), fill=MUTED)
d.text((2150, 824), "schema 失败 → 模板", font=f(20), fill=MUTED)
arrow(d, (cx+335, 770), (2120, 770), CORAL, 4, 16)

# bottom band
rrect(d, (90, 1370, 2510, 1490), 18, (255,255,255,210), (0,0,0,10), 2)
d.text((120, 1390), "Handoff 五条规则", font=f(26, True), fill=INK)
d.text((120, 1434), "只传 typed state · 写 handoff_id/from/to · 下游只读已提交字段 · schema 失败重试 1 次 · 跨 Agent 不共享对话历史",
       font=f(21), fill=MUTED)

img.save(os.path.join(OUT, "03-multi-agent.png"), quality=95)
print("saved 03")