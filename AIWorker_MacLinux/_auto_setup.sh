#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  BRAIN Project 一键安装 (Mac/Linux)"
echo "=========================================="
echo ""

# ==========================================================
# [1/5] 前置环境检查
# ==========================================================
echo "[1/5] 检查基础环境 (Node.js / uv / Claude CLI)..."
echo "  ℹ️  Python 3.12 将在 uv sync 时自动安装"
bash "$SCRIPT_DIR/install.sh"
# install.sh 已经 set -e，失败会退出

# 刷新 PATH（install.sh 中安装的工具可能不在当前 PATH 中）
export PATH="$HOME/.local/bin:$PATH"

# 显式刷新 Homebrew 环境（Mac 首次安装时 install.sh 子 shell 的环境不会传回）
if [[ "$OSTYPE" == "darwin"* ]]; then
    if [ -x "/opt/homebrew/bin/brew" ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x "/usr/local/bin/brew" ]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi

# npm 全局安装路径（Claude CLI 可能在这里）
NPM_GLOBAL_BIN="$(npm config get prefix 2>/dev/null)/bin"
if [ -d "$NPM_GLOBAL_BIN" ]; then
    export PATH="$NPM_GLOBAL_BIN:$PATH"
fi

# 尝试 source shell rc 文件刷新
if [ -f "$HOME/.zshrc" ]; then source "$HOME/.zshrc" 2>/dev/null || true; fi
if [ -f "$HOME/.bashrc" ]; then source "$HOME/.bashrc" 2>/dev/null || true; fi

# ==========================================================
# [2/5] 虚拟环境初始化 + 文件复制
# ==========================================================
echo ""
echo "[2/5] 初始化虚拟环境..."

# 重新检测镜像源（install.sh 子 shell 中的 export 不会传回）
detect_fastest_mirror() {
    for mirror in \
        "https://pypi.tuna.tsinghua.edu.cn/simple" \
        "https://mirrors.aliyun.com/pypi/simple/" \
        "https://pypi.org/simple"; do
        if curl -s --connect-timeout 3 "$mirror" > /dev/null 2>&1; then
            echo "$mirror"
            return 0
        fi
    done
    echo "https://pypi.org/simple"
}
export UV_DEFAULT_INDEX=$(detect_fastest_mirror)

# 使用 uv run 运行 Step1（uv 会自动使用其管理的 Python）
uv run --python 3.12 --directory "$SCRIPT_DIR" python "$SCRIPT_DIR/Step1_init_project_files.py"

# 验证虚拟环境
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ 虚拟环境创建失败"
    exit 1
fi
echo "✅ 虚拟环境已就绪: $VENV_PYTHON"

# ==========================================================
# [3/5] Agent 角色配置 + MCP 服务注册
# ==========================================================
echo ""
echo "[3/5] 配置 BRAIN 顾问角色 & MCP 工具服务..."

# 3a. 复制 brain-consultant.md 到项目级 .claude/agents/
AGENTS_DIR="$SCRIPT_DIR/.claude/agents"
mkdir -p "$AGENTS_DIR"
if [ -f "$SCRIPT_DIR/brain-consultant.md" ]; then
    cp "$SCRIPT_DIR/brain-consultant.md" "$AGENTS_DIR/"
    echo "  ✅ brain-consultant.md 已安装"
else
    echo "  ⚠️ brain-consultant.md 未找到，跳过"
fi

# 3b. MCP 服务注册（项目级）
echo "  正在注册 MCP 工具服务..."
claude mcp remove brain-mcp 2>/dev/null || true
claude mcp add --transport stdio --scope project brain-mcp -- \
    "$VENV_PYTHON" "$SCRIPT_DIR/platform_functions.py"

# 3d. 后处理 .mcp.json（添加 timeout 和 description）
if [ -f "$SCRIPT_DIR/.mcp.json" ]; then
    "$VENV_PYTHON" -c "
import json
from pathlib import Path

config_path = Path('$SCRIPT_DIR/.mcp.json')
with open(config_path, 'r') as f:
    config = json.load(f)

if 'mcpServers' not in config:
    config['mcpServers'] = {}
if 'brain-mcp' not in config['mcpServers']:
    config['mcpServers']['brain-mcp'] = {}

brain_mcp = config['mcpServers']['brain-mcp']
brain_mcp['timeout'] = 900
brain_mcp['description'] = 'WorldQuant BRAIN Platform MCP Server'

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
print('  ✅ MCP 配置已更新 (timeout=900)')
"
fi

# ==========================================================
# [4/5] API 模型配置（交互式）
# ==========================================================
echo ""
echo "[4/5] 配置 AI 模型 (API Key)..."
echo "  即将启动交互式配置，请按提示输入您的 API 信息"
echo ""
"$VENV_PYTHON" "$SCRIPT_DIR/Step4_SetAPI_And_Check_LLMModel.py"

# ==========================================================
# [+] 可选：知识库创建
# ==========================================================
echo ""
echo "[+] 创建 BRAIN 知识库（可选）"
echo "  知识库包含 BRAIN 平台的操作符、数据集和文档，可帮助 AI 更好地辅助您"
echo ""
read -p "  是否现在创建知识库？需要 BRAIN 平台账号密码 (y/n，默认 n): " -r create_kb
create_kb=${create_kb:-n}

if [[ "$create_kb" == "y" || "$create_kb" == "Y" ]]; then
    echo "  正在启动知识库创建工具..."
    set +e
    "$VENV_PYTHON" "$SCRIPT_DIR/Step5_create_knowledge_base.py"
    kb_exit_code=$?
    set -e
    if [ $kb_exit_code -ne 0 ]; then
        echo "  ⚠️ 知识库创建失败，您可以稍后手动运行："
        echo "     $VENV_PYTHON Step5_create_knowledge_base.py"
    else
        echo "  ✅ 知识库创建成功！"
    fi
else
    echo "  跳过。您可以稍后运行: $VENV_PYTHON Step5_create_knowledge_base.py"
fi

# ==========================================================
# 完成提示
# ==========================================================
echo ""
echo "=========================================="
echo "  🎉 所有安装步骤已完成！"
echo "=========================================="
echo ""
echo "  请先重启终端（关闭后重新打开），然后："
echo ""
echo "  1. cd $SCRIPT_DIR"
echo "  2. claude --agent brain-consultant"
echo ""
echo "  按回车键关闭..."
read
