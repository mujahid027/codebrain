// codebrain chat panel for VS Code.
//
// This is the small glue layer: it draws a chat panel in the sidebar and, for
// each question, runs the Python brain (chat_bridge.py) and streams the answer
// back into the chat. All the real logic lives in Python.

const vscode = require("vscode");
const cp = require("child_process");
const path = require("path");
const fs = require("fs");

function activate(context) {
  const provider = new ChatViewProvider(context);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("codebrain.chat", provider, {
      // Keep the chat alive when you switch to the Explorer and back, so the
      // conversation isn't wiped every time the panel loses focus.
      webviewOptions: { retainContextWhenHidden: true },
    })
  );
}

class ChatViewProvider {
  constructor(context) {
    this.context = context;
    this.current = null; // the running python process, if any
  }

  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = getHtml(view.webview);

    view.webview.onDidReceiveMessage((msg) => {
      if (msg.type === "ask") this.ask(msg.text);
      if (msg.type === "stop") this.stop();
    });
  }

  post(message) {
    if (this.view) this.view.webview.postMessage(message);
  }

  stop() {
    if (this.current) {
      this.current.kill();
      this.current = null;
    }
  }

  ask(question) {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) {
      this.post({ type: "error", text: "Open your project folder in VS Code first (File -> Open Folder)." });
      return;
    }
    const repo = folders[0].uri.fsPath;

    const config = vscode.workspace.getConfiguration("codebrain");
    const python = config.get("pythonPath") || "python";
    let bridge = config.get("bridgePath");
    if (!bridge) {
      bridge = path.join(this.context.extensionPath, "..", "chat_bridge.py");
    }
    if (!fs.existsSync(bridge)) {
      this.post({
        type: "error",
        text: "Couldn't find chat_bridge.py. Set 'codebrain.bridgePath' in Settings to its full path.",
      });
      return;
    }

    this.stop();
    this.post({ type: "start" });

    let proc;
    try {
      proc = cp.spawn(python, [bridge, repo, question]);
    } catch (e) {
      this.post({ type: "error", text: "Couldn't start Python: " + e.message });
      return;
    }
    this.current = proc;

    proc.stdout.setEncoding("utf8");
    proc.stdout.on("data", (chunk) => this.post({ type: "chunk", text: chunk }));

    let stderr = "";
    proc.stderr.setEncoding("utf8");
    proc.stderr.on("data", (d) => (stderr += d));

    proc.on("error", (e) => {
      this.post({ type: "error", text: "Python error: " + e.message });
      this.current = null;
    });
    proc.on("close", (code) => {
      if (code !== 0 && stderr) {
        this.post({ type: "error", text: stderr.slice(0, 800) });
      }
      this.post({ type: "done" });
      this.current = null;
    });
  }
}

