/**
 * MobX store for room management.
 *
 * Handles room list, creation, and connection state.
 */

import { makeAutoObservable, runInAction } from "mobx";
import { listRooms, createRoom, deleteRoom, type RoomInfo } from "@/api/client";

export class RoomStore {
  rooms: RoomInfo[] = [];
  isLoading = false;
  error: string | null = null;

  constructor() {
    makeAutoObservable(this);
  }

  async loadRooms() {
    this.isLoading = true;
    this.error = null;
    try {
      const rooms = await listRooms();
      runInAction(() => {
        this.rooms = rooms;
      });
    } catch (e: any) {
      runInAction(() => {
        this.error = e.response?.data?.error || "Failed to load rooms";
      });
    } finally {
      runInAction(() => {
        this.isLoading = false;
      });
    }
  }

  async createRoom(name: string): Promise<RoomInfo | null> {
    this.isLoading = true;
    this.error = null;
    try {
      const room = await createRoom(name);
      runInAction(() => {
        this.rooms = [...this.rooms, room];
      });
      return room;
    } catch (e: any) {
      runInAction(() => {
        this.error = e.response?.data?.error || "Failed to create room";
      });
      return null;
    } finally {
      runInAction(() => {
        this.isLoading = false;
      });
    }
  }

  async removeRoom(roomId: number) {
    this.isLoading = true;
    this.error = null;
    try {
      await deleteRoom(roomId);
      runInAction(() => {
        this.rooms = this.rooms.filter((r) => r.id !== roomId);
      });
    } catch (e: any) {
      runInAction(() => {
        this.error = e.response?.data?.error || "Failed to delete room";
      });
    } finally {
      runInAction(() => {
        this.isLoading = false;
      });
    }
  }

  getRoomById(id: number): RoomInfo | undefined {
    return this.rooms.find((r) => r.id === id);
  }
}
