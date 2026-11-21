import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const definition = JSON.parse(await readFile(process.env.OWUI_THEME_DEFINITION, 'utf8'));
const badge = (page) =>
	page.locator('[data-testid="dissipative-control"] button[aria-label="Dissipative Memory"]');
const settingsSelect = (page) =>
	page.locator('select').filter({ has: page.locator('option[value="oled-dark"]') });
const shot = (page, name) =>
	page.screenshot({
		path: path.join(process.env.OWUI_SCREENSHOTS, process.env.OWUI_PROBE_RUN + '-' + name + '.png')
	});

async function openSettings(page) {
	const menu = page
		.locator(
			'button[aria-label="User menu"]:visible, button:has(img[alt="Open User Profile Menu"]):visible'
		)
		.first();
	await menu.click();
	await page.getByText('Settings', { exact: true }).filter({ visible: true }).last().click();
	await settingsSelect(page).waitFor();
}

async function appearance(page, mode) {
	const expected = definition.modes[mode === 'oled-dark' ? 'oled' : mode].ui;
	await page.waitForFunction(
		(expected) => {
			const style = getComputedStyle(document.body);
			const rgb = (hex) =>
				'rgb(' +
				hex
					.match(/[a-f0-9]{2}/gi)
					.map((byte) => parseInt(byte, 16))
					.join(', ') +
				')';
			return (
				style.backgroundColor === rgb(expected.canvas) &&
				style.color === rgb(expected.text) &&
				style.backgroundImage.includes('linear-gradient')
			);
		},
		expected,
		{ timeout: 12000 }
	);
	return page.evaluate(() => {
		const s = getComputedStyle(document.body);
		return {
			canvas: s.backgroundColor,
			text: s.color,
			grid: s.backgroundImage.includes('linear-gradient'),
			theme: document.documentElement.getAttribute('data-theme'),
			accent: s.getPropertyValue('--ops-accent').trim()
		};
	});
}

