# SetAPI_And_Check_MoonShot.py
import os
import sys
import subprocess
import time

import platform
from pathlib import Path

# Ensure openai is installed
try:
    from openai import OpenAI
except ImportError:
    print("正在安装 openai 依赖包...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "openai"])
    except subprocess.CalledProcessError:
         print("⚠️ 常规安装失败 (可能由于 PEP 668). 尝试使用 --break-system-packages...")
         subprocess.check_call([sys.executable, "-m", "pip", "install", "openai", "--break-system-packages"])
    from openai import OpenAI

def set_env_var(name, value):
    """Sets environment variable cross-platform (Windows/User, Mac+Linux/Shell Config)"""
    if not value: return
    
    system = platform.system()
    
    if system == "Windows":
        # Windows Logic (PowerShell User Scope)
        value_escaped = value.replace('"', '`"')
        ps_command = f'[Environment]::SetEnvironmentVariable("{name}", "{value_escaped}", "User")'
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command]
        try:
            subprocess.check_call(cmd)
            print(f"✅ [Windows] 环境变量已设置: {name}")
        except subprocess.CalledProcessError as e:
            print(f"❌ 设置失败 {name}: {e}")
            
    else:
        # Unix Logic (Mac/Linux - Append to Shell Config)
        home = Path.home()
        shell = os.environ.get("SHELL", "/bin/bash")
        
        # Determine config file based on shell
        rc_files = []
        if "zsh" in shell:
            rc_files = [home / ".zshrc", home / ".zprofile"]
        elif "bash" in shell:
            rc_files = [home / ".bashrc", home / ".bash_profile"]
        else:
            rc_files = [home / ".profile"]

        entry_line = f'export {name}="{value}"'
        
        success = False
        for rc in rc_files:
            # Create if not exists (touch)
            if not rc.exists():
                try: rc.touch()
                except: continue

            try:
                content = rc.read_text(encoding='utf-8')
                # Simple check to avoid duplicate flooding (not perfect but helpful)
                if f'export {name}=' in content and value in content:
                     print(f"ℹ️  [Unix] {name} 已存在于 {rc.name}")
                     success = True
                     break
                
                with open(rc, "a", encoding='utf-8') as f:
                    f.write(f"\n{entry_line}")
                print(f"✅ [Unix] 已添加 {name} 到 {rc.name}")
                success = True
                break # Only write to the first valid config file found
            except Exception as e:
                print(f"⚠️  即写 {rc.name} 失败: {e}")
        
        if not success:
             print(f"❌ 无法自动设置环境变量 {name}。请手动执行: {entry_line}")

def get_provider_config():
    print("\n请选择您要使用的 API 提供商:")
    print("1. Kimi (Moonshot) - [platform.moonshot.cn]")
    print("2. DeepSeek (深度求索) - [platform.deepseek.com]")
    print("3. 手动输入 Base URL（适用于 Claude、GPT、豆包、千问等任何 OpenAI 兼容平台）")
    
    while True:
        choice = input("\n请输入序号 (1 / 2 / 3): ").strip()
        if choice == "1":
            return {
                "name": "Moonshot (Kimi)",
                "site": "platform.moonshot.cn",
                "list_base_url": "https://api.moonshot.cn/v1",
                "anthropic_base_url": "https://api.moonshot.cn/anthropic",
                "extra_envs": {}
            }
        elif choice == "2":
            return {
                "name": "DeepSeek",
                "site": "platform.deepseek.com",
                "list_base_url": "https://api.deepseek.com",
                "anthropic_base_url": "https://api.deepseek.com/anthropic",
                "extra_envs": {
                    "API_TIMEOUT_MS": "900000",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "ANTHROPIC_SMALL_FAST_MODEL": "{model}" # Placeholder
                }
            }
        elif choice == "3":
            print("\n请输入您的 API Base URL（OpenAI 兼容格式）")
            print("示例: https://api.anthropic.com/v1  或  https://ark.cn-beijing.volces.com/api/v3")
            base_url = input("Base URL: ").strip()
            if not base_url:
                print("Base URL 不能为空，请重新选择。")
                continue
            # 确保 base_url 不以 / 结尾
            base_url = base_url.rstrip("/")
            # anthropic_base_url 默认与 list_base_url 相同，去掉 /v1 后缀（如有）作为 anthropic 端点
            if base_url.endswith("/v1"):
                anthropic_url = base_url[:-3]
            else:
                anthropic_url = base_url
            return {
                "name": "自定义平台",
                "site": base_url,
                "list_base_url": base_url,
                "anthropic_base_url": anthropic_url,
                "extra_envs": {}
            }
        else:
            print("输入无效，请重新输入。")

