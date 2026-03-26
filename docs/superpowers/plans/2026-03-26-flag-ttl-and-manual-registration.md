# Flag TTL and Manual Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make commit-gate flags expire automatically after 10 minutes and replace silent auto-registration with explicit AI-guided member registration.

**Architecture:** Keep the current hook-based architecture. Implement flag TTL only inside `pre-commit-decision.py`, and centralize identity behavior in `compat.py` so both `session-init.py` and `pre-commit-decision.py` use the same source semantics (`account`, `git_email`, `git_name`, `unregistered`, `unknown`). Update rules so the AI knows how to complete registration after the hooks surface the prompt.

**Tech Stack:** Python 3 hook scripts, JSON config files, Cursor rules (`.mdc`), Claude Code rules (`.md`), git-based manual verification.

---

## File structure

### Files to modify
- `.cursor/hooks/pre-commit-decision.py` — add timestamp-based flag TTL handling and block unregistered users before decision-record flow
- `.cursor/hooks/compat.py` — remove silent auto-registration, return `source: "unregistered"`, add explicit `register_user()` helper
- `.cursor/hooks/session-init.py` — prepend registration guidance for `unregistered` and `unknown` users while preserving decision context
- `.claude/rules/teamwork-decisions.md` — add new-member registration instructions
- `.cursor/rules/teamwork-decisions.mdc` — add the same new-member registration instructions for Cursor

### Files not to change
- `.cursor/hooks/pre-push-validate.py`
- `.cursor/hooks/post-pull-review.py`
- `.cursor/hooks/pre-compact-reminder.py`
- `.teamwork/decisions/*`

### Testing approach
This repo has no automated test framework today. Verification will use focused Python syntax checks plus manual hook-behavior simulations with inline `python3 -c` commands.

---

### Task 1: Add TTL support for commit-gate flag files

**Files:**
- Modify: `.cursor/hooks/pre-commit-decision.py`

- [ ] **Step 1: Add flag TTL constants and helper functions**

Add near `FLAG_DIR`:

```python
FLAG_TTL_SECONDS = 600
```

Add helpers:

```python
def write_flag(flag_path):
    with open(flag_path, "w", encoding="utf-8") as f:
        f.write(str(time.time()))


def is_flag_valid(flag_path):
    try:
        with open(flag_path, "r", encoding="utf-8") as f:
            created_at = float(f.read().strip())
    except (OSError, ValueError):
        return False
    return time.time() - created_at < FLAG_TTL_SECONDS
```
```

- [ ] **Step 2: Resolve user before any flag-based allow path**

Move:

```python
user = resolve_current_user_simple(hook, cwd)
```

so it happens before any `hook.allow()` return path.

Then enforce this rule:
- if `user["source"]` is `unregistered` or `unknown`, deny the commit first
- only registered users can use a valid retry flag to pass through

This prevents an unregistered user from bypassing registration with a fresh flag left behind by an earlier interrupted flow.

- [ ] **Step 3: Update retry-pass logic to expire stale flags**

Replace the current block:

```python
if os.path.exists(flag_path):
    try:
        os.remove(flag_path)
    except OSError:
        pass
    hook.allow()
    return
```

with logic equivalent to:

```python
if os.path.exists(flag_path):
    if is_flag_valid(flag_path):
        try:
            os.remove(flag_path)
        except OSError:
            pass
        hook.allow()
        return
    try:
        os.remove(flag_path)
    except OSError:
        pass
```
```

Expected behavior:
- fresh timestamp flag → allow once, then delete
- stale timestamp flag → delete, continue normal interception
- old-format conversation-id flag → parse fails, delete, continue normal interception

- [ ] **Step 4: Update flag creation to write timestamps**

Replace:

```python
with open(flag_path, "w") as f:
    f.write(conversation_id)
```

with:

```python
write_flag(flag_path)
```
```

- [ ] **Step 5: Add imports and keep behavior minimal**

Add:

```python
import time
```

Do not add retries, background cleanup jobs, or any new files.

- [ ] **Step 6: Verify syntax**

Run:

```bash
python3 -c "import py_compile; py_compile.compile('.cursor/hooks/pre-commit-decision.py', doraise=True); print('pre-commit-decision.py OK')"
```

Expected: `pre-commit-decision.py OK`

- [ ] **Step 7: Manually verify stale, fresh, and legacy-flag behavior**

Run three one-off simulations:

Expired flag:

```bash
python3 -c "import time,tempfile; from pathlib import Path; p=Path(tempfile.gettempdir())/'decision-test'; p.write_text(str(time.time()-601), encoding='utf-8'); created=float(p.read_text(encoding='utf-8').strip()); print('expired' if time.time()-created>=600 else 'valid'); p.unlink()"
```

Expected: `expired`

Fresh flag:

```bash
python3 -c "import time,tempfile; from pathlib import Path; p=Path(tempfile.gettempdir())/'decision-test'; p.write_text(str(time.time()-60), encoding='utf-8'); created=float(p.read_text(encoding='utf-8').strip()); print('valid' if time.time()-created<600 else 'expired'); p.unlink()"
```

Expected: `valid`

Legacy non-numeric flag:

```bash
python3 -c "import tempfile; from pathlib import Path; p=Path(tempfile.gettempdir())/'decision-test'; p.write_text('abc-session-id', encoding='utf-8');
try:
    float(p.read_text(encoding='utf-8').strip())
    print('unexpected')
