/**
 * Centrifugo-backed Yjs provider with hybrid transport.
 *
 * Sync strategy:
 * - Small updates (≤64KB): sent via Centrifugo RPC ("yjs_update")
 * - Large updates (>64KB): sent via HTTP POST to /upload-update/
 * - Django merges update, saves to DB, broadcasts:
 *   - yjs-update-b64 (for small updates) back through Centrifugo
 *   - room-resync-needed (for large updates) → clients reload full state
 * - Remote updates are applied with origin "centrifugo".
 * - Initial room state is loaded from REST API by EditorPage before provider creation.
 */

import * as Y from "yjs";
import { Awareness } from "y-protocols/awareness";
import {
  Centrifuge,
  type PublicationContext,
  type Subscription,
} from "centrifuge";
import { EditorStore } from "@/stores/EditorStore";
import { getRoomState } from "@/api/client";
import { decode_yjs_state } from "@/yjs/utils";

interface YjsBinaryUpdate {
  type: "yjs-update-b64";
  senderId: string;
  data: string;
}

interface RoomResyncNeeded {
  type: "room-resync-needed";
  senderId: string;
}

type ProviderMessage = YjsBinaryUpdate | RoomResyncNeeded;

function encodeUpdateToBase64(update: Uint8Array): string {
  let binary = "";
  const chunkSize = 8192;
  for (let i = 0; i < update.length; i += chunkSize) {
    const chunk = update.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, chunk as unknown as number[]);
  }
  return btoa(binary);
}

