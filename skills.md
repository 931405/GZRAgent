一文讲清Skills概念与OpenClaw运作机制
图片
作者：AI让世界更懂你（蒋峰），深度学习自然语言处理公众号整理
链接：https://blog.csdn.net/qq_35082030/article/details/158510164

“Skills”在 2025–2026 年的语境里，已不仅是“可复用提示词模板”，而逐渐演化为一种可移植的、可工程化治理的“过程性能力包”：以文件夹为最小分发单元，包含 SKILL.md（YAML frontmatter + Markdown 指令）、可选的 references/（按需加载知识/规程）、assets/（模板/静态资源）与 scripts/（可执行脚本），并以“渐进式信息披露（progressive disclosure）”降低上下文成本、提升可维护性与可审计性。AgentSkills 规范将这一模式标准化：启动时仅加载元数据（name/description），触发后加载 SKILL.md 正文，执行时再按需读取资源或运行脚本。

OpenClaw（开源、可自托管的常驻 Agent 平台）把“Skills”作为核心扩展机制，并显式实现了：多目录技能加载与覆盖优先级、基于 metadata 的加载时过滤（OS / binaries / env / config 依赖）、将“可用技能清单”以紧凑 XML 形式注入系统提示、以及与 Slash Commands（/...）的联动（可选择绕过模型，直接把命令分发到工具以获得确定性）。同时，围绕 Skills 的开放生态（ClawHub 注册中心、第三方 skills）也带来了显著的供应链与提示注入风险，促使社区与安全厂商提出“把 Skills 当作不可信代码”的运行与隔离建议。

本文从 Prompt 到 Scripts的谱系，逐层给出定义、作用、示例与误区；进一步系统分解 Skill 的组成成分、运行流程与 LLM 交互模式（同步/异步、流式/批量），并给出可落地的伪码与 Mermaid 序列图；随后给出两张对比表（Prompt/Memory/MCP/Skills；以及 LLM→工具调用→Agent→多 Agent→增强记忆→Workflow/Manus→OpenClaw），最后用两个端到端示例展示从 prompt 到 skill 触发、执行、结果整合的完整链路。

1. 从 Prompt 到 Scripts：可操作上下文的分层谱系
1.1 Prompt
定义：Prompt 是一次模型推理的“输入上下文集合”，通常包含：系统级指令、用户输入、对话历史、工具/函数定义与工具返回、以及（可能的）外部检索片段或记忆摘要等。它不是单一字符串，而是多段结构化内容在运行时拼装后的整体。

作用：Prompt 的核心作用是把“任务意图 + 约束 + 可用能力边界 + 证据”对齐到一次或多次模型调用中。提示工程研究与实践普遍认为：结构更清晰、约束更明确的输入，通常能降低幻觉与偏航概率，但过度复杂的提示也可能带来收益递减。

示例（伪码）：

prompt = [
  system("你是一个工程助理。遵循安全与权限规则。"),
  system("可用工具: search_web, fetch_url, run_script"),
  user("总结最近的 OpenClaw skills 安全事件，并给出缓解建议。"),
  tool_result("search_web", {...}),  // 后续回填
]
response = LLM.generate(prompt)
最佳实践：把 Prompt 当作“输入合约（input contract）”来设计：明确角色、目标、不可做的事、以及可用工具边界；将可变信息（证据、运行参数）从不可变规范（策略、格式）中分离，减少“提示耦合”。

常见误区：把 Prompt 等同于“几段话术”；把所有背景一次性塞进上下文导致窗口膨胀；在缺乏证据时要求模型“给出权威结论”，诱发编造。

1.2 普通提示词
定义：普通提示词指以自然语言为主的指令/问答式输入，输出期望也通常是自然语言。它强调“人类可读”，但对模型而言约束较松。

作用：快速表达意图与评估模型能力；适合探索性对话、创意生成、粗略方案讨论。

示例：

请用中文解释 OpenClaw 的 skills 机制，说明它与 MCP、工具调用的关系，并给出工程化最佳实践。
最佳实践：用“任务 + 受众 + 约束 + 输出格式”四件套写法减少歧义；把不可妥协的约束（安全、权限、引用）写成显式规则。

常见误区：把复杂工作流交给一个“长句”提示；把“过程”隐藏，只要“结果”，导致模型在中间步骤难以自纠错。

1.3 结构化提示词
定义：结构化提示词是指把输入/输出组织为明确结构（如分隔区块、YAML/JSON、表格约束、或直接使用函数/工具调用的 JSON Schema 合约）。在现代 API 里，它往往与“工具调用（tool/function calling）”与“结构化输出（structured outputs）”绑定。

作用：把部分“语言问题”变成“接口问题”：模型只负责选择工具与生成参数，运行时负责执行与校验，从而提升确定性与可测试性。

示例（OpenAI 风格工具定义，JSON Schema）（示意）：

