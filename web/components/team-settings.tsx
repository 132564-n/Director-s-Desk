"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, getModelSettings, testModelConnection, updateModelSettings } from "@/lib/api";
import type { AgentModelSettings, AgentWorkProfile, ModelSettings, ProviderSettings } from "@/lib/types";

const PROFILE_OPTIONS: Array<{
  value: AgentWorkProfile;
  label: string;
  description: string;
}> = [
  { value: "creative", label: "创意探索", description: "更开放，强调画面与新鲜方案" },
  { value: "rigorous", label: "严谨审校", description: "低随机，优先查冲突与约束" },
  { value: "decision", label: "决策收束", description: "聚焦取舍，给出唯一推荐动作" },
  { value: "performance", label: "表演听感", description: "关注情绪、节奏、声音与音乐" },
];

export function TeamSettings() {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [testModels, setTestModels] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setSettings(await getModelSettings()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "无法读取模型配置"); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  function updateProvider(index: number, patch: Partial<ProviderSettings>) {
    setSettings((current) => current ? {
      ...current,
      providers: current.providers.map((provider, position) => position === index ? { ...provider, ...patch } : provider),
    } : current);
  }

  function updateAssignment(index: number, patch: Partial<AgentModelSettings>) {
    setSettings((current) => current ? {
      ...current,
      assignments: current.assignments.map((assignment, position) => position === index ? { ...assignment, ...patch } : assignment),
    } : current);
  }

  function addProvider() {
    setSettings((current) => current ? {
      ...current,
      providers: [...current.providers, {
        id: `provider-${crypto.randomUUID().slice(0, 8)}`,
        label: "新模型供应商",
        kind: "openai_compatible",
        base_url: "https://api.example.com/v1",
        api_key_env: "",
      }],
    } : current);
  }

  async function save() {
    if (!settings) return;
    setBusy(true); setError(""); setMessage("");
    try {
      setSettings(await updateModelSettings(settings));
      setMessage("模型分配已保存");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "保存失败");
    } finally { setBusy(false); }
  }

  async function testProvider(provider: ProviderSettings) {
    const model = testModels[provider.id] || settings?.assignments.find(
      (item) => item.provider_id === provider.id,
    )?.model;
    if (!model?.trim()) { setError("请先输入测试模型名称"); return; }
    if (!settings) return;
    setTesting(provider.id); setBusy(true); setError(""); setMessage("");
    try {
      setSettings(await updateModelSettings(settings));
      const result = await testModelConnection(provider.id, model.trim());
      setMessage(`${provider.label}：${result.message}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接测试失败");
    } finally { setTesting(null); setBusy(false); }
  }

  if (!settings) return <section className="team-settings"><div className="loading-block">{error || "正在读取团队配置…"}</div></section>;

  return (
    <section className="team-settings">
      <header className="editor-heading"><div><p>MODEL CASTING</p><h1>团队 API 配置</h1><span>填写接口地址与 API Key，为九个角色选择模型。保存后对新一轮讨论生效，无需重启。</span></div><div className="asset-count"><b>{settings.providers.length}</b><small>个供应商</small></div></header>
      {error ? <div className="error-banner" role="alert">{error}</div> : null}
      {message ? <div className="success-banner" role="status">{message}</div> : null}
      <fieldset disabled={busy} style={{ border: 0, padding: 0, minWidth: 0 }}>

      <div className="settings-section-heading"><div><span>PROVIDERS</span><h2>模型供应商</h2></div><button className="text-action" onClick={addProvider}>＋ 添加兼容接口</button></div>
      <div className="provider-list">
        {settings.providers.map((provider, index) => (
          <article className="provider-card" key={`${provider.id}-${index}`}>
            <div className="provider-type"><span>{provider.kind === "demo" ? "DEMO" : "OPENAI COMPATIBLE"}</span>{provider.kind !== "demo" ? <button disabled={settings.assignments.some((item) => item.provider_id === provider.id)} title="请先将使用此供应商的 Agent 切换到其他模型" onClick={() => setSettings({ ...settings, providers: settings.providers.filter((_, position) => position !== index) })}>移除</button> : null}</div>
            <label><span>显示名称</span><input value={provider.label} onChange={(event) => updateProvider(index, { label: event.target.value })} /></label>
            {provider.kind !== "demo" ? <>
              <label><span>OpenAI 兼容接口地址（Base URL）</span><input type="url" autoComplete="off" spellCheck={false} value={provider.base_url} onChange={(event) => updateProvider(index, { base_url: event.target.value })} /><small>例如 https://api.example.com/v1。修改地址后需重新填写密钥。</small></label>
              <label><span>API Key <span className="key-status">{provider.api_key_set ? "已保存" : "未配置"}</span></span><input type="password" autoComplete="new-password" spellCheck={false} value={provider.api_key ?? ""} placeholder={provider.api_key_set ? "留空保留已保存的密钥…" : "输入供应商的 API Key…"} onChange={(event) => updateProvider(index, { api_key: event.target.value || undefined })} /><small>密钥在本机加密保存，保存成功后不回显。</small></label>
              {provider.api_key_set ? <button type="button" onClick={() => updateProvider(index, { api_key: "", api_key_set: false })}>清除已保存密钥（保存后生效）</button> : null}
              <details><summary>高级：使用环境变量</summary><label><span>环境变量名（可选）</span><input autoComplete="off" value={provider.api_key_env} onChange={(event) => updateProvider(index, { api_key_env: event.target.value })} /></label></details>
              <div className="connection-tools"><input aria-label={`${provider.label}测试模型`} placeholder="输入测试模型名称…" value={testModels[provider.id] ?? ""} onChange={(event) => setTestModels((current) => ({ ...current, [provider.id]: event.target.value }))} /><button type="button" onClick={() => void testProvider(provider)}>{testing === provider.id ? "测试中…" : "保存并测试连接"}</button></div>
              <small>测试只发送一条简短请求，可能产生少量调用费用。</small>
            </> : <p>内置演示团队，不联网、不消耗 Token；切换到兼容接口后才会调用真实模型。</p>}
          </article>
        ))}
      </div>

      <div className="settings-section-heading"><div><span>ASSIGNMENTS</span><h2>Agent 模型与工作方式</h2></div><small>工作方式会同时调整角色提示词与创作随机度</small></div>
      <div className="assignment-table">
        <div className="assignment-head"><span>角色</span><span>供应商</span><span>模型名称</span><span>工作方式</span></div>
        {settings.assignments.map((assignment, index) => (
          <div className="assignment-row" key={assignment.role}>
            <b>{assignment.role}</b>
            <select aria-label={`${assignment.role}供应商`} value={assignment.provider_id} onChange={(event) => updateAssignment(index, { provider_id: event.target.value })}>{settings.providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select>
            <input aria-label={`${assignment.role}模型`} autoComplete="off" spellCheck={false} value={assignment.model} onChange={(event) => updateAssignment(index, { model: event.target.value })} />
            <label className="profile-select">
              <select aria-label={`${assignment.role}工作方式`} value={assignment.profile} onChange={(event) => updateAssignment(index, { profile: event.target.value as AgentWorkProfile })}>
                {PROFILE_OPTIONS.map((profile) => <option key={profile.value} value={profile.value}>{profile.label}</option>)}
              </select>
              <small>{PROFILE_OPTIONS.find((profile) => profile.value === assignment.profile)?.description}</small>
            </label>
          </div>
        ))}
      </div>
      <div className="settings-save"><span>配置文件保存在本地 data 目录，不会进入导演执行包。</span><button className="primary-action" disabled={busy} onClick={() => void save()}>{busy ? "正在保存…" : "保存团队配置"}</button></div>
      </fieldset>
    </section>
  );
}
