# BBox-DocVQA Improvement Plan

## 论文主线

建议把论文主线定义为：

**BBox-DocVQA 不只是一个普通的 Document QA 数据集，而是提供从 query 到局部证据区域的监督，用于连接 document QA、visual grounding 和 fine-grained RAG。**

围绕这个主线，实验不要拆成 3 个彼此平行的小点，而应该组织成：

1. Evidence-conditioned QA
2. Query-conditioned Localization
3. Hierarchical Visual RAG
4. 关键消融与分组分析

这样更像一篇完整论文，而不是一个只展示数据集样例的 benchmark。

---

## Task 1: Evidence-conditioned QA

这是最重要的主实验，用来回答：

**更精细的证据输入，是否能够显著提升 DocQA 表现？**

建议至少做以下 5 个输入设置：

1. **Whole document**
   直接给整个 PDF 或全部页面。

2. **Retrieved / selected page**
   给检索到的 page，作为真实系统设置。

3. **Ground-truth evidence page**
   给标注的证据页，作为 page-level oracle。

4. **Predicted bbox crop**
   给模型预测出的证据框 crop，作为真实 bbox 系统设置。

5. **Ground-truth evidence subimage**
   给标注 bbox 对应的 crop，作为 upper bound。

### 这组实验的作用

- `Whole document -> GT evidence page` 的提升，体现 page-level evidence selection / RAG 的价值。
- `GT evidence page -> GT evidence subimage` 的提升，体现 fine-grained bbox evidence 的价值。
- `Predicted bbox -> GT bbox` 的差距，体现定位误差对最终 QA 的影响。

### 为什么不能只做 3 个设置

如果只做：

- whole document
- evidence page
- evidence subimage

那么只能证明 oracle 条件下的趋势，缺少真实系统中的 `predicted bbox`，论文会缺一个关键环节。

---

## Task 2: Query-conditioned Localization

这是第二个核心任务，用来回答：

**模型能不能根据 query，在给定 evidence page 的条件下，准确找出答案所在区域？**

实验设置：

- 输入：`query + evidence page`
- 输出：预测 bbox
- 监督：标注 bbox

### 推荐指标

不要只用单一 IoU，建议同时报告：

- `Mean IoU`
- `Recall@IoU=0.3`
- `Recall@IoU=0.5`
- `Recall@IoU=0.7`
- `Center Point Accuracy` 或 `Hit@1`

### 多框样本的处理

数据集中存在多页、多框证据，因此建议补充以下评估方式：

- 单框样本：标准 IoU
- 多框样本：`max IoU` 或 `coverage-based recall`

这样更公平，也更符合真实 query 可能对应多个证据区域的情况。

### 必做分组分析

建议至少按以下维度分别汇报：

- `text / table / image`
- `single-page / multi-page`
- `single-region / multi-region`

这能说明模型到底擅长定位什么类型的视觉证据，也能体现数据集的结构价值。

---

## Task 3: Hierarchical Visual RAG

第三部分不建议只做 page-level retrieval，也不建议只做 bbox-level retrieval，而应该做成层级式系统：

1. **Page retrieval**
2. **Region localization / region retrieval within page**
3. **Reader answering on retrieved evidence**

### 为什么要做层级式

如果只做 page-level，reviewer 会问：

**既然只评 page retrieval，那 bbox 标注的意义是什么？**

如果只做 bbox-level，reviewer 会问：

**真实长文档里，page selection 怎么处理？**

因此最佳方案是同时覆盖 coarse retrieval 和 fine-grained retrieval。

### 推荐评估指标

分三层报告：

1. **Page retrieval**
   - `Page Recall@1`
   - `Page Recall@3`
   - `Page Recall@5`

2. **Region retrieval / localization**
   - `Region Recall@1`
   - `Region Recall@k`
   - `BBox Recall@IoU=0.5`
   - `Mean IoU`

3. **End-to-end QA**
   - `Exact Match`
   - `ANLS`（如果答案存在轻微文本变体）
   - 其他适合你的 QA 指标

### 推荐系统对比

至少比较以下三条管线：