{
  "tool": {
    "name": "search_web",
    "description": "在互联网上检索最新信息并返回结果列表",
    "parameters": {
      "type": "object",
      "properties": {
        "q": { "type": "string" },
        "recency_days": { "type": "integer" }
      },
      "required": ["q"]
    }
  }
}
这类“用 schema 定义工具输入”的机制是 entity ["company","OpenAI","ai research company"] 与 entity ["company","Anthropic","ai safety company"] 文档中共同强调的能力形态：工具输入可被校验，非法参数可直接失败并回传给模型进入下一轮修正。

最佳实践：
把“结构”用在真正需要确定性的地方（工具参数、输出格式、可审计报告）；对 schema 做“向后兼容”设计（可选字段、版本号）；将工具返回做成“短而有效”的上下文，不把大段日志原封不动塞回模型。

常见误区：以为“给了 JSON schema 就必然严格遵守”；在流式场景下把工具调用 JSON 当作字符串拼接，造成半截 JSON/非法 JSON；把“结构化提示”误用为“更长的模板”，反而增加 token 负担。

1.4 Command
定义：Command 是“绕过自然语言推理、直接驱动控制流”的输入形式。典型表现是 Slash Commands（/...）或 CLI 子命令，其语义更接近“操作系统命令/协议帧”而不是问答。OpenClaw 的文档将其明确为由 Gateway 处理：多数命令必须是以 / 开头的独立消息；并存在“directives”（如 /think、/model、/exec）这类会在进入模型前被剥离的控制指令。

作用：

把“会话状态”（模型选择、推理强度、是否允许 exec、队列模式等）显式化；
在安全与可预期性要求更高的场景下，把路径从“模型决定”改为“确定性分发”。OpenClaw 甚至允许 skill 声明 command-dispatch: tool，使某些 skill 命令直接路由到工具而完全不经模型。
示例（OpenClaw）：

/status
/skill pdf-processing ./input.pdf
/think high
/exec host=sandbox security=allowlist ask=on-miss
最佳实践：把命令系统当作“控制平面 API”：做授权（allowlist）、审计、以及“默认拒绝”（deny wins）的策略；让普通自然语言只走“数据平面”（模型推理与工具组合），避免把权限控制混进 prompt。

常见误区：把 commands 当作“更强 prompt”，把敏感信息与权限开关暴露在群聊或不可信入口；把“命令执行成功”误判为“任务已安全完成”，忽视命令链路带来的副作用（例如环境被修改、凭据常驻、配置漂移）。

1.5 Metadata description
定义：Metadata description 是“给模型/运行时用于发现、筛选、触发与治理”的紧凑描述层。在 AgentSkills/Skill 体系里，它通常落在 SKILL.md 的 YAML frontmatter（至少 name 与 description），决定“这个 skill 何时该被使用”。

OpenClaw 在此基础上扩展了更强的运行时 metadata：其技能解析器要求 frontmatter key 多为单行，并建议 metadata 为单行 JSON 对象；metadata.openclaw 可声明依赖（需要哪些 bins/env/config）、平台限制（OS）、安装器规格、以及与 skills.entries.<name> 的注入与配置绑定。

作用：

发现与触发：启动时只加载 name/description，让模型用低成本“知道有哪些技能”，再在匹配时加载正文。
过滤与治理：运行时据 metadata 决定 skill 是否“eligible”（可用），例如缺少二进制依赖或环境变量则不加载，避免“模型看到不可执行能力”导致失败循环。
安全与权限边界：通过 disable-model-invocation 让 skill 不进入模型提示，仅允许用户显式调用；或通过 command-dispatch: tool 走确定性路径。
示例（一个合并“规范 + OpenClaw gating”的 SKILL.md 头部）：

---
name:web-research
description:面向技术调研的证据检索与引用汇总。用户提到“最新/近况/对比/引用来源”时使用。
metadata:{"openclaw":{"os":["darwin","linux"],"requires":{"config":["web.enabled"]}}}
user-invocable:true
disable-model-invocation:false
---
最佳实践：把 description 写成“可检索的触发器”（包含用户可能说的关键词 + 明确的使用边界）；把平台/依赖写入 metadata 而不是正文；为 metadata 加版本号与作者信息，便于审计与回滚。元数据质量直接影响“技能检索是否被投毒/误选”，属于治理重点。

常见误区：description 过于抽象（“帮助你更高效”）导致检索泛化；metadata 与实际行为不一致（“只读”却要求执行脚本）；将复杂 JSON 放入 OpenClaw 不支持的多行 frontmatter，导致解析失败。

1.6 Reference
定义：Reference 是“技能执行时按需加载的补充材料”，典型形态是独立 Markdown 文档、表单填写指南、API 参考、政策/规范等。AgentSkills/Claude 的最佳实践明确建议：SKILL.md 类似目录（table of contents），详细材料放到 reference.md、FORMS.md、examples.md 等文件里，必要时再加载。

作用：

