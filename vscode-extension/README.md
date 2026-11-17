# codebrain - Chat with your codebase (VS Code panel)

A chat panel in VS Code's sidebar. Ask questions about the project you have open
in plain English and get answers grounded in your real files.

The panel is a thin shell; all the thinking happens in the Python engine
(`../chat_bridge.py` -> the `codebrain` package).

## How to run it (development)

1. Open **this folder** (`vscode-extension`) in VS Code:
   `File -> Open Folder...` and pick the `vscode-extension` folder.
2. Press **F5**. A second VS Code window opens titled
   **[Extension Development Host]** - the extension is now live in that window.
3. In that new window, open **your project**:
   `File -> Open Folder...` and pick your repo (e.g. `relaxon mattress`).
4. Click the **codebrain speech-bubble icon** in the left sidebar (activity bar).
5. Type a question and press **Ask**. Try:
   - "what is this app?"
   - "how does login work?"
   - "why does add to cart do nothing?"

## Requirements

- **Python** on your PATH (the panel runs `python`). Change it in
  `Settings -> Extensions -> codebrain -> Python Path` if your command is
  `python3` or a full path.
- The AI key in `../.env` (`OPENROUTER_API_KEY`) - already set up.

## Notes / current limits

- Each question is answered fresh (no back-and-forth memory yet) - that's the
  next improvement.
- If you move `chat_bridge.py`, set its full path in
  `Settings -> Extensions -> codebrain -> Bridge Path`.
