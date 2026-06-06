# Russo-Ukrainian War Monitor

俄乌冲突公开情报可视分析系统，面向公开事件数据、公开文本材料和用户上传情报文档，提供态势总览、事件追踪、关系网络、材料结构化处理和带来源引用的智能研判能力。

## 项目定位

本项目按照“主题文档输入 -> 数据处理 -> 知识组织 -> 检索问答 -> 可视化呈现”的流程构建，围绕俄乌冲突公开情报材料展开分析。系统既包含 ACLED 风格的结构化冲突事件数据和公开文本样本，也支持用户导入 PDF、DOCX、TXT 材料，自动完成解析、切分、结构化抽取、语义索引和可视化呈现。

## 主要功能

### 1. 态势分析

- 展示冲突事件数量、时间范围、地理事件规模和知识层指标。
- 支持事件时间线、空间热点、阶段演化、地区-事件类型矩阵、行动主体关系排行等分析视图。
- 使用 ECharts 构建交互式图表，适合课程演示和报告截图。

### 2. 事件追踪

- 选择具体事件后，展示锚点事件详情、前后邻近事件、同地区演化和相关主体排行。
- 根据结构化字段构建事件链路，辅助观察事件前后关联。
- 支持来源 notes 展示和事件链智能解读。

### 3. 关系网络

- 基于结构化知识层展示组织、地点、事件、来源之间的关系。
- 支持全局关系图与局部关联查看。
- 图节点与边可用于辅助理解行动主体、地理位置、事件类型之间的联系。

### 4. 情报管理

- 支持一次导入最多五份 PDF、DOCX、TXT 材料。
- 上传后自动解析文本，按段落与长度进行 chunk 切分。
- 保留文件名、文档主题、段落编号、页码、offset、文件路径等来源信息。
- 使用大模型与规则抽取结合的方式识别实体、事件、关系和证据片段。
- 为当前材料生成时间线、关系图和结构化线索。
- 支持对当前材料生成语义索引，用于后续问答召回。

### 5. 智能研判

- 提供会话式问答界面，支持多轮对话和历史会话保存。
- 问答时可同时结合结构化事件库、当前上传材料、文档 chunk 和语义索引。
- 回答附带来源引用，点击引用可查看对应证据文本。
- 支持从情报管理界面携带当前材料进入智能研判，实现材料范围内的问答。

## 技术架构

```text
用户上传材料 / 公开事件数据 / 公开文本样本
        |
        v
文本解析与清洗（PDF / DOCX / TXT）
        |
        v
Chunk 切分与来源保留
        |
        v
实体、事件、关系、证据抽取
        |
        +----> MySQL 结构化存储
        +----> SQLite 本地向量索引
        +----> Neo4j 关系图谱增强
        |
        v
检索规划、SQL 查询、语义召回、证据组织
        |
        v
React + ECharts 可视化界面与智能问答
```

## 技术栈

### 后端

- Python 3.10+
- FastAPI
- PyMySQL
- Pandas
- pdfplumber
- python-docx
- OpenAI-compatible API
- LangChain Core
- Neo4j Python Driver
- SQLite 本地向量索引

### 前端

- React 18
- TypeScript
- Vite
- ECharts

### 数据存储

- MySQL：核心结构化数据、文档、chunk、问答历史、情报材料抽取结果。
- Neo4j：关系图谱增强与图结构展示。
- SQLite：本地 chunk 向量索引。

## 目录结构

```text
.
├── backend/                  # FastAPI 后端
│   ├── app/
│   │   ├── routers/          # API 路由
│   │   ├── schemas/          # 响应模型
│   │   ├── services/         # 数据处理、问答、图谱、向量索引服务
│   │   ├── config.py         # 环境配置
│   │   ├── database.py       # MySQL 初始化与连接
│   │   └── main.py           # FastAPI 入口
│   └── requirements.txt      # 后端依赖
├── frontend/                 # React 前端
│   ├── src/
│   │   ├── App.tsx           # 主界面与交互逻辑
│   │   └── App.css           # 页面样式
│   ├── package.json
│   └── vite.config.ts
├── database/                 # MySQL 与 Neo4j 数据库脚本
│   ├── schema.sql            # MySQL 建表脚本
│   └── neo4j_seed.cypher.zip # Neo4j 图数据库初始化脚本压缩包
├── scripts/
│   └── export_neo4j_seed.py  # 不依赖 APOC 的 Neo4j Cypher 导出工具
├── raw_data/                 # 示例材料
├── russia_ukraine_conflict.csv
├── RU_Dataset_cleaned.csv
├── requirements.txt          # 根目录后端依赖入口
├── .env.example              # 环境变量模板
└── README.md
```