把上下文窗口当作“公共资源”：只在需要时消耗 token；
让参考资料成为可审计资产（版本控制、diff、评审）；
让技能正文保持短小，降低触发成本。
示例（目录结构）（来自 Claude 最佳实践示意）：

pdf/
├── SKILL.md
├── FORMS.md
├── reference.md
├── examples.md
└── scripts/
    ├── analyze_form.py
    ├── fill_form.py
    └── validate.py
最佳实践：reference 以“可定位、可检索”为第一原则：短段落、强标题、明确输入输出示例；在 SKILL.md 中用相对路径链接引用文件；把组织级 SOP/安全策略放进 references 而不是写进 prompt 模板里。

常见误区：把 reference 当作“知识仓库倾倒点”，导致加载成本巨大；把敏感信息（密钥、内网地址）放入 reference，形成泄漏面；引用链过深（reference 里再引用 reference）使 agent 在执行时迷失。

1.7 Scripts
定义：Scripts 是技能包内的可执行代码（Python/Bash/JS 等），其关键点在于：脚本应被“执行”而不是“加载进上下文”。Claude 的技能目录示例明确标注 scripts 为“executed, not loaded”。AgentSkills 规范也把 scripts/resources 放在渐进式披露的第 3 层：仅在需要时才使用。

作用：把确定性步骤外包给传统程序：解析/校验/格式化/批处理等；从而提升可测试性、可复现性，并降低“让模型凭 token 模拟执行”的错误率。

示例（SKILL.md 中声明可用脚本）：

## Available scripts
- scripts/extract_citations.py — 从网页抓取结果中抽取主张与证据片段
- scripts/normalize_md.py — 把输出归一化为团队博客模板

执行规则：优先运行脚本，不要尝试在对话中“脑补执行”。
最佳实践：

运行脚本前先做输入校验与最小权限（workspace-only、deny-by-default）；
将脚本视作供应链依赖：需要签名、审计、锁版本与 CI 验证；
把“验证步骤”写进 skill（例如 validate.py），形成反馈闭环，避免错误一路传播到最后一步。
常见误区：把 scripts 当作“更强的 prompt”，允许其在宿主机任意执行；从不审计第三方 skills/scripts；将“安装依赖”写成一条不透明的 curl | bash 指令，制造典型社会工程入口。

2. Skill：最新概念、组成与运行机制
2.1 “Skill”在 2026 语境下的严格定义
从规范与主流实现看，一个“Skill”更接近如下定义：

Skill = 可发现的元数据 + 可执行/可操作的过程性指令 + 可选资源（references/assets/scripts） + 渐进式加载策略 +（可选）权限/环境门控。

AgentSkills 规范给出了最小合约：skill 是包含 SKILL.md 的目录；启动时加载 name/description，激活时加载正文，运行时按需加载 resources。 Claude、GitHub Copilot、VS Code 等实现都围绕这一文件系统布局展开，并强调“目录名与 name 匹配、description 要写清何时使用”。 OpenClaw 明确声明其 skills 文件夹兼容 AgentSkills，并在运行时做额外 gating 与命令联动。

2.2 Skill 的组成成分拆解
下面给出一个面向工程实现的“Skill 组件清单”（不是唯一标准，但与主流规范兼容）。

接口（Interface）：Skill 对外至少暴露“何时使用（trigger）”与“如何调用（instructions）”。在实践里，接口由两层构成：

发现接口：name/description（以及可选 trigger hints、兼容性信息）；
执行接口：正文指令 + 告诉 agent 需要哪些工具、需要读哪些 reference、要运行哪些 scripts。
Schema（合约/结构）：

对“工具调用”的 schema：通常是 JSON Schema（OpenAI/Anthropic 工具接口）或 MCP 的 tool schema；
对“skill 输入”的 schema：行业里有两种常见做法：
轻量做法：让 skill 在指令中要求模型先提取字段并以固定格式呈现；
强约束做法：将 skill 暴露为一个 tool（SkillTool），用 JSON Schema 约束 skill 的输入参数，再由运行时装载 skill 正文与资源。
能力描述（Capability description）：description 是核心，决定检索命中质量。学术综述将其视为“Pattern-1：Metadata-Driven Disclosure”的关键风险面：元数据写错会导致误检索或被投毒。

输入/输出（I/O）：

输入：用户原始意图 +（可选）从对话中结构化提取的槽位参数 +（可选）执行上下文（workspace 路径、会话状态、工具权限）；
输出：对用户的自然语言结果 +（可选）结构化产物（JSON、补丁、文件、外部系统状态变更）。OpenAI 的 Responses API 设计把“tool call”与“tool output”作为可关联的 item（call_id），便于回放与评估。
状态/上下文（State/Context）：技能执行往往依赖会话状态（已检索到的证据、已生成的 artifacts、已运行的命令与返回码）。在工程实现上，常见做法是将其放入 Agent state（LangGraph/LangChain 语境）或 SDK 提供的内置 agent loop 状态。