function decodeUpdateFromBase64(stateB64: string): Uint8Array {
  const binary = atob(stateB64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

// Updates larger than this (in bytes) go via HTTP, smaller ones via RPC
const LARGE_UPDATE_THRESHOLD = 65536; // 64 KB

const DEFAULT_WS_URL =
  import.meta.env.VITE_CENTRIFUGO_WS_URL ??
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/connection/websocket`;

export interface CentrifugoProvider {
  doc: Y.Doc;
  awareness: Awareness;
  connected: boolean;
  syncing: boolean;
  on: (event: string, cb: (...args: any[]) => void) => void;
  destroy: () => void;
}

export function createCentrifugoProvider(
  roomId: number,
  ydoc: Y.Doc,
  editorStore: EditorStore,
  options: { centrifugoUrl?: string } = {}
): CentrifugoProvider {
  const wsUrl = options.centrifugoUrl ?? DEFAULT_WS_URL;
  const channel = `rooms:${roomId}`;
  const awarenessChannel = `rooms:${roomId}:awareness`;
  const localClientId = crypto.randomUUID();

  const centrifuge = new Centrifuge(wsUrl);
  const awareness = new Awareness(ydoc);
  const remoteAwarenessStates = new Map<string, any>(); // Track remote awareness states
  const remoteClientIdMap = new Map<string, number>(); // Map from string clientId to stable numeric ID
  let isHandlingRemoteAwareness = false; // Flag to skip sync publish when emitting for remote cursors
  const listeners = new Map<string, Set<(...args: any[]) => void>>();

  // Helper to get stable numeric ID for a string client ID
  const getStableClientId = (stringId: string): number => {
    if (!remoteClientIdMap.has(stringId)) {
      // Use a simple hash from the string
      let hash = 0;
      for (let i = 0; i < stringId.length; i++) {
        const char = stringId.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convert to 32bit integer
      }
      // Ensure it's positive and starts from 1000
      hash = Math.abs(hash) % 1000000 + 1000;
      remoteClientIdMap.set(stringId, hash);
    }
    return remoteClientIdMap.get(stringId)!;
  };

  // Override awareness.getStates() to include remote awareness for cursor rendering.
  // y-monaco expects: Map<clientID: number, state: { selection?: { anchor, head }, user?: any }>
  const originalGetStates = awareness.getStates.bind(awareness);
  
  awareness.getStates = () => {
    const states = originalGetStates() as any;
    
    // Include remote awareness states so y-monaco can render their cursors.
    // IMPORTANT: value must be the state directly, NOT wrapped in { clock, state, ... }
    for (const [clientId, remoteState] of remoteAwarenessStates.entries()) {
      const stableId = getStableClientId(clientId);
      states.set(stableId, remoteState);
    }
    
    return states;
  };

  let subscription: Subscription | null = null;
  let awarenessSubscription: Subscription | null = null;
  let connected = false;
  let lastPublishedState: any = null;
  let syncAwarenessTimeout: NodeJS.Timeout | null = null;
  let rpcQueue: Promise<void> = Promise.resolve();
  let isLoadingRemoteState = false; // Flag to prevent update loop during state load

  const emit = (event: string, ...args: any[]) => {
    listeners.get(event)?.forEach((cb) => cb(...args));
  };

  // Set local awareness state
  const userColor = EditorStore.generateUserColor();
  const userName = EditorStore.generateDisplayName(localClientId);
  awareness.setLocalState({
    user: {
      clientId: localClientId,
      color: userColor,
      name: userName,
    },
  });

  // Sync awareness state to awareness channel
  const syncAwarenessState = () => {
    if (!awarenessSubscription || !connected) return;
    
    const state = awareness.getLocalState();
    if (!state) return;

    // Only publish if state actually changed
    if (lastPublishedState && JSON.stringify(lastPublishedState) === JSON.stringify(state)) {
      console.log("[awareness] State unchanged, skipping publish");
      return;
    }

    lastPublishedState = JSON.parse(JSON.stringify(state)); // Deep copy
    
    console.log("[awareness] Publishing local state to awareness channel", state);
    
    awarenessSubscription
      .publish({
        type: "awareness",
        clientId: localClientId,
        state: state,
      })
      .catch((err) => {
        console.error("[awareness] Failed to publish awareness state:", err);
      });
  };

  // Debounced version for awareness change events
  const debouncedSyncAwareness = () => {
    if (syncAwarenessTimeout) {
      clearTimeout(syncAwarenessTimeout);
    }
    syncAwarenessTimeout = setTimeout(() => {
      syncAwarenessState();
      syncAwarenessTimeout = null;
    }, 200); // Wait 200ms before publishing to batch changes
  };

  // Listen to local awareness changes and sync to channel (with debounce)
  const handleAwarenessLocalChange = () => {
    // Skip if we're emitting change for a remote awareness update
    if (isHandlingRemoteAwareness) return;
    console.log("[awareness] Local state changed");
    debouncedSyncAwareness();
  };
  
  awareness.on("change", handleAwarenessLocalChange);

  const sendUpdateViaRpc = async (update: Uint8Array) => {
    if (!connected) return;

    const sizeKb = update.byteLength / 1024;
    editorStore.setLastMsgSizeKb(sizeKb);

    const b64 = encodeUpdateToBase64(update);
    editorStore.setSaving(true);

    try {
      // Large update: use HTTP upload endpoint
      if (update.byteLength > LARGE_UPDATE_THRESHOLD) {
        console.log(`[sendUpdateViaRpc] Sending large update (${sizeKb.toFixed(2)} KB) via HTTP POST`);
        const response = await fetch(`/api/rooms/${roomId}/upload-update/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            yjs_state_b64: b64,
            sender_id: localClientId,
          }),
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        console.log(`[sendUpdateViaRpc] HTTP upload OK, updated_at: ${data.updated_at}`);
        editorStore.setLastSavedAt(data.updated_at || new Date().toISOString());
        return;
      }

      // Small update: use Centrifugo RPC
      console.log(`[sendUpdateViaRpc] Sending small update (${sizeKb.toFixed(2)} KB) via RPC`);
      await centrifuge.rpc("yjs_update", {
        room_id: roomId,
        data: b64,
        sender_id: localClientId,
      });
      console.log(`[sendUpdateViaRpc] RPC OK`);
      editorStore.setLastSavedAt(new Date().toISOString());
    } finally {
      editorStore.setSaving(false);
    }
  };

  const ydocUpdateHandler = (update: Uint8Array, origin: any) => {
    // Skip if we're currently loading state from server (prevents feedback loop)
    if (isLoadingRemoteState) {
      console.log(
        `[ydocUpdateHandler] Skipping update during remote state load (size: ${(update.byteLength / 1024).toFixed(2)} KB)`,
      );
      return;
    }

    if (origin === "centrifugo") {
      console.log(
        `[ydocUpdateHandler] Skipping update with origin="centrifugo" (size: ${(update.byteLength / 1024).toFixed(2)} KB)`,
      );
      return;
    }

    console.log(
      `[ydocUpdateHandler] Local update detected (origin: ${origin}, size: ${(update.byteLength / 1024).toFixed(2)} KB)`,
    );

    rpcQueue = rpcQueue
      .then(() => sendUpdateViaRpc(update))
      .catch((err) => {
        console.error("Failed to publish Yjs update:", err);
      });
  };

  const handlePublication = (ctx: PublicationContext) => {
    const msg = ctx.data as ProviderMessage;
    if (!msg || typeof msg !== "object" || !("type" in msg)) return;

    if (msg.type === "yjs-update-b64") {
      if (msg.senderId === localClientId || !msg.data) return;
      Y.applyUpdate(ydoc, decodeUpdateFromBase64(msg.data), "centrifugo");
      return;
    }

    if (msg.type === "room-resync-needed") {
      console.log(`[handlePublication] room-resync-needed from senderId=${msg.senderId}, localClientId=${localClientId}`);
      if (msg.senderId === localClientId) {
        console.log("  → Ignoring own resync event");
        return;
      }
      console.log("  → Reloading state from server...");
      // Fetch latest state and apply it
      getRoomState(roomId)
        .then((state) => {
          if (state.yjs_state) {
            console.log("  → Got state from server, applying with isLoadingRemoteState=true to prevent feedback loop");
            const stateBytes = decode_yjs_state(state.yjs_state);
            
            // Mark that we're loading remote state to skip update handler
            isLoadingRemoteState = true;
            try {
              // Load fresh state into current doc
              const newDoc = new Y.Doc();
              Y.applyUpdate(newDoc, stateBytes);
              
              // Replace content in current doc
              const newText = newDoc.getText("content");
              const oldText = ydoc.getText("content");
              
              ydoc.transact(() => {
                oldText.delete(0, oldText.length);
                oldText.insert(0, newText.toString());
              });
              
              console.log("  → State applied successfully");
            } finally {
              // Always reset flag, even on error
              isLoadingRemoteState = false;
              console.log("  → isLoadingRemoteState reset to false");
            }
          }
        })
        .catch((err) => {
          console.error("Failed to reload state after resync event:", err);
          // Make sure flag is reset
          isLoadingRemoteState = false;
        });
      return;
    }
  };

  const setupSubscription = () => {
    subscription = centrifuge.newSubscription(channel);

    subscription.on("publication", handlePublication);

    subscription.on("subscribed", () => {
      connected = true;
      editorStore.setConnectionStatus("connected");
      emit("sync", []);
      emit("status", ["connected"]);
    });

    subscription.on("unsubscribed", () => {
      connected = false;
      editorStore.setConnectionStatus("disconnected");
    });

    subscription.on("error", (ctx) => {
      console.error("Centrifugo subscription error:", ctx);
      editorStore.setConnectionStatus("error", "Subscription error");
    });

    subscription.subscribe();
  };

  const handleAwarenessPublication = (ctx: PublicationContext) => {
    const msg = ctx.data as any;
    if (!msg || typeof msg !== "object" || msg.type !== "awareness") return;

    const clientId = msg.clientId as string;
    if (clientId === localClientId) return; // Ignore own awareness

    const state = msg.state as any;
    if (!state || !state.user) return;

    console.log(`[awareness] Received awareness from ${state.user.name}`);

    // Update remote state
    remoteAwarenessStates.set(clientId, state);
    
    // Emit 'change' event so y-monaco re-renders cursors.
    // Set flag so our own sync handler skips publishing (prevents feedback loop).
    isHandlingRemoteAwareness = true;
    awareness.emit("change", [{ added: [], updated: [clientId], removed: [] }]);
    isHandlingRemoteAwareness = false;

    // Update EditorStore for user list display
    updateConnectedUsersList();
  };

  const updateConnectedUsersList = () => {
    const users = new Map<number, any>();
    let index = 0;
    
    // Add current user (ourselves)
    const localState = awareness.getLocalState();
    if (localState && localState.user) {
      users.set(index++, {
        clientId: localState.user.clientId,
        displayName: localState.user.name,
        color: localState.user.color,
      });
    }

    // Add all remote users from tracked states
    for (const [_, remoteState] of remoteAwarenessStates.entries()) {
      if (remoteState && remoteState.user) {
        users.set(index++, {
          clientId: remoteState.user.clientId,
          displayName: remoteState.user.name,
          color: remoteState.user.color,
        });
      }
    }

    editorStore.updateConnectedUsers(users);
  };

  const setupAwarenessSubscription = () => {
    awarenessSubscription = centrifuge.newSubscription(awarenessChannel);

    awarenessSubscription.on("publication", handleAwarenessPublication);

    awarenessSubscription.on("subscribed", () => {
      console.log("[awareness] Subscribed to awareness channel");
      // Publish our initial state
      syncAwarenessState();
    });

    awarenessSubscription.on("error", (ctx) => {
      console.error("[awareness] Subscription error:", ctx);
    });

    awarenessSubscription.subscribe();
  };

  centrifuge.on("connected", () => {
    editorStore.setConnectionStatus("connected");
  });

  centrifuge.on("disconnected", () => {
    connected = false;
    editorStore.setConnectionStatus("disconnected");
  });

  centrifuge.on("error", (ctx) => {
    console.error("Centrifugo connection error:", ctx);
    editorStore.setConnectionStatus("error", ctx.error?.message ?? "Connection error");
  });

  editorStore.setConnectionStatus("connecting");
  ydoc.on("update", ydocUpdateHandler);
  setupSubscription();
  setupAwarenessSubscription();
  centrifuge.connect();

  const destroy = () => {
    if (syncAwarenessTimeout) {
      clearTimeout(syncAwarenessTimeout);
      syncAwarenessTimeout = null;
    }

    ydoc.off("update", ydocUpdateHandler);
    awareness.off("change", handleAwarenessLocalChange);

    if (subscription) {
      subscription.unsubscribe();
      subscription = null;
    }

    if (awarenessSubscription) {
      awarenessSubscription.unsubscribe();
      awarenessSubscription = null;
    }

    centrifuge.disconnect();
    connected = false;
    editorStore.setConnectionStatus("disconnected");
  };

  return {
    get doc() {
      return ydoc;
    },
    get awareness() {
      return awareness;
    },
    get connected() {
      return connected;
    },
    get syncing() {
      return false;
    },
    on(event: string, cb: (...args: any[]) => void) {
      if (!listeners.has(event)) {
        listeners.set(event, new Set());
      }
      listeners.get(event)?.add(cb);
    },
    destroy,
  };
}
