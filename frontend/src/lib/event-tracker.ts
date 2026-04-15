/**
 * 浅愈(GentleMend) — 前端事件采集 SDK
 *
 * 功能:
 *   - 5 个 PRD 事件的类型安全采集
 *   - session_id 生成与管理（串联用户旅程）
 *   - 批量上报（攒批 + 定时 flush + 页面离开时 flush）
 *   - IndexedDB 离线缓存，网络恢复后自动重传
 */

// ============================================================
// 类型定义
// ============================================================

export enum EventType {
  ASSESSMENT_STARTED = "assessment_started",
  ASSESSMENT_SUBMITTED = "assessment_submitted",
  RESULT_VIEWED = "result_viewed",
  CONTACT_TEAM_CLICKED = "contact_team_clicked",
  ASSESSMENT_CLOSED = "assessment_closed",
}

export interface EventPayload {
  /** 事件类型 */
  event_type: EventType;
  /** 客户端时间戳 ISO 8601 */
  timestamp: string;
  /** 会话 ID，串联同一用户旅程 */
  session_id: string;
  /** 关联的评估 ID（可选） */
  assessment_id?: string;
  /** 事件附加数据 */
  payload?: Record<string, unknown>;
}

export interface TrackerConfig {
  /** 事件上报接口地址 */
  endpoint: string;
  /** 攒批大小，达到后立即 flush */
  batchSize: number;
  /** 定时 flush 间隔（毫秒） */
  flushInterval: number;
  /** 单次重试最大次数 */
  maxRetries: number;
  /** session 过期时间（毫秒），默认 30 分钟 */
  sessionTimeout: number;
}

const DEFAULT_CONFIG: TrackerConfig = {
  endpoint: "/api/v1/events",
  batchSize: 10,
  flushInterval: 5_000,
  maxRetries: 3,
  sessionTimeout: 30 * 60 * 1000,
};

// ============================================================
// IndexedDB 离线缓存
// ============================================================

