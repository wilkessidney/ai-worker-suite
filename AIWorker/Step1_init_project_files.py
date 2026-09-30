import os
import shutil
import sys
import subprocess
from pathlib import Path
import importlib.util
import site


def run_uv_sync():
    """使用 uv sync 基于 pyproject.toml 创建 .venv 并安装所有依赖"""
    if not shutil.which("uv"):
        print("❌ uv 未找到。请先运行 install.sh 安装 uv")
        print("   手动安装: curl -LsSf https://astral.sh/uv/install.sh | sh")
        sys.exit(1)

    print("正在使用 uv sync 创建虚拟环境并安装依赖...")
    result = subprocess.run(["uv", "sync"], cwd=Path.cwd())
    if result.returncode != 0:
        print("❌ uv sync 失败，请检查网络连接或镜像源配置")
        print("   可尝试手动运行: uv sync")
        sys.exit(1)
    print("✅ uv sync 完成")


def get_package_path(package_name):
    importlib.invalidate_caches()
    spec = importlib.util.find_spec(package_name)
    if spec and spec.origin:
        return Path(spec.origin).parent
    # Fallback search
    try:
        for site_pkg in site.getsitepackages():
            p = Path(site_pkg) / package_name
            if p.exists():
                return p
    except:
        pass
    return None


def copy_project_files(pkg_path, project_dir):
    """从 cnhkmcp 包复制项目文件"""
    untracked_dir = pkg_path / "untracked"

    # Files to copy
    files = ["forum_functions.py", "platform_functions.py", "brain-consultant.md"]
    for filename in files:
        src = untracked_dir / filename
        dst = project_dir / filename
        if src.exists():
            shutil.copy2(src, dst)
            print(f"✅ 已复制: {filename}")

    # Copy untracked folder
    try:
        shutil.copytree(untracked_dir, project_dir / "untracked", dirs_exist_ok=True)
        print("✅ untracked 文件夹已复制")
    except:
        pass

    # Copy skills to global ~/.claude/skills/ (skills 需要全局可用)
    src_skills = untracked_dir / "skills"
    dst_skills = Path.home() / ".claude" / "skills"
    if src_skills.exists():
        try:
            if not dst_skills.parent.exists():
                dst_skills.parent.mkdir(parents=True)
            shutil.copytree(src_skills, dst_skills, dirs_exist_ok=True)
            print("✅ Skills 文件夹已同步到全局 ~/.claude/skills/")
        except:
            pass

    # 将项目内的技能包同步到全局 ~/.claude/skills/
    project_skill_dirs = ["ai-worker-skill", "spc-prompt-writer"]
    for skill_name in project_skill_dirs:
        src_skill = Path(__file__).resolve().parent / skill_name
        if not src_skill.exists():
            continue
        try:
            dst_skills.mkdir(parents=True, exist_ok=True)
            dst_skill = dst_skills / skill_name
            if dst_skill.is_symlink():
                dst_skill.unlink()
            elif dst_skill.exists():
                shutil.rmtree(dst_skill)
            shutil.copytree(src_skill, dst_skill)
            print(f"✅ {skill_name} 已同步到全局 ~/.claude/skills/")
        except Exception as e:
            print(f"⚠️ {skill_name} 同步失败: {e}")

    # 将 settings.json 复制到项目级 .claude/（而非全局 ~/.claude/）
    dst_claude = project_dir / ".claude"
    dst_claude.mkdir(parents=True, exist_ok=True)

    if (project_dir / "settings.json").exists():
        dst_set = dst_claude / "settings.json"
        shutil.copy2(str(project_dir / "settings.json"), str(dst_set))
        print("✅ settings.json 已复制到项目级 .claude/")

    # 将 hooks 复制到项目级 .claude/
    if (project_dir / "hooks").exists():
        dst_hooks = dst_claude / "hooks"
        if dst_hooks.exists():
            shutil.rmtree(dst_hooks)
        shutil.copytree(str(project_dir / "hooks"), str(dst_hooks))
        print("✅ hooks 已复制到项目级 .claude/")


def get_venv_python(project_dir):
    """Return the venv interpreter path (cross-platform), or None."""
    for candidate in (
        project_dir / ".venv" / "bin" / "python",          # Mac/Linux
        project_dir / ".venv" / "Scripts" / "python.exe",  # Windows
    ):
        if candidate.exists():
            return candidate
    return None


def verify_installation(project_dir):
    """验证安装结果"""
    venv_python = get_venv_python(project_dir)
    if venv_python:
        print(f"\n✅ 虚拟环境: {venv_python}")
        # 检查关键包
        for pkg in ["cnhkmcp", "requests", "pandas", "openai", "flask"]:
            result = subprocess.run(
                [str(venv_python), "-c",
                 f"import {pkg}; print({pkg}.__version__ if hasattr({pkg}, '__version__') else 'OK')"],
                capture_output=True, text=True
            )
            status = "✅" if result.returncode == 0 else "❌"
            version = result.stdout.strip() if result.returncode == 0 else "未安装"
            print(f"  {status} {pkg}: {version}")
    else:
        print("⚠️ 虚拟环境未创建，请检查 uv sync 是否成功")


def main():
    project_dir = Path.cwd()

    # Step 1: 使用 uv sync 安装依赖
    run_uv_sync()

    # Step 2: 定位 cnhkmcp 包
    venv_python = get_venv_python(project_dir)
    if venv_python:
        # 使用 venv 中的 python 来找包路径
        result = subprocess.run(
            [str(venv_python), "-c",
             "import cnhkmcp; from pathlib import Path; print(Path(cnhkmcp.__file__).parent)"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            pkg_path = Path(result.stdout.strip())
        else:
            pkg_path = get_package_path("cnhkmcp")
    else:
        pkg_path = get_package_path("cnhkmcp")

    if not pkg_path:
        print("❌ 无法找到 cnhkmcp 包安装路径")
        sys.exit(1)

    print(f"cnhkmcp 安装位置: {pkg_path}")

    # Step 3: 文件复制
    copy_project_files(pkg_path, project_dir)

    # Step 4: 验证安装
    verify_installation(project_dir)


if __name__ == "__main__":
    main()
