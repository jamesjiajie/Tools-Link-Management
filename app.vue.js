const { createApp } = Vue;

createApp({
  data() {
    return {
      tools: [],
      view: "workspace",
      query: "",
      sortMode: "status",
      busy: false,
      toast: "",
      toastTimer: null,
      lastCreated: 0,
      editing: this.emptyTool(),
      tagText: "",
      logTitle: "",
      logText: "",
    };
  },

  computed: {
    runningCount() {
      return this.tools.filter((tool) => this.isRunning(tool)).length;
    },
    launchableCount() {
      return this.tools.filter((tool) => tool.startCommand).length;
    },
    rememberedCount() {
      return this.tools.filter((tool) => tool.source === "detected").length;
    },
    visibleTools() {
      const query = this.query.trim().toLowerCase();
      const filtered = this.tools.filter((tool) => {
        if (this.view === "running" && !this.isRunning(tool)) return false;
        if (this.view === "configured" && !tool.startCommand) return false;
        if (this.view === "detected" && tool.source !== "detected") return false;
        if (!query) return true;
        return [
          tool.name,
          tool.url,
          tool.port,
          tool.projectPath,
          tool.startCommand,
          tool.processName,
          tool.notes,
          ...(tool.tags || []),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query);
      });

      return filtered.sort((a, b) => {
        if (this.sortMode === "name") return a.name.localeCompare(b.name);
        if (this.sortMode === "port") return Number(a.port || 0) - Number(b.port || 0);
        if (this.sortMode === "updated") return Number(b.updatedAt || 0) - Number(a.updatedAt || 0);
        return this.statusRank(a.status) - this.statusRank(b.status) || a.name.localeCompare(b.name);
      });
    },
  },

  mounted() {
    this.refreshTools();
  },

  methods: {
    emptyTool() {
      return {
        id: "",
        name: "",
        url: "",
        port: "",
        projectPath: "",
        startCommand: "",
        tags: [],
        notes: "",
        source: "manual",
      };
    },
    async api(path, options = {}) {
      const response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "请求失败");
      return payload;
    },
    async refreshTools() {
      try {
        const payload = await this.api("/api/tools");
        this.tools = payload.tools;
      } catch (error) {
        this.notify(error.message);
      }
    },
    async discoverTools() {
      this.busy = true;
      try {
        const payload = await this.api("/api/discover", { method: "POST" });
        this.tools = payload.tools;
        this.lastCreated = payload.created;
        this.notify(payload.created ? `检测完成，新增 ${payload.created} 个工具` : "检测完成，没有新增工具");
      } catch (error) {
        this.notify(error.message);
      } finally {
        this.busy = false;
      }
    },
    openEditor(tool = null) {
      this.editing = tool ? structuredClone(tool) : this.emptyTool();
      this.tagText = (this.editing.tags || []).join(", ");
      this.$refs.editorDialog.showModal();
    },
    closeEditor() {
      this.$refs.editorDialog.close();
    },
    async saveTool() {
      const body = {
        ...this.editing,
        tags: this.tagText
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      };
      if (!body.port && body.url) {
        try {
          body.port = new URL(body.url).port;
        } catch {
          body.port = "";
        }
      }

      try {
        if (body.id) {
          await this.api(`/api/tools/${body.id}`, { method: "PUT", body: JSON.stringify(body) });
        } else {
          await this.api("/api/tools", { method: "POST", body: JSON.stringify(body) });
        }
        this.closeEditor();
        await this.refreshTools();
        this.notify("已保存到工作空间");
      } catch (error) {
        this.notify(error.message);
      }
    },
    async deleteTool(tool) {
      try {
        await this.api(`/api/tools/${tool.id}`, { method: "DELETE" });
        this.closeEditor();
        await this.refreshTools();
        this.notify("已删除");
      } catch (error) {
        this.notify(error.message);
      }
    },
    async startTool(tool) {
      await this.mutateTool(tool, "start", "启动指令已发送");
    },
    async stopTool(tool) {
      await this.mutateTool(tool, "stop", "停止指令已发送");
    },
    async restartTool(tool) {
      await this.mutateTool(tool, "restart", "重启指令已发送");
    },
    async mutateTool(tool, action, message) {
      try {
        await this.api(`/api/tools/${tool.id}/${action}`, { method: "POST" });
        await this.refreshTools();
        this.notify(message);
      } catch (error) {
        this.notify(error.message);
      }
    },
    openLink(tool) {
      if (tool.url) window.open(tool.url, "_blank", "noopener,noreferrer");
    },
    async showLog(tool) {
      try {
        const payload = await this.api(`/api/logs/${tool.id}`);
        this.logTitle = tool.name;
        this.logText = payload.log;
        this.$refs.logDialog.showModal();
      } catch (error) {
        this.notify(error.message);
      }
    },
    notify(message) {
      this.toast = message;
      window.clearTimeout(this.toastTimer);
      this.toastTimer = window.setTimeout(() => {
        this.toast = "";
      }, 2600);
    },
    isRunning(tool) {
      return tool.status === "running" || tool.status === "starting";
    },
    statusText(status) {
      return {
        running: "运行中",
        starting: "启动中",
        stopped: "已停止",
        configured: "已配置",
      }[status] || "未知";
    },
    lastSeenText(value) {
      if (!value) return "还未检测";
      const date = new Date(Number(value));
      if (Number.isNaN(date.getTime())) return "还未检测";
      return date.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    },
    memoryHint(tool) {
      if (tool.startCommand) return "可从工作空间启动";
      if (tool.source === "detected") return "已记住链接，补充项目路径和启动命令后可一键启动";
      return "补充启动命令后可一键启动";
    },
    sourceText(source) {
      return source === "detected" ? "自动检测" : "手动";
    },
    statusRank(status) {
      return { running: 0, starting: 1, configured: 2, stopped: 3, unknown: 4 }[status] ?? 5;
    },
  },
}).mount("#app");
