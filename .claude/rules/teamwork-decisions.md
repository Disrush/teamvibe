# 团队协作决策管理

你正在一个多人协作的 vibe coding 项目中工作。

## 一、冲突检测（每次用户描述需求时）

每当用户描述一个新的需求、修改请求或功能变更时：

1. 读取 `.teamwork/decisions/` 目录下的所有 JSON 文件
2. 对每个 `decision_key`，找到最新的 active 版本，按以下规则排除被替代的 entry：
   - **Entry 级 supersedes**：某 entry 的 `supersedes.record_id` 指向旧记录 ID，则旧记录中**同一 `decision_key`** 的 entry 被替代（旧记录中其他 key 不受影响）
   - **Record 级 supersedes**（历史兼容）：`record.supersedes` 为字符串时，被引用的旧记录**整体**视为已替代
   - 只有未被替代且 `status != "deprecated"` 的 entry 才算 active
3. 将用户请求与 active 决策做业务语义比对
4. 确定当前用户身份：优先读取 `.teamwork/config.json` 的 `current_user` 字段（按 name 匹配 `team_members`），若为空则回退到 git config 推断

### `human` 类型冲突 → 必须线下沟通

当用户请求与其他成员的人工明确决策冲突时：
- 立即告知：说明哪位成员在何时做了什么决策
- 引用动机：展示 `decision.motivation`
- 要求沟通：明确要求用户先与该成员线下确认
- 等待确认：用户必须回复"已沟通，可以继续"后才执行
- 不可跳过：即使你判断当前方案更优，也不能绕过

### `human_ai` 类型冲突 → 提醒，当前用户判断为准

- 告知用户存在冲突，简要展示原决策
- 说明这是人和 AI 共同做出的决策
- 当前用户可直接决定是否覆盖

### `ai` 类型冲突 → 简要提及，直接执行

- 一句话提及存在旧的 AI 决策
- 直接按当前用户要求执行

### 无冲突

正常执行，不做任何额外提示。
不要在没有冲突时主动告知"我检查了决策清单没有发现冲突"。

## 二、实时决策草稿维护

在整个对话过程中，维护决策草稿 `.teamwork/drafts/current.json`。
草稿的作用是在 commit 之前暂存决策，防止上下文丢失或遗忘。

### 何时更新

以下场景发生后，**立即**写入或追加到草稿文件（不要等 commit 时再补）：

1. 用户做出明确的业务决策（如"我们用方案A"、"就这样做"、"改成X"）
2. 用户与你讨论后达成共识（方案确定下来的那一刻）
3. 你自主做出了设计决策（用户未明确指定，你选择了方案），实现完成后立即记录
4. 收到上下文折叠（compact）通知时，确认草稿是否完整，缺失则补写

### 何时不更新

- 纯代码 bug 修复、类型错误修正
- AI 理解偏差后的纠正
- 纯重构、格式化

### 草稿格式

```json
{
  "status": "draft",
  "session_id": "对话或会话标识",
  "entries": [
    {
      "decision_key": "feature-name-kebab-case",
      "status": "active",
      "requirement": { "what": "...", "why": "..." },
      "solution": { "approach": "...", "not_included": "..." },
      "decision": { "type": "human|human_ai|ai", "motivation": "...", "decided_by": "..." }
    }
  ]
}
```

### 更新方式

- 首次写入：创建 `.teamwork/drafts/current.json`，写入完整 JSON
- 追加式更新：读取已有文件，向 `entries` 数组追加新 entry，写回文件
- commit hook 生成正式记录后，草稿文件由 hook 流程删除

## 三、supersedes 规范

### 格式要求

supersedes **必须写在 entry 级别**，格式如下：

```json
{
  "decision_key": "same-key-as-old",
  "supersedes": {
    "record_id": "被替代的记录 ID",
    "reason": "为什么替代"
  }
}
```

### 核心原则

- **不修改旧文件**：旧记录中被替代的 entry 保持原样不动，"被替代"的状态由新记录的 supersedes 链推导得出
- **同 key 替代**：新 entry 的 `decision_key` 必须与被替代的旧 entry 的 key 一致
- **只替代具体 entry**：supersedes 指向的 record_id 中，只有相同 `decision_key` 的 entry 被替代，该记录中其他 key 的 entry 不受影响

### 判断 active 的逻辑

1. 收集所有 entry 的 supersedes 引用，构建 `(record_id, decision_key)` 的被替代集合
2. 遍历所有记录（按时间降序），对每个 entry：
   - 如果 `(当前记录ID, 该entry的key)` 在被替代集合中 → 跳过
   - 如果 `status == "deprecated"` → 跳过
   - 如果该 key 尚未出现 → 标记为 active
3. 最终得到每个 `decision_key` 的唯一 active 版本

## 四、文件位置

- 决策记录：`.teamwork/decisions/*.json`
- 决策草稿：`.teamwork/drafts/current.json`（已加入 .gitignore，不提交）
- 团队配置：`.teamwork/config.json`

## 五、新成员注册

当会话上下文或 hook 提示当前用户是 `unregistered` 或 `unknown` 时：
1. 询问用户希望使用的显示名和团队角色
2. 读取 `.teamwork/config.json`
3. 以 fresh read -> append -> write 的方式写入 `team_members`
4. 明确告知用户：这次配置变更提交时应使用 `[skip decision]` 标记
5. 完成注册后，再继续正常开发流程