except ValueError:
    print('parse-fails-as-expected')
p.unlink()"
```

Expected: `parse-fails-as-expected`

- [ ] **Step 8: Commit**

```bash
git add .cursor/hooks/pre-commit-decision.py
git commit -m "fix: expire stale decision gate flags [skip decision]"
```

---

### Task 2: Replace silent auto-registration with explicit unregistered state

**Files:**
- Modify: `.cursor/hooks/compat.py`

- [ ] **Step 1: Remove silent auto-registration branches**

In `resolve_current_user()`, remove the branches that currently:
- append a git-name-only member to `config["team_members"]`
- append an email-derived member to `config["team_members"]`
- call `save_config()` from those branches

- [ ] **Step 2: Return explicit `unregistered` identity**

Make the unresolved cases return user dicts like:

```python
{"name": git_name, "role": "", "email": git_email or user_email or "", "source": "unregistered"}
```

and keep the final no-identity fallback as:

```python
{"name": "未知用户", "role": "", "email": "", "source": "unknown"}
```
```

- [ ] **Step 3: Add explicit registration helper**

Add:

```python
def register_user(project_root, name, role, email=""):
    config = load_config(project_root)
    if "team_members" not in config:
        config["team_members"] = []
    config["team_members"].append({"name": name, "role": role, "email": email})
    save_config(project_root, config)
    return config
```
```

Keep it simple: fresh read, append, write. Do not add duplicate-detection logic in this change.

- [ ] **Step 4: Verify syntax**

Run:

```bash
python3 -c "import py_compile; py_compile.compile('.cursor/hooks/compat.py', doraise=True); print('compat.py OK')"
```

Expected: `compat.py OK`

- [ ] **Step 5: Manually verify resolve behavior**

Run a small simulation with empty `team_members` and current git config:

```bash
python3 -c "import sys; sys.path.insert(0,'.cursor/hooks'); from compat import resolve_current_user; class H: get_user_email=lambda self:''; user,_=resolve_current_user(H(), '.'); print(user['source'])"
```

Expected: `unregistered` or `unknown` (but not `auto_registered`)

- [ ] **Step 6: Commit**

```bash
git add .cursor/hooks/compat.py
git commit -m "fix: require explicit member registration [skip decision]"
```

---

### Task 3: Show registration guidance at session start

**Files:**
- Modify: `.cursor/hooks/session-init.py`

- [ ] **Step 1: Add helper to build registration prompt**

Add a small helper such as:

```python
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
```
```

- [ ] **Step 2: Prepend registration notice to normal context**

Update `main()` so it does:

```python
notice = format_registration_notice(current_user)
context = notice + format_context(active, config, current_user)
```

This must preserve the existing decision summary for registered users.

- [ ] **Step 3: Verify syntax**

Run:

```bash
python3 -c "import py_compile; py_compile.compile('.cursor/hooks/session-init.py', doraise=True); print('session-init.py OK')"
```

Expected: `session-init.py OK`

- [ ] **Step 4: Manually verify prompt rendering**

Use an executable import-by-path check so the hyphenated filename is not a problem:

```bash
python3 -c "import importlib.util; spec=importlib.util.spec_from_file_location('session_init_mod','.cursor/hooks/session-init.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print(mod.format_registration_notice({'source':'unregistered','name':'alice','email':'alice@example.com'}))"
```

Expected: output contains `新成员注册` and `.teamwork/config.json`

- [ ] **Step 5: Commit**

```bash
git add .cursor/hooks/session-init.py
git commit -m "feat: prompt new members to register at session start [skip decision]"
```

---

### Task 4: Block commits from unregistered users before decision-record flow

**Files:**
- Modify: `.cursor/hooks/pre-commit-decision.py`

- [ ] **Step 1: Add early registration guard before any flag-based allow path**

Move user resolution up so it happens before the flag allow branch:

```python
user = resolve_current_user_simple(hook, cwd)
if user.get("source") in {"unregistered", "unknown"}:
    hook.deny(...)
    return
```

Then leave the valid-flag allow path after this guard.

This ordering is required: unregistered users must never pass through on a fresh retry flag.

