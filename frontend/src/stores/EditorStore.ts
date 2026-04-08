/**
 * MobX store for collaborative editor state.
 *
 * Owns the shared Yjs document for the current room and coordinates
 * provider lifecycle, connection status, and lightweight save indicators.
 */

import { makeAutoObservable, runInAction } from "mobx";
import * as Y from "yjs";
import { getRoomState } from "../api/client";
import { decode_yjs_state } from "@/yjs/utils";
import {
  createCentrifugoProvider,
  type CentrifugoProvider,
} from "@/yjs/CentrifugoProvider";

export interface ConnectedUser {
  clientId: string;
  displayName: string;
  color: string;
}

export type ConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "error";

export class EditorStore {
  roomId: number | null = null;

  yDoc: Y.Doc = new Y.Doc();
  yText: Y.Text = this.yDoc.getText("content");

  provider: CentrifugoProvider | null = null;

  connectionStatus: ConnectionStatus = "disconnected";
  connectionError: string | null = null;
  isInitializing = false;

  connectedUsers: Map<number, ConnectedUser> = new Map();
  currentUser: ConnectedUser | null = null;

  isSaving = false;
  lastSavedAt: string | null = null;
  lastMsgSizeKb: number | null = null;

  private initToken = 0;
  private saveIndicatorTimer: ReturnType<typeof setTimeout> | null = null;
  private docUpdateHandler:
    | ((update: Uint8Array, origin: unknown) => void)
    | null = null;

  constructor() {
    makeAutoObservable(this, {}, { autoBind: true });
    this.attachDocObservers();
  }

  async initializeRoom(roomId: number) {
    const currentToken = ++this.initToken;

    this.disposeCurrentRoom();
    runInAction(() => {
      this.roomId = roomId;
      this.isInitializing = true;
      this.connectionStatus = "connecting";
      this.connectionError = null;

      const localUser = this.createLocalUser();
      this.currentUser = localUser;
      this.connectedUsers = new Map([[0, localUser]]);
    });

    try {
      try {
        const state = await getRoomState(roomId);
        if (this.initToken !== currentToken) return;

        if (state.yjs_state) {
          Y.applyUpdate(this.yDoc, decode_yjs_state(state.yjs_state), "server");
        }
      } catch {
        // Room may not have persisted state yet.
      }

      const provider = createCentrifugoProvider(roomId, this.yDoc);

      if (this.initToken !== currentToken) {
        provider.destroy();
        return;
      }

      provider.on("status", (status: ConnectionStatus) => {
        runInAction(() => {
          this.connectionStatus = status;
          if (status !== "error") {
            this.connectionError = null;
          }
        });
      });

      provider.on("sync", () => {
        runInAction(() => {
          this.lastSavedAt = new Date().toISOString();
        });
      });

      runInAction(() => {
        this.provider = provider;
      });
    } catch (error: any) {
      if (this.initToken !== currentToken) return;

      runInAction(() => {
        this.connectionStatus = "error";
        this.connectionError = error?.message ?? "Failed to initialize editor";
      });
    } finally {
      if (this.initToken === currentToken) {
        runInAction(() => {
          this.isInitializing = false;
        });
      }
    }
  }

  setConnectionStatus(status: ConnectionStatus, error: string | null = null) {
    this.connectionStatus = status;
    this.connectionError = error;
  }

  setCurrentUser(user: ConnectedUser | null) {
    this.currentUser = user;
  }

  updateConnectedUsers(users: Map<number, ConnectedUser>) {
    this.connectedUsers = new Map(users);
  }

  setProvider(provider: CentrifugoProvider | null) {
    this.provider = provider;
  }

  setSaving(saving: boolean) {
    this.isSaving = saving;
  }

  setLastSavedAt(timestamp: string | null) {
    this.lastSavedAt = timestamp;
  }

  setLastMsgSizeKb(kb: number | null) {
    this.lastMsgSizeKb = kb;
  }

  get activeUserCount(): number {
    return this.connectedUsers.size;
  }

  get connectedUsersList(): ConnectedUser[] {
    return Array.from(this.connectedUsers.values());
  }

  private createLocalUser(): ConnectedUser {
    const clientId = crypto.randomUUID();
    return {
      clientId,
      displayName: EditorStore.generateDisplayName(clientId),
      color: EditorStore.generateUserColor(),
    };
  }

  private attachDocObservers() {
    this.detachDocObservers();

    this.docUpdateHandler = (update: Uint8Array, origin: unknown) => {
      if (origin === "centrifugo" || origin === "server") {
        return;
      }

      this.lastMsgSizeKb = update.byteLength / 1024;
      this.isSaving = true;

      if (this.saveIndicatorTimer) {
        clearTimeout(this.saveIndicatorTimer);
      }

      this.saveIndicatorTimer = setTimeout(() => {
        runInAction(() => {
          this.isSaving = false;
          this.lastSavedAt = new Date().toISOString();
        });
      }, 250);
    };

    this.yDoc.on("update", this.docUpdateHandler);
  }

  private detachDocObservers() {
    if (this.docUpdateHandler) {
      this.yDoc.off("update", this.docUpdateHandler);
      this.docUpdateHandler = null;
    }

    if (this.saveIndicatorTimer) {
      clearTimeout(this.saveIndicatorTimer);
      this.saveIndicatorTimer = null;
    }
  }

  private disposeCurrentRoom() {
    if (this.provider) {
      this.provider.destroy();
      this.provider = null;
    }

    this.detachDocObservers();
    this.yDoc.destroy();

    this.yDoc = new Y.Doc();
    this.yText = this.yDoc.getText("content");
    this.attachDocObservers();

    this.connectionStatus = "disconnected";
    this.connectionError = null;
    this.connectedUsers = new Map();
    this.currentUser = null;
    this.isSaving = false;
    this.lastSavedAt = null;
    this.lastMsgSizeKb = null;
  }

  resetDocument() {
    this.initToken += 1;
    this.disposeCurrentRoom();
  }

  destroy() {
    this.roomId = null;
    this.resetDocument();
  }

  static generateUserColor(): string {
    const colors = [
      "#ff6b6b",
      "#feca57",
      "#48dbfb",
      "#ff9ff3",
      "#54a0ff",
      "#5f27cd",
      "#01a3a4",
      "#f368e0",
      "#ff6348",
      "#7bed9f",
      "#70a1ff",
      "#ffa502",
    ];
    return colors[Math.floor(Math.random() * colors.length)];
  }

  static generateDisplayName(clientId: string): string {
    const adjectives = [
      "Swift",
      "Bright",
      "Calm",
      "Bold",
      "Wise",
      "Cool",
      "Dark",
      "Eager",
      "Fair",
      "Grand",
    ];
    const suffix = clientId.slice(0, 4).toUpperCase();
    const adj = adjectives[Math.floor(Math.random() * adjectives.length)];
    return `${adj} ${suffix}`;
  }
}
