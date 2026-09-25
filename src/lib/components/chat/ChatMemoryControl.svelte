<script context="module" lang="ts">
  import { writable } from "svelte/store";

  const hudOpen = writable(false);
  const hudOwner = writable(0);
  const mountedInstances = new Set<number>();
  let nextInstanceId = 0;
</script>

<script lang="ts">
  import { get } from "svelte/store";
  import { onDestroy, onMount, tick } from "svelte";
  import Tooltip from "$lib/components/common/Tooltip.svelte";
  import Wrench from "$lib/components/icons/Wrench.svelte";
  import XMark from "$lib/components/icons/XMark.svelte";
  import { manageMemory } from "$lib/apis/chat-memory";
  import ProjectionNode from "./ChatMemory/ProjectionNode.svelte";
  import ProfileStateNode from "./ChatMemory/ProfileStateNode.svelte";
  import ProfileEditor from "./ChatMemory/ProfileEditor.svelte";

  export let chatId = "";
  export let available = false;
  export let selectedToolIds: string[] = [];
  export let enabled = false;
  export let availableState = false;
  export let pending = false;
  export let stateError = "";
  // Evaluation activity; this does not assert that a send request is held.
  export let sendHold = false;

  const instanceId = ++nextInstanceId;
  let status: any = { state: "Unavailable", reason: "No chat is associated yet." };
  let view = "overview";
  let projection: any = null;
  let profileState: any = null;
  let evaluationStatus: any = null;
  let profileStateError = "";
  let inspector: any = null;
  let profiles: any[] = [];
  let curatorPreferences: any = null;
  let preferenceDraft = { recent_round_count: 1, summary_budget_units: 768 };
  let preferencePending = false;
  let preferenceDraftDirty = false;
  let editor: any = null;
  let savedIds: string[] = [];
  let validation: any = null;
  let error = "";
  let notice = "";
  let triggerElement: HTMLButtonElement;
  let memoryPanel: HTMLElement;
  let requestGeneration = 0;
  let profileReadGeneration = 0;
  let statusReadGeneration = 0;
  let scopeKey = "";
  let refreshInFlight = false;
  let refreshQueued = false;
  let queuedProfileRead = false;
  let requestedEvaluationRevision = 0;
  let refreshRetry: ReturnType<typeof setTimeout> | null = null;
  let refreshAttempts = 0;
  // Phase 5H D1: the applied evaluation revision for this scope. A push at or below it is stale
  // and is dropped, so a repeated delivery cannot cause a second fetch.
  let appliedEvaluationRevision: number | null = null;
  let unsubscribeOpen: (() => void) | null = null;
  let unsubscribeOwner: (() => void) | null = null;
  let nextScopeKey = "";
  let previousEnabledMode = "NORMAL";
  let autonomousPending = false;
  let mounted = false;

  const token = () => localStorage.token ?? "";
  const usableScope = () => available && Boolean(chatId);
  const isCurrent = (scope: string, generation: number) =>
    scope === chatId && generation === requestGeneration;
  const scopedCall = (scope: string, action: string, payload: object = {}) =>
    manageMemory(token(), scope, action, payload);

  function syncRecallTool(state: boolean) {
    const hasTool = selectedToolIds.includes("phase09_remember");
    if (state && !hasTool) selectedToolIds = [...selectedToolIds, "phase09_remember"];
    if (!state && hasTool) selectedToolIds = selectedToolIds.filter((id) => id !== "phase09_remember");
  }

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy() { if (node.parentNode) node.parentNode.removeChild(node); } };
  }

  function clearScopeState() {
    requestGeneration += 1;
    appliedEvaluationRevision = null;
    requestedEvaluationRevision = 0;
    evaluationStatus = null;
    refreshAttempts = 0;
    if (refreshRetry !== null) clearTimeout(refreshRetry);
    refreshRetry = null;
    projection = null;
    profileState = null;
    profileStateError = "";
    profileReadGeneration += 1;
    statusReadGeneration += 1;
    inspector = null;
    profiles = [];
    curatorPreferences = null;
    preferenceDraft = { recent_round_count: 1, summary_budget_units: 768 };
    preferenceDraftDirty = false;
    preferencePending = false;
    editor = null;
    savedIds = [];
    validation = null;
    error = "";
    notice = "";
    stateError = "";
    availableState = available;
    pending = Boolean(available && chatId);
    enabled = Boolean(available && !chatId && selectedToolIds.includes("phase09_remember"));
    if (!available) {
      syncRecallTool(false);
      if (get(hudOwner) === instanceId) closePanel({ restoreFocus: false });
    }
    status = !chatId
      ? { state: "Unavailable", reason: "This new chat is not associated with Memory yet." }
      : !available
        ? { state: "Unavailable", reason: "The selected model does not support Chat Memory." }
        : { state: "Loading" };
    sendHold = false;
  }

  function closePanel({ restoreFocus = true } = {}) {
    hudOpen.set(false);
    if (restoreFocus) tick().then(() => triggerElement?.isConnected && triggerElement.focus());
  }

  function handlePanelKeyDown(event: KeyboardEvent) {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    if (!memoryPanel?.contains(document.activeElement)) return;
    event.stopPropagation();
    closePanel();
  }

  async function refreshStatus({ background = false } = {}) {
    if (!usableScope()) return;
    const scope = chatId;
    const generation = requestGeneration;
    const readGeneration = ++statusReadGeneration;
    const previousStatus = status;
    if (!background) status = { state: "Loading" };
    try {
      const result = await scopedCall(scope, "STATUS");
      if (!isCurrent(scope, generation) || readGeneration !== statusReadGeneration) return;
      if (result.state === "READY" && result.integration?.adapter !== "chat-memory-curator-redesign-phase4") {
        status = { state: "INCOMPATIBLE", reason: "Chat Memory Core and Adapter versions do not match." };
        availableState = false;
        enabled = false;
        pending = false;
        return;
      }
      status = result;
      evaluationStatus = result.processing ?? null;
      if (result.state === "READY") {
        // Display evaluation activity independently of the backend send policy.
        sendHold = ["WAITING", "REEVALUATING", "PROCESSING"].includes(result.processing?.state ?? "");
        const authoritativeIdentityChanged = previousStatus?.state === "READY"
          && !statusIdentityMatches(previousStatus, result);
        const cachedIdentityIsIneligible = profileState !== null
          && !profileIdentityMatchesStatus(profileState, result);
        if (authoritativeIdentityChanged || cachedIdentityIsIneligible) {
          profileState = null;
          profileStateError = "";
          profileReadGeneration += 1;
        }
        availableState = true;
        enabled = result.mode !== "OFF";
        previousEnabledMode = ["NORMAL", "READ_ONLY"].includes(result.client_previous_enabled_mode)
          ? result.client_previous_enabled_mode
          : result.mode === "READ_ONLY" ? "READ_ONLY" : "NORMAL";
        syncRecallTool(enabled);
        if (!enabled && get(hudOwner) === instanceId) closePanel({ restoreFocus: false });
      } else {
        availableState = false;
        enabled = false;
        sendHold = false;
        syncRecallTool(false);
        if (get(hudOwner) === instanceId) closePanel({ restoreFocus: false });
      }
      pending = false;
      stateError = "";
      error = "";
      return result.state === "READY";
    } catch (e) {
      if (!isCurrent(scope, generation) || readGeneration !== statusReadGeneration) return;
      status = { state: "Unavailable", reason: "Memory service unavailable." };
      error = "Memory service unavailable";
      stateError = "Chat Memory status is unavailable";
      pending = false;
      // An unreachable Core holds nothing: the backend skips the wait rather than blocking the send.
      sendHold = false;
    }
  }

  function statusIdentityMatches(left: any, right: any) {
    return left?.profile?.profile_id === right?.profile?.profile_id
      && left?.profile?.revision === right?.profile?.revision
      && left?.profile?.profile_hash === right?.profile?.profile_hash
      && left?.profile_selection_revision === right?.profile_selection_revision
      && left?.scope_generation === right?.scope_generation
      && left?.branch_generation === right?.branch_generation;
  }

  function profileIdentityMatchesStatus(candidate: any, authoritativeStatus: any) {
    return candidate?.profile_id === authoritativeStatus?.profile?.profile_id
      && candidate?.profile_revision === authoritativeStatus?.profile?.revision
      && candidate?.profile_hash === authoritativeStatus?.profile?.profile_hash
      && candidate?.selection_revision === authoritativeStatus?.profile_selection_revision
      && candidate?.scope_generation === authoritativeStatus?.scope_generation
      && candidate?.branch_generation === authoritativeStatus?.branch_generation;
  }

  async function refreshVisibleRead({ forcePreferenceDraft = false } = {}) {
    if (!usableScope() || editor) return;
    const scope = chatId;
    const generation = requestGeneration;
    try {
      if (view === "active") {
        const result = await scopedCall(scope, "TRACKER_PROJECTION");
        if (isCurrent(scope, generation)) projection = result;
      } else if (view === "inspector") {
        const page = inspector?.page ?? 1;
        const includeHistory = inspector?.include_history ?? false;
        const result = await scopedCall(scope, "INSPECT_PAGE", { page, page_size: 25, include_history: includeHistory });
        if (isCurrent(scope, generation)) inspector = result;
      } else if (view === "profiles") {
        const result = await scopedCall(scope, "PROFILE_LIST");
        if (isCurrent(scope, generation)) profiles = result.profiles;
      } else if (view === "settings") {
        const result = await scopedCall(scope, "CURATOR_PREFERENCES_GET");
        if (isCurrent(scope, generation)) {
          curatorPreferences = result;
          if (forcePreferenceDraft || !preferenceDraftDirty) {
            preferenceDraft = { ...result.effective };
            preferenceDraftDirty = false;
          }
        }
      }
    } catch (e: any) {
      if (isCurrent(scope, generation)) error = e?.detail ?? "Memory operation failed";
    }
  }

  async function refreshProfileState() {
    if (!usableScope() || status.state !== "READY") return;
    const scope = chatId;
    const generation = requestGeneration;
    const readGeneration = ++profileReadGeneration;
    const expectedStatus = status;
    try {
      const result = await scopedCall(scope, "PROFILE_STATE");
      if (!isCurrent(scope, generation) || readGeneration !== profileReadGeneration) return;
      if (!profileIdentityMatchesStatus(result, expectedStatus)) return;
      if (!profileIdentityMatchesStatus(result, status)) return;
      profileState = result;
      profileStateError = "";
      return true;
    } catch (e: any) {
      if (isCurrent(scope, generation) && readGeneration === profileReadGeneration) {
        profileStateError = e?.detail ?? "Profile State is unavailable";
      }
    }
  }

  // Failed reads never consume the pushed revision. Retries are bounded per notification.
  async function refreshHud({ background = false, profile = true } = {}) {
    if (!usableScope()) return;
    if (refreshInFlight) {
      refreshQueued = true;
      queuedProfileRead ||= profile;
      return;
    }
    const generation = requestGeneration;
    refreshInFlight = true;
    let succeeded = false;
    try {
      const ready = await refreshStatus({ background });
      if (!ready || generation !== requestGeneration) return;
      const terminalSuccess = ["SUCCEEDED_CHANGED", "SUCCEEDED_UNCHANGED"].includes(evaluationStatus?.state);
      const openHere = get(hudOpen) && get(hudOwner) === instanceId;
      const needsCommittedValues = openHere && terminalSuccess
        && (profileState?.processing?.evaluation_revision ?? -1) < (evaluationStatus?.evaluation_revision ?? 0);
      const profileApplied = !(profile || needsCommittedValues) || await refreshProfileState();
      if (profile || needsCommittedValues) await refreshVisibleRead();
      if (generation !== requestGeneration || !profileApplied) return;
      const readRevision = evaluationStatus?.evaluation_revision;
      if (typeof readRevision === "number" && readRevision >= requestedEvaluationRevision) {
        appliedEvaluationRevision = Math.max(appliedEvaluationRevision ?? 0, readRevision);
        succeeded = true;
      } else if (requestedEvaluationRevision === 0) succeeded = true;
    } finally {
      refreshInFlight = false;
      if (generation === requestGeneration) {
        if (succeeded) {
          refreshAttempts = 0;
          if (refreshRetry !== null) clearTimeout(refreshRetry);
          refreshRetry = null;
        } else if (requestedEvaluationRevision > (appliedEvaluationRevision ?? 0) && refreshAttempts < 3 && refreshRetry === null) {
          refreshRetry = setTimeout(() => {
            refreshRetry = null;
            refreshHud({ background: true, profile: false });
          }, 250 * 2 ** refreshAttempts++);
        }
      }
      if (refreshQueued) {
        const profile = queuedProfileRead;
        refreshQueued = false;
        queuedProfileRead = false;
        refreshHud({ background: true, profile });
      }
    }
  }

  type EvaluationPush = {
    chat_id: string;
    evaluation_revision: number;
    event_version?: number;
    phase?: "QUEUED" | "RUNNING" | "TERMINAL";
    scope_generation?: number;
    branch_generation?: number;
  };

  function handleEvaluationPush(event: Event) {
    const payload = (event as CustomEvent<EvaluationPush>).detail;
    if (!payload || String(payload.chat_id ?? "") !== chatId) return;
    const revision = payload.evaluation_revision;
    if (!Number.isSafeInteger(revision) || revision <= 0) return;
    if (appliedEvaluationRevision !== null && revision <= appliedEvaluationRevision) return;
    if (typeof payload.scope_generation === "number" && payload.scope_generation < (status.scope_generation ?? 0)) return;
    if (payload.scope_generation === status.scope_generation && typeof payload.branch_generation === "number"
      && payload.branch_generation < (status.branch_generation ?? 0)) return;
    requestedEvaluationRevision = Math.max(requestedEvaluationRevision, revision);
    refreshAttempts = 0;
    refreshHud({ background: true, profile: false });
  }

  function handleReconnect() {
    refreshHud({ background: true, profile: get(hudOpen) && get(hudOwner) === instanceId });
  }

  function handleVisibilityChange() {
    if (!document.hidden && get(hudOpen) && get(hudOwner) === instanceId) {
      refreshHud({ background: true });
    }
  }

  function handleMemoryChanged() {
    if (get(hudOpen) && get(hudOwner) === instanceId) refreshHud({ background: true });
  }

  async function togglePanel() {
    if (get(hudOpen) && get(hudOwner) === instanceId) {
      closePanel();
      return;
    }
    hudOwner.set(instanceId);
    hudOpen.set(true);
    notice = "";
    await refreshHud();
    await tick();
    memoryPanel?.focus();
  }

  async function setMode(mode: string) {
    if (!usableScope() || status.state !== "READY") return;
    const scope = chatId;
    const generation = requestGeneration;
    const revision = status.config_revision;
    notice = "";
    pending = true;
    stateError = "";
    try {
      const result = await scopedCall(scope, "SET_MODE", { mode, base_revision: revision });
      if (!isCurrent(scope, generation)) return;
      if (result.state !== "MODE_UPDATED" || result.mode !== mode) throw new Error("Mode update was not accepted");
      window.dispatchEvent(new CustomEvent("chat-memory:changed"));
      await refreshStatus();
    } catch (e) {
      if (!isCurrent(scope, generation)) return;
      pending = false;
      await refreshStatus();
      if (!isCurrent(scope, generation)) return;
      error = "Mode update failed";
      stateError = "Chat Memory mode update failed";
    }
  }

  async function setAutonomousWriting(enabled: boolean) {
    if (!usableScope() || status.state !== "READY" || autonomousPending) return;
    const scope = chatId;
    const generation = requestGeneration;
    autonomousPending = true;
    error = "";
    try {
      const result = await scopedCall(scope, "SET_AUTONOMOUS_WRITING", {
        enabled,
        base_revision: status.config_revision,
      });
      if (!isCurrent(scope, generation)) return;
      if (result.state !== "AUTONOMOUS_WRITING_UPDATED" || result.autonomous_writing_enabled !== enabled) {
        throw new Error("Autonomous writing update was not accepted");
      }
      await refreshStatus();
      if (isCurrent(scope, generation)) window.dispatchEvent(new CustomEvent("chat-memory:changed"));
    } catch (e: any) {
      if (!isCurrent(scope, generation)) return;
      error = e?.detail ?? "Autonomous memory writing update failed";
      await refreshStatus();
    } finally {
      if (isCurrent(scope, generation)) autonomousPending = false;
    }
  }

  async function saveCuratorPreferences(target: "user" | "chat") {
    if (!usableScope() || !curatorPreferences || preferencePending) return;
    const scope = chatId;
    const generation = requestGeneration;
    preferencePending = true;
    error = "";
    try {
      const action = target === "user" ? "SET_CURATOR_USER_DEFAULTS" : "SET_CURATOR_CHAT_OVERRIDE";
      const base_revision = target === "user"
        ? curatorPreferences.user_defaults.revision
        : curatorPreferences.chat_config_revision;
      await scopedCall(scope, action, {
        recent_round_count: Number(preferenceDraft.recent_round_count),
        summary_budget_units: Number(preferenceDraft.summary_budget_units),
        base_revision,
      });
      if (!isCurrent(scope, generation)) return;
      await refreshVisibleRead({ forcePreferenceDraft: true });
      if (!isCurrent(scope, generation)) return;
      notice = target === "user" ? "User Curator defaults saved." : "This chat now overrides your defaults.";
    } catch (e: any) {
      if (!isCurrent(scope, generation)) return;
      await refreshVisibleRead({ forcePreferenceDraft: true });
      if (!isCurrent(scope, generation)) return;
      error = e?.detail ?? "Curator preference update conflicted; authoritative values were reloaded.";
    } finally {
      if (isCurrent(scope, generation)) preferencePending = false;
    }
  }

  async function resetCuratorOverride() {
    if (!usableScope() || !curatorPreferences?.chat_override || preferencePending) return;
    const scope = chatId;
    const generation = requestGeneration;
    preferencePending = true;
    try {
      await scopedCall(scope, "RESET_CURATOR_CHAT_OVERRIDE", { base_revision: curatorPreferences.chat_config_revision });
      if (!isCurrent(scope, generation)) return;
      await refreshVisibleRead({ forcePreferenceDraft: true });
      if (!isCurrent(scope, generation)) return;
      notice = "This chat now inherits your user defaults.";
    } catch (e: any) {
      if (!isCurrent(scope, generation)) return;
      await refreshVisibleRead({ forcePreferenceDraft: true });
      if (!isCurrent(scope, generation)) return;
      error = e?.detail ?? "Curator preference reset conflicted; authoritative values were reloaded.";
    } finally {
      if (isCurrent(scope, generation)) preferencePending = false;
    }
  }

  export async function setEnabled(state: boolean) {
    if (!availableState || pending) return;
    stateError = "";
    if (!chatId) {
      enabled = state;
      syncRecallTool(state);
      if (!state && get(hudOwner) === instanceId) closePanel({ restoreFocus: false });
      window.dispatchEvent(new CustomEvent("chat-memory:changed"));
      return;
    }
    await setMode(state ? previousEnabledMode : "OFF");
  }

  async function show(name: string) {
    view = name;
    editor = null;
    error = "";
    notice = "";
    if (!usableScope() || name === "overview") return;
    await refreshVisibleRead();
  }

  async function inspectorPage(page: number) {
    if (!usableScope()) return;
    const scope = chatId;
    const generation = requestGeneration;
    const includeHistory = inspector?.include_history ?? false;
    const result = await scopedCall(scope, "INSPECT_PAGE", { page, page_size: 25, include_history: includeHistory });
    if (isCurrent(scope, generation)) inspector = result;
  }

  async function toggleHistory() {
    if (!usableScope()) return;
    const scope = chatId;
    const generation = requestGeneration;
    const result = await scopedCall(scope, "INSPECT_PAGE", { page: 1, page_size: 25, include_history: !inspector?.include_history });
    if (isCurrent(scope, generation)) inspector = result;
  }

  async function command(action: string, item: any) {
    if (!usableScope()) return;
    if (["FORGET", "REDACT"].includes(action) && !confirm(`Confirm ${action.toLowerCase()} for this memory?`)) return;
    const scope = chatId;
    const generation = requestGeneration;
    const target = { ...item };
    const semanticRevision = inspector?.semantic_revision;
    const payload: any = {
      target_id: target.item_id,
      base_revision: semanticRevision,
      command_id: crypto.randomUUID(),
    };
    if (["EDIT", "CORRECT"].includes(action)) {
      const assertion = prompt("Correct memory text", target.semantic_content);
      if (!assertion) return;
      payload.assertion = assertion;
    }
    try {
      const result = await scopedCall(scope, action, payload);
      if (!isCurrent(scope, generation)) return;
      if (action === "WHY_REMEMBERED") {
        inspector = { ...inspector, items: inspector.items.map((value: any) => value.revision_id === target.revision_id ? { ...value, why: result } : value) };
        return;
      }
      window.dispatchEvent(new CustomEvent("chat-memory:changed"));
      await refreshHud();
    } catch (e: any) {
      if (isCurrent(scope, generation)) error = e?.detail ?? "Memory operation failed";
    }
  }

  const blank = () => ({
    spec_version: 1,
    profile_id: "my-profile",
    display_name: "My Profile",
    purpose: "Custom observation plan.",
    global_guidance: "Observe supported continuity.",
    nodes: [],
  });
  const flatten = (nodes: any[]): any[] => nodes.flatMap((node) => [node, ...flatten(node.children ?? [])]);

  async function editProfile(profile: any) {
    if (!usableScope()) return;
    const scope = chatId;
    const generation = requestGeneration;
    notice = "";
    try {
      let selected = profile;
      if (selected.builtin) {
        const id = `my-${selected.profile_id}`;
        const result = await scopedCall(scope, "PROFILE_DUPLICATE", {
          source_id: selected.profile_id,
          target_id: id,
          display_name: `${selected.display_name} Copy`,
        });
        if (!isCurrent(scope, generation)) return;
        selected = { ...result, builtin: false };
      }
      const value = await scopedCall(scope, "PROFILE_GET", { profile_id: selected.profile_id, revision: selected.revision });
      if (!isCurrent(scope, generation)) return;
      editor = value.canonical;
      savedIds = flatten(editor.nodes).map((item: any) => item.id);
      validation = null;
    } catch (e: any) {
      if (isCurrent(scope, generation)) error = e?.detail ?? "Profile could not be opened";
    }
  }

  async function preview(event: any) {
    if (!usableScope()) return;
    const scope = chatId;
    const generation = requestGeneration;
    try {
      const result = await scopedCall(scope, "PROFILE_PREVIEW", { draft: event.detail, revision: (editor?.revision ?? 0) + 1 });
      if (!isCurrent(scope, generation)) return;
      validation = result;
      error = "";
    } catch (e: any) {
      if (isCurrent(scope, generation)) error = e?.detail ?? "Profile validation failed";
    }
  }

  async function save(event: any) {
    if (!usableScope()) return;
    const scope = chatId;
    const generation = requestGeneration;
    try {
      const validated = await scopedCall(scope, "PROFILE_PREVIEW", { draft: event.detail, revision: (editor?.revision ?? 0) + 1 });
      if (!isCurrent(scope, generation)) return;
      validation = validated;
      if (savedIds.length) await scopedCall(scope, "PROFILE_REVISE", { profile_id: event.detail.profile_id, draft: event.detail });
      else await scopedCall(scope, "PROFILE_CREATE", { draft: event.detail });
      if (!isCurrent(scope, generation)) return;
      editor = null;
      notice = "Profile saved as an immutable revision.";
      window.dispatchEvent(new CustomEvent("chat-memory:changed"));
      await refreshHud();
    } catch (e: any) {
      if (isCurrent(scope, generation)) error = e?.detail ?? "Profile save failed";
    }
  }

  async function selectProfile(profile: any) {
    if (!usableScope()) return;
    const scope = chatId;
    const generation = requestGeneration;
    error = "";
    notice = "";
    try {
      await scopedCall(scope, "PROFILE_SELECT", { profile_id: profile.profile_id, revision: profile.revision });
      if (!isCurrent(scope, generation)) return;
      profileState = null;
      profileReadGeneration += 1;
      await refreshHud();
      if (!isCurrent(scope, generation) || status.profile?.profile_id !== profile.profile_id || status.profile?.revision !== profile.revision) return;
      notice = `${profile.display_name} is now used by this chat.`;
      window.dispatchEvent(new CustomEvent("chat-memory:changed"));
    } catch (e: any) {
      if (!isCurrent(scope, generation)) return;
      error = e?.detail ?? "Profile selection failed";
      await refreshHud();
    }
  }

  async function deleteProfile(profile: any) {
    if (!usableScope() || profile.builtin) return;
    const scope = chatId;
    const generation = requestGeneration;
    const target = { ...profile };
    const impact = `Delete Profile “${target.display_name}”?\n\nAll of its versions will disappear from normal Profile lists. Chats using it will fall back to General. Accepted-round policy history and existing memory/archive data will be retained.`;
    if (!confirm(impact)) return;
    error = "";
    notice = "";
    try {
      const result = await scopedCall(scope, "PROFILE_DELETE", { profile_id: target.profile_id });
      if (!isCurrent(scope, generation)) return;
      await refreshHud();
      if (!isCurrent(scope, generation)) return;
      notice = `${target.display_name} deleted. ${result.fallback_chats} chat${result.fallback_chats === 1 ? "" : "s"} moved to General.`;
      window.dispatchEvent(new CustomEvent("chat-memory:changed"));
    } catch (e: any) {
      if (!isCurrent(scope, generation)) return;
      error = e?.detail ?? "Profile deletion failed";
      await refreshHud();
    }
  }

  onMount(() => {
    mounted = true;
    mountedInstances.add(instanceId);
    if (get(hudOpen) && !mountedInstances.has(get(hudOwner))) hudOwner.set(instanceId);
    unsubscribeOpen = hudOpen.subscribe(() => {});
    unsubscribeOwner = hudOwner.subscribe((owner) => {
      if (owner === instanceId && get(hudOpen)) {
        clearScopeState();
        refreshHud();
      }
    });
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("chat-memory:changed", handleMemoryChanged);
    window.addEventListener("chat-memory:evaluated", handleEvaluationPush);
    window.addEventListener("chat-memory:reconnected", handleReconnect);
    if (usableScope() && !(get(hudOpen) && get(hudOwner) === instanceId)) refreshStatus();
  });

  onDestroy(() => {
    mounted = false;
    requestGeneration += 1;
    unsubscribeOpen?.();
    unsubscribeOwner?.();
    document.removeEventListener("visibilitychange", handleVisibilityChange);
    window.removeEventListener("chat-memory:changed", handleMemoryChanged);
    window.removeEventListener("chat-memory:evaluated", handleEvaluationPush);
    window.removeEventListener("chat-memory:reconnected", handleReconnect);
    if (refreshRetry !== null) clearTimeout(refreshRetry);
    mountedInstances.delete(instanceId);
    if (get(hudOwner) === instanceId) {
      hudOwner.set(Array.from(mountedInstances).at(-1) ?? 0);
    }
  });

  $: nextScopeKey = `${chatId}|${available}`;
  $: if (nextScopeKey !== scopeKey) {
    scopeKey = nextScopeKey;
    appliedEvaluationRevision = null;
    clearScopeState();
    if (mounted) {
      if (get(hudOpen) && get(hudOwner) === instanceId) refreshHud();
      else if (usableScope()) refreshStatus();
    }
  }

  $: if (!chatId && availableState && !pending) {
    enabled = selectedToolIds.includes("phase09_remember");
  }

  const modeLabel = (mode: string) => mode === "NORMAL" ? "On" : mode === "READ_ONLY" ? "Read only" : mode === "OFF" ? "Off" : mode;
  const evaluationText = (processing: any) => {
    const state = processing?.state ?? "NEVER_EVALUATED";
    const labels: Record<string, string> = {
      WAITING: "Waiting for its turn · showing last successful values",
      REEVALUATING: "Reevaluating message…",
      PROCESSING: "Processing this round · showing last successful values",
      SUCCEEDED_CHANGED: "Complete · Profile values changed",
      SUCCEEDED_UNCHANGED: "Complete · Profile values unchanged",
      FAILED: "Failed · last successful values retained",
      EXPIRED: "Skipped after queue expiry · coverage gap recorded",
      TIMED_OUT: "Timed out · coverage gap recorded",
      SKIPPED: "Skipped · coverage gap recorded",
      OBSOLETE: "Superseded by a newer branch",
      SUPERSEDED: "Evaluated earlier, then superseded by an edit or continuation · nothing to evaluate on this branch",
      NEVER_EVALUATED: "Not evaluated yet",
    };
    return labels[state] ?? state;
  };
  $: headerStatus = status.state === "READY"
    ? `${modeLabel(status.mode)} · ${status.active_count} active · ${status.pinned_count} pinned`
    : status.state === "Loading" ? "Loading current chat…" : status.reason ?? status.state;