错误处理（Error handling）：技能的价值之一是“把错误处理流程也固化下来”：例如命令失败时要收集 stderr、调整参数重试、或回退到保守策略。SoK 指出：把“恢复（recovery）”当作一等技能，会带来可治理性与可信度上的要求（恢复 skill 必须至少与被恢复 skill 同等可信）。

2.3 Skill 的运作流程：触发、解析、执行、回调与结果整合
下面用一个“兼容 AgentSkills/OpenClaw”的通用流水线描述技能生命周期（阶段名与 OpenClaw/AgentSkills 的术语做了对齐）。

flowchart TD
  A[Discover: 扫描技能目录] --> B[Index: 仅加载name/description等元数据]
  B --> C{Match: 与用户意图匹配?}
  C -- 否 --> D[继续普通对话/工具调用]
  C -- 是 --> E[Activate: 加载SKILL.md正文]
  E --> F{Need refs/assets?}
  F -- 是 --> G[Load refs/assets: 按需读取文件]
  F -- 否 --> H[Execute: 进入Agent Loop]
  G --> H
  H --> I{Need scripts/tool calls?}
  I -- 工具调用 --> J[Tool call -> 执行 -> tool result回填]
  I -- 运行脚本 --> K[Run script -> stdout/stderr -> 回填]
  J --> H
  K --> H
  H --> L[Integrate: 汇总结果与证据]
  L --> M[Respond: 输出给用户 + 可选产物]
这一流程与 AgentSkills 的“渐进式披露三层结构”一致：先元数据，再正文，再资源；也与 OpenClaw 的“加载/过滤/注入/执行/回填”相吻合。

在 OpenClaw 中，上述阶段还会叠加若干运行时细节：

多来源与覆盖优先级：bundled → ~/.openclaw/skills → <workspace>/skills，同名 skill 可被更高优先级覆盖。
Load-time gating：读取 metadata.openclaw.requires（bins/env/config）决定 skill 是否 eligible；并支持在一次 agent run 内注入 env、结束后还原。
Prompt 注入策略：把“可用技能清单”以紧凑 XML 列表注入系统提示，并给出确定的字符成本公式，便于估算 token 开销。
Slash command 联动：user-invocable skill 会暴露为 slash command；并可选择“转发给模型”或“command-dispatch: tool”确定性执行。
2.4 Skill 与大模型的交互模式：同步/异步、流式/批量
同步 vs 异步：

同步：模型发起工具调用，运行时立即执行并回填，再让模型生成最终结果；这是传统函数调用/agent loop 的默认形态。
异步：长耗时任务（爬取、编译、批处理）常被放入后台队列/进程；OpenClaw 的 exec 支持前台/后台以及配套的 process 工具来管理后台会话。 工程建议是：把异步当成“第一类控制流”，否则技能一旦遇到长任务就会出现超时、截断或上下文漂移。
流式 vs 批量：

流式：模型边生成边产出工具调用片段、或边生成边汇总结果；流式对“结构化输出”更苛刻，容易出现半截 JSON，需要修复策略。
批量：将多个 tool call 规划好后批量执行，再一次性把关键结果回填；在强调效率与可复现的技能里更常见。
与 MCP 的关系：MCP（在 LLM 生态中通常指 Model Context Protocol）把“工具/资源/提示”等能力以标准化的 JSON-RPC 客户端/服务器架构暴露给 Host 应用，并支持多种传输；它解决的是“怎么连工具与数据源”的 N×M 集成问题，而 Skills 更偏“教 agent 怎么用这些工具完成 SOP”。

2.5 示例实现：一个最小 Skill 引擎（伪码）与序列图
下面给一个“最小技能引擎”伪码：它体现 AgentSkills 的 5 步最小要求（discover → load metadata → match → activate → execute）。

class SkillIndexItem:
  name: string
  description: string
  path: string
  metadata: map

class SkillEngine:
def discover(skills_dirs) -> list[SkillIndexItem]:
    items = []
    for dir in skills_dirs:
      for skill_dir in list_subdirs(dir):
        if exists(skill_dir+"/SKILL.md"):
          fm = parse_yaml_frontmatter(skill_dir+"/SKILL.md")
          items.append(SkillIndexItem(
            name=fm.name,
            description=fm.description,
            metadata=fm.metadata,
            path=skill_dir
          ))
    return items

def eligible(item, runtime_env) -> bool:
    # OpenClaw 风格：按 OS/bins/env/config 门控
    return satisfies(item.metadata, runtime_env)

def match(user_msg, index_items) -> SkillIndexItem?:
    # 最简：embedding/关键词；工程上应加投毒防护与阈值
    return best_semantic_match(user_msg, index_items)