## 环境要求

- Python 3.10 或以上
- Node.js 18 或以上
- MySQL 8.0
- Neo4j Desktop 或 Neo4j Server
- 可用的 OpenAI-compatible 大模型接口
- 可用的 OpenAI-compatible embedding 模型接口

## 快速启动

### 1. 克隆项目

```powershell
git clone https://github.com/Attachment818/rus-ukr-vis.git
cd rus-ukr-vis
```

### 2. 配置环境变量

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

根据本地环境修改 `.env`：

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=rus_ukr_analysis

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password

CHAT_OPENAI_API_KEY=your_api_key
CHAT_OPENAI_BASE_URL=https://api.siliconflow.cn/v1
CHAT_OPENAI_MODEL=deepseek-ai/DeepSeek-V3.2

EMBEDDING_OPENAI_API_KEY=your_api_key
EMBEDDING_OPENAI_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_OPENAI_MODEL=Qwen/Qwen3-Embedding-8B
```

### 3. 安装后端依赖

建议使用虚拟环境或 Conda 环境：

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

也可以使用后端目录中的依赖文件：

```powershell
python -m pip install -r backend/requirements.txt
```

### 4. 安装前端依赖

```powershell
cd frontend
npm install
cd ..
```

### 5. 准备数据库

#### 5.1 MySQL

```sql
CREATE DATABASE IF NOT EXISTS rus_ukr_analysis
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
```

如果已有导出的建表脚本，可以执行：

```powershell
mysql -u root -p rus_ukr_analysis < database/schema.sql
```

后端启动时也会自动检查并创建运行所需的扩展表。

#### 5.2 Neo4j

使用 Neo4j Desktop 创建并启动一个本地 DBMS，默认连接信息如下：

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password
```

如果项目中已经包含 `database/neo4j_seed.cypher.zip`，先解压得到 `database/neo4j_seed.cypher`，再导入图数据库：

```powershell
Expand-Archive database\neo4j_seed.cypher.zip -DestinationPath database -Force
```

```powershell
cypher-shell -a bolt://localhost:7687 -u neo4j -p your_neo4j_password -d neo4j -f database\neo4j_seed.cypher
```

如果 PowerShell 找不到 `cypher-shell`，可以在 Neo4j Desktop 中打开对应 DBMS 的 Terminal，或使用 Neo4j 安装目录下的 `bin\cypher-shell.bat`：

```powershell
.\bin\cypher-shell.bat -a bolt://localhost:7687 -u neo4j -p your_neo4j_password -d neo4j -f D:\DataVisualization\test3\database\neo4j_seed.cypher
```

导入后可以在 Neo4j Browser 中验证：

```cypher
MATCH (n) RETURN count(n);
```

```cypher
MATCH ()-[r]->() RETURN count(r);
```

### 6. 启动后端

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

后端健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/llm/status
```

### 7. 启动前端

新开一个终端：

```powershell
cd frontend
npm run dev
```

浏览器打开：

```text
http://127.0.0.1:5175/
```

## 数据导入与演示流程

### 基础数据

项目根目录包含两个公开数据样本：

- `russia_ukraine_conflict.csv`：俄乌冲突结构化事件数据。
- `RU_Dataset_cleaned.csv`：公开文本样本数据。

可通过前端界面或后端接口导入基础数据：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/datasets/conflict/reindex
Invoke-RestMethod -Method Post http://127.0.0.1:8000/datasets/weibo/reindex
```

### 情报材料处理

