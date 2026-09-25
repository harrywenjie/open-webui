# Downstream Open WebUI

This fork is the source of truth for the Chat Memory adapter, HUD and client customizations.
Memory Core, deployable Functions/Tools and private host configuration belong to the separate operations repository. No host configuration or credentials belong here.

The initial downstream commit imports the qualified Adapter 4.14 on upstream v0.11.3 byte-for-byte.
Upgrades merge a fixed upstream release into a new branch, resolve conflicts, run the downstream and integration gates, then freeze an immutable release commit. Never rewrite published release history.

The operations repository may carry machine-generated patch/overlay exports for offline qualification. They are not editable sources; changes start in this fork and are exported from a pinned commit.
