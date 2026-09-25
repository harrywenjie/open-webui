<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	export let valves: Record<string, any> = {};
	export let disabled = false;

	const dispatch = createEventDispatcher();
	const SCHEMA_VERSION = 2;
	const GENERAL_ID = 'general';
	const LEGACY_GENERAL_ID = 'general-use';
	const MAX_PRESETS = 32;
	const BUILTIN_PRESETS = [
		{
			id: GENERAL_ID,
			name: 'General',
			description:
				'Balanced exploration for conversation, analysis, reasoning, research, and technical discussion.',
			temperature: 1.0,
			top_p: 0.95,
			top_k: 40,
			min_p: 0,
			presence_penalty: 0.3,
			repeat_penalty: 1
		},
		{
			id: 'creative-writing',
			name: 'Creative Writing',
			description:
				'More varied and expressive output for fiction, dialogue, roleplay, and stylistic rewriting.',
			temperature: 1.2,
			top_p: 0.97,
			top_k: 60,
			min_p: 0,
			presence_penalty: 0.5,
			repeat_penalty: 1
		},
		{
			id: 'brainstorming',
			name: 'Brainstorming',
			description:
				'Aggressive diversity for divergent ideas, alternatives, worldbuilding, and concept generation.',
			temperature: 1.3,
			top_p: 0.98,
			top_k: 80,
			min_p: 0,
			presence_penalty: 0.7,
			repeat_penalty: 1
		},
		{
			id: 'coding',
			name: 'Coding',
			description: 'Controlled sampling for precise code, debugging, configuration, and shell work.',
			temperature: 0.6,
			top_p: 0.95,
			top_k: 20,
			min_p: 0,
			presence_penalty: 0,
			repeat_penalty: 1
		},
		{
			id: 'instruct',
			name: 'Instruct',
			description:
				'Focused output for strict instructions, summaries, extraction, schemas, and formatting-sensitive transformations.',
			temperature: 0.7,
			top_p: 0.8,
			top_k: 20,
			min_p: 0,
			presence_penalty: 0.5,
			repeat_penalty: 1
		}
	];
	const BUILTIN_IDS = new Set(BUILTIN_PRESETS.map((preset) => preset.id));
	const fields = [
		{ key: 'temperature', label: 'Temperature', min: 0, max: 2, step: 0.05 },
		{ key: 'top_p', label: 'Top P', min: 0, max: 1, step: 0.05 },
		{ key: 'top_k', label: 'Top K', min: 0, max: 200, step: 1 },
		{ key: 'min_p', label: 'Min P', min: 0, max: 1, step: 0.01 },
		{ key: 'presence_penalty', label: 'Presence Penalty', min: -2, max: 2, step: 0.05 },
		{ key: 'repeat_penalty', label: 'Repeat Penalty', min: 0.01, max: 2, step: 0.05 }
	];

	let observedValves: Record<string, any> | null = null;
	let editing = false;
	let editSnapshot: Record<string, any> | null = null;

	const clone = <T,>(value: T): T => structuredClone(value);
	const builtins = () => clone(BUILTIN_PRESETS);

	const normalize = (raw: Record<string, any>) => {
		const source = Array.isArray(raw?.presets) ? raw.presets : [];
		const custom = source
			.filter((item) => item && typeof item === 'object' && typeof item.id === 'string')
			.filter((item) => !BUILTIN_IDS.has(item.id) && item.id !== LEGACY_GENERAL_ID)
			.map((item) => ({ ...item }));
		const normalized = [...builtins(), ...custom];
		const requested = raw?.selected_preset_id === LEGACY_GENERAL_ID ? GENERAL_ID : raw?.selected_preset_id;
		const selected = normalized.some((item) => item.id === requested)
			? requested
			: GENERAL_ID;
		return { schema_version: SCHEMA_VERSION, selected_preset_id: selected, presets: normalized };
	};

	const replaceValves = (next: Record<string, any>) => {
		observedValves = next;
		valves = next;
	};

	$: if (valves !== observedValves) {
		const next = normalize(valves ?? {});
		observedValves = next;
		valves = next;
		editing = false;
		editSnapshot = null;
	}
	$: presets = valves?.presets ?? [];
	$: current = presets.find((item) => item.id === valves?.selected_preset_id) ?? presets[0];
	$: currentIsBuiltin = current ? BUILTIN_IDS.has(current.id) : false;

	const choosePreset = (event: Event) => {
		const nextId = (event.currentTarget as HTMLSelectElement).value;
		if (editing && editSnapshot && !confirm('Discard the unsaved preset changes?')) {
			(event.currentTarget as HTMLSelectElement).value = valves.selected_preset_id;
			return;
		}
		replaceValves({ ...valves, selected_preset_id: nextId });
		editing = false;
		editSnapshot = null;
	};

	const beginEdit = () => {
		if (currentIsBuiltin) return;
		editSnapshot = clone(valves);
		editing = true;
	};

	const cancelEdit = () => {
		if (editSnapshot) replaceValves(editSnapshot);
		editing = false;
		editSnapshot = null;
	};

	const uniqueNewName = () => {
		const names = new Set(presets.map((item) => String(item.name).toLocaleLowerCase()));
		let index = 1;
		let name = 'New Preset';
		while (names.has(name.toLocaleLowerCase())) name = `New Preset ${++index}`;
		return name;
	};

	const addPreset = () => {
		if (presets.length >= MAX_PRESETS) {
			toast.error(`At most ${MAX_PRESETS} presets are allowed.`);
			return;
		}
		const source = current ?? builtins()[0];
		const id = `preset-${crypto.randomUUID()}`;
		const created = {
			id,
			name: uniqueNewName(),
			description: '',
			...Object.fromEntries(fields.map((field) => [field.key, Number(source[field.key])]))
		};
		editSnapshot = clone(valves);
		replaceValves({ ...valves, selected_preset_id: id, presets: [...presets, created] });
		editing = true;
	};

	const updateName = (event: Event) => {
		if (!current || currentIsBuiltin) return;
		current.name = (event.currentTarget as HTMLInputElement).value;
		replaceValves({ ...valves, presets: [...presets] });
	};

	const updateDescription = (event: Event) => {
		if (!current || currentIsBuiltin) return;
		current.description = (event.currentTarget as HTMLTextAreaElement).value;
		replaceValves({ ...valves, presets: [...presets] });
	};

	const updateNumber = (key: string, event: Event) => {
		if (!current || currentIsBuiltin) return;
		current[key] = Number((event.currentTarget as HTMLInputElement).value);
		replaceValves({ ...valves, presets: [...presets] });
	};

	const removePreset = () => {
		if (!current || currentIsBuiltin) return;
		if (!confirm(`Delete “${current.name}”? This cannot be undone.`)) return;
		const remaining = presets.filter((item) => item.id !== current.id);
		replaceValves({ ...valves, selected_preset_id: GENERAL_ID, presets: remaining });
		editing = false;
		editSnapshot = null;
		dispatch('submit');
	};

	export const prepareSubmit = () => {
		const normalized = normalize(valves);
		const names = new Set<string>(BUILTIN_PRESETS.map((preset) => preset.name.toLocaleLowerCase()));
		for (const preset of normalized.presets) {
			if (BUILTIN_IDS.has(preset.id)) continue;
			preset.name = String(preset.name ?? '').trim().replace(/\s+/g, ' ');
			if (!preset.name || preset.name.length > 64) {
				toast.error('Preset names must contain 1–64 characters.');
				return false;
			}
			const folded = preset.name.toLocaleLowerCase();
			if (names.has(folded)) {
				toast.error('Preset names must be unique.');
				return false;
			}
			names.add(folded);
			preset.description = String(preset.description ?? '').trim().replace(/\s+/g, ' ');
			if (preset.description.length > 280) {
				toast.error('Preset descriptions must contain at most 280 characters.');
				return false;
			}
			if (!preset.description) preset.description = null;
			for (const field of fields) {
				const value = Number(preset[field.key]);
				if (!Number.isFinite(value) || value < field.min || value > field.max) {
					toast.error(`${field.label} must be between ${field.min} and ${field.max}.`);
					return false;
				}
				if (field.key === 'top_k' && !Number.isInteger(value)) {
					toast.error('Top K must be an integer.');
					return false;
				}
				preset[field.key] = value;
			}
		}
		replaceValves(normalized);
		return true;
	};

	export const commitSucceeded = () => {
		editing = false;
		editSnapshot = null;
	};
