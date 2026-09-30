"""
Step 3: BRAIN Credentials Setup (Mandatory)
============================================
Collects the WorldQuant BRAIN platform email/password interactively,
validates them against the platform, and saves them into
<AIWorker directory>/user_config.json.

This step is mandatory and runs before Step4: later tools
(Step5 knowledge base, Osmosis allocator, MCP server) read credentials
from user_config.json and will no longer ask for them.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import requests

try:
    import questionary
except ImportError:
    print("正在安装 questionary 依赖包...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "questionary"])
    except subprocess.CalledProcessError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "questionary", "--break-system-packages"]
        )
    import questionary


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "user_config.json"
MAX_LOGIN_ATTEMPTS = 3


def ask(prompt, *args, **kwargs):
    """Run a questionary prompt; exit cleanly on Ctrl+C / Esc (None)."""
    answer = prompt(*args, **kwargs).ask()
    if answer is None:
        print("\n已取消。")
        raise SystemExit(130)
    return answer


def ask_yes_no(message, default=True):
    """Ask a Yes/No question as an up/down select (not plain confirm text)."""
    yes_opt = "是 (Yes)"
    no_opt = "否 (No)"
    answer = ask(
        questionary.select,
        message,
        choices=[yes_opt, no_opt] if default else [no_opt, yes_opt],
    )
    return answer == yes_opt


def collect_credentials() -> tuple:
    """Collect email/password interactively."""
    email = ask(
        questionary.text,
        "请输入 BRAIN 平台邮箱: ",
        validate=lambda text: bool(text.strip()) or "邮箱不能为空",
    ).strip()

    # 密码不做 strip：首尾空格可能是密码的一部分，裁剪会导致下游登录失败；
    # 仅通过 validate 保证非空。
    password = ask(
        questionary.password,
        "请输入 BRAIN 平台密码: ",
        validate=lambda text: bool(text.strip()) or "密码不能为空",
    )

    return email, password


def verify_credentials(email: str, password: str):
    """POST /authentication with BasicAuth.

    Returns (True, "") on success, or (False, reason) on failure.
    """
    import base64

    brain_api_url = os.environ.get("BRAIN_API_URL", "https://api.worldquantbrain.com")
    token = base64.b64encode(f"{email}:{password}".encode()).decode()
    try:
        resp = requests.post(
            f"{brain_api_url}/authentication",
            headers={"Authorization": f"Basic {token}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        return False, f"网络错误: {exc}"

    if resp.status_code in (200, 201):
        return True, ""
    if resp.status_code == 401:
        www_auth = resp.headers.get("WWW-Authenticate", "")
        if www_auth == "persona":
            return False, (
                "平台要求进行生物识别/设备验证 (persona)，"
                "请先在浏览器登录 BRAIN 完成验证后重试"
            )
        return False, "邮箱或密码错误 (HTTP 401)"
    return False, f"意外状态码 HTTP {resp.status_code}"


def save_credentials(email: str, password: str) -> None:
    """Write credentials into user_config.json, preserving other fields.

    If the file does not exist yet, copy the template shipped inside the
    cnhkmcp package (if available) so the rest of the config is complete.
    """
    if not CONFIG_PATH.is_file():
        spec = importlib.util.find_spec("cnhkmcp")
        if spec is not None and spec.origin is not None:
            src_config = Path(spec.origin).parent / "untracked" / "user_config.json"
            if src_config.is_file():
                shutil.copy2(str(src_config), str(CONFIG_PATH))
                print(f"✅ 已从 cnhkmcp 复制配置模板到 {CONFIG_PATH}")

    user_cfg = {}
    if CONFIG_PATH.is_file():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                user_cfg = loaded
        except Exception:
            user_cfg = {}

    if not isinstance(user_cfg.get("credentials"), dict):
        user_cfg["credentials"] = {}
    user_cfg["credentials"]["email"] = email
    user_cfg["credentials"]["password"] = password

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(user_cfg, f, indent=2, ensure_ascii=False)
    # 收紧权限：含明文密码的配置文件仅限当前用户读写（POSIX 系统）
    if os.name != "nt":
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except OSError:
            pass
    print(f"✅ 账号密码已保存到 {CONFIG_PATH}")


def main() -> int:
    print("=" * 50)
    print("  BRAIN 平台账号配置  (Step 3 · 必填)")
    print("=" * 50)
    print("后续的 Step5 知识库、Osmosis 分配器、MCP 工具都将使用此处保存的账号。")

    # 已有有效凭证时，允许直接复用或重新输入
    if CONFIG_PATH.is_file():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            creds = cfg.get("credentials", {}) if isinstance(cfg, dict) else {}
            if creds.get("email") and creds.get("password"):
                masked = creds["email"]
                if not ask_yes_no(
                    f"检测到已保存的账号 ({masked})，是否重新输入？", default=False
                ):
                    print("✅ 沿用已保存的账号密码。")
                    return 0
        except Exception:
            pass

    for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
        email, password = collect_credentials()
        print("\n正在验证账号密码...")
        try:
            ok, reason = verify_credentials(email, password)
        except Exception as exc:
            ok, reason = False, f"网络错误: {exc}"

        if ok:
            print("✅ 登录验证成功")
            save_credentials(email, password)
            return 0

        print(f"❌ 验证失败: {reason}")
        if reason.startswith("网络错误"):
            if ask_yes_no("网络异常，是否仍然保存账号密码（稍后再验证）？", default=False):
                save_credentials(email, password)
                return 0
        if attempt < MAX_LOGIN_ATTEMPTS:
            if not ask_yes_no(f"是否重新输入？(剩余 {MAX_LOGIN_ATTEMPTS - attempt} 次)", default=True):
                break
        else:
            print(f"已达最大尝试次数 ({MAX_LOGIN_ATTEMPTS})。")
            if ask_yes_no("是否仍然保存当前账号密码（不保证正确）？", default=False):
                save_credentials(email, password)
                return 0

    print("❌ 账号配置未完成，请重新运行: python Step3_set_brain_credentials.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
