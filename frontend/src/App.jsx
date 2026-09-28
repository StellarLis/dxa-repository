import { useEffect, useMemo, useState } from "react";

const API = "/api";
const TERMINAL_JOB_STATUSES = ["SUCCESS", "FAILED", "PARTIAL"];

async function request(path, options = {}) {
  const token = localStorage.getItem("dxa_token");
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    if (response.status === 401 && token) {
      localStorage.removeItem("dxa_token");
      window.dispatchEvent(new Event("dxa:unauthorized"));
    }
    let message = `Ошибка запроса (${response.status})`;
    try {
      const payload = await response.json();
      message = payload.message || payload.error || message;
    } catch {
      // Сервер может вернуть ответ без JSON.
    }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

async function download(path) {
  const token = localStorage.getItem("dxa_token");
  const response = await fetch(`${API}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (response.status === 401 && token) {
    localStorage.removeItem("dxa_token");
    window.dispatchEvent(new Event("dxa:unauthorized"));
  }
  if (!response.ok) throw new Error(`Ошибка выгрузки (${response.status})`);
  return response.blob();
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function statusLabel(status) {
  const labels = {
    PENDING: "Ожидает обработки",
    QUEUED: "В очереди",
    PROCESSING: "Обрабатывается",
    SUCCESS: "Успешно",
    FAILED: "Ошибка",
    PARTIAL: "Частично завершено",
    FAILURE: "Ошибка",
  };
  return labels[status] || status || "Ожидает обработки";
}

function qualityLabel(scan) {
  if (scan.processingStatus === "SUCCESS") {
    if (scan.qualityClass === 0) return "Успешно";
    if (scan.qualityClass === 1) return "Неуспешно";
    return "Не определено";
  }
  if (scan.processingStatus === "FAILED") return "Неуспешно";
  return "Ожидает обработки";
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem("dxa_token"));
  const [authMode, setAuthMode] = useState("login");
  const [view, setView] = useState("researches");
  const [researches, setResearches] = useState([]);
  const [selectedResearch, setSelectedResearch] = useState(null);
  const [scans, setScans] = useState([]);
  const [selectedScan, setSelectedScan] = useState(null);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [error, setError] = useState("");

  const loadResearches = async () => {
    setLoading(true);
    setError("");
    try {
      setResearches(await request("/researches"));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const openResearch = async (research) => {
    setSelectedResearch(research);
    setSelectedScan(null);
    setView("research-detail");
    setError("");
    try {
      setScans(await request(`/researches/${research.id}/scans`));
    } catch (err) {
      setError(err.message);
    }
  };

  const openScan = async (scan) => {
    setError("");
    setView("scan-detail");
    setSelectedScan(scan);
    try {
      setSelectedScan(await request(`/scans/${scan.id}`));
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    if (token) loadResearches();
  }, [token]);

  useEffect(() => {
    const handleUnauthorized = () => {
      setAuthMode("register");
      setToken(null);
      setSelectedResearch(null);
      setSelectedScan(null);
      setJob(null);
      setView("researches");
    };
    window.addEventListener("dxa:unauthorized", handleUnauthorized);
    return () =>
      window.removeEventListener("dxa:unauthorized", handleUnauthorized);
  }, []);

  useEffect(() => {
    if (!job || TERMINAL_JOB_STATUSES.includes(job.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const nextJob = await request(`/jobs/${job.jobId}`);
        setJob(nextJob);
        if (selectedResearch)
          setScans(await request(`/researches/${selectedResearch.id}/scans`));
      } catch (err) {
        setError(err.message);
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [job, selectedResearch]);

  const exportReport = async () => {
    if (!selectedResearch) return;
    setReportLoading(true);
    setError("");
    try {
      const blob = await download(`/researches/${selectedResearch.id}/report`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${selectedResearch.name || "research-report"}.xlsx`.replace(/[\\/:*?"<>|]/g, "_");
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    } finally {
      setReportLoading(false);
    }
  };

  const signOut = () => {
    localStorage.removeItem("dxa_token");
    setToken(null);
    setSelectedResearch(null);
    setSelectedScan(null);
    setJob(null);
  };
  if (!token)
    return <AuthScreen initialMode={authMode} onAuthenticated={setToken} />;

  const backToResearch = () => {
    setView("research-detail");
    setSelectedScan(null);
  };
  const goHome = () => {
    setView("researches");
    setSelectedResearch(null);
    setSelectedScan(null);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">+</span>
          <span>
            Clarity <b>DXA</b>
          </span>
        </div>
        <div className="workspace-label">КЛИНИЧЕСКОЕ ПРОСТРАНСТВО</div>
        <nav>
          <button
            className={view === "researches" ? "nav-item active" : "nav-item"}
            onClick={goHome}
          >
            <span className="nav-icon">▦</span> Исследования
          </button>
          {selectedResearch && (
            <button
              className={
                view === "research-detail" || view === "scan-detail"
                  ? "nav-item active"
                  : "nav-item"
              }
              onClick={backToResearch}
            >
              <span className="nav-icon">◈</span> Текущее исследование
            </button>
          )}
        </nav>
        <div className="sidebar-foot">
          <div className="secure-badge">
            <span>✓</span>
            <div>
              <strong>Защищённое пространство</strong>
              <small>Шифрование медицинских данных</small>
            </div>
          </div>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <div>
            <span className="eyebrow">Контроль качества DXA</span>
            <h1>
              {view === "research-detail"
                ? selectedResearch?.name
                : view === "scan-detail"
                  ? "Результат исследования"
                  : "Исследования"}
            </h1>
          </div>
          <div className="top-actions">
            <span className="status-dot">Система онлайн</span>
            <button className="avatar-button" onClick={signOut} title="Выйти">
              DR
            </button>
          </div>
        </header>
        {error && (
          <div className="alert" role="alert">
            <span>!</span>
            {error}
            <button onClick={() => setError("")}>Закрыть</button>
          </div>
        )}
        {view === "researches" && (
          <ResearchList
            researches={researches}
            loading={loading}
            onCreate={() => setView("create")}
            onOpen={openResearch}
          />
        )}
        {view === "create" && (
          <CreateResearch
            onCancel={goHome}
            onCreated={(research) => {
              setResearches((items) => [research, ...items]);
              openResearch(research);
            }}
          />
        )}
        {view === "research-detail" && selectedResearch && (
          <ResearchDetail
            research={selectedResearch}
            scans={scans}
            job={job}
            onScan={openScan}
            onExport={exportReport}
            reportLoading={reportLoading}
            onUpload={async (files) => {
              setLoading(true);
              setError("");
              try {
                const form = new FormData();
                files.forEach((file) => form.append("files", file));
                const response = await request(
                  `/researches/${selectedResearch.id}/scans`,
                  { method: "POST", body: form },
                );
                setJob(await request(`/jobs/${response.jobId}`));
                setScans(
                  await request(`/researches/${selectedResearch.id}/scans`),
                );
              } catch (err) {
                setError(err.message);
              } finally {
                setLoading(false);
              }
            }}
            onBack={goHome}
          />
        )}
        {view === "scan-detail" && selectedScan && (
          <ScanDetail scan={selectedScan} onBack={backToResearch} />
        )}
      </main>
    </div>
  );
}

function AuthScreen({ initialMode, onAuthenticated }) {
  const [mode, setMode] = useState(initialMode);
  const [form, setForm] = useState({
    email: "",
    password: "",
    displayName: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const payload =
        mode === "login"
          ? { email: form.email, password: form.password }
          : form;
      const response = await request(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      localStorage.setItem("dxa_token", response.accessToken);
      onAuthenticated(response.accessToken);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="auth-page">
      <div className="auth-panel">
        <div className="brand">
          <span className="brand-mark">+</span>
          <span>
            Clarity <b>DXA</b>
          </span>
        </div>
        <div className="auth-copy">
          <span className="eyebrow">Рабочее пространство для снимков</span>
          <h1>
            Каждый снимок
            <br />
            <em>имеет значение.</em>
          </h1>
          <p>
            Проверяйте и контролируйте качество исследований DXA в одном
            спокойном клиническом интерфейсе.
          </p>
        </div>
        <div className="auth-note">
          <span>◉</span>
          <span>
            Для внимательного клинического анализа
            <br />
            <small>Безопасно по умолчанию. Понятно по дизайну.</small>
          </span>
        </div>
      </div>
      <div className="auth-form-wrap">
        <div className="auth-form">
          <div className="form-kicker">
            {mode === "login" ? "С возвращением" : "Новое пространство"}
          </div>
          <h2>
            {mode === "login"
              ? "Войдите, чтобы продолжить"
              : "Создайте аккаунт"}
          </h2>
          <p className="muted">
            {mode === "login"
              ? "Введите данные клинического пространства."
              : "Аккаунт откроет доступ к вашим исследованиям."}
          </p>
          <form onSubmit={submit}>
            {mode === "register" && (
              <label>
                Имя пользователя
                <input
                  required
                  value={form.displayName}
                  onChange={(e) =>
                    setForm({ ...form, displayName: e.target.value })
                  }
                  placeholder="Иван Петров"
                />
              </label>
            )}
            <label>
              Электронная почта
              <input
                required
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="doctor@clinic.ru"
              />
            </label>
            <label>
              Пароль
              <input
                required
                minLength={8}
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="Не менее 8 символов"
              />
            </label>
            {error && <div className="form-error">{error}</div>}
            <button className="primary-button full" disabled={loading}>
              {loading
                ? "Подключение..."
                : mode === "login"
                  ? "Войти"
                  : "Создать аккаунт"}{" "}
              <span>→</span>
            </button>
          </form>
          <button
            className="switch-button"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError("");
            }}
          >
            {mode === "login"
              ? "Нет аккаунта? Создать"
              : "Уже зарегистрированы? Войти"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ResearchList({ researches, loading, onCreate, onOpen }) {
  const totalScans = useMemo(
    () => researches.reduce((sum, item) => sum + item.scanCount, 0),
    [researches],
  );
  return (
    <section className="content-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Ваша клиническая библиотека</span>
          <h2>Все исследования</h2>
          <p className="muted">
            Сфокусированный обзор рабочего процесса контроля DXA.
          </p>
        </div>
        <button className="primary-button" onClick={onCreate}>
          <span>+</span> Новое исследование
        </button>
      </div>
      <div className="metric-row">
        <div className="metric">
          <span className="metric-label">Активные исследования</span>
          <strong>{researches.length}</strong>
          <small>В вашем пространстве</small>
        </div>
        <div className="metric">
          <span className="metric-label">Получено снимков</span>
          <strong>{totalScans}</strong>
          <small>Готовы к проверке</small>
        </div>
        <div className="metric accent">
          <span className="metric-label">Статус анализа</span>
          <strong>Онлайн</strong>
          <small>Конвейер обработки работает</small>
        </div>
      </div>
      {loading ? (
        <div className="empty-state">Загрузка исследований...</div>
      ) : researches.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">+</div>
          <h3>Пространство готово к работе</h3>
          <p>Создайте исследование, чтобы начать загрузку снимков DXA.</p>
          <button className="primary-button" onClick={onCreate}>
            Создать первое исследование
          </button>
        </div>
      ) : (
        <div className="research-grid">
          {researches.map((research) => (
            <button
              className="research-card"
              key={research.id}
              onClick={() => onOpen(research)}
            >
              <div className="card-top">
                <span className="research-symbol">◈</span>
                <span className="arrow">↗</span>
              </div>
              <h3>{research.name}</h3>
              <p>{research.description || "Описание не добавлено."}</p>
              <div className="card-meta">
                <span>
                  <strong>{research.scanCount}</strong> снимков
                </span>
                <span>Обновлено {formatDate(research.updatedAt)}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function CreateResearch({ onCancel, onCreated }) {
  const [form, setForm] = useState({ name: "", description: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      onCreated(
        await request("/researches", {
          method: "POST",
          body: JSON.stringify(form),
        }),
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  return (
    <section className="form-section">
      <button className="back-link" onClick={onCancel}>
        ← Все исследования
      </button>
      <div className="form-card">
        <div className="form-kicker">Новая клиническая коллекция</div>
        <h2>Создать исследование</h2>
        <p className="muted">
          Создайте именованное пространство для группы снимков DXA.
        </p>
        <form onSubmit={submit}>
          <label>
            Название исследования
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Например, контроль качества тазобедренных суставов"
            />
          </label>
          <label>
            Описание <span className="optional">Необязательно</span>
            <textarea
              rows="4"
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              placeholder="Добавьте заметку о группе пациентов или периоде проверки."
            />
          </label>
          {error && <div className="form-error">{error}</div>}
          <div className="form-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={onCancel}
            >
              Отмена
            </button>
            <button className="primary-button" disabled={loading}>
              {loading ? "Создание..." : "Создать исследование"} <span>→</span>
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}

function ResearchDetail({ research, scans, job, onUpload, onScan, onExport, reportLoading, onBack }) {
  const [files, setFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const addFiles = (incoming) =>
    setFiles((current) => [
      ...current,
      ...Array.from(incoming).filter(
        (file) => !current.some((item) => item.name === file.name),
      ),
    ]);
  return (
    <section className="content-section">
      <button className="back-link" onClick={onBack}>
        ← Все исследования
      </button>
      <div className="detail-header">
        <div>
          <span className="eyebrow">Детали исследования</span>
          <h2>{research.name}</h2>
          <p className="muted">
            {research.description || "Описание не добавлено."}
          </p>
        </div>
        <div className="detail-actions">
          <button className="secondary-button" onClick={onExport} disabled={reportLoading}>
            {reportLoading ? "Формирование..." : "Выгрузить отчёт"} <span>↓</span>
          </button>
          <div className="detail-count">
            <strong>{scans.length}</strong>
            <span>снимков в исследовании</span>
          </div>
        </div>
      </div>
      <div className="upload-layout">
        <div className="upload-card">
          <div className="card-heading">
            <div>
              <h3>Загрузить снимки</h3>
              <p className="muted">
                Добавьте DICOM-файлы для асинхронного контроля качества.
              </p>
            </div>
            <span className="file-type">DICOM</span>
          </div>
          <label
            className={dragging ? "dropzone dragging" : "dropzone"}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              addFiles(e.dataTransfer.files);
            }}
          >
            <input
              type="file"
              multiple
              accept=".dcm,application/dicom"
              onChange={(e) => addFiles(e.target.files)}
            />
            <span className="upload-icon">↑</span>
            <strong>Перетащите DICOM-файлы сюда</strong>
            <small>или нажмите, чтобы выбрать их на устройстве</small>
          </label>
          {files.length > 0 && (
            <div className="file-list">
              {files.map((file) => (
                <div className="file-row" key={file.name}>
                  <span className="file-icon">D</span>
                  <span>
                    {file.name}
                    <small>{(file.size / 1024 / 1024).toFixed(2)} МБ</small>
                  </span>
                  <button
                    onClick={() =>
                      setFiles(files.filter((item) => item.name !== file.name))
                    }
                  >
                    ×
                  </button>
                </div>
              ))}
              <button
                className="primary-button full"
                onClick={() => {
                  onUpload(files);
                  setFiles([]);
                }}
              >
                Отправить: {files.length}{" "}
                {files.length === 1 ? "снимок" : "снимка"} <span>→</span>
              </button>
            </div>
          )}
        </div>
        <div className="pipeline-card">
          <span className="eyebrow">Конвейер обработки</span>
          <div className={job ? "pipeline-status active" : "pipeline-status"}>
            <span className="pulse"></span>
            <div>
              <strong>
                {job ? statusLabel(job.status) : "Готов к работе"}
              </strong>
              <small>
                {job
                  ? `${job.counts?.success || 0} из ${job.totalScans} обработано`
                  : "Загрузите файлы, чтобы начать анализ"}
              </small>
            </div>
          </div>
          {job && (
            <div className="progress-track">
              <span
                style={{
                  width: `${job.totalScans ? (((job.counts?.success || 0) + (job.counts?.failed || 0)) / job.totalScans) * 100 : 0}%`,
                }}
              />
            </div>
          )}
          <div className="pipeline-note">
            Результаты обрабатываются асинхронно. Страница обновится
            автоматически.
          </div>
        </div>
      </div>
      <div className="table-heading">
        <div>
          <span className="eyebrow">Очередь снимков</span>
          <h3>Загруженные исследования</h3>
        </div>
        <span className="table-count">Всего: {scans.length}</span>
      </div>
      {scans.length === 0 ? (
        <div className="empty-state compact">
          <h3>Снимков пока нет</h3>
          <p>Загрузите DICOM-исследования, чтобы увидеть их статус здесь.</p>
        </div>
      ) : (
        <div className="scan-table">
          <div className="table-row table-head">
            <span>Имя файла</span>
            <span>Область</span>
            <span>Статус</span>
            <span>Контроль качества</span>
            <span>Загружен</span>
          </div>
          {scans.map((scan) => (
            <button
              className="table-row scan-row-button"
              key={scan.id}
              onClick={() => onScan(scan)}
            >
              <span className="filename">
                <span className="file-icon">D</span>
                {scan.originalFilename}
              </span>
              <span>{scan.anatomicalRegion || "Ожидает"}</span>
              <span>
                <span
                  className={`status-pill ${String(scan.processingStatus || "").toLowerCase()}`}
                >
                  {statusLabel(scan.processingStatus)}
                </span>
              </span>
              <span>
                <span
                  className={`quality-pill ${qualityLabel(scan) === "Успешно" ? "success" : qualityLabel(scan) === "Неуспешно" ? "failed" : "pending"}`}
                >
                  {qualityLabel(scan)}
                </span>
              </span>
              <span>{formatDate(scan.uploadedAt)}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function ScanDetail({ scan, onBack }) {
  const fields = [
    ["ID снимка", scan.id],
    ["ID исследования", scan.researchId],
    ["ID задания", scan.jobId],
    ["Study UID", scan.studyUid],
    ["Image UID", scan.imageUid],
    ["Исходное имя файла", scan.originalFilename],
    ["Область исследования", scan.anatomicalRegion],
    [
      "Класс качества",
      scan.qualityClass === null || scan.qualityClass === undefined
        ? "Не определён"
        : scan.qualityClass,
    ],
    ["Тип нарушения", scan.violationType],
    ["Комментарий", scan.comment],
    [
      "Время обработки",
      scan.timeOfProcessing ? `${scan.timeOfProcessing.toFixed(3)} с` : "—",
    ],
    ["Загружен", formatDate(scan.uploadedAt)],
    ["Обработан", formatDate(scan.processedAt)],
  ];
  const imageSource = scan.thumbnailPngB64
    ? `data:image/png;base64,${scan.thumbnailPngB64}`
    : null;
  return (
    <section className="content-section scan-detail-page">
      <button className="back-link" onClick={onBack}>
        ← Вернуться к исследованию
      </button>
      <div className="scan-detail-heading">
        <div>
          <span className="eyebrow">Полный результат контроля</span>
          <h2>{scan.originalFilename || "Снимок DXA"}</h2>
          <p className="muted">
            Результат обработки одного DICOM-исследования.
          </p>
        </div>
        <span
          className={`status-pill large ${String(scan.processingStatus || "").toLowerCase()}`}
        >
          {statusLabel(scan.processingStatus)}
        </span>
      </div>
      <div className="scan-result-layout">
        <div className="scan-preview-panel">
          <div className="panel-label">Предпросмотр снимка</div>
          {imageSource ? (
            <img
              className="scan-preview"
              src={imageSource}
              alt="Предпросмотр DICOM-снимка"
            />
          ) : (
            <div className="scan-preview-empty">
              <span>◉</span>
              <strong>Предпросмотр недоступен</strong>
              <small>
                Изображение ещё не обработано или не было возвращено сервисом.
              </small>
            </div>
          )}
        </div>
        <div className="quality-panel">
          <div className="panel-label">Результат контроля качества</div>
          <div className="quality-result">
            <span
              className={
                scan.qualityClass === 1 ? "quality-mark bad" : "quality-mark"
              }
            >
              {scan.qualityClass === 1 ? "!" : "✓"}
            </span>
            <div>
              <strong>
                {scan.qualityClass === null || scan.qualityClass === undefined
                  ? "Класс не определён"
                  : scan.qualityClass === 1
                    ? "Требуется внимание"
                    : "Качество соответствует"}
              </strong>
              <small>
                {scan.anatomicalRegion || "Анатомическая область определяется"}
              </small>
            </div>
          </div>
          {scan.errorMessage && (
            <div className="result-warning">
              <strong>Сообщение обработки</strong>
              <span>{scan.errorMessage}</span>
            </div>
          )}
          {scan.comment && (
            <div className="result-comment">
              <strong>Комментарий специалиста</strong>
              <p>{scan.comment}</p>
            </div>
          )}
        </div>
      </div>
      <div className="scan-data-panel">
        <div className="panel-label">Данные исследования</div>
        <div className="scan-data-grid">
          {fields.map(([label, value]) => (
            <div className="data-field" key={label}>
              <span>{label}</span>
              <strong>{value || "—"}</strong>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default App;