- [ ] **Step 2: Keep the deny message specific and non-destructive**

After:

```python
user = resolve_current_user_simple(hook, cwd)
```

insert logic like:

```python
if user.get("source") in {"unregistered", "unknown"}:
    try:
        os.remove(flag_path)
    except OSError:
        pass
    hook.deny(
        user_message="Hook: 请先完成团队成员注册...",
        agent_message=(
            "⚠️ 当前用户尚未注册到项目团队配置中，暂不能提交。\n\n"
            f"检测到的身份：name={user.get('name') or 'not set'}, email={user.get('email') or 'not set'}\n"
            "请先告诉我你的显示名和团队角色，我会帮你写入 .teamwork/config.json。\n"
            "完成注册并提交配置后，再重新执行当前 commit。"
        )
    )
    return
```
```

Important: remove the just-created flag before denying, so registration does not leave a valid retry token behind.

- [ ] **Step 3: Keep existing decision-record flow unchanged for registered users**

Do not change the large `agent_msg` block for normal users except what is strictly necessary.

- [ ] **Step 4: Verify syntax**

- [ ] **Step 5: Manually verify the unregistered deny path**

Use a focused inline Python snippet or temporary local simulation that builds a user dict with `source='unregistered'` and confirms the deny message path is reachable.

Expected: deny text contains `请先完成团队成员注册`

- [ ] **Step 6: Commit**

```bash
git add .cursor/hooks/pre-commit-decision.py
git commit -m "feat: block commits for unregistered members [skip decision]"
```

---

### Task 5: Teach both AI rule files how to complete registration

**Files:**
- Modify: `.claude/rules/teamwork-decisions.md`
- Modify: `.cursor/rules/teamwork-decisions.mdc`

- [ ] **Step 1: Add a new registration section to the Claude rule file**

Append a section like:

```md
## 五、新成员注册

当会话上下文或 hook 提示当前用户是 `unregistered` 或 `unknown` 时：
1. 询问用户希望使用的显示名和团队角色
2. 读取 `.teamwork/config.json`
3. 以 fresh read -> append -> write 的方式写入 `team_members`
4. 明确告知用户：这次配置变更提交时应使用 `[skip decision]` 标记
5. 完成注册后，再继续正常开发流程
```
```

- [ ] **Step 2: Mirror the same content in the Cursor rule file**

Keep the wording aligned so Cursor and Claude Code behave the same way.

- [ ] **Step 3: Verify both files contain the new section once**

Run:

```bash
python3 -c "from pathlib import Path; files=['.claude/rules/teamwork-decisions.md','.cursor/rules/teamwork-decisions.mdc'];
for f in files:
    text=Path(f).read_text(encoding='utf-8');
    print(f, text.count('## 五、新成员注册'))"
```

Expected:
- each file prints count `1`

- [ ] **Step 4: Commit**

```bash
git add .claude/rules/teamwork-decisions.md .cursor/rules/teamwork-decisions.mdc
git commit -m "docs: add new member registration workflow [skip decision]"
```

---

### Task 6: Final verification of the full workflow

**Files:**
- Verify only — no planned file changes

- [ ] **Step 1: Run syntax checks for all modified Python hook files**

```bash
python3 -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['.cursor/hooks/compat.py','.cursor/hooks/session-init.py','.cursor/hooks/pre-commit-decision.py']]; print('all hook files OK')"
```

Expected: `all hook files OK`

- [ ] **Step 2: Verify registered-user detection still works**

Run a small inline check against current config and current git identity.

Expected: if the current user exists in `team_members`, source is one of `account`, `git_email`, or `git_name`.

- [ ] **Step 3: Verify unregistered-user path by temporarily simulating empty members in-memory**

Use an inline snippet that exercises the new unresolved path without modifying committed config.

Expected: source resolves to `unregistered` or `unknown`, never `auto_registered`.

- [ ] **Step 4: Verify both rule files mention registration**

Check that both rules contain the new section and `[skip decision]` guidance.

Expected: both files updated consistently.

- [ ] **Step 5: Review git diff for scope control**

Run:

```bash
git diff -- .cursor/hooks/compat.py .cursor/hooks/session-init.py .cursor/hooks/pre-commit-decision.py .claude/rules/teamwork-decisions.md .cursor/rules/teamwork-decisions.mdc
```

Expected: only the planned TTL + manual registration changes appear.

- [ ] **Step 6: Commit final polish if needed**

```bash
git add .cursor/hooks/compat.py .cursor/hooks/session-init.py .cursor/hooks/pre-commit-decision.py .claude/rules/teamwork-decisions.md .cursor/rules/teamwork-decisions.mdc
git commit -m "fix: finalize flag TTL and member registration flow [skip decision]"
```

Only do this step if Task 1-5 verification required follow-up edits.