function getHtml(webview) {
  const nonce = String(Math.random()).slice(2);
  const csp =
    `default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; ` +
    `script-src 'nonce-${nonce}';`;

  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --gap: 12px;
    --radius: 12px;
    --accent: var(--vscode-textLink-foreground, #4aa3ff);
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0;
    font-family: var(--vscode-font-family);
    font-size: 13px;
    line-height: 1.55;
    color: var(--vscode-foreground);
    background: var(--vscode-sideBar-background, transparent);
    display: flex;
    flex-direction: column;
    height: 100vh;
  }

  /* Header */
  header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    border-bottom: 1px solid var(--vscode-panel-border, rgba(128,128,128,.25));
    flex: 0 0 auto;
  }
  header .logo {
    width: 20px; height: 20px; flex: 0 0 auto;
    color: var(--accent);
  }
  header .title { font-weight: 600; letter-spacing: .2px; }
  header .spacer { flex: 1; }
  header button.ghost {
    display: inline-flex; align-items: center; gap: 5px;
    background: transparent; color: var(--vscode-foreground);
    border: 1px solid var(--vscode-panel-border, rgba(128,128,128,.35));
    border-radius: 8px; padding: 4px 9px; font-size: 12px; cursor: pointer;
    opacity: .8;
  }
  header button.ghost:hover { opacity: 1; background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,.15)); }

  /* Conversation */
  #log { flex: 1 1 auto; overflow-y: auto; padding: 6px 12px 14px; scroll-behavior: smooth; }
  #log::-webkit-scrollbar { width: 10px; }
  #log::-webkit-scrollbar-thumb { background: var(--vscode-scrollbarSlider-background); border-radius: 6px; }
  #log::-webkit-scrollbar-thumb:hover { background: var(--vscode-scrollbarSlider-hoverBackground); }

  .turn { margin: 14px 0; }
  .turn .head { display: flex; align-items: center; gap: 7px; margin-bottom: 5px; }
  .turn .dot {
    width: 18px; height: 18px; border-radius: 6px; flex: 0 0 auto;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 700; color: #fff;
  }
  .turn.user .dot { background: var(--vscode-badge-background, #555); color: var(--vscode-badge-foreground, #fff); }
  .turn.bot  .dot { background: var(--accent); }
  .turn .name { font-size: 11.5px; font-weight: 600; opacity: .75; letter-spacing: .3px; }

  .turn .body { padding-left: 25px; }
  .turn.user .body {
    background: var(--vscode-input-background);
    border: 1px solid var(--vscode-input-border, transparent);
    border-radius: var(--radius);
    padding: 8px 11px;
    margin-left: 25px;
    white-space: pre-wrap; word-wrap: break-word;
  }

  /* Rendered markdown */
  .body h1,.body h2,.body h3 { margin: .7em 0 .35em; font-size: 1.05em; line-height: 1.3; }
  .body h1 { font-size: 1.15em; }
  .body p { margin: .5em 0; }
  .body ul,.body ol { margin: .4em 0; padding-left: 1.25em; }
  .body li { margin: .25em 0; }
  .body code {
    font-family: var(--vscode-editor-font-family, monospace); font-size: .92em;
    background: var(--vscode-textCodeBlock-background, rgba(128,128,128,.18));
    padding: .08em .35em; border-radius: 5px;
  }
  .body pre {
    background: var(--vscode-textCodeBlock-background, rgba(128,128,128,.12));
    border: 1px solid var(--vscode-panel-border, rgba(128,128,128,.2));
    padding: 10px 11px; border-radius: 10px; overflow-x: auto; margin: .6em 0;
  }
  .body pre code { background: none; padding: 0; font-size: .9em; }
  .body hr { border: none; border-top: 1px solid var(--vscode-panel-border); margin: .9em 0; }
  .body strong { font-weight: 600; }

  /* Empty state */
  .empty { padding: 22px 6px; opacity: .95; }
  .empty h2 { font-size: 15px; margin: 0 0 4px; }
  .empty p { margin: 0 0 14px; opacity: .7; font-size: 12.5px; }
  .chips { display: flex; flex-direction: column; gap: 8px; }
  .chip {
    text-align: left; cursor: pointer;
    background: var(--vscode-input-background);
    border: 1px solid var(--vscode-panel-border, rgba(128,128,128,.3));
    color: var(--vscode-foreground);
    border-radius: 10px; padding: 9px 11px; font-size: 12.5px; line-height: 1.35;
    display: flex; align-items: center; gap: 8px;
  }
  .chip:hover { border-color: var(--accent); background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,.12)); }
  .chip .arrow { opacity: .5; margin-left: auto; }

  /* Thinking */
  .thinking { display: inline-flex; gap: 4px; align-items: center; opacity: .7; }
  .thinking span { width: 5px; height: 5px; border-radius: 50%; background: currentColor; animation: bounce 1.2s infinite ease-in-out; }
  .thinking span:nth-child(2){ animation-delay: .15s; }
  .thinking span:nth-child(3){ animation-delay: .3s; }
  @keyframes bounce { 0%,80%,100%{ transform: translateY(0); opacity:.4 } 40%{ transform: translateY(-4px); opacity:1 } }

  .err { color: var(--vscode-errorForeground, #f14c4c); font-style: italic; }

  /* Input */
  #bar {
    flex: 0 0 auto;
    display: flex; align-items: flex-end; gap: 8px;
    padding: 10px 12px;
    border-top: 1px solid var(--vscode-panel-border, rgba(128,128,128,.25));
  }
  .inputwrap {
    flex: 1; display: flex; align-items: flex-end;
    background: var(--vscode-input-background);
    border: 1px solid var(--vscode-input-border, rgba(128,128,128,.35));
    border-radius: 12px; padding: 4px 4px 4px 10px;
  }
  .inputwrap:focus-within { border-color: var(--accent); }
  #q {
    flex: 1; resize: none; border: none; outline: none; background: transparent;
    color: var(--vscode-input-foreground); font-family: inherit; font-size: 13px;
    line-height: 1.4; padding: 6px 0; max-height: 140px;
  }
  #send {
    flex: 0 0 auto; width: 30px; height: 30px; border: none; border-radius: 9px;
    cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
    background: var(--vscode-button-background); color: var(--vscode-button-foreground);
  }
  #send:hover { background: var(--vscode-button-hoverBackground); }
  #send:disabled { opacity: .4; cursor: default; }
