(() => {
  "use strict";

  const PAGE_SIZE = 12;
  const NEWS_POLL_MS = 15000;
  const STATUS_POLL_MS = 5000;
  const INTERVAL_LABELS = {
    "1_minute": "1 Minute",
    "5_minutes": "5 Minutes",
    "1_hour": "1 Hour",
    "1_day": "1 Day",
  };
  const ICONS = {
    news: "#i-news",
    start: "#i-play",
    stop: "#i-stop",
    run: "#i-zap",
    schedule: "#i-calendar",
    external: "#i-arrow",
    error: "#i-bell",
  };
  const state = {
    interval: "1_day",
    selectedInterval: "1_day",
    category: "",
    keyword: "",
    scheduleDirty: false,
    skip: 0,
    articles: [],
    articleKeys: new Set(),
    totalArticles: null,
    status: null,
    actionPending: false,
    newsLoading: false,
    statusLoading: false,
    lastNewsRefresh: null,
    lastActivityKey: "",
    lastActivityTime: 0,
  };
  const elements = {};
  const byId = (id) => document.getElementById(id);

  function cacheElements() {
    [
      "sidebar", "sidebarScrim", "mobileMenu", "themeToggle", "globalSearch",
      "newsSearch", "newsList", "newsEmpty", "emptyMessage", "newsError",
      "categoryFilters", "loadMore", "resultCount", "refreshArticles",
      "refreshIndicator", "lastUiRefresh", "startScheduler", "stopScheduler",
      "applySchedule", "runNow", "schedulerMessage", "schedulerBadge",
      "topSchedulerStatus", "topStatusPulse", "statTotal", "statToday",
      "statStatus", "schedulerStatDot", "statInterval", "statLastSuccess",
      "statLastSuccessHint", "currentInterval", "lastRun", "nextRun",
      "countdown", "nextRunProgress", "activityList", "navArticleCount",
      "notificationButton", "notificationDot", "todayLabel", "briefingList",
      "apiHealthDot", "healthApiCheck", "healthApiStatus", "healthDatabaseCheck",
      "healthDatabaseStatus", "healthProviderCheck", "healthProviderStatus",
      "healthMessage",
    ].forEach((id) => {
      elements[id] = byId(id);
    });
  }

  function formatDate(value, options = {}) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: options.dateStyle || "medium",
      ...(options.timeStyle ? { timeStyle: options.timeStyle } : {}),
    }).format(date);
  }

  function formatRelative(value) {
    if (!value) return "Not yet";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    const delta = Date.now() - date.getTime();
    if (delta < 0) return formatDate(value, { timeStyle: "short" });
    const minutes = Math.floor(delta / 60000);
    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  }

  function iconUse(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icon");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", ICONS[name] || ICONS.news);
    svg.append(use);
    return svg;
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error(`The server returned an unreadable response (${response.status}).`);
    }
    if (!response.ok) {
      const message = payload && typeof payload.error === "string"
        ? payload.error
        : `Request failed with HTTP ${response.status}.`;
      throw new Error(message);
    }
    return payload;
  }

  function setSchedulerMessage(message = "", kind = "") {
    const target = elements.schedulerMessage;
    target.textContent = message;
    target.classList.toggle("error", kind === "error");
    target.classList.toggle("success", kind === "success");
  }

  function setLoading(button, loading, text) {
    if (!button) return;
    if (loading) {
      button.dataset.originalText = button.textContent.trim();
      button.classList.add("is-loading");
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.setAttribute("aria-label", `${text || button.dataset.originalText}, working`);
    } else {
      button.classList.remove("is-loading");
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.removeAttribute("aria-label");
    }
  }

  function setPending(pending, activeButton) {
    state.actionPending = pending;
    [elements.startScheduler, elements.stopScheduler, elements.applySchedule, elements.runNow]
      .forEach((button) => {
        if (button !== activeButton) button.disabled = pending;
      });
    document.querySelectorAll(".schedule-card").forEach((card) => {
      card.disabled = pending;
    });
    setLoading(activeButton, pending);
  }

  function setStatusDot(dot, stateName) {
    if (!dot) return;
    dot.classList.remove("good", "bad");
    if (stateName === "good") dot.classList.add("good");
    if (stateName === "bad") dot.classList.add("bad");
  }

  function setPulse(pulse, statusName) {
    if (!pulse) return;
    pulse.classList.remove("stopped", "error");
    if (statusName === "stopped") pulse.classList.add("stopped");
    if (statusName === "error") pulse.classList.add("error");
  }

  function renderSchedulerStatus(status) {
    state.status = status;
    state.interval = status.interval || state.interval;
    if (!state.scheduleDirty) state.selectedInterval = state.interval;
    state.totalArticles = status.total_articles == null
      ? null
      : Number(status.total_articles);

    document.querySelectorAll(".schedule-card").forEach((card) => {
      const selected = card.dataset.interval === state.selectedInterval;
      card.classList.toggle("selected", selected);
      card.setAttribute("aria-checked", String(selected));
    });

    const isRunning = Boolean(status.running);
    const statusLabel = status.collecting
      ? "Collecting"
      : isRunning ? "Running" : "Stopped";
    elements.topSchedulerStatus.textContent = statusLabel;
    elements.statStatus.textContent = statusLabel;
    elements.schedulerBadge.querySelector("span:last-child").textContent = statusLabel;
    [elements.topStatusPulse, elements.schedulerBadge.querySelector(".status-pulse")]
      .forEach((pulse) => setPulse(pulse, status.last_error ? "error" : isRunning ? "running" : "stopped"));
    elements.schedulerStatDot.classList.toggle("stopped", !isRunning);
    elements.currentInterval.textContent = status.schedule_label || INTERVAL_LABELS[state.interval] || "—";
    elements.statInterval.textContent = status.schedule_label || INTERVAL_LABELS[state.interval] || "—";
    elements.lastRun.textContent = status.last_run
      ? formatDate(status.last_run, { timeStyle: "short" })
      : "Not run yet";
    elements.nextRun.textContent = status.next_run
      ? formatDate(status.next_run, { timeStyle: "short" })
      : isRunning ? "Pending" : "Scheduler stopped";
    elements.statLastSuccess.textContent = status.last_successful_run
      ? formatRelative(status.last_successful_run)
      : "Not yet";
    elements.statLastSuccess.title = status.last_successful_run
      ? formatDate(status.last_successful_run, { dateStyle: "full", timeStyle: "long" })
      : "No successful collection has been recorded.";
    elements.statLastSuccessHint.textContent = status.last_successful_run
      ? formatDate(status.last_successful_run, { dateStyle: "medium", timeStyle: "short" })
      : "No successful collection recorded";
    elements.statTotal.textContent = status.total_articles == null
      ? "—"
      : Number(status.total_articles).toLocaleString();
    elements.statToday.textContent = status.today_articles == null
      ? "—"
      : Number(status.today_articles).toLocaleString();
    elements.navArticleCount.textContent = status.total_articles == null
      ? "—"
      : Number(status.total_articles).toLocaleString();
    elements.startScheduler.disabled = state.actionPending || isRunning;
    elements.stopScheduler.disabled = state.actionPending || !isRunning;
    elements.runNow.disabled = state.actionPending || Boolean(status.collecting || status.collection_queued);
    if (status.last_error) {
      elements.notificationDot.hidden = false;
      if (!state.actionPending) {
        setSchedulerMessage(`Last collection failed: ${status.last_error}`, "error");
      }
    } else {
      elements.notificationDot.hidden = true;
      if (elements.schedulerMessage.classList.contains("error")) setSchedulerMessage();
    }
    if (status.last_successful_run) {
      elements.healthMessage.textContent = status.last_error
        ? `A previous collection succeeded; the latest attempt failed: ${status.last_error}`
        : `Last confirmed collection succeeded ${formatRelative(status.last_successful_run)}.`;
    } else if (status.last_error) {
      elements.healthMessage.textContent = `Latest collection attempt failed: ${status.last_error}`;
    } else {
      elements.healthMessage.textContent = "Provider connectivity has not been confirmed by a collection yet.";
    }
    const providerHasSucceeded = Boolean(status.last_successful_run && !status.last_error);
    elements.healthProviderStatus.textContent = status.last_error
      ? "Last attempt failed"
      : providerHasSucceeded ? "Last collection succeeded" : "Not tested";
    setStatusDot(elements.healthProviderCheck, status.last_error ? "bad" : providerHasSucceeded ? "good" : "");
    renderActivity(status.activity || []);
    tickCountdown();
  }

  function tickCountdown() {
    const status = state.status;
    if (!status || !status.running || !status.next_run) {
      elements.countdown.textContent = status && status.collecting
        ? "Collection in progress"
        : "Waiting for scheduler";
      elements.nextRunProgress.style.width = "0%";
      return;
    }
    const next = new Date(status.next_run).getTime();
    const remaining = Math.max(0, next - Date.now());
    const totalSeconds = Math.floor(remaining / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const parts = [];
    if (hours) parts.push(`${hours}h`);
    if (minutes || hours) parts.push(`${minutes}m`);
    parts.push(`${seconds}s`);
    elements.countdown.textContent = `In ${parts.join(" ")}`;
    if (status.interval_trigger && status.interval_seconds > 0) {
      const progress = Math.max(0, Math.min(
        100,
        ((status.interval_seconds * 1000 - remaining) / (status.interval_seconds * 1000)) * 100,
      ));
      elements.nextRunProgress.style.width = `${progress}%`;
    } else {
      elements.nextRunProgress.style.width = "0%";
    }
  }

  function renderActivity(activity) {
    if (!activity.length) {
      elements.activityList.innerHTML = '<div class="activity-empty">No scheduler activity has been recorded yet.</div>';
      return;
    }
    const fragment = document.createDocumentFragment();
    activity.slice(0, 6).forEach((entry) => {
      const item = document.createElement("div");
      item.className = "activity-item";
      const level = entry.level === "error" ? "error"
        : /completed|started|requested/i.test(entry.message || "") ? "success" : "";
      const marker = document.createElement("span");
      marker.className = `activity-marker ${level}`;
      marker.append(iconUse(level === "error" ? "error" : /started/i.test(entry.message || "") ? "start" : "run"));
      const copy = document.createElement("div");
      copy.className = "activity-copy";
      const title = document.createElement("strong");
      title.textContent = entry.message || "Scheduler event";
      const time = document.createElement("time");
      time.className = "activity-time";
      time.dateTime = entry.timestamp || "";
      time.textContent = entry.timestamp ? formatDate(entry.timestamp, { timeStyle: "short" }) : "Time unavailable";
      copy.append(title, time);
      item.append(marker, copy);
      fragment.append(item);
    });
    elements.activityList.replaceChildren(fragment);
  }

  function safeArticleUrl(value) {
    if (typeof value !== "string") return null;
    try {
      const parsed = new URL(value);
      return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
    } catch (_error) {
      return null;
    }
  }

  function articleKey(article) {
    return article._id ? `id:${article._id}` : `url:${article.url || article.title || Math.random()}`;
  }

  function makeArticleCard(article) {
    const card = document.createElement("article");
    card.className = "article-card";
    const imageUrl = safeArticleUrl(article.image_url || article.urlToImage || article.image);
    if (imageUrl) {
      const image = document.createElement("img");
      image.className = "article-image";
      image.src = imageUrl;
      image.alt = "";
      image.loading = "lazy";
      image.referrerPolicy = "no-referrer";
      image.addEventListener("error", () => image.remove(), { once: true });
      card.append(image);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "article-image-placeholder";
      placeholder.append(iconUse("news"));
      card.append(placeholder);
    }

    const body = document.createElement("div");
    body.className = "article-body";
    const meta = document.createElement("div");
    meta.className = "article-meta";
    const category = document.createElement("span");
    category.className = "category-badge";
    category.textContent = article.category || "Other Technology";
    category.title = category.textContent;
    meta.append(category);
    if (article.is_demo) {
      const demo = document.createElement("span");
      demo.className = "demo-badge";
      demo.textContent = "DEMO DATA";
      meta.append(demo);
    }
    const source = document.createElement("span");
    source.className = "article-source";
    source.textContent = article.source || "Unknown source";
    meta.append(source);

    const title = document.createElement("h3");
    title.textContent = article.title || "Untitled article";
    const description = document.createElement("p");
    description.textContent = article.description || "No description was provided by the source.";
    const footer = document.createElement("div");
    footer.className = "article-footer";
    const published = document.createElement("time");
    published.className = "article-date";
    published.dateTime = article.published_at || article.collected_at || "";
    published.textContent = formatDate(article.published_at || article.collected_at, {
      timeStyle: "short",
    });
    footer.append(published);
    const url = safeArticleUrl(article.url);
    if (url) {
      const link = document.createElement("a");
      link.className = "article-link";
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.append(document.createTextNode("Read story"), iconUse("external"));
      footer.append(link);
    }
    body.append(meta, title, description, footer);
    card.append(body);
    return card;
  }

  function renderArticles() {
    const fragment = document.createDocumentFragment();
    state.articles.forEach((article) => fragment.append(makeArticleCard(article)));
    elements.newsList.replaceChildren(fragment);
    const hasArticles = state.articles.length > 0;
    elements.newsEmpty.hidden = hasArticles;
    elements.newsList.hidden = !hasArticles;
    elements.newsError.hidden = true;
    if (!hasArticles) {
      elements.emptyMessage.textContent = state.keyword || state.category
        ? "Try another search term or category filter."
        : "No articles are saved yet. Start the scheduler or use Run Now to collect news.";
    }
    const matchingCount = state.articles.length;
    elements.resultCount.textContent = state.totalArticles == null
      ? `${matchingCount} articles loaded`
      : `${matchingCount.toLocaleString()} loaded · ${Number(state.totalArticles).toLocaleString()} saved in total`;
    elements.loadMore.hidden = state.articles.length < state.skip + PAGE_SIZE;
    elements.loadMore.disabled = state.newsLoading;
  }

  function buildNewsUrl(skip = 0) {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), skip: String(skip) });
    if (state.category) params.set("category", state.category);
    if (state.keyword) params.set("keyword", state.keyword);
    return `/news?${params.toString()}`;
  }

  async function loadNews({ reset = true, silent = false } = {}) {
    if (state.newsLoading) return;
    state.newsLoading = true;
    elements.refreshIndicator.classList.add("loading");
    elements.loadMore.disabled = true;
    if (reset) {
      state.skip = 0;
      state.articles = [];
      state.articleKeys.clear();
      elements.newsError.hidden = true;
      elements.newsEmpty.hidden = true;
      if (!silent) {
        elements.newsList.hidden = false;
        elements.newsList.innerHTML = '<div class="news-skeleton"></div><div class="news-skeleton"></div><div class="news-skeleton"></div>';
      }
    }
    try {
      const articles = await requestJson(buildNewsUrl(state.skip));
      if (!Array.isArray(articles)) throw new Error("The news endpoint did not return an article list.");
      articles.forEach((article) => {
        const key = articleKey(article);
        if (!state.articleKeys.has(key)) {
          state.articleKeys.add(key);
          state.articles.push(article);
        }
      });
      state.skip += articles.length;
      state.lastNewsRefresh = new Date();
      elements.lastUiRefresh.textContent = state.lastNewsRefresh.toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit",
      });
      elements.lastUiRefresh.title = state.lastNewsRefresh.toLocaleString();
      renderArticles();
      await loadStatus({ silent: true });
    } catch (error) {
      if (reset) {
        elements.newsList.hidden = true;
        elements.newsEmpty.hidden = true;
      }
      elements.newsError.textContent = `Could not load saved articles: ${error.message}`;
      elements.newsError.hidden = false;
      elements.resultCount.textContent = "Article request failed";
    } finally {
      state.newsLoading = false;
      elements.refreshIndicator.classList.remove("loading");
      elements.loadMore.disabled = false;
    }
  }

  async function loadStatus({ silent = false } = {}) {
    if (state.statusLoading) return;
    state.statusLoading = true;
    try {
      const status = await requestJson("/scheduler/status");
      renderSchedulerStatus(status);
    } catch (error) {
      if (!silent) setSchedulerMessage(`Could not read scheduler status: ${error.message}`, "error");
      elements.topSchedulerStatus.textContent = "Unavailable";
      elements.statStatus.textContent = "Unavailable";
      setPulse(elements.topStatusPulse, "error");
      setStatusDot(elements.schedulerStatDot, "bad");
    } finally {
      state.statusLoading = false;
    }
  }

  async function loadHealth() {
    try {
      const health = await requestJson("/health");
      const apiOk = health.status === "ok";
      elements.healthApiStatus.textContent = apiOk ? "Operational" : "Unavailable";
      elements.healthDatabaseStatus.textContent = health.database === "connected" ? "Connected" : "Disconnected";
      elements.healthProviderStatus.textContent = health.news_provider_configured
        ? "Configured · not tested"
        : "Needs configuration";
      setStatusDot(elements.healthApiCheck, apiOk ? "good" : "bad");
      setStatusDot(elements.healthDatabaseCheck, health.database === "connected" ? "good" : "bad");
      setStatusDot(elements.healthProviderCheck, health.news_provider_configured ? "" : "bad");
      elements.apiHealthDot.style.background = apiOk ? "var(--green)" : "var(--red)";
      if (!state.status || (!state.status.last_error && !state.status.last_successful_run)) {
        elements.healthMessage.textContent = health.news_provider_configured
          ? "Provider settings are present. A collection is needed to confirm connectivity and credentials."
          : "Set the news-provider key and query in your local .env file; secrets are not displayed.";
      }
    } catch (_error) {
      elements.healthApiStatus.textContent = "Unavailable";
      elements.healthDatabaseStatus.textContent = "Unavailable";
      elements.healthProviderStatus.textContent = "Not checked";
      setStatusDot(elements.healthApiCheck, "bad");
      setStatusDot(elements.healthDatabaseCheck, "bad");
      elements.apiHealthDot.style.background = "var(--red)";
      elements.healthMessage.textContent = "The health endpoint could not be reached.";
    }
  }

  async function loadBriefings() {
    try {
      const briefings = await requestJson("/briefings?limit=5");
      if (!Array.isArray(briefings) || !briefings.length) {
        elements.briefingList.innerHTML = '<div class="activity-empty">No daily briefing has been generated yet. Run a collection to create one.</div>';
        return;
      }
      const fragment = document.createDocumentFragment();
      briefings.forEach((briefing) => {
        const row = document.createElement("div");
        row.className = "briefing-item";
        const summary = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = `Global Tech Briefing · ${briefing.briefing_date || "Date unavailable"}`;
        const detail = document.createElement("small");
        const categories = briefing.categories && typeof briefing.categories === "object"
          ? Object.keys(briefing.categories).join(", ")
          : "";
        detail.textContent = `${briefing.total_news ?? 0} saved articles${categories ? ` · ${categories}` : ""}`;
        summary.append(title, detail);
        const link = document.createElement("a");
        link.href = `/briefings/${encodeURIComponent(briefing.briefing_date || "")}`;
        link.textContent = "View details →";
        link.addEventListener("click", async (event) => {
          event.preventDefault();
          try {
            const detailData = await requestJson(link.href);
            showBriefingDetail(detailData);
          } catch (error) {
            setSchedulerMessage(`Could not open briefing: ${error.message}`, "error");
          }
        });
        row.append(summary, link);
        fragment.append(row);
      });
      elements.briefingList.replaceChildren(fragment);
    } catch (error) {
      elements.briefingList.textContent = `Could not load briefings: ${error.message}`;
    }
  }

  function showBriefingDetail(briefing) {
    const oldDetail = document.querySelector(".briefing-detail");
    if (oldDetail) oldDetail.remove();
    const detail = document.createElement("pre");
    detail.className = "briefing-detail";
    detail.textContent = typeof briefing.briefing_text === "string"
      ? briefing.briefing_text
      : JSON.stringify(briefing, null, 2);
    elements.briefingList.append(detail);
  }

  async function runSchedulerAction(button, route, body, successMessage) {
    if (state.actionPending) return;
    setPending(true, button);
    setSchedulerMessage("Updating scheduler…");
    try {
      const status = await requestJson(route, {
        method: body ? "PUT" : "POST",
        ...(body ? {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        } : {}),
      });
      if (route.endsWith("/interval")) state.scheduleDirty = false;
      if (status && typeof status.running === "boolean") renderSchedulerStatus(status);
      setSchedulerMessage(successMessage, "success");
      if (route.endsWith("run-now")) {
        setSchedulerMessage("Collection requested. The dashboard will show updated stories after the backend saves them.", "success");
      }
      await loadStatus({ silent: true });
      if (route.endsWith("run-now")) {
        window.setTimeout(() => {
          if (!document.hidden) loadNews({ reset: true, silent: true });
        }, 1200);
      }
    } catch (error) {
      setSchedulerMessage(error.message, "error");
    } finally {
      setPending(false);
      await loadStatus({ silent: true });
    }
  }

  function chooseInterval(interval) {
    state.selectedInterval = interval;
    state.scheduleDirty = true;
    document.querySelectorAll(".schedule-card").forEach((card) => {
      const selected = card.dataset.interval === interval;
      card.classList.toggle("selected", selected);
      card.setAttribute("aria-checked", String(selected));
    });
  }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("signaldesk-theme", theme);
    } catch (_error) {
      // Theme still applies for this page when browser storage is unavailable.
    }
    const use = elements.themeToggle.querySelector("use");
    use.setAttribute("href", theme === "dark" ? "#i-sun" : "#i-moon");
    elements.themeToggle.setAttribute(
      "aria-label",
      theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
    );
  }

  function closeSidebar() {
    elements.sidebar.classList.remove("open");
    elements.sidebarScrim.classList.remove("visible");
  }

  function debounce(callback, wait) {
    let timer;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => callback(...args), wait);
    };
  }

  function bindEvents() {
    document.querySelectorAll(".schedule-card").forEach((card) => {
      card.addEventListener("click", () => chooseInterval(card.dataset.interval));
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          chooseInterval(card.dataset.interval);
        }
      });
    });
    elements.applySchedule.addEventListener("click", () => {
      runSchedulerAction(
        elements.applySchedule,
        "/scheduler/interval",
        { interval: state.selectedInterval },
        `Schedule updated to ${INTERVAL_LABELS[state.selectedInterval]}.`,
      );
    });
    elements.startScheduler.addEventListener("click", () => {
      runSchedulerAction(elements.startScheduler, "/scheduler/start", null, "Scheduler started.");
    });
    elements.stopScheduler.addEventListener("click", () => {
      if (state.status && state.status.running
        && !window.confirm("Stop automatic news collection? An active collection will finish, but future scheduled runs will pause.")) {
        return;
      }
      runSchedulerAction(elements.stopScheduler, "/scheduler/stop", null, "Scheduler stopped.");
    });
    elements.runNow.addEventListener("click", () => {
      runSchedulerAction(elements.runNow, "/scheduler/run-now", null, "Manual collection queued.");
    });
    elements.refreshArticles.addEventListener("click", () => loadNews({ reset: true }));
    elements.loadMore.addEventListener("click", () => loadNews({ reset: false }));

    elements.categoryFilters.addEventListener("click", (event) => {
      const button = event.target.closest("[data-category]");
      if (!button) return;
      state.category = button.dataset.category || "";
      elements.categoryFilters.querySelectorAll(".filter-chip").forEach((chip) => {
        chip.classList.toggle("selected", chip === button);
      });
      loadNews({ reset: true });
    });

    const applySearch = debounce((value) => {
      state.keyword = value.trim();
      elements.newsSearch.value = value;
      elements.globalSearch.value = value;
      loadNews({ reset: true });
    }, 350);
    elements.newsSearch.addEventListener("input", () => applySearch(elements.newsSearch.value));
    elements.globalSearch.addEventListener("input", () => applySearch(elements.globalSearch.value));
    elements.globalSearch.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        state.keyword = elements.globalSearch.value.trim();
        elements.newsSearch.value = state.keyword;
        loadNews({ reset: true });
        byId("latest-news").scrollIntoView({ behavior: "smooth" });
      }
    });
    byId("navSearch").addEventListener("click", () => {
      window.setTimeout(() => elements.globalSearch.focus(), 0);
    });

    elements.themeToggle.addEventListener("click", () => {
      setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    });
    elements.notificationButton.addEventListener("click", () => {
      byId("scheduler").scrollIntoView({ behavior: "smooth" });
      if (state.status && state.status.last_error) {
        setSchedulerMessage(`Last collection failed: ${state.status.last_error}`, "error");
      } else {
        setSchedulerMessage("No collection errors are currently reported.", "success");
      }
    });
    elements.mobileMenu.addEventListener("click", () => {
      elements.sidebar.classList.add("open");
      elements.sidebarScrim.classList.add("visible");
    });
    elements.sidebarScrim.addEventListener("click", closeSidebar);
    elements.sidebar.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeSidebar));
    document.querySelectorAll(".nav-link").forEach((link) => {
      link.addEventListener("click", () => {
        document.querySelectorAll(".nav-link").forEach((item) => item.classList.remove("active"));
        link.classList.add("active");
      });
    });
    document.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        elements.globalSearch.focus();
      }
      if (event.key === "Escape") closeSidebar();
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        loadNews({ reset: true, silent: true });
        loadStatus({ silent: true });
        loadHealth();
      }
    });
  }

  function startPolling() {
    window.setInterval(() => {
      if (!document.hidden) loadNews({ reset: true, silent: true });
    }, NEWS_POLL_MS);
    window.setInterval(() => {
      if (!document.hidden) loadStatus({ silent: true });
    }, STATUS_POLL_MS);
    window.setInterval(tickCountdown, 1000);
    window.setInterval(loadHealth, 30000);
    window.setInterval(loadBriefings, 60000);
  }

  function initialize() {
    cacheElements();
    let savedTheme = "dark";
    try {
      savedTheme = localStorage.getItem("signaldesk-theme") || "dark";
    } catch (_error) {
      savedTheme = "dark";
    }
    setTheme(savedTheme === "light" ? "light" : "dark");
    elements.todayLabel.textContent = new Intl.DateTimeFormat(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(new Date());
    bindEvents();
    loadNews();
    loadStatus();
    loadHealth();
    loadBriefings();
    startPolling();
  }

  document.addEventListener("DOMContentLoaded", initialize, { once: true });
})();
