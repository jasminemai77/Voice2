"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const API = process.env.NEXT_PUBLIC_VOICE2_API ?? "http://127.0.0.1:8765";

type Gpu = { name: string; total_vram_mib: number; free_vram_mib: number; safe_budget_mib: number };
type Hardware = {
  cpu: string; physical_cores: number; logical_cores: number;
  total_ram_mib: number; available_ram_mib: number; cuda_available: boolean; gpus: Gpu[];
};
type Provider = {
  id: string; name: string; license: string; available: boolean; availability_reason?: string;
  languages: string[]; variants: { id: string; device: string; precision: string }[];
};
type Voice = { id: string; name: string; language: string; duration_seconds?: number };
type Status = {
  profile: string; provider_id: string;
  variant: { id: string; device: string; precision: string };
  selection_reason: string; realtime_expected: boolean;
  queue: { active: number; waiting: number; queue_limit: number };
  last_metrics: { ttfa_ms?: number; rtf?: number };
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: response.statusText }));
    throw new Error(error.message ?? error.detail?.message ?? "请求失败");
  }
  return response.json() as Promise<T>;
}

function mib(value?: number) {
  if (value === undefined) return "—";
  return value >= 1024 ? `${(value / 1024).toFixed(1)} GB` : `${value} MB`;
}

