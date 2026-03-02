# PD-MAWS 系统架构文档

> 本文档随系统架构变化同步更新。最后更新时间：2026-03-02

## 一、系统总览

PD-MAWS（Protocol-Driven Multi-Agent Academic Writing System）是一个协议驱动的多智能体学术写作系统。
核心特征：可验证、可审计、可恢复，采用四层协议栈架构。

```mermaid
graph TB
    subgraph "Frontend (React/Next.js)"
        UI["统一工作台 Studio"]
        AR["审计回放"]
        HI["人机干预台"]
    end

    subgraph "API Gateway (FastAPI)"
        REST["REST API"]
        WS["WebSocket"]
        MW["Security Middleware<br/>JWT / HMAC / Nonce"]
    end

    subgraph "L4 - ANP 网络组织层"
        SR["SessionRegistry<br/>(唯一权威)"]
        CB["Token 熔断<br/>(双层治理)"]
        DL["死锁检测"]
        BB["Document Blackboard<br/>(版本锁)"]
    end

    subgraph "L3 - A2A 通信语义层"
        VP["消息校验管线<br/>(6级校验)"]
        BUS_C["控制面总线<br/>(Redis Streams)"]
        BUS_D["数据面总线<br/>(Redis Pub/Sub)"]
    end

    subgraph "L2 - ACP Agent 控制层"
        SM["统一状态机<br/>(IDLE→PLAN→EXEC→<br/>VERIFY→EMIT→DONE)"]
        CC["约束执行框架"]
    end

    subgraph "L1 - Skills 能力层"
        LLM["多 LLM Provider<br/>(OpenAI/DeepSeek/<br/>Gemini/Ollama/Custom)"]
        RAG["文献检索<br/>(Qdrant RAG)"]
        TOOL["工具集<br/>(代码沙箱/图表)"]
    end

    UI --> REST
    UI --> WS
    REST --> MW
    WS --> MW
    MW --> SR
    MW --> VP
    VP --> BUS_C
    VP --> BUS_D
    SR --> SM
    BUS_C --> SM
    SM --> CC
    CC --> LLM
    CC --> RAG
    CC --> TOOL
    BB --> SR
    CB --> SR
    DL --> SR
```

## 二、Agent 拓扑

系统包含 8 类 Agent 节点，通过 A2A 协议通信：

```mermaid
graph LR
    PI["PI_Agent<br/>调度与仲裁"]

    subgraph "执笔组"
        W1["Writer_Agent #1"]
        W2["Writer_Agent #2"]
        WN["Writer_Agent #N"]
    end

    subgraph "证据服务"
        LR["Literature_Researcher<br/>文献检索"]
        DA["Data_Analyst<br/>数据分析"]
    end

    subgraph "质量保障"
        RT["Red_Team_Reviewer<br/>对抗审查"]
        FC["Format_Controller<br/>排版规范"]
    end

    HP["Human_Proxy<br/>人类代理"]

    PI -->|"Map: 任务拆解"| W1
    PI -->|"Map: 任务拆解"| W2
    PI -->|"Map: 任务拆解"| WN
    W1 -->|"请求证据"| LR
    W1 -->|"请求数据"| DA
    W2 -->|"请求证据"| LR
    W1 -->|"draft.integrated.ready"| RT
    RT -->|"审查反馈"| PI
    W1 -->|"请求排版"| FC
    HP -->|"FORCE_UPDATE"| PI
    PI -->|"仲裁升级"| HP
    VD["Visual_Diagram<br/>图表生成"] 
    W1 -->|"请求图表"| VD
```

## 三、Agent 定义架构

每个 Agent 采用「约束声明 + ACP 状态机 + L1 Skills」三位一体模式：

```mermaid
graph TD
    A["Agent 定义"] --> B["约束声明<br/>Role / AllowedActions /<br/>ForbiddenActions / QualityGates"]
    A --> C["ACP 状态机<br/>IDLE-PLAN-EXECUTE-<br/>VERIFY-EMIT-DONE"]
    A --> D["L1 Skills 能力层<br/>LLM / Retrieval /<br/>Code Exec / Diagram"]
    B -->|"违约即 NACK"| E["ANP 审计"]
    C -->|"驱动任务推进"| F["A2A 消息"]
    D -->|"外部交互"| G["LLM / Qdrant / FS"]
```

