[**开始使用**](./getting-started.md) > **如何安装** > **Docker** _(当前)_

---

### 通过 docker 安装 PDFMathTranslate

#### 什么是 docker？

[Docker](https://docs.docker.com/get-started/docker-overview/) 是一个用于开发、运输和运行应用程序的开放平台。Docker 使您能够将应用程序与基础设施分离，从而可以快速交付软件。通过 Docker，您可以用管理应用程序的方式来管理基础设施。利用 Docker 的代码运输、测试和部署方法，您可以显著减少编写代码与在生产环境中运行代码之间的延迟。

#### 如何安装

<h4>1. 直接使用当前仓库构建并运行：</h4>

```bash
cp .env.example .env
docker compose build
docker compose up -d
```

> [!NOTE]
>
> 仓库内置的 `Dockerfile` 会在镜像构建阶段完成 React 前端构建，并以 `pdf2zh --gui --server-host 0.0.0.0` 启动 WebUI，更适合云服务器部署。

<h4>2. 或者直接拉取镜像运行：</h4>

```bash
docker pull awwaawwa/pdfmathtranslate-next
docker run -d --name pdf2zh-next -p 7860:7860 awwaawwa/pdfmathtranslate-next pdf2zh --gui --server-host 0.0.0.0
```

> [!NOTE]
>
> 如果无法访问 Docker Hub，请尝试使用 [GitHub Container Registry](https://github.com/PDFMathTranslate/PDFMathTranslate-next/pkgs/container/pdfmathtranslate) 上的镜像。
>
> ```bash
> docker pull ghcr.io/PDFMathTranslate/PDFMathTranslate-next
> docker run -d --name pdf2zh-next -p 7860:7860 ghcr.io/PDFMathTranslate/PDFMathTranslate-next pdf2zh --gui --server-host 0.0.0.0
> ```

<h4>3. 在浏览器中打开以下地址进入 WebUI 页面：</h4>

```
http://127.0.0.1:17860/
```

仓库内置的 compose 默认会把服务绑定到宿主机 `127.0.0.1:17860`。如果需要换端口，可以修改 `.env`：

```bash
PDF2ZH_BIND_IP=127.0.0.1
PDF2ZH_WEB_PORT=17860
```

如果你前面有 Nginx 或 Caddy，就把它反向代理到 `127.0.0.1:17860`。只有在你明确要直接暴露容器端口时，才把 `PDF2ZH_BIND_IP` 改成 `0.0.0.0`。

> [!NOTE]
>
> 仓库中的 `docker-compose.yml` 会持久化以下目录：
>
> - `./data/config`：保存 WebUI 默认配置和已保存设置
> - `./data/output`：保存上传文件与翻译结果

> [!NOTE]
> 如果在使用 WebUI 时遇到任何问题，请参考 [如何使用 --> WebUI](./USAGE_webui.md)。

> [!NOTE]
> 如果在使用命令行时遇到任何问题，请参考 [如何使用 --> 命令行](./USAGE_commandline.md)。
<!-- 
#### For docker deployment on cloud service:

<div>
<a href="https://www.heroku.com/deploy?template=https://github.com/PDFMathTranslate/PDFMathTranslate-next">
  <img src="https://www.herokucdn.com/deploy/button.svg" alt="Deploy" height="26"></a>
<a href="https://render.com/deploy">
  <img src="https://render.com/images/deploy-to-render-button.svg" alt="Deploy to Koyeb" height="26"></a>
<a href="https://zeabur.com/templates/5FQIGX?referralCode=reycn">
  <img src="https://zeabur.com/button.svg" alt="Deploy on Zeabur" height="26"></a>
<a href="https://app.koyeb.com/deploy?type=git&builder=buildpack&repository=github.com/PDFMathTranslate/PDFMathTranslate-next&branch=main&name=pdf-math-translate">
  <img src="https://www.koyeb.com/static/images/deploy/button.svg" alt="Deploy to Koyeb" height="26"></a>
</div>

-->

<div align="right"> 
<h6><small>本页面的部分内容由 GPT 翻译，可能包含错误。</small></h6>