def run(user_msg):
    index = [i for i in discover(dirs) if eligible(i, env)]
    skill = match(user_msg, index)
    ifnot skill:
      return llm_generate(normal_prompt(user_msg, index))

    full = read_file(skill.path+"/SKILL.md")          # Activate
    prompt = build_prompt(user_msg, index, full)      # 注入 skill 清单 + 正文
    whileTrue:                                       # Agent loop
      out = llm_generate(prompt, stream=True)
      if out.is_tool_call:
        result = execute_tool(out.tool_name, out.args)
        prompt.append(tool_result(out.call_id, result))
      else:
        return out.final_text
对应的交互序列如下：

sequenceDiagram
  participant U as User
  participant G as Gateway/Agent Runtime
  participant M as LLM
  participant T as Tools/Sandbox
  U->>G: message
  G->>G: discover+load metadata (name/description)
  G->>G: match & activate (load SKILL.md)
  G->>M: prompt (skills index + skill body)
  M-->>G: tool_call(args)
  G->>T: execute tool / script
  T-->>G: tool_result(stdout/stderr/data)
  G->>M: tool_result (call_id关联)
  M-->>G: final answer (integrated)
  G-->>U: response
该序列与 OpenAI 的“tool calls 与 outputs 通过 call_id 关联”的实践一致，也符合 OpenClaw 的“Gateway 组装 prompt、工具在 sandbox/host 执行、结果回填”的形态。

3. 机制对比：Prompt / Memory / MCP / Skills
Prompt 更像“当前对话的瞬时指令”，优势是低门槛与即时性，劣势是不可持久与难治理；Skills 像“可版本化 SOP 包”，在一致性、可复用、可审计上更强，但引入供应链与权限治理成本。
MCP 的核心价值在“标准化连接外部工具/数据（协议层）”，而 Skills 的核心价值在“标准化可复用过程（方法层）”；二者互补：MCP 给“手”，Skill 给“操作手册”。
机制
定义
持久性
可编程性
可组合性
调用延迟
示例场景
提示词（Prompt）
一次推理的输入上下文集合（系统/用户/历史/工具结果等）
低（默认随会话消失）
低到中（主要靠提示工程）
中（可拼接模板，但易冲突）
低（单轮调用）
快速问答、头脑风暴、一次性总结
记忆（Memory）
跨轮保存的对话/状态/检索片段（短期或长期），供后续调用检索
中到高（取决于存储与策略）
中（需要检索、压缩、冲突处理）
中（可被多个技能/工具复用）
中（检索+融合）
个性化助理、长任务跟踪、跨会话项目协作
MCP
Model Context Protocol：以 JSON-RPC 标准化“LLM 应用 ↔ 外部工具/数据源”连接
中（server/connector 常驻）
高（工具/资源以协议暴露）
高（多 server 组合）
中（网络/鉴权/执行）
IDE 接入代码库、企业系统连接（CRM/DB/工单）
Skills
以目录为单位的可移植能力包：SKILL.md +（可选）references/assets/scripts；渐进式披露加载
高（版本化、可共享）
高（可运行脚本/约束流程）
高（可同时加载多个 skill）
中到高（匹配+激活+执行）
代码评审 SOP、自动化报表、受控的数据处理流水线

备注：这里的 “MCP” 在 LLM 场景下通常指 Anthropic 提出的 Model Context Protocol。

4. 框架演进：从 LLM 到 OpenClaw
从 LLM → Tool Calling → Agent 的演进，本质是在把“控制流”从人类手工（写提示、点按钮）转移到运行时（agent loop），再用更强的结构（skills/workflow）把不确定性收束到可治理范围。
OpenClaw 的“产品化差异”在于：它把 agent 变成常驻基础设施（多入口聊天应用 + 本地执行 + 可安装技能市场），因此其主要挑战从“能不能做事”转向“能不能在开放生态里安全地做事”。
阶段
架构层级
控制流
状态管理
扩展性
典型实现/开源项目
适用场景
优缺点
LLM
单次生成
人工组织 prompt
低（主要靠对话历史）
低
通用对话 API / 提示工程总览
问答、生成、分析
👍简单；👎不可控、难复现
工具调用
LLM + tools
模型选择工具、运行时执行
中（工具结果回填）
中
OpenAI function calling；Claude tool use
结构化参数调用、RAG、自动化步骤
👍更确定；👎工具描述/返回需精心设计
Agent
LLM + tool loop
运行时循环直到 stop condition
中到高（state/checkpoints）
中到高
LangChain Agents；OpenAI Agents SDK（内置 agent loop）
多步任务、交互式执行
👍会规划迭代；👎易循环/漂移，需护栏与评估
多 Agent 协同
多 agent + 路由/对话协议
分工、handoff、协作对话
高（跨 agent 协作状态）
高
Microsoft AutoGen（多 agent 对话框架）
复杂项目拆解、角色协作
👍并行与分工；👎状态与一致性更难、成本更高
增强记忆的 Agent
agent + 长短记忆
控制流同 agent，但记忆参与决策
高（长期存储+检索）
中到高
LangGraph/LangChain memory；Generative Agents 架构
个性化助理、长周期任务
👍连续性强；👎隐私与污染风险、需压缩与治理
Workflow / Manus
workflow 引擎 + agent（或 agent 平台）
更显式的图/流程/约束，或“CodeAct”式执行
高（强状态机/虚拟环境）
高
LangGraph 图式编排；Manus（行动引擎/工作流执行）
可重复业务流程、端到端交付
👍可控、可观测；👎搭建成本高、需要更多工程能力
OpenClaw
常驻 agent 平台 + skills 市场 + 本地执行
Gateway 命令/指令 + agent loop + 可选确定性分发
高（session、workspace、插件槽等）
很高（skills、plugins、registry）
OpenClaw（自托管、聊天入口、多工具与技能）
个人/小团队自动化、跨应用操作
👍“能做事”的可用性强；👎安全面巨大、供应链与权限治理是硬问题

