<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	const dispatch=createEventDispatcher();
	export let draft: any;
	export let savedIds: string[]=[];
	export let validation: any=null;
	let dragged='';
	let rows:any[]=[];

	const slug=(label:string, used:string[])=>{
		let base=label.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,64)||'item';
		let candidate=base, n=2; while(used.includes(candidate)){const suffix=`-${n++}`; candidate=base.slice(0,64-suffix.length)+suffix;} return candidate;
	};
	const entries=()=>{const out:any[]=[]; const visit=(nodes:any[],parent:any,depth:number)=>nodes.forEach((node,index)=>{out.push({node,nodes,parent,depth,index});visit(node.children??[],node,depth+1)});visit(draft.nodes??[],null,0);return out;};
	$: { draft; rows=entries(); }
	const touch=()=>draft={...draft,nodes:[...draft.nodes]};
	const add=(entry:any|null,child=false)=>{const used=entries().map(x=>x.node.id); const node={id:slug('New item',used),label:'New item',kind:'ITEM',guidance:'',children:[]}; if(!entry){draft={...draft,nodes:[...(draft.nodes??[]),node]};return} if(child){entry.node.kind='GROUP';entry.node.children.push(node)} else entry.nodes.splice(entry.index+1,0,node);touch();};
	const remove=(entry:any)=>{entry.nodes.splice(entry.index,1);touch();};
	const move=(entry:any,delta:number)=>{const to=entry.index+delta;if(to<0||to>=entry.nodes.length)return;entry.nodes.splice(to,0,entry.nodes.splice(entry.index,1)[0]);touch();};
	const indent=(entry:any)=>{if(entry.index<1)return;const parent=entry.nodes[entry.index-1];if(parent.kind!=='GROUP')return;parent.children??=[];if(parent.children.length>=16)return;parent.children.push(entry.nodes.splice(entry.index,1)[0]);touch();};
	const outdent=(entry:any)=>{if(!entry.parent)return;const parentEntry=entries().find(x=>x.node===entry.parent);if(!parentEntry)return;entry.nodes.splice(entry.index,1);parentEntry.nodes.splice(parentEntry.index+1,0,entry.node);touch();};
	const drop=(target:any)=>{const source=entries().find(x=>x.node.id===dragged);if(source&&source.nodes===target.nodes&&source!==target){source.nodes.splice(source.index,1);const index=target.nodes.indexOf(target.node);target.nodes.splice(index,0,source.node);touch()}dragged='';};
	const relabel=(entry:any)=>{if(!savedIds.includes(entry.node.id)){const used=entries().map(x=>x.node.id).filter(x=>x!==entry.node.id);entry.node.id=slug(entry.node.label,used)}touch();};
</script>

<div class="space-y-3" data-testid="profile-editor">
	<div class="grid gap-2 sm:grid-cols-2"><label class="text-sm">Name<input class="mt-1 w-full rounded-lg border bg-transparent px-2 py-1" bind:value={draft.display_name}/></label><label class="text-sm">Stable profile ID<input class="mt-1 w-full rounded-lg border bg-transparent px-2 py-1" bind:value={draft.profile_id} disabled={savedIds.length>0}/></label></div>
	<label class="block text-sm">Purpose<input class="mt-1 w-full rounded-lg border bg-transparent px-2 py-1" bind:value={draft.purpose}/></label>
	<label class="block text-sm">Global guidance<textarea class="mt-1 w-full rounded-lg border bg-transparent px-2 py-1" rows="2" bind:value={draft.global_guidance}></textarea></label>
	<div class="flex items-center justify-between"><h3 class="font-medium">Observation tree</h3><button type="button" class="rounded-lg border px-2 py-1" on:click={()=>add(null)}>+ Add item</button></div>
	<div class="space-y-1">
		{#each rows as entry (entry.node.id)}
			<div class="grid gap-1 rounded-lg border border-gray-200 p-2 dark:border-gray-700" style={`margin-left:${Math.min(entry.depth,4)*1.25}rem`} role="listitem" draggable="true" on:dragstart={()=>dragged=entry.node.id} on:dragover|preventDefault on:drop={()=>drop(entry)} data-node-id={entry.node.id}>
				<div class="flex flex-wrap items-center gap-1"><span aria-label="Drag to reorder" class="cursor-grab px-1">⋮⋮</span><input aria-label="Label" class="min-w-32 flex-1 rounded border bg-transparent px-2 py-1" bind:value={entry.node.label} on:change={()=>relabel(entry)}/><select aria-label="Kind" class="rounded border bg-transparent px-1 py-1" bind:value={entry.node.kind}><option value="ITEM">Item</option><option value="GROUP">Group</option></select></div>
				<label class="text-xs text-gray-500">Stable ID <input class="rounded border bg-transparent px-1" bind:value={entry.node.id} disabled={savedIds.includes(entry.node.id)}/></label>
				<textarea aria-label="Guidance" class="w-full rounded border bg-transparent px-2 py-1 text-sm" rows="2" bind:value={entry.node.guidance}></textarea>
				<div class="flex flex-wrap gap-1 text-xs"><button type="button" class="rounded border px-2 py-1" on:click={()=>add(entry)}>+ sibling</button>{#if entry.node.kind==='GROUP'}<button type="button" class="rounded border px-2 py-1" on:click={()=>add(entry,true)}>+ child</button>{/if}<button type="button" aria-label="Move up" class="rounded border px-2 py-1" on:click={()=>move(entry,-1)}>↑</button><button type="button" aria-label="Move down" class="rounded border px-2 py-1" on:click={()=>move(entry,1)}>↓</button><button type="button" class="rounded border px-2 py-1" on:click={()=>indent(entry)}>Indent</button><button type="button" class="rounded border px-2 py-1" on:click={()=>outdent(entry)}>Outdent</button><button type="button" class="rounded border border-red-300 px-2 py-1 text-red-600" on:click={()=>remove(entry)}>Delete</button></div>
			</div>
		{/each}
	</div>
	<div class="rounded-lg bg-gray-50 p-2 text-xs dark:bg-gray-800" aria-live="polite">{#if validation}<span>{validation.node_count} nodes · depth {validation.max_depth} · {validation.canonical_bytes}/16384 bytes · {validation.profile_hash}</span>{:else}<span>Save validation is authoritative on the server.</span>{/if}</div>
	<div class="flex justify-end gap-2"><button type="button" class="rounded-lg border px-3 py-1.5" on:click={()=>dispatch('preview',draft)}>Preview</button><button type="button" class="rounded-lg bg-black px-3 py-1.5 text-white dark:bg-white dark:text-black" on:click={()=>dispatch('save',draft)}>Save immutable revision</button></div>
</div>
