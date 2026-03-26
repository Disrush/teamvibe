#!/usr/bin/env python3
"""
Hook: 会话启动时注入团队决策上下文。
兼容 Cursor (sessionStart) 和 Claude Code (SessionStart)。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compat import HookIO, load_config, load_local_config, resolve_current_user


def load_decisions(project_root):
    decisions_dir = os.path.join(project_root, ".teamwork", "decisions")
    if not os.path.isdir(decisions_dir):
        return []

    records = []
    for fname in os.listdir(decisions_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(decisions_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                records.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue

    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return records


def get_active_decisions(records):
    fully_superseded_records = set()
    superseded_entries = set()

    for rec in records:
        rec_sup = rec.get("supersedes")
        if isinstance(rec_sup, str) and rec_sup:
            fully_superseded_records.add(rec_sup)

        for entry in rec.get("entries", []):
            sup = entry.get("supersedes", {})
            if isinstance(sup, dict) and sup.get("record_id"):
                superseded_entries.add((sup["record_id"], entry.get("decision_key", "")))

    active = {}
    for rec in records:
        rec_id = rec.get("id", "")
        if rec_id in fully_superseded_records:
            continue
        for entry in rec.get("entries", []):
            key = entry.get("decision_key", "")
            if not key or key in active:
                continue
            if entry.get("status") == "deprecated":
                continue
            if (rec_id, key) in superseded_entries:
                continue
            active[key] = {**entry, "_record": rec}

    return active


def format_current_user_notice(current_user, config, project_root):
    """当 local.json 的 current_user 为空时，提示设置身份。"""
    local_config = load_local_config(project_root)
    current_user_field = local_config.get("current_user", "")
    if current_user_field:
        return ""
    members = config.get("team_members", [])
    member_names = [m["name"] for m in members if m.get("name")]

    # 构建成员选项列表（供 AskUserQuestion 使用）
    member_options = ""
    if member_names:
        opts = ", ".join(f'"{n}"' for n in member_names)
        member_options = f"已注册成员可选：{opts}\n"

    return (
        "## 身份设置（需交互）\n\n"
        "**当前 `.teamwork/local.json` 中 `current_user` 未设置。**\n"
        f"{member_options}\n"
        "请立即使用 AskUserQuestion 工具向用户提问，收集身份信息：\n\n"
        "**问题设计（分两步）：**\n\n"
        "**第一步：** 使用 AskUserQuestion 同时提问：\n"
        "1. 问题「你是哪位团队成员？」header: \"身份\"\n"
        f"   - 将已注册成员作为选项（用户也可选 Other 输入新名称）\n"
        f"   - 如果没有已注册成员，提供「注册新成员」作为唯一选项\n"
        "2. 问题「你的角色是什么？」header: \"角色\"\n"
        "   - 选项：开发者、前端开发、后端开发、设计师（用户可选 Other）\n"
        "3. 问题「你的邮箱是什么？」header: \"邮箱\"\n"
        "   - 如果有已注册成员，将他们的邮箱作为选项（用户可选 Other 输入新邮箱）\n"
        "   - 如果没有已注册成员的邮箱，提供常见邮箱后缀选项如「@gmail.com」「@outlook.com」（用户选 Other 输入完整邮箱）\n\n"
        "**第二步：收到回答后**\n"
        "- 如果选择了已有成员 → 将 `current_user` 写入 `.teamwork/local.json`\n"
        "- 如果是新名称 → 追加到 `config.json` 的 `team_members`（含 name、role、email），再将 `current_user` 写入 `local.json`\n"
        "- `local.json` 已加入 .gitignore，不会被提交\n"
    )


def format_registration_notice(current_user):
    if current_user.get("source") == "unregistered":
        return (
            "## 新成员注册\n\n"
            "**你还未注册到当前项目团队配置中。**\n"
            f"检测到 git name：{current_user.get('name') or 'not set'}\n"
            f"检测到 email：{current_user.get('email') or 'not set'}\n"
            "请告诉我你希望使用的显示名和团队角色，我会帮你写入 .teamwork/config.json。\n"
        )
    if current_user.get("source") == "unknown":
        return (
            "## 新成员注册\n\n"
            "**未检测到你的 git 身份信息，也未在团队配置中找到你。**\n"
            "请告诉我你希望使用的显示名和团队角色，我会帮你写入 .teamwork/config.json。\n"
        )
    return ""


def format_context(active, config, current_user):
    lines = ["## 团队决策上下文\n"]

    lines.append(f"**当前用户：{current_user['name']}（{current_user.get('role') or '角色未配置'}）**\n")

    members = {m["name"]: m.get("role", "") for m in config.get("team_members", [])}
    if members:
        member_list = ", ".join(f"{n}({r or '未配置'})" for n, r in members.items())
    else:
        member_list = "未配置"
    lines.append(f"团队成员：{member_list}\n")

    if not active:
        return "\n".join(lines)

    lines.append(f"当前 active 决策共 {len(active)} 条：\n")

    type_labels = {"human": "👤人工", "human_ai": "👥人+AI", "ai": "🤖AI"}

    for i, (key, entry) in enumerate(active.items(), 1):
        rec = entry["_record"]
        author = rec.get("author", {})
        decision = entry.get("decision", {})
        req = entry.get("requirement", {})

        label = type_labels.get(decision.get("type", ""), "")
        lines.append(
            f"{i}. [{author.get('name', '?')}/{author.get('role', '?')}] "
            f"{rec.get('timestamp', '?')[:10]}\n"
            f"   decision_key: {key}\n"
            f"   需求：{req.get('what', '')}\n"
            f"   决策类型：{label}\n"
        )

    return "\n".join(lines)


def main():
    hook = HookIO()
    project_root = hook.get_project_root()

    current_user, config = resolve_current_user(hook, project_root)
    records = load_decisions(project_root)
    active = get_active_decisions(records[:10])
    notice = format_current_user_notice(current_user, config, project_root) or format_registration_notice(current_user)
    context = notice + format_context(active, config, current_user)

    env = {"TEAMWORK_DIR": ".teamwork", "TEAMWORK_USER": current_user["name"]}
    hook.context(text=context, env=env)


if __name__ == "__main__":
    main()
