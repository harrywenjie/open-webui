<script lang="ts">
	export let node: any;

	const statusText = (value: string) => ({
		NOT_ESTABLISHED: "Not established",
		UNKNOWN: "Unknown",
		NOT_APPLICABLE: "Not applicable",
		STALE: "Stale",
	}[value] ?? value);
</script>

{#if node.kind === "GROUP"}
	<section class="ml-1 border-l border-gray-200 pl-3 dark:border-gray-700" data-profile-state-node={node.node_id}>
		<h4 class="py-1 text-xs font-semibold uppercase tracking-wide ops-muted">{node.label}</h4>
		{#each node.children ?? [] as child (child.node_id)}
			<svelte:self node={child} />
		{/each}
	</section>
{:else}
	<div class="mb-1.5 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-2 text-sm dark:border-gray-700 dark:bg-gray-800" data-profile-state-field={node.field_id} data-profile-state-status={node.status}>
		<div class="flex items-start justify-between gap-2">
			<span class="font-medium">{node.label}</span>
			<span class="shrink-0 text-[11px] uppercase tracking-wide ops-muted">{statusText(node.status)}</span>
		</div>
		{#if node.status === "ESTABLISHED"}
			<p class="mt-1 whitespace-pre-wrap break-words">{node.value}</p>
		{:else if node.status === "STALE" && node.disclosure === "HISTORICAL" && node.value}
			<p class="mt-1 whitespace-pre-wrap break-words opacity-75">{node.value}</p>
		{:else if node.status === "STALE" && node.disclosure === "WITHHELD"}
			<p class="mt-1 ops-muted">Unavailable because its source was removed or suppressed.</p>
		{:else}
			<p class="mt-1 ops-muted">{statusText(node.status)}</p>
		{/if}
		{#if node.last_evaluated_round_id || node.updated_at}
			<p class="mt-1 text-[11px] ops-muted">
				{node.last_evaluated_round_id ? "Evaluated" : "Not evaluated on this branch"}
				{#if node.updated_at} · value recorded {new Date(node.updated_at).toLocaleString()}{/if}
			</p>
		{/if}
	</div>
{/if}
