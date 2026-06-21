
    const $ = (id) => document.getElementById(id);
    const apiBaseInput = $("apiBase");
    
    // 默认 API 地址始终为 127.0.0.1:8080，可手动修改
    const defaultApi = "http://127.0.0.1:8080";
    
    // 只在用户手动点击"检测连接"成功后更新 localStorage，不自动覆盖
    apiBaseInput.value = defaultApi;
    // 清掉旧版 localStorage 中可能错误的 API 地址，避免幽灵劫持
    localStorage.removeItem("apiBase");

    let chatHistory = [];
    let uploadedPaths = [];
    let pendingFiles = [];
    let isGenerating = false;
    let currentTaskId = null;
    let currentOutputs = [];
    let _autoDetected = null;  // AI 自动识别的主题信息缓存
    
    // 产物历史记录管理
    function saveToHistory(record) {
      const history = JSON.parse(localStorage.getItem("outputHistory") || "[]");
      history.unshift(record);
      if (history.length > 20) history.pop();
      localStorage.setItem("outputHistory", JSON.stringify(history));
    }
    
    function loadHistory() {
      return JSON.parse(localStorage.getItem("outputHistory") || "[]");
    }
    
    function showHistory() {
      const history = loadHistory();
      if (history.length === 0) {
        appendMessage("system", "暂无历史记录");
        return;
      }
      let msg = "历史生成记录：\n\n";
      history.slice(0, 5).forEach((h, i) => {
        const date = new Date(h.timestamp).toLocaleString();
        msg += `${i + 1}. ${h.theme} (${date})\n`;
        msg += `   格式: ${h.formats.join(", ")} | 耗时: ${h.elapsed}s\n`;
        msg += `   产物: ${h.outputs.length} 个文件\n\n`;
      });
      appendMessage("system", msg);
    }
    
    // 对话历史管理
    function saveChatHistory() {
      localStorage.setItem("chatHistory", JSON.stringify(chatHistory));
    }
    
    function loadChatHistory() {
      const saved = localStorage.getItem("chatHistory");
      if (saved) {
        chatHistory = JSON.parse(saved);
        chatHistory.forEach(msg => {
          appendMessage(msg.role, msg.content);
        });
      }
    }
    
    // 页面加载时恢复对话历史
    loadChatHistory();

    // AI 自动识别提示区域
    const autoHintEl = $("autoHint");
    autoHintEl.style.cssText = "color: var(--gold); font-size: 0.78rem; margin-top: 6px; padding: 6px 10px; background: rgba(201,168,76,0.08); border-radius: 6px; border-left: 3px solid var(--gold);";

    let autoHintTimer = null;
    function showAutoHint(msg) {
      autoHintEl.textContent = msg;
      autoHintEl.style.display = "block";
      clearTimeout(autoHintTimer);
      autoHintTimer = setTimeout(() => { autoHintEl.style.display = "none"; }, 15000);
    }

    let parseCache = {};
    let parseDebounceTimer = null;

    const PARSE_PROMPT = `你是一个档案专题解析器。从用户输入中提取档案主题信息。
只返回合法JSON，不要任何解释文字：
{"archive_name":"<具体主题名称>","keywords":["<关键词1>","<关键词2>"]}
重要规则：
1. archive_name 必须是具体的人名、事件名或组织名，绝不能是泛化类别词（如"名人档案""红色档案""历史档案"等）
2. keywords 必须是与该具体主题紧密绑定的专有名词（如人名、成果名、组织名），绝不能包含：
   - 泛化类别词（名人档案、红色档案、科学家、院士等）
   - 孤立的时间/地点词（1919、北京、武汉等，除非是专有名词的一部分如"五四运动"）
   - 宽泛描述词（历史、事迹、故事、发展等）
   原则：每个关键词单独拿去搜索，都应该返回与该主题直接相关的内容
3. 例如"为朱英国院士做一个名人档案"→ archive_name="朱英国院士", keywords=["朱英国","杂交水稻","红莲型","武汉大学"]
4. 例如"讲述程开甲院士的故事，生成名人档案"→ archive_name="程开甲", keywords=["程开甲","两弹一星","核武器","核试验"]
5. 例如"做一个五四运动红色档案"→ archive_name="五四运动", keywords=["五四运动","新文化运动","反帝反封建"]
如果看不出档案意图，返回 {"archive_name":null}
`;

    async function llmParseArchive(text) {
      if (parseCache[text]) return parseCache[text];
      try {
        const r = await fetch(apiBase() + "/api/v2/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: PARSE_PROMPT + "\n\n用户输入：" + text,
            history: [],
            archive_name: "档案主题识别",
            mode: "parse",
          }),
        });
        if (!r.ok) return null;
        const data = await r.json();
        const reply = (data.reply || "").trim();

        let jsonStr = reply;
        const m = reply.match(/\{[\s\S]*\}/);
        if (m) jsonStr = m[0];

        const parsed = JSON.parse(jsonStr);
        if (!parsed || !parsed.archive_name) return null;

        const result = {
          name: parsed.archive_name || "",
          keywords: parsed.keywords || [parsed.archive_name],
        };
        parseCache[text] = result;
        return result;
      } catch (e) {
        return null;
      }
    }

    // 关键词标签管理
    let _keywordList = [];
    function renderKeywordTags() {
      const wrap = $("keywordTags");
      if (!_keywordList.length) {
        wrap.innerHTML = '<span style="color:var(--text-dim);font-size:0.75rem;padding:4px 0;">输入聊天内容后自动提取…</span>';
        return;
      }
      wrap.innerHTML = _keywordList.map((kw, i) =>
        `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;font-size:0.78rem;color:var(--text);">` +
        `${escapeHtml(kw)}<button onclick="removeKeyword(${i})" style="background:none;border:none;color:var(--text-dim);cursor:pointer;padding:0 2px;font-size:0.9rem;line-height:1;">&times;</button></span>`
      ).join("");
    }
    window.removeKeyword = (idx) => {
      _keywordList.splice(idx, 1);
      renderKeywordTags();
    };
    function addKeyword(kw) {
      const t = kw.trim();
      if (t && !_keywordList.includes(t)) _keywordList.push(t);
      renderKeywordTags();
    }
    $("btnAddKeyword").addEventListener("click", () => {
      const input = $("keywordInput");
      addKeyword(input.value);
      input.value = "";
    });
    $("keywordInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { addKeyword($("keywordInput").value); $("keywordInput").value = ""; }
    });

    $("chatInput").addEventListener("input", () => {
      const text = $("chatInput").value.trim();
      if (!text || text.length < 4) return;

      clearTimeout(parseDebounceTimer);
      parseDebounceTimer = setTimeout(async () => {
        const result = await llmParseArchive(text);
        if (!result || !result.name) return;
        showAutoHint("已识别: 「" + result.name + "」 关键词: " + result.keywords.slice(0, 6).join("、"));
        _autoDetected = result;
        // 同步到左侧关键词区
        _keywordList = result.keywords.slice(0, 10);
        renderKeywordTags();
      }, 800);
    });

    function getArchiveInfo() {
      const manualName = $("archiveNameInput").value.trim();
      const name = manualName || (_autoDetected && _autoDetected.name) || "档案";

      // 优先使用左侧编辑过的关键词列表
      let keywords = _keywordList.length ? [..._keywordList] : [];
      if (!keywords.length && _autoDetected && _autoDetected.keywords) {
        keywords = [..._autoDetected.keywords];
      }
      if (!keywords.length) {
        keywords = [name];
      }
      // 确保档案名称在关键词中
      if (manualName && !keywords.includes(manualName)) {
        keywords.unshift(manualName);
      }

      return { type: "custom", name, keywords };
    }

    function apiBase() {
      return apiBaseInput.value.replace(/\/$/, "");
    }
    function log(msg, agent="", action="", detail="") {
      const box = $("logBox");
      const t = new Date().toLocaleTimeString();
      let entry = `[${t}] `;
      if (agent) entry += `<span class="agent">${agent}</span> `;
      if (action) entry += `<span class="action">${action}</span> `;
      if (detail) entry += `<span class="detail">${detail}</span>`;
      if (!agent && !action && !detail) entry += msg;
      box.innerHTML = `<div class="log-entry">${entry}</div>` + box.innerHTML;
      box.scrollTop = 0;
    }
    function setStatus(ok) {
      $("statusDot").className = "status-dot" + (ok ? " ok" : " err");
    }

    function appendMessage(role, content) {
      const wrap = $("messages");
      const div = document.createElement("div");
      div.className = "msg " + role;
      const tag = role === "user" ? "您" : role === "assistant" ? "AI Agent" : "";
      if (tag) div.innerHTML = `<div class="role-tag">${tag}</div>` + escapeHtml(content);
      else div.textContent = content;
      wrap.appendChild(div);
      wrap.scrollTop = wrap.scrollHeight;
    }
    function escapeHtml(s) {
      return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    }

    // 工作流状态更新
    function setWorkflowStep(step, status, detail="") {
      const el = $(`wf-step-${step}`);
      if (!el) return;
      el.className = "wf-step " + status;
      const statusEl = el.querySelector(".step-status");
      if (statusEl) {
        const labels = { waiting: "等待", running: "执行中...", completed: "完成", failed: "失败" };
        statusEl.textContent = labels[status] || status;
        if (detail) statusEl.textContent += " " + detail;
      }
    }
    function resetWorkflow() {
      [1, 2, 3].forEach(i => setWorkflowStep(i, "waiting"));
      $("progressBar").style.display = "none";
      $("progressFill").style.width = "0%";
    }
    function updateProgress(percent) {
      $("progressBar").style.display = "block";
      $("progressFill").style.width = percent + "%";
    }

    // 通用的带重试的 fetch 函数
    async function fetchWithRetry(url, options = {}, maxRetries = 3) {
      let lastError;
      for (let i = 0; i < maxRetries; i++) {
        try {
          const response = await fetch(url, options);
          if (!response.ok && i < maxRetries - 1) {
            throw new Error(`HTTP ${response.status}`);
          }
          return response;
        } catch (error) {
          lastError = error;
          if (i < maxRetries - 1) {
            log("", "", "", `请求失败，${2 ** i}秒后重试... (${i + 1}/${maxRetries})`);
            await new Promise(resolve => setTimeout(resolve, 1000 * (2 ** i)));
          }
        }
      }
      throw lastError;
    }

    async function ping() {
      const url = apiBase();
      log("", "", "", "检测 " + url + " ...");
      try {
        const r = await fetchWithRetry(url + "/", { signal: AbortSignal.timeout(5000) }, 2);
        if (!r.ok) throw new Error(r.status);
        const data = await r.json();
        localStorage.setItem("apiBase", url);  // 仅在成功时保存
        setStatus(true);
        log("", "", "", "已连接: " + data.project + " v" + data.version);
        loadDiagnostics();
        return true;
      } catch (e) {
        setStatus(false);
        const isOffline = e.name === "TypeError" || e.message.includes("Failed to fetch") || e.name === "TimeoutError";
        if (isOffline) {
          log("", "", "", "API 未启动或无法连接");
          appendMessage("system", "无法连接到 API 服务。请确保已启动后端：\n\n  cd " + (apiBase().includes("127.0.0.1") ? "项目目录" : apiBase()) + "\n  python api/main.py\n\n或检查 API 地址是否正确。");
        } else {
          log("", "", "", "连接失败: " + e.message);
        }
        return false;
      }
    }

    async function loadDiagnostics() {
      try {
        const r = await fetch(apiBase() + "/api/v1/system/diagnostics");
        const d = await r.json();
        const agents = d.agents || [];
        const cntEl = document.querySelector(".panel:last-child .panel-head");
        if (cntEl) cntEl.textContent = "系统状态（" + agents.length + " Agent）";
        $("agentChips").innerHTML = agents.map(a =>
          `<span class="agent-chip" title="${a.layer}">${a.name.replace("Agent","")}</span>`
        ).join("");
        $("llmList").innerHTML = (d.llm_providers || []).map(p =>
          `<li class="${p.available ? 'ok' : ''}">${p.name} ${p.available ? '[OK]' : '[未配置]'}</li>`
        ).join("");
      } catch (e) {
        log("", "", "", "诊断加载失败");
      }
    }

    // Upload
    const dropzone = $("dropzone");
    const fileInput = $("fileInput");
    dropzone.addEventListener("click", () => fileInput.click());
    dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      pendingFiles = [...pendingFiles, ...e.dataTransfer.files];
      renderFileList();
    });
    fileInput.addEventListener("change", () => {
      pendingFiles = [...pendingFiles, ...fileInput.files];
      renderFileList();
    });

    function renderFileList() {
      const el = $("fileList");
      if (!pendingFiles.length && !uploadedPaths.length) {
        el.innerHTML = "";
        $("btnUpload").disabled = true;
        return;
      }
      let html = "";
      pendingFiles.forEach((f) => {
        html += `<div class="file-item"><span class="name">${f.name}</span><span class="status pending">待上传</span></div>`;
      });
      uploadedPaths.forEach(p => {
        html += `<div class="file-item"><span class="name">${p.split(/[/\\]/).pop()}</span><span class="status ok">已解析</span></div>`;
      });
      el.innerHTML = html;
      $("btnUpload").disabled = !pendingFiles.length;
    }

    $("btnUpload").addEventListener("click", async () => {
      if (!pendingFiles.length) return;
      const fd = new FormData();
      pendingFiles.forEach(f => fd.append("files", f));
      $("btnUpload").disabled = true;
      log("", "DocumentParser", "开始", "上传并解析 " + pendingFiles.length + " 个文件");
      try {
        const r = await fetch(apiBase() + "/api/v1/parse/documents", { method: "POST", body: fd });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || r.statusText);
        uploadedPaths = [...new Set([...uploadedPaths, ...(data.file_paths || [])])];
        pendingFiles = [];
        fileInput.value = "";
        renderFileList();
        let preview = "已成功解析档案：\n";
        (data.previews || []).forEach(p => {
          preview += `\n【${p.file || p.filename}】\n${(p.preview || p.error || "").slice(0, 200)}…\n`;
        });
        appendMessage("assistant", preview);
        chatHistory.push({ role: "assistant", content: preview });
        log("", "DocumentParser", "完成", "共 " + uploadedPaths.length + " 个文件");
      } catch (e) {
        log("", "DocumentParser", "失败", e.message);
        appendMessage("system", "档案解析失败: " + e.message);
      }
      $("btnUpload").disabled = !pendingFiles.length;
    });

    $("btnSend").addEventListener("click", sendChat);
    $("chatInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.ctrlKey) { 
        e.preventDefault(); 
        sendChat(); 
      } else if (e.key === "Enter" && !e.shiftKey) { 
        e.preventDefault(); 
        sendChat(); 
      }
    });

    async function sendChat() {
      const text = $("chatInput").value.trim();
      if (!text) return;
      if (!(await ping())) {
        appendMessage("system", "请先启动 API：在项目目录运行 python api/main.py");
        return;
      }
      appendMessage("user", text);
      chatHistory.push({ role: "user", content: text });
      saveChatHistory();
      $("chatInput").value = "";
      $("btnSend").disabled = true;
      log("", "", "", "对话请求...");

      const archiveInfo = getArchiveInfo();
      try {
        const r = await fetchWithRetry(apiBase() + "/api/v2/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            history: chatHistory.slice(-10),
            files: uploadedPaths,
            archive_type: archiveInfo.type,
            archive_name: archiveInfo.name,
          }),
        }, 2);
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || JSON.stringify(data));

        // 后端检测到生成意图时只提示用户点击生成按钮
        appendMessage("assistant", data.reply);
        chatHistory.push({ role: "assistant", content: data.reply });
        saveChatHistory();
        if (data.intent === "generate_hint") {
          log("", "SmartOrchestrator", "提示", "已引导用户点击生成按钮");
          // 高亮生成按钮，吸引用户注意
          const btn = $("btnGenerate");
          btn.style.animation = "pulseGold 0.6s ease-in-out 3";
          btn.scrollIntoView({ behavior: "smooth", block: "center" });
        } else {
          log("", "", "", "对话完成");
        }
      } catch (e) {
        appendMessage("system", "对话错误: " + e.message);
        log("", "", "", "对话失败: " + e.message);
      }
      $("btnSend").disabled = false;
    }

    // ========== 共享：从后端结果提取并渲染产物 ==========
    function extractOutputItems(results, backendOutputs) {
      const items = [];
      function walk(obj) {
        if (!obj || typeof obj !== "object") return;
        if (obj.html_path) {
          const n = obj.html_path.replace(/\\/g, "/");
          const rel = n.includes("outputs/") ? n.split("outputs/")[1] : n;
          items.push({ type: "HTML 网站", path: obj.html_path, url: "/outputs/" + rel });
        }
        if (obj.output_files && obj.output_files.threejs) {
          const n = obj.output_files.threejs.replace(/\\/g, "/");
          const rel = n.includes("outputs/") ? n.split("outputs/")[1] : n;
          items.push({ type: "3D 展厅", path: obj.output_files.threejs, url: "/outputs/" + rel });
        }
        for (const [k, v] of Object.entries(obj)) {
          if (v && typeof v === "object" && k !== "_context") walk(v);
        }
      }
      walk(results || {});
      for (const o of (backendOutputs || [])) {
        if (!items.find(x => x.path === o.path)) items.push(o);
      }
      return items;
    }

    function renderGeneratedOutputs(data) {
      const outputs = extractOutputItems(data.results, data.outputs);
      currentOutputs = outputs;
      if (outputs.length > 0) {
        $("outputPreview").style.display = "block";
        const base = apiBase();
        $("outputList").innerHTML = outputs.map(o => {
          const fullUrl = (o.url && o.url.startsWith("http")) ? o.url : base + (o.url || "");
          const isPreviewable = o.type.includes("HTML") || o.type.includes("3D");
          return `<div class="output-item">
            <span>${o.type}:</span>
            <a href="${fullUrl}" target="_blank">${(o.path || "").split(/[/\\]/).pop() || o.type}</a>
            ${isPreviewable ? `<button class="btn-sm btn-ghost" onclick="openPreviewModal('${fullUrl}', '${o.type}')">预览</button>` : ''}
          </div>`;
        }).join("");
        renderGalleryBrowser(outputs);
      }
      return outputs;
    }

    $("btnGenerate").addEventListener("click", async () => {
      if (isGenerating) return;
      const formats = [...document.querySelectorAll("#formatChecks input:checked")].map(c => c.value);
      if (!formats.length) {
        alert("请至少选择一种输出格式");
        return;
      }
      if (!(await ping())) return;

      const archiveInfo = getArchiveInfo();
      const chatText = $("chatInput").value.trim();

      let userReq, archiveName, archiveType, crawlKeywords;

      if (chatText) {
        archiveName = archiveInfo.name;
        archiveType = archiveInfo.type;
        crawlKeywords = archiveInfo.keywords;
        if (archiveType === "custom" && crawlKeywords.length <= 1) {
          const chatKws = chatText.split(/[,，、\s]+/).filter(s => s.length > 1);
          if (chatKws.length > 0) crawlKeywords = [...new Set([...crawlKeywords, ...chatKws])];
        }
        userReq = `为「${archiveName}」生成档案数字叙事作品，专题类型 ${archiveType}，输出格式: ${formats.join("、")}。补充说明: ${chatText}`;
      } else {
        userReq = `请为「${archiveInfo.name}」生成数字叙事作品，输出格式：${formats.join("、")}`;
        archiveName = archiveInfo.name;
        archiveType = archiveInfo.type;
        crawlKeywords = archiveInfo.keywords;
      }

      $("chatInput").value = "";

      appendMessage("user", "[生成任务] " + userReq);
      appendMessage("system", "SmartOrchestrator 正在调度多 Agent，可能需要数分钟，请稍候...");
      $("btnGenerate").disabled = true;
      $("btnGenerate").style.display = "none";
      $("btnCancel").style.display = "inline-block";
      isGenerating = true;
      resetWorkflow();

      const workflowViz = $("workflowViz");
      workflowViz.innerHTML = '<div class="wf-step" style="color:var(--text-dim);font-size:0.8rem;text-align:center;padding:12px 0">等待编排器规划...</div>';
      $("progressBar").style.display = "block";
      $("progressFill").classList.add("indeterminate");

      const abortController = new AbortController();
      currentTaskId = Date.now();

      $("btnCancel").onclick = () => {
        abortController.abort();
        isGenerating = false;
        $("btnGenerate").disabled = false;
        $("btnGenerate").style.display = "inline-block";
        $("btnCancel").style.display = "none";
        $("progressBar").style.display = "none";
        $("workflowViz").innerHTML = '<div class="wf-step failed" style="text-align:center;padding:12px 0"><span class="step-status" style="color:var(--err)">任务已取消</span></div>';
        appendMessage("system", "任务已取消");
        log("", "", "", "用户取消了任务");
      };

      try {
        // Step 1: 提交任务 -> 立即获取 task_id
        const submitResp = await fetch(apiBase() + "/api/v2/narrative/smart", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_request: userReq,
            files: uploadedPaths,
            output_formats: formats,
            archive_type: archiveType,
            archive_name: archiveName,
            enable_crawl: $("enableCrawl").checked,
            crawl_keywords: crawlKeywords,
          }),
          signal: abortController.signal
        });
        const submitData = await submitResp.json();
        if (!submitResp.ok) throw new Error(submitData.detail || "Submit failed");
        const taskId = submitData.task_id;
        log("", "SmartOrchestrator", "已提交", "任务ID: " + taskId);

        // Step 2: 轮询直到完成
        let data = null;
        let lastLogCount = 0;
        let pollErrors = 0;
        for (let i = 0; i < 900; i++) {
          if (abortController.signal.aborted) break;
          await new Promise(r => setTimeout(r, 2000));
          let pollData;
          try {
            const pollResp = await fetch(apiBase() + "/api/v2/narrative/status/" + taskId);
            if (!pollResp.ok) throw new Error(`HTTP ${pollResp.status}`);
            pollData = await pollResp.json();
            pollErrors = 0; // 成功后重置错误计数
          } catch (pollErr) {
            pollErrors++;
            if (pollErrors >= 5) throw new Error("轮询连续失败5次: " + pollErr.message);
            continue; // 单次失败跳过，继续轮询
          }
          updateProgress(Math.min(95, 10 + i * 3));

          // 实时显示 Agent 执行日志
          const execLog = pollData.execution_log || [];
          if (execLog.length > lastLogCount) {
            const agentLabels = {
              "planner": "规划器", "WebCrawlerAgent": "网络爬虫",
              "DocumentParserAgent": "文档解析", "ArchiveAnalysisAgent": "档案分析",
              "SmartAnalysisAgent": "智能分析", "WebGalleryAgent": "网站生成",
              "Exhibition3DAgent": "3D展厅生成", "SmartOutputAgent": "输出编排",
              "orchestrator": "编排器",
            };
            for (let li = lastLogCount; li < execLog.length; li++) {
              const entry = execLog[li];
              const label = agentLabels[entry.agent] || entry.agent;
              const actionLabels = { started: "开始", completed: "完成", failed: "失败", error: "出错", planning: "规划中" };
              const actionLabel = actionLabels[entry.action] || entry.action;
              log("", label, actionLabel, entry.detail ? entry.detail.substring(0, 80) : "");
            }
            lastLogCount = execLog.length;

            // 更新工作流可视化
            const viz = $("workflowViz");
            const agentStatus = {};
            for (const entry of execLog) {
              const agent = entry.agent;
              if (entry.action === "started") agentStatus[agent] = "running";
              else if (entry.action === "completed") agentStatus[agent] = "completed";
              else if (entry.action === "failed" || entry.action === "error") agentStatus[agent] = "failed";
            }
            const uniqueAgents = [...new Set(execLog.map(e => e.agent))];
            viz.innerHTML = uniqueAgents.map((agent, idx) => {
              const status = agentStatus[agent] || "waiting";
              const label = agentLabels[agent] || agent;
              const labels = { waiting: "等待", running: "执行中...", completed: "完成", failed: "失败" };
              return `<div class="wf-step ${status}"><span class="step-num">${idx + 1}</span><span class="step-name">${label}</span><span class="step-status">${labels[status] || status}</span></div>`;
            }).join("");
          }

          // 显示当前进度文字
          if (pollData.progress) {
            log("", "", "", pollData.progress);
          }

          if (pollData.status === "completed" || pollData.status === "failed") {
            data = pollData.result || pollData;
            if (pollData.status === "failed") {
              const failMsg = pollData.progress || "Task failed";
              if (failMsg.includes("检查点已保存") || failMsg.includes("断点恢复")) {
                throw new Error(failMsg + " — 请重新点击生成按钮，系统将从断点继续");
              }
              throw new Error(failMsg);
            }
            break;
          }
        }
        if (!data) throw new Error("任务超时");

        $("progressFill").classList.remove("indeterminate");
        updateProgress(100);
        log("", "SmartOrchestrator", "完成", "耗时 " + (data.elapsed || "?") + " 秒");

        let summary = `编排完成（耗时 ${data.elapsed || "?"} 秒）\n\n`;

        if (data.plan && data.plan.workflow) {
          const viz = $("workflowViz");
          viz.innerHTML = "";

          const execLog = data.execution_log || [];
          const agentStatus = {};
          for (const entry of execLog) {
            const agent = entry.agent;
            if (entry.action === "started") agentStatus[agent] = "running";
            else if (entry.action === "completed") agentStatus[agent] = "completed";
            else if (entry.action === "failed" || entry.action === "error") agentStatus[agent] = "failed";
          }

          data.plan.workflow.forEach((step, idx) => {
            const agent = step.agent || "";
            const status = agentStatus[agent] || "waiting";
            const stepDiv = document.createElement("div");
            stepDiv.className = "wf-step " + status;
            const labels = { waiting: "等待", running: "执行中", completed: "完成", failed: "失败" };
            const statusText = labels[status] || status;
            stepDiv.innerHTML = `<span class="step-num">${idx + 1}</span><span class="step-name" title="${step.task || ''}">${agent.replace("Agent", "")}</span><span class="step-status">${statusText}</span>`;
            viz.appendChild(stepDiv);
            summary += `  ${idx + 1}. ${agent} [${statusText}] → ${step.output_key || ""}\n`;
          });
        }


        const results = data.results || {};

        if (data.data_source && data.data_source !== "unknown") {
          summary += `\n数据来源: ${data.data_source}`;
        }

        // 展示执行日志
        if (data.execution_log && data.execution_log.length > 0) {
          summary += `\n\n执行日志：\n`;
          data.execution_log.slice(-10).forEach(entry => {
            summary += `  [${entry.agent}] ${entry.action}: ${entry.detail.substring(0, 100)}\n`;
          });
        }

        // 提取并渲染产物
        const outputs = renderGeneratedOutputs(data);
        if (outputs.length > 0) {
          summary += `\n\n已生成 ${outputs.length} 个产物文件`;
        }

        appendMessage("assistant", summary);

        // 保存到历史
        saveToHistory({
          timestamp: Date.now(),
          theme: archiveInfo.name,
          formats: formats,
          elapsed: data.elapsed,
          outputs: outputs.map(o => ({ type: o.type, path: o.path }))
        });

        log("", "", "", "生成完成");
      } catch (e) {
        if (e.name === 'AbortError') {
          return;
        }
        setWorkflowStep(1, "failed");
        setWorkflowStep(2, "failed");
        setWorkflowStep(3, "failed");
        appendMessage("system", "生成失败: " + e.message);
        log("", "SmartOrchestrator", "失败", e.message);
      } finally {
        $("btnGenerate").disabled = false;
        $("btnGenerate").style.display = "inline-block";
        $("btnCancel").style.display = "none";
        isGenerating = false;
        currentTaskId = null;
      }
    });

    // 作品画廊浏览器
    function renderGalleryBrowser(outputs) {
      const browser = $("galleryBrowser");
      const tabs = $("galleryTabs");
      const content = $("galleryContent");
      
      browser.classList.add("active");
      
      // 按类型分组
      const groups = {};
      outputs.forEach(o => {
        let cat = "其他";
        if (o.type.includes("HTML") || o.type.includes("网站")) cat = "网站";
        else if (o.type.includes("3D")) cat = "3D展厅";
        else if (o.type.includes("文档")) cat = "文档";

        if (!groups[cat]) groups[cat] = [];
        groups[cat].push(o);
      });
      
      // 渲染标签
      const categories = Object.keys(groups);
      tabs.innerHTML = categories.map((cat, i) => 
        `<button class="gallery-tab ${i === 0 ? 'active' : ''}" onclick="switchGalleryTab('${cat}')">${cat} (${groups[cat].length})</button>`
      ).join("");
      
      // 渲染内容
      window._galleryGroups = groups;
      switchGalleryTab(categories[0]);
    }
    
    window.switchGalleryTab = function(category) {
      const groups = window._galleryGroups || {};
      const content = $("galleryContent");
      const items = groups[category] || [];
      
      // 更新标签状态
      document.querySelectorAll(".gallery-tab").forEach(tab => {
        tab.classList.toggle("active", tab.textContent.startsWith(category));
      });
      
      // 图标映射
      const icons = {
        "网站": "🌐", "文档": "📄", "3D展厅": "🏛️", "其他": "📦"
      };
      
      content.innerHTML = `<div class="gallery-grid">${items.map(o => {
        const base = apiBase();
        const fullUrl = (o.url && o.url.startsWith("http")) ? o.url : base + (o.url || "");
        const isPreviewable = category === "网站" || category === "3D展厅";
        return `
          <div class="gallery-card" onclick="${isPreviewable ? `openPreviewModal('${fullUrl}', '${o.type}')` : `window.open('${fullUrl}', '_blank')`}">
            <div class="card-thumb">${icons[category] || "📦"}</div>
            <div class="card-info">
              <div class="card-title">${(o.path || "").split(/[/\\]/).pop() || o.type}</div>
              <div class="card-meta">${o.type}</div>
            </div>
          </div>
        `;
      }).join("")}</div>`;
    };

    // 预览模态框
    window.openPreviewModal = function(url, title) {
      const modal = $("previewModal");
      const frame = $("previewFrame");
      const titleEl = $("previewTitle");
      frame.src = url;
      titleEl.textContent = title || "作品预览";
      modal.classList.add("active");
    };
    
    window.closePreviewModal = function() {
      const modal = $("previewModal");
      const frame = $("previewFrame");
      frame.src = "";
      modal.classList.remove("active");
    };
    
    // 点击模态框背景关闭
    $("previewModal").addEventListener("click", (e) => {
      if (e.target === $("previewModal")) {
        closePreviewModal();
      }
    });

    $("btnClear").addEventListener("click", () => {
      chatHistory = [];
      saveChatHistory();
      $("messages").innerHTML = '<div class="msg system">对话已清空。</div>';
      resetWorkflow();
      $("outputPreview").style.display = "none";
      $("galleryBrowser").classList.remove("active");
    });

    $("btnPing").addEventListener("click", ping);

    // 页面加载时自动检测连接
    window.addEventListener("load", () => {
      setTimeout(ping, 500);
    });
  