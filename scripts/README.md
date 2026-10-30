# scripts

仓库级脚本，不参与运行时。

```text
scripts/
├─ dev/
│  ├─ run.py             # 一键启动 API + Web
│  └─ run.ps1            # Windows 包装
├─ contracts/
│  ├─ generate.py        # OpenAPI -> generated.ts
│  └─ export_openapi.py  # 只导出 OpenAPI
├─ checks/
│  └─ check_repo.py      # 文件、链接、JSON、skill 映射检查
├─ eval/
│  ├─ m2_exit.py         # M2 退出判定（10 条 golden 回放）
│  ├─ s4_graph_build.py  # M2.5 S4 建图评测（20 道未见题）
│  ├─ s5_verify.py       # M2.5 S5 建图 + claim 反例验证
│  ├─ s5_session.py      # M2.5 S5 请求链路（建图 → 探针 → 卡点卡）
│  ├─ s6_physics.py      # M2.5 S6 物理接入（6 题）
│  ├─ s6_verifier.py     # M2.5 S6 物理验证器自检（无需 key）
│  ├─ s7_none_tier.py    # M2.5 S7 语文 NONE 档结构提示（6 题 × 2 段）
│  └─ s8_alignment.py    # M2.5 S8 分句级对齐（6 题 × 3 段）
└─ release/
   └─ export_public.py   # 可选的公开树导出工具
```

## 评测

```powershell
cd apps/api
# 规则基线；--live-shadow 需要仓库根 .env 里的 DEEPSEEK_API_KEY
.\.venv\Scripts\python.exe ..\..\scripts\eval\m2_exit.py
.\.venv\Scripts\python.exe ..\..\scripts\eval\m2_exit.py --live-shadow

# 20 道未见题建图，需真实 key；报告写入 eval/reports/
.\.venv\Scripts\python.exe ..\..\scripts\eval\s4_graph_build.py

# S5：建图 + claim 反例验证 / 请求链路（20 题，需真实 key）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_verify.py
.\.venv\Scripts\python.exe ..\..\scripts\eval\s5_session.py

# S6：物理接入（6 题，需真实 key）；验证器自检不需要 key
.\.venv\Scripts\python.exe ..\..\scripts\eval\s6_physics.py
.\.venv\Scripts\python.exe ..\..\scripts\eval\s6_verifier.py

# S7：语文 NONE 档结构提示（6 题 × 2 段，需真实 key）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s7_none_tier.py

# S8：分句级对齐（6 题 × 3 段 partial/full/blank，需真实 key）
.\.venv\Scripts\python.exe ..\..\scripts\eval\s8_alignment.py
```

## 可选本地检查

CI 不再运行文档/链接完整性检查；需要排查时再手动执行：

```bash
python scripts/checks/check_repo.py
```

检查内容：

- 根目录必需文件是否存在；
- `README.md` 与 `docs/` 下的相对链接/图片是否可解析；
- `specs/*.json` 是否为合法 JSON；
- `docs/design/chapters/08-skill映射.md` 是否有 11 条编号映射；
- 三张设计图是否存在。

## 一键启动

```powershell
python scripts/dev/run.py
# Windows 包装
.\scripts\dev\run.ps1
# 只检查环境
python scripts/dev/run.py --check
# 启动、确认健康、再自动停（用于验证）
python scripts/dev/run.py --smoke --no-install
```

## 导出 OpenAPI 与生成 TS 类型

需要先安装 API 依赖：

```powershell
python scripts/contracts/generate.py
```

它等价于：

```powershell
# 1. 用 API venv 导出 OpenAPI
apps\api\.venv\Scripts\python.exe scripts\contracts\export_openapi.py
# 2. 在 apps/web 生成 TS 类型
cd apps/web
npm run generate:api
```

生成物默认在 `.tmp/`（忽略）；`apps/web/src/lib/api/generated.ts` 入库，供 fresh clone 直接 typecheck/build。不要把它粘回 `specs/`；`specs/` 只放人写的契约源。

## 公开树（可选）

`scripts/release/export_public.py` 只在需要发布公开代码时使用；它不是日常开发步骤，也不会创建/推送任何远程仓库。