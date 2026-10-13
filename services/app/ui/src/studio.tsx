import { useCallback, useEffect, useState } from "react";

type Camera = {
  camera_id: string;
  source: string;
  link: string;
  det_size?: number;
  track_lost_secs?: number;
  track_activation?: number;
  track_min_frames?: number;
};
type TestResult = { snapshot?: string; resolution?: number[]; fps?: number | null; error?: string };
type CameraStatus = {
  camera_id: string;
  state: string;
  processed_fps: number | null;
  people: number;
  tracks: number;
  drops: number;
  preview_drops: number;
  health: string;
  last_event: unknown;
  session_folder: string | null;
  preview_port: number | null;
};
type Status = { running: boolean; cameras: CameraStatus[] };
type Session = { camera_id: string; group_id: string; status: string; folder: string; summary: string | null };

async function request<T>(url: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

export default function StudioApp() {
  const [page, setPage] = useState("Record");
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [status, setStatus] = useState<Status>({ running: false, cameras: [] });
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState("");
  const [tested, setTested] = useState<Record<string, TestResult>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<Camera>({ camera_id: "cam1", source: "0", link: "builtin" });

  const refresh = useCallback(async () => {
    try {
      setCameras(await request<Camera[]>("/api/cameras"));
      setStatus(await request<Status>("/api/status"));
      setError("");
    } catch (reason) {
      setError(String(reason));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 1000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function action(url: string, method = "POST", body?: unknown) {
    try {
      await request(url, method, body);
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
    await action(editing ? `/api/cameras/${editing}` : "/api/cameras", editing ? "PUT" : "POST", form);
    setEditing(null);
    setForm({ camera_id: "cam1", source: "0", link: "builtin" });
  }

  return (
    <main>
      <header>
        <h1>Pointr Studio</h1>
        <nav>
          {["Cameras", "Record", "Sessions", "Calibration"].map((item) => (
            <button type="button" key={item} onClick={() => {
              setPage(item);
              if (item === "Sessions") void loadSessions();
            }}>{item}</button>
          ))}
        </nav>
      </header>
      {error && <p className="error">{error}</p>}
      {page === "Cameras" && (
        <section>
          <h2>Cameras</h2>
          <form onSubmit={(event) => void submitCamera(event)}>
            <input aria-label="Camera ID" value={form.camera_id} onChange={(event) => setForm({ ...form, camera_id: event.target.value })} />
            <input aria-label="Source" value={form.source} onChange={(event) => setForm({ ...form, source: event.target.value })} />
            <select aria-label="Link" value={form.link} onChange={(event) => setForm({ ...form, link: event.target.value })}>
              <option>builtin</option><option>usb</option><option>wifi</option><option>file</option>
            </select>
            <input aria-label="Detection size" type="number" min="32" step="32" placeholder="Detection size" value={form.det_size ?? ""} onChange={(event) => setForm({ ...form, det_size: event.target.value ? Number(event.target.value) : undefined })} />
            <input aria-label="Lost track seconds" type="number" min="0.01" step="0.1" placeholder="Lost track seconds" value={form.track_lost_secs ?? ""} onChange={(event) => setForm({ ...form, track_lost_secs: event.target.value ? Number(event.target.value) : undefined })} />
            <input aria-label="Track activation" type="number" min="0.01" max="1" step="0.01" placeholder="Track activation" value={form.track_activation ?? ""} onChange={(event) => setForm({ ...form, track_activation: event.target.value ? Number(event.target.value) : undefined })} />
            <input aria-label="Track minimum frames" type="number" min="1" step="1" placeholder="Track minimum frames" value={form.track_min_frames ?? ""} onChange={(event) => setForm({ ...form, track_min_frames: event.target.value ? Number(event.target.value) : undefined })} />
            <button type="submit">{editing ? "Save camera" : "Add camera"}</button>
          </form>
          {cameras.map((camera) => (
            <article key={camera.camera_id}>
              <b>{camera.camera_id}</b> {camera.source}
              <button type="button" onClick={async () => {
                try {
                  const result = await request<TestResult>(`/api/cameras/${camera.camera_id}/test`, "POST");
                  setTested({ ...tested, [camera.camera_id]: result });
                } catch (reason) {
                  setTested({ ...tested, [camera.camera_id]: { error: String(reason) } });
                }
              }}>Test</button>
              <button type="button" onClick={() => { setEditing(camera.camera_id); setForm(camera); }}>Edit</button>
              <button type="button" onClick={() => void action(`/api/cameras/${camera.camera_id}`, "DELETE")}>Remove</button>
              {tested[camera.camera_id] && (tested[camera.camera_id].snapshot
                ? <img alt={`${camera.camera_id} camera test`} src={`data:image/jpeg;base64,${tested[camera.camera_id].snapshot}`} />
                : <p className="error">{tested[camera.camera_id].error}</p>)}
            </article>
          ))}
        </section>
      )}
      {page === "Record" && (
        <section>
          <h2>Record group</h2>
          <button type="button" disabled={status.running} onClick={() => void action("/api/recording/start")}>Start</button>
          <button type="button" disabled={!status.running} onClick={() => void action("/api/recording/stop")}>Stop</button>
          <p>{status.running ? "Recording continues in the backend; closing this tab will not stop it." : "Not recording"}</p>
          <div className="grid">
            {status.cameras.map((camera) => (
              <article key={camera.camera_id}>
                <h3>{camera.camera_id} · {camera.state}</h3>
                {camera.preview_port && <img alt={`${camera.camera_id} live preview`} src={`/api/cameras/${camera.camera_id}/preview/mjpeg`} />}
                <p>fps {camera.processed_fps?.toFixed(2) ?? "—"} · people {camera.people} · tracks {camera.tracks} · drops {camera.drops} · preview drops {camera.preview_drops}</p>
                <p className={`health ${camera.health}`}>{camera.health} · {JSON.stringify(camera.last_event ?? "No events")}</p>
                <small>{camera.session_folder ?? "Waiting for session"}</small>
                {!status.running && ["interrupted", "ended"].includes(camera.state) && <strong>Stopped cleanly</strong>}
                {!status.running && camera.state === "error" && <strong className="error">Error</strong>}
              </article>
            ))}
          </div>
        </section>
      )}
      {page === "Sessions" && (
        <section><h2>Sessions</h2><button type="button" onClick={() => void loadSessions()}>Refresh</button>
          {sessions.map((session) => <article key={session.folder}><b>{session.camera_id}</b> · {session.group_id} · {session.status} · {session.folder}<p>{session.summary ?? "No report summary"}</p></article>)}
        </section>
      )}
      {page === "Calibration" && <section><h2>Calibration</h2><p>Coming in part 5b.</p></section>}
    </main>
  );
}