</script>

{#if enabled && availableState}
  <div class="group ml-1 flex shrink-0 items-center rounded-full border border-sky-200/40 bg-sky-50 text-sky-500 dark:border-sky-500/20 dark:bg-sky-400/10 dark:text-sky-300 ops-composer-control ops-composer-control--active" data-testid="chat-memory-control">
    {#if sendHold}
      <!-- Display-only evaluation activity. -->
      <span class="px-2 text-[11px] leading-none ops-muted" data-testid="chat-memory-send-hold" role="status" aria-live="polite">Recording Facts…</span>
    {/if}
    <Tooltip content="Chat Memory" placement="top">
      <button
        bind:this={triggerElement}
        type="button"
        class="flex items-center self-center rounded-full p-[0.375rem] focus:outline-hidden"
        aria-label="Chat Memory"
        aria-haspopup="dialog"
        aria-expanded={$hudOpen && $hudOwner === instanceId}
        aria-controls="chat-memory-panel"
        on:click={togglePanel}
      >
        <Wrench className="size-4" strokeWidth="1.75" />
      </button>
    </Tooltip>
    <Tooltip content="Disable Chat Memory" placement="top">
      <button
        type="button"
        class="hidden items-center justify-center rounded-full py-[0.375rem] pr-[0.375rem] leading-none focus:flex focus:outline-hidden group-hover:flex group-focus-within:flex"
        aria-label="Disable Chat Memory"
        disabled={pending}
        on:click|stopPropagation={() => setEnabled(false)}
      >
        <XMark className="size-4" strokeWidth="1.75" />
      </button>
    </Tooltip>
  </div>
{/if}

{#if $hudOpen && $hudOwner === instanceId}
  <div
    use:portal
    bind:this={memoryPanel}
    id="chat-memory-panel"
    data-testid="chat-memory-panel"
    class="ops-memory-hud fixed right-3 top-1/2 z-[9998] m-0 flex max-h-[calc(100vh-24px)] w-[min(384px,calc(100vw-24px))] -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white p-0 text-gray-900 shadow-2xl dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
    role="dialog"
    aria-modal="false"
    aria-label="Chat Memory settings and status"
    tabindex="-1"
    on:keydown={handlePanelKeyDown}
  >
    <header class="ops-memory-hud__header flex shrink-0 items-start justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
      <div class="min-w-0 pr-2">
        <h2 class="text-sm font-semibold">Chat Memory</h2>
        <p class="ops-muted mt-0.5 text-xs" data-testid="chat-memory-status">{headerStatus}</p>
      </div>
      <button type="button" aria-label="Close Chat Memory" class="ops-memory-action rounded-lg px-2 py-1 focus:outline-hidden" on:click={() => closePanel()}>✕</button>
    </header>

    <div class="min-h-0 overflow-y-auto p-3">
      {#if view !== "overview"}
        <button type="button" class="mb-3 rounded-lg px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 focus:outline-hidden dark:text-gray-300 dark:hover:bg-gray-800" on:click={() => show("overview")}>← Overview</button>
      {/if}

      {#if error}<div class="ops-memory-alert ops-memory-alert--danger mb-2 rounded-lg p-2 text-sm" role="alert">{error}</div>{/if}
      {#if notice}<div class="ops-memory-alert ops-memory-alert--positive mb-2 rounded-lg p-2 text-sm" role="status">{notice}</div>{/if}

      {#if !(available && chatId)}
        <div class="ops-memory-alert ops-memory-alert--warning rounded-xl border p-3 text-sm" role="status">
          <strong class="block">Chat Memory unavailable</strong>
          <span>{status.reason}</span>
        </div>
      {:else if status.state === "Loading"}
        <div class="rounded-xl border border-gray-200 p-3 text-sm text-gray-500 dark:border-gray-700">Loading current chat…</div>
      {:else if view === "overview"}
        {#if status.observation?.state === "FAILED"}
          <div class="ops-memory-alert ops-memory-alert--warning mb-3 rounded-xl border p-3 text-sm" role="status" data-testid="chat-memory-observation-warning">
            <strong class="block">Latest response was not recorded</strong>
            <span>Profile State may be out of date ({status.observation.error_class ?? "INTERNAL_ERROR"}).</span>
          </div>
        {/if}
        <div class="mb-3">
          <div class="mb-1 px-1 text-xs font-medium text-gray-500">Access mode</div>
          <div class="grid grid-cols-3 gap-1">
            {#each [["NORMAL", "On"], ["READ_ONLY", "Read only"], ["OFF", "Off"]] as option}
              <button type="button" disabled={status.state !== "READY"} class="ops-memory-mode rounded-lg border px-2 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-40 {status.mode === option[0] ? 'ops-memory-mode--selected' : ''}" aria-pressed={status.state === "READY" && status.mode === option[0]} on:click={() => setMode(option[0])}>{option[1]}</button>
            {/each}
          </div>
        </div>
        <section class="mb-3 flex items-center justify-between gap-3 rounded-xl border border-gray-200 p-3 dark:border-gray-700" data-testid="autonomous-writing-control">
          <div class="min-w-0">
            <h3 class="text-sm font-semibold">Autonomous long-term memory</h3>
            <p class="text-xs ops-muted">Allow future completed rounds to create or revise durable memories. Existing memory and Profile tracking remain available.</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-label="Autonomous long-term memory writing"
            aria-checked={Boolean(status.autonomous_writing_enabled)}
            disabled={status.state !== "READY" || autonomousPending}
            class="ops-memory-mode min-w-[3.25rem] shrink-0 rounded-lg border px-2 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-40 {status.autonomous_writing_enabled ? 'ops-memory-mode--selected' : ''}"
            on:click={() => setAutonomousWriting(!status.autonomous_writing_enabled)}
          >{autonomousPending ? "Saving…" : status.autonomous_writing_enabled ? "On" : "Off"}</button>
        </section>
        <section class="mb-3 border-t border-gray-200 pt-3 dark:border-gray-700" data-testid="chat-memory-profile-state">
          <div class="mb-2 flex items-start justify-between gap-2 px-1">
            <div>
              <h3 class="text-sm font-semibold">Profile State</h3>
              <p class="text-xs ops-muted">{status.profile?.display_name ?? "Current Profile"}</p>
            </div>
            {#if evaluationStatus}
              <span class="max-w-[58%] text-right text-[11px] ops-muted" data-testid="profile-evaluation-status">{evaluationText(evaluationStatus)}</span>
            {/if}
          </div>
          {#if profileStateError}
            <div class="ops-memory-alert ops-memory-alert--warning mb-2 rounded-lg p-2 text-xs" role="status">{profileStateError}. Last loaded values are retained.</div>
          {/if}
          {#if profileState}
            <div data-profile-id={profileState.profile_id} data-profile-revision={profileState.profile_revision} data-selection-revision={profileState.selection_revision}>
              {#each profileState.nodes ?? [] as node (node.node_id)}
                <ProfileStateNode {node} />
              {/each}
            </div>
            {#if evaluationStatus?.last_successful_round_id}
              <p class="mt-2 px-1 text-[11px] ops-muted">Last successful round: {evaluationStatus.last_successful_round_id}</p>
            {/if}
            {#if evaluationStatus?.coverage_gaps?.length}
              <details class="mt-2 rounded-lg border border-amber-300/60 p-2 text-xs" data-testid="profile-coverage-gaps">
                <summary>{evaluationStatus.coverage_gaps.length} processing coverage gap(s)</summary>
                {#each evaluationStatus.coverage_gaps as gap}
                  <p class="mt-1 break-words">{gap.round_id}: {gap.error_class ?? gap.state}</p>
                {/each}
              </details>
            {/if}
          {:else}
            <div class="rounded-xl border border-gray-200 p-3 text-sm ops-muted dark:border-gray-700">Loading Profile State…</div>
          {/if}
        </section>
        <div class="space-y-1 border-t border-gray-200 pt-2 dark:border-gray-700">
          <button type="button" disabled={status.state !== "READY"} class="w-full rounded-lg px-2 py-2 text-left text-sm hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-800" on:click={() => show("profiles")}><span class="block text-xs text-gray-500">Current Profile</span>{status.state === "READY" ? status.profile?.display_name : "Unavailable"}</button>
          <button type="button" disabled={status.state !== "READY"} class="w-full rounded-lg px-2 py-2 text-left text-sm hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-800" on:click={() => show("active")}>View Active Memory</button>
          <button type="button" disabled={status.state !== "READY"} class="w-full rounded-lg px-2 py-2 text-left text-sm hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-800" on:click={() => show("inspector")}>Memory Inspector / Settings</button>
          <button type="button" disabled={status.state !== "READY"} class="w-full rounded-lg px-2 py-2 text-left text-sm hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-800" on:click={() => show("profiles")}>Profile Management</button>
          <button type="button" disabled={status.state !== "READY"} class="w-full rounded-lg px-2 py-2 text-left text-sm hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-800" on:click={() => show("settings")}>Curator context settings</button>
        </div>
      {:else if view === "active"}
        <h3 class="mb-1 font-semibold">Active Memory</h3>
        {#if projection}
          <p class="mb-2 text-sm text-gray-500">{projection.active_count} active · {projection.pinned_count} pinned {projection.overflow ? " · overflow" : ""}</p>
          {#each projection.sections as section (section.node_id)}<ProjectionNode node={section} />{/each}
        {:else}<p class="text-sm text-gray-500">Loading active memory…</p>{/if}
      {:else if view === "inspector"}
        <h3 class="mb-2 font-semibold">Memory Inspector / Settings</h3>
        {#if inspector}
          <div class="mb-2 flex flex-wrap items-center justify-between gap-2 text-sm">
            <span>{inspector.total} current items · page {inspector.page}</span>
            <div class="flex gap-1">
              <button type="button" class="rounded border px-2 py-1" disabled={inspector.page <= 1} on:click={() => inspectorPage(inspector.page - 1)}>Previous</button>
              <button type="button" class="rounded border px-2 py-1" disabled={inspector.page * inspector.page_size >= inspector.total} on:click={() => inspectorPage(inspector.page + 1)}>Next</button>
              <button type="button" class="rounded border px-2 py-1" on:click={toggleHistory}>{inspector.include_history ? "Hide history" : "Show history"}</button>
            </div>
          </div>
          {#each inspector.items as item (item.revision_id)}
            <article class="mb-2 rounded-xl border border-gray-200 p-3 dark:border-gray-700">
              <div class="flex justify-between gap-2"><p>{item.semantic_content ?? "[Removed]"}</p><span class="text-xs text-gray-500">{item.activity_state ?? item.currentness}</span></div>
              <div class="mt-1 text-xs text-gray-500">{item.profile_revision ?? "Unmapped"}{#if item.presentation_bindings?.length} · {item.presentation_bindings.map((binding: any) => `${binding.node_id} (${(binding.assertion_currentness ?? "CURRENT").toLowerCase()})`).join(", ")}{/if}</div>
              <div class="mt-2 flex flex-wrap gap-1 text-xs">
                <button type="button" class="rounded border px-2 py-1" on:click={() => command(item.activity_state === "PINNED" ? "UNPIN" : "PIN", item)}>{item.activity_state === "PINNED" ? "Unpin" : "Pin"}</button>
                <button type="button" class="rounded border px-2 py-1" on:click={() => command("CORRECT", item)}>Edit / Correct</button>
                <button type="button" class="rounded border border-red-300 px-2 py-1 text-red-600" on:click={() => command("FORGET", item)}>Forget</button>
                <button type="button" class="rounded border px-2 py-1" on:click={() => command("WHY_REMEMBERED", item)}>Why remembered?</button>
              </div>
              {#if item.why}<pre class="mt-2 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs dark:bg-gray-800">{JSON.stringify(item.why, null, 2)}</pre>{/if}
            </article>
          {/each}
        {:else}<p class="text-sm text-gray-500">Loading inspector…</p>{/if}
      {:else if view === "profiles"}
        <div class="mb-3 rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm dark:border-sky-500/30 dark:bg-sky-400/10"><span class="block text-xs text-gray-500">Current Profile</span><strong>{status.state === "READY" ? status.profile?.display_name : "Unavailable"}</strong></div>
        {#if editor}
          <div class="mb-2 flex items-center justify-between gap-2"><span class="text-sm font-medium">Editing draft: {editor.display_name}</span><button type="button" class="rounded border px-2 py-1 text-sm" on:click={() => (editor = null)}>Cancel edit</button></div>
          <ProfileEditor bind:draft={editor} {savedIds} {validation} on:preview={preview} on:save={save} />
        {:else}
          <div class="mb-2 flex items-center justify-between gap-2"><h3 class="font-semibold">Profile Management</h3><button type="button" class="rounded-lg border px-3 py-1.5 text-sm" on:click={() => { editor = blank(); savedIds = []; }}>+ New custom Profile</button></div>
          {#if profiles.length === 0}<p class="text-sm text-gray-500">Loading Profiles…</p>{/if}
          {#each profiles as profile (`${profile.profile_id}@${profile.revision}`)}
            {@const selected = status.profile?.profile_id === profile.profile_id && status.profile?.revision === profile.revision}
            <div class="mb-2 rounded-xl border p-3 {selected ? 'border-sky-400 bg-sky-50 ring-1 ring-sky-300 dark:border-sky-500 dark:bg-sky-400/10 dark:ring-sky-500/40' : 'border-gray-200 dark:border-gray-700'}" aria-current={selected ? "true" : undefined}>
              <div class="flex flex-wrap items-start justify-between gap-2">
                <div class="min-w-0">
                  <div class="font-medium">{#if selected}<span aria-label="Selected Profile" class="mr-1 text-sky-600 dark:text-sky-300">✓</span>{/if}{profile.display_name} · revision {profile.revision}</div>
                  <div class="text-xs text-gray-500">{profile.builtin ? "Built-in factory preset · cannot be deleted" : "Custom"} · {profile.node_count} nodes</div>
                </div>
                <div class="flex flex-wrap gap-1">
                  <button type="button" class="rounded border px-2 py-1 text-sm" disabled={selected} on:click={() => selectProfile(profile)}>{selected ? "Selected" : "Select"}</button>
                  <button type="button" class="rounded border px-2 py-1 text-sm" on:click={() => editProfile(profile)}>{profile.builtin ? "Duplicate as custom" : "Edit new revision"}</button>
                  <button type="button" class="rounded border border-red-300 px-2 py-1 text-sm text-red-600 disabled:cursor-not-allowed disabled:opacity-40" disabled={profile.builtin} title={profile.builtin ? "Built-in Profiles cannot be deleted" : `Delete ${profile.display_name}`} on:click={() => deleteProfile(profile)}>Delete</button>
                </div>
              </div>
            </div>
          {/each}
        {/if}
      {:else if view === "settings"}
        <section data-testid="curator-context-settings">
          <h3 class="mb-1 font-semibold">Curator context settings</h3>
          <p class="mb-3 text-xs ops-muted">Controls future admitted rounds only. Summary budgets use portable estimated units, not model tokens.</p>
          {#if curatorPreferences}
            <div class="mb-3 rounded-xl border border-gray-200 p-3 dark:border-gray-700">
              <p class="mb-2 text-xs ops-muted">Effective source: {curatorPreferences.inheritance === "CHAT" ? "this chat override" : curatorPreferences.inheritance === "USER" ? "your user defaults" : "system defaults"}</p>
              <label class="mb-2 block text-sm">Recent complete rounds
                <input data-testid="curator-recent-rounds" class="mt-1 w-full rounded-lg border bg-transparent px-2 py-1" type="number" min="1" step="1" bind:value={preferenceDraft.recent_round_count} on:input={() => preferenceDraftDirty = true} />
              </label>
              <label class="block text-sm">Rolling summary budget
                <input data-testid="curator-summary-budget" class="mt-1 w-full rounded-lg border bg-transparent px-2 py-1" type="number" min="128" max="8192" step="1" bind:value={preferenceDraft.summary_budget_units} on:input={() => preferenceDraftDirty = true} />
              </label>
              <div class="mt-3 flex flex-wrap gap-1">
                <button type="button" disabled={preferencePending} class="rounded border px-2 py-1 text-sm disabled:opacity-50" on:click={() => saveCuratorPreferences("user")}>Save as user defaults</button>
                <button type="button" disabled={preferencePending} class="rounded border px-2 py-1 text-sm disabled:opacity-50" on:click={() => saveCuratorPreferences("chat")}>Override this chat</button>
                <button type="button" disabled={preferencePending || !curatorPreferences.chat_override} class="rounded border px-2 py-1 text-sm disabled:opacity-50" on:click={resetCuratorOverride}>Reset chat override</button>
              </div>
            </div>
          {:else}
            <p class="text-sm ops-muted">Loading Curator context settings…</p>
          {/if}
        </section>
      {/if}
    </div>
  </div>
{/if}
