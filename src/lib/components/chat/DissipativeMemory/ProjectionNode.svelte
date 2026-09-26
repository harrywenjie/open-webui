<script lang="ts">
	export let node: any;
</script>

<section class="ml-2 border-l border-gray-200 pl-3 dark:border-gray-700" data-memory-node={node.node_id}>
	<h4 class="py-1 text-sm font-medium text-gray-700 dark:text-gray-200">{node.label}</h4>
	{#each node.items ?? [] as item (item.item_id)}
		<div class="mb-1 flex items-start justify-between gap-2 rounded-lg bg-gray-50 px-2 py-1.5 text-sm dark:bg-gray-800">
			<span>{item.text}</span><span class="text-xs text-gray-500">{item.activity_state}</span>
		</div>
	{/each}
	{#each node.children ?? [] as child (child.node_id)}
		<svelte:self node={child} />
	{/each}
</section>
