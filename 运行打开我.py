"""
BRAIN Expression Template Decoder - Flask Web Application
A complete web application for decoding string templates with WorldQuant BRAIN integration
"""

# Auto-install dependencies if missing
import subprocess
import sys
import os
import io
import math
import random
import re
import shutil
from collections import Counter
from pathlib import Path

# Change working directory to script directory to ensure relative paths work correctly
# This fixes issues when running from VS Code context menu where CWD might be the workspace root
try:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
except Exception:
    pass

# try set gbk problem
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    elif hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass


# ---------------------------------------------------------------------------
# Interpreter self-heal: this script usually lives inside a virtualenv
# (e.g. <project>/.venv/lib/python3.12/site-packages/cnhkmcp/untracked/APP).
# If it is launched with a DIFFERENT interpreter (e.g. uv's bare Python),
# packages installed in the venv are invisible and imports fail with
# confusing "No module named 'flask'" errors even after `uv add flask`.
# Detect the enclosing venv via pyvenv.cfg and re-exec with its interpreter.
# ---------------------------------------------------------------------------
def _reexec_with_enclosing_venv():
    if os.environ.get('BRAIN_VENV_REEXEC_DONE'):
        return
    try:
        here = Path(os.path.abspath(__file__)).resolve().parent
        venv_root = None
        for parent in here.parents:
            if (parent / 'pyvenv.cfg').is_file():
                venv_root = parent
                break
        if venv_root is None:
            return
        # Already running inside this venv? (compare sys.prefix, NOT the
        # executable path: uv venvs symlink .venv/bin/python to the bare
        # interpreter, so realpath comparison would always match.)
        try:
            if os.path.realpath(sys.prefix) == os.path.realpath(str(venv_root)):
                return
        except Exception:
            pass
        if os.name == 'nt':
            candidates = [venv_root / 'Scripts' / 'python.exe']
        else:
            candidates = [venv_root / 'bin' / 'python3', venv_root / 'bin' / 'python']
        for py in candidates:
            if not py.is_file():
                continue
            env = dict(os.environ)
            env['BRAIN_VENV_REEXEC_DONE'] = '1'
            env.pop('PYTHONHOME', None)
            print(f"🔁 Detected virtualenv at {venv_root}; re-launching with its interpreter: {py}")
            os.execve(str(py), [str(py), os.path.abspath(__file__)] + sys.argv[1:], env)
            return
    except Exception as e:
        print(f"⚠️  venv self-heal skipped: {e}")


_reexec_with_enclosing_venv()




def _build_windows_cmd_launch(script_name):
    command = f'"{sys.executable}" "{script_name}"'
    return f'cmd /k "{command}"'

def _shell_quote(value):
    """Quote a value for POSIX shells (shlex.quote) with a safe fallback."""
    import shlex
    text = str(value)
    try:
        return shlex.quote(text)
    except Exception:
        return "'" + text.replace("'", "'\\''") + "'"


def _merge_env(*extra_envs):
    """Current process environment merged with optional extra variables."""
    merged = dict(os.environ)
    for extra in extra_envs:
        if extra:
            merged.update(extra)
    return merged


def _linux_terminal_argv(terminal, full_cmd, cwd, python_exe, script_abs, extra_args):
    """Build the argv needed to launch a command in a Linux terminal emulator."""
    argv = [python_exe, script_abs] + list(extra_args or [])
    if terminal == 'gnome-terminal':
        return [terminal, '--working-directory', cwd, '--'] + argv
    if terminal == 'konsole':
        return [terminal, '--hold', '-e', 'bash', '-lc', full_cmd]
    if terminal == 'xfce4-terminal':
        return [terminal, '--hold', '-e', 'bash', '-lc', full_cmd]
    if terminal == 'kgx':
        return [terminal, '--', 'bash', '-lc', full_cmd]
    if terminal == 'kitty':
        return [terminal, 'bash', '-lc', full_cmd]
    if terminal == 'alacritty':
        return [terminal, '-e', 'bash', '-lc', full_cmd]
    if terminal == 'tilix':
        return [terminal, '-e', 'bash', '-lc', full_cmd]
    # mate-terminal / lxterminal / xterm / x-terminal-emulator / generic fallback
    return [terminal, '-e', 'bash', '-lc', full_cmd]


def _open_in_new_terminal(script_name, cwd, env=None, extra_args=None):
    """Launch a Python script in a NEW VISIBLE TERMINAL, cross-platform.

    - Windows : cmd /k (keeps the window open after the script exits)
    - macOS   : writes an executable .command file and opens it with
                Terminal.app via the "open" command (avoids osascript automation
                permission prompts; env vars are exported inside the file
                because Terminal does not inherit our process environment)
    - Linux   : tries a list of common terminal emulators; if none is found,
                falls back to running the script headless in the background.

    Uses sys.executable so the child always runs with the SAME interpreter
    that is serving this web app (previously "python3" was hard-coded, which
    broke venv installs and missing system python3 on macOS).
    """
    extra_args = list(extra_args or [])
    python_exe = sys.executable
    merged_env = _merge_env(env)
    script_abs = os.path.join(cwd, script_name)

    if os.name == 'nt':
        try:
            subprocess.Popen(
                _build_windows_cmd_launch(os.path.basename(script_abs)),
                cwd=cwd,
                env=merged_env,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except OSError:
            subprocess.Popen(
                [python_exe, script_abs] + extra_args,
                cwd=cwd,
                env=merged_env,
                start_new_session=True,
            )
        return True

    if sys.platform == 'darwin':
        try:
            import tempfile
            fd, command_file = tempfile.mkstemp(prefix='brain_run_', suffix='.command')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write('#!/bin/bash\n')
                if env:
                    for key, value in env.items():
                        if value is None:
                            continue
                        f.write('export {}={}\n'.format(_shell_quote(key), _shell_quote(value)))
                f.write('cd {}\n'.format(_shell_quote(cwd)))
                parts = [_shell_quote(python_exe), _shell_quote(script_abs)]
                parts += [_shell_quote(a) for a in extra_args]
                f.write(' '.join(parts) + '\n')
                f.write('exec bash\n')
            os.chmod(command_file, 0o755)
            subprocess.Popen(['open', '-a', 'Terminal', command_file])
            return True
        except Exception as e:
            print(f"⚠️  macOS Terminal launch failed ({e}); running headless")
            subprocess.Popen(
                [python_exe, script_abs] + extra_args,
                cwd=cwd,
                env=merged_env,
                start_new_session=True,
            )
            return False

    # Linux / other POSIX
    has_display = "DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ
    if has_display:
        terminals = [
            'gnome-terminal', 'x-terminal-emulator', 'konsole',
            'xfce4-terminal', 'mate-terminal', 'lxterminal',
            'tilix', 'kgx', 'kitty', 'alacritty', 'xterm',
        ]
        full_cmd = 'cd {} && {} {}'.format(
            _shell_quote(cwd),
            _shell_quote(python_exe),
            _shell_quote(script_abs),
        )
        if extra_args:
            full_cmd += ' ' + ' '.join(_shell_quote(a) for a in extra_args)
        for terminal in terminals:
            try:
                subprocess.Popen(
                    _linux_terminal_argv(terminal, full_cmd, cwd, python_exe, script_abs, extra_args),
                    env=merged_env,
                )
                return True
            except FileNotFoundError:
                continue
        print("⚠️  Warning: no supported terminal emulator found; running in background")
    subprocess.Popen(
        [python_exe, script_abs] + extra_args,
        cwd=cwd,
        env=merged_env,
        start_new_session=True,
    )
    return False

print("🚀 Initializing BRAIN Expression Template Decoder...")

# ---------------------------------------------------------------------------
# QuantFlow Agent CLI bootstrap (Claude Code / Codex)
# 启动时检查 Agent 执行所需的 CLI。claude 与 codex 都缺失时，自动用国内镜像
# 安装 Claude Code（Claude Code 即可驱动 QuantFlow 的 Agent 功能；Codex 可
# 由用户在运行时设置里另行选用）。已经安装任一 CLI 的用户不受任何影响：
# 不做安装、不做强制更新，仅打印一行状态。所有子进程调用均跨平台兼容。
# ---------------------------------------------------------------------------

QUANTFLOW_CLAUDE_PACKAGE = '@anthropic-ai/claude-code'
# npm 镜像候选：环境变量 NPM_REGISTRY 优先（可指定任意镜像，置空则全用默认列表），
# 之后按 国内镜像 -> 官方源 的顺序自动探测，安装时选用延迟最低的可用镜像，
# 单个镜像失败会自动切换到下一个，避免某些路由下安装卡死或超时。
QUANTFLOW_NPM_REGISTRIES = [
    os.environ.get('NPM_REGISTRY', '').strip(),
    'https://registry.npmmirror.com',
    'https://mirrors.huaweicloud.com/repository/npm/',
    'https://mirrors.cloud.tencent.com/npm/',
    'https://registry.npmjs.org',
]
QUANTFLOW_NPM_REGISTRIES = [u for u in dict.fromkeys(QUANTFLOW_NPM_REGISTRIES) if u]


def _npm_network_flags():
    """npm flags that tolerate slow/unstable routes (timeouts + retries)."""
    return [
        '--fetch-timeout=60000',      # 单次请求 60s 超时
        '--fetch-retries=3',          # 失败自动重试 3 次
        '--fetch-retry-mintimeout=10000',
        '--fetch-retry-maxtimeout=120000',
        '--prefer-online',            # 慢路由下优先走网络而非过期缓存
        '--no-audit',                 # 跳过安全审计，减少额外网络请求
        '--no-fund',
        '--loglevel=error',
    ]


def _pick_fastest_npm_registry(candidates):
    """Probe registries (bounded per-candidate timeout) and return the fastest reachable one.

    A candidate counts as reachable if the HTTP connection succeeds (any response code);
    only timeouts/connection errors disqualify it.  Returns None when nothing is reachable."""
    import urllib.request
    results = []
    for url in candidates:
        probe = url.rstrip('/') + '/'
        try:
            start = time.time()
            req = urllib.request.Request(probe, method='HEAD', headers={'User-Agent': 'quantflow-bootstrap/1.0'})
            with urllib.request.urlopen(req, timeout=6) as resp:
                latency = (time.time() - start) * 1000
                results.append((url, latency));
        except Exception:
            continue
    results.sort(key=lambda item: item[1])
    if results:
        best, ms = results[0]
        detail = ', '.join(f"{u.split('//')[-1].split('/')[0]} {int(lat)}ms" for u, lat in results[:4])
        print(f"  🌐 镜像探测: {detail} -> 选用 {best}")
        return best
    return None



def _which_any(*names):
    """Return the first executable found among names (cross-platform)."""
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _claude_code_candidates():
    """Common locations where a user-level Claude Code install may live."""
    home = Path.home()
    prefixes = [
        home / '.local',
        home / '.npm-global',
        home / '.claude-code-cli',
        home / '.claude',
    ]
    if os.name == 'nt':
        appdata = os.environ.get('APPDATA', '')
        if appdata:
            prefixes.append(Path(appdata) / 'npm')
    candidates = []
    for prefix in prefixes:
        candidates.extend([
            prefix / 'bin' / 'claude',
            prefix / 'claude.cmd',
            prefix / 'claude',
        ])
    return [str(p) for p in candidates]


def _find_claude_code():
    """Locate the claude executable; returns (path_or_None, source_label).

    Falls back to scanning user-level install prefixes and, if found there,
    prepends that directory to PATH for the current process so QuantFlow can
    resolve it without the user having to edit their shell profile."""
    found = _which_any('claude', 'claude.cmd')
    if found:
        return found, 'PATH'
    for candidate in _claude_code_candidates():
        if os.path.isfile(candidate):
            bindir = os.path.dirname(candidate)
            os.environ['PATH'] = bindir + os.pathsep + os.environ.get('PATH', '')
            return candidate, 'user-prefix'
    return None, None


def _run_cli(cmd, timeout=900, extra_env=None):
    """Run a subprocess quietly; return True on exit code 0 (cross-platform)."""
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    try:
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            env=env,
            creationflags=creationflags,
        )
    except Exception as e:
        print(f"  ⚠️  命令执行失败: {e}")
        return False
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or '').strip()[-600:]
        print(f"  ⚠️  命令退出码 {proc.returncode}: {tail}")
        return False
    return True


def _install_claude_code_via_npm():
    """Install Claude Code via npm with automatic mirror selection.

    Strategy for slow/unstable routes:
    1. probe candidate registries (NPM_REGISTRY override, then China mirrors, then
       official) and install through the fastest reachable one;
    2. npm runs with fetch timeouts/retries so a slow mirror fails fast instead of
       hanging;
    3. if the chosen mirror fails, rotate to the next candidate (system-global then
       user-level prefix per candidate)."""
    npm = _which_any('npm', 'npm.cmd')
    if not npm:
        return False, 'npm 未安装'
    candidates = list(QUANTFLOW_NPM_REGISTRIES)
    if not candidates:
        candidates = ['https://registry.npmjs.org']
    # 慢路由：先探测所有候选镜像，选延迟最低的可用镜像
    registry = _pick_fastest_npm_registry(candidates)
    order = [registry] if registry else []
    order += [u for u in candidates if u not in order]
    network_flags = _npm_network_flags()
    prefix = str(Path.home() / '.claude-code-cli')

    for attempt, reg in enumerate(order, start=1):
        label = f"（镜像 {attempt}/{len(order)}: {reg}）"
        print(f"  📦 通过 npm 安装 Claude Code {label}...")
        # 1) 系统全局安装
        cmd = [npm, 'install', '-g', QUANTFLOW_CLAUDE_PACKAGE, '--registry', reg] + network_flags
        if _run_cli(cmd, timeout=900):
            return True, ''
        # 2) 权限失败等场景：改用用户级 prefix（不需要管理员）
        print("  🔄 系统全局失败，改用用户级安装（无需管理员权限）...")
        try:
            os.makedirs(prefix, exist_ok=True)
        except Exception:
            pass
        cmd = [npm, 'install', '-g', '--prefix', prefix, QUANTFLOW_CLAUDE_PACKAGE, '--registry', reg] + network_flags
        if _run_cli(cmd, timeout=900):
            claude, _ = _find_claude_code()
            if claude:
                return True, ''
        # 该镜像不可用 -> 继续尝试下一个镜像
        if attempt < len(order):
            print("  🔄 当前镜像不可用，切换到下一个镜像重试...")
    return False, '所有 npm 镜像安装均失败'



def _install_claude_code_native():
    """Official standalone installer as a fallback when npm is unavailable.

    The official install scripts ship a platform binary and do NOT require
    Node.js.  claude.ai may be slow/unreachable in some regions; this is only
    a fallback behind the npm path."""
    if os.name == 'nt':
        print("  📦 通过官方 PowerShell 脚本安装 Claude Code ...")
        return _run_cli(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-Command', 'irm https://claude.ai/install.ps1 | iex'],
            timeout=900,
        )
    print("  📦 通过官方独立安装脚本安装 Claude Code ...")
    return _run_cli(['bash', '-lc', 'curl -fsSL https://claude.ai/install.sh | bash'], timeout=900)


def _try_install_node_npm():
    """Best-effort install of Node.js/npm when missing (no sudo prompts).

    Only attempts lightweight, non-interactive installers; any failure just
    prints guidance and returns None."""
    if os.name == 'nt':
        print("  ⚙️  未检测到 npm，尝试通过 winget 安装 Node.js LTS ...")
        if _run_cli(['winget', 'install', '--id', 'OpenJS.NodeJS.LTS',
                     '--accept-source-agreements', '--accept-package-agreements'],
                    timeout=600):
            return _which_any('npm', 'npm.cmd')
    elif sys.platform == 'darwin':
        if _which_any('brew') and _run_cli(['brew', 'install', 'node'], timeout=900):
            return _which_any('npm', 'npm.cmd')
    else:
        # Linux: only attempt when passwordless sudo is available (no prompt).
        if _which_any('sudo') and _run_cli(['sudo', '-n', 'true'], timeout=30):
            pm = _which_any('apt-get', 'dnf', 'yum')
            if pm:
                print(f"  ⚙️  未检测到 npm，尝试通过 {os.path.basename(pm)} 安装 Node.js ...")
                pkg = 'nodejs npm' if os.path.basename(pm) == 'apt-get' else 'nodejs'
                if _run_cli(['sudo', '-n', pm, 'install', '-y', pkg], timeout=600):
                    return _which_any('npm', 'npm.cmd')
    return None


def ensure_quantflow_agent_cli():
    """Bootstrap Claude Code / Codex CLI for QuantFlow agent execution.

    Runs early at startup (after Python dependency check):
    - claude OR codex already usable -> skip entirely (no install / no update).
    - both missing -> auto-install Claude Code: npm + China mirror first,
      official standalone installer as fallback, Node.js bootstrap when npm
      itself is missing.  A failure only prints guidance and never blocks
      the application from starting.
    """
    print("🔎 检查 QuantFlow Agent 执行环境（Claude Code / Codex CLI）...")
    claude, claude_src = _find_claude_code()
    codex = _which_any('codex', 'codex.cmd')
    if claude:
        print(f"✅ Claude Code 已就绪（{claude_src}）")
        return
    if codex:
        print("✅ Codex CLI 已就绪，跳过自动安装（QuantFlow 可选用 Codex）")
        return
    print("ℹ️  未检测到 Claude Code 与 Codex CLI，自动安装 Claude Code（QuantFlow Agent 功能需要）...")

    # 逃生舱：QUANTFLOW_CLI_AUTO_INSTALL=0 只提示不自动安装（默认自动安装）
    if os.environ.get('QUANTFLOW_CLI_AUTO_INSTALL', '1') != '1':
        print("   自动安装已禁用（QUANTFLOW_CLI_AUTO_INSTALL=0）。请手动安装 Claude Code 后重新启动。")
        return

    npm = _which_any('npm', 'npm.cmd')
    if not npm:
        print("  ⚠️  未检测到 npm（Node.js）。先尝试安装 Node.js...")
        npm = _try_install_node_npm()

    ok = False
    reason = ''
    if npm:
        ok, reason = _install_claude_code_via_npm()
    if not ok:
        print(f"  ⚠️  npm 方式未成功（{reason or '未知'}），尝试官方独立安装脚本...")
        ok = _install_claude_code_native()

    claude, claude_src = _find_claude_code()
    if claude:
        print(f"✅ Claude Code 安装完成：{claude}")
        print("   QuantFlow Agent 功能已就绪。Claude Code 运行时仍需在 QuantFlow 设置中"
              "配置 API Key / 网关（国内可填 https://api.moonshot.cn/anthropic 等）。")
    else:
        print("❌ Claude Code 自动安装未成功。请手动安装后重新启动：")
        if os.name == 'nt':
            print("   winget install OpenJS.NodeJS.LTS")
            print("   npm install -g @anthropic-ai/claude-code --registry=https://registry.npmmirror.com")
        else:
            print("   npm install -g @anthropic-ai/claude-code --registry=https://registry.npmmirror.com")
        print("   或参考官方文档: https://docs.anthropic.com/en/docs/claude-code/setup")
        print("   （不影响主应用启动；QuantFlow 的 Agent 功能使用前需要该 CLI）")



# ---------------------------------------------------------------------------
# 桌面快捷方式（Brain工作站）：首次在有桌面的平台运行时间用户，创建后不重复询问
# ---------------------------------------------------------------------------

BRAIN_SHORTCUT_NAME = 'Brain工作站'


def _shortcut_marker_file():
    """状态标记：无论用户是否选择创建都记录一次，避免每次启动重复询问。"""
    return Path.home() / '.quantflow' / 'brain_workstation_shortcut.json'


def _shortcut_path(desktop):
    if os.name == 'nt':
        return desktop / (BRAIN_SHORTCUT_NAME + '.lnk')
    if sys.platform == 'darwin':
        return desktop / (BRAIN_SHORTCUT_NAME + '.command')
    return desktop / (BRAIN_SHORTCUT_NAME + '.desktop')


def _desktop_directory():
    """Locate the desktop directory, or None when there is no usable desktop."""
    if os.name == 'nt':
        profile = os.environ.get('USERPROFILE') or str(Path.home())
        for cand in (Path(profile) / 'Desktop', Path(profile) / 'OneDrive' / 'Desktop'):
            if cand.is_dir():
                return cand
        return Path(profile) / 'Desktop'
    if sys.platform == 'darwin':
        desktop = Path.home() / 'Desktop'
        return desktop if desktop.is_dir() else None
    # Linux: headless servers have no desktop to put a shortcut on.
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return None
    desktop = Path.home() / 'Desktop'
    if desktop.is_dir():
        return desktop
    try:
        out = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=5)
        p = Path(out.stdout.strip())
        if p.is_dir():
            return p
    except Exception:
        pass
    return None





def _logo_assets():
    """App-local paths where the BRAIN workstation logo lives."""
    app_dir = os.path.dirname(os.path.abspath(__file__))
    return (
        os.path.join(app_dir, 'static', 'brain_workstation_logo.png'),
        os.path.join(app_dir, 'static', 'brain_workstation_logo.ico'),
    )


def _png_to_ico_powershell(png, ico):
    """Fallback PNG -> ICO conversion via Windows PowerShell System.Drawing."""
    ps = (
        "Add-Type -AssemblyName System.Drawing;\n"
        "$src = [System.Drawing.Image]::FromFile($env:QF_ICON_SRC);\n"
        "$bmp = New-Object System.Drawing.Bitmap($src.Width, $src.Height);\n"
        "$g = [System.Drawing.Graphics]::FromImage($bmp);\n"
        "$g.Clear([System.Drawing.Color]::Transparent);\n"
        "$g.DrawImage($src, 0, 0, $src.Width, $src.Height);\n"
        "$hIcon = $bmp.GetHicon();\n"
        "$icon = [System.Drawing.Icon]::FromHandle($hIcon);\n"
        "$fs = [System.IO.File]::Create($env:QF_ICON_DST);\n"
        "$icon.Save($fs);\n"
        "$fs.Close();\n"
        "$icon.Dispose(); $g.Dispose(); $bmp.Dispose(); $src.Dispose();\n"
    )
    env = dict(os.environ)
    env['QF_ICON_SRC'] = str(png)
    env['QF_ICON_DST'] = str(ico)
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=60, env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except Exception as e:
        print(f"  ⚠️ 图标转换失败: {e}")


