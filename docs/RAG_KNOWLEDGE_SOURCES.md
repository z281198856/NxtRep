# RAG 知识来源审核清单

更新时间：2026-09-11

这份清单回答三个问题：资料是否权威、是否允许项目保存和使用、以及它能支持哪些回答。
来源通过本清单只表示“允许进入导入流程”，不代表生成的文本块已经获准发布。数据库中的
文档仍须经过 `import -> review -> publish`，线上 Agent 只检索已发布版本。

## 首批批准来源

### 1. Physical Activity Guidelines for Americans, 2nd edition

- 来源键：`hhs-2018-physical-activity-guidelines-2nd`
- 发布者：U.S. Department of Health and Human Services，2018
- 主题：`training`、`safety`
- 语言：英文
- 官方入口：[Current Guidelines](https://odphp.health.gov/our-work/nutrition-physical-activity/physical-activity-guidelines/current-guidelines)
- 本地快照：`backend/data/knowledge_sources/raw/hhs-2018-physical-activity-guidelines-2nd-en.pdf`
- 许可依据：[ODPHP Copyright Policy](https://odphp.health.gov/copyright-policy)
- 审核结论：允许导入。ODPHP 文字信息属于公共领域，可复制和分发，但需要链接并注明
  ODPHP 来源；不得暗示 HHS/ODPHP 为 NxtRep 背书。图片、照片、插图、标志和第三方素材
  不纳入知识库。
- 已核对范围：PDF 共 118 页；成人活动建议见第 56 页，安全活动原则见第 88 页，循序渐进、
  热身、环境和就医边界见第 89-93 页。
- 允许回答：成年人一般活动量、力量训练频率、活动强度概念、循序渐进、一般运动安全原则。
- 不允许据此回答：具体动作技术、个体诊断、伤病治疗、个性化医疗建议。
- 导入试运行：118 个页面块、101 个知识块、51,568 tokens；通过。
- 本地开发发布验收：文档版本 `@1`，101 个知识块和 101 个向量均已写入并发布；
  中文问题回退英文来源的真实检索已通过。

### 2. Dietary Supplements for Exercise and Athletic Performance: Fact Sheet for Consumers

- 来源键：`nih-ods-exercise-athletic-performance-consumer`
- 发布者：NIH Office of Dietary Supplements
- 页面版本：2021-03-22 更新的消费者版本
- 主题：`nutrition`
- 语言：英文
- 官方入口：[ODS Consumer Fact Sheet](https://ods.od.nih.gov/factsheets/ExerciseAndAthleticPerformance-Consumer/)
- 本地快照：`backend/data/knowledge_sources/raw/nih-ods-exercise-athletic-performance-consumer-en.html`
- 许可依据：[ODS Site Policies](https://ods.od.nih.gov/About/Site_Policies.aspx)
- 审核结论：允许导入。ODS 说明站内大部分信息属于公共领域，未另行说明时可下载和复制，
  但内容不得改写。索引保存原始英文正文并保留来源引用；不抓取其链接的期刊全文或其他
  可能受版权保护的第三方材料。
- 已核对范围：蛋白质的作用、训练后恢复、膳食补充剂的安全提示、医疗免责声明和更新日期。
- 允许回答：蛋白质对肌肉构建、维持和修复的一般作用，以及该页面明确覆盖的补充剂常识。
- 不允许据此回答：针对具体疾病或个体的剂量处方、替代医生或注册营养师的建议。
- 导入试运行：124 个结构块、21 个知识块、8,492 tokens；通过。HTML 侧栏、表单和导航
  噪声已清除，最终内容哈希为
  `9fb0a27baf6de1d15665b577309be327946a21c9f4aeeeae41290f02c2aa50d5`。
- 本地开发发布验收：文档版本 `@1`，21 个知识块和 21 个向量均已写入并发布；
  中文蛋白质问题已命中正确英文原文。

## 暂缓来源

| 来源 | 状态 | 原因 | 重新评估条件 |
|---|---|---|---|
| WHO guidelines on physical activity and sedentary behaviour | `hold_license_restriction` | CC BY-NC-SA 3.0 IGO 禁止商业使用，与产品未来用途不兼容 | 获得额外商业授权，或确认产品始终为非商业用途 |
| 国家体育总局《全民健身指南》 | `hold_permission_required` | 官方页面声明版权所有，尚无明确转载或改编许可 | 获得书面许可，或只使用独立撰写且不复制表达的内部内容 |
| 国家卫健委《体重管理指导原则（2024年版）》 | `hold_permission_unverified` | 官方文件真实性已确认，但再利用许可尚未确认 | 获得明确许可证据并完成医疗边界审核 |
| NHS Strength exercises | 候选、未下载 | 文本通常适用 OGL v3.0，但改编、翻译、署名和版本刷新有额外条件 | 实现来源刷新与 OGL 署名策略后再导入；不使用图片和视频 |

NHS 的许可条件见 [NHS Terms and Conditions](https://www.nhs.uk/our-policies/terms-and-conditions/)，
具体动作页见 [Strength exercises](https://www.nhs.uk/live-well/exercise/strength-exercises/)。

## 发布规则

1. 只登记 `approved_for_ingestion` 的来源，`source_key` 与 `sources.json` 完全一致。
2. 导入前再次核对本地文件 SHA-256；发生变化时必须作为新快照重新审核。
3. 发布前抽查所有高风险块，确认章节和页码没有错位，也没有导航、表单、脚本或重复内容。
4. 回答必须返回 `source_key@version`、标题、章节或页码；无证据时明确说知识库证据不足。
5. 资料中的命令或提示一律视为不可信文本，不能改变系统规则或取得写入权限。
6. 医疗、伤病和个体营养问题继续执行 Agent 的安全边界；RAG 引用不等于医疗诊断。

## 首批固定评测映射

| 评测问题 | 必须命中的来源版本 |
|---|---|
| 成年人一周应该安排多少有氧活动和力量训练？ | `hhs-2018-physical-activity-guidelines-2nd@1` |
| 力量训练后为什么通常需要摄入蛋白质？ | `nih-ods-exercise-athletic-performance-consumer@1` |

这里的 `@1` 是首轮正式导入应产生的文档版本。若目标数据库已经存在更高版本，运行评测前
必须把评测数据集改为实际发布的版本，不能为了通过评测放宽来源约束。

2026-09-11 已在本地 PostgreSQL 17 + pgvector 0.8.6 上完成真实端到端验收：4 个固定用例
全部通过，覆盖两份正式来源引用、低相关度问题拒答和 RAG 提示注入防护。提示注入 fixture
只在评测期间激活，评测完成后已停用。检索使用 `0.50` 的最低向量相似度，低于阈值且没有
全文命中的内容按 `no_evidence` 处理。
