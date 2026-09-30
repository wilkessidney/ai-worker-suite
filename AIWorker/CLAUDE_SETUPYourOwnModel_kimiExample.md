# WorldQuant BRAIN & Claude Code 全套环境搭建指南

本文档记录了从零开始搭建 WorldQuant BRAIN 开发环境（集成 Claude Code、Moonshot/DeepSeek 模型及 MCP 工具）的完整步骤。

## 0. 基础环境准备 (Prerequisites)

在运行任何脚本之前，请确保已安装 **Node.js** 和 **Python**。

我们提供了一个脚本来自动检查并安装这两者：
```powershell
.\Step0_ensure_prerequisites.ps1
```

### 安装 Claude Code CLI
打开 PowerShell 运行：
```powershell
# 全局安装 (使用国内镜像)
npm install -g @anthropic-ai/claude-code --registry=https://registry.npmmirror.com

# 验证安装
claude --version
```

### 初始化 Claude 配置 (仅需一次)
运行以下命令以生成配置文件，跳过可能因网络问题导致的向导卡死：
```powershell
node --eval "const fs=require('fs');const p=require('path').join(require('os').homedir(),'.claude.json');const c=fs.existsSync(p)?JSON.parse(fs.readFileSync(p,'utf8')):{};c.hasCompletedOnboarding=true;fs.writeFileSync(p,JSON.stringify(c,null,2));console.log('配置已初始化: '+p);"
```

---

## 1. 项目初始化 (Step 1)

我们使用 `Step1_init_project_files.py` 脚本自动拉取核心文件并安装依赖。

### 运行初始化脚本
```powershell
python Step1_init_project_files.py
```
**此脚本会自动执行以下操作：**
1.  安装/更新 `cnhkmcp` Python 包。
2.  将 `forum_functions.py`, `platform_functions.py`, `brain-consultant.md` 等核心文件复制到当前目录。
3.  **自动运行** `配置前运行我_安装必要依赖包.py`，安装 `playwright`, `pandas` 等必要库。

---

## 2. 配置 Brain Consultant 角色 (Step 2)

将 WorldQuant BRAIN 专家角色文件安装到 Claude 的配置目录中。

### 运行角色配置脚本
```powershell
.\Step2_config_brainSystemPrompt_Toclaude.ps1
```
**此脚本会自动执行以下操作：**
1.  找到当前目录下的 `brain-consultant.md`。
2.  将其复制到 `C:\Users\<你的用户名>\.claude\agents` 目录下。

---

## 3. 注册 BRAIN MCP 服务 (Step 3)

将本地的 `platform_functions.py` 注册为 Claude 的 MCP 工具服务。

### 运行注册脚本
```powershell
.\Step3_setup_mcp.ps1
```
**此脚本会自动执行以下操作：**
1.  检测当前目录路径。
2.  移除旧的 `brain-mcp` 配置（防止路径错误）。
3.  将当前目录下的 `platform_functions.py` 注册为新的 `brain-mcp` 服务。

---

## 4. 配置模型与 API (Step 4)

使用交互式脚本配置 Kimi (Moonshot) 或 DeepSeek 模型。

### 运行配置脚本
```powershell
python Step4_SetAPI_And_Check_MoonShot.py
```
**此脚本会自动执行以下操作：**
1.  询问您选择 **Kimi** 还是 **DeepSeek**。
2.  验证您的 API Key 并拉取在线模型列表。
3.  让您选择默认模型（如 `deepseek-chat` 或 `kimi-k1.5-preview`）。
4.  自动设置所有必要的 Windows 环境变量。

*注意：运行完此步后，请**重启终端**以使环境变量生效。*

---

## 5. 开始使用 (Usage)

完成以上所有步骤后，您就可以启动带有 **BRAIN 顾问专家** 人格的 Claude 了。

### 启动命令
```powershell
claude --agent brain-consultant
```

*   **验证**：启动后，可以尝试问它 "What is a Pyramid in BRAIN?"，看它是否能根据专家知识回答。
*   **工具使用**：输入 `/mcp` 检查工具状态，或直接要求它 "Login to BRAIN platform"。

---

## 6. 迁移指南 (Portability)

如果您将此文件夹复制到新电脑：
1.  运行 `.\Step0_ensure_prerequisites.ps1` (一键安装 Node/Python/Claude CLI)。
2.  运行 `python Step1_init_project_files.py` (恢复文件和依赖)。
3.  运行 `.\Step2_config_brainSystemPrompt_Toclaude.ps1` (安装角色)。
if ($LASTEXITCODE -eq 0) {
4.  运行 `.\Step3_setup_mcp.ps1` (注册 MCP服务)。
5.  运行 `python Step4_SetAPI_And_Check_MoonShot.py` (配置 Key 和模型)。
6.  配置完成后，**重启终端**。
7.  使用 `claude --agent brain-consultant` 启动。

---

## 7. 生成便携安装包 (Builder)

如果您想制作一个“一键安装包”分发给其他从未配置过环境的电脑，可以使用构建脚本生成 EXE 安装程序。

### 运行构建脚本
```powershell
python build_installer.py
```
**此脚本会自动执行以下操作：**
1.  安装 `PyInstaller` (如果未安装)。
2.  将所有必要文件（Step脚本、Python代码、Markdown文档、Skills文件夹）打包。
3.  自动修改 `Step1` 逻辑，使其在安装包模式下优先使用本地打包的资源，而非在线下载。
4.  在 `dist/` 目录下生成 **`BRAIN_Project_Setup.exe`**。

### 如何使用生成的安装包
1.  将 **`BRAIN_Project_Setup.exe`** 复制到新电脑。
2.  双击运行，选择一个空文件夹作为安装目录（例如 `C:\BRAIN_Project`）。
3.  程序会自动释放文件，并打开 PowerShell 窗口。
4.  在打开的窗口中，直接按照 **步骤 0 (Step 0)** 开始执行即可。
    *   *注意：安装包已包含经过修改的 `Step1`，它会自动处理无需联网拉取核心包的逻辑。*
