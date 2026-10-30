import { useCallback, useEffect, useMemo, useState } from "react";

type Camera = {
  camera_id: string;
  name?: string;
  source: string;
  link: string;
  det_size?: number;
  fps_cap?: number;
  enabled?: boolean;
  track_lost_secs?: number;
  track_activation?: number;
  track_min_frames?: number;
};
type TestResult = {
  snapshot?: string;
  resolution?: number[];
  fps?: number | null;
  error?: string;
};
type CameraStatus = {
  camera_id: string;
  name?: string;
  state: string;
  processed_fps: number | null;
  people: number;
  tracks: number;
  drops: number;
  preview_drops: number;
  health: string;
  last_event: { kind?: string; detail?: string; t_wall?: string } | null;
  session_folder: string | null;
  preview_port: number | null;
  error?: string | null;
  calibration_warning?: string | null;
  last_error?: CameraError | null;
  recent_events?: CameraEvent[];
  calibration?: { calibration_id: string; check_error_m: number } | null;
};
const STATE_LABELS: Record<string, string> = {
  starting: "starting",
  loading_model: "loading model",
  waiting_first_frame: "waiting for first frame",
  recording: "recording",
  preview_ready: "preview ready",
  stopping: "stopping",
  ended: "ended",
  interrupted: "interrupted",
  error: "error",
};
const PREVIEW_WAIT: Record<string, string> = {
  starting: "Opening source…",
  loading_model: "Loading model…",
  waiting_first_frame: "Waiting for first frame…",
  recording: "Preparing preview…",
};

type CameraError = { message: string; detail: string; at: string };
type CameraEvent = { t_wall: string; kind: string; detail: string | null };
type IdleCamera = {
  camera_id: string;
  last_error: CameraError | null;
  recent_events: CameraEvent[];
};
type Status = {
  running: boolean;
  cameras: CameraStatus[];
  idle_cameras?: IdleCamera[];
  config_warning?: string | null;
  uncalibrated?: Record<string, string>; // camera_id -> refusal it will start with
};
type FieldIssue = { index: number | null; field: string; message: string };

// why Studio refused a calibration (D-057)
type Refusal =
  | { kind: "too_few_points"; role: "calibration" | "check"; have: number; need: number }
  | {
      kind: "check_error_over_limit";
      check_point_indices: number[];
      check_errors_m: number[];
      check_mean_m: number;
      max_check_error_m: number;
    }
  | { kind: "invalid" };
class RequestError extends Error {
  fields: FieldIssue[];
  refusal?: Refusal;

  constructor(message: string, fields: FieldIssue[] = [], refusal?: Refusal) {
    super(message);
    this.fields = fields;
    this.refusal = refusal;
  }
}
type Session = {
  camera_id: string | null;
  group_id: string | null;
  status: string | null;
  folder: string;
  started_at: string | null;
  duration: number | null;
  fps: number | null;
  captured: number | null;
  dropped: number | null;
  drop_rate: number | null;
  events: Record<string, number>;
  missing: string[];
};
function formatDuration(seconds: number | null) {
  if (seconds === null) return "unknown";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h} h ${m} min` : m > 0 ? `${m} min ${s} s` : `${s} s`;
}
function formatEvents(events: Record<string, number>) {
  const kinds = Object.entries(events);
  if (kinds.length === 0) return "none";
  const total = kinds.reduce((sum, [, n]) => sum + n, 0);
  return `${total} (${kinds.map(([kind, n]) => `${kind.replaceAll("_", " ")} ${n}`).join(", ")})`;
}
type Point = {
  id: string;
  image_px: [number, number];
  court_m: [number, number];
  role: "calibration" | "check";
};
type Court = {
  kind: "fiba_full" | "fiba_half" | "custom";
  length_m: number;
  width_m: number;
  landmarks: Record<string, [number, number]>;
};
type Fit = {
  ransac_threshold_m: number;
  ransac_dropped_points: number[];
  point_errors_m: number[];
  calibration_mean_m: number;
  check_mean_m: number | null;
  check_max_m: number | null;
  projected_court_lines: number[][][];
  court: Court;
};
type CourtGeometry = {
  landmarks: Record<string, [number, number]>;
  lines: [number, number][][];
};
type CalibrationFrame = {
  token: string;
  url: string;
  width: number;
  height: number;
};
type Comparison = {
  audit_frame: string;
  fresh_frame: string;
  difference_score: number | null;
  warning: boolean;
};

async function request<T>(
  url: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text.replace(/^"|"$/g, "");
    let fields: FieldIssue[] = [];
    let refusal: Refusal | undefined;
    try {
      refusal = JSON.parse(text).refusal;
      const detail = JSON.parse(text).detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object") {
        message = detail.message ?? "Camera settings were rejected.";
        fields = Array.isArray(detail.fields) ? detail.fields : [];
      }
    } catch {
      // not JSON: show the text as it is
    }
    throw new RequestError(message, fields, refusal);
  }
  return response.json() as Promise<T>;
}

function errorText(cameraId: string, error: CameraError) {
  return [
    `Camera ${cameraId} · ${error.at}`,
    error.message,
    "",
    error.detail,
  ].join("\n");
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

// An error stays until the user dismisses it (or the camera next starts):
// there is no timer anywhere in this component.
function ErrorPanel({
  cameraId,
  error,
  onDismiss,
}: {
  cameraId: string;
  error: CameraError;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="error-panel" role="alert">
      <div className="error-panel-head">
        <b>{error.message}</b>
        <time dateTime={error.at}>{new Date(error.at).toLocaleString()}</time>
      </div>
      {error.detail && (
        <details>
          <summary>Technical detail</summary>
          <pre>{error.detail}</pre>
        </details>
      )}
      <div className="error-panel-actions">
        <button
          type="button"
          onClick={async () => {
            await copyText(errorText(cameraId, error));
            setCopied(true);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

function EventLog({ events }: { events: CameraEvent[] }) {
  if (events.length === 0) return null;
  const counts = new Map<string, number>();
  const rows = events.map((event) => {
    const base = `${event.t_wall}|${event.kind}|${event.detail}`;
    const n = (counts.get(base) ?? 0) + 1;
    counts.set(base, n);
    return { key: `${base}#${n}`, event };
  });
  return (
    <details className="event-log">
      <summary>Event log ({events.length})</summary>
      <ol>
        {rows.map(({ key, event }) => (
          <li key={key}>
            <time dateTime={event.t_wall}>
              {new Date(event.t_wall).toLocaleTimeString()}
            </time>
            <b>{event.kind}</b>
            {event.detail && <span>{event.detail}</span>}
          </li>
        ))}
      </ol>
    </details>
  );
}