1. 打开前端“情报管理”。
2. 选择 PDF、DOCX 或 TXT 文件。
3. 点击“导入并处理”。
4. 系统自动完成解析、chunk、实体抽取、事件抽取、关系抽取和证据保留。
5. 查看材料时间线和当前材料关系图。
6. 点击“生成语义索引”，为当前材料建立向量检索能力。
7. 在底部问答框输入问题，系统会跳转至“智能研判”并结合当前材料回答。

### 智能研判示例

可以尝试以下问题：

```text
最近一次冲突事件是什么？
```

```text
分析 2024 年苏梅州的冲突态势。
```

```text
根据当前材料，按时间顺序梳理事件，并说明主要主体、地点和证据来源。
```

```text
当前材料中哪些组织、地点和武器装备之间存在关联？
```

## 常用接口

### 系统状态

```text
GET  /health
GET  /llm/status
POST /llm/test
POST /llm/embedding/test
```

### 情报材料

```text
POST /intelligence/cases
GET  /intelligence/cases/{case_id}
POST /intelligence/cases/{case_id}/documents
POST /intelligence/cases/{case_id}/process
POST /intelligence/cases/{case_id}/embeddings
GET  /intelligence/cases/{case_id}/timeline
GET  /intelligence/cases/{case_id}/graph
GET  /intelligence/cases/{case_id}/entities
GET  /intelligence/cases/{case_id}/events
```

### 智能研判

```text
GET  /chat/sessions
POST /chat/sessions
GET  /chat/sessions/{session_id}/messages
POST /chat/sessions/{session_id}/query
```

### 数据集视图

```text
GET  /datasets/conflict/timeline
GET  /datasets/conflict/map
GET  /datasets/conflict/events
GET  /datasets/conflict/actor-pairs
GET  /datasets/acled/knowledge-graph
```

## 课程作业对应关系

| 实验要求 | 当前实现 |
| --- | --- |
| 支持 PDF、DOCX、TXT 输入 | 情报管理支持三类文件导入 |
| 文本切分并保留来源 | `document_chunks` 保留段落、页码、offset、文件路径 |
| 数据清洗与规范化 | 文档解析、文本清洗、chunk 切分、来源元数据整理 |
| 抽取人物、时间、组织、地点、事件 | LLM 与规则结合抽取实体、事件、关系 |
| 组织成图结构或可检索结构 | MySQL 知识表、Neo4j 图谱、本地向量索引 |
| 检索与问答 | SQL 规划、文档召回、向量检索、来源引用 |
| 可视化呈现 | 态势图、时间线、事件链、关系网络、材料图谱 |
| 来源定位 | 问答引用可定位至事件、文档段落或证据片段 |

## 开发命令

前端类型检查：

```powershell
cd frontend
npx tsc --noEmit
```

前端构建：

```powershell
cd frontend
npm run build
```

后端语法检查：

```powershell
python -m compileall backend
```

导出 Neo4j 初始化脚本：

```powershell
python scripts\export_neo4j_seed.py --database neo4j --output database\neo4j_seed.cypher
```

`database/neo4j_seed.cypher` 可能较大，不直接提交到 GitHub。导出后建议压缩为 zip：

```powershell
Compress-Archive -Path database\neo4j_seed.cypher -DestinationPath database\neo4j_seed.cypher.zip -Force
```

如果希望导入时自动清空目标 Neo4j 数据库，可以导出带清空语句的版本：

```powershell
python scripts\export_neo4j_seed.py --database neo4j --output database\neo4j_seed.cypher --include-clear
```

## GitHub 上传

首次上传到空仓库：

```powershell
cd D:\DataVisualization\test3
git init
git add .
git add -f .env
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/Attachment818/rus-ukr-vis.git
git push -u origin main
```

后续更新：

```powershell
git add .
git add -f .env
git commit -m "Update project"
git push
```

如果导出了 Neo4j 初始化脚本，需要提交压缩包：

```powershell
Compress-Archive -Path database\neo4j_seed.cypher -DestinationPath database\neo4j_seed.cypher.zip -Force
git add scripts/export_neo4j_seed.py database/neo4j_seed.cypher.zip
git commit -m "Add Neo4j seed file"
git push
```
