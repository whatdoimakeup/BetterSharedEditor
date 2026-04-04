/**
 * MobX store for editor state.
 *
 * Manages Yjs document, connection status, and user awareness.
 */

import { makeAutoObservable } from "mobx";
import * as Y from "yjs";

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
  // Yjs document
  yDoc: Y.Doc;
  yText: Y.Text;

  // Connection state
  connectionStatus: ConnectionStatus = "disconnected";
  connectionError: string | null = null;

  // Awareness (presence)
  connectedUsers: Map<number, ConnectedUser> = new Map();
  currentUser: ConnectedUser | null = null;

  // Persistence
  isSaving = false;
  lastSavedAt: string | null = null;
  lastMsgSizeKb: number | null = null;

  // Provider reference (set after initialization)
  provider: any = null;

  constructor() {
    this.yDoc = new Y.Doc();
    this.yText = this.yDoc.getText("content");

    makeAutoObservable(this);
  }

  setConnectionStatus(status: ConnectionStatus, error: string | null = null) {
    this.connectionStatus = status;
    this.connectionError = error;
  }

  setCurrentUser(user: ConnectedUser) {
    this.currentUser = user;
  }

  updateConnectedUsers(users: Map<number, ConnectedUser>) {
    this.connectedUsers = new Map(users);
  }

  setProvider(provider: any) {
    this.provider = provider;
  }

  setSaving(saving: boolean) {
    this.isSaving = saving;
  }

  setLastSavedAt(timestamp: string) {
    this.lastSavedAt = timestamp;
  }

  setLastMsgSizeKb(kb: number | null) {
    this.lastMsgSizeKb = kb;
  }

  /**
   * Get the number of active users in the room.
   */
  get activeUserCount(): number {
    return this.connectedUsers.size;
  }

  /**
   * Get list of connected users.
   */
  get connectedUsersList(): ConnectedUser[] {
    return Array.from(this.connectedUsers.values());
  }

  /**
   * Generate a random color for user cursors.
   */
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

  /**
   * Generate a display name for an anonymous user.
   */
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

  /**
   * Reset the Yjs document for a new room.
   */
  resetDocument() {
    if (this.provider) {
      this.provider.destroy();
      this.provider = null;
    }
    this.yDoc.destroy();
    this.yDoc = new Y.Doc();
    this.yText = this.yDoc.getText("content");
    this.connectedUsers.clear();
    this.currentUser = null;
    this.lastSavedAt = null;
    this.connectionError = null;
  }

  /**
   * Cleanup resources.
   */
  destroy() {
    if (this.provider) {
      this.provider.destroy();
      this.provider = null;
    }
    this.yDoc.destroy();
  }
}