</script>

{#if current}
	<div class="space-y-3">
		<div class="flex items-end gap-2">
			<label class="min-w-0 flex-1 text-xs">
				<span class="mb-1 block text-gray-500 dark:text-gray-400">Preset</span>
				<select
					class="w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-hidden dark:border-gray-700 dark:text-gray-200"
					value={valves.selected_preset_id}
					on:change={choosePreset}
					disabled={disabled}
				>
					{#each presets as preset (preset.id)}
						<option value={preset.id}>{preset.name}</option>
					{/each}
				</select>
			</label>
			<button class="preset-action" type="button" on:click={addPreset} disabled={disabled}>New</button>
			{#if editing}
				<button class="preset-action" type="button" on:click={cancelEdit} disabled={disabled}>Cancel</button>
			{:else}
				<button class="preset-action" type="button" on:click={beginEdit} disabled={disabled || currentIsBuiltin}>Edit</button>
			{/if}
		</div>

		<label class="block text-xs">
			<span class="mb-1 block text-gray-500 dark:text-gray-400">Name</span>
			<input
				class="preset-input"
				type="text"
				value={current.name}
				on:input={updateName}
				disabled={!editing || disabled || currentIsBuiltin}
				maxlength="64"
			/>
		</label>

		<label class="block text-xs">
			<span class="mb-1 block text-gray-500 dark:text-gray-400">Purpose</span>
			<textarea
				class="preset-input min-h-16 resize-y"
				value={current.description ?? ''}
				on:input={updateDescription}
				disabled={!editing || disabled || currentIsBuiltin}
				maxlength="280"
				placeholder="Optional short description of when to use this preset"
			></textarea>
		</label>

		<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
			{#each fields as field}
				<label class="text-xs">
					<span class="mb-1 block text-gray-500 dark:text-gray-400">{field.label}</span>
					<input
						class="preset-input"
						type="number"
						value={current[field.key]}
						min={field.min}
						max={field.max}
						step={field.step}
						on:input={(event) => updateNumber(field.key, event)}
						disabled={!editing || disabled || currentIsBuiltin}
					/>
				</label>
			{/each}
		</div>

		{#if currentIsBuiltin}
			<p class="text-xs text-gray-500 dark:text-gray-400">Built-in preset · cannot be edited or deleted</p>
		{:else}
			<div class="flex justify-start">
				<button
					class="rounded-lg px-2 py-1 text-xs text-red-600 transition hover:bg-red-50 disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-950/30"
					type="button"
					on:click={removePreset}
					disabled={disabled}
				>Delete preset</button
				>
			</div>
		{/if}
	</div>
{/if}

<style>
	.preset-action {
		border-radius: 0.5rem;
		padding: 0.5rem 0.75rem;
		font-size: 0.75rem;
		transition: background-color 150ms ease;
	}
	.preset-action:hover:not(:disabled) {
		background: rgb(249 250 251);
	}
	:global(.dark) .preset-action:hover:not(:disabled) {
		background: rgb(31 41 55);
	}
	.preset-action:disabled {
		opacity: 0.5;
	}
	.preset-input {
		width: 100%;
		border-radius: 0.5rem;
		border: 1px solid rgb(229 231 235);
		background: transparent;
		padding: 0.5rem 0.75rem;
		font-size: 0.875rem;
		outline: none;
	}
	.preset-input:disabled {
		cursor: default;
		opacity: 0.75;
	}
	:global(.dark) .preset-input {
		border-color: rgb(55 65 81);
		color: rgb(229 231 235);
	}
</style>