4.1 重点：OpenClaw 的机制解剖、信息来源与不确定性
信息来源（相对确定）：

OpenClaw 官方仓库与文档明确其定位：运行在用户自有设备上、通过已有聊天渠道交互；并强调 Gateway 是控制平面（control plane）。
Skills 文档明确：兼容 AgentSkills；多目录加载与覆盖优先级；load-time gating（bins/env/config）；会话快照/热更新；以及把技能清单注入系统 prompt 的方式。
Slash Commands 文档明确：命令由 Gateway 处理；directives 会在模型看到消息前被剥离；skill 可作为命令暴露，并可配置为直接 dispatch 到工具。
ClawHub 文档明确：作为公开 registry，提供版本化存储与发现；支持 install/update/publish/sync；并描述了默认开放上传与“GitHub 账号至少 1 周”之类的 moderation 策略。
Plugins 文档明确：插件加载的目录/ID 规则、配置 schema 校验、以及若干安全护栏（例如路径不能逃逸、安装依赖时 --ignore-scripts）。
公开资料稀少或仍在变化的部分（需要保留不确定性）：

“技能匹配/检索”具体算法（embedding、关键词、阈值、是否有对抗投毒防护）通常不会在产品文档里详述；SoK 提到 metadata-driven disclosure 的风险，但具体实现策略依赖各平台。
多 agent/远程节点/沙箱与权限的组合细节在快速迭代，且安全修复频繁（这类系统高度时变）；因此任何“架构推断”都应以源码与版本为准，并配套验收测试。
在不完整信息下的合理架构推断（可验证）：
基于官方文档，“OpenClaw 的核心循环”可以被验证性地理解为：

Gateway 接收消息并先做 command/directive 解析；
构建会话级上下文（含技能清单 XML、工具策略、可选激活 skill 正文）；
调用外部模型；
若模型发起工具调用，则在 sandbox/host 执行并回填；
进入下一轮直到产出最终响应；
会话状态与技能快照在 session 维度管理。
你可以用两类“可验证建议”来验证/替代上述推断：

验收测试（黑盒）：构造一个只含 2 个 skill 的环境（一个可用、一个因缺少 bin/env 被 gating），观察系统提示内 skills list 是否包含/不包含它，并用 /context detail（OpenClaw 提供的上下文可视化命令）确认 token 分布与注入内容。
替代实现（白盒）：若不使用 OpenClaw，也可用“OpenAI Agents SDK + MCP + AgentSkills 文件夹”搭建同构系统：SDK 提供 agent loop 与 handoffs，MCP 提供工具/数据接入，AgentSkills 提供可移植 SOP 包。
安全重点：OpenClaw 及其 skills 生态的公开事件显示：开放 registry 与“markdown 指令 + 可执行脚本”的组合会形成供应链攻击面；多家安全报告与新闻指出了恶意 skills、信息窃取与隔离建议； entity ["company","Microsoft","software company"]  的安全博客也明确建议将 OpenClaw 视为“带持久凭据的不可信代码执行”，仅在隔离环境中运行。

5. 端到端示例：两个完整场景
下面两个示例分别覆盖：

示例一：信息检索 + 工具调用（强调结构化工具与证据汇总）；
示例二：多步骤任务自动化（强调 command 显式触发 + scripts 确定性执行 + 结果整合）。
5.1 示例一：技术调研与证据汇总（自动触发 Skill）
目标：用户问“最近 OpenClaw Skills 的安全事件有哪些？我该如何安全使用？”系统自动触发 web-research skill：先检索、再抓取、再抽取证据、最后按模板输出“主张-证据-建议”。这一类 workflow 对“可信引用”敏感，适合用 skill 固化流程并用工具做检索与抓取。

Skill 目录结构（示例）：

web-research/
├── SKILL.md
├── references/
│   ├── source_policy.md
│   └── output_template.md
└── scripts/
    ├── extract_claims.py
    └── dedupe_sources.py
SKILL.md（核心片段）：

---
name: web-research
description: 当用户要求“最新/近况/引用来源/对比”时，执行证据驱动的技术调研并输出可追溯引用。
---

# Web Research

