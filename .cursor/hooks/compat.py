"""
Cursor / Claude Code 双平台 Hook 兼容层。

平台检测：通过输入 JSON 中的 cursor_version 字段或 CURSOR_VERSION 环境变量判断。
提供统一的输入读取、命令提取、输出格式化接口。
"""

import json
import os
import subprocess
import sys


class HookIO:
    def __init__(self):
        self.payload = json.load(sys.stdin)
        self.platform = self._detect_platform()

    def _detect_platform(self):
        if self.payload.get("cursor_version") or os.environ.get("CURSOR_VERSION"):
            return "cursor"
        return "claude_code"

    @property
    def is_cursor(self):
        return self.platform == "cursor"

    @property
    def is_claude_code(self):
        return self.platform == "claude_code"

    def get_command(self):
        if self.is_cursor:
            if "command" in self.payload:
                return self.payload["command"]
        tool_input = self.payload.get("tool_input", {})
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except json.JSONDecodeError:
                return tool_input
        if isinstance(tool_input, dict):
            return tool_input.get("command", self.payload.get("command", ""))
        return ""

    def get_cwd(self):
        return (
            self.payload.get("cwd")
            or os.environ.get("CURSOR_PROJECT_DIR")
            or os.environ.get("CLAUDE_PROJECT_DIR")
            or "."
        )

    def get_project_root(self):
        roots = self.payload.get("workspace_roots", [])
        if roots:
            return roots[0]
        return (
            os.environ.get("CURSOR_PROJECT_DIR")
            or os.environ.get("CLAUDE_PROJECT_DIR")
            or self.payload.get("cwd", ".")
        )

    def get_conversation_id(self):
        return (
            self.payload.get("conversation_id")
            or self.payload.get("session_id")
            or "unknown"
        )

    def get_user_email(self):
        return (
            self.payload.get("user_email")
            or os.environ.get("CURSOR_USER_EMAIL")
            or ""
        )

    def allow(self):
        if self.is_cursor:
            json.dump({"permission": "allow"}, sys.stdout)

    def deny(self, user_message="", agent_message=""):
        if self.is_cursor:
            result = {"permission": "deny"}
            if user_message:
                result["user_message"] = user_message
            if agent_message:
                result["agent_message"] = agent_message
            json.dump(result, sys.stdout, ensure_ascii=False)
        else:
            reason = agent_message or user_message
            if reason:
                print(reason, file=sys.stderr)
            sys.exit(2)

    def context(self, text="", env=None):
        """SessionStart: inject context and env vars."""
        if self.is_cursor:
            result = {}
            if env:
                result["env"] = env
            if text:
                result["additional_context"] = text
            json.dump(result, sys.stdout, ensure_ascii=False)
        else:
            if text:
                print(text)

    def additional_context(self, text=""):
        """PostToolUse: inject additional context."""
        if self.is_cursor:
            if text:
                json.dump({"additional_context": text}, sys.stdout, ensure_ascii=False)
            else:
                json.dump({}, sys.stdout)
        else:
            if text:
                print(text)

    def user_message(self, text=""):
        """PreCompact: show message to user."""
        if self.is_cursor:
            json.dump({"user_message": text}, sys.stdout, ensure_ascii=False)
        else:
            if text:
                print(text)

    def empty(self):
        if self.is_cursor:
            json.dump({}, sys.stdout)


def load_config(project_root):
    config_path = os.path.join(project_root, ".teamwork", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"version": "1.0", "team_members": [], "major_change_keywords": []}


def save_config(project_root, config):
    config_path = os.path.join(project_root, ".teamwork", "config.json")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


def register_user(project_root, name, role, email=""):
    config = load_config(project_root)
    if "team_members" not in config:
        config["team_members"] = []
    config["team_members"].append({"name": name, "role": role, "email": email})
    save_config(project_root, config)
    return config


def resolve_current_user(hook, project_root):
    """Resolve current user identity and auto-register to config.json if new."""
    config = load_config(project_root)
    members = config.get("team_members", [])
    email_map = {m.get("email", "").lower(): m for m in members if m.get("email")}
    name_map = {m["name"]: m for m in members if m.get("name")}

    # 1. Try Cursor/Claude account email
    user_email = hook.get_user_email()
    if user_email and user_email.lower() in email_map:
        m = email_map[user_email.lower()]
        return {"name": m["name"], "role": m.get("role", ""), "email": user_email, "source": "account"}, config

    # 2. Try git email
    git_email = ""
    try:
        git_email = subprocess.run(
            ["git", "config", "user.email"],
            cwd=project_root, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        pass

    if git_email and git_email.lower() in email_map:
        m = email_map[git_email.lower()]
        return {"name": m["name"], "role": m.get("role", ""), "email": git_email, "source": "git_email"}, config

    # 3. Try git name
    git_name = ""
    try:
        git_name = subprocess.run(
            ["git", "config", "user.name"],
            cwd=project_root, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        pass

    if git_name and git_name in name_map:
        m = name_map[git_name]
        user = {"name": m["name"], "role": m.get("role", ""), "email": git_email or user_email or "", "source": "git_name"}
        # Update email if member record is missing it
        if (git_email or user_email) and not m.get("email"):
            m["email"] = git_email or user_email
            save_config(project_root, config)
        return user, config

    # 4. Not found in team_members — return unregistered
    if git_name or user_email:
        return {"name": git_name or user_email.split("@")[0], "role": "", "email": git_email or user_email or "", "source": "unregistered"}, config

    return {"name": "未知用户", "role": "", "email": "", "source": "unknown"}, config