export default async function ({ page }) {
	const values = {};
	try {
		await page
			.locator('input[autocomplete="email"],input[name="email"],input[placeholder*="Email" i]')
			.first()
			.fill('admin@example.org');
		await page.locator('input[type="password"]').first().fill(process.env.OWUI_FIXTURE_PASSWORD);
		await page.locator('button[type="submit"]').filter({ visible: true }).first().click();
		await page.waitForURL((url) => !url.pathname.startsWith('/auth'), { timeout: 30000 });
		await page.locator('#chat-input').waitFor({ timeout: 30000 });
		const initial = await page.evaluate(() => {
			const choice = document.documentElement.getAttribute('data-theme') || 'system';
			return choice === 'system'
				? matchMedia('(prefers-color-scheme: dark)').matches
					? 'dark'
					: 'light'
				: choice;
		});
		if (process.env.OWUI_PROBE_RUN === '2') assert.equal(initial, 'her');
		await appearance(page, initial);
		await shot(page, 'initial');
		for (const label of ["Okay, Let's Go!", 'Get started', 'Skip']) {
			const button = page.getByRole('button', { name: label, exact: true });
			if (await button.isVisible().catch(() => false)) await button.click();
		}
		await openSettings(page);
		for (const [choice, mode] of [
			['dark', 'dark'],
			['oled-dark', 'oled-dark'],
			['light', 'light'],
			['her', 'her'],
			['system', 'light'],
			['system', 'dark']
		]) {
			if (choice === 'system') await page.emulateMedia({ colorScheme: mode });
			await settingsSelect(page).selectOption(choice);
			if (choice === 'system') {
				await page.reload();
				await page.locator('#chat-input').waitFor();
			}
			values[choice === 'system' ? 'system-' + mode : choice] = await appearance(page, mode);
			if (
				await settingsSelect(page)
					.isVisible()
					.catch(() => false)
			)
				await page.keyboard.press('Escape');
			await page.locator('#chat-input').focus();
			await badge(page).click();
			const hud = page.getByRole('dialog', { name: 'Dissipative Memory settings and status' });
			await hud.waitFor();
			assert(await hud.getByRole('button', { name: 'Close Dissipative Memory' }).isVisible());
			await shot(page, choice === 'system' ? 'system-' + mode : choice);
			await hud.getByRole('button', { name: 'Close Dissipative Memory' }).click();
			if (choice !== 'system' || mode === 'light') await openSettings(page);
		}
		const iconPaths = await page
			.locator('link[rel*="icon"],link[rel="manifest"]')
			.evaluateAll((links) => links.map((el) => new URL(el.href).pathname));
		for (const name of ['/static/favicon.png', '/static/apple-touch-icon.png', '/manifest.json'])
			assert(iconPaths.includes(name));
		const branding = JSON.parse(
			await readFile(new URL('../branding/manifest.json', import.meta.url), 'utf8')
		).assets;
		if (process.env.OWUI_PROBE_RUN === '1') {
			await openSettings(page);
			await settingsSelect(page).selectOption('her');
			await appearance(page, 'her');
			const value = await page.evaluate(() => localStorage.getItem('theme'));
			assert.equal(value, 'her');
			const origin = new URL(page.url()).origin;
			// Carry only the saved theme across the real service restart. The next browser signs in again.
			await writeFile(
				path.join(process.env.OWUI_SCREENSHOTS, 'theme-choice.json'),
				JSON.stringify({
					cookies: [],
					origins: [{ origin, localStorage: [{ name: 'theme', value }] }]
				})
			);
		}
		for (const [manifestPath, sizes] of [
			['/manifest.json', ['500x500']],
			['/static/site.webmanifest', ['192x192', '512x512']]
		]) {
			const manifest = await (
				await page.request.get(new URL(manifestPath, page.url()).href)
			).json();
			assert.deepEqual([...new Set(manifest.icons.map((icon) => icon.sizes))].sort(), sizes);
			for (const icon of manifest.icons) {
				const url = new URL(icon.src, page.url());
				const asset = branding[path.posix.basename(url.pathname)];
				assert.equal(icon.sizes, asset.width + 'x' + asset.height);
				const body = await (await page.request.get(url.href)).body();
				assert.equal(createHash('sha256').update(body).digest('hex'), asset.sha256);
			}
		}
		await writeFile(
			path.join(process.env.OWUI_SCREENSHOTS, process.env.OWUI_PROBE_RUN + '-modes.json'),
			JSON.stringify({ values, iconPaths }, null, 2)
		);
		const chatFile = path.join(process.env.OWUI_SCREENSHOTS, 'chat-path.json');
		const answer = page.getByText('Rehearsal response from the local model.', { exact: true });
		if (process.env.OWUI_PROBE_RUN === '1') {
			await page.keyboard.press('Escape');
			await page.locator('#chat-input').fill('Check that a fresh chat survives a service restart.');
			await page.getByRole('button', { name: 'Send message', exact: true }).click();
			await page.waitForURL((url) => /^\/c\/[\da-f-]+$/.test(url.pathname), { timeout: 30000 });
			await answer.first().waitFor({ timeout: 30000 });
			await writeFile(chatFile, JSON.stringify(new URL(page.url()).pathname));
		} else {
			const saved = JSON.parse(await readFile(chatFile, 'utf8'));
			assert(/^\/c\/[\da-f-]+$/.test(saved));
			await page.goto(new URL(saved, page.url()).href);
			await answer.first().waitFor({ timeout: 30000 });
		}
		return { modes: Object.keys(values), hud: true, chat: true };
	} catch (e) {
		await shot(page, 'failure').catch(() => {});
		const info = await page.evaluate(() => ({
			route: location.pathname,
			body: getComputedStyle(document.body).backgroundColor,
			theme: document.documentElement.getAttribute('data-theme'),
			labels: [...document.querySelectorAll('button[aria-label]')]
				.map((x) => x.getAttribute('aria-label'))
				.slice(-22)
		}));
		await writeFile(
			path.join(process.env.OWUI_SCREENSHOTS, 'browser-diagnostic.json'),
			JSON.stringify(info)
		);
		throw e;
	}
}
