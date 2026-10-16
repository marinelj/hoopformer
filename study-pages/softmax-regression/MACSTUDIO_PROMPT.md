请在这台 Mac Studio 上，把仓库 [marinelj/hoopformer](https://github.com/marinelj/hoopformer) 的 `main` 分支中的 `study-pages/softmax-regression/softmax-regression-study.html` 部署到这边的 Jupyter Server，并给我可点击的访问链接。请实际完成部署与验证。

- 找到本机仓库并读取适用的 `AGENTS.md`，获取 `origin/main` 的最新文件，再读取该 HTML，确认它是讲解 softmax、交叉熵、L2 正则和梯度下降的完整学习页。保留已有未提交修改；若当前工作区不便更新，可以从 `origin/main` 提取该文件到独立部署目录。
- 查找正在运行的 Jupyter 服务，确认它的根目录、地址、端口和 `base_url`，优先复用。若 HTML 已位于服务根目录内，直接使用；否则把它复制到根目录下的 `study-pages/softmax-regression/`。如果目标文件已有不同内容，先备份。保留其他 notebook、运行中的 kernel 和服务配置；若没有可用的 Jupyter 服务，再启动一个。
- 通过 Jupyter 的 `/files/` 路由展示 HTML 页面，保留内嵌 CSS、JavaScript 和所有交互；无需安装前端依赖，也无需运行页面里的 Python 示例。不要为了展示页面而关闭认证或修改安全策略。
- 实际打开部署后的页面，验证 HTTP 响应、七步推导面板的展开与收起、数值例子和 `320px` 手机布局；确认显示的是完整网页。验证时处理现有认证，避免把 token 写进仓库。
- 完成后给出完整访问 URL、部署文件路径及使用的 Jupyter 地址和端口。优先沿用现有可从我的浏览设备访问的主机名或 IP；不要把 `localhost` 或 `127.0.0.1` 当作跨设备访问地址。如果当前只能本机访问，请明确说明可访问范围。