## Rules
1) 先检索再下结论；2) 每个关键主张必须对应来源；3) 遇到相互矛盾的来源要并列呈现并说明不确定性。

## References
- references/source_policy.md
- references/output_template.md

## Procedure
1) 用 search_web 获取候选来源（优先官方/论文/权威媒体）
2) 用 fetch_url 抓取全文
3) 运行 scripts/dedupe_sources.py 去重
4) 运行 scripts/extract_claims.py 抽取“主张-证据片段”
5) 按模板生成最终报告，并附来源列表
该写法符合“SKILL.md 作为总览，细则与模板在 references，确定性处理在 scripts”的最佳实践。

工具定义（结构化提示的一部分，示意）：

[
  {
    "name": "search_web",
    "description": "检索最新网页并返回[{title,url,snippet,date}]",
    "parameters": { "type": "object", "properties": { "q": {"type":"string"} }, "required": ["q"] }
  },
  {
    "name": "fetch_url",
    "description": "抓取url正文并返回{text,meta}",
    "parameters": { "type": "object", "properties": { "url": {"type":"string"} }, "required": ["url"] }
  },
  {
    "name": "run_script",
    "description": "在沙箱内运行技能脚本，返回stdout/stderr/exit_code",
    "parameters": { "type": "object", "properties": { "path":{"type":"string"}, "args":{"type":"array"} }, "required":["path"] }
  }
]
这对应主流“用 JSON Schema 描述工具输入”的实践。

端到端时序图：

sequenceDiagram
  participant U as User
  participant A as Agent Runtime
  participant M as LLM
  participant W as Web Tools
  participant S as Sandbox (scripts)
  U->>A: "总结最近OpenClaw skills安全事件并给建议（含引用）"
  A->>A: match skills index ->> activate web-research
  A->>M: prompt + web-research(SKILL.md)
  M-->>A: tool_call search_web(q)
  A->>W: search_web
  W-->>A: results[]
  A->>M: tool_result(call_id=1)
  M-->>A: tool_call fetch_url(url...) xN
  A->>W: fetch_url xN
  W-->>A: pages{text} xN
  A->>S: run_script(dedupe_sources.py)
  S-->>A: deduped list
  A->>S: run_script(extract_claims.py)
  S-->>A: claims+citations
  A->>M: tool_results merged
  M-->>A: final report (claims + sources + mitigation)
  A-->>U: response
关键实现片段（处理 OpenAI Responses 工具回填的思路，伪码）：

resp = responses.create(input=prompt, tools=tools, stream=true)
for item in resp.items:
  if item.type == "tool_call":
    result = exec_tool(item.name, item.arguments)
    responses.submit_tool_output(call_id=item.call_id, output=result)
这里的关键是“tool call 与 tool output 分离，并用 call_id 关联”，便于可观测与评估。

5.2 示例二：多步骤任务自动化（显式 Command + 确定性 Scripts）
目标：用户在 OpenClaw 里用命令触发一个“发布说明自动生成”流程：从仓库拉取最近变更 → 根据模板生成 release notes → 写入 workspace 文件并回传摘要。该例故意用 /skill <name> 显式触发，以展示“command 作为控制平面”的作用。

Skill 目录结构（示例）：

release-notes/
├── SKILL.md
├── references/
│   └── notes_template.md
└── scripts/
    ├── git_log.sh
    └── render_notes.py
SKILL.md（含 command 相关 frontmatter 的 OpenClaw 风格示例）：

---
name:release-notes
description:为代码仓库生成发布说明；当用户说“发版说明/变更日志/releasenotes”或执行/release-notes时使用。
user-invocable:true
command-dispatch:tool
command-tool:exec
command-arg-mode:raw
---
command-dispatch: tool 表示：当用户用 /release-notes ... 触发时，不走模型推理路径，而是直接把命令分发到指定工具，以获得确定性（例如直接执行脚本入口）。此能力在 OpenClaw 的 skills 与 slash commands 文档中明示。

命令触发：

/release-notes repo=. since="7 days"
端到端时序图：

sequenceDiagram
  participant U as User
  participant G as OpenClaw Gateway
  participant X as Exec Tool (sandbox/host)
  participant P as Process Tool
  participant F as Filesystem Tools
  U->>G: /release-notes repo=. since="7 days"
  G->>G: command parsing + authz
  G->>X: exec("scripts/git_log.sh --since '7 days'")
  X-->>G: stdout (commit list) + exit_code
  alt long running
    G->>P: track background session
    P-->>G: status/result
  end
  G->>X: exec("python scripts/render_notes.py --template references/notes_template.md")
  X-->>G: release_notes.md content
  G->>F: write("release_notes.md", content)
  F-->>G: ok
  G-->>U: 摘要 + 文件路径 + 可选 diff
这里用到了 OpenClaw 文档中描述的 exec（前台/后台）与 process（管理后台会话）思路，以及 slash command 解析由 Gateway 执行。

脚本片段示例（简化版）：