const DB_NAME = "gentlemend_events";
const STORE_NAME = "pending_events";
const DB_VERSION = 1;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function persistEvents(events: EventPayload[]): Promise<void> {
  const db = await openDB();
  const tx = db.transaction(STORE_NAME, "readwrite");
  const store = tx.objectStore(STORE_NAME);
  for (const evt of events) {
    store.add(evt);
  }
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function loadAndClearPersistedEvents(): Promise<EventPayload[]> {
  const db = await openDB();
  const tx = db.transaction(STORE_NAME, "readwrite");
  const store = tx.objectStore(STORE_NAME);
  const all = store.getAll();
  return new Promise((resolve, reject) => {
    all.onsuccess = () => {
      store.clear();
      resolve(all.result as EventPayload[]);
    };
    all.onerror = () => reject(all.error);
  });
}

// ============================================================
// Session 管理
// ============================================================

const SESSION_KEY = "gentlemend_session";

interface SessionData {
  id: string;
  createdAt: number;
}

function generateSessionId(): string {
  // 时间戳前缀 + crypto 随机，保证唯一且可排序
  const ts = Date.now().toString(36);
  const rand = crypto.getRandomValues(new Uint8Array(12));
  const hex = Array.from(rand, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${ts}-${hex}`;
}

function getOrCreateSession(timeout: number): string {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (raw) {
      const data: SessionData = JSON.parse(raw);
      if (Date.now() - data.createdAt < timeout) {
        return data.id;
      }
    }
  } catch {
    // sessionStorage 不可用时 fallback
  }
  const newSession: SessionData = {
    id: generateSessionId(),
    createdAt: Date.now(),
  };
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(newSession));
  } catch {
    // ignore
  }
  return newSession.id;
}

// ============================================================
// EventTracker 核心类
// ============================================================

export class EventTracker {
  private config: TrackerConfig;
  private buffer: EventPayload[] = [];
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private isFlushing = false;

  constructor(config?: Partial<TrackerConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /** 初始化：启动定时 flush、监听页面离开、重传离线缓存 */
  init(): void {
    // 定时 flush
    this.flushTimer = setInterval(
      () => void this.flush(),
      this.config.flushInterval,
    );

    // 页面离开时用 sendBeacon 兜底
    if (typeof window !== "undefined") {
      window.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") {
          this.flushSync();
        }
      });
      window.addEventListener("pagehide", () => this.flushSync());

      // 网络恢复时重传 IndexedDB 中的离线事件
      window.addEventListener("online", () => void this.retryPersisted());
    }

    // 启动时也尝试重传
    void this.retryPersisted();
  }

  /** 销毁：清理定时器 */
  destroy(): void {
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    void this.flush();
  }

  /** 获取当前 session_id */
  get sessionId(): string {
    return getOrCreateSession(this.config.sessionTimeout);
  }

  // ----------------------------------------------------------
  // 5 个 PRD 事件的便捷方法
  // ----------------------------------------------------------

  /** 用户打开评估页面时触发 */
  trackAssessmentStarted(assessmentId?: string): void {
    this.track(EventType.ASSESSMENT_STARTED, assessmentId, {
      referrer: typeof document !== "undefined" ? document.referrer : "",
      url: typeof window !== "undefined" ? window.location.pathname : "",
    });
  }

  /** 用户提交评估表单时触发 */
  trackAssessmentSubmitted(
    assessmentId: string,
    meta: { inputLength: number; symptomCount: number },
  ): void {
    this.track(EventType.ASSESSMENT_SUBMITTED, assessmentId, {
      input_length: meta.inputLength,
      symptom_count: meta.symptomCount,
    });
  }

  /** 用户查看评估结果时触发 */
  trackResultViewed(
    assessmentId: string,
    meta: { riskLevel: string; loadTimeMs: number },
  ): void {
    this.track(EventType.RESULT_VIEWED, assessmentId, {
      risk_level: meta.riskLevel,
      load_time_ms: meta.loadTimeMs,
    });
  }

  /** 用户点击"联系医疗团队"按钮时触发 */
  trackContactTeamClicked(
    assessmentId: string,
    meta: { urgency: string },
  ): void {
    this.track(EventType.CONTACT_TEAM_CLICKED, assessmentId, {
      urgency: meta.urgency,
    });
  }

  /** 用户关闭/离开评估页面时触发 */
  trackAssessmentClosed(
    assessmentId: string,
    meta: { durationSec: number; completed: boolean },
  ): void {
    this.track(EventType.ASSESSMENT_CLOSED, assessmentId, {
      duration_sec: meta.durationSec,
      completed: meta.completed,
    });
  }

  // ----------------------------------------------------------
  // 核心方法
  // ----------------------------------------------------------

  /** 通用事件采集入口 */
  private track(
    eventType: EventType,
    assessmentId?: string,
    payload?: Record<string, unknown>,
  ): void {
    const event: EventPayload = {
      event_type: eventType,
      timestamp: new Date().toISOString(),
      session_id: this.sessionId,
      ...(assessmentId && { assessment_id: assessmentId }),
      ...(payload && { payload }),
    };
    this.buffer.push(event);

    // 达到批量阈值立即 flush
    if (this.buffer.length >= this.config.batchSize) {
      void this.flush();
    }
  }

  /** 异步 flush：通过 fetch 批量上报 */
  async flush(): Promise<void> {
    if (this.isFlushing || this.buffer.length === 0) return;
    this.isFlushing = true;

    const batch = this.buffer.splice(0, this.config.batchSize);
    let retries = 0;

    while (retries < this.config.maxRetries) {
      try {
        const resp = await fetch(this.config.endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ events: batch }),
        });
        if (resp.ok) {
          this.isFlushing = false;
          return;
        }
        // 服务端 5xx 时重试
        if (resp.status >= 500) {
          retries++;
          await this.backoff(retries);
          continue;
        }
        // 4xx 客户端错误不重试，丢弃
        console.warn("[EventTracker] 事件被服务端拒绝:", resp.status);
        this.isFlushing = false;
        return;
      } catch {
        retries++;
        if (retries >= this.config.maxRetries) {
          // 网络不可达，持久化到 IndexedDB
          await persistEvents(batch).catch(() => {
            console.error("[EventTracker] IndexedDB 写入失败，事件丢失");
          });
          this.isFlushing = false;
          return;
        }
        await this.backoff(retries);
      }
    }
    this.isFlushing = false;
  }

  /** 同步 flush：页面离开时用 sendBeacon 兜底 */
  private flushSync(): void {
    if (this.buffer.length === 0) return;
    const batch = this.buffer.splice(0);
    const blob = new Blob(
      [JSON.stringify({ events: batch })],
      { type: "application/json" },
    );
    const sent = navigator.sendBeacon(this.config.endpoint, blob);
    if (!sent) {
      // sendBeacon 失败，尝试写 IndexedDB（异步，尽力而为）
      void persistEvents(batch);
    }
  }

  /** 重传 IndexedDB 中的离线事件 */
  private async retryPersisted(): Promise<void> {
    try {
      const events = await loadAndClearPersistedEvents();
      if (events.length > 0) {
        this.buffer.unshift(...events);
        await this.flush();
      }
    } catch {
      // IndexedDB 不可用时静默忽略
    }
  }

  /** 指数退避 */
  private backoff(attempt: number): Promise<void> {
    const ms = Math.min(1000 * 2 ** attempt, 10_000);
    return new Promise((r) => setTimeout(r, ms));
  }
}

// ============================================================
// 单例导出（Next.js 客户端使用）
// ============================================================

let _instance: EventTracker | null = null;

export function getEventTracker(
  config?: Partial<TrackerConfig>,
): EventTracker {
  if (!_instance) {
    _instance = new EventTracker(config);
    _instance.init();
  }
  return _instance;
}
