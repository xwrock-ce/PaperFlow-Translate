[**Getting Started**](./getting-started.md) > **Installation** > **WebUI** _(current)_

---

### Use PDFMathTranslate via Webui

#### How to open the WebUI page:

There are several methods to open the WebUI interface. If you are using **Windows**, please refer to [this article](./INSTALLATION_winexe.md);

1. Python installed (3.10 <= version < 3.14)

2. Install our package:

   Follow [Installation via uv](./INSTALLATION_uv.md), or use the [Windows EXE](./INSTALLATION_winexe.md) / [Docker](./INSTALLATION_docker.md) guide if that matches your environment.

3. Start using in browser:

    ```bash
    pdf2zh_next --gui
    ```

4. If your browser has not been started automatically, open the default address below in your browser (or the custom port you set with `--server-port`):

    ```bash
    http://localhost:7860/
    ```

    Drop the PDF file into the window and click `Translate`.

5. The first launch may spend some time downloading BabelDOC assets. If you deploy PDFMathTranslate with Docker and use Ollama as the backend LLM, fill `Ollama host` with:

   ```bash
   http://host.docker.internal:11434
   ```

   If you are running from a source checkout, make sure `npm` is installed locally. The React WebUI is built automatically on first launch when the frontend assets are missing.

<!-- <img src="./images/gui.gif" width="500"/> -->
<img src='./../../images/gui.gif' width="500"/>

### Environment Variables

You can set the source and target languages using environment variables:

- `PDF2ZH_LANG_FROM`: Sets the source language. Defaults to "English".
- `PDF2ZH_LANG_TO`: Sets the target language. Defaults to "Simplified Chinese".

## Preview

<img src="./../../images/before.png" width="500"/>
<img src="./../../images/after.png" width="500"/>
