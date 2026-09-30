"""
Step 5: BRAIN Knowledge Base Creator
=====================================
Wrapper script that locates the knowledge-base tools inside the cnhkmcp package
and fetches operators, datasets, and documentation from the BRAIN platform.

Credentials are always collected interactively via plain input().

Output is saved to <AIWorker directory>/knowledge/
"""

import base64
import importlib.util
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

import requests

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
# 2. Credentials
# ---------------------------------------------------------------------------

def get_credentials() -> tuple:
    """Always collect credentials interactively (no env-var dependency)."""
    email = input("请输入 BRAIN 平台邮箱: ").strip()
    while not email:
        email = input("邮箱不能为空，请重新输入: ").strip()

    password = input("请输入 BRAIN 平台密码: ").strip()
    while not password:
        password = input("密码不能为空，请重新输入: ").strip()

    return email, password

# ---------------------------------------------------------------------------
# 3. Main workflow
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 50)
    print("  BRAIN 知识库创建工具  (Step 5)")
    print("=" * 50)

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

    # --- Credentials ---
    email, password = get_credentials()

    # --- Copy & update user_config.json ---
    script_dir = Path(__file__).resolve().parent
    try:
        spec = importlib.util.find_spec("cnhkmcp")
        if spec is not None and spec.origin is not None:
            pkg_dir = Path(spec.origin).parent
            src_config = pkg_dir / "untracked" / "user_config.json"
            dst_config = script_dir / "user_config.json"

            if src_config.is_file():
                if not dst_config.is_file():
                    # 首次：复制整个文件
                    shutil.copy2(str(src_config), str(dst_config))
                    print(f"✅ 已复制 user_config.json 到 {dst_config}")

                # 读取现有配置，仅更新 credentials
                with open(dst_config, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)

                if "credentials" not in user_cfg:
                    user_cfg["credentials"] = {}
                user_cfg["credentials"]["email"] = email
                user_cfg["credentials"]["password"] = password

                with open(dst_config, "w", encoding="utf-8") as f:
                    json.dump(user_cfg, f, indent=2, ensure_ascii=False)
                print("✅ 已更新 user_config.json 中的 credentials")
            else:
                print(f"⚠️  未找到源文件 {src_config}，跳过 user_config.json 复制")
        else:
            print("⚠️  未找到 cnhkmcp 包，跳过 user_config.json 复制")
    except Exception as exc:
        print(f"⚠️  user_config.json 处理失败: {exc}（不影响后续流程）")

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

    # ---- 2. Operators ----
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

    # ---- 3. Datasets ----
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

    # ---- Summary ----
    print("\n" + "=" * 50)
    if fail_count == 0:
        print(f"🎉 知识库创建完成！成功处理 {success_count}/3 个模块")
        print(f"   输出目录: {knowledge_dir_str}")
        return 0
    else:
        print(f"⚠️  知识库部分创建完成: {success_count} 成功, {fail_count} 失败")
        print(f"   输出目录: {knowledge_dir_str}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
