"""
Step 5: BRAIN Knowledge Base Creator
=====================================
Wrapper script that locates the knowledge-base tools inside the cnhkmcp package
and fetches operators, datasets, and documentation from the BRAIN platform.

Credentials are read from user_config.json (written by the mandatory
Step3_set_brain_credentials.py) and are no longer asked interactively.

Output is saved to <AIWorker directory>/knowledge/
"""

import base64
import importlib.util
import json
import os
import subprocess
import sys
import traceback
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


def ask(prompt, *args, **kwargs):
    """Run a questionary prompt; exit cleanly on Ctrl+C / Esc (None)."""
    answer = prompt(*args, **kwargs).ask()
    if answer is None:
        print("\n已取消。")
        raise SystemExit(130)
    return answer

# ---------------------------------------------------------------------------
# 1. Locate the cnhkmcp package and its tool directory
# ---------------------------------------------------------------------------

def find_tool_dir() -> Path:
    """Return the path to cnhkmcp/untracked/AI桌面插件/get_knowledgeBase_tool."""
    spec = importlib.util.find_spec("cnhkmcp")
    if spec is None or spec.origin is None:
        raise RuntimeError(
            "找不到 cnhkmcp 包。请确保已安装: pip install cnhkmcp"
        )
    pkg_dir = Path(spec.origin).parent  # …/site-packages/cnhkmcp
    desktop_dir = pkg_dir / "untracked" / "AI桌面插件"
    tool_dir = desktop_dir / "get_knowledgeBase_tool"
    if not tool_dir.is_dir():
        raise RuntimeError(
            f"找不到知识库工具目录: {tool_dir}\n"
            "请确保 cnhkmcp 包版本正确且包含 untracked/AI桌面插件/ 子目录"
        )
    return tool_dir


def find_desktop_dir() -> Path:
    """Return the path to cnhkmcp/untracked/AI桌面插件."""
    spec = importlib.util.find_spec("cnhkmcp")
    if spec is None or spec.origin is None:
        raise RuntimeError("找不到 cnhkmcp 包。")
    return Path(spec.origin).parent / "untracked" / "AI桌面插件"

# ---------------------------------------------------------------------------
# 2. Credentials (read from user_config.json written by Step 3)
# ---------------------------------------------------------------------------

def load_saved_credentials() -> tuple:
    """Read email/password from user_config.json; no interactive prompts.

    Step3_set_brain_credentials.py (mandatory, before Step4) is responsible
    for collecting and validating the credentials.
    """
    config_path = Path(__file__).resolve().parent / "user_config.json"
    hint = (
        "请先运行凭证配置（必填步骤）:\n"
        "   python Step3_set_brain_credentials.py"
    )
    if not config_path.is_file():
        raise RuntimeError(f"未找到配置文件 {config_path}\n{hint}")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as exc:
        raise RuntimeError(
            f"user_config.json 解析失败: {exc}\n{hint}"
        )
    creds = cfg.get("credentials", {}) if isinstance(cfg, dict) else {}
    email = creds.get("email") or creds.get("username")
    password = creds.get("password")
    if not email or not password:
        raise RuntimeError(f"user_config.json 中缺少有效的账号/密码\n{hint}")
    # 密码不裁剪（与 Step3 保持一致）；邮箱去除首尾空白以容错旧配置
    return str(email).strip(), str(password)


# The three fetchable knowledge-base modules (also the checkbox labels).
ALL_MODULES = ["文档 (Documentation)", "操作符 (Operators)", "数据集 (Datasets)"]


def make_choice(title, value=None, selected=False):
    """Build a questionary.Choice compatible with both old and new versions.

    The ``selected`` keyword only exists in questionary >= 2.1.0, so fall back
    to the plain constructor on older installs.
    """
    try:
        return questionary.Choice(title, value=value, selected=selected)
    except TypeError:
        return questionary.Choice(title, value=value if value is not None else title)


def select_modules() -> set:
    """Multi-select knowledge modules via questionary; 全选 picks everything."""
    all_value = "__ALL__"
    selected = ask(
        questionary.checkbox,
        "请选择要获取的知识库模块（空格选中，回车确认）:",
        choices=[make_choice("✅ 全选", value=all_value)]
        + [make_choice(m, value=m, selected=True) for m in ALL_MODULES],
        validate=lambda answer: len(answer) > 0 or "请至少选择一个模块",
    )
    if all_value in selected:
        return set(ALL_MODULES)
    return set(selected)