def _prepare_shortcut_icon():
    """Make the BRAIN logo available as a shortcut icon (best effort).

    - Copies the logo png into the app static/ dir (first run / when the
      source is newer) so shortcuts on every machine point at a stable asset.
    - On Windows also produces an .ico next to it for .lnk IconLocation.
    Returns (png_path_or_None, ico_path_or_None).
    """
    png_asset, ico_asset = _logo_assets()
    # Candidate sources, most preferred first.
    sources = []
    env_logo = os.environ.get('BRAIN_WORKSTATION_LOGO', '').strip()
    if env_logo:
        sources.append(env_logo)
    sources.append(r'C:\Users\liwei\Pictures\ScreenShot_2025-12-31_031533_322.png')
    if os.path.isfile(png_asset):
        sources.append(png_asset)
    src = next((s for s in sources if s and os.path.isfile(s)), None)
    try:
        if src and (not os.path.exists(png_asset) or os.path.getmtime(src) > os.path.getmtime(png_asset)):
            shutil.copy2(src, png_asset)
    except Exception as e:
        print(f"  ⚠️ 图标资源复制失败: {e}")
    if not os.path.isfile(png_asset):
        return None, None
    if os.name == 'nt':
        made_ico = os.path.isfile(ico_asset) and os.path.getmtime(ico_asset) >= os.path.getmtime(png_asset)
        if not made_ico:
            try:
                from PIL import Image
                img = Image.open(png_asset).convert('RGBA')
                img.save(ico_asset, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
            except ImportError:
                _png_to_ico_powershell(png_asset, ico_asset)
            except Exception as e:
                print(f"  ⚠️ 图标生成失败(尝试 PowerShell): {e}")
                _png_to_ico_powershell(png_asset, ico_asset)
    return (
        png_asset if os.path.isfile(png_asset) else None,
        ico_asset if os.path.isfile(ico_asset) else None,
    )


def _create_desktop_shortcut(desktop):
    """Create the platform shortcut; returns (ok, detail). Cross-platform."""
    python_exe = sys.executable
    script_abs = os.path.abspath(__file__)
    app_dir = os.path.dirname(script_abs)
    png_asset, ico_asset = _prepare_shortcut_icon()
    try:
        if os.name == 'nt':
            # Windows .lnk via PowerShell (paths passed through env to avoid quoting issues)
            lnk = desktop / (BRAIN_SHORTCUT_NAME + '.lnk')
            ps_lines = [
                "$ws = New-Object -ComObject WScript.Shell;\n",
                "$s = $ws.CreateShortcut($env:QF_SHORTCUT);\n",
                "$s.TargetPath = $env:QF_TARGET;\n",
                "$s.Arguments = '\"' + $env:QF_ARGS + '\"';\n",
                "$s.WorkingDirectory = $env:QF_WORKDIR;\n",
            ]
            if ico_asset:
                ps_lines.append("$s.IconLocation = $env:QF_ICON;\n")
            ps_lines.append("$s.Description = 'Brain工作站 - BRAIN Expression Template Decoder';\n")
            ps_lines.append("$s.Save();\n")
            ps_script = ''.join(ps_lines)
            env = dict(os.environ)
            env['QF_SHORTCUT'] = str(lnk)
            env['QF_TARGET'] = python_exe
            env['QF_ARGS'] = script_abs
            env['QF_WORKDIR'] = app_dir
            if ico_asset:
                env['QF_ICON'] = '{},0'.format(ico_asset)
            proc = subprocess.run(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=60, env=env,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout or '').strip()[-400:])
            return lnk.exists(), str(lnk)
        if sys.platform == 'darwin':
            # macOS: executable .command file that opens in Terminal.app on double-click
            cmd_file = desktop / (BRAIN_SHORTCUT_NAME + '.command')
            content = "#!/bin/bash\ncd {}\nexec {} {}\n".format(
                _shell_quote(app_dir), _shell_quote(python_exe), _shell_quote(script_abs))
            cmd_file.write_text(content, encoding='utf-8')
            os.chmod(cmd_file, 0o755)
            return cmd_file.exists(), str(cmd_file)
        # Linux: freedesktop .desktop entry (terminal=true)
        desktop_file = desktop / (BRAIN_SHORTCUT_NAME + '.desktop')
        content = (
            "[Desktop Entry]\nType=Application\nName={}\nComment=BRAIN Expression Template Decoder\n"
            "Exec=\"{}\" \"{}\"\nPath={}\nTerminal=true\n"
        ).format(BRAIN_SHORTCUT_NAME, python_exe, script_abs, app_dir)
        if png_asset:
            content += "Icon={}\n".format(png_asset)
        desktop_file.write_text(content, encoding='utf-8')
        os.chmod(desktop_file, 0o755)
        # GNOME requires a trusted flag before it allows double-click launching.
        try:
            subprocess.run(['gio', 'set', str(desktop_file), 'metadata::trusted', 'true'],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        return desktop_file.exists(), str(desktop_file)
    except Exception as e:
        return False, str(e)


def _ensure_desktop_shortcut():
    """Ask (once) whether to create the Brain工作站 desktop shortcut.

    - No usable desktop -> skip silently (no marker, so a later graphical session can ask).
    - Shortcut already exists -> skip.
    - Already asked before (marker file) -> skip.
    - Otherwise prompt on the console; non-interactive sessions default to creating.
    """
    try:
        desktop = _desktop_directory()
        if desktop is None:
            print("ℹ️  未检测到可用桌面环境，跳过桌面快捷方式创建。")
            return
        marker = _shortcut_marker_file()
        shortcut = _shortcut_path(desktop)
        if shortcut.exists():
            print(f"✅ 桌面快捷方式已存在：{shortcut}")
            return
        if marker.exists():
            return  # 已询问过（无论之前是否创建）
        print()
        print(f"🖥️  检测到桌面环境。是否在桌面创建快捷方式「{BRAIN_SHORTCUT_NAME}」？双击即可打开本应用，不用再去文件夹里找。")
        interactive = True
        try:
            interactive = sys.stdin.isatty()
        except Exception:
            interactive = False
        if interactive:
            try:
                answer = input("   请输入 y/是 创建，n/否 跳过（直接回车默认创建）: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = ""
        else:
            answer = ""  # 非交互环境默认创建（用户已明确要这个功能）
        if answer in ("", "y", "yes", "yeah", "是", "创建"):
            ok, detail = _create_desktop_shortcut(desktop)
            _write_json_file(marker, {"created": bool(ok), "path": detail, "prompted": True})
            if ok:
                print(f"✅ 已创建桌面快捷方式：{detail}")
                print("   以后双击桌面的「Brain工作站」即可启动本应用。")
            else:
                print(f"⚠️  桌面快捷方式创建失败：{detail}")
        else:
            _write_json_file(marker, {"created": False, "path": "", "prompted": True})
            print("ℹ️  已跳过创建（以后不再询问）。")
    except Exception as e:
        print(f"⚠️  桌面快捷方式检查跳过：{e}")

# Run the agent-CLI bootstrap before importing the heavy web stack so that
# QuantFlow's Agent features are ready by the time the app serves pages.
ensure_quantflow_agent_cli()

# Now import the packages
try:
    from flask import Flask, render_template, request, jsonify, session as flask_session, Response, stream_with_context, send_from_directory, send_file, after_this_request
    from werkzeug.utils import secure_filename
    from flask_cors import CORS
    import requests
    import json
    import time
    import re
    import os
    import shutil
    import zipfile
    import tempfile
    import threading
    import queue
    import uuid
    from datetime import datetime
    from blueprints.validator import ExpressionValidator
    print("📚 Core packages imported successfully!")

    # Import ace_lib for simulation options
    try:
        # Try importing from hkSimulator package
        sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hkSimulator'))
        from ace_lib import get_instrument_type_region_delay
        print("✅ Imported get_instrument_type_region_delay from ace_lib")
    except ImportError as e:
        print(f"⚠️ Warning: Could not import get_instrument_type_region_delay: {e}")
        get_instrument_type_region_delay = None

except ImportError as e:
    print(f"❌ Failed to import core packages: {e}")
    print(f"   Current interpreter: {sys.executable}")
    print("   Please install dependencies into THIS interpreter's environment, e.g.:")
    print("     uv add -r requirements.txt   (or: pip install -r requirements.txt)")
    if __name__ == "__main__":
        sys.exit(1)
    raise

app = Flask(__name__)
app.secret_key = 'brain_template_decoder_secret_key_change_in_production'
CORS(app)

print("🌐 Flask application initialized with CORS support!")



# ---------------------------------------------------------------------------
# 查更新：检查 PyPI 上 cnhkmcp 包是否有新版本，并提供一键升级
# ---------------------------------------------------------------------------

UPDATER_PACKAGE_NAME = 'cnhkmcp'
# PyPI JSON API 候选（官方 + 国内镜像兜底，慢路由自动切换）
UPDATER_PYPI_JSON_URLS = [
    'https://pypi.org/pypi/cnhkmcp/json',
    'https://pypi.tuna.tsinghua.edu.cn/pypi/cnhkmcp/json',
    'https://mirrors.aliyun.com/pypi/pypi/cnhkmcp/json',
]


def _running_source_version():
    """Return ``(version, package_root)`` for the code containing this launcher.

    A desktop shortcut may point at an extracted/source tree whose parent is
    renamed by an installer. Therefore package-root discovery must inspect
    ``__init__.py`` content rather than require a directory named cnhkmcp.
    """
    import re as _re
    here = Path(__file__).resolve()
    for parent in here.parents:
        init_file = parent / '__init__.py'
        if not init_file.is_file():
            continue
        try:
            text = init_file.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        match = _re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
        if match:
            return match.group(1), str(parent)
        pkg_info = parent / 'PKG-INFO'
        if pkg_info.is_file():
            try:
                info_text = pkg_info.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            match = _re.search(r'^Version:\s*(.+)$', info_text, _re.M)
            if match:
                return match.group(1).strip(), str(parent)
    return None, None


def _installed_package_version(package_name=UPDATER_PACKAGE_NAME):
    """Return the version of the cnhkmcp code actually running.

    Prefer the source tree containing this launcher. ``importlib.metadata``
    only describes a site-packages distribution and may be absent or stale
    when the desktop shortcut starts an extracted source tree.
    """
    import importlib.metadata as _metadata
    source_version, _source_root = _running_source_version()
    if source_version:
        return source_version
    try:
        return _metadata.version(package_name)
    except Exception:
        return None


def _fetch_pypi_latest_version():
    """Return (latest_version, source_url) published on PyPI, or (None, None)."""
    import urllib.request
    for url in UPDATER_PYPI_JSON_URLS:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'brain-workstation-updater/1.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            version = (data.get('info') or {}).get('version')
            if version:
                return version, url
        except Exception:
            continue
    return None, None


def _version_greater(a, b):
    """Return True when version string a is newer than b (packaging preferred)."""
    try:
        from packaging.version import Version
        return Version(a) > Version(b)
    except Exception:
        def _parts(v):
            out = []
            for seg in re.split(r'[.+-]', str(v)):
                out.append(int(seg) if seg.isdigit() else seg)
            return out
        return _parts(a) > _parts(b)


@app.route('/api/check-update', methods=['POST'])
def api_check_update():
    """Check the installed cnhkmcp version against the latest one on PyPI."""
    installed = _installed_package_version()
    source_version, source_root = _running_source_version()
    latest, source = _fetch_pypi_latest_version()
    if not latest:
        return jsonify({'ok': False, 'error': '无法连接 PyPI（请检查网络）'}), 502
    # installed 未知（None）时 has_update 必须是 null，不能冒充"已是最新版本"。
    has_update = None if not installed else _version_greater(latest, installed)
    update_mode = 'source_tree' if source_version else 'installed_package'
    return jsonify({
        'ok': True,
        'package': UPDATER_PACKAGE_NAME,
        'installed_version': installed,
        'running_source_version': source_version,
        'running_source_root': source_root,
        'running_entry': str(Path(__file__).resolve()),
        'update_mode': update_mode,
        'pip_upgrade_applies_to_running_entry': not bool(source_version),
        'latest_version': latest,
        'has_update': has_update,
        'source': source,
    })


def _write_upgrade_runner():
    """Write a detached upgrade+restart helper script; returns its path."""
    import tempfile
    runner_path = os.path.join(tempfile.gettempdir(), 'brain_workstation_upgrade.py')
    script = r'''import subprocess, sys, time, os, tempfile

def main():
    entry = sys.argv[1]
    pkg = sys.argv[2]
    log_path = os.path.join(tempfile.gettempdir(), 'brain_workstation_upgrade.log')
    time.sleep(6)  # wait for the host app to exit and release package files
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write('\n=== upgrade start ' + time.strftime('%Y-%m-%d %H:%M:%S') + ' ===\n')
        try:
            r = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '-U',
                 '--disable-pip-version-check', '--no-warn-script-location', pkg],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900)
            f.write((r.stdout or '') + (r.stderr or ''))
            f.write('pip exit code: ' + str(r.returncode) + '\n')
        except Exception as e:
            f.write('upgrade error: ' + str(e) + '\n')
        f.write('restarting app...\n')
    time.sleep(1)
    try:
        if os.name == 'nt':
            subprocess.Popen([sys.executable, entry], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([sys.executable, entry], start_new_session=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write('app restart launched: ' + entry + '\n')
    except Exception as e:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write('app restart FAILED: ' + repr(e) + '\n')

if __name__ == '__main__':
    main()
'''
    with open(runner_path, 'w', encoding='utf-8') as fh:
        fh.write(script)
    return runner_path


@app.route('/api/apply-update', methods=['POST'])
def api_apply_update():
    """Detached upgrade: run pip in a separate process, then auto-restart the app."""
    def generate():
        def emit(payload):
            return json.dumps(payload, ensure_ascii=False) + '\n'

        installed = _installed_package_version()
        source_version, source_root = _running_source_version()
        if source_version:
            yield emit({
                'type': 'error',
                'text': (
                    f'当前桌面快捷方式运行源码目录（{source_root}，版本 {source_version}）。'
                    'pip install -U cnhkmcp 只会更新 site-packages，不能更新这个快捷方式运行的源码目录。'
                    '请使用该源码目录对应的发布包/仓库更新方式，或重新创建指向已安装包入口的快捷方式。'
                ),
            })
            return
        yield emit({'type': 'log', 'text': '当前安装版本: ' + str(installed or '未安装')})
        yield emit({'type': 'log', 'text': '正在查询 PyPI 最新版本...'})
        latest, _ = _fetch_pypi_latest_version()
        if not latest:
            yield emit({'type': 'error', 'text': '无法连接 PyPI（请检查网络）'})
            return
        yield emit({'type': 'log', 'text': 'PyPI 最新版本: ' + str(latest)})
        if installed and not _version_greater(latest, installed):
            yield emit({'type': 'done', 'text': '已是最新版本，无需更新',
                        'installed_version': installed, 'latest_version': latest})
            return
        # 写入独立升级器并启动它（脱离本进程，宿主退出后由它完成升级并重启）
        try:
            runner_path = _write_upgrade_runner()
            entry = os.path.abspath(__file__)
            if os.name == 'nt':
                subprocess.Popen(
                    [sys.executable, runner_path, entry, UPDATER_PACKAGE_NAME],
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
                )
            else:
                subprocess.Popen(
                    [sys.executable, runner_path, entry, UPDATER_PACKAGE_NAME],
                    start_new_session=True,
                )
        except Exception as e:
            yield emit({'type': 'error', 'text': '启动升级器失败: ' + str(e)})
            return
        yield emit({'type': 'done',
                    'text': '升级已启动。本应用将在几秒后自动关闭以完成升级（替换包文件），完成后会自动重启。请稍候刷新本页面。',
                    'before_version': installed, 'latest_version': latest, 'auto_restart': True})
        # 让本应用退出，释放被占用的包内文件（如 ace.log），由独立升级器完成升级并重启
        threading.Timer(3.0, lambda: os._exit(0)).start()

    return Response(stream_with_context(generate()), mimetype='application/x-ndjson')

# BRAIN API configuration
BRAIN_API_BASE = 'https://api.worldquantbrain.com'


def _ace_credentials_path() -> Path:
    return Path.home() / 'secrets' / 'platform-brain.json'


def _sync_ace_persisted_credentials(username: str, password: str):
    username = str(username or '').strip()
    password = str(password or '').strip()
    if not username or not password:
        return
    try:
        _write_json_file(_ace_credentials_path(), {'email': username, 'password': password})
    except Exception as e:
        print(f"⚠️ Warning: Could not cache credentials to local disk: {e}")


def _sync_pipeline_credentials(username: str, password: str):
    if not _pipeline_available:
        return 0
    username = str(username or '').strip()
    password = str(password or '').strip()
    if not username or not password:
        return 0

    updated = 0
    try:
        for item in _list_pipelines():
            pipeline_id = item.get('pipeline_id') if isinstance(item, dict) else None
            if not pipeline_id:
                continue
            runner = _get_pipeline(pipeline_id)
            if not runner:
                continue
            old_username = str(runner.config.get('brain_username', '') or '').strip()
            if old_username and old_username != username:
                continue
            runner.config['brain_username'] = username
            runner.config['brain_password'] = password
            updated += 1
    except Exception as e:
        print(f"⚠️ Warning: Could not sync pipeline credentials: {e}")
    return updated


def _pick_first_non_empty(mapping, keys, default=''):
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _extract_submitter_llm_settings():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}

    form_payload = request.form if request.form else {}
    api_key = _pick_first_non_empty(
        payload,
        ['moonshot_api_key', 'apiKey', 'api_key', 'LLM_API_KEY'],
    ) or _pick_first_non_empty(
        form_payload,
        ['moonshot_api_key', 'apiKey', 'api_key', 'LLM_API_KEY'],
    )
    base_url = _pick_first_non_empty(
        payload,
        ['moonshot_base_url', 'baseUrl', 'base_url', 'llm_base_url', 'LLM_BASE_URL'],
        'https://api.moonshot.cn/v1',
    ) or _pick_first_non_empty(
        form_payload,
        ['moonshot_base_url', 'baseUrl', 'base_url', 'llm_base_url', 'LLM_BASE_URL'],
        'https://api.moonshot.cn/v1',
    )
    model = _pick_first_non_empty(
        payload,
        ['moonshot_model', 'model', 'LLM_model_name', 'LLM_MODEL_NAME'],
    ) or _pick_first_non_empty(
        form_payload,
        ['moonshot_model', 'model', 'LLM_model_name', 'LLM_MODEL_NAME'],
    )

    return {
        'api_key': api_key,
        'base_url': base_url,
        'model': model,
    }


def _orchestrator_root() -> Path:
    app_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    return app_dir / 'brain-orchestrator'


def _orchestrator_index_path() -> Path:
    return _orchestrator_root() / 'outputs' / 'index' / 'task_index.json'


def _orchestrator_center_path() -> Path:
    return _orchestrator_root() / 'outputs' / 'state_views' / 'command_center.json'


def _read_json_file(path: Path, default_value):
    try:
        if not path.exists():
            return default_value
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default_value


def _write_json_file(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _queue_statuses():
    return ('ready', 'running', 'done', 'failed', 'deadletter')


def _task_queue_path(day_key: str, queue_status: str, task_id: str) -> Path:
    return _orchestrator_root() / 'outputs' / 'partitions' / day_key / 'queue' / queue_status / f'{task_id}.json'


def _find_task_queue_file(day_key: str, task_id: str):
    for queue_status in _queue_statuses():
        p = _task_queue_path(day_key, queue_status, task_id)
        if p.exists():
            return queue_status, p
    return None, None


def _status_to_queue_name(status: str) -> str:
    status = str(status or '').lower()
    if status == 'completed':
        return 'done'
    return status


def _update_center_view_from_index(day_key: str):
    index_doc = _read_json_file(_orchestrator_index_path(), {'tasks': {}})
    tasks = index_doc.get('tasks', {}) if isinstance(index_doc, dict) else {}

    summary = {
        'updated_at': datetime.utcnow().isoformat() + 'Z',
        'day_key': day_key,
        'counts': {'ready': 0, 'running': 0, 'completed': 0, 'failed': 0, 'deadletter': 0},
        'by_stage': {},
        'reasoning_backlog': [],
        'blocked_dependencies': [],
    }

    same_day = {
        k: v for k, v in tasks.items()
        if isinstance(v, dict) and str(v.get('day_key', '')) == str(day_key)
    }

    for task in same_day.values():
        status = str(task.get('status', 'ready')).lower()
        stage = str(task.get('stage', 'unknown'))

        if status in summary['counts']:
            summary['counts'][status] += 1

        stage_bucket = summary['by_stage'].setdefault(stage, {
            'ready': 0,
            'running': 0,
            'completed': 0,
            'failed': 0,
            'deadletter': 0,
        })
        if status in stage_bucket:
            stage_bucket[status] += 1

        if task.get('reasoning_required') and status == 'ready':
            summary['reasoning_backlog'].append(task.get('task_id'))

        if status == 'ready':
            deps = task.get('depends_on') or []
            missing = []
            for dep in deps:
                dep_task = same_day.get(dep)
                if not dep_task or str(dep_task.get('status', '')).lower() != 'completed':
                    missing.append(dep)
            if missing:
                summary['blocked_dependencies'].append({'task_id': task.get('task_id'), 'missing': missing})

    _write_json_file(_orchestrator_center_path(), summary)
    return summary

# Store BRAIN sessions (in production, use proper session management like Redis)
brain_sessions = {}

print("🧠 BRAIN API integration configured!")

def sign_in_to_brain(username, password):
    """Sign in to BRAIN API with retry logic and biometric authentication support"""
    from urllib.parse import urljoin
    
    # Create a session to persistently store the headers
    session = requests.Session()
    # Save credentials into the session 
    session.auth = (username, password)
    
    retry_count = 0
    max_retries = 3
    
    while retry_count < max_retries:
        try:
            # Send a POST request to the /authentication API
            response = session.post(f'{BRAIN_API_BASE}/authentication')
            
            # Check if biometric authentication is needed
            if response.status_code == requests.codes.unauthorized:
                if response.headers.get("WWW-Authenticate") == "persona":
                    # Get biometric auth URL
                    location = response.headers.get("Location")
                    if location:
                        biometric_url = urljoin(response.url, location)
                        
                        # Return special response indicating biometric auth is needed
                        return {
                            'requires_biometric': True,
                            'biometric_url': biometric_url,
                            'session': session,
                            'location': location
                        }
                    else:
                        raise Exception("Biometric authentication required but no Location header provided")
                else:
                    # Regular authentication failure
                    print("Incorrect username or password")
                    raise requests.HTTPError(
                        "Authentication failed: Invalid username or password",
                        response=response,
                    )
            
            # If we get here, authentication was successful
            response.raise_for_status()
            print("Authentication successful.")
            return session
            
        except requests.HTTPError as e:
            if "Invalid username or password" in str(e) or "Authentication failed" in str(e):
                raise  # Don't retry for invalid credentials
            print(f"HTTP error occurred: {e}")
            retry_count += 1
            if retry_count < max_retries:
                print(f"Retrying... Attempt {retry_count + 1} of {max_retries}")
                time.sleep(10)
            else:
                print("Max retries reached. Authentication failed.")
                raise
        except Exception as e:
            print(f"Error during authentication: {e}")
            retry_count += 1
            if retry_count < max_retries:
                print(f"Retrying... Attempt {retry_count + 1} of {max_retries}")
                time.sleep(10)
            else:
                print("Max retries reached. Authentication failed.")
                raise

# Routes
@app.route('/')
def index():
    """Main application page"""
    return render_template('index.html')

@app.route('/simulator')
def simulator():
    """User-friendly simulator interface"""
    return render_template('simulator.html')


@app.route('/orchestrator-dashboard')
def orchestrator_dashboard():
    """编排任务可视化看板"""
    return render_template('orchestrator_dashboard.html')


@app.route('/api/orchestrator/summary', methods=['GET'])
def api_orchestrator_summary():
    """获取编排中心摘要状态"""
    center_doc = _read_json_file(_orchestrator_center_path(), {
        'day_key': '',
        'counts': {'ready': 0, 'running': 0, 'completed': 0, 'failed': 0, 'deadletter': 0},
        'reasoning_backlog': [],
        'blocked_dependencies': [],
        'by_stage': {}
    })

    return jsonify({
        'ok': True,
        'root': str(_orchestrator_root()),
        'summary': center_doc
    })


@app.route('/api/orchestrator/tasks', methods=['GET'])
def api_orchestrator_tasks():
    """获取任务列表（支持按状态/阶段筛选）"""
    status_filter = request.args.get('status', '').strip().lower()
    stage_filter = request.args.get('stage', '').strip().lower()
    limit = request.args.get('limit', default=200, type=int)
    day_key = request.args.get('day_key', '').strip()

    index_doc = _read_json_file(_orchestrator_index_path(), {'tasks': {}})
    tasks_dict = index_doc.get('tasks', {}) if isinstance(index_doc, dict) else {}

    tasks = []
    for task_id, task in tasks_dict.items():
        if not isinstance(task, dict):
            continue
        row = dict(task)
        row.setdefault('task_id', task_id)
        tasks.append(row)

    if day_key:
        tasks = [x for x in tasks if str(x.get('day_key', '')) == day_key]
    if status_filter:
        tasks = [x for x in tasks if str(x.get('status', '')).lower() == status_filter]
    if stage_filter:
        tasks = [x for x in tasks if str(x.get('stage', '')).lower() == stage_filter]

    tasks.sort(key=lambda x: (str(x.get('updated_at', '')), str(x.get('task_id', ''))), reverse=True)
    if limit > 0:
        tasks = tasks[:limit]

    return jsonify({
        'ok': True,
        'count': len(tasks),
        'tasks': tasks
    })


@app.route('/api/orchestrator/tasks', methods=['POST'])
def api_orchestrator_create_task():
    """创建新任务并入队"""
    body = request.get_json(silent=True) or {}
    task_id = str(body.get('task_id', '')).strip()
    day_key = str(body.get('day_key', '')).strip()
    stage = str(body.get('stage', '')).strip()

    if not task_id:
        return jsonify({'ok': False, 'error': '缺少 task_id'}), 400
    if not day_key:
        return jsonify({'ok': False, 'error': '缺少 day_key'}), 400
    if not stage:
        return jsonify({'ok': False, 'error': '缺少 stage'}), 400

    now = datetime.utcnow().isoformat() + 'Z'
    task = {
        'task_id': task_id,
        'day_key': day_key,
        'stage': stage,
        'status': 'ready',
        'created_at': now,
        'updated_at': now,
        'depends_on': body.get('depends_on', []),
        'note': str(body.get('note', '')),
        'last_error': '',
        'reasoning_required': bool(body.get('reasoning_required', False)),
    }

    index_path = _orchestrator_index_path()
    index_doc = _read_json_file(index_path, {'tasks': {}})
    tasks = index_doc.get('tasks', {}) if isinstance(index_doc, dict) else {}

    if task_id in tasks:
        return jsonify({'ok': False, 'error': f'任务已存在 {task_id}'}), 409

    tasks[task_id] = task
    index_doc['tasks'] = tasks
    _write_json_file(index_path, index_doc)

    queue_path = _task_queue_path(day_key, 'ready', task_id)
    _write_json_file(queue_path, task)

    summary = _update_center_view_from_index(day_key)

    return jsonify({
        'ok': True,
        'task': task,
        'summary': summary,
    }), 201


@app.route('/api/orchestrator/task/<task_id>', methods=['GET'])
def api_orchestrator_task_detail(task_id):
    """获取单个任务详情"""
    index_doc = _read_json_file(_orchestrator_index_path(), {'tasks': {}})
    tasks_dict = index_doc.get('tasks', {}) if isinstance(index_doc, dict) else {}
    task = tasks_dict.get(task_id)

    if not isinstance(task, dict):
        return jsonify({'ok': False, 'error': f'任务不存在 {task_id}'}), 404

    return jsonify({'ok': True, 'task': task})


@app.route('/api/orchestrator/task/<task_id>/action', methods=['POST'])
def api_orchestrator_task_action(task_id):
    """任务管理动作：重试入队/取消"""
    body = request.get_json(silent=True) or {}
    action = str(body.get('action', '')).strip().lower()
    reason = str(body.get('reason', '')).strip()

    if action not in {'retry', 'cancel'}:
        return jsonify({'ok': False, 'error': '不支持的动作，仅支持 retry/cancel'}), 400

    index_path = _orchestrator_index_path()
    index_doc = _read_json_file(index_path, {'tasks': {}})
    tasks = index_doc.get('tasks', {}) if isinstance(index_doc, dict) else {}
    task = tasks.get(task_id)

    if not isinstance(task, dict):
        return jsonify({'ok': False, 'error': f'任务不存在: {task_id}'}), 404

    day_key = str(task.get('day_key', '')).strip()
    if not day_key:
        return jsonify({'ok': False, 'error': '任务缺少 day_key'}), 400

    old_status = str(task.get('status', '')).lower()
    old_queue = _status_to_queue_name(old_status)

    if action == 'retry':
        if old_status not in {'failed', 'deadletter', 'completed'}:
            return jsonify({'ok': False, 'error': f'当前状态不支持重试: {old_status}'}), 400
        new_status = 'ready'
        new_queue = 'ready'
        task['last_error'] = ''
    else:
        if old_status not in {'ready', 'running'}:
            return jsonify({'ok': False, 'error': f'当前状态不支持取消: {old_status}'}), 400
        new_status = 'failed'
        new_queue = 'failed'
        task['last_error'] = reason or 'manual_cancelled'

    src_queue_name, src_path = _find_task_queue_file(day_key, task_id)
    if src_path is None:
        src_queue_name = old_queue
        src_path = _task_queue_path(day_key, src_queue_name, task_id)
        _write_json_file(src_path, task)

    dst_path = _task_queue_path(day_key, new_queue, task_id)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    task['status'] = new_status
    task['updated_at'] = datetime.utcnow().isoformat() + 'Z'

    _write_json_file(src_path, task)
    if src_path.resolve() != dst_path.resolve():
        try:
            shutil.move(str(src_path), str(dst_path))
        except Exception:
            _write_json_file(dst_path, task)
            if src_path.exists() and src_path.resolve() != dst_path.resolve():
                src_path.unlink(missing_ok=True)
    else:
        _write_json_file(dst_path, task)

    tasks[task_id] = task
    index_doc['tasks'] = tasks
    _write_json_file(index_path, index_doc)
    summary = _update_center_view_from_index(day_key)

    return jsonify({
        'ok': True,
        'task_id': task_id,
        'action': action,
        'from_status': old_status,
        'to_status': new_status,
        'from_queue': src_queue_name,
        'to_queue': new_queue,
        'task': task,
        'summary': summary,
    })

@app.route('/api/simulator/logs', methods=['GET'])
def get_simulator_logs():
    """Get available log files in the simulator directory"""
    try:
        import glob
        import os
        from datetime import datetime
        
        # Look for log files in the current directory and simulator directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        simulator_dir = os.path.join(script_dir, 'simulator')
        
        log_files = []
        
        # Check both current directory and simulator directory
        for directory in [script_dir, simulator_dir]:
            if os.path.exists(directory):
                patterns = [
                    os.path.join(directory, 'wqb*.log'),
                    os.path.join(directory, 'ace*.log'),
                ]
                for pattern in patterns:
                    for log_file in glob.glob(pattern):
                        try:
                            stat = os.stat(log_file)
                            log_files.append({
                                'filename': os.path.basename(log_file),
                                'path': log_file,
                                'size': f"{stat.st_size / 1024:.1f} KB",
                                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                                'mtime': stat.st_mtime
                            })
                        except Exception as e:
                            print(f"Error reading log file {log_file}: {e}")

        deduped = {}
        for item in log_files:
            deduped[item['path']] = item
        log_files = list(deduped.values())
        
        # Sort by modification time (newest first)
        log_files.sort(key=lambda x: x['mtime'], reverse=True)
        
        # Find the latest log file
        latest = log_files[0]['filename'] if log_files else None
        
        return jsonify({
            'logs': log_files,
            'latest': latest,
            'count': len(log_files)
        })
        
    except Exception as e:
        return jsonify({'error': f'Error getting log files: {str(e)}'}), 500

@app.route('/api/transformer_candidates')
def get_transformer_candidates():
    """Get Alpha candidates generated by Transformer"""
    try:
        # Path to the Transformer output file
        # Note: Folder name is 'Tranformer' (missing 's') based on user context
        file_path = os.path.join(os.path.dirname(__file__), 'Tranformer', 'output', 'Alpha_candidates.json')
        
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        else:
            return jsonify({"error": "File not found", "path": file_path})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/simulator/logs/<filename>', methods=['GET'])
def get_simulator_log_content(filename):
    """Get content of a specific log file"""
    try:
        import os
        
        # Security: only allow log files with safe names
        if not filename.endswith('.log') or not (filename.startswith('wqb') or filename.startswith('ace')):
            return jsonify({'error': 'Invalid log file name'}), 400
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        simulator_dir = os.path.join(script_dir, 'simulator')
        
        # Look for the file in both directories
        log_path = None
        for directory in [script_dir, simulator_dir]:
            potential_path = os.path.join(directory, filename)
            if os.path.exists(potential_path):
                log_path = potential_path
                break
        
        if not log_path:
            return jsonify({'error': 'Log file not found'}), 404
        
        # Read file content with multiple encoding attempts
        content = None
        encodings_to_try = ['utf-8', 'gbk', 'gb2312', 'big5', 'latin-1', 'cp1252']
        
        for encoding in encodings_to_try:
            try:
                with open(log_path, 'r', encoding=encoding) as f:
                    content = f.read()
                print(f"Successfully read log file with {encoding} encoding")
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                print(f"Error reading with {encoding}: {e}")
                continue
        
        if content is None:
            # Last resort: read as binary and decode with error handling
            try:
                with open(log_path, 'rb') as f:
                    raw_content = f.read()
                content = raw_content.decode('utf-8', errors='replace')
                print("Used UTF-8 with error replacement for log content")
            except Exception as e:
                content = f"Error: Could not decode file content - {str(e)}"
        
        response = jsonify({
            'content': content,
            'filename': filename,
            'size': len(content)
        })
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
        
    except Exception as e:
        return jsonify({'error': f'Error reading log file: {str(e)}'}), 500

@app.route('/api/simulator/test-connection', methods=['POST'])
def test_simulator_connection():
    """Test BRAIN API connection for simulator"""
    try:
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = data.get('password') or ''

        simulator_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'simulator')
        if simulator_dir not in sys.path:
            sys.path.insert(0, simulator_dir)

        import simulator_wqb

        session, logger = simulator_wqb.test_authentication(
            username=username or None,
            password=password or None,
        )

        if session is not None:
            try:
                session.close()
            except Exception:
                pass
            return jsonify({
                'success': True,
                'message': 'Connection successful'
            })
        return jsonify({
            'success': False,
            'error': 'Connection failed'
        })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Connection failed: {str(e)}'
        })


