#import "../templates/nsfc_template.typ": conf
#show: doc => conf(title: "复杂多 Agent 系统中的动态内存与调度算法", project_type: "面上项目", doc)

= 立项依据

动态内存与调度算法在多智能体系统（MAS）中起着至关重要的作用。以下是不同架构对比：

#table(columns: 3,
  [架构],
  [延迟 (ms)],
  [吞吐量],
  [传统轮询],
  [120],
  [500],
  [事件驱动],
  [45],
  [1200],
  [混合调度],
  [20],
  [2500],
)

= 研究目标与内容

本项目拟解决资源受限下的内存回收问题，核心动态调度方程如下：

$ E = integral_0^T (P(t) - L(t)) dif t + sum_(i=1)^N alpha_i $

其中 $P(t)$ 为处理能力，$L(t)$ 为负载，$alpha_i$ 为动态惩罚项。

= 研究方案与可行性



= 特色与创新



= 研究基础



= 参考文献


