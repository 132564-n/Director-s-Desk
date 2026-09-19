"use client";

import { FormEvent, useState } from "react";
import { API_URL } from "@/lib/api";
import type { Asset, AssetKind, AssetPolicy } from "@/lib/types";

const KIND_LABEL: Record<AssetKind, string> = { character: "角色", location: "场景", prop: "道具", style: "风格" };

export function AssetLibrary({
  assets,
  busy,
  onUpload,
  onConfirm,
}: {
  assets: Asset[];
  busy: boolean;
  onUpload: (input: { file: File; name: string; kind: AssetKind; policy: AssetPolicy }) => void;
  onConfirm: (assetId: string, input: { description: string; policy: AssetPolicy }) => void;
}) {
  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || !file.size) return;
    onUpload({ file, name: String(form.get("name")), kind: form.get("kind") as AssetKind, policy: form.get("policy") as AssetPolicy });
  }
  return (
    <section className="asset-library">
      <header className="editor-heading"><div><p>ASSET REGISTRY</p><h1>视觉资产库</h1><span>资产先上传、再确认。只有已确认的角色和场景才能进入分镜提示词。</span></div><div className="asset-count"><b>{assets.length}</b><small>项资产</small></div></header>
      <form className="upload-deck" onSubmit={upload}>
        <label className="file-drop"><input name="file" type="file" accept="image/png,image/jpeg,image/webp,image/gif" required /><span aria-hidden="true">＋</span><b>选择资产图片</b><small>JPG、PNG、WebP 或 GIF，不超过 10 MB</small></label>
        <div className="upload-fields"><label><span>资产名称</span><input name="name" required placeholder="例如：林雾定妆" /></label><div className="form-pair"><label><span>类型</span><select name="kind"><option value="character">角色</option><option value="location">场景</option><option value="prop">道具</option><option value="style">风格</option></select></label><label><span>初始规则</span><select name="policy"><option value="reference">参考资产</option><option value="locked">锁定资产</option></select></label></div><button className="primary-action" disabled={busy}>{busy ? "正在入库…" : "上传到资产库"}</button></div>
      </form>
      <div className="asset-grid">
        {assets.map((asset) => <AssetCard key={asset.id} asset={asset} busy={busy} onConfirm={onConfirm} />)}
      </div>
      {assets.length === 0 ? <div className="form-empty">资产库为空。可以先制作大纲，但分镜前建议补齐角色和场景参考。</div> : null}
    </section>
  );
}

function AssetCard({ asset, busy, onConfirm }: { asset: Asset; busy: boolean; onConfirm: (assetId: string, input: { description: string; policy: AssetPolicy }) => void }) {
  const [description, setDescription] = useState(asset.description);
  const [policy, setPolicy] = useState<AssetPolicy>(asset.policy);
  return (
    <article className="asset-card">
      <div className="asset-image">{asset.source_path ? <img src={`${API_URL}/media/${asset.source_path}`} alt={asset.name} /> : <span>{asset.name.slice(0, 1)}</span>}<i className={asset.confirmed ? "confirmed" : "pending"}>{asset.confirmed ? "已确认" : "待确认"}</i></div>
      <div className="asset-card-body"><div className="asset-meta"><span>{KIND_LABEL[asset.kind]}</span><small>{asset.policy === "locked" ? "锁定资产" : "参考资产"}</small></div><h3>{asset.name}</h3>
        {asset.confirmed ? <p>{asset.description}</p> : <div className="confirm-fields"><textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="描述必须保留的外观、服装、色彩或空间特征" /><select value={policy} onChange={(event) => setPolicy(event.target.value as AssetPolicy)}><option value="reference">参考资产</option><option value="locked">锁定资产</option></select><button disabled={busy || !description.trim()} onClick={() => onConfirm(asset.id, { description, policy })}>确认并锁定描述</button></div>}
      </div>
    </article>
  );
}
