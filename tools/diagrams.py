# -*- coding: utf-8 -*-
import os, math
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "design", "assets")
os.makedirs(OUT, exist_ok=True)

W, H = 2400, 1400
INK = (31, 42, 46)
MUTED = (93, 107, 112)
TEAL = (15, 107, 99)
TEAL_L = (232, 242, 239)
AMBER = (176, 106, 18)
AMBER_L = (251, 240, 220)
CORAL = (168, 67, 53)
CORAL_L = (250, 235, 231)
BLUE = (45, 95, 139)
BLUE_L = (232, 240, 246)
BG = (250, 248, 242)
WHITE = (255, 255, 255)
BORDER = (216, 210, 196)

FONT_DIR = r"C:\Windows\Fonts"
def F(size, bold=False):
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)

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

def text_block(draw, xy, text, font, fill, max_w, line_gap=8, align="left"):
    x, y = xy
    lines = wrap(draw, text, font, max_w)
    for line in lines:
        w = draw.textlength(line, font=font)
        dx = 0 if align == "left" else ((max_w - w) / 2 if align == "center" else max_w - w)
        draw.text((x + dx, y), line, font=font, fill=fill)
        y += font.size + line_gap
    return y

def box(draw, xy, fill=WHITE, outline=BORDER, radius=18, width=3):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

