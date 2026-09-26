# Downstream Open WebUI

This fork is the source of truth for the Dissipative Memory adapter, HUD and client customizations.
Dissipative Core, deployable Functions/Tools, build exports and qualification belong to [Dissipative Memory](https://github.com/harrywenjie/dissipative), locally `E:/dissipative`. PrivateOperations retains host inventory, credentials and operational records.

The initial downstream commit imports the qualified Adapter 4.14 on upstream v0.11.3 byte-for-byte.
Upgrades merge a fixed upstream release into a new branch, resolve conflicts, run the downstream and integration gates, then freeze an immutable release commit. Never rewrite published release history.

The Dissipative repository carries machine-generated patch/overlay exports for offline qualification. They are not editable sources; changes start in this fork and are exported from a pinned commit.

The `dissipative-adapter-4.16` source candidate is not deployed. Existing API routes, socket event names, model metadata and plugin IDs remain compatibility contracts until a coordinated deployment migration.
