=== BRAIN CLI 助手安装说明 (Mac/Linux 版) ===

【安装方式】
1. 打开终端（Mac: 访达 → 应用程序 → 实用工具 → 终端）
2. 进入此文件夹：cd /path/to/Brain_工具一键安装_MacLinux版本
3. 给脚本添加执行权限：chmod +x _auto_setup.sh
4. 运行一键安装：./_auto_setup.sh
5. 按提示完成配置（BRAIN 平台账号密码（必填）、API Key、可选知识库等）
6. 安装完成后，关闭终端重新打开

【启动方式】
1. 打开终端
2. 进入安装目录：cd /path/to/Brain_工具一键安装_MacLinux版本
3. 启动助手：claude --agent brain-consultant

【需要准备】
- BRAIN 平台账号密码（必填，安装时会强制配置，用于知识库、Osmosis 和 MCP 工具）
- LLM API Key

【Hook 说明】
- .claude/settings.json 是一个 hook 配置文件
- 它会在 simulate alpha 之后自动检查表达式语法
- 如果不需要，可以用 /hooks 命令禁用

【常见问题】
Q: 提示 "permission denied"
A: 运行 chmod +x _auto_setup.sh 添加执行权限

Q: uv 安装失败
A: 手动安装：curl -LsSf https://astral.sh/uv/install.sh | sh

Q: Claude CLI 安装失败
A: 手动安装：npm install -g @anthropic-ai/claude-code

Q: 镜像源连接超时
A: 检查网络连接，或手动设置：export UV_DEFAULT_INDEX="https://pypi.org/simple"

Q: 知识库创建失败 / 提示缺少账号密码
A: 账号密码在安装时已强制配置（Step3），可稍后单独运行：
   .venv/bin/python Step5_create_knowledge_base.py
   若提示缺少账号，先运行: .venv/bin/python Step3_set_brain_credentials.py

Q: BRAIN 账号配置失败或需要更换账号
A: 重新运行: .venv/bin/python Step3_set_brain_credentials.py