# ---------------------------------------------------------------------------
# 3. Main workflow
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 50)
    print("  BRAIN 知识库创建工具  (Step 5)")
    print("=" * 50)

    # --- Module selection ---
    selected_modules = select_modules()

    # --- Locate tool directory ---
    try:
        tool_dir = find_tool_dir()
        desktop_dir = find_desktop_dir()
    except RuntimeError as exc:
        print(f"\n❌ {exc}")
        return 1

    print(f"工具目录: {tool_dir}")

    # --- Prepare sys.path so ace_lib / fetch modules can be imported ---
    tool_dir_str = str(tool_dir)
    desktop_dir_str = str(desktop_dir)
    for p in (tool_dir_str, desktop_dir_str):
        if p not in sys.path:
            sys.path.insert(0, p)

    # --- Import modules after path setup ---
    try:
        import ace_lib
        from fetch_all_operators import fetch_operators
        from fetch_all_datasets import (
            fetch_all_combinations,
            fetch_datasets_for_combo,
            merge_and_deduplicate,
        )
        from fetch_all_documentation import (
            fetch_tutorials,
            fetch_tutorial_pages,
            fetch_page,
            _extract_page_id,
        )
    except ImportError as exc:
        print(f"\n❌ 导入模块失败: {exc}")
        traceback.print_exc()
        return 1

    # --- Credentials (from user_config.json, written by Step 3) ---
    try:
        email, password = load_saved_credentials()
    except RuntimeError as exc:
        print(f"\n❌ {exc}")
        return 1
    print(f"已读取账号: {email}")

    # --- Monkey-patch ace_lib BEFORE any authentication ---
    # This ensures that if any internal code (e.g. check_session_and_relogin)
    # calls start_session() -> get_credentials(), it gets the real credentials.
    ace_lib.get_credentials = lambda: (email, password)

    # Reset SingleSession singleton so it starts fresh with correct credentials
    ace_lib.SingleSession._instance = None
    ace_lib.SingleSession._initialized = False

    # --- Login (direct BasicAuth, bypassing ace_lib.start_session) ---
    print("\n正在登录 BRAIN 平台...")
    try:
        brain_api_url = os.environ.get(
            "BRAIN_API_URL", "https://api.worldquantbrain.com"
        )
        # Create a direct session using BasicAuth header (reliable method
        # from fetch_all_documentation.py), then transfer cookies to
        # the ace_lib SingleSession so all internal functions work.
        token = base64.b64encode(f"{email}:{password}".encode()).decode()
        auth_headers = {"Authorization": f"Basic {token}"}

        tmp_session = requests.Session()
        resp = tmp_session.post(
            f"{brain_api_url}/authentication",
            headers=auth_headers,
            timeout=30,
        )

        if resp.status_code == 401:
            detail = resp.text[:200] if resp.text else "(无响应体)"
            print(f"❌ 登录失败: 邮箱或密码错误 (HTTP 401)\n   {detail}")
            return 1
        if resp.status_code != 201:
            detail = resp.text[:200] if resp.text else "(无响应体)"
            print(
                f"❌ 登录失败: 意外状态码 {resp.status_code}\n   {detail}"
            )
            return 1

        # Build the ace_lib SingleSession and transplant cookies/auth
        session = ace_lib.SingleSession()
        session.cookies.update(tmp_session.cookies)
        session.headers.update(tmp_session.headers)
        # Keep BasicAuth on the session so re-login also works
        session.auth = (email, password)

        # Verify the session is actually valid
        verify_resp = session.get(
            f"{brain_api_url}/authentication", timeout=15
        )
        if verify_resp.status_code != 200:
            print(
                f"⚠️  登录后验证失败 (HTTP {verify_resp.status_code})，"
                "尝试通过 ace_lib.start_session() 重新认证..."
            )
            # Fallback: use ace_lib's own start_session (monkey-patch
            # is already in place, singleton is reset)
            ace_lib.SingleSession._instance = None
            ace_lib.SingleSession._initialized = False
            session = ace_lib.start_session()

        print("✅ 登录成功")
    except Exception as exc:
        print(f"❌ 登录失败: {exc}")
        traceback.print_exc()
        return 1

    # --- Prepare output directory ---
    script_dir = Path(__file__).resolve().parent
    knowledge_dir = script_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    knowledge_dir_str = str(knowledge_dir)
    print(f"输出目录: {knowledge_dir_str}\n")

    # --- Import helper from process_knowledge_base ---
    # We inline the helpers (to_jsonable, safe_filename) to avoid
    # SCRIPT_DIR conflicts in the original module.
    import pandas as pd
    import re

    def to_jsonable(value):
        """Convert values to JSON-serializable, handling NaN and nested structures."""
        try:
            if isinstance(value, float) and pd.isna(value):
                return None
        except TypeError:
            pass
        if isinstance(value, list):
            return [to_jsonable(v) for v in value if not (isinstance(v, float) and pd.isna(v))]
        if isinstance(value, dict):
            return {k: to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def safe_filename(name: str, suffix: str = "") -> str:
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_") or "doc"
        base = base[:80]
        return f"{base}{suffix}"

    success_count = 0
    fail_count = 0

    # ---- 1. Documentation ----
    if "文档 (Documentation)" in selected_modules:
        print("=== [1/3] 获取文档 ===")
        try:
            tutorials = fetch_tutorials(session)
            if not tutorials:
                print("⚠️  未获取到教程文档")
            else:
                print(f"获取到 {len(tutorials)} 个教程")
                page_count = 0
                seen_pages: set = set()

                for idx, tutorial in enumerate(tutorials, start=1):
                    tutorial_id = _extract_page_id(tutorial) or f"tutorial_{idx}"
                    tutorial_title = tutorial.get("title") or tutorial_id

                    page_candidates = []
                    if isinstance(tutorial.get("pages"), list):
                        page_candidates.extend(tutorial["pages"])
                    if tutorial_id:
                        try:
                            page_candidates.extend(fetch_tutorial_pages(session, tutorial_id))
                        except Exception:
                            pass

                    if not page_candidates and tutorial_id:
                        page_candidates.append({"id": tutorial_id, "title": tutorial_title})

                    for page_entry in page_candidates:
                        page_id = _extract_page_id(page_entry)
                        if not page_id or page_id in seen_pages:
                            continue
                        seen_pages.add(page_id)

                        try:
                            page = fetch_page(session, page_id)
                        except Exception:
                            continue

                        page_count += 1
                        page_title = page.get("title") or page_entry.get("title") or page_id
                        filename = safe_filename(f"{idx:03d}_{page_title}", "_documentation.json")
                        filepath = knowledge_dir / filename

                        with open(filepath, "w", encoding="utf-8") as f:
                            json.dump(to_jsonable(page), f, ensure_ascii=False, indent=2)

                print(f"✅ 文档处理完成，共 {page_count} 个页面")
                success_count += 1
        except Exception as exc:
            print(f"❌ 文档获取失败: {exc}")
            traceback.print_exc()
            fail_count += 1
    else:
        print("=== [1/3] 获取文档 === 已跳过")

    # ---- 2. Operators ----
    if "操作符 (Operators)" in selected_modules:
        print("\n=== [2/3] 获取操作符 ===")
        try:
            operators_df = fetch_operators(session)
            if operators_df.empty:
                print("⚠️  未获取到操作符")
            else:
                print(f"获取到 {len(operators_df)} 个操作符")
                categories = sorted(operators_df["category"].dropna().unique())

                for category in categories:
                    category_data = operators_df[operators_df["category"] == category].copy()
                    filename = f"{category.replace(' ', '_').lower()}_operators.json"
                    filepath = knowledge_dir / filename

                    category_list = []
                    for _, row in category_data.iterrows():
                        operator_dict = {col: to_jsonable(row[col]) for col in row.index}
                        category_list.append(operator_dict)

                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(category_list, f, ensure_ascii=False, indent=2)

                    print(f"  ✓ {filename} ({len(category_list)} 个操作符)")
                print("✅ 操作符处理完成")
                success_count += 1
        except Exception as exc:
            print(f"❌ 操作符获取失败: {exc}")
            traceback.print_exc()
            fail_count += 1
    else:
        print("\n=== [2/3] 获取操作符 === 已跳过")

    # ---- 3. Datasets ----
    if "数据集 (Datasets)" in selected_modules:
        print("\n=== [3/3] 获取数据集 ===")
        try:
            options_df = fetch_all_combinations(session)
            if options_df is None or options_df.empty:
                print("⚠️  未获取到数据集组合")
            else:
                all_datasets = []
                combo_idx = 0

                for _, row in options_df.iterrows():
                    instrument_type = row.get("InstrumentType")
                    region = row.get("Region")
                    delay = row.get("Delay")
                    universes = row.get("Universe") or []

                    for universe in universes:
                        combo_idx += 1
                        print(f"  [{combo_idx}] {instrument_type} / {region} / D{delay} / {universe}")
                        try:
                            df = fetch_datasets_for_combo(session, instrument_type, region, delay, universe)
                            print(f"       -> {len(df)} 条记录")
                            all_datasets.append(df)
                        except Exception as exc:
                            print(f"       -> 失败: {exc}")

                if all_datasets:
                    combined_df = pd.concat([df for df in all_datasets if not df.empty], ignore_index=True)
                    if not combined_df.empty:
                        regions = sorted(combined_df["param_region"].dropna().unique())
                        for region in regions:
                            region_df = combined_df[combined_df["param_region"] == region]
                            region_unique = merge_and_deduplicate([region_df])

                            region_list = []
                            for _, row in region_unique.iterrows():
                                record = {col: to_jsonable(row[col]) for col in row.index}
                                region_list.append(record)

                            filename = f"{region.replace(' ', '_').lower()}_datasets.json"
                            filepath = knowledge_dir / filename
                            with open(filepath, "w", encoding="utf-8") as f:
                                json.dump(region_list, f, ensure_ascii=False, indent=2)

                            print(f"  ✓ {filename} ({len(region_list)} 个数据集)")
                print("✅ 数据集处理完成")
                success_count += 1
        except Exception as exc:
            print(f"❌ 数据集获取失败: {exc}")
            traceback.print_exc()
            fail_count += 1
    else:
        print("\n=== [3/3] 获取数据集 === 已跳过")

    # ---- Summary ----
    total_modules = len(selected_modules)
    print("\n" + "=" * 50)
    if fail_count == 0:
        print(f"🎉 知识库创建完成！成功处理 {success_count}/{total_modules} 个模块")
        print(f"   输出目录: {knowledge_dir_str}")
        return 0
    else:
        print(f"⚠️  知识库部分创建完成: {success_count} 成功, {fail_count} 失败")
        print(f"   输出目录: {knowledge_dir_str}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