def arrow(draw, p1, p2, color=TEAL, width=5, head=16, dashed=False):
    x1, y1 = p1; x2, y2 = p2
    if dashed:
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy)
        n = max(1, int(dist // 18))
        for i in range(n):
            if i % 2 == 0:
                a = (x1 + dx * i / n, y1 + dy * i / n)
                b = (x1 + dx * (i + 1) / n, y1 + dy * (i + 1) / n)
                draw.line([a, b], fill=color, width=width)
    else:
        draw.line([p1, p2], fill=color, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    for s in (-0.5, 0.5):
        draw.line([(x2, y2), (x2 - head * math.cos(ang + s), y2 - head * math.sin(ang + s))], fill=color, width=width)

def circle_num(draw, center, n, color=TEAL):
    r = 24
    draw.ellipse([center[0]-r, center[1]-r, center[0]+r, center[1]+r], fill=color)
    f = F(26, True)
    t = str(n)
    w = draw.textlength(t, font=f)
    draw.text((center[0]-w/2, center[1]-17), t, font=f, fill=WHITE)

# ---------------- 01 dialogue loop ----------------
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
d.text((90, 55), "单题诊断闭环", font=F(58, True), fill=INK)
d.text((90, 130), "不是讲这道题，是找到你卡住的那一步", font=F(30), fill=TEAL)

steps = [
    ("交题", "题目 + 自己的答案\n或一句“完全不会”", TEAL_L, TEAL),
    ("拆题", "解法图：7 个\n认知动作节点", AMBER_L, AMBER),
    ("对齐", "把步骤贴到图上\n找第一处偏离", TEAL_L, TEAL),
    ("追问", "2–6 轮，一次一问\n用反例逼出真实理解", AMBER_L, AMBER),
    ("定位", "L0–L6 + 证据\n+ 排除项 + 置信度", TEAL_L, TEAL),
    ("微干预", "3 分钟讲一个点\n+ 1 道同构题", AMBER_L, AMBER),
    ("迁移验证", "24h/7d 新题\n看卡点是否复发", TEAL_L, TEAL),
]
n = len(steps)
margin = 90
gap = 26
bw = (W - 2*margin - gap*(n-1)) / n
by, bh = 250, 360
for i, (title, body, fill, color) in enumerate(steps):
    x = margin + i*(bw+gap)
    box(d, [x, by, x+bw, by+bh], fill=fill, outline=color, width=3)
    circle_num(d, (x+40, by+40), i+1, color)
    d.text((x+76, by+24), title, font=F(30, True), fill=INK)
    text_block(d, (x+22, by+86), body, F(21), INK, bw-44, line_gap=9)
    if i < n-1:
        arrow(d, (x+bw+4, by+bh/2), (x+bw+gap-4, by+bh/2), color=TEAL, width=5, head=13)

# bottom: output band
oy = 710
box(d, [margin, oy, W-margin, oy+190], fill=WHITE, outline=TEAL, width=4)
d.text((margin+34, oy+28), "输出不是一整道题的解答，而是一张卡点卡", font=F(32, True), fill=TEAL)
chips = ["卡在哪一层", "为什么不是别的", "下一练什么", "怎么验证"]
cx = margin + 34
for c in chips:
    tw = d.textlength(c, font=F(22, True))
    d.rounded_rectangle([cx, oy+92, cx+tw+44, oy+148], radius=28, fill=TEAL_L, outline=TEAL, width=2)
    d.text((cx+22, oy+104), c, font=F(22, True), fill=TEAL)
    cx += tw + 64

# bottom loop
ly = 1010
d.line([margin+60, ly, W-margin-60, ly], fill=MUTED, width=3)
for x in (margin+60, W-margin-60):
    d.ellipse([x-6, ly-6, x+6, ly+6], fill=MUTED)
d.text((margin+90, ly-52), "证据沉淀 → 个人卡点库 → 下一次诊断更快", font=F(26, True), fill=MUTED)
d.text((margin+90, ly+30), "每一次对话都留下：卡点、证据、用户是否认同、24h 是否复发", font=F(22), fill=MUTED)

d.text((90, H-70), "SynapseMind 突触智学 · 单题诊断引导", font=F(20), fill=MUTED)
img.save(os.path.join(OUT, "01-dialogue-loop.png"))

# ---------------- 02 diagnosis engine ----------------
W2, H2 = 2600, 1600
img = Image.new("RGB", (W2, H2), BG)
d = ImageDraw.Draw(img)
d.text((80, 55), "诊断引擎：从答案到卡点", font=F(54, True), fill=INK)
d.text((80, 125), "题目解法图 × 学生步骤对齐 × 假设后验", font=F(28), fill=TEAL)

# left panel
lx, ly, lw, lh = 80, 210, 760, 960
box(d, [lx, ly, lx+lw, ly+lh], fill=WHITE, outline=BORDER, width=3)
d.text((lx+28, ly+24), "① 题目解法图", font=F(30, True), fill=TEAL)
nodes = [
    ("n1 READ", "读懂“恒成立”", BLUE_L, BLUE),
    ("n2 CONCEPT", "转化为最大值", TEAL_L, TEAL),
    ("n3 COMPUTE", "f'(x)=1/x-a", AMBER_L, AMBER),
    ("n4 CONDITION", "a>0 时驻点存在", CORAL_L, CORAL),
    ("n5 CONCEPT", "f''<0，是最大值", TEAL_L, TEAL),
    ("n6 COMPUTE", "解 ln(1/a)≤1", AMBER_L, AMBER),
    ("n7 CHECK", "等号/反例", BLUE_L, BLUE),
]
ny = ly + 80
nh = 100
for i, (label, desc, fill, color) in enumerate(nodes):
    box(d, [lx+28, ny, lx+lw-28, ny+nh], fill=fill, outline=color, width=2, radius=12)
    d.text((lx+44, ny+16), label, font=F(19, True), fill=color)
    d.text((lx+44, ny+48), desc, font=F(21), fill=INK)
    if i < len(nodes)-1:
        arrow(d, (lx+lw/2, ny+nh+2), (lx+lw/2, ny+nh+22), color=MUTED, width=2, head=6)
    ny += nh + 24

# middle panel
mx, my, mw, mh = 900, 210, 760, 960
box(d, [mx, my, mx+mw, my+mh], fill=WHITE, outline=BORDER, width=3)
d.text((mx+28, my+24), "② 学生作答对齐", font=F(30, True), fill=TEAL)
steps = [
    ("s1", "f'(x)=1/x-a", "ok", TEAL),
    ("s2", "令 f'(x)=0 得 x=1/a", "partial", AMBER),
    ("s3", "最大值 ln(1/a)-1", "ok", TEAL),
    ("s4", "a≥1/e", "ok", TEAL),
]
sy = my + 90
for sid, text, status, color in steps:
    box(d, [mx+30, sy, mx+mw-30, sy+130], fill=WHITE, outline=color, width=3, radius=12)
    d.text((mx+48, sy+16), sid, font=F(20, True), fill=MUTED)
    text_block(d, (mx+104, sy+16), text, F(22), INK, mw-160, line_gap=5)
    badge = "✓ 通过" if status == "ok" else "! 前提缺失"
    bw2 = d.textlength(badge, font=F(19, True))
    d.rounded_rectangle([mx+mw-40-bw2-24, sy+82, mx+mw-40, sy+116], radius=17, fill=color)
    d.text((mx+mw-40-bw2-12, sy+89), badge, font=F(19, True), fill=WHITE)
    sy += 160

# highlight first divergence
d.rounded_rectangle([mx+20, my+250, mx+mw-20, my+390], radius=14, outline=CORAL, width=4)
d.text((mx+34, my+266), "第一处偏离：s2", font=F(22, True), fill=CORAL)

# right panel
rx, ry, rw, rh = 1720, 210, 800, 960
box(d, [rx, ry, rx+rw, ry+rh], fill=WHITE, outline=BORDER, width=3)
d.text((rx+28, ry+24), "③ 假设与探针", font=F(30, True), fill=TEAL)
hyps = [
    ("L2 条件转译", 0.86, CORAL),
    ("L1 概念不清", 0.09, MUTED),
    ("L4 计算错误", 0.05, MUTED),
]
hy = ry + 95
for label, p, color in hyps:
    d.text((rx+34, hy), label, font=F(22, True), fill=INK)
    d.text((rx+rw-110, hy), f"{p:.2f}", font=F(22, True), fill=color)
    d.rounded_rectangle([rx+34, hy+38, rx+rw-34, hy+62], radius=12, fill=(238, 235, 226))
    d.rounded_rectangle([rx+34, hy+38, rx+34+(rw-68)*p, hy+62], radius=12, fill=color)
    hy += 105

# speech bubble
by2 = ry + 440
box(d, [rx+30, by2, rx+rw-30, by2+210], fill=AMBER_L, outline=AMBER, width=3, radius=18)
d.text((rx+50, by2+18), "下一问（信息增益最大）", font=F(20, True), fill=AMBER)
text_block(d, (rx+50, by2+58), "“a=-1 时，f'(x)=1/x+1 有零点吗？”", F(25, True), INK, rw-100, line_gap=8)
d.text((rx+50, by2+152), "区分：漏分类 vs 概念不清", font=F(19), fill=MUTED)

# bottom card
cx, cy, cw, ch = 380, 1260, 1840, 250
box(d, [cx, cy, cx+cw, cy+ch], fill=TEAL, outline=TEAL, width=3, radius=20)
d.text((cx+40, cy+24), "④ 卡点卡（不是报告，是下一动作）", font=F(30, True), fill=WHITE)
d.text((cx+40, cy+78), "L2 条件转译 / 参数分类：用驻点前，未确认 a>0 使 x=1/a 存在且落在 x>0", font=F(22), fill=WHITE)
chips = ["证据：a=0、a=-1 仍用 x=1/a", "排除：求导/解不等式", "置信：0.86", "下一练：存在性三步检查"]
cx2 = cx+40
for c in chips:
    tw = d.textlength(c, font=F(18, True))
    d.rounded_rectangle([cx2, cy+150, cx2+tw+36, cy+205], radius=20, fill=WHITE)
    d.text((cx2+18, cy+162), c, font=F(18, True), fill=TEAL)
    cx2 += tw + 52

# arrows between panels
arrow(d, (lx+lw+6, ly+lh/2), (mx-8, my+mh/2), color=TEAL, width=6, head=16)
arrow(d, (mx+mw+6, my+mh/2), (rx-8, ry+rh/2), color=TEAL, width=6, head=16)
arrow(d, (rx+rw/2, ry+rh+6), (cx+cw/2, cy-8), color=CORAL, width=6, head=16)
d.text((80, H2-60), "SynapseMind 突触智学 · 诊断引擎", font=F(20), fill=MUTED)
img.save(os.path.join(OUT, "02-diagnosis-engine.png"))

# ---------------- 03 architecture ----------------
W3, H3 = 2600, 1600
img = Image.new("RGB", (W3, H3), BG)
d = ImageDraw.Draw(img)
d.text((90, 55), "技术架构：4 个部署单元，7 个服务边界", font=F(50, True), fill=INK)
d.text((90, 122), "3 个人 8 周先跑 4 个进程；拆分有触发条件，不为了微服务而微服务", font=F(26), fill=TEAL)

# client
cx, cy, cw, ch = 90, 200, 2420, 110
box(d, [cx, cy, cx+cw, cy+ch], fill=WHITE, outline=BORDER, width=3, radius=16)
d.text((cx+30, cy+22), "Client", font=F(22, True), fill=TEAL)
d.text((cx+150, cy+22), "Web / 手机拍照 / 粘贴文本 / SSE 流式回复", font=F(26), fill=INK)
d.text((cx+cw-360, cy+22), "JWT · 限流 · 灰度", font=F(20), fill=MUTED)

# nginx/gateway
ny = 360
box(d, [90, ny, 2420, ny+90], fill=TEAL_L, outline=TEAL, width=3, radius=14)
d.text((120, ny+22), "Nginx（SSE 关闭缓冲）  →  Gateway（鉴权 / 限流 / 路由）", font=F(28, True), fill=TEAL)

# units
uy = 520
uh = 460
units = [
    ("core", "session · problem\ndiagnosis · evidence", "会话状态 / 解法图\n对齐 / 假设 / 卡点卡", TEAL_L, TEAL),
    ("ai", "parser · coach\nverifier · orchestrator", "OCR / 追问生成\nSymPy 校验 / 模型路由", AMBER_L, AMBER),
    ("content", "knowledge · admin", "概念卡 / 提示卡\n迁移题 / 标注后台", BLUE_L, BLUE),
]
uw = 730
gap = 40
for i, (name, services, desc, fill, color) in enumerate(units):
    x = 90 + i*(uw+gap)
    box(d, [x, uy, x+uw, uy+uh], fill=fill, outline=color, width=4, radius=18)
    d.text((x+28, uy+24), name.upper(), font=F(34, True), fill=color)
    d.text((x+28, uy+78), services, font=F(23, True), fill=INK, spacing=8)
    d.text((x+28, uy+190), desc, font=F(21), fill=INK, spacing=8)
    d.text((x+28, uy+uh-48), "独立部署 / 独立扩缩", font=F(18), fill=MUTED)

# data stores
dy = 1140
box(d, [90, dy, 2420, dy+230], fill=WHITE, outline=BORDER, width=3, radius=18)
d.text((120, dy+20), "数据层", font=F(26, True), fill=TEAL)
stores = [
    ("MySQL 8", "14 张核心表\nuser_id 16 片"),
    ("Redis 7", "会话 / 提示卡\n幂等 / 分布式锁"),
    ("PostgreSQL 16", "pgvector\n五类知识卡"),
    ("对象存储", "题目原图\n7 天删除"),
]
sw = 540
for i, (name, desc) in enumerate(stores):
    x = 120 + i*(sw+30)
    box(d, [x, dy+70, x+sw, dy+200], fill=BG, outline=BORDER, width=2, radius=12)
    d.text((x+20, dy+82), name, font=F(22, True), fill=INK)
    d.text((x+20, dy+120), desc, font=F(19), fill=MUTED, spacing=6)

# observability strip
oy = 1010
box(d, [90, oy, 2420, oy+90], fill=WHITE, outline=CORAL, width=3, radius=16)
d.text((118, oy+26), "可观测性", font=F(24, True), fill=CORAL)
obs = ["Prometheus", "Grafana 三张大盘", "ARMS / OTel Trace", "JVM / GC / 慢 SQL", "首问 >12s 告警"]
ox = 300
for t in obs:
    tw = d.textlength(t, font=F(19))
    d.text((ox, oy+30), "· " + t, font=F(19), fill=INK)
    ox += tw + 54

# arrows
arrow(d, (1300, 310), (1300, 355), color=TEAL, width=5, head=12)
arrow(d, (1300, 450), (1300, 515), color=TEAL, width=5, head=12)
arrow(d, (1300, oy+96), (1300, dy-8), color=TEAL, width=4, head=10)

d.text((90, H3-55), "SynapseMind 突触智学 · 4 单元 / 7 服务边界", font=F(20), fill=MUTED)
img.save(os.path.join(OUT, "03-architecture.png"))

print("saved")
for f in ("01-dialogue-loop.png","02-diagnosis-engine.png","03-architecture.png"):
    p=os.path.join(OUT,f)
    im=Image.open(p)
    print(f, im.size, os.path.getsize(p))