@app.route('/api/simulator/processed-files/<filename>', methods=['GET'])
def download_processed_expression_file(filename):
    """Download a processed expression JSON generated by the web simulator."""
    try:
        if not filename or filename != os.path.basename(filename) or not filename.endswith('.json'):
            return jsonify({'error': 'Invalid filename'}), 400

        processed_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'simulator', 'processed_expressions')
        file_path = os.path.join(processed_dir, filename)

        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404

        return send_file(file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        return jsonify({'error': f'Failed to download processed file: {str(e)}'}), 500

@app.route('/api/validate_expressions', methods=['POST'])
def validate_expressions():
    """Validate a list of expressions using ExpressionValidator"""
    try:
        data = request.json
        expressions = data.get('expressions', [])
        
        if not isinstance(expressions, list):
            return jsonify({'error': 'Expressions must be a list'}), 400
            
        validator = ExpressionValidator()
        results = []
        valid_count = 0
        invalid_count = 0
        
        # Validate all expressions
        expressions_to_validate = expressions
        
        for expr in expressions_to_validate:
            validation_result = validator.check_expression(expr)
            if validation_result['valid']:
                valid_count += 1
                results.append({
                    'expression': expr,
                    'valid': True
                })
            else:
                invalid_count += 1
                results.append({
                    'expression': expr,
                    'valid': False,
                    'errors': validation_result['errors']
                })
        
        return jsonify({
            'results': results,
            'summary': {
                'total': len(expressions_to_validate),
                'valid': valid_count,
                'invalid': invalid_count
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/simulator/run', methods=['POST'])
def run_simulator_with_params():
    """Run simulator with user-provided parameters in a new terminal"""
    try:
        import subprocess
        import threading
        import json
        import os
        import random
        import tempfile
        import sys
        import time
        
        # Get form data
        json_file = request.files.get('jsonFile')
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        start_position = int(request.form.get('startPosition', 0))
        concurrent_count = int(request.form.get('concurrentCount', 3))
        random_shuffle = request.form.get('randomShuffle') == 'true'
        use_multi_sim = request.form.get('useMultiSim') == 'true'
        alpha_count_per_slot = int(request.form.get('alphaCountPerSlot', 3))
        
        if not json_file:
            return jsonify({'error': 'Missing required parameters'}), 400
        
        # Validate and read JSON file
        try:
            json_content = json_file.read().decode('utf-8')
            expressions_data = json.loads(json_content)
            if not isinstance(expressions_data, list):
                return jsonify({'error': 'JSON file must contain an array of expressions'}), 400
        except Exception as e:
            return jsonify({'error': f'Invalid JSON file: {str(e)}'}), 400
        
        # Get paths
        script_dir = os.path.dirname(os.path.abspath(__file__))
        simulator_dir = os.path.join(script_dir, 'simulator')
        
        # Create temporary files for the automated run
        temp_json_path = os.path.join(simulator_dir, f'temp_expressions_{int(time.time())}.json')
        temp_script_path = os.path.join(simulator_dir, f'temp_automated_{int(time.time())}.py')
        temp_batch_path = os.path.join(simulator_dir, f'temp_run_{int(time.time())}.bat')
        
        try:
            processed_expressions = expressions_data
            processed_file_info = None
            original_expression_count = len(expressions_data) if isinstance(expressions_data, list) else 0

            if start_position > 0 or random_shuffle:
                if not isinstance(expressions_data, list):
                    return jsonify({'error': 'JSON file must contain an array of expressions'}), 400

                processed_expressions = expressions_data[start_position:] if start_position > 0 else list(expressions_data)
                if random_shuffle:
                    processed_expressions = list(processed_expressions)
                    random.shuffle(processed_expressions)

                processed_dir = os.path.join(simulator_dir, 'processed_expressions')
                os.makedirs(processed_dir, exist_ok=True)

                source_name = os.path.splitext(json_file.filename or 'expressions_with_settings')[0]
                processed_filename = f'{source_name}_processed_{int(time.time())}.json'
                processed_file_path = os.path.join(processed_dir, processed_filename)

                with open(processed_file_path, 'w', encoding='utf-8') as f:
                    json.dump(processed_expressions, f, ensure_ascii=False, indent=2)

                processed_file_info = {
                    'filename': processed_filename,
                    'download_url': f'/api/simulator/processed-files/{processed_filename}',
                    'expression_count': len(processed_expressions),
                    'original_filename': json_file.filename or 'expressions_with_settings.json',
                    'trimmed_count': start_position,
                    'was_shuffled': random_shuffle,
                }

            # Save the JSON data to temporary file
            with open(temp_json_path, 'w', encoding='utf-8') as f:
                json.dump(processed_expressions, f, ensure_ascii=False, indent=2)
            
            # Create the automated script that calls automated_main
            username_literal = json.dumps(username, ensure_ascii=False)
            password_literal = json.dumps(password, ensure_ascii=False)

            script_content = f'''
import asyncio
import sys
import os
import json

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simulator_wqb

async def run_automated():
    """Run the automated simulator with parameters from web interface"""
    try:
        # Load JSON data
        with open(r"{temp_json_path}", 'r', encoding='utf-8') as f:
            json_content = f.read()
        
        # Call automated_main with parameters
        result = await simulator_wqb.automated_main(
            json_file_content=json_content,
            username={username_literal},
            password={password_literal},
            start_position=0,
            concurrent_count={concurrent_count},
            random_shuffle=False,
            use_multi_sim={use_multi_sim},
            alpha_count_per_slot={alpha_count_per_slot}
        )
        
        if result['success']:
            print("\\n" + "="*60)
            print("🎀 WEB INTERFACE AUTOMATION Finished, Go to the webpage to check your result 🎀")
            print("="*60)
            print(f"Total simulations: {{result['results']['total']}}")
            print("="*60)
        else:
            print("\\n" + "="*60)
            print("❌ WEB INTERFACE AUTOMATION FAILED")
            print("="*60)
            print(f"Error: {{result['error']}}")
            print("="*60)
            
    except Exception as e:
        print(f"\\n❌ Script execution error: {{e}}")
    
    finally:
        # Clean up temporary files
        try:
            if os.path.exists(r"{temp_json_path}"):
                os.remove(r"{temp_json_path}")
            if os.path.exists(r"{temp_script_path}"):
                os.remove(r"{temp_script_path}")
            if os.path.exists(r"{temp_batch_path}"):
                os.remove(r"{temp_batch_path}")
        except:
            pass
        
        print("\\n🔄 Press Enter to close this window...")
        try:
            if sys.stdin.isatty():
                input()
        except Exception:
            pass

if __name__ == '__main__':
    asyncio.run(run_automated())
'''
            
            # Save the script
            with open(temp_script_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            
            # Create batch file for Windows only (cmd /k keeps the window open)
            if os.name == 'nt':
                batch_content = f'''@echo off
cd /d "{simulator_dir}"
"{sys.executable}" "{os.path.basename(temp_script_path)}"
'''
                with open(temp_batch_path, 'w', encoding='utf-8') as f:
                    f.write(batch_content)
            
            # Launch in a new visible terminal. The shared cross-platform helper
            # opens cmd /k on Windows, Terminal.app on macOS, or a Linux terminal
            # emulator, and falls back to a headless background run if needed.
            thread = threading.Thread(
                target=_open_in_new_terminal,
                kwargs={
                    'script_name': os.path.basename(temp_script_path),
                    'cwd': simulator_dir,
                },
            )
            thread.daemon = True
            thread.start()
            
            return jsonify({
                'success': True,
                'message': 'Simulator launched in new terminal window',
                'parameters': {
                    'expressions_count': len(processed_expressions),
                    'original_expressions_count': original_expression_count,
                    'concurrent_count': concurrent_count,
                    'start_position': start_position,
                    'random_shuffle': random_shuffle,
                    'use_multi_sim': use_multi_sim,
                    'alpha_count_per_slot': alpha_count_per_slot if use_multi_sim else None,
                    'processed_file': processed_file_info,
                }
            })
            
        except Exception as e:
            # Clean up on error
            try:
                if os.path.exists(temp_json_path):
                    os.remove(temp_json_path)
                if os.path.exists(temp_script_path):
                    os.remove(temp_script_path)
                if os.path.exists(temp_batch_path):
                    os.remove(temp_batch_path)
            except:
                pass
            raise e
        
    except Exception as e:
        return jsonify({'error': f'Failed to run simulator: {str(e)}'}), 500

@app.route('/api/simulator/stop', methods=['POST'])
def stop_simulator():
    """Stop running simulator"""
    try:
        # This is a placeholder - in a production environment, you'd want to 
        # implement proper process management to stop running simulations
        return jsonify({
            'success': True,
            'message': 'Stop signal sent'
        })
    except Exception as e:
        return jsonify({'error': f'Failed to stop simulator: {str(e)}'}), 500

@app.route('/api/authenticate', methods=['POST'])
def authenticate():
    """Authenticate with BRAIN API"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        # Authenticate with BRAIN
        result = sign_in_to_brain(username, password)
        
        # Check if biometric authentication is required
        if isinstance(result, dict) and result.get('requires_biometric'):
            # Store the session temporarily with biometric pending status
            session_id = f"{username}_{int(time.time())}_biometric_pending"
            brain_sessions[session_id] = {
                'session': result['session'],
                'username': username,
                'password': password,
                'timestamp': time.time(),
                'biometric_pending': True,
                'biometric_location': result['location']
            }
            
            # Store session ID in Flask session
            flask_session['brain_session_id'] = session_id
            
            return jsonify({
                'success': False,
                'requires_biometric': True,
                'biometric_url': result['biometric_url'],
                'session_id': session_id,
                'message': 'Please complete biometric authentication by visiting the provided URL'
            })
        
        # Regular successful authentication
        brain_session = result
        
        # Fetch simulation options
        valid_options = get_valid_simulation_options(brain_session)
        
        # Store session
        session_id = f"{username}_{int(time.time())}"
        brain_sessions[session_id] = {
            'session': brain_session,
            'username': username,
            'password': password,
            'timestamp': time.time(),
            'options': valid_options
        }
        _sync_ace_persisted_credentials(username, password)
        _sync_pipeline_credentials(username, password)
        
        # Store session ID in Flask session
        flask_session['brain_session_id'] = session_id
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'message': 'Authentication successful',
            'options': valid_options
        })
        
    except requests.HTTPError as e:
        resp = getattr(e, 'response', None)
        status_code = getattr(resp, 'status_code', None)

        # Common: wrong username/password
        if status_code == 401 or 'Invalid username or password' in str(e):
            return jsonify({
                'error': '用户名或密码错误',
                'hint': '请检查账号密码是否正确；如果你的账号需要生物验证（persona），请按弹出的生物验证流程完成后再点“Complete Authentication”。'
            }), 401

        # Upstream/network/server issues
        return jsonify({
            'error': 'Authentication failed',
            'detail': str(e)
        }), 502
    except Exception as e:
        return jsonify({'error': f'Authentication error: {str(e)}'}), 500

@app.route('/api/complete-biometric', methods=['POST'])
def complete_biometric():
    """Complete biometric authentication after user has done it in browser"""
    try:
        from urllib.parse import urljoin
        
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if not session_id or session_id not in brain_sessions:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        session_info = brain_sessions[session_id]
        
        # Check if this session is waiting for biometric completion
        if not session_info.get('biometric_pending'):
            return jsonify({'error': 'Session is not pending biometric authentication'}), 400
        
        brain_session = session_info['session']
        location = session_info['biometric_location']
        
        # Complete the biometric authentication following the reference pattern
        try:
            # Construct the full URL for biometric authentication
            auth_url = urljoin(f'{BRAIN_API_BASE}/authentication', location)
            
            # Keep trying until biometric auth succeeds (like in reference code)
            max_attempts = 5
            attempt = 0
            
            while attempt < max_attempts:
                bio_response = brain_session.post(auth_url)
                if bio_response.status_code == 201:
                    # Biometric authentication successful
                    break
                elif bio_response.status_code == 401:
                    # Biometric authentication not complete yet
                    attempt += 1
                    if attempt >= max_attempts:
                        return jsonify({
                            'success': False,
                            'error': 'Biometric authentication not completed. Please try again.'
                        })
                    time.sleep(2)  # Wait a bit before retrying
                else:
                    # Other error
                    bio_response.raise_for_status()
            
            # Update session info - remove biometric pending status
            session_info['biometric_pending'] = False
            del session_info['biometric_location']
            
            # Create a new session ID without the biometric_pending suffix
            new_session_id = f"{session_info['username']}_{int(time.time())}"
            brain_sessions[new_session_id] = {
                'session': brain_session,
                'username': session_info['username'],
                'password': session_info.get('password'),
                'timestamp': time.time()
            }
            _sync_ace_persisted_credentials(session_info.get('username'), session_info.get('password'))
            _sync_pipeline_credentials(session_info.get('username'), session_info.get('password'))
            
            # Remove old session
            del brain_sessions[session_id]
            
            # Update Flask session
            flask_session['brain_session_id'] = new_session_id
            
            return jsonify({
                'success': True,
                'session_id': new_session_id,
                'message': 'Biometric authentication completed successfully'
            })
            
        except requests.HTTPError as e:
            return jsonify({
                'success': False,
                'error': f'Failed to complete biometric authentication: {str(e)}'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error completing biometric authentication: {str(e)}'
        })

@app.route('/api/operators', methods=['GET'])
def get_operators():
    """Get user operators from BRAIN API"""
    try:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if not session_id or session_id not in brain_sessions:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        session_info = brain_sessions[session_id]
        brain_session = session_info['session']
        
        # First try without pagination parameters (most APIs return all operators at once)
        try:
            response = brain_session.get(f'{BRAIN_API_BASE}/operators')
            response.raise_for_status()
            
            data = response.json()
            
            # If it's a list, we got all operators
            if isinstance(data, list):
                all_operators = data
                print(f"Fetched {len(all_operators)} operators from BRAIN API (direct)")
            # If it's a dict with results, handle pagination
            elif isinstance(data, dict) and 'results' in data:
                all_operators = []
                total_count = data.get('count', len(data['results']))
                print(f"Found {total_count} total operators, fetching all...")
                
                # Get first batch
                all_operators.extend(data['results'])
                
                # Get remaining batches if needed
                limit = 100
                offset = len(data['results'])
                
                while len(all_operators) < total_count:
                    params = {'limit': limit, 'offset': offset}
                    batch_response = brain_session.get(f'{BRAIN_API_BASE}/operators', params=params)
                    batch_response.raise_for_status()
                    batch_data = batch_response.json()
                    
                    if isinstance(batch_data, dict) and 'results' in batch_data:
                        batch_operators = batch_data['results']
                        if not batch_operators:  # No more data
                            break
                        all_operators.extend(batch_operators)
                        offset += len(batch_operators)
                    else:
                        break
                
                print(f"Fetched {len(all_operators)} operators from BRAIN API (paginated)")
            else:
                # Unknown format, treat as empty
                all_operators = []
                print("Unknown response format for operators API")
            
        except Exception as e:
            print(f"Error fetching operators: {str(e)}")
            # Fallback: try with explicit pagination
            all_operators = []
            limit = 100
            offset = 0
            
            while True:
                params = {'limit': limit, 'offset': offset}
                response = brain_session.get(f'{BRAIN_API_BASE}/operators', params=params)
                response.raise_for_status()
                
                data = response.json()
                if isinstance(data, list):
                    all_operators.extend(data)
                    if len(data) < limit:
                        break
                elif isinstance(data, dict) and 'results' in data:
                    batch_operators = data['results']
                    all_operators.extend(batch_operators)
                    if len(batch_operators) < limit:
                        break
                else:
                    break
                
                offset += limit
            
            print(f"Fetched {len(all_operators)} operators from BRAIN API (fallback)")
        
        # Extract name, category, description, definition and other fields (if available)
        filtered_operators = []
        for op in all_operators:
            operator_data = {
                'name': op['name'], 
                'category': op['category']
            }
            # Include description if available
            if 'description' in op and op['description']:
                operator_data['description'] = op['description']
            # Include definition if available
            if 'definition' in op and op['definition']:
                operator_data['definition'] = op['definition']
            # Include usage count if available  
            if 'usageCount' in op:
                operator_data['usageCount'] = op['usageCount']
            # Include other useful fields if available
            if 'example' in op and op['example']:
                operator_data['example'] = op['example']
            filtered_operators.append(operator_data)
        
        # Save valid operators to file
        try:
            valid_op_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'validOp.json')
            import json
            with open(valid_op_path, 'w', encoding='utf-8') as f:
                json.dump(filtered_operators, f, ensure_ascii=False, indent=2)
            print(f"Saved {len(filtered_operators)} operators to {valid_op_path}")
        except Exception as e:
            print(f"Failed to save validOp: {e}")

        return jsonify(filtered_operators)
        
    except Exception as e:
        print(f"Error fetching operators: {str(e)}")
        return jsonify({'error': f'Failed to fetch operators: {str(e)}'}), 500

@app.route('/api/simulation-options', methods=['GET'])
def get_simulation_options():
    """Get valid simulation options from BRAIN"""
    try:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if not session_id or session_id not in brain_sessions:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        session_info = brain_sessions[session_id]
        
        # Return cached options if available
        if 'options' in session_info and session_info['options']:
            return jsonify(session_info['options'])
            
        # Otherwise fetch them
        brain_session = session_info['session']
        valid_options = get_valid_simulation_options(brain_session)
        
        # Cache them
        session_info['options'] = valid_options
        
        return jsonify(valid_options)
        
    except Exception as e:
        print(f"Error fetching simulation options: {str(e)}")
        return jsonify({'error': f'Failed to fetch simulation options: {str(e)}'}), 500

@app.route('/api/datasets', methods=['GET'])
def get_datasets():
    """Get datasets from BRAIN API"""
    try:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if not session_id or session_id not in brain_sessions:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        session_info = brain_sessions[session_id]
        brain_session = session_info['session']
        
        # Get parameters
        region = request.args.get('region', 'USA')
        delay = request.args.get('delay', '1')
        universe = request.args.get('universe', 'TOP3000')
        instrument_type = request.args.get('instrument_type', 'EQUITY')
        
        # Fetch datasets (theme=false)
        url_false = f"{BRAIN_API_BASE}/data-sets?instrumentType={instrument_type}&region={region}&delay={delay}&universe={universe}&theme=false"
        response_false = brain_session.get(url_false)
        response_false.raise_for_status()
        datasets_false = response_false.json().get('results', [])
        
        # Fetch datasets (theme=true)
        url_true = f"{BRAIN_API_BASE}/data-sets?instrumentType={instrument_type}&region={region}&delay={delay}&universe={universe}&theme=true"
        response_true = brain_session.get(url_true)
        response_true.raise_for_status()
        datasets_true = response_true.json().get('results', [])
        
        # Combine results
        all_datasets = datasets_false + datasets_true
        
        return jsonify({'results': all_datasets, 'count': len(all_datasets)})
        
    except Exception as e:
        print(f"Error fetching datasets: {str(e)}")
        return jsonify({'error': f'Failed to fetch datasets: {str(e)}'}), 500

@app.route('/api/datafields', methods=['GET'])
def get_datafields():
    """Get data fields from BRAIN API"""
    try:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if not session_id or session_id not in brain_sessions:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        session_info = brain_sessions[session_id]
        brain_session = session_info['session']
        
        # Get parameters
        region = request.args.get('region', 'USA')
        delay = request.args.get('delay', '1')
        universe = request.args.get('universe', 'TOP3000')
        dataset_id = request.args.get('dataset_id', 'fundamental6')
        search = ''
        
        # Build URL template based on notebook implementation
        if len(search) == 0:
            url_template = f"{BRAIN_API_BASE}/data-fields?" + \
                f"&instrumentType=EQUITY" + \
                f"&region={region}&delay={delay}&universe={universe}&dataset.id={dataset_id}&limit=50" + \
                "&offset={x}"
            # Get count from first request
            first_response = brain_session.get(url_template.format(x=0))
            first_response.raise_for_status()
            count = first_response.json()['count']
        else:
            url_template = f"{BRAIN_API_BASE}/data-fields?" + \
                f"&instrumentType=EQUITY" + \
                f"&region={region}&delay={delay}&universe={universe}&limit=50" + \
                f"&search={search}" + \
                "&offset={x}"
            count = 100  # Default for search queries
        
        # Fetch all data fields in batches
        datafields_list = []
        for x in range(0, count, 50):
            response = brain_session.get(url_template.format(x=x))
            while response.status_code == 429:
                print("status_code 429, sleep 3 seconds")
                time.sleep(3)
                response = brain_session.get(url_template.format(x=x))
            response.raise_for_status()
            datafields_list.append(response.json()['results'])
        
        # Flatten the list
        datafields_list_flat = [item for sublist in datafields_list for item in sublist]
        
        # Filter fields to only include necessary information
        filtered_fields = [
            {
                'id': field['id'],
                'description': field['description'],
                'type': field['type'],
                'coverage': field.get('coverage', 0),
                'userCount': field.get('userCount', 0),
                'alphaCount': field.get('alphaCount', 0)
            }
            for field in datafields_list_flat
        ]
        
        return jsonify(filtered_fields)
        
    except Exception as e:
        return jsonify({'error': f'Failed to fetch data fields: {str(e)}'}), 500

@app.route('/api/dataset-description', methods=['GET'])
def get_dataset_description():
    """Get dataset description from BRAIN API"""
    try:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if not session_id or session_id not in brain_sessions:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        session_info = brain_sessions[session_id]
        brain_session = session_info['session']
        
        # Get parameters
        region = request.args.get('region', 'USA')
        delay = request.args.get('delay', '1')
        universe = request.args.get('universe', 'TOP3000')
        dataset_id = request.args.get('dataset_id', 'analyst10')
        
        # Build URL for dataset description
        url = f"{BRAIN_API_BASE}/data-sets/{dataset_id}?" + \
              f"instrumentType=EQUITY&region={region}&delay={delay}&universe={universe}"
        
        print(f"Getting dataset description from: {url}")
        
        # Make request to BRAIN API
        response = brain_session.get(url)
        response.raise_for_status()
        
        data = response.json()
        description = data.get('description', 'No description available')
        
        print(f"Dataset description retrieved: {description[:100]}...")
        
        return jsonify({
            'success': True,
            'description': description,
            'dataset_id': dataset_id
        })
        
    except Exception as e:
        print(f"Dataset description error: {str(e)}")
        return jsonify({'error': f'Failed to get dataset description: {str(e)}'}), 500

@app.route('/api/status', methods=['GET'])
def check_status():
    """Check if session is still valid"""
    try:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if not session_id or session_id not in brain_sessions:
            return jsonify({'valid': False})
        
        session_info = brain_sessions[session_id]
        # Check if session is not too old (24 hours)
        if time.time() - session_info['timestamp'] > 86400:
            del brain_sessions[session_id]
            return jsonify({'valid': False})
        
        # Check if biometric authentication is pending
        if session_info.get('biometric_pending'):
            return jsonify({
                'valid': False,
                'biometric_pending': True,
                'username': session_info['username'],
                'message': 'Biometric authentication pending'
            })
        
        return jsonify({
            'valid': True,
            'username': session_info['username']
        })
        
    except Exception as e:
        return jsonify({'error': f'Status check failed: {str(e)}'}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    """Logout and clean up session"""
    try:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if session_id and session_id in brain_sessions:
            del brain_sessions[session_id]
        
        if 'brain_session_id' in flask_session:
            flask_session.pop('brain_session_id')
        
        return jsonify({'success': True, 'message': 'Logged out successfully'})
        
    except Exception as e:
        return jsonify({'error': f'Logout failed: {str(e)}'}), 500

@app.route('/api/test-expression', methods=['POST'])
def test_expression():
    """Test an expression using BRAIN API simulation"""
    try:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if not session_id or session_id not in brain_sessions:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        session_info = brain_sessions[session_id]
        brain_session = session_info['session']
        
        # Get the simulation data from request
        simulation_data = request.get_json()
        
        # Ensure required fields are present
        if 'type' not in simulation_data:
            simulation_data['type'] = 'REGULAR'
        
        # Ensure settings have required fields
        if 'settings' not in simulation_data:
            simulation_data['settings'] = {}
        
        # Set default values for missing settings
        default_settings = {
            'instrumentType': 'EQUITY',
            'region': 'USA',
            'universe': 'TOP3000',
            'delay': 1,
            'decay': 15,
            'neutralization': 'SUBINDUSTRY',
            'truncation': 0.08,
            'pasteurization': 'ON',
            'testPeriod': 'P1Y6M',
            'unitHandling': 'VERIFY',
            'nanHandling': 'OFF',
            'language': 'FASTEXPR',
            'visualization': False
        }
        
        for key, value in default_settings.items():
            if key not in simulation_data['settings']:
                simulation_data['settings'][key] = value
        
        # Convert string boolean values to actual boolean
        if isinstance(simulation_data['settings'].get('visualization'), str):
            viz_value = simulation_data['settings']['visualization'].lower()
            simulation_data['settings']['visualization'] = viz_value == 'true'
        
        # Validate settings against cached options
        valid_options = session_info.get('options')
        if valid_options:
            settings = simulation_data['settings']
            inst_type = settings.get('instrumentType', 'EQUITY')
            region = settings.get('region')
            neut = settings.get('neutralization')
            
            # Check if this specific neutralization is allowed for this region
            allowed_neuts = valid_options.get(inst_type, {}).get(region, {}).get('neutralizations', [])
            
            if neut and allowed_neuts and neut not in allowed_neuts:
                print(f"Warning: {neut} is invalid for {region}. Auto-correcting.")
                # Auto-correct to the first valid one if available
                if allowed_neuts:
                    print(f"Auto-correcting neutralization to {allowed_neuts[0]}")
                    settings['neutralization'] = allowed_neuts[0]
                else:
                    del settings['neutralization']

        # Send simulation request (following notebook pattern)
        try:
            message = {}
            simulation_response = brain_session.post(f'{BRAIN_API_BASE}/simulations', json=simulation_data)
            
            # Check if we got a Location header (following notebook pattern)
            if 'Location' in simulation_response.headers:
                # Follow the location to get the actual status
                message = brain_session.get(simulation_response.headers['Location']).json()
                
                # Check if simulation is running or completed
                if 'progress' in message.keys():
                    info_to_print = "Simulation is running"
                    return jsonify({
                        'success': True,
                        'status': 'RUNNING',
                        'message': info_to_print,
                        'full_response': message
                    })
                else:
                    # Return the full message as in notebook
                    return jsonify({
                        'success': message.get('status') != 'ERROR',
                        'status': message.get('status', 'UNKNOWN'),
                        'message': str(message),
                        'full_response': message
                    })
            else:
                # Try to get error from response body (following notebook pattern)
                try:
                    message = simulation_response.json()
                    return jsonify({
                        'success': False,
                        'status': 'ERROR',
                        'message': str(message),
                        'full_response': message
                    })
                except:
                    return jsonify({
                        'success': False,
                        'status': 'ERROR', 
                        'message': 'web Connection Error',
                        'full_response': {}
                    })
                    
        except Exception as e:
            return jsonify({
                'success': False,
                'status': 'ERROR',
                'message': 'web Connection Error',
                'full_response': {'error': str(e)}
            })
            
    except Exception as e:
        import traceback
        return jsonify({
            'success': False,
            'status': 'ERROR',
            'message': f'Test expression failed: {str(e)}',
            'full_response': {'error': str(e), 'traceback': traceback.format_exc()}
        }), 500

@app.route('/api/test-operators', methods=['GET'])
def test_operators():
    """Test endpoint to check raw BRAIN operators API response"""
    try:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if not session_id or session_id not in brain_sessions:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        session_info = brain_sessions[session_id]
        brain_session = session_info['session']
        
        # Get raw response from BRAIN API
        response = brain_session.get(f'{BRAIN_API_BASE}/operators')
        response.raise_for_status()
        
        data = response.json()
        
        # Return raw response info for debugging
        result = {
            'type': str(type(data)),
            'is_list': isinstance(data, list),
            'is_dict': isinstance(data, dict),
            'length': len(data) if isinstance(data, list) else None,
            'keys': list(data.keys()) if isinstance(data, dict) else None,
            'count_key': data.get('count') if isinstance(data, dict) else None,
            'first_few_items': data[:3] if isinstance(data, list) else (data.get('results', [])[:3] if isinstance(data, dict) else None)
        }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': f'Test failed: {str(e)}'}), 500

# Import blueprints
try:
    from blueprints import idea_house_bp, paper_analysis_bp, feature_engineering_bp, inspiration_house_bp
    print("📦 Blueprints imported successfully!")
except ImportError as e:
    print(f"❌ Failed to import blueprints: {e}")
    print("Some features may not be available.")

# Register blueprints
app.register_blueprint(idea_house_bp, url_prefix='/idea-house')
app.register_blueprint(paper_analysis_bp, url_prefix='/paper-analysis')
app.register_blueprint(feature_engineering_bp, url_prefix='/feature-engineering')
app.register_blueprint(inspiration_house_bp, url_prefix='/inspiration-house')

try:
    from quantflow import quantflow_bp
    app.register_blueprint(quantflow_bp)
    print("   - QuantFlow: /quantflow")
except ImportError as e:
    print(f"⚠️  QuantFlow blueprint not available: {e}")

try:
    from quantflow import quantflow_api_bp
    app.register_blueprint(quantflow_api_bp)
    print("   - QuantFlow API: /quantflow/api")
except ImportError as e:
    print(f"⚠️  QuantFlow API blueprint not available: {e}")

print("🔡 All blueprints registered successfully!")
print("   - Idea House: /idea-house")
print("   - Paper Analysis: /paper-analysis") 
print("   - Feature Engineering: /feature-engineering")
print("   - Inspiration House: /inspiration-house")

# Template Management Routes
# Get the directory where this script is located for templates
script_dir = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(script_dir, 'custom_templates')

# Ensure templates directory exists
if not os.path.exists(TEMPLATES_DIR):
    os.makedirs(TEMPLATES_DIR)
    print(f"📁 Created templates directory: {TEMPLATES_DIR}")
else:
    print(f"📁 Templates directory ready: {TEMPLATES_DIR}")

print("✅ BRAIN Expression Template Decoder fully initialized!")
print("🎆 Ready to process templates and integrate with BRAIN API!")

@app.route('/api/templates', methods=['GET'])
def get_templates():
    """Get all custom templates"""
    try:
        templates = []
        templates_file = os.path.join(TEMPLATES_DIR, 'templates.json')
        
        if os.path.exists(templates_file):
            with open(templates_file, 'r', encoding='utf-8') as f:
                templates = json.load(f)
        
        return jsonify(templates)
    except Exception as e:
        return jsonify({'error': f'Error loading templates: {str(e)}'}), 500

@app.route('/api/templates', methods=['POST'])
def save_template():
    """Save a new custom template"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        expression = data.get('expression', '').strip()
        template_configurations = data.get('templateConfigurations', {})
        
        if not name or not expression:
            return jsonify({'error': 'Name and expression are required'}), 400
        
        # Load existing templates
        templates_file = os.path.join(TEMPLATES_DIR, 'templates.json')
        templates = []
        
        if os.path.exists(templates_file):
            with open(templates_file, 'r', encoding='utf-8') as f:
                templates = json.load(f)
        
        # Check for duplicate names
        existing_index = next((i for i, t in enumerate(templates) if t['name'] == name), None)
        
        new_template = {
            'name': name,
            'description': description,
            'expression': expression,
            'templateConfigurations': template_configurations,
            'createdAt': datetime.now().isoformat()
        }
        
        if existing_index is not None:
            # Update existing template but preserve createdAt if it exists
            if 'createdAt' in templates[existing_index]:
                new_template['createdAt'] = templates[existing_index]['createdAt']
            new_template['updatedAt'] = datetime.now().isoformat()
            templates[existing_index] = new_template
            message = f'Template "{name}" updated successfully'
        else:
            # Add new template
            templates.append(new_template)
            message = f'Template "{name}" saved successfully'
        
        # Save to file
        with open(templates_file, 'w', encoding='utf-8') as f:
            json.dump(templates, f, indent=2, ensure_ascii=False)
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        return jsonify({'error': f'Error saving template: {str(e)}'}), 500

@app.route('/api/templates/<int:template_id>', methods=['DELETE'])
def delete_template(template_id):
    """Delete a custom template"""
    try:
        templates_file = os.path.join(TEMPLATES_DIR, 'templates.json')
        templates = []
        
        if os.path.exists(templates_file):
            with open(templates_file, 'r', encoding='utf-8') as f:
                templates = json.load(f)
        
        if 0 <= template_id < len(templates):
            deleted_template = templates.pop(template_id)
            
            # Save updated templates
            with open(templates_file, 'w', encoding='utf-8') as f:
                json.dump(templates, f, indent=2, ensure_ascii=False)
            
            return jsonify({'success': True, 'message': f'Template "{deleted_template["name"]}" deleted successfully'})
        else:
            return jsonify({'error': 'Template not found'}), 404
            
    except Exception as e:
        return jsonify({'error': f'Error deleting template: {str(e)}'}), 500

@app.route('/api/templates/export', methods=['GET'])
def export_templates():
    """Export all templates as JSON"""
    try:
        templates_file = os.path.join(TEMPLATES_DIR, 'templates.json')
        templates = []
        
        if os.path.exists(templates_file):
            with open(templates_file, 'r', encoding='utf-8') as f:
                templates = json.load(f)
        
        return jsonify(templates)
        
    except Exception as e:
        return jsonify({'error': f'Error exporting templates: {str(e)}'}), 500

@app.route('/api/templates/import', methods=['POST'])
def import_templates():
    """Import templates from JSON"""
    try:
        data = request.get_json()
        imported_templates = data.get('templates', [])
        overwrite = data.get('overwrite', False)
        
        if not isinstance(imported_templates, list):
            return jsonify({'error': 'Invalid template format'}), 400
        
        # Validate template structure
        valid_templates = []
        for template in imported_templates:
            if (isinstance(template, dict) and 
                'name' in template and 'expression' in template and
                template['name'].strip() and template['expression'].strip()):
                valid_templates.append({
                    'name': template['name'].strip(),
                    'description': template.get('description', '').strip(),
                    'expression': template['expression'].strip(),
                    'templateConfigurations': template.get('templateConfigurations', {}),
                    'createdAt': template.get('createdAt', datetime.now().isoformat())
                })
        
        if not valid_templates:
            return jsonify({'error': 'No valid templates found'}), 400
        
        # Load existing templates
        templates_file = os.path.join(TEMPLATES_DIR, 'templates.json')
        existing_templates = []
        
        if os.path.exists(templates_file):
            with open(templates_file, 'r', encoding='utf-8') as f:
                existing_templates = json.load(f)
        
        # Handle duplicates
        duplicates = []
        new_templates = []
        
        for template in valid_templates:
            existing_index = next((i for i, t in enumerate(existing_templates) if t['name'] == template['name']), None)
            
            if existing_index is not None:
                duplicates.append(template['name'])
                if overwrite:
                    existing_templates[existing_index] = template
            else:
                new_templates.append(template)
        
        # Add new templates
        existing_templates.extend(new_templates)
        
        # Save to file
        with open(templates_file, 'w', encoding='utf-8') as f:
            json.dump(existing_templates, f, indent=2, ensure_ascii=False)
        
        result = {
            'success': True,
            'imported': len(new_templates),
            'duplicates': duplicates,
            'overwritten': len(duplicates) if overwrite else 0
        }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': f'Error importing templates: {str(e)}'}), 500

@app.route('/api/run-simulator', methods=['POST'])
def run_simulator():
    """Run the simulator_wqb.py script"""
    try:
        import subprocess
        import threading
        from pathlib import Path
        
        # Get the script path (now in simulator subfolder)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        simulator_dir = os.path.join(script_dir, 'simulator')
        simulator_path = os.path.join(simulator_dir, 'simulator_wqb.py')
        
        # Check if the script exists
        if not os.path.exists(simulator_path):
            return jsonify({'error': 'simulator_wqb.py not found in simulator folder'}), 404
        
        # Launch the script in a new visible terminal. The shared cross-platform
        # helper opens cmd /k on Windows, Terminal.app on macOS (via an
        # executable .command file — no osascript permission prompts), or a
        # Linux terminal emulator, and falls back to a headless background run
        # when no terminal is available. It always uses sys.executable so the
        # child runs with the same Python interpreter as this web app.
        thread = threading.Thread(
            target=_open_in_new_terminal,
            kwargs={
                'script_name': 'simulator_wqb.py',
                'cwd': simulator_dir,
            },
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Simulator script started in new terminal window'
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to run simulator: {str(e)}'}), 500

@app.route('/api/open-submitter', methods=['POST'])
def open_submitter():
    """Run the alpha_submitter.py script"""
    try:
        import subprocess
        import threading
        from pathlib import Path
        
        # Get the script path (now in simulator subfolder)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        simulator_dir = os.path.join(script_dir, 'simulator')
        submitter_path = os.path.join(simulator_dir, 'alpha_submitter.py')
        
        # Check if the script exists
        if not os.path.exists(submitter_path):
            return jsonify({'error': 'alpha_submitter.py not found in simulator folder'}), 404

        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        session_info = brain_sessions.get(session_id) if session_id else None
        submitter_env = os.environ.copy()
        credential_email = ''
        llm_settings = _extract_submitter_llm_settings()
        if session_info:
            credential_email = str(session_info.get('username') or '').strip()
            credential_password = str(session_info.get('password') or '').strip()
            if credential_email and credential_password:
                submitter_env['BRAIN_CREDENTIAL_EMAIL'] = credential_email
                submitter_env['BRAIN_CREDENTIAL_PASSWORD'] = credential_password
        if llm_settings['api_key']:
            submitter_env['MOONSHOT_API_KEY'] = llm_settings['api_key']
            submitter_env['LLM_API_KEY'] = llm_settings['api_key']
        if llm_settings['base_url']:
            submitter_env['MOONSHOT_BASE_URL'] = llm_settings['base_url']
            submitter_env['LLM_BASE_URL'] = llm_settings['base_url']
        if llm_settings['model']:
            submitter_env['MOONSHOT_MODEL'] = llm_settings['model']
            submitter_env['LLM_MODEL_NAME'] = llm_settings['model']
        
        # Launch the script in a new visible terminal (cross-platform helper).
        # submitter_env is forwarded: on macOS the helper exports these
        # variables inside the generated .command file, because Terminal.app
        # does not inherit this process's environment.
        thread = threading.Thread(
            target=_open_in_new_terminal,
            kwargs={
                'script_name': 'alpha_submitter.py',
                'cwd': simulator_dir,
                'env': submitter_env,
            },
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Alpha submitter script started in new terminal window'
                + (f' (preloaded credentials for {credential_email})' if credential_email else '')
                + (' (LLM config forwarded)' if llm_settings['api_key'] and llm_settings['model'] else '')
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to open submitter: {str(e)}'}), 500

@app.route('/api/open-hk-simulator', methods=['POST'])
def open_hk_simulator():
    """Run the autosimulator.py script from hkSimulator folder"""
    try:
        import subprocess
        import threading
        from pathlib import Path
        
        # Get the script path (hkSimulator subfolder)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        hk_simulator_dir = os.path.join(script_dir, 'hkSimulator')
        autosimulator_path = os.path.join(hk_simulator_dir, 'autosimulator.py')
        
        # Check if the script exists
        if not os.path.exists(autosimulator_path):
            return jsonify({'error': 'autosimulator.py not found in hkSimulator folder'}), 404
        
        # Launch the script in a new visible terminal (cross-platform helper).
        thread = threading.Thread(
            target=_open_in_new_terminal,
            kwargs={
                'script_name': 'autosimulator.py',
                'cwd': hk_simulator_dir,
            },
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'HK simulator script started in new terminal window'
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to open HK simulator: {str(e)}'}), 500

@app.route('/api/open-transformer', methods=['POST'])
def open_transformer():
    """Run the Transformer.py script from the Tranformer folder in a new terminal."""
    try:
        import subprocess
        import threading
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        transformer_dir = os.path.join(script_dir, 'Tranformer')
        transformer_path = os.path.join(transformer_dir, 'Transformer.py')
        
        if not os.path.exists(transformer_path):
            return jsonify({'error': 'Transformer.py not found in Tranformer folder'}), 404
        
        # Launch the script in a new visible terminal (cross-platform helper).
        thread = threading.Thread(
            target=_open_in_new_terminal,
            kwargs={
                'script_name': 'Transformer.py',
                'cwd': transformer_dir,
            },
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': 'Transformer script started in new terminal window'})
    
    except Exception as e:
        return jsonify({'error': f'Failed to open Transformer: {str(e)}'}), 500


@app.route('/api/usage-doc', methods=['GET'])
def get_usage_doc():
    """Return usage.md as raw markdown text for in-app help display."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        usage_path = os.path.join(base_dir, 'usage.md')
        if not os.path.exists(usage_path):
            return jsonify({'success': False, 'error': 'usage.md not found'}), 404

        with open(usage_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return jsonify({'success': True, 'markdown': content})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Global task manager for Transformer Web
transformer_tasks = {}

# Global task manager for Inspiration direct pipeline
inspiration_pipeline_tasks = {}

# Global task manager for template enhancement
inspiration_enhance_tasks = {}

@app.route('/transformer-web')
def transformer_web():
    return render_template('transformer_web.html')

@app.route('/api/llm/providers', methods=['GET'])
def llm_list_providers():
    """List OpenAI-compatible LLM provider presets (QuantFlow-style)."""
    try:
        from llm_providers import list_providers
        return jsonify({'ok': True, 'providers': list_providers()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/llm/models', methods=['POST'])
def llm_fetch_models():
    """Fetch live model list from vendor official /models endpoints."""
    data = request.json or {}
    provider = data.get('provider') or data.get('modelProvider') or 'moonshot'
    api_key = (
        data.get('api_key')
        or data.get('apiKey')
        or data.get('LLM_API_KEY')
        or ''
    )
    base_url = (
        data.get('base_url')
        or data.get('baseUrl')
        or data.get('llm_base_url')
        or ''
    )
    preferred = (
        data.get('model')
        or data.get('model_name')
        or data.get('modelName')
        or ''
    )
    allow_manual = bool(data.get('allow_manual'))
    try:
        from llm_providers import list_remote_models, normalize_provider, probe_chat_completion, select_model
        provider_id = normalize_provider(str(provider))
        try:
            listed = list_remote_models(
                provider=provider_id,
                api_key=str(api_key),
                base_url=str(base_url),
            )
            selected = select_model(listed['models'], str(preferred))
            return jsonify({
                'ok': True,
                'success': True,
                'provider': listed['provider'],
                'models': listed['models'],
                'model_catalog': listed['model_catalog'],
                'endpoint': listed['endpoint'],
                'count': listed['count'],
                'base_url': listed['base_url'],
                'selected': selected,
                'probed': False,
            })
        except ValueError as list_exc:
            # Custom OpenAI-compatible endpoints often omit /models; allow typed model probe.
            if provider_id == 'custom' or allow_manual:
                probed = probe_chat_completion(
                    provider=provider_id,
                    api_key=str(api_key),
                    base_url=str(base_url),
                    model=str(preferred),
                )
                return jsonify({
                    'ok': True,
                    'success': True,
                    'provider': probed['provider'],
                    'models': probed['models'],
                    'model_catalog': probed['model_catalog'],
                    'endpoint': probed['endpoint'],
                    'count': probed['count'],
                    'base_url': probed['base_url'],
                    'selected': probed['selected'],
                    'probed': True,
                    'list_error': str(list_exc),
                })
            raise
    except ValueError as e:
        return jsonify({'ok': False, 'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'success': False, 'error': str(e)}), 500


@app.route('/api/test-llm-connection', methods=['POST'])
def test_llm_connection():
    data = request.json or {}
    api_key = data.get('apiKey') or data.get('api_key')
    base_url = data.get('baseUrl') or data.get('base_url')
    model = data.get('model') or data.get('model_name')
    provider = data.get('provider') or data.get('modelProvider') or ''
    
    try:
        from llm_providers import (
            list_remote_models,
            normalize_provider,
            probe_chat_completion,
            resolve_base_url,
            select_model,
        )
        provider_id = normalize_provider(str(provider or 'custom'))
        # Custom + typed model: probe Chat Completions directly (OpenAI format).
        if provider_id == 'custom' and model:
            probed = probe_chat_completion(
                provider=provider_id,
                api_key=str(api_key or ''),
                base_url=str(base_url or ''),
                model=str(model or ''),
            )
            return jsonify({
                'success': True,
                'ok': True,
                'provider': probed['provider'],
                'models': probed['models'],
                'model_catalog': probed['model_catalog'],
                'endpoint': probed['endpoint'],
                'count': probed['count'],
                'base_url': probed['base_url'],
                'selected': probed['selected'],
                'model': probed['selected'],
                'probed': True,
            })
        listed = list_remote_models(
            provider=provider_id,
            api_key=str(api_key or ''),
            base_url=str(base_url or ''),
        )
        selected = select_model(listed['models'], str(model or ''))
        return jsonify({
            'success': True,
            'ok': True,
            'provider': listed['provider'],
            'models': listed['models'],
            'model_catalog': listed['model_catalog'],
            'endpoint': listed['endpoint'],
            'count': listed['count'],
            'base_url': listed['base_url'] or resolve_base_url(listed['provider'], str(base_url or '')),
            'selected': selected,
            'model': selected,
            'probed': False,
        })
    except Exception as e:
        return jsonify({'success': False, 'ok': False, 'error': str(e)})

@app.route('/api/get-default-template-summary')
def get_default_template_summary():
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        transformer_dir = os.path.join(script_dir, 'Tranformer')
        
        # Read the file directly to avoid import issues/side effects
        transformer_path = os.path.join(transformer_dir, 'Transformer.py')
        with open(transformer_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract template_summary variable using regex
        import re
        match = re.search(r'template_summary\s*=\s*"""(.*?)"""', content, re.DOTALL)
        if match:
            return jsonify({'success': True, 'summary': match.group(1)})
        else:
            return jsonify({'success': False, 'error': 'Could not find template_summary in Transformer.py'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/run-transformer-web', methods=['POST'])
def run_transformer_web():
    data = request.json
    task_id = str(uuid.uuid4())
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    transformer_dir = os.path.join(script_dir, 'Tranformer')
    
    # Handle template summary content
    template_summary_content = data.get('template_summary_content')
    template_summary_path = None
    
    if template_summary_content:
        template_summary_path = os.path.join(transformer_dir, f'temp_summary_{task_id}.txt')
        with open(template_summary_path, 'w', encoding='utf-8') as f:
            f.write(template_summary_content)
    
    # Create a temporary config file
    config = {
        "LLM_model_name": data.get('LLM_model_name'),
        "LLM_API_KEY": data.get('LLM_API_KEY'),
        "llm_base_url": data.get('llm_base_url'),
        "username": data.get('username'),
        "password": data.get('password'),
        "template_summary_path": template_summary_path,
        "alpha_id": data.get('alpha_id'),
        "top_n_datafield": int(data.get('top_n_datafield', 50)),
        "user_region": data.get('region'),
        "user_universe": data.get('universe'),
        "user_delay": int(data.get('delay')) if data.get('delay') else None,
        "user_category": data.get('category'),
        "user_data_type": data.get('data_type', 'MATRIX')
    }
    
    config_path = os.path.join(transformer_dir, f'config_{task_id}.json')
    
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)
        
    # Start the process
    transformer_script = os.path.join(transformer_dir, 'Transformer.py')
    
    # Use a queue to store logs
    log_queue = queue.Queue()
    
    def run_process():
        try:
            # Force UTF-8 encoding for the subprocess output to avoid UnicodeEncodeError on Windows
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            
            process = subprocess.Popen(
                [sys.executable, '-u', transformer_script, config_path],
                cwd=transformer_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace',
                env=env
            )
            
            transformer_tasks[task_id]['process'] = process
            
            for line in iter(process.stdout.readline, ''):
                log_queue.put(line)
                
            process.stdout.close()
            process.wait()
            transformer_tasks[task_id]['return_code'] = process.returncode
        except Exception as e:
            log_queue.put(f"Error running process: {str(e)}")
            transformer_tasks[task_id]['return_code'] = 1
        finally:
            log_queue.put(None) # Signal end
            # Clean up config file and temp summary file
            try:
                if os.path.exists(config_path):
                    os.remove(config_path)
                if template_summary_path and os.path.exists(template_summary_path):
                    os.remove(template_summary_path)
            except:
                pass

    thread = threading.Thread(target=run_process)
    thread.start()
    
    transformer_tasks[task_id] = {
        'queue': log_queue,
        'status': 'running',
        'output_dir': os.path.join(transformer_dir, 'output')
    }
    
    return jsonify({'success': True, 'taskId': task_id})

@app.route('/api/transformer/login-and-fetch-options', methods=['POST'])
def transformer_login_and_fetch_options():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password are required'})
        
    try:
        # Add Tranformer to path to import ace_lib
        script_dir = os.path.dirname(os.path.abspath(__file__))
        transformer_dir = os.path.join(script_dir, 'Tranformer')
        if transformer_dir not in sys.path:
            sys.path.append(transformer_dir)
            
        from ace_lib import SingleSession, get_instrument_type_region_delay
        
        # Use SingleSession for consistency with ace_lib
        session = SingleSession()
        # Force re-authentication
        session.auth = (username, password)
        
        brain_api_url = "https://api.worldquantbrain.com"
        response = session.post(brain_api_url + "/authentication")
        
        if response.status_code == 201:
             # Auth success
             pass
        elif response.status_code == 401:
             return jsonify({'success': False, 'error': 'Authentication failed: Invalid credentials'})
        else:
             return jsonify({'success': False, 'error': f'Authentication failed: {response.status_code} {response.text}'})
             
        # Now fetch options
        df = get_instrument_type_region_delay(session)
        
        # Fetch categories
        brain_api_url = "https://api.worldquantbrain.com"
        categories_resp = session.get(brain_api_url + "/data-categories")
        categories = []
        if categories_resp.status_code == 200:
            categories_data = categories_resp.json()
            if isinstance(categories_data, list):
                categories = categories_data
            elif isinstance(categories_data, dict):
                categories = categories_data.get('results', [])
        
        # Convert DataFrame to a nested dictionary structure for the frontend
        # Structure: Region -> Delay -> Universe
        # We only care about EQUITY for now as per previous code
        
        df_equity = df[df['InstrumentType'] == 'EQUITY']
        
        options = {}
        for _, row in df_equity.iterrows():
            region = row['Region']
            delay = row['Delay']
            universes = row['Universe'] # This is a list
            
            if region not in options:
                options[region] = {}
            
            # Convert delay to string for JSON keys
            delay_str = str(delay)
            if delay_str not in options[region]:
                options[region][delay_str] = universes
                
        return jsonify({
            'success': True, 
            'options': options,
            'categories': categories
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/stream-transformer-logs/<task_id>')
def stream_transformer_logs(task_id):
    def generate():
        if task_id not in transformer_tasks:
            yield f"data: {json.dumps({'status': 'error', 'log': 'Task not found'})}\n\n"
            return
            
        q = transformer_tasks[task_id]['queue']
        
        while True:
            try:
                line = q.get(timeout=1)
                if line is None:
                    return_code = transformer_tasks[task_id].get('return_code', 0)
                    status = 'completed' if return_code == 0 else 'error'
                    yield f"data: {json.dumps({'status': status, 'log': ''})}\n\n"
                    break
                yield f"data: {json.dumps({'status': 'running', 'log': line})}\n\n"
            except queue.Empty:
                # Check if process is still running
                if 'process' in transformer_tasks[task_id]:
                    proc = transformer_tasks[task_id]['process']
                    if proc.poll() is not None and q.empty():
                         return_code = proc.returncode
                         status = 'completed' if return_code == 0 else 'error'
                         yield f"data: {json.dumps({'status': status, 'log': ''})}\n\n"
                         break
                yield f"data: {json.dumps({'status': 'running', 'log': ''})}\n\n" # Keep alive
                
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/api/download-transformer-result/<task_id>/<file_type>')
def download_transformer_result(task_id, file_type):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    transformer_dir = os.path.join(script_dir, 'Tranformer')
    output_dir = os.path.join(transformer_dir, 'output')
    
    if file_type == 'candidates':
        filename = 'Alpha_candidates.json'
    elif file_type == 'success':
        filename = 'Alpha_generated_expressions_success.json'
    elif file_type == 'error':
        filename = 'Alpha_generated_expressions_error.json'
    else:
        return "Invalid file type", 400
        
    return send_from_directory(output_dir, filename, as_attachment=True)

# --- 缘分一道桥 (Alpha Inspector) Routes ---

# Add '缘分一道桥' to sys.path to allow importing brain_alpha_inspector
yuanfen_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '缘分一道桥')
if yuanfen_dir not in sys.path:
    sys.path.append(yuanfen_dir)

try:
    import brain_alpha_inspector
except ImportError as e:
    print(f"Warning: Could not import brain_alpha_inspector: {e}")
    brain_alpha_inspector = None

@app.route('/alpha_inspector')
def alpha_inspector_page():
    return render_template('alpha_inspector.html')

@app.route('/api/yuanfen/login', methods=['POST'])
def yuanfen_login():
    if not brain_alpha_inspector:
        return jsonify({'success': False, 'message': 'Module not loaded'})
    
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    try:
        session = brain_alpha_inspector.brain_login(username, password)
        session_id = str(uuid.uuid4())
        brain_sessions[session_id] = session
        return jsonify({'success': True, 'session_id': session_id})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/yuanfen/fetch_alphas', methods=['POST'])
def yuanfen_fetch_alphas():
    if not brain_alpha_inspector:
        return jsonify({'success': False, 'message': 'Module not loaded'})
        
    data = request.json
    session_id = data.get('session_id')
    mode = data.get('mode', 'date_range')
    
    session = brain_sessions.get(session_id)
    if not session:
        return jsonify({'success': False, 'message': 'Invalid session'})

    def generate():
        try:
            alphas = []
            if mode == 'ids':
                alpha_ids_str = data.get('alpha_ids', '')
                import re
                alpha_ids = [x.strip() for x in re.split(r'[,\s\n]+', alpha_ids_str) if x.strip()]
                yield json.dumps({"type": "progress", "message": f"Fetching {len(alpha_ids)} alphas by ID..."}) + "\n"
                alphas = brain_alpha_inspector.fetch_alphas_by_ids(session, alpha_ids)
            else:
                start_date = data.get('start_date')
                end_date = data.get('end_date')
                yield json.dumps({"type": "progress", "message": f"Fetching alphas from {start_date} to {end_date}..."}) + "\n"
                alphas = brain_alpha_inspector.fetch_alphas_by_date_range(session, start_date, end_date)
            yield json.dumps({"type": "progress", "message": f"Found {len(alphas)} alphas. Fetching operators..."}) + "\n"
            
            # 2. Fetch Operators (needed for parsing)
            operators = brain_alpha_inspector.fetch_operators(session)
            
            # 2.5 Fetch Simulation Options (for validation)
            simulation_options = None
            if brain_alpha_inspector.get_instrument_type_region_delay:
                yield json.dumps({"type": "progress", "message": "Fetching simulation options..."}) + "\n"
                try:
                    simulation_options = brain_alpha_inspector.get_instrument_type_region_delay(session)
                except Exception as e:
                    print(f"Error fetching simulation options: {e}")
            
            yield json.dumps({"type": "progress", "message": f"Analyzing {len(alphas)} alphas..."}) + "\n"
            
            # 3. Analyze each alpha
            analyzed_alphas = []
            for i, alpha in enumerate(alphas):
                alpha_id = alpha.get('id', 'Unknown')
                yield json.dumps({"type": "progress", "message": f"Processing alpha {i+1}/{len(alphas)}: {alpha_id}"}) + "\n"
                
                result = brain_alpha_inspector.get_alpha_variants(session, alpha, operators, simulation_options)
                if result['valid'] and result['variants']:
                    analyzed_alphas.append(result)
            
            yield json.dumps({"type": "result", "success": True, "alphas": analyzed_alphas}) + "\n"
            
        except Exception as e:
            print(f"Error in fetch_alphas: {e}")
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return Response(stream_with_context(generate()), mimetype='application/x-ndjson')

@app.route('/api/yuanfen/simulate', methods=['POST'])
def yuanfen_simulate():
    if not brain_alpha_inspector:
        return jsonify({'success': False, 'message': 'Module not loaded'})
        
    data = request.json
    session_id = data.get('session_id')
    # alpha_id = data.get('alpha_id') # Not strictly needed if we have full payload
    payload = data.get('payload') # The full simulation payload
    
    session = brain_sessions.get(session_id)
    if not session:
        return jsonify({'success': False, 'message': 'Invalid session'})
        
    try:
        success, result_or_msg = brain_alpha_inspector.run_simulation_payload(session, payload)
        
        if success:
            return jsonify({'success': True, 'result': result_or_msg})
        else:
            return jsonify({'success': False, 'message': result_or_msg})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

def process_options_dataframe(df):
    """
    Transforms the options DataFrame into a nested dictionary:
    {

        "EQUITY": {
            "USA": {
                "delays": [0, 1],
                "universes": ["TOP3000", ...],
                "neutralizations": ["MARKET", "INDUSTRY", ...] 
            },
            "TWN": { ... }
        }
    }
    """
    result = {}
    if df is None or df.empty:
        return result

    for _, row in df.iterrows():
        inst = row.get('InstrumentType', 'EQUITY')
        region = row.get('Region')
        
        if inst not in result: result[inst] = {}
        if region not in result[inst]: 
            result[inst][region] = {
                "delays": [],
                "universes": [],
                "neutralizations": []
            }
            
        # Aggregate unique values
        delay = row.get('Delay')
        if delay is not None and delay not in result[inst][region]['delays']:
            result[inst][region]['delays'].append(delay)
            
        universes = row.get('Universe')
        if isinstance(universes, list):
            for u in universes:
                if u not in result[inst][region]['universes']:
                    result[inst][region]['universes'].append(u)
        elif isinstance(universes, str):
             if universes not in result[inst][region]['universes']:
                result[inst][region]['universes'].append(universes)

        neutralizations = row.get('Neutralization')
        if isinstance(neutralizations, list):
            for n in neutralizations:
                if n not in result[inst][region]['neutralizations']:
                    result[inst][region]['neutralizations'].append(n)
        elif isinstance(neutralizations, str):
            if neutralizations not in result[inst][region]['neutralizations']:
                result[inst][region]['neutralizations'].append(neutralizations)
        
    return result

def get_valid_simulation_options(session):
    """Fetch valid simulation options from BRAIN."""
    try:
        if get_instrument_type_region_delay:
            print("Fetching simulation options using ace_lib...")
            df = get_instrument_type_region_delay(session)
            return process_options_dataframe(df)
        else:
            print("ace_lib not available, skipping options fetch")
            return {}
    except Exception as e:
        print(f"Error fetching options: {e}")
        return {}

# --- Inspiration Master Routes ---

def get_active_session():
    """Helper to get active session from header or SingleSession"""
    # Check header first
    session_id = request.headers.get('Session-ID')
    if session_id and session_id in brain_sessions:
        return brain_sessions[session_id]['session']
    
    # Fallback to SingleSession
    script_dir = os.path.dirname(os.path.abspath(__file__))
    transformer_dir = os.path.join(script_dir, 'Tranformer')
    if transformer_dir not in sys.path:
        sys.path.append(transformer_dir)
    from ace_lib import SingleSession
    s = SingleSession()
    if hasattr(s, 'auth') and s.auth:
        return s
    return None

@app.route('/api/check_login', methods=['GET'])
def check_login():
    try:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if session_id and session_id in brain_sessions:
            info = brain_sessions[session_id]
            return jsonify({'logged_in': True, 'success': True, 'username': info.get('username', '')})
        s = get_active_session()
        if s:
             return jsonify({'logged_in': True, 'success': True})
        else:
             return jsonify({'logged_in': False, 'success': False})
    except Exception as e:
        print(f"Check login error: {e}")
        return jsonify({'logged_in': False, 'success': False})

@app.route('/api/inspiration/options', methods=['GET'])
def inspiration_options():
    try:
        # Use the same path logic as the main login
        script_dir = os.path.dirname(os.path.abspath(__file__))
        transformer_dir = os.path.join(script_dir, 'Tranformer')
        if transformer_dir not in sys.path:
            sys.path.append(transformer_dir)
            
        from ace_lib import get_instrument_type_region_delay
        
        s = get_active_session()
        if not s:
            return jsonify({'error': 'Not logged in'}), 401
            
        df = get_instrument_type_region_delay(s)
        
        result = {}
        for _, row in df.iterrows():
            inst = row['InstrumentType']
            region = row['Region']
            delay = row['Delay']
            univs = row['Universe']
            
            if inst not in result: result[inst] = {}
            if region not in result[inst]: 
                result[inst][region] = {"delays": [], "universes": []}
            
            if delay not in result[inst][region]['delays']:
                result[inst][region]['delays'].append(delay)
                
            if isinstance(univs, list):
                for u in univs:
                    if u not in result[inst][region]['universes']:
                        result[inst][region]['universes'].append(u)
            else:
                if univs not in result[inst][region]['universes']:
                    result[inst][region]['universes'].append(univs)
                    
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/inspiration/datasets', methods=['POST'])
def inspiration_datasets():
    data = request.json
    region = data.get('region')
    delay = data.get('delay')
    universe = data.get('universe')
    search = data.get('search', '')
    
    try:
        # Use the same path logic as the main login
        script_dir = os.path.dirname(os.path.abspath(__file__))
        transformer_dir = os.path.join(script_dir, 'Tranformer')
        if transformer_dir not in sys.path:
            sys.path.append(transformer_dir)
            
        from ace_lib import get_datasets
        
        s = get_active_session()
        if not s:
            return jsonify({'error': 'Not logged in'}), 401
            
        df = get_datasets(s, region=region, delay=int(delay), universe=universe)
        
        if search:
            search = search.lower()
            mask = (
                df['id'].str.lower().str.contains(search, na=False) |
                df['name'].str.lower().str.contains(search, na=False) |
                df['description'].str.lower().str.contains(search, na=False)
            )
            df = df[mask]
            
        # Return all results instead of limiting to 50
        # Use to_json to handle NaN values correctly (converts to null)
        json_str = df.to_json(orient='records', date_format='iso')
        return Response(json_str, mimetype='application/json')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/inspiration/test_llm', methods=['POST'])
def inspiration_test_llm():
    data = request.json or {}
    api_key = data.get('apiKey') or data.get('api_key')
    base_url = data.get('baseUrl') or data.get('base_url')
    model = data.get('model') or data.get('model_name')
    provider = data.get('provider') or data.get('modelProvider') or 'custom'
    
    try:
        from llm_providers import list_remote_models, select_model
        listed = list_remote_models(
            provider=str(provider or ('custom' if base_url else 'moonshot')),
            api_key=str(api_key or ''),
            base_url=str(base_url or ''),
        )
        selected = select_model(listed['models'], str(model or ''))
        return jsonify({
            'success': True,
            'ok': True,
            'provider': listed['provider'],
            'models': listed['models'],
            'model_catalog': listed['model_catalog'],
            'endpoint': listed['endpoint'],
            'count': listed['count'],
            'base_url': listed['base_url'],
            'selected': selected,
            'model': selected,
        })
    except Exception as e:
        # Fallback: openai SDK models.list / tiny completion
        try:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            try:
                client.models.list()
                return jsonify({'success': True, 'ok': True})
            except Exception:
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=1
                )
                return jsonify({'success': True, 'ok': True})
        except Exception as e2:
            return jsonify({'success': False, 'ok': False, 'error': str(e2) or str(e)})

@app.route('/api/inspiration/generate', methods=['POST'])
def inspiration_generate():
    data = request.json
    api_key = data.get('apiKey')
    base_url = data.get('baseUrl')
    model = data.get('model')
    region = data.get('region')
    delay = data.get('delay')
    universe = data.get('universe')
    dataset_id = data.get('datasetId')
    data_type = data.get('dataType') or 'MATRIX'
    
    try:
        import openai
        # Use the same path logic as the main login
        script_dir = os.path.dirname(os.path.abspath(__file__))
        transformer_dir = os.path.join(script_dir, 'Tranformer')
        if transformer_dir not in sys.path:
            sys.path.append(transformer_dir)
            
        from ace_lib import get_operators, get_datafields
        
        s = get_active_session()
        if not s:
            return jsonify({'error': 'Not logged in'}), 401
        
        if data_type not in ("MATRIX", "VECTOR"):
            data_type = "MATRIX"

        operators_df = get_operators(s)
        operators_df = operators_df[operators_df['scope'] == 'REGULAR']
        
        datafields_df = get_datafields(s, region=region, delay=int(delay), universe=universe, dataset_id=dataset_id, data_type=data_type)
        
        # count the datatype of the datafields_df, if most of them are VECTOR, then we keep the VECTOR category operators in the operators_df, otherwise we remove them
        datatype_counts = datafields_df['type'].value_counts().to_dict()
        vector_count = datatype_counts.get('VECTOR', 0)
        total_fields = sum(datatype_counts.values())
        if total_fields > 0 and vector_count > (total_fields / 2):
            # keep VECTOR operators
            pass
            print("Keeping VECTOR operators because majority of datafields are VECTOR type")
            operators_df = operators_df[operators_df['category'] != 'Vector']

        script_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(script_dir, "give_me_idea", "what_is_Alpha_template.md")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        except:
            system_prompt = "You are a helpful assistant for generating Alpha templates."
        
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        
        max_retries = 5
        n_ops = len(operators_df)
        n_fields = len(datafields_df)
        
        last_error = None
        
        for attempt in range(max_retries + 1):
            ops_subset = operators_df.head(n_ops)
            fields_subset = datafields_df.head(n_fields)
            
            # Render subsets as Markdown tables (with robust fallbacks)
            try:
                operators_info = ops_subset[['name', 'category', 'description']].to_markdown(index=False)
            except Exception:
                try:
                    from tabulate import tabulate
                    operators_info = tabulate(
                        ops_subset[['name', 'category', 'description']].fillna(''),
                        headers='keys',
                        tablefmt='github',
                        showindex=False
                    )
                except Exception:
                    operators_info = ops_subset[['name', 'category', 'description']].to_string(index=False)

            try:
                datafields_info = fields_subset[['id', 'description', 'subcategory']].to_markdown(index=False)
            except Exception:
                try:
                    from tabulate import tabulate
                    datafields_info = tabulate(
                        fields_subset[['id', 'description', 'subcategory']].fillna(''),
                        headers='keys',
                        tablefmt='github',
                        showindex=False
                    )
                except Exception:
                    datafields_info = fields_subset[['id', 'description', 'subcategory']].to_string(index=False)

            user_prompt = f"""
Here is the information about available operators (first {n_ops} rows):
{operators_info}

Here is the information about the dataset '{dataset_id}' (first {n_fields} rows):
{datafields_info}

Please come up with as much diverse Alpha templates as you can based on above information. And do remember to make some innovation of the templates.
Answer in Chinese.
"""
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=1,
                )
                return jsonify({'result': completion.choices[0].message.content})
                
            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                if "token limit" in error_msg or "context_length_exceeded" in error_msg or "400" in error_msg:
                    n_ops = max(1, n_ops // 2)
                    n_fields = max(1, n_fields // 2)
                    if n_ops == 1 and n_fields == 1:
                        break
                else:
                    break
        
        return jsonify({'error': f"Failed after retries. Last error: {last_error}"})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _safe_dataset_id(dataset_id: str) -> str:
    return "".join([c for c in str(dataset_id) if c.isalnum() or c in ("-", "_")])


def _get_pipeline_paths(dataset_id: str, region: str, delay: int):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    trail_dir = os.path.join(script_dir, 'trailSomeAlphas')
    run_pipeline_path = os.path.join(trail_dir, 'run_pipeline.py')
    data_dir = os.path.join(trail_dir, 'skills', 'brain-feature-implementation', 'data')
    dataset_folder = f"{_safe_dataset_id(dataset_id)}_{region}_delay{delay}"
    output_folder = os.path.join(data_dir, dataset_folder)
    return run_pipeline_path, trail_dir, output_folder, dataset_folder


@app.route('/api/inspiration/run-pipeline', methods=['POST'])
def inspiration_run_pipeline():
    try:
        data = request.get_json() or {}
        dataset_id = data.get('datasetId')
        data_category = data.get('dataCategory')
        region = data.get('region')
        delay = data.get('delay')
        universe = data.get('universe')
        data_type = data.get('dataType') or 'MATRIX'
        api_key = data.get('apiKey')
        base_url = data.get('baseUrl')
        model = data.get('model')

        if not dataset_id or not data_category or not region or delay is None or not universe:
            return jsonify({'success': False, 'error': 'Missing required parameters'}), 400

        run_pipeline_path, trail_dir, output_folder, dataset_folder = _get_pipeline_paths(dataset_id, region, int(delay))
        if not os.path.exists(run_pipeline_path):
            return jsonify({'success': False, 'error': f'run_pipeline.py not found: {run_pipeline_path}'}), 404

        task_id = str(uuid.uuid4())
        log_queue = queue.Queue()
        inspiration_pipeline_tasks[task_id] = {
            'queue': log_queue,
            'status': 'running',
            'output_folder': output_folder,
            'dataset_folder': dataset_folder
        }

        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        session_info = brain_sessions.get(session_id) if session_id else None

        def run_process():
            try:
                if data_type not in ("MATRIX", "VECTOR"):
                    dt = "MATRIX"
                else:
                    dt = str(data_type)

                cmd = [
                    sys.executable,
                    run_pipeline_path,
                    '--data-category', str(data_category),
                    '--region', str(region),
                    '--delay', str(delay),
                    '--dataset-id', str(dataset_id),
                    '--universe', str(universe),
                    '--data-type', dt,
                ]

                if api_key:
                    cmd.extend(['--moonshot-api-key', str(api_key)])
                if model:
                    cmd.extend(['--moonshot-model', str(model)])

                env = os.environ.copy()
                if api_key:
                    env['MOONSHOT_API_KEY'] = str(api_key)
                if base_url:
                    env['MOONSHOT_BASE_URL'] = str(base_url)
                if model:
                    env['MOONSHOT_MODEL'] = str(model)
                if session_info and session_info.get('username') and session_info.get('password'):
                    env['BRAIN_USERNAME'] = session_info['username']
                    env['BRAIN_PASSWORD'] = session_info['password']

                proc = subprocess.Popen(
                    cmd,
                    cwd=trail_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1,
                    env=env
                )

                if proc.stdout:
                    for line in proc.stdout:
                        log_queue.put(line.rstrip('\n'))

                exit_code = proc.wait()
                success = exit_code == 0
                inspiration_pipeline_tasks[task_id]['status'] = 'completed' if success else 'failed'
                log_queue.put({
                    '__event__': 'done',
                    'success': success,
                    'exit_code': exit_code,
                    'dataset_folder': dataset_folder
                })
            except Exception as e:
                inspiration_pipeline_tasks[task_id]['status'] = 'failed'
                log_queue.put({
                    '__event__': 'done',
                    'success': False,
                    'error': str(e),
                    'dataset_folder': dataset_folder
                })

        thread = threading.Thread(target=run_process)
        thread.daemon = True
        thread.start()

        return jsonify({'success': True, 'taskId': task_id})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/inspiration/stream-pipeline/<task_id>')
def inspiration_stream_pipeline(task_id):
    task = inspiration_pipeline_tasks.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Task not found'}), 404

    def generate():
        q = task['queue']
        while True:
            item = q.get()
            if isinstance(item, dict) and item.get('__event__') == 'done':
                yield f"event: done\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                break

            payload = {'line': item}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/api/inspiration/download-pipeline/<task_id>')
def inspiration_download_pipeline(task_id):
    task = inspiration_pipeline_tasks.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Task not found'}), 404

    output_folder = task.get('output_folder')
    if not output_folder or not os.path.isdir(output_folder):
        return jsonify({'success': False, 'error': 'Output folder not found'}), 404

    temp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    temp.close()

    with zipfile.ZipFile(temp.name, 'w', zipfile.ZIP_DEFLATED) as zf:
        base_name = os.path.basename(output_folder.rstrip(os.sep))
        for root, _, files in os.walk(output_folder):
            for filename in files:
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, output_folder)
                arcname = os.path.join(base_name, rel_path)
                zf.write(abs_path, arcname=arcname)

    @after_this_request
    def _cleanup_zip(response):
        try:
            os.remove(temp.name)
        except Exception:
            pass
        return response

    download_name = f"{os.path.basename(output_folder)}.zip"
    return send_file(temp.name, as_attachment=True, download_name=download_name)


@app.route('/api/inspiration/enhance-template', methods=['POST'])
def inspiration_enhance_template():
    try:
        idea_files = request.files.getlist('ideaFiles')
        api_key = request.form.get('apiKey')
        base_url = request.form.get('baseUrl')
        model = request.form.get('model')
        data_type = request.form.get('dataType') or 'MATRIX'
        universe = (request.form.get('universe') or 'TOP3000').strip().upper()

        def _is_valid_idea_filename(filename: str) -> bool:
            # Expected: <dataset_id>_<region>_<delay>_idea_<timestamp>.json
            # (same parsing rule used by trailSomeAlphas/enhance_template.py)
            name = (filename or '').strip()
            if not name:
                return False
            parts = name.split('_')
            if len(parts) < 5:
                return False
            if parts[-2] != 'idea':
                return False
            if not (parts[-3] or '').isdigit():
                return False
            if not parts[-4]:
                return False
            dataset_id = '_'.join(parts[:-4])
            return bool(dataset_id)

        def _normalize_manual_token(value: str) -> str:
            # Keep it simple: alnum + underscore only, so parsing is stable.
            v = (value or '').strip()
            v = re.sub(r'[^A-Za-z0-9_]+', '_', v)
            v = re.sub(r'_+', '_', v).strip('_')
            return v

        def _build_manual_idea_file(task_root: str, template_override: str | None = None, idea_override: str | None = None) -> tuple[str, str]:
            dataset_id = _normalize_manual_token(request.form.get('datasetId') or '').lower()
            region = _normalize_manual_token(request.form.get('region') or '').upper()
            delay_raw = (request.form.get('delay') or '').strip()
            template = (template_override if template_override is not None else (request.form.get('template') or '')).strip()
            idea = (idea_override if idea_override is not None else (request.form.get('idea') or '')).strip()

            if not dataset_id or not region or not delay_raw or not template:
                raise ValueError('Missing datasetId/region/delay/template for manual enhance')

            # Manual datasetId must contain both letters and digits, e.g. fundamental3
            if not re.search(r"[a-zA-Z]", dataset_id) or not re.search(r"\d", dataset_id):
                raise ValueError('datasetId must contain both letters and digits (e.g., fundamental3)')

            if not delay_raw.isdigit():
                raise ValueError('delay must be an integer')
            delay = int(delay_raw)
            if delay < 0 or delay > 10:
                raise ValueError('delay out of reasonable range')

            name = f"{dataset_id}_{region}_{delay}_idea_{time.time_ns()}.json"
            name = secure_filename(name) or f"manual_{time.time_ns()}.json"

            file_dir = os.path.join(task_root, '01_manual')
            os.makedirs(file_dir, exist_ok=True)
            idea_path = os.path.join(file_dir, name)
            with open(idea_path, 'w', encoding='utf-8') as f:
                json.dump({'template': template, 'idea': idea}, f, ensure_ascii=False, indent=2)
            return name, idea_path

        def _extract_template_idea_from_upload(file_storage) -> tuple[str, str]:
            try:
                raw = file_storage.read()
                if isinstance(raw, bytes):
                    text = raw.decode('utf-8', errors='replace')
                else:
                    text = str(raw)
                payload = json.loads(text)
            except Exception as e:
                raise ValueError(f"Invalid idea JSON content: {e}")
            if not isinstance(payload, dict):
                raise ValueError("idea json must be an object")
            if 'template' not in payload or 'idea' not in payload:
                raise ValueError("idea json must contain 'template' and 'idea'")
            template = str(payload.get('template') or '').strip()
            idea = str(payload.get('idea') or '').strip()
            if not template:
                raise ValueError("idea json field 'template' is empty")
            return template, idea

        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        session_info = brain_sessions.get(session_id) if session_id else None

        if data_type not in ("MATRIX", "VECTOR"):
            data_type = "MATRIX"

        if not api_key:
            return jsonify({'success': False, 'error': 'Missing apiKey'}), 400

        script_dir = os.path.dirname(os.path.abspath(__file__))
        trail_dir = os.path.join(script_dir, 'trailSomeAlphas')
        enhance_script = os.path.join(trail_dir, 'enhance_template.py')
        if not os.path.exists(enhance_script):
            return jsonify({'success': False, 'error': f'enhance_template.py not found: {enhance_script}'}), 404

        task_id = str(uuid.uuid4())
        log_queue = queue.Queue()
        task_root = tempfile.mkdtemp(prefix='enhance_batch_')

        saved_files = []

        if idea_files:
            for idx, idea_file in enumerate(idea_files, start=1):
                name = secure_filename(idea_file.filename or f'idea_{idx}.json')
                if _is_valid_idea_filename(name):
                    file_dir = os.path.join(task_root, f"{idx:02d}_{os.path.splitext(name)[0]}")
                    os.makedirs(file_dir, exist_ok=True)
                    idea_path = os.path.join(file_dir, name)
                    idea_file.save(idea_path)
                    saved_files.append((name, idea_path))
                else:
                    # Treat invalid filenames as manual-mode inputs: require datasetId/region/delay,
                    # and take template/idea from either the uploaded JSON content or the manual form fields.
                    try:
                        up_template, up_idea = _extract_template_idea_from_upload(idea_file)
                        name2, idea_path2 = _build_manual_idea_file(task_root, template_override=up_template, idea_override=up_idea)
                        saved_files.append((name2, idea_path2))
                    except Exception as e:
                        return jsonify({
                            'success': False,
                            'errorCode': 'NEED_MANUAL_INPUT',
                            'error': f"上传的 idea JSON 文件名不合规，且无法自动转换为手动模式：{e}"
                        }), 400
        else:
            # Manual mode: user supplies datasetId/region/delay/template/idea
            try:
                name, idea_path = _build_manual_idea_file(task_root)
            except Exception as e:
                return jsonify({
                    'success': False,
                    'errorCode': 'NEED_MANUAL_INPUT',
                    'error': str(e)
                }), 400
            saved_files.append((name, idea_path))

        if not saved_files:
            return jsonify({
                'success': False,
                'errorCode': 'NEED_MANUAL_INPUT',
                'error': 'No valid idea files provided. Please upload a valid idea JSON or use manual input.'
            }), 400

        inspiration_enhance_tasks[task_id] = {
            'queue': log_queue,
            'status': 'running',
            'task_root': task_root,
            'saved_files': saved_files,
            'is_cross_task': False
        }

        def run_process():
            try:
                total = len(saved_files)
                completed_ok = True

                for idx, (name, idea_path) in enumerate(saved_files, start=1):
                    env = os.environ.copy()
                    env['IDEA_JSON'] = idea_path
                    env['MOONSHOT_API_KEY'] = api_key
                    env['DATA_TYPE'] = str(data_type)
                    env['UNIVERSE'] = universe
                    if base_url:
                        env['MOONSHOT_BASE_URL'] = base_url
                    if model:
                        env['MOONSHOT_MODEL'] = model
                    env['PYTHONIOENCODING'] = 'utf-8'

                    # Inherit BRAIN auth from the logged-in web session (same as run-pipeline).
                    # Do NOT accept raw credentials from the enhance form.
                    if session_info and session_info.get('username') and session_info.get('password'):
                        env['BRAIN_USERNAME'] = session_info['username']
                        env['BRAIN_PASSWORD'] = session_info['password']

                    log_queue.put(f"=== 开始处理 {name} ({idx}/{total}) ===")
                    proc = subprocess.Popen(
                        [sys.executable, enhance_script],
                        cwd=trail_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        bufsize=1,
                        env=env
                    )

                    if proc.stdout:
                        for line in proc.stdout:
                            log_queue.put({'line': line.rstrip('\n'), 'file': name})

                    exit_code = proc.wait()
                    success = exit_code == 0
                    if not success:
                        completed_ok = False
                    log_queue.put({'__event__': 'file_done', 'type': 'file_done', 'file': name, 'success': success})

                inspiration_enhance_tasks[task_id]['status'] = 'completed' if completed_ok else 'failed'
                log_queue.put({
                    '__event__': 'done',
                    'success': completed_ok,
                    'total': total
                })
            except Exception as e:
                inspiration_enhance_tasks[task_id]['status'] = 'failed'
                log_queue.put({
                    '__event__': 'done',
                    'success': False,
                    'error': str(e)
                })

        thread = threading.Thread(target=run_process)
        thread.daemon = True
        thread.start()

        return jsonify({'success': True, 'taskId': task_id})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/inspiration/cross-enhance-template', methods=['POST'])
def inspiration_cross_enhance_template():
    try:
        idea_files = request.files.getlist('ideaFiles')
        api_key = request.form.get('apiKey')
        base_url = request.form.get('baseUrl')
        model = request.form.get('model')
        data_type = request.form.get('dataType') or 'MATRIX'
        cross_style = (request.form.get('crossStyle') or 'balanced').strip().lower()
        universe = (request.form.get('universe') or 'TOP3000').strip().upper()

        def _is_valid_idea_filename(filename: str) -> bool:
            name = (filename or '').strip()
            if not name:
                return False
            parts = name.split('_')
            if len(parts) < 5:
                return False
            if parts[-2] != 'idea':
                return False
            if not (parts[-3] or '').isdigit():
                return False
            if not parts[-4]:
                return False
            dataset_id = '_'.join(parts[:-4])
            return bool(dataset_id)

        def _parse_meta_from_filename(filename: str):
            parts = (filename or '').split('_')
            if len(parts) < 5:
                return None
            if parts[-2] != 'idea':
                return None
            delay = parts[-3]
            region = parts[-4]
            if not delay.isdigit() or not region:
                return None
            dataset_id = '_'.join(parts[:-4])
            if not dataset_id:
                return None
            return dataset_id, region, int(delay)

        def _normalize_manual_token(value: str) -> str:
            v = (value or '').strip()
            v = re.sub(r'[^A-Za-z0-9_]+', '_', v)
            v = re.sub(r'_+', '_', v).strip('_')
            return v

        def _build_manual_cross_idea_files(task_root: str) -> tuple[list[tuple[str, str]], list[tuple[str, str, int]]]:
            dataset_id = _normalize_manual_token(request.form.get('datasetId') or '').lower()
            region = _normalize_manual_token(request.form.get('region') or '').upper()
            delay_raw = (request.form.get('delay') or '').strip()

            template1 = str(request.form.get('template') or '').strip()
            idea1 = str(request.form.get('idea') or '').strip()
            manual_templates_raw = request.form.get('manualTemplates')

            if not dataset_id or not region or not delay_raw:
                raise ValueError('Missing datasetId/region/delay for cross manual enhance')
            if not re.search(r"[a-zA-Z]", dataset_id) or not re.search(r"\d", dataset_id):
                raise ValueError('datasetId must contain both letters and digits (e.g., fundamental3)')
            if not delay_raw.isdigit():
                raise ValueError('delay must be an integer')

            delay = int(delay_raw)
            if delay < 0 or delay > 10:
                raise ValueError('delay out of reasonable range')

            items = []
            if manual_templates_raw:
                try:
                    parsed = json.loads(manual_templates_raw)
                except Exception as e:
                    raise ValueError(f'invalid manualTemplates JSON: {e}')
                if not isinstance(parsed, list):
                    raise ValueError('manualTemplates must be a JSON array')
                for row in parsed:
                    if not isinstance(row, dict):
                        continue
                    items.append({
                        'template': str(row.get('template') or '').strip(),
                        'idea': str(row.get('idea') or '').strip(),
                    })
            else:
                items = [
                    {'template': template1, 'idea': idea1},
                    {
                        'template': str(request.form.get('template2') or '').strip(),
                        'idea': str(request.form.get('idea2') or '').strip(),
                    },
                ]

            if not items:
                items = [{'template': template1, 'idea': idea1}]
            items = [x for x in items if str(x.get('template') or '').strip()]
            if len(items) < 2:
                raise ValueError('cross manual enhance requires at least 2 templates')

            saved = []
            metas_local = []
            ts_seed = time.time_ns()
            for idx, item in enumerate(items, start=1):
                name = f"{dataset_id}_{region}_{delay}_idea_{ts_seed + idx}.json"
                name = secure_filename(name) or f"manual_cross_{ts_seed + idx}.json"
                file_dir = os.path.join(task_root, f"{idx:02d}_manual")
                os.makedirs(file_dir, exist_ok=True)
                idea_path = os.path.join(file_dir, name)
                with open(idea_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        {
                            'template': str(item.get('template') or '').strip(),
                            'idea': str(item.get('idea') or '').strip(),
                        },
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
                saved.append((name, idea_path))
                metas_local.append((dataset_id, region, delay))

            return saved, metas_local

        if not api_key:
            return jsonify({'success': False, 'error': 'Missing apiKey'}), 400

        if data_type not in ("MATRIX", "VECTOR"):
            data_type = "MATRIX"

        script_dir = os.path.dirname(os.path.abspath(__file__))
        trail_dir = os.path.join(script_dir, 'trailSomeAlphas')
        enhance_script = os.path.join(trail_dir, 'enhance_template.py')
        if not os.path.exists(enhance_script):
            return jsonify({'success': False, 'error': f'enhance_template.py not found: {enhance_script}'}), 404

        task_id = str(uuid.uuid4())
        log_queue = queue.Queue()
        task_root = tempfile.mkdtemp(prefix='enhance_cross_')

        saved_files = []
        metas = []

        if idea_files:
            if len(idea_files) < 2:
                return jsonify({'success': False, 'error': 'Cross enhance requires at least 2 idea JSON files'}), 400

            for idx, idea_file in enumerate(idea_files, start=1):
                name = secure_filename(idea_file.filename or f'idea_{idx}.json')
                if not _is_valid_idea_filename(name):
                    return jsonify({
                        'success': False,
                        'error': f'Cross mode requires valid idea filename: {name}. Expected <dataset>_<region>_<delay>_idea_<ts>.json'
                    }), 400
                meta = _parse_meta_from_filename(name)
                if not meta:
                    return jsonify({'success': False, 'error': f'Invalid idea filename metadata: {name}'}), 400
                metas.append(meta)

                file_dir = os.path.join(task_root, f"{idx:02d}_{os.path.splitext(name)[0]}")
                os.makedirs(file_dir, exist_ok=True)
                idea_path = os.path.join(file_dir, name)
                idea_file.save(idea_path)

                # Input structure validation: each idea json must include template and idea.
                try:
                    with open(idea_path, 'r', encoding='utf-8') as f:
                        payload = json.load(f)
                    if not isinstance(payload, dict):
                        return jsonify({'success': False, 'error': f'Invalid JSON object in file: {name}'}), 400
                    if 'template' not in payload or 'idea' not in payload:
                        return jsonify({'success': False, 'error': f'File missing required keys template/idea: {name}'}), 400
                except Exception as e:
                    return jsonify({'success': False, 'error': f'Invalid JSON file {name}: {str(e)}'}), 400

                saved_files.append((name, idea_path))
        else:
            try:
                saved_files, metas = _build_manual_cross_idea_files(task_root)
            except Exception as e:
                return jsonify({'success': False, 'errorCode': 'NEED_MANUAL_INPUT', 'error': str(e)}), 400

        if len(saved_files) < 2:
            return jsonify({'success': False, 'error': 'Cross enhance requires at least 2 idea inputs'}), 400

        if len(set(metas)) != 1:
            return jsonify({'success': False, 'error': 'Cross mode requires all idea files to share same dataset/region/delay'}), 400

        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        session_info = brain_sessions.get(session_id) if session_id else None

        inspiration_enhance_tasks[task_id] = {
            'queue': log_queue,
            'status': 'running',
            'task_root': task_root,
            'saved_files': saved_files,
            'is_cross_task': True
        }

        def run_process():
            try:
                env = os.environ.copy()
                env['IDEA_JSON_LIST'] = json.dumps([p for _, p in saved_files], ensure_ascii=False)
                env['MOONSHOT_API_KEY'] = api_key
                env['DATA_TYPE'] = str(data_type)
                env['UNIVERSE'] = universe
                env['CROSS_PROMPT_STYLE'] = cross_style or 'balanced'
                env['PYTHONIOENCODING'] = 'utf-8'

                if base_url:
                    env['MOONSHOT_BASE_URL'] = base_url
                if model:
                    env['MOONSHOT_MODEL'] = model

                if session_info and session_info.get('username') and session_info.get('password'):
                    env['BRAIN_USERNAME'] = session_info['username']
                    env['BRAIN_PASSWORD'] = session_info['password']

                log_queue.put(f"=== 开始 Cross 增强: {len(saved_files)} 个 idea 文件 ===")
                proc = subprocess.Popen(
                    [sys.executable, enhance_script],
                    cwd=trail_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=1,
                    env=env
                )

                if proc.stdout:
                    for line in proc.stdout:
                        log_queue.put({'line': line.rstrip('\n'), 'file': 'cross_batch'})

                exit_code = proc.wait()
                success = exit_code == 0
                inspiration_enhance_tasks[task_id]['status'] = 'completed' if success else 'failed'
                log_queue.put({'__event__': 'file_done', 'type': 'file_done', 'file': 'cross_batch', 'success': success})
                log_queue.put({'__event__': 'done', 'success': success, 'total': 1})
            except Exception as e:
                inspiration_enhance_tasks[task_id]['status'] = 'failed'
                log_queue.put({'__event__': 'done', 'success': False, 'error': str(e)})

        thread = threading.Thread(target=run_process)
        thread.daemon = True
        thread.start()

        return jsonify({'success': True, 'taskId': task_id})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/inspiration/stream-enhance/<task_id>')
def inspiration_stream_enhance(task_id):
    task = inspiration_enhance_tasks.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Task not found'}), 404

    def generate():
        q = task['queue']
        while True:
            item = q.get()
            if isinstance(item, dict) and item.get('__event__') == 'done':
                yield f"event: done\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                break

            if isinstance(item, dict) and item.get('__event__') == 'file_done':
                payload = {'type': 'file_done', 'file': item.get('file'), 'success': item.get('success')}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                continue

            if isinstance(item, dict):
                payload = item
            else:
                payload = {'line': item}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/api/inspiration/download-enhance/<task_id>')
def inspiration_download_enhance(task_id):
    task = inspiration_enhance_tasks.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Task not found'}), 404

    task_root = task.get('task_root')
    if not task_root or not os.path.isdir(task_root):
        return jsonify({'success': False, 'error': 'Task output not found'}), 404

    saved_files = task.get('saved_files') or []
    is_cross_task = bool(task.get('is_cross_task'))

    temp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    temp.close()

    with zipfile.ZipFile(temp.name, 'w', zipfile.ZIP_DEFLATED) as zf:
        base_name = os.path.basename(task_root.rstrip(os.sep))
        if is_cross_task:
            # Cross mode: package final outputs + selected original idea jsons in a flat zip layout.
            output_prefixes = (
                'enhanced_templates_',
                'enhanced_final_expressions_',
            )
            output_files = []
            for root, _, files in os.walk(task_root):
                for filename in files:
                    if filename.startswith(output_prefixes):
                        output_files.append(os.path.join(root, filename))

            if not output_files:
                zf.close()
                try:
                    os.remove(temp.name)
                except Exception:
                    pass
                return jsonify({
                    'success': False,
                    'error': 'Cross output files not found. Please wait for task completion and retry download.'
                }), 404

            used_names = set()
            for idx, item in enumerate(saved_files, start=1):
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                original_name = os.path.basename(str(item[0] or f'idea_{idx}.json'))
                original_path = str(item[1] or '')
                if not original_path or not os.path.isfile(original_path):
                    continue

                # Keep zip flat and avoid collisions for duplicate filenames.
                arcname = f"input_{idx:02d}_{original_name}"
                if arcname in used_names:
                    arcname = f"input_{idx:02d}_{int(time.time())}_{original_name}"
                used_names.add(arcname)
                zf.write(original_path, arcname=arcname)

            for abs_path in output_files:
                arcname = os.path.basename(abs_path)
                if arcname in used_names:
                    arcname = f"output_{int(time.time())}_{arcname}"
                used_names.add(arcname)
                zf.write(abs_path, arcname=arcname)
        else:
            for root, _, files in os.walk(task_root):
                for filename in files:
                    abs_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(abs_path, task_root)
                    arcname = os.path.join(base_name, rel_path)
                    zf.write(abs_path, arcname=arcname)

    @after_this_request
    def _cleanup_zip(response):
        try:
            os.remove(temp.name)
        except Exception:
            pass
        return response

    download_name = f"{os.path.basename(task_root)}.zip"
    return send_file(temp.name, as_attachment=True, download_name=download_name)


# --------------------------------------------------------------------
# Pipeline API (autopilot alpha pipeline)
# --------------------------------------------------------------------

try:
    _orchestrator_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'brain-orchestrator')
    if _orchestrator_dir not in sys.path:
        sys.path.insert(0, _orchestrator_dir)
    from pipeline_runner import (
        create_pipeline as _create_pipeline,
        get_pipeline as _get_pipeline,
        list_pipelines as _list_pipelines,
        load_existing_pipelines as _load_existing_pipelines,
        global_worker_usage as _global_worker_usage,
        GLOBAL_WORKER_LIMIT as _GLOBAL_WORKER_LIMIT,
        delete_pipeline as _delete_pipeline,
        archive_pipeline as _archive_pipeline,
        restore_pipeline as _restore_pipeline,
        list_archived as _list_archived,
    )
    _load_existing_pipelines()
    print("🚀 Pipeline runner loaded!")
    _pipeline_available = True
except Exception as _pipe_err:
    print(f"⚠️  Pipeline runner not available: {_pipe_err}")
    _pipeline_available = False


def _alpha_judge_root() -> Path:
    return Path(os.path.dirname(os.path.abspath(__file__))) / 'brain-alpha-judge'


def _get_active_brain_credentials():
    session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
    if not session_id or session_id not in brain_sessions:
        return None, None

    session_info = brain_sessions.get(session_id, {})
    username = str(session_info.get('username', '') or '').strip()
    password = str(session_info.get('password', '') or '').strip()
    if not username or not password:
        return None, None
    return username, password


def _extract_cli_json(stdout_text: str):
    text = str(stdout_text or '').strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.rfind('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


def _to_chat_completions_url(base_url: str) -> str:
    url = str(base_url or '').strip()
    if not url:
        return 'https://api.moonshot.cn/v1/chat/completions'
    if url.endswith('/chat/completions'):
        return url
    return url.rstrip('/') + '/chat/completions'


def _normalize_llm_model(model: str) -> str:
    text = str(model or '').strip()
    if not text:
        return 'kimi-latest'
    lowered = text.lower().replace('_', '-').replace(' ', '')
    alias = {
        'kimi-2.5': 'kimi-k2.6',
        'kimi2.5': 'kimi-k2.6',
        'kimi-k2.6': 'kimi-k2.6',
        'kimi-latest': 'kimi-latest',
    }
    return alias.get(lowered, text)


def _resolve_alpha_judge_llm_settings(body: dict, username: str):
    body = body or {}

    api_key = _pick_first_non_empty(
        body,
        ['llm_api_key', 'moonshot_api_key', 'apiKey', 'api_key', 'LLM_API_KEY'],
    )
    base_url = _pick_first_non_empty(
        body,
        ['llm_base_url', 'moonshot_base_url', 'baseUrl', 'base_url', 'LLM_BASE_URL'],
        'https://api.moonshot.cn/v1',
    )
    model = _pick_first_non_empty(
        body,
        ['llm_model', 'moonshot_model', 'model', 'LLM_model_name', 'LLM_MODEL_NAME'],
        'kimi-latest',
    )

    if api_key:
        return {
            'api_key': api_key,
            'base_url': base_url,
            'model': _normalize_llm_model(model),
            'source': 'request',
        }

    # 1. Fallback to existing config.json in brain-alpha-judge
    root = _alpha_judge_root()
    cfg_path = root / 'configs' / 'config.json'
    try:
        if cfg_path.exists():
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            stored_user = cfg.get('username')
            if stored_user and stored_user == username:
                llm_cfg = cfg.get('judge', {}).get('llm', {})
                stored_key = str(llm_cfg.get('api_key', '') or '').strip()
                if stored_key:
                    return {
                        'api_key': stored_key,
                        'base_url': str(llm_cfg.get('api_url', '') or '').strip().replace('/chat/completions', '') or 'https://api.moonshot.cn/v1',
                        'model': _normalize_llm_model(str(llm_cfg.get('model', '') or '')),
                        'source': 'local_config',
                    }
    except Exception:
        pass

    # 2. Reuse pre-stored LLM settings from existing pipeline configs.
    if _pipeline_available:
        preferred = None
        try:
            for item in _list_pipelines():
                pipeline_id = item.get('pipeline_id') if isinstance(item, dict) else None
                if not pipeline_id:
                    continue
                runner = _get_pipeline(pipeline_id)
                if not runner:
                    continue
                cfg = runner.config if isinstance(runner.config, dict) else {}
                key = str(cfg.get('moonshot_api_key', '') or '').strip()
                if not key:
                    continue
                cand = {
                    'api_key': key,
                    'base_url': str(cfg.get('moonshot_base_url', '') or '').strip() or 'https://api.moonshot.cn/v1',
                    'model': _normalize_llm_model(
                        str(cfg.get('moonshot_model', '') or '').strip()
                        or str(cfg.get('LLM_model_name', '') or '').strip()
                        or 'kimi-latest'
                    ),
                    'source': f'pipeline:{pipeline_id}',
                }
                pipeline_user = str(cfg.get('brain_username', '') or '').strip()
                if username and pipeline_user and pipeline_user == username:
                    preferred = cand
                    break
        except Exception:
            preferred = None

        if preferred:
            return preferred

    return None


def _write_alpha_judge_config(root: Path, username: str, password: str, llm_settings: dict):
    cfg_path = root / 'configs' / 'config.json'
    cfg = {}
    try:
        if cfg_path.exists():
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
    except Exception:
        cfg = {}

    if not isinstance(cfg, dict):
        cfg = {}

    cfg['username'] = username
    cfg['password'] = password
    cfg.setdefault('BRAIN_API_URL', 'https://api.worldquantbrain.com')
    cfg.setdefault('BRAIN_URL', 'https://platform.worldquantbrain.com')

    judge = cfg.get('judge')
    if not isinstance(judge, dict):
        judge = {}
        cfg['judge'] = judge

    trend = judge.get('value_factor_trend')
    if not isinstance(trend, dict):
        judge['value_factor_trend'] = {'enabled': True, 'window_days': 365}

    llm_cfg = judge.get('llm')
    if not isinstance(llm_cfg, dict):
        llm_cfg = {}
        judge['llm'] = llm_cfg

    llm_api_key = str(llm_settings.get('api_key', '') or '')
    if llm_api_key == password:
        llm_api_key = ''

    llm_cfg['enabled'] = True
    llm_cfg['language'] = str(llm_cfg.get('language', 'zh-CN') or 'zh-CN')
    llm_cfg['provider'] = 'openai-compatible'
    llm_cfg['model'] = _normalize_llm_model(str(llm_settings.get('model', '') or 'kimi-latest'))
    llm_cfg['api_url'] = _to_chat_completions_url(llm_settings.get('base_url', ''))
    llm_cfg['api_key'] = llm_api_key
    llm_cfg['timeout_seconds'] = int(llm_cfg.get('timeout_seconds', 300) or 300)

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


@app.route('/pipeline-dashboard')
def pipeline_dashboard():
    """流水线控制面板"""
    return render_template('pipeline_dashboard.html')


@app.route('/alpha-judge')
def alpha_judge_dashboard():
    """Alpha判官页面"""
    return render_template('alpha_judge.html')


@app.route('/api/alpha-judge/run', methods=['POST'])
def api_alpha_judge_run():
    root = _alpha_judge_root()
    script_path = root / 'scripts' / 'judge_alpha.py'
    if not script_path.exists():
        return jsonify({'ok': False, 'error': 'Alpha judge module not found in APP/brain-alpha-judge.'}), 404

    username, password = _get_active_brain_credentials()
    if not username or not password:
        return jsonify({'ok': False, 'error': '请先在主页连接到 BRAIN，再使用 Alpha判官。'}), 401

    body = request.get_json(silent=True) or {}
    alpha_id = str(body.get('alpha_id', '') or '').strip()
    if not alpha_id:
        return jsonify({'ok': False, 'error': 'alpha_id 不能为空。'}), 400
    trend_start_date = str(body.get('trend_start_date', '') or '').strip()
    trend_end_date = str(body.get('trend_end_date', '') or '').strip()
    trend_window_days = body.get('trend_window_days', None)
    llm_settings = _resolve_alpha_judge_llm_settings(body, username)
    if not llm_settings:
        return jsonify({
            'ok': False,
            'errorCode': 'NEED_LLM_INPUT',
            'error': '未找到可用的 LLM 配置。请输入 LLM API Key（可选 Base URL / Model）后重试。',
        }), 400

    try:
        _sync_ace_persisted_credentials(username, password)
        _write_alpha_judge_config(root, username, password, llm_settings)
    except Exception:
        pass

    command = [sys.executable, str(script_path), '--alpha-id', alpha_id]
    if trend_start_date:
        command.extend(['--trend-start-date', trend_start_date])
    if trend_end_date:
        command.extend(['--trend-end-date', trend_end_date])
    if trend_window_days is not None:
        try:
            command.extend(['--trend-window-days', str(int(trend_window_days))])
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'trend_window_days 必须是整数。'}), 400

    env = os.environ.copy()
    env['BRAIN_USERNAME'] = username
    env['BRAIN_PASSWORD'] = password
    env['BRAIN_JUDGE_LLM_API_KEY'] = str(llm_settings.get('api_key', '') or '')

    try:
        result = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': '运行超时，请稍后重试。'}), 504
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'运行 Alpha判官失败: {exc}'}), 500

    output = _extract_cli_json(result.stdout)
    if result.returncode != 0:
        return jsonify({
            'ok': False,
            'error': 'Alpha判官执行失败。',
            'return_code': result.returncode,
            'stderr': (result.stderr or '').strip(),
            'stdout': (result.stdout or '').strip(),
        }), 500

    json_path = output.get('json') if isinstance(output, dict) else ''
    markdown_path = output.get('markdown') if isinstance(output, dict) else ''
    report = []
    if json_path and os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                report = json.load(f)
        except Exception:
            report = []

    # If LLM decision is unavailable because preset key is missing/unauthorized,
    # ask frontend to collect manual LLM input and retry.
    first_report = report[0] if isinstance(report, list) and report else {}
    llm_decision = first_report.get('llm_decision', {}) if isinstance(first_report, dict) else {}
    llm_available = bool(llm_decision.get('available')) if isinstance(llm_decision, dict) else False
    llm_reason = str(llm_decision.get('reason', '') or '') if isinstance(llm_decision, dict) else ''
    llm_reason_lower = llm_reason.lower()
    provided_llm_key = bool(_pick_first_non_empty(
        body,
        ['llm_api_key', 'moonshot_api_key', 'apiKey', 'api_key', 'LLM_API_KEY'],
    ))
    llm_needs_input = (
        (not llm_available)
        and (
            ('missing_api_key' in llm_reason_lower)
            or ('unauthorized' in llm_reason_lower)
            or ('401' in llm_reason_lower)
            or ('404' in llm_reason_lower)
            or ('not found' in llm_reason_lower)
        )
    )
    if llm_needs_input:
        msg = 'LLM 裁决鉴权失败，请输入可用的 LLM API Key 后重试。'
        if not provided_llm_key:
            msg = '未找到可用的预存 LLM 配置，请输入 LLM API Key（可选 Base URL / Model）后重试。'
        return jsonify({
            'ok': False,
            'errorCode': 'NEED_LLM_INPUT',
            'error': msg,
            'llm_reason': llm_reason,
        }), 400

    return jsonify({
        'ok': True,
        'meta': output if isinstance(output, dict) else {},
        'report': report,
        'json_path': json_path,
        'markdown_path': markdown_path,
        'stdout': (result.stdout or '').strip(),
    })


@app.route('/api/alpha-judge/reports', methods=['GET'])
def api_alpha_judge_reports():
    root = _alpha_judge_root()
    outputs = root / 'outputs'
    if not outputs.exists():
        return jsonify({'ok': True, 'items': []})

    limit = request.args.get('limit', default=20, type=int)
    json_files = sorted(outputs.glob('judge_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for p in json_files[:max(limit, 1)]:
        md_name = p.with_suffix('.md').name
        items.append({
            'json_file': p.name,
            'markdown_file': md_name,
            'updated_at': datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
        })
    return jsonify({'ok': True, 'items': items})


@app.route('/api/alpha-judge/reports/<path:filename>', methods=['GET'])
def api_alpha_judge_report_file(filename):
    if '..' in filename:
        return jsonify({'ok': False, 'error': 'Invalid filename'}), 400
    outputs = _alpha_judge_root() / 'outputs'
    if not outputs.exists():
        return jsonify({'ok': False, 'error': 'Outputs directory not found'}), 404
    return send_from_directory(str(outputs), filename, as_attachment=False)


@app.route('/api/pipeline/list', methods=['GET'])
def api_pipeline_list():
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    return jsonify({'ok': True, 'pipelines': _list_pipelines(), 'workers': _global_worker_usage()})


@app.route('/api/pipeline/create', methods=['POST'])
def api_pipeline_create():
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503

    body = request.get_json(silent=True) or {}

    try:
        body['prompt_overrides'] = _sanitize_prompt_overrides(body.get('prompt_overrides'))
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'高级提示词配置无效: {exc}'}), 400

    _apply_default_enhance_prompt_overrides(body)

    try:
        body['stop_conditions'] = _sanitize_stop_conditions(body.get('stop_conditions'))
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'停止条件配置无效: {exc}'}), 400

    # Inject BRAIN credentials from active session (user already logged in)
    session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
    if session_id and session_id in brain_sessions:
        sess_info = brain_sessions[session_id]
        if isinstance(sess_info, dict):
            body.setdefault('brain_username', sess_info.get('username', ''))
            body.setdefault('brain_password', sess_info.get('password', ''))

    required = ['data_category', 'region', 'delay', 'dataset_id', 'moonshot_api_key',
                'brain_username', 'brain_password']
    missing = [k for k in required if not body.get(k)]
    if missing:
        return jsonify({'ok': False, 'error': f'缺少必要字段: {missing}。请确保已登录 BRAIN 平台。'}), 400

    try:
        runner = _create_pipeline(body)
        return jsonify({'ok': True, 'pipeline_id': runner.pipeline_id, 'status': runner.status()}), 201
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/api/pipeline/<pipeline_id>/start', methods=['POST'])
def api_pipeline_start(pipeline_id):
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    body = request.get_json(silent=True) or {}
    # Inject BRAIN credentials from active session only if config doesn't have them
    # Priority: 1) Explicitly provided in body, 2) Existing config, 3) Web session
    existing_username = str(runner.config.get('brain_username', '') or '').strip()
    existing_password = str(runner.config.get('brain_password', '') or '').strip()

    if body.get('brain_username'):
        runner.config['brain_username'] = body['brain_username']
    elif not existing_username:
        # Only fall back to session if no credentials in config
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if session_id and session_id in brain_sessions:
            sess_info = brain_sessions[session_id]
            if isinstance(sess_info, dict):
                runner.config['brain_username'] = sess_info.get('username', '')

    if body.get('brain_password'):
        runner.config['brain_password'] = body['brain_password']
    elif not existing_password:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if session_id and session_id in brain_sessions:
            sess_info = brain_sessions[session_id]
            if isinstance(sess_info, dict):
                runner.config['brain_password'] = sess_info.get('password', '')

    if body.get('moonshot_api_key'):
        runner.config['moonshot_api_key'] = body['moonshot_api_key']
    runner.start()
    return jsonify({'ok': True, 'status': runner.status()})


@app.route('/api/pipeline/<pipeline_id>/stop', methods=['POST'])
def api_pipeline_stop(pipeline_id):
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    runner.stop()
    return jsonify({'ok': True, 'status': runner.status()})


@app.route('/api/pipeline/<pipeline_id>/force-restart', methods=['POST'])
def api_pipeline_force_restart(pipeline_id):
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404

    body = request.get_json(silent=True) or {}
    new_config = dict(runner.config)
    new_config.pop('pipeline_id', None)

    # Priority: 1) Explicitly provided in body, 2) Existing config, 3) Web session
    existing_username = str(new_config.get('brain_username', '') or '').strip()
    existing_password = str(new_config.get('brain_password', '') or '').strip()

    if body.get('brain_username'):
        new_config['brain_username'] = body['brain_username']
    elif not existing_username:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if session_id and session_id in brain_sessions:
            sess_info = brain_sessions[session_id]
            if isinstance(sess_info, dict):
                new_config['brain_username'] = sess_info.get('username', '')
                
    if body.get('brain_password'):
        new_config['brain_password'] = body['brain_password']
    elif not existing_password:
        session_id = request.headers.get('Session-ID') or flask_session.get('brain_session_id')
        if session_id and session_id in brain_sessions:
            sess_info = brain_sessions[session_id]
            if isinstance(sess_info, dict):
                new_config['brain_password'] = sess_info.get('password', '')

    if body.get('moonshot_api_key'):
        new_config['moonshot_api_key'] = body['moonshot_api_key']
    if body.get('data_type'):
        dt = str(body['data_type']).strip().upper()
        if dt in ('MATRIX', 'VECTOR'):
            new_config['data_type'] = dt

    try:
        deleted = _delete_pipeline(pipeline_id)
        if not deleted:
            return jsonify({'ok': False, 'error': '旧流水线删除失败'}), 400
        new_runner = _create_pipeline(new_config)
        new_runner.start()
        return jsonify({'ok': True, 'pipeline_id': new_runner.pipeline_id, 'status': new_runner.status()})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@app.route('/api/pipeline/<pipeline_id>/status', methods=['GET'])
def api_pipeline_status(pipeline_id):
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    return jsonify({'ok': True, **runner.status()})


@app.route('/api/pipeline/<pipeline_id>/pool', methods=['GET'])
def api_pipeline_pool(pipeline_id):
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404

    def _sanitize_json_value(value):
        if isinstance(value, dict):
            return {k: _sanitize_json_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_sanitize_json_value(v) for v in value]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    return jsonify({
        'ok': True,
        'pool': _sanitize_json_value(runner.pool.all()),
        'stats': _sanitize_json_value(runner.pool.stats()),
    })


@app.route('/api/pipeline/<pipeline_id>/idea-content', methods=['GET'])
def api_pipeline_idea_content(pipeline_id):
    """Return idea content: alpha expressions if inspected, else raw JSON."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    idea_file = request.args.get('idea_file', '')
    if not idea_file:
        return jsonify({'ok': False, 'error': 'Missing idea_file'}), 400
    # Find entry in pool
    entry = next((e for e in runner.pool.all() if e.get('idea_file') == idea_file), None)
    if entry is None:
        return jsonify({'ok': False, 'error': 'Idea not found in pool'}), 404

    alpha_list_file = entry.get('alpha_list_file', '')
    if alpha_list_file and entry.get('inspect_status') == 'done':
        # Return alpha expressions
        alp = runner.pipeline_dir / alpha_list_file
        if alp.exists():
            try:
                data = json.loads(alp.read_text(encoding='utf-8'))
                exprs = []
                for item in data:
                    if isinstance(item, dict):
                        # Extract the nested settings dict (contains delay, neutralization, etc.)
                        inner = item.get('settings', {}) if isinstance(item.get('settings'), dict) else {}
                        flat_settings = dict(inner)
                        # Also include top-level non-expression keys (e.g. type) 
                        for k, v in item.items():
                            if k not in ('regular', 'expression', 'Regular', 'settings'):
                                flat_settings.setdefault(k, v)
                        exprs.append({
                            'expression': item.get('regular', item.get('expression', item.get('Regular', str(item)))),
                            'settings': flat_settings,
                        })
                    else:
                        exprs.append({'expression': str(item), 'settings': {}})
                return jsonify({'ok': True, 'type': 'expressions', 'expressions': exprs, 'idea_file': idea_file})
            except Exception as exc:
                return jsonify({'ok': False, 'error': str(exc)}), 500

    # Return raw idea JSON
    idea_path = runner.pipeline_dir / idea_file
    if idea_path.exists():
        try:
            raw = idea_path.read_text(encoding='utf-8')
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = raw
            return jsonify({'ok': True, 'type': 'json', 'content': data, 'idea_file': idea_file})
        except Exception as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 500
    return jsonify({'ok': False, 'error': 'Idea file not found on disk'}), 404


@app.route('/api/pipeline/<pipeline_id>/sim-detail', methods=['GET'])
def api_pipeline_sim_detail(pipeline_id):
    """Return per-alpha simulation details (alpha_id, sharpe, expression, status) from CSV."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    idea_file = request.args.get('idea_file', '')
    if not idea_file:
        return jsonify({'ok': False, 'error': 'Missing idea_file'}), 400
    entry = next((e for e in runner.pool.all() if e.get('idea_file') == idea_file), None)
    if entry is None:
        return jsonify({'ok': False, 'error': 'Idea not found in pool'}), 404
    sim_csv = entry.get('sim_csv', '')
    if not sim_csv:
        # During running, sim_csv isn't set yet - infer path from idea_file
        from pipeline_runner import _sim_csv_name
        inferred = runner.pipeline_dir / "sim" / _sim_csv_name(idea_file)
        if inferred.exists():
            csv_path = inferred
        else:
            return jsonify({'ok': True, 'alphas': [], 'idea_file': idea_file})
    else:
        csv_path = runner.pipeline_dir / sim_csv
    if not csv_path.exists():
        return jsonify({'ok': True, 'alphas': [], 'idea_file': idea_file})
    try:
        import pandas as pd
        import math as _math
        from stage_simulate import _load_latest_sim_rows

        def _safe_num(v):
            """Convert pandas NaN / Inf to None so json.dumps emits null, not NaN."""
            if v is None:
                return None
            try:
                f = float(v)
                return None if not _math.isfinite(f) else f
            except (TypeError, ValueError):
                return v

        df = _load_latest_sim_rows(csv_path)
        records = []
        for _, row in df.iterrows():
            records.append({
                'alpha_id': str(row.get('alpha_id', '')),
                'expression': str(row.get('regular_expression', '')),
                'sharpe': _safe_num(row.get('sharpe')),
                'fitness': _safe_num(row.get('fitness')),
                'turnover': _safe_num(row.get('turnover')),
                'status': str(row.get('status', '')),
                'error': str(row.get('error', '')),
                'error_details': str(row.get('error_details', '')),
            })
        return jsonify({'ok': True, 'alphas': records, 'idea_file': idea_file, 'summary': entry.get('sim_summary', {}), 'sim_status': entry.get('sim_status', '')})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


def _read_text_optional(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return ''


GENERATE_SYSTEM_PROMPT_TEMPLATE = """You are executing two skills in sequence:
1) brain-data-feature-engineering
2) brain-feature-implementation
The following SKILL.md documents are authoritative; follow them exactly.

--- SKILL.md (brain-data-feature-engineering) ---
{{FEATURE_ENGINEERING_SKILL_MD}}

--- SKILL.md (brain-feature-implementation) ---
{{FEATURE_IMPLEMENTATION_SKILL_MD}}
------
"allowed_operators": {{ALLOWED_OPERATORS_JSON}}
-------
"allowed_placeholders": {{ALLOWED_PLACEHOLDERS_JSON}}

{{VECTOR_DATA_HINT}}
{{VECTOR_OPERATORS_LINE}}
CRITICAL OUTPUT RULES (to ensure implement_idea.py can generate expressions):
- Every Implementation Example MUST be a Python format template using {variable}.
- Every {variable} MUST come from the allowed_placeholders list provided in user content.
- When you implement ideas, ONLY use operators from allowed_operators provided.
- Do NOT include dataset codes/prefixes/horizons in {variable} (suffix-only).
- If you show raw field ids in tables, use backticks `like_this`, NOT {braces}.
- Include these metadata lines verbatim somewhere near the top:
  **Dataset**: <dataset_id>
  **Region**: <region>
  **Delay**: <delay>""".strip()

INSPECT_SETTINGS_SYSTEM_PROMPT_TEMPLATE = (
    'You are a WorldQuant BRAIN expert. Given an alpha idea context and valid simulation '
    'setting candidates, choose the BEST neutralization and decay for this alpha. '
    'Respond with ONLY a JSON object: {"neutralization": "...", "decay": <int>}'
)

INSPECT_REPAIR_SYSTEM_PROMPT_TEMPLATE = (
    'You are repairing a WorldQuant BRAIN alpha idea that failed local expression validation. '
    'Keep the same economic meaning and structure, but fix invalid operators, wrong operator names, '
    'wrong argument signatures, and syntax issues. Use only operators from the provided operator list, '
    'and follow the provided local signatures exactly. Respond with ONLY a JSON object: '
    '{"template":"...","idea":"...","expression_list":["..."]}'
)

ENHANCE_SYSTEM_PROMPT_TEMPLATE_V1 = """An alpha template is a reusable recipe that captures an economic idea and leaves "slots" (data fields, operators, groups, decay, neutralization choices, etc.) to instantiate many candidate alphas. Typical structure: clean data (backfill, winsorize) -> transform/compare across time or peers -> rank/neutralize -> (optionally) decay/turnover tune. Templates encourage systematic search, reuse, and diversification while keeping an explicit economic rationale.

Some Example Templates and rationales to help you understand the format

CAPM residual (market/sector-neutral return): ts_regression(returns, group_mean(returns, log(ts_mean(cap,21)), sector), 252, rettype=0) after backfill+winsorize. Rationale: strip market/sector beta to isolate idiosyncratic alpha; sector-weighted by smoothed log-cap to reduce large-cap dominance.
CAPM beta (slope) template: same regression with rettype=2; pre-clean target/market (ts_backfill(...,63) + winsorize(std=4)). Rationale: rank stocks by relative risk within sector; long low-尾, short high-尾, or study 尾 dispersion across groups.
CAPM generalized to any feature: data = winsorize(ts_backfill({data},63),std=4); data_gpm = group_mean(data, log(ts_mean(cap,21)), sector); resid = ts_regression(data, data_gpm, 252, rettype=0). Rationale: pull out the component unexplained by group average of same feature; reduces common-mode exposure.
Actual vs estimate spread (analyst): group_zscore( group_zscore({act}, industry) - group_zscore({est}, industry), industry ) or the abstracted group_compare(diff(group_compare(act,...), group_compare(est,...)), ...). Rationale: surprise/beat-miss signal within industry, normalized to peers to avoid level bias.
Analyst term-structure (fp1 vs fy1/fp2/fy2): group_zscore( group_zscore({mean_eps_period1}, industry) - group_zscore({mean_eps_period2}, industry), industry ) with operator/group slots. Rationale: cross-period expectation steepness; rising near-term vs long-term forecasts can flag momentum/inflection.
Option Greeks net spread: group_operator({put_greek} - {call_greek}, {grouping_data}) over industry/sector (Delta/Gamma/Vega/Theta). Rationale: options-implied sentiment/convexity skew vs peers; outlier net Greeks may precede spot moves; extend with multi-Greek composites or time-series deltas.

based on the following guidance of how to make a data collation template into a signal, and guidance on how to utilize the best of operators.

guidance of how to make a data collation template into a signal
--------------
{{GUIDE1}}
--------------
guidance on how to use the best of operators
--------------
{{GUIDE2}}
--------------

{{VECTOR_DATA_HINT}}

Return ONLY valid JSON (no markdown / no code fences).""".strip()

ENHANCE_SYSTEM_PROMPT_TEMPLATE_V2 = """You are executing the enhancement stage as a strict WorldQuant BRAIN alpha-optimization prompt, not a generic paraphrasing prompt.

Your job is to produce enhanced alpha templates that are structurally stronger, more diverse, and more simulation-ready while preserving the baseline template's core economic fields and dataset family.

Hard rules:
1. Freeze the core fields and dataset family from the input template. Do not replace the core source with unrelated fields.
2. Prioritize structural upgrades over cosmetic rewrites.
3. In Stage A style enhancement, pure parameter fine-tuning is forbidden unless current best metrics already satisfy Sharpe > 1.40 and Fitness > 0.90.
4. Prefer economically meaningful upgrades such as conditional trading, denoising, truncation, orthogonalization, correlation-structure modeling, or turnover control.
5. Keep templates implementable. Do not invent unsupported operators, fields, or placeholders.
6. Any optional operator argument must be used in explicit name=value form.
7. Do not simplify away the core signal just to make the template look cleaner.
8. Return ONLY valid JSON with enhanced templates and ideas. No markdown and no code fences.

Enhancement targets:
- create high-difference variants rather than shallow paraphrases
- reduce future trial-and-error by making operator usage more deliberate
- improve the chance that downstream validation and simulation pass on the first try
- encourage lower crowding by covering different operator themes

Preferred structural themes to mix across outputs:
- conditional trading or freeze logic: trade_when, keep, if_else, nan_mask
- denoising and backfill logic: filter, hump, hump_decay, jump_decay, ts_backfill, group_backfill
- robust tail treatment: clamp, nan_out, pasteurize, purify, truncate, winsorize
- orthogonalization and projection: regression_neut, regression_proj, ts_regression, vector_neut, vector_proj, group_vector_neut
- correlation structure: ts_corr, ts_covariance, ts_partial_corr, ts_co_skewness, ts_co_kurtosis
- turnover and sizing control: scale, scale_down, rank_by_side, one_side, ts_delta_limit, ts_target_tvr_decay

Generation rules:
- Keep placeholders in { } unchanged.
- Do not invent new placeholders.
- Preserve the baseline template's economic meaning, but upgrade the operator pipeline.
- Favor a diverse set of outputs with different structural themes rather than repeating one motif.
- If you use frequent operators such as rank, zscore, winsorize, ts_mean, or scale, combine them with at least one stronger structural theme instead of stacking only common operators.
- For vector datasets, follow the vector-data constraints exactly.

Quality bar for each output:
- economically interpretable
- operator choices are deliberate, not random
- implementation-ready for downstream local validation
- materially different from sibling outputs in the same batch

Use the following two guides as authoritative context.

guidance of how to make a data collation template into a signal
--------------
{{GUIDE1}}
--------------
guidance on how to use the best of operators
--------------
{{GUIDE2}}
--------------

{{VECTOR_DATA_HINT}}

Return ONLY valid JSON (no markdown / no code fences).""".strip()

ENHANCE_SYSTEM_PROMPT_TEMPLATE = ENHANCE_SYSTEM_PROMPT_TEMPLATE_V1


def _enhance_prompt_variants():
    return {
        'v1': ENHANCE_SYSTEM_PROMPT_TEMPLATE_V1,
        'v2': ENHANCE_SYSTEM_PROMPT_TEMPLATE_V2,
    }


def _pick_random_enhance_prompt_variant():
    variants = list(_enhance_prompt_variants().items())
    return random.choice(variants)


def _apply_default_enhance_prompt_overrides(body: dict):
    overrides = dict(body.get('prompt_overrides') or {})
    need_single = not str(overrides.get('enhance_single_system_prompt') or '').strip()
    if not need_single:
        body['prompt_overrides'] = overrides
        return

    variant_name, variant_text = _pick_random_enhance_prompt_variant()
    overrides['enhance_single_system_prompt'] = variant_text

    body['prompt_overrides'] = overrides
    body['enhance_prompt_variant'] = variant_name


def _replace_prompt_tokens(template: str, mapping: dict[str, str]) -> str:
    rendered = str(template or '')
    for key, value in mapping.items():
        rendered = rendered.replace('{{' + key + '}}', str(value or ''))
    return rendered


def _advanced_prompt_sections():
    from stage_decide import DEFAULT_DECIDE_PROMPT

    return [
        {
            'key': 'generate_system_prompt',
            'title': '生成阶段系统提示词',
            'description': '控制初始 idea 生成阶段使用的系统提示词模板。',
            'default_text': GENERATE_SYSTEM_PROMPT_TEMPLATE,
            'locked_tokens': [
                '{{FEATURE_ENGINEERING_SKILL_MD}}',
                '{{FEATURE_IMPLEMENTATION_SKILL_MD}}',
                '{{ALLOWED_OPERATORS_JSON}}',
                '{{ALLOWED_PLACEHOLDERS_JSON}}',
                '{{VECTOR_DATA_HINT}}',
                '{{VECTOR_OPERATORS_LINE}}',
            ],
        },
        {
            'key': 'inspect_settings_system_prompt',
            'title': '检查阶段选参提示词',
            'description': '控制检查阶段选择 neutralization、decay 等参数时使用的系统提示词。',
            'default_text': INSPECT_SETTINGS_SYSTEM_PROMPT_TEMPLATE,
            'locked_tokens': [],
        },
        {
            'key': 'inspect_repair_system_prompt',
            'title': '检查阶段修复提示词',
            'description': '控制检查阶段在表达式不合法时进行修复的系统提示词。',
            'default_text': INSPECT_REPAIR_SYSTEM_PROMPT_TEMPLATE,
            'locked_tokens': [],
        },
        {
            'key': 'decide_system_prompt',
            'title': '决策阶段系统提示词',
            'description': '控制决策阶段如何选择下一轮增强目标与增强风格。',
            'default_text': DEFAULT_DECIDE_PROMPT.replace('{max_enhance_per_round}', '{{MAX_ENHANCE_PER_ROUND}}').strip(),
            'locked_tokens': ['{{MAX_ENHANCE_PER_ROUND}}'],
        },
        {
            'key': 'enhance_single_system_prompt',
            'title': '增强阶段单模板提示词',
            'description': '控制增强阶段针对单个模板做常规增强时使用的系统提示词。若不自定义，新建流水线时系统会在内置 V1/V2 中随机选择并固化。',
            'default_text': ENHANCE_SYSTEM_PROMPT_TEMPLATE_V1,
            'preset_options': [
                {
                    'key': 'v1',
                    'label': '使用内置 V1',
                    'description': '原有单模板增强 system prompt。',
                    'text': ENHANCE_SYSTEM_PROMPT_TEMPLATE_V1,
                },
                {
                    'key': 'v2',
                    'label': '使用内置 V2',
                    'description': '带有更强结构化优化约束的新单模板增强 system prompt。',
                    'text': ENHANCE_SYSTEM_PROMPT_TEMPLATE_V2,
                },
            ],
            'locked_tokens': ['{{GUIDE1}}', '{{GUIDE2}}', '{{VECTOR_DATA_HINT}}'],
        },
        {
            'key': 'enhance_cross_system_prompt',
            'title': '增强阶段交叉增强提示词',
            'description': '控制增强阶段进行交叉融合增强时使用的系统提示词。若不自定义，将保持默认提示词。',
            'default_text': ENHANCE_SYSTEM_PROMPT_TEMPLATE_V1,
            'locked_tokens': ['{{GUIDE1}}', '{{GUIDE2}}', '{{VECTOR_DATA_HINT}}'],
        },
    ]


def _advanced_prompt_section_map():
    return {item['key']: item for item in _advanced_prompt_sections()}


def _prompt_token_preview(section_key: str, token: str, data_type: str = 'MATRIX', max_enhance_per_round: int = 4):
    section_map = _advanced_prompt_section_map()
    section = section_map.get(section_key)
    if not section:
        raise ValueError(f'未知的提示词配置项: {section_key}')

    allowed_tokens = set(re.findall(r'\{\{[A-Z0-9_]+\}\}', str(section.get('default_text') or '')))
    if token not in allowed_tokens:
        raise ValueError(f'{section.get("title") or section_key} 不包含变量 {token}')

    app_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    trail_dir = app_dir / 'trailSomeAlphas'
    vector_hint = (
        'since all the following the data is vector type data, before you do any process, '
        'you should choose a vector operator to generate its statistical feature to use, '
        'the data cannot be directly use. for example, if datafieldA and datafieldB are '
        'vector type data, you can use vec_avg(datafieldA) -  vec_avg(datafieldB), where '
        'vec_avg() operator is used to generate the average of the data on a certain date. '
        'similarly, vector type operator can only be used on the vector type operator '
        'directly and cannot be nested, for example vec_avg(vec_sum(datafield)) is a false use.'
    )
    vector_operators_line = 'the available vector operators are: vec_avg, vec_sum, vec_max, vec_min, vec_std, vec_count'

    preview_map = {
        '{{FEATURE_ENGINEERING_SKILL_MD}}': {
            'title': '变量预览：FEATURE_ENGINEERING_SKILL_MD',
            'description': '生成阶段会把数据特征工程技能文档插入到这里。',
            'content': _read_text_optional(trail_dir / 'skills' / 'brain-data-feature-engineering' / 'SKILL.md') or '未找到技能文档。',
        },
        '{{FEATURE_IMPLEMENTATION_SKILL_MD}}': {
            'title': '变量预览：FEATURE_IMPLEMENTATION_SKILL_MD',
            'description': '生成阶段会把特征实现技能文档插入到这里。',
            'content': _read_text_optional(trail_dir / 'skills' / 'brain-feature-implementation' / 'SKILL.md') or '未找到技能文档。',
        },
        '{{ALLOWED_OPERATORS_JSON}}': {
            'title': '变量预览：ALLOWED_OPERATORS_JSON',
            'description': '运行时会替换为当前数据集允许使用的算子 JSON 列表。',
            'content': json.dumps({
                'note': '这里会在运行时替换成 allowed_operators 的完整 JSON。不同数据集和运行环境下内容可能不同。',
                'example': ['ts_mean', 'group_mean', 'rank', 'winsorize']
            }, ensure_ascii=False, indent=2),
        },
        '{{ALLOWED_PLACEHOLDERS_JSON}}': {
            'title': '变量预览：ALLOWED_PLACEHOLDERS_JSON',
            'description': '运行时会替换为当前数据集可用的占位符后缀列表。',
            'content': json.dumps({
                'note': '这里会在运行时替换成 allowed_placeholders 的完整 JSON。它用于告知模型哪些 {variable} 可用。',
                'example': ['revenue', 'eps', 'close', 'turnover']
            }, ensure_ascii=False, indent=2),
        },
        '{{VECTOR_DATA_HINT}}': {
            'title': '变量预览：VECTOR_DATA_HINT',
            'description': '当 data_type=VECTOR 时，这里会插入向量字段使用说明；否则为空。',
            'content': vector_hint if str(data_type or 'MATRIX').upper() == 'VECTOR' else '当前 data_type 不是 VECTOR，因此该变量在运行时会展开为空。',
        },
        '{{VECTOR_OPERATORS_LINE}}': {
            'title': '变量预览：VECTOR_OPERATORS_LINE',
            'description': '当 data_type=VECTOR 时，这里会插入可用向量算子说明；否则为空。',
            'content': vector_operators_line if str(data_type or 'MATRIX').upper() == 'VECTOR' else '当前 data_type 不是 VECTOR，因此该变量在运行时会展开为空。',
        },
        '{{MAX_ENHANCE_PER_ROUND}}': {
            'title': '变量预览：MAX_ENHANCE_PER_ROUND',
            'description': '决策阶段会把这里替换成当前配置中的“每轮最多增强数”。',
            'content': str(int(max_enhance_per_round or 4)),
        },
        '{{GUIDE1}}': {
            'title': '变量预览：GUIDE1',
            'description': '增强阶段会把 Guide1 文档插入到这里。',
            'content': 'Guide1 content preview is unavailable in this environment.',
        },
        '{{GUIDE2}}': {
            'title': '变量预览：GUIDE2',
            'description': '增强阶段会把 Guide2 文档插入到这里。',
            'content': 'Guide2 content preview is unavailable in this environment.',
        },
    }

    item = preview_map.get(token)
    if not item:
        raise ValueError(f'暂不支持预览变量: {token}')
    return item


def _sanitize_prompt_overrides(raw):
    if raw in (None, '', {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError('prompt_overrides 必须是对象')

    section_map = _advanced_prompt_section_map()
    sanitized = {}
    for key, value in raw.items():
        if key not in section_map:
            raise ValueError(f'未知的提示词配置项: {key}')
        text = str(value or '').strip()
        if not text:
            continue
        sanitized[key] = text
    return sanitized


def _default_stop_conditions():
    return {
        'sharpe_target_count': {
            'min_sharpe': None,
            'target_count': None,
            'use_abs': False,
        },
        'max_pool_ideas': None,
        'max_alpha_submitted': None,
        'max_sim_completed': None,
        'max_iterations': None,
        'diminishing_returns': {
            'enabled': False,
            'min_sharpe': None,
            'lookback_rounds': 2,
            'degrade_ratio': 0.5,
            'min_baseline_samples': 20,
        },
    }


def _parse_positive_int(value, field_name: str):
    if value in (None, ''):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} 必须是正整数')
    if parsed <= 0:
        raise ValueError(f'{field_name} 必须是正整数')
    return parsed


def _parse_positive_float(value, field_name: str):
    if value in (None, ''):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} 必须是正数')
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f'{field_name} 必须是正数')
    return parsed


def _parse_non_negative_float(value, field_name: str):
    if value in (None, ''):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} 必须是数字')
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f'{field_name} 必须是大于等于 0 的数字')
    return parsed


def _parse_bool(value, field_name: str):
    if value in (None, ''):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ('1', 'true', 'yes', 'on'):
            return True
        if normalized in ('0', 'false', 'no', 'off'):
            return False
    raise ValueError(f'{field_name} 必须是布尔值')


def _sanitize_stop_conditions(raw):
    defaults = _default_stop_conditions()
    if raw in (None, '', {}):
        return defaults
    if not isinstance(raw, dict):
        raise ValueError('stop_conditions 必须是对象')

    allowed_keys = set(defaults.keys())
    unknown = [key for key in raw.keys() if key not in allowed_keys]
    if unknown:
        raise ValueError(f'未知的停止条件配置项: {unknown}')

    sanitized = _default_stop_conditions()

    sharpe_cfg = raw.get('sharpe_target_count') or {}
    if sharpe_cfg not in ({}, None):
        if not isinstance(sharpe_cfg, dict):
            raise ValueError('sharpe_target_count 必须是对象')
        use_abs = _parse_bool(sharpe_cfg.get('use_abs'), 'Sharpe 绝对值开关')
        sanitized['sharpe_target_count'] = {
            'min_sharpe': _parse_non_negative_float(sharpe_cfg.get('min_sharpe'), 'Sharpe 阈值'),
            'target_count': _parse_positive_int(sharpe_cfg.get('target_count'), '目标结果数'),
            'use_abs': False if use_abs is None else use_abs,
        }

    for field_name, label in [
        ('max_pool_ideas', '最大池中 idea 数'),
        ('max_alpha_submitted', '最大回测提交量'),
        ('max_sim_completed', '最大回测完成量'),
        ('max_iterations', '最大迭代数'),
    ]:
        sanitized[field_name] = _parse_positive_int(raw.get(field_name), label)

    diminishing_raw = raw.get('diminishing_returns') or {}
    if diminishing_raw not in ({}, None):
        if not isinstance(diminishing_raw, dict):
            raise ValueError('diminishing_returns 必须是对象')
        lookback_rounds = diminishing_raw.get('lookback_rounds', defaults['diminishing_returns']['lookback_rounds'])
        degrade_ratio = diminishing_raw.get('degrade_ratio', defaults['diminishing_returns']['degrade_ratio'])
        min_baseline_samples = diminishing_raw.get('min_baseline_samples', defaults['diminishing_returns']['min_baseline_samples'])
        try:
            enabled = bool(diminishing_raw.get('enabled'))
            lookback_rounds = int(lookback_rounds)
            min_baseline_samples = int(min_baseline_samples)
            degrade_ratio = float(degrade_ratio)
        except (TypeError, ValueError):
            raise ValueError('增强收益递减配置格式无效')
        if lookback_rounds < 1:
            raise ValueError('增强收益递减回看轮数必须 >= 1')
        if min_baseline_samples < 1:
            raise ValueError('增强收益递减样本门槛必须 >= 1')
        if not math.isfinite(degrade_ratio) or degrade_ratio <= 0:
            raise ValueError('增强收益递减倍率必须 > 0')
        sanitized['diminishing_returns'] = {
            'enabled': enabled,
            'min_sharpe': _parse_non_negative_float(diminishing_raw.get('min_sharpe'), '增强收益递减 Sharpe 阈值'),
            'lookback_rounds': lookback_rounds,
            'degrade_ratio': degrade_ratio,
            'min_baseline_samples': min_baseline_samples,
        }

    sharpe_target = sanitized['sharpe_target_count']
    if (sharpe_target.get('min_sharpe') is None) != (sharpe_target.get('target_count') is None):
        raise ValueError('Sharpe 停止条件需要同时填写 Sharpe 阈值和目标结果数')

    return sanitized


def _get_prompt_overrides(config: dict | None):
    overrides = (config or {}).get('prompt_overrides') or {}
    if isinstance(overrides, dict):
        return overrides
    return {}


def _get_prompt_override(config: dict | None, key: str) -> str:
    return str(_get_prompt_overrides(config).get(key) or '')


@app.route('/api/pipeline/prompt-templates', methods=['GET'])
def api_pipeline_prompt_templates():
    return jsonify({'ok': True, 'sections': _advanced_prompt_sections()})


@app.route('/api/pipeline/prompt-token-preview', methods=['GET'])
def api_pipeline_prompt_token_preview():
    try:
        section_key = str(request.args.get('section_key') or '').strip()
        token = str(request.args.get('token') or '').strip()
        data_type = str(request.args.get('data_type') or 'MATRIX').strip().upper()
        max_enhance_per_round = int(request.args.get('max_enhance_per_round') or 4)
        preview = _prompt_token_preview(section_key, token, data_type, max_enhance_per_round)
        return jsonify({'ok': True, **preview})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


def _generate_prompt_preview_sections(runner):
    app_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    trail_dir = app_dir / 'trailSomeAlphas'
    feature_engineering_skill = _read_text_optional(
        trail_dir / 'skills' / 'brain-data-feature-engineering' / 'SKILL.md'
    )
    feature_implementation_skill = _read_text_optional(
        trail_dir / 'skills' / 'brain-feature-implementation' / 'SKILL.md'
    )

    config = runner.config
    data_type = str(config.get('data_type') or 'MATRIX').upper()
    prompt_lines = [
        'You are executing two skills in sequence:',
        '1) brain-data-feature-engineering',
        '2) brain-feature-implementation',
        'The following SKILL.md documents are authoritative; follow them exactly.',
        '',
        '--- SKILL.md (brain-data-feature-engineering) ---',
        feature_engineering_skill.strip(),
        '',
        '--- SKILL.md (brain-feature-implementation) ---',
        feature_implementation_skill.strip(),
        '------',
        '"allowed_operators": <runtime allowed operators JSON>',
        '-------',
        '"allowed_placeholders": <runtime allowed placeholder suffix list>',
        '',
    ]
    if data_type == 'VECTOR':
        prompt_lines.append(
            'since all the following the data is vector type data, before you do any process, '
            'you should choose a vector operator to generate its statistical feature to use, '
            'the data cannot be directly use. for example, if datafieldA and datafieldB are '
            'vector type data, you can use vec_avg(datafieldA) -  vec_avg(datafieldB), where '
            'vec_avg() operator is used to generate the average of the data on a certain date. '
            'similarly, vector type operator can only be used on the vector type operator '
            'directly and cannot be nested, for example vec_avg(vec_sum(datafield)) is a false use.'
        )
        prompt_lines.append('the available vector operators are: vec_avg, vec_sum, vec_max, vec_min, vec_std, vec_count')
    prompt_lines.extend([
        'CRITICAL OUTPUT RULES (to ensure implement_idea.py can generate expressions):',
        '- Every Implementation Example MUST be a Python format template using {variable}.',
        '- Every {variable} MUST come from the allowed_placeholders list provided in user content.',
        '- When you implement ideas, ONLY use operators from allowed_operators provided.',
        '- Do NOT include dataset codes/prefixes/horizons in {variable} (suffix-only).',
        '- If you show raw field ids in tables, use backticks `like_this`, NOT {braces}.',
        '- Include these metadata lines verbatim somewhere near the top:',
        '  **Dataset**: <dataset_id>',
        '  **Region**: <region>',
        '  **Delay**: <delay>',
    ])
    system_prompt = '\n'.join(prompt_lines)
    system_override = _get_prompt_override(runner.config, 'generate_system_prompt')
    if system_override:
        system_prompt = _replace_prompt_tokens(system_override, {
            'FEATURE_ENGINEERING_SKILL_MD': feature_engineering_skill.strip(),
            'FEATURE_IMPLEMENTATION_SKILL_MD': feature_implementation_skill.strip(),
            'ALLOWED_OPERATORS_JSON': '<runtime allowed operators JSON>',
            'ALLOWED_PLACEHOLDERS_JSON': '<runtime allowed placeholder suffix list>',
            'VECTOR_DATA_HINT': data_type == 'VECTOR' and (
                'since all the following the data is vector type data, before you do any process, '
                'you should choose a vector operator to generate its statistical feature to use, '
                'the data cannot be directly use. for example, if datafieldA and datafieldB are '
                'vector type data, you can use vec_avg(datafieldA) -  vec_avg(datafieldB), where '
                'vec_avg() operator is used to generate the average of the data on a certain date. '
                'similarly, vector type operator can only be used on the vector type operator '
                'directly and cannot be nested, for example vec_avg(vec_sum(datafield)) is a false use.'
            ) or '',
            'VECTOR_OPERATORS_LINE': data_type == 'VECTOR' and 'the available vector operators are: vec_avg, vec_sum, vec_max, vec_min, vec_std, vec_count' or '',
        })
    user_prompt = json.dumps({
        'instructions': {
            'output_format': 'Fill OUTPUT_TEMPLATE.md with concrete content.',
            'implementation_examples': (
                'Each Implementation Example must be a template with {variable} placeholders. '
                'Use only placeholders from allowed_placeholders. '
                'Use suffix-only names; do not include dataset code/prefix/horizon.'
            ),
            'no_code_fences': True,
            'do_not_invent_placeholders': True,
        },
        'dataset_context': {
            'dataset_id': config.get('dataset_id') or '<dataset_id>',
            'dataset_name': '<runtime dataset_name>',
            'dataset_description': '<runtime dataset_description>',
            'category': config.get('data_category') or '<data_category>',
            'region': config.get('region') or '<region>',
            'delay': config.get('delay'),
            'universe': config.get('universe') or 'TOP3000',
            'field_count': '<runtime field_count>',
        },
        'fields': [
            {'id': '<field_id_1>', 'description': '<field_description_1>'},
            {'id': '<field_id_2>', 'description': '<field_description_2>'},
        ],
    }, ensure_ascii=False, indent=2)
    return [
        {'label': 'System Prompt', 'content': system_prompt},
        {'label': 'User Prompt 模板', 'content': user_prompt},
    ]


def _inspect_settings_prompt_preview_sections(runner):
    fixed_universe = str(runner.config.get('universe') or '').strip().upper() or None
    choose_fields = 'neutralization and decay' if fixed_universe else 'neutralization, universe, and decay'
    response_schema = '{"neutralization": "...", "decay": <int>}' if fixed_universe else '{"universe": "...", "neutralization": "...", "decay": <int>}'
    choose_system = _get_prompt_override(runner.config, 'inspect_settings_system_prompt') or (
        'You are a WorldQuant BRAIN expert. Given an alpha idea context and valid simulation '
        f'setting candidates, choose the BEST {choose_fields} for this alpha. '
        'Respond with ONLY a JSON object: '
        f'{response_schema}'
    )
    choose_user = json.dumps({
        'idea': {
            'dataset': runner.config.get('dataset_id') or '<dataset_id>',
            'region': runner.config.get('region') or '<region>',
            'delay': runner.config.get('delay'),
            'template': '<idea template from idea_*.json>',
            'idea_description': '<idea description from idea_*.json>',
        },
        'fixed_universe': fixed_universe,
        'candidates': [
            {'universe': fixed_universe or '<candidate_universe>', 'neutralization': '<candidate_neutralization>', 'decay': 4},
            {'universe': fixed_universe or '<candidate_universe>', 'neutralization': '<candidate_neutralization>', 'decay': 8},
        ],
    }, ensure_ascii=False, indent=2)

    return [
        {'label': '设置选择 System Prompt', 'content': choose_system},
        {'label': '设置选择 User Prompt 模板', 'content': choose_user},
    ]


def _inspect_repair_prompt_preview_sections(runner):
    repair_system = _get_prompt_override(runner.config, 'inspect_repair_system_prompt') or (
        'You are repairing a WorldQuant BRAIN alpha idea that failed local expression validation. '
        'Keep the same economic meaning and structure, but fix invalid operators, wrong operator names, '
        'wrong argument signatures, and syntax issues. Use only operators from the provided operator list, '
        'and follow the provided local signatures exactly. Respond with ONLY a JSON object: '
        '{"template":"...","idea":"...","expression_list":["..."]}'
    )
    repair_user = json.dumps({
        'task': 'Repair the invalid alpha template and expressions so they pass the local validator.',
        'rules': [
            'Do not change the alpha hypothesis unless necessary to make the expression valid.',
            'Prefer minimal edits over rewriting from scratch.',
            'Use only operator names present in operator_list.',
            'If an operator signature is wrong, fix it to match local_signatures.',
            'If all current expressions are invalid, regenerate a fresh expression_list from template and idea using validation_failures as guidance.',
            'Return at least one repaired expression in expression_list.',
        ],
        'raw_idea': {
            'template': '<raw template>',
            'idea': '<raw idea>',
            'expression_list': ['<invalid expression 1>', '<invalid expression 2>'],
        },
        'validation_failures': [
            {'expression': '<invalid expression>', 'errors': ['非法字符 ^', '无法解析表达式']},
        ],
        'local_signatures': {
            'group_mean': 'group_mean(x, weight, group)',
            'ts_mean': 'ts_mean(x, d)',
        },
        'operator_list': [
            {'name': 'ts_mean', 'category': 'Time Series'},
            {'name': 'group_mean', 'category': 'Group'},
        ],
    }, ensure_ascii=False, indent=2)
    return [
        {'label': '表达式修复 System Prompt', 'content': repair_system},
        {'label': '表达式修复 User Prompt 模板', 'content': repair_user},
    ]


def _decide_prompt_preview_sections(runner):
    from stage_decide import DEFAULT_DECIDE_PROMPT

    max_enhance_per_round = int(runner.config.get('max_enhance_per_round') or 4)
    prompt_override = _get_prompt_override(runner.config, 'decide_system_prompt')
    custom_prompt = str(runner.config.get('decide_prompt') or '')
    effective_prompt = (
        prompt_override and _replace_prompt_tokens(prompt_override, {
            'MAX_ENHANCE_PER_ROUND': str(max_enhance_per_round),
        })
    ) or custom_prompt or DEFAULT_DECIDE_PROMPT.format(
        max_enhance_per_round=max_enhance_per_round,
    )
    user_prompt = json.dumps({
        'iteration': runner.status().get('iteration', 0),
        'candidates': [
            {
                'idea_file': '<idea_file>',
                'tier': 'strong|weak',
                'origin': 'gen|enhance_round_N',
                'sim': {
                    'completed': 5,
                    'sharpe_avg': 0.92,
                    'fitness_avg': 0.61,
                    'turnover_avg': 0.24,
                },
                'idea': '<runtime loaded idea JSON or raw content>',
            }
        ],
    }, ensure_ascii=False, indent=2)
    return [
        {'label': (prompt_override or custom_prompt) and '当前生效 System Prompt（自定义）' or '当前生效 System Prompt（默认）', 'content': effective_prompt},
        {'label': 'LLM User Prompt 模板', 'content': user_prompt},
    ]


def _enhance_system_prompt(runner, override_key: str = ''):
    app_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    trail_dir = app_dir / 'trailSomeAlphas'
    guide1 = _read_text_optional(trail_dir / 'skills' / 'template_final_enhance' / '单因子思考逻辑链.md')
    guide2 = _read_text_optional(trail_dir / 'skills' / 'template_final_enhance' / 'op总结.md')
    data_type = str(runner.config.get('data_type') or 'MATRIX').upper()
    vector_hint = (
        'since the data is vector type data, the data cannot be directly use. before you do any process, '
        'you should choose a vector operator to generate its statistical feature to use (if the current '
        'template did not do so or you think you can have a better choice of another vector operator). '
        'for example, if datafieldA and datafieldB are vector type data, you cannot use vec_avg(datafieldA) '
        '-  vec_avg(datafieldB). similarly, vector type operator can only be used on the vector type operator.'
    )
    system_prompt = '\n\n'.join([
        'An alpha template is a reusable recipe that captures an economic idea and leaves "slots" (data fields, operators, groups, decay, neutralization choices, etc.) to instantiate many candidate alphas. Typical structure: clean data (backfill, winsorize) -> transform/compare across time or peers -> rank/neutralize -> (optionally) decay/turnover tune. Templates encourage systematic search, reuse, and diversification while keeping an explicit economic rationale.',
        '',
        'Some Example Templates and rationales to help you understand the format',
        '',
        'CAPM residual (market/sector-neutral return): ts_regression(returns, group_mean(returns, log(ts_mean(cap,21)), sector), 252, rettype=0) after backfill+winsorize. Rationale: strip market/sector beta to isolate idiosyncratic alpha; sector-weighted by smoothed log-cap to reduce large-cap dominance.',
        'CAPM beta (slope) template: same regression with rettype=2; pre-clean target/market (ts_backfill(...,63) + winsorize(std=4)). Rationale: rank stocks by relative risk within sector; long low-尾, short high-尾, or study 尾 dispersion across groups.',
        'CAPM generalized to any feature: data = winsorize(ts_backfill({data},63),std=4); data_gpm = group_mean(data, log(ts_mean(cap,21)), sector); resid = ts_regression(data, data_gpm, 252, rettype=0). Rationale: pull out the component unexplained by group average of same feature; reduces common-mode exposure.',
        'Actual vs estimate spread (analyst): group_zscore( group_zscore({act}, industry) - group_zscore({est}, industry), industry ) or the abstracted group_compare(diff(group_compare(act,...), group_compare(est,...)), ...). Rationale: surprise/beat-miss signal within industry, normalized to peers to avoid level bias.',
        'Analyst term-structure (fp1 vs fy1/fp2/fy2): group_zscore( group_zscore({mean_eps_period1}, industry) - group_zscore({mean_eps_period2}, industry), industry ) with operator/group slots. Rationale: cross-period expectation steepness; rising near-term vs long-term forecasts can flag momentum/inflection.',
        'Option Greeks net spread: group_operator({put_greek} - {call_greek}, {grouping_data}) over industry/sector (Delta/Gamma/Vega/Theta). Rationale: options-implied sentiment/convexity skew vs peers; outlier net Greeks may precede spot moves; extend with multi-Greek composites or time-series deltas.',
        '',
        'based on the following guidance of how to make a data collation template into a signal, and guidance on how to utilize the best of operators.',
        '',
        'guidance of how to make a data collation template into a signal',
        '--------------',
        guide1,
        '--------------',
        'guidance on how to use the best of operators',
        '--------------',
        guide2,
        '--------------',
        '',
        vector_hint if data_type == 'VECTOR' else '',
        '',
        'Return ONLY valid JSON (no markdown / no code fences).',
    ])
    override_text = _get_prompt_override(runner.config, override_key)
    if override_text:
        return _replace_prompt_tokens(override_text, {
            'GUIDE1': guide1,
            'GUIDE2': guide2,
            'VECTOR_DATA_HINT': vector_hint if data_type == 'VECTOR' else '',
        })
    return system_prompt


def _enhance_single_prompt_preview_sections(runner):
    system_prompt = _enhance_system_prompt(runner, 'enhance_single_system_prompt')
    single_user = json.dumps({
        'instruction': 'Improve the following raw template. Keep { } placeholders unchanged (they represent datafields). Return at least 5 diverse and complicate enhanced templates as possible.',
        'input': {
            'template': '<raw template>',
            'idea': '<raw idea>',
        },
        'output_format': [
            {'enhanced_template': '', 'idea': ''},
            {'enhanced_template': '', 'idea': ''},
        ],
        'idea_answer_in': 'Chinese',
    }, ensure_ascii=False, indent=2)
    return [
        {'label': 'System Prompt', 'content': system_prompt},
        {'label': 'Single Enhance User Prompt 模板', 'content': single_user},
    ]


def _enhance_cross_prompt_preview_sections(runner):
    system_prompt = _enhance_system_prompt(runner, 'enhance_cross_system_prompt')
    cross_user = json.dumps({
        'mode': 'cross_enhance',
        'style': 'balanced',
        'instruction': '交叉增强（均衡模式）：在创新性与稳定性之间取得平衡。每个输出应融合至少两个输入模板中有价值的运算逻辑，同时保持可实现性和可解释性。',
        'objective': 'Use all input templates and ideas to perform cross-enhancement with cross-applied operators and structures.',
        'constraints': [
            'Keep { } placeholders unchanged.',
            'Do not invent new placeholders.',
            'Each output should integrate transferable logic from multiple sources.',
            'Return at least 8 enhanced templates.',
        ],
        'inputs': [
            {'source': '<idea_1.json>', 'template': '<template_1>', 'idea': '<idea_1>'},
            {'source': '<idea_2.json>', 'template': '<template_2>', 'idea': '<idea_2>'},
        ],
        'output_format': [
            {'enhanced_template': '', 'idea': ''},
            {'enhanced_template': '', 'idea': ''},
        ],
        'idea_answer_in': 'Chinese',
    }, ensure_ascii=False, indent=2)
    return [
        {'label': 'System Prompt', 'content': system_prompt},
        {'label': 'Cross Enhance User Prompt 模板', 'content': cross_user},
    ]


def _phase_prompt_preview(runner, phase: str, kind: str = ''):
    phase = str(phase or '').strip().lower()
    kind = str(kind or '').strip().lower()
    if phase == 'generate':
        return {'title': '生成阶段提示词', 'editable': False, 'sections': _generate_prompt_preview_sections(runner)}
    if phase == 'inspect':
        if kind in {'', 'settings', 'choose-settings', 'settings-choose'}:
            return {'title': '检查阶段提示词：选参', 'editable': False, 'sections': _inspect_settings_prompt_preview_sections(runner)}
        if kind in {'repair', 'repair-invalid', 'invalid-repair'}:
            return {'title': '检查阶段提示词：修复', 'editable': False, 'sections': _inspect_repair_prompt_preview_sections(runner)}
        raise ValueError(f'Unsupported inspect prompt kind: {kind}')
    if phase == 'decide':
        return {'title': '决策阶段提示词', 'editable': False, 'sections': _decide_prompt_preview_sections(runner)}
    if phase == 'enhance':
        if kind in {'', 'single'}:
            return {'title': '增强阶段提示词：Single Enhance', 'editable': False, 'sections': _enhance_single_prompt_preview_sections(runner)}
        if kind in {'cross', 'cross-enhance'}:
            return {'title': '增强阶段提示词：Cross Enhance', 'editable': False, 'sections': _enhance_cross_prompt_preview_sections(runner)}
        raise ValueError(f'Unsupported enhance prompt kind: {kind}')
    if phase in {'simulate', 'implement'}:
        return {'title': f'{phase} 阶段', 'editable': False, 'sections': [{'label': '说明', 'content': '该阶段当前不直接调用大语言模型，因此没有独立的 LLM 提示词可展示。'}]}
    raise ValueError(f'Unsupported phase: {phase}')


@app.route('/api/pipeline/<pipeline_id>/phase-prompt', methods=['GET'])
def api_pipeline_phase_prompt(pipeline_id):
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    phase = request.args.get('phase', '').strip().lower()
    kind = request.args.get('kind', '').strip().lower()
    if not phase:
        return jsonify({'ok': False, 'error': 'Missing phase'}), 400
    try:
        payload = _phase_prompt_preview(runner, phase, kind)
        return jsonify({'ok': True, 'phase': phase, 'kind': kind, **payload})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@app.route('/api/pipeline/default-prompt', methods=['GET'])
def api_pipeline_default_prompt():
    """Return the built-in default decide prompt."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    try:
        from stage_decide import DEFAULT_DECIDE_PROMPT
        return jsonify({'ok': True, 'prompt': DEFAULT_DECIDE_PROMPT})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/api/pipeline/<pipeline_id>/update-prompt', methods=['POST'])
def api_pipeline_update_prompt(pipeline_id):
    """Update the decide prompt for a running pipeline."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    body = request.get_json(silent=True) or {}
    new_prompt = body.get('decide_prompt', '')
    runner.config['decide_prompt'] = new_prompt
    runner.log_activity(f"决策提示词已更新 ({'自定义' if new_prompt else '恢复默认'})", phase="decide")
    return jsonify({'ok': True, 'msg': 'Prompt updated'})


@app.route('/api/pipeline/<pipeline_id>/update-workers', methods=['POST'])
def api_pipeline_update_workers(pipeline_id):
    """Adjust sim_concurrent for a pipeline, enforcing global limit."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    body = request.get_json(silent=True) or {}
    new_val = body.get('sim_concurrent')
    if not isinstance(new_val, int) or new_val < 1:
        return jsonify({'ok': False, 'error': 'sim_concurrent must be int >= 1'}), 400
    usage = _global_worker_usage()
    current = runner.config.get('sim_concurrent', 2)
    delta = new_val - current
    if delta > 0 and usage['used'] + delta > usage['limit']:
        return jsonify({'ok': False, 'error': f'全局 Worker 配额不足 (已用{usage["used"]}/{usage["limit"]})', 'workers': usage}), 400
    runner.config['sim_concurrent'] = new_val
    runner.save_config()
    runner.log_activity(f"Worker数调整: {current} -> {new_val}", phase="simulate")
    if delta > 0:
        runner.trigger_sim()
    return jsonify({'ok': True, 'workers': _global_worker_usage()})


@app.route('/api/pipeline/<pipeline_id>/update-stop-conditions', methods=['POST'])
def api_pipeline_update_stop_conditions(pipeline_id):
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404

    body = request.get_json(silent=True) or {}
    try:
        stop_conditions = _sanitize_stop_conditions(body.get('stop_conditions'))
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'停止条件配置无效: {exc}'}), 400

    runner.config['stop_conditions'] = stop_conditions
    runner.save_config()
    runner.log_activity('停止条件已更新', phase='idle')
    triggered_reason = runner.apply_stop_conditions_now()
    return jsonify({
        'ok': True,
        'stop_conditions': stop_conditions,
        'stop_triggered': bool(triggered_reason),
        'stop_reason': triggered_reason or '',
        'status': runner.status(),
    })


@app.route('/api/pipeline/<pipeline_id>/config', methods=['GET'])
def api_pipeline_get_config(pipeline_id):
    """Get the current configuration of a pipeline (excluding sensitive data)."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404

    config = dict(runner.config)
    config.pop('moonshot_api_key', None)
    config.pop('brain_password', None)

    return jsonify({'ok': True, 'config': config})


@app.route('/api/pipeline/<pipeline_id>/update-config', methods=['POST'])
def api_pipeline_update_config(pipeline_id):
    """Update pipeline configuration (LLM settings, prompts, BRAIN credentials)."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404

    body = request.get_json(silent=True) or {}

    if 'moonshot_base_url' in body and body['moonshot_base_url']:
        runner.config['moonshot_base_url'] = str(body['moonshot_base_url']).strip()
    if 'moonshot_model' in body and body['moonshot_model']:
        runner.config['moonshot_model'] = str(body['moonshot_model']).strip()
    if 'moonshot_api_key' in body and body['moonshot_api_key']:
        runner.config['moonshot_api_key'] = str(body['moonshot_api_key']).strip()

    if 'prompt_overrides' in body and body['prompt_overrides']:
        try:
            runner.config['prompt_overrides'] = _sanitize_prompt_overrides(body['prompt_overrides'])
        except Exception as exc:
            return jsonify({'ok': False, 'error': f'提示词配置无效: {exc}'}), 400

    if 'brain_username' in body and body['brain_username']:
        runner.config['brain_username'] = str(body['brain_username']).strip()
    if 'brain_password' in body and body['brain_password']:
        runner.config['brain_password'] = str(body['brain_password']).strip()

    runner.save_config()
    runner.log_activity('流水线配置已更新', phase='idle')

    return jsonify({'ok': True, 'config': {k: v for k, v in runner.config.items() if k not in ('moonshot_api_key', 'brain_password')}})


@app.route('/api/pipeline/<pipeline_id>/abort-idea', methods=['POST'])
def api_pipeline_abort_idea(pipeline_id):
    """Abort a running simulation for a specific idea."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    body = request.get_json(silent=True) or {}
    idea_file = body.get('idea_file', '')
    if not idea_file:
        return jsonify({'ok': False, 'error': 'Missing idea_file'}), 400
    runner.abort_idea(idea_file)
    return jsonify({'ok': True, 'msg': f'Abort requested for {idea_file}'})


@app.route('/api/pipeline/<pipeline_id>/retry-idea', methods=['POST'])
def api_pipeline_retry_idea(pipeline_id):
    """Retry or resume a failed/aborted simulation for a specific idea."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    body = request.get_json(silent=True) or {}
    idea_file = body.get('idea_file', '')
    if not idea_file:
        return jsonify({'ok': False, 'error': 'Missing idea_file'}), 400
    if not runner.retry_idea(idea_file):
        return jsonify({'ok': False, 'error': 'Idea not found in pool'}), 404
    return jsonify({'ok': True, 'msg': f'Auto retry/resume requested for {idea_file}'})


@app.route('/api/pipeline/<pipeline_id>/retry-inspect-idea', methods=['POST'])
def api_pipeline_retry_inspect_idea(pipeline_id):
    """Retry a failed inspect for a specific idea."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    body = request.get_json(silent=True) or {}
    idea_file = body.get('idea_file', '')
    if not idea_file:
        return jsonify({'ok': False, 'error': 'Missing idea_file'}), 400
    try:
        if not runner.retry_inspect_idea(idea_file):
            return jsonify({'ok': False, 'error': 'Idea not found in pool'}), 404
        return jsonify({'ok': True, 'msg': f'Inspect retry requested for {idea_file}'})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@app.route('/api/pipeline/<pipeline_id>/continue-idea', methods=['POST'])
def api_pipeline_continue_idea(pipeline_id):
    """Backward-compatible alias for retry auto-resume behavior."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    body = request.get_json(silent=True) or {}
    idea_file = body.get('idea_file', '')
    if not idea_file:
        return jsonify({'ok': False, 'error': 'Missing idea_file'}), 400
    if not runner.retry_idea(idea_file):
        return jsonify({'ok': False, 'error': 'Idea not found in pool'}), 404
    return jsonify({'ok': True, 'msg': f'Auto retry/resume requested for {idea_file}'})


@app.route('/api/pipeline/<pipeline_id>/retry-enhance-idea', methods=['POST'])
def api_pipeline_retry_enhance_idea(pipeline_id):
    """Retry a failed single enhancement for a specific idea."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    body = request.get_json(silent=True) or {}
    idea_file = body.get('idea_file', '')
    if not idea_file:
        return jsonify({'ok': False, 'error': 'Missing idea_file'}), 400
    try:
        if not runner.retry_enhance_idea(idea_file):
            return jsonify({'ok': False, 'error': 'Idea not found in pool'}), 404
        return jsonify({'ok': True, 'msg': f'Enhance retry requested for {idea_file}'})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


@app.route('/api/pipeline/<pipeline_id>/log', methods=['GET'])
def api_pipeline_log(pipeline_id):
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404
    n = request.args.get('n', 50, type=int)
    phase = request.args.get('phase', '')
    logs = runner.get_activity_log(n)
    if phase:
        logs = [e for e in logs if e.get('phase') == phase]
    return jsonify({'ok': True, 'log': logs})


@app.route('/api/pipeline/<pipeline_id>/stream')
def api_pipeline_stream(pipeline_id):
    """SSE endpoint for real-time pipeline log streaming."""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _get_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': 'Pipeline not found'}), 404

    q = runner.subscribe()

    def generate():
        try:
            while True:
                try:
                    item = q.get(timeout=30)
                except Exception:
                    # Send heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
                    continue

                if isinstance(item, dict) and item.get('__event__') == 'done':
                    yield f"event: done\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            runner.unsubscribe(q)

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/api/pipeline/<pipeline_id>/delete', methods=['POST'])
def api_pipeline_delete(pipeline_id):
    """永久删除流水线（含本地文件）。"""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    ok = _delete_pipeline(pipeline_id)
    if not ok:
        return jsonify({'ok': False, 'error': '流水线不存在'}), 404
    return jsonify({'ok': True})


@app.route('/api/pipeline/<pipeline_id>/archive', methods=['POST'])
def api_pipeline_archive(pipeline_id):
    """归档流水线（从活跃列表移除，文件保留）。"""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    ok = _archive_pipeline(pipeline_id)
    if not ok:
        return jsonify({'ok': False, 'error': '流水线不存在或仍在运行'}), 404
    return jsonify({'ok': True})


@app.route('/api/pipeline/<pipeline_id>/restore', methods=['POST'])
def api_pipeline_restore(pipeline_id):
    """恢复归档流水线到活跃列表。"""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    runner = _restore_pipeline(pipeline_id)
    if not runner:
        return jsonify({'ok': False, 'error': '归档流水线不存在或文件丢失'}), 404
    return jsonify({'ok': True, 'pipeline_id': pipeline_id})


@app.route('/api/pipeline/archived', methods=['GET'])
def api_pipeline_archived():
    """列出所有归档流水线。"""
    if not _pipeline_available:
        return jsonify({'ok': False, 'error': 'Pipeline runner not available'}), 503
    return jsonify({'ok': True, 'archived': _list_archived()})


if __name__ == '__main__':
    def perform_network_diagnostics():
        """Proactively checks for common Windows environment issues (Errno 2/Proxy)."""
        print("🔍 正在进行环境预检...")
        try:
            import httpx
            # Attempt to init standard client. This often triggers the Errno 2 on broken Windows envs
            with httpx.Client() as client:
                pass
            return {"use_secure_client": False}
        except Exception as e:
            # Check for specific "No such file" error (Errno 2)
            err_msg = str(e)
            if "[Errno 2]" in err_msg or "No such file" in err_msg or "proxy" in err_msg.lower():
                print(f"⚠️  预检发现环境配置异常: {e}")
                print("➡️  已自动启用：【环境隔离模式】（将清洗代理和证书变量）")
                return {"use_secure_client": True}
            return {"use_secure_client": False}

    # 1. Proactive Diagnostics
    diag_result = perform_network_diagnostics()

    # 2. Force clean environment variables if issues detected
    # This ensures any subprocesses spawned by Flask also run in a clean environment
    if diag_result.get("use_secure_client"):
        print("🛜 正在为所有子进程净化环境变量...")
        keys_to_remove = [
            'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 
            'http_proxy', 'https_proxy', 'all_proxy',
            'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE'
        ]
        
        for key in keys_to_remove:
            if key in os.environ:
                print(f"   - 移除: {key}")
                del os.environ[key]

    # 首次在有桌面的平台运行时，询问是否创建桌面快捷方式（Brain工作站），
    # 创建/询问过一次后不再重复（标记文件 ~/.quantflow/brain_workstation_shortcut.json）
    _ensure_desktop_shortcut()

    print("Starting BRAIN Expression Template Decoder Web Application...")
    print("Starting in safe mode: binding only to localhost (127.0.0.1)")
    # Allow an explicit override only via an environment variable (not recommended)
    bind_host = os.environ.get('BRAIN_BIND_HOST', '127.0.0.1')
    if bind_host not in ('127.0.0.1', 'localhost'):
        print(f"Refusing to bind to non-localhost address: {bind_host}")
        print("To override (not recommended), set environment variable BRAIN_BIND_HOST")
        sys.exit(1)

    def _port_is_free(host, port, timeout=0.4):
        """Return True if we can bind (host, port) right now."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.bind((host, port))
            return True
        except OSError:
            return False

    def _open_browser_later(url, delay=1.2):
        """Open the web browser shortly after the server starts (opt out via BRAIN_NO_BROWSER=1)."""
        if os.environ.get('BRAIN_NO_BROWSER') == '1':
            return

        def _open():
            try:
                time.sleep(delay)
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=_open, daemon=True).start()

    # macOS: port 5000 is often already taken by AirPlay Receiver (ControlCenter).
    # Try 5000 first and automatically fall back to the next free ports.
    start_port = int(os.environ.get('BRAIN_PORT', '5000') or 5000)
    last_error = None
    print("BRAIN API integration included - no separate proxy needed!")
    try:
        for port in range(start_port, start_port + 11):
            if not _port_is_free(bind_host, port):
                print(f"⚠️  Port {port} is already in use (macOS AirPlay Receiver commonly occupies 5000). Trying port {port + 1}...")
                continue
            url = f'http://{bind_host}:{port}'
            print(f"Application will run on {url}")
            print("Opening browser automatically... (set BRAIN_NO_BROWSER=1 to disable)")
            _open_browser_later(url)
            try:
                app.run(debug=False, use_reloader=False, host=bind_host, port=port)
                break  # Server shut down normally
            except OSError as exc:
                last_error = exc
                print(f"⚠️  Could not bind to {bind_host}:{port} ({exc}); trying next port...")
                continue
        else:
            print(f"❌ Could not bind to any port in {start_port}-{start_port + 10}: {last_error}")
            sys.exit(1)
    finally:
        # Stop Cell/Claude processes and pause armed interval schedules on clean exit.
        try:
            from quantflow import shutdown_quantflow_runtime
            summary = shutdown_quantflow_runtime('Flask 退出', pause_all_schedules=True)
            print(
                f"QuantFlow shutdown: stopped_runs={summary.get('stopped_runs', 0)} "
                f"paused_intervals={summary.get('paused_intervals', 0)}"
            )
        except Exception as exc:
            print(f"QuantFlow shutdown hook failed: {exc}")