export default function Home() {
  const [hardware, setHardware] = useState<Hardware>();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [status, setStatus] = useState<Status>();
  const [profile, setProfile] = useState("auto");
  const [text, setText] = useState("你好，我是 Voice2。这段语音完全在本机生成。Hello from your local voice runtime.");
  const [voiceId, setVoiceId] = useState("");
  const [format, setFormat] = useState("wav");
  const [audioUrl, setAudioUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("正在连接本地运行时…");
  const [voiceForm, setVoiceForm] = useState({ name: "", transcript: "", language: "auto", consent: false });
  const [file, setFile] = useState<File>();

  const refresh = useCallback(async () => {
    try {
      const [nextHardware, nextProviders, nextVoices, nextStatus] = await Promise.all([
        api<Hardware>("/api/v1/runtime/hardware"), api<Provider[]>("/api/v1/providers"),
        api<Voice[]>("/api/v1/voices"), api<Status>("/api/v1/runtime/status"),
      ]);
      setHardware(nextHardware); setProviders(nextProviders); setVoices(nextVoices); setStatus(nextStatus);
      setProfile(nextStatus.profile);
      setNotice("本地运行时已连接，参考音频不会离开此设备。");
    } catch {
      setNotice(`无法连接 ${API}，请先运行后端：voice2`);
    }
  }, []);

  useEffect(() => {
    const task = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(task);
  }, [refresh]);
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl); }, [audioUrl]);
  const activeProvider = useMemo(() => providers.find((item) => item.id === status?.provider_id), [providers, status]);

  async function switchProfile(value: string) {
    setBusy("profile");
    try {
      const custom = value === "custom" && status
        ? { provider_id: status.provider_id, variant_id: status.variant.id }
        : {};
      await api("/api/v1/runtime/profile", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ profile: value, custom }) });
      setProfile(value); await refresh();
    } catch (error) { setNotice((error as Error).message); } finally { setBusy(""); }
  }

  async function synthesize() {
    setBusy("speech"); setNotice("正在本机生成，首次加载真实模型可能需要更长时间…");
    try {
      const response = await fetch(`${API}/api/v1/speech`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ text, voice_id: voiceId || null, response_format: format, profile }),
      });
      if (!response.ok) { const error = await response.json(); throw new Error(error.message ?? "生成失败"); }
      const blob = await response.blob(); if (audioUrl) URL.revokeObjectURL(audioUrl);
      setAudioUrl(URL.createObjectURL(blob));
      setNotice(`生成完成 · ${response.headers.get("X-Voice2-Provider") ?? status?.provider_id}`);
      await refresh();
    } catch (error) { setNotice((error as Error).message); } finally { setBusy(""); }
  }

  async function registerVoice(event: FormEvent) {
    event.preventDefault();
    if (!file) { setNotice("请选择 5–30 秒参考音频。"); return; }
    setBusy("voice");
    const form = new FormData();
    form.set("name", voiceForm.name); form.set("language", voiceForm.language);
    form.set("transcript", voiceForm.transcript); form.set("consent_confirmed", String(voiceForm.consent));
    form.set("audio", file);
    try {
      const created = await api<Voice>("/api/v1/voices", { method: "POST", body: form });
      setVoiceId(created.id); setVoiceForm({ name: "", transcript: "", language: "auto", consent: false }); setFile(undefined);
      setNotice(`音色“${created.name}”已仅保存在本机。`); await refresh();
    } catch (error) { setNotice((error as Error).message); } finally { setBusy(""); }
  }

  async function benchmark() {
    setBusy("benchmark"); setNotice("正在执行不超过 60 秒的本地短基准…");
    try {
      const result = await api<{ metrics: { ttfa_ms: number; rtf: number }; provider_id: string }>("/api/v1/runtime/benchmark", { method: "POST" });
      setNotice(`基准完成 · ${result.provider_id} · TTFA ${result.metrics.ttfa_ms} ms · RTF ${result.metrics.rtf}`); await refresh();
    } catch (error) { setNotice((error as Error).message); } finally { setBusy(""); }
  }

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Voice2 首页"><span>V2</span>Voice2</a>
        <div className="runtime-pill"><i className={hardware ? "online" : ""} />{hardware ? "LOCAL ONLINE" : "LOCAL OFFLINE"}</div>
      </header>

      <section className="hero" id="top">
        <div><p className="eyebrow">HARDWARE-ADAPTIVE VOICE RUNTIME</p><h1>你的声音，<br /><em>只在本地。</em></h1><p className="lead">零样本音色克隆、流式生成与实时会话骨架。Voice2 根据 CPU、内存、GPU 和显存自动选择稳定且尽可能实时的配置。</p></div>
        <div className="trust-card"><strong>隐私边界</strong><p>不会自动上传参考音频，不会自动切换第三方 TTS。资源不足时只执行明确的本地降级。</p><span>LOCAL-FIRST / CONSENT REQUIRED</span></div>
      </section>

      <div className="notice" role="status"><span>●</span>{notice}</div>

      <section className="dashboard">
        <article className="panel composer">
          <div className="panel-title"><div><small>01 / GENERATE</small><h2>语音生成</h2></div><b>{text.length}/5000</b></div>
          <textarea value={text} maxLength={5000} onChange={(event) => setText(event.target.value)} aria-label="待生成文本" />
          <div className="controls">
            <label>音色<select value={voiceId} onChange={(event) => setVoiceId(event.target.value)}><option value="">开发测试信号</option>{voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name}</option>)}</select></label>
            <label>格式<select value={format} onChange={(event) => setFormat(event.target.value)}><option>wav</option><option>mp3</option><option>pcm</option></select></label>
            <button className="primary" disabled={!text.trim() || !!busy} onClick={synthesize}>{busy === "speech" ? "生成中…" : "生成语音 →"}</button>
          </div>
          {audioUrl && <div className="player"><audio controls autoPlay src={audioUrl} /><a href={audioUrl} download={`voice2.${format}`}>下载 {format.toUpperCase()}</a></div>}
        </article>

        <aside className="panel telemetry">
          <div className="panel-title"><div><small>02 / RUNTIME</small><h2>性能面板</h2></div></div>
          <div className="profile-tabs">{["auto", "fast", "quality", "custom"].map((item) => <button key={item} className={profile === item ? "active" : ""} disabled={!!busy} onClick={() => switchProfile(item)}>{item}</button>)}</div>
          <dl><div><dt>Provider</dt><dd>{activeProvider?.name ?? status?.provider_id ?? "—"}</dd></div><div><dt>Variant</dt><dd>{status?.variant.id ?? "—"}</dd></div><div><dt>Device / Precision</dt><dd>{status ? `${status.variant.device} / ${status.variant.precision}` : "—"}</dd></div><div><dt>TTFA</dt><dd>{status?.last_metrics.ttfa_ms ? `${status.last_metrics.ttfa_ms} ms` : "—"}</dd></div><div><dt>RTF</dt><dd>{status?.last_metrics.rtf ?? "—"}</dd></div><div><dt>Queue</dt><dd>{status ? `${status.queue.active} active · ${status.queue.waiting} wait` : "—"}</dd></div></dl>
          <button className="secondary" disabled={!!busy} onClick={benchmark}>{busy === "benchmark" ? "基准运行中…" : "重新运行短基准"}</button>
          {status && <p className="reason">{status.selection_reason}</p>}
        </aside>
      </section>

      <section className="lower-grid">
        <form className="panel voice-form" onSubmit={registerVoice}>
          <div className="panel-title"><div><small>03 / VOICE</small><h2>注册本地音色</h2></div></div>
          <div className="form-grid">
            <label>名称<input required value={voiceForm.name} onChange={(event) => setVoiceForm({ ...voiceForm, name: event.target.value })} placeholder="例如：我的中文音色" /></label>
            <label>语言<select value={voiceForm.language} onChange={(event) => setVoiceForm({ ...voiceForm, language: event.target.value })}><option value="auto">自动 / 中英混合</option><option value="zh">中文</option><option value="en">English</option></select></label>
            <label className="wide">准确参考文本<textarea required value={voiceForm.transcript} onChange={(event) => setVoiceForm({ ...voiceForm, transcript: event.target.value })} placeholder="逐字填写音频中的内容" /></label>
            <label className="upload wide">5–30 秒 WAV / MP3 / FLAC<input required type="file" accept="audio/wav,audio/mpeg,audio/flac" onChange={(event: ChangeEvent<HTMLInputElement>) => setFile(event.target.files?.[0])} /><span>{file?.name ?? "选择本地音频"}</span></label>
            <label className="consent wide"><input type="checkbox" checked={voiceForm.consent} onChange={(event) => setVoiceForm({ ...voiceForm, consent: event.target.checked })} />我确认拥有该声音的使用授权，并理解克隆风险。</label>
          </div>
          <button className="primary" disabled={!voiceForm.consent || !!busy}>{busy === "voice" ? "保存中…" : "保存到本机"}</button>
        </form>

        <article className="panel hardware">
          <div className="panel-title"><div><small>04 / HARDWARE</small><h2>设备画像</h2></div></div>
          <dl><div><dt>CPU</dt><dd>{hardware?.cpu ?? "等待检测"}</dd></div><div><dt>Cores</dt><dd>{hardware ? `${hardware.physical_cores}P / ${hardware.logical_cores}T` : "—"}</dd></div><div><dt>RAM</dt><dd>{hardware ? `${mib(hardware.available_ram_mib)} free / ${mib(hardware.total_ram_mib)}` : "—"}</dd></div><div><dt>GPU</dt><dd>{hardware?.gpus[0]?.name ?? "CPU fallback"}</dd></div><div><dt>VRAM safe budget</dt><dd>{mib(hardware?.gpus[0]?.safe_budget_mib)}</dd></div><div><dt>CUDA</dt><dd>{hardware?.cuda_available ? "Available" : "Unavailable"}</dd></div></dl>
        </article>
      </section>

      <section className="providers panel">
        <div className="panel-title"><div><small>05 / PROVIDERS</small><h2>可插拔内核</h2></div><b>{providers.filter((item) => item.available).length}/{providers.length} READY</b></div>
        <div className="provider-list">{providers.map((provider) => <div key={provider.id} className={provider.available ? "ready" : "disabled"}><span>{provider.available ? "READY" : "OFF"}</span><strong>{provider.name}</strong><p>{provider.languages.join(" · ")} · {provider.license}</p><small>{provider.availability_reason ?? provider.variants.map((item) => item.id).join(", ")}</small></div>)}</div>
      </section>

      <footer><span>VOICE2 / APACHE-2.0</span><p>真实音色克隆需显式安装并启用 VoxCPM Provider；默认测试信号不冒充语音。</p></footer>
    </main>
  );
}
