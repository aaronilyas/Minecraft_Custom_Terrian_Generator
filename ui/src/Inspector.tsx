import { useState, type FormEvent } from "react";
import { BIOMES, TREE_KINDS, VEGETATION, draftFromRegion, emptyDraft } from "./plan";
import type { BlockInfo, Project, Region, RegionDraft } from "./types";

interface InspectorProps {
  project: Project;
  region: Region | null;
  blocks: BlockInfo[];
  onApply: (draft: RegionDraft) => void;
  onUpload: (file: File, draft: RegionDraft) => Promise<string | null>;
  onDelete: (regionId: string) => void;
}

function solidChoices(blocks: BlockInfo[], current: string): BlockInfo[] {
  const solid = blocks.filter((block) => block.solid);
  if (current && !solid.some((block) => block.id === current)) {
    return [{ id: current, name: current, category: "current", rgb: [128, 128, 128], solid: true }, ...solid];
  }
  return solid;
}

function BlockSelect({
  testId,
  value,
  blocks,
  disabled,
  onChange,
}: {
  testId: string;
  value: string;
  blocks: BlockInfo[];
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const groups: { category: string; blocks: BlockInfo[] }[] = [];
  for (const block of solidChoices(blocks, value)) {
    const group = groups.find((item) => item.category === block.category);
    if (group) group.blocks.push(block);
    else groups.push({ category: block.category, blocks: [block] });
  }
  return (
    <select data-testid={testId} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
      {groups.map((group) => (
        <optgroup key={group.category} label={group.category}>
          {group.blocks.map((block) => (
            <option key={block.id} value={block.id}>
              {block.name}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

export function Inspector({ project, region, blocks, onApply, onUpload, onDelete }: InspectorProps) {
  const [draft, setDraft] = useState<RegionDraft>(() => (region ? draftFromRegion(region) : emptyDraft()));

  function update(patch: Partial<RegionDraft>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    onApply(draft);
  }

  async function onFile(file: File) {
    const assetId = await onUpload(file, draft);
    if (!assetId) return;
    setDraft((current) => ({
      ...current,
      assetIds: [...current.assetIds.filter((id) => id !== assetId), assetId],
    }));
  }

  const locked = !region;
  const primaryId = draft.assetIds[draft.assetIds.length - 1];
  const primary = project.assets.find((asset) => asset.id === primaryId);

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Region</h2>
      {region ? (
        <p className="note">
          {region.shape.x}, {region.shape.z} · {region.shape.width}×{region.shape.depth}
        </p>
      ) : (
        <p className="note">Select a region to edit its brief, blocks, and terrain.</p>
      )}
      <div className="fields">
        <label className="wide">
          Name
          <input
            data-testid="region-name"
            value={draft.name}
            maxLength={48}
            disabled={locked}
            onChange={(event) => update({ name: event.target.value })}
          />
        </label>
        <label>
          Color
          <input
            data-testid="region-color"
            type="color"
            value={draft.color}
            disabled={locked}
            onChange={(event) => update({ color: event.target.value })}
          />
        </label>
        <label>
          Vanilla biome
          <select
            data-testid="vanilla-biome"
            value={draft.biome}
            disabled={locked}
            onChange={(event) => update({ biome: event.target.value })}
          >
            {BIOMES.some((biome) => biome.id === draft.biome) ? null : (
              <option value={draft.biome}>{draft.biome}</option>
            )}
            {BIOMES.map((biome) => (
              <option key={biome.id} value={biome.id}>
                {biome.label}
              </option>
            ))}
          </select>
        </label>
        <label className="wide">
          Brief
          <textarea
            data-testid="brief-text"
            value={draft.text}
            maxLength={4000}
            disabled={locked}
            onChange={(event) => update({ text: event.target.value })}
          />
        </label>
        <label className="wide">
          Reference image
          <input
            data-testid="brief-image"
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            disabled={locked}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void onFile(file);
            }}
          />
        </label>
      </div>
      <div className="thumbs">
        {draft.assetIds.length === 0 ? (
          <img data-testid="brief-thumb" alt="Region reference" hidden />
        ) : (
          draft.assetIds.map((assetId) => {
            const asset = project.assets.find((item) => item.id === assetId);
            const isPrimary = assetId === primaryId;
            return (
              <img
                key={assetId}
                data-testid={isPrimary ? "brief-thumb" : undefined}
                alt={asset?.caption ? `Reference: ${asset.caption}` : "Region reference"}
                src={`/api/projects/${project.id}/assets/${assetId}/thumb`}
              />
            );
          })
        )}
      </div>
      {primary?.caption ? <p className="note">{primary.caption}</p> : null}
      <h3>Palette</h3>
      <div className="fields">
        <label>
          Surface
          <BlockSelect
            testId="palette-surface"
            value={draft.surface}
            blocks={blocks}
            disabled={locked}
            onChange={(surface) => update({ surface })}
          />
        </label>
        <label>
          Subsurface
          <BlockSelect
            testId="palette-subsurface"
            value={draft.subsurface}
            blocks={blocks}
            disabled={locked}
            onChange={(subsurface) => update({ subsurface })}
          />
        </label>
        <label className="wide">
          Stone
          <BlockSelect
            testId="palette-stone"
            value={draft.stone}
            blocks={blocks}
            disabled={locked}
            onChange={(stone) => update({ stone })}
          />
        </label>
      </div>
      <h3>Terrain</h3>
      <div className="fields">
        <label>
          Base height
          <input
            data-testid="terrain-base"
            type="number"
            min={8}
            max={180}
            step={1}
            value={draft.baseHeight}
            disabled={locked}
            onChange={(event) => update({ baseHeight: event.target.value })}
          />
        </label>
        <label>
          Amplitude
          <input
            data-testid="terrain-amplitude"
            type="number"
            min={0}
            max={48}
            step={1}
            value={draft.amplitude}
            disabled={locked}
            onChange={(event) => update({ amplitude: event.target.value })}
          />
        </label>
        <label>
          Roughness
          <input
            data-testid="terrain-roughness"
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={draft.roughness}
            disabled={locked}
            onChange={(event) => update({ roughness: event.target.value })}
          />
        </label>
        <label className="check">
          <input
            data-testid="terrain-water"
            type="checkbox"
            checked={draft.water}
            disabled={locked}
            onChange={(event) => update({ water: event.target.checked })}
          />
          Water
        </label>
      </div>
      <h3>Features</h3>
      <div className="fields">
        <label>
          Trees
          <select
            data-testid="feature-trees"
            value={draft.trees}
            disabled={locked}
            onChange={(event) => update({ trees: event.target.value })}
          >
            {TREE_KINDS.some((kind) => kind === draft.trees) ? null : (
              <option value={draft.trees}>{draft.trees}</option>
            )}
            {TREE_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
        </label>
        <label>
          Tree density
          <input
            data-testid="feature-tree-density"
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={draft.density}
            disabled={locked}
            onChange={(event) => update({ density: event.target.value })}
          />
        </label>
        <label>
          Vegetation
          <select
            data-testid="feature-vegetation"
            value={draft.vegetation}
            disabled={locked}
            onChange={(event) => update({ vegetation: event.target.value })}
          >
            {VEGETATION.some((kind) => kind === draft.vegetation) ? null : (
              <option value={draft.vegetation}>{draft.vegetation}</option>
            )}
            {VEGETATION.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input
            data-testid="feature-ores"
            type="checkbox"
            checked={draft.ores}
            disabled={locked}
            onChange={(event) => update({ ores: event.target.checked })}
          />
          Ores
        </label>
        <label className="check">
          <input
            data-testid="feature-caves"
            type="checkbox"
            checked={draft.caves}
            disabled={locked}
            onChange={(event) => update({ caves: event.target.checked })}
          />
          Caves
        </label>
      </div>
      <div className="actions">
        <button className="primary" type="submit" data-testid="apply-region" disabled={locked}>
          Apply region
        </button>
        <button type="button" onClick={() => region && onDelete(region.id)} disabled={locked}>
          Remove region
        </button>
      </div>
    </form>
  );
}