# scripts/git_log.sh
git log --since="$1" --pretty=format:"- %s (%h) by %an"
# scripts/render_notes.py (伪代码风格)
import sys
commits = sys.stdin.read().splitlines()
template = open("references/notes_template.md").read()
notes = template.replace("{{COMMITS}}", "\n".join(commits))
print(notes)
工程要点：这个例子刻意让“关键步骤都在 scripts 里”，把模型扮演的角色降到最低：模型不需要“幻想执行 git”，而是读取脚本输出并做轻量整合。

6. 结论与后续研究清单
6.1 结论
“Skills”的最新含义可以概括为：用标准化目录结构把“方法（SOP）”产品化，并用渐进式披露把上下文成本最小化；它与工具调用、MCP、记忆共同构成“Agent 工程栈”的不同层次：MCP 解决连接，工具调用解决接口与参数，Skills 解决方法与一致性，记忆解决跨时延续。

OpenClaw 则是这一工程栈的一种“平台化落地”：它把 skills、commands、plugins、registry、沙箱/工具策略与多入口聊天整合为常驻系统；其优势是“非常接近真实生产力”，其风险也同步放大为“真实的权限与供应链安全问题”。因此，对技术团队而言，OpenClaw 更像一个值得研究的“参照架构”，而不是不加隔离就能直接引入企业内网的通用解。

6.2  进一步研究与实现建议清单
为 Skills 引入 CI/CD 与评估飞轮：把每个 skill 当作软件包，建立版本号、变更日志、lint/validate（如 skills-ref validate）与回归评估；可参考评估框架与“把技能纳入 Evals”类实践，形成持续改进闭环。
把“元数据安全”当作一等问题：对 description 做质量门控（避免过宽、避免误导、避免注入式关键词堆砌），并对 skill 检索加入防投毒策略（阈值、白名单、交叉验证、多路检索）。
最小权限与分层隔离：工具策略坚持 deny-wins；高风险工具（exec、browser、web_fetch/search）默认关闭或仅 allowlist；运行时尽量 sandbox；把凭据注入限制为“会话内、最小集合、可轮换”。
把 Scripts 当作供应链依赖治理：强制审计第三方 scripts；拒绝不透明安装指令；对 curl | bash 等模式在执行层直接拦截或需要人工批准；对外部依赖锁版本并记录 SBOM。
优先“确定性外包”：对解析、验证、格式化、diff、patch 这类任务，优先写脚本而不是让模型凭 token 模拟；并在 skill 中固化验证步骤与失败恢复路径。
MCP + Skills 的组合设计：用 MCP 暴露标准化工具/资源，把 Skills 作为“如何用这些工具”的 SOP；在企业内可先做私有 MCP server 与私有 skills registry，避免直接接入开放市场。
对 OpenClaw 做“可验证的渐进式采用”：先在隔离环境验证 commands/tool policy/sandbox；只引入少量自研 skills；对 ClawHub/第三方 skills 采取默认禁止策略；通过 /context detail 或类似可观测命令持续测量上下文与权限变化。
替代方案路线图：如果目标是企业级可控自动化，可考虑“Agents SDK（agent loop）+ LangGraph（可控流程）+ MCP（工具接入）+ AgentSkills（SOP 包）”的组合式自建；用更小的攻击面获得 OpenClaw 式能力。
7. 写在最后
我正式的接受计算机教育要从本科说起，那时候大部分时间在学习数据结构和编程语言，实际上是学习数字世界如何进行描述的。还十分抽象，因为是从面向过程的编程开始学起的，而后接触到了面向对象的编程才逐渐适应了这个数字世界的运作模式。

之前，我经常听人说，程序=数据结构+算法。而后，我开始学习了算法和模型，就掌握了数字世界的运作规律。因为算法就是为数据结构施加变换规则，类似物理定律约束物质状态的演化。这样，我们就能够利用这些算法去改造数字世界和预测数字世界了。

幸运的是，后来，接触到了大模型。它其实也是模型，甚至说是算法的一个分支，但是它的出现，其实已经有“工业革命”的味道在，因为大模型是可以进行推理的，而数字世界的推理过程，和物理世界的能量运用是一样的，实际上和执行算法的效果是一样的，它是一个动态的过程，既不是物质，也不是规律，而是运行起来的程序。但是大模型有一个好处，就是我们能够越来越少的考虑能量消耗的具体形式了。类比我们现实世界的话，就可以想象，我们能够利用蒸汽机将化石燃料的能量转换为通用做功的形式，能够避免我们人类直接做功，或者避免为了特定的活动精心设计能量消耗方式。

因此大模型的性能改进，实际上是我们能够在数字世界“能量运用”水平的高低。不过，我们一直以来的梦想从不止步于此，我们希望它不仅可以自行做功，而且越来越有自我意识的做功。这不就是物理世界中，我们人类出现所带来的变化吗？

换个角度看，这又何尝不是在数字世界中，构建所谓的“人工智能”呢？

兜兜转转，我们又回来了。