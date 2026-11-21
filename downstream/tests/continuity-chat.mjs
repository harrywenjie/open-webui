import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

export default async function ({ page }) {
  const lab = process.env.OWUI_SCREENSHOTS;
  const saved = path.join(lab, 'browser-chat.json');
  const real = process.env.OWUI_REAL === '1';
  const base = new URL(page.url()).origin;
  await page.locator('input[autocomplete="email"],input[name="email"],input[placeholder*="Email" i]').first().fill('admin@example.org');
  await page.locator('input[type="password"]').first().fill(process.env.OWUI_FIXTURE_PASSWORD);
  await page.locator('button[type="submit"]:visible').first().click();
  const input = page.locator('#chat-input');
  await input.waitFor({timeout: 45000});
  for (const label of ["Okay, Let's Go!", 'Get started', 'Skip']) {
    const button = page.getByRole('button', {name: label, exact: true});
    if (await button.isVisible()) await button.click();
  }
  const headers = {authorization: 'Bearer ' + await page.evaluate(() => localStorage.token)};
  const readChat = async () => {
    const id = new URL(page.url()).pathname.split('/').at(-1);
    const res = await page.request.get(base + '/api/v1/chats/' + id, {headers});
    assert.equal(res.status(), 200);
    return (await res.json()).chat.history;
  };
  const completed = async (check, stage = 'reply') => {
    const until = Date.now() + 125000;
    while (Date.now() < until) {
      const hist = await readChat();
      const msg = hist.messages[hist.currentId];
      if (msg?.error) throw Error('Chat completion failed');
      if (msg?.role === 'assistant' && msg.done && msg.content && check(msg, hist)) return msg;
      await new Promise(resolve => setTimeout(resolve, 400));
    }
    throw Error('Persisted assistant did not reach the expected ' + stage);
  };
  const send = async text => {
    await input.fill(text);
    await page.getByRole('button', {name:'Send message', exact:true}).click();
    await page.waitForURL(url => /^\/c\/[\da-f-]+$/.test(url.pathname), {timeout:45000});
  };
  if (process.env.OWUI_PROBE_RUN === '2') {
    const state = JSON.parse(await readFile(saved, 'utf8'));
    await page.goto(base + state.path);
    const msg = await completed(m => m.id === state.final);
    assert(msg.content.length > 0);
    return {browserRestart:true};
  }
  await send("New information: the Lantern project marker is cobalt-tamarind-726. Just reply ACK. Do not use any tools for this acknowledgement.");
  const first = await completed(() => true);
  const hud = page.locator('[data-testid="dissipative-control"] button[aria-label="Dissipative Memory"]:visible').first();
  await hud.click();
  await page.getByRole('button', {name:'Curate completed messages'}).waitFor({timeout:20000});
  await page.screenshot({path:path.join(lab, 'continuity-hud.png')});
  await page.keyboard.press('Escape');
  let final;
  if (real) {
    await send("Use answer_from_chat_memory_v2 to verify the earlier Lantern project marker. Use EXPLICIT_MEMORY_ONLY. Return just its publication marker.");
    final = await completed(m => m.id !== first.id);
    const output = final.output ?? [];
    const tool = output.find(o => o.type === 'function_call' && o.name === 'answer_from_chat_memory_v2');
    assert(tool, 'Real chat did not invoke the mounted FAST tool');
    assert(final.content.includes('cobalt-tamarind-726') && !final.content.includes('[[CHAT_MEMORY_PUBLICATION:'), 'FAST answer was not published');
  } else {
    await page.getByRole('button', {name:'Continue Response', exact:true}).last().click();
    await completed(m => m.id === first.id && m.content.length > first.content.length, 'continuation');
    await page.getByRole('button', {name:'Regenerate', exact:true}).last().click();
    const again = page.getByRole('button', {name:'Try Again', exact:true});
    await again.click({timeout:10000});
    final = await completed(m => m.id !== first.id && m.parentId === first.parentId, 'regenerated sibling');
  }
  await writeFile(saved, JSON.stringify({path:new URL(page.url()).pathname, final:final.id}));
  return {real, continuedAndRegenerated:!real, publishedFast:real};
}
