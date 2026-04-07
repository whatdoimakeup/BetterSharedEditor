import * as Y from "yjs";
import { Awareness } from "y-protocols/awareness";
import {
  Centrifuge,
  type PublicationContext,
  type Subscription,
} from "centrifuge";

const DEFAULT_WS_URL =
  import.meta.env.VITE_CENTRIFUGO_WS_URL ??
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/connection/websocket`;

interface YjsUpdateMessage {
  type: "yjs-update";
  senderId: string;
  data: string;
}

export interface CentrifugoProvider {
  doc: Y.Doc;
  awareness: Awareness;
  connected: boolean;
  syncing: boolean;
  on: (event: "status" | "sync", cb: (...args: any[]) => void) => void;
  destroy: () => void;
}

function encodeUpdateToBase64(update: Uint8Array): string {
  let binary = "";
  for (const byte of update) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

function decodeUpdateFromBase64(data: string): Uint8Array {
  const binary = atob(data);
  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }

  return bytes;
}

export function createCentrifugoProvider(
  roomId: number,
  doc: Y.Doc,
  options: { centrifugoUrl?: string; token?: string } = {},
): CentrifugoProvider {
  const centrifuge = new Centrifuge(options.centrifugoUrl ?? DEFAULT_WS_URL, {
    token: options.token,
  });
  const awareness = new Awareness(doc);
  const localClientId = crypto.randomUUID();
  const channel = `rooms:${roomId}`;
  const listeners = new Map<string, Set<(...args: any[]) => void>>();

  let connected = false;
  let syncing = false;
  let subscription: Subscription | null = null;

  const emit = (event: "status" | "sync", ...args: any[]) => {
    listeners.get(event)?.forEach((cb) => cb(...args));
  };

  const handleDocUpdate = (update: Uint8Array, origin: unknown) => {
    if (!subscription || !connected || origin === "centrifugo") {
      return;
    }

    centrifuge
      .rpc("yjs_update", {
        room_id: roomId,
        data: encodeUpdateToBase64(update),
        sender_id: localClientId,
      })
      .catch((error) => {
        console.error("[CentrifugoProvider] Failed to publish update:", error);
      });
  };

  const handlePublication = (ctx: PublicationContext) => {
    const message = ctx.data as Partial<YjsUpdateMessage>;

    if (
      message.type !== "yjs-update" ||
      typeof message.data !== "string" ||
      message.senderId === localClientId
    ) {
      return;
    }

    syncing = true;
    try {
      Y.applyUpdate(doc, decodeUpdateFromBase64(message.data), "centrifugo");
      emit("sync");
    } finally {
      syncing = false;
    }
  };

  subscription = centrifuge.newSubscription(channel);
  subscription.on("publication", handlePublication);
  subscription.on("subscribed", () => {
    connected = true;
    emit("status", "connected");
  });
  subscription.on("unsubscribed", () => {
    connected = false;
    emit("status", "disconnected");
  });
  subscription.on("error", (ctx) => {
    console.error("[CentrifugoProvider] Subscription error:", ctx);
    emit("status", "disconnected");
  });

  centrifuge.on("connected", () => {
    connected = true;
    emit("status", "connected");
  });

  centrifuge.on("disconnected", () => {
    connected = false;
    emit("status", "disconnected");
  });

  doc.on("update", handleDocUpdate);
  subscription.subscribe();
  centrifuge.connect();

  return {
    get doc() {
      return doc;
    },
    get awareness() {
      return awareness;
    },
    get connected() {
      return connected;
    },
    get syncing() {
      return syncing;
    },
    on(event, cb) {
      if (!listeners.has(event)) {
        listeners.set(event, new Set());
      }
      listeners.get(event)?.add(cb);
    },
    destroy() {
      doc.off("update", handleDocUpdate);
      awareness.destroy();

      if (subscription) {
        subscription.unsubscribe();
        subscription = null;
      }

      centrifuge.disconnect();
      connected = false;
    },
  };
}