</style>
</head>
<body>
  <header>
    <svg class="logo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
      <path d="M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9l-4 3v-3H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z"/>
      <path d="M8 10h8M8 13h5"/>
    </svg>
    <span class="title">codebrain</span>
    <span class="spacer"></span>
    <button class="ghost" id="new" title="Start a new chat">
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
      New
    </button>
  </header>

  <div id="log"></div>

  <div id="bar">
    <div class="inputwrap">
      <textarea id="q" rows="1" placeholder="Ask about your codebase..."></textarea>
    </div>
    <button id="send" title="Ask">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>
    </button>
  </div>

<script nonce="${nonce}">
const vscode = acquireVsCodeApi();
const log = document.getElementById('log');
const q = document.getElementById('q');
const send = document.getElementById('send');
const newBtn = document.getElementById('new');
let botEl = null, botRaw = "", busy = false;

const SUGGESTIONS = [
  "What is this app, in plain English?",
  "How does login work?",
  "Walk me through the main files and what each does",
  "Why might a feature not be working?"
];

const ICON_SEND = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
const ICON_STOP = '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2.5"/></svg>';
const ICON_ARROW = '<svg class="arrow" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';

function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// Minimal Markdown -> HTML so answers read cleanly (mirrors the Python renderer).
function md(src){
  const lines = src.split('\\n');
  let out=[], para=[], code=[], inCode=false, list=null;
  const inline = t => esc(t)
      .replace(/\`([^\`]+)\`/g,'<code>$1</code>')
      .replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');
  const flushP = ()=>{ if(para.length){ out.push('<p>'+inline(para.join(' '))+'</p>'); para=[]; } };
  const closeL = ()=>{ if(list){ out.push('</'+list+'>'); list=null; } };
  for(const line of lines){
    const s = line.trim();
    if(s.startsWith('\`\`\`')){
      if(inCode){ out.push('<pre><code>'+esc(code.join('\\n'))+'</code></pre>'); code=[]; inCode=false; }
      else { flushP(); closeL(); inCode=true; }
      continue;
    }
    if(inCode){ code.push(line); continue; }
    if(!s){ flushP(); closeL(); continue; }
    if(/^(-{3,}|\\*{3,}|_{3,})$/.test(s)){ flushP(); closeL(); out.push('<hr>'); continue; }
    let m = s.match(/^(#{1,6})\\s+(.*)/);
    if(m){ flushP(); closeL(); const n=m[1].length; out.push('<h'+n+'>'+inline(m[2])+'</h'+n+'>'); continue; }
    m = s.match(/^[-*]\\s+(.*)/);
    if(m){ flushP(); if(list!=='ul'){ closeL(); out.push('<ul>'); list='ul'; } out.push('<li>'+inline(m[1])+'</li>'); continue; }
    m = s.match(/^\\d+\\.\\s+(.*)/);
    if(m){ flushP(); if(list!=='ol'){ closeL(); out.push('<ol>'); list='ol'; } out.push('<li>'+inline(m[1])+'</li>'); continue; }
    closeL(); para.push(s);
  }
  if(inCode) out.push('<pre><code>'+esc(code.join('\\n'))+'</code></pre>');
  flushP(); closeL();
  return out.join('\\n');
}

function renderEmpty(){
  const chips = SUGGESTIONS.map(s =>
    '<button class="chip" data-q="'+esc(s)+'">'+esc(s)+ICON_ARROW+'</button>'
  ).join('');
  log.innerHTML =
    '<div class="empty">' +
      '<h2>Ask your codebase anything</h2>' +
      '<p>Answers come straight from the files in the project open in this window.</p>' +
      '<div class="chips">'+chips+'</div>' +
    '</div>';
  log.querySelectorAll('.chip').forEach(c =>
    c.addEventListener('click', ()=>{ q.value = c.getAttribute('data-q'); autosize(); ask(); })
  );
}

function addTurn(who, cls){
  const turn = document.createElement('div');
  turn.className = 'turn ' + cls;
  const letter = cls === 'user' ? 'U' : 'C';
  turn.innerHTML = '<div class="head"><span class="dot">'+letter+'</span><span class="name">'+who+'</span></div>';
  const body = document.createElement('div');
  body.className = 'body';
  turn.appendChild(body);
  log.appendChild(turn);
  return body;
}

function scroll(){ log.scrollTop = log.scrollHeight; }

function autosize(){
  q.style.height = 'auto';
  q.style.height = Math.min(q.scrollHeight, 140) + 'px';
}

function setBusy(v){
  busy = v;
  send.innerHTML = v ? ICON_STOP : ICON_SEND;
  send.title = v ? 'Stop' : 'Ask';
}

function ask(){
  const text = q.value.trim();
  if(!text || busy) return;
  if(log.querySelector('.empty')) log.innerHTML = '';
  addTurn('You','user').textContent = text;
  q.value=''; autosize();
  botEl = addTurn('codebrain','bot'); botRaw = "";
  botEl.innerHTML = '<span class="thinking"><span></span><span></span><span></span></span>';
  setBusy(true);
  vscode.postMessage({ type:'ask', text });
  scroll();
}

send.addEventListener('click', ()=>{ if(busy) vscode.postMessage({type:'stop'}); else ask(); });
newBtn.addEventListener('click', ()=>{ if(busy) vscode.postMessage({type:'stop'}); setBusy(false); botEl=null; botRaw=""; renderEmpty(); q.focus(); });
q.addEventListener('input', autosize);
q.addEventListener('keydown', e=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); ask(); } });

window.addEventListener('message', ev=>{
  const m = ev.data;
  if(m.type==='chunk'){ if(botRaw===""){ botEl.innerHTML=""; } botRaw += m.text; botEl.innerHTML = md(botRaw); scroll(); }
  else if(m.type==='error'){ if(botEl){ botEl.innerHTML = md(botRaw) + '<p class="err">'+esc(m.text)+'</p>'; } setBusy(false); scroll(); }
  else if(m.type==='done'){ if(botEl && botRaw===""){ botEl.innerHTML = '<p class="err">(no answer)</p>'; } setBusy(false); }
});

renderEmpty();
autosize();
</script>
</body>
</html>`;
}

module.exports = { activate, deactivate() {}, getHtml };
