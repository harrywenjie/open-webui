<script lang="ts">
	export let src = '';
	export let name = '';
	export let trusted = false;
	export let className = 'size-4';

	$: useMask = trusted && src.startsWith('data:image/svg+xml');

	function trustedMaskSource(value: string) {
		const separator = value.indexOf(',');
		if (separator === -1) return '';

		const header = value.slice(0, separator);
		const payload = value.slice(separator + 1);
		if (header.toLowerCase().includes(';base64')) return `url("${value}")`;

		let svg = payload;
		try {
			svg = decodeURIComponent(payload);
		} catch {
			// Raw data-SVG payloads are valid inputs and are encoded below.
		}
		return `url("${header},${encodeURIComponent(svg)}")`;
	}

	$: maskSource = useMask ? trustedMaskSource(src) : '';
</script>

{#if useMask}
	<span
		class="ops-trusted-function-icon inline-block shrink-0 {className}"
		style={`--ops-trusted-function-icon: ${maskSource};`}
		role="img"
		aria-label={name}
	></span>
{:else}
	<img src={src} class="{className} {src.startsWith('data:image/svg') ? 'dark:invert-[80%]' : ''}" alt={name} />
{/if}

<style>
	.ops-trusted-function-icon {
		background-color: currentColor;
		mask-image: var(--ops-trusted-function-icon);
		mask-position: center;
		mask-repeat: no-repeat;
		mask-size: contain;
		-webkit-mask-image: var(--ops-trusted-function-icon);
		-webkit-mask-position: center;
		-webkit-mask-repeat: no-repeat;
		-webkit-mask-size: contain;
	}
</style>
