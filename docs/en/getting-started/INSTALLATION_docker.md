[**Getting Started**](./getting-started.md) > **Installation** > **Docker** _(current)_

---

### Install PDFMathTranslate via docker

#### What is docker?

[Docker](https://docs.docker.com/get-started/docker-overview/) is an open platform for developing, shipping, and running applications. Docker enables you to separate your applications from your infrastructure so you can deliver software quickly. With Docker, you can manage your infrastructure in the same ways you manage your applications. By taking advantage of Docker's methodologies for shipping, testing, and deploying code, you can significantly reduce the delay between writing code and running it in production.

#### Installation

<h4>1. Build and run from this repository:</h4>

```bash
cp .env.example .env
docker compose build
docker compose up -d
```

> [!NOTE]
>
> The repository `Dockerfile` builds the React frontend at image-build time and starts the WebUI with `--server-host 0.0.0.0`, which makes it suitable for cloud servers and container port publishing.

<h4>2. Or pull and run a published image directly:</h4>

```bash
docker pull awwaawwa/pdfmathtranslate-next
docker run -d --name pdf2zh-next -p 7860:7860 awwaawwa/pdfmathtranslate-next pdf2zh --gui --server-host 0.0.0.0
```

> [!NOTE]
>
> If you cannot access Docker Hub, try the image on [GitHub Container Registry](https://github.com/PDFMathTranslate/PDFMathTranslate-next/pkgs/container/pdfmathtranslate).
>
> ```bash
> docker pull ghcr.io/PDFMathTranslate/PDFMathTranslate-next
> docker run -d --name pdf2zh-next -p 7860:7860 ghcr.io/PDFMathTranslate/PDFMathTranslate-next pdf2zh --gui --server-host 0.0.0.0
> ```

<h4>3. Enter this URL in your browser to open the WebUI page:</h4>

```
http://127.0.0.1:17860/
```

The included compose file binds the service to `127.0.0.1:17860` by default. Change `.env` if you need another host port:

```bash
PDF2ZH_BIND_IP=127.0.0.1
PDF2ZH_WEB_PORT=17860
```

If you are connecting through a reverse proxy, proxy to `127.0.0.1:17860`. If you really want to expose the container directly on the public network, set `PDF2ZH_BIND_IP=0.0.0.0`.

> [!NOTE]
>
> The included `docker-compose.yml` persists:
>
> - `./data/config` for saved WebUI settings and default config files
> - `./data/output` for uploaded PDFs and generated artifacts

> [!NOTE]
> If you encounter any issues during use WebUI, please refer to [Usage --> WebUI](./USAGE_webui.md).

> [!NOTE]
> If you encounter any issues during use command line, please refer to [Usage --> Command Line](./USAGE_commandline.md).
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
