#!/bin/bash
set -e

echo "=== Brain Project 环境检查 (Mac/Linux) ==="
echo ""

# ── Anaconda/Miniconda 冲突隔离 ──
if echo "$PATH" | grep -qiE "anaconda|miniconda"; then
    echo "⚠️  检测到 Anaconda/Miniconda 可能导致冲突，临时隔离..."
    CLEAN_PATH=$(echo "$PATH" | tr ':' '\n' | grep -viE "anaconda|miniconda" | tr '\n' ':' | sed 's/:$//')
    export PATH="$CLEAN_PATH"
    echo "   已从 PATH 中临时移除 Anaconda/Miniconda 路径"
    echo ""
fi

# ── 前置工具检查：curl ──
if ! command -v curl &> /dev/null; then
    echo "🔸 curl 未找到，正在安装..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y curl
    elif command -v yum &> /dev/null; then
        sudo yum install -y curl
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y curl
    elif command -v pacman &> /dev/null; then
        sudo pacman -Sy --noconfirm curl
    else
        echo "❌ 无法自动安装 curl，请手动安装后重试。"
        exit 1
    fi
    if ! command -v curl &> /dev/null; then
        echo "❌ curl 安装失败。"
        exit 1
    fi
    echo "✅ curl 已安装"
fi

# ── Helper: Install Homebrew and Node on Mac ──
install_homebrew_mac() {
    echo "🍺 Homebrew not found. Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Activate brew for current session
    if [[ -d "/opt/homebrew/bin" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -d "/usr/local/bin" ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
}

# ── [1/4] Node.js 检查安装 ──
echo "[1/4] 检查 Node.js ..."
if ! command -v node &> /dev/null; then
    echo "🔸 Node.js 未找到，正在安装..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if ! command -v brew &> /dev/null; then install_homebrew_mac; fi
        echo "📦 Installing Node.js via Homebrew..."
        brew install node
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command -v apt-get &> /dev/null; then
            sudo apt-get update
            sudo apt-get install -y nodejs npm
        else
            echo "❌ 无法自动安装 Node.js，请手动安装。"
            exit 1
        fi
    fi
    if ! command -v node &> /dev/null; then echo "❌ Node.js 安装失败。"; exit 1; fi
fi
echo "✅ Node.js: $(node -v)"
echo ""

# ── [2/4] uv 检查安装 ──
echo "[2/4] 检查 uv ..."
if ! command -v uv &> /dev/null; then
    echo "🔸 uv 未找到，正在安装..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # 将 ~/.local/bin 加入当前 session PATH
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &> /dev/null; then echo "❌ uv 安装失败。"; exit 1; fi
fi
echo "✅ uv: $(uv --version)"
echo ""

echo "  ℹ️  Python 3.12 将在 uv sync 时自动安装（无需单独检查）"
echo ""

# ── [3/4] Claude CLI 检查安装 ──
echo "[3/4] 检查 Claude CLI ..."
if ! command -v claude &> /dev/null; then
    echo "🔸 Claude CLI 未找到，正在安装..."
    npm config set registry https://registry.npmmirror.com/
    # 判断 npm 全局目录是否有写入权限，决定是否需要 sudo
    NPM_PREFIX="$(npm config get prefix 2>/dev/null)"
    if [ -w "$NPM_PREFIX/lib" ] 2>/dev/null; then
        npm install -g @anthropic-ai/claude-code
    else
        echo "  ℹ️  全局安装需要管理员权限..."
        sudo npm install -g @anthropic-ai/claude-code --unsafe-perm=true --allow-root
    fi
    if ! command -v claude &> /dev/null; then echo "❌ Claude CLI 安装失败。"; exit 1; fi
fi
echo "✅ Claude CLI: $(claude --version)"
echo ""

# ── [4/4] PyPI 镜像源自动检测 ──
echo "[4/4] 正在检测最快的 PyPI 镜像源..."

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

FASTEST_MIRROR=$(detect_fastest_mirror)
export UV_DEFAULT_INDEX="$FASTEST_MIRROR"
echo "✅ 已选择镜像源: $FASTEST_MIRROR"
echo ""

echo "============================================"
echo "✅ 所有前置依赖已就绪"
echo "============================================"
