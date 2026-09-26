// Mount the real Svelte HUD in Chromium. Only management HTTP and unrelated widgets are doubled.
// Usage: CHAT_MEMORY_FRONTEND_NODE_MODULES=<qualified build>/node_modules node <this file>
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const {createRequire} = require('node:module');
const root = path.resolve(__dirname, '../..');
const dependencies = process.env.CHAT_MEMORY_FRONTEND_NODE_MODULES;
if (!dependencies) throw new Error('Set CHAT_MEMORY_FRONTEND_NODE_MODULES to the prepared upstream dependencies');
const fromBuild = createRequire(path.join(path.resolve(dependencies), 'package.json'));
const {compile} = fromBuild('svelte/compiler');
const esbuild = fromBuild('esbuild');
const {chromium} = require(path.join(process.env.APPDATA, 'npm/node_modules/@playwright/mcp/node_modules/playwright'));
const main = path.join(root, 'src/lib/components/chat/DissipativeMemoryControl.svelte');

async function run() {
  const bundle = await esbuild.build({
    stdin: {contents: `import {createClassComponent} from 'svelte/legacy'; import Hud from ${JSON.stringify(main)};
      window.control = createClassComponent({component:Hud,target:document.body,props:{chatId:'',available:true,availableState:true,enabled:true,selectedToolIds:['phase09_remember']}});`,
      resolveDir: root, sourcefile: 'hud-entry.js'},
    bundle: true, write: false, format: 'iife', platform: 'browser', conditions: ['browser'],
    nodePaths: [path.resolve(dependencies)],
    plugins: [{name: 'actual-hud', setup(build) {
      build.onResolve({filter: /^\$lib\/apis\/chat-memory$/}, () => ({path: 'api', namespace: 'mock'}));
      build.onLoad({filter: /.*/, namespace: 'mock'}, () => ({contents:
        'export const manageMemory = (_token, chat, action, payload) => window.manage(chat,action,payload);'}));
      build.onResolve({filter: /Tooltip\.svelte$|Wrench\.svelte$|XMark\.svelte$|ProfileEditor\.svelte$/},
        () => ({path: 'widget.svelte', namespace: 'widget'}));
      build.onLoad({filter: /.*/, namespace: 'widget'}, () => ({contents:
        compile('<slot />', {filename: 'widget.svelte', generate: 'client'}).js.code, resolveDir: root}));
      build.onLoad({filter: /\.svelte$/}, args => ({
        contents: compile(fs.readFileSync(args.path, 'utf8'), {filename: args.path, generate: 'client', css: 'injected'}).js.code,
        resolveDir: path.dirname(args.path), loader: 'js'}));
    }}]
  });
  const server = http.createServer((request, response) => {
    response.setHeader('content-type', request.url === '/bundle.js' ? 'application/javascript' : 'text/html');
    response.end(request.url === '/bundle.js' ? bundle.outputFiles[0].text : '<!doctype html><html><body><script src="/bundle.js"></script></body></html>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.reads = [];
      window.fixture = {state: 'SUCCEEDED_CHANGED', value: 'previous value', revision: 1};
      const identity = {profile_id: 'general', profile_revision: 1, profile_hash: 'profile-hash',
        selection_revision: 1, scope_generation: 1, branch_generation: 1};
      window.manage = async (chat, action) => {
        window.reads.push({chat, action});
        const processing = {state: window.fixture.state, round_id: 'round-a',
          evaluation_revision: window.fixture.revision};
        if (action === 'STATUS') return {state: 'READY', mode: 'NORMAL', active_count: 0, pinned_count: 0,
          integration: {adapter: 'chat-memory-curator-redesign-phase4'}, profile: {profile_id: 'general', revision: 1, profile_hash: 'profile-hash'},
          profile_selection_revision: 1, scope_generation: 1, branch_generation: 1, processing};
        if (action === 'PROFILE_STATE' && window.fixture.failReads > 0) { window.fixture.failReads--; throw new Error('synthetic read failure'); }
        if (action === 'PROFILE_STATE') return {state: 'READY', ...identity, processing,
          nodes: [{kind: 'ITEM', node_id: 'field', field_id: 'field', label: 'Current value', status: 'ESTABLISHED', value: window.fixture.value}]};
        throw new Error(`Unexpected action ${action}`);
      };
    });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.locator('button[aria-label="Dissipative Memory"]').click();
    await page.getByText('Dissipative Memory unavailable', {exact: true}).waitFor();
    await page.evaluate(() => window.control.$set({chatId:'chat-a'}));
    await page.locator('[data-profile-state-field="field"]').getByText('previous value', {exact: true}).waitFor({timeout: 2500});
    await page.evaluate(() => {
      window.fixture = {state: 'SUCCEEDED_CHANGED', value: 'committed value', revision: 2};
      window.dispatchEvent(new CustomEvent('chat-memory:evaluated', {detail: {
        chat_id: 'chat-a', evaluation_revision: 2, event_version: 2, phase: 'TERMINAL',
        scope_generation: 1, branch_generation: 1, disposition: 'COMMITTED'}}));
    });
    await page.locator('[data-profile-state-field="field"]').getByText('committed value', {exact: true}).waitFor({timeout: 2500});
    const before = await page.evaluate(() => window.reads.filter(x => x.action === 'PROFILE_STATE').length);
    for (const [revision, phase, state, label] of [[3, 'QUEUED', 'WAITING', 'Waiting'], [4, 'RUNNING', 'PROCESSING', 'Processing']]) {
      await page.evaluate(({revision, phase, state}) => {
        window.fixture = {state, value: 'uncommitted value', revision};
        window.dispatchEvent(new CustomEvent('chat-memory:evaluated', {detail: {
          chat_id: 'chat-a', evaluation_revision: revision, event_version: 2, phase,
          scope_generation: 1, branch_generation: 1, disposition: state}}));
      }, {revision, phase, state});
      await page.locator('[data-testid="profile-evaluation-status"]').filter({hasText: label}).waitFor({timeout: 2500});
      assert.match(await page.locator('[data-profile-state-field="field"]').innerText(), /committed value/);
    }
    assert.equal(await page.evaluate(() => window.reads.filter(x => x.action === 'PROFILE_STATE').length), before);
    // Failure is a terminal status, never permission to replace last committed values.
    await page.evaluate(() => {
      window.fixture = {state: 'FAILED', value: 'failed proposal', revision: 5};
      window.dispatchEvent(new CustomEvent('chat-memory:evaluated', {detail: {chat_id: 'chat-a', evaluation_revision: 5}}));
    });
    await page.locator('[data-testid="profile-evaluation-status"]').filter({hasText: 'Failed'}).waitFor();
    assert.match(await page.locator('[data-profile-state-field="field"]').innerText(), /committed value/);
    assert.equal(await page.evaluate(() => window.reads.filter(x => x.action === 'PROFILE_STATE').length), before);
    // A failed read cannot consume the success revision; bounded read recovery applies the result.
    await page.evaluate(() => {
      window.fixture = {state: 'SUCCEEDED_UNCHANGED', value: 'recovered value', revision: 6, failReads: 1};
      window.dispatchEvent(new CustomEvent('chat-memory:evaluated', {detail: {chat_id: 'chat-a', evaluation_revision: 6}}));
    });
    await page.locator('[data-profile-state-field="field"]').getByText('recovered value', {exact: true}).waitFor();
    await page.waitForTimeout(50);
    const stable = await page.evaluate(() => window.reads.length);
    await page.evaluate(() => {
      for (const [chat_id, evaluation_revision] of [['chat-a', 6], ['chat-a', 3], ['other-chat', 999]]) {
        window.dispatchEvent(new CustomEvent('chat-memory:evaluated', {detail: {chat_id, evaluation_revision}}));
      }
    });
    await page.waitForTimeout(4300);
    assert.equal(await page.evaluate(() => window.reads.length), stable, 'No duplicate/stale/other-chat reads or four-second poll');
    // A lost completion is recovered by the existing socket's reconnect event.
    await page.evaluate(() => {
      window.fixture = {state: 'SUCCEEDED_CHANGED', value: 'reconnected value', revision: 7};
      window.dispatchEvent(new CustomEvent('chat-memory:reconnected'));
    });
    await page.locator('[data-profile-state-field="field"]').getByText('reconnected value', {exact: true}).waitFor();
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({result: 'PASS', draftScopeTransition: true, completionRefresh: true, queuedAndRunningVisible: true, profileRetainedDuringEvaluation: true, failedValuesRetained: true, failedReadRecovered: true, duplicateAndStaleIgnored: true, noPolling: true, reconnectReconciled: true}));
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
run().catch(error => {console.error(error.message); process.exitCode = 1;});