const emptyCamera: Camera = {
  camera_id: "cam1",
  name: "Camera 1",
  source: "0",
  link: "builtin",
  enabled: true,
};
export default function StudioApp() {
  const [page, setPage] = useState("Record");
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [status, setStatus] = useState<Status>({ running: false, cameras: [] });
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState("");
  const [offline, setOffline] = useState(""); // the poll failed; clears when it works again
  const [notice, setNotice] = useState("");
  const [tested, setTested] = useState<Record<string, TestResult>>({});
  const [fieldErrors, setFieldErrors] = useState<FieldIssue[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<Camera>(emptyCamera);
  const [selected, setSelected] = useState("");
  const [frame, setFrame] = useState<CalibrationFrame | null>(null);
  const [points, setPoints] = useState<Point[]>([]);
  const [undoPoint, setUndoPoint] = useState<Point | null>(null);
  const [pendingImage, setPendingImage] = useState<[number, number] | null>(
    null,
  );
  const [courtKind, setCourtKind] = useState<"fiba_full" | "fiba_half" | "custom">("custom");
  const [length, setLength] = useState(28);
  const [width, setWidth] = useState(15);
  const [maxError, setMaxError] = useState(0.5);
  const [saveAnyway, setSaveAnyway] = useState(false);
  const [fit, setFit] = useState<Fit | null>(null);
  // the refusal being shown, and the camera whose next start is uncalibrated because of it
  const [refused, setRefused] = useState<{
    camera: string;
    message: string;
    refusal: Refusal;
  } | null>(null);
  const skippedReason = selected
    ? status.uncalibrated?.[selected]
    : undefined;
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [customX, setCustomX] = useState(0);
  const [customY, setCustomY] = useState(0);
  const [hoverPoint, setHoverPoint] = useState<number | null>(null);
  const [geometry, setGeometry] = useState<CourtGeometry | null>(null);
  // the diagram and the snap points come from the server's court model, the one the fit uses
  const landmarks: Record<string, [number, number]> =
    fit?.court.landmarks ?? geometry?.landmarks ?? {};
  const fitCourtPoints = points.filter((point) => point.role === "calibration");
  const fitXs = fitCourtPoints.map((point) => point.court_m[0]);
  const fitYs = fitCourtPoints.map((point) => point.court_m[1]);
  const fitAreaCoverage =
    courtKind === "fiba_half" && fitXs.length >= 4
      ? ((Math.max(...fitXs) - Math.min(...fitXs)) *
          (Math.max(...fitYs) - Math.min(...fitYs))) /
        (14 * 15)
      : null;
  const halfAnchors = new Set([
    "corner_near_left",
    "corner_near_right",
    "midcourt_near_corner",
    "midcourt_far_corner",
  ]);

  const refresh = useCallback(async () => {
    try {
      const [nextCameras, nextStatus] = await Promise.all([
        request<Camera[]>("/api/cameras"),
        request<Status>("/api/status"),
      ]);
      setCameras(nextCameras);
      setStatus(nextStatus);
      setOffline("");
      setSelected((old) =>
        nextCameras.some((camera) => camera.camera_id === old)
          ? old
          : nextCameras[0]?.camera_id || "",
      );
    } catch (reason) {
      setOffline(String(reason));
    }
  }, []);

  useEffect(() => {
    let current = true;
    const query = new URLSearchParams({
      kind: courtKind,
      length_m: String(length),
      width_m: String(width),
    });
    request<CourtGeometry>(`/api/court?${query}`)
      .then((next) => current && setGeometry(next))
      .catch(() => current && setGeometry(null)); // e.g. a dimension mid-edit: no diagram yet
    return () => {
      current = false;
    };
  }, [courtKind, length, width]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 1200);
    return () => clearInterval(timer);
  }, [refresh]);

  async function action(url: string, method = "POST", body?: unknown) {
    try {
      await request(url, method, body);
      setNotice("Changes saved.");
      setFieldErrors([]);
      await refresh();
      return true;
    } catch (reason) {
      setNotice("");
      setError(String(reason));
      setFieldErrors(reason instanceof RequestError ? reason.fields : []);
      await refresh(); // a refused start leaves its reason in the camera's own panel
      return false;
    }
  }

  async function dismissCameraError(cameraId: string) {
    try {
      await request(`/api/cameras/${cameraId}/error`, "DELETE");
      await refresh();
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function loadSessions() {
    try {
      setSessions(await request<Session[]>("/api/sessions"));
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function submitCamera(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const saved = await action(
      editing ? `/api/cameras/${editing}` : "/api/cameras",
      editing ? "PUT" : "POST",
      form,
    );
    if (saved) {
      setEditing(null);
      setForm(emptyCamera);
    }
  }

  const formIndex = editing
    ? cameras.findIndex((camera) => camera.camera_id === editing)
    : cameras.length;
  function fieldError(field: string) {
    return fieldErrors
      .filter((issue) => issue.field === field && (issue.index === null || issue.index === formIndex))
      .map((issue) => issue.message)
      .join("; ");
  }

  async function captureFrame() {
    if (!selected) return;
    try {
      const response = await fetch(
        `/api/cameras/${selected}/calibration/frame`,
      );
      if (!response.ok) throw new Error(await response.text());
      const blob = await response.blob();
      setFrame({
        token: response.headers.get("X-Frame-Token") ?? "",
        url: URL.createObjectURL(blob),
        width: Number(response.headers.get("X-Frame-Width")),
        height: Number(response.headers.get("X-Frame-Height")),
      });
      setPoints([]);
      setPendingImage(null);
      setFit(null);
      setComparison(null);
      setNotice(
        `Frame captured at ${response.headers.get("X-Frame-Width")} × ${response.headers.get("X-Frame-Height")} px. Recording checks this size before using the calibration.`,
      );
      setError("");
    } catch (reason) {
      setError(String(reason));
    }
  }

  const fitPayload = useMemo(
    () => ({
      frame_token: frame?.token,
      court_kind: courtKind,
      length_m: length,
      width_m: width,
      max_check_error_m: maxError,
      save_anyway: saveAnyway,
      points: points.map(({ id, ...point }) => point),
    }),
    [frame, courtKind, length, width, maxError, saveAnyway, points],
  );

  const showFitError = useCallback(
    (reason: unknown) => {
      if (reason instanceof RequestError && reason.refusal) {
        setRefused({
          camera: selected,
          message: reason.message,
          refusal: reason.refusal,
        });
        setError("");
      } else setError(String(reason));
    },
    [selected],
  );

  async function runFit(save = false) {
    if (!selected) return;
    try {
      const result = await request<Fit>(
        `/api/cameras/${selected}/calibration${save ? "" : "/fit"}`,
        save ? "PUT" : "POST",
        fitPayload,
      );
      setFit(result);
      setRefused(null);
      setNotice(
        save
          ? "Calibration saved for this camera."
          : "Fit updated. Check the held-out points before saving.",
      );
      setError("");
    } catch (reason) {
      showFitError(reason);
    }
  }

  async function startUncalibrated() {
    try {
      await request(`/api/cameras/${selected}/calibration/uncalibrated`, "POST");
      setRefused(null);
      setNotice(
        `Camera ${selected} will start uncalibrated; the calibration check is recorded as failed.`,
      );
      setError("");
      void refresh();
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function undoUncalibrated() {
    try {
      await request(`/api/cameras/${selected}/calibration/uncalibrated`, "DELETE");
      void refresh();
    } catch (reason) {
      setError(String(reason));
    }
  }

  useEffect(() => {
    if (
      !frame ||
      !selected ||
      points.filter((point) => point.role === "calibration").length < 4
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      void request<Fit>(
        `/api/cameras/${selected}/calibration/fit`,
        "POST",
        fitPayload,
      )
        .then((result) => {
          setFit(result);
          setRefused(null);
          setError("");
        })
        .catch((reason: unknown) => showFitError(reason));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [frame, selected, points, fitPayload, showFitError]);

  useEffect(() => {
    return () => {
      if (frame) URL.revokeObjectURL(frame.url);
    };
  }, [frame]);

  function markImage(event: React.MouseEvent<HTMLButtonElement>) {
    if (!frame) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.round(
      ((event.clientX - rect.left) * frame.width) / rect.width,
    );
    const y = Math.round(
      ((event.clientY - rect.top) * frame.height) / rect.height,
    );
    setPendingImage([x, y]);
    setNotice(
      "Image point selected. Click its matching location on the court, or enter coordinates below.",
    );
  }

  function addPoint(x: number, y: number) {
    if (!pendingImage) return;
    setPoints((old) => [
      ...old,
      {
        id: crypto.randomUUID(),
        image_px: pendingImage,
        court_m: [Number(x.toFixed(3)), Number(y.toFixed(3))],
        role: "calibration",
      },
    ]);
    setPendingImage(null);
    setFit(null);
  }

  async function compare() {
    try {
      setComparison(
        await request<Comparison>(
          `/api/cameras/${selected}/calibration/compare`,
        ),
      );
    } catch (reason) {
      setError(String(reason));
    }
  }

  function changePage(item: string) {
    setPage(item);
    setNotice("");
    if (item === "Sessions") void loadSessions();
  }

  return (
    <div className="studio-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">P</span>
          <span>
            <b>Pointr</b>
            <small>LOCAL STUDIO</small>
          </span>
        </div>
        <div className="side-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {["Record", "Cameras", "Calibration", "Sessions"].map((item, i) => (
            <button
              type="button"
              className={page === item ? "nav-item active" : "nav-item"}
              key={item}
              onClick={() => changePage(item)}
            >
              <span className="nav-index">0{i + 1}</span>
              {item}
            </button>
          ))}
        </nav>
        <div className="side-bottom">
          <span className={status.running ? "pulse on" : "pulse"} />
          {status.running ? "Recording group active" : "Local device ready"}
          <small>Data stays on this computer</small>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div>
            <div className="eyebrow">POINTR V0 / {page.toUpperCase()}</div>
            <h1>{page === "Record" ? "Recording" : page}</h1>
          </div>
          <div className="top-status">
            <span
              className={status.running ? "status-dot live" : "status-dot"}
            />
            {status.running ? "Group recording" : "Not recording"}
          </div>
        </header>
        {offline && (
          <div role="status" className="notice error-box">
            Lost contact with Studio ({offline}). Recording is not affected.
            Retrying…
          </div>
        )}
        {status.config_warning && (
          <div role="alert" className="notice error-box">
            Camera configuration warning: {status.config_warning}
          </div>
        )}
        {(error || notice) && (
          <div role="status" className={error ? "notice error-box" : "notice"}>
            {error || notice}
            <button
              type="button"
              aria-label="Dismiss message"
              onClick={() => {
                setError("");
                setNotice("");
              }}
            >
              ×
            </button>
          </div>
        )}

        {page === "Cameras" && (
          <section className="page-content">
            <div className="section-heading">
              <div>
                <div className="eyebrow">INPUT SOURCES</div>
                <h2>Camera setup</h2>
                <p>
                  Configure each view once. A phone stream can only have one
                  viewer.
                </p>
              </div>
              <span className="count-pill">{cameras.length} configured</span>
            </div>
            <div className="camera-layout">
              <form
                className="form-panel"
                onSubmit={(event) => void submitCamera(event)}
              >
                <h3>{editing ? "Edit camera" : "Add a camera"}</h3>
                <label>
                  Camera ID
                  <input
                    required
                    value={form.camera_id}
                    onChange={(event) =>
                      setForm({ ...form, camera_id: event.target.value })
                    }
                    placeholder="cam1"
                    aria-invalid={!!fieldError("camera_id")}
                  />
                  {fieldError("camera_id") && (
                    <small className="field-error">{fieldError("camera_id")}</small>
                  )}
                </label>
                <label>
                  Display name
                  <input
                    required
                    value={form.name ?? form.camera_id}
                    onChange={(event) =>
                      setForm({ ...form, name: event.target.value })
                    }
                    placeholder="Main court"
                    aria-invalid={!!fieldError("name")}
                  />
                  {fieldError("name") && (
                    <small className="field-error">{fieldError("name")}</small>
                  )}
                </label>
                <label>
                  Connection type
                  <select
                    value={form.link}
                    onChange={(event) =>
                      setForm({ ...form, link: event.target.value })
                    }
                  >
                    <option value="builtin">Built-in camera</option>
                    <option value="usb">USB camera</option>
                    <option value="wifi">Wi-Fi phone</option>
                    <option value="file">Video file</option>
                  </select>
                  {fieldError("link") && (
                    <small className="field-error">{fieldError("link")}</small>
                  )}
                </label>
                <label>
                  {form.link === "wifi"
                    ? "Phone stream URL"
                    : form.link === "builtin" || form.link === "usb"
                      ? "Camera index"
                      : "Video path"}
                  <input
                    required
                    value={form.source}
                    onChange={(event) =>
                      setForm({ ...form, source: event.target.value })
                    }
                    placeholder={
                      form.link === "wifi"
                        ? "http://192.168.1.20:4747/video"
                        : "0"
                    }
                    aria-invalid={!!fieldError("source")}
                  />
                  {fieldError("source") && (
                    <small className="field-error">{fieldError("source")}</small>
                  )}
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={form.enabled !== false}
                    aria-invalid={!!fieldError("enabled")}
                    onChange={(event) =>
                      setForm({ ...form, enabled: event.target.checked })
                    }
                  />
                  Enabled for recording
                  {fieldError("enabled") && (
                    <small className="field-error">{fieldError("enabled")}</small>
                  )}
                </label>
                <details>
                  <summary>Detection and tracking options</summary>
                  <div className="option-grid">
                    <label>
                      Detection size
                      <select
                        value={form.det_size ?? ""}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            det_size: event.target.value
                              ? Number(event.target.value)
                              : undefined,
                          })
                        }
                        aria-invalid={!!fieldError("det_size")}
                      >
                        <option value="">Model default</option>
                        {Array.from({ length: 31 }, (_, index) => 320 + index * 32).map(
                          (size) => (
                            <option key={size} value={size}>
                              {size}
                            </option>
                          ),
                        )}
                      </select>
                      {fieldError("det_size") && (
                        <small className="field-error">{fieldError("det_size")}</small>
                      )}
                    </label>
                    <label>
                      FPS cap (optional)
                      <input
                        type="number"
                        min="1"
                        max="60"
                        step="1"
                        value={form.fps_cap ?? ""}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            fps_cap: event.target.value
                              ? Number(event.target.value)
                              : undefined,
                          })
                        }
                        placeholder="No cap"
                        aria-invalid={!!fieldError("fps_cap")}
                      />
                      {fieldError("fps_cap") && (
                        <small className="field-error">{fieldError("fps_cap")}</small>
                      )}
                    </label>
                    <label>
                      Lost track (seconds)
                      <input
                        type="number"
                        min="0.01"
                        step="0.1"
                        value={form.track_lost_secs ?? ""}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            track_lost_secs: event.target.value
                              ? Number(event.target.value)
                              : undefined,
                          })
                        }
                        placeholder="1.0"
                      />
                    </label>
                    <label>
                      Track activation
                      <input
                        type="number"
                        min="0.01"
                        max="1"
                        step="0.01"
                        value={form.track_activation ?? ""}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            track_activation: event.target.value
                              ? Number(event.target.value)
                              : undefined,
                          })
                        }
                        placeholder="0.7"
                      />
                    </label>
                    <label>
                      Minimum frames
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={form.track_min_frames ?? ""}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            track_min_frames: event.target.value
                              ? Number(event.target.value)
                              : undefined,
                          })
                        }
                        placeholder="2"
                      />
                    </label>
                  </div>
                </details>
                <button className="primary" type="submit">
                  {editing ? "Save changes" : "Add camera"}
                </button>
                {editing && (
                  <button
                    type="button"
                    className="quiet"
                    onClick={() => {
                      setEditing(null);
                      setForm(emptyCamera);
                    }}
                  >
                    Cancel edit
                  </button>
                )}
              </form>
              <div className="camera-list">
                <h3>Your cameras</h3>
                {cameras.length === 0 && (
                  <p className="empty">
                    No cameras yet. Add a source to get started.
                  </p>
                )}
                {cameras.map((camera) => (
                  <article className="camera-row" key={camera.camera_id}>
                    <div>
                      <b>{camera.name || camera.camera_id}</b>
                      <span>
                        {camera.camera_id} · {camera.link} · {camera.source}
                      </span>
                    </div>
                    <div className="row-actions">
                      <button
                        type="button"
                        onClick={async () => {
                          let result: TestResult;
                          try {
                            result = await request<TestResult>(
                              `/api/cameras/${camera.camera_id}/test`,
                              "POST",
                            );
                          } catch (reason) {
                            result = { error: String(reason) };
                          }
                          setTested((old) => ({
                            ...old,
                            [camera.camera_id]: result,
                          }));
                        }}
                      >
                        Test
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setEditing(camera.camera_id);
                          setForm(camera);
                        }}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="danger-text"
                        onClick={() =>
                          void action(
                            `/api/cameras/${camera.camera_id}`,
                            "DELETE",
                          )
                        }
                      >
                        Remove
                      </button>
                    </div>
                    {tested[camera.camera_id] && (
                      <div
                        className={
                          tested[camera.camera_id].error
                            ? "test-result test-failed"
                            : "test-result"
                        }
                      >
                        {tested[camera.camera_id].snapshot && (
                          <img
                            alt={`${camera.camera_id} test snapshot`}
                            src={`data:image/jpeg;base64,${tested[camera.camera_id].snapshot}`}
                          />
                        )}
                        {tested[camera.camera_id].error ? (
                          <p>Test failed: {tested[camera.camera_id].error}</p>
                        ) : (
                          <p>Test passed</p>
                        )}
                        <small>
                          {tested[camera.camera_id].resolution
                            ? `${tested[camera.camera_id].resolution?.join(" × ")} · `
                            : ""}
                          {tested[camera.camera_id].fps != null
                            ? `${tested[camera.camera_id].fps?.toFixed(1)} fps`
                            : "no frame rate"}
                        </small>
                        <button
                          type="button"
                          onClick={() =>
                            setTested(
                              ({ [camera.camera_id]: _gone, ...rest }) => rest,
                            )
                          }
                        >
                          Dismiss
                        </button>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </div>
          </section>
        )}

        {page === "Record" && (
          <section className="page-content">
            <div className="section-heading">
              <div>
                <div className="eyebrow">SESSION CONTROL</div>
                <h2>
                  {status.running
                    ? "Recording in progress"
                    : "Ready when you are"}
                </h2>
                <p>
                  Start all configured cameras together. Recording continues if
                  you close this browser tab.
                </p>
              </div>
              <div className="record-actions">
                <button
                  className="primary"
                  type="button"
                  disabled={status.running || !cameras.some((camera) => camera.enabled !== false)}
                  onClick={() => void action("/api/recording/start")}
                >
                  Start group
                </button>
                <button
                  className="stop-button"
                  type="button"
                  disabled={!status.running}
                  onClick={() => void action("/api/recording/stop")}
                >
                  Stop group
                </button>
              </div>
            </div>
            {!status.running &&
              status.cameras.length === 0 &&
              !status.idle_cameras?.length && (
              <div className="empty-state">
                <span>01</span>
                <b>No camera group is active</b>
                <p>
                  Add your camera sources, then return here to start recording.
                </p>
                <button type="button" onClick={() => changePage("Cameras")}>
                  Set up cameras
                </button>
              </div>
            )}
            <div className="record-grid">
              {status.cameras.map((camera) => (
                <article className="feed" key={camera.camera_id}>
                  <div className="feed-head">
                    <div>
                      <span className="eyebrow">CAMERA</span>
                      <h3>{camera.name || camera.camera_id}</h3>
                    </div>
                    <span className={`state ${camera.state}`}>
                      {STATE_LABELS[camera.state] ?? camera.state}
                    </span>
                  </div>
                  {camera.preview_port ? (
                    <img
                      className="preview"
                      alt={`${camera.camera_id} live annotated preview`}
                      src={`/api/cameras/${camera.camera_id}/preview/mjpeg`}
                    />
                  ) : (
                    <div className="preview-placeholder">
                      {PREVIEW_WAIT[camera.state] ?? "Preview unavailable"}
                    </div>
                  )}
                  <div className="metric-strip">
                    <span>
                      <b>{camera.processed_fps?.toFixed(1) ?? "—"}</b>
                      <small>FPS</small>
                    </span>
                    <span>
                      <b>{camera.people}</b>
                      <small>PEOPLE</small>
                    </span>
                    <span>
                      <b>{camera.tracks}</b>
                      <small>TRACKS</small>
                    </span>
                    <span>
                      <b>{camera.drops}</b>
                      <small>DROPS</small>
                    </span>
                  </div>
                  <div className="feed-foot">
                    <span className={`health-tag ${camera.health}`}>
                      {camera.health}
                    </span>
                    <span>
                      {camera.calibration
                        ? `Calibrated · check ${camera.calibration.check_error_m.toFixed(2)} m`
                        : "Not calibrated · positions in pixels"}
                    </span>
                  </div>
                  {camera.calibration_warning && (
                    <p className="feed-warning" role="alert">
                      Calibration not used: {camera.calibration_warning}
                    </p>
                  )}
                  {camera.last_error ? (
                    <ErrorPanel
                      cameraId={camera.camera_id}
                      error={camera.last_error}
                      onDismiss={() => void dismissCameraError(camera.camera_id)}
                    />
                  ) : (
                    camera.state === "error" &&
                    camera.error && <p className="feed-error">{camera.error}</p>
                  )}
                  <EventLog events={camera.recent_events ?? []} />
                  {camera.last_event && (
                    <small className="last-event">
                      Last event: {JSON.stringify(camera.last_event)}
                    </small>
                  )}
                  {camera.session_folder && (
                    <small className="session-path">
                      {camera.session_folder}
                    </small>
                  )}
                  {!status.running &&
                    ["interrupted", "ended"].includes(camera.state) && (
                      <p className="result-clean">
                        Recording saved · {camera.state}
                      </p>
                    )}
                </article>
              ))}
              {(status.idle_cameras ?? []).map((camera) => (
                <article className="feed" key={camera.camera_id}>
                  <div className="feed-head">
                    <div>
                      <span className="eyebrow">CAMERA</span>
                      <h3>{camera.camera_id}</h3>
                    </div>
                    <span className="state error">not started</span>
                  </div>
                  {camera.last_error && (
                    <ErrorPanel
                      cameraId={camera.camera_id}
                      error={camera.last_error}
                      onDismiss={() => void dismissCameraError(camera.camera_id)}
                    />
                  )}
                  <EventLog events={camera.recent_events} />
                </article>
              ))}
            </div>
          </section>
        )}

        {page === "Calibration" && (
          <section className="page-content calibration-page">
            <div className="section-heading">
              <div>
                <div className="eyebrow">PART 5B · CAMERA GEOMETRY</div>
                <h2>Map the floor to metres</h2>
                <p>
                  Mark known floor points in the image, then pair them with
                  measured court coordinates.
                </p>
              </div>
              <span className="count-pill">
                {status.running
                  ? "Camera can be sampled live"
                  : "Camera must be stationary"}
              </span>
            </div>
            <div className="calibration-controls">
              <label>
                Camera
                <select
                  value={selected}
                  onChange={(event) => {
                    setSelected(event.target.value);
                    setFrame(null);
                    setPoints([]);
                    setFit(null);
                  }}
                >
                  <option value="">Choose camera</option>
                  {cameras.map((camera) => (
                    <option key={camera.camera_id} value={camera.camera_id}>
                      {camera.camera_id} · {camera.link}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Court model
                <select
                  value={courtKind}
                  onChange={(event) => {
                    const kind = event.target.value as
                      | "fiba_full"
                      | "fiba_half"
                      | "custom";
                    setCourtKind(kind);
                    if (kind === "fiba_full") {
                      setLength(28);
                      setWidth(15);
                    } else if (kind === "fiba_half") {
                      setLength(14);
                      setWidth(15);
                    }
                    setPoints([]);
                    setFit(null);
                  }}
                >
                  <option value="fiba_full">Full court</option>
                  <option value="fiba_half">Half court</option>
                  <option value="custom">Custom</option>
                </select>
              </label>
              <label>
                Length (m)
                <input
                  type="number"
                  min="0.1"
                  step="0.1"
                  value={length}
                  disabled={courtKind !== "custom"}
                  onChange={(event) => setLength(Number(event.target.value))}
                />
              </label>
              <label>
                Width (m)
                <input
                  type="number"
                  min="0.1"
                  step="0.1"
                  value={width}
                  disabled={courtKind !== "custom"}
                  onChange={(event) => setWidth(Number(event.target.value))}
                />
              </label>
              <button
                type="button"
                className="primary"
                disabled={!selected}
                onClick={() => void captureFrame()}
              >
                Capture frame
              </button>
            </div>
            <div className="axis-note">
              <b>Axes:</b> origin is the near-left corner. +X runs along court
              length; +Y runs across court width. Use measured metres for a
              custom floor. {courtKind === "fiba_half" && "Half court runs from basket baseline x=0 to midcourt x=14 m."}
            </div>
            {frame ? (
              <>
                <div className="calibration-workspace">
                  <div className="work-panel">
                    <div className="panel-title">
                      <div>
                        <span className="eyebrow">01 / CAMERA IMAGE</span>
                        <h3>Click a floor landmark</h3>
                      </div>
                      <span>
                        {frame.width} × {frame.height}px
                      </span>
                    </div>
                    <div
                      className="image-stage"
                      style={{
                        aspectRatio: `${frame.width} / ${frame.height}`,
                      }}
                    >
                      <button
                        type="button"
                        className="frame-capture"
                        aria-label="Choose floor point in camera image"
                        onClick={markImage}
                      >
                        <img
                          src={frame.url}
                          alt="Unannotated calibration frame"
                        />
                      </button>
                      <svg
                        viewBox={`0 0 ${frame.width} ${frame.height}`}
                        preserveAspectRatio="none"
                        aria-hidden="true"
                      >
                        {fit?.projected_court_lines.map((line) => (
                          <polyline
                            key={`${line[0]?.join("-")}-${line.at(-1)?.join("-")}`}
                            points={line.map((p) => p.join(",")).join(" ")}
                          />
                        ))}
                        {pendingImage && (
                          <circle
                            className="pending-point"
                            cx={pendingImage[0]}
                            cy={pendingImage[1]}
                            r={Math.max(frame.width / 130, 7)}
                          />
                        )}
                      </svg>
                      {points.map((point, index) => (
                        <button
                          key={point.id}
                          type="button"
                          aria-label={`Calibration point ${index + 1}`}
                          className={`frame-point ${hoverPoint === index ? "highlight" : ""}`}
                          style={{
                            left: `${(point.image_px[0] / frame.width) * 100}%`,
                            top: `${(point.image_px[1] / frame.height) * 100}%`,
                          }}
                          onMouseEnter={() => setHoverPoint(index)}
                          onMouseLeave={() => setHoverPoint(null)}
                          onFocus={() => setHoverPoint(index)}
                          onBlur={() => setHoverPoint(null)}
                        >
                          {index + 1}
                        </button>
                      ))}
                    </div>
                    <small className="helper">
                      Use floor intersections, not moving players. Spread points
                      across the visible area.
                    </small>
                  </div>
                  <div className="work-panel">
                    <div className="panel-title">
                      <div>
                        <span className="eyebrow">02 / COURT MODEL</span>
                        <h3>Pair with a court point</h3>
                      </div>
                      <span>
                        {length} × {width} m
                      </span>
                    </div>
                    <div className="court-map-shell">
                      <svg
                        className="court-map"
                        viewBox="0 0 280 150"
                        role="img"
                        aria-label="Basketball court diagram"
                      >
                        <rect
                          x="1"
                          y="1"
                          width="278"
                          height="148"
                          rx="3"
                          className="court-fill"
                        />
                        {geometry?.lines.map((line, index) => (
                          <path
                            // biome-ignore lint/suspicious/noArrayIndexKey: fixed list from the server
                            key={index}
                            d={line
                              .map(
                                ([x, y], i) =>
                                  `${i === 0 ? "M" : "L"}${((x / length) * 280).toFixed(2)} ${((y / width) * 150).toFixed(2)}`,
                              )
                              .join(" ")}
                            className="court-lines"
                            fill="none"
                          />
                        ))}
                        {Object.entries(landmarks).map(([name, xy]) => {
                          return (
                            <g
                              key={name}
                              className={`landmark ${courtKind === "fiba_half" && halfAnchors.has(name) ? "recommended" : ""}`}
                            >
                              <circle
                                cx={(xy[0] / length) * 280}
                                cy={(xy[1] / width) * 150}
                                r="3.2"
                              />
                              <title>
                                {name.replaceAll("_", " ")} ({xy[0].toFixed(2)},{" "}
                                {xy[1].toFixed(2)}) m
                              </title>
                            </g>
                          );
                        })}
                        {points.map((point, index) => (
                          <g key={point.id}>
                            <circle
                              className={`court-point ${hoverPoint === index ? "highlight" : ""}`}
                              cx={(point.court_m[0] / length) * 280}
                              cy={(point.court_m[1] / width) * 150}
                              r="4"
                            />
                            <text
                              x={(point.court_m[0] / length) * 280 + 5}
                              y={(point.court_m[1] / width) * 150 - 4}
                            >
                              {index + 1}
                            </text>
                          </g>
                        ))}
                      </svg>
                      <button
                        type="button"
                        className="court-coordinate-hit"
                        aria-label="Add a custom measured court point"
                        onClick={(event) => {
                          const rect =
                            event.currentTarget.getBoundingClientRect();
                          addPoint(
                            ((event.clientX - rect.left) / rect.width) * length,
                            ((event.clientY - rect.top) / rect.height) * width,
                          );
                        }}
                      />
                      {Object.entries(landmarks).map(([name, xy]) => {
                        return (
                          <button
                            key={name}
                            type="button"
                            className="court-landmark-hit"
                            style={{
                              left: `${(xy[0] / length) * 100}%`,
                              top: `${(xy[1] / width) * 100}%`,
                            }}
                            aria-label={`Snap to ${name.replaceAll("_", " ")}`}
                            title={name.replaceAll("_", " ")}
                            onClick={() => addPoint(...xy)}
                          />
                        );
                      })}
                      {points.map((point, index) => (
                        <button
                          key={point.id}
                          type="button"
                          className={`court-point-hit ${hoverPoint === index ? "highlight" : ""}`}
                          style={{
                            left: `${(point.court_m[0] / length) * 100}%`,
                            top: `${(point.court_m[1] / width) * 100}%`,
                          }}
                          aria-label={`Court point ${index + 1}`}
                          onMouseEnter={() => setHoverPoint(index)}
                          onMouseLeave={() => setHoverPoint(null)}
                          onFocus={() => setHoverPoint(index)}
                          onBlur={() => setHoverPoint(null)}
                        >
                          {index + 1}
                        </button>
                      ))}
                    </div>
                    <div className="court-axis">
                      <span>0 m · origin</span>
                      <span>+X {length} m</span>
                      <span>+Y {width} m</span>
                    </div>
                    {pendingImage && (
                      <div className="manual-point">
                        <span>
                          Selected image point: {pendingImage[0]},{" "}
                          {pendingImage[1]} px
                        </span>
                        <label>
                          X{" "}
                          <input
                            aria-label="Court X metres"
                            type="number"
                            step="0.01"
                            value={customX}
                            onChange={(e) => setCustomX(Number(e.target.value))}
                          />
                        </label>
                        <label>
                          Y{" "}
                          <input
                            aria-label="Court Y metres"
                            type="number"
                            step="0.01"
                            value={customY}
                            onChange={(e) => setCustomY(Number(e.target.value))}
                          />
                        </label>
                        <button
                          type="button"
                          onClick={() => addPoint(customX, customY)}
                        >
                          Use coordinates
                        </button>
                      </div>
                    )}
                    <small className="helper">
                      Click the diagram to place the point at a custom
                      coordinate. Click a named landmark to snap.
                    </small>
                      {courtKind === "fiba_half" && (
                        <small className="helper half-court-guide">
                          Best visible anchors: baseline corners and midcourt
                          line corners. Use separate lane or measured floor
                          marks as held-out checks.
                        </small>
                      )}
                  </div>
                </div>
                {fitAreaCoverage !== null && fitAreaCoverage < 0.2 && (
                  <p className="half-court-warning" role="alert">
                    Fit points cover {(fitAreaCoverage * 100).toFixed(0)}% of
                    the 210 m² half-court area; at least 20% is required. fit
                    points too close together, add the baseline corners or
                    midcourt line points or measured floor marks.
                  </p>
                )}
                <div className="point-tools">
                  <div>
                    <b>{points.length} points</b>
                    <span>
                      {" "}
                      · {points.filter((p) => p.role === "calibration").length}{" "}
                      fit · {points.filter((p) => p.role === "check").length}{" "}
                      held out
                    </span>
                  </div>
                  <div>
                    <button
                      type="button"
                      disabled={!undoPoint}
                      onClick={() => {
                        if (undoPoint) {
                          setPoints((old) => [...old, undoPoint]);
                          setUndoPoint(null);
                          setFit(null);
                        }
                      }}
                    >
                      Undo delete
                    </button>
                    <button
                      type="button"
                      disabled={!pendingImage}
                      onClick={() => setPendingImage(null)}
                    >
                      Cancel point
                    </button>
                  </div>
                </div>
                <div className="point-table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Image px</th>
                        <th>Court m</th>
                        <th>Role</th>
                        <th>Residual</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {points.map((point, index) => (
                        <tr key={point.id}>
                          <td>{index + 1}</td>
                          <td>{point.image_px.join(", ")}</td>
                          <td>{point.court_m.join(", ")}</td>
                          <td>
                            <button
                              type="button"
                              className="role-pill"
                              onClick={() => {
                                setPoints((old) =>
                                  old.map((p, i) =>
                                    i === index
                                      ? {
                                          ...p,
                                          role:
                                            p.role === "calibration"
                                              ? "check"
                                              : "calibration",
                                        }
                                      : p,
                                  ),
                                );
                                setFit(null);
                              }}
                            >
                              {point.role}
                            </button>
                          </td>
                          <td>
                            {fit
                              ? `${fit.point_errors_m[index]?.toFixed(3) ?? "—"} m`
                              : "—"}
                          </td>
                          <td>
                            <button
                              type="button"
                              className="danger-text"
                              onClick={() => {
                                setUndoPoint(point);
                                setPoints((old) =>
                                  old.filter((_, i) => i !== index),
                                );
                                setFit(null);
                              }}
                            >
                              Delete
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {points.length === 0 && (
                    <p className="empty">
                      Select a point in the image, then pair it on the court
                      diagram.
                    </p>
                  )}
                </div>
                <div className="fit-footer">
                  <label>
                    Maximum mean check error (m)
                    <input
                      type="number"
                      min="0.01"
                      max="2"
                      step="0.05"
                      value={maxError}
                      onChange={(event) => {
                        setMaxError(Number(event.target.value));
                        setFit(null);
                      }}
                    />
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={saveAnyway}
                      onChange={(event) => setSaveAnyway(event.target.checked)}
                    />{" "}
                    Save anyway if check error exceeds limit
                  </label>
                  <button
                    type="button"
                    onClick={() => void runFit()}
                    disabled={
                      points.filter((p) => p.role === "calibration").length < 4
                    }
                  >
                    Fit and inspect
                  </button>
                  <button
                    type="button"
                    className="primary"
                    onClick={() => void runFit(true)}
                    disabled={
                      points.filter((p) => p.role === "calibration").length <
                        4 ||
                      points.filter((p) => p.role === "check").length < 2 ||
                      (!!fit &&
                        fit.check_mean_m !== null &&
                        fit.check_mean_m > maxError &&
                        !saveAnyway)
                    }
                  >
                    Save calibration
                  </button>
                </div>
                {refused && refused.camera === selected && (
                  <div className="refusal" role="alert">
                    <b>Calibration refused</b>
                    <span>{refused.message}</span>
                    {refused.refusal.kind === "too_few_points" && (
                      <span>
                        {refused.refusal.have} of {refused.refusal.need}{" "}
                        {refused.refusal.role} points placed; place{" "}
                        {refused.refusal.need - refused.refusal.have} more.
                      </span>
                    )}
                    {refused.refusal.kind === "check_error_over_limit" && (
                      <>
                        {refused.refusal.check_point_indices.map(
                          (index, position) => (
                            <span key={index}>
                              Check point {index + 1}:{" "}
                              {(
                                refused.refusal as Extract<
                                  Refusal,
                                  { kind: "check_error_over_limit" }
                                >
                              ).check_errors_m[position].toFixed(3)}{" "}
                              m
                            </span>
                          ),
                        )}
                        <span>
                          Mean {refused.refusal.check_mean_m.toFixed(3)} m, limit{" "}
                          {refused.refusal.max_check_error_m.toFixed(3)} m
                        </span>
                      </>
                    )}
                    <div className="refusal-actions">
                      <button type="button" onClick={() => setRefused(null)}>
                        Retry (keep placed points)
                      </button>
                      <button type="button" onClick={() => void startUncalibrated()}>
                        Start this camera uncalibrated
                      </button>
                    </div>
                  </div>
                )}
                {skippedReason && (
                  <div className="refusal" role="status">
                    <b>Camera {selected} will start uncalibrated</b>
                    <span>
                      Recorded as a failed calibration check: {skippedReason}
                    </span>
                    <div className="refusal-actions">
                      <button type="button" onClick={() => void undoUncalibrated()}>
                        Calibrate it instead
                      </button>
                    </div>
                  </div>
                )}
                {fit && (
                  <div
                    className={
                      fit.check_mean_m !== null && fit.check_mean_m > maxError
                        ? "fit-summary warn"
                        : "fit-summary"
                    }
                  >
                    <b>
                      {fit.check_mean_m !== null && fit.check_mean_m > maxError
                        ? "Check error exceeds limit"
                        : "Fit ready to save"}
                    </b>
                    <span>Fit mean {fit.calibration_mean_m.toFixed(3)} m</span>
                    <span>
                      Held-out mean{" "}
                      {fit.check_mean_m === null
                        ? "add check points"
                        : `${fit.check_mean_m.toFixed(3)} m`}
                    </span>
                    <span>
                      Held-out max{" "}
                      {fit.check_max_m === null
                        ? "not measured"
                        : `${fit.check_max_m.toFixed(3)} m`}
                    </span>
                    {fit.ransac_dropped_points.length > 0 && (
                      <span role="alert">
                        Left out of the fit as outliers (further than{" "}
                        {fit.ransac_threshold_m} m from it): point{" "}
                        {fit.ransac_dropped_points
                          .map((index) => index + 1)
                          .join(", ")}
                        . Check their image or court position.
                      </span>
                    )}
                  </div>
                )}
              </>
            ) : (
              <div className="empty-state">
                <span>STEP 01</span>
                <b>Capture a camera frame to begin</b>
                <p>
                  For a recording camera, Studio uses its existing capture
                  stream. It will not open a second phone viewer.
                </p>
              </div>
            )}
            {selected && (
              <div className="compare-panel">
                <div>
                  <b>Did the phone move?</b>
                  <p>
                    Compare the saved calibration image with a new frame. This
                    visual difference is a warning signal, not a recalibration.
                  </p>
                </div>
                <button type="button" onClick={() => void compare()}>
                  Compare with fresh frame
                </button>
                {comparison && (
                  <div className="compare-images">
                    <figure>
                      <img
                        src={`data:image/jpeg;base64,${comparison.audit_frame}`}
                        alt="Saved calibration audit frame"
                      />
                      <figcaption>Saved calibration</figcaption>
                    </figure>
                    <figure>
                      <img
                        src={`data:image/jpeg;base64,${comparison.fresh_frame}`}
                        alt="Current camera frame"
                      />
                      <figcaption>
                        Current frame · difference{" "}
                        {comparison.difference_score?.toFixed(3) ??
                          "unavailable"}{" "}
                        {comparison.warning
                          ? "· check camera position"
                          : "· no large change"}
                      </figcaption>
                    </figure>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {page === "Sessions" && (
          <section className="page-content">
            <div className="section-heading">
              <div>
                <div className="eyebrow">LOCAL HISTORY</div>
                <h2>Recorded sessions</h2>
                <p>Reports are built from each camera's local session files.</p>
              </div>
              <button type="button" onClick={() => void loadSessions()}>
                Refresh list
              </button>
            </div>
            {sessions.length === 0 ? (
              <div className="empty-state">
                <span>NO SESSIONS</span>
                <b>Nothing recorded yet</b>
                <p>
                  Completed recordings will appear here with when they were
                  recorded, duration, frame rate, drops and events.
                </p>
              </div>
            ) : (
              <div className="session-list">
                {sessions.map((session) => (
                  <article key={session.folder}>
                    <div className="session-head">
                      <b>{session.camera_id || "Camera"}</b>
                      <span>{session.status ?? "status unknown"}</span>
                    </div>
                    <small>
                      {session.started_at
                        ? new Date(session.started_at).toLocaleString()
                        : "Time unknown"}
                      {" · "}
                      {session.folder}
                    </small>
                    <dl className="session-facts">
                      <div>
                        <dt>Cameras</dt>
                        <dd>
                          {session.group_id
                            ? sessions
                                .filter((s) => s.group_id === session.group_id)
                                .map((s) => s.camera_id || "Camera")
                                .join(", ")
                            : session.camera_id || "Camera"}
                        </dd>
                      </div>
                      <div>
                        <dt>Duration</dt>
                        <dd>{formatDuration(session.duration)}</dd>
                      </div>
                      <div>
                        <dt>Frame rate</dt>
                        <dd>
                          {session.fps === null
                            ? "unknown"
                            : `${session.fps.toFixed(1)} fps`}
                        </dd>
                      </div>
                      <div>
                        <dt>Dropped</dt>
                        <dd>
                          {session.dropped === null
                            ? "unknown"
                            : `${session.dropped} of ${session.captured}${
                                session.drop_rate === null
                                  ? ""
                                  : ` (${session.drop_rate.toFixed(0)}%)`
                              }`}
                        </dd>
                      </div>
                      <div>
                        <dt>Events</dt>
                        <dd>{formatEvents(session.events)}</dd>
                      </div>
                    </dl>
                    {session.missing.length > 0 && (
                      <p className="session-missing">
                        Not available: {session.missing.join("; ")}
                      </p>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}
