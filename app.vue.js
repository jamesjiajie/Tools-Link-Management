const { createApp } = Vue;

createApp({
  data() {
    return {
      tools: [],
      view: "workspace",
      query: "",
      sortMode: "status",
      busy: false,
      stoppingOthers: false,
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
    stoppableOtherCount() {
      return this.tools.filter((tool) => this.isRunning(tool) && !this.isLinkManagement(tool)).length;
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
    async stopOtherLinks() {
      this.stoppingOthers = true;
      try {
        const payload = await this.api("/api/tools/stop-others", { method: "POST" });
        this.tools = payload.tools;
        const stopped = payload.stopped?.length || 0;
        const failed = payload.errors?.length || 0;
        if (failed) {
          this.notify(`已停止 ${stopped} 个链接，${failed} 个失败`);
        } else {
          this.notify(stopped ? `已停止 ${stopped} 个其他链接` : "没有其他运行中的链接");
        }
      } catch (error) {
        this.notify(error.message);
      } finally {
        this.stoppingOthers = false;
      }
    },
    cloneTool(tool) {
      return JSON.parse(JSON.stringify(tool));
    },
    openEditor(tool = null) {
      this.editing = tool ? this.cloneTool(tool) : this.emptyTool();
      this.tagText = (this.editing.tags || []).join(", ");
      if (this.$refs.editorDialog.open) this.$refs.editorDialog.close();
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
      const name = tool.name || tool.url || "这个工具";
      if (!window.confirm(`从工作空间删除「${name}」？`)) return;
      try {
        await this.api(`/api/tools/${tool.id}`, { method: "DELETE" });
        if (this.$refs.editorDialog.open) this.closeEditor();
        await this.refreshTools();
        this.notify("已删除");
      } catch (error) {
        this.notify(error.message);
      }
    },
    async startTool(tool) {
      if (!tool.startCommand) {
        this.openEditor(tool);
        this.notify("先补充项目路径和启动命令");
        return;
      }
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
    isLinkManagement(tool) {
      const text = [tool.name, tool.url, tool.projectPath, tool.startCommand].filter(Boolean).join(" ").toLowerCase();
      return tool.port === "4173" || text.includes("link-management") || text.includes("portal hub");
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
    startButtonText(tool) {
      if (!tool.startCommand) return "配置启动";
      return this.isRunning(tool) ? "已启动" : "启动";
    },
    sourceText(source) {
      return source === "detected" ? "自动检测" : "手动";
    },
    statusRank(status) {
      return { running: 0, starting: 1, configured: 2, stopped: 3, unknown: 4 }[status] ?? 5;
    },
  },
}).mount("#app");