## 四、多 LLM Provider 架构

```mermaid
graph TD
    F["LLMProviderFactory"] --> O["OpenAI Provider"]
    F --> DS["DeepSeek Provider<br/>(OpenAI 兼容)"]
    F --> G["Gemini Provider"]
    F --> OL["Ollama Provider<br/>(本地)"]
    F --> C["Custom Provider<br/>(HTTP 自定义)"]

    subgraph "统一接口"
        IF["complete() / stream() /<br/>structured_output()"]
    end

    O --> IF
    DS --> IF
    G --> IF
    OL --> IF
    C --> IF
```

## 五、会话状态机

```mermaid
stateDiagram-v2
    [*] --> INIT
    INIT --> RUNNING: 启动
    RUNNING --> NEGOTIATING: Agent 协商
    NEGOTIATING --> RUNNING: 达成共识
    NEGOTIATING --> ARBITRATION: 死锁/冲突
    ARBITRATION --> RUNNING: 仲裁完成
    ARBITRATION --> HALTED: 人工升级
    RUNNING --> DEGRADED: Grounding 不可用
    DEGRADED --> RUNNING: 服务恢复
    RUNNING --> HALTED: Token 熔断
    HALTED --> RUNNING: 预算重置
    HALTED --> FAILED: 人工终止
    RUNNING --> COMPLETED: 全部完成
    COMPLETED --> [*]
    FAILED --> [*]
```

## 六、文档 Blackboard 状态机

```mermaid
stateDiagram-v2
    [*] --> EMPTY
    EMPTY --> DRAFTING: Writer 开始编撰
    DRAFTING --> DRAFTING: Patch 提交
    DRAFTING --> CONFLICT: 并发冲突
    CONFLICT --> DRAFTING: 冲突解决
    DRAFTING --> REVIEW_PENDING: 提交审查
    REVIEW_PENDING --> DRAFTING: 审查驳回
    REVIEW_PENDING --> INTEGRATED: 图文集成
    INTEGRATED --> REVIEW_PENDING: Red Team 驳回
    INTEGRATED --> FINAL: 终审通过
    FINAL --> [*]
```

## 七、数据流

```mermaid
graph LR
    subgraph "存储层"
        PG["PostgreSQL<br/>业务数据/审计"]
        RD["Redis<br/>会话缓存/消息总线"]
        QD["Qdrant<br/>向量检索"]
    end

    SR["SessionRegistry"] -->|"快照暂存"| RD
    SR -->|"持久归档"| PG
    BB["Blackboard"] -->|"Patch JSONB"| PG
    LR2["Researcher"] -->|"向量检索"| QD
    BUS["消息总线"] -->|"控制面 Streams"| RD
    BUS -->|"数据面 Pub/Sub"| RD
    AL["审计日志"] -->|"全链路记录"| PG
```

## 八、技术栈映射

| 层级 | 组件 | 技术选型 |
|------|------|----------|
| 前端 | 框架 | React 18 / Next.js (App Router) |
| 前端 | 编辑器 | Tiptap / ProseMirror |
| 前端 | Agent 流 | React Flow + Mermaid.js |
| 后端 | 主框架 | FastAPI (Python 3.11+) |
| 后端 | 编排 | LangGraph StateGraph |
| 后端 | 校验 | Pydantic v2 |
| 存储 | RDBMS | PostgreSQL 16+ |
| 存储 | 缓存 | Redis 7+ |
| 存储 | 向量 | Qdrant |
| 通信 | 控制面 | Redis Streams |
| 通信 | 数据面 | Redis Pub/Sub |
| 安全 | 认证 | JWT / OAuth2 |
| 安全 | 签名 | HMAC-SHA256 |
| 观测 | 链路 | OpenTelemetry |