1. **Doc -> Reader**
   不做检索，直接从整篇文档回答。

2. **Doc -> Page Retriever -> Reader**
   只做 page-level evidence selection。

3. **Doc -> Page Retriever -> Region Localizer / Region Retriever -> Reader**
   做完整的层级式 RAG。

这会直接展示 bbox supervision 对 end-to-end 决策质量的贡献。

---

## 关键消融实验

如果想让论文更完整，这些消融非常关键。

### 1. Oracle / Predicted 组合消融

建议至少报告以下组合：

- `Oracle page + Oracle bbox`
- `Oracle page + Predicted bbox`
- `Predicted page + Oracle bbox`
- `Predicted page + Predicted bbox`

作用：

- 隔离 page retrieval 误差
- 隔离 bbox localization 误差
- 给出真实 end-to-end 上限与下限

### 2. Context expansion 消融

即使 bbox 是对的，crop 太小也可能损失上下文，因此建议测试：

- `bbox only`
- `bbox + 10% margin`
- `bbox + 25% margin`
- `full page`

作用：

- 找到最优证据粒度
- 回答 reviewer 对“局部 crop 会不会丢上下文”的质疑

### 3. 按证据类型分组

至少分别汇报：

- `text`
- `table`
- `image`

这是非常重要的分析，因为这三类区域对模型的难度明显不同。

### 4. 按样本复杂度分组

建议至少汇报：

- `single-page vs multi-page`
- `single-box vs multi-box`

这组分析可以说明数据集并不只是简单的单页单框查找问题。

---

## 论文中三种想法的定位

你原来的三个想法都应该保留，但定位需要调整：

### 想法 1

`whole pdf / evidence page / evidence subimage`

这是**论文主结果**，必须保留，并扩展加入 `predicted bbox`。

### 想法 2

`给 evidence page，让模型预测 bbox`

这是**核心能力验证任务**，必须保留，因为它直接证明数据集具备 grounding 监督价值。

### 想法 3

`traditional RAG with visual retrievers`

这个也建议保留，但不要只停留在 page-level。

更合理的做法是：

- page retrieval 作为第一阶段
- bbox / region retrieval 作为第二阶段
- 最终 QA 作为 end-to-end 指标

换句话说，RAG 实验应当设计成：

**page -> region -> answer**

而不是只做 `retrieve page`。

---

## 推荐的论文定位

相比于把论文定义成“一个新的 DocQA benchmark”，更稳的定位是：

**A benchmark for evidence-grounded document QA with fine-grained bbox supervision, enabling the evaluation of answering, localization, and hierarchical retrieval.**

这个定位有几个优点：

- 能同时解释 QA、定位、RAG 三类实验为什么都需要
- 能解释 bbox 标注为什么是核心贡献，而不是附属信息
- 更容易形成完整的 benchmark + task formulation + analysis 叙事

---

## 实验优先级建议

如果时间有限，建议按以下顺序推进：

1. **主实验必须完成**
   - `whole doc`
   - `GT evidence page`
   - `GT bbox`
   - `predicted bbox`

2. **定位实验必须完成**
   - 给定 evidence page 预测 bbox
   - 报告 IoU / Recall@IoU / breakdown

3. **RAG 实验尽量做成层级式**
   - 至少包含 page recall、region recall、end-to-end QA

4. **至少做两组 breakdown**
   - `text/table/image`
   - `single/multi evidence`

如果只能保留最核心的一套结果，那么建议优先保证：

- Evidence-conditioned QA
- Query-conditioned Localization
- Oracle / Predicted 消融

---

## 一句话结论

最合理的论文实验结构不是把你的三个想法并列摆放，而是将它们组织为：

- **Task 1:** Evidence-conditioned QA
- **Task 2:** Query-conditioned Localization
- **Task 3:** Hierarchical Visual RAG
- **Ablations:** Oracle / Predicted、Context Expansion、Type / Complexity Breakdown

其中：

- 想法 1 是主实验
- 想法 2 是核心能力验证
- 想法 3 应扩展为层级式 `page -> region -> answer`

这样更容易支撑一套完整、有效、可发表的论文产出。