def perform_network_diagnostics():
    """Proactively checks for common Windows environment issues (Errno 2/Proxy)."""
    print("正在进行环境预检...")
    try:
        import httpx
        # Attempt to init standard client. This often triggers the Errno 2 on broken Windows envs
        with httpx.Client() as client:
            pass
        return {"use_secure_client": False}
    except Exception as e:
        # Check for specific "No such file" error (Errno 2)
        err_msg = str(e)
        if "[Errno 2]" in err_msg or "No such file" in err_msg:
             print(f"⚠️  预检发现环境路径异常: {e}")
             print("➡️  已自动启用：【隔离网络模式】(将绕过系统代理和证书配置)")
             return {"use_secure_client": True}
        print(f"ℹ️  预检检测到网络异常，但不影响后续连接: {e}")
        return {"use_secure_client": False}

def main():
    print("=== Claude Code API 多模型配置工具 ===")
    
    # 0. Proactive Diagnostics
    diag_result = perform_network_diagnostics()
    
    # 1. Select Provider
    config = get_provider_config()
    
    # 2. Get API Key
    print(f"\n您选择了 {config['name']}。")
    print(f"请前往官网 {config['site']} 申请 API Key。")
    api_key = input(f"请输入您的 API Key (sk-...): ").strip()
    if not api_key:
        print("API Key 不能为空。")
        return

    # 3. Initialize Client to fetch models
    print(f"\n正在连接 {config['name']} API 以获取可用模型列表...")
    
    model_data = None
    selected_model = None  # Track the selected model across both paths
    
    def try_connect_api(force_secure=False):
        import httpx
        
        if force_secure:
             print("   正在应用隔离模式 (trust_env=False)...")
             secure_client = httpx.Client(verify=False, trust_env=False)
             client = OpenAI(
                 api_key=api_key, 
                 base_url=config['list_base_url'],
                 http_client=secure_client
             )
        else:
             client = OpenAI(api_key=api_key, base_url=config['list_base_url'])
             
        return client.models.list().data

    try:
        model_data = try_connect_api(force_secure=False)
    except Exception as e:
        err_msg = str(e)
        if "[Errno 2]" in err_msg or "No such file" in err_msg:
             print(f"\n⚠️  连接尝试失败 (环境路径异常): {e}")
             print("➡️  尝试启用隔离模式...")
             try:
                 model_data = try_connect_api(force_secure=True)
                 print("✅ 隔离模式连接成功！")
             except Exception as e2:
                 print(f"❌ 隔离模式也失败了: {e2}")
                 model_data = None
        else:
            print(f"\n❌ API 连接失败: {e}")
            print(f"   🔍 调试信息: Base URL = {config['list_base_url']}")
            print(f"   🔍 实际请求: {config['list_base_url']}/models")
            print(f"   部分平台（如豆包）不支持 /models 端点，您可以选择手动输入模型名。")
            model_data = None

    # If model list unavailable, offer manual input
    if not model_data:
        print("\n⚠️  无法自动获取模型列表。")
        manual = input("是否手动输入模型名？(y/n): ").strip()
        if manual.lower() == 'y':
            selected_model = input("请输入模型名 (如 claude-sonnet-4-20250514): ").strip()
            if not selected_model:
                print("模型名不能为空。")
                return
            print(f"已选择模型: {selected_model}")
        else:
            print("已取消配置。")
            return
    else:
        # 4. List and Select Model
        print(f"\n可用模型列表:")
        sorted_models = sorted(model_data, key=lambda m: m.id)
        for i, model in enumerate(sorted_models):
            print(f"[{i}] {model.id}")
            
        selection = input("\n请输入序号选择默认模型 (例如 0): ").strip()
        try:
            index = int(selection)
            if 0 <= index < len(sorted_models):
                selected_model = sorted_models[index].id
                print(f"已选择模型: {selected_model}")
            else:
                print("无效的序号。")
                return
        except ValueError:
            print("输入无效，请输入数字。")
            return

    # 5. Configure Environment Variables
    print("\n正在配置全局环境变量...")
    
    # Core Anthropic Vars
    set_env_var("ANTHROPIC_BASE_URL", config['anthropic_base_url'])
    set_env_var("ANTHROPIC_AUTH_TOKEN", api_key)
    
    # Model Vars (Standard)
    # Applying selected model to all Standard Roles
    set_env_var("ANTHROPIC_MODEL", selected_model)
    set_env_var("ANTHROPIC_DEFAULT_OPUS_MODEL", selected_model)
    set_env_var("ANTHROPIC_DEFAULT_SONNET_MODEL", selected_model)
    set_env_var("ANTHROPIC_DEFAULT_HAIKU_MODEL", selected_model)
    set_env_var("CLAUDE_CODE_SUBAGENT_MODEL", selected_model)

    # Extra Vars (Provider specific)
    for key, val_template in config['extra_envs'].items():
        val = val_template.format(model=selected_model) # Format if placeholder exists
        set_env_var(key, val)

    print("\n✨ 配置完成！")
    print("************************************************")
    print(f" 提供商: {config['name']}")
    print(f" 模型  : {selected_model}")
    print(f" 接口  : {config['anthropic_base_url']}")
    print("************************************************")
    print("⚠️ 请注意：请务必 关闭并重新打开 您的终端窗口，以应用新的环境变量。")

if __name__ == "__main__":
    main()